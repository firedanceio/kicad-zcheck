"""kicad-zcheck command line."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .model import candidate, env, solve_width, z0, zdiff
from .stackup import read_stackup


def _load(path):
    try:
        import pcbnew
    except ImportError:
        print("this command needs KiCad's pcbnew module: run it with the Python that ships with KiCad", file=sys.stderr)
        raise SystemExit(2)
    b = pcbnew.LoadBoard(path)
    cu = [pcbnew.BOARD.GetStandardLayerName(l) for l in b.GetEnabledLayers().CuStack()]   # the stack-up's names
    return b, cu, read_stackup(path, cu)


def _planes(a, b):
    """--planes accepts the board's own layer names or KiCad's standard ones; returns standard names."""
    from .board import detect_planes, shown
    if a.planes:
        back = {v: k for k, v in shown(b).items()}
        return {back.get(x, x) for x in a.planes.split(",")}
    return detect_planes(b)


def cmd_widths(a, stack, cu, planes, names, routed, title="board stack-up"):
    """Every layer that is not a plane, and every plane layer that also carries routing (its own pour ignored)."""
    print(f"{title}: planes {', '.join(names[L] for L in sorted(planes, key=cu.index)) or 'none'}; total {sum(l.thickness for l in stack.layers):.3f} mm")
    for L in cu:
        if L in planes and routed.get(L, 0.0) < 10.0:
            continue
        e = env(stack, L, planes - {L})
        if e.h_up is None and e.h_down is None:
            print(f"  {names[L]:8s} no reference plane")
            continue
        hs = " / ".join(f"{h:.3f}" for h in (e.h_up, e.h_down) if h is not None)
        w_se = solve_width(lambda w: z0(e, w), a.se)
        w_d = solve_width(lambda w: zdiff(e, w, a.gap), a.diff)
        fmt = lambda w: "n/a" if w is None else f"{w:.3f}"
        extra = " ".join(f"| Z0 at {w:g} = {z0(e, w):.0f}" for w in a.at)
        print(f"  {names[L]:8s} {e.kind:10s} h {hs} mm: {a.se:g} ohm SE w={fmt(w_se)} | {a.diff:g} ohm diff w={fmt(w_d)} at gap {a.gap:g} {extra}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kicad-zcheck", description="Impedance and return-path checks on a KiCad board's stack-up and routed copper "
                                 "(closed-form estimates: your fabricator's field solver is the authority).")
    ap.add_argument("--version", action="version", version=f"kicad-zcheck {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, nets=False):
        p.add_argument("board")
        p.add_argument("--planes", help="comma-separated copper layers to treat as planes everywhere (default: detected from zone fills)")
        p.add_argument("--se", type=float, default=50.0, help="single-ended target, ohm (default 50)")
        p.add_argument("--diff", type=float, default=100.0, help="differential target, ohm (default 100)")
        if nets:
            p.add_argument("--nets", required=True, action="append", help="net pattern (wildcards), repeatable")
            p.add_argument("--exclude", action="append", default=[], help="net pattern to leave out, repeatable")
            p.add_argument("--json", metavar="FILE")
            p.add_argument("--map", metavar="PNG", help="draw the selected nets on the board, coloured by the result (needs Pillow)")

    p = sub.add_parser("widths", help="width per layer for the targets")
    common(p)
    p.add_argument("--gap", type=float, default=0.1, help="pair gap, mm (default 0.1)")
    p.add_argument("--at", type=float, action="append", default=[], help="also print Z0 at this width (mm), repeatable")
    p = sub.add_parser("routed", help="share of routed copper within tolerance of its target")
    common(p, nets=True)
    p.add_argument("--pair-suffix", default="_P,_N", help="pair leg suffixes (default _P,_N; empty to disable)")
    p.add_argument("--tol", type=float, default=10.0, help="tolerance, %% (default 10)")
    p.add_argument("--loose", type=float, default=3.0, help="a pair gap above this many plane heights is loosely coupled (default 3)")
    p = sub.add_parser("returns", help="return-current path at every layer change of the selected nets")
    common(p, nets=True)
    p = sub.add_parser("stack", help="widths on candidate stack-ups (dielectric gaps top to bottom, mm)")
    common(p)
    p.add_argument("--candidate", action="append", required=True, help="NAME=d1,d2,... one thickness per copper-to-copper gap")
    p.add_argument("--gap", type=float, default=0.1)
    p.add_argument("--at", type=float, action="append", default=[])
    a = ap.parse_args(argv)

    b, cu, stack = _load(a.board)
    if a.cmd in ("widths", "stack"):
        import pcbnew
        from .board import shown
        planes = _planes(a, b)
        names = shown(b)
        routed = {}
        for t in b.GetTracks():
            if t.Type() != pcbnew.PCB_VIA_T:
                L = pcbnew.BOARD.GetStandardLayerName(t.GetLayer())
                routed[L] = routed.get(L, 0.0) + t.GetLength() / 1e6
        cmd_widths(a, stack, cu, planes, names, routed)
        if a.cmd == "stack":
            for c in a.candidate:
                name, _, spec = c.partition("=")
                cmd_widths(a, candidate(stack, [float(x) for x in spec.split(",")]), cu, planes, names, routed, f"candidate {name}")
        return 0
    from .board import PlaneMap, plane_fills, return_hops, routed_share
    fills = plane_fills(b)
    pm = PlaneMap(b, fills, set(a.planes.split(",")) if a.planes else None)
    if a.cmd == "routed":
        suf = tuple(a.pair_suffix.split(",")) if a.pair_suffix else None
        segs = [] if a.map else None
        r = routed_share(b, stack, pm, a.nets, suf, a.exclude, a.se, a.diff, a.tol / 100.0, a.loose, segs)
        if a.map:
            from .render import AMBER, GREEN, GREY, RED, draw
            t = a.tol / 100.0
            col = lambda d: GREY if d is None else GREEN if d <= t else AMBER if d <= 2 * t else RED
            pts = [p for s0, s1, *_ in segs for p in (s0, s1)]
            crop = (min(p[0] for p in pts) - 3, min(p[1] for p in pts) - 3, max(p[0] for p in pts) + 3, max(p[1] for p in pts) + 3) if pts else None
            draw(b, a.map, [(s0, s1, w, col(d)) for s0, s1, w, d in segs], crop=crop, title=f"kicad-zcheck routed ({a.se:g} / {a.diff:g} ohm)",
                 legend=[(GREEN, f"within {a.tol:g} %"), (AMBER, f"within {2 * a.tol:g} %"), (RED, "further off"), (GREY, "no reference plane")])
            print(f"map: {a.map}")
        tin = tall = 0.0
        for (kind, L), (i, t, zs) in sorted(r.rows.items()):
            tin += i
            tall += t
            print(f"{kind:6s} {L:7s} {i:8.1f} / {t:8.1f} mm in band ({100 * i / t:3.0f} %), mean {zs / t:5.1f} ohm (target {a.diff if kind == 'pair' else a.se:g})")
        for L, ln in r.skipped.items():
            print(f"skipped {L}: {ln:.1f} mm with no reference plane")
        if tall:
            print(f"ALL {tin:.0f} / {tall:.0f} mm in band ({100 * tin / tall:.0f} %)")
            worst = sorted(r.nets.items(), key=lambda kv: kv[1][0] / kv[1][1])[:10]
            print("worst nets: " + ", ".join(f"{n} {100 * i / t:.0f} %" for n, (i, t) in worst))
        if a.json:
            json.dump({"rows": [{"kind": k, "layer": L, "in_band_mm": i, "total_mm": t, "mean_ohm": zs / t} for (k, L), (i, t, zs) in r.rows.items()],
                       "nets": {n: {"in_band_mm": i, "total_mm": t} for n, (i, t) in r.nets.items()}, "skipped": r.skipped}, open(a.json, "w"), indent=1)
        return 0 if not tall or tin / tall >= 0.9 else 1
    if a.cmd == "returns":
        hops = return_hops(b, stack, pm, a.nets, fills, a.exclude)
        if not hops:
            print("no layer changes found on the selected nets")
            return 0
        from collections import Counter
        kinds = Counter(h.path.split(" (")[0].split(" of ")[0].split(" ")[0] for h in hops)
        ds = sorted(h.distance for h in hops if h.distance is not None)
        print(f"{len(hops)} layer changes on {len({h.net for h in hops})} nets; paths: " + ", ".join(f"{k} {v}" for k, v in kinds.items()))
        if ds:
            print(f"distance to the return path: median {ds[len(ds) // 2]:.2f} mm, 90th pct {ds[int(len(ds) * 0.9)]:.2f} mm, worst {ds[-1]:.2f} mm")
        missing = [h for h in hops if h.distance is None]
        for h in sorted(hops, key=lambda h: -(h.distance if h.distance is not None else 1e9))[:8]:
            d = "none found" if h.distance is None else f"{h.distance:.2f} mm"
            print(f"  {h.net} @({h.x:.2f},{h.y:.2f}) {h.layers[0]}->{h.layers[1]} refs {h.refs[0]}/{h.refs[1]}: {h.path}, {d}")
        if a.map:
            import pcbnew
            from fnmatch import fnmatchcase
            from .render import AMBER, GREEN, RED, draw, span
            sel = {t.GetNetname() for t in b.GetTracks() if any(fnmatchcase(t.GetNetname(), p) for p in a.nets)
                   and not any(fnmatchcase(t.GetNetname(), e) for e in a.exclude)}
            lines = [((t.GetStart().x / 1e6, t.GetStart().y / 1e6), (t.GetEnd().x / 1e6, t.GetEnd().y / 1e6), t.GetWidth() / 1e6, (120, 140, 170))
                     for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T and t.GetNetname() in sel]
            col = lambda d: RED if d is None or d > 3 else AMBER if d > 1 else GREEN
            draw(b, a.map, lines, markers=[(h.x, h.y, 9, col(h.distance)) for h in hops], crop=span(b, sel),
                 title="kicad-zcheck returns", legend=[(GREEN, "return path within 1 mm"), (AMBER, "1-3 mm"), (RED, "over 3 mm or none")])
            print(f"map: {a.map}")
        if a.json:
            json.dump([h.__dict__ for h in hops], open(a.json, "w"), indent=1)
        return 1 if missing else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

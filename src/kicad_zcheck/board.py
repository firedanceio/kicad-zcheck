"""Board-side analysis (needs KiCad's pcbnew): planes, routed impedance share, return-path hops at layer changes."""
from __future__ import annotations

import fnmatch
import math
from collections import defaultdict
from dataclasses import dataclass, field

from .model import env, z0, zdiff
from .stackup import Stackup


def _M(v):
    return v / 1e6


def std(lid) -> str:
    """KiCad's standard name for a copper layer ("In1.Cu"), which is how the stack-up block names it, whatever the
    designer renamed the layer to."""
    import pcbnew
    return pcbnew.BOARD.GetStandardLayerName(lid)


def shown(b) -> dict[str, str]:
    """Standard layer name -> the board's own name, for output."""
    return {std(l): b.GetLayerName(l) for l in b.GetEnabledLayers().CuStack()}


def _polys(zone, lid):
    from shapely.geometry import Polygon
    ps = zone.GetFilledPolysList(lid)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [(_M(o.CPoint(k).x), _M(o.CPoint(k).y)) for k in range(o.PointCount())]
        holes = [[(_M(ps.Hole(i, h).CPoint(k).x), _M(ps.Hole(i, h).CPoint(k).y)) for k in range(ps.Hole(i, h).PointCount())]
                 for h in range(ps.HoleCount(i))]
        if len(pts) >= 3:
            out.append(Polygon(pts, holes).buffer(0))
    return out


def plane_fills(b) -> dict[str, list[tuple[str, object]]]:
    """{copper layer: [(net, filled polygon), ...]} for every filled, non-rule-area zone."""
    out = defaultdict(list)
    for z in b.Zones():
        if z.GetIsRuleArea() or not z.GetNetname():
            continue
        for lid in z.GetLayerSet().CuStack():
            for p in _polys(z, lid):
                out[std(lid)].append((z.GetNetname(), p))
    return out


def detect_planes(b, fills=None, min_fraction: float = 0.4) -> set[str]:
    """The copper layers the designer set to type "power" in Board Setup, if there are any; otherwise the layers whose
    zone fills cover at least ``min_fraction`` of the board outline's bounding box. Standard layer names."""
    import pcbnew
    typed = {std(l) for l in b.GetEnabledLayers().CuStack() if b.GetLayerType(l) == pcbnew.LT_POWER}
    if typed:
        return typed
    fills = fills if fills is not None else plane_fills(b)
    bb = b.GetBoardEdgesBoundingBox()
    area = _M(bb.GetWidth()) * _M(bb.GetHeight()) or 1.0
    return {L for L, fs in fills.items() if sum(p.area for _, p in fs) >= min_fraction * area}


class PlaneMap:
    """Which copper layers have filled copper at a point: a layer acts as a reference plane wherever it is filled, so
    partial pours (a ground island under a memory bus) count where they exist. ``force`` makes layers planes
    everywhere."""

    def __init__(self, b, fills=None, force: set[str] | None = None):
        from shapely.ops import unary_union
        from shapely.prepared import prep
        fills = fills if fills is not None else plane_fills(b)
        self.prep = {L: prep(unary_union([p for _, p in fs])) for L, fs in fills.items() if fs}
        self.force = set(force or ())
        self._env = {}

    def planes_at(self, x: float, y: float, r: float = 0.0) -> set[str]:
        from shapely.geometry import Point
        pt = Point(x, y).buffer(r) if r else Point(x, y)
        return self.force | {L for L, pp in self.prep.items() if (pp.intersects(pt) if r else pp.contains(pt))}

    def env_at(self, stack: Stackup, layer: str, x: float, y: float, r: float = 0.0):
        planes = frozenset(self.planes_at(x, y, r) - {layer})
        key = (layer, planes)
        if key not in self._env:
            self._env[key] = env(stack, layer, set(planes))
        return self._env[key]


def _sel(name: str, patterns: list[str], exclude: list[str] | None = None) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns) and not any(fnmatch.fnmatchcase(name, e) for e in exclude or ())


@dataclass
class Share:
    rows: dict = field(default_factory=dict)    # (kind, layer) -> [mm in band, mm total, z*mm]
    nets: dict = field(default_factory=dict)    # net -> [mm in band, mm total]
    skipped: dict = field(default_factory=dict) # layer -> mm (no plane reference)


def routed_share(b, stack: Stackup, pm: "PlaneMap", patterns: list[str], pair_suffix: tuple[str, str] | None,
                 exclude: list[str] | None, z_se: float, z_diff: float, tol: float, loose_factor: float = 3.0,
                 collect: list | None = None) -> Share:
    """How much copper of the selected nets is within +-tol (fraction) of its target. Single nets: Z0 vs z_se. Pair
    legs (partner found by swapping the suffix): Zdiff at the gap measured at each segment's midpoint vs z_diff; a
    partner farther than loose_factor x the nearer plane distance counts as loosely coupled (2 x Z0)."""
    import pcbnew
    segs = [t for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T and _sel(t.GetNetname(), patterns, exclude)]
    by = defaultdict(list)
    for t in segs:
        by[(t.GetNetname(), t.GetLayer())].append(t)
    res = Share()
    netset = {t.GetNetname() for t in segs}
    names = shown(b)

    def partner(n):
        if not pair_suffix:
            return None
        p, q = pair_suffix
        if n.endswith(p):
            return n[: -len(p)] + q
        if n.endswith(q):
            return n[: -len(q)] + p
        return None

    def gap(t, mate):
        px, py = _M((t.GetStart().x + t.GetEnd().x) / 2), _M((t.GetStart().y + t.GetEnd().y) / 2)
        best = math.inf
        for s in by.get((mate, t.GetLayer()), []):
            ax, ay, bx, by_ = _M(s.GetStart().x), _M(s.GetStart().y), _M(s.GetEnd().x), _M(s.GetEnd().y)
            dx, dy = bx - ax, by_ - ay
            l2 = dx * dx + dy * dy
            u = 0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            best = min(best, math.hypot(px - ax - u * dx, py - ay - u * dy) - _M(s.GetWidth()) / 2 - _M(t.GetWidth()) / 2)
        return best

    for t in segs:
        L = std(t.GetLayer())
        mx, my = _M((t.GetStart().x + t.GetEnd().x) / 2), _M((t.GetStart().y + t.GetEnd().y) / 2)
        e = pm.env_at(stack, L, mx, my)
        ln = _M(t.GetLength())
        seg = ((_M(t.GetStart().x), _M(t.GetStart().y)), (_M(t.GetEnd().x), _M(t.GetEnd().y)), _M(t.GetWidth()))
        if e.h_up is None and e.h_down is None:
            res.skipped[names[L]] = res.skipped.get(names[L], 0.0) + ln
            if collect is not None:
                collect.append(seg + (None,))
            continue
        n = t.GetNetname()
        w = _M(t.GetWidth())
        mate = partner(n)
        if mate and mate in netset:
            h = e.h_down if e.h_up is None else (e.h_up if e.h_down is None else min(e.h_up, e.h_down))
            g = gap(t, mate)
            z = 2 * z0(e, w) if g > loose_factor * h else zdiff(e, w, max(g, 0.01))
            kind, tgt = "pair", z_diff
        else:
            z, kind, tgt = z0(e, w), "single", z_se
        inb = abs(z - tgt) <= tol * tgt
        if collect is not None:
            collect.append(seg + (abs(z - tgt) / tgt,))
        r = res.rows.setdefault((kind, names[L]), [0.0, 0.0, 0.0])
        r[0] += ln * inb
        r[1] += ln
        r[2] += ln * z
        q = res.nets.setdefault(n, [0.0, 0.0])
        q[0] += ln * inb
        q[1] += ln
    return res


@dataclass
class Hop:
    net: str
    x: float
    y: float
    layers: tuple[str, str]
    refs: tuple[str, str]       # reference net on each side
    path: str                   # "same plane", "via of NET", "capacitor NET1-NET2", "none found"
    distance: float | None      # mm to the return path


def return_hops(b, stack: Stackup, pm: "PlaneMap", patterns: list[str], fills=None, exclude: list[str] | None = None) -> list[Hop]:
    """For each via where a selected net changes layer, the reference plane net on each side and the distance to the
    nearest path for the return current: none needed if both sides reference the same plane layer; else the nearest
    via of the plane net that spans both plane layers (same net), or the nearest two-pin capacitor between the two
    plane nets (different nets)."""
    import pcbnew
    from shapely.geometry import Point
    fills = fills if fills is not None else plane_fills(b)
    ends = defaultdict(set)
    for t in b.GetTracks():
        if t.Type() != pcbnew.PCB_VIA_T and _sel(t.GetNetname(), patterns, exclude):
            for p in (t.GetStart(), t.GetEnd()):
                ends[(t.GetNetname(), round(_M(p.x), 3), round(_M(p.y), 3))].add(std(t.GetLayer()))
    allvias = [v for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T]
    cu = [std(l) for l in b.GetEnabledLayers().CuStack()]
    names = shown(b)
    caps = defaultdict(list)
    for fp in b.GetFootprints():
        nets = {p.GetNetname() for p in fp.Pads() if p.GetNumber()}
        if fp.GetReference().upper().startswith("C") and len(nets) == 2 and "" not in nets:
            caps[frozenset(nets)].append((_M(fp.GetPosition().x), _M(fp.GetPosition().y)))
    def ref_plane(L, x, y):
        e = pm.env_at(stack, L, x, y, r=0.6)   # the via's own antipad voids the plane right at the via
        if e.plane_up is None:
            return e.plane_down
        if e.plane_down is None:
            return e.plane_up
        return e.plane_up if e.h_up <= e.h_down else e.plane_down

    def net_at(L, x, y):
        best, bn = math.inf, None
        pt = Point(x, y)
        for n, p in fills.get(L, []):
            d = p.distance(pt)
            if d < best:
                best, bn = d, n
        return bn if best < 1.0 else None

    hops = []
    for v in allvias:
        n = v.GetNetname()
        if not _sel(n, patterns, exclude):
            continue
        x, y = _M(v.GetPosition().x), _M(v.GetPosition().y)
        lays = set()
        for (nn, ex, ey), ls in ends.items():
            if nn == n and abs(ex - x) < 0.05 and abs(ey - y) < 0.05:
                lays |= ls
        lays = sorted(lays, key=cu.index)
        if len(lays) < 2:
            continue
        la, lb = lays[0], lays[-1]
        pa, pb = ref_plane(la, x, y), ref_plane(lb, x, y)
        if pa is None or pb is None:
            continue
        na, nb = net_at(pa, x, y), net_at(pb, x, y)
        if pa == pb:
            hops.append(Hop(n, x, y, (names[la], names[lb]), (na, nb), "same plane", 0.0))
            continue
        if na and na == nb:
            ia, ib = sorted((cu.index(pa), cu.index(pb)))
            cand = [( _M(w.GetPosition().x), _M(w.GetPosition().y)) for w in allvias if w.GetNetname() == na
                    and cu.index(std(w.TopLayer())) <= ia and cu.index(std(w.BottomLayer())) >= ib]
            path = f"via of {na}"
        elif na and nb:
            cand = caps.get(frozenset((na, nb)), [])
            path = f"capacitor {na}-{nb}"
        else:
            cand, path = [], "no plane under the via"
        d = min((math.hypot(cx - x, cy - y) for cx, cy in cand), default=None)
        hops.append(Hop(n, x, y, (names[la], names[lb]), (na, nb), path if d is not None else path + " (none found)", d))
    return hops

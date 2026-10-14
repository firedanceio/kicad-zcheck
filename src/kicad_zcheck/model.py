"""Closed-form transmission-line estimates on a KiCad stack-up.

Formulas (the usual first-pass set; expect about +-10 % against a field solver, and trust your fabricator's numbers
over these):
* surface or embedded microstrip, IPC-2141: Z0 = 87 / sqrt(er + 1.41) * ln(5.98 h / (0.8 w + t))
* stripline between two planes, IPC-2141 with h the trace-to-plane distance on each side: each side is evaluated as a
  symmetric stripline of that half-spacing and the two are combined in parallel, 2 Z1 Z2 / (Z1 + Z2)
* differential: microstrip 2 Z0 (1 - 0.48 exp(-0.96 s / h)); stripline 2 Z0 (1 - 0.374 exp(-2.9 s / h)), h the
  nearer plane distance
A copper layer that is not a plane counts as dielectric between a trace and its plane (its copper is assumed sparse).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .stackup import Layer, Stackup


@dataclass
class Env:
    layer: str
    kind: str                 # "microstrip" or "stripline"
    h_up: float | None        # dielectric distance to the plane above (None: none, outer surface)
    er_up: float | None
    h_down: float | None
    er_down: float | None
    t: float                  # copper thickness
    plane_up: str | None
    plane_down: str | None


def env(stack: Stackup, layer: str, planes: set[str]) -> Env:
    L = stack.layers
    i = next(k for k, l in enumerate(L) if l.name == layer)

    def walk(step):
        h, acc, j = 0.0, [], i + step
        while 0 <= j < len(L):
            l = L[j]
            if l.kind == "copper":
                if l.name in planes:
                    er = sum(a * b for a, b in acc) / h if h else 4.3
                    return h, er, l.name
                h += l.thickness
            else:
                h += l.thickness
                acc.append((l.thickness, l.epsilon_r or 4.3))
            j += step
        return None, None, None

    hu, eu, pu = walk(-1)
    hd, ed, pd = walk(1)
    kind = "stripline" if (hu is not None and hd is not None) else "microstrip"
    return Env(layer, kind, hu, eu, hd, ed, L[i].thickness, pu, pd)


def _ms(w, h, er, t):
    return 87.0 / math.sqrt(er + 1.41) * math.log(max(5.98 * h / (0.8 * w + t), 1.0001))


def _sl(w, h, er, t):
    return 60.0 / math.sqrt(er) * math.log(max(1.9 * (2 * h + t) / (0.8 * w + t), 1.0001))


def z0(e: Env, w: float) -> float:
    if e.h_up is None and e.h_down is None:
        return float("nan")
    if e.kind == "microstrip":
        h, er = (e.h_down, e.er_down) if e.h_up is None else (e.h_up, e.er_up)
        return _ms(w, h, er, e.t)
    z1, z2 = _sl(w, e.h_up, e.er_up, e.t), _sl(w, e.h_down, e.er_down, e.t)
    return 2 * z1 * z2 / (z1 + z2)


def zdiff(e: Env, w: float, s: float) -> float:
    z = z0(e, w)
    if e.kind == "microstrip":
        h = e.h_down if e.h_up is None else e.h_up
        return 2 * z * (1 - 0.48 * math.exp(-0.96 * s / h))
    h = min(e.h_up, e.h_down)
    return 2 * z * (1 - 0.374 * math.exp(-2.9 * s / h))


def solve_width(f, target: float, lo: float = 0.02, hi: float = 3.0) -> float | None:
    """Width at which the decreasing function f(width) equals target; None if out of [lo, hi]."""
    if not (f(hi) <= target <= f(lo)):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > target else (lo, mid)
    return (lo + hi) / 2


def candidate(stack: Stackup, dielectrics: list[float], er: list[float] | None = None) -> Stackup:
    """A copy of ``stack`` with the dielectric thicknesses between consecutive copper layers replaced (one value per
    gap, top to bottom; a gap made of several dielectric entries becomes one). ``er`` optionally replaces permittivity."""
    cu = stack.copper
    if len(dielectrics) != len(cu) - 1:
        raise ValueError(f"need {len(cu) - 1} dielectric thicknesses for {len(cu)} copper layers, got {len(dielectrics)}")
    old_er = []
    i = 0
    for k in range(len(cu) - 1):
        a = stack.layers.index(cu[k])
        b = stack.layers.index(cu[k + 1])
        gap = stack.layers[a + 1:b]
        tot = sum(l.thickness for l in gap) or 1
        old_er.append(sum(l.thickness * (l.epsilon_r or 4.3) for l in gap) / tot)
    out = Stackup()
    for k, c in enumerate(cu):
        out.layers.append(Layer(c.name, "copper", c.thickness))
        if k < len(cu) - 1:
            out.layers.append(Layer(f"gap {k + 1}", "dielectric", dielectrics[k], (er[k] if er else old_er[k])))
    return out

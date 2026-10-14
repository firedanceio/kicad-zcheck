"""Closed-form transmission-line estimates on a KiCad stack-up.

Formulas (trust your fabricator's numbers over these):
* surface microstrip: Hammerstad & Jensen (1980) with their strip-thickness correction, the model behind KiCad's own
  transmission-line calculator. Within about 1 % of the quasi-static solution; solder mask is not modelled and pulls
  the real value down a few ohm.
* stripline between two planes: Wheeler (1978) with thickness correction, within about 0.5 % of the exact
  conformal-mapping result for a centred trace. With h the trace-to-plane distance on each side, each side is
  evaluated as a centred stripline of plane spacing 2 h + t and the two are combined in parallel, 2 Z1 Z2 / (Z1 + Z2).
* stripline differential: Cohn's exact odd-mode impedance of edge-coupled lines (zero thickness), scaled by the same
  thickness correction as the single-ended line, per side and combined in parallel as above.
* microstrip differential: the IPC-2141 coupling factor, 2 Z0 (1 - 0.48 exp(-0.96 s / h)). This one is empirical:
  expect about +-10 %, more for gaps well under h.
Single-ended IPC-2141 (87 / sqrt(er + 1.41) ln(5.98 h / (0.8 w + t))) was used before 0.1.1; it reads 15-25 % low for
microstrip when w/h passes about 1.5, which thin outer prepregs make common.
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
    """Hammerstad & Jensen microstrip, trace width w and thickness t at height h over the plane."""
    u, tn = w / h, max(t, 1e-6) / h
    du1 = tn / math.pi * math.log(1 + 4 * math.e / (tn / math.tanh(math.sqrt(6.517 * u)) ** 2))
    dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(max(er - 1, 0.0)))) * du1
    u1, ur = u + du1, u + dur

    def z01(x):
        f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / x) ** 0.7528))
        return 60 * math.log(f / x + math.sqrt(1 + 4 / x ** 2))

    def e_eff(x):
        a = 1 + math.log((x ** 4 + (x / 52) ** 2) / (x ** 4 + 0.432)) / 49 + math.log(1 + (x / 18.1) ** 3) / 18.7
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / x) ** (-a * b)

    return z01(ur) / math.sqrt(e_eff(ur) * (z01(u1) / z01(ur)) ** 2)


def _sl(w, h, er, t):
    """Wheeler stripline, centred in a plane spacing b = 2 h + t (h: trace-to-plane distance)."""
    b = 2 * h + t
    x = t / b
    m = 2 / (1 + 2 / 3 * x / (1 - x))
    dw = x / (math.pi * (1 - x)) * (1 - 0.5 * math.log((x / (2 - x)) ** 2 + (0.0796 * x / (w / b + 1.1 * x)) ** m)) if x > 0 else 0.0
    k = 4 / (math.pi * (w / (b - t) + dw))
    return 30 / math.sqrt(er) * math.log(1 + k * (2 * k + math.sqrt((2 * k) ** 2 + 6.27)))


def _K(m):
    """Complete elliptic integral of the first kind K(m), m = k^2, by the arithmetic-geometric mean."""
    a, g = 1.0, math.sqrt(1 - m)
    for _ in range(40):
        a, g = (a + g) / 2, math.sqrt(a * g)
    return math.pi / (2 * a)


def _sl_diff(w, s, h, er, t):
    """Edge-coupled stripline differential impedance, centred in a plane spacing 2 h + t: Cohn's exact odd mode for
    zero thickness, times the thickness correction of the single line."""
    b = 2 * h + t
    ko = math.tanh(math.pi * w / (2 * b)) / math.tanh(math.pi * (w + s) / (2 * b))
    z_odd = 30 * math.pi / math.sqrt(er) * _K(1 - ko * ko) / _K(ko * ko)
    return 2 * z_odd * _sl(w, h, er, t) / _sl(w, h + t / 2, er, 0.0)     # same spacing b, without the thickness


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
    z1, z2 = _sl_diff(w, s, e.h_up, e.er_up, e.t), _sl_diff(w, s, e.h_down, e.er_down, e.t)
    return 2 * z1 * z2 / (z1 + z2)


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

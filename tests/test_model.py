import math

import pytest

from kicad_zcheck.model import candidate, env, solve_width, z0, zdiff
from kicad_zcheck.stackup import Layer, Stackup


def eight_layer():
    st = Stackup()
    cu = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"]
    gaps = [(0.092, 4.1), (0.13, 4.17), (0.406, 4.4), (0.13, 4.17), (0.406, 4.4), (0.13, 4.17), (0.092, 4.1)]
    for k, c in enumerate(cu):
        st.layers.append(Layer(c, "copper", 0.035 if k in (0, 7) else 0.03))
        if k < 7:
            st.layers.append(Layer(f"d{k}", "core", *gaps[k]))
    return st


PLANES = {"In2.Cu", "In4.Cu", "In6.Cu"}


def test_environment():
    st = eight_layer()
    e = env(st, "In3.Cu", PLANES)
    assert e.kind == "stripline" and e.h_up == pytest.approx(0.406) and e.h_down == pytest.approx(0.13)
    f = env(st, "F.Cu", PLANES)                       # In1 is a signal layer: counted as dielectric
    assert f.kind == "microstrip" and f.h_up is None and f.h_down == pytest.approx(0.092 + 0.03 + 0.13)
    assert env(st, "B.Cu", PLANES).h_up == pytest.approx(0.092)


def test_values_match_the_closed_forms():
    st = eight_layer()
    # IPC-2141 microstrip by hand: 87/sqrt(4.1+1.41)*ln(5.98*0.092/(0.8*0.1+0.035))
    want = 87 / math.sqrt(5.51) * math.log(5.98 * 0.092 / (0.8 * 0.1 + 0.035))
    assert z0(env(st, "B.Cu", PLANES), 0.1) == pytest.approx(want)
    e3 = env(st, "In3.Cu", PLANES)
    assert z0(e3, 0.09) == pytest.approx(61, abs=1)         # the value our board review used
    assert zdiff(e3, 0.13, 0.10) == pytest.approx(101, abs=1.5)


def test_monotonic_and_solver():
    e = env(eight_layer(), "In5.Cu", PLANES)
    assert z0(e, 0.08) > z0(e, 0.1) > z0(e, 0.2)
    assert zdiff(e, 0.1, 0.1) < zdiff(e, 0.1, 0.3) < 2 * z0(e, 0.1)
    w = solve_width(lambda w: z0(e, w), 50)
    assert z0(e, w) == pytest.approx(50, abs=0.05)
    assert solve_width(lambda w: z0(e, w), 500) is None     # unreachable


def test_candidate_stack():
    st = eight_layer()
    c = candidate(st, [0.092, 0.075, 0.075, 0.45, 0.45, 0.075, 0.092])
    assert [l.name for l in c.copper] == [l.name for l in st.copper]
    e = env(c, "In3.Cu", PLANES)
    assert e.h_up == pytest.approx(0.075) and e.h_down == pytest.approx(0.45)
    assert z0(e, 0.09) < z0(env(st, "In3.Cu", PLANES), 0.09)   # thinner dielectric, lower impedance
    with pytest.raises(ValueError):
        candidate(st, [0.1, 0.1])

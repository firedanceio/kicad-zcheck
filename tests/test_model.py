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


def test_microstrip_matches_reference_values():
    from kicad_zcheck.model import _ms
    assert _ms(3.0, 1.6, 4.4, 0.035) == pytest.approx(50.4, abs=0.3)      # the classic 50 ohm line on 1.6 mm FR4
    assert _ms(1.0, 1.0, 10.0, 1e-6) == pytest.approx(48.9, abs=0.3)      # Pozar: w/h ~0.95 for 50 ohm on er 10
    # wide trace on thin prepreg (w/h 2): IPC-2141 reads ~15 % low here; Hammerstad-Jensen does not
    assert _ms(0.15, 0.074, 4.0, 0.035) > 45


def test_stripline_matches_exact_solution():
    from kicad_zcheck.model import _sl

    def exact(w, b, er):                     # zero-thickness centred stripline, conformal mapping (Cohn)
        k = 1 / math.cosh(math.pi * w / (2 * b))
        kp = math.sqrt(1 - k * k)

        def K(m):                             # complete elliptic integral of the first kind, by the AGM
            a, g = 1.0, math.sqrt(1 - m)
            for _ in range(30):
                a, g = (a + g) / 2, math.sqrt(a * g)
            return math.pi / (2 * a)
        return 30 * math.pi / math.sqrt(er) * K(k * k) / K(kp * kp)

    for w, b in [(2.66, 3.2), (0.1, 0.3), (0.2, 0.25)]:
        assert _sl(w, b / 2, 4.0, 0.0) == pytest.approx(exact(w, b, 4.0), rel=0.005)
    assert _sl(2.66, 1.6, 2.2, 0.0) == pytest.approx(50, abs=0.3)         # Pozar example 3.5


def test_values_on_a_stackup():
    st = eight_layer()
    e3 = env(st, "In3.Cu", PLANES)
    assert z0(e3, 0.09) == pytest.approx(61, abs=1)         # the value our board review used
    # pairs: a 2D finite-difference field solve of this cross-section gives 76.1 ohm for a centred 0.13/0.10 pair in
    # 0.33 mm of er 4.0; the closed form reads about 5 % high (thick-copper coupling is not modelled)
    from kicad_zcheck.model import Env
    centred = Env("x", "stripline", 0.15, 4.0, 0.15, 4.0, 0.03, "p", "q")
    assert zdiff(centred, 0.13, 0.10) == pytest.approx(76.1, rel=0.07)
    assert z0(centred, 0.13) == pytest.approx(47.2, rel=0.01)                # field solve 47.17
    offset = Env("x", "stripline", 0.406, 4.3, 0.13, 4.3, 0.03, "p", "q")
    assert z0(offset, 0.13) == pytest.approx(51.3, rel=0.04)                 # field solve 51.28
    loose = zdiff(centred, 0.13, 5.0)
    assert loose == pytest.approx(2 * z0(centred, 0.13), rel=0.001)          # far apart: twice the single line


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

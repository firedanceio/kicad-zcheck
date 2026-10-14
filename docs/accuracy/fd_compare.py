"""Compare kicad-zcheck with the 2D field solve in fd2d.py on stripline cross-sections like the example boards.

Run from this directory with KiCad's Python (it needs numpy and scipy): python3 fd_compare.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from fd2d import impedance
from kicad_zcheck.model import Env, z0, zdiff
cases = [
  # kind, w, t, h_low(trace-to-lower-plane), h_up(trace top to upper plane), er, s
  ("stripline", 0.13, 0.03, 0.15, 0.15, 4.0, None),
  ("stripline", 0.13, 0.03, 0.13, 0.406, 4.3, None),
  ("stripline", 0.13, 0.03, 0.114, 0.20, 4.0, None),
  ("stripline", 0.13, 0.03, 0.15, 0.15, 4.0, 0.10),
  ("stripline", 0.13, 0.03, 0.13, 0.406, 4.3, 0.10),
  ("stripline", 0.10, 0.03, 0.114, 0.20, 4.0, 0.10),
]
print(f"{'kind':10s} {'w':>5s} {'h':>11s} {'s':>5s} | {'FD d':>7s} {'FD d/2':>7s} {'FD ext':>7s} | {'zcheck':>7s} {'diff':>6s}")
for kind, w, t, hl, hu, er, s in cases:
    d = min(w, t, hl) / 6
    a = impedance(kind, w, t, hl, hu, er, s, d=d)
    b = impedance(kind, w, t, hl, hu, er, s, d=d / 2)
    ext = 2 * b - a                                    # Richardson, first order
    if kind == "microstrip":
        e = Env("x", "microstrip", None, None, hl, er, t, None, "p")
    else:
        e = Env("x", "stripline", hu, er, hl, er, t, "p", "q")
    ours = z0(e, w) if s is None else zdiff(e, w, s)
    print(f"{kind:10s} {w:5.2f} {str(hl)+'/'+str(hu):>11s} {str(s):>5s} | {a:7.2f} {b:7.2f} {ext:7.2f} | {ours:7.2f} {100*(ours-ext)/ext:+5.1f}%", flush=True)

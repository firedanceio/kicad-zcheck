"""kicad-zcheck: impedance and return-path checks on a KiCad board's own stack-up and routed copper."""
from .model import candidate, env, solve_width, z0, zdiff
from .stackup import Stackup, read_stackup

__all__ = ["candidate", "env", "solve_width", "z0", "zdiff", "Stackup", "read_stackup"]
__version__ = "0.1.0"

"""Field solve of a covered (buried) microstrip: an inner-layer trace with a plane below it and only dielectric, no
plane, between it and the board surface. kicad-zcheck does not model this case yet: it computes such a trace as a
surface microstrip with air above. This script measures how far off that is, for In1 of an 8-layer stack-up:

  F.Cu level 0.035 mm, no copper (air, or solder mask)
  prepreg    0.092 mm, er 4.1
  In1 trace  0.10 mm wide, 0.030 mm copper (inside the prepreg)
  core       0.130 mm, er 4.17
  In2        plane

Cell-centred finite differences (harmonic-mean permittivity at cell faces, plane at y = 0, no-flux box walls), Z0 =
1 / (c sqrt(C C_air)) with the capacitance from the field energy. The fixed-potential trace cells shrink the trace by
half a cell on each side, so the error is first order in the cell size: each case is solved at 5 and 2.5 um and
extrapolated, 2 Z(d/2) - Z(d) (a 1.25 um solve agrees within 0.1 ohm). In3 of the same stack-up, a stripline between
In2 and In4, is the control: the extrapolated value sits 3.6 % under Wheeler's 58.85 ohm, in line with the off-centre
row of the table in README.md. Run with any Python with numpy and scipy (about a minute):

    python3 fd_covered.py
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

C0, EPS0 = 299792458.0, 8.8541878128e-12


def z0(layers, top_plane, w, t, y_trace, d, half_width=2.0, air=2.0):
    """layers: [(y0, y1, er)] from the lower plane (y = 0) up; top_plane: y of an upper plane, or None for open (air
    up to ``air`` mm above the dielectric); the trace's bottom at y_trace. Returns Z0 in ohm."""
    ymax = top_plane or max(l[1] for l in layers) + air
    nx, ny = int(round(2 * half_width / d)), int(round(ymax / d))
    xs = (np.arange(nx) + 0.5) * d - half_width
    ys = (np.arange(ny) + 0.5) * d
    er = np.ones((ny, nx))
    for y0, y1, e in layers:
        er[(ys >= y0) & (ys < y1), :] = e
    trace = (np.abs(xs)[None, :] <= w / 2 + 1e-9) & (ys[:, None] >= y_trace) & (ys[:, None] < y_trace + t)

    def cap(eps):
        idx = np.arange(nx * ny).reshape(ny, nx)
        gx = 2 * eps[:, 1:] * eps[:, :-1] / (eps[:, 1:] + eps[:, :-1])
        gy = 2 * eps[1:, :] * eps[:-1, :] / (eps[1:, :] + eps[:-1, :])
        diag = np.zeros((ny, nx))
        diag[:, :-1] += gx; diag[:, 1:] += gx; diag[:-1, :] += gy; diag[1:, :] += gy
        diag[0, :] += 2 * eps[0, :]                         # lower plane, half a cell below the first row
        if top_plane:
            diag[-1, :] += 2 * eps[-1, :]
        pairs = ((idx[:, :-1], idx[:, 1:], gx), (idx[:, 1:], idx[:, :-1], gx),
                 (idx[:-1, :], idx[1:, :], gy), (idx[1:, :], idx[:-1, :], gy))
        r = np.concatenate([a.ravel() for a, _, _ in pairs])
        c = np.concatenate([b.ravel() for _, b, _ in pairs])
        v = np.concatenate([-g.ravel() for _, _, g in pairs])
        fixed = trace.ravel()
        keep = ~fixed[r]                                    # trace cells: phi = 1
        dg = diag.ravel().copy(); dg[fixed] = 1.0
        n = nx * ny
        A = coo_matrix((np.concatenate([v[keep], dg]), (np.concatenate([r[keep], np.arange(n)]),
                                                         np.concatenate([c[keep], np.arange(n)]))), shape=(n, n))
        phi = spsolve(A.tocsr(), fixed.astype(float)).reshape(ny, nx)
        u = (gx * np.diff(phi, axis=1) ** 2).sum() + (gy * np.diff(phi, axis=0) ** 2).sum()
        u += (2 * eps[0, :] * phi[0, :] ** 2).sum()
        if top_plane:
            u += (2 * eps[-1, :] * phi[-1, :] ** 2).sum()
        return u * EPS0

    return 1.0 / (C0 * np.sqrt(cap(er) * cap(np.ones_like(er))))


def extrapolated(*args):
    return 2 * z0(*args, 0.0025) - z0(*args, 0.005)


if __name__ == "__main__":
    W, T = 0.10, 0.030
    top = 0.13 + T + 0.092
    in3 = [(0, 0.13, 4.17), (0.13, 0.13 + T + 0.406, 4.4)]
    print(f"In3 stripline (control), w 0.10: {extrapolated(in3, 0.13 + T + 0.406, W, T, 0.13):.1f} ohm "
          f"(kicad-zcheck, Wheeler: 58.85)", flush=True)
    in1 = [(0, 0.13, 4.17), (0.13, top, 4.1)]
    print(f"In1 covered microstrip, no mask, w 0.10: {extrapolated(in1, None, W, T, 0.13):.1f} ohm "
          f"(kicad-zcheck, as a surface microstrip: 77.6)", flush=True)
    masked = in1 + [(top, top + 0.035 + 0.025, 3.8)]       # mask filling the empty F.Cu level, 0.025 mm above it
    print(f"In1 covered microstrip, 0.025 mm mask er 3.8, w 0.10: {extrapolated(masked, None, W, T, 0.13):.1f} ohm",
          flush=True)

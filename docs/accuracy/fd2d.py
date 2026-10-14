"""Small 2D finite-difference field solver for PCB trace cross-sections (quasi-static, lossless).

Z0 = 1 / (c * sqrt(C * C_air)), C and C_air the capacitance per unit length with and without the dielectric.
Capacitance from the stored field energy: U = 1/2 sum(Q V) -> single trace at 1 V: C = 2 U; odd mode at +1/-1 V:
U = C_odd, and Z_diff = 2 Z_odd.

Geometry (mm), y up, plane(s) at y=0 and (stripline) y=b:
  stripline(w, t, h_low, h_up, er, s=None)   trace bottom at h_low above the lower plane, h_up from its top to the upper
  microstrip(w, t, h, er, s=None)           trace on top of a dielectric of height h, air above. The uniform grid does
                                            not converge well for microstrip (the open top needs a large air box); we
                                            use this solver for stripline only.
"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

EPS0 = 8.854187817e-12
C0 = 299792458.0


def _solve(nx, ny, d, eps, fixed, vals):
    """eps: (ny, nx) cell permittivity (cells between nodes: (ny-1, nx-1)); fixed/vals: node masks/values."""
    N = nx * ny
    idx = np.arange(N).reshape(ny, nx)
    rows, cols, data = [], [], []
    diag = np.zeros(N)
    # edge permittivity: average of the (up to) two cells that share the edge
    ec = np.pad(eps, 1, mode="edge")                      # (ny+1, nx+1) cells around nodes
    # horizontal edges (i,j)-(i,j+1): cells (i-1,j) and (i,j) in eps index -> ec[i, j+1], ec[i+1, j+1]
    eh = 0.5 * (ec[:-1, 1:-1] + ec[1:, 1:-1])             # (ny, nx-1)
    ev = 0.5 * (ec[1:-1, :-1] + ec[1:-1, 1:])             # (ny-1, nx)
    a, b = idx[:, :-1].ravel(), idx[:, 1:].ravel()
    w = eh.ravel()
    for p, q in ((a, b), (b, a)):
        rows.append(p); cols.append(q); data.append(-w)
    np.add.at(diag, a, w); np.add.at(diag, b, w)
    a, b = idx[:-1, :].ravel(), idx[1:, :].ravel()
    w = ev.ravel()
    for p, q in ((a, b), (b, a)):
        rows.append(p); cols.append(q); data.append(-w)
    np.add.at(diag, a, w); np.add.at(diag, b, w)
    A = sp.coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N)).tocsr()
    A = A + sp.diags(diag)
    f = fixed.ravel()
    v = np.where(f, vals.ravel(), 0.0)
    free = ~f
    rhs = -A[free][:, f] @ v[f]
    phi = v.copy()
    phi[free] = spla.spsolve(A[free][:, free].tocsc(), rhs)
    phi = phi.reshape(ny, nx)
    # energy per unit length: 1/2 eps0 sum over edges eps_edge (dphi)^2 (d cancels in 2D: |grad|^2 * d^2)
    U = 0.5 * EPS0 * (np.sum(eh * np.diff(phi, axis=1) ** 2) + np.sum(ev * np.diff(phi, axis=0) ** 2))
    return U


def _cross(kind, w, t, h_low, h_up, er, s, d, side=6.0, air=10.0):
    n = lambda x: int(round(x / d))
    traces = [(-w / 2, w / 2)] if s is None else [(-s / 2 - w, -s / 2), (s / 2, s / 2 + w)]
    half = (w if s is None else s / 2 + w) + side * (h_low + t + (h_up or 0))
    nx = 2 * n(half) + 1
    if kind == "stripline":
        H = h_low + t + h_up
    else:
        H = h_low + t + air * (h_low + t)
    ny = n(H) + 1
    xs = (np.arange(nx) - (nx - 1) / 2) * d
    ys = np.arange(ny) * d
    X, Y = np.meshgrid(xs, ys)
    fixed = np.zeros((ny, nx), bool)
    vals = np.zeros((ny, nx))
    fixed[0, :] = True                                      # lower plane
    if kind == "stripline":
        fixed[-1, :] = True                                 # upper plane
    else:
        fixed[-1, :] = True                                 # far "ground" boundary, far away
    fixed[:, 0] = fixed[:, -1] = True                       # far side walls at 0 V
    pol = [1.0] if s is None else [-1.0, 1.0]
    for (x0, x1), V in zip(traces, pol):
        m = (X >= x0 - 1e-9) & (X <= x1 + 1e-9) & (Y >= h_low - 1e-9) & (Y <= h_low + t + 1e-9)
        fixed |= m
        vals[m] = V
    yc = (np.arange(ny - 1) + 0.5) * d
    if kind == "stripline":
        epsc = np.full((ny - 1, nx - 1), er)
    else:
        epsc = np.where(yc[:, None] < h_low, er, 1.0) * np.ones((1, nx - 1))
    return nx, ny, epsc, fixed, vals


def impedance(kind, w, t, h_low, h_up=None, er=4.0, s=None, d=None):
    d = d or min(w, t if t > 0 else w, h_low) / 8
    nx, ny, epsc, fixed, vals = _cross(kind, w, t, h_low, h_up, er, s, d)
    U = _solve(nx, ny, d, epsc, fixed, vals)
    U0 = _solve(nx, ny, d, np.ones_like(epsc), fixed, vals)
    k = 2.0 if s is None else 1.0                          # C = 2U (single at 1 V); C_odd = U (+1/-1)
    C, Ca = k * U, k * U0
    z = 1 / (C0 * np.sqrt(C * Ca))
    return z if s is None else 2 * z


if __name__ == "__main__":
    # sanity: centred stripline, compare with the exact (zero-thickness) Cohn result
    print("stripline w=0.2 b=0.25 t~0 er=4:", round(impedance("stripline", 0.2, 0.0025, 0.12375, 0.12375, 4.0, d=0.0025), 2), "(exact 37.98)")

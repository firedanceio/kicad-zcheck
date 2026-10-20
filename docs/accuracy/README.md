# How accurate are the numbers?

kicad-zcheck uses closed-form formulas, so it is fast and needs nothing beyond KiCad. This page records what they
were checked against and how far off they can be.

## Single-ended

| Line | Formula | Checked against | Result |
|---|---|---|---|
| Outer layer (microstrip) | Hammerstad & Jensen (1980), with their thickness correction; the model in KiCad's own transmission-line calculator | Published values: 50 ohm, 3.0 mm on 1.6 mm FR4 (er 4.4); Pozar's w/h ~0.95 for 50 ohm on er 10 | 50.4 and 48.9 ohm |
| Inner layer, centred (stripline) | Wheeler (1978), with thickness correction | Exact conformal-mapping solution (Cohn), zero thickness; Pozar's example 3.5 | within 0.3 %; 49.8 ohm for the book's 50 |
| Inner layer, centred | same | 2D field solve, 0.13 mm trace, 30 um copper, 0.15 mm to each plane | -0.1 % |
| Inner layer, off-centre | each side as a centred line of its own plane spacing, combined in parallel | 2D field solve, 0.13 mm trace at 0.13 / 0.406 mm and 0.114 / 0.2 mm | +3.3 % and +0.3 % |

Solder mask is not modelled. On an outer layer it pulls the real impedance down a few ohm.

### Not handled yet: an inner layer with a plane on one side only

An inner trace with a plane on one side and only dielectric between it and the board surface (a covered, or buried,
microstrip) is computed as a surface microstrip with air above, so the dielectric covering it is left out. That
reads high:

| Line | Checked against | kicad-zcheck | Result |
|---|---|---|---|
| In1, 0.10 mm trace, 30 um copper, 0.13 mm (er 4.17) over In2, under 0.092 mm prepreg (er 4.1) and an empty F.Cu level | 2D field solve (`fd_covered.py`): 63.7 ohm, 62.8 ohm with 0.025 mm of mask (er 3.8) | 77.6 ohm | 22-24 % high |

The same applies to pairs on such a layer. Until this case is modelled, treat numbers there as an upper limit.

## Differential pairs

| Line | Formula | Checked against | Result |
|---|---|---|---|
| Inner layer | Cohn's exact odd-mode impedance of edge-coupled lines (zero thickness), times the single line's thickness correction | 2D field solve, 0.10-0.13 mm traces with a 0.10 mm gap, three cross-sections | 5 to 8 % high |
| Outer layer | IPC-2141 coupling factor, 2 Z0 (1 - 0.48 exp(-0.96 s / h)) | not checked here | empirical: treat as +-10 %, more for gaps well under h |

The inner-layer pair numbers read high because the copper's own thickness adds coupling between the two traces,
which the zero-thickness formula leaves out. With 30 um copper and a 0.1 mm gap that is worth 5 to 8 %.

## What changed

Before this check, kicad-zcheck used IPC-2141 throughout. On the same cases:

| Case | IPC-2141 | Now |
|---|---|---|
| Inner, single-ended, 0.13 mm | within 2 % | within 3.3 % |
| Inner, single-ended, 0.2 mm on a 0.25 mm spacing | about 10 % low | Wheeler, within 0.5 % of the exact solution |
| Outer, single-ended, 0.1-0.2 mm over 0.074 mm prepreg | 15 to 24 % low | Hammerstad & Jensen |
| Inner pairs, 0.1 mm gap | 15 to 31 % high | 5 to 8 % high |

The IPC microstrip formula is only meant for w/h up to about 2, and thin outer prepregs push real boards past that.

## The field solver

`fd2d.py` is a small 2D finite-difference solver for a trace cross-section: it solves Laplace's equation with the
traces held at a voltage and the planes at 0, finds the capacitance per unit length from the stored field energy,
and gets the impedance from that capacitance with and without the dielectric. It is checked against the exact
centred-stripline solution (37.74 against 37.98 ohm with a 2.5 um trace). Each comparison is solved at two grid
sizes and extrapolated. On its uniform grid it does not converge well for microstrip, so it is used for stripline
only.

`fd_covered.py` solves the covered microstrip above: a cell-centred grid in a 4 mm wide box with 2 mm of air above
the board, solved at 5 and 2.5 um cells and extrapolated, with a stripline on the same stack-up as a control.

```bash
python3 fd2d.py          # the self-check
python3 fd_compare.py    # the table above
python3 fd_covered.py    # the covered-microstrip row
```

Run them with KiCad's Python, or any Python with numpy and scipy.

## The final word

These are estimates for finding problems and comparing options. For a board you are ordering, send the fabricator
the targets, widths and reference layers and let their impedance calculation and test coupons set the build.

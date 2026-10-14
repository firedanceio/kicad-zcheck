# Changelog

## 0.1.0 (unreleased)
- First release: stack-up read from the board file, closed-form Z0/Zdiff per layer and widths for targets, candidate
  stack-ups, routed-copper share within tolerance (pairs judged at their measured gap), return-current path at every
  layer change (same plane, stitching via, or decoupling capacitor), local plane detection from zone fills, KiCad's "power" layer type honoured, renamed layers handled, `--map` board views.
- Impedance model checked against published values, exact solutions and a 2D field solve (docs/accuracy). Single-ended
  microstrip now uses Hammerstad and Jensen and stripline uses Wheeler; IPC-2141 read 15-25 % low for microstrip on
  thin outer prepreg. Stripline pairs use Cohn's coupled-line result; the IPC-2141 coupling factor read 15-30 % high.
- Docs: a second worked example (Antmicro's 12-layer DDR4 tester), maps redrawn with the new model.

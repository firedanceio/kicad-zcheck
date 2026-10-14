# Validation

What we checked before release, why, and what happened. Run on 2026-10-14 with KiCad 10.0.6 on macOS.

## What was needed

kicad-zcheck's numbers are closed-form estimates. Before sharing it we needed to know how far off they can be, on
stack-ups other than ours, and whether any of our own conclusions depended on a formula that was wrong.

## 1. Unit tests

`pytest`: 9 passed. The model tests now pin the formulas to published values, the exact stripline solution and a 2D
field solve (see below), instead of to the formulas' own output.

## 2. Accuracy

Full tables and the scripts are in [docs/accuracy](docs/accuracy/README.md). In short:

| Line | Checked against | Before (IPC-2141) | Now |
|---|---|---|---|
| Outer layer, single | Hammerstad & Jensen (KiCad calculator's model), published values | 15-24 % low over 0.074 mm prepreg | Hammerstad & Jensen |
| Inner layer, single | exact conformal-mapping solution; 2D field solve | within 2 % at 0.13 mm, about 10 % low at 0.2 mm | within 3.3 % of the field solve, centred or off-centre |
| Inner layer, pair | 2D field solve | 15-31 % high | 5-8 % high |
| Outer layer, pair | not checked | empirical | empirical, treat as +-10 % |

The off-centre check also settled how to treat a trace that is closer to one plane: combining the two sides in
parallel came within 3.3 % of the field solve, where using a centred line at the mean spacing was 18 % off.

## 3. Open-source boards

| Board | Targets | Result |
|---|---|---|
| [Antmicro LPDDR4 test board](https://github.com/antmicro/lpddr4-test-board) (8 layers, commit 5c8b5d3) | 40 / 80 ohm | inner layer In2: 96 % single, 86 % pair copper within 10 % |
| [Antmicro DDR4 RDIMM tester](https://github.com/antmicro/data-center-dram-tester) (12 layers, commit e7c85eb) | 40 / 80 ohm | three of four inner layers 88-89 % single, up to 93 % pair; In7 (check bits) runs just under 36 ohm |

We first read the DDR4 tester at 36 ohm because the old formulas put its inner layers there. With the corrected
formulas they average about 38 ohm, so the example uses the common 40 ohm target and says we don't know Antmicro's.

## 4. Our own board, rechecked

The README's claim about FirePod's board rests on this tool. Rerun with the new model on spin 2 r3: 25 % of the DDR
copper within 10 % of target (398 of 1581 mm), the same as the review found. Single-ended numbers barely moved; the
pair numbers came down, as the table above predicts.

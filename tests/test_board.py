"""Synthetic 4-layer boards built with pcbnew; skipped without KiCad's Python."""
import os

import pytest

pcbnew = pytest.importorskip("pcbnew")
from kicad_zcheck.board import PlaneMap, plane_fills, return_hops, routed_share
from kicad_zcheck.model import env, z0
from kicad_zcheck.stackup import read_stackup

mm = pcbnew.FromMM


def build(tmp_path, rename=False):
    """A 40 x 30 mm 4-layer board: GND planes on In1/In2 (already filled, with an antipad around the signal via), a SIG
    track F.Cu -> via at (20, 15) -> B.Cu, and a GND via at (20, 17), 2 mm away and clear of the tracks. Written as
    board-file text so the geometry is exact and needs no zone filler."""
    b = pcbnew.BOARD()
    b.SetCopperLayerCount(4)
    if rename:   # a designer's names and layer types, as many real boards have them
        for L, new in (("In1.Cu", "In1.GND"), ("In2.Cu", "In2.GND")):
            lid = b.GetLayerID(L)
            b.SetLayerName(lid, new)
            b.SetLayerType(lid, pcbnew.LT_POWER)
    p = os.path.join(str(tmp_path), "z.kicad_pcb")
    b.Save(p)
    sq = "(pts (xy 0.5 0.5) (xy 39.5 0.5) (xy 39.5 29.5) (xy 0.5 29.5))"
    # the fill as KiCad writes it: fractured, with an antipad around the SIG via
    fill = ("(pts (xy 0.5 0.5) (xy 39.5 0.5) (xy 39.5 29.5) (xy 0.5 29.5) (xy 0.5 15) (xy 19.4 15) (xy 19.4 15.6) "
            "(xy 20.6 15.6) (xy 20.6 14.4) (xy 19.4 14.4) (xy 19.4 15) (xy 0.5 15))")
    edge = "".join(f'  (gr_line (start {a}) (end {c}) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))\n'
                   for a, c in (("0 0", "40 0"), ("40 0", "40 30"), ("40 30", "0 30"), ("0 30", "0 0")))
    zones = "".join(f'  (zone (net "GND") (layer "{L}") (uuid "00000000-0000-0000-0001-00000000000{k}") (hatch edge 0.5) '
                    f'(connect_pads (clearance 0.2)) (min_thickness 0.25) (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) '
                    f'(polygon {sq}) (filled_polygon (layer "{L}") {fill}))\n' for k, L in enumerate(("In1.Cu", "In2.Cu")))
    items = """
  (segment (start 5 15) (end 20 15) (width 0.2) (layer "F.Cu") (net "SIG") (uuid "00000000-0000-0000-0000-000000000001"))
  (segment (start 20 15) (end 35 15) (width 0.2) (layer "B.Cu") (net "SIG") (uuid "00000000-0000-0000-0000-000000000002"))
  (via (at 20 15) (size 0.5) (drill 0.25) (layers "F.Cu" "B.Cu") (net "SIG") (uuid "00000000-0000-0000-0000-000000000003"))
  (via (at 20 17) (size 0.5) (drill 0.25) (layers "F.Cu" "B.Cu") (net "GND") (uuid "00000000-0000-0000-0000-000000000004"))
"""
    text = open(p).read().rstrip()
    assert text.endswith(")")
    open(p, "w").write(text[:-1] + edge + zones + items + ")\n")
    return pcbnew.LoadBoard(p), p


def test_routed_share_and_planes(tmp_path):
    b, p = build(tmp_path)
    st = read_stackup(p, [b.GetLayerName(l) for l in b.GetEnabledLayers().CuStack()])
    fills = plane_fills(b)
    assert {"In1.Cu", "In2.Cu"} <= set(fills)
    pm = PlaneMap(b, fills)
    e = pm.env_at(st, "F.Cu", 10, 15)
    assert e.kind == "microstrip" and e.plane_down == "In1.Cu"
    target = z0(e, 0.2)
    r = routed_share(b, st, pm, ["SIG"], None, None, target, 100, 0.10)
    row = r.rows[("single", "F.Cu")]
    assert row[1] == pytest.approx(15.0, rel=0.02) and row[0] == pytest.approx(row[1], rel=0.05)


def test_return_hop_through_ground_via(tmp_path):
    b, p = build(tmp_path)
    st = read_stackup(p, [b.GetLayerName(l) for l in b.GetEnabledLayers().CuStack()])
    fills = plane_fills(b)
    hops = return_hops(b, st, PlaneMap(b, fills), ["SIG"], fills)
    assert len(hops) == 1
    h = hops[0]
    assert h.layers == ("F.Cu", "B.Cu") and h.refs == ("GND", "GND")
    assert h.path == "via of GND" and h.distance == pytest.approx(2.0, abs=0.01)


def test_renamed_power_layers(tmp_path):
    from kicad_zcheck.board import detect_planes, shown
    b, p = build(tmp_path, rename=True)
    assert shown(b)["In1.Cu"] == "In1.GND"
    assert detect_planes(b) == {"In1.Cu", "In2.Cu"}              # standard names, from the layer type
    cu = [pcbnew.BOARD.GetStandardLayerName(l) for l in b.GetEnabledLayers().CuStack()]
    st = read_stackup(p, cu)
    fills = plane_fills(b)
    pm = PlaneMap(b, fills)
    assert pm.env_at(st, "F.Cu", 10, 15).plane_down == "In1.Cu"
    hops = return_hops(b, st, pm, ["SIG"], fills)
    assert hops[0].layers == ("F.Cu", "B.Cu") and hops[0].distance == pytest.approx(2.0, abs=0.01)

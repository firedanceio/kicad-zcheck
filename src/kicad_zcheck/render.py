"""Draw a board view to PNG: the outline, every track faintly for context, then highlighted segments and markers.
Needs KiCad's pcbnew and Pillow."""
from __future__ import annotations

import math

GREEN, AMBER, RED, BLUE, GREY = (46, 204, 113), (243, 156, 18), (231, 76, 60), (52, 152, 219), (150, 150, 150)
BG, CONTEXT, EDGE, TEXT = (18, 20, 24), (48, 52, 58), (200, 200, 200), (235, 235, 235)


def _M(v):
    return v / 1e6


def outline(b):
    """Board outline as line segments (mm), arcs and circles flattened."""
    import pcbnew
    segs = []
    for d in b.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts or not hasattr(d, "GetShape"):
            continue
        sh = d.GetShape()
        if sh == pcbnew.SHAPE_T_SEGMENT:
            segs.append(((_M(d.GetStart().x), _M(d.GetStart().y)), (_M(d.GetEnd().x), _M(d.GetEnd().y))))
        elif sh == pcbnew.SHAPE_T_RECT:
            x0, y0, x1, y1 = _M(d.GetStart().x), _M(d.GetStart().y), _M(d.GetEnd().x), _M(d.GetEnd().y)
            segs += [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        elif sh in (pcbnew.SHAPE_T_ARC, pcbnew.SHAPE_T_CIRCLE, pcbnew.SHAPE_T_POLY):
            pts = [(_M(p.x), _M(p.y)) for p in d.GetCorners()] if sh == pcbnew.SHAPE_T_POLY and hasattr(d, "GetCorners") else []
            if not pts:
                poly = pcbnew.SHAPE_POLY_SET()
                d.TransformShapeToPolygon(poly, pcbnew.Edge_Cuts, 0, pcbnew.FromMM(0.01), pcbnew.ERROR_INSIDE)
                if poly.OutlineCount():
                    o = poly.Outline(0)
                    pts = [(_M(o.CPoint(k).x), _M(o.CPoint(k).y)) for k in range(o.PointCount())]
            segs += list(zip(pts, pts[1:] + pts[:1])) if sh != pcbnew.SHAPE_T_ARC else list(zip(pts, pts[1:]))
    return segs


def draw(b, out: str, lines=(), markers=(), legend=(), title: str = "", width: int = 1400, crop=None, context: bool = True):
    """lines: [((x0, y0), (x1, y1), width_mm, rgb)]; markers: [(x, y, radius_px, rgb)]; legend: [(rgb, text)].
    crop: (x0, y0, x1, y1) in mm, default the board outline (or the drawn items) plus a margin."""
    import pcbnew
    from PIL import Image, ImageDraw, ImageFont
    edge = outline(b)
    pts = [p for s in edge for p in s] or [p for l in lines for p in l[:2]] or [(m[0], m[1]) for m in markers]
    if crop:
        x0, y0, x1, y1 = crop
    else:
        x0, y0 = min(p[0] for p in pts) - 2, min(p[1] for p in pts) - 2
        x1, y1 = max(p[0] for p in pts) + 2, max(p[1] for p in pts) + 2
    s = width / (x1 - x0)
    head = 46 if (title or legend) else 0
    img = Image.new("RGB", (width, int((y1 - y0) * s) + head), BG)
    g = ImageDraw.Draw(img)
    P = lambda x, y: ((x - x0) * s, (y - y0) * s + head)
    if context:
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                continue
            a, c = P(_M(t.GetStart().x), _M(t.GetStart().y)), P(_M(t.GetEnd().x), _M(t.GetEnd().y))
            g.line([a, c], fill=CONTEXT, width=max(1, int(_M(t.GetWidth()) * s)))
    for a, c in edge:
        g.line([P(*a), P(*c)], fill=EDGE, width=2)
    for a, c, w, col in lines:
        g.line([P(*a), P(*c)], fill=col, width=max(2, int(w * s)))
    for x, y, r, col in markers:
        cx, cy = P(x, y)
        g.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)
    f = ImageFont.load_default(size=20)
    x = 14
    if title:
        g.text((x, 12), title, fill=TEXT, font=f)
        x += int(g.textlength(title, font=f)) + 30
    for col, txt in legend:
        g.rectangle([x, 16, x + 18, 34], fill=col)
        g.text((x + 26, 12), txt, fill=TEXT, font=f)
        x += 26 + int(g.textlength(txt, font=f)) + 24
    img.save(out, optimize=True)
    return out


def span(b, nets: set[str], margin: float = 3.0):
    """Bounding box (mm) of the given nets' copper, with a margin: a crop for a zoomed view."""
    import pcbnew
    xs, ys = [], []
    for t in b.GetTracks():
        if t.GetNetname() in nets:
            for p in ((t.GetStart(), t.GetEnd()) if t.Type() != pcbnew.PCB_VIA_T else (t.GetPosition(),)):
                xs.append(_M(p.x))
                ys.append(_M(p.y))
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin) if xs else None

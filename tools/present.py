#!/usr/bin/env python3
"""Presentation harness — composite a DSL program and its rendered canvas into one image.

Renders the DSL source syntax-highlighted (monospace, editor-style) on the left and the baked
canvas on the right, into a single PNG suitable for a screenshot.

Run with a python that has Pillow (Blender's bundled one does):
  .../python3.13 tools/present.py <dsl> <canvas.png> <out.png> [title] [caption]
"""
import re
import sys

from PIL import Image, ImageDraw, ImageFont

dsl_path, canvas_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
title = sys.argv[4] if len(sys.argv) > 4 else "Noisemaker for Blender"
caption = sys.argv[5] if len(sys.argv) > 5 else ""

# Catppuccin-ish dark theme.
BG, PANEL, BAR = (24, 24, 37), (30, 30, 46), (17, 17, 27)
FG = (205, 214, 244)
COL = {"kw": (203, 166, 247), "fn": (137, 180, 250), "num": (250, 179, 135),
       "str": (166, 227, 161), "param": (148, 226, 213), "punct": (147, 153, 178),
       "comment": (108, 112, 134), "gutter": (69, 71, 90)}
KW = {"search", "render"}


def font(size):
    for p in ("/System/Library/Fonts/Menlo.ttc",
              "/System/Library/Fonts/SFNSMono.ttf",
              "/System/Library/Fonts/Supplemental/Courier New.ttf",
              "/Library/Fonts/Courier New.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


mono, mono_b, titlef, capf = font(13), font(14), font(22), font(14)
_TOK = re.compile(r'(//.*$)|("(?:[^"\\]|\\.)*")|(\b\d+\.?\d*\b)|([A-Za-z_]\w*)|(\s+)|(.)')


def color_line(line):
    out = []
    for m in _TOK.finditer(line):
        comment, strg, num, ident, ws, other = m.groups()
        if comment:
            out.append((comment, COL["comment"]))
        elif strg:
            out.append((strg, COL["str"]))
        elif num:
            out.append((num, COL["num"]))
        elif ident:
            rest = line[m.end():].lstrip()
            if ident in KW:
                out.append((ident, COL["kw"]))
            elif rest.startswith("("):
                out.append((ident, COL["fn"]))
            elif rest.startswith(":"):
                out.append((ident, COL["param"]))
            else:
                out.append((ident, FG))
        elif ws:
            out.append((ws, FG))
        else:
            out.append((other, COL["punct"]))
    return out


lines = open(dsl_path).read().rstrip("\n").split("\n")
asc, desc = mono.getmetrics()
lh = asc + desc + 3
maxw = max((mono.getlength(ln) for ln in lines), default=240)
pad, gutter = 22, 38
dsl_w = int(maxw) + gutter + pad
dsl_h = len(lines) * lh

canvas = Image.open(canvas_path).convert("RGB")
title_h = 58
cap_h = 30
body_h = max(dsl_h + pad * 2, canvas.size[1] + cap_h + pad * 2)
# Scale the canvas up for presence and to balance the tall DSL panel (cap to stay sharp).
disp_side = min(int(body_h * 0.66), 720)
canvas = canvas.resize((disp_side, disp_side), Image.LANCZOS)
cw, ch = canvas.size
W = pad + dsl_w + pad + cw + pad
H = title_h + body_h

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# title bar
d.rectangle([0, 0, W, title_h], fill=BAR)
d.text((pad, 17), title, font=titlef, fill=FG)
sub = "Polymorphic DSL  →  in-addon compile_graph  →  GPU backend  →  canvas"
d.text((pad + titlef.getlength(title) + 24, 23), sub, font=capf, fill=COL["comment"])

# DSL panel
dx, dy = pad, title_h + pad
d.rectangle([dx, dy, dx + dsl_w, dy + dsl_h + 4], fill=PANEL)
y = dy + 2
for i, ln in enumerate(lines):
    d.text((dx + 8, y), "%2d" % (i + 1), font=mono, fill=COL["gutter"])
    x = dx + gutter
    for text, c in color_line(ln):
        d.text((x, y), text, font=mono, fill=c)
        x += mono.getlength(text)
    y += lh

# canvas panel — vertically centered in the right column
cx = pad + dsl_w + pad
cy = title_h + (body_h - ch - cap_h) // 2 + pad
d.rectangle([cx - 3, cy - 3, cx + cw + 2, cy + ch + 2], outline=(88, 91, 112), width=2)
img.paste(canvas, (cx, cy))
if caption:
    tw = capf.getlength(caption)
    d.text((cx + (cw - tw) // 2, cy + ch + 12), caption, font=capf, fill=FG)

img.save(out_path)
print("wrote %s  %dx%d" % (out_path, W, H))

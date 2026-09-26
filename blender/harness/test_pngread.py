"""Standalone tests for blender/harness/pngread.py (no Blender, no numpy needed).

Covers all five scanline filters on synthetic PNGs with known pixels, the
grayscale and RGB expansions, and a decode of the committed adjust golden with
structural invariants (exact dimensions, nonzero variance, header agreement).

Usage: python3 blender/harness/test_pngread.py
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pngread  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))  # repo root (HERE = blender/harness)
GOLDEN = os.path.join(REPO, "parity", "evidence-2026-09-25", "adjust.golden.png")

fails = []


def build_png(width, height, rows, color_type=6):
    """rows: list of per-scanline filter bytes already applied (raw scanlines)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)

    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))

    idat = zlib.compress(b"".join(bytes(r) for r in rows), 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def expect(cond, msg):
    if cond:
        print("  OK   %s" % msg)
    else:
        print("  FAIL %s" % msg)
        fails.append(msg)


# --- all five filters, RGBA, 4x2, known pixels ------------------------------------
px = [
    [10, 20, 30, 255], [40, 50, 60, 255], [70, 80, 90, 255], [100, 110, 120, 255],
    [130, 140, 150, 255], [160, 170, 180, 255], [190, 200, 210, 255], [220, 230, 240, 255],
]
row0 = bytes(v for p in px[:4] for v in p)
row1 = bytes(v for p in px[4:] for v in p)
stride = 16

# filter 0 (None): raw rows as-is
png0 = build_png(4, 2, [bytes([0]) + row0, bytes([0]) + row1])

# filter 1 (Sub): first pixel raw, rest deltas from left
sub1 = bytearray(row0)
for i in range(stride - 4, -1, -4):
    for k in range(4):
        sub1[i + k] = (row0[i + k] - (row0[i - 4 + k] if i else 0)) & 0xFF
sub2 = bytearray(row1)
for i in range(stride - 4, 0, -4):
    for k in range(4):
        sub2[i + k] = (row1[i + k] - row1[i - 4 + k]) & 0xFF
png1 = build_png(4, 2, [bytes([1]) + bytes(sub1), bytes([1]) + bytes(sub2)])

# filter 2 (Up): row0 raw, row1 deltas from row0
png2 = build_png(4, 2, [bytes([0]) + row0,
                        bytes([2]) + bytes((a - b) & 0xFF for a, b in zip(row1, row0))])

# filter 3 (Average): row0 raw; row1 predictor uses the ORIGINAL left neighbor
# (reconstruction is sequential, so the decoded left pixel equals the source value).
avg = bytearray(row1)
for i in range(stride):
    left = row1[i - 4] if i >= 4 else 0
    avg[i] = (row1[i] - ((left + row0[i]) >> 1)) & 0xFF
png3 = build_png(4, 2, [bytes([0]) + row0, bytes([3]) + bytes(avg)])

# filter 4 (Paeth): row0 raw; row1 predictor uses the ORIGINAL left and
# up-left neighbors (a = reconstructed left = source, c = row0[i-4]).
def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c

pth = bytearray(row1)
for i in range(stride):
    a = row1[i - 4] if i >= 4 else 0
    c = row0[i - 4] if i >= 4 else 0
    pth[i] = (row1[i] - paeth(a, row0[i], c)) & 0xFF
png4 = build_png(4, 2, [bytes([0]) + row0, bytes([4]) + bytes(pth)])

want = bytes(v for p in (px[:4] + px[4:]) for v in p)

for name, blob in (("filter0", png0), ("filter1", png1), ("filter2", png2),
                   ("filter3", png3), ("filter4", png4)):
    tmp = os.path.join(HERE, "_tmp_pngread_%s.png" % name)
    with open(tmp, "wb") as f:
        f.write(blob)
    try:
        got, w, h = pngread.read_png_rgba(tmp)
        expect((w, h) == (4, 2), "%s dimensions" % name)
        expect(got == want, "%s exact pixels" % name)
    finally:
        os.remove(tmp)

# --- RGB expansion -----------------------------------------------------------------
rgb_row = bytes([1, 2, 3, 4, 5, 6])
png_rgb = build_png(2, 1, [bytes([0]) + rgb_row], color_type=2)
tmp = os.path.join(HERE, "_tmp_pngread_rgb.png")
with open(tmp, "wb") as f:
    f.write(png_rgb)
got, w, h = pngread.read_png_rgba(tmp)
os.remove(tmp)
expect((w, h) == (2, 1), "rgb dimensions")
expect(got == bytes([1, 2, 3, 255, 4, 5, 6, 255]), "rgb expands to RGBA alpha=255")

# --- grayscale expansion -------------------------------------------------------------
png_gray = build_png(2, 1, [bytes([0]) + bytes([7, 9])], color_type=0)
tmp = os.path.join(HERE, "_tmp_pngread_gray.png")
with open(tmp, "wb") as f:
    f.write(png_gray)
got, w, h = pngread.read_png_rgba(tmp)
os.remove(tmp)
expect(got == bytes([7, 7, 7, 255, 9, 9, 9, 255]), "grayscale expands to RGBA alpha=255")

# --- committed golden decodes with structural invariants ------------------------------
if os.path.exists(GOLDEN):
    got, w, h = pngread.read_png_rgba(GOLDEN)
    expect((w, h) == (256, 256), "golden is 256x256")
    vals = sorted(set(got))
    expect(len(vals) > 1, "golden is non-flat (%d distinct byte values)" % len(vals))
    head = open(GOLDEN, "rb").read(24)
    gw, gh = struct.unpack(">II", head[16:24])
    expect((gw, gh) == (w, h), "decoder dims match IHDR")
else:
    print("  SKIP golden not present: %s" % GOLDEN)

print()
if fails:
    print("PNGREAD FAIL (%d)" % len(fails))
    sys.exit(1)
print("PNGREAD PASS")

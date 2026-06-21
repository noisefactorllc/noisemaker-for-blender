"""Minimal dependency-free PNG writer (8-bit RGBA, top-down, no color management).

Bypasses bpy.types.Image.save (which applies the view transform / sRGB) so the bytes
stay raw-linear, matching the reference golden capture. arr is HxWx4 uint8, top-down.
"""
import zlib
import struct


def write_png(path, arr):
    h, w, _ = arr.shape
    raw = bytearray()
    rows = arr.tobytes()
    stride = w * 4
    for y in range(h):
        raw.append(0)  # filter type 0 (none)
        raw.extend(rows[y * stride:(y + 1) * stride])

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit, color type 6 (RGBA)
    idat = zlib.compress(bytes(raw), 6)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))

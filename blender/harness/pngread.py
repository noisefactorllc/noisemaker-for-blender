"""Minimal stdlib PNG reader for harness grading (RGBA uint8).

Exists so INVARIANT B (bake vs golden) can execute in Blender sessions whose
python lacks Pillow, instead of being skipped. Supports the formats the repo's
own goldens and pngio.write_png produce: 8-bit depth, color types 6 (RGBA),
2 (RGB) and 0 (grayscale), all five scanline filters. Anything else raises
ValueError rather than guessing.

No numpy and no third-party imports: runs in plain python3 and in Blender.
"""
import struct
import zlib


def read_png_rgba(path):
    """Decode a PNG file to (rows, cols, 4) uint8 RGBA, top-down.

    Grayscale and RGB sources are expanded to RGBA (alpha 255). Bit depth,
    palette, interlacing, and 16-bit data are not supported.
    """
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)

    width = height = depth = color = None
    idat = bytearray()
    pos = 8
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            interlace = body[12]
            if interlace != 0:
                raise ValueError("interlaced PNG unsupported: %s" % path)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length

    if None in (width, height, depth, color):
        raise ValueError("missing IHDR: %s" % path)
    if depth != 8:
        raise ValueError("unsupported bit depth %d: %s" % (depth, path))
    channels = {0: 1, 2: 3, 6: 4}.get(color)
    if channels is None:
        raise ValueError("unsupported color type %d: %s" % (color, path))

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    # Each scanline: 1 filter byte + stride bytes.
    if len(raw) != (stride + 1) * height:
        raise ValueError("truncated PNG data: %s" % path)

    out = bytearray(stride * height)
    prev = bytearray(stride)
    off = 0
    for y in range(height):
        ftype = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise ValueError("unsupported filter %d: %s" % (ftype, path))
        out[y * stride:(y + 1) * stride] = line
        prev = line

    if color == 6:
        rgba = out
    else:
        rgba = bytearray(width * height * 4)
        for y in range(height):
            src = y * stride
            dst = y * width * 4
            for x in range(width):
                if color == 0:
                    g = out[src + x]
                    rgba[dst + 4 * x:dst + 4 * x + 3] = bytes((g, g, g))
                else:  # RGB
                    rgba[dst + 4 * x:dst + 4 * x + 3] = out[src + 3 * x:src + 3 * x + 3]
                rgba[dst + 4 * x + 3] = 255
    return bytes(rgba), width, height

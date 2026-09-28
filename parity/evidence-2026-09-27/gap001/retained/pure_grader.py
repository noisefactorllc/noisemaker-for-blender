#!/usr/bin/env python3
"""Pure-stdlib grader matching parity/compare.py semantics (uint8 RGBA, 8-bit units).

Used only where the host python lacks numpy/PIL; this copy IS committed as the
record of how its reports were produced. Decodes 8-bit RGBA PNGs (all filter
types), computes max/mean abs diff over ALL four RGBA channels and the same
global SSIM as parity/compare.py, and writes a report JSON with the same
measure fields (max_abs_diff, mean_abs_diff, ssim, tolerance, ssim_min,
passed); it adds width/height and omits compare.py's "shape" convenience field.
"""
import json
import struct
import sys
import zlib


def decode_rgba(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", path
    pos = 8
    w = h = bd = ct = None
    idat = b""
    while pos < len(d):
        ln, typ = struct.unpack(">I4s", d[pos:pos + 8])
        chunk = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert bd == 8 and ct == 6, (path, bd, ct)
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b = prev[i]
                c = prev[i - 4] if i >= 4 else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, out


def main():
    golden, candidate, report = sys.argv[1], sys.argv[2], sys.argv[3]
    name = sys.argv[4] if len(sys.argv) > 4 else "case"
    tol = float(sys.argv[5]) if len(sys.argv) > 5 else 2.0
    w1, h1, a = decode_rgba(golden)
    w2, h2, b = decode_rgba(candidate)
    assert (w1, h1) == (w2, h2), "size mismatch"
    n = w1 * h1 * 4
    mx = 0
    tot = 0
    # global SSIM, exactly parity/compare.py: Rec.601 luma, single window
    sa = sb = saa = sbb = sab = 0.0
    for i in range(0, n, 4):
        for c in range(4):
            diff = a[i + c] - b[i + c]
            if diff < 0:
                diff = -diff
            if diff > mx:
                mx = diff
            tot += diff
        la = (0.299 * a[i] + 0.587 * a[i + 1] + 0.114 * a[i + 2]) / 255.0
        lb = (0.299 * b[i] + 0.587 * b[i + 1] + 0.114 * b[i + 2]) / 255.0
        sa += la
        sb += lb
        saa += la * la
        sbb += lb * lb
        sab += la * lb
    N = w1 * h1
    mean = tot / n
    mu_a, mu_b = sa / N, sb / N
    var_a = saa / N - mu_a * mu_a
    var_b = sbb / N - mu_b * mu_b
    cov = sab / N - mu_a * mu_b
    c1, c2 = 0.0001, 0.0009
    num = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    den = (mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2)
    ssim = num / den if den != 0 else 1.0
    passed = (mx <= tol) and (ssim >= 0.98)
    rep = {
        "name": name, "golden": golden, "candidate": candidate,
        "width": w1, "height": h1,
        "max_abs_diff": float(mx), "mean_abs_diff": mean,
        "ssim": ssim, "tolerance": tol, "ssim_min": 0.98, "passed": passed,
        "grader": "pure-stdlib mirror of parity/compare.py (uint8, 8-bit units)",
    }
    open(report, "w").write(json.dumps(rep, indent=1))
    print("[%s] %s: max-abs-diff=%.3f mean-abs-diff=%.4f ssim=%.5f (tol=%s)" % (
        "PASS" if passed else "FAIL", name, mx, mean, ssim, tol))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

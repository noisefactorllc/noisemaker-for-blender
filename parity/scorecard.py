#!/usr/bin/env python3
"""scorecard.py — grade every <name>.golden.png / <name>.candidate.png pair in parity/out and
print a sorted parity scorecard (ssim, max-abs-diff, mean-abs-diff). Continuous/stateful programs
aren't byte-identical cross-engine; ssim is the structural gate. Run with Blender's python
(has numpy; pip install pillow). Usage: scorecard.py [prefix]  (default prefix 'c_' for corpus)."""
import glob
import os
import sys

import numpy as np
from PIL import Image


def load(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0


def ssim(a, b):
    def luma(x):
        return 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    la, lb = luma(a).ravel(), luma(b).ravel()
    ma, mb = la.mean(), lb.mean()
    va, vb = la.var(), lb.var()
    cov = ((la - ma) * (lb - mb)).mean()
    c1, c2 = 1e-4, 9e-4
    return float(((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma**2 + mb**2 + c1) * (va + vb + c2)))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    prefix = sys.argv[1] if len(sys.argv) > 1 else "c_"
    out = os.path.join(here, "out")
    rows = []
    for g in sorted(glob.glob(os.path.join(out, prefix + "*.golden.png"))):
        name = os.path.basename(g)[:-len(".golden.png")]
        cand = os.path.join(out, name + ".candidate.png")
        if not os.path.exists(cand):
            rows.append((name, None, None, None, "NO CANDIDATE"))
            continue
        a, b = load(g), load(cand)
        if a.shape != b.shape:
            rows.append((name, None, None, None, "SHAPE %s vs %s" % (a.shape, b.shape)))
            continue
        s = ssim(a, b)
        mx = float(np.max(np.abs(a - b)) * 255)
        mn = float(np.mean(np.abs(a - b)) * 255)
        rows.append((name, s, mx, mn, ""))
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    print("%-16s %8s %8s %9s  %s" % ("program", "ssim", "maxdiff", "meandiff", "note"))
    print("-" * 60)
    graded = [r for r in rows if r[1] is not None]
    for name, s, mx, mn, note in rows:
        if s is None:
            print("%-16s %8s %8s %9s  %s" % (name, "-", "-", "-", note))
        else:
            print("%-16s %8.4f %8.1f %9.3f  %s" % (name, s, mx, mn, note))
    if graded:
        ss = [r[1] for r in graded]
        print("-" * 60)
        print("graded %d | ssim mean %.4f median %.4f | >=0.9: %d  >=0.99: %d  byte(<2 maxdiff): %d"
              % (len(graded), float(np.mean(ss)), float(np.median(ss)),
                 sum(s >= 0.9 for s in ss), sum(s >= 0.99 for s in ss),
                 sum(r[2] < 2 for r in graded)))


if __name__ == "__main__":
    main()

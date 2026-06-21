#!/usr/bin/env python3
"""batch-compare.py — compare every golden against its candidate and classify.

Usage: python3 batch-compare.py <goldDir> <candDir> [--out report.json]
  goldDir holds <name>.golden.png ; candDir holds <name>.png
  Classifies each: PASS (max-abs-diff <= 2 AND ssim >= 0.98),
                   NEAR (ssim >= 0.98 but max-abs-diff > 2),
                   FAIL (ssim < 0.98),
                   MISSING (golden or candidate absent).
Prints measured numbers per effect and a summary. Never fabricates.
"""
import sys, json, argparse
from pathlib import Path
import numpy as np
from PIL import Image


def load_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0


def global_ssim(a, b):
    ya = a[..., :3].mean(axis=2)
    yb = b[..., :3].mean(axis=2)
    mu_a, mu_b = ya.mean(), yb.mean()
    va, vb = ya.var(), yb.var()
    cov = ((ya - mu_a) * (yb - mu_b)).mean()
    c1 = (0.01) ** 2
    c2 = (0.03) ** 2
    return float(((2 * mu_a * mu_b + c1) * (2 * cov + c2)) /
                 ((mu_a ** 2 + mu_b ** 2 + c1) * (va + vb + c2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("goldDir", type=Path)
    ap.add_argument("candDir", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--tolerance", type=float, default=2.0)
    ap.add_argument("--ssim-min", type=float, default=0.98)
    args = ap.parse_args()

    goldens = sorted(args.goldDir.glob("*.golden.png"))
    results = []
    for g in goldens:
        name = g.name[:-len(".golden.png")]
        cand = args.candDir / f"{name}.png"
        rec = {"name": name}
        if not cand.exists():
            rec.update(cls="MISSING_CAND", max_abs_diff=None, ssim=None)
            results.append(rec)
            continue
        a = load_rgba(g)
        b = load_rgba(cand)
        if a.shape != b.shape:
            rec.update(cls="SIZE_MISMATCH", gshape=list(a.shape), cshape=list(b.shape),
                       max_abs_diff=None, ssim=None)
            results.append(rec)
            continue
        mad = float(np.max(np.abs(a - b)) * 255.0)
        mean = float(np.mean(np.abs(a - b)) * 255.0)
        ssim = global_ssim(a, b)
        if mad <= args.tolerance and ssim >= args.ssim_min:
            cls = "PASS"
        elif ssim >= args.ssim_min:
            cls = "NEAR"
        else:
            cls = "FAIL"
        rec.update(cls=cls, max_abs_diff=round(mad, 3), mean_abs_diff=round(mean, 4),
                   ssim=round(ssim, 5))
        results.append(rec)

    # candidates without goldens
    cand_names = {p.name[:-4] for p in args.candDir.glob("*.png")}
    gold_names = {g.name[:-len(".golden.png")] for g in goldens}
    for cn in sorted(cand_names - gold_names):
        results.append({"name": cn, "cls": "MISSING_GOLD", "max_abs_diff": None, "ssim": None})

    order = {"FAIL": 0, "SIZE_MISMATCH": 1, "MISSING_CAND": 2, "MISSING_GOLD": 3, "NEAR": 4, "PASS": 5}
    results.sort(key=lambda r: (order.get(r["cls"], 9), r["name"]))

    from collections import Counter
    counts = Counter(r["cls"] for r in results)
    for r in results:
        if r["cls"] in ("PASS",):
            continue
        print(f"[{r['cls']:>13}] {r['name']:<40} mad={r.get('max_abs_diff')} ssim={r.get('ssim')}")
    print("\n=== SUMMARY ===")
    print(f"total compared: {len(results)}")
    for k in ("PASS", "NEAR", "FAIL", "SIZE_MISMATCH", "MISSING_CAND", "MISSING_GOLD"):
        if counts.get(k):
            print(f"  {k}: {counts[k]}")
    if args.out:
        args.out.write_text(json.dumps({"counts": dict(counts), "results": results}, indent=2) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""check_parse.py — parser parity gate.

Runs the ported Python lexer + parser (noisemaker_blender.compiler) on every
parity/corpus/*.dsl and compares the resulting AST against the golden
parity/out/<name>.ast.json (produced by the REFERENCE JS parser via tools/dump-ast.mjs).

Comparison is STRUCTURAL: both sides are loaded via json.load and compared as Python
objects. Dict comparison is order-insensitive over keys (so JSON key ordering never causes a
false negative); list comparison is order-SENSITIVE (so real ordering differences fail). This
also makes JS-number vs Python-int/float a non-issue (30 == 30.0 in Python). On mismatch the
program name and the FIRST/most-specific differing path are printed. Ends with
`parser parity: N/20`. Exits non-zero unless all programs match.

Plain ``python3`` is fine — stdlib only.
"""
import glob
import json
import os
import sys

# --- locate dirs and wire up the addon import root (mirrors check_lex.py) ------------------
HERE = os.path.dirname(os.path.abspath(__file__))            # parity/compiler
PARITY = os.path.dirname(HERE)                               # parity
ROOT = os.path.dirname(PARITY)                               # repo root (noisemaker-blender)
ADDON = os.path.join(ROOT, "blender", "noisemaker_blender")  # addon package dir
sys.path.insert(0, os.path.dirname(ADDON))                   # .../blender (parent of package)

from noisemaker_blender.compiler.lexer import lex            # noqa: E402
from noisemaker_blender.compiler.parser import parse         # noqa: E402

CORPUS = os.path.join(PARITY, "corpus")
OUT = os.path.join(PARITY, "out")


def diff_path(expected, got, path="$"):
    """Return a human-readable description of the first structural/value difference.

    Dicts: order-insensitive over keys (compare key sets, then recurse per key).
    Lists: order-sensitive (compare length, then recurse per index).
    Scalars: compared with ==, but treat int/float of equal value as equal (matches the
    reference, where every Number is a JS double).
    Returns None when the two values are structurally equal.
    """
    # Numeric equality: 30 (int) == 30.0 (float), and bool is NOT numeric here (keep
    # True != 1 strict, since the AST distinguishes Boolean nodes from Number nodes anyway).
    e_num = isinstance(expected, (int, float)) and not isinstance(expected, bool)
    g_num = isinstance(got, (int, float)) and not isinstance(got, bool)
    if e_num and g_num:
        if expected == got:
            return None
        return "%s: expected %r, got %r" % (path, expected, got)

    if type(expected) is not type(got):
        # Allow the numeric case handled above; everything else is a type mismatch.
        return "%s: type mismatch — expected %s (%r), got %s (%r)" % (
            path, type(expected).__name__, expected, type(got).__name__, got
        )

    if isinstance(expected, dict):
        e_keys = set(expected.keys())
        g_keys = set(got.keys())
        if e_keys != g_keys:
            missing = sorted(e_keys - g_keys)
            extra = sorted(g_keys - e_keys)
            return "%s: key mismatch — missing %s, extra %s" % (path, missing, extra)
        # Recurse in the expected key order for stable, readable output.
        for k in expected.keys():
            sub = diff_path(expected[k], got[k], "%s.%s" % (path, k))
            if sub is not None:
                return sub
        return None

    if isinstance(expected, list):
        if len(expected) != len(got):
            return "%s: list length mismatch — expected %d, got %d" % (
                path, len(expected), len(got)
            )
        for i in range(len(expected)):
            sub = diff_path(expected[i], got[i], "%s[%d]" % (path, i))
            if sub is not None:
                return sub
        return None

    if expected == got:
        return None
    return "%s: expected %r, got %r" % (path, expected, got)


def main():
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*.dsl")))
    if not corpus_files:
        print("no corpus .dsl files found under %s" % CORPUS)
        return 1

    passed = 0
    total = len(corpus_files)
    for path in corpus_files:
        name = os.path.basename(path)[: -len(".dsl")]
        golden_path = os.path.join(OUT, name + ".ast.json")
        if not os.path.exists(golden_path):
            print("FAIL %-10s  (no golden: %s)" % (name, golden_path))
            continue

        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        with open(golden_path, "r", encoding="utf-8") as fh:
            expected = json.load(fh)

        try:
            got = parse(lex(src))
        except Exception as exc:  # noqa: BLE001 - report parser crash as a failure
            print("FAIL %-10s  (parser raised: %s: %s)" % (name, type(exc).__name__, exc))
            continue

        # Round-trip through JSON so the candidate is plain dict/list/str/num/bool/None,
        # exactly like the golden — no tuples, no custom types leaking into the compare.
        got = json.loads(json.dumps(got))

        d = diff_path(expected, got)
        if d is None:
            print("PASS %-10s" % name)
            passed += 1
        else:
            print("FAIL %-10s" % name)
            print("       program: %s" % path)
            print("       diff: %s" % d)

    print("parser parity: %d/%d" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

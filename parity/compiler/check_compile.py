#!/usr/bin/env python3
"""check_compile.py — Stage-1 (compile) parity gate.

Runs the ported Python ``compile(source)`` (noisemaker_blender.compiler) — i.e.
lex -> parse -> validate — on every parity/corpus/*.dsl and compares the result
against the golden parity/out/<name>.compile.json (the REFERENCE JS
``compile(source)`` output, including its ``diagnostics``: warnings AND errors).

Comparison is STRUCTURAL (same rules as check_parse.py): both sides are loaded as
plain Python objects. Dict comparison is order-insensitive over keys; list
comparison is order-SENSITIVE; int/float of equal value compare equal (every JS
Number is a double). On mismatch the program name and the FIRST/most-specific
differing path are printed. Ends with ``compile parity: N/20``. Exits non-zero
unless all programs match.

Plain ``python3`` is fine — stdlib only.
"""
import glob
import json
import os
import sys

# --- locate dirs and wire up the addon import root (mirrors check_parse.py) ----
HERE = os.path.dirname(os.path.abspath(__file__))            # parity/compiler
PARITY = os.path.dirname(HERE)                               # parity
ROOT = os.path.dirname(PARITY)                               # repo root (noisemaker-for-blender)
ADDON = os.path.join(ROOT, "blender", "noisemaker_blender")  # addon package dir
sys.path.insert(0, os.path.dirname(ADDON))                   # .../blender (parent of package)

from noisemaker_blender.compiler.compile import compile      # noqa: E402

CORPUS = os.path.join(PARITY, "corpus")
OUT = os.path.join(PARITY, "out")


def diff_path(expected, got, path="$"):
    """First structural/value difference, or None when structurally equal.

    Dicts: order-insensitive over keys. Lists: order-sensitive. Scalars: ==,
    treating int/float of equal value as equal (bool stays strict, since the
    validated output distinguishes Boolean nodes/values from Numbers).
    """
    e_num = isinstance(expected, (int, float)) and not isinstance(expected, bool)
    g_num = isinstance(got, (int, float)) and not isinstance(got, bool)
    if e_num and g_num:
        if expected == got:
            return None
        return "%s: expected %r, got %r" % (path, expected, got)

    if type(expected) is not type(got):
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
        golden_path = os.path.join(OUT, name + ".compile.json")
        if not os.path.exists(golden_path):
            print("FAIL %-10s  (no golden: %s)" % (name, golden_path))
            continue

        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        with open(golden_path, "r", encoding="utf-8") as fh:
            expected = json.load(fh)

        try:
            got = compile(src)
        except Exception as exc:  # noqa: BLE001 - report a compile crash as a failure
            print("FAIL %-10s  (compile raised: %s: %s)" % (name, type(exc).__name__, exc))
            continue

        # Round-trip through JSON so the candidate is plain dict/list/str/num/bool/None,
        # exactly like the golden — mirrors how JS JSON.stringify produced the golden
        # (functions dropped, undefined keys omitted).
        got = json.loads(json.dumps(got))

        d = diff_path(expected, got)
        if d is None:
            print("PASS %-10s" % name)
            passed += 1
        else:
            print("FAIL %-10s" % name)
            print("       program: %s" % path)
            print("       diff: %s" % d)

    print("compile parity: %d/%d" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

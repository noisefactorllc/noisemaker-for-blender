#!/usr/bin/env python3
"""check_lex.py — lexer parity gate.

Runs the ported Python lexer (noisemaker_blender.compiler.lexer.lex) on every
parity/corpus/*.dsl and compares its token stream against the golden
parity/out/<name>.tokens.json (produced by the REFERENCE JS lexer via
tools/dump-tokens.mjs). Prints per-program PASS/FAIL and, on the first failure,
the FIRST differing token (index, expected vs got). Ends with `lexer parity: N/20`.

Plain ``python3`` is fine — stdlib only. Exits non-zero unless all programs match.
"""
import glob
import json
import os
import sys

# --- locate dirs and wire up the addon import root (mirrors blender/harness/render_all.py
#     and parity/scorecard.py: addon package dir is .../blender/noisemaker_blender, and we
#     insert its PARENT so `import noisemaker_blender...` resolves). -------------------------
HERE = os.path.dirname(os.path.abspath(__file__))            # parity/compiler
PARITY = os.path.dirname(HERE)                               # parity
ROOT = os.path.dirname(PARITY)                               # repo root (noisemaker-for-blender)
ADDON = os.path.join(ROOT, "blender", "noisemaker_blender")  # addon package dir
sys.path.insert(0, os.path.dirname(ADDON))                   # .../blender (parent of package)

from noisemaker_blender.compiler.lexer import lex            # noqa: E402

CORPUS = os.path.join(PARITY, "corpus")
OUT = os.path.join(PARITY, "out")

# Field order of a golden token object. We compare these exactly (semantic equality of the
# token, independent of JSON whitespace — the JS golden is compact, Python's json.dumps is not,
# but the token data is the contract).
FIELDS = ("type", "lexeme", "line", "col")


def first_diff(expected, got):
    """Return (index, exp_token_or_None, got_token_or_None) of the first mismatch, or None."""
    m = max(len(expected), len(got))
    for k in range(m):
        e = expected[k] if k < len(expected) else None
        g = got[k] if k < len(got) else None
        if e is None or g is None:
            return (k, e, g)
        if any(e.get(f) != g.get(f) for f in FIELDS):
            return (k, e, g)
    return None


def norm(tok):
    """Project a token dict to just the golden fields (drop any extras, ignore key order)."""
    return {f: tok.get(f) for f in FIELDS}


def main():
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*.dsl")))
    if not corpus_files:
        print("no corpus .dsl files found under %s" % CORPUS)
        return 1

    passed = 0
    total = len(corpus_files)
    for path in corpus_files:
        name = os.path.basename(path)[: -len(".dsl")]
        golden_path = os.path.join(OUT, name + ".tokens.json")
        if not os.path.exists(golden_path):
            print("FAIL %-10s  (no golden: %s)" % (name, golden_path))
            continue

        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        with open(golden_path, "r", encoding="utf-8") as fh:
            expected = [norm(t) for t in json.load(fh)]

        try:
            got = [norm(t) for t in lex(src)]
        except Exception as exc:  # noqa: BLE001 - report lexer crash as a failure
            print("FAIL %-10s  (lexer raised: %s: %s)" % (name, type(exc).__name__, exc))
            continue

        diff = first_diff(expected, got)
        if diff is None:
            print("PASS %-10s  (%d tokens)" % (name, len(got)))
            passed += 1
        else:
            idx, e, g = diff
            print("FAIL %-10s  first diff at token #%d" % (name, idx))
            print("       expected: %s" % json.dumps(e, sort_keys=True))
            print("       got:      %s" % json.dumps(g, sort_keys=True))

    print("lexer parity: %d/%d" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""check_graph.py -- Stage-3 (graph assembly) parity gate. THE TARGET.

Runs the ported Python ``compile_graph(source)`` (noisemaker_blender.compiler) --
the full ``compile`` -> ``expand`` -> resource-allocation -> assembly pipeline,
NORMALIZED to the golden shape -- on every parity/corpus/*.dsl and compares the
result against the golden parity/out/<name>.graph.json. That golden is produced
by ``tools/export-graph.mjs`` running the UNCHANGED reference engine's
``compileGraph`` and then normalizing the result (strip id/source/compiledAt from
the serialized program source, promote compile-time define globals into
``defines``, etc.). ``compile_graph`` replicates that complete shaping, so its
output is the SAME normalized graph object -- the milestone: the addon can now
produce render graphs with NO external reference.

B5oBsA has compile-time errors (no graph golden) and is EXCLUDED; we also assert
that ``compile_graph`` ABORTS on it (raises) like the reference ``compileGraph``
throws on ERR_COMPILATION_FAILED. The other 19 corpus programs must match.

Comparison is STRUCTURAL (same rules as check_expanded.py): both sides are loaded
as plain Python objects. Dict comparison is order-insensitive over keys; list
comparison is order-SENSITIVE; int/float of equal value compare equal (every JS
Number is a double; bool stays strict). On mismatch the program name and the
FIRST/most-specific differing path are printed. Ends with ``graph parity: N/19``.
Exits non-zero unless all (non-excluded) programs match.

Plain ``python3`` is fine -- stdlib only.
"""
import glob
import json
import os
import sys

# --- locate dirs and wire up the addon import root (mirrors check_expanded.py) -
HERE = os.path.dirname(os.path.abspath(__file__))            # parity/compiler
PARITY = os.path.dirname(HERE)                               # parity
ROOT = os.path.dirname(PARITY)                               # repo root (noisemaker-blender)
ADDON = os.path.join(ROOT, "blender", "noisemaker_blender")  # addon package dir
sys.path.insert(0, os.path.dirname(ADDON))                   # .../blender (parent of package)

from noisemaker_blender.compiler.compiler import (            # noqa: E402
    compile_graph,
    CompilationError,
    ExpansionError,
)

CORPUS = os.path.join(PARITY, "corpus")
OUT = os.path.join(PARITY, "out")

# Excluded: compile-time errors mean there is no graph golden. We still assert
# that compile_graph raises/aborts on it (the reference compileGraph throws).
EXCLUDE = {"B5oBsA"}


def diff_path(expected, got, path="$"):
    """First structural/value difference, or None when structurally equal.

    Dicts: order-insensitive over keys. Lists: order-sensitive. Scalars: ==,
    treating int/float of equal value as equal; bool stays strict.
    """
    e_num = isinstance(expected, (int, float)) and not isinstance(expected, bool)
    g_num = isinstance(got, (int, float)) and not isinstance(got, bool)
    if e_num and g_num:
        if expected == got:
            return None
        return "%s: expected %r, got %r" % (path, expected, got)

    if type(expected) is not type(got):
        return "%s: type mismatch -- expected %s (%r), got %s (%r)" % (
            path, type(expected).__name__, expected, type(got).__name__, got
        )

    if isinstance(expected, dict):
        e_keys = set(expected.keys())
        g_keys = set(got.keys())
        if e_keys != g_keys:
            missing = sorted(e_keys - g_keys)
            extra = sorted(g_keys - e_keys)
            return "%s: key mismatch -- missing %s, extra %s" % (path, missing, extra)
        for k in expected.keys():
            sub = diff_path(expected[k], got[k], "%s.%s" % (path, k))
            if sub is not None:
                return sub
        return None

    if isinstance(expected, list):
        if len(expected) != len(got):
            return "%s: list length mismatch -- expected %d, got %d" % (
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


def check_excluded_aborts():
    """Assert each EXCLUDEd program makes compile_graph raise (mirrors the
    reference ``compileGraph`` throw on ERR_COMPILATION_FAILED)."""
    all_ok = True
    for name in sorted(EXCLUDE):
        path = os.path.join(CORPUS, name + ".dsl")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        try:
            compile_graph(src)
        except (CompilationError, ExpansionError) as exc:
            print("PASS %-10s  (correctly aborts: %s)" % (name, type(exc).__name__))
        except Exception as exc:  # noqa: BLE001 - any abort is acceptable here
            print("PASS %-10s  (aborts: %s: %s)" % (name, type(exc).__name__, exc))
        else:
            print("FAIL %-10s  (compile_graph did NOT raise -- expected abort)" % name)
            all_ok = False
    return all_ok


def main():
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*.dsl")))
    if not corpus_files:
        print("no corpus .dsl files found under %s" % CORPUS)
        return 1

    aborts_ok = check_excluded_aborts()

    passed = 0
    total = 0
    for path in corpus_files:
        name = os.path.basename(path)[: -len(".dsl")]
        if name in EXCLUDE:
            continue
        total += 1
        golden_path = os.path.join(OUT, name + ".graph.json")
        if not os.path.exists(golden_path):
            print("FAIL %-10s  (no golden: %s)" % (name, golden_path))
            continue

        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        with open(golden_path, "r", encoding="utf-8") as fh:
            expected = json.load(fh)

        try:
            got = compile_graph(src)
        except Exception as exc:  # noqa: BLE001 - report a compile_graph crash as a failure
            print("FAIL %-10s  (compile_graph raised: %s: %s)" % (name, type(exc).__name__, exc))
            continue

        # Round-trip through JSON so the candidate is plain dict/list/str/num/bool/None,
        # exactly like the golden -- mirrors how JS JSON.stringify produced the golden.
        got = json.loads(json.dumps(got))

        d = diff_path(expected, got)
        if d is None:
            print("PASS %-10s" % name)
            passed += 1
        else:
            print("FAIL %-10s" % name)
            print("       program: %s" % path)
            print("       diff: %s" % d)

    print("graph parity: %d/%d" % (passed, total))
    return 0 if (passed == total and aborts_ok) else 1


if __name__ == "__main__":
    sys.exit(main())

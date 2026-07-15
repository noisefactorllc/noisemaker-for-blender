#!/usr/bin/env python3
"""check_expanded.py -- Stage-2 (expand) parity gate.

Runs the ported Python ``expand(compile(source))`` (noisemaker_blender.compiler)
on every parity/corpus/*.dsl and compares the result against the golden
parity/out/<name>.expanded.json -- the REFERENCE JS
``expand(compile(source), {shaderOverrides})`` output
``{passes, programs, textureSpecs, renderSurface}``.

B5oBsA has compile-time errors (no expanded golden) and is EXCLUDED; the other
19 corpus programs must match.

Comparison is STRUCTURAL (same rules as check_compile.py): both sides are loaded
as plain Python objects. Dict comparison is order-insensitive over keys; list
comparison is order-SENSITIVE; int/float of equal value compare equal (every JS
Number is a double; bool stays strict). On mismatch the program name and the
FIRST/most-specific differing path are printed. Ends with
``expander parity: N/19``. Exits non-zero unless all (non-excluded) match.

The golden was produced by JSON.stringify of the reference ``expand()`` output,
so it contains exactly ``{passes, programs, textureSpecs, renderSurface}`` (the
``errors`` field the reference also returns is dropped here before comparing,
since it isn't in the golden and is empty for every clean program).

Plain ``python3`` is fine -- stdlib only.
"""
import glob
import json
import os
import sys

# --- locate dirs and wire up the addon import root (mirrors check_compile.py) --
HERE = os.path.dirname(os.path.abspath(__file__))            # parity/compiler
PARITY = os.path.dirname(HERE)                               # parity
ROOT = os.path.dirname(PARITY)                               # repo root (noisemaker-for-blender)
ADDON = os.path.join(ROOT, "blender", "noisemaker_blender")  # addon package dir
sys.path.insert(0, os.path.dirname(ADDON))                   # .../blender (parent of package)

from noisemaker_blender.compiler.compile import compile      # noqa: E402
from noisemaker_blender.compiler.expander import expand       # noqa: E402

CORPUS = os.path.join(PARITY, "corpus")
OUT = os.path.join(PARITY, "out")

# Excluded: compile-time errors mean there is no expanded golden.
EXCLUDE = {"B5oBsA"}

# Keys present in the reference expand() return but NOT serialized into the
# golden (the golden is {passes, programs, textureSpecs, renderSurface}).
GOLDEN_KEYS = ("passes", "programs", "textureSpecs", "renderSurface")


def normalize_programs(programs):
    """Mirror tools/dump-expanded.mjs ``normalizePrograms``.

    The golden strips shader SOURCE from every program, keeping only
    ``{uniformLayout: prog.uniformLayout || null, defines: prog.defines || {}}``
    (source is ported separately as .frag files). The ported ``expand()`` is a
    faithful port that returns FULL programs (e.g. ``blit`` with its
    fragment/wgsl source), so we apply the SAME normalization to the candidate
    before comparing -- this keeps ``expand()`` itself byte-faithful to the
    reference while the gate accounts for the golden's known post-processing.

    ``x || null`` / ``x || {}`` use JS truthiness: a missing key, ``None``, or an
    empty dict ``{}`` all fall through to the default.
    """
    out = {}
    for prog_id, prog in (programs or {}).items():
        layout = prog.get("uniformLayout") if isinstance(prog, dict) else None
        defines = prog.get("defines") if isinstance(prog, dict) else None
        out[prog_id] = {
            "uniformLayout": layout if layout else None,
            "defines": defines if defines else {},
        }
    return out


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


def main():
    corpus_files = sorted(glob.glob(os.path.join(CORPUS, "*.dsl")))
    if not corpus_files:
        print("no corpus .dsl files found under %s" % CORPUS)
        return 1

    passed = 0
    total = 0
    for path in corpus_files:
        name = os.path.basename(path)[: -len(".dsl")]
        if name in EXCLUDE:
            continue
        total += 1
        golden_path = os.path.join(OUT, name + ".expanded.json")
        if not os.path.exists(golden_path):
            print("FAIL %-10s  (no golden: %s)" % (name, golden_path))
            continue

        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        with open(golden_path, "r", encoding="utf-8") as fh:
            expected = json.load(fh)

        try:
            got = expand(compile(src))
        except Exception as exc:  # noqa: BLE001 - report an expand crash as a failure
            print("FAIL %-10s  (expand raised: %s: %s)" % (name, type(exc).__name__, exc))
            continue

        # Keep only the keys the golden serializes; the reference also returns
        # ``errors`` (empty here) which is not in the golden. Normalize the
        # candidate's programs the same way the golden was dumped (source
        # stripped to {uniformLayout, defines}).
        got = {k: got[k] for k in GOLDEN_KEYS if k in got}
        if "programs" in got:
            got["programs"] = normalize_programs(got["programs"])

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

    print("expander parity: %d/%d" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

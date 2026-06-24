#!/usr/bin/env bash
# Regenerate the compiler-parity goldens that the in-Blender DSL compiler is checked against:
#   parity/out/<name>.{tokens,ast,compile,expanded,graph}.json
# for every parity/corpus/*.dsl, produced by the REFERENCE JS compiler (tools/dump-*.mjs +
# export-graph.mjs). parity/out/ is git-ignored, so on a fresh clone you MUST run this once before
# the compiler gates (parity/compiler/check_{lex,parse,compile,expanded,graph}.py) — otherwise they
# find no goldens and pass vacuously.
#
#   NM_REFERENCE_ROOT=../noisemaker bash parity/regen-compiler-goldens.sh
#
# B5oBsA has compile-time errors, so its compile/expanded/graph dumps fail and leave no golden
# (the gates EXCLUDE/skip it); its tokens/ast goldens are still written (it lexes + parses fine).
set -u
cd "$(dirname "$0")/.." || exit 1                       # repo root
ROOT="${NM_REFERENCE_ROOT:-../noisemaker}"
export NM_REFERENCE_ROOT="$ROOT"
if [ ! -d "$ROOT/shaders" ]; then
  echo "NM_REFERENCE_ROOT='$ROOT' is not the reference engine (no shaders/ dir). Set it and retry." >&2
  exit 1
fi
mkdir -p parity/out
n=0
for f in parity/corpus/*.dsl; do
  name="$(basename "$f" .dsl)"; n=$((n + 1))
  # tokens + ast: every program (incl. B5oBsA) lexes + parses.
  node tools/dump-tokens.mjs "$f"   > "parity/out/$name.tokens.json"   2>/dev/null || rm -f "parity/out/$name.tokens.json"
  node tools/dump-ast.mjs    "$f"   > "parity/out/$name.ast.json"      2>/dev/null || rm -f "parity/out/$name.ast.json"
  # compile/expanded/graph: B5oBsA fails here on purpose -> no golden, gate excludes it.
  node tools/dump-compile.mjs  "$f" > "parity/out/$name.compile.json"  2>/dev/null || rm -f "parity/out/$name.compile.json"
  node tools/dump-expanded.mjs "$f" > "parity/out/$name.expanded.json" 2>/dev/null || rm -f "parity/out/$name.expanded.json"
  node tools/export-graph.mjs --file "$f" "parity/out/$name.graph.json" >/dev/null 2>&1 || rm -f "parity/out/$name.graph.json"
  echo "  $name"
done
echo "regenerated compiler goldens for $n corpus programs -> parity/out/ (B5oBsA compile/expanded/graph intentionally absent)"

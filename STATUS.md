# Noisemaker for Blender — status & parity

*Verified on Apple Silicon / Metal. The sources of truth are `parity/integration.sh`,
`parity/compare.py`, and `parity/compiler/check_*.py`. Crystallized against reference (noisemaker)
content **pinned at commit 75507112** ("Add CPU Composer link to index footer"). Upstream's
artistic-filter batch lives in a single commit that is rebased/amended in place (unstable SHA), so
this round re-verified by diffing tree CONTENT against a pinned snapshot of that commit, not by
commit-range history — the prior sync SHAs (a27bf823/b7c1bc36/36e7f3f5) are off the mainline.*

*Incrementally synced 2026-07-23 to reference `349e9909` — `filter/pondRipples` gained a `speed`
control, the only port-affecting change in that range. pondRipples re-graded 7 PASS / 1 NEAR
(`pondRipples_aroundCenter`, pre-existing: its candidate is byte-identical before and after this
change), plus two new animated fixtures. The catalogue-wide numbers below are still the `75507112`
figures; only pondRipples was re-rendered.*

*Incrementally synced 2026-09-15 to reference `0ed489ec4684` (`246ff57f43cc..0ed489ec4684`) — 3 new
effects (`synth3d/heightmap3d`, `render/renderLandscape3d`, `points/heightGrid`) and content changes
to `render/pointsRender` + `render/pointsBillboardRender` (new `perspective` view mode; billboard
render additionally gained depth-sorted alpha blending and aperture defocus), `synth/remap` (267 →
275 UBO slots), and `synth/media` (alpha-sampling fix). Defs + shaders regenerated via
`convert-defs-blender.mjs` / `convert-shaders-blender.mjs`; the DSL compiler (`compiler/expander.py`,
`compiler/compiler.py`) needed 3 real fixes to reach this round's new per-pass-defines/conditions
pattern (pointsRender/pointsBillboardRender's viewMode-split deposit draws) — see PORTING-GUIDE.md's
"This round's compiler fixes". **Verified: `parity/compiler/check_{lex,parse,compile,expanded,graph}.py`
all pass (19-20/20; `B5oBsA` is an intentional compile-error exclusion), plus every non-Blender-GUI
`parity/test_*.py`.** These do not need Blender.

**Full Blender-GUI verification (2026-09-15, a second session with real Metal access):** two real
bugs found and fixed (commit `a0e7a97`) — `std140.py`'s `rename_shadow_builtins()` mishandled a
`for`-loop header's own paren scope, breaking `pointsBillboardRender/depthMerge.frag` and
`renderLandscape3d/landscape.frag` (both shadow the builtin `step()` in a `for` condition/increment);
and `blender/harness/compile_check.py`'s `default_defines()` didn't know about this round's
per-pass-defines pattern, producing 3 false "FAIL"s on the viewMode-split deposit/depthKeys programs
(confirmed harness-only by rendering through the real pipeline first, then fixed to fall back to the
first pass whose `program` carries a `defines` block). Full-corpus `compile_check.py`: 310/312 (was
305/312 before this round; +7 is this round's new shaders; the remaining 2 are the known
`scope`/`spectrum` audio exclusions — no regressions). Render + parity via `render_all.py` +
`export-and-render.mjs` against reference `0ed489ec4684`, all 4 new fixtures: `heightGrid_billboard`
PASS, `heightGrid_billboard_alpha` PASS, `heightmap3d_landscape` PASS (1/65536 pixels at diff=3 vs
tol=2, ULP-class, ssim=1.0), `heightGrid_pointsRender_perspective` PASS at `NM_FRAMES=8` (matches
export-and-render.mjs's 8-frame settle protocol — `render/pointsRender`'s deposit pass is additive
with no per-pass clear, so a `render_all.py` default of `NM_FRAMES=1` under-accumulates relative to
the golden for any points-namespace fixture; not a port bug, just a frame-count mismatch between the
two harnesses). No open issues from this round.

*Incrementally synced 2026-09-17 to reference `688c514655d3` (`5a14256732b5..688c514655d3`) — audited upstream WebGPU frame export row-orientation fix (`5ceb97ba` and `688c5146`); confirmed inapplicable to Blender (Blender PyGPU runs via GLSL/MSL framebuffer readback). Compiler goldens regenerated and verified: `parity/compiler/check_{lex,parse,compile,expanded,graph}.py` all pass (20/20 lex/parse/compile, 19/19 expand/graph with `B5oBsA` compile-error exclusion), and 84/84 parity unit tests pass.*

*Incrementally synced 2026-09-18 to reference `ead42a5df110` (`688c514655d3..ead42a5df110`) — ported starter position check in `compiler/transform.py` (`replace_effect`, `list_steps`, `get_compatible_replacements`) to correctly recognize inline surface producers (starter effects with no pipeline predecessor flattened into the chain). Updated `defaultProgram` in `effects/synth3d/heightmap3d.json` and `effects/render/renderLandscape3d.json` as well as `parity/programs/heightmap3d_landscape.dsl` to separate write/read chains format matching upstream. Added unit tests in `parity/test_transform.py`. Verified: `parity/compiler/check_{lex,parse,compile,expanded,graph}.py` all pass (20/20 lex/parse/compile, 19/19 expand/graph with `B5oBsA` compile-error exclusion), and 88/88 parity unit tests pass.*

This file holds the detailed coverage and parity numbers. For what the project is and how to use it,
see the [README](README.md).

## Coverage

**213 effect definitions** across 8 namespaces (was 210 — see the 2026-09-15 sync note above for
the +3 new effects and the def/shader regeneration). **301 / 303 shader programs compile on Metal**
— the whole catalog except the two audio synths `scope` / `spectrum` (audio input is out of scope)
— **as of the 75507112 crystallization; the 2026-09-15 sync's def/shader changes are not yet
Metal-compile-verified** (would need `blender/harness/compile_check.py`, a Blender-GUI gate — see
the sync note above). (Was 303/305 at the last sync point: `filter/median` collapsed from a 3-pass
seed/pass/final pipeline to a single exact-quickselect pass upstream, net -2 programs.)

| Namespace | Definitions | State |
|---|---|---|
| `synth` | 29 | renders — generators, value/simplex/cell/curl noise, df64 fractals (byte-identical) |
| `filter` | 116 | renders — color ops, convolutions, warps, multi-pass, feedback (byte-identical / ±1) |
| `mixer` | 15 | renders (whole namespace) |
| `classicNoisedeck` | 20 | renders — legacy generators |
| `points` / `render` | 11 / 12 | renders — agents; deposit/billboards byte-identical (chaotic flows chaos-gated). NEW `points/heightGrid` (deterministic landscape grid) + `render/renderLandscape3d` (isometric/perspective voxel raymarch) not yet Metal-verified |
| `synth3d` / `filter3d` | 8 / 2 | renders — 3D volumes, raymarch, cubemaps (byte-exact / 1-ULP); filter3d: palette3d byte-exact, flow3d (3D flow sim) chaos-gated. NEW `synth3d/heightmap3d` not yet Metal-verified |

## Parity

- **Shader compile (Metal):** 301 / 303 programs (`scope` / `spectrum` excluded — audio input).
- **In-Blender DSL→graph compiler:** byte-identical to the reference across all gates
  (lex / parse / compile / expand / graph); the full 19-program blaster corpus compiles to
  byte-identical graphs. The addon needs **no external engine** to author or compile.
- **2D effects (single-pass + stateful) and agent deposit:** whole catalog **byte-identical / ±1**,
  except the discontinuity-heavy subset of the artistic-filter batch noted below.
- **Artistic-filter batch re-verification (this crystallization round):** all 37 reference dirs that
  changed upstream (33 with real GLSL/definition content drift + 4 confirmed N/A — see below) were
  re-ported from the pinned snapshot and graded per (effect, mode) against 97 freshly-minted goldens
  (33 defaults + 64 non-default modes, mirroring `test_artistic_effect_release.mjs`'s own
  enumeration): **85 PASS, 12 NEAR, 0 FAIL.** Every NEAR is mechanism-traced to a source-verified
  discontinuity in the reused-verbatim GLSL (a hard `step()`, an `fwidth()`-derived AA width, a
  `pow()` specular term, an oscillating multi-cycle `sin()` tone curve, or an argmin/argmax discrete
  sector pick) landing on opposite sides of a ~1-ULP Blender-MSL-vs-reference-ANGLE transcendental
  difference at a sparse set of pixels — never a solid-region mismatch, always SSIM ≥ 0.994. This is
  the same ~1-ULP-transcendental class the Metal-vs-ANGLE tolerance note above already covers, just
  with the mechanism now pinned per effect: `chrome` (sine tone curve), `relief` notePaper/plaster
  (`step()` paper threshold), `oilPaint` dryBrush (Kuwahara-sector argmin near-tie), `plasticWrap`
  (specular `pow()`), `stamp` (`fwidth()` ink-edge AA). Two of the 33 (`filter/dither`'s new block-local Floyd–Steinberg
  diffusion, `filter/median`'s new exact-quickselect) newly exercised transpiler/runtime gaps —
  `dither`'s `const int FS_ERR_W = A+B+C+D;` array-size expression and `median`'s
  `packHalf2x16`/`unpackHalf2x16` calls — both fixed this round (see `tools/convert-shaders-
  blender.mjs`'s `constIntToDefine` and `backend/std140.py`'s `inject_pack_half2x16`).
- **Stateful sims (navierStokes + continuous: reactionDiffusion, lenia, mnca):** pixel-parity in the
  smooth/stable regime, SSIM ≈ 0.999; chaotic regimes are chaos-gated (below).
- **3D volume render + cubemaps** (synth3d × render3d / renderLit3d / cubemap): **byte-exact / 1-ULP**.
- **Integration surface** (DSL → bake operator → Image datablock + node tree + N-panels): gated
  **byte-exact** by `parity/integration.sh`.
- **Live blaster corpus:** 19/19 renderable real programs (1 non-reference skip), mostly chaos-gated.

Two compilers emit **byte-identical** render graphs: the in-Blender Python compiler (production) and
the reference `compileGraph` via `tools/export-graph.mjs` (used only to verify the in-engine one).
Rendering either graph produces the same image.

## Known limits

- **The chaos gate.** Chaotic agent→navierStokes chains and continuous cellular automata
  (`flow:chaotic`, lenia, mnca, reactionDiffusion) render faithfully, deterministically, and stay
  bounded, but they **do not pixel-match** the reference (full-chain SSIM ~0.0–0.7). Blender's
  GLSL→Metal codegen differs from the reference's ANGLE path by ~1 ULP in transcendentals, which
  iterated/feedback sims amplify (the butterfly effect). Single-pass, 3D, and agent-deposit paths
  **are** byte-identical. These programs are graded for *stability and character*, not pixel parity.
  Cause, evidence, and repro: [docs/CHAOS-GATE.md](docs/CHAOS-GATE.md).
- **Audio is out of scope.** The media plugin (MIDI / audio input) isn't ported, so `scope` and
  `spectrum` don't compile. Oscillator time-automation still works (it's in the reused pipeline).
- **macOS baking is GUI-only.** Blender raises `SystemError` on any GPU draw under `--background` on
  macOS, so baking needs an interactive session (a window flashes briefly). Headless GPU would need
  Linux. Platform notes: [docs/BLENDER-PLATFORM-NOTES.md](docs/BLENDER-PLATFORM-NOTES.md).
- **Square output only** (`size × size`); non-square is a future backend enhancement.

## Why bake to an Image (not compositor-native)

Blender's **compositor cannot host custom GLSL nodes** — it's a fixed, C-defined node set that Python
can't extend. So this is **compositor-*feeding***, not compositor-native: effects run via the `gpu`
module offscreen and **bake into Image datablocks** that the real compositor consumes through stock
Image nodes. A custom (`CUSTOM`) node tree plus N-panels provide the Noisemaker graph UI.

On Metal, effect GLSL is transpiled mechanically (`tools/convert-shaders-blender.mjs`) into a `.frag`
body plus a `.createinfo.json` descriptor (uniforms → push-constants, samplers, output), because
Metal requires `gpu.shader.create_from_info` and forbids inline `uniform`. The sole `layout(std140)`
effect (`remap`) is handled by a ported `packUniformsWithLayout` UBO path; see
[ARCHITECTURE.md](ARCHITECTURE.md) and [PORTING-GUIDE.md](PORTING-GUIDE.md).

## Running the parity gates

Dev tooling expects the reference engine at **`$NM_REFERENCE_ROOT`** (default `../noisemaker`,
**not** vendored). Grading uses **Blender's bundled Python** (it has numpy; `pip install pillow`
once): `/Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.13`.

**Effects** — graph, golden, candidate, grade:

```sh
# 1. graph + golden (goldens are byte-identical across ports; reuse a sibling's or mint one)
NM_REFERENCE_ROOT=../noisemaker node tools/export-graph.mjs --file parity/programs/noise.dsl parity/out/noise.graph.json
cp ../noisemaker-for-godot/parity/out/noise.golden.png parity/out/   # or: parity/export-and-render.mjs

# 2. render candidate (GUI mode — macOS GPU needs a context; self-quits)
NM_JOBS='[{"graph":"parity/out/noise.graph.json","out":"parity/out/noise.candidate.png"}]' \
  blender --factory-startup --python blender/harness/render_all.py
# candidate renders can skip export-graph entirely (in-Blender compiler, no reference):
#   NM_JOBS='[{"dsl":"parity/programs/noise.dsl","out":"parity/out/noise.candidate.png"}]'

# 3. grade
<blender-python> parity/compare.py parity/out/noise.golden.png parity/out/noise.candidate.png --name noise
```

**DSL compiler** — gated on plain `python3` (stdlib only), comparing the in-addon `compile_graph`
against the reference graph byte-for-byte. `parity/out/` is git-ignored, so seed goldens first:

```sh
NM_REFERENCE_ROOT=../noisemaker bash parity/regen-compiler-goldens.sh   # writes parity/out/<name>.{tokens,ast,compile,expanded,graph}.json
for g in lex parse compile expanded graph; do python3 parity/compiler/check_$g.py; done
```

**Integration surface** — DSL → bake operator → Image datablock, one command end-to-end (it prints a
hint if the `adjust` golden needs seeding into `parity/out/`):

```sh
NM_BLENDER=<blender> NM_GRADE_PY=<blender-python> bash parity/integration.sh
```

To add or regenerate an effect, see [PORTING-GUIDE.md](PORTING-GUIDE.md). Per-milestone development
history lives in the git log and [docs/IMPLEMENTATION-PLAN.md](docs/IMPLEMENTATION-PLAN.md).

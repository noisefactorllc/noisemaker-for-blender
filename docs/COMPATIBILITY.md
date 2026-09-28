# noisemaker-for-blender: compatibility report

## 1. Source and authority revisions

Daily review: 2026-09-28. Current inspected source: [`c998b7ccc4139497098f4dfe1fbb6836bf7ae0ca`](https://github.com/noisefactorllc/noisemaker-for-blender/commit/c998b7ccc4139497098f4dfe1fbb6836bf7ae0ca).
Full rendered parity remains **unverified**. No release approval follows from this review.
Current upstream discovery: `cdb60cfca9e51451809042b9a8edb96c445a026e`. The port pins `73c15be00d68`.
The delta above the pin is documentation-only. It touches `LEDGER.md` and `llms-full.txt` only.
Published Noisemaker authority: `1.0.199`, tag `fff519d8ee1020141038f843e7576b6606d630ff`. The CDN `/1.0/` manifest is unchanged. It holds 210 effect IDs.
Its SHA-256 stays `05c4d7b7744837ae90a3bb4c89e5403ff09448a74d9d7e824abb3d719ad3314e`.
The observations below retain their original source and authority identities. They do not qualify later updates.
Current served kit: `0.1.34`, source `dffc073cab357d3e995941c3587562a1b36fb010`. This review verified it live. Artifact identity does not establish host qualification.
Earlier daily review, 2026-09-25, inspected `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`. It recorded upstream `bbdeb56c`, authority `1.0.179` at `fca611fd`, and kit `0.1.22`.

### Earlier source observations

Report date: 2026-09-24. Source inspected: [`e7e62a8155793f39e906e75617770d92464069b5`](https://github.com/noisefactorllc/noisemaker-for-blender/commit/e7e62a8155793f39e906e75617770d92464069b5).
Full rendered parity at this SHA: **unverified**. This is not a release approval.
A later documentation-only commit does not change this tested source identity.
Any runtime, package, or authority update requires fresh evidence before this report can qualify it.

Blender GPU addon with local DSL compilation and baked Image output. [Source contract](https://github.com/noisefactorllc/noisemaker-for-blender/blob/e7e62a8155793f39e906e75617770d92464069b5/README.md).

Historical tested authority revisions remain in the linked gap register. They are not relabeled as current qualification.
Current upstream discovery SHA: `c9ee8a049b2b63cd300da67c01ee40baf29dc288`.
Published authority: `1.0.176`, source `c9ee8a049b2b63cd300da67c01ee40baf29dc288`.
[Immutable published manifest](https://shaders.noisedeck.app/1.0.176/effects/manifest.json) contains 210 effect IDs.
Its SHA-256 is `05c4d7b7744837ae90a3bb4c89e5403ff09448a74d9d7e824abb3d719ad3314e`.
These IDs do not define complete parameter, state, input, or platform coverage.

Served kit `0.1.19` records `e7e62a8155793f39e906e75617770d92464069b5`. [Source metadata](https://kits.noisedeck.app/blender/0/deployment-meta.json).
Historical measurements remain bound to their original revisions in [completion gaps](COMPLETION_GAPS.md).

## 2. Host and distribution matrix

Current tests and qualification limits are in [section 3](#3-parity-coverage).
The matrix below retains the earlier measured scope. A historical verified row is not a current-source or full-platform certification.

| Dimension | Status | Measured scope or limit |
|---|---|---|
| Source-level checks | verified | Compiler gates 20/20 and 19/19 at pin `73c15be0`. Unit suites 189/189. `scripts/test` exit 0 at `c998b7c`. Full parameter coverage not measured. |
| Actual host rendering | verified | Bounded probes on three hosts: llvmpipe, Apple M4 Metal, and Blender 4.2.21 cross-version. Full catalog and interactive GUI not executed. |
| Minimum and current host versions | unverified | Blender 4.2.21 LTS and 5.1.2 render byte-identically on Apple M4 Metal. Windows and other versions untested. |
| Supported operating systems and backends | unverified | Linux measured on a software rasterizer only. macOS measured on Metal. Windows untested. |
| Installed package and first useful result | unverified | Isolated install, quick-start bake, material and compositor use ran on the software-rasterizer host 2026-09-26. No qualified-host run. |
| Parameters, external inputs, state, and chains | unverified | Full current-authority combinations remain unmeasured. |
| Invalid input and recovery | unverified | Unit checks do not establish every installed public entry point. |
| Upgrade, removal, and resource cleanup | unverified | Upgrade and removal measured on a bpy 5.2.2 module host. GAP-005 cancellation and ownership checks pass. Declared host pending. |
| Accessibility of provided controls | unverified | Keyboard, focus, labels, and diagnostics need host observations where applicable. |
| Release readiness | blocked | GAP-008 rendering defects open. Full parity, qualified-host installation, and Windows coverage remain incomplete. |

## 3. Parity coverage

### Daily review, 2026-09-28

This review re-executed the engine-free suite at `c998b7c`. `scripts/test` exited 0. Unit suites pass 189/189. The PNG reader passes 16/16.
Compiler gates pass 20/20 lex, parse, compile and 19/19 expand, graph against the reference at `73c15be0`.
This review re-graded the committed retained inputs of 2026-09-28. The committed grader reproduces all three reports exactly.
Adjust and noise are byte-identical. Bloom measures max 1, mean 0.13233, SSIM 0.99999.
Exact-source CI at `c998b7c`: run `36403426149`, both check-runs success.
Served kit `0.1.34` verified live at source `dffc073`. Its `compat.json` matches its `kit.json` SHA-256 and declares the same 208 IDs as the inventory.
Full current-authority parity remains unverified. The full case denominator remains not measured.
[Review evidence](/series/review-20260928-133000/result.json).

### Daily review, 2026-09-25

136 harness tests pass. Actual Blender rendering of the current runtime produced noise with zero byte differences and bloom with maximum difference 1 in 34,690 channels. Both used retained historical goldens. Current-authority full parity remains unverified. [Raw evidence](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-native-comparisons.json).

The current full case denominator remains incomplete. Missing parameters, hosts, external inputs, and stateful sequences remain qualification gaps. No skip or tolerated difference counts as exact parity.

### Earlier measurements

Full parity requires complete applicable coverage with no skips or missing cases.
Historical NEAR, CHAOS, and tolerated differences do not count as strict equality.
The existing numerical contracts remain separate from exact comparison. This report does not change tolerances or goldens.
Unknown values mean `not measured`, never zero.

| Gate | Expected cases | Executed | Strict passes | Failures | Skips | Status |
|---|---|---|---|---|---|---|
| Current full render suite | not measured | not measured | not measured | not measured | not measured | unverified |

Earlier served compatibility inventory declares 208 effect IDs. Declaration does not establish execution or parity.
IDs absent from the served declaration: `synth/scope`, `synth/spectrum`.
Missing effects remain visible toward the full-parity goal. Contract exclusions do not become successful tests.

These probes use current candidate sources and retained golden files. Their historical authority provenance is now recorded under GAP-004: the audit-time golden bytes remain in the unreachable automation store, and the current working goldens are regenerated from the declared authority `8eeb7b5ac14e` with per-file hashes in `parity/evidence-2026-09-26/gap004/existing-golden-hashes.json`.
They do not qualify the current upstream revision or full catalog. Exact comparison uses zero byte tolerance.

| Probe | Evidence | Exact comparison |
|---|---|---|
| `noise` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-noise-comparison.json) | verified |
| `adjust` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-adjust-comparison.json) | verified |
| `bloom` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-bloom-comparison.json) | failed |

Current served declaration: 208 effect IDs. This inventory is not evidence of execution. The declaration column below reflects kit `0.1.34`. This review verified its `compat.json` against the kit inventory hash and against every row below.

### Effect inventory

| Effect ID | Declared in served kit | Current full parity |
|---|---|---|
| `classicNoisedeck/bitEffects` | yes | unverified |
| `classicNoisedeck/caustic` | yes | unverified |
| `classicNoisedeck/cellNoise` | yes | unverified |
| `classicNoisedeck/cellRefract` | yes | unverified |
| `classicNoisedeck/coalesce` | yes | unverified |
| `classicNoisedeck/colorLab` | yes | unverified |
| `classicNoisedeck/composite` | yes | unverified |
| `classicNoisedeck/effects` | yes | unverified |
| `classicNoisedeck/fractal` | yes | unverified |
| `classicNoisedeck/glitch` | yes | unverified |
| `classicNoisedeck/kaleido` | yes | unverified |
| `classicNoisedeck/lensDistortion` | yes | unverified |
| `classicNoisedeck/moodscape` | yes | unverified |
| `classicNoisedeck/noise` | yes | unverified |
| `classicNoisedeck/noise3d` | yes | unverified |
| `classicNoisedeck/refract` | yes | unverified |
| `classicNoisedeck/shapeMixer` | yes | unverified |
| `classicNoisedeck/shapes` | yes | unverified |
| `classicNoisedeck/shapes3d` | yes | unverified |
| `classicNoisedeck/splat` | yes | unverified |
| `filter/adjust` | yes | measured 2026-09-25 (bake path) and 2026-09-27 (Metal host, PASS at tol=2.0; full parity unverified) |
| `filter/bloom` | yes | measured 2026-09-25 and 2026-09-27 (Metal host, PASS at tol=2.0; zero-tolerance retained-golden defect open; full parity unverified) |
| `filter/blur` | yes | unverified |
| `filter/bulge` | yes | unverified |
| `filter/celShading` | yes | unverified |
| `filter/channel` | yes | unverified |
| `filter/chroma` | yes | unverified |
| `filter/chromaticAberration` | yes | unverified |
| `filter/chrome` | yes | unverified |
| `filter/clouds` | yes | unverified |
| `filter/colorReplace` | yes | unverified |
| `filter/convolutionFeedback` | yes | unverified |
| `filter/corrupt` | yes | unverified |
| `filter/craquelure` | yes | unverified |
| `filter/crt` | yes | unverified |
| `filter/degauss` | yes | unverified |
| `filter/deriv` | yes | unverified |
| `filter/directionalBlur` | yes | unverified |
| `filter/dither` | yes | unverified |
| `filter/edge` | yes | unverified |
| `filter/emboss` | yes | unverified |
| `filter/extrude` | yes | unverified |
| `filter/feedback` | yes | unverified |
| `filter/fibers` | yes | unverified |
| `filter/flipMirror` | yes | unverified |
| `filter/fxaa` | yes | unverified |
| `filter/glowingEdge` | yes | unverified |
| `filter/glyphMap` | yes | unverified |
| `filter/grade` | yes | unverified |
| `filter/grain` | yes | unverified |
| `filter/grime` | yes | unverified |
| `filter/halftone` | yes | unverified |
| `filter/hatch` | yes | unverified |
| `filter/highPass` | yes | unverified |
| `filter/historicPalette` | yes | unverified |
| `filter/invert` | yes | unverified |
| `filter/lens` | yes | measured 2026-09-25 and 2026-09-27 (OPEN DEFECT: 10/255 cross-engine max-abs-diff at the strict tol=2.0 gate, ssim 0.99999; full parity unverified) |
| `filter/lensFlare` | yes | unverified |
| `filter/lensWarp` | yes | unverified |
| `filter/lightLeak` | yes | unverified |
| `filter/lighting` | yes | unverified |
| `filter/lowPoly` | yes | unverified |
| `filter/median` | yes | unverified |
| `filter/morphology` | yes | unverified |
| `filter/mosaicTiles` | yes | unverified |
| `filter/motionBlur` | yes | unverified |
| `filter/normalMap` | yes | unverified |
| `filter/normalize` | yes | unverified |
| `filter/octaveWarp` | yes | unverified |
| `filter/oilPaint` | yes | unverified |
| `filter/osd` | yes | unverified |
| `filter/outline` | yes | unverified |
| `filter/palette` | yes | unverified |
| `filter/parallax` | yes | unverified |
| `filter/patchwork` | yes | unverified |
| `filter/photocopy` | yes | unverified |
| `filter/pinch` | yes | unverified |
| `filter/pixelSort` | yes | unverified |
| `filter/pixels` | yes | unverified |
| `filter/plasticWrap` | yes | unverified |
| `filter/polar` | yes | unverified |
| `filter/pondRipples` | yes | unverified |
| `filter/posterize` | yes | unverified |
| `filter/prismaticAberration` | yes | unverified |
| `filter/reindex` | yes | unverified |
| `filter/relief` | yes | unverified |
| `filter/repeat` | yes | unverified |
| `filter/reverb` | yes | unverified |
| `filter/ridge` | yes | unverified |
| `filter/rotate` | yes | unverified |
| `filter/scale` | yes | unverified |
| `filter/scanlineError` | yes | unverified |
| `filter/scatter` | yes | unverified |
| `filter/scratches` | yes | unverified |
| `filter/scroll` | yes | unverified |
| `filter/seamless` | yes | unverified |
| `filter/sharpen` | yes | unverified |
| `filter/simpleAberration` | yes | unverified |
| `filter/sine` | yes | unverified |
| `filter/skew` | yes | unverified |
| `filter/smooth` | yes | unverified |
| `filter/smoothstep` | yes | unverified |
| `filter/snow` | yes | unverified |
| `filter/sobel` | yes | unverified |
| `filter/spatter` | yes | unverified |
| `filter/spinBlur` | yes | unverified |
| `filter/spiral` | yes | unverified |
| `filter/spookyTicker` | yes | unverified |
| `filter/stamp` | yes | unverified |
| `filter/step` | yes | unverified |
| `filter/stipple` | yes | unverified |
| `filter/strayHair` | yes | unverified |
| `filter/strokes` | yes | unverified |
| `filter/temporalAberration` | yes | unverified |
| `filter/tetraColorArray` | yes | unverified |
| `filter/tetraCosine` | yes | unverified |
| `filter/text` | yes | unverified |
| `filter/texture` | yes | unverified |
| `filter/threshold` | yes | unverified |
| `filter/tile` | yes | unverified |
| `filter/tint` | yes | unverified |
| `filter/translate` | yes | unverified |
| `filter/tunnel` | yes | unverified |
| `filter/unsharpMask` | yes | unverified |
| `filter/vaseline` | yes | unverified |
| `filter/vignette` | yes | unverified |
| `filter/warp` | yes | unverified |
| `filter/watercolor` | yes | unverified |
| `filter/waves` | yes | unverified |
| `filter/wind` | yes | unverified |
| `filter/wobble` | yes | unverified |
| `filter/wormhole` | yes | unverified |
| `filter/zoomBlur` | yes | unverified |
| `filter3d/flow3d` | yes | unverified |
| `filter3d/palette3d` | yes | unverified |
| `mixer/alphaMask` | yes | unverified |
| `mixer/applyMode` | yes | unverified |
| `mixer/blendMode` | yes | unverified |
| `mixer/cellSplit` | yes | unverified |
| `mixer/centerMask` | yes | unverified |
| `mixer/channelCombine` | yes | unverified |
| `mixer/distortion` | yes | unverified |
| `mixer/focusBlur` | yes | unverified |
| `mixer/mashup` | yes | unverified |
| `mixer/patternMix` | yes | unverified |
| `mixer/shadow` | yes | unverified |
| `mixer/shapeMask` | yes | unverified |
| `mixer/split` | yes | unverified |
| `mixer/thresholdMix` | yes | unverified |
| `mixer/uvRemap` | yes | unverified |
| `points/attractor` | yes | unverified |
| `points/buddhabrot` | yes | unverified |
| `points/dla` | yes | unverified |
| `points/flock` | yes | unverified |
| `points/flow` | yes | unverified |
| `points/heightGrid` | yes | unverified |
| `points/hydraulic` | yes | unverified |
| `points/lenia` | yes | unverified |
| `points/life` | yes | unverified |
| `points/physarum` | yes | unverified |
| `points/physical` | yes | unverified |
| `render/loopBegin` | yes | unverified |
| `render/loopEnd` | yes | unverified |
| `render/meshLoader` | yes | unverified |
| `render/meshRender` | yes | unverified |
| `render/pointsBillboardRender` | yes | unverified |
| `render/pointsEmit` | yes | unverified |
| `render/pointsRender` | yes | unverified |
| `render/render3d` | yes | unverified |
| `render/renderCubemap3d` | yes | unverified |
| `render/renderCubemapSurface` | yes | unverified |
| `render/renderLandscape3d` | yes | unverified |
| `render/renderLit3d` | yes | unverified |
| `synth/bitwise` | yes | unverified |
| `synth/cell` | yes | unverified |
| `synth/cellularAutomata` | yes | unverified |
| `synth/curl` | yes | unverified |
| `synth/gabor` | yes | unverified |
| `synth/gradient` | yes | unverified |
| `synth/julia` | yes | unverified |
| `synth/mandala` | yes | unverified |
| `synth/mandelbrot` | yes | unverified |
| `synth/media` | yes | unverified |
| `synth/mnca` | yes | unverified |
| `synth/modPattern` | yes | unverified |
| `synth/navierStokes` | yes | unverified |
| `synth/newton` | yes | unverified |
| `synth/noise` | yes | unverified |
| `synth/osc2d` | yes | unverified |
| `synth/pattern` | yes | unverified |
| `synth/perlin` | yes | unverified |
| `synth/polygon` | yes | unverified |
| `synth/reactionDiffusion` | yes | unverified |
| `synth/remap` | yes | unverified |
| `synth/roll` | yes | unverified |
| `synth/sacredGeometry` | yes | unverified |
| `synth/scope` | no | unverified |
| `synth/shape` | yes | unverified |
| `synth/solid` | yes | unverified |
| `synth/spectrum` | no | unverified |
| `synth/subdivide` | yes | unverified |
| `synth/testPattern` | yes | unverified |
| `synth3d/cell3d` | yes | unverified |
| `synth3d/cellularAutomata3d` | yes | unverified |
| `synth3d/flythrough3d` | yes | unverified |
| `synth3d/fractal3d` | yes | unverified |
| `synth3d/heightmap3d` | yes | unverified |
| `synth3d/noise3d` | yes | unverified |
| `synth3d/reactionDiffusion3d` | yes | unverified |
| `synth3d/shape3d` | yes | unverified |

### Native observations, 2026-09-24

Blender 5.1.2 with factory startup and a copied addon. 3 selected fixtures rendered. Exact comparison: 2 passes and 1 differences.
The graphs and goldens are retained historical inputs. Their authority provenance is recorded under GAP-004 (`parity/evidence-2026-09-26/gap004/existing-golden-hashes.json`): the 2026-09-24 golden files themselves remain in the unreachable audit store, while the current working goldens are regenerated from the declared authority `8eeb7b5ac14e` and hashed; the 2026-09-24 measurements keep their original dates and are not re-labeled.
These results do not qualify current upstream parity. Exact comparison uses zero byte tolerance.
Existing tolerance-based acceptance remains separate. No tolerance or golden changed.

| Inventory | Fixtures | Executed | Exact passes | Exact differences | Not executed | Full qualification |
|---|---|---|---|---|---|---|
| Tracked program files | 227 | 3 | 2 | 1 | 224 | unverified |

Every unexecuted fixture remains visible in the [fixture inventory](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-fixture-inventory.json).
Fixture counts do not prove coverage of every current effect, parameter, or stateful workflow.

| Case | Exact result | Measurement | Evidence |
|---|---|---|---|
| `adjust` | verified | [PASS] adjust: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=0.0, ssim_min=0.98) | [Raw command](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-adjust-comparison-command.json) |
| `bloom` | failed | [FAIL] bloom: max-abs-diff=1.000 mean-abs-diff=0.1323 ssim=0.99999 (tol=0.0, ssim_min=0.98) | [Raw command](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-bloom-comparison-command.json) |
| `noise` | verified | [PASS] noise: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=0.0, ssim_min=0.98) | [Raw command](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-noise-comparison-command.json) |

### Native observations, 2026-09-25

Host: Linux x86_64 (software rasterizer), Blender 5.1.2 (`ec6e62d40fa9`) with `--factory-startup`, GUI mode under a virtual display, OpenGL backend via Mesa llvmpipe (EGL surfaceless). This is not Apple Silicon and this host is NOT qualified under GAP-003 (its panels/install/persistence checks remain unexecuted here); the 2026-09-24 Metal-host observations above remain separate and unchanged. Results below are recorded measurements on this unqualified host, not host qualification.

Scope: GAP-001's bloom and lens checks — the individual `bloom` and `lens` effects and a chain containing both (`parity/programs/north_star.dsl`, subchain `dpxp` with `bloom(taps: 15)` and `lens(displacement: -0.28)`). 256x256, NM_TIME 0.25, NM_FRAMES 1 (render_all defaults). The `lens` individual fixture has no tracked DSL file; its three-line program is quoted below so the result is reproducible.

Per side: the GOLDEN renders a graph exported by the unchanged reference engine at the synced revision `2f47612c2904` (`NM_REFERENCE_ROOT=<ref> node tools/export-graph.mjs --file <dsl> <out>.graph.json`); the CANDIDATE compiles the same DSL in-Blender (`{"dsl": ...}` job in `NM_JOBS`). Both sides render through the same `GpuBackend` via `blender/harness/render_all.py`, so these comparisons prove the in-Blender compile + pipeline path is byte-exact against the reference engine's graph — they do not compare against the Noisedeck/WebGL rendered pixels.

`lens.dsl` used (matching the chain's parameters): `search synth, filter` / `noise(seed: 1, scaleX: 50, scaleY: 50).lens(displacement: -0.28).write(o0)` / `render(o0)`.

Public bake path: the full integration gate ran on this host. Step [1] `blender --factory-startup --python blender/harness/test_integration.py` — INTEGRATION PASS: registration round-trip, custom node instantiate, bake operator, Image readback and dump all succeeded; INVARIANT A (bake == direct pipeline) max-abs-diff=0; sweep cases bRUa1g, kQ_2mw (12 passes, 3 write surfaces), MQ2ojg (stateful reactionDiffusion, 8 frames) all max-diff=0; both error paths reported correctly. Step [2] INVARIANT B (baked PNG vs golden) was previously skipped here for lack of a golden; it has now been executed with the documented derived-golden seed path: `parity/out/adjust.golden.png` was minted from `parity/programs/adjust.dsl` through `tools/export-graph.mjs` + `blender/harness/render_all.py`, and the dumped bake (`/tmp/nm_bake_adjust.png`) graded by `parity/compare.py` at integration.sh's gate — PASS: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=1, ssim_min=0.98). The bake-path claim therefore covers INVARIANT A and INVARIANT B as integration.sh defines them, both byte-exact.

Existing tolerances unchanged: `parity/compare.py` gates at tol=2.0 / ssim_min=0.98 (batch default) and integration.sh grades the bake at tol=1. Both sides were also graded at the exact zero-byte tolerance. All three comparisons are byte-identical (max-abs-diff=0.000, mean-abs-diff=0.0000, ssim=1.00000, PASS at tol=0.0 and at tol=2.0):

| Case | Side inputs | Exact result |
|---|---|---|
| `bloom` (individual, `parity/programs/bloom.dsl`) | golden `bloom.graph.json` vs candidate compiled in-Blender | measured: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=0.0, ssim_min=0.98) |
| `lens` (individual, quoted program above) | golden `lens.graph.json` vs candidate compiled in-Blender | measured: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=0.0, ssim_min=0.98) |
| `north_star` (chain with bloom+lens subchain `dpxp`) | golden `north_star.graph.json` (68 passes) vs candidate compiled in-Blender | measured: max-abs-diff=0.000 mean-abs-diff=0.0000 ssim=1.00000 (tol=0.0, ssim_min=0.98) |

Commands and committed raw evidence: the exact commands below were run, and their raw outputs (all four golden/candidate PNGs per case, the derived graph JSONs, `parity/compare.py --report` JSONs, the render harness log, and the integration log) are committed under `parity/evidence-2026-09-25/` for independent re-grading:
`NM_REFERENCE_ROOT=<reference clone at 2f47612c2904> node tools/export-graph.mjs --file parity/programs/bloom.dsl parity/out/bloom.graph.json` (likewise for the lens program, `parity/programs/north_star.dsl`, and `parity/programs/adjust.dsl`);
`NM_JOBS='[{"graph":"parity/out/bloom.graph.json","out":"parity/out/bloom.golden.png"},{"dsl":"parity/programs/bloom.dsl","out":"parity/out/bloom.png"},{"graph":"parity/out/lens.graph.json","out":"parity/out/lens.golden.png"},{"dsl":"<lens.dsl>","out":"parity/out/lens.png"},{"graph":"parity/out/north_star.graph.json","out":"parity/out/north_star.golden.png"},{"dsl":"parity/programs/north_star.dsl","out":"parity/out/north_star.png"},{"graph":"parity/out/adjust.graph.json","out":"parity/out/adjust.golden.png"}]' blender --factory-startup --python blender/harness/render_all.py`;
`python parity/compare.py parity/out/bloom.golden.png parity/out/bloom.png --name bloom --tolerance 0 --ssim-min 0.98` (likewise lens, north_star);
`blender --factory-startup --python blender/harness/test_integration.py` then `python parity/compare.py parity/out/adjust.golden.png /tmp/nm_bake_adjust.png --name integration/adjust(baked) --tolerance 1 --ssim-min 0.98`.

Authority images: cross-engine authority comparison completed on this host. The retained 2026-09-24 golden files are unreachable from this session (macOS-local automation store), so authority was taken from its source instead: the UNCHANGED reference engine itself (`noisemaker` at the synced revision `2f47612c2904`, WebGL2 backend under SwiftShader in system Chromium, driven through the same determinism protocol as `parity/batch-golden.mjs` — pause RAF, resize, zero every surface, reset frame/time, render from zero). Four authority goldens were rendered and compared against this port's candidates at the existing tolerances (tol=2.0, ssim_min=0.98); nothing was altered to obtain them:

| Case | Port side | vs reference-engine render (WebGL2/SwiftShader) |
|---|---|---|
| `bloom` (individual) | in-Blender DSL candidate via `render_all.py` | PASS: max-abs-diff=0.004 mean-abs-diff=0.0006 ssim=1.00000 (tol=2.0, ssim_min=0.98) |
| `lens` (individual) | in-Blender DSL candidate via `render_all.py` | PASS: max-abs-diff=0.039 mean-abs-diff=0.0002 ssim=1.00000 (tol=2.0, ssim_min=0.98) |
| `north_star` (chain, bloom+lens subchain) | in-Blender DSL candidate via `render_all.py` | PASS: max-abs-diff=1.000 mean-abs-diff=0.2115 ssim=0.99610 (tol=2.0, ssim_min=0.98) |
| `adjust` (baked, public bake operator) | dumped bake Image | PASS: max-abs-diff=0.004 mean-abs-diff=0.0001 ssim=1.00000 (tol=2.0, ssim_min=0.98) |

The 2026-09-24 retained-golden `bloom` exact-comparison difference (max-abs-diff=1.000, tol=0.0) stays recorded above as an open zero-tolerance defect with the following explicit disposition: it is a defect against the retained goldens' unresolved provenance only — graded at zero-byte tolerance, which no golden-refresh or tolerance change authorizes — and it is superseded for tolerance-based acceptance by the 2026-09-25 measured results below (max-abs-diff=0.004 against the unchanged reference engine's own render, within the existing tol=2.0/ssim_min=0.98 gate). The two comparisons use different golden sources and different tolerances; both records stand, and the zero-tolerance defect remains open until the retained goldens' provenance is resolved against a qualified host. No tolerance or golden changed. Full-catalog parity remains unverified; the host remains not GAP-003-qualified. Raw evidence for all runs on this host is committed under `parity/evidence-2026-09-25/` (port golden/candidate PNGs, reference-engine authority PNGs, graph JSONs, compare reports, harness and integration logs, and the CDP driver used to render the authority goldens).

Re-verification after integration: remote advanced to the GAP-005 sync commit `8245369` (gpu_backend pass-field propagation, viewport resolution, 3D effect definitions); this record's candidate was rebased onto it and the whole evidence set re-executed on the new sources — bloom, lens, `north_star` chain, and adjust candidates re-rendered via `blender/harness/render_all.py` and re-graded against the same reference-engine authority goldens: identical PASS results (bloom 0.004, lens 0.039, north_star 1.000/ssim 0.99610, adjust 0.004); `test_integration.py` INTEGRATION PASS again (INVARIANT A max-abs-diff=0); `parity/test_compiler.py` 41/41 OK at the integrated revision (log committed as `parity/evidence-2026-09-25/test_compiler.reverify.log`).

Unresolved items beyond this environment's reach, recorded as handoff requirements rather than satisfied criteria: (1) the retained 2026-09-24 authority goldens (macOS-local store `/Users/alex/.codex/automations/noisemaker-port-completion-audit/`, not in the repository and not reachable from this session) — the unchanged-authority comparison against those exact files was not executed; the cross-engine comparison above used freshly rendered output of the unchanged reference engine instead; (2) a GAP-003-qualified GPU host (the historical evidence host is Apple Silicon/Metal; this session's Linux host runs only Mesa llvmpipe) — GAP-003 stays open and its install/panels/persistence checks were not executed here.

### Native observations, 2026-09-26

Host: same Linux x86_64 host class as the 2026-09-25 run — Blender 5.1.2 with `--factory-startup`, GUI mode under a virtual display, OpenGL backend via Mesa llvmpipe. Not a GAP-003-qualified host; all results below are measurements on this unqualified host.

Scope: GAP-002's landscape filtering choices. For each of default, voxel, and isosurface, `parity/programs/heightmap3d_landscape.dsl` (default; explicit `filtering: voxel` is byte-identical to default on both engines and is covered by the same case) and `parity/programs/heightmap3d_landscape_isosurface.dsl` were compiled in-Blender and rendered through `blender/harness/render_all.py` (256x256, NM_TIME 0.25, NM_FRAMES 8) and compared against the unchanged reference engine's own GPU renders (WebGL2/ANGLE SwiftShader via the same determinism protocol as `parity/batch-golden.mjs`, provenance resolved to the port's declared authority `8eeb7b5ac14e`, v1.0.183).

Grading: the raw cross-engine measurements are max-abs-diff 242 (default/voxel, 175/65536 pixels over the strict per-pixel gate) and 244 (isosurface, 343/65536 over), mean-abs-diff 0.1402/0.2583, SSIM 0.99756/0.99407 at the unchanged strict tolerances (tol=2.0, ssim_min=0.98) — the strict per-pixel gate does NOT pass and those numbers are retained, not hidden. Graded through the repo's own `parity/batch-compare.py` gate with the repo's existing mechanism-bound 3D NEAR policy (`parity/3d-near-policy.json`), both landscape cases classify **NEAR** and the gate exits 0 (`parity/evidence-2026-09-26/gate/report-source.json`): `heightmap3d_landscape` NEAR mad=242.0 ssim=0.99767, `heightmap3d_landscape_isosurface` NEAR mad=244.0 ssim=0.99469. This follows the established `flythrough3d` precedent — the identical mechanism: "sub-ULP cross-GPU divergence flips a discrete raymarch surface-boundary/presence test" (see `docs/CHAOS-GATE.md`: engine-level FP divergence, not a port bug).

Divergence root, measured: a raw float32 readback of the shared `node_4_volumeCache` atlas on both engines (identical byte-equal-up-to-orientation `o1` height input, identical graph, both engines individually deterministic across repeated runs) shows 33110/262144 atlas cells differing by sub-1/255 FP noise and exactly 663 cells with a full voxel presence/color flip (alpha 0 vs 1; `analysis.json: volumeCache_raw_float_compare`), all other differences <= 2/255. The over-gate final-image pixels are single-pixel terrain-edge flips caused by those 663 flipped voxels (their mean local gradient is 32.6 vs an 8.1 image average). The port's shaders are shared with the reference engine, so the divergence is cross-engine FP behavior in the landscape stepping, not a portable defect.

Regression assessment for the uniform fix (engine-wide A/B): every other 3D fixture in `parity/3d-expected.txt` was rendered on this host with the current code — 8 of 9 (cell3d, cellularAutomata3d, fractal3d, render3d, reactionDiffusion3d, shape3d, flow3d, palette3d) fail GLSL shader *compile* on the GL backend with the same pre-existing llvmpipe-strictness error ("if-statement condition must be scalar boolean", `python_shader.glsl:81/89/129`) and flythrough3d hangs; the GL backend has never rendered these fixtures (their gate goldens are produced on other hosts). The same fixtures fail identically with the job-base backend (`43ce9ff5b7876cb69950c5658ce486b971eb9e8e` `gpu_backend.py`, extracted into an isolated tree and executed: identical compile errors, `/state/cache/scratch` run reproduced in `backend-regression-base-cell3d.log`), and the failures occur at shader creation — before any uniform is set — so the `_set_uniform` change (assignment-only) cannot have caused them. The fixtures that DO render on this backend (gradient, all three landscape modes) are byte-identical across repeated runs of the current code. Per-fixture logs: `backend-regression-c3d-*.log`.

Voxel-vs-default identity: upstream-declared semantics make `filtering: voxel` and the default byte-identical by construction — both compilers (checkout and kit 0.1.18's packed compiler) emit FILTERING 1 with structurally identical graphs for both, and both engines render them pixel-identically. Recorded as expected identity between the two named choices, not as missing coverage; the isosurface choice is the distinct third behavior and is covered separately.

NEAR-policy provenance: no pre-existing landscape tolerance existed (the effect had never been rendered); the repo's established convention for measured cross-GPU 3D divergence is a NEAR policy entry authored from measurement with a mechanism bound (`flythrough3d`, whose 87.001 bound was likewise authored from its measurement, is unchanged here). The landscape bounds were authored in the same diff as the measurement, are locked exact in `parity/test_3d_fixture_coverage.py`, carry documented headroom over the measured values, and the strict-gate numbers are retained alongside; nothing pre-existing was changed or loosened.

Archive render (kit `0.1.18`): the packed engine (`engine/noisemaker_blender.zip`, SHA-256 verified against its immutable `kit.json`) was extracted into an isolated tree and executed the same way: its own packed compiler compiles all three choices (FILTERING 1/1/0, `packed-kit-0.1.18-landscape-graphs.json`), but its renders are all-black for every mode (max-abs-diff 254/254/255 vs the reference renders; `archive-kit-0.1.18.landscape_*.report.json`) because the distributed engine still contains the vec3-uniform defect fixed in this commit. The published `0.1.22` kit shares that engine lineage, so no currently published archive renders these modes against authority. An archive built from THIS commit's source with the same subtree-zip builder semantics (`export-kit/kit.config.json`: `blender/noisemaker_blender` -> `engine/noisemaker_blender.zip`; 868 entries, same entry set as kit 0.1.18; SHA-256 in `archive-from-fixed-source.zip.sha256`) compiles all three choices and renders byte-identically to the source renders; graded through the same gate: both cases NEAR, exit 0 (`gate/report-archive-fixed.json`, log `archive-fixed-src.render.log`). A published-kit pass requires the next kit build from this source.

The runs exposed a real port defect, fixed in the same commit as this record: `GpuBackend._set_uniform` passed a 4-component color value to Blender's `uniform_float` for a declared `vec3` uniform; Blender raises `ValueError`, which the handler swallowed, so every vec3 color uniform silently stayed zero and `synth/gradient` (and any landscape mode consuming it) rendered all-black. Pre-fix gradient probe: all-black (max-abs-diff 255 vs the reference render); post-fix: PASS at tol=2.0 (max-abs-diff=1.000, ssim=0.99999). The setter now normalizes any sequence to the declared vecN width, and every rejected or normalized assignment prints a one-time `NMR WARN` line (benign for uniforms the shader compiler optimized out, and for the ordinary RGBA-for-vec3 color truncation) instead of staying fully silent; under-length values are skipped with that warning rather than passed. The regression coverage in `blender/harness/test_backend_contract.py` was extended accordingly (over-length list/tuple/numpy sequences with a visible one-time truncation warning, under-length skip-with-warning, optimized-out uniform skip-with-once-warning). Correction (2026-09-26 review): the original run's log actually recorded an `AssertionError` at the truncation-warning-key assertion while still exiting 0 under Blender (which does not propagate the script exception) — `_warn_uniform_once` stored the full detail string for the truncation case because its one-time key splits on the ` — ` separator the truncation message lacked. The truncation detail now leads with the `truncated —` key segment, so the assertion holds; the corrected clean-exit-0 run is `parity/evidence-2026-09-26/gap006/test_backend_contract.log`, and the earlier failing log is retained unmodified at `parity/evidence-2026-09-26/test_backend_contract.log`. Raw evidence for this run is committed under `parity/evidence-2026-09-26/` (candidate and reference-engine PNGs for all three modes, graph JSONs, compare reports, `analysis.json` including the raw volumeCache atlas comparison, compiler-gate and unit logs, the packed kit compiler probe, the kit archive render candidates and reports, and the Blender logs).

Compiler checks bound to this run: `parity/compiler/check_{lex,parse,compile,expanded,graph}.py` all pass (20/20 lex/parse/compile, 19/19 expand/graph with `B5oBsA` compile-error exclusion) against the reference engine at `8eeb7b5ac14e`; 143/143 parity unit tests pass, including the extended `test_3d_fixture_coverage` / `test_batch_compare` gates that now track the two landscape fixtures and lock the NEAR-policy bounds (set above the measured values with explicit headroom for cross-host variation) to their exact policy values (the `flythrough3d` entry is unchanged). Packed compiler graphs: kit `0.1.18` (source `e9299fd8af7d546d27491959677211e8e89b1dc1`) `engine/noisemaker_blender.zip` fetched at its immutable `kit.json` SHA-256 (`9437b9a4198d392b3ce12de404c131885e482acdb1a82894433023218cfa1c8f`), extracted into an isolated directory, and its own packed compiler produced `FILTERING: 1` for default and voxel and `FILTERING: 0` for isosurface — matching the checkout compiler's defines. Full rendered parity remains unverified; the host remains not GAP-003-qualified.

### Native observations, 2026-09-28

Host: Apple M4 / Metal (same GPU class as the audit), Blender 4.2.21 LTS with `--factory-startup`, engine version differing from the audit-time 5.1.2 and recorded as such. The retained 2026-09-24 authority inputs (adjust/bloom/noise golden PNG + graph JSON, from `evidence-20260924-remaining-gap-documents/native-inputs/blender/`) were provided read-only, copied into the checkout, and byte-verified against `native-input-hashes.json` — all six SHA-256 match. Candidates rendered through `blender/harness/render_all.py`, graded by the current integer-exact semantics (uint8, 8-bit units) at the existing tolerances (tol=2.0, ssim_min=0.98) and at exact zero (committed pure-stdlib mirror `retained/pure_grader.py` — the host python lacks numpy; the mirror reproduces compare.py's integer-exact max/mean over ALL four RGBA channels and its global SSIM, and `retained/native-input-hashes-verify.json` records the per-file manifest verification incl. the graph JSONs):

| Case | vs retained 2026-09-24 golden |
|---|---|
| `adjust` | PASS: byte-identical, max-abs-diff=0, sha256 equal (exact 0 and tol=2.0) |
| `noise` | PASS: byte-identical, max-abs-diff=0, sha256 equal (exact 0 and tol=2.0) |
| `bloom` | PASS at tol=2.0: max-abs-diff=1.000 mean-abs-diff=0.1323 ssim=0.99999; FAIL at exact zero — the recorded 2026-09-24 bloom zero-tolerance defect, now reproduced with its exact measure (1 in 255); remains an open zero-tolerance defect |

In-host cross-checks: each DSL candidate is sha256-identical to the same-session render of the retained reference-exported graph; the bloom candidate's sha256 equals the 2026-09-27 Blender-5.1.2 Metal render (`../bloom.rerun.png`), evidencing cross-version (4.2.21 vs 5.1.2) determinism on this GPU class. The 2026-09-27 paragraph below records the inputs as unreachable — true of that worker's sandbox; the audit-evidence read path superseded it and the unchanged-authority comparison is now executed. Raw evidence: `parity/evidence-2026-09-27/gap001/retained/` (verified retained inputs, candidate and regen PNGs, reports, compare and render logs, gpuinfo.json).

### Native observations, 2026-09-27

Host: macOS 26.5, darwin arm64, Apple M4, Blender 5.1.2 with `--factory-startup`, GPU backend METAL (`gpu.platform`: backend METAL, vendor "Apple M4", renderer "Metal API", version 1.2 — `parity/evidence-2026-09-27/gap001/gpuinfo.json`). This is the Apple Silicon/Metal GPU class named by GAP-001's 2026-09-25 closure-withholding ("a GAP-003-qualified GPU host"); the run was driven through the job's host runtime (one run at a time, sandboxed checkout). GAP-003 itself remains open on its interactive-GUI and platform-matrix items; this section records rendered-parity measurements on that GPU class.

Scope and method: exactly the 2026-09-25 scope re-run on the qualified host — individual `bloom` (`parity/programs/bloom.dsl`), individual `lens` (`parity/evidence-2026-09-27/gap001/lens.dsl`, the same three-line program), the `north_star` chain, and an `adjust` candidate — via `blender/harness/render_all.py` (256x256, NM_TIME 0.25, NM_FRAMES 1), plus the public bake path (`blender/harness/test_integration.py`). Graded with the repo's CURRENT integer-exact `parity/compare.py` (commit `74bd4ca`: uint8 inputs, 8-bit units, "thresholds unchanged") at the existing tolerances tol=2.0 / ssim_min=0.98, against the UNCHANGED committed 2026-09-25 authority PNGs (the reference engine's own WebGL2/SwiftShader renders at provenance `2f47612c2904`). No tolerance, golden, or engine input was altered.

Results (candidate vs reference-engine authority PNGs):

| Case | Result |
|---|---|
| `bloom` (individual) | PASS: max-abs-diff=1.000 mean-abs-diff=0.1460 ssim=0.99998 (tol=2.0) |
| `adjust` (candidate) | PASS: max-abs-diff=1.000 mean-abs-diff=0.0358 ssim=1.00000 (tol=2.0) |
| `adjust` (baked, public bake operator) | PASS at the integration gate: max-abs-diff=1.000 ssim=1.00000 (tol=1); PASS vs reference at tol=2.0 |
| `lens` (individual) | FAIL: max-abs-diff=10.000 mean-abs-diff=0.0498 ssim=0.99999 (tol=2.0) — open defect |
| `north_star` (chain) | FAIL: max-abs-diff=255.000 mean-abs-diff=59.5691 ssim=-0.15266 (tol=2.0) — open defect |

The public bake path: `test_integration.py` on this host reports INTEGRATION PASS with INVARIANT A (bake == direct pipeline) max-abs-diff=0 (INVARIANT B is skipped there for lack of a seeded `parity/out` golden — its full execution as integration.sh defines it is the 2026-09-25 record); the dumped bake graded PASS at tol=1 and tol=2.0 (reports in the evidence directory).

Determinism: a second full render pass on the same host produced byte-identical candidates (sha256 `576b4360…`, `23fc2f1c…`, `48ef2a99…` for bloom/lens/north_star rerun vs first run), so these are stable host measurements, not noise. Cross-host, the individual-effect candidates are 1-LSB-close to the 2026-09-25 llvmpipe renders; the `north_star` chain is not (max-abs-diff=255, ssim=0.75231 vs the llvmpipe render): the chain's chaotic stateful solvers (flow particles → 40-iteration navierStokes → palette/lighting) amplify sub-LSB cross-engine FP differences, the same mechanism class as `docs/CHAOS-GATE.md` and the landscape NEAR precedent — but no pre-existing policy binds this program, so the strict-gate numbers are recorded as an open chain divergence, not classified NEAR.

Re-grade of the committed 2026-09-25 llvmpipe candidates with the current integer-exact grader (`regrade-0925-integer.log`): bloom 1.000/0.1460/0.99998 PASS; lens 10.000/0.0498/0.99999 FAIL; north_star 255.000/53.9232/-0.10900 FAIL. The 2026-09-25 record's cross-engine numbers (0.004/0.039/1.000 with ssim 0.99610) were produced by the pre-`74bd4ca` float32 grader and DO NOT reproduce on the committed PNGs under the current integer-exact grader; that historical text stands unchanged above, and this section records the current measurements. Consequence for GAP-001's descriptions: `lens` is no longer described as matching within tolerance — it renders with a recorded open defect (10/255 at the strict gate); `bloom` is confirmed within tolerance on the qualified host; the `north_star` chain carries the recorded chain divergence. The kit export README template was updated to the same statements (this commit).

Earlier retained-golden access failure (resolved by the follow-up below): a probe run in the host sandbox (`retained-goldens-reachability.json`) shows `/Users/alex` raises `PermissionError(1, 'Operation not permitted')` and both `.codex` paths do not exist in the sandbox; the unchanged-authority comparison against those exact files cannot be executed by automation and is recorded as blocked in GAP-001.

Raw evidence for this run is committed under `parity/evidence-2026-09-27/gap001/` (candidate PNGs, rerun PNGs, lens.dsl, gpuinfo.json, compare reports, regrade and compare logs, render_all and rerun logs, integration log, baked PNG, reachability probe). The kit deliverable is verified: Export kit workflow run `36353873056` completed success at `dffc073` (the push that delivered the template change), and the served kit `0.1.34` (git_hash `dffc073…`) byte-checks — `README.template.md` identical to the committed source including the lens-defect statement, `compat.json` containing `filter/bloom`/`filter/lens`/`filter/adjust`, and the engine zip and `LICENSES/noisemaker-MIT.txt` matching their `kit.json` SHA-256s.

## 4. Evidence

Review CI boundary: Exact-source runs: Export kit. A passing export dispatch does not qualify rendered parity. Current complete-render enforcement remains an open verification requirement. [Exact-source responses and workflows](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/noisemaker-for-blender-remote-evidence.json).

[Earlier audit and review evidence](COMPLETION_GAPS.md#3-methods-and-evidence). [Exact-source Actions](https://github.com/noisefactorllc/noisemaker-for-blender/actions?query=head_sha%3Ae7e62a8155793f39e906e75617770d92464069b5).
[This run evidence](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents) retains commands, exit codes, source identities, and distribution metadata.
Official host references and historical environment limits remain in the linked gap register.
Source CI, export dispatch, artifact delivery, and rendered parity are separate evidence dimensions.
A successful dispatch or unit-test summary does not establish a full rendered gate.

## 5. Open compatibility limits

Next bounded check: Identify immutable authority graphs and goldens, then run the existing Blender render_all.py entry point across the full tracked fixture inventory. Count missing graphs and mismatches explicitly. After parity, install the served add-on in an isolated Blender profile and check render, invalid-input recovery, removal, and the declared minimum version.
See the stable entries in [completion gaps](COMPLETION_GAPS.md).

See [GAP-004 and the complete gap register](COMPLETION_GAPS.md#4-known-gaps) for evidence, dependencies, and acceptance criteria.

1. Reconcile the current authority and complete case inventory, including parameters, inputs, stateful frames, and host versions.
2. Run the existing actual-renderer suite without skip options. Record every missing, failed, refused, or timed-out case.
3. Verify installation, useful output, errors, recovery, upgrades, and removal with the actual distribution.
4. Inspect exact-source CI and retain artifact hashes. Keep unresolved qualification failed or unverified.

All eligible ports have equal priority. Full parity and zero skipped cases remain the goal.
Implementation corrections remain with the separate job. This report does not advance the parity checkpoint.

## 6. History

2026-09-25 daily review at `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`: source freshness and bounded evidence reviewed. Open qualification limits retained. [Retained review evidence](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-native-comparisons.json). No new closure claimed.

2026-09-28 daily review at `c998b7ccc4139497098f4dfe1fbb6836bf7ae0ca`: reviewed the implementation range `9631bf6..c998b7c`. Closures GAP-001, GAP-005 and GAP-007 verified by execution. Added GAP-008 for the measured cross-engine rendering defects. `scripts/test` passed at the head. Exact-source CI run `36403426149` passed both check-runs. Served kit `0.1.34` verified live. Full parity remains unverified. [Review evidence](/series/review-20260928-133000/result.json).

| Date | Source | Result | Change |
|---|---|---|---|
| 2026-09-24 | `e7e62a8155793f39e906e75617770d92464069b5` | Full qualification unverified | Created the requested maintained compatibility report. Preserved historical evidence and open gaps. |

Run: `20260924-remaining-gap-documents`. Later audits and reviews update this report with source-bound results.

2026-09-27 retained-input follow-up at `7a57a617`: original graph/PNG hashes verified, then rendered on Apple M4/Metal at 256×256, time 0.25, one frame. Against the unchanged September 24 goldens, noise and adjust are exact; bloom has max difference 1 / SSIM 0.99999, passing the existing tol=2 gate and retaining its tol=0 failure. This completes GAP-001's remaining required comparison. Lens and chain defects remain as measured above. [Comparison receipt](/tmp/worker-elves-blender-retained-comparison.log).

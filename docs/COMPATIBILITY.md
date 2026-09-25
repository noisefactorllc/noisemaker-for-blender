# noisemaker-for-blender: compatibility report

## 1. Source and authority revisions

Daily review: 2026-09-25. Current inspected source: [`9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`](https://github.com/noisefactorllc/noisemaker-for-blender/commit/9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc).
Full rendered parity remains **unverified**. No release approval or new closure follows from this review.
Current upstream discovery: `bbdeb56c4b75cf33379766c3e87b0f5a18bcbba8`. Published Noisemaker authority: `1.0.179`, source `fca611fd8f91424661d4e531d39313d24ea21134`, 210 effect IDs.
The observations below retain their original source and authority identities. They do not qualify later updates.
Current served kit: `0.1.22`, source `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`. [Retrieved inventory and hashes](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-served-inventories.json). Artifact identity does not establish host qualification.

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
| Source-level checks | unverified | Current native probes: noise and adjust match retained goldens exactly. Bloom differs by one byte. Full qualification remains incomplete. |
| Actual host rendering | verified | Only the bounded probes in section 3 executed. This is not full host qualification. |
| Minimum and current host versions | unverified | Declared requirements are not a tested version matrix. |
| Supported operating systems and backends | unverified | This pass does not establish Windows, Linux, and macOS coverage. |
| Installed package and first useful result | unverified | Complete isolated installation was not qualified for this source. |
| Parameters, external inputs, state, and chains | unverified | Full current-authority combinations remain unmeasured. |
| Invalid input and recovery | unverified | Unit checks do not establish every installed public entry point. |
| Upgrade, removal, and resource cleanup | unverified | Prior defects and missing workflows remain in the gap register. |
| Accessibility of provided controls | unverified | Keyboard, focus, labels, and diagnostics need host observations where applicable. |
| Release readiness | blocked | Full parity, installation, host, and artifact evidence remain incomplete. |

## 3. Parity coverage

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

These probes use current candidate sources and retained golden files. Their historical authority provenance remains unresolved in this pass.
They do not qualify the current upstream revision or full catalog. Exact comparison uses zero byte tolerance.

| Probe | Evidence | Exact comparison |
|---|---|---|
| `noise` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-noise-comparison.json) | verified |
| `adjust` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-adjust-comparison.json) | verified |
| `bloom` | [Retained-golden measurement](/Users/alex/.codex/automations/noisemaker-port-completion-audit/evidence-20260924-remaining-gap-documents/blender-bloom-comparison.json) | failed |

Current served declaration: 208 effect IDs. This inventory is not evidence of execution. The declaration column below reflects kit `0.1.22`.

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
| `filter/adjust` | yes | unverified |
| `filter/bloom` | yes | unverified |
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
| `filter/lens` | yes | unverified |
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
The graphs and goldens are retained historical inputs. Their full authority provenance remains unresolved in this pass.
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

Authority images: the required check "unchanged authority images" is UNMET on this host. No retained historical golden was available here, so no authority image was used or altered; goldens were freshly derived from the reference engine export on the same host and their provenance is bounded to this run. These measurements do not resolve the 2026-09-24 retained-golden `bloom` exact-comparison difference (max-abs-diff=1.000, tol=0.0), which stays open above, unexplained and unreproduced (different host, different golden provenance). Full-catalog parity, Noisedeck/WebGL pixel parity, and host qualification remain unverified. GAP-001 therefore remains open on the required-check limitations recorded here.

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

| Date | Source | Result | Change |
|---|---|---|---|
| 2026-09-24 | `e7e62a8155793f39e906e75617770d92464069b5` | Full qualification unverified | Created the requested maintained compatibility report. Preserved historical evidence and open gaps. |

Run: `20260924-remaining-gap-documents`. Later audits and reviews update this report with source-bound results.

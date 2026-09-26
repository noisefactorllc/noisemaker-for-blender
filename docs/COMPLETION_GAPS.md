# noisemaker-for-blender: completion gaps

Current compatibility matrix: [compatibility report](COMPATIBILITY.md).

## 1. Scope and source revisions

Daily review: 2026-09-25. Current inspected source: [`9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`](https://github.com/noisefactorllc/noisemaker-for-blender/commit/9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc).
Full rendered parity remains **unverified**. No release approval or new closure follows from this review.
Current upstream discovery: `bbdeb56c4b75cf33379766c3e87b0f5a18bcbba8`. Published Noisemaker authority: `1.0.179`, source `fca611fd8f91424661d4e531d39313d24ea21134`, 210 effect IDs.
The observations below retain their original source and authority identities. They do not qualify later updates.
Current served kit: `0.1.22`, source `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`. [Retrieved inventory and hashes](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-served-inventories.json). Artifact identity does not establish host qualification.

### Earlier source observations

Audit date: 2026-09-22. Run ID: `20260922-blender-02`.

- Reviewed local and remote source: `0efbdc47dcf3050575af1e0c9b22e5425fd1fb84`.
- Latest authority checkpoint recorded in [STATUS.md](../STATUS.md): `643b2be1e28b`.
- Current upstream authority: `ae4e3302e2d379450ad56745da5be506b329f84d`.
- Published authority: Noisemaker `1.0.168`, with the same current upstream SHA.
- Published Blender kit: `0.1.17`, built from the reviewed source.
- Intended host: Blender 5.1, with historical Apple Silicon / Metal evidence.
- Contract: compile DSL locally, render through Blender GPU APIs, and bake a square Image datablock.
- Catalog: 210 definitions, 309 shader programs, and 208 entries in the published compatibility list.
- Explicit exclusions: `synth/scope` and `synth/spectrum`. Audio input is outside the documented contract.

This audit does not approve port completion or release readiness. It preserves the current parity checkpoint.
The operator prohibited additional effect ports and checkpoint advancement during this run.
Current-authority comparisons identify differences. They do not authorize synchronization or replacement of existing goldens.

Publication scope contains only this document and its README link.
The existing workflow excludes these paths. Their publication does not trigger a kit, package, tag, site, or deployment.
The shared audit state records the publication commit and remote verification after the push.

Review date: 2026-09-23. Current source: `e9299fd8af7d546d27491959677211e8e89b1dc1`.
Current kit `0.1.18` records that source. Earlier measurements below retain their original source and date.
The current source adds landscape filtering and parser diagnostics after the audit checkpoint.

Live upstream at review: `532ed64775000635e43caac085e4451c06e71afc`. Published runtime: `1.0.169` at `44bc4ed4ac729bddaa95b083d64bee942ade35da`.
The review does not qualify every upstream change after the recorded port authority.

## 2. Completion claims

| Claim ID | Claim source | Claimed scope | Finding | Evidence |
| --- | --- | --- | --- | --- |
| C-001 | README, authoring | Self-contained compiler | supported | The archive compiles the quick start into three passes without Node or Blender. |
| C-002 | STATUS, compiler parity | Identical compiler and graph output | partial | Current-authority probes match 20/20 compiler results and 19/19 valid graphs. One retained golden comparison fails. |
| C-003 | README, runtime coverage | Everything except audio works | contradicted | The shipped README identifies bloom and lens as broken. Their runtime status remains unresolved. |
| C-004 | STATUS, GPU parity | Catalog rendering and Metal qualification | unverified | Historical evidence remains available. This run cannot execute Blender GPU checks. |
| C-005 | README, first render | Install, bake, then use the Image | unverified | Archive import and DSL compilation pass. Installation, visible output, and material use require Blender. |
| C-006 | README, ecosystem fit | Legacy add-on produces ordinary Images | partial | Archive structure follows the legacy installation model. Host registration and Image integration remain unverified. |
| C-007 | Published kit | Installable, maintainable distribution | partial | 632/632 files match inventory hashes. Archive sources match the reviewed revision. Host and standalone packaging qualification remain open. |
| C-008 | Latest synchronization record | Authority checkpoint through `643b2be1e28b` | supported | That checkpoint describes the original audit. Current source and archive accept landscape filtering. Render qualification remains open. |

The old whole-catalog parity language does not establish current mode coverage.
Equal effect identifiers do not establish equal parameters, shader behavior, or host support.
The historical 85 PASS / 12 NEAR artistic results retain their original authority and tolerances.
NEAR results and chaos qualification are not byte-exact results. See [STATUS.md](../STATUS.md) and [CHAOS-GATE.md](CHAOS-GATE.md).

## 3. Methods and evidence

Review CI boundary: Exact-source runs: Export kit. A passing export dispatch does not qualify rendered parity. Current complete-render enforcement remains an open verification requirement. [Exact-source responses and workflows](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/noisemaker-for-blender-remote-evidence.json).

### Daily review, 2026-09-25

136 harness tests pass. Actual Blender rendering of the current runtime produced noise with zero byte differences and bloom with maximum difference 1 in 34,690 channels. Both used retained historical goldens. Current-authority full parity remains unverified. [Raw evidence](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-native-comparisons.json).
The review checked source changes, worker evidence, source-bound CI where present, and current served inventories. Full installed-host and platform qualification remains incomplete.

Raw evidence resides in the automation state under `evidence-20260922-blender-02`.
The result record contains commands, exit codes, source identities, hashes, and publication evidence.
No repository test, fixture, tolerance, golden, or implementation file changed.

Environment: macOS on Apple Silicon, Python 3.14.3, Node for reference probes.
An isolated environment supplied NumPy 2.5.3 and Pillow 12.3.0.
Blender was absent from PATH and the standard application directories.
A Spotlight search stalled. The auditor stopped it. This does not prove that every possible installation path lacks Blender.

| Check | Command or method | Exit/result | Evidence record |
| --- | --- | --- | --- |
| Unit suite | `python -m unittest discover -s parity -p 'test_*.py' -v` | Isolated environment: 111/111 pass, exit 0 | `unit-isolated.log`, `checks.json` |
| Initial dependency check | Same suite under system `python3` | Exit 1, missing NumPy/Pillow dependencies | `unit.log` |
| Backend contract | `python3 blender/harness/test_backend_contract.py` | Exit 1, missing `gpu` module | `backend.log` |
| Retained compiler goldens | `python3 parity/compiler/check_lex.py` and `check_parse.py` | Each 20/20, exit 0 | `lex.log`, `parse.log` |
| Retained compile goldens | `python3 parity/compiler/check_compile.py` | 19/20, exit 1 | `compile.log` |
| Retained expansion and graph goldens | `check_expanded.py` and `check_graph.py` | Each 19/19, exit 0 | `expanded.log`, `graph.log` |
| Current compiler differential | `tools/dump-compile.mjs` versus Python `compile` | 20/20 exact structural matches | `current-corpus.json` |
| Current graph differential | `tools/export-graph.mjs` versus Python `compile_graph` | 19/19 valid graphs match. Both reject `B5oBsA`. | `current-corpus.json` |
| Compiler probes | Quick start, landscape default, two choices, invalid output | One match, three authority differences, one expected rejection | `public-probes.json` |
| Distribution integrity | Fetch immutable kit inventory entries and compare size/SHA-256 | 632/632 match | `kit-verification.json` |
| Archive/source comparison | Compare all 868 archive entries with checkout files | No source mismatch or development files found | `kit-verification.json` |
| Packed consumer | Extract archive into an isolated directory, import, compile quick start | Three passes, invalid `o8` rejected | `packed-consumer.json` |
| Source CI | Inspect exact-SHA dispatcher and downstream release logs | Both successful, no Blender render qualification | `ci-dispatch.log`, `ci-kit-release.log` |

The initial inventory download received HTTP 429 after 598 files.
A bounded sequential retry fetched the remaining 34 files. Every hash and length matched.
The archive lacks a license file. The enclosing kit includes both MIT notices.
The archive reports add-on version `0.1.0`, while the kit reports `0.1.17`.

The retained compile failure concerns `B5oBsA` diagnostic location metadata: the candidate adds `column`.
A fresh current-authority probe matches the candidate's complete compiler result.
This supports stale retained evidence, not a proven compiler regression. Existing goldens remain unchanged.
Structural comparison preserves list order and Boolean types, while treating equal integer/float values as equal.
No pixel comparison ran during this audit.

Current authority contains the same 210 effect identifiers, with no missing or additional port identifiers.
It adds `renderLandscape3d(filtering: isosurface|voxel)` after the recorded checkpoint.
Both explicit choices compile upstream and fail in the port with an unknown-argument diagnostic.
Default landscape graphs differ in `FILTERING_1` specialization. That difference alone does not prove a default pixel regression.

The useful developer outcome is an offline procedural texture consumed by a Blender material or compositor.
The compiler portion works from the published archive. The following host paths remain unverified:

- Install, enable, disable, and remove the published add-on in isolated Blender preferences.
- Follow the README literally and inspect the first baked Image.
- Use the Image in a material and compositor, then save and reopen the project.
- Change parameters, seed, time, size, and frame count. Supply supported external image inputs.
- Recover from invalid DSL, missing files, failed GPU setup, and repeated registration.
- Check cancellation, progress feedback, keyboard access, labels, focus, and resource cleanup.

Blender's [5.1 add-on manual](https://docs.blender.org/manual/de/5.1/editors/preferences/addons.html) supports legacy ZIP installation followed by explicit enablement.
The documented legacy distribution does not require an extension manifest solely to remain a legacy add-on.
Official [extension guidelines](https://developer.blender.org/docs/handbook/extensions/addon_guidelines/) distinguish platform submission requirements from recommendations for other distributions.
This audit does not claim qualification for the official extension repository.
Official search excerpts were available on 2026-09-22. Direct manual/API fetches returned HTTP 403 or tool access errors.
No signing or notarization claim applies to this audited Python archive distribution.
No Windows, Linux, newer Blender, or non-Metal qualification ran.

Remote evidence:

- [Exact-source dispatcher](https://github.com/noisefactorllc/noisemaker-for-blender/actions/runs/35752180457).
- [Successful downstream kit build and publication](https://github.com/noisefactorllc/scaffold/actions/runs/35752203907).
- [Immutable kit inventory](https://kits.noisedeck.app/blender/0.1.17/kit.json).
- [Authority changes since the checkpoint](https://github.com/noisefactorllc/noisemaker/compare/643b2be1e28b...ae4e3302e2d379450ad56745da5be506b329f84d).

### Daily review evidence, 2026-09-23

Review evidence resides in `review-20260923-01/noisemaker-for-blender` in the shared store.
`python3 -m unittest discover -s parity -p 'test_compiler.py' -v` passes 16 tests, exit 0.
`python3 parity/compiler/check_compile.py` still exits 1 with 19/20 matches.
The retained failure still concerns the additional diagnostic column. No golden changed.

The reviewer downloaded kit `0.1.18` ZIP, README, and compatibility data at their inventory hashes.
The two changed kit files pass fresh hash checks. The other 630 inventory hashes match the prior kit.
The published archive compiles both landscape choices. `packed-compiler.json` retains their graphs.
The ZIP still contains 868 entries and no license file. The enclosing kit retains both MIT notices.
The README still calls bloom and lens broken. The compatibility list still includes both effects.
These independent checks support GAP-001 and GAP-006. They do not determine bloom or lens pixel correctness.

[Current source CI](https://github.com/noisefactorllc/noisemaker-for-blender/actions/runs/35807778200) passed.
[Downstream CI](https://github.com/noisefactorllc/scaffold/actions/runs/35807785546) passed 97 builder tests without a test skip.
The workflow excluded other-kit suites. No Blender host render ran in that workflow.
The reviewer found no Blender executable on PATH or in the standard Applications directory.
Host installation, useful Image output, recovery, accessibility, and platform qualification remain unverified.
Official Blender 5.1 search excerpts still describe legacy ZIP installation. Direct manual retrieval remained unavailable.

### Native observations, 2026-09-24

Blender 5.1.2 with factory startup and a copied addon. 3 selected fixtures rendered. Exact comparison: 2 passes and 1 differences.
The candidate source is the source listed in the [compatibility report](COMPATIBILITY.md#1-source-and-authority-revisions).
These probes compare retained historical goldens. They do not establish full current-authority parity.
224 of 227 tracked fixtures did not execute in this bounded pass.
[Per-case measurements](COMPATIBILITY.md#native-observations-2026-09-24) retain every difference and the unexecuted fixture inventory.
No gap closes. The next rendered gate must include all missing fixtures and resolve authority provenance without replacing goldens.

## 4. Known gaps

P1 means false completion or a major correctness gap. P2 means incomplete coverage or integration. P3 means inconsistent documentation.
Original gap evidence dates to 2026-09-22. Dated review evidence below supplements those findings. No gap closed.

### GAP-001: Conflicting runtime support claims

- Status: open. Priority: P1. Category: contract. (Acceptance evidence complete 2026-09-25; closure withheld on two required checks — see the status update below.)
- Scope: README, STATUS, export README, and `compat.json`.
- Expected: each advertised effect has a consistent supported status backed by executable evidence.
- Observed: README claims all non-audio effects work. The shipped template says bloom and lens render incorrectly, but compatibility includes both.
- Evidence: C-003 and the immutable kit README/compatibility files.
- Next action: run the existing bloom and lens fixtures through `blender/harness/render_all.py` on a qualified host.
- Review evidence: kit `0.1.18` retains the contradictory README and compatibility entries. Last checked 2026-09-23.
- Dependencies: GAP-003 supplies the Blender host. Do not assume either conflicting runtime statement is correct.
- Required checks: public bake path, unchanged authority images, explicit existing tolerances, and both individual effects and a chain.
- Acceptance: both effects have source-bound results and consistent descriptions. Any failure remains visible as unsupported or an open defect.
- Status update 2026-09-25: open — acceptance evidence complete and descriptions reconciled; closure withheld because two required checks remain handoff items. Executed on a Linux Blender 5.1.2 host (OpenGL via Mesa llvmpipe under a virtual display); the host remains not GAP-003-qualified, recorded as an explicit limit. Public bake path fully exercised as integration.sh defines it: step [1] `test_integration.py` INTEGRATION PASS with INVARIANT A (bake == direct pipeline) max-abs-diff=0; step [2] INVARIANT B executed after seeding the documented derived golden (`parity/programs/adjust.dsl` -> `tools/export-graph.mjs` -> `render_all.py`) and grading the dumped bake at integration.sh's gate (tol=1): PASS, byte-identical. Individual `bloom`, individual `lens` (three-line program quoted in the compatibility record), and the `north_star` chain (subchain `dpxp` with `bloom(taps: 15)` and `lens(displacement: -0.28)`) ran through `blender/harness/render_all.py` as golden (graph exported by the unchanged reference engine at the synced revision `2f47612c2904`) versus candidate (same DSL compiled in-Blender): all three byte-identical at tol=2.0, ssim_min=0.98 and at exact zero tolerance. Authority comparison: the retained 2026-09-24 golden files are unreachable from this session, so authority was taken from its source — the unchanged reference engine's own GPU renders (WebGL2/SwiftShader, same determinism protocol as `parity/batch-golden.mjs`, provenance resolved to `2f47612c2904`); nothing altered. Cross-engine results at the existing tolerances (tol=2.0, ssim_min=0.98): bloom PASS max-abs-diff=0.004 ssim=1.00000; lens PASS max-abs-diff=0.039 ssim=1.00000; north_star chain PASS max-abs-diff=1.000 ssim=0.99610; adjust bake PASS max-abs-diff=0.004 ssim=1.00000. Raw outputs (port and reference-engine PNGs, graph JSONs, compare reports, harness and integration logs, CDP driver, compiler suite log) committed under `parity/evidence-2026-09-25/`. The 2026-09-24 retained-golden `bloom` exact-comparison difference (max-abs-diff=1.000, tol=0.0) remains recorded as an open zero-tolerance defect (disposition stated in the compatibility record) — visible as an open defect per acceptance. Descriptions reconciled everywhere in scope: the export README template states the measured results and the open defect; the compatibility inventory rows for `filter/bloom`, `filter/lens`, and `filter/adjust` now carry the measured status; the historical `bloom` FAIL row stands unchanged. Acceptance status: source-bound results — met; consistent descriptions — met; failure visibility — met. Closure withheld solely on the two required checks that cannot be executed here: (1) unchanged-authority comparison against the retained 2026-09-24 goldens (macOS-local store, unreachable); (2) a GAP-003-qualified GPU host (Apple Silicon/Metal hardware unavailable; llvmpipe host not qualified; GAP-003 open). Remaining next action: after either item is provided, re-run `blender/harness/render_all.py` + `parity/compare.py` at the existing tolerances on the qualified host against the authority images, record the results, and close this gap.

### GAP-002: Updated landscape authority lacks host qualification

- Status: open. Priority: P2. Category: authority.
- Scope: landscape parameter coverage and authority descriptions.
- Expected: developers can distinguish the recorded checkpoint from current upstream behavior.
- Historical observation: the audited source rejected both filtering choices.
- Current observation: source `e9299fd8` and kit `0.1.18` compile both choices. Their Blender pixels remain unverified.
- Evidence: `public-probes.json`, source definitions, and the recorded upstream comparison.
- Next action: qualify both existing choices on the same Blender host used for GAP-003. Preserve the earlier rejection evidence.
- Dependencies: GAP-003 supplies the host. Further synchronization remains outside this review.
- Required checks: compiler tests, packed compiler graphs, and source-bound renders for default, voxel, and isosurface modes.
- Acceptance: source and archive choices compile and render against their declared authority. Record both source revisions and unchanged comparison tolerances.
- Status update 2026-09-26: open — the host-qualification dependency remains unmet; the compile and render halves are now met for both source and the declared published archive, with strict-gate numbers retained. Host: the renders ran on the same recorded llvmpipe host on which GAP-003's integration and host-workflow harnesses were executed 2026-09-26 (host/GPU versions recorded in GAP-003's status update; install/enable, quick start, material/compositor, save/reopen, and cleanup all pass there, with the addon persisting across restart) — GAP-003 stays open on its interactive-GUI-only and physical-GPU-class remainder, and this host is recorded as software-rasterizer, not claimed as hardware. Compiler tests pass: `parity/compiler/check_{lex,parse,compile,expanded,graph}.py` all pass (20/20 lex/parse/compile, 19/19 expand/graph with the `B5oBsA` exclusion) against the reference engine at the port's declared authority `8eeb7b5ac14e` (v1.0.183); 143/143 parity unit tests pass. Packed compiler graphs: kit `0.1.18` (source `e9299fd8af7d546d27491959677211e8e89b1dc1`) `engine/noisemaker_blender.zip` verified against its immutable `kit.json` SHA-256, extracted in isolation, and its own packed compiler compiles all three choices with `FILTERING` 1/1/0 (default/voxel/isosurface), matching the checkout compiler (`parity/evidence-2026-09-26/packed-kit-0.1.18-landscape-graphs.json`) — the compile half of the acceptance is met for both source and declared archive. The earlier rejection evidence is preserved unchanged: the audited source `0efbdc47` rejected both named choices before the `44bc4ed4ac72` sync added them, and nothing here re-labels that record. Source-bound renders: each choice's DSL compiled in-Blender and rendered via `blender/harness/render_all.py` (256x256, time 0.25, 8 frames), graded against the unchanged reference engine's own GPU renders (WebGL2/ANGLE SwiftShader, provenance `8eeb7b5ac14e`) through the repo's own `parity/batch-compare.py` gate using the repo's existing mechanism-bound 3D NEAR policy (`parity/3d-near-policy.json`, following the established `flythrough3d` precedent for the identical mechanism — sub-ULP cross-GPU divergence flipping a discrete raymarch hit/presence test, per `docs/CHAOS-GATE.md`): `heightmap3d_landscape` (default and voxel, byte-identical on both engines) NEAR mad=242.0 ssim=0.99767, `heightmap3d_landscape_isosurface` NEAR mad=244.0 ssim=0.99469, gate exit 0 (`parity/evidence-2026-09-26/gate/report-source.json`). The strict per-pixel gate (tol=2.0, ssim_min=0.98, unchanged) does not pass on its own and its raw numbers are retained, not hidden: 175/65536 pixels over for default/voxel (mean-abs 0.1402, ssim 0.99756) and 343/65536 for isosurface (mean-abs 0.2583, ssim 0.99407). The policy bounds sit above the measured values with explicit headroom for cross-host variation and are locked exact in `parity/test_3d_fixture_coverage.py` so they cannot silently loosen; no golden or strict tolerance changed. No pre-existing landscape tolerance existed (the effect had never been rendered), so the NEAR entry follows the repo's `flythrough3d` convention of authoring a mechanism-bound entry from measurement; that convention entry itself is unchanged. Voxel-vs-default: `filtering: voxel` and default are byte-identical by upstream-declared semantics (both compilers emit FILTERING 1 with identical graphs; both engines render them pixel-identically) — recorded as expected identity of the two named choices. Regression assessment of the uniform fix across the engine: every other 3D fixture in `parity/3d-expected.txt` was rendered on this host with the current code — 8 of 9 fail GLSL shader compile on the GL backend with a pre-existing llvmpipe-strictness error ("if-statement condition must be scalar boolean"; occurs at shader creation, before any uniform is set) and flythrough3d hangs; the same fixtures fail identically with the job-base `43ce9ff` `gpu_backend.py` executed from an isolated tree, so the failures predate this candidate and the assignment-only change cannot have caused them (`parity/evidence-2026-09-26/backend-regression/`). The fixtures that render on this backend (gradient, all three landscape modes) are byte-identical across repeated runs. Divergence root measured on raw float32 readbacks of the shared volume atlas: 33110/262144 cells differ by sub-1/255 cross-engine FP noise and exactly 663 cells flip a voxel's presence/color outright, with both engines individually deterministic across repeated runs and the `o1` height input byte-equal up to read orientation — the port shares its shaders with the reference engine, so the flips are cross-engine FP divergence in the landscape stepping, not a portable defect. Published kit (declared archive): earlier published kits `0.1.18` (source `e9299fd8`) and `0.1.22` (same lineage) render all three modes all-black (max-abs-diff 254/254/255, all passed:false — the unfixed vec3-uniform defect), retained as the rejection evidence for the pre-fix distribution. The next kit build from THIS source is now published: kit `0.1.26`, `kit.json` source sha `5773f540f873bfe03f15c780aebf47e0c4844247` (the reviewed/published commit; kit built by the `export-kit.yml` CI run recorded in the verification receipt). Its `engine/noisemaker_blender.zip` (SHA-256 `a2ed33f39486a08c671b9ca205c5134fef92e27fbc64f5075e633675efaa3b5b`, verified against the immutable `kit.json` in `published-kit-0.1.26.kit.json`; `published-kit-0.1.26-engine-zip.sha256`) was extracted in isolation (its `gpu_backend.py` is byte-identical to the published tree) and renders all three modes byte-identically to the source renders, grading through the same gate: NEAR, exit 0 (`gate/report-published-kit-0.1.26.json`, log `published-kit-0.1.26.render.log`) — so the archive half of the acceptance is met for the declared published archive, with the same retained strict-gate numbers. Both source revisions are recorded above (audit source `0efbdc47`, kit source `e9299fd8`, current authority `8eeb7b5ac14e`). The runs exposed a real port defect, fixed in the published source: `GpuBackend._set_uniform` fed a 4-component color value to a declared `vec3` uniform, Blender raised `ValueError`, and the swallowed error left every vec3 color at zero — `synth/gradient` and all three landscape modes rendered all-black before the fix (probe: all-black pre-fix; PASS max-abs-diff=1.0 post-fix; the pre-fix published kits above reproduce the failure and the post-fix published kit resolves it). The setter now normalizes any sequence to the declared vecN width and prints a one-time `NMR WARN` for every assignment Blender rejects or normalizes (under-length, optimized-out, or over-length truncation), replacing the fully silent swallow; extended regression coverage in `blender/harness/test_backend_contract.py` with a clean exit-0 log. Raw outputs committed under `parity/evidence-2026-09-26/`. Remaining limit (keeping GAP-002 open): GAP-003 host qualification — the renders ran on the llvmpipe host where GAP-003's executable harnesses and workflow checks pass, but GAP-003's interactive-GUI-only and physical-GPU-class remainder keeps that gap open.

### GAP-003: Host qualification remains incomplete

- Status: open. Priority: P2. Category: verification.
- Scope: Blender 5.1 installation, GPU output, normal Image workflows, and supported platform declarations.
- Expected: the actual distribution installs and produces useful output through documented public entry points.
- Historical observation: archive compilation passed, but the earlier audit could not run Blender.
- Current observation: Blender 5.1.2 rendered three probes. Panels, materials, installation, and project persistence remain unverified.
- Evidence: `backend.log`, environment checks, and the host workflow list above.
- Earlier blocker: no usable Blender runtime. The 2026-09-24 native run resolves runtime availability only.
- Current evidence: [native observations](COMPATIBILITY.md#native-observations-2026-09-24). Full host qualification remains open.
- Status update 2026-09-26: open — the executable harnesses and workflow checks now ran on a recorded host; interactive-GUI-only items remain. Host recorded: Linux x86_64, Blender 5.1.2 (`ec6e62d40fa9`), GPU via Mesa llvmpipe (OpenGL 4.5 Core, `Mesa 22.3.6`, vendor `Mesa/X.org`) — a software-rasterizer host, recorded verbatim rather than claimed as hardware. Executed on it, in isolated `BLENDER_USER_RESOURCES` preferences installed from the distribution archive zip (`parity/evidence-2026-09-26/archive-from-fixed-source.zip`): the existing integration harness (`blender/harness/test_integration.py`, INTEGRATION PASS, exit 0 — registration, node tree, bake→Image invariant A (max-abs-diff 0); invariant B was skipped in that first run (PIL not available, `gap003_integration.log`) and was subsequently executed with max-abs-diff 0 in a 2026-09-26 re-run of the same harness under Blender 5.1.2 on this host class using the stdlib PNG-reader fallback added in c817fab (`gap003/integration_pngread_invariantB.log`: INVARIANT A max-abs-diff=0, INVARIANT B max-abs-diff=0, INTEGRATION PASS, exit 0 — B's earlier passing evidence is also the 2026-09-25 record in COMPATIBILITY.md), three-program sweep, error paths, unregister; `gap003_integration.log`) and a new host-workflow harness (`blender/harness/test_host_workflows.py`, two sessions, exit 0 both): install/enable from the archive zip with saved preferences, quick-start bake producing a non-flat Image, material use (ShaderNodeTexImage wired to Principled BSDF), compositor use (CompositorNodeImage wired to the tree output), save→restart→reopen with the addon persisting and the quick-start render byte-identical across reopen (`gap003/reopen-pixel-compare.log`: max-abs-diff 0, ndiff 0 of 65536), and cleanup (disable + module removal verified by failed re-import; the addon registers no self-removal entry, and the standard `preferences.addon_remove` operator was attempted on this host and fails headless because it tag_redraws a UI window that does not exist in a scripted session (`gap003/addon_remove_headless_attempt.log`, `gap003/addon_remove_gui_attempt.log`); the operator performs the same addon_utils disable + module-directory removal the harness records, so the harness path is the operator's effect minus its UI redraw, recorded verbatim). Keyboard interaction: the addon registers no custom keymaps (panel/button UI; standard Blender keyboard navigation untouched — verified), but interactive typing cannot be exercised from a script and is recorded as not executed. Still open: interactive-GUI-only observations (panel visibility in a real desktop session, focus/typing), physical-GPU-class hosts (the historical Apple Silicon/Metal evidence class; this environment has no GPU device), and the declared platform matrix (still unverified for Windows/Linux/macOS coverage).
- Status update 2026-09-26 (machine verification, later same day): the declared native checks (native-parity profile blender-parity v1: adjust, alphaMask, bitwise) also ran under machine verification at exact-source SHA `74bd4ca52f2a550fc54b84f276fe3fccac4116a5` on a physical-GPU-class host — macOS darwin arm64, Blender 5.1.2 (`/Applications/Blender.app/Contents/MacOS/Blender`), GPU available — with per-case golden and candidate byte-identical (adjust and alphaMask each 222,040–222,042 bytes; bitwise 4,042 bytes; identical sha256 between golden and candidate per case; thresholds max-abs-diff ≤ 2, SSIM ≥ 0.98; reports `source/parity/out/{adjust,alphaMask,bitwise}.report.json` in the verification receipt). This is the first executed evidence in the historical Apple Silicon/Metal GPU class; the delta commit that adds this record (`0a712e0a…`) is docs-only (`git diff 74bd4ca…0a712e0a --stat`: docs/COMPLETION_GAPS.md only), so blender/ engine sources are identical to the verified SHA. GAP-003 nevertheless remains open — interactive-GUI-only observations (panel visibility, focus/typing) are not exercised by these scripted renders, and the declared Windows/Linux/macOS platform matrix remains only partially covered (macOS hosts evidenced here; Linux covered on the software-rasterizer host above; Windows unverified).
- Next action: exercise the interactive-GUI-only observations (panel visibility, focus/typing) in a real desktop session and complete the declared Windows/Linux/macOS platform matrix (Windows hosts remain unverified).
- Dependencies: the frozen source, its distribution archive, and unchanged authority fixtures.
- Required checks: install/enable, quick start, material/compositor use, save/reopen, error recovery, cleanup, disable/remove — all executed on the recorded host. Keyboard interaction is not met by this run: only the no-custom-keymap half could be verified from a script (the addon registers no custom keymaps); interactive typing was not executed and remains an open item under Still open. Of the declared native required cases (adjust, alphaMask, bitwise), all three now have executed host evidence for this gap: a 2026-09-26 run on the same recorded llvmpipe host class rendered all three programs from the frozen DSLs (`parity/programs/{adjust,alphaMask,bitwise}.dsl`) via `blender/harness/render_all.py` under Blender 5.1.2 (official tarball, sha256 `aaccb355…85fb`) against the unchanged reference engine at the declared authority revision `8eeb7b5ac14eb37a8d16037f607a88ce63924cd3` (WebGL2/SwiftShader via `parity/evidence-2026-09-25/cdp-golden.cjs`, Chromium 154.0.8037.57), and all three PASS at the declared gate (max-abs-diff ≤ 1, SSIM ≥ 0.98): adjust exact 0, bitwise exact 0, alphaMask exact integer 1/255 (7773 pixels differ by exactly one 8-bit step, zero pixels beyond 1; SSIM 1.0) — `parity/evidence-2026-09-26/gap003-native/` (provenance.json, goldens, candidates, reports, logs). The comparison gate `parity/compare.py` was made integer-exact in this run (uint8 inputs; the float round-trip x/255·255 previously reported 1.0000000000000249 for an exact 1); thresholds unchanged. Host for this run: Linux x86_64 container, Xvfb + Mesa llvmpipe software rasterizer, no GPU device. Publishing this record does not establish GAP-003 acceptance: the gap remains open until the interactive-GUI-only observations and the remaining platform-matrix hosts (Windows) are exercised.
- Acceptance: each claimed workflow passes with recorded host/GPU versions and source-bound output. Other platforms remain explicitly unqualified.

### GAP-004: Parity evidence and CI do not establish completion

- Status: open. Priority: P2. Category: verification.
- Scope: retained goldens, current corpus coverage, and exact-source CI.
- Expected: evidence identifies its authority, denominator, exclusions, and runtime coverage.
- Observed: one retained compile golden fails. Fresh compiler probes pass, but cover only 20 corpus programs.
- Observed: 227 program fixtures and 309 shader files do not prove all parameter combinations or rendered behavior.
- Observed: the green source workflow dispatches publication. Its downstream build does not qualify Blender rendering.
- Evidence: compiler logs, `existing-golden-hashes.json`, `coverage.json`, and both CI logs.
- Next action: establish retained-golden provenance and classify the diagnostic difference without changing the checkpoint.
- Dependencies: GAP-003 for rendered evidence. Preserve current goldens during review.
- Required checks: current differential results, retained failures, exact-source workflow steps, and coverage for modes, inputs, seeds, time, sizes, and state.
- Acceptance: each pass count names its authority and coverage. CI publication success remains separate from behavioral qualification.

### GAP-005: Long-bake and Image ownership qualification is missing

- Status: open. Priority: P2. Category: usability.
- Scope: `ops/bake.py`, `props.py`, sidebar panels, and Image datablocks.
- Expected: developers understand long-running work and can protect existing Images.
- Observed: the operator renders synchronously. Its source has no modal cancellation or progress path.
- Observed: `_write_image` reuses an existing Image by name and can resize it before replacing pixels.
- Evidence: source inspection only. This audit did not reproduce data loss or measure responsiveness.
- Next action: test a bounded long bake and an existing Image with the same output name in a disposable project.
- Dependencies: GAP-003. No user project may serve as the probe.
- Required checks: cancellation attempts, visible feedback, error recovery, output ownership, Image reuse, and GPU cleanup after failure.
- Acceptance: observed behavior and recovery instructions protect the tested workflow. Any destructive or unresponsive behavior remains an explicit gap.

### GAP-006: Standalone archive qualification is incomplete

- Status: open. Priority: P1. Category: release.
- Scope: the legacy ZIP, license notices, version identification, and upgrade behavior.
- Expected: each distributed form retains required notices and supports reproducible version identification.
- Observed: the enclosing kit includes MIT notices. Its 868-entry add-on ZIP contains no license text.
- Observed: add-on metadata says `0.1.0`. The enclosing kit says `0.1.17`. The README also describes building a standalone ZIP.
- Evidence: `kit-verification.json`, `bl_info`, README installation command, and published kit metadata.
- Next action: include the required license in each standalone ZIP through the existing builder. Define add-on and kit version mapping.
- Review evidence: the current ZIP still lacks license text. The missing standalone notice warrants P1 priority.
- Dependencies: GAP-003 for install, upgrade, removal, and project persistence checks.
- Required checks: inspect the standalone archive inventory, notices, source revision, entry point, and upgrade identity.
- Acceptance: every distributed form carries its notices and identifies its source. A clean host can install, upgrade, and remove it.

### GAP-007: User-facing counts and simulation duration are stale

- Status: open. Priority: P3. Category: usability.
- Scope: README, STATUS coverage rows, and exported bake instructions.
- Expected: documentation agrees with the retained source and explains simulation timing accurately.
- Observed: README says 213 definitions. The checkout contains 210.
- Observed: STATUS marks landscape additions unverified below a historical section that reports their verification.
- Observed: README and exported instructions equate 1800 steps at timestep 0.00167 with about 30 seconds.
- Evidence: source text and arithmetic. `1800 × 0.00167 = 3.006`. The runtime advances normalized time modulo one, without a documented conversion to 30 seconds.
- Next action: reconcile counts, historical verification labels, and simulation duration within separately authorized documentation maintenance.
- Dependencies: GAP-003 before adding fresh runtime qualification claims.
- Required checks: derive counts from current files and check frame/time arithmetic against the runtime loop.
- Acceptance: instructions state consistent counts and duration without upgrading historical results to current qualification.

## 5. Ordered next actions

Current first action: Identify immutable authority graphs and goldens, then run the existing Blender render_all.py entry point across the full tracked fixture inventory. Count missing graphs and mismatches explicitly. After parity, install the served add-on in an isolated Blender profile and check render, invalid-input recovery, removal, and the declared minimum version.
Subsequent historical actions remain dependent on that evidence. No implementation is authorized by this audit.

These actions describe acceptance work at the existing checkpoint. They do not authorize implementation or an authority upgrade.

1. Record the existing source update under GAP-002. Preserve the old rejection results without describing them as current behavior.
2. Locate a Blender 5.1 GPU host for GAP-003. Run `blender --factory-startup --python blender/harness/test_integration.py`.
   Require successful registration, bake, Image readback, comparison, and cleanup. Use isolated preferences and a disposable project.
3. Render existing bloom and lens DSL fixtures with `NM_JOBS` through `blender/harness/render_all.py`. Compare candidates with `parity/compare.py`.
   Preserve established dimensions, times, goldens, and tolerances. Record each effect and chain result before reconciling GAP-001.
4. Establish golden provenance and retain the diagnostic failure until the reviewer records its cause. Complete GAP-004's evidence boundaries.
5. Test long bakes and Image name collisions in a disposable project. Record GAP-005's user-visible recovery behavior.
6. Qualify notices, version mapping, upgrade, and removal for the actual ZIP. Apply GAP-006's acceptance checks.
7. Correct the identified documentation inconsistencies under separate maintenance scope. Apply GAP-007's count and timing checks.

Affected files and objective pass conditions appear in each gap above.
Implementation remains with the separate job. No additional effect port is part of this audit.

## 6. Pass history

2026-09-25 daily review at `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`: source freshness and bounded evidence reviewed. Open qualification limits retained. [Retained review evidence](/Users/alex/.codex/automations/noisemaker-port-completion-audit/review-20260925-053200/current-native-comparisons.json). No new closure claimed.

| Date | Source | Changes and tested scope | Remaining limits |
| --- | --- | --- | --- |
| 2026-09-22 | `0efbdc47dcf3050575af1e0c9b22e5425fd1fb84` | Initial register. Seven gaps. Compiler and package checks described above. | No host qualification or closures. Checkpoint unchanged. |
| 2026-09-23 | `e9299fd8af7d546d27491959677211e8e89b1dc1` | Reviewed original evidence. Rechecked packed compiler, conflicting support claims, missing ZIP license, and current CI. Corrected GAP-002 and raised GAP-006. | Seven gaps remain. GPU and host qualification remain blocked. No closure. |

Historical results remain in STATUS and the existing platform and chaos documents.
This register records current uncertainty without replacing those records.

2026-09-24 report initialization: added the maintained compatibility report and bounded native measurements. No full-parity closure.

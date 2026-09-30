# noisemaker-for-blender: completion gaps

Current compatibility matrix: [compatibility report](COMPATIBILITY.md).

## 1. Scope and source revisions

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

Review CI boundary: Exact-source runs: Export kit. A passing export dispatch does not qualify rendered parity. Current complete-render enforcement remains an open verification requirement. Exact-source responses and workflows (audit evidence `review-20260925-053200/noisemaker-for-blender-remote-evidence.json`).

### Daily review, 2026-09-28

No new worker audit ran since the 2026-09-24 report. This review covers the implementation range `9631bf6..c998b7c` and the current documents at `c998b7c`.

Checked by execution on Linux x86_64, Node 26.5.1, Python 3.13.13:

- `scripts/test` at `c998b7c`: exit 0. Unit suites pass 189/189. `test_pngread.py` passes 16/16.
  Compiler gates pass 20/20 lex, parse, compile and 19/19 expand, graph. They ran against a fresh reference clone at `73c15be0`.
- Re-graded the committed retained inputs with the committed `pure_grader.py`. All three reports reproduce exactly.
  Adjust and noise are byte-identical by SHA-256. Bloom measures max 1, mean 0.13233, SSIM 0.99999. It fails tol 0 and passes tol 2.
- Verified the six retained golden and graph hashes against `native-input-hashes-verify.json`. All match.
- Verified the four GAP-005 evidence files against `provenance.json`. All SHA-256 values match.
- Recounted the catalog: 210 effect definitions, 309 shader programs. The namespace split matches GAP-007.
  No stale `213` or `30 seconds` claim remains in README, the kit templates, or ARCHITECTURE.md.
- Verified the GAP-001 cross-version claim by hash. The bloom candidate equals both committed Metal renders of 2026-09-27.
- Exact-source CI at `c998b7c`: run `36403426149`. The `engine-free` and `blender` check-runs both completed success at 2026-09-28T09:25Z.
- Served kit `0.1.34` verified live. `deployment-meta.json` records source `dffc073`. Export kit run `36353873056` completed success at `dffc073`.
  `git diff dffc073..c998b7c` touches no export-kit trigger path. The kit's `compat.json` matches its `kit.json` SHA-256 and declares the same 208 effect IDs as the inventory.

Closure verdicts: GAP-001, GAP-005 and GAP-007 are supported by committed evidence. They stay closed.
This review added GAP-008 for the measured open rendering defects. The lens and chain numbers stand as recorded.
Full current-authority parity remains unverified. The full case denominator remains not measured.
[Review evidence](/series/review-20260928-133000/result.json).

### Daily review, 2026-09-25

136 harness tests pass. Actual Blender rendering of the current runtime produced noise with zero byte differences and bloom with maximum difference 1 in 34,690 channels. Both used retained historical goldens. Current-authority full parity remains unverified. Raw evidence (audit evidence `review-20260925-053200/current-native-comparisons.json`).
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

- Status: closed 2026-09-27. Priority: P1. Category: contract. The retained-golden comparison below completes the remaining required check; existing rendering defects remain recorded.
- Scope: README, STATUS, export README, and `compat.json`.
- Expected: each advertised effect has a consistent supported status backed by executable evidence.
- Observed: README claims all non-audio effects work. The shipped template says bloom and lens render incorrectly, but compatibility includes both.
- Evidence: C-003 and the immutable kit README/compatibility files.
- Next action: None for this contract-reconciliation gap. GAP-008 now tracks the measured bloom, lens and chain defects.
- Review evidence: kit `0.1.18` retains the contradictory README and compatibility entries. Last checked 2026-09-23.
- Dependencies: GAP-003 supplies the Blender host. Do not assume either conflicting runtime statement is correct.
- Required checks: public bake path, unchanged authority images, explicit existing tolerances, and both individual effects and a chain.
- Acceptance: both effects have source-bound results and consistent descriptions. Any failure remains visible as unsupported or an open defect.
- Status update 2026-09-25: open — acceptance evidence complete and descriptions reconciled; closure withheld because two required checks remain handoff items. Executed on a Linux Blender 5.1.2 host (OpenGL via Mesa llvmpipe under a virtual display); the host remains not GAP-003-qualified, recorded as an explicit limit. Public bake path fully exercised as integration.sh defines it: step [1] `test_integration.py` INTEGRATION PASS with INVARIANT A (bake == direct pipeline) max-abs-diff=0; step [2] INVARIANT B executed after seeding the documented derived golden (`parity/programs/adjust.dsl` -> `tools/export-graph.mjs` -> `render_all.py`) and grading the dumped bake at integration.sh's gate (tol=1): PASS, byte-identical. Individual `bloom`, individual `lens` (three-line program quoted in the compatibility record), and the `north_star` chain (subchain `dpxp` with `bloom(taps: 15)` and `lens(displacement: -0.28)`) ran through `blender/harness/render_all.py` as golden (graph exported by the unchanged reference engine at the synced revision `2f47612c2904`) versus candidate (same DSL compiled in-Blender): all three byte-identical at tol=2.0, ssim_min=0.98 and at exact zero tolerance. Authority comparison: the retained 2026-09-24 golden files are unreachable from this session, so authority was taken from its source — the unchanged reference engine's own GPU renders (WebGL2/SwiftShader, same determinism protocol as `parity/batch-golden.mjs`, provenance resolved to `2f47612c2904`); nothing altered. Cross-engine results at the existing tolerances (tol=2.0, ssim_min=0.98): bloom PASS max-abs-diff=0.004 ssim=1.00000; lens PASS max-abs-diff=0.039 ssim=1.00000; north_star chain PASS max-abs-diff=1.000 ssim=0.99610; adjust bake PASS max-abs-diff=0.004 ssim=1.00000. Raw outputs (port and reference-engine PNGs, graph JSONs, compare reports, harness and integration logs, CDP driver, compiler suite log) committed under `parity/evidence-2026-09-25/`. The 2026-09-24 retained-golden `bloom` exact-comparison difference (max-abs-diff=1.000, tol=0.0) remains recorded as an open zero-tolerance defect (disposition stated in the compatibility record) — visible as an open defect per acceptance. Descriptions reconciled everywhere in scope: the export README template states the measured results and the open defect; the compatibility inventory rows for `filter/bloom`, `filter/lens`, and `filter/adjust` now carry the measured status; the historical `bloom` FAIL row stands unchanged. Acceptance status: source-bound results — met; consistent descriptions — met; failure visibility — met. Closure withheld solely on the two required checks that cannot be executed here: (1) unchanged-authority comparison against the retained 2026-09-24 goldens (macOS-local store, unreachable); (2) a GAP-003-qualified GPU host (Apple Silicon/Metal hardware unavailable; llvmpipe host not qualified; GAP-003 open). Remaining next action: after either item is provided, re-run `blender/harness/render_all.py` + `parity/compare.py` at the existing tolerances on the qualified host against the authority images, record the results, and close this gap.
- Status update 2026-09-27: blocked — the qualified-GPU-host required check is now executed and the retained-goldens check is recorded as blocked with direct evidence. Host: macOS 26.5, darwin arm64, Apple M4, Blender 5.1.2, `gpu.platform` METAL / "Apple M4" / "Metal API" (`parity/evidence-2026-09-27/gap001/gpuinfo.json`) — the Apple Silicon/Metal class named by the 2026-09-25 closure-withholding; GAP-003 itself remains open on its interactive-GUI and platform-matrix items. The full 2026-09-25 scope re-ran on it through `blender/harness/render_all.py` against the UNCHANGED committed 2026-09-25 authority PNGs (reference engine at `2f47612c2904`), graded by the repo's CURRENT integer-exact `parity/compare.py` (`74bd4ca`) at the existing tolerances (tol=2.0, ssim_min=0.98): bloom PASS (max-abs-diff=1.000, ssim=0.99998); adjust PASS (1.000, ssim=1.00000); the public bake path re-verified — `test_integration.py` INTEGRATION PASS with INVARIANT A max-abs-diff=0, and the dumped bake PASS at integration.sh's tol=1 gate and at tol=2.0; lens FAIL (max-abs-diff=10.000, ssim=0.99999) — recorded as an open defect; north_star chain FAIL (max-abs-diff=255.000, ssim=-0.15266) — recorded as an open chain divergence (chaotic stateful solvers amplify cross-engine FP differences; no pre-existing policy binds this program, so it is recorded as an open defect, not classified NEAR). A second full render pass was byte-identical (sha256-identical bloom/lens/north_star candidates), so these are stable host measurements. Re-grade of the committed 2026-09-25 llvmpipe candidates with the current integer-exact grader (`parity/evidence-2026-09-27/gap001/regrade-0925-integer.log`) reproduces the same integer diffs (bloom 1, lens 10, north_star 255, ssim -0.109) — the 2026-09-25 record's cross-engine numbers (0.004/0.039/1.000, ssim 0.99610) were produced by the pre-`74bd4ca` float32 grader and do not reproduce under the current grader on the committed PNGs; that historical text stands unchanged and the compatibility record's new 2026-09-27 section states this explicitly. Descriptions reconciled everywhere in scope for the new measurements: the kit export README template now states bloom confirmed within tolerance on the qualified host, lens's open measured defect (10/255 at the strict gate) and the chain-class divergence; the compatibility inventory rows for `filter/adjust`, `filter/bloom`, and `filter/lens` carry the 2026-09-27 measured status (lens as an open defect). Raw evidence committed under `parity/evidence-2026-09-27/gap001/`. The retained-goldens check is blocked, not open: a probe run in the macOS host's own sandbox (`retained-goldens-reachability.json`) shows `~` raises `PermissionError(1, 'Operation not permitted')` and both `.codex` store paths do not exist in the sandbox, so the unchanged-authority comparison against `~/.codex/automations/noisemaker-port-completion-audit/` cannot be executed by automation; everything automation can do for this gap is done. Acceptance status: source-bound results — met; consistent descriptions — met; failure visibility — met (lens and the chain are visible as open defects). Post-publication kit verification (same day): the Export kit workflow run `36353873056` completed success at `dffc073` — the push that delivered the template change; the follow-up `b9cb843` changes only README.md, which is not kit content, so the kit content of the published tip is unchanged — and the served kit `0.1.34` (`https://kits.noisedeck.app/blender/0/deployment-meta.json`: git_hash `dffc073cab…`) byte-verifies: `README.template.md` matches the committed source byte-for-byte and carries the lens-defect statement; `compat.json` includes `filter/bloom`, `filter/lens`, and `filter/adjust` (208 effects); `engine/noisemaker_blender.zip` and `LICENSES/noisemaker-MIT.txt` match their `kit.json` SHA-256 entries.
- Retained-input completion, 2026-09-27 at `7a57a617`: the six original Blender graph/PNG hashes match `native-input-hashes.json`. `render_all.py` on Apple M4/Metal, Blender 5.1.2, 256×256, time 0.25, one frame, renders those unchanged graphs. Current integer-exact grading against the retained September 24 PNGs gives noise and adjust max 0 / SSIM 1; bloom max 1 / SSIM 0.99999, passing the existing tol=2 / SSIM≥0.98 gate while retaining its tol=0 failure. The earlier access obstruction is resolved; lens and chain failures above are unchanged. [Render receipt](/tmp/worker-elves-blender-retained.log), [comparison receipt](/tmp/worker-elves-blender-retained-comparison.log).
- Evidence addendum, 2026-09-28: the retained-input comparison's raw evidence is committed under `parity/evidence-2026-09-27/gap001/retained/` — the six manifest-hash-verified retained inputs, the DSL candidates and same-session renders of the retained graphs, per-case reports, compare and render logs, and `gpuinfo.json`; on that worker's numpy-less python the committed `retained/pure_grader.py` (a pure-stdlib mirror of `parity/compare.py`'s uint8/8-bit-unit max/mean over all four RGBA channels and its SSIM) produced the reports, and `retained/native-input-hashes-verify.json` records the per-file verification of all six retained inputs against `native-input-hashes.json` (a copy of whose blender entries ships alongside); the committed bloom mean-abs-diff 0.1323 matches the audit's own recorded bloom measurement. It adds a cross-version point on the same Apple M4/Metal GPU class: under Blender 4.2.21 LTS (`gpu.platform` METAL / "Apple M4" / "Metal API") the retained graphs and DSLs render byte-identically — adjust and noise exact 0 against the retained goldens (sha256-equal candidates), bloom max 1 / SSIM 0.99999 (PASS at tol=2.0, retaining the open tol=0 defect, whose audit-time measure this reproduces exactly), each candidate sha256-identical to its same-session graph render, and the bloom candidate sha256-identical to the 2026-09-27 Blender-5.1.2 render (`../bloom.rerun.png`). Results match the closure above; no tolerance, golden, or status changed.

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
- Status (current statement, 2026-09-29 sixth round; replaces all earlier folded status bullets): open, P2, category authority. The rendered-parity closure contract is unmet: the two landscape cases grade PARITY-SUMMARY {"expected":2,"executed":2,"exact":0,"strict":0,"near":2} (worker-run receipt `parity-summary/r2-gap2.json`, 2026-09-29; the per-case mad 242.0/244.0 figures are re-confirmed in `parity-summary/m4-bisection/compare-receipts.json`; both receipts are uncredited worker-run provenance, not checked results), NEAR is not a pass, and closure needs exact+strict=expected with near=0.
  - Tolerances (recorded, not "unchanged"): the strict per-pixel gate is `parity/batch-compare.py` tol=2.0, ssim_min=0.98 and fails on its own (175/65536 pixels over for default/voxel, mean-abs 0.1402, ssim 0.99756; 343/65536 for isosurface, mean-abs 0.2583, ssim 0.99407). The landscape NEAR entry in `parity/3d-near-policy.json` (max_abs_diff 260.0, mean_abs_diff 0.35, ssim_min 0.992) was newly authored for this mechanism class following the flythrough3d convention (no landscape tolerance existed before); its bounds sit above the measured values and are locked exact in `parity/test_3d_fixture_coverage.py`. NEAR does not evidence acceptance.
  - Compile half (met, both sides): compiler gates pass at the authority pinned when the gates ran, `8eeb7b5ac14e` (v1.0.183; STATUS.md's pin has since advanced to `73c15be00d68` in the 2026-09-28 sync, both revisions pass, further synchronization out of scope); 143/143 parity unit tests; kit `0.1.18` (source `e9299fd8…`) and the rebuilt published kit `0.1.26` (source `5773f540…`, engine zip sha `a2ed33f3…`) both compile all three filtering choices with `FILTERING` 1/1/0 and render identically to the source renders, graded NEAR through the same gate; kits `0.1.18`/`0.1.22` all-black rejection evidence retained (the since-fixed vec3-uniform defect). Receipts: `parity/evidence-2026-09-26/` (packed-kit-0.1.18-landscape-graphs.json, gate/*).
  - Bisection findings (receipts and raw float32 dumps in the job evidence archive `parity-summary/m4-bisection/`): the executed precompute and raymarch fragment bodies are line-identical, compiled graphs structurally identical, and the bound o1/tex contents texel-identical; the divergence survives an identical GPU (`compare-receipts.json`: ref-on-M4 vs ref-on-SwiftShader mad 163.0/131.0 vs port-on-M4 vs ref-on-M4 mad 242.0/244.0; receipts are uncredited worker-run provenance).
  - Fixed port defect (x=0 column): a fullscreen draw with viewport height 4096 on the Metal backend leaves the leftmost pixel column of the target unwritten (MRT and single-target alike) — the retained `fixed-readback/` dumps show the port's x=0 column entirely unwritten (589 reference-solid texels vs 0) while every other column is populated; the earlier in-session probe receipts for this finding (`redraw-probe.json`, `redraw2/3.log`, `postfix.json`) were not preserved in the retained evidence archive, so the retained dumps are the evidence of record here. `_render` now draws FS passes in ≤2048-row slabs (`slab_ranges`, GPU-free helper, semantically identical), regression-tested in the credited engine-free check `parity/test_slab_tiling.py` plus the Blender-side asserts in `test_backend_contract.py`. The post-fix render is pixel-identical to pre-fix, so this camera does not sample the x=0 column.
  - Residual, operation-level state (receipt `parity-summary/m4-bisection/atlas-occupancy-corrected.json`, regenerated 2026-09-30 from the retained `fixed-readback/` dumps; both the fifth round's transposed-indexing decomposition in `atlas-alpha-flip-decomposition.txt` (11/652) and the sixth round's first corrected figures (74 scattered flips; 60/11/3 model matches; median 0.46) could not be reproduced from the retained dumps and are retracted in favor of this recomputed receipt): per-texel RGBA presence (alpha > 0.002) on the retained 64x4096 float32 atlases (flat = row*64 + x, row = z*64 + v) yields 649 occupancy flips — 589 in the (fixed, these dumps pre-date the slab fix) x=0 column plus 60 scattered; every scattered flip is reference-present → port-void with the port column count = reference count − 1 voxel (column occupancy is not bottom-contiguous, so column height is the count of present texels). The fp32-emulated documented model h = floor(clamp(dot(rgb,(0.2126,0.7152,0.0722))*0.35,0,1)*64+0.5) at o1 texel (4x+2, 4z+2) matches the reference column count in 54 of the 60, the port in 3, and neither in 3, and the emulated t = v*64+0.5 sits a median 0.4922 of a voxel from the flip boundary — the sub-ULP floor()-boundary attribution stays falsified; with byte-identical o1 inputs the port computes a systematically lower column height at these columns. The root operation is not yet localized.
  - Next (automatable, keeps this gap open): measure the port's actual internal columnHeight/luminance with an instrumented precompute shader (scratch copy writing t and L into the atlas color; earlier probe attempts were killed by the host's intermittent Blender startup wedge and their receipts are not present in the retained evidence archive, so the measurement remains pending with no cited receipt), compare t against the reference's implied (h−0.5, h+0.5] per column to localize the first diverging operation, fix it if it is port-side, and re-grade through `scripts/parity-summary`. NEAR-graded attribution alone does not close the gap; exact+strict=expected is the contract.
- Parity cases: heightmap3d_landscape, heightmap3d_landscape_isosurface (the `filtering: voxel` choice is byte-identical to default by the recorded upstream-declared semantics — both filtering DSLs compile to identical graphs — and shares the heightmap3d_landscape case).

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
- Evidence: compiler logs, `existing-golden-hashes.json`, `coverage.json`, and the CI run records — materialized under `parity/evidence-2026-09-26/gap004/`: three exact-source dispatcher run metadata files (`ci-dispatch-35752180457.json`, `ci-dispatch-35807778200.json`, `ci-dispatch-5773f540.json`) and one downstream-privacy record (`ci-downstream-scaffold-private.json`); the two audit downstream runs (`35752203907`, `35807785546`) stay private to unauthenticated API access (404 on fetch) and exist only as recorded run-ID strings in this session.
- Next action: extend rendered coverage toward the full tracked fixture inventory on GAP-003-qualified hosts; the retained diagnostic failure stays recorded until its audit-time golden bytes are reachable.
- Dependencies: GAP-003 for rendered evidence. Preserve current goldens during review.
- Required checks: current differential results, retained failures, exact-source workflow steps, and coverage for modes, inputs, seeds, time, sizes, and state.
- Acceptance: each pass count names its authority and coverage. CI publication success remains separate from behavioral qualification.
- Status update 2026-09-26: open — retained-golden provenance established and the diagnostic difference classified, without changing the checkpoint. Provenance: the compiler-gate goldens live in `parity/out/`, which is git-ignored by design (`.gitignore` line 2) and regenerated per checkout by `parity/regen-compiler-goldens.sh` against `NM_REFERENCE_ROOT`; the working set was regenerated 2026-09-26 from the declared-authority reference clone verified at HEAD `8eeb7b5ac14e` (noisemaker v1.0.183, the authority named by GAP-002's record), and every file's SHA-256/size/mtime is recorded in `gap004/existing-golden-hashes.json`. The checkpoint pin `643b2be1e28b` (STATUS.md) is unchanged; an earlier same-day regeneration from the older checkpoint clone was replaced by the declared-authority set and is recorded in the hashes file. The 2026-09-22..25 audit-time golden capture itself remains in the unreachable automation store — that unreachability is now named as the provenance limit instead of being left implicit. Classification: the port's `compile()` output for the failing corpus program `B5oBsA` is structurally identical to the reference engine's at every reference revision available to this session (`a0ff705a` pre-checkpoint, `643b2be1` checkpoint, `ae4e3302` audit authority, `8eeb7b5a` declared authority — `gap004/b5obsa-classification.log`); all four emit `"location": {"line": 20, "column": 4}` on the S005 diagnostic and so does the port, so the audited 19/20 "the candidate adds column" cannot be reproduced against any available reference and is classified as stale retained golden evidence, not a port compiler regression. The retained failure stays on the record; no golden, tolerance, gate, or checkpoint changed (fresh gates reproduce the committed results: lex 20/20, parse 20/20, compile 20/20, expanded 19/19 and graph 19/19 with the unchanged `EXCLUDE = {"B5oBsA"}`, unit 143/143 at the audited revision `9631bf6f` — `gap004/check_*.log`, `gap004/unit.log`; unit.log has since been refreshed to the 157/157 run at the integrated tip, see the second status update below). Coverage: `gap004/coverage.json` names the authority behind every denominator — 20 corpus programs (`git ls-tree HEAD parity/corpus`), 227 tracked fixtures at the audited revision `9631bf6f` and 228 at this candidate (the delta is `heightmap3d_landscape_isosurface.dsl`, added in `81a9d07` for GAP-002), 309 tracked `.frag` shader programs, 210 effect definition files, 143 unit tests, exclusions (`B5oBsA` expanded/graph, `synth/scope`, `synth/spectrum`), and the runtime render coverage actually executed (2026-09-25 cross-engine bloom/lens/north_star/adjust; 2026-09-26 llvmpipe and macOS machine-verified adjust/alphaMask/bitwise; landscape modes + gradient probe) with the remaining fixtures explicitly not rendered. CI: the exact-source dispatcher run for the kit-build source `5773f540` (36216741151, success 2026-09-26T04:04:34Z) is materialized as metadata (`gap004/ci-dispatch-5773f540.json`), as are both audit dispatcher runs (`ci-dispatch-35752180457.json` success at `0efbdc47`, `ci-dispatch-35807778200.json` success at `e9299fd8`); the audit's downstream scaffold runs (`35752203907`, `35807785546`) remain private to unauthenticated API access — the fetch attempt and its 404 are materialized in `gap004/ci-downstream-scaffold-private.json` — so fresh downstream verification remains the supervisor's post-publication verify step, and CI publication success stays separate from behavioral qualification.

- Status update 2026-09-26 (second): the "Preserve current goldens during review" blocker was only partially met earlier the same day — `parity/out/` was regenerated twice before hashing (13:47 checkpoint clone, replaced 16:13 by the declared-authority set), so the pre-regeneration working bytes are not recoverable; the loss window is bounded by the committed gate logs (08:18, last known-good) and the first regeneration. Corrective record: the declared-authority set's preservation is recorded durably as the per-file SHA-256/byte/mtime manifest in `gap004/existing-golden-hashes.json` (98 files, re-hashed with 0 mismatches; `parity/out/` itself stays untracked per `.gitignore` line 2 and is deterministically regenerable from the pinned authority `8eeb7b5ac14e` via `parity/regen-compiler-goldens.sh`), with restore-and-verify steps, a review-window byte copy held outside the repository, and a no-regeneration-without-review-approval policy in the hashes file's `preservation` block. Gates reproduce at the integrated tip `a5f8986` (lex 20/20, parse 20/20, compile 20/20, expanded 19/19, graph 19/19; unit 157/157 — `gap004/unit.log` refreshed at this tip; 143/143 at the audited revision, the delta being the 14 texture-pooling tests added in `a5f8986`) and the checkpoint pin `643b2be1e28b` is unchanged. The compile gate over regenerated goldens is named as partially self-referential; the independent classification of the audited 19/20 failure remains the four-revision comparison in `gap004/b5obsa-classification.log`.

### GAP-005: Long-bake and Image ownership qualification is missing

- Status: closed 2026-09-26. Priority: P2. Category: usability.
- Scope: `ops/bake.py`, `props.py`, sidebar panels, and Image datablocks.
- Expected: developers understand long-running work and can protect existing Images.
- Observed: the operator rendered synchronously. Its source had no modal cancellation or progress path.
- Observed: `_write_image` reused an existing Image by name and could resize it before replacing pixels.
- Evidence: source inspection only. This audit did not reproduce data loss or measure responsiveness.
- Qualification 2026-09-26 (executed, `parity/evidence-2026-09-26/gap005/`): the audit's two observations were reproduced by execution against the then-published base `039840158df6bda7cd1d254361bac4128fe9ea68` with a disposable in-memory project (`red-before.log`): a bake targeting the name of an existing 64x32 foreign Image resized that Image and then failed writing into it (`TypeError: expected sequence size 8192, got 262144`) — the destructive name-collision behavior the audit inferred, now exercised. The fix (in this candidate) gives the bake image ownership and a cancellable long-bake path:
  - Image ownership: the bake reuses an existing Image only when a previous bake created it (custom property `noisemaker_baked` stamped on every Image the operator writes). Any other Image with the target name is never resized or overwritten; the bake writes to a fresh unique name (`<name>.001`), reports a WARNING naming both images, and leaves the foreign Image byte-identical — proven for a different-size image, a same-size image, and a packed image (`test.log` checks ownership-foreign-*, pixels compared before/after). Rebaking into a Noisemaker-created Image still reuses and updates the same datablock.
  - Long bakes: invoked from a window with more than one frame, `noisemaker.bake` now runs MODAL — one frame per timer tick via a new `pipeline.FrameStepper` (the `render()` loop body factored out byte-for-byte; `render()` is now defined in terms of it), so the UI stays responsive between frames, progress (`frame N/M — ESC to cancel`) is set on the status bar, and ESC cancels between frames. The modal decision uses the RESOLVED frame count — operator overrides or the scene settings (the sidebar panels invoke with no overrides), so a scene-configured 1800-frame settle bake from the Bake button is modal too (both entry points exercised: `test.log` modal-invoke-running and modal-scene-settings-running). The modal timer and status text are cleared on every exit path — success, ESC cancel, mid-render failure, and a final-image-write failure (`test.log` modal-cleanup-timer-status). Because nothing is written to the Image until every frame finished, a cancelled or failed bake leaves the target Image exactly as it was (verified: mid-bake cancel writes nothing and frees the backend; a compile error and an injected mid-render failure leave all existing Images byte-identical, free the backend, and a following bake still succeeds — recovery-gpu-healthy-* checks). A 60-frame, 256px bounded bake measured 12.1 ms/frame (0.72 s wall) on this host — an 1800-step evolution bake is therefore ~22 s of modal, cancellable work, not a freeze.
  - Scripts and headless sessions keep the synchronous `execute()` path (EXEC_DEFAULT), which is what `test_integration.py` drives: after the change it still reports INTEGRATION PASS with INVARIANT A max-abs-diff=0 including the stateful frames+timestep sweep (`integration-after.log`; INVARIANT B skipped — `parity/out` goldens are absent in this container and regenerating them needs `NM_REFERENCE_ROOT`, which this container lacks; A plus the unchanged unit suite covers the wrapper), and the parity unit suite passes 157/157 (`unit.log`).
- Remaining limits (explicit): ESC was exercised at the machinery level (the modal `ESC` branch semantics via `_release`, plus the real modal invocation completing through Blender's timer loop) but a physical ESC keypress in an interactive session was not, consistent with GAP-003's interactive-GUI-only limit; cancellation is between frames — one already-running frame always completes, so a single very heavy frame (e.g. a 4096px single-pass bake) still blocks its duration; Images baked by versions before this change carry no marker, so rebaking onto such an Image creates a new datablock instead of reusing it (recovery: delete or rename the old Image, or bake onto the new one). Status text and the report stream are the visible feedback; Blender shows operator reports in the status bar/UI only in a real session.
- Recovery instructions (user-visible): to protect an Image, never name it as the bake target — a collision bake never touches it and reports where the bake went; to stop a long bake, press ESC between frames and the Image keeps its previous content; if a bake reports an error, the Image is untouched — fix the DSL and bake again; pre-upgrade baked Images without the marker get a fresh datablock on rebake.
- Closure: the acceptance — observed behavior and recovery instructions protect the tested workflow, with any destructive or unresponsive behavior explicit — is met for the executed checks above; the remaining limits are recorded and are not destructive in the tested cases.

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
- Status update 2026-09-26: open — the standalone-archive half is implemented and exercised; closure waits on the next published kit build's byte check and GAP-003's host qualification. Implemented through the existing builder: the notice now ships inside the add-on tree as `blender/noisemaker_blender/LICENSE.txt` (byte-identical to the repository LICENSE, SHA-256 `e502d1baf14c5fde7a7476f8a860665352d31d26f75b7a6977943606c8b51259`), so BOTH standalone forms carry it with no builder change — the documented README build (`cd blender && zip -r noisemaker_blender.zip noisemaker_blender`) and the kit builder's subtree zip mode (`export-kit/kit.config.json`: `blender/noisemaker_blender` -> `engine/noisemaker_blender.zip`; the served kit 0.1.26 engine zip's 868 entries are all `noisemaker_blender/…`-prefixed files of this tree, so the notice enters the next build as entry 869 — pending the post-publication kit byte check). Version mapping defined (README "Versions and notices" and the kit README template): the kit version `0.1.N` is the release builder's publication counter and is NOT the add-on version; the binding is each published `kit.json`'s `source.sha`, which names the exact source revision — and therefore the exact add-on version — a kit was built from; the add-on's own upgrade identity is its `bl_info` literal version, bumped to `(0, 1, 1)` in the same change that alters the distributed add-on (previous distributions are `(0, 1, 0)`), with the bump rule recorded. Required checks executed (`parity/evidence-2026-09-26/gap006/`): `parity/test_archive_identity.py` (5 tests) proves red-before at base `d9a4243` (3 failures + 1 error) and, green: the standalone-zip inventory (869 entries, entry point `register()`, bl_info literal in lockstep with the version constant), the packaged notice byte-identical to the repo LICENSE, and the kit-config license/subtree wiring; full parity suites 162/162 (`unit.log`); compiler gates regenerated against the reference at `6a0af04d3c4f` (20/20 lex/parse/compile, 19/19 expand/graph — `check_*.log`). A clean-host install→upgrade→remove cycle ran under a bpy 5.2.2 wheel module as the Blender host (environment disclosed; NOT the declared Blender 5.1 GUI host, and `addon_remove`'s UI limitation applies as already recorded under GAP-003) with isolated `BLENDER_USER_RESOURCES` (`upgrade-cycle.log`): the served kit 0.1.26 engine zip installed and enabled as `(0, 1, 0)` with no notice (reproducing the gap), the candidate archive installed over it via `addon_install`, identified as `(0, 1, 1)` with `LICENSE.txt` present and the MIT text, enabled, disabled, and was removed (module no longer importable). The cycle caught a real defect before commit: `bl_info` must stay a LITERAL dict (Blender `ast.literal_eval`s it at install time — the first draft referenced the version constant and Blender logged `AST error parsing bl_info`); fixed and regression-locked in `test_archive_identity.py`. Remaining: the enclosing-kit form carries the notice only from the next published kit build (verify after publication); install/upgrade/removal on the declared Blender 5.1 host remains GAP-003-dependent.
- Status update 2026-09-26 (kit-form verification): the next kit build from THIS source is published and byte-verified — kit `0.1.30`, `kit.json` `source.sha` `81ca79e5ea32c87dd273257c04d2e91da48ea078` (the reviewed/published commit; built by the exact-source `export-kit` dispatch recorded in the verification receipt). Its `engine/noisemaker_blender.zip` (SHA-256 `cfba99cbe1893855b5ef7b44b4d7aba3e78e2ab712e56ef36f72346c59720484`, verified against the immutable `kit.json`) is 869 entries, carries `noisemaker_blender/LICENSE.txt` with the MIT text, reports `bl_info` version `(0, 1, 1)`, and every entry byte-matches the published checkout tree `blender/` (0 mismatches) — `published-kit-0.1.30.kit.json`, `published-kit-0.1.30-engine-zip.sha256`. The standalone-notice half of the acceptance ("every distributed form carries its notices and identifies its source") is now met for both standalone forms (README manual build and kit-shipped engine zip) and the enclosing kit's `LICENSES/` notices remain. The remaining open item stays GAP-003-dependent: install/upgrade/removal on the declared Blender 5.1 host.
- Verification 2026-09-26 (reproducible, committed with this record): `parity/verify_standalone_kit.py` fetches the served kit and machine-checks every required item; its committed report `parity/evidence-2026-09-26/gap006/published-kit-0.1.30-verification.json` shows `all_passed: true` for kit `0.1.30`: engine zip SHA-256 `cfba99cb…` and byte length both match the immutable `kit.json`; 869 entries all under `noisemaker_blender/`; `noisemaker_blender/LICENSE.txt` present, MIT text, byte-identical to the repository LICENSE (SHA-256 `e502d1ba…`); entry point `noisemaker_blender/__init__.py` exposes `def register():` and a LITERAL `bl_info` dict (Blender `ast.literal_eval` contract) with version `(0, 1, 1) > (0, 1, 0)`; every zip entry byte-matches the checkout `blender/noisemaker_blender/` tree and no checkout file is missing (0 mismatches / 0 missing either direction) — the archive identifies its source. Version mapping for the published candidate: kit `0.1.30` ↔ `source.sha` `81ca79e5ea32c87dd273257c04d2e91da48ea078` (the implementation commit that built it) ↔ add-on `bl_info` `(0, 1, 1)`; the follow-up commit `4435f2c767c7ef7e0055b4e21743c49c3cf9558a` is documentation/evidence-only (its full diff touches `docs/COMPLETION_GAPS.md` and two `parity/evidence-2026-09-26/gap006/` files — no engine source), so kit `0.1.30` remains the engine artifact of the published tip. The clean-host install→upgrade→remove evidence is the committed `upgrade-cycle.log` (bpy 5.2.2 module host, environment disclosed; `unit.log` carries the per-file counts of the 162-test suite — 157 prior plus the 5-test archive-identity battery — and the battery's red-before run is committed as `archive-identity-red-before.log`, re-executed at base `d9a4243`: FAILED failures=3, errors=1, then OK at the candidate HEAD); GAP-006 remains open solely on its GAP-003 dependency (declared Blender 5.1 host qualification).
- Verification 2026-09-27 (published-tip identity): published main is `1f506a6252db448f1c7ad2e2854faf0c43d3f078`; `git diff 81ca79e5ea32c87dd273257c04d2e91da48ea078..1f506a6… -- blender export-kit LICENSE .github/workflows/export-kit.yml` is EMPTY (`kit-0.1.30-tip-identity.log`) — the two commits between them are docs/evidence-only and touch none of the `export-kit.yml` trigger paths, so no kit rebuild was dispatched and served kit `0.1.30` remains the current engine artifact of the published tip; `parity/verify_standalone_kit.py 0.1.30` re-run against the `1f506a6` checkout reports `all_passed: true` (its 869 engine-zip entries byte-match this tip's `blender/noisemaker_blender` tree, committed report refreshed).

### GAP-007: User-facing counts and simulation duration are stale

- Status: closed 2026-09-27. Priority: P3. Category: usability.
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
- Status update 2026-09-27: closed — all three observations reconciled in documentation-only changes, with no historical result upgraded to current qualification. (1) Counts: the checkout's `blender/noisemaker_blender/effects` holds exactly 210 effect definition JSONs (filter 113, synth 29, mixer 15, classicNoisedeck 20, points 11, render 12, synth3d 8, filter3d 2 — matching STATUS.md's coverage table) and `blender/noisemaker_blender/shaders/effects` holds 309 `.frag` programs; README's two stale "213" claims now read 210 (`count-and-time-check.log`). (2) Historical verification labels: STATUS's coverage rows no longer say "not yet Metal-verified" for `points/heightGrid`, `render/renderLandscape3d`, and `synth3d/heightmap3d` below the 2026-09-15 sync section that reports those four fixtures rendered PASS in the real-Metal session; the rows now cite that historical session and state the results are "not re-verified since" — historical results stay historical, and full rendered parity remains unverified per this document's standing scope note. (3) Simulation duration: the runtime loop is `tt = (time + f * timestep) % 1.0` with per-frame delta equal to the timestep (`runtime/pipeline.py`, `FrameStepper.step`), so 1800 frames at timestep 0.00167 (1/600) advance normalized simulation time by 3.006 (3.000 at exactly 1/600) units wrapping at 1 — there is no seconds conversion. README, both exported bake instructions (`export-kit/kit/README.template.md`, `export-kit/kit/bake.template.py`), and ARCHITECTURE.md's validation section now state the normalized-time arithmetic and drop the "30 seconds" equation; the recommended 1800-frame / 1-600 recipe itself is unchanged. Executed check committed as `parity/evidence-2026-09-27/gap007/count-and-time-check.log` (counts derived from current files, loop line quoted from source, arithmetic, and a scan asserting no "213"/"30 seconds" claims remain; exit 0). No source, test, golden, tolerance, or checkpoint changed; GAP-003's dependency is untouched because no fresh runtime qualification is claimed.

### GAP-008: Measured cross-engine rendering defects lack a register entry

- Status: open. Priority: P1. Category: implementation.
- Scope: `filter/lens`, the `north_star` chain, and `filter/bloom` at exact zero tolerance.
- Expected: each advertised effect passes the port's strict gate, or a mechanism-bound policy records its divergence.
- Observed: `filter/lens` renders with a measured 10/255 worst per-channel difference on the qualified Metal host. This exceeds the strict 2-step gate. SSIM is 0.99999.
- Observed: the `north_star` chain diverges structurally cross-engine. Max difference is 255 and SSIM is −0.15. Its chaotic solvers amplify sub-LSB floating-point differences.
- Observed: `filter/bloom` passes the strict gate. It fails the retained-golden zero-tolerance comparison by 1/255.
- Evidence: [Host measurements, 2026-09-27](COMPATIBILITY.md#native-observations-2026-09-27) and the committed reports under `parity/evidence-2026-09-27/gap001/`. The retained-input reports were re-graded 2026-09-28 and reproduce exactly.
- Next action: on a qualified Metal host, bisect the `lens` divergence pass by pass against the shared reference GLSL. Fix the port defect, or bind the divergence to a measured cross-engine mechanism. Then decide the chain the same way. Author a chaos-gate entry only from measurement, per the `flythrough3d` precedent.
- Dependencies: GAP-003 supplies the qualified host. Do not change any tolerance or golden while classifying.
- Required checks: per-pass readbacks of the lens program on both engines. The existing `parity/compare.py` gate at tol 2.0 and SSIM 0.98. The committed 2026-09-27 reports stay the baseline.
- Acceptance: `lens` passes the strict gate, or a mechanism-bound policy entry records the measured divergence. The chain receives the same treatment. The bloom zero-tolerance defect keeps its recorded status.
- Added: 2026-09-28 daily review. The defects were measured 2026-09-25 through 2026-09-27 but lacked a register entry after GAP-001 closed.

## 5. Ordered next actions

Current first action: classify and fix GAP-008's `lens` defect on a qualified Metal host. Then run the full tracked fixture sweep for GAP-004. The earlier actions for GAP-001, GAP-005 and GAP-007 are complete. No implementation is authorized by this audit.

These actions describe acceptance work at the existing checkpoint. They do not authorize implementation or an authority upgrade.

1. On a GAP-003-qualified host, bisect the `lens` 10/255 divergence pass by pass against the reference engine.
   Fix the port defect, or author a mechanism-bound policy entry from measurement.
   Pass condition: `lens` passes `parity/compare.py` at tol 2.0, or a policy entry records the measured mechanism. This serves GAP-008.
2. Decide the `north_star` chain divergence the same way. Author a chaos-gate entry per the `flythrough3d` precedent, or record a port defect.
   Pass condition: a policy entry or a defect record exists with measured per-pass evidence. This serves GAP-008.
3. Export immutable authority graphs for all 227 tracked programs. Run them through `blender/harness/render_all.py`.
   Count missing graphs, mismatches, errors and timeouts per case. Keep every result explicit.
   Pass condition: every case executes with a recorded result. This serves GAP-004.
4. Exercise the interactive-GUI items and the Windows host of the GAP-003 matrix. Record host and GPU versions for each step.
   Pass condition: each workflow passes on the recorded host. This serves GAP-003.
5. Install, upgrade and remove kit `0.1.34` on the declared Blender 5.1 host. Use the public entry points only.
   Pass condition: each step passes and the archive identifies its source. This serves GAP-006.

Affected files and objective pass conditions appear in each gap above.
Implementation remains with the separate job. No additional effect port is part of this audit.

## 6. Pass history

2026-09-25 daily review at `9631bf6fc44578b29ba4c2eb6aab6ab1704d98bc`: source freshness and bounded evidence reviewed. Open qualification limits retained. Retained review evidence (audit evidence `review-20260925-053200/current-native-comparisons.json`). No new closure claimed.

2026-09-28 daily review at `c998b7ccc4139497098f4dfe1fbb6836bf7ae0ca`: reviewed the implementation range `9631bf6..c998b7c`. Closures GAP-001, GAP-005 and GAP-007 verified by execution and retained. Added GAP-008 for the measured cross-engine rendering defects. `scripts/test` passed at the head. Exact-source CI run `36403426149` passed both check-runs. Served kit `0.1.34` verified live. GAP-002, GAP-003, GAP-004, GAP-006 and GAP-008 stay open. Full parity remains unverified. [Review evidence](/series/review-20260928-133000/result.json).

| Date | Source | Changes and tested scope | Remaining limits |
| --- | --- | --- | --- |
| 2026-09-22 | `0efbdc47dcf3050575af1e0c9b22e5425fd1fb84` | Initial register. Seven gaps. Compiler and package checks described above. | No host qualification or closures. Checkpoint unchanged. |
| 2026-09-23 | `e9299fd8af7d546d27491959677211e8e89b1dc1` | Reviewed original evidence. Rechecked packed compiler, conflicting support claims, missing ZIP license, and current CI. Corrected GAP-002 and raised GAP-006. | Seven gaps remain. GPU and host qualification remain blocked. No closure. |

Historical results remain in STATUS and the existing platform and chaos documents.
This register records current uncertainty without replacing those records.

2026-09-24 report initialization: added the maintained compatibility report and bounded native measurements. No full-parity closure.

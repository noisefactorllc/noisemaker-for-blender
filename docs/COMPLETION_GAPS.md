# noisemaker-for-blender: completion gaps

## 1. Scope and source revisions

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
| C-008 | Latest synchronization record | Authority checkpoint through `643b2be1e28b` | supported | That checkpoint remains explicit. Current upstream adds an unsupported landscape parameter. |

The old whole-catalog parity language does not establish current mode coverage.
Equal effect identifiers do not establish equal parameters, shader behavior, or host support.
The historical 85 PASS / 12 NEAR artistic results retain their original authority and tolerances.
NEAR results and chaos qualification are not byte-exact results. See [STATUS.md](../STATUS.md) and [CHAOS-GATE.md](CHAOS-GATE.md).

## 3. Methods and evidence

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

## 4. Known gaps

P1 means false completion or a major correctness gap. P2 means incomplete coverage or integration. P3 means inconsistent documentation.
All gaps below were last checked on 2026-09-22. No gap closed during this pass.

### GAP-001: Conflicting runtime support claims

- Status: open. Priority: P1. Category: contract.
- Scope: README, STATUS, export README, and `compat.json`.
- Expected: each advertised effect has a consistent supported status backed by executable evidence.
- Observed: README claims all non-audio effects work. The shipped template says bloom and lens render incorrectly, but compatibility includes both.
- Evidence: C-003 and the immutable kit README/compatibility files.
- Next action: test existing bloom and lens fixtures at the frozen checkpoint, then reconcile the claims with those results.
- Dependencies: GAP-003 supplies the Blender host. Do not assume either conflicting runtime statement is correct.
- Required checks: public bake path, unchanged authority images, explicit existing tolerances, and both individual effects and a chain.
- Acceptance: both effects have source-bound results and consistent descriptions. Any failure remains visible as unsupported or an open defect.

### GAP-002: Current authority exceeds the frozen checkpoint

- Status: open. Priority: P2. Category: authority.
- Scope: landscape parameter coverage and authority descriptions.
- Expected: developers can distinguish the recorded checkpoint from current upstream behavior.
- Observed: current upstream accepts both filtering choices. This port rejects the parameter.
- Evidence: `public-probes.json`, source definitions, and the recorded upstream comparison.
- Next action: preserve the checkpoint and document its boundary. Do not port the new parameter during this audit.
- Dependencies: none. Any future synchronization needs separate implementation authority.
- Required checks: identify source and authority revisions for each completion claim. Retain the bounded rejection probes.
- Acceptance: checkpoint claims exclude later behavior, and no current-authority completion claim conceals the difference.

### GAP-003: Host qualification is unavailable

- Status: blocked. Priority: P2. Category: verification.
- Scope: Blender 5.1 installation, GPU output, normal Image workflows, and supported platform declarations.
- Expected: the actual distribution installs and produces useful output through documented public entry points.
- Observed: archive compilation passes. The audit cannot run Blender, GPU shaders, panels, materials, or project persistence.
- Evidence: `backend.log`, environment checks, and the host workflow list above.
- Blocker: the auditor could not locate a usable Blender runtime.
- Next action: execute the existing integration and render harnesses in isolated Blender 5.1 preferences on a supported GPU host.
- Dependencies: the frozen source, its distribution archive, and unchanged authority fixtures.
- Required checks: install/enable, quick start, material/compositor use, save/reopen, error recovery, cleanup, disable/remove, and keyboard interaction.
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

- Status: open. Priority: P2. Category: release.
- Scope: the legacy ZIP, license notices, version identification, and upgrade behavior.
- Expected: each distributed form retains required notices and supports reproducible version identification.
- Observed: the enclosing kit includes MIT notices. Its 868-entry add-on ZIP contains no license text.
- Observed: add-on metadata says `0.1.0`. The enclosing kit says `0.1.17`. The README also describes building a standalone ZIP.
- Evidence: `kit-verification.json`, `bl_info`, README installation command, and published kit metadata.
- Next action: qualify the standalone distribution and define the mapping between add-on and kit versions.
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

These actions describe acceptance work at the existing checkpoint. They do not authorize implementation or an authority upgrade.

1. Preserve the checkpoint and classify later authority differences in this register. Keep the current rejection evidence for GAP-002.
2. Locate a qualified Blender 5.1 host. Execute the existing installation and integration checks for GAP-003.
3. Test bloom and lens before repeating broad completion claims. Resolve GAP-001 from output evidence, not document precedence.
4. Establish golden provenance and retain the diagnostic failure until the reviewer records its cause. Complete GAP-004's evidence boundaries.
5. Test long bakes and Image name collisions in a disposable project. Record GAP-005's user-visible recovery behavior.
6. Qualify notices, version mapping, upgrade, and removal for the actual ZIP. Apply GAP-006's acceptance checks.
7. Correct the identified documentation inconsistencies under separate maintenance scope. Apply GAP-007's count and timing checks.

Affected files and objective pass conditions appear in each gap above.
Implementation remains with the separate job. No additional effect port is part of this audit.

## 6. Pass history

| Date | Source | Changes and tested scope | Remaining limits |
| --- | --- | --- | --- |
| 2026-09-22 | `0efbdc47dcf3050575af1e0c9b22e5425fd1fb84` | Initial register. Seven gaps. Compiler and package checks described above. | No host qualification or closures. Checkpoint unchanged. |

Historical results remain in STATUS and the existing platform and chaos documents.
This register records current uncertainty without replacing those records.

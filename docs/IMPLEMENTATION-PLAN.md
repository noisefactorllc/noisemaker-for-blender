# noisemaker-blender — Implementation Plan

A Blender port (Polymorphic DSL compiler, render-graph executor, effects collection) of
`../noisemaker/shaders`, pixel-parity (relaxed Metal tolerance) to the reference WebGL2 engine.
Primary analog: `noisemaker-td` (Python + node-based + GLSL + GUI harness). Reference named by
user: `noisemaker-hlsl`.

## Architecture in one line

Reference compiler (Node, build time) → `graph.json` + transpiled `.frag`/`.createinfo.json` →
Blender Python addon runs them on the `gpu` module (Metal), bakes to Image datablocks consumed by
the real compositor. See `ARCHITECTURE.md`, `docs/BLENDER-PLATFORM-NOTES.md`, `PORTING-GUIDE.md`.

## Phases

- **P0 — De-risk & scaffold ✓ (done)**
  - Verbatim scaffold from `hlsl`: `reference/01–10`, `GRAPH-JSON-SCHEMA.md`, `tools/export-graph`
    + `convert-definitions`, `parity/compare.py` + `export-and-render.mjs` + `programs/` (75) +
    `corpus/` (20), legal files. Git initialized.
  - Blender 5.1.2 installed; spikes proved create_from_info offscreen render, sampler2D, float
    readback, push-constants, orientation, linear storage on Metal (`blender/harness/spike_*.py`).
  - Findings locked into platform notes + porting guide.

- **P1 — Shader transpiler + first-effect compile**
  - `tools/convert-shaders-blender.mjs`: reference `<prog>.glsl` → `<prog>.frag` (verbatim body,
    declarations stripped) + `<prog>.createinfo.json` (push_constants/samplers/fragment_out,
    std140 size, ubo flag). Run over all effects; report compile coverage.
  - Verify a handful compile via `create_from_info` in a Blender spike (synth/solid, synth/noise).

- **P2 — `GpuBackend` + minimal pipeline → Tier-1 gate (THE gate)**
  - `gpu_backend.py` (createTexture/compileProgram/executePass single-output/readPixels) +
    `graph_loader.py` + a minimal `pipeline.py` (ordered passes, engine uniforms, surfaces).
  - `blender/harness/render_all.py` (GUI, timer→render→save→quit) renders a graph.json to PNG.
  - Drive **8 Tier-1 programs** (solid, noise, cell, gradient, shape, osc2d, blur, blendMode) to
    parity vs golden via `parity/run.sh`. Gate: pass at relaxed tolerance.

- **P3 — Full executor**
  - Multi-pass, blit/copy/clear, blend modes, three-tier ping-pong + iteration-swap + feedback
    (reference `pipeline.js` semantics, `reference/04`). Texture pool from `allocations`.
  - Per-frame oscillator automation (sine/tri/saw/sawInv/square/noise). **No MIDI/audio** (skipped).

- **P4 — Parity sweep (corpus-driven, like godot/td)**
  - Batch goldens (`parity/batch-golden.mjs`) + batch candidate render; grade all 75 programs +
    `corpus/` with the per-effect tolerance map in `parity/sweep.sh`.
  - **Stateful mode** for navierStokes / reactionDiffusion / cellularAutomata / agents:
    `--duration 30 --interval 5` — run ~30s, sample every 5s, grade each sample (per user
    guidance; this is the class siblings deferred). Continuous solvers may stay cross-backend
    divergent (document as skips, per the discrete-vs-continuous principle).

- **P5 — Integration surface**
  - `ops/` bake-to-Image operator (the primary "compositor-feeding" UX): pick effect/DSL → render
    via gpu → write `bpy.types.Image` → drop an Image node in the compositor.
  - `nodes/` `CUSTOM` NodeTree + hand-written evaluator (noisemaker graph as Blender nodes).
  - `blender_manifest.toml` Extension packaging (Blender 4.2+/5.x), `register()/unregister()`.

- **P6 — Staged**
  - In-Blender Python DSL compiler (graph-diff vs oracle), MRT, points/agents draw modes, 3D
    volumes/raymarch, Linux headless CI path. Docs + examples + README + memory.

## Harness specifics

- macOS forces **GUI mode** (no `--background` GPU). All candidate renders go through
  `blender --factory-startup --python <script>` with a timer that renders then quits.
- Capture params match siblings: 256×256, normalized time, linear 8-bit, row-flipped to top-down.
- Tolerances: strict (max-diff ≤ 1) where achievable; relaxed (≤ 2–4 + SSIM ≥ 0.98) for
  discontinuity-heavy/Metal-divergent effects.

## Constraints

- Local-only; **do not push** without instruction. Omit `Co-Authored-By` on commits.
- Additive: never modify `../noisemaker`. The port consumes it read-only.
- Scope: `../noisemaker/shaders` + `../noisemaker/docs/shaders` ONLY — never the legacy Python/TF
  `noisemaker/` package.

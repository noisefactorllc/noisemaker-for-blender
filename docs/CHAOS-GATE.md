# The chaos gate

**TL;DR.** Every deterministic effect in this port matches the reference to within the parity gate
(single-pass: byte-identical or ±1; navierStokes *in isolation*: SSIM ≥ 0.999). One class does
**not** pixel-match: **chaotic agent flows fed into navierStokes** (`points/flow` + the agent sims
that ride the same path — life/flock/attractor/hydraulic — and the continuous CAs lenia/mnca). They
render correctly, deterministically, and stay bounded, but they are a *different instance* of the
chaos, not a pixel match (full-chain SSIM ~0.0–0.7 over 30 s / 5 s sampling). This is **engine-level
floating-point divergence, not a port bug**, and it is not reachable through Blender's `gpu` module.

## Why

Blender's `gpu`-module shader path lowers GLSL → Metal differently from the reference's WebGL2/ANGLE
path. The specs do **not** require correctly-rounded transcendentals (`pow`/`exp2`/`log2`/`sin`),
so the two toolchains legally differ by ~1 ULP (~1e-8). For single-pass effects this is invisible
(byte-identical). For an iterated/feedback sim it is amplified:

- The `points/flow` agent steers each agent by the **OKLab lightness** of the sampled colour
  (`oklab_l` → `srgb_to_linear` uses `pow(x, 2.4)`, `cube_root` uses `pow(x, 1/3)`), exactly the
  spot the sibling ports pinned. The ~1-ULP `pow` delta is multiplied into the steering angle
  (×`TAU·kink`), then forced through two per-frame discontinuities — `fract()` position wrap and
  integer `texelFetch` texel boundaries — so over ~300 frames the agent field diverges visibly.
- navierStokes then **amplifies** that: a slightly different dye/velocity input, advected for 1800
  frames at speed 145, is the textbook butterfly effect — a different-but-equally-valid outcome.

It is the project's existing **"continuous solvers diverge cross-backend"** principle (already true
for reactionDiffusion / mnca) confirmed for the chaotic *agent flow*.

## Evidence it is NOT a port bug

- **Post-process is byte-exact.** adjust (max-diff 0), chromaticAberration (max-diff 0), bloom
  (max-diff 1), and the lighting/palette used by the byte-identical corpus programs all match. So
  the brightness/hue differences seen in chaotic programs (GyzQxg, u_8aBg, awB68w, …) come from the
  *upstream* agent→nav field, not the colour/lighting stages.
- **navierStokes in isolation is SSIM ≥ 0.999** (smooth static input, the target's exact params).
- **The deposit / diffuse / blend / agent-spawn / single-pass paths are byte-identical** (incl. the
  1M-agent point/billboard scatter at default stateSize).
- The divergent set is *exactly* the flow/agent→navierStokes programs (and lenia/mnca); nothing
  else.

## What was tried (and did not work on Blender)

The two stabilization mitigations the sibling ports use were ported and **measured**, then reverted
— they are toolchain-specific and do not transfer to Blender's `gpu` codegen:

- **Density-cull hi/lo split** (`fract(float(id)·φ)` split by radix 4096): fixes a *catastrophic*
  fract bucketization the sibling toolchains hit at ~1M agents. Blender's codegen does **not** have
  that bucketization, so the split's different arithmetic instead moves *away* from ANGLE's direct
  `fract` (which Blender already matches) — it **regressed** the integration target (0.50 → 0.38)
  with no benefit on the over-bloom targets. Reverted.
- **navierStokes input clamp to [0,1]**: a no-op here (no measured benefit). Reverted.
- `precise` qualifier: rejected by Blender's `gpu` shader compiler.
- Rewriting `pow(x,y)` → `exp2(y·log2(x))`: the sibling analysis showed this is a no-op (their
  `pow` already lowers to exp2/log2); it cannot make Blender's `pow` *more* like ANGLE's.

Closing the gap would require an engine-level change to Blender's transcendental lowering (out of
port scope).

## The gate

- **Deterministic effects** (single/multi-pass synth/filter/mixer, 3D, navierStokes in isolation):
  byte-identical or ±1, SSIM ≥ 0.98. These are the bar.
- **Chaotic agent-flow → navierStokes** (and lenia/mnca continuous CAs): **SSIM-divergent by
  design.** Accepted as faithful/stable/bounded but not a pixel match — the same class as
  reactionDiffusion. They are run with the stateful recipe (1800 frames @ 1/600, 30 s / 5 s
  sampling) and graded for *stability and character*, not pixel parity.

See `parity/CORPUS-SCORECARD.txt` for the per-program numbers and `README.md` → "Platform note".

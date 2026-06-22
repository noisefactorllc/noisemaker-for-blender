# noisemaker-blender

A Blender port of the [Noisemaker](../noisemaker/shaders) procedural shader engine — Polymorphic
DSL compiler, render-graph executor, and effects collection — running on Blender's `gpu` module
(Metal/Apple). Sibling to `noisemaker-hlsl` (Unity), `noisemaker-godot`, `noisemaker-td`
(TouchDesigner), `noisemaker-three`, `noisemaker-babylon`.

**Target:** Blender 5.1 · Python 3.13 · Metal. Local-only; not pushed.

## What this is (and isn't)

Blender's **compositor cannot host custom GLSL nodes** (a fixed C-defined node set; Python can't
add to it). So this is **compositor-*feeding***, not compositor-native: effects run via the `gpu`
module offscreen and **bake into Image datablocks** that the real compositor consumes through
Image nodes. A custom (`CUSTOM`) node tree provides the noisemaker graph UI (staged). See
[`docs/BLENDER-PLATFORM-NOTES.md`](docs/BLENDER-PLATFORM-NOTES.md).

## Architecture

The universal **render-graph JSON** seam (`docs/GRAPH-JSON-SCHEMA.md`) is produced verbatim by the
reference compiler (`tools/export-graph.mjs`) and consumed by a Python backend on the `gpu` module.
Effect GLSL is transpiled mechanically (`tools/convert-shaders-blender.mjs`) into a `.frag` body +
`.createinfo.json` descriptor (uniforms→push-constants, samplers, output), since Metal requires
`gpu.shader.create_from_info` and forbids inline `uniform`. See [`ARCHITECTURE.md`](ARCHITECTURE.md)
and [`PORTING-GUIDE.md`](PORTING-GUIDE.md).

## Status

| Phase | State |
|---|---|
| P0 scaffold + GPU de-risk | ✅ (`blender/harness/spike_*.py`) |
| P1 shader transpiler | ✅ 249/249 transpiled; **218 compile on Metal** (std140 UBO path + load-time MSL fixups: builtin-shadow rename, C++ alt-token rename, type-aware vecN==, mat2 vec-ctor, struct constructors; rest: staged MRT/varying + a few hard per-effect cases) |
| P2 backend + **Tier-1 parity gate** | ✅ **8/8 pass** (7 byte-identical, blur ±1) |
| P4 single-pass sweep | ✅ **61/64 rendered pass** (NEAREST+CLAMP via texelFetch); 2 stateful→P3, 1 crt |
| P3 executor: double-buffered surfaces, 3-tier ping-pong, iteration (`repeat`), `resolveDimension`, timed evolution (1800f @ 1/600) | ✅ |
| **points/agents** (MRT + drawMode:points/billboards, additive ONE,ONE) | ✅ **byte-identical** (flow/flock/pointsRender/billboards, even @1800 timed) |
| **3D perlin** (`#define DIMENSIONS 3`) | ✅ **byte-identical** |
| **navierStokes** parity | ✅ **ssim 0.999** (smooth input @ speed 55 & 145 = the continuous-solver bar) |
| breadth compile-fixes (palette struct-array, const-int→#define) | ✅ palette (was fail); classicNoisedeck PUSH_OVER_128 → UBO path staged |
| **Integration target** (32 passes: perlin3d+agents+billboards+blur+navierStokes+palette/lighting+bloom/lens/vignette) | ✅ **renders end-to-end** (ssim 0.496; structure/colour match — chaotic-precision gap) |
| **Agent behaviors** (life/hydraulic/attractor/lenia/mnca) | ✅ **all structurally render**; life was 8×8-clamped to black → fixed (pooled-slot envelope + §10.7 swap); residual = chaotic/exp precision wall |
| **loopBegin/loopEnd** feedback construct (zp_G3w) | ✅ renders (ssim 0.69) — fixed `vecN==vecN` ternary → `all(equal())` (Blender MSL rejects bvecN conditions) |
| 20-program blaster corpus scorecard | 🔄 **19/19 renderable** (B5oBsA non-reference, skip); mean ssim **0.56** (was 0.48); 5≥0.9, 3 byte-identical |
| **In-Blender DSL compiler** (lexer→parser→validate→expand→graph, stdlib-only) | ✅ **byte-identical to the reference** (`compile_graph` == `tools/export-graph.mjs`); gates lex/parse/compile **20/20**, expand/graph **19/19**; addon needs no external engine to author or compile |
| **P5 integration surface** (bake-to-Image operator + CUSTOM node tree + N-panels) | ✅ **gated byte-exact** (`parity/integration.sh`): DSL→operator→Image == reference golden (max-diff 0, ssim 1.0); breadth-checked across single/multi-pass, multi-surface, and stateful (frames+timestep) shapes, render-level compiler drop-in (`compile_graph`==`graph.json`), and graceful error paths |
| **classicNoisedeck std140 UBO path** (>128B push-constant overflow) | ✅ implemented + de-risked (`spike_ubo*.py`); `cnd_noise`/`cnd_shapes` **byte-identical** via UBO; Metal vec3=16 layout fix |
| **classicNoisedeck namespace** | ✅ 19/20 compile (colorLab/bitEffects/fractal fixed; `cnd_noise/shapes/fractal/bitEffects/caustic/moodscape/noise3d` **byte-identical**); only `shapeMixer` left (scalar reflect/refract Metal-overload quirk) |
| P6 shapeMixer scalar reflect/refract; attractor/lenia/life chaotic-precision | staged |

**Out of scope:** media plugin (MIDI/audio inputs).

### Platform note (cross-engine precision)
Blender's `gpu`-module Metal shader codegen differs from the reference's ANGLE path (transcendentals/fma/divide-singularities). This is **invisible for single-pass effects** (byte-identical) but **amplified by chaotic iteration** (navierStokes with sharp input, `flow:chaotic`). `babylon` reaches byte-identical on these *only because it runs the same ANGLE compiler as the reference*; through Blender's gpu module, raw chaotic byte-parity isn't reachable — structural parity is.

## Using the addon

The addon renders a Noisemaker DSL program with the `gpu` module and **bakes the result into
an Image datablock** — the real compositor consumes it through a stock **Image node**
("compositor-feeding"; Blender's compositor node set is C-defined and closed to Python).

1. **Enable** — Edit ▸ Preferences ▸ Add-ons ▸ install `blender/noisemaker_blender/`, enable "Noisemaker".
2. **Author** — in the Text Editor write a DSL program, e.g.
   ```
   search synth, filter
   noise(seed: 1, scaleX: 50, scaleY: 50).adjust().write(o0)
   render(o0)
   ```
   (or point the panel at an external `.dsl` file).
3. **Bake** — in the **Compositor** or **Image Editor** sidebar (`N`) ▸ **Noisemaker** tab,
   pick the Text block, set Size/Time, and click **Bake**. Or use the **Noisemaker** node
   editor: add a *Program* node (Shift+A), set its DSL + params, and Bake from the node.
   The result lands in an Image datablock (default name `Noisemaker`).
4. **Consume** — add an **Image node** in the compositor pointing at that datablock (or use it
   as any texture). It's stored `Non-Color` (raw linear values, matching the reference capture).

For stateful effects (navierStokes, agent sims, reaction-diffusion, cellular automata) raise
**Frames** and set **Timestep** (≈ `0.00167` = 1/600) so the simulation evolves to steady state.

## Running the parity gate

```sh
# 1. graph + golden (goldens are byte-identical across ports; reused from a sibling)
NM_REFERENCE_ROOT=../noisemaker node tools/export-graph.mjs --file parity/programs/noise.dsl parity/out/noise.graph.json
cp ../noisemaker-godot/parity/out/noise.golden.png parity/out/

# 2. render candidate (GUI mode — macOS GPU needs a context; self-quits)
NM_JOBS='[{"graph":"parity/out/noise.graph.json","out":"parity/out/noise.candidate.png"}]' \
  blender --factory-startup --python blender/harness/render_all.py

# 3. grade
python parity/compare.py parity/out/noise.golden.png parity/out/noise.candidate.png --name noise
```

The **DSL compiler** is gated separately on plain `python3` (stdlib only), comparing the
in-addon `compile_graph` against the reference graph byte-for-byte:

```sh
for g in lex parse compile expanded graph; do python parity/compiler/check_$g.py; done
```

The **integration surface** (DSL → bake operator → Image datablock) has its own one-command
end-to-end gate (needs the `adjust` golden seeded in `parity/out/`):

```sh
bash parity/integration.sh    # registers the addon, bakes adjust.dsl, grades vs the golden
```

## Layout

```
reference/            engine-agnostic re-implementer specs (01–10, verbatim)
docs/                 GRAPH-JSON-SCHEMA, BLENDER-PLATFORM-NOTES, IMPLEMENTATION-PLAN
tools/                export-graph.mjs, convert-definitions.mjs, convert-shaders-blender.mjs
parity/               compare.py, programs/*.dsl, corpus/, out/ (generated)
blender/
  noisemaker_blender/ the addon: backend/ runtime/ shaders/ effects/ nodes/ ops/ compiler/
  harness/            spike_*.py (de-risk), compile_check.py, render_all.py
```

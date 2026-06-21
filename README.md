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
| P1 shader transpiler | ✅ 249/249 transpiled; **194 compile on Metal** (rest: staged MRT/UBO/varying) |
| P2 backend + **Tier-1 parity gate** | ✅ **8/8 pass** (7 byte-identical, blur ±1) |
| P4 single-pass sweep | ✅ **61/64 rendered pass** (NEAREST+CLAMP via texelFetch); 2 stateful→P3, 1 crt |
| P3 executor: double-buffered surfaces, 3-tier ping-pong, iteration (`repeat`), `resolveDimension`, timed evolution (1800f @ 1/600) | ✅ |
| **points/agents** (MRT + drawMode:points/billboards, additive ONE,ONE) | ✅ **byte-identical** (flow/flock/pointsRender/billboards, even @1800 timed) |
| **3D perlin** (`#define DIMENSIONS 3`) | ✅ **byte-identical** |
| **navierStokes** parity | ✅ **ssim 0.999** (smooth input @ speed 55 & 145 = the continuous-solver bar) |
| breadth compile-fixes (palette struct-array, const-int→#define) | ✅ palette (was fail); classicNoisedeck PUSH_OVER_128 → UBO path staged |
| **Integration target** (32 passes: perlin3d+agents+billboards+blur+navierStokes+palette/lighting+bloom/lens/vignette) | ✅ **renders end-to-end** (ssim 0.496; structure/colour match — chaotic-precision gap) |
| 20-program blaster corpus scorecard | 🔄 (19/20 renderable; B5oBsA uses non-reference effects) |
| P5 integration (bake-to-Image, node tree) | ⏳ |
| P6 in-Blender DSL compiler; classicNoisedeck UBO; attractor/lenia/life | staged |

**Out of scope:** media plugin (MIDI/audio inputs).

### Platform note (cross-engine precision)
Blender's `gpu`-module Metal shader codegen differs from the reference's ANGLE path (transcendentals/fma/divide-singularities). This is **invisible for single-pass effects** (byte-identical) but **amplified by chaotic iteration** (navierStokes with sharp input, `flow:chaotic`). `babylon` reaches byte-identical on these *only because it runs the same ANGLE compiler as the reference*; through Blender's gpu module, raw chaotic byte-parity isn't reachable — structural parity is.

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

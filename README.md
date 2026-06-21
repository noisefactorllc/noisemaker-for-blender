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
| P3 full executor (feedback/ping-pong/iteration/blend) | ⏳ navierStokes, points/agents |
| P4b breadth: compile-fail effects (palette, classicNoisedeck…) | ⏳ |
| P5 integration (bake-to-Image, node tree) | ⏳ |
| P6 in-Blender DSL compiler; MRT/points/3D | staged |

**Out of scope:** media plugin (MIDI/audio inputs).

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

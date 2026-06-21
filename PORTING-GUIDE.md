# noisemaker-blender — Porting Guide (shader translation)

How a reference GLSL effect program (`noisemaker/shaders/effects/<ns>/<name>/glsl/<prog>.glsl`)
becomes a Blender `gpu`-module shader. The translation is **mechanical** (a transpiler,
`tools/convert-shaders-blender.mjs`) plus a small fixed runtime wrapper. The reference GLSL
*body* is reused **verbatim**; only declarations move out of the source into a Python
`GPUShaderCreateInfo` descriptor. See `docs/BLENDER-PLATFORM-NOTES.md` for the proof of each rule.

## The transpile (per `<prog>.glsl` → `<prog>.frag` + `<prog>.createinfo.json`)

Reference fragment program looks like:
```glsl
#version 300 es
precision highp float;
#ifndef NOISE_TYPE
#define NOISE_TYPE 10
#endif
uniform float time;
uniform vec2 resolution;
uniform sampler2D inputTex;
out vec4 fragColor;
void main() { ... fragColor = ...; }
```

Transform rules:

1. **Strip** `#version`, `precision ...;` lines (Blender injects `#version`; precision is implicit).
2. **Lift every `uniform <type> <name>;`** out of the body into the create-info descriptor as a
   **push_constant** (scalars/vec/mat) — record `{type,name}`. Delete the line from the body.
   `uniform` is illegal in MSL source, so this is mandatory, not cosmetic.
3. **Lift every `uniform sampler2D <name>;`** (and `sampler3D`) into a **sampler** entry
   `{slot,'FLOAT_2D'|'FLOAT_3D',name}`. Delete the line. Body keeps `texture(name, uv)` verbatim.
4. **Lift `out vec4 <name>;`** into `fragment_out(0,'VEC4',name)`. Keep the name; the body’s
   `name = ...` assignment is unchanged. (MRT: multiple `out` → multiple `fragment_out` slots —
   staged.)
5. **Keep `#define`/`#ifndef` blocks verbatim** in the body. Compile-time defines (`NOISE_TYPE`,
   `LOOP_OFFSET`, …) are injected by **prepending `#define K V`** lines to the source before
   compile (per-pass `defines{}` from the graph). Cache compiled shaders per (prog, define-set).
6. **Body is otherwise verbatim** — PCG, helpers, `gl_FragCoord`, math, control flow all reused.
   PCG divisor `4294967295.0`. No `#include` (reference programs are self-contained).
7. **Engine/system uniforms** (`time`, `resolution`, `seed`, `tileOffset`, `fullResolution`,
   `aspectRatio`, `renderScale`, `frame`, `deltaTime`) are just push_constants like any other,
   fed every pass by the pipeline. Coordinate convention (unchanged): `st = (gl_FragCoord.xy +
   tileOffset) / fullResolution.y` (divide by **height**).

The descriptor (`.createinfo.json`) is consumed by the Python backend to build the
`GPUShaderCreateInfo` at load time:
```json
{ "pushConstants": [["FLOAT","time"],["VEC2","resolution"], ...],
  "samplers": [[0,"FLOAT_2D","inputTex"]],
  "fragmentOut": [[0,"VEC4","fragColor"]] }
```

## Push-constant 128-byte budget

Metal push-constant block ≤ 128 bytes (≈ 8×vec4). Most effects fit. The transpiler **sums the
std140 size**; if a program exceeds 128 bytes it emits `"ubo": true` and the backend packs those
uniforms into a UBO instead (staged; no Tier-1 effect overflows).

## The fixed vertex wrapper (all effects share)

```glsl
void main() { gl_Position = vec4(pos, 0.0, 1.0); }   // info.vertex_in(0,'VEC2','pos')
```
Fullscreen triangle `pos = [(-1,-1),(3,-1),(-1,3)]`. The fragment body uses `gl_FragCoord`, so no
interpolated UV is needed.

## Type map (GLSL → create-info)

| GLSL | create-info type |
|---|---|
| `float`/`int`/`bool` | `FLOAT`/`INT`/`BOOL` (bool fed as 0/1 via uniform_int) |
| `vec2/3/4` | `VEC2/3/4` |
| `ivec*` | `IVEC*` ; `mat3/4` | `MAT3/4` |
| `sampler2D` | sampler `FLOAT_2D` ; `sampler3D` | `FLOAT_3D` |

## Parity rules (carry over from siblings)

- Cross-check numeric constants against the **GLSL** reference, never the WGSL (the WebGL2 golden
  *is* the GLSL path; porting from WGSL bit godot — the curl seed bug).
- All surfaces sampled **NEAREST**, wrap **CLAMP_TO_EDGE** (load-bearing for warp/resample
  effects). Set on every `GPUTexture`.
- Render targets are linear RGBA16F; shaders do any sRGB math themselves.
- Expect ±1–2/255 (half-float / MSL). Tolerances live in `parity/sweep.sh`.

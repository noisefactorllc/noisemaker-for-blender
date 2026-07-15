# Noisemaker for Blender — Porting Guide (shader translation)

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
3. **Lift every `uniform sampler2D <name>;`** into a **sampler** entry `{slot,'FLOAT_2D',name}`
   and delete the line. **Rewrite every 2-arg `texture(s, uv)` in the body to the `nmTex(s, uv)`
   macro** (a `texelFetch` with `clamp`, prepended as a `#define`) — this forces NEAREST + CLAMP,
   because the `gpu` module has no sampler filter/wrap state (it would default to LINEAR/REPEAT).
   The explicit-LOD 3-arg `textureLod(s, uv, lod)` form (e.g. `filter/parallax`'s ray march) gets
   the same treatment via a second macro, `nmTexLod(s, uv, lod)`, that ignores its `lod` arg (every
   render target here is a single mip level, so the requested LOD is always a no-op).
   (3D volumes are 2D atlases sampled with `sampler2D`; there is no `sampler3D`/`FLOAT_3D`.)
4. **Lift `out vec4 <name>;`** into `fragment_out(0,'VEC4',name)`. Keep the name; the body’s
   `name = ...` assignment is unchanged. **MRT**: multiple `out` → multiple `fragment_out` slots,
   bound via a multi-attachment framebuffer (implemented — 21 programs use it: agent state, 3D
   precompute, render3d). A graph output key may differ from the GLSL `out` name (e.g. `fragColor`
   ↔ `color`); the backend maps by name, falling back to slot position.
5. **Keep `#define`/`#ifndef` blocks verbatim** in the body. Compile-time defines (`NOISE_TYPE`,
   `LOOP_OFFSET`, …) are injected by **prepending `#define K V`** lines to the source before
   compile (per-pass `defines{}` from the graph). Cache compiled shaders per (prog, define-set).
6. **Body is otherwise verbatim** — PCG, helpers, `gl_FragCoord`, math, control flow all reused.
   PCG divisor `4294967295.0`. No `#include` (reference programs are self-contained). The one
   exception: a chain of **load-time GLSL→MSL fix-ups** (`backend/shader_build._body` →
   `std140.*`, each a no-op when nothing matches) repairs MSL-strictness cases ANGLE tolerates but
   Blender's Metal backend rejects — builtin-shadow rename, C++ alt-token rename, type-aware
   `vecN==`, `mat2(vec2,…)` ctor, struct constructors, `const` array params, redundant-prototype
   strip, scalar `reflect`/`refract`, `v_texCoord`→`gl_FragCoord`, multi-`uniform`-per-line split.
   See `docs/BLENDER-PLATFORM-NOTES.md` §5b.
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
uniforms into a std140 UBO instead (**implemented** — ~11 effects, mostly the big classicNoisedeck
generators; plus remap's explicit `vec4 data[267]` zone-config block). **std140-on-Metal gotcha: a
`vec3` occupies 16 bytes, not 12** (Blender maps `vec3`→Metal `float3`). See
`docs/BLENDER-PLATFORM-NOTES.md` §5b + `backend/std140.py`.

## The fixed vertex wrapper (all effects share)

```glsl
void main() { gl_Position = vec4(pos, 0.0, 1.0); }   // info.vertex_in(0,'VEC2','pos')
```
Fullscreen triangle `pos = [(-1,-1),(3,-1),(-1,3)]`. The fragment body uses `gl_FragCoord`, so no
interpolated UV is needed.

## Type map (GLSL → create-info)

| GLSL | create-info type |
|---|---|
| `float`/`int`/`bool` | `FLOAT`/`INT`/`BOOL` (BOOL push-constant, fed via `shader.uniform_bool`) |
| `vec2/3/4` | `VEC2/3/4` |
| `ivec*` | `IVEC*` ; `mat3/4` | `MAT3/4` |
| `sampler2D` | sampler `FLOAT_2D` (no `sampler3D` — 3D volumes are 2D atlases) |

## Parity rules (carry over from siblings)

- Cross-check numeric constants against the **GLSL** reference, never the WGSL (the WebGL2 golden
  *is* the GLSL path; porting from WGSL bit godot — the curl seed bug).
- All surfaces sampled **NEAREST**, wrap **CLAMP_TO_EDGE** (load-bearing for warp/resample
  effects). Enforced **in shader source** via the `nmTex` `texelFetch` macro (rule 3) — the `gpu`
  module has no `GPUTexture` filter/wrap API to set.
- Render targets are linear RGBA16F; shaders do any sRGB math themselves.
- Expect ±1–2/255 (half-float / MSL). Tolerance defaults are in `parity/compare.py`
  (`--tolerance 2`, `--ssim-min 0.98`); per-program overrides live at the call sites
  (`parity/integration.sh`, `parity/scorecard.py`).

## Adding / regenerating an effect

```sh
# transpile reference GLSL -> .frag + .createinfo.json (one effect, or omit the arg for all)
NM_REFERENCE_ROOT=../noisemaker node tools/convert-shaders-blender.mjs synth/noise   # --dry-run to preview
# regenerate its definition JSON (effects/<ns>/<func>.json)
NM_REFERENCE_ROOT=../noisemaker node tools/convert-defs-blender.mjs
# confirm it compiles on Metal
blender --factory-startup --python blender/harness/compile_check.py        # NM_ONLY=synth/noise/noise to scope
```
Output goes under `blender/noisemaker_blender/shaders/effects/` (override with `NM_OUT_DIR`). Then
add a `parity/programs/<name>.dsl` + golden and grade per "Running the parity gates" in the README.

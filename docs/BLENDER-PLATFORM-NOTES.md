# Blender Platform Notes (empirical)

Target: **Blender 5.1.2**, Python **3.13.9**, GPU backend **METAL / APPLE** (Apple Silicon).
Every claim below was verified on this machine with a spike (see `blender/harness/spike_*.py`),
not just from docs. These are the load-bearing facts the backend depends on.

## 1. The compositor cannot host this; we *feed* it

Compositor nodes are a fixed, C-defined set. Python **cannot** add nodes to the compositor
tree (`CompositorNodeCustomGroup` only wraps groups of existing stock nodes). Therefore a
faithful GLSL port is **not "compositor-native."** The design is **"compositor-feeding"**: run
the effects via the `gpu` module, bake the result into an **Image datablock**, which the real
compositor consumes through a standard **Image node**. A bespoke `CUSTOM` node tree (with a
hand-written evaluator) provides the noisemaker graph UI. This limit is fundamental, not a gap.
(OSL is CPU/material-only — rejected. DSL→native-compositor-graph is infeasible — rejected.)

## 2. GPU works only in GUI mode (not `--background`) on macOS

`blender -b --python ...` raises **`SystemError: GPU functions for drawing are not available
in background mode`** the moment you touch the GPU (even `gpu.platform.backend_type_get()`).
Module *import* works headless; *drawing* does not.

**Consequence — the harness mirrors the TouchDesigner `.toe` pattern:** launch Blender **with
GUI**, run a `--python` script that defers GPU work to a `bpy.app.timers` callback (fires after
the window/context is live, `first_interval≈0.5`), renders all programs, then
`bpy.ops.wm.quit_blender()`. A window flashes briefly — same as the TD harness. (If CI ever
needs true headless, run it on **Linux**, where EEVEE/gpu headless is supported.)

## 3. Shaders: `create_from_info` only — no raw GLSL, no `uniform` keyword

The legacy `GPUShader(vertexcode=, fragcode=)` constructor is **rejected at runtime on Metal**.
Must use `gpu.shader.create_from_info(GPUShaderCreateInfo)`. Inside the GLSL source:

- **NEVER write `uniform ...;`** — `uniform` is a reserved MSL template keyword; it fails with
  *"use of class template 'uniform' requires template arguments."* Declare every uniform via
  `info.push_constant(type, name)` and reference the **bare name** in the body.
- Likewise strip `#version`, `precision ...;`, and global `in`/`out` declarations from the body.
  Declare the fragment output via `info.fragment_out(0,'VEC4',name)`; declare samplers via
  `info.sampler(slot,'FLOAT_2D',name)`; declare the fullscreen attribute via `info.vertex_in`.
- `gl_FragCoord` **is available** in the fragment body (the reference's coordinate source).
- Vertex shader is ours (fullscreen triangle): `gl_Position = vec4(pos,0,1)`.

## 4. Render target + readback: linear RGBA16F, flatten, quantize, flip

- Render to **`GPUOffScreen(W,H,format='RGBA16F')`** — float, **no sRGB encoding** (verified:
  linear `0.4` stores/reads as `0.4`, quantizes to `102`, *not* sRGB `168`). Matches the
  reference's "linear 16-bit, `round(v*255)`, no gamma."
- Read back with **`fb.read_color(0,0,W,H,4,0,'FLOAT')`**. The returned `Buffer` is **3-D
  `[H,W,4]`** and `np.array()` mis-reads it — you **must flatten first**:
  `buf.dimensions = W*H*4; arr = np.array(buf, np.float32).reshape(H,W,4)`.
- **Row 0 is the BOTTOM** of the image (GL origin). Flip vertically (`arr[::-1]`) to match the
  top-down goldens.
- Quantize with `round(clip(v,0,1)*255)`.

## 5. Core ops, all verified

| Op | API |
|---|---|
| compile | `gpu.shader.create_from_info(info)` |
| push uniform | `shader.uniform_float/int(name, value)` (bound by name; VEC2/3/4 OK) |
| sampler input | `info.sampler(slot,'FLOAT_2D',name)` + `shader.uniform_sampler(name, GPUTexture)` |
| create texture w/ data | `GPUTexture((w,h), format='RGBA16F', data=Buffer('FLOAT', n, [...]))` |
| fullscreen draw | `batch_for_shader(sh,'TRIS',{"pos":[(-1,-1),(3,-1),(-1,3)]}); batch.draw(sh)` |
| offscreen | `with off.bind(): fb = gpu.state.active_framebuffer_get(); fb.clear(...)` |

## 6. Parity expectation

Candidate (Blender GLSL→**MSL**) vs golden (reference WebGL2 → ANGLE→**Metal**): both land on
Metal but via different translators, so expect **±1–2/255** half-float divergence. Use the
**relaxed-tolerance table** the Metal-backed godot/td ports already established
(strict max-diff ≤ 1 where possible; relaxed ≤ 2–4 + SSIM ≥ 0.98 for discontinuity-heavy
effects). Byte-tight parity is *not* expected and not required.

## Sources (Blender 4.x/5.x docs; confirmed on 5.1.2)
gpu / gpu.types / gpu.shader API; GPUShaderCreateInfo + create_from_info; GLSL cross-compilation
(BSL→MSL); Metal-only backend on Apple Silicon (OpenGL deprecated 4.0); legacy ctor removal;
EEVEE/gpu headless unsupported on macOS; CompositorNodeTree fixed node set; Python 3.11 (4.x) /
3.13 (5.1). Full URL list in the Phase-0 research log.

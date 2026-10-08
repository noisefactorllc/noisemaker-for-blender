# Blender Platform Notes (empirical)

Target: **Blender 5.1.2**, Python **3.13.9**, GPU backend **METAL / APPLE** (Apple Silicon).
The historical sections record the original backend spikes (`blender/harness/spike_*.py`).
Current integration qualification is recorded in section 7; historical counts are not current
full-catalog or realtime acceptance.

## 1. The compositor cannot host this; we *feed* it

Compositor nodes are a fixed, C-defined set. Python **cannot** add nodes to the compositor
tree (`CompositorNodeCustomGroup` only wraps groups of existing stock nodes). Therefore a
faithful GLSL port is **not "compositor-native."** The design is **"compositor-feeding"**: run
the effects via the `gpu` module, bake the result into an **Image datablock**, which the real
compositor consumes through a standard **Image node**. A bespoke `CUSTOM` node tree (with a
hand-written evaluator) provides the noisemaker graph UI. This limit is fundamental, not a gap.
OSL does not provide this port's complete multipass feedback graph contract; it is not the
integration path. Its CPU/OptiX availability does not change that boundary.

## 2. GPU works only in GUI mode (not `--background`) on macOS

`blender -b --python ...` raises **`SystemError: GPU functions for drawing are not available
in background mode`** the moment you touch the GPU (even `gpu.platform.backend_type_get()`).
Module *import* works headless; *drawing* does not.

**Consequence — the harness mirrors the TouchDesigner `.toe` pattern:** launch Blender **with
GUI**, run a `--python` script that defers GPU work to a `bpy.app.timers` callback (fires after
the window/context is live, `first_interval≈0.5`), renders all programs, then
`bpy.ops.wm.quit_blender()`. A window flashes briefly — same as the TD harness. Fresh `gpu` evaluation on other operating systems needs its own native qualification; do not
infer it from a successful background scene render or a GPU-module import.

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
- Legacy capture quantizes with `round(clip(v,0,1)*255)`. The live/session float path retains
  negative/HDR samples and flips rows without clipping or quantization.

## 5. Core ops, all verified

| Op | API |
|---|---|
| compile | `gpu.shader.create_from_info(info)` |
| push uniform | `shader.uniform_float/int(name, value)` (bound by name; VEC2/3/4 OK) |
| sampler input | `info.sampler(slot,'FLOAT_2D',name)` + `shader.uniform_sampler(name, GPUTexture)` |
| create texture w/ data | `GPUTexture((w,h), format='RGBA16F', data=Buffer('FLOAT', n, [...]))` |
| fullscreen draw | `batch_for_shader(sh,'TRIS',{"pos":[(-1,-1),(3,-1),(-1,3)]}); batch.draw(sh)` |
| offscreen | `with off.bind(): fb = gpu.state.active_framebuffer_get(); fb.clear(...)` |

## 5b. Push constants cap at 128 bytes → std140 UBO (backend/std140.py)

Metal push constants are limited to **128 bytes**; `create_from_info` errors *"Push constants
have a minimum supported size of 128 bytes, however the constants added so far already reach
NNN bytes. Consider using UBO."* once an effect's uniforms exceed it (~10 effects, e.g. the
big classicNoisedeck generators `noise`/`fractal`/`shapes3d` at 130–190 B). Those descriptors
are flagged `"ubo": true`; the backend compiles them with a **std140 uniform block** instead:

- `info.typedef_source("struct NmUniforms { ... };")` + `info.uniform_buf(0,"NmUniforms","nm_ub")`;
  bind a `GPUUniformBuf(Buffer('FLOAT', n, packed))` via `shader.uniform_block("nm_ub", ubo)`.
- **Anonymous blocks are NOT supported** (empty instance name → malformed MSL); the block needs
  a named instance, so members are referenced `nm_ub.<field>`. The shader body uses *bare* names,
  so we **scope-aware-rewrite** bare uniform refs → `nm_ub.<field>`, leaving declarations and
  shadowing locals/params alone (a `#define` can't — it rewrites the param decl too; e.g. noise's
  `multires(int octaves,…)` shadows the `octaves` uniform).
- **std140-on-Metal gotcha (load-bearing): a `vec3` occupies 16 bytes, not 12.** Blender maps
  GLSL `vec3`→Metal `float3` (size 16), so a scalar *following* a vec3 lands at +16. Textbook
  std140 (vec3 size 12) silently shifts every field after the first vec3→scalar boundary — it
  renders *almost* right (the palette/hue tail drifts) so it's easy to miss. `spike_ubo4.py`
  pins it with a known-answer over the real 24-field `noise` struct; `_ALIGN`/`_SIZE` use 16.
- Keep the value packing as the single source of truth (`std140.pack`) shared with the struct
  generator (`std140.struct_source`) so layout can't drift between the two sides.

**Load-time GLSL→MSL fix-ups** (`shader_build._body` → `std140.*`, applied to every effect; each
a no-op when nothing matches, all verified non-regressing via compile_check + golden grading).
These are MSL-strictness issues that ANGLE (the reference path) tolerates but Blender's MSL
backend rejects — surfaced once the cnd namespace started compiling:

- **builtin shadow** — `float max = max(r, max(g, b));` (inlined rgb→hsl helper). MSL rejects
  calling a builtin once a same-named local is in scope. `rename_shadow_builtins` renames the
  local scope-aware (keeping the builtin in the local's own initializer).
- **C++ alternative tokens** — `int or(int,int)` / `and` / `xor`: these are *keywords* in Metal's
  C++ (→ "expected member name or ';'"). `rename_cpp_alt_tokens` renames the identifier (skips
  comments/members); none are GLSL keywords so it's safe.
- **vecN==vecN(...) in bool contexts** — GLSL says it's a scalar bool, MSL makes a bvecN (rejected
  in `||`/`&&`/`?:`). The transpiler's fixVecBoolTernary catches the single-compare-before-`?`
  case; `fix_vec_bool_compare` also catches compound (`a==vec2(1) || a==vec2(3)`, colorLab).
  `all(equal(...))`/`any(notEqual(...))` is exactly equivalent.
- **mat2(vec2, float, float)** — Metal has no mixed vec2+scalar mat2 ctor; `fix_mat2_vector_ctor`
  expands the leading vec2 to components (`mat2(z,-z.y,z.x)` → `mat2(z.x,z.y,-z.y,z.x)`, fractal).
- **struct constructors** — Blender MSL emits a C++ ctor call for GLSL `Foo(a,b)` but never
  generates it; `fix_struct_constructors` injects a `nm_make_Foo(...)` maker per `struct` and
  rewrites the calls (newton, historicPalette).
- **`const` array params** — Metal lowers a `vec3 pal[4]` param to a *mutable* `vec3*`, so a
  `const` global array can't bind; `const_array_params` qualifies `in` array params `const` (dither
  palettes; GLSL `in` arrays are read-only copies, so it's exact).
- **redundant prototypes** — Blender wraps all functions in one MSL class, where a forward
  prototype + later definition is "class member cannot be redeclared"; `remove_redundant_prototypes`
  drops the prototype (dither).
- **scalar reflect/refract** — Metal's geometric lib has only `float2/3/4`+`half2/3/4` (no scalar
  overload), so GLSL `reflect(float,float)` is ambiguous; `fix_scalar_reflect_refract` injects
  scalar `nm_reflect`/`nm_refract` (exact GLSL formulas) and rewrites *only* scope-locally-scalar
  calls (shapeMixer's two `blend()` overloads share param names — vector calls keep the builtin).
- **`v_texCoord` varying** — the reference full-screen VS supplies `v_texCoord`; the port's VS does
  not, so `fixFragmentVarying` rewrites it to `gl_FragCoord.xy/vec2(textureSize(inputTex,0))`
  (grime/spookyTicker/texture/wobble).
- **multi-`uniform`-per-line** — the line-anchored uniform lifter missed `uniform int a; uniform
  int b;`; `splitMultiUniformLines` puts each on its own line first (mashup's `layerN_active`).
- **`const int` array-size EXPRESSIONS** (transpile-time, `convert-shaders-blender.mjs`'s
  `constIntToDefine`, not a `shader_build.py` runtime fixup like the rest of this list) — Blender's
  GLSL→MSL codegen rejects ANY top-level `const int` as an array size (non-static data member),
  literal or not; the transpiler already promoted the bare-literal case (`const int X = 4;` →
  `#define X 4`) to committed `.frag` source, but missed an arithmetic-expression RHS until the
  artistic-batch crystallization surfaced `filter/dither`'s `const int FS_ERR_W = FS_BLOCK +
  FS_APRON_MAX + FS_RPAD + 1;` (sizes its Floyd–Steinberg error-row array). Now promotes both
  shapes, parenthesizing the expansion for precedence. Catalog-wide grep confirms dither is (still)
  the only file this class of decl appears in.
- **`packHalf2x16`/`unpackHalf2x16`** — Blender's GLSL→MSL codegen has no builtin under either name
  ("undeclared identifier") — unlike scalar reflect/refract there's no Metal-side *ambiguity* to
  dodge, just an absent one, so `inject_pack_half2x16` prepends real polyfill functions under the
  exact reference names (no call-site rewriting needed), built on `floatBitsToUint`/
  `uintBitsToFloat` + `uint` bitwise ops already proven elsewhere in the catalog. Surfaced by
  `filter/median`'s new exact-quickselect packed-record sort key.

Result: classicNoisedeck **20/20 compile**; cnd_noise/shapes/fractal/bitEffects/caustic/moodscape/
noise3d byte-identical. `shapeMixer` is fixed via the injected scope-aware `nm_reflect`/`nm_refract`
above (byte-exact vs reference golden, max-diff 0.000). Across the catalog only `scope`/`spectrum`
(audio input, out of scope) do not compile → **301/303** (303 total programs as of the artistic-batch
crystallization: `filter/median` went from 3 programs to 1, net -2 vs the prior 305).

## 6. Parity expectation

The port's shaders are the reference GLSL bodies, so a case that differs from the reference does so
through one of three causes: a port defect (wrong uniform, format, binding or pass), a different
shader toolchain (Blender GLSL→MSL here, ANGLE in the browser), or a different GPU.

`scripts/parity-summary` mints its authority goldens with the reference engine in headless Chromium
on ANGLE over **Metal**, on the Apple-silicon GPU class the port renders on, and
`parity/golden-cdp.mjs` refuses any other renderer. Effects that put a hard discontinuity in the
per-pixel path (a `step()` threshold, an `fwidth()` antialiasing width, a high-exponent `pow()`
specular term, an oscillating `sin()` tone curve, an argmin or argmax pick, a raymarch hit test)
resolve it through the GPU's arithmetic. A golden from a different rasterizer lands on the other
side of it at a sparse set of pixels, so `max-abs-diff` reads high there while SSIM stays near 1.

SwiftShader, a CPU rasterizer, is therefore never the authority. At the 5976b7a pin the same 116
candidates grade 87 exact, 25 strict, 4 near and 0 failing against goldens minted on ANGLE over
Metal, and 1 exact, 49 strict, 8 near and 58 failing against goldens minted on SwiftShader. That
difference measures the rasterizer, not the port.

**Exception — the chaos class.** Chaotic agent→navierStokes chains and continuous CAs diverge by
design over long evolutions; see [`CHAOS-GATE.md`](CHAOS-GATE.md).

## 7. Live integration qualification

The 2026-10-07 native integration probes use Blender 5.1.2 / Apple M4 / Metal. Coherent float
Image publication reaches the measured stock consumers; writing only to an Image-associated GPU
texture does not update CPU pixels, Cycles, compositor and Geometry Nodes consistently. The
persistent session path preserves float samples; the old bake/parity path still quantizes.

Fresh GPU evaluation inside native animation's render callbacks crashed on the second frame.
Production callbacks only mark/suspend work. Scripted evaluation before each scene render passes
the tested Eevee/Cycles frame markers. Cycles Persistent Data needs a prepared EXR sequence to
refresh frames; generated Image updates alone retained the first frame. Background Blender can
reopen and render those verified caches without constructing a Noisemaker GPU session.

See [the implementation checkpoint](REALTIME-INTEGRATION-PLAN.md#9-implementation-status) for
individual harnesses, measurements and unqualified gates. These results do not establish native
F12 integration, full-catalog realtime performance or another platform's GPU behavior.

## Sources (Blender 4.x/5.x docs; confirmed on 5.1.2)
gpu / gpu.types / gpu.shader API; GPUShaderCreateInfo + create_from_info; GLSL cross-compilation
(BSL→MSL); Metal-only backend on Apple Silicon (OpenGL deprecated 4.0); legacy ctor removal;
EEVEE/gpu headless unsupported on macOS; CompositorNodeTree fixed node set; Python 3.11 (4.x) /
3.13 (5.1).

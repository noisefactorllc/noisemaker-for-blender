# Noisemaker for Blender realtime integration

## 1. Objective and status

The objective is a GPU port with immediate editor feedback and a supported Python API that integrates Noisemaker output into Blender scenes, animation, materials, geometry processing and compositing. An editable program must continue rendering while its output is used by other Blender systems. Manual rebaking cannot be the required authoring loop.

Sections 1–8 preserve the initial source audit, proposed architecture and remediation sequence.
Section 9 records implementation and native verification performed after the plan. It was prepared on 2026-10-07 against local `main` at `a2c473e23aca9840608fb9b1216b3af69e20eff4`, with a clean worktree before this document was added. No renderer, UI, test, dependency, workflow or historical audit document was changed. No implementation or release is qualified by this plan.

The recommended design retains the Python DSL compiler and Blender GPU backend, adds a persistent rendering session, and publishes each evaluated frame to a coherent floating-point Image. That Image is the baseline output path: Blender's Image Editor, material preview, compositor and Geometry Nodes already display or consume it. Direct GPU presentation in editor regions is an optimization, added only where task 0 measurements show Image publication cannot meet the preview gates. The same session API drives interactive use and deterministic rendering. Eevee and Cycles remain the scene renderers.

### 1.1 Required outcomes

1. A user can enable live preview, edit DSL or parameters, and see the result without pressing Bake. Invalid edits show a diagnostic while the last valid output remains visible.
2. Playback, scrubbing, keyframes and drivers evaluate the intended scene time. A simulation does not restart on every redraw or advance twice because two editors display it.
3. A Python script can create a program, bind inputs, set parameters, evaluate a frame, obtain a GPU output or Blender Image, connect consumers, and release resources without depending on the active editor or operator context.
4. Materials, world backgrounds, compositor graphs and image-sampling Geometry Nodes can consume current outputs. Actual consumer renders or evaluated geometry prove integration; links alone do not.
5. F12, animation rendering and scripted rendering use the correct program revision, inputs, frame, subframe and resolution. They never silently render a stale preview. Background GPU evaluation is qualified separately from consuming a prepared cache.
6. HDR values, alpha and color semantics survive the bridge. Display transforms are applied only at display/output boundaries.
7. Existing DSL behavior, graph output, saved node/scene settings, square bake API and historical parity protocol remain compatible.

## 2. Investigation method and results

### 2.1 Evidence gathered

Inspected the add-on registration, scene properties, custom node tree, panels, bake operator, graph wrapper, GPU resource/pass execution, frame stepping, sink/export contracts, host tests and CI definitions. Compared relevant integration responsibilities with upstream `shaders/src/runtime/pipeline.js`. Checked Blender's official Python API documentation and source for GPU presentation, Image textures, render engines, handlers and message-bus behavior.

Executed the existing engine-free unittest discovery under the bundled Python runtime with bytecode writes disabled:

```sh
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m unittest discover -s parity -p 'test_*.py' -q
```

Result: **227 tests passed in 3.029 seconds**, with no reported failures or skips. `$PYTHON` was the available bundled interpreter with NumPy and Pillow, not Blender's bundled Python. This was not the complete `scripts/test` entry point: no dependency installation, reference clone, compiler-golden regeneration or Blender process was run.

A native compiler smoke test compiled `noise(seed: 1).write(o0)` followed by `render(o0)` into two passes with output `o0`. A direct call to `default_engine(512, ...)` returned square resolution/fullResolution and aspect 1. A NumPy reproduction of the existing readback/write conversion mapped `-0.25 → 0`, `0.0005 → 0`, `0.5 → 0.5019608`, and `2.0 → 1`.

These are current source and CPU contract observations. No new GPU frame, interactive session, final Eevee/Cycles render, performance measurement or cross-platform qualification was executed. The repository's old rendered reports remain historical evidence, not measurements of the proposed system.

### 2.2 Confirmed gaps

The identifiers below belong to this plan. They do not renumber or close the historical `GAP-*` records. Line numbers refer to the audit revision `a2c473e`; later commits can move them (the next upstream sync shifted the cited `pipeline.py` ranges by five to six lines).

| ID | Finding and consequence | Current evidence |
|---|---|---|
| RT-01 | No editor live-render loop. Panels expose only Bake; the operator creates a backend for each job, publishes once at completion and frees it. | [panels.py](../blender/noisemaker_blender/ui/panels.py), lines 10–35; [bake.py](../blender/noisemaker_blender/ops/bake.py), lines 117–174 |
| RT-02 | The custom Program node has no evaluated output connection. Its Image socket is explicitly cosmetic, and the node only forwards settings to Bake. | [tree.py](../blender/noisemaker_blender/nodes/tree.py), lines 23–70 |
| RT-03 | No scene-time, dependency-graph, render, load or undo integration is registered by the add-on. Existing properties do not invalidate/render when changed. | [props.py](../blender/noisemaker_blender/props.py), lines 50–68; [registration](../blender/noisemaker_blender/__init__.py); source search across add-on Python files |
| RT-04 | Scriptability exists as a bake operator and internal classes, but there is no supported persistent session with parameter changes, inputs, resize, evaluation, output ownership and lifecycle. | [bake.py](../blender/noisemaker_blender/ops/bake.py), lines 7–21 and 177–228; [runtime exports](../blender/noisemaker_blender/runtime/__init__.py) |
| RT-05 | The float Image receives quantized, clipped 8-bit values. HDR, negative data and fine gradients are lost before Blender consumes them. | [gpu_backend.py](../blender/noisemaker_blender/backend/gpu_backend.py), lines 524–531; [bake.py](../blender/noisemaker_blender/ops/bake.py), lines 76–114; conversion reproduction above |
| RT-06 | Root output is square: one `size` feeds width, height, aspect, viewport resolution and sink descriptors. | [props.py](../blender/noisemaker_blender/props.py), lines 11–14; [pipeline.py](../blender/noisemaker_blender/runtime/pipeline.py), lines 542–553 and 1029–1062 |
| RT-07 | The existing stepper is a finite bake driver, with immutable initial time/step configuration and cached default uniforms. It is not a scene evaluation or indefinite live-session API. | [pipeline.py](../blender/noisemaker_blender/runtime/pipeline.py), lines 1001–1090 |
| RT-08 | Live-frame costs are not controlled: periodic whole-output readback every 30 evolving frames, shader files/descriptors read before each cache lookup, and new UBO objects allocated per applicable pass. | [pipeline.py](../blender/noisemaker_blender/runtime/pipeline.py), lines 1074–1082; [gpu_backend.py](../blender/noisemaker_blender/backend/gpu_backend.py), lines 261–279 and 340–361 |
| RT-09 | Output sinks receive an offscreen binding but are described as fixed 60 FPS, RGBA8/sRGB regardless of actual float output. No borrowed-texture lifetime is defined for Blender consumers. | [pipeline.py](../blender/noisemaker_blender/runtime/pipeline.py), lines 1029–1037 and 1070–1073; [sink tests](../parity/test_pipeline_sink.py) |
| RT-10 | No public host texture/mesh/text input binding exists in the backend/runtime. The graph wrapper does not expose `mediaSteps` as a convenience field, although raw graph data remains available. Compiler-level text or automation tests do not prove rendered host inputs. | [graph_loader.py](../blender/noisemaker_blender/runtime/graph_loader.py), lines 6–13; [backend](../blender/noisemaker_blender/backend/gpu_backend.py); [text test](../parity/test_text_style.py) |
| RT-11 | Existing material/compositor host tests create nodes and assert links; they do not render a scene/composite and compare received pixels across updates. | [test_host_workflows.py](../blender/harness/test_host_workflows.py), lines 101–136 |
| RT-12 | Current repository CI explicitly runs engine-free and GPU-context-free checks. It cannot prove editor realtime behavior, current image delivery, or GPU parity. | [tests.yml](../.github/workflows/tests.yml), lines 6–15 |
| RT-13 | Shared-editor GPU state and long-lived cleanup need qualification. Draw paths set blend to NONE rather than restoring prior state, lack a complete error-safe state guard, and backend `free()` leaves binding/cache dictionaries populated. | [gpu_backend.py](../blender/noisemaker_blender/backend/gpu_backend.py), lines 253–258 and 464–504 |
| RT-14 | General execution support needs explicit admission: unknown pass types return silently; only points and billboards have dedicated primitive paths; other draw modes take the fullscreen path. Existing broad README claims cannot establish mesh/compute integration. | [gpu_backend.py](../blender/noisemaker_blender/backend/gpu_backend.py), lines 368–387 |

### 2.3 Existing work to preserve

The compiler is native Python. `FrameStepper.step()` already advances one frame without inherently reading pixels every frame. The backend retains ping-pong surfaces, pooled targets, compiled shaders and fullscreen batches during a job. `SinkManager` can deliver each completed output. Long GUI bakes already run modally, process one frame per timer tick and support cancellation; they are not uniformly blocking as the README suggests. Cancellation preserves the previous Image and existing Image ownership checks protect unrelated content. [Bake implementation](../blender/noisemaker_blender/ops/bake.py), lines 15–26 and 230–305.

These mechanisms make incremental remediation plausible. Their existence does not demonstrate a frame-rate budget or correct long-lived embedding.

## 3. Blender integration boundary

### 3.1 Public API facts and uncertainties

Blender exposes offscreen rendering and drawing textures in editor regions. Its GPU documentation also gives a readback-to-Image example and identifies the pixel-transfer path as costly. Direct texture presentation and updating a stock Image are distinct operations. [GPU module examples](https://docs.blender.org/api/5.1/gpu.html).

Python add-ons cannot register new editor (Space) types. Direct presentation means draw handlers on existing spaces: the Image Editor, the Node Editor showing the Noisemaker node tree, or the 3D Viewport. Each handler draws over that space's own content and shares its GPU state.

`gpu.texture.from_image(image)` returns Blender's shared GPU texture for an Image, with scene-linear samples and alpha semantics derived from the Image. That documented direction is Image-to-GPU access. It does not establish that arbitrary GPU writes will update the CPU image buffer, Cycles texture storage, saved files, compositor caches or every render device. [Blender 5.1 texture API](https://docs.blender.org/api/5.1/gpu.texture.html).

Blender's GPU framebuffer API can attach GPU textures. A framebuffer drawing into an Image-associated texture is therefore a candidate for a bounded optimization probe, not a supported universal Image bridge assumed by this plan. Qualify redraw, invalidation, resource replacement, CPU coherence, save/reload and each consumer independently before adopting it. [Blender 5.1 GPU types](https://docs.blender.org/api/5.1/gpu.types.html).

Frame handlers can run while the viewport accesses data from another thread; Blender warns that unsafe mutation can crash it. Its documented mitigation is to lock the interface before starting a render (Render → Lock Interface, `RenderSettings.use_lock_interface`). Task 0 must test the render barrier with that setting enabled and disabled, and the add-on must enable it or refuse to mutate Images from frame handlers while a render runs with live instances. Notifications must enqueue or mark evaluation work and use a tested render barrier, not perform arbitrary GPU/Image mutation in every callback. The message bus alone is insufficient for animation changes. [Handlers](https://docs.blender.org/api/5.1/bpy.app.handlers.html), [message bus](https://docs.blender.org/api/5.1/bpy.msgbus.html).

The repository's statement that OSL is CPU-only ([platform notes](BLENDER-PLATFORM-NOTES.md), line 15) is stale: Blender documents CPU and OptiX support. OSL still does not supply this port's complete multipass, feedback and cross-engine graph contract, so replacing the port with OSL is not the proposed remedy. [Blender 5.1 Cycles settings](https://docs.blender.org/manual/id/5.1/render/cycles/render_settings/index.html).

### 3.2 Approaches considered

| Approach | Benefits | Limits | Decision |
|---|---|---|---|
| Persistent Python/GPU session publishing a coherent float Image, with optional direct preview | Reuses the current compiler/shaders; preserves Eevee/Cycles; one output path serves editors and consumers; practical Python automation | Stock consumers may require readback/upload and explicit invalidation | Recommended baseline; measure Image publication first and direct preview only if publication misses the preview gates |
| GPU-only Image sharing or native Blender integration | Potentially removes expensive transfers and permits deeper engine integration | Coherence and backend ownership are unproved; native changes impose version/platform maintenance | Probe early; use only for consumers that pass; native extension/source work requires an explicit design decision |
| A separate Noisemaker `RenderEngine` | Blender has viewport/final-render hooks and RenderResult/pass support | Selecting it replaces the scene engine; an overlay or separate engine alone does not make Eevee/Cycles materials evaluate Noisemaker | Not the primary remediation |

Blender's custom render-engine example distinguishes `view_update`, `view_draw` and final `render` responsibilities. Those hooks are useful reference material, but creating a new engine would not by itself meet the requested integration with existing engines. [RenderEngine API](https://docs.blender.org/api/5.1/bpy.types.RenderEngine.html).

Registering a Python node or custom group is also not proof of custom shader execution within stock engines. Use functional groups containing stock Image nodes and a separately evaluated Noisemaker resource, with explicit generation tracking. Do not label a decorative socket as an evaluated resource.

## 4. Proposed architecture

### 4.1 Data flow

```text
DSL + typed parameters + evaluated scene time + host inputs
                         |
                  Program / Instance
                         |
              persistent RenderSession
             compiler -> graph -> GPU passes
                  /                 \
       borrowed GPU output        float Image publication
               |                         |
   optional editor draw adapter  Image Editor / material preview /
                                 Shader / World / Compositor /
                                 Geometry Nodes image consumers
                         |
          deterministic render/cache preparation barrier
```

The diagram describes the proposed design, not implemented modules. Rendering sessions are scoped by program instance, scene/view-layer inputs and graphics context. GPU resources are runtime state and are never serialized into `.blend` files.

### 4.2 Program, instance and session

Separate serializable program/instance configuration from GPU execution state. Give each instance a stable identity independent of display names. Persist DSL/Text references, typed parameter bindings, input references, output pointers, loop/time policy and preview/render settings on Blender-owned data. Rebuild sessions after file load, undo/redo, context recreation or add-on registration. Detect duplicated identities when users duplicate scenes/nodes; create independent instances unless sharing was explicitly requested.

A session owns graph, backend, shader cache, state surfaces, parameter revisions and output generation. Scalar parameter changes update uniforms without recompiling or restarting a simulation. Defines, topology and resource-size changes follow separate invalidation paths. Compile and preflight a replacement before swapping it into use; leave the old graph and image intact on failure. Size-sensitive parameters must reallocate affected resources consistently, not just alter shader uniforms.

Parameter bindings, keyframes and drivers must survive DSL edits. Address each parameter by a stable key derived from the program, such as effect name, occurrence within the chain and parameter name (`noise#0.seed`), never by a bare step index that shifts when a step is inserted. On recompilation, rebind by key. A binding whose key no longer exists stays listed as orphaned with its animation intact until the user deletes or reassigns it; it is never dropped or silently attached to a different parameter. Store values as custom properties on the owning instance, with `id_properties_ui` ranges, defaults and descriptions, so Blender can keyframe and drive them without registering a new `bpy.props` class for each program. Enum-valued parameters need an explicit integer mapping and a UI that shows the names.

Retain a backward-compatible square `size` argument while adding independent physical-pixel width and height. Carry them through resource dimensions, engine uniforms, aspect, viewport, sinks, Images and capture. Preview resolution and final render resolution are distinct explicit settings, never silently substituted.

### 4.3 Proposed Python API

All names below are proposed. The public facade should import without requiring an active editor; GPU evaluation still requires a qualified graphics context.

```python
from noisemaker_blender import api as nm

program = nm.compile(source)
instance = nm.create_instance(scene=scene, program=program, name="Clouds")
nm.set_parameter(instance, key="noise#0.seed", value=7)
# Optional declared binding: nm.bind_input(instance, binding="...", image=source_image)

with nm.open_session(instance, width=1024, height=512) as session:
    request = nm.FrameRequest(frame=42, subframe=0.0, fps=24.0,
                              loop_seconds=10.0, mode="timeline")
    output = session.evaluate(request)
    image = session.publish_image(output, name="Clouds")
    node = nm.attach_material(instance, material=material, image=image)
```

`compile` returns a reusable immutable `Program` or structured diagnostics. `create_instance` creates persistent Blender-owned configuration. `set_parameter` and `bind_input` validate names/types and increment revisions. `open_session` acquires graphics-context-bound state; it cannot manufacture a missing GPU context. `evaluate` returns an `OutputHandle` containing texture, actual descriptor, generation and frame provenance. `publish_image` returns an actual Image pointer, preserving ownership markers and identity for existing links. `attach_material` returns a functional stock-node wrapper without rewriting unrelated nodes.

Other facade operations: `attach_compositor(instance, node_tree, image)`, `attach_world(instance, world, image)`, `attach_geometry_image(instance, node_tree, image)`, `session.resize(width, height)`, `session.reset()`, `session.recompile(program)`, `session.close()`, `prepare_render(scene, frames, policy)`, and `render_animation(scene, frame_start, frame_end, policy)`.

`OutputHandle` is borrowed until the next successful evaluation, resize, graph replacement or session close. A consumer requiring retention requests an explicit GPU copy in the same qualified context. Reject stale generations and cross-context use. Multiple outputs use named surface handles; exposing them must preserve source graph semantics.

`prepare_render` establishes current/cache-ready outputs and reports capability failures before rendering starts. `render_animation` provides a deterministic scripted per-frame evaluation/publication/render sequence where automatic native animation hooks are not yet qualified. It must not masquerade as proof that Blender's built-in animation render works; the latter has its own acceptance gate.

### 4.4 Scheduling and time

Use a small scheduler that publishes to the session's Image, plus editor draw adapters only where task 2 needs them. Property callbacks, dependency-graph notices and file/Text change detection mark dirty state. A registered timer requests redraw and debounces compilation; heavy GPU work occurs only in a context proven safe by task 0. Do not use Python worker threads for `bpy` or GPU operations. CPU-only work may be separated only with clear ownership and snapshot boundaries.

Treat source editing, scalar parameters, resource changes, scene time and input generations separately. Message-bus notifications supplement, rather than replace, frame/dependency evaluation. Detect Text changes with a bounded revision/hash check while live sessions exist, because per-keystroke RNA notification behavior needs qualification. File watching is optional for explicitly selected file sources and must not poll unrelated files.

A single requested generation is evaluated once per session even when several areas redraw. Presentation does not advance simulation time. A preview-only idle/hidden instance can sleep; an instance feeding visible materials or an active render remains demanded even with its preview panel closed.

For timeline mode define `fps_effective = fps / fps_base`, seconds from `(frame + subframe - origin_frame) / fps_effective`, and normalized time from loop duration and offset. Keep elapsed seconds, normalized loop time, simulation step and frame index separate. Preserve the legacy bake/harness stepping protocol, including its observed wrap behavior, in the legacy API; a new clock must not silently rewrite historical parity.

Define a second, preview-only `free_run` mode for the case where the timeline is stopped: the session advances on wall-clock time at the declared fps, so animated programs keep moving while the user edits. Free-run state never feeds a final render or a render cache; those always evaluate in timeline mode at the requested frame. Switching from free-run to timeline re-evaluates at the current scene frame (with replay for stateful programs). The panel shows which mode is active, so a free-running preview is not mistaken for what F12 will render.

Stateless programs evaluate directly at a requested time. Stateful programs advance at an explicit fixed step and replay from the start or a verified checkpoint after backward/nonsequential seeks. Checkpoint identity includes source, parameters, inputs, size, seed, time mapping and simulation policy. Bound checkpoint storage and expose replay progress/cancellation. Repeated evaluation of the same frame is idempotent. Preview may omit presentations to meet its budget, but must not silently omit simulation updates or call an unevaluated frame current. Final renders must wait for the exact requested state.

### 4.5 Output precision, color and coherence

Add a raw float readback separate from the existing quantized capture function. Live Images receive scene-linear float values without 8-bit conversion or [0,1] clipping. Keep the old PNG/parity capture path unchanged so its historical comparison contract remains intact. Verify negative values, HDR 2.0+, fine gradients, alpha ramps and asymmetric corner markers. Graph textures default to `rgba16f` ([graph_loader.py](../blender/noisemaker_blender/runtime/graph_loader.py), line 20), so a float32 Image carries half-float values: about 11 significant bits and a ±65504 range. Gradient and HDR fixtures must expect half-float precision, not float32.

Specify alpha mode and color role per output. Color output, numeric height/mask data and normal/vector data need explicit contracts; do not select Non-Color for everything simply because the old bake did. A numeric equality test and an AgX/display-transform test are distinct. GPU preview applies the scene's display transform once; data outputs remain untransformed until their consumer requests interpretation.

Publish to a stable, owned float Image using reusable buffers and explicit Image update/invalidation. Test whether Eevee, Cycles viewport/final render, compositor CPU/GPU modes and Geometry Nodes see the new generation. Prevent Image publication from recursively invalidating its own producer forever. GPU-only Image sharing, if it qualifies, is a separate optimization with per-consumer capability reporting and an explicit CPU-coherence step before save or consumers that require it.

The transfer cost is material: 1920×1080×4 float32 channels×60 FPS is approximately **1.99 GB/s in one direction**, before upload, copies or the scene renderer. This is byte arithmetic, not a measured bandwidth result. The Image bridge must be measured separately from GPU-only preview. No universal 1080p60 claim follows from a fast standalone texture draw.

### 4.6 Scene integration and dependencies

| Consumer/input | Proposed contract | Required proof |
|---|---|---|
| Image Editor / material preview (baseline) | Show the published float Image; Blender applies zoom, orientation and the display transform | Real editing and redraw show each new generation |
| Optional direct preview in the Image Editor, the Noisemaker node tree's Node Editor or the 3D Viewport | Draw handler shows the current GPU output with correct zoom/orientation/display transform | Adopted only if Image publication misses the preview gates; no per-frame CPU readback; host GPU state restored |
| Eevee/Cycles material | Managed Image Texture wrapper with stable image identity, Color/Alpha and UV handling | Render a textured object at two program generations; verify received pixels |
| World shader | Managed image source with explicit mapping/color role | World changes in viewport and final render; no stale texture cache |
| Compositor | Stock Image node/group input with correct frame/generation | CPU and GPU compositor output comparisons after updates and animation |
| Geometry Nodes | Stock Image Texture sampling for masks/heights/colors | Evaluated geometry attributes/displacement change correctly, including frame changes |
| External images/movies/sequences | Host adapter resolves frame/alpha/color, supplies named per-step texture inputs | Moving asymmetric input, repeated media instances and change detection |
| Text and mesh inputs | Host-derived text raster and evaluated mesh/UV/normal data | Correct rendered input; compiler acceptance alone insufficient |
| Audio/MIDI automation | Accept deterministic host snapshots through the existing evaluation seam | Existing automation tests plus native-rendered parameter changes; device UI is separate scope |

Do not accept arbitrary material/compositor/Geometry Nodes sockets as if they were Python-accessible pixel buffers. Initial graph inputs are explicit Image/texture providers and supported host data adapters. For scene render passes/AOVs as inputs, define a staged dependency graph: producer scene/pass → Noisemaker → downstream consumer. A scene consuming its own current render as a texture creates a cycle and must be rejected or explicitly use previous-frame feedback. Prove acyclic staged capture and final-render consumption before advertising render-pass integration. An overlay over a scene is not compositing within its render pipeline.

### 4.7 Final renders, persistence and headless use

Register lifecycle and render integration once, with reentrancy guards and explicit owner identities. Clean up timers, draw callbacks, subscriptions, sinks and GPU resources on disable, area/window removal, file load and undo/redo. GPU state restoration must survive shader/allocation errors.

Task 0 must establish when an output can be prepared before each engine snapshots its inputs, with a valid graphics context and without handler/thread races. Do not presume that `render_pre` or `frame_change_post` alone is sufficient. The automatic F12/animation path is incomplete until actual frame-stamped scene output proves ordering, including cancellation and render restart.

For remote/background rendering, support an explicit preparation/cache workflow: evaluate required frames on a qualified GPU host, save float image sequences and a provenance manifest, then consume the correct frame with Blender's normal image-sequence facilities. Cache identity includes source/inputs/parameters/time/resolution/color/simulation policy; reject missing/stale frames before render. This permits deterministic unattended consumption but is not fresh headless Noisemaker evaluation. Qualify fresh background GPU evaluation separately per OS/backend; do not repeat the old claim that Linux alone guarantees it.

Save persistent configuration and asset references in `.blend`. Pack or reference binary output snapshots when requested; do not serialize GPU handles or encode images as text. Reopening must reconstruct sessions and report absent external assets precisely. Library-linked/overridden data requires explicit writable ownership rather than mutations to linked assets.

## 5. Remediation work packages

All source paths and commands introduced below are proposed. Existing source paths refer to the audit revision. Implement one acceptance boundary at a time; preserve compiler and rendered regression coverage. The new session API is additive, with the old bake operator delegated to it only after compatibility tests pass.

### Task 0. Qualify Blender execution and consumer boundaries

**Create:** `blender/harness/probe_live_integration.py` and `blender/harness/probe_consumer_coherence.py`.

- [ ] Render an asymmetric float/HDR test texture in a real Blender 5.1.2 GUI context, redraw it in Image/Node/3D regions, and log thread/context and resource lifetime.
- [ ] Publish float pixels to an Image; update it twice and render actual Eevee and Cycles consumers, compositor CPU/GPU outputs, world and evaluated Geometry Nodes samples.
- [ ] Independently probe GPU writes to `gpu.texture.from_image` through a framebuffer; test every consumer, CPU pixels, reload, resize, save/reopen and backend change. An isolated passing viewport is not universal coherence.
- [ ] Trace F12 and built-in animation callback order, input snapshot timing, cancellation and valid GPU contexts, with Lock Interface enabled and disabled. Include frame/subframe markers. Do not perform unsafe concurrent writes to obtain a pass.
- [ ] Measure synchronous float publication, consumer refresh and direct preview at 512², 1024² and 1920×1080. Record exact Blender build, GPU/backend, source and settings. Publication at 512² decides whether task 2 needs a direct-draw adapter.

**Exit:** select supported publication and render-barrier mechanisms with evidence. If public APIs cannot meet exact automatic render or performance requirements, identify the smallest native integration required and its maintenance cost; do not relabel an explicit bake workaround as complete.

Run the probes in a real GPU-backed Blender 5.1.2 GUI session, never under `--background`, on a host that nothing else is rendering on at the time. Scripts write evidence outside the checkout. A host without a GPU session is a reason to move the probe, not evidence that the API fails.

### Task 1. Extract persistent sessions and rectangular rendering

**Create:** `blender/noisemaker_blender/api.py`, `runtime/session.py`, `runtime/output.py`, `parity/test_render_session.py`, `parity/test_rectangular_runtime.py`.

**Modify:** `runtime/pipeline.py`, `runtime/graph_loader.py`, `backend/gpu_backend.py`; preserve current functional bake API.

**Contract:** `Program`, `RenderSession`, `FrameRequest` and `OutputHandle` from section 4; explicit float/quantized output methods and descriptor metadata.

- [ ] Test repeated frames without repeated setup, two independent sessions, multiple outputs, stale handles, scalar updates, topology changes and transactional failure.
- [ ] Parameterize width/height through every root resolution, dimension and viewport use; keep `size=N` equivalent to `width=N,height=N`.
- [ ] Add raw float output while retaining the old 8-bit capture path and actual texture/sink metadata.
- [ ] Validate pass types, draw modes and inputs explicitly; reject unsupported execution rather than silently returning or drawing fullscreen geometry.
- [ ] Run focused engine-free tests and native square-versus-legacy/257×129 rendering comparisons.

**Exit:** a script retains GPU state across evaluations, resizes safely and gets correct output descriptors. Existing square bakes and parity captures are unchanged.

### Task 2. Add editor live preview and correct GPU lifetimes

**Create:** `integration/scheduler.py`, `integration/images.py`, `integration/lifecycle.py`, `ops/live.py`, `parity/test_live_scheduler.py`, `parity/test_image_publication.py`, `blender/harness/test_live_preview.py` under the add-on/harness trees as appropriate. Add `integration/preview.py` only if the direct-draw bullet below applies.

**Modify:** `__init__.py`, `ui/panels.py`, `nodes/tree.py`, `props.py`, backend state guards.

- [ ] Add explicit Live/Pause/Reset state, source/parameter dirty tracking, debounced compilation and last-good-output diagnostics.
- [ ] Publish each new generation to one owned float Image through the task 0 mechanism: stable Image pointer, reusable buffers, explicit update/invalidation, ownership markers that protect unrelated user Images. The Image Editor and material preview show it with no custom draw code. Deduplicate evaluation across multiple consumers and repeated redraws.
- [ ] Only if task 0 measured Image publication missing the preview gates at 512²: draw the session's GPU output directly in the editor regions task 0 qualified, and save/restore host GPU state on success and failure.
- [ ] Make backend passes restore prior GPU state on success and failure, and make backend `free()` clear its binding and cache dictionaries (RT-13).
- [ ] Handle area changes, window closure, file loading, undo/redo, add-on disable and repeated enable without leaked timers, callbacks or stale textures.
- [ ] Qualify removal/replacement of the bake-only periodic readback flush for the live event loop. Preserve it in legacy bake mode until equivalent stability is proved.
- [ ] Exercise real DSL typing, a parameter drag, invalid edits/recovery, playback and cancellation. Instrument readbacks and shader compilations rather than inferring their absence.

**Exit:** visible feedback without Bake in the Image Editor and material preview, meeting the section 6.1 preview gates at 512² with bounded scheduling, or a precisely documented unresolved blocker. A direct preview, if built, has zero steady-state CPU readbacks. Modal baking continues to work.

### Task 3. Implement scene time, animation and parameter bindings

**Create:** `runtime/clock.py`, `runtime/checkpoints.py`, `integration/parameters.py`, `parity/test_scene_clock.py`, `parity/test_parameter_bindings.py`, `blender/harness/test_timeline.py`.

**Modify:** scene/node property definitions and session invalidation.

- [ ] Generate typed controls from effect metadata as keyed custom properties (section 4.2), with enum/default/range behavior, keyframes and drivers.
- [ ] Test that inserting, removing and reordering DSL steps rebinds parameters by key, keeps their keyframes and drivers, and lists unmatched bindings as orphaned instead of dropping or reassigning them.
- [ ] Resolve evaluated keyframes and drivers from the intended dependency graph; do not read only original datablock values or rely solely on message-bus notifications.
- [ ] Implement section 4.4 time conversion, fixed simulation stepping, bounded checkpoints/replay and explicit invalidation on input/parameter changes.
- [ ] Compare sequential frames with seeks in order `1, 20, 5, 20`, repeated frames, fractional FPS and subframes; verify deterministic state and no extra advance on editor redraw.
- [ ] Implement the free-run preview mode from section 4.4; verify that it never reaches a final render or cache and that switching to timeline mode re-evaluates at the scene frame.
- [ ] Test parameter changes that alter defines or resource dimensions separately from scalar uniforms.

**Exit:** timeline/playback and programmatic evaluation agree for stateless and stateful fixtures, with observable replay status and no hidden simulation skips.

### Task 4. Deliver coherent float Images and functional Blender consumers

**Create:** `integration/materials.py`, `integration/compositor.py`, `integration/geometry.py`, `blender/harness/test_consumer_rendering.py`.

**Modify:** `integration/images.py`, `nodes/tree.py`, `ops/bake.py` through compatibility adapters; keep existing ownership and cancellation tests.

- [ ] Extend task 2's Image publication with explicit alpha/color roles per output and generation metadata; preserve unrelated user Images.
- [ ] Implement idempotent stock-node wrappers for materials/world, compositor and Geometry Nodes image sampling. Replace cosmetic output behavior with a real resource reference and evaluated consumer path.
- [ ] Render/check two generations in actual consumers, including HDR, alpha, odd dimensions, two independent instances and shared instances.
- [ ] Validate consumer invalidation and suppress producer/publication feedback loops. Test AgX/display changes separately from numeric output parity.
- [ ] Add any GPU-sharing optimization only for the consumer/backend combinations task 0 proves; retain the float publication path for coherent save/export and other engines.

**Exit:** current pixels reach each claimed consumer; wiring-only assertions cannot pass this gate. Report end-to-end consumer refresh performance separately from direct preview.

### Task 5. Implement host inputs and supported dependency graphs

**Create:** `runtime/inputs.py`, `integration/inputs.py`, `parity/test_input_bindings.py`, `blender/harness/test_host_inputs.py`.

**Modify:** graph metadata exposure, backend input binding, session input revisions and existing automation integration.

- [ ] Bind Image/texture inputs by declared per-step names; handle alpha/color/orientation, repeated media steps and frame-specific movie/sequence data.
- [ ] Implement text and evaluated mesh input adapters where upstream declares them, with frame/rendered evidence and input ownership rules.
- [ ] Expose host audio/MIDI snapshots through the existing runtime seam; qualify supported effect inputs separately from value-evaluator tests. No new capture UI is required.
- [ ] Topologically evaluate dependent program instances. Reject circular current-frame dependencies; explicit prior-frame feedback has a separate contract.
- [ ] Qualify staged scene/render-pass inputs only after acyclic capture/output ordering is implemented. Do not expose arbitrary socket-to-texture links without an evaluator.

**Exit:** rendered input changes propagate to the intended instances/consumers, and dependency cycles fail with actionable diagnostics.

### Task 6. Integrate final rendering, animation and persistence

**Create:** `integration/render.py`, `integration/persistence.py`, `runtime/frame_cache.py`, `blender/harness/test_final_render.py`, `blender/harness/test_save_reopen_live.py`, `parity/test_frame_cache.py`.

**Modify:** add-on lifecycle and host workflow harness.

- [ ] Implement the task-0-proven render barrier for F12 and native animation; suspend preview mutation while final consumers snapshot/use data.
- [ ] Provide context-independent `prepare_render` and scripted `render_animation`; preserve separate status for native animation versus the scripted path.
- [ ] Render frames with embedded generation/frame markers in Eevee and Cycles, including animation, nonsequential frame requests, cancellation/restart and subframe policy. Run Cycles animation renders with Persistent Data (`render.use_persistent_data`) enabled and disabled, since retained render data is a likely source of stale textures between frames.
- [ ] Implement provenance-checked binary float cache consumption for background jobs. Test absent/stale cache failure before output and separate it from fresh GPU evaluation.
- [ ] Save/reopen with configuration, linked inputs and optional packed output; reconstruct sessions without serialized GPU handles. Test duplication, undo/redo, linked libraries and add-on removal.

**Exit:** final output corresponds to exact requested state and survives project lifecycle. Motion-blur/subframe evaluation that requires multiple procedural states must be proved or explicitly remain unqualified; one Image per integer frame is not that proof.

### Task 7. Meet performance, parity and distribution gates

**Modify:** shader/resource caching as measurements justify, native harness and package validation, then README/architecture/platform notes to describe tested behavior. Keep historical compatibility/gap records intact.

- [ ] Move shader text/descriptor reads out of the steady-state cache-hit path. Reuse frame uniform storage where safe; instrument texture/pipeline/UBO allocations and lifetimes.
- [ ] Profile representative static, multipass and stateful fixtures. Track generation-to-presentation latency, CPU scheduling, GPU work, transfers, consumer refresh, memory, dropped presentations and simulation lag.
- [ ] Run current full compiler/catalog/rendered parity without shrinking denominators or replacing oracle output with candidate output. Keep historical CHAOS/NEAR results distinct from strict acceptance.
- [ ] Run lifecycle stress, actual host interactions, clean package install, script-only usage and saved-file round trips on every claimed Blender/OS/backend combination.
- [ ] Add native GPU verification of the new harness groups once the implementation qualifies. Keep the per-push workflow short and on GitHub-hosted runners, as `tests.yml` requires for this public repository; run long native, catalog and performance suites on a schedule or on demand, not on every push. GitHub CPU/background-only checks remain useful but cannot replace native GPU runs.

**Exit:** measured acceptance in section 6, current source-bound evidence, accurate product documentation and a reproducible package.

## 6. Acceptance definitions and measurements

### 6.1 Realtime acceptance proposal

Use the following as initial engineering targets to validate during task 0, not as measured performance claims. Record exact host, backend, build and workload before adopting a baseline.

| Measurement | Proposed gate |
|---|---|
| Scalar edit to visible feedback | p95 ≤ 100 ms at 512×512 for a declared simple/multipass fixture set after warm-up |
| Continuous preview | sustained ≥ 30 completed presentations/s for 60 s at 512×512 on that fixture set, measured through Image publication (and through direct preview if built); target 60 where measured |
| Live material/compositor feedback | separate ≥ 30 updates/s target at 512×512 with a simple consumer scene; if transfer/cache costs fail it, this outcome remains incomplete |
| UI responsiveness | input and cancellation remain serviced; no unbounded bake/compile/replay loop in a UI callback |
| Live source errors | last valid frame remains, diagnostics identify source stage/location, correction resumes without re-enable |
| Stable session resources | no shader-file reads or recompilation on unchanged warm frames; no unbounded texture/callback/buffer growth over a ten-minute run |
| Presentation correctness | no extra simulation steps from additional windows/editors; no stale-generation final frames |

Measure the flagship/stateful workload separately at 512², 1024² and 1080p. Report attainable rates and bottlenecks; a tiny solid shader cannot establish realtime support for the full catalog. Lower preview resolution or a limited publication cadence must be visible settings/status, never a hidden quality reduction or a substitute for exact final rendering.

### 6.2 Correctness and integration gates

- Old bake outputs and compiler stages retain their existing contracts; new rectangular/HDR behavior has independent fixtures.
- GPU-only preview, published float pixels, rendered consumer pixels and final render/cache outputs identify source, inputs, parameters and requested frame independently.
- A material test renders a textured object; a compositor test compares final composite pixels; a Geometry Nodes test inspects evaluated geometry; a world test renders its environment.
- Compare final color-managed images under identical Blender settings separately from raw linear Noisemaker parity. Validate alpha edges and orientation with asymmetric inputs.
- Full relevant parity reports preserve expected/executed/pass/mismatch/error/timeout/unsupported/missing totals. Unknown cases and unsupported hosts remain visible.
- Exact-source native checks, unit checks, package checks, interaction evidence and performance reports are separate claims. CPU tests or llvmpipe renders do not establish hardware-GPU realtime performance.

### 6.3 Proposed verification entry points

Existing engine-free discovery remains as executed in section 2. New native harnesses should run in isolated preferences on a GPU-capable host with `--factory-startup --python-exit-code 1 --python <harness>` and a real supported graphics session. A test must terminate on its own, fail on missing assertions/output, record capabilities and avoid modifying user scenes/preferences.

The planned native suite should cover session/rectangular output, preview, timeline, consumers, inputs, final render, persistence and performance. Run focused groups during implementation, then the complete suite once integrated. At plan creation these harnesses did not exist; section 9 identifies the implemented entry points and the gates they actually exercised.

## 7. Priorities and decision gates

Start with **task 0 plus the session/HDR core in task 1**. The highest-risk unknown is coherent delivery and final-render timing in Blender's actual engines; resolving it early prevents building a preview UI around a false integration assumption.

Then deliver **the live loop through Image publication and timeline behavior (tasks 2–3)**, followed by **actual material/compositor/geometry consumption (task 4)**. Because the live loop publishes the same Image that consumers read, task 4 builds on task 2's output path instead of adding a second one. A direct-draw preview is built only if task 0 shows publication cannot meet the preview gates. These form the first useful interactive milestone, but that milestone is not the full requested outcome. Complete host inputs, deterministic final renders and saved-project lifecycle (tasks 5–6), then qualify performance and distribution (task 7).

A separate RenderEngine, unverified GPU mutation of Image storage, permanent rebaking, or screenshot-only preview must not substitute for the requested Blender integration. If public APIs fail the defined realtime/automatic-render gates, the next decision is a narrowly specified native bridge or Blender-source integration with measured benefit and explicit version support. It is not permission to weaken the goal or advertise an unqualified path.

## 8. Limitations of this investigation

This review establishes the current bake-oriented integration and specific code-level gaps. It does not prove the public Image bridge can sustain the proposed rates, that shared-GPU Image writes are coherent, that native animation callbacks can safely prepare every frame, or that fresh background GPU execution works on a target host. Those are the first native proving tasks.

The current implementation has more capability than the README's description of an entirely blocking bake, but less Blender integration than the broad “textures, materials, animated backgrounds” wording suggests. The remediation should preserve the functioning GPU/compiler core while making editor, scene and programmatic behavior explicit and testable.


## 9. Implementation status

Implementation started from plan commit `86f3c2ef95b4ea63d256dadef4f5d5c6efcf0aea` on
2026-10-07. This is an implementation checkpoint, not qualification of the full requested outcome.
The original task checklists remain open where their combined acceptance criteria are incomplete.
Independent review identified and corrected failed-property-write rollback, GPU session retention
on Live disable, and stale prepared Geometry Nodes evaluation. The reviewed implementation is
`54a9ed7`, integrated on upstream `59e9e84`, with add-on version 0.1.15. Earlier hashes below
identify retained pre-integration evidence snapshots; they are not final-source qualification.
A later upstream reference-only update, `b36d4d0`, was integrated as `ee91144`. Product,
native harness and test code remained byte-identical; the reference revision became
`15c9114e864fcc8cd2557669f2ac6d36f0ea080f`.

### 9.1 Implemented paths

- `api.py` and `runtime/session.py`: immutable programs, persistent GPU sessions, rectangular
  dimensions, raw float output, borrowed handle invalidation, transactional source replacement,
  typed scalar/define/resource updates and bounded stateful replay. Legacy square bake and
  quantized parity capture retain their separate contracts.
- `integration/lifecycle.py`, `scheduler.py`, `parameters.py` and the Live panels: timer-driven
  source/parameter updates, last-good output on invalid source, pause/reset, evaluated scene
  parameters, stable keyed bindings and explicit timeline/free-run modes. GPU work does not run
  in render/frame handlers.
- `integration/images.py` and consumer helpers: coherent float Images, explicit color/alpha roles,
  stable ownership, material/world/compositor/Geometry Nodes stock Image nodes and preserved
  unrelated links. Direct writes to Image-associated GPU textures were rejected as a universal
  delivery mechanism because downstream consumers do not agree.
- `runtime/inputs.py` and `integration/inputs.py`: declared Image, text and evaluated mesh inputs,
  premultiplied media handling, exact-frame audio/MIDI snapshots and content-based CPU identities.
  Movie/sequence inputs require an explicit exact-frame provider.
- `integration/render.py`, `sequences.py` and `runtime/frame_cache.py`: explicit GPU preparation,
  scripted scene animation, hashed binary float caches and CPU-only prepared scene rendering.
  Cycles Persistent Data temporarily uses verified numeric EXR sequences; original Image nodes
  and settings are restored after the render scope.
- `integration/persistence.py`: persistent instance configuration, Image input references, stable
  identities and optional save-time packing of the latest output. Output references store an Image UUID
  and resolve it against the instance owner; consumer nodes retain their ordinary Image links.
  Legacy local output pointer properties migrate on load/undo/redo, before timer-driven evaluation,
  and before save-time packing. GPU resources are reconstructed.

### 9.2 Native observations and verification

The native host is the spare office Mac, Apple M4, Blender 5.1.2, Metal. Tests use disposable
`--factory-startup` GUI processes under the host's shared resource lock; only prepared cache
consumption uses `--background`. New GUI harnesses require `NM_HARNESS_AUTOCLOSE=1` before
changing the disposable scene and closing their process. Evidence directories are named
`task0-20261007*` beneath the configured native evidence root and are mirrored outside the checkout.

| Gate | Result and scope |
|---|---|
| Current reference compiler gate | At `ee91144`, `scripts/test` passed all 371 unit tests, 16 PNG decoder tests, lexer/parser/compile parity 23/23 each, and expander/graph parity 22/22 each against reference `15c9114e864fcc8cd2557669f2ac6d36f0ea080f`. The rebuilt export kit retained identical hashes and byte counts for all 632 inventoried files, including the previously tested ZIP. |
| Reviewed engine-free and packaging gates | At `54a9ed7`, `scripts/test` passed 371 unit tests, 16 PNG decoder tests, lexer/parser/compile parity 23/23 each, and expander/graph parity 22/22 each against reference `8e5835932a7297d360b943200b42953224eea0a4`. The full export-kit release test command passed 97 tests with zero failures or skips, including the Blender contracts. The real builder packaged 891 tracked add-on files; ZIP SHA-256 is `414e9fba8a86022c7f34f2711baef8ccf190575f7b6bffd238fad66d520f7b24`. |
| Reviewed lifecycle transaction and package | The exact `54a9ed7` product bytes, unchanged at `ee91144`, passed native Pause/session retention, Live-disable GPU cleanup, fresh-session resume and keyed override restoration. An injected second IDProperty write failure after the first value/UI mutation restored the prior graph, source, session, Image, values and UI metadata; valid source recovery and separate background save/reopen then passed. The initial reopen fixture incorrectly compared pre-recovery metadata; the retained fixture correction captures the successful recompile metadata before save and adds a recovered-source hash check, without changing failure-time rollback assertions. Evidence is in `task0-20261007-54a9-lifecycle-transaction-corrected`. The exact ZIP above also installed, enabled, registered Scene properties and disabled successfully with isolated Blender scripts/configuration (`task0-20261007-54a9-package`). |
| Reviewed native integration | Exact `54a9ed7` passed the tracked live-preview harness, three-process create → undo/redo → save/reopen sequence, six Eevee/Cycles scripted frame markers with Persistent Data off/on, and read-only prepared background frames 2→1. The new `test_prepared_geometry.py` passed four Cycles Persistent Data renders in reverse and forward order with unchanged Image socket identity and zero measured vertex-offset error. The same strict harness failed before the consumer-tree invalidation fix because evaluated geometry stayed stale despite correct Image pixels. Evidence is in `task0-20261007-54a9-{gn,live,persistence,render}`; source archive SHA-256 is `7dc6fdd9218395c9b8ee6ee3a854ac635e4f7b3ee3cccef0e5a854f13c4aeed5`. |
| Persistent session | `test_render_session_native.py`: legacy square output comparison, 257×129 output, HDR/negative/premultiplied alpha publication, repeated-frame/handle checks and stateful sequential/jump/backward replay passed. |
| Host inputs | `test_host_inputs.py`: asymmetric Image orientation/update, text change, evaluated mesh deformation, compiled `media()` with a 3×2 premultiplied source and audio-driven alpha change passed. |
| Float consumer probe | `probe_consumer_coherence.py`: 11 assertions passed, including the analytic RGB delta `[.75, -1.75, 1.375]` in six Eevee/Cycles material/world and CPU/GPU compositor renders, both evaluated Geometry Nodes vertices, and managed node/link identity. Tolerance was .03; compositor alpha remained .60635. |
| Scripted final rendering | `test_final_render.py` at `d2dc7ab`: six frame markers passed, covering Eevee, Cycles Persistent Data off, and Cycles Persistent Data on; temporary sequence nodes restored the original generated Image. |
| Prepared background rendering | `test_frame_cache_background.py` at `d2dc7ab`: reopened the saved scene, forbade GPU session creation, rendered Cycles Persistent Data frames 2 then 1, checked their pixels and rejected changed source before renderer entry. The cache directory and files were read-only; the inventory and SHA-256 hashes stayed unchanged, and original modes were restored. |
| Saved outputs/inputs | At `d2dc7ab`, three independent tracked create → undo/redo → save/reopen sequences passed. Each forced copied-Scene output publication between undo and redo, checked 16×8/64×8 pixels and fresh sessions, drew the Live panel, and verified scalar Image UUID references without a saved output pointer. No ID-user warning or crash occurred. Old `a2d0257` files also migrated and reopened correctly, including an immediate save before the first live timer. Earlier `a2d0257` and intermediate candidates crashed in nested Image-pointer conversion or reported Image user undercounts; those failures are retained. A timer-paused stress probe passed after the reference-storage change. This is measured lifecycle coverage, not a proof for every undo history. |
| Live interaction before pacing correction | `test_live_interactive.py`: actual Text Editor source edits, static/multipass scalar changes, invalid-source recovery and pause/resume passed. Publication p95 was 47.3/61.8 ms; this does not measure edit-to-display latency. The shorter free-run segment averaged 25.79 displayed generations/s, below the 30 FPS target. |
| Continuous multipass preview | `probe_live_integration.py` (`NM_PROBE_PHASE=continuous`): 60.039 seconds of actual `noise().bloom()` GPU evaluation at 512² produced 24.87 publications/s and 24.85 displayed generations/s. This misses the proposed ≥30/s gate. Shader compiles/file reads stayed at 5/8, with one surface and four pooled textures. |
| Image transfer alone | A separate 60-second Image Editor probe displayed 46.8 generations/s at 512² with a 60 Hz requested timer. Float publication p95 was 0.386 ms and publication-to-draw p95 was 12.435 ms. It used precomputed pixels, not full graph evaluation. |
| Ten-minute multipass preview | The staged `task0-20261007-continuous-600` probe completed 600.018 s with 18,100 publications and presentations. Aggregate rate was 30.166/s, but the worst sliding 60-second window was 23.75/s, so sustained acceptance remains unmet. Shader compiles/file reads stayed at 5/8, surface/pool counts at 1/4, and process RSS rose and was reclaimed (653,216 KB start, 719,616 KB peak, 586,208 KB end). This establishes bounded resources for that measured snapshot, not whole-catalog realtime performance. |
| Native shader catalog | The `e750b80` runtime plus corrected declared-variant harness executed all 309 shader programs: 307 compiled programs, 317 compiled variants, two known unsupported audio programs (`scope`, `spectrum`) and zero unexpected failures. Unsupported programs remain in the denominator. |
| Engine-free and distribution checks | At `d2dc7ab`, `scripts/test` passed all 367 unit tests, all 16 PNG decoder tests and all compiler parity gates. The real export-kit builder packaged 891 tracked add-on files, and all 22 Blender export-kit contract tests passed. The final ZIP (SHA-256 `9e39e6be026ca18f5ed84a603a878c25f4e5595962f5b396af290f36274b40da`) installed, enabled, registered and disabled successfully in an isolated Blender 5.1.2 GUI process. |
| Frozen keyed replay | `test_timeline.py` at exact `05ee79c` captured evaluated keyframes, restored Scene time, and matched sequential frames 1–20 against seeks 1→20→5→20 at 30000/1001 FPS. Keyed history changed raw pixels versus constant history by .0561523. Native driver capture and current-instance animated final rendering remain unqualified. |
| Full rendered parity | The exact `e750b80` candidate and independently verified pinned reference `8fa067f6afec1f091272a8fae7b0b40d78f7b04d` completed all 116 cases: 1 exact, 49 strict, 8 near, 58 fail, zero missing/deferred/skipped. All candidate and reference pixels have hashes/provenance. The exact pre-change `c18336a` source, rendered against the same byte-identical goldens, produced identical grades and byte-identical candidate PNGs for all 116 cases. Thus historical output is preserved, while the existing numerical parity gate remains failed. |

### 9.3 Remaining acceptance boundaries

Automatic F12/native animation is not qualified. Fresh GPU evaluation from `frame_change_post`
crashed Blender's Metal context; real graph evaluation in `render_pre` crashed when native
animation reached its second frame, including with Lock Interface. Suspension prevents live timer
mutation during render but does not prepare fresh native frames. The Live panel warns about this
boundary. Scripted preparation and cache consumption do not close automatic-render acceptance.
A later exact-`d823bb1` probe prepared both frames once in `render_init`, but frame-2
`render_pre` preceded `frame_change_post` and rejected stale evaluated parameters. Blender
swallowed that handler exception, returned `FINISHED` and wrote the frame with stale pixels.
Deliberate preparation failure in `render_init` plus refusal in `render_pre` likewise produced
output files. Thus successful preparation alone does not establish an abort-on-failure barrier;
Python render handlers are not qualified for the automatic path. No such handler was installed.

Stateful Blender instances with keyed or driven parameters require historical parameter
snapshots. Without those snapshots the integration rejects the request rather than applying the
target frame's values to earlier simulation steps. Prepared-cache consumption of dependent live
instances is rejected until historical upstream snapshots can be validated without first mutating
Images; this also limits the Cycles Persistent Data scripted path. Fresh live/scripted
evaluation with Persistent Data off orders producers before consumers. Direct instance sessions synchronize evaluated
parameters at the current scene time; requests at a different scene time fail explicitly. Plain
Program sessions can supply deterministic per-step parameter/input providers. The explicit
`prepare_parameter_snapshots` API captures up to 256 evaluated fixed-step scalar samples and
restores Scene time. Its immutable result opens a frozen Program session; it does not claim
freshness after Scene edits or qualify current-instance final rendering. Animated defines,
resource sizes and render-pass conditions remain rejected.

The sustained multipass preview gate is measured but unmet. The ten-minute run gives bounded-resource
evidence for its measured snapshot. Live material/compositor refresh, flagship workloads at
512²/1024²/1080p, passing full rendered parity,
undo histories beyond the measured repetitions, duplicated-scene consumer remapping and other
operating systems/backends require separate evidence. Linked legacy output references cannot be
migrated and are rejected. Cross-window
GPU frees are deferred until the owning window returns; permanent window loss remains a resource
lifetime qualification limit. Multi-state motion blur remains rejected. These boundaries must not
be presented as completed plan tasks or supported platform claims.

### 9.4 Native render integration decision

The proposed next architecture is a Blender source bridge, retaining Eevee and Cycles. This is
a design direction requiring approval, not an implemented or qualified path. A supported Python
handler cannot supply the needed abort result: Blender prints handler exceptions and discards
successful return values. The still-frame `render_pre` callback also precedes render dependency
graph initialization. [Handler dispatch](https://github.com/blender/blender/blob/v5.1.2/source/blender/python/intern/bpy_app_handlers.cc#L435-L455),
[still-frame ordering](https://github.com/blender/blender/blob/v5.1.2/source/blender/render/intern/pipeline.cc#L1813-L1828).

The proposed gate sits in the engine-rendered view-layer path after `engine_depsgraph_init` and
before the engine's `update`/`render` calls. It receives the actual render dependency graph,
evaluated Scene, ViewLayer, frame/subframe and required Image generation; a viewport graph from
`bpy.context` cannot substitute. This location and API shape are an engineering proposal inferred
from the source, not a supported extension point. [Engine synchronization](https://github.com/blender/blender/blob/v5.1.2/source/blender/render/intern/engine.cc#L810-L875).

Its result must distinguish ready, cancelled and failed. Non-ready results must release locks,
prevent engine synchronization and file writes, preserve cancellation cleanup, and propagate an
error through both synchronous and asynchronous jobs. GPU preparation requires a proven owning-
context handoff; the render worker must not call the current Python GPU session directly.
Persistent Data must consume the exact newly published generation. Those are acceptance
requirements, not assumptions about a native implementation.

A maintained source build would need version/platform qualification, starting with the existing
Blender 5.1.2/Apple Metal test target. An upstream API addition is the alternative to maintaining
that patch. Neither route is implemented by this add-on checkpoint, and neither by itself fixes
the measured preview-rate shortfall. The public-API implementation must not be presented as the
full requested realtime/automatic-render outcome.

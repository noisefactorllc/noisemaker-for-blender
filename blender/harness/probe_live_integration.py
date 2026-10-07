"""Task 0 native GUI probe: float publication, redraw cost and render callbacks.

Run with Blender 5.1.2 in a real GUI session, not --background. Set
NM_EVIDENCE_DIR to an absolute directory outside the checkout. The probe exits
on its own and records measurements and callback order as JSON. It never writes
an Image from a render/frame handler in the main phase. The marker phase tests
CPU-only publication under Lock Interface and records an unlocked refusal;
GPU evaluation from a handler is isolated because it may crash Blender.
"""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
import traceback

import bpy
import gpu
import numpy as np

if "--factory-startup" not in sys.argv or os.environ.get("NM_HARNESS_AUTOCLOSE") != "1":
    raise RuntimeError("Task 0 probe requires a disposable --factory-startup Blender process with NM_HARNESS_AUTOCLOSE=1")

EVIDENCE = Path(os.environ["NM_EVIDENCE_DIR"]).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)
PHASE = os.environ.get("NM_PROBE_PHASE", "main")
RESULT = {"probe": "live_integration", "phase": PHASE, "events": [], "measurements": [], "renders": [], "errors": []}
START = time.perf_counter()
MAIN_THREAD = threading.get_ident()
HANDLERS = []


def stamp(kind, **fields):
    row = {"at_ms": round((time.perf_counter() - START) * 1000, 3),
           "kind": kind, "thread": threading.get_ident(), **fields}
    RESULT["events"].append(row)
    print("NM_PROBE", json.dumps(row, default=str), flush=True)


def save():
    name = {"marker": "live_marker.json", "presentation": "image_editor_presentation.json",
            "continuous": "continuous_%s.json" % os.environ.get("NM_CONTINUOUS_SECONDS", "60")}.get(PHASE, "live_integration.json")
    (EVIDENCE / name).write_text(json.dumps(RESULT, indent=2, default=str) + "\n")


def context_info():
    try:
        fb = gpu.state.active_framebuffer_get()
        return {"valid": fb is not None, "type": type(fb).__name__}
    except Exception as exc:
        return {"valid": False, "error": repr(exc)}


def callback(kind):
    def handler(*args):
        scene = next((a for a in args if isinstance(a, bpy.types.Scene)), bpy.context.scene)
        stamp(kind, frame=scene.frame_current if scene else None,
              subframe=scene.frame_subframe if scene else None,
              lock_interface=scene.render.use_lock_interface if scene else None,
              gpu_context="unqueried in render/frame handler: unsafe on Blender 5.1.2")
    return handler


def install_callbacks():
    for kind in ("frame_change_pre", "frame_change_post", "render_init",
                 "render_pre", "render_post", "render_write", "render_complete",
                 "render_cancel"):
        collection = getattr(bpy.app.handlers, kind)
        fn = callback(kind)
        collection.append(fn)
        HANDLERS.append((collection, fn))


def remove_callbacks():
    for collection, fn in HANDLERS:
        if fn in collection:
            collection.remove(fn)


def build_image(width, height):
    # Bottom row, top row and left/right all differ; retain negative and HDR RGB.
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[:, :, 0] = -0.25 + x
    rgba[:, :, 1] = 0.125 + 2.0 * y
    rgba[:, :, 2] = 0.25 + x * y
    rgba[:, :, 3] = 0.2 + 0.8 * x
    img = bpy.data.images.new("NM_task0_%dx%d" % (width, height), width=width,
                              height=height, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    return img, rgba.reshape(-1)


def publish(img, pixels, count=5):
    rows = []
    for iteration in range(count):
        t0 = time.perf_counter()
        img.pixels.foreach_set(pixels)
        t1 = time.perf_counter()
        img.update()
        t2 = time.perf_counter()
        areas = []
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type in {"IMAGE_EDITOR", "NODE_EDITOR", "VIEW_3D"}:
                    area.tag_redraw()
                    areas.append(area.type)
        t3 = time.perf_counter()
        rows.append({"iteration": iteration, "foreach_set_ms": (t1-t0)*1000,
                     "image_update_ms": (t2-t1)*1000,
                     "redraw_request_ms": (t3-t2)*1000,
                     "total_ms": (t3-t0)*1000, "areas": areas})
    return rows


def direct_gpu(width, height):
    from gpu.types import GPUOffScreen
    t0 = time.perf_counter()
    off = GPUOffScreen(width, height, format="RGBA16F")
    t1 = time.perf_counter()
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(-0.25, 2.0, 0.5, 0.75))
        buf = fb.read_color(0, 0, 1, 1, 4, 0, "FLOAT")
        buf.dimensions = 4
        sample = tuple(float(v) for v in np.array(buf, dtype=np.float32))
    t2 = time.perf_counter()
    off.free()
    return {"allocate_ms": (t1-t0)*1000, "clear_read_1px_ms": (t2-t1)*1000,
            "sample": sample}


def scene_for_render(img):
    scene = bpy.context.scene
    for existing in list(scene.objects):
        bpy.data.objects.remove(existing, do_unlink=True)
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else "BLENDER_EEVEE"
    scene.render.resolution_x = 32
    scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(EVIDENCE / "animation_")
    scene.render.film_transparent = True
    scene.camera = bpy.data.objects.new("NM_probe_camera", bpy.data.cameras.new("NM_probe_camera"))
    scene.collection.objects.link(scene.camera)
    scene.camera.location = (0, 0, 3)
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 2
    mesh = bpy.data.meshes.new("NM_probe_mesh")
    mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)], [], [(0,1,2,3)])
    uv = mesh.uv_layers.new()
    for loop, coord in zip(mesh.polygons[0].loop_indices, ((0,0), (1,0), (1,1), (0,1))):
        uv.data[loop].uv = coord
    obj = bpy.data.objects.new("NM_probe_plane", mesh)
    scene.collection.objects.link(obj)
    mat = bpy.data.materials.new("NM_probe_mat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    emission = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    mat.node_tree.links.new(tex.outputs["Color"], emission.inputs["Color"])
    mat.node_tree.links.new(emission.outputs[0], out.inputs["Surface"])
    obj.data.materials.append(mat)
    return scene


def render_probe(scene, *, lock_interface, animation):
    scene.render.use_lock_interface = lock_interface
    scene.frame_start, scene.frame_end = 1, 2
    stamp("render_call_begin", animation=animation, lock_interface=lock_interface,
          gpu_context=context_info())
    t0 = time.perf_counter()
    try:
        result = bpy.ops.render.render("EXEC_DEFAULT", animation=animation,
                                       write_still=False)
        record = {"lock_interface": lock_interface, "animation": animation,
                  "operator": sorted(result), "elapsed_s": time.perf_counter()-t0}
    except Exception as exc:
        record = {"lock_interface": lock_interface, "animation": animation,
                  "error": repr(exc), "elapsed_s": time.perf_counter()-t0}
    RESULT["renders"].append(record)
    stamp("render_call_end", **record)


def run():
    try:
        if bpy.app.background or not bpy.context.window_manager.windows:
            raise RuntimeError("requires real Blender GUI, not background mode")
        RESULT["blender"] = {"version": bpy.app.version_string,
                             "build_hash": str(bpy.app.build_hash),
                             "build_branch": str(bpy.app.build_branch),
                             "background": bpy.app.background}
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "vendor": gpu.platform.vendor_get(),
                         "renderer": gpu.platform.renderer_get(),
                         "version": gpu.platform.version_get()}
        RESULT["main_thread"] = MAIN_THREAD
        stamp("probe_start", gpu_context=context_info())
        install_callbacks()
        for width, height in ((512, 512), (1024, 1024), (1920, 1080)):
            img, pixels = build_image(width, height)
            rows = publish(img, pixels)
            read = np.empty(4, dtype=np.float32)
            img.pixels.foreach_get(read) if len(img.pixels) == 4 else None
            measurement = {"size": [width, height], "publication": rows,
                           "direct_gpu": direct_gpu(width, height),
                           "image_float": img.is_float,
                           "image_colorspace": img.colorspace_settings.name}
            RESULT["measurements"].append(measurement)
            stamp("publication_done", size=[width, height], last_ms=rows[-1]["total_ms"])
            if (width, height) != (512, 512):
                bpy.data.images.remove(img)
            else:
                first = img
        scene = scene_for_render(first)
        for frame, subframe in ((2, 0.0), (1, 0.5), (3, 0.0), (1, 0.0)):
            scene.frame_set(frame, subframe=subframe)
            stamp("frame_set_return", frame=scene.frame_current,
                  subframe=scene.frame_subframe, gpu_context=context_info())
        for lock in (True, False):
            render_probe(scene, lock_interface=lock, animation=False)
            render_probe(scene, lock_interface=lock, animation=True)
        RESULT["status"] = "completed"
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error": repr(exc), "traceback": traceback.format_exc()})
    finally:
        remove_callbacks()
        save()
        print("NM_PROBE_RESULT", RESULT["status"], EVIDENCE / "live_integration.json", flush=True)
        bpy.ops.wm.quit_blender()
    return None



def marker_sample(image):
    width, height = image.size
    flat = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(flat)
    return flat.reshape(height, width, 4)[height // 2, width // 2].tolist()


def run_marker():
    marker_handler = None
    session = None
    try:
        if bpy.app.background or not bpy.context.window_manager.windows:
            raise RuntimeError("requires real GUI GPU context")
        RESULT["blender"] = bpy.app.version_string
        RESULT["invalidation"] = os.environ.get("NM_MARKER_INVALIDATE", "none")
        RESULT["handler"] = os.environ.get("NM_MARKER_HANDLER", "frame_change_post")
        RESULT["gpu_evaluation"] = os.environ.get("NM_MARKER_GPU_EVAL") == "1"
        if RESULT["gpu_evaluation"] and RESULT["handler"] != "render_pre":
            raise RuntimeError("GPU evaluation probe requires render_pre")
        if RESULT["handler"] not in {"frame_change_post", "render_pre"}:
            raise RuntimeError("invalid marker handler")
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "renderer": gpu.platform.renderer_get()}
        if RESULT["gpu_evaluation"]:
            source_root = os.environ.get("NM_TASK0_SOURCE", str(Path(__file__).resolve().parents[1]))
            sys.path.insert(0, source_root)
            from noisemaker_blender import api
            from noisemaker_blender.integration.images import ImagePublisher
            program = api.compile("search synth\nsolid(color: [0.1,0.2,0.333333]).write(o0)\nrender(o0)")
            session = api.open_session(program, width=32, height=32)
            publisher = ImagePublisher("task0-render-pre-gpu")
            initial = session.evaluate(api.FrameRequest(frame=1))
            image = session.publish_image(initial, publisher=publisher)
        else:
            image = bpy.data.images.new("NM_task0_frame_marker", width=32, height=32,
                                        alpha=True, float_buffer=True)
            image.colorspace_settings.name = "Non-Color"
            image.pixels.foreach_set(np.tile(np.array([0., 0., 0., 1.], dtype=np.float32), 32 * 32))
            image.update()
        scene = scene_for_render(image)
        world = bpy.data.worlds.new("NM_probe_world")
        world.use_nodes = True
        world.node_tree.nodes.clear()
        env = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
        env.image = image
        background = world.node_tree.nodes.new("ShaderNodeBackground")
        output_world = world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(env.outputs["Color"], background.inputs["Color"])
        world.node_tree.links.new(background.outputs[0], output_world.inputs["Surface"])
        scene.world = world
        scene.render.resolution_x = 32
        scene.render.resolution_y = 32
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "32"
        scene.view_settings.view_transform = "Standard"
        scene.frame_start, scene.frame_end = 1, 2
        install_callbacks()
        def publish_frame(scene, depsgraph=None):
            if not scene.render.use_lock_interface:
                stamp("marker_refused_unlocked", frame=scene.frame_current,
                      sample=marker_sample(image))
                return
            value = np.array([scene.frame_current / 10,
                              (scene.frame_current + scene.frame_subframe) / 5,
                              scene.frame_current / 3, 1.], dtype=np.float32)
            if session is not None:
                session.set_parameter("solid#0.color", value[:3].tolist())
                handle = session.evaluate(api.FrameRequest(frame=scene.frame_current))
                returned = session.publish_image(handle, publisher=publisher)
                if returned != image:
                    raise RuntimeError("GPU session replaced the Image identity")
            else:
                image.pixels.foreach_set(np.tile(value, 32 * 32))
                image.update()
            invalidation = RESULT["invalidation"]
            if invalidation in {"image", "material", "both"}:
                image.update_tag()
            if invalidation in {"material", "both"}:
                for material in bpy.data.materials:
                    if material.name == "NM_probe_mat":
                        material.node_tree.update_tag()
            if invalidation == "both" and scene.world and scene.world.use_nodes:
                scene.world.node_tree.update_tag()
            stamp("marker_published", frame=scene.frame_current,
                  subframe=scene.frame_subframe, sample=marker_sample(image))
        marker_collection = getattr(bpy.app.handlers, RESULT["handler"])
        marker_collection.append(publish_frame)
        marker_handler = publish_frame
        for engine, persistent in (("BLENDER_EEVEE", False), ("CYCLES", False), ("CYCLES", True)):
            scene.render.engine = engine
            if engine == "CYCLES":
                scene.cycles.samples = 4
                scene.cycles.device = "CPU"
            scene.render.use_persistent_data = persistent
            scene.render.use_lock_interface = True
            prefix = "marker_%s_p%d_" % (engine, int(persistent))
            scene.render.filepath = str(EVIDENCE / prefix)
            scene.frame_set(1)
            t0 = time.perf_counter()
            result = bpy.ops.render.render("EXEC_DEFAULT", animation=True)
            row = {"engine": engine, "persistent_data": persistent,
                   "lock_interface": True, "operator": sorted(result),
                   "elapsed_s": time.perf_counter() - t0, "frames": []}
            for frame in (1, 2):
                path = EVIDENCE / (prefix + "%04d.exr" % frame)
                if not path.exists():
                    row["frames"].append({"frame": frame, "error": "output missing"})
                    continue
                loaded = bpy.data.images.load(str(path), check_existing=False)
                row["frames"].append({"frame": frame, "center": marker_sample(loaded),
                                      "path": str(path)})
                bpy.data.images.remove(loaded)
            RESULT["renders"].append(row)
            stamp("marker_animation_done", **row)
        # With the interface unlocked the probe records a refusal and leaves the
        # last prepared Image untouched; no concurrent Image write is attempted.
        scene.render.use_lock_interface = False
        scene.frame_set(1, subframe=.5)
        if RESULT["handler"] == "render_pre":
            publish_frame(scene)
        stamp("unlocked_state", frame=scene.frame_current,
              subframe=scene.frame_subframe, sample=marker_sample(image))
        RESULT["status"] = "completed"
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error": repr(exc), "traceback": traceback.format_exc()})
    finally:
        if marker_handler is not None:
            collection = getattr(bpy.app.handlers, RESULT.get("handler", "frame_change_post"))
            if marker_handler in collection:
                collection.remove(marker_handler)
        remove_callbacks()
        if session is not None:
            session.close()
        save()
        print("NM_PROBE_RESULT", RESULT["status"], EVIDENCE / "live_marker.json", flush=True)
        bpy.ops.wm.quit_blender()
    return None


def run_presentation():
    """Count real Image Editor draw callbacks while publishing for 60 seconds."""
    handler = None
    try:
        if bpy.app.background or not bpy.context.window_manager.windows:
            raise RuntimeError("requires real Blender GUI, not background mode")
        RESULT["blender"] = {"version": bpy.app.version_string,
                             "build_hash": str(bpy.app.build_hash),
                             "build_branch": str(bpy.app.build_branch),
                             "background": bpy.app.background}
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "vendor": gpu.platform.vendor_get(),
                         "renderer": gpu.platform.renderer_get(),
                         "version": gpu.platform.version_get()}
        window = bpy.context.window
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        area.type = "IMAGE_EDITOR"
        image, pixels = build_image(512, 512)
        area.spaces.active.image = image
        publications = []
        draw_times = []
        drawn_generations = {}
        state = {"generation": 0, "last_publish": None, "began": time.perf_counter()}

        def draw():
            now = time.perf_counter()
            draw_times.append(now)
            generation = state["generation"]
            if generation and generation not in drawn_generations:
                drawn_generations[generation] = now

        handler = bpy.types.SpaceImageEditor.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
        area.tag_redraw()

        def finish(status, error=None):
            nonlocal handler
            if handler is not None:
                bpy.types.SpaceImageEditor.draw_handler_remove(handler, "WINDOW")
                handler = None
            observed = [drawn_generations[gen] - at for gen, at, _ in publications
                        if gen in drawn_generations]
            costs = [cost for _, _, cost in publications]
            intervals = [(b-a) for a, b in zip(draw_times, draw_times[1:])]
            def percentiles(values):
                if not values:
                    return None
                ordered = sorted(values)
                return {"p50": ordered[len(ordered)//2],
                        "p95": ordered[min(len(ordered)-1, int(len(ordered)*.95))],
                        "p99": ordered[min(len(ordered)-1, int(len(ordered)*.99))],
                        "max": ordered[-1]}
            RESULT["presentation"] = {
                "requested_duration_s": 60, "elapsed_s": time.perf_counter()-state["began"],
                "target_publication_hz": 60, "image_size": [512, 512],
                "image_float": image.is_float, "image_editor_area": [area.width, area.height],
                "publications": len(publications), "draw_callbacks": len(draw_times),
                "distinct_generations_drawn": len(drawn_generations),
                "first_draw_s": draw_times[0]-state["began"] if draw_times else None,
                "last_draw_s": draw_times[-1]-state["began"] if draw_times else None,
                "publication_ms": percentiles([value*1000 for value in costs]),
                "publication_to_draw_ms": percentiles([value*1000 for value in observed]),
                "draw_interval_ms": percentiles([value*1000 for value in intervals]),
            }
            RESULT["status"] = status
            if error is not None:
                RESULT["errors"].append(error)
            save()
            print("NM_PROBE_RESULT", status, EVIDENCE / "image_editor_presentation.json", flush=True)
            bpy.ops.wm.quit_blender()
            return None

        def tick():
            try:
                if time.perf_counter() - state["began"] >= 60:
                    return finish("completed")
                generation = state["generation"] + 1
                pixels[0] = 0.1 if generation % 2 else 0.9
                t0 = time.perf_counter()
                image.pixels.foreach_set(pixels)
                image.update()
                area.tag_redraw()
                t1 = time.perf_counter()
                state["generation"] = generation
                state["last_publish"] = t1
                publications.append((generation, t1, t1-t0))
                return 1/60
            except Exception as exc:
                return finish("failed", {"error": repr(exc), "traceback": traceback.format_exc()})

        bpy.app.timers.register(tick, first_interval=0.0)
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error": repr(exc), "traceback": traceback.format_exc()})
        if handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(handler, "WINDOW")
        save()
        bpy.ops.wm.quit_blender()
    return None


def run_continuous():
    """Observe one real live multipass producer and Image Editor for 60/600 s."""
    handler = None
    try:
        if bpy.app.background or bpy.context.window is None:
            raise RuntimeError("requires real Blender GUI")
        duration = int(os.environ.get("NM_CONTINUOUS_SECONDS", "60"))
        if duration not in (60, 600):
            raise ValueError("continuous duration must be 60 or 600 seconds")
        source_root = os.environ.get("NM_TASK0_SOURCE", str(Path(__file__).resolve().parents[1]))
        sys.path.insert(0, source_root)
        from noisemaker_blender import register as register_addon
        from noisemaker_blender.integration.lifecycle import registry
        from noisemaker_blender.integration.persistence import create_instance
        from noisemaker_blender.integration.images import ImagePublisher
        from noisemaker_blender.runtime.session import RenderSession
        register_addon()
        scene = bpy.context.scene
        text_block = bpy.data.texts.new("NM continuous multipass source")
        text_block.write("search synth, filter\nnoise(seed: 1, scaleX: 50, scaleY: 50).bloom().write(o0)\nrender(o0)\n")
        config = create_instance(scene, "", "NM continuous multipass")
        config.source_mode = "TEXT"
        config.text = text_block
        config.preview_width = 512
        config.preview_height = 512
        config.preview_fps = 60
        config.time_mode = "free_run"
        config.live_enabled = True
        area = max(bpy.context.window.screen.areas, key=lambda item: item.width * item.height)
        area.type = "IMAGE_EDITOR"
        state = {"started": None, "first_image": None, "base_generation": None,
                 "published": [], "drawn": [], "last_published": None,
                 "last_drawn": None, "draw_callbacks": 0, "rss": [],
                 "resource_samples": [], "last_resource_sample": 0,
                 "last_rss_sample": 0, "warm_started": time.monotonic(),
                 "error": None}
        stage_times = {name: [] for name in ("registry_tick", "registry_scan",
                        "sync_instance", "session_evaluate", "session_read_float",
                        "image_publish")}
        tick_spans = []
        wrapped = []

        def time_method(owner, method, label):
            original = getattr(owner, method)
            def measured(*args, **kwargs):
                began = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    if state["started"] is not None:
                        ended = time.perf_counter()
                        stage_times[label].append((ended-began)*1000)
                        if label == "registry_tick":
                            tick_spans.append((began, ended))
            setattr(owner, method, measured)
            wrapped.append((owner, method, original))

        time_method(registry, "tick", "registry_tick")
        time_method(registry, "scan", "registry_scan")
        time_method(registry, "sync_instance", "sync_instance")
        time_method(RenderSession, "evaluate", "session_evaluate")
        time_method(RenderSession, "read_float", "session_read_float")
        time_method(ImagePublisher, "publish", "image_publish")
        RESULT["blender"] = {"version": bpy.app.version_string,
                             "build_hash": str(bpy.app.build_hash),
                             "background": bpy.app.background}
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "vendor": gpu.platform.vendor_get(),
                         "renderer": gpu.platform.renderer_get(),
                         "version": gpu.platform.version_get()}

        def rss_kb():
            result = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
                                    capture_output=True, text=True, check=True)
            return int(result.stdout.strip())

        def backend_metrics(record):
            backend = record.session.backend if record.session else None
            if backend is None:
                return None
            return dict(getattr(backend, "metrics", {}),
                        surface_count=len(getattr(backend, "surfaces", {})),
                        pool_count=len(getattr(backend, "pool", {})),
                        session_generation=record.session.generation)

        def draw():
            state["draw_callbacks"] += 1
            if state["started"] is None:
                return
            image = config.output_image
            if image is None:
                return
            generation = image.get("noisemaker_generation")
            if generation is not None and generation != state["last_drawn"]:
                state["last_drawn"] = generation
                state["drawn"].append((int(generation), time.monotonic()-state["started"]))

        handler = bpy.types.SpaceImageEditor.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")

        def percentiles(values):
            if not values:
                return None
            ordered = sorted(values)
            return {"p50": ordered[len(ordered)//2],
                    "p95": ordered[min(len(ordered)-1, int(len(ordered)*.95))],
                    "p99": ordered[min(len(ordered)-1, int(len(ordered)*.99))],
                    "max": ordered[-1]}

        def finish(error=None):
            nonlocal handler
            if handler is not None:
                bpy.types.SpaceImageEditor.draw_handler_remove(handler, "WINDOW")
                handler = None
            for owner, method, original in reversed(wrapped):
                setattr(owner, method, original)
            record = registry.get(scene, config.instance_id)
            now = time.monotonic()
            elapsed = now-state["started"] if state["started"] is not None else 0
            published = state["published"]
            drawn = state["drawn"]
            pub_intervals = [(b[1]-a[1])*1000 for a,b in zip(published,published[1:])]
            draw_intervals = [(b[1]-a[1])*1000 for a,b in zip(drawn,drawn[1:])]
            RESULT["continuous"] = {
                "requested_duration_s": duration, "elapsed_s": elapsed,
                "source": text_block.as_string(), "image_size": [512,512],
                "preview_fps_setting": config.preview_fps,
                "publication_count": len(published), "presented_generation_count": len(drawn),
                "publication_fps": len(published)/max(.001,elapsed),
                "presented_fps": len(drawn)/max(.001,elapsed),
                "draw_callbacks": state["draw_callbacks"],
                "publication_interval_ms": percentiles(pub_intervals),
                "presentation_interval_ms": percentiles(draw_intervals),
                "publication_timestamps": published,
                "presentation_timestamps": drawn,
                "rss_kb_samples": state["rss"],
                "rss_kb_start": state["rss"][0][1] if state["rss"] else None,
                "rss_kb_end": state["rss"][-1][1] if state["rss"] else None,
                "rss_kb_peak": max((row[1] for row in state["rss"]), default=None),
                "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "resource_samples": state["resource_samples"],
                "backend_metrics_end": backend_metrics(record),
                "stage_profile_ms": {name: {"calls": len(values),
                                              "latency": percentiles(values)}
                                     for name, values in stage_times.items()},
                "timer_start_interval_ms": percentiles([
                    (next_start-start)*1000 for (start, _), (next_start, _) in
                    zip(tick_spans, tick_spans[1:])]),
                "post_work_wait_ms": percentiles([
                    (next_start-end)*1000 for (_, end), (next_start, _) in
                    zip(tick_spans, tick_spans[1:])]),
                "stable_image_identity": config.output_image is state["first_image"],
                "image_float": bool(config.output_image and config.output_image.is_float),
                "last_error": config.last_error,
            }
            if error is not None:
                RESULT["errors"].append(error)
            RESULT["status"] = "completed" if not RESULT["errors"] and len(drawn)>0 else "failed"
            save()
            print("NM_PROBE_RESULT", RESULT["status"], EVIDENCE / ("continuous_%d.json" % duration), flush=True)
            bpy.ops.wm.quit_blender()
            return None

        def poll():
            try:
                now = time.monotonic()
                record = registry.get(scene, config.instance_id)
                image = config.output_image
                if image is not None and area.spaces.active.image is not image:
                    area.spaces.active.image = image
                    area.tag_redraw()
                if state["started"] is None:
                    if image is None or record.session is None or now-state["warm_started"]<2:
                        return .01
                    state["started"] = now
                    state["first_image"] = image
                    state["base_generation"] = int(image.get("noisemaker_generation",0))
                    state["last_published"] = state["base_generation"]
                    state["last_drawn"] = state["base_generation"]
                    state["last_resource_sample"] = now-60
                    state["last_rss_sample"] = now-1
                elapsed = now-state["started"]
                generation = int(image.get("noisemaker_generation",0)) if image is not None else 0
                if generation != state["last_published"]:
                    state["last_published"] = generation
                    state["published"].append((generation,elapsed))
                if now-state["last_rss_sample"]>=1:
                    state["rss"].append((elapsed,rss_kb()))
                    state["last_rss_sample"] = now
                if now-state["last_resource_sample"]>=60:
                    state["resource_samples"].append((elapsed,backend_metrics(record)))
                    state["last_resource_sample"] = now
                if config.last_error:
                    return finish({"error":"live instance error", "detail":config.last_error})
                if elapsed>=duration:
                    return finish()
                return .01
            except Exception as exc:
                return finish({"error":repr(exc),"traceback":traceback.format_exc()})

        bpy.app.timers.register(poll, first_interval=.05)
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error":repr(exc),"traceback":traceback.format_exc()})
        if handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(handler,"WINDOW")
        save()
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register({"marker": run_marker, "presentation": run_presentation,
                         "continuous": run_continuous}.get(PHASE, run), first_interval=0.5)

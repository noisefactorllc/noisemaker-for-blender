"""Task 0 GUI probe for actual Blender Image consumers and GPU-write coherence.

NM_EVIDENCE_DIR is required and must point outside the checkout. Main phase
publishes an asymmetric floating-point Image twice, renders Eevee/Cycles
material, world and CPU/GPU compositor consumers, evaluates a Geometry Nodes
image sample, then attempts framebuffer writes to gpu.texture.from_image.
Reopen phase, selected by NM_PROBE_PHASE=reopen, inspects the saved .blend in a
second Blender GUI process. Optional/unsupported APIs are reported as such;
only observed output qualifies a consumer.
"""
import json
import os
from pathlib import Path
import threading
import time
import traceback
import sys
sys.path.insert(0, os.environ.get("NM_TASK0_ADDON_STAGING", str(Path(__file__).resolve().parents[1])))
from noisemaker_blender.integration.materials import attach_material, attach_world
from noisemaker_blender.integration.compositor import attach_compositor
from noisemaker_blender.integration.geometry import attach_geometry_image

import bpy
import gpu
import numpy as np

if "--factory-startup" not in sys.argv or os.environ.get("NM_HARNESS_AUTOCLOSE") != "1":
    raise RuntimeError("Task 0 probe requires a disposable --factory-startup Blender process with NM_HARNESS_AUTOCLOSE=1")

EVIDENCE = Path(os.environ["NM_EVIDENCE_DIR"]).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)
PHASE = os.environ.get("NM_PROBE_PHASE", "main")
NAME = "NM_task0_consumer"
RESULT = {"probe": "consumer_coherence", "phase": PHASE, "events": [],
          "consumers": [], "gpu_write": {}, "errors": []}
START = time.perf_counter()


def record(kind, **fields):
    row = {"at_ms": round((time.perf_counter()-START)*1000, 3),
           "kind": kind, "thread": threading.get_ident(), **fields}
    RESULT["events"].append(row)
    print("NM_PROBE", json.dumps(row, default=str), flush=True)


def save():
    filename = "consumer_sequence.json" if PHASE == "sequence" else ("consumer_coherence%s.json" % ("_reopen" if PHASE == "reopen" else ""))
    path = EVIDENCE / filename
    path.write_text(json.dumps(RESULT, indent=2, default=str) + "\n")
    return path


def pattern(width, height, revision):
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[:, :, 0] = (-0.25 if revision == 1 else 0.5) + x
    rgba[:, :, 1] = (2.0 if revision == 1 else 0.25) + y
    rgba[:, :, 2] = (0.125 if revision == 1 else 1.5) + x * y
    rgba[:, :, 3] = 0.2 + 0.8 * x
    return rgba.reshape(-1)


def pixel_samples(img):
    w, h = img.size
    flat = np.empty(w*h*4, dtype=np.float32)
    img.pixels.foreach_get(flat)
    arr = flat.reshape(h, w, 4)
    return {"bottom_left": arr[0, 0].tolist(),
            "bottom_right": arr[0, -1].tolist(),
            "top_left": arr[-1, 0].tolist(),
            "top_right": arr[-1, -1].tolist(),
            "center": arr[h//2, w//2].tolist(),
            "min": arr.min(axis=(0,1)).tolist(),
            "max": arr.max(axis=(0,1)).tolist()}


def create_image():
    img = bpy.data.images.new(NAME, width=64, height=32, alpha=True,
                              float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    return img


def publish(img, revision):
    pixels = pattern(*img.size, revision)
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
    record("publish", revision=revision, foreach_set_ms=(t1-t0)*1000,
           image_update_ms=(t2-t1)*1000, areas=areas,
           samples=pixel_samples(img))


def setup_scene(img):
    scene = bpy.context.scene
    for existing in list(scene.objects):
        bpy.data.objects.remove(existing, do_unlink=True)
    scene.render.resolution_x = 48
    scene.render.resolution_y = 48
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "32"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.camera = bpy.data.objects.new("NM_camera", bpy.data.cameras.new("NM_camera"))
    scene.collection.objects.link(scene.camera)
    scene.camera.location = (0, 0, 3)
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 2
    mesh = bpy.data.meshes.new("NM_mesh")
    mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)], [], [(0,1,2,3)])
    uv = mesh.uv_layers.new()
    for loop, coord in zip(mesh.polygons[0].loop_indices,
                           ((0,0), (1,0), (1,1), (0,1))):
        uv.data[loop].uv = coord
    plane = bpy.data.objects.new("NM_plane", mesh)
    scene.collection.objects.link(plane)
    mat = bpy.data.materials.new("NM_material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    tex = attach_material("shared-consumer", mat, img)
    tex.interpolation = "Closest"
    emit = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    mat.node_tree.links.new(tex.outputs["Color"], emit.inputs["Color"])
    mat.node_tree.links.new(emit.outputs[0], output.inputs["Surface"])
    same = attach_material("shared-consumer", mat, img)
    independent = attach_material("independent-consumer", mat, img)
    RESULT["adapter_checks"] = {"shared_reused": same == tex,
                                "independent_node": independent != tex,
                                "material_link_preserved": any(link.from_node == tex and link.to_node == emit
                                                               for link in mat.node_tree.links)}
    plane.data.materials.append(mat)
    world = bpy.data.worlds.new("NM_world")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    nodes.clear()
    env = attach_world("shared-consumer", world, img)
    background = nodes.new("ShaderNodeBackground")
    output = nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(env.outputs["Color"], background.inputs["Color"])
    world.node_tree.links.new(background.outputs[0], output.inputs["Surface"])
    scene.world = world
    return scene, plane


def render_samples(scene, label):
    t0 = time.perf_counter()
    try:
        output = EVIDENCE / (label + ".exr")
        output.unlink(missing_ok=True)
        scene.render.filepath = str(output)
        result = bpy.ops.render.render("EXEC_DEFAULT", write_still=True)
        if not output.exists():
            raise RuntimeError("render did not write EXR output")
        image = bpy.data.images.load(str(output), check_existing=False)
        samples = pixel_samples(image)
        bpy.data.images.remove(image)
        row = {"label": label, "operator": sorted(result), "elapsed_s": time.perf_counter()-t0,
               "compositing_node_group": getattr(scene.compositing_node_group, "name", None),
               "samples": samples}
    except Exception as exc:
        row = {"label": label, "elapsed_s": time.perf_counter()-t0,
               "error": repr(exc), "traceback": traceback.format_exc()}
    RESULT["consumers"].append(row)
    record("consumer_render", **{k: v for k, v in row.items() if k != "traceback"})
    return row


def render_consumers(scene, plane, revision):
    for engine in ("BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
        except Exception as exc:
            RESULT["consumers"].append({"label": f"{engine}_material_r{revision}", "unsupported": repr(exc)})
            continue
        if engine == "CYCLES":
            scene.cycles.samples = 4
            scene.cycles.device = "CPU"
        scene.use_nodes = False
        if hasattr(scene, "compositing_node_group"):
            scene.compositing_node_group = None
        plane.hide_render = False
        render_samples(scene, f"{engine}_material_r{revision}")
        scene.collection.objects.unlink(plane)
        scene.view_layers.update()
        record("world_setup", engine=engine, revision=revision, plane_in_scene=plane.name in scene.objects)
        render_samples(scene, f"{engine}_world_r{revision}")
        scene.collection.objects.link(plane)
    scene.render.engine = "BLENDER_EEVEE"
    try:
        scene.use_nodes = True
        if hasattr(scene, "compositing_node_group"):
            tree = bpy.data.node_groups.new("NM_compositor_r%s" % revision, "CompositorNodeTree")
            scene.compositing_node_group = tree
        else:
            tree = scene.node_tree
        nodes = tree.nodes
        nodes.clear()
        image = attach_compositor("shared-consumer", tree, bpy.data.images[NAME])
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        out = nodes.new("NodeGroupOutput")
        tree.links.new(image.outputs["Image"], out.inputs["Image"])
        for device in ("CPU", "GPU"):
            label = f"compositor_{device}_r{revision}"
            try:
                scene.render.compositor_device = device
            except Exception as exc:
                RESULT["consumers"].append({"label": label, "unsupported": repr(exc)})
                continue
            render_samples(scene, label)
    except Exception as exc:
        RESULT["consumers"].append({"label": f"compositor_setup_r{revision}", "error": repr(exc)})
    finally:
        scene.use_nodes = False
        if hasattr(scene, "compositing_node_group"):
            scene.compositing_node_group = None


def geometry_sample(img, revision):
    label = f"geometry_nodes_r{revision}"
    try:
        group = bpy.data.node_groups.get("NM_geometry")
        obj = bpy.data.objects.get("NM_geometry_object")
        if group is None:
            group = bpy.data.node_groups.new("NM_geometry", "GeometryNodeTree")
            group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
            group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
            input_node = group.nodes.new("NodeGroupInput")
            output_node = group.nodes.new("NodeGroupOutput")
            tex = attach_geometry_image("shared-consumer", group, img)
            position = group.nodes.new("GeometryNodeInputPosition")
            set_position = group.nodes.new("GeometryNodeSetPosition")
            group.links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
            group.links.new(position.outputs["Position"], tex.inputs["Vector"])
            group.links.new(tex.outputs["Color"], set_position.inputs["Offset"])
            group.links.new(set_position.outputs["Geometry"], output_node.inputs["Geometry"])
            mesh = bpy.data.meshes.new("NM_geometry_mesh")
            mesh.from_pydata([(0.25, 0.25, 0), (0.75, 0.75, 0)], [], [])
            obj = bpy.data.objects.new("NM_geometry_object", mesh)
            bpy.context.scene.collection.objects.link(obj)
            mod = obj.modifiers.new("NM_geometry_mod", "NODES")
            mod.node_group = group
        tex = next(node for node in group.nodes if node.bl_idname == "GeometryNodeImageTexture")
        tex.inputs["Image"].default_value = img
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        positions = [list(v.co) for v in mesh.vertices]
        evaluated.to_mesh_clear()
        row = {"label": label, "positions": positions}
    except Exception as exc:
        row = {"label": label, "error": repr(exc), "traceback": traceback.format_exc()}
    RESULT["consumers"].append(row)
    record("geometry_sample", **{k:v for k,v in row.items() if k != "traceback"})


def gpu_write_probe(img):
    try:
        from gpu.types import GPUFrameBuffer
        tex = gpu.texture.from_image(img)
        before = pixel_samples(img)
        t0 = time.perf_counter()
        framebuffer = GPUFrameBuffer(color_slots=(tex,))
        with framebuffer.bind():
            framebuffer.clear(color=(0.875, 0.125, 1.75, 0.5))
        t1 = time.perf_counter()
        after = pixel_samples(img)
        RESULT["gpu_write"] = {"attempted": True, "elapsed_ms": (t1-t0)*1000,
                               "texture_format": tex.format,
                               "cpu_before": before, "cpu_after": after,
                               "cpu_changed": before != after}
        record("gpu_write", **RESULT["gpu_write"])
    except Exception as exc:
        RESULT["gpu_write"] = {"attempted": True, "error": repr(exc),
                               "traceback": traceback.format_exc()}
        record("gpu_write_error", error=repr(exc))


def assert_consumer_generations():
    """Check observed consumer deltas against the fixture's analytic RGB shift."""
    expected = np.array((0.75, -1.75, 1.375), dtype=np.float32)
    rows = {row["label"]: row for row in RESULT["consumers"]}
    checked = []
    for kind in ("BLENDER_EEVEE_material", "CYCLES_material",
                 "BLENDER_EEVEE_world", "CYCLES_world",
                 "compositor_CPU", "compositor_GPU"):
        before = rows[kind + "_r1"]
        after = rows[kind + "_r2"]
        if "samples" not in before or "samples" not in after:
            raise AssertionError("missing rendered consumer samples: %s" % kind)
        first = np.asarray(before["samples"]["center"], dtype=np.float32)
        second = np.asarray(after["samples"]["center"], dtype=np.float32)
        delta = second[:3] - first[:3]
        if not np.allclose(delta, expected, atol=.03, rtol=0):
            raise AssertionError("%s center RGB delta %s expected %s" %
                                 (kind, delta.tolist(), expected.tolist()))
        if kind.startswith("compositor") and not np.isclose(first[3], second[3], atol=.002):
            raise AssertionError("%s lost source alpha across generations" % kind)
        checked.append({"consumer": kind, "rgb_delta": delta.tolist(),
                        "alpha_before": float(first[3]), "alpha_after": float(second[3])})
    before = rows["geometry_nodes_r1"].get("positions")
    after = rows["geometry_nodes_r2"].get("positions")
    if before is None or after is None or len(before) != len(after) or not before:
        raise AssertionError("missing evaluated Geometry Nodes positions")
    for index, (first, second) in enumerate(zip(before, after)):
        delta = np.asarray(second, dtype=np.float32)-np.asarray(first, dtype=np.float32)
        if not np.allclose(delta, expected, atol=.03, rtol=0):
            raise AssertionError("Geometry Nodes vertex %d delta %s expected %s" %
                                 (index, delta.tolist(), expected.tolist()))
        checked.append({"consumer": "geometry_nodes_vertex_%d" % index,
                        "rgb_delta": delta.tolist()})
    if not all(RESULT.get("adapter_checks", {}).values()):
        raise AssertionError("managed consumer identity/link adapter checks failed")
    RESULT["assertions"] = {"expected_rgb_delta": expected.tolist(),
                            "tolerance_absolute": .03, "checked": checked,
                            "passed_count": len(checked) + len(RESULT["adapter_checks"])}



def post_gpu_lifecycle(img):
    checks = {"backend_change": "unavailable in macOS Metal session"}
    try:
        img.update()
        checks["after_image_update"] = pixel_samples(img)
        checks["texture_after_update"] = {"format": gpu.texture.from_image(img).format}
    except Exception as exc:
        checks["update_error"] = repr(exc)
    try:
        img.reload()
        checks["after_reload"] = pixel_samples(img)
    except Exception as exc:
        checks["reload_error"] = repr(exc)
    try:
        img.scale(32, 16)
        img.update()
        checks["after_resize"] = {"size": list(img.size), "samples": pixel_samples(img),
                                  "texture_format": gpu.texture.from_image(img).format}
    except Exception as exc:
        checks["resize_error"] = repr(exc)
    RESULT["gpu_lifecycle"] = checks
    record("gpu_lifecycle", **checks)

def run():
    try:
        if bpy.app.background or not bpy.context.window_manager.windows:
            raise RuntimeError("requires real Blender GUI, not background mode")
        RESULT["blender"] = {"version": bpy.app.version_string,
                             "build_hash": str(bpy.app.build_hash)}
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "vendor": gpu.platform.vendor_get(),
                         "renderer": gpu.platform.renderer_get()}
        if PHASE == "reopen":
            img = bpy.data.images.get(NAME)
            if img is None:
                raise RuntimeError("saved Image missing after reopen")
            RESULT["reopen"] = {"size": list(img.size), "is_float": img.is_float,
                                "samples": pixel_samples(img)}
            RESULT["status"] = "completed"
            return None
        img = create_image()
        scene, plane = setup_scene(img)
        for revision in (1, 2):
            publish(img, revision)
            render_consumers(scene, plane, revision)
            geometry_sample(img, revision)
        assert_consumer_generations()
        gpu_write_probe(img)
        # Test downstream behavior even if the direct write did not reach CPU pixels.
        render_consumers(scene, plane, "gpu")
        geometry_sample(img, "gpu")
        post_gpu_lifecycle(img)
        scene.render.compositor_device = "CPU"
        scene.use_nodes = False
        path = EVIDENCE / "consumer_coherence.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
        RESULT["saved_blend"] = str(path)
        RESULT["status"] = "completed"
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error": repr(exc), "traceback": traceback.format_exc()})
    finally:
        path = save()
        print("NM_PROBE_RESULT", RESULT["status"], path, flush=True)
        bpy.ops.wm.quit_blender()
    return None



def run_sequence():
    try:
        if bpy.app.background or not bpy.context.window_manager.windows:
            raise RuntimeError("requires real Blender GUI")
        RESULT["blender"] = bpy.app.version_string
        RESULT["gpu"] = {"backend": gpu.platform.backend_type_get(),
                         "renderer": gpu.platform.renderer_get()}
        frame_colors = ((0.1, 0.2, 0.333333, 1.), (0.2, 0.4, 0.666667, 1.))
        sequence_colorspace = os.environ.get("NM_SEQUENCE_COLORSPACE", "Linear Rec.709")
        RESULT["sequence_colorspace"] = sequence_colorspace
        for frame, color in enumerate(frame_colors, 1):
            path = EVIDENCE / ("prepared_%04d.exr" % frame)
            image = bpy.data.images.new("NM_prepared_%d" % frame, width=32, height=32,
                                        alpha=True, float_buffer=True)
            image.colorspace_settings.name = sequence_colorspace
            image.alpha_mode = "STRAIGHT"
            image.pixels.foreach_set(np.tile(np.asarray(color, dtype=np.float32), 32 * 32))
            image.update()
            image.filepath_raw = str(path)
            image.file_format = "OPEN_EXR"
            image.save()
            RESULT["events"].append({"kind": "prepared_file", "frame": frame,
                                      "path": str(path), "bytes": path.stat().st_size})
            bpy.data.images.remove(image)
        sequence = bpy.data.images.load(str(EVIDENCE / "prepared_0001.exr"), check_existing=False)
        sequence.source = "SEQUENCE"
        sequence.colorspace_settings.name = sequence_colorspace
        scene, plane = setup_scene(sequence)
        tex = next(node for node in plane.active_material.node_tree.nodes
                   if node.bl_idname == "ShaderNodeTexImage")
        tex.image_user.frame_start = 1
        tex.image_user.frame_duration = 2
        tex.image_user.frame_offset = 0
        tex.image_user.use_auto_refresh = True
        scene.render.resolution_x = 32
        scene.render.resolution_y = 32
        scene.render.use_lock_interface = True
        scene.render.film_transparent = True
        scene.frame_start, scene.frame_end = 1, 2
        for engine, persistent in (("BLENDER_EEVEE", False), ("CYCLES", False), ("CYCLES", True)):
            scene.render.engine = engine
            scene.render.use_persistent_data = persistent
            if engine == "CYCLES":
                scene.cycles.samples = 4
                scene.cycles.device = "CPU"
            prefix = "sequence_%s_p%d_" % (engine, int(persistent))
            scene.render.filepath = str(EVIDENCE / prefix)
            scene.frame_set(1)
            t0 = time.perf_counter()
            operator = bpy.ops.render.render("EXEC_DEFAULT", animation=True)
            row = {"engine": engine, "persistent_data": persistent,
                   "operator": sorted(operator), "elapsed_s": time.perf_counter()-t0,
                   "image_source": sequence.source, "image_user": {
                       "frame_start": tex.image_user.frame_start,
                       "frame_duration": tex.image_user.frame_duration,
                       "use_auto_refresh": tex.image_user.use_auto_refresh},
                   "frames": []}
            for frame in (1, 2):
                path = EVIDENCE / (prefix + "%04d.exr" % frame)
                if not path.exists():
                    row["frames"].append({"frame": frame, "error": "render output missing"})
                    continue
                rendered = bpy.data.images.load(str(path), check_existing=False)
                row["frames"].append({"frame": frame, "center": pixel_samples(rendered)["center"],
                                      "path": str(path)})
                bpy.data.images.remove(rendered)
            RESULT["consumers"].append(row)
            record("sequence_animation_done", **row)
        # from_image() has no ImageUser argument. Observe its global Image view
        # separately from stock node ImageUser frame selection used above.
        direct = []
        for frame in (1, 2):
            scene.frame_set(frame)
            row = {"scene_frame": frame, "image_user_frame_current": tex.image_user.frame_current,
                   "cpu_image_center": pixel_samples(sequence)["center"]}
            try:
                from gpu.types import GPUFrameBuffer
                texture = gpu.texture.from_image(sequence)
                framebuffer = GPUFrameBuffer(color_slots=(texture,))
                with framebuffer.bind():
                    raw = gpu.state.active_framebuffer_get().read_color(16, 16, 1, 1, 4, 0, "FLOAT")
                    raw.dimensions = 4
                    row["from_image_center"] = np.array(raw, dtype=np.float32).tolist()
            except Exception as exc:
                row["from_image_error"] = repr(exc)
            direct.append(row)
        RESULT["direct_sequence_image"] = direct
        RESULT["status"] = "completed"
    except Exception as exc:
        RESULT["status"] = "failed"
        RESULT["errors"].append({"error": repr(exc), "traceback": traceback.format_exc()})
    finally:
        path = save()
        print("NM_PROBE_RESULT", RESULT["status"], path, flush=True)
        bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(run_sequence if PHASE == "sequence" else run, first_interval=0.5)

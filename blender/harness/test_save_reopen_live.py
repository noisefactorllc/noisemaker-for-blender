"""Two-phase GUI persistence probe for live configuration and packed float output.

Set NM_LIVE_PHASE=create, run in an isolated Blender GPU window, then run again
with NM_LIVE_PHASE=verify and the saved blend file as Blender's input file.
Require both phase JSON results to report success=true, including actual undo
and redo after a disposable operator-created undo baseline. Scratch files go
only to NM_EVIDENCE_DIR.
"""
from array import array
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy

ARMED = os.environ.get("NM_HARNESS_AUTOCLOSE") == "1" and "--factory-startup" in sys.argv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender"))
from noisemaker_blender import register as register_addon
from noisemaker_blender.integration.lifecycle import registry
from noisemaker_blender.integration.parameters import BlenderPropertyAdapter
from noisemaker_blender.integration.persistence import create_instance, ensure_unique_ids

EVIDENCE = Path(os.environ.get("NM_EVIDENCE_DIR", "/tmp/noisemaker-live-persistence"))
EVIDENCE.mkdir(parents=True, exist_ok=True)
PHASE = os.environ.get("NM_LIVE_PHASE", "create")
BLEND = EVIDENCE / "live-instance.blend"


def read_pixel(image):
    pixels = array("f", [0.0]) * (image.size[0] * image.size[1] * 4)
    image.pixels.foreach_get(pixels)
    return list(pixels[:4])


def finish(result):
    (EVIDENCE / (PHASE + ".json")).write_text(json.dumps(result, indent=2))
    print("NM_LIVE_PERSISTENCE", json.dumps(result), flush=True)
    if ARMED:
        bpy.ops.wm.quit_blender()


def window_override():
    window = bpy.context.window
    area = next((area for area in window.screen.areas if area.type == 'VIEW_3D'), None)
    if area is None:
        area = next(area for area in window.screen.areas
                    if any(region.type == 'WINDOW' for region in area.regions))
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, screen=window.screen,
                                     area=area, region=region)


def run():
    result = {"success": False, "phase": PHASE, "blender": bpy.app.version_string}
    deferred = False
    try:
        assert ARMED, "disposable native probe requires NM_HARNESS_AUTOCLOSE=1 and --factory-startup"
        assert not bpy.app.background and bpy.context.window is not None, "GUI GPU window required"
        if not hasattr(bpy.types.Scene, "noisemaker_instances"):
            register_addon()
        scene = bpy.context.scene
        if PHASE == "create":
            text = bpy.data.texts.new("NM saved DSL")
            text.write("search synth\nsolid(color: [0.25, 0.5, 0.75, 1]).write(o0)\nrender(o0)\n")
            config = create_instance(scene, "", "NM saved live")
            config.source_mode = 'TEXT'
            config.text = text
            config.preview_width = 16
            config.preview_height = 8
            config.live_enabled = True
            record = registry.ensure_session(scene, config.instance_id, 16, 8, force_sync=True)
            image = registry._produce(record)
            assert image.is_float and config.output_image is image
            initial = read_pixel(image)
            image.pack()  # Persist an older generation first.
            color_property = BlenderPropertyAdapter.property_name("solid#0.color")
            registry.set_parameter(scene, config.instance_id, "solid#0.color",
                                   (0.6, 0.1, 0.3, 1.0))
            assert tuple(config[color_property]) == (0.6, 0.1, 0.3, 1.0)
            refreshed = registry._produce(record)
            assert refreshed is image, "source revision changed Image identity"
            before = read_pixel(image)
            assert max(abs(a - b) for a, b in zip(initial, before)) > 0.1
            # Persist a declared host Image binding and its own consumer Image.
            source_image = bpy.data.images.new("NM saved host input", width=16, height=8,
                                               alpha=True, float_buffer=True)
            source_image.colorspace_settings.name = "Linear Rec.709"
            source_image.pixels.foreach_set(array("f", [0.8, 0.2, 0.1, 1.0]) * (16 * 8))
            source_image.update()
            source_image.pack()
            media = create_instance(scene,
                "search synth\nmedia().write(o0)\nrender(o0)\n", "NM saved media")
            media.preview_width = 16
            media.preview_height = 8
            media.live_enabled = True
            media.pack_output = True
            registry.bind_input(scene, media.instance_id, "imageTex_step_0", image=source_image)
            media_record = registry.ensure_session(scene, media.instance_id, 16, 8,
                                                   force_sync=True)
            media_output = registry._produce(media_record)
            media_pixel = read_pixel(media_output)
            assert max(media_pixel[:3]) > 0.05, "bound host Image rendered no color"
            config.pack_output = True
            bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
            assert BLEND.exists(), "blend file was not saved"
            result.update(success=True, instance_id=config.instance_id,
                          image_name=image.name, pixel=before, previous_pixel=initial,
                          packed=bool(image.packed_file), blend=str(BLEND),
                          media_instance_id=media.instance_id,
                          media_input_name=source_image.name,
                          media_pixel=media_pixel)
        elif PHASE == "verify":
            created = json.loads((EVIDENCE / "create.json").read_text())
            assert bpy.data.filepath == str(BLEND), "verification did not load saved blend"
            configs = [item for item in scene.noisemaker_instances
                       if item.instance_id == created["instance_id"]]
            assert len(configs) == 1, "live config ID did not survive reopen"
            config = configs[0]
            assert config.text is not None and "solid(" in config.text.as_string()
            assert (config.preview_width, config.preview_height) == (16, 8)
            image = config.output_image
            assert image is not None and image.name == created["image_name"]
            assert image.packed_file is not None, "packed Image payload not retained"
            after = read_pixel(image)
            assert max(abs(a - b) for a, b in zip(after, created["pixel"])) < 0.005, \
                "saved/reopened Image pixels changed"
            assert max(abs(a - b) for a, b in zip(after, created["previous_pixel"])) > 0.1, \
                "save retained stale packed generation"
            media = next((item for item in scene.noisemaker_instances
                          if item.instance_id == created["media_instance_id"]), None)
            assert media is not None and len(media.input_bindings) == 1
            assert media.input_bindings[0].binding_name == "imageTex_step_0"
            assert media.input_bindings[0].image.name == created["media_input_name"]
            assert media.input_bindings[0].image.packed_file is not None
            media_record = registry.ensure_session(scene, media.instance_id, 16, 8,
                                                   force_sync=True)
            media_output = registry._produce(media_record)
            media_after = read_pixel(media_output)
            assert max(abs(a - b) for a, b in zip(media_after, created["media_pixel"])) < 0.01, \
                "reopened host Image binding rendered different pixels"
            duplicate = scene.copy()
            repaired = ensure_unique_ids(tuple(bpy.data.scenes))
            copied = duplicate.noisemaker_instances[0]
            assert copied.instance_id != config.instance_id
            assert copied.output_image is None, "duplicate adopted original output Image"
            assert copied in repaired
            # Blender's Operator API creates an undo step for an operator with
            # REGISTER and UNDO after it finishes. Seal the disposable baseline
            # first, then edit in a second operator before polling undo.
            class NM_OT_probe_baseline(bpy.types.Operator):
                bl_idname = "noisemaker.probe_baseline"
                bl_label = "Probe Noisemaker Undo Baseline"
                bl_options = {'REGISTER', 'UNDO'}
                def execute(self, context):
                    context.scene["nm_undo_probe_baseline"] = 1
                    return {'FINISHED'}
            class NM_OT_probe_width(bpy.types.Operator):
                bl_idname = "noisemaker.probe_width"
                bl_label = "Probe Noisemaker Undo"
                bl_options = {'REGISTER', 'UNDO'}
                def execute(self, context):
                    context.scene.noisemaker_instances[0].preview_width = 64
                    return {'FINISHED'}
            copied_id = copied.instance_id
            scene_name = scene.name
            result.update(persistence_success=True, instance_id=created["instance_id"],
                          image_name=created["image_name"], pixel=after,
                          duplicate_id=copied_id, media_pixel=media_after,
                          undo_status="pending")
            before_record = registry.ensure_session(scene, created["instance_id"], 16, 8,
                                                    force_sync=True)
            before_image = registry._produce(before_record)
            assert tuple(before_image.size) == (16, 8)
            before_session = before_record.session
            bpy.context.preferences.edit.use_global_undo = True
            result["global_undo"] = bool(bpy.context.preferences.edit.use_global_undo)
            bpy.utils.register_class(NM_OT_probe_baseline)
            bpy.utils.register_class(NM_OT_probe_width)
            with window_override():
                assert bpy.ops.noisemaker.probe_baseline('EXEC_DEFAULT') == {'FINISHED'}
                assert bpy.ops.noisemaker.probe_width('EXEC_DEFAULT') == {'FINISHED'}
            assert scene.noisemaker_instances[0].preview_width == 64

            def close_undo(error=None):
                if error is not None:
                    result["undo_status"] = "failed"
                    result["error"] = "%s: %s" % (type(error).__name__, error)
                    result["traceback"] = traceback.format_exc()
                for operator_class in (NM_OT_probe_width, NM_OT_probe_baseline):
                    try:
                        bpy.utils.unregister_class(operator_class)
                    except RuntimeError:
                        pass
                finish(result)
                return None

            def restored_output(expected_width):
                current_scene = bpy.data.scenes[scene_name]
                current = next(item for item in current_scene.noisemaker_instances
                               if item.instance_id == created["instance_id"])
                assert current.preview_width == expected_width, \
                    "undo/redo did not restore the live configuration width"
                # Undo handlers invalidate old GPU state. Rebuild on this later
                # timer tick, after Blender has replaced the Scene datablocks.
                registry.tick(tuple(bpy.data.scenes), now=time.monotonic(), allowed=False,
                              window_id=bpy.context.window.as_pointer())
                refreshed = registry.ensure_session(current_scene, current.instance_id,
                                                    expected_width, 8, force_sync=True)
                image = registry._produce(refreshed)
                assert image.is_float and image.get("noisemaker_owner") == current.instance_id
                assert tuple(image.size) == (expected_width, 8), \
                    "rebuilt Image dimensions do not match restored config"
                pixel = read_pixel(image)
                assert max(abs(a - b) for a, b in zip(pixel, created["pixel"])) < 0.01, \
                    "rebuilt output pixels differ from saved keyed parameter"
                return refreshed.session, pixel

            state = {"undo_session": None}

            def verify_after_redo():
                try:
                    redo_session, redo_pixel = restored_output(64)
                    assert state["undo_session"].closed, \
                        "redo did not dispose the post-undo GPU session"
                    assert redo_session is not state["undo_session"], \
                        "redo reused a session from the replaced Scene"
                    result["redo_output"] = {"size": [64, 8], "pixel": redo_pixel,
                                             "rebuilt_session": True}
                    result["undo_status"] = "verified"
                    result["success"] = True
                    return close_undo()
                except Exception as exc:
                    return close_undo(exc)

            def verify_after_undo():
                try:
                    undo_session, undo_pixel = restored_output(16)
                    assert before_session.closed, "undo did not dispose the prior GPU session"
                    assert undo_session is not before_session, \
                        "undo reused a session from the replaced Scene"
                    state["undo_session"] = undo_session
                    result["undo_output"] = {"size": [16, 8], "pixel": undo_pixel,
                                             "rebuilt_session": True}
                    with window_override():
                        result["redo_poll_after_undo"] = bool(bpy.ops.ed.redo.poll())
                        assert result["redo_poll_after_undo"], "redo unavailable after undo"
                        assert bpy.ops.ed.redo('EXEC_DEFAULT') == {'FINISHED'}
                    bpy.app.timers.register(verify_after_redo, first_interval=0.2)
                except Exception as exc:
                    return close_undo(exc)
                return None

            def verify_undo():
                try:
                    with window_override():
                        result["undo_poll_after_edit"] = bool(bpy.ops.ed.undo.poll())
                        assert result["undo_poll_after_edit"], \
                            "undo unavailable after two REGISTER/UNDO operators"
                        assert bpy.ops.ed.undo('EXEC_DEFAULT') == {'FINISHED'}
                    bpy.app.timers.register(verify_after_undo, first_interval=0.2)
                except Exception as exc:
                    return close_undo(exc)
                return None

            deferred = True
            bpy.app.timers.register(verify_undo, first_interval=0.2)
        else:
            raise ValueError("NM_LIVE_PHASE must be create or verify")
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["traceback"] = traceback.format_exc()
    finally:
        if not deferred:
            finish(result)
    return None


bpy.app.timers.register(run, first_interval=0.5)

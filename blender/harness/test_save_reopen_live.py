"""Two-phase GUI persistence probe for live configuration and packed float output.

Set NM_LIVE_PHASE=create, run in an isolated Blender GPU window, then run again
with NM_LIVE_PHASE=verify and the saved blend file as Blender's input file.
Require both phase JSON results to report success=true. Undo is reported as a
separate subcheck because scripted timer contexts may reject its operator poll.
Scratch files go only to NM_EVIDENCE_DIR.
"""
from array import array
import json
import os
from pathlib import Path
import sys
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


def run():
    result = {"success": False, "phase": PHASE, "blender": bpy.app.version_string}
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
            # A timer callback may have no active undo operator context even in
            # a real GUI window; report that admission limit separately.
            class NM_OT_probe_width(bpy.types.Operator):
                bl_idname = "noisemaker.probe_width"
                bl_label = "Probe Noisemaker Undo"
                bl_options = {'UNDO'}
                def execute(self, context):
                    context.scene.noisemaker_instances[0].preview_width = 64
                    return {'FINISHED'}
            copied_id = copied.instance_id
            bpy.utils.register_class(NM_OT_probe_width)
            try:
                area = next(area for area in bpy.context.window.screen.areas
                            if any(region.type == 'WINDOW' for region in area.regions))
                region = next(region for region in area.regions if region.type == 'WINDOW')
                with bpy.context.temp_override(window=bpy.context.window,
                                               screen=bpy.context.window.screen,
                                               area=area, region=region):
                    if bpy.ops.ed.undo.poll():
                        assert bpy.ops.noisemaker.probe_width('EXEC_DEFAULT') == {'FINISHED'}
                        assert scene.noisemaker_instances[0].preview_width == 64
                        assert bpy.ops.ed.undo('EXEC_DEFAULT') == {'FINISHED'}
                        restored = bpy.context.scene.noisemaker_instances[0]
                        assert restored.preview_width == 16, "undo did not restore live config"
                        result["undo_status"] = "verified"
                    else:
                        result["undo_status"] = "unqualified: operator poll rejected timer context"
            finally:
                bpy.utils.unregister_class(NM_OT_probe_width)
            result.update(success=True, instance_id=created["instance_id"],
                          image_name=created["image_name"], pixel=after,
                          duplicate_id=copied_id, media_pixel=media_after)
        else:
            raise ValueError("NM_LIVE_PHASE must be create or verify")
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["traceback"] = traceback.format_exc()
    finally:
        (EVIDENCE / (PHASE + ".json")).write_text(json.dumps(result, indent=2))
        print("NM_LIVE_PERSISTENCE", json.dumps(result), flush=True)
        if ARMED:
            bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=0.5)

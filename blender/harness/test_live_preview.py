"""GUI-only live-loop probe: exact Image updates, source recovery and time modes.

Run in a real Blender GPU window with isolated preferences. Results are written to
NM_EVIDENCE_DIR; an external runner must require result.json success=true.
"""
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
from noisemaker_blender.integration.lifecycle import registry, request_for_scene
from noisemaker_blender.integration.persistence import create_instance
from noisemaker_blender.runtime.clock import map_frame
from noisemaker_blender.runtime.checkpoints import ReplayPending

EVIDENCE = Path(os.environ.get("NM_EVIDENCE_DIR", "/tmp/noisemaker-live-preview"))
EVIDENCE.mkdir(parents=True, exist_ok=True)


def run():
    result = {"success": False, "blender": bpy.app.version_string}
    try:
        assert ARMED, "disposable native probe requires NM_HARNESS_AUTOCLOSE=1 and --factory-startup"
        assert not bpy.app.background and bpy.context.window is not None, "GUI GPU window required"
        if not hasattr(bpy.types.Scene, "noisemaker_instances"):
            register_addon()
        import gpu.platform
        result["gpu"] = {"vendor": gpu.platform.vendor_get(),
                         "renderer": gpu.platform.renderer_get(),
                         "backend": gpu.platform.backend_type_get()}
        scene = bpy.context.scene
        text = bpy.data.texts.new("NM live fixture")
        text.write("search synth\nsolid(color: [0.25, 0.5, 0.75, 1]).write(o0)\nrender(o0)\n")
        config = create_instance(scene, "", "NM live fixture")
        config.source_mode = 'TEXT'
        config.text = text
        config.preview_width = 32
        config.preview_height = 16
        config.live_enabled = True
        record = registry.ensure_session(scene, config.instance_id, 32, 16, force_sync=True)
        assert tuple(config["nm:solid#0.color"]) == (0.25, 0.5, 0.75, 1), "compiled DSL color not seeded"
        image = registry._produce(record)
        assert image is config.output_image and image.is_float
        assert tuple(image.size) == (32, 16)
        assert image.alpha_mode == 'PREMUL'
        generation = record.session.generation
        registry._produce(record)
        assert record.session.generation == generation, "redraw advanced the same frame"
        text.clear()
        text.write("invalid(")
        try:
            registry._produce(record)
        except Exception:
            pass
        else:
            raise AssertionError("invalid DSL unexpectedly evaluated")
        assert config.output_image is image, "source error replaced last valid Image"
        text.clear()
        text.write("search synth\nsolid(color: [0.5, 0.25, 0.75, 1]).write(o0)\nrender(o0)\n")
        recovered = registry._produce(record)
        assert recovered is image, "valid source recovery changed owned Image identity"
        config.time_mode = 'free_run'
        preview = request_for_scene(scene, config, purpose='preview', free_run_elapsed=0.5)
        final = request_for_scene(scene, config, purpose='final')
        assert preview.mode == 'free_run' and map_frame(preview).elapsed_seconds == 0.5
        assert final.mode == 'timeline' and final.frame == scene.frame_current
        other_scene = bpy.data.scenes.new("NM inactive scene probe")
        other = create_instance(other_scene,
            "search synth\nsolid(color: [0.9, 0.1, 0.2, 1]).write(o0)\nrender(o0)\n",
            "NM other scene")
        other.preview_width = 16
        other.preview_height = 8
        other.live_enabled = True
        other_record = registry.ensure_session(other_scene, other.instance_id, 16, 8,
                                               force_sync=True)
        other_image = registry._produce(other_record)
        other_pixel = tuple(other_image.pixels[:4])
        assert bpy.context.scene == scene, "two-scene probe changed active editor scene"
        assert other_pixel[0] > 0.8 and other_pixel[1] < 0.2, \
            "inactive scene did not use its own evaluated instance properties"
        result["inactive_scene_pixel"] = other_pixel

        producer = create_instance(scene,
            "search synth\nsolid(color: [0.8, 0.2, 0.1, 1]).write(o0)\nrender(o0)\n",
            "NM upstream")
        consumer = create_instance(scene,
            "search synth\nmedia().write(o0)\nrender(o0)\n",
            "NM downstream")
        for dependent in (producer, consumer):
            dependent.live_enabled = True
            dependent.preview_width = dependent.render_width = 16
            dependent.preview_height = dependent.render_height = 8
        config.render_width, config.render_height = 16, 8
        upstream = registry.ensure_session(scene, producer.instance_id, 16, 8,
                                           force_sync=True)
        registry._produce(upstream)
        registry.bind_input(scene, consumer.instance_id, "imageTex_step_0",
                            image=producer.output_image)
        ordered = [entry.config.instance_id for entry in registry.instances_for_scene(scene)]
        assert ordered.index(producer.instance_id) < ordered.index(consumer.instance_id), \
            "owned Image dependency did not order instances"
        downstream = registry.ensure_session(scene, consumer.instance_id, 16, 8,
                                             force_sync=True)
        registry._produce(downstream)
        live_pixel = tuple(consumer.output_image.pixels[:4])
        assert live_pixel[0] > 0.7 and live_pixel[1] < 0.3, \
            "live owned Image consumer did not receive upstream pixels"
        registry.set_parameter(scene, producer.instance_id, "solid#0.color",
                               (0.1, 0.7, 0.2, 1))
        registry._produce(upstream)
        registry._produce(downstream)
        updated_pixel = tuple(consumer.output_image.pixels[:4])
        assert updated_pixel[0] < 0.2 and updated_pixel[1] > 0.6, \
            "owned Image pixel change did not invalidate downstream input"
        from noisemaker_blender.integration.render import _evaluate
        _evaluate(scene, registry)
        scripted_pixel = tuple(consumer.output_image.pixels[:4])
        assert scripted_pixel[0] < 0.2 and scripted_pixel[1] > 0.6, \
            "scripted final consumer did not receive freshly prepared upstream pixels"
        result["owned_dependency"] = {"order": ordered,
                                      "live_pixel": live_pixel,
                                      "updated_pixel": updated_pixel,
                                      "scripted_pixel": scripted_pixel}
        reaction = create_instance(scene,
            "search synth\nreactionDiffusion().write(o0)\nrender(o0)\n",
            "NM bounded replay")
        reaction.preview_width = reaction.preview_height = 16
        reaction_record = registry.get(scene, reaction.instance_id)
        scene.frame_set(8)
        timeline_pending = 0
        for _ in range(50):
            try:
                timeline_image = registry._produce(reaction_record)
                break
            except ReplayPending:
                timeline_pending += 1
                assert reaction.output_image is None, "pending replay published an incomplete frame"
        else:
            raise AssertionError("bounded timeline replay never completed")
        assert timeline_pending > 0 and timeline_image is reaction.output_image
        reaction.time_mode = 'free_run'
        reaction_record.free_run_started = time.monotonic() - 0.5
        free_run_pending = 0
        for _ in range(50):
            try:
                free_run_image = registry._produce(reaction_record)
                break
            except ReplayPending:
                free_run_pending += 1
                assert reaction.output_image is timeline_image, \
                    "pending free-run replay replaced the last completed Image"
        else:
            raise AssertionError("bounded free-run replay never completed")
        assert free_run_pending > 0 and free_run_image is timeline_image
        result["bounded_replay"] = {"timeline_pending_ticks": timeline_pending,
                                    "free_run_pending_ticks": free_run_pending,
                                    "generation": reaction_record.session.generation}
        scene.frame_set(1)
        result.update(success=True, instance_id=config.instance_id,
                      generation=record.session.generation,
                      image=image.name, size=list(image.size),
                      last_error=config.last_error)
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["traceback"] = traceback.format_exc()
    finally:
        (EVIDENCE / "result.json").write_text(json.dumps(result, indent=2))
        print("NM_LIVE_PREVIEW", json.dumps(result), flush=True)
        if ARMED:
            bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=0.5)

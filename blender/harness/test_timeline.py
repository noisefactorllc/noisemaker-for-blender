"""Guarded GUI proof for frozen keyed parameter snapshots and stateful seeks."""

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import numpy as np

ARMED = os.environ.get("NM_HARNESS_AUTOCLOSE") == "1" and "--factory-startup" in sys.argv
if not ARMED:
    raise RuntimeError("run only in a disposable --factory-startup process")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(os.environ["NM_EVIDENCE_DIR"]).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


def run():
    result = {"passed": False, "checks": []}
    try:
        assert not bpy.app.background and bpy.context.window is not None
        from noisemaker_blender import api, register as register_addon
        from noisemaker_blender.integration.parameters import BlenderPropertyAdapter
        if not hasattr(bpy.types.Scene, "noisemaker_instances"):
            register_addon()
        scene = bpy.context.scene
        scene.render.fps = 30000
        scene.render.fps_base = 1001
        source = "search synth\nreactionDiffusion().write(o0)\nrender(o0)"
        instance = api.create_instance(scene, api.compile(source), name="Keyed simulation")
        key = "reactionDiffusion#0.feed"
        prop = BlenderPropertyAdapter.property_name(key)
        instance[prop] = 70.0
        assert instance.keyframe_insert(data_path='["%s"]' % prop, frame=1)
        instance[prop] = 90.0
        assert instance.keyframe_insert(data_path='["%s"]' % prop, frame=5)
        scene.frame_set(7, subframe=.25)
        original = (scene.frame_current, scene.frame_subframe)
        target = api.FrameRequest(frame=20, fps=30000, fps_base=1001)
        try:
            api.prepare_parameter_snapshots(instance, target, max_steps=10)
            raise AssertionError("oversized snapshot admitted")
        except ValueError as error:
            assert "max_steps" in str(error)
        assert (scene.frame_current, scene.frame_subframe) == original
        try:
            api.open_session(instance, size=32)
            raise AssertionError("live animated stateful instance admitted")
        except ValueError as error:
            assert "animated parameters" in str(error)
        prepared = api.prepare_parameter_snapshots(instance, target, max_steps=64)
        assert (scene.frame_current, scene.frame_subframe) == original
        def request(frame):
            return api.FrameRequest(frame=frame, fps=30000, fps_base=1001)
        first = prepared.resolve(request(1))[0][key]
        fifth = prepared.resolve(request(5))[0][key]
        assert abs(first - 70.0) < 1e-5 and abs(fifth - 90.0) < 1e-5
        result["checks"].append("evaluated_keyframes_capture_and_scene_restore")
        with api.open_session(prepared, size=32) as sequential:
            for frame in range(1, 21):
                output = sequential.evaluate(request(frame))
                if frame == 5:
                    fifth_pixels = sequential.read_float(output).copy()
            twentieth_pixels = sequential.read_float(output).copy()
        with api.open_session(prepared, size=32) as seek:
            seek.evaluate(request(1))
            output = seek.evaluate(request(20))
            np.testing.assert_array_equal(seek.read_float(output), twentieth_pixels)
            output = seek.evaluate(request(5))
            np.testing.assert_array_equal(seek.read_float(output), fifth_pixels)
            output = seek.evaluate(request(20))
            np.testing.assert_array_equal(seek.read_float(output), twentieth_pixels)
            assert seek.evaluate(request(20)).generation == output.generation
        constant = api.PreparedParameterSnapshots(
            prepared.program, prepared.policy, prepared.animated_keys,
            prepared.static_values, tuple(((key, first),) for _ in prepared.steps))
        with api.open_session(constant, size=32) as control:
            control_pixels = control.read_float(control.evaluate(request(20))).copy()
        difference = float(np.max(np.abs(twentieth_pixels - control_pixels)))
        assert difference > 1e-5, "keyed feed history did not affect rendered pixels"
        result["checks"].append("sequential_equals_seek_1_20_5_20_fractional_fps")
        result.update(passed=True, feed_first=first, feed_fifth=fifth,
                      snapshot_source=prepared.source_identity(),
                      history_pixel_difference=difference,
                      twentieth_sha256=hashlib.sha256(twentieth_pixels.tobytes()).hexdigest())
    except Exception as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
        print(result["traceback"], flush=True)
    finally:
        (EVIDENCE / "timeline.json").write_text(json.dumps(result, indent=2) + "\n")
        print("NM_TIMELINE", json.dumps(result), flush=True)
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(run, first_interval=.5)

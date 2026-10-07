"""Disposable 60-second GUI timer/Text Editor/Image Editor live acceptance probe.

Run with --factory-startup, NM_HARNESS_AUTOCLOSE=1, and NM_EVIDENCE_DIR. This
uses the add-on's registered timer only; it never invokes registry._produce.
"""
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback

import bpy

ARMED = os.environ.get("NM_HARNESS_AUTOCLOSE") == "1" and "--factory-startup" in sys.argv
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender"))
from noisemaker_blender import register as register_addon
from noisemaker_blender.integration.lifecycle import registry
from noisemaker_blender.integration.persistence import create_instance

EVIDENCE = Path(os.environ.get("NM_EVIDENCE_DIR", "/tmp/noisemaker-live-interactive"))
STATIC = "search synth\nsolid(color: [0.25, 0.5, 0.75, 1]).write(o0)\nrender(o0)\n"
MULTIPASS = "search synth, filter\nnoise(seed: 1, scaleX: 50, scaleY: 50).bloom().write(o0)\nrender(o0)\n"
state = {"phase": "setup", "edits": [], "draw_generations": {}, "draw_count": 0,
         "source_edits": 0, "static_latency": [], "multipass_latency": []}
handler = None


def p95(values):
    values = sorted(values)
    return values[min(len(values) - 1, (95 * len(values) + 99) // 100 - 1)] if values else None


def metrics(record):
    backend = record.session.backend if record.session else None
    if backend is None:
        return {}
    return dict(getattr(backend, "metrics", {}),
                surface_count=len(getattr(backend, "surfaces", {})),
                pool_count=len(getattr(backend, "pool", {})))


def draw():
    state["draw_count"] += 1
    config = state.get("config")
    image = config.output_image if config is not None else None
    if image is not None:
        generation = image.get("noisemaker_generation")
        if generation is not None:
            state["draw_generations"].setdefault(str(generation), time.monotonic())


def text_replace(source):
    area = state["text_area"]
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=bpy.context.window,
                                   screen=bpy.context.window.screen,
                                   area=area, region=region):
        assert bpy.ops.text.select_all('EXEC_DEFAULT') == {'FINISHED'}
        assert bpy.ops.text.insert('EXEC_DEFAULT', text=source) == {'FINISHED'}
    assert state["text"].as_string() == source, "Text Editor operator did not replace DSL"
    state["source_edits"] += 1


def queue_parameter(key, value, latency_name):
    config = state["config"]
    record = registry.get(state["scene"], config.instance_id)
    before = record.session.generation
    registry.set_parameter(state["scene"], config.instance_id, key, value)
    state["pending"] = {"target": before + 1, "started": time.monotonic(),
                        "latency_name": latency_name, "key": key}
    state["edits"].append({"key": key, "value": value, "target": before + 1})


def finish(success, error=None):
    global handler
    if state.get("finished"):
        return None
    state["finished"] = True
    if handler is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(handler, 'WINDOW')
        handler = None
    now = time.monotonic()
    record = registry.get(state["scene"], state["config"].instance_id) if state.get("config") else None
    draws = state["draw_generations"]
    for edit in state["edits"]:
        first = draws.get(str(edit["target"]))
        edit["presented"] = first is not None
    fps_start = state.get("fps_start", now)
    fps_generations = [generation for generation, when in draws.items() if when >= fps_start]
    result = {
        "success": bool(success), "error": error, "blender": bpy.app.version_string,
        "duration_seconds": now - state.get("started", now),
        "phase": state["phase"], "source_edits_via_text_operator": state["source_edits"],
        "draw_callbacks": state["draw_count"], "distinct_presented_generations": len(draws),
        "static_publish_latency_p95_ms": p95(state["static_latency"]),
        "multipass_publish_latency_p95_ms": p95(state["multipass_latency"]),
        "static_samples": len(state["static_latency"]),
        "multipass_samples": len(state["multipass_latency"]),
        "free_run_presented_fps": len(fps_generations) / max(0.001, now - fps_start),
        "static_metrics_before": state.get("static_metrics_before"),
        "static_metrics_after": state.get("static_metrics_after"),
        "multipass_metrics_before": state.get("multipass_metrics_before"),
        "multipass_metrics_after": state.get("multipass_metrics_after"),
        "last_error": state["config"].last_error if state.get("config") else "",
        "edits": state["edits"],
        "session_generation": record.session.generation if record and record.session else None,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "interactive.json").write_text(json.dumps(result, indent=2))
    print("NM_LIVE_INTERACTIVE", json.dumps(result), flush=True)
    if ARMED:
        bpy.ops.wm.quit_blender()
    return None


def poll():
    try:
        now = time.monotonic()
        elapsed = now - state["started"]
        config = state["config"]
        record = registry.get(state["scene"], config.instance_id)
        image = config.output_image
        if image is not None and state["image_area"].spaces.active.image is not image:
            state["image_area"].spaces.active.image = image
            state["image_area"].tag_redraw()
        pending = state.get("pending")
        if pending is not None and image is not None:
            generation = image.get("noisemaker_generation", -1)
            if generation >= pending["target"]:
                state[pending["latency_name"]].append((now - pending["started"]) * 1000)
                state["pending"] = None
        phase = state["phase"]
        if phase == "await_static" and image is not None:
            state["static_metrics_before"] = metrics(record)
            state["phase"] = "static"
            state["next_edit"] = now
            state["static_count"] = 0
        elif phase == "static":
            if state["static_count"] < 8 and state.get("pending") is None and now >= state["next_edit"]:
                index = state["static_count"]
                queue_parameter("solid#0.color", (0.2 + index * 0.05, 0.4, 0.6, 1),
                                "static_latency")
                state["static_count"] += 1
                state["next_edit"] = now + 0.55
            if state["static_count"] >= 8 and state.get("pending") is None:
                state["static_metrics_after"] = metrics(record)
                text_replace(MULTIPASS)
                state["phase"] = "await_multipass"
                state["source_generation"] = record.session.generation
        elif phase == "await_multipass":
            if record.session and record.session.generation > state["source_generation"]:
                state["multipass_metrics_before"] = metrics(record)
                state["phase"] = "multipass"
                state["next_edit"] = now
                state["multipass_count"] = 0
        elif phase == "multipass":
            if state["multipass_count"] < 8 and state.get("pending") is None and now >= state["next_edit"]:
                index = state["multipass_count"]
                queue_parameter("noise#0.seed", index + 2, "multipass_latency")
                state["multipass_count"] += 1
                state["next_edit"] = now + 0.65
            if state["multipass_count"] >= 8 and state.get("pending") is None:
                state["multipass_metrics_after"] = metrics(record)
                state["last_good_image"] = image
                text_replace("invalid(")
                state["phase"] = "await_invalid"
        elif phase == "await_invalid":
            if config.last_error:
                assert config.output_image is state["last_good_image"]
                text_replace(MULTIPASS)
                state["phase"] = "await_recovery"
        elif phase == "await_recovery":
            if not config.last_error and record.session and image is not None:
                config.paused = True
                state["paused_generation"] = record.session.generation
                registry.set_parameter(state["scene"], config.instance_id,
                                       "noise#0.seed", 20)
                state["pause_started"] = now
                state["phase"] = "paused"
        elif phase == "paused" and now - state["pause_started"] >= 2.0:
            assert record.session.generation == state["paused_generation"], "Pause allowed GPU generation"
            config.paused = False
            state["phase"] = "await_resume"
        elif phase == "await_resume":
            if record.session.generation > state["paused_generation"]:
                config.time_mode = 'free_run'
                state["fps_start"] = now
                state["phase"] = "free_run"
        if elapsed >= 60:
            assert state["phase"] == "free_run", "60-second probe did not complete stages"
            assert state["draw_count"] > 0 and len(state["draw_generations"]) >= 4, \
                "Image Editor did not present distinct generations"
            assert len(state["static_latency"]) >= 5 and len(state["multipass_latency"]) >= 5
            assert state["source_edits"] >= 3
            for before_key, after_key in (("static_metrics_before", "static_metrics_after"),
                                          ("multipass_metrics_before", "multipass_metrics_after")):
                before, after = state[before_key], state[after_key]
                assert after["shader_compiles"] == before["shader_compiles"], "warm shader compile"
                assert after["shader_file_reads"] == before["shader_file_reads"], "warm shader file read"
                assert after["surface_count"] == before["surface_count"], "surface growth"
                assert after["pool_count"] == before["pool_count"], "pool growth"
            return finish(True)
        return 0.02
    except Exception:
        return finish(False, traceback.format_exc())


def setup():
    global handler
    try:
        assert ARMED, "requires NM_HARNESS_AUTOCLOSE=1 and --factory-startup"
        assert not bpy.app.background and bpy.context.window is not None
        if not hasattr(bpy.types.Scene, "noisemaker_instances"):
            register_addon()
        areas = sorted((area for area in bpy.context.window.screen.areas
                        if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR', 'PROPERTIES', 'OUTLINER'}),
                       key=lambda area: area.width * area.height, reverse=True)
        assert len(areas) >= 2, "two editable UI areas required"
        text_area, image_area = areas[:2]
        text_area.type = 'TEXT_EDITOR'
        image_area.type = 'IMAGE_EDITOR'
        scene = bpy.context.scene
        text = bpy.data.texts.new("NM interactive source")
        text.write(STATIC)
        text_area.spaces.active.text = text
        config = create_instance(scene, "", "NM interactive")
        config.source_mode = 'TEXT'
        config.text = text
        config.preview_width = 512
        config.preview_height = 512
        config.live_enabled = True
        state.update(started=time.monotonic(), phase="await_static", scene=scene,
                     text=text, config=config, text_area=text_area, image_area=image_area)
        handler = bpy.types.SpaceImageEditor.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
        bpy.app.timers.register(poll, first_interval=0.05)
    except Exception:
        state["started"] = time.monotonic()
        finish(False, traceback.format_exc())
    return None


bpy.app.timers.register(setup, first_interval=1.0)

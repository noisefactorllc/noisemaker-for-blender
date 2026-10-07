"""Compile every packaged effect program with its declared default variants."""
import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import gpu

if "--factory-startup" not in sys.argv or os.environ.get("NM_HARNESS_AUTOCLOSE") != "1":
    raise RuntimeError("catalog gate requires a disposable --factory-startup Blender process")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from noisemaker_blender.backend.gpu_backend import GpuBackend

EVIDENCE = Path(os.environ["NM_EVIDENCE_DIR"]).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)
KNOWN_UNSUPPORTED = {
    "synth/scope/scope.createinfo.json",
    "synth/spectrum/spectrum.createinfo.json",
}


def _declared_variants(shaders, namespace, effect, program):
    effect_file = shaders.parents[1] / "effects" / namespace / (effect + ".json")
    if not effect_file.is_file():
        return [{}]
    descriptor = json.loads(effect_file.read_text())
    defaults = {
        spec["define"]: int(spec["default"]) if isinstance(spec["default"], bool) else spec["default"]
        for spec in descriptor.get("globals", {}).values()
        if "define" in spec
    }
    variants = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("program") == program:
                variants.append({**defaults, **value.get("defines", {})})
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(descriptor.get("passes", []))
    unique = {}
    for variant in variants or [defaults]:
        unique[tuple(sorted(variant.items()))] = variant
    return list(unique.values())


def run():
    shaders = Path(__file__).resolve().parents[1] / "noisemaker_blender" / "shaders" / "effects"
    files = sorted(shaders.rglob("*.createinfo.json"))
    result = {"status": "failed", "blender": bpy.app.version_string,
              "build_hash": str(bpy.app.build_hash),
              "gpu": {"backend": gpu.platform.backend_type_get(),
                      "vendor": gpu.platform.vendor_get(),
                      "renderer": gpu.platform.renderer_get()},
              "expected": len(files), "executed": [], "compiled": [],
              "compiled_variants": 0, "known_unsupported": [], "unexpected_failures": []}
    backend = None
    try:
        assert not bpy.app.background and bpy.context.window is not None
        backend = GpuBackend(str(shaders), size=32)
        for path in files:
            namespace, effect, filename = path.relative_to(shaders).parts
            program = filename.removesuffix(".createinfo.json")
            name = str(path.relative_to(shaders))
            result["executed"].append(name)
            for defines in _declared_variants(shaders, namespace, effect, program):
                try:
                    backend.compile(namespace, effect, program, defines)
                    result["compiled_variants"] += 1
                    if name not in result["compiled"]:
                        result["compiled"].append(name)
                except Exception as exc:
                    failure = {"shader": name, "defines": defines,
                               "error": repr(exc), "traceback": traceback.format_exc()}
                    field = "known_unsupported" if name in KNOWN_UNSUPPORTED else "unexpected_failures"
                    result[field].append(failure)
        assert len(files) == 309, "packaged shader denominator changed"
        assert len(result["executed"]) == len(files)
        assert not result["unexpected_failures"], "%d unexpected shader compile failures" % len(result["unexpected_failures"])
        assert {entry["shader"] for entry in result["known_unsupported"]} == KNOWN_UNSUPPORTED
        result["status"] = "qualified_with_known_unsupported"
    except Exception as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        if backend is not None:
            backend.free()
        (EVIDENCE / "shader_catalog.json").write_text(json.dumps(result, indent=2) + "\n")
        print("NATIVE SHADER CATALOG", result["status"], len(result["executed"]),
              "executed;", len(result["compiled"]), "compiled;",
              len(result["known_unsupported"]), "known unsupported;",
              len(result["unexpected_failures"]), "unexpected failures", flush=True)
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=.5)

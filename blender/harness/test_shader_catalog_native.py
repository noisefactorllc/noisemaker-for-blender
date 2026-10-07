"""Compile every packaged base effect shader in an isolated Blender GPU GUI."""
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


def run():
    shaders = Path(__file__).resolve().parents[1] / "noisemaker_blender" / "shaders" / "effects"
    files = sorted(shaders.rglob("*.createinfo.json"))
    result = {"status": "failed", "blender": bpy.app.version_string,
              "build_hash": str(bpy.app.build_hash),
              "gpu": {"backend": gpu.platform.backend_type_get(),
                      "vendor": gpu.platform.vendor_get(),
                      "renderer": gpu.platform.renderer_get()},
              "expected": len(files), "compiled": [], "failures": []}
    backend = None
    try:
        assert not bpy.app.background and bpy.context.window is not None
        backend = GpuBackend(str(shaders), size=32)
        for path in files:
            namespace, effect, filename = path.relative_to(shaders).parts
            program = filename.removesuffix(".createinfo.json")
            try:
                backend.compile(namespace, effect, program, {})
                result["compiled"].append(str(path.relative_to(shaders)))
            except Exception as exc:
                result["failures"].append({"shader": str(path.relative_to(shaders)),
                                           "error": repr(exc),
                                           "traceback": traceback.format_exc()})
        assert len(files) == 309, "packaged shader denominator changed"
        assert not result["failures"], "%d shader compile failures" % len(result["failures"])
        assert len(result["compiled"]) == len(files)
        result["status"] = "passed"
    except Exception as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        if backend is not None:
            backend.free()
        (EVIDENCE / "shader_catalog.json").write_text(json.dumps(result, indent=2) + "\n")
        print("NATIVE SHADER CATALOG", result["status"], len(result["compiled"]),
              "of", result["expected"], flush=True)
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=.5)

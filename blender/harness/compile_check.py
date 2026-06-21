"""Compile-check every transpiled shader via create_from_info on Metal.

Reports the true Metal compile-coverage of the transpiler output and surfaces
any MSL incompatibilities. GUI mode (GPU needs a context); self-quits.

Usage: blender --factory-startup --python blender/harness/compile_check.py
"""
import os
import sys
import json
import glob
import traceback

import bpy

HARNESS = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HARNESS), "noisemaker_blender")
SHADERS = os.path.join(ADDON, "shaders", "effects")
sys.path.insert(0, os.path.dirname(ADDON))
from noisemaker_blender.backend import shader_build  # noqa: E402


def run():
    only = os.environ.get("NM_ONLY")
    ok, fail, skip = [], [], []
    for ci in sorted(glob.glob(os.path.join(SHADERS, "**", "*.createinfo.json"), recursive=True)):
        rel = os.path.relpath(ci, SHADERS)[:-len(".createinfo.json")]
        if only and rel != only:
            continue
        desc = json.load(open(ci))
        frag = open(ci[:-len(".createinfo.json")] + ".frag").read()
        # skip the staged classes (UBO overflow, MRT, no-out, varyings) — not P1.
        notes = " ".join(desc.get("notes", []))
        if desc.get("ubo") or len(desc.get("fragmentOut", [])) != 1 or "VARYING" in notes or "NO_OUT" in notes:
            skip.append(rel)
            continue
        try:
            shader_build.build_shader(frag, desc)
            ok.append(rel)
        except Exception as e:
            fail.append((rel, str(e).splitlines()[0] if str(e) else repr(e)))

    print("NMCC ===== compile-check =====")
    print("NMCC ok=%d fail=%d skip(staged)=%d total=%d"
          % (len(ok), len(fail), len(skip), len(ok) + len(fail) + len(skip)))
    for rel, err in fail:
        print("NMCC FAIL", rel, "::", err)
    sys.stdout.flush()


if bpy.app.background:
    run()
else:
    def _t():
        try:
            run()
        except Exception:
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.5)

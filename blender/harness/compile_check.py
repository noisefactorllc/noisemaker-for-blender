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
EFFECTS = os.path.join(ADDON, "effects")
sys.path.insert(0, os.path.dirname(ADDON))
from noisemaker_blender.backend import shader_build  # noqa: E402


def default_defines(rel):
    """The compile-time #defines a pass would normally inject, at the effect's DEFAULT values —
    so define-gated shaders (render3d's INVERT/FILTERING, noise3d's OCTAVES/RIDGES/COLOR_MODE)
    compile standalone exactly as they do in-pipeline (the graph supplies these per-pass). Read
    from the effect definition's `define`-marked globals; bool -> 0/1 for GLSL.

    Newer effects (pointsRender/pointsBillboardRender's viewMode-split deposit draws) instead
    carry per-pass `defines` blocks keyed by `program` (one pass per shader-variant, e.g.
    deposit_0/deposit_1/deposit_2 all with `program: deposit`), with no single effect-level
    global default to read. Falls back to the first such pass's defines — enough to compile the
    file under one real, valid combination; the render harness exercises the other variants."""
    parts = rel.split("/")
    if len(parts) < 2:
        return {}
    ej = os.path.join(EFFECTS, parts[0], parts[1] + ".json")
    if not os.path.exists(ej):
        return {}
    data = json.load(open(ej))
    out = {}
    for g in data.get("globals", {}).values():
        if isinstance(g, dict) and "define" in g:
            v = g.get("default", 0)
            out[g["define"]] = int(v) if isinstance(v, bool) else v
    if out:
        return out
    program = parts[-1]
    for p in data.get("passes", []):
        if p.get("program") == program and p.get("defines"):
            return dict(p["defines"])
    return out


def run():
    only = os.environ.get("NM_ONLY")
    ok, fail, skip = [], [], []
    for ci in sorted(glob.glob(os.path.join(SHADERS, "**", "*.createinfo.json"), recursive=True)):
        rel = os.path.relpath(ci, SHADERS)[:-len(".createinfo.json")]
        if only and rel != only:
            continue
        desc = json.load(open(ci))
        base = ci[:-len(".createinfo.json")]
        frag = open(base + ".frag").read()
        # A render shader needs a fragment output. The only genuinely-unbuildable class is NO_OUT
        # (gl_FragColor-style / no `out`); everything else compiles via the matching path:
        #   - vertex:true  -> build_shader_vf (its own VS + varying interface): deposit/3D render
        #   - MRT (>1 out) -> build_shader (create_from_info takes multiple fragment_out): agents/3D
        notes = " ".join(desc.get("notes", []))
        if len(desc.get("fragmentOut", [])) == 0 or "NO_OUT" in notes:
            skip.append(rel)
            continue
        defines = default_defines(rel)
        try:
            if desc.get("vertex"):
                vert = open(base + ".vert").read()
                shader_build.build_shader_vf(vert, frag, desc, defines)
            else:
                shader_build.build_shader(frag, desc, defines)
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

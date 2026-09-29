"""Dump intermediate textures of a rendered DSL graph as raw float32.

Companion to dump_atlas.py for same-GPU texel diffing against the reference
engine (parity/golden-cdp-dump.mjs): after the warm render it readbacks each
requested texture as raw RGBA float32 (top-down rows) and writes
<path>.f32 plus a <path>.dump.json manifest {texId: width, height, sha256}.

NM_GRAPH, NM_FRAMES, NM_OUT (path prefix), NM_DUMP_TEX (comma-separated ids;
"surface:<name>" for global surfaces, plain id for node textures, "final" for
the render surface), NM_GOLDEN_SIZE/NM_GOLDEN_TIME/NM_TIMESTEP optional.
"""
import hashlib
import json
import os
import struct
import sys
import traceback

import bpy
import gpu
import numpy as np

HARNESS = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HARNESS), "noisemaker_blender")
sys.path.insert(0, os.path.dirname(ADDON))
from noisemaker_blender.backend.gpu_backend import GpuBackend          # noqa: E402
from noisemaker_blender.runtime import graph_loader, pipeline          # noqa: E402


def read_float(tex):
    """Raw RGBA float32 readback of a GPUTexture, top-down."""
    w, h = tex.width, tex.height
    with tex.bind():
        buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
    buf.dimensions = w * h * 4
    a = np.array(buf, dtype=np.float32).reshape(h, w, 4)
    return a[::-1]  # Blender framebuffer origin is bottom-left; flip to top-down


def main():
    graph = graph_loader.load(os.environ["NM_GRAPH"])
    frames = int(os.environ.get("NM_FRAMES", "8"))
    size = int(os.environ.get("NM_GOLDEN_SIZE", "256"))
    time_t = float(os.environ.get("NM_GOLDEN_TIME", "0.25"))
    timestep = float(os.environ.get("NM_TIMESTEP", "0"))
    out_prefix = os.environ["NM_OUT"]
    wanted = os.environ.get("NM_DUMP_TEX", "surface:o1,surface:o2,final").split(",")

    be = GpuBackend(os.path.join(ADDON, "shaders", "effects"), size)
    defaults = pipeline.collect_default_uniforms(graph)
    capture = os.environ.get("NM_CAPTURE_PASS")
    if capture:
        orig = be._render
        cap = {"log": []}

        def wrap(compiled, merged, inputs, p, graph):
            if p.get("id") == capture:
                cap["log"] = [{"merged": {k: (v if isinstance(v, (int, float, str, list, tuple)) else str(v)) for k, v in merged.items()}, "inputs": dict(inputs)}]
            return orig(compiled, merged, inputs, p, graph)

        be._render = wrap
    pipeline.render(be, graph, time=time_t, frames=frames, timestep=timestep)

    if os.environ.get("NM_DUMP_UNIFORMS"):
        import json as _json
        dumped = {}
        for p in graph.passes:
            try:
                u = p.uniforms if hasattr(p, 'uniforms') else p.get('uniforms')
            except Exception:
                u = None
            dumped[p.id if hasattr(p, 'id') else p.get('id')] = {k: (v if isinstance(v, (int, float, str, list, tuple)) else str(v)) for k, v in (u or {}).items()} if u else None
        print("UNIFORMS", _json.dumps(dumped))

    manifest = {}
    for spec in wanted:
        spec = spec.strip()
        if spec == "final":
            tex = be.surfaces[graph.render_surface].read
        elif spec.startswith("surface:"):
            tex = be.surfaces[spec[8:]].read
        else:
            ids = [t for t in graph.textures if t.startswith("node_")] if spec == "node:*" else [spec]
            for tid in ids:
                try:
                    tex = be.pool[be.pool_key[tid]]
                except (KeyError, AttributeError):
                    print("DUMPMISS", tid)
                    continue
                a = read_float(tex)
                raw = a.astype("<f4").tobytes()
                path = f"{out_prefix}.{tid}.f32"
                with open(path, "wb") as f:
                    f.write(raw)
                manifest[tid] = {"width": int(tex.width), "height": int(tex.height),
                                 "bytes": len(raw),
                                 "sha256": hashlib.sha256(raw).hexdigest()}
            continue
        a = read_float(tex)
        raw = a.astype("<f4").tobytes()
        path = f"{out_prefix}.{spec.replace(':', '_')}.f32"
        with open(path, "wb") as f:
            f.write(raw)
        manifest[spec] = {"width": int(tex.width), "height": int(tex.height),
                          "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest()}
    with open(out_prefix + ".dump.json", "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print("DUMP", json.dumps(manifest))
    if capture:
        print("CAPTURE", json.dumps(cap["log"]))
    be.free()


if bpy.app.background:
    main()
else:
    def _t():
        try:
            main()
        except Exception:
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.5)
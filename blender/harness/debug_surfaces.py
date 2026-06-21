"""Diagnostic harness — render a graph and dump RAW float stats for named surfaces at
sample frames, to bisect where a multi-pass chain goes bad (agent state vs deposit vs
solver). Unlike render_all (which clips/quantizes to uint8), this reads raw floats so
positions/velocities/typeIds/forceMatrix are visible.

Driven by env:
  NM_GRAPH        graph.json path
  NM_FRAMES       frames to evolve (default 120)
  NM_TIME         start time (default 0.25)
  NM_TIMESTEP     evolution step (default 0.0016667)
  NM_SAMPLE_EVERY sample stride (default 30)
  NM_SURFACES     comma list of texture ids to inspect (global_* or pool ids)

Usage: NM_GRAPH=... blender --factory-startup --python blender/harness/debug_surfaces.py
"""
import os
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


def raw_read(off):
    w, h = off.width, off.height
    with off.bind():
        buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
    buf.dimensions = w * h * 4
    return np.array(buf, dtype=np.float32).reshape(h, w, 4)


def resolve_off(be, graph, tid):
    """Return the current READ offscreen for a texture id (global_* surface or pool)."""
    if tid.startswith("global_"):
        name = tid[len("global_"):]
        s = be.surfaces.get(name)
        return s.read if s else None
    try:
        return be.pool.get(graph.phys(tid))
    except Exception:
        return None


def stat(arr):
    flat = arr.reshape(-1, 4)
    nan = int(np.isnan(flat).sum())
    return ("min=%s max=%s mean=%s nan=%d"
            % (flat.min(0).round(4).tolist(), flat.max(0).round(4).tolist(),
               flat.mean(0).round(4).tolist(), nan))


def run():
    graph = graph_loader.load(os.environ["NM_GRAPH"])
    size = int(os.environ.get("NM_SIZE", "256"))
    frames = int(os.environ.get("NM_FRAMES", "120"))
    time = float(os.environ.get("NM_TIME", "0.25"))
    timestep = float(os.environ.get("NM_TIMESTEP", "0.0016667"))
    every = int(os.environ.get("NM_SAMPLE_EVERY", "30"))
    surfs = [s for s in os.environ.get("NM_SURFACES", "").split(",") if s]
    shaders_root = os.path.join(ADDON, "shaders", "effects")
    be = GpuBackend(shaders_root, size)

    defaults = pipeline.collect_default_uniforms(graph)
    be.setup(graph, defaults)
    prev_tt = None
    for f in range(frames):
        tt = (time + f * timestep) % 1.0 if timestep else time
        dt = 0.0 if prev_tt is None else (tt - prev_tt)
        prev_tt = tt
        engine = pipeline.default_engine(be.size, tt, f, dt)
        lookup = dict(engine); lookup.update(defaults)
        be.frame_begin()
        for p in graph.passes:
            if pipeline.should_skip(p, lookup):
                continue
            count = pipeline.resolve_repeat_count(p, lookup)
            for _ in range(count):
                be.execute(p, graph, engine)
                for tid in p.get("outputs", {}).values():
                    be.swap_after_write(tid)
        be.frame_persist()
        if (f + 1) % every == 0 or f == frames - 1:
            print("=== frame %d (tt=%.4f) ===" % (f + 1, tt))
            for tid in surfs:
                off = resolve_off(be, graph, tid)
                if off is None:
                    print("  %-32s <missing>" % tid)
                    continue
                arr = raw_read(off)
                extra = ""
                if "xyz" in tid:  # alive flag in .w
                    alive = float((arr[..., 3] >= 0.5).mean())
                    extra = " alive=%.3f" % alive
                print("  %-32s %s%s" % (tid, stat(arr), extra))
            sys.stdout.flush()
    be.free()


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

"""Candidate render harness — runs noisemaker graph.json files through the GpuBackend
and writes candidate PNGs. GUI mode (macOS GPU needs a context); self-quits.

Driven by env:
  NM_JOBS   JSON list of {"graph": <path>, "out": <path>}
  NM_SIZE   render size (default 256)
  NM_TIME   normalized time (default 0.25)
  NM_FRAMES settle frames (default 1; stateful effects use more)

Usage: NM_JOBS='[...]' blender --factory-startup --python blender/harness/render_all.py
"""
import os
import sys
import json
import traceback

import bpy

HARNESS = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HARNESS), "noisemaker_blender")
sys.path.insert(0, os.path.dirname(ADDON))
from noisemaker_blender.backend.gpu_backend import GpuBackend          # noqa: E402
from noisemaker_blender.runtime import graph_loader, pipeline, pngio   # noqa: E402


def run():
    size = int(os.environ.get("NM_SIZE", "256"))
    time = float(os.environ.get("NM_TIME", "0.25"))
    frames = int(os.environ.get("NM_FRAMES", "1"))
    jobs = json.loads(os.environ["NM_JOBS"])
    # Stateful timed-sampling (reference/04 convention): run NM_RUN_SECONDS at 60fps
    # (1/600 normalized dt, advancing time), capture every NM_SAMPLE_EVERY seconds ->
    # <out>.t<sec>.png, matching golden.t<sec>.png. The methodology for navierStokes/
    # cellularAutomata/reactionDiffusion/agents (user: "run 30s, record every 5").
    run_seconds = os.environ.get("NM_RUN_SECONDS")
    sample_every = int(os.environ.get("NM_SAMPLE_EVERY", "5"))
    shaders_root = os.path.join(ADDON, "shaders", "effects")
    for job in jobs:
        try:
            graph = graph_loader.load(job["graph"])
            be = GpuBackend(shaders_root, size)
            if run_seconds:
                rs = int(run_seconds)
                total = rs * 60
                sample_idx = {(s + 1) * sample_every * 60 - 1 for s in range(rs // sample_every)}
                res = pipeline.render(be, graph, frames=total, samples=sample_idx, timed=True)
                for f, arr in sorted(res.items()):
                    sec = (f + 1) // 60
                    out = job["out"].replace(".png", ".t%d.png" % sec)
                    pngio.write_png(out, arr)
                    print("NMR OK", os.path.basename(out),
                          "mean=%s" % arr.reshape(-1, 4).mean(0).round(1).tolist())
            else:
                arr = pipeline.render(be, graph, time=time, frames=frames)
                pngio.write_png(job["out"], arr)
                print("NMR OK", os.path.basename(job["out"]),
                      "mean=%s px00=%s pxCtr=%s"
                      % (arr.reshape(-1, 4).mean(0).round(1).tolist(),
                         arr[0, 0].tolist(), arr[arr.shape[0] // 2, arr.shape[1] // 2].tolist()))
            be.free()
        except Exception as e:
            print("NMR FAIL", job.get("graph"), "::", repr(e))
            traceback.print_exc()
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

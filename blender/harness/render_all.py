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
from noisemaker_blender.compiler import compile_graph                  # noqa: E402


def run():
    size = int(os.environ.get("NM_SIZE", "256"))
    time = float(os.environ.get("NM_TIME", "0.25"))
    frames = int(os.environ.get("NM_FRAMES", "1"))
    # NM_TIMESTEP>0 evolves continuous solvers / agent sims to steady state, matching the
    # golden harness (parity/batch-golden.mjs: tt=(time+i*ts)%1). The byte-identical
    # navierStokes/integration recipe is NM_FRAMES=1800 NM_TIMESTEP=0.0016667 (30s @ 1/600).
    timestep = float(os.environ.get("NM_TIMESTEP", "0"))
    # Optional diagnostic: NM_SAMPLE_EVERY (in frames) -> <out>.f<frame>.png snapshots.
    sample_every = int(os.environ.get("NM_SAMPLE_EVERY", "0"))
    jobs = json.loads(os.environ["NM_JOBS"])
    shaders_root = os.path.join(ADDON, "shaders", "effects")
    for job in jobs:
        try:
            # "dsl" job -> compile the DSL to a graph in-process (in-Blender Python compiler,
            # no external reference engine); "graph" job -> load a pre-exported graph.json.
            if "dsl" in job:
                graph = graph_loader.Graph(compile_graph(open(job["dsl"]).read()))
            else:
                graph = graph_loader.load(job["graph"])
            be = GpuBackend(shaders_root, size)
            if sample_every:
                sample_idx = set(range(sample_every - 1, frames, sample_every)) | {frames - 1}
                res = pipeline.render(be, graph, time=time, frames=frames,
                                      timestep=timestep, samples=sample_idx)
                for f, arr in sorted(res.items()):
                    out = job["out"].replace(".png", ".f%d.png" % (f + 1))
                    pngio.write_png(out, arr)
                    print("NMR OK", os.path.basename(out),
                          "mean=%s" % arr.reshape(-1, 4).mean(0).round(1).tolist())
            else:
                arr = pipeline.render(be, graph, time=time, frames=frames, timestep=timestep)
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

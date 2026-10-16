"""Candidate render harness — runs noisemaker graph.json files through the GpuBackend
and writes candidate PNGs. GUI mode (macOS GPU needs a context); self-quits.

Driven by env:
  NM_JOBS   JSON list of {"graph": <path>, "out": <path>}
  NM_SIZE   render size (default 256)
  NM_WIDTH/NM_HEIGHT optional axis overrides
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
sys.path.insert(0, HARNESS)
from fixture_inputs import make_frames                                # noqa: E402
from noisemaker_blender.backend.gpu_backend import GpuBackend          # noqa: E402
from noisemaker_blender.runtime import graph_loader, pipeline, pngio   # noqa: E402
from noisemaker_blender.runtime.session import Program, RenderSession  # noqa: E402
from noisemaker_blender.compiler import compile_graph                  # noqa: E402


def render_rectangular(graph, shaders_root, width, height, time, frames, timestep, samples):
    # The legacy FrameStepper supplies square engine uniforms. The existing
    # session frame driver supplies both axes without changing add-on code.
    program = Program.from_graph("parity capture", graph.data)
    captured = {}
    previous_time = None
    with RenderSession(program, width=width, height=height, shaders_root=shaders_root) as session:
        for frame in range(frames):
            tt = (time + frame * timestep) % 1.0 if timestep else time
            delta = 0.0 if previous_time is None else tt - previous_time
            session._render_at(tt, frame, delta)
            previous_time = tt
            if samples is not None and frame in samples:
                captured[frame] = session.backend.read_surface(graph.render_surface)
            elif timestep and frame % 30 == 29:
                session.backend.read_surface(graph.render_surface)
        return captured if samples is not None else session.backend.read_surface(graph.render_surface)


def run():
    size = int(os.environ.get("NM_SIZE", "256"))
    width = int(os.environ.get("NM_WIDTH", size))
    height = int(os.environ.get("NM_HEIGHT", size))
    time = float(os.environ.get("NM_TIME", "0.25"))
    frames = int(os.environ.get("NM_FRAMES", "1"))
    # NM_TIMESTEP>0 evolves continuous solvers / agent sims to steady state, matching the
    # golden harness (parity/batch-golden.mjs: tt=(time+i*ts)%1). The byte-identical
    # navierStokes/integration recipe is NM_FRAMES=1800 NM_TIMESTEP=0.0016667 (30s @ 1/600).
    timestep = float(os.environ.get("NM_TIMESTEP", "0"))
    # Optional diagnostic: NM_SAMPLE_EVERY (in frames) -> <out>.f<frame>.png snapshots.
    sample_every = int(os.environ.get("NM_SAMPLE_EVERY", "0"))
    jobs = json.loads(os.environ["NM_JOBS"])
    bindings = json.loads(os.environ.get("NM_INPUT_BINDINGS", "{}"))
    shaders_root = os.path.join(ADDON, "shaders", "effects")
    for job in jobs:
        try:
            # "dsl" job -> compile the DSL to a graph in-process (in-Blender Python compiler,
            # no external reference engine); "graph" job -> load a pre-exported graph.json.
            if "dsl" in job:
                graph = graph_loader.Graph(compile_graph(open(job["dsl"]).read()))
            else:
                graph = graph_loader.load(job["graph"])
            sample_idx = (set(range(sample_every - 1, frames, sample_every)) | {frames - 1}
                          if sample_every else None)
            if width != height:
                if bindings:
                    raise ValueError("supplied parity inputs require square captures")
                res = render_rectangular(graph, shaders_root, width, height,
                                         time, frames, timestep, sample_idx)
            else:
                be = GpuBackend(shaders_root, width)
                if bindings:
                    be.set_external_inputs(make_frames(bindings, graph))
                res = pipeline.render(be, graph, time=time, frames=frames,
                                      timestep=timestep, samples=sample_idx)
                be.free()
            if sample_every:
                for f, arr in sorted(res.items()):
                    out = job["out"].replace(".png", ".f%d.png" % (f + 1))
                    pngio.write_png(out, arr)
                    print("NMR OK", os.path.basename(out),
                          "mean=%s" % arr.reshape(-1, 4).mean(0).round(1).tolist())
            else:
                arr = res
                pngio.write_png(job["out"], arr)
                print("NMR OK", os.path.basename(job["out"]),
                      "mean=%s px00=%s pxCtr=%s"
                      % (arr.reshape(-1, 4).mean(0).round(1).tolist(),
                         arr[0, 0].tolist(), arr[arr.shape[0] // 2, arr.shape[1] // 2].tolist()))
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

"""Dump a 3D-volume-atlas surface as an 8x8 grid of Z-slices for visual inspection.
NM_GRAPH, NM_FRAMES, NM_ATLAS (texture id), NM_OUT (png path), NM_VOL (volumeSize)."""
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


def run():
    graph = graph_loader.load(os.environ["NM_GRAPH"])
    frames = int(os.environ.get("NM_FRAMES", "8"))
    vol = int(os.environ.get("NM_VOL", "64"))
    atlas = os.environ["NM_ATLAS"]
    be = GpuBackend(os.path.join(ADDON, "shaders", "effects"), 256)
    defaults = pipeline.collect_default_uniforms(graph)
    arr = pipeline.render(be, graph, time=0.25, frames=frames, timestep=0.0016667)  # warm
    # read the atlas surface raw
    name = atlas[len("global_"):] if atlas.startswith("global_") else atlas
    off = be.surfaces[name].read if name in be.surfaces else be.pool.get(graph.phys(atlas))
    w, h = off.width, off.height
    with off.bind():
        buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
    buf.dimensions = w * h * 4
    a = np.array(buf, dtype=np.float32).reshape(h, w, 4)
    print("ATLAS %s size=%dx%d  r:min=%.3f max=%.3f mean=%.3f" % (atlas, w, h,
          a[..., 0].min(), a[..., 0].max(), a[..., 0].mean()))
    # atlas: width=vol, height=vol*vol; row r=y+z*vol -> z=row//vol, y=row%vol
    nz = h // vol
    grid_n = int(np.ceil(np.sqrt(nz)))
    canvas = np.zeros((grid_n * vol, grid_n * vol, 3), np.float32)
    for z in range(nz):
        sl = a[z * vol:(z + 1) * vol, :vol, :3]
        gy, gx = z // grid_n, z % grid_n
        canvas[gy * vol:(gy + 1) * vol, gx * vol:(gx + 1) * vol] = sl
    out = np.clip(canvas, 0, 1)
    img = bpy.data.images.new("atlas", width=canvas.shape[1], height=canvas.shape[0])
    rgba = np.concatenate([out, np.ones((*out.shape[:2], 1), np.float32)], axis=2)
    img.pixels.foreach_set(rgba[::-1].reshape(-1))
    img.filepath_raw = os.environ["NM_OUT"]
    img.file_format = 'PNG'
    img.save()
    print("wrote", os.environ["NM_OUT"], canvas.shape)
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

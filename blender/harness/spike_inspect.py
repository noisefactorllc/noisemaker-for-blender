"""Spike A3: nail the read_color Buffer layout + orientation + sRGB.

Key rule learned: on Metal you MUST NOT write `uniform ...;` in the GLSL
source (reserved MSL keyword). Declare via info.push_constant() only and
reference the bare name in the body.
"""
import sys
import traceback

import bpy
import gpu
from gpu.types import GPUShaderCreateInfo, GPUOffScreen
from gpu_extras.batch import batch_for_shader
import numpy as np

W = H = 4
TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}


def shader(frag, pushes=()):
    info = GPUShaderCreateInfo()
    for t, n in pushes:
        info.push_constant(t, n)
    info.vertex_in(0, 'VEC2', "pos")
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source("void main(){ gl_Position = vec4(pos, 0.0, 1.0); }")
    info.fragment_source(frag)
    return gpu.shader.create_from_info(info)


def draw(sh, uniforms=()):
    batch = batch_for_shader(sh, 'TRIS', TRI)
    off = GPUOffScreen(W, H, format='RGBA8')
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 1.0))
        sh.bind()
        for n, v in uniforms:
            sh.uniform_float(n, v)
        batch.draw(sh)
        buf = fb.read_color(0, 0, W, H, 4, 0, 'UBYTE')
    off.free()
    return buf


def run():
    try:
        buf = draw(shader("void main(){ FragColor = vec4(0.1,0.4,0.7,1.0); }"))
        print("BUF type", type(buf).__name__,
              "dims", getattr(buf, 'dimensions', None), "len", len(buf))
        flat = np.array(buf, dtype=np.uint8).reshape(-1)
        print("BUF first16:", flat[:16].tolist())
        print("   (correct interleaved RGBA const => 26,102,178,255 repeating)")
        print("   (linear store=>26,102,178 ; sRGB store=>89,168,217)")

        # Orientation: G ramps with gl_FragCoord.y. res via push_constant only.
        gbuf = draw(shader(
            "void main(){ FragColor = vec4(0.0, gl_FragCoord.y/resolution.y, 0.0, 1.0); }",
            pushes=[('VEC2', 'resolution')]),
            uniforms=[("resolution", (float(W), float(H)))])
        g = np.array(gbuf, dtype=np.uint8).reshape(H, W, 4)
        print("ORIENT G[:,0,1] (row0..rowN):", g[:, 0, 1].tolist(),
              "=> row0 is BOTTOM if increasing")

        # VEC3 push-constant binding sanity
        cbuf = draw(shader(
            "void main(){ FragColor = vec4(color, 1.0); }",
            pushes=[('VEC3', 'color')]),
            uniforms=[("color", (0.2, 0.5, 0.9))])
        c = np.array(cbuf, dtype=np.uint8).reshape(H, W, 4)
        print("PUSH vec3 color px[0,0]:", c[0, 0].tolist(), "(linear=>51,128,230,255)")
    except Exception as e:
        print("FAIL", repr(e))
        traceback.print_exc()
    finally:
        sys.stdout.flush()


if bpy.app.background:
    run()
else:
    def _t():
        run()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.5)

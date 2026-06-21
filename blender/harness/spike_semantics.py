"""Spike A2: characterize offscreen readback semantics for the backend.

Determines, definitively:
  - channel independence (does RGBA come back as 4 distinct channels?)
  - sRGB-on-write (is a linear 0.4 stored as 102 [linear] or ~166 [sRGB]?)
  - row orientation (is read_color row 0 the BOTTOM or TOP of the image?)
  - whether named push-constant uniforms bind correctly (VEC2 + VEC3 layout)
"""
import sys
import traceback

import bpy
import gpu
from gpu.types import GPUShaderCreateInfo, GPUOffScreen
from gpu_extras.batch import batch_for_shader
import numpy as np

W = H = 8
TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}


def make_shader(frag, pushes=()):
    info = GPUShaderCreateInfo()
    for t, n in pushes:
        info.push_constant(t, n)
    info.vertex_in(0, 'VEC2', "pos")
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source("void main(){ gl_Position = vec4(pos, 0.0, 1.0); }")
    info.fragment_source(frag)
    return gpu.shader.create_from_info(info)


def render(shader, uniforms=()):
    batch = batch_for_shader(shader, 'TRIS', TRI)
    off = GPUOffScreen(W, H, format='RGBA8')
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 1.0))
        shader.bind()
        for n, v in uniforms:
            shader.uniform_float(n, v)
        batch.draw(shader)
        buf = fb.read_color(0, 0, W, H, 4, 0, 'UBYTE')
    off.free()
    return np.array(buf, dtype=np.uint8).reshape(H, W, 4)


def run():
    try:
        # TEST 1: constant distinct color, NO uniforms -> channel independence + sRGB
        a = render(make_shader(
            "void main(){ FragColor = vec4(0.1, 0.4, 0.7, 1.0); }"))
        print("T1 const(0.1,0.4,0.7,1.0): px=", a[0, 0].tolist(),
              "uniform_across_image=", bool((a == a[0, 0]).all()))
        print("   -> linear would be [26,102,178,255]; sRGB ~ [89,168,217,255]")

        # TEST 2: horizontal ramp in R only -> orientation + channel isolation
        b = render(make_shader(
            "uniform vec2 resolution;\n"
            "void main(){ FragColor = vec4(gl_FragCoord.x/resolution.x, 0.0, 0.0, 1.0); }",
            pushes=[('VEC2', 'resolution')]),
            uniforms=[("resolution", (float(W), float(H)))])
        print("T2 R=x-ramp: row0=", b[0, :, 0].tolist())
        print("   col R across row0 (expect L->R increasing if no x-flip):")
        print("T2 G,B,A at [0,0]=", b[0, 0, 1:].tolist(), "(expect [0,0,255])")

        # TEST 3: vertical ramp in G -> row orientation (top vs bottom first)
        c = render(make_shader(
            "uniform vec2 resolution;\n"
            "void main(){ FragColor = vec4(0.0, gl_FragCoord.y/resolution.y, 0.0, 1.0); }",
            pushes=[('VEC2', 'resolution')]),
            uniforms=[("resolution", (float(W), float(H)))])
        print("T3 G=y-ramp: G col0 top->bottom=", c[:, 0, 1].tolist())
        print("   -> read_color row 0 is BOTTOM if this list INCREASES, TOP if it DECREASES")

        # TEST 4: named VEC3 push-constant binding (the earlier suspect)
        d = render(make_shader(
            "uniform vec3 color;\n"
            "void main(){ FragColor = vec4(color, 1.0); }",
            pushes=[('VEC3', 'color')]),
            uniforms=[("color", (0.2, 0.5, 0.9))])
        print("T4 push vec3 color(0.2,0.5,0.9): px=", d[0, 0].tolist(),
              "(linear [51,128,230,255]); uniform=", bool((d == d[0, 0]).all()))
    except Exception as e:
        print("NMSEM FAIL", repr(e))
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

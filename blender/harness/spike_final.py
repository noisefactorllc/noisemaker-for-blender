"""Spike A4 (definitive): the real backend path.

RGBA16F offscreen (linear, no sRGB) + FLOAT readback + dimensions-flatten,
plus the sampler2D input path. Proves every core backend op:
  push-constants, samplers (NEAREST/CLAMP), fullscreen pass, float readback,
  channel order, orientation, linear (no-gamma) storage.
"""
import sys
import traceback

import bpy
import gpu
from gpu.types import GPUShaderCreateInfo, GPUOffScreen, GPUTexture, Buffer
from gpu_extras.batch import batch_for_shader
import numpy as np

W = H = 4
TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}


def shader(frag, pushes=(), samplers=()):
    info = GPUShaderCreateInfo()
    for t, n in pushes:
        info.push_constant(t, n)
    for slot, t, n in samplers:
        info.sampler(slot, t, n)
    info.vertex_in(0, 'VEC2', "pos")
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source("void main(){ gl_Position = vec4(pos, 0.0, 1.0); }")
    info.fragment_source(frag)
    return gpu.shader.create_from_info(info)


def draw(sh, floats=(), texs=()):
    batch = batch_for_shader(sh, 'TRIS', TRI)
    off = GPUOffScreen(W, H, format='RGBA16F')
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 1.0))
        sh.bind()
        for n, v in floats:
            sh.uniform_float(n, v)
        for n, t in texs:
            sh.uniform_sampler(n, t)
        batch.draw(sh)
        buf = fb.read_color(0, 0, W, H, 4, 0, 'FLOAT')
    off.free()
    buf.dimensions = W * H * 4            # <-- flatten 3D Buffer (the fix)
    return np.array(buf, dtype=np.float32).reshape(H, W, 4)


def q(a):
    return np.round(np.clip(a, 0, 1) * 255).astype(int)


def run():
    try:
        a = draw(shader("void main(){ FragColor = vec4(0.1,0.4,0.7,1.0); }"))
        print("CONST float px[0,0]=", [round(x, 3) for x in a[0, 0].tolist()],
              "quant=", q(a[0, 0]).tolist(),
              "uniform=", bool(np.allclose(a, a[0, 0])))
        print("   PASS if quant=[26,102,178,255] (linear, channels independent)")

        g = draw(shader(
            "void main(){ FragColor = vec4(0.0, gl_FragCoord.y/resolution.y, 0.0, 1.0); }",
            pushes=[('VEC2', 'resolution')]),
            floats=[("resolution", (float(W), float(H)))])
        print("ORIENT q(G[:,0]) row0..rowN=", q(g[:, 0, 1]).tolist(),
              "=> row0 BOTTOM if increasing (need flip for top-down golden)")

        # sampler path: 1x1 input texture, sampled everywhere
        tex = GPUTexture((1, 1), format='RGBA16F',
                         data=Buffer('FLOAT', 4, [0.3, 0.6, 0.9, 1.0]))
        s = draw(shader(
            "void main(){ FragColor = texture(tex, vec2(0.5)); }",
            samplers=[(0, 'FLOAT_2D', 'tex')]),
            texs=[("tex", tex)])
        print("SAMPLER q(px[0,0])=", q(s[0, 0]).tolist(),
              "PASS if [77,153,230,255] (sampler2D works)")

        c = draw(shader(
            "void main(){ FragColor = vec4(color, 1.0); }",
            pushes=[('VEC3', 'color')]),
            floats=[("color", (0.2, 0.5, 0.9))])
        print("PUSH vec3 q(px[0,0])=", q(c[0, 0]).tolist(),
              "PASS if [51,128,230,255]")
        print("NMFINAL DONE")
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

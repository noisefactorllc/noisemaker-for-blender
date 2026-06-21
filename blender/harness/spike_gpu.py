"""Spike A: prove gpu-module offscreen render + readback on this Blender/GPU.

Tests the load-bearing assumptions for the whole port:
  1. A reference-STYLE fragment shader (uses gl_FragCoord + a `resolution`
     push-constant, no uv varying) compiles via GPUShaderCreateInfo on Metal.
  2. A fullscreen-triangle pass renders into a GPUOffScreen.
  3. Pixels read back are a correct, varying gradient (not black/garbage).

Runs in both --background and GUI mode (GUI defers to a timer, then quits),
so we can learn empirically whether headless GPU works on macOS.
"""
import sys
import traceback

import bpy
import gpu
from gpu.types import GPUShaderCreateInfo, GPUOffScreen
from gpu_extras.batch import batch_for_shader

W = H = 64


def run():
    print("NMSPIKE begin background=%s" % bpy.app.background)
    try:
        import gpu.platform as gp
        try:
            print("NMSPIKE backend", gp.backend_type_get(), "device", gp.device_type_get())
        except Exception as e:
            print("NMSPIKE backend_err", repr(e))

        info = GPUShaderCreateInfo()
        info.push_constant('VEC2', "resolution")
        info.push_constant('VEC3', "color")
        info.vertex_in(0, 'VEC2', "pos")
        info.fragment_out(0, 'VEC4', "FragColor")
        info.vertex_source("void main(){ gl_Position = vec4(pos, 0.0, 1.0); }")
        info.fragment_source(
            "void main(){ vec2 st = gl_FragCoord.xy / resolution.y;"
            " FragColor = vec4(st, color.b, 1.0); }"
        )
        shader = gpu.shader.create_from_info(info)
        print("NMSPIKE shader_compiled OK")

        batch = batch_for_shader(
            shader, 'TRIS', {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}
        )
        off = GPUOffScreen(W, H, format='RGBA8')
        print("NMSPIKE offscreen_created OK")
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 1.0))
            shader.bind()
            shader.uniform_float("resolution", (float(W), float(H)))
            shader.uniform_float("color", (0.0, 0.0, 1.0))
            batch.draw(shader)
            buf = fb.read_color(0, 0, W, H, 4, 0, 'UBYTE')
        off.free()

        import numpy as np
        arr = np.array(buf, dtype=np.uint8).reshape(H, W, 4)
        print("NMSPIKE readback shape", arr.shape, "min", int(arr.min()), "max", int(arr.max()))
        print("NMSPIKE px[0,0]", arr[0, 0].tolist(),
              "px[32,32]", arr[32, 32].tolist(),
              "px[63,63]", arr[63, 63].tolist())
        ok = (arr.min() != arr.max()) and (int(arr[..., 2].min()) >= 250)
        print("NMSPIKE RESULT", "PASS" if ok else "SUSPECT")
    except Exception as e:
        print("NMSPIKE FAIL", repr(e))
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

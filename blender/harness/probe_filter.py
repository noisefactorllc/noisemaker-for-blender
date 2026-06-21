"""Probe default sampler filtering/wrap, and whether texelFetch/textureSize work."""
import bpy
import gpu
import numpy as np
from gpu.types import GPUShaderCreateInfo, GPUOffScreen, GPUTexture, Buffer
from gpu_extras.batch import batch_for_shader

W = 16
TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}


def mk(frag):
    info = GPUShaderCreateInfo()
    info.push_constant('FLOAT', "w")
    info.sampler(0, 'FLOAT_2D', "tex")
    info.vertex_in(0, 'VEC2', "pos")
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source("void main(){ gl_Position = vec4(pos,0.0,1.0); }")
    info.fragment_source(frag)
    return gpu.shader.create_from_info(info)


def draw(sh, tex):
    off = GPUOffScreen(W, 1, format='RGBA16F')
    with off.bind():
        gpu.state.active_framebuffer_get().clear(color=(0, 0, 0, 1))
        sh.bind(); sh.uniform_float("w", float(W)); sh.uniform_sampler("tex", tex)
        batch_for_shader(sh, 'TRIS', TRI).draw(sh)
        buf = off.texture_color  # noqa
        b = gpu.state.active_framebuffer_get().read_color(0, 0, W, 1, 4, 0, 'FLOAT')
    off.free()
    b.dimensions = W * 4
    return np.array(b, np.float32).reshape(W, 4)[:, 0]


def run():
    # 2x1 texture: texel0 R=0, texel1 R=1
    tex = GPUTexture((2, 1), format='RGBA16F', data=Buffer('FLOAT', 8, [0, 0, 0, 1, 1, 1, 1, 1]))
    try:
        a = draw(mk("void main(){ FragColor = texture(tex, vec2((gl_FragCoord.x-0.5)/(w-1.0), 0.5)); }"), tex)
        print("DEFAULT texture() R across uv 0..1:", [round(float(x), 2) for x in a])
        print("  -> ramp(0..1)=LINEAR ; step(0 then 1)=NEAREST")
    except Exception as e:
        print("DEFAULT err", repr(e))
    try:
        b = draw(mk("void main(){ ivec2 sz=textureSize(tex,0); int xi=clamp(int((gl_FragCoord.x-0.5)/(w-1.0)*float(sz.x)),0,sz.x-1); FragColor = texelFetch(tex, ivec2(xi,0),0); }"), tex)
        print("texelFetch R across uv 0..1:", [round(float(x), 2) for x in b])
        print("  -> should be a clean step (NEAREST), proves texelFetch+textureSize work")
    except Exception as e:
        print("texelFetch err", repr(e))


if bpy.app.background:
    run()
else:
    def _t():
        run(); bpy.ops.wm.quit_blender(); return None
    bpy.app.timers.register(_t, first_interval=0.3)

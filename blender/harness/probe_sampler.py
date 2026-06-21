"""Probe: how to force NEAREST/CLAMP sampler state in the gpu module."""
import inspect
import bpy
import gpu


def run():
    print("PROBE GPUSamplerState?", hasattr(gpu.types, "GPUSamplerState"))
    if hasattr(gpu.types, "GPUSamplerState"):
        try:
            print("PROBE GPUSamplerState sig:", inspect.signature(gpu.types.GPUSamplerState.__init__))
        except Exception as e:
            print("PROBE sig err", repr(e))
        print("PROBE GPUSamplerState doc:", (gpu.types.GPUSamplerState.__doc__ or "")[:300])
    # info.sampler signature
    info = gpu.types.GPUShaderCreateInfo()
    print("PROBE info.sampler doc:", (info.sampler.__doc__ or "")[:300])
    # shader.uniform_sampler doc
    print("PROBE uniform_sampler in dir(GPUShader):", "uniform_sampler" in dir(gpu.types.GPUShader))
    # GPUTexture doc (filter param?)
    print("PROBE GPUTexture doc:", (gpu.types.GPUTexture.__doc__ or "")[:400])
    # gpu.state sampler?
    print("PROBE gpu.state attrs:", [a for a in dir(gpu.state) if "sampl" in a.lower() or "filter" in a.lower()])


if bpy.app.background:
    run()
else:
    def _t():
        run()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.3)

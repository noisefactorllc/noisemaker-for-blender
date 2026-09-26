"""Run under Blender to verify capability contracts exposed by GpuBackend."""

import os
import sys


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

from noisemaker_blender.backend.gpu_backend import GpuBackend


backend = GpuBackend.__new__(GpuBackend)
assert backend.create_frame_export_queue(slots=3) is None
print("BACKEND CONTRACT PASS — asynchronous frame export is explicitly unsupported")


class MockShader:
    """Records uniform_float values without a GPU context."""

    def __init__(self):
        self.floats = {}

    def uniform_float(self, name, value):
        self.floats[name] = tuple(value)


# vecN uniforms must receive exactly N components: an over-length sequence (e.g. a
# 4-component color value for the declared `vec3 color1`) raises ValueError inside
# Blender's uniform_float, which _set_uniform swallows — the uniform stays at its
# default zero and the effect silently renders black (observed: gradient, and the
# landscape modes that consume it).
shader = MockShader()
backend._set_uniform(shader, "VEC3", "color1", [0.0, 0.43, 0.58, 1.0])
assert shader.floats["color1"] == (0.0, 0.43, 0.58), shader.floats
backend._set_uniform(shader, "VEC4", "color2", [1.0, 2.0, 3.0, 4.0, 5.0])
assert shader.floats["color2"] == (1.0, 2.0, 3.0, 4.0), shader.floats
backend._set_uniform(shader, "VEC2", "resolution", [256.0, 256.0])
assert shader.floats["resolution"] == (256.0, 256.0), shader.floats
print("BACKEND CONTRACT PASS — vecN uniform values are sliced to the declared width")


class MockOffscreen:
    def __init__(self, w, h, fmt):
        self.width = w
        self.height = h
        self.fmt = fmt
        self.freed = False

    def free(self):
        self.freed = True


class MockGraph:
    def __init__(self, textures):
        self.textures = textures
        self.passes = []

    def phys(self, tid):
        return 0


backend.surfaces = {}
backend.pool = {}
backend.frame_read = {}
backend.frame_write = {}
backend.tex_dims = {}
backend._fb_cache = {}
backend.size = 256
backend._new_off = lambda w, h, fmt: MockOffscreen(w, h, fmt)

# Setup initial global surface
backend.setup(MockGraph({"global_vel": {"width": 256, "height": 256, "format": "rgba32f"}}), {})
surface1 = backend.surfaces["vel"]
assert surface1.fmt == "RGBA32F"
assert surface1.read.width == 256
assert not surface1.read.freed

# Re-setup with identical config: preserved
backend.setup(MockGraph({"global_vel": {"width": 256, "height": 256, "format": "rgba32f"}}), {})
surface2 = backend.surfaces["vel"]
assert surface2 is surface1
assert not surface1.read.freed

# Simulate active frame bindings and framebuffer cache
backend.frame_read["vel"] = surface1.read
backend.frame_write["vel"] = surface1.write
backend._fb_cache[(id(surface1.write),)] = object()

# Re-setup with changed format: recreated, old freed, frame bindings and fb cache evicted
backend.setup(MockGraph({"global_vel": {"width": 256, "height": 256, "format": "rgba16f"}}), {})
surface3 = backend.surfaces["vel"]
assert surface3 is not surface1
assert surface3.fmt == "RGBA16F"
assert surface1.read.freed
assert surface1.write.freed
assert "vel" not in backend.frame_read
assert "vel" not in backend.frame_write
assert len(backend._fb_cache) == 0

# Re-setup with changed dimension: recreated, old freed
backend.frame_read["vel"] = surface3.read
backend.setup(MockGraph({"global_vel": {"width": 128, "height": 128, "format": "rgba16f"}}), {})
surface4 = backend.surfaces["vel"]
assert surface4 is not surface3
assert surface4.read.width == 128
assert surface3.read.freed
assert surface3.write.freed
assert "vel" not in backend.frame_read

print("BACKEND CONTRACT PASS — global surface refreshed when format or dimensions change")

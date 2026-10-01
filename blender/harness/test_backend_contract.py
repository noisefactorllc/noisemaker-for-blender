"""Run under Blender to verify capability contracts exposed by GpuBackend.

The slab-tiling asserts are also covered engine-free by parity/test_slab_tiling.py.
"""

import os
import sys


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

from noisemaker_blender.backend.gpu_backend import GpuBackend
import noisemaker_blender.backend.gpu_backend as _gb


backend = GpuBackend.__new__(GpuBackend)
assert backend.create_frame_export_queue(slots=3) is None
print("BACKEND CONTRACT PASS — asynchronous frame export is explicitly unsupported")

# __init__-constructed backends keep their diagnostic-state identity: the lazy
# _diagnostic_state() triple must seed from the __init__-created collector and
# dedup sets (review finding on 048f8ac: the original lazy-init discarded them).
backend_real = GpuBackend(REPO, 256)
_diag = backend_real.diagnostics
_dim = backend_real._warned_dimension_fallbacks
_fmt = backend_real._warned_format_fallbacks
state = backend_real._diagnostic_state()
assert state[0] is _diag and state[1] is _dim and state[2] is _fmt, (
    "_diagnostic_state must seed from the __init__-created triple")
backend_real.resolve_dim("screen", {})
assert backend_real._diagnostic_state()[0] is _diag, (
    "collector identity must survive the first resolver call")
print("BACKEND CONTRACT PASS — __init__-built backends keep their diagnostic-state identity")


class MockShader:
    """Records uniform_float values without a GPU context."""

    def __init__(self):
        self.floats = {}

    def uniform_float(self, name, value):
        self.floats[name] = tuple(value)


class StrictShader(MockShader):
    """Mimics Blender: a vecN uniform rejects a sequence of the wrong length."""

    WIDTHS = {"res2": 2, "col3": 3, "col4": 4, "short3": 3}

    def uniform_float(self, name, value):
        if name not in self.WIDTHS:
            raise ValueError("GPUShader.uniform_float: uniform %s not found" % name)
        if len(value) != self.WIDTHS[name]:
            raise ValueError("GPUShader.uniform_float: expected %d values for %s"
                             % (self.WIDTHS[name], name))
        self.floats[name] = tuple(value)


_gb._WARNED_UNIFORMS.clear()

# vecN uniforms must receive exactly N components: an over-length sequence (e.g. a
# 4-component color value for the declared `vec3 color1`) raises ValueError inside
# Blender's uniform_float, which _set_uniform swallows — the uniform stays at its
# default zero and the effect silently renders black (observed: gradient, and the
# landscape modes that consume it). _set_uniform normalizes any sequence to the
# declared width; an under-length value cannot be padded, so it is skipped with a
# visible one-time warning instead of silently rendering with default colors.
shader = MockShader()
backend._set_uniform(shader, "VEC3", "color1", [0.0, 0.43, 0.58, 1.0])
assert shader.floats["color1"] == (0.0, 0.43, 0.58), shader.floats
backend._set_uniform(shader, "VEC4", "color2", (1.0, 2.0, 3.0, 4.0, 5.0))
assert shader.floats["color2"] == (1.0, 2.0, 3.0, 4.0), shader.floats
backend._set_uniform(shader, "VEC2", "resolution", [256.0, 256.0])
assert shader.floats["resolution"] == (256.0, 256.0), shader.floats
# Non-list sequence (numpy row) with an over-length vec3: same normalization.
import numpy as np  # noqa: E402  (Blender ships numpy)
backend._set_uniform(shader, "VEC3", "color3", np.array([0.1, 0.2, 0.3, 0.4]))
assert shader.floats["color3"] == (0.1, 0.2, 0.3), shader.floats

# Under-length: Blender rejects it; the setter must skip it with a warning, not pass it.
strict = StrictShader()
_gb._WARNED_UNIFORMS.clear()
backend._set_uniform(strict, "VEC3", "short3", [0.1, 0.2])
assert "short3" not in strict.floats, strict.floats
assert ("short3", "VEC3", "not set") in _gb._WARNED_UNIFORMS

# Optimized-out uniform (never declared): skipped with a one-time warning, no raise.
_gb._WARNED_UNIFORMS.clear()
backend._set_uniform(strict, "VEC2", "absent2", [1.0, 2.0])
assert "absent2" not in strict.floats
assert ("absent2", "VEC2", "not set") in _gb._WARNED_UNIFORMS
backend._set_uniform(strict, "VEC2", "absent2", [1.0, 2.0])  # second failure: quiet
assert _gb._WARNED_UNIFORMS == {("absent2", "VEC2", "not set")}

# Over-length truncation is also visible once (a genuine width mismatch must not
# be silently masked by the RGBA-for-vec3 normalization).
_gb._WARNED_UNIFORMS.clear()
backend._set_uniform(shader, "VEC3", "wide3", [0.1, 0.2, 0.3, 0.4])
assert shader.floats["wide3"] == (0.1, 0.2, 0.3), shader.floats
assert ("wide3", "VEC3", "truncated") in _gb._WARNED_UNIFORMS

print("BACKEND CONTRACT PASS — vecN uniform values are normalized to the declared width;"
      " failed assignments warn once instead of staying silent")

# Upstream f83a427e audit (STATUS 2026-09-26 sync): the reference's structured
# ShaderDiagnostic union (GLSL info logs, WebGPU compilation info, bind-group
# layout retries) has no Blender analogue on this gpu surface — none of those
# APIs exist on gpu.types, so the port has no ERR_SHADER_* throw sites to
# normalize and browser-backend diagnostics remain out of scope here.
import gpu.types as _gt  # noqa: E402
for _probe in ("getShaderInfoLog", "getProgramInfoLog", "getCompilationInfo",
               "createBindGroup", "getBindGroupLayout", "createRenderPipeline"):
    assert not hasattr(_gt, _probe), "unexpected diagnostic surface: " + _probe
print("BACKEND CONTRACT PASS — no shader info-log/bind-group diagnostic surface"
      " on gpu.types (structured backend diagnostics inapplicable)")


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
        self.allocations = {}

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

# Slab tiling for the Metal tall-viewport workaround: slabs must tile the full
# height exactly, in order, with no gaps or overlap, and respect the cap.
for vy, vh in [(0, 4096), (0, 2048), (0, 2049), (37, 4097), (0, 1), (512, 63)]:
    ranges = _gb.slab_ranges(vy, vh)
    assert ranges[0][0] == vy
    assert all(h <= _gb._MAX_DRAW_SLAB for _, h in ranges), ranges
    assert ranges[-1][0] + ranges[-1][1] == vy + vh, ranges
    for (y0, h0), (y1, _h1) in zip(ranges, ranges[1:]):
        assert y1 == y0 + h0, ranges  # contiguous, ordered, no overlap
assert _gb.slab_ranges(0, 2048) == [(0, 2048)]  # small passes: single draw
assert _gb.slab_ranges(0, 4096) == [(0, 2048), (2048, 2048)]
assert _gb.slab_ranges(100, 3000, cap=1000) == [(100, 1000), (1100, 1000), (2100, 1000)]

# The pass viewport box must consume an already-resolved viewportResolved box's
# concrete pixel ints directly. Re-resolving it clamped an authored 0 through
# resolve_dimension's max(1, ...) floor and drew viewport-spec passes at (1, 1)
# instead of (0, 0) — the volume-cache atlas's leftmost column and bottom GPU
# row were silently unwritten (measured on the M4 host: box=(1,1,64,4096)).
_backend2 = GpuBackend.__new__(GpuBackend)
_backend2.size = 256
_p = {"viewportResolved": {"x": 0, "y": 0, "w": 64, "h": 4096}}
_box = _backend2._resolve_pass_viewport_box(_p, {}, 64, 4096)
assert _box == (0, 0, 64, 4096), _box
_box = _backend2._resolve_pass_viewport_box({"viewportResolved": {"x": 3, "y": 7, "w": 16, "h": 32}}, {}, 64, 4096)
assert _box == (3, 7, 16, 32), _box
# An authored raw numeric viewport (no viewportResolved) is consumed directly too.
_box = _backend2._resolve_pass_viewport_box({"viewport": {"x": 0, "y": 0, "w": 8, "h": 8}}, {}, 64, 4096)
assert _box == (0, 0, 8, 8), _box
# Expression-form specs still resolve against the merged uniforms.
_box = _backend2._resolve_pass_viewport_box(
    {"viewportResolved": {"x": 0, "y": 0, "w": {"param": "volumeSize", "default": 64},
                          "h": {"param": "volumeSize", "power": 2, "default": 4096}}},
    {"volumeSize": 64}, 64, 4096)
assert _box == (0, 0, 64, 4096), _box

print("BACKEND CONTRACT PASS — pass viewport box consumes resolved pixel ints")

print("BACKEND CONTRACT PASS — global surface refreshed when format or dimensions change")

"""GpuBackend — the noisemaker render-graph executor on Blender's `gpu` module (Metal).

Primitives the pipeline drives: offscreen management, shader compile (from transpiled
.frag + .createinfo.json), effect/blit pass execution, float readback. All surfaces are
linear RGBA16F (no sRGB); readback flattens the 3-D Buffer, flips rows to top-down, and
quantizes round(v*255). See docs/BLENDER-PLATFORM-NOTES.md and PORTING-GUIDE.md.
"""
import os
import json

import gpu
import numpy as np
from gpu.types import GPUOffScreen
from gpu_extras.batch import batch_for_shader

from . import shader_build

_FS_TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}

# Built-in passthrough copy (blit). Straight 1:1 texel copy at NEAREST.
_BLIT_FRAG = "void main(){ fragColor = texture(src, gl_FragCoord.xy / resolution); }\n"
_BLIT_DESC = {
    "pushConstants": [["VEC2", "resolution"]],
    "samplers": [[0, "FLOAT_2D", "src"]],
    "fragmentOut": [[0, "VEC4", "fragColor"]],
    "uniformAliases": {},
}


class GpuBackend:
    def __init__(self, shaders_root, size=256):
        self.shaders_root = shaders_root
        self.size = size
        self.offscreens = {}      # phys_id -> GPUOffScreen
        self._shader_cache = {}   # (relpath, defines_key) -> (shader, descriptor, rev_alias)
        self._batch_cache = {}    # shader -> batch

    # ---- offscreens -------------------------------------------------------
    def ensure_offscreen(self, phys_id, w=None, h=None):
        if phys_id not in self.offscreens:
            self.offscreens[phys_id] = GPUOffScreen(w or self.size, h or self.size, format='RGBA16F')
        return self.offscreens[phys_id]

    def free(self):
        for off in self.offscreens.values():
            off.free()
        self.offscreens.clear()

    # ---- shaders ----------------------------------------------------------
    def _load_descriptor(self, namespace, func, prog):
        base = os.path.join(self.shaders_root, namespace, func, prog)
        if not os.path.exists(base + ".frag"):
            raise FileNotFoundError("no shader for %s/%s/%s" % (namespace, func, prog))
        frag = open(base + ".frag").read()
        desc = json.load(open(base + ".createinfo.json"))
        return frag, desc, namespace + "/" + func + "/" + prog

    def compile(self, namespace, func, prog, defines):
        defines = defines or {}
        if namespace is None and func == "blit":
            frag, desc, rel = _BLIT_FRAG, _BLIT_DESC, "blit"
        else:
            frag, desc, rel = self._load_descriptor(namespace, func, prog)
        key = (rel, tuple(sorted(defines.items())))
        if key not in self._shader_cache:
            shader = shader_build.build_shader(frag, desc, defines)
            rev_alias = {v: k for k, v in desc.get("uniformAliases", {}).items()}
            self._shader_cache[key] = (shader, desc, rev_alias)
        return self._shader_cache[key]

    def _batch(self, shader):
        if shader not in self._batch_cache:
            self._batch_cache[shader] = batch_for_shader(shader, 'TRIS', _FS_TRI)
        return self._batch_cache[shader]

    # ---- uniform binding --------------------------------------------------
    @staticmethod
    def _set_uniform(shader, ctype, name, value):
        if value is None:
            return
        try:
            if ctype == "FLOAT":
                shader.uniform_float(name, float(value))
            elif ctype in ("VEC2", "VEC3", "VEC4", "MAT3", "MAT4"):
                shader.uniform_float(name, value)
            elif ctype == "INT":
                shader.uniform_int(name, int(value))
            elif ctype in ("IVEC2", "IVEC3", "IVEC4"):
                shader.uniform_int(name, [int(x) for x in value])
            elif ctype == "BOOL":
                shader.uniform_bool(name, [bool(value)])
        except ValueError:
            pass  # push-constant optimized out of this define-variant — fine.

    # ---- pass execution ---------------------------------------------------
    def execute_effect(self, p, graph, engine):
        shader, desc, rev_alias = self.compile(p.get("namespace"), p["func"], p["progName"], p.get("defines"))
        merged = dict(engine)
        merged.update(p.get("uniforms", {}))

        out_texids = list(p.get("outputs", {}).values())
        target = self.ensure_offscreen(graph.phys(out_texids[0]))
        with target.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            shader.bind()
            for ctype, name in desc.get("pushConstants", []):
                graph_name = rev_alias.get(name, name)
                self._set_uniform(shader, ctype, name, merged.get(graph_name))
            for slot, stype, name in desc.get("samplers", []):
                graph_name = rev_alias.get(name, name)
                tex_id = p.get("inputs", {}).get(graph_name)
                if tex_id is not None:
                    src = self.ensure_offscreen(graph.phys(tex_id))
                    shader.uniform_sampler(name, src.texture_color)
            self._batch(shader).draw(shader)

    def execute_blit(self, p, graph, engine):
        shader, desc, _ = self.compile(None, "blit", "blit", None)
        src_id = p.get("inputs", {}).get("src")
        dst_id = list(p.get("outputs", {}).values())[0]
        target = self.ensure_offscreen(graph.phys(dst_id))
        src = self.ensure_offscreen(graph.phys(src_id))
        with target.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            shader.bind()
            shader.uniform_float("resolution", (float(self.size), float(self.size)))
            shader.uniform_sampler("src", src.texture_color)
            self._batch(shader).draw(shader)

    def execute(self, p, graph, engine):
        if p.get("passType") == "blit":
            self.execute_blit(p, graph, engine)
        elif p.get("passType") == "effect":
            self.execute_effect(p, graph, engine)
        # other pass types (points/compute/repeat) staged.

    # ---- readback ---------------------------------------------------------
    def read(self, phys_id):
        off = self.offscreens[phys_id]
        w = h = self.size
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
        buf.dimensions = w * h * 4
        arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)
        arr = arr[::-1]  # GL row0=bottom -> top-down to match goldens
        return np.round(np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)

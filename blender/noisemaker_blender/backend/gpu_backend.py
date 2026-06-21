"""GpuBackend — noisemaker render-graph executor on Blender's `gpu` module (Metal).

Implements reference/04 §10: double-buffered global_* surfaces, resolveDimension for
downsampled state (zoom), three-tier ping-pong (the pipeline drives within-frame /
per-iteration / end-of-frame swaps via swap_after_write + persist). All surfaces linear
RGBA16F; readback flattens the 3-D Buffer, flips to top-down, quantizes round(v*255).
"""
import os
import json
import math

import gpu
import numpy as np
from gpu.types import GPUOffScreen
from gpu_extras.batch import batch_for_shader

from . import shader_build

_FS_TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}
_BLIT_FRAG = ("#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))),"
              " ivec2(0), textureSize((s),0)-ivec2(1)), 0))\n"
              "void main(){ fragColor = nmTex(src, gl_FragCoord.xy / resolution); }\n")
_BLIT_DESC = {"pushConstants": [["VEC2", "resolution"]], "samplers": [[0, "FLOAT_2D", "src"]],
              "fragmentOut": [[0, "VEC4", "fragColor"]], "uniformAliases": {}}


def _is_state_surface(name):
    # display surfaces are o0..o7; everything else (sims, particles) is persistent state.
    return not (len(name) == 2 and name[0] == "o" and name[1].isdigit())


class _Surface:
    __slots__ = ("read", "write")

    def __init__(self, read, write):
        self.read = read
        self.write = write


class GpuBackend:
    def __init__(self, shaders_root, size=256):
        self.shaders_root = shaders_root
        self.size = size
        self.surfaces = {}        # surfaceName -> _Surface (offscreen pair), for global_*
        self.pool = {}            # phys_id -> GPUOffScreen, for pooled textures
        self.frame_read = {}      # surfaceName -> GPUOffScreen (current frame binding)
        self.frame_write = {}
        self._shader_cache = {}
        self._batch_cache = {}

    # ---- dimension resolution (reference/04 §resolveDimension) -------------
    def resolve_dim(self, spec, uniforms):
        s = self.size
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            return max(1, int(math.floor(spec)))
        if isinstance(spec, str):
            if spec in ("screen", "auto"):
                return s
            if spec.endswith("%"):
                return max(1, int(math.floor(s * float(spec[:-1]) / 100.0)))
            return s
        if isinstance(spec, dict):
            if spec.get("param") is not None:
                val = uniforms.get(spec["param"], spec.get("paramDefault", 64))
                if spec.get("multiply") is not None:
                    val *= spec["multiply"]
                if spec.get("power") is not None:
                    val = val ** spec["power"]
                if (spec.get("power") is not None or spec.get("multiply") is not None) \
                        and uniforms.get(spec["param"]) is None and spec.get("default") is not None:
                    val = spec["default"]
                return max(1, int(math.floor(val)))
            if spec.get("screenDivide") is not None:
                div = uniforms.get(spec["screenDivide"], spec.get("default", 1)) or 1
                return max(1, int(round(s / div)))
            if spec.get("scale") is not None:
                return max(1, int(math.floor(s * spec["scale"])))
        return s

    # ---- surface/pool setup ----------------------------------------------
    def setup(self, graph, uniforms):
        texspecs = dict(graph.textures)
        for p in graph.passes:
            for tid in list(p.get("inputs", {}).values()) + list(p.get("outputs", {}).values()):
                texspecs.setdefault(tid, {"width": "screen", "height": "screen"})
        for tid, spec in texspecs.items():
            w = self.resolve_dim(spec.get("width", "screen"), uniforms)
            h = self.resolve_dim(spec.get("height", "screen"), uniforms)
            if tid.startswith("global_"):
                name = tid[len("global_"):]
                if name not in self.surfaces:
                    self.surfaces[name] = _Surface(GPUOffScreen(w, h, format='RGBA16F'),
                                                   GPUOffScreen(w, h, format='RGBA16F'))
            else:
                phys = graph.phys(tid)
                if phys not in self.pool:
                    self.pool[phys] = GPUOffScreen(w, h, format='RGBA16F')

    def frame_begin(self):
        for name, s in self.surfaces.items():
            self.frame_read[name] = s.read
            self.frame_write[name] = s.write

    def frame_persist(self):
        # end-of-frame (reference/04 §10.7): keep the latest bindings so sims/particles continue.
        for name, s in self.surfaces.items():
            s.read = self.frame_read[name]
            s.write = self.frame_write[name]

    def _read(self, tid, graph):
        if tid.startswith("global_"):
            return self.frame_read[tid[len("global_"):]]
        return self.pool[graph.phys(tid)]

    def _write(self, tid, graph):
        if tid.startswith("global_"):
            return self.frame_write[tid[len("global_"):]]
        return self.pool[graph.phys(tid)]

    def swap_after_write(self, tid):
        if tid.startswith("global_"):
            n = tid[len("global_"):]
            self.frame_read[n], self.frame_write[n] = self.frame_write[n], self.frame_read[n]

    def free(self):
        for s in self.surfaces.values():
            s.read.free(); s.write.free()
        for off in self.pool.values():
            off.free()
        self.surfaces.clear(); self.pool.clear()

    # ---- shaders ----------------------------------------------------------
    def compile(self, namespace, func, prog, defines):
        defines = defines or {}
        if namespace is None and func == "blit":
            frag, desc, rel = _BLIT_FRAG, _BLIT_DESC, "blit"
        else:
            base = os.path.join(self.shaders_root, namespace, func, prog)
            frag = open(base + ".frag").read()
            desc = json.load(open(base + ".createinfo.json"))
            rel = namespace + "/" + func + "/" + prog
        key = (rel, tuple(sorted(defines.items())))
        if key not in self._shader_cache:
            shader = shader_build.build_shader(frag, desc, defines)
            rev = {v: k for k, v in desc.get("uniformAliases", {}).items()}
            self._shader_cache[key] = (shader, desc, rev)
        return self._shader_cache[key]

    def _batch(self, shader):
        if shader not in self._batch_cache:
            self._batch_cache[shader] = batch_for_shader(shader, 'TRIS', _FS_TRI)
        return self._batch_cache[shader]

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
            pass

    # ---- pass execution ---------------------------------------------------
    def execute(self, p, graph, engine):
        pt = p.get("passType")
        if pt == "blit":
            self._draw(self.compile(None, "blit", "blit", None),
                       {"resolution": [float(self.size), float(self.size)]},
                       {"src": p["inputs"]["src"]},
                       list(p["outputs"].values())[0], graph)
        elif pt == "effect":
            merged = dict(engine)
            merged.update(p.get("uniforms", {}))
            self._draw(self.compile(p.get("namespace"), p["func"], p["progName"], p.get("defines")),
                       merged, p.get("inputs", {}), list(p["outputs"].values())[0], graph)

    def _draw(self, compiled, merged, inputs, out_tid, graph):
        shader, desc, rev = compiled
        target = self._write(out_tid, graph)
        with target.bind():
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
            shader.bind()
            for ctype, name in desc.get("pushConstants", []):
                self._set_uniform(shader, ctype, name, merged.get(rev.get(name, name)))
            for slot, stype, name in desc.get("samplers", []):
                tid = inputs.get(rev.get(name, name))
                if tid is not None:
                    shader.uniform_sampler(name, self._read(tid, graph).texture_color)
            self._batch(shader).draw(shader)

    # ---- readback ---------------------------------------------------------
    def read_surface(self, name):
        off = self.frame_read[name]
        w, h = off.width, off.height
        with off.bind():
            buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
        buf.dimensions = w * h * 4
        arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)[::-1]
        return np.round(np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)

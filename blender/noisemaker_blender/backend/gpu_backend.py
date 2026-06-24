"""GpuBackend — noisemaker render-graph executor on Blender's `gpu` module (Metal).

Implements reference/04 §10 + reference/05 backend semantics:
- double-buffered global_* surfaces, resolveDimension for downsampled state (zoom),
  three-tier ping-pong (the pipeline drives within-frame / per-iteration / end-of-frame
  swaps via swap_after_write + persist);
- per-surface formats (rgba8/rgba16f/rgba32f — agent position needs 32f);
- MRT (multi-output agent passes write xyz/vel/rgba together via a multi-attachment FBO);
- points scatter (drawMode:'points' — attribute-less gl_VertexID draw, additive ONE,ONE
  blend, NO per-pass clear: targets retain content, cleared once at creation per reference/05).
Readback flattens the 3-D Buffer, flips to top-down, quantizes round(v*255).
"""
import os
import re
import json
import math

import gpu
import numpy as np
from gpu.types import (GPUOffScreen, GPUFrameBuffer, GPUVertFormat, GPUVertBuf, GPUBatch,
                       GPUUniformBuf, Buffer)
from gpu_extras.batch import batch_for_shader

from . import shader_build, std140

_FS_TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}
_BLIT_FRAG = ("#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))),"
              " ivec2(0), textureSize((s),0)-ivec2(1)), 0))\n"
              "void main(){ fragColor = nmTex(src, gl_FragCoord.xy / resolution); }\n")
_BLIT_DESC = {"pushConstants": [["VEC2", "resolution"]], "samplers": [[0, "FLOAT_2D", "src"]],
              "fragmentOut": [[0, "VEC4", "fragColor"]], "uniformAliases": {}}

# graph texture format string -> GPUOffScreen format token.
_FORMAT = {"rgba8": "RGBA8", "rgba16f": "RGBA16F", "rgba32f": "RGBA32F"}
# Precision rank: a pooled slot shared by mixed formats must hold the most demanding one.
_FMT_RANK = {"RGBA8": 1, "RGBA16F": 2, "RGBA32F": 3}


_STATE_NODE_RE = re.compile(r"^(xyz|vel|rgba|points_trail)_node_\d+$")


def _is_state_surface(name):
    """reference/04 §10.7 isStateSurface — EXACT predicate (parity-critical; name has no
    global_ prefix). State surfaces persist their within-frame bindings end-of-frame so
    particle/feedback sims continue; everything else (display/scratch) swaps read<->write.
    Getting this wrong desyncs feedback: a display surface written an EVEN number of times
    per frame (lenia's clear+deposit) needs the swap, or deposit lands on a never-cleared
    buffer and accumulates unbounded."""
    if name in ("xyz", "vel", "rgba", "trail"):
        return True
    if name.endswith(("_xyz", "_vel", "_rgba", "_trail")):
        return True
    if "state" in name or "State" in name:
        return True
    return bool(_STATE_NODE_RE.match(name))


class _Surface:
    __slots__ = ("read", "write", "fmt")

    def __init__(self, read, write, fmt):
        self.read = read
        self.write = write
        self.fmt = fmt


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
        self._fb_cache = {}       # tuple(id(off)..) -> GPUFrameBuffer (MRT)
        self._vbuf_cache = {}     # count -> GPUVertBuf (attribute-less points draw)

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

    def _fmt(self, spec):
        return _FORMAT.get(str(spec.get("format", "rgba16f")).lower(), "RGBA16F")

    def _new_off(self, w, h, fmt):
        off = GPUOffScreen(w, h, format=fmt)
        with off.bind():                      # reference/05: FBOs cleared once to (0,0,0,0) at creation
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
        return off

    # ---- surface/pool setup ----------------------------------------------
    def setup(self, graph, uniforms):
        texspecs = dict(graph.textures)
        for p in graph.passes:
            for tid in list(p.get("inputs", {}).values()) + list(p.get("outputs", {}).values()):
                texspecs.setdefault(tid, {"width": "screen", "height": "screen"})
        # Resolve every logical texture's dims once (drives per-pass viewport, not the
        # physical slot size — a small pooled texture renders only its corner of a shared slot).
        self.tex_dims = {}
        for tid, spec in texspecs.items():
            self.tex_dims[tid] = (self.resolve_dim(spec.get("width", "screen"), uniforms),
                                  self.resolve_dim(spec.get("height", "screen"), uniforms))
        for tid, spec in texspecs.items():
            if tid.startswith("global_"):
                name = tid[len("global_"):]
                if name not in self.surfaces:
                    w, h = self.tex_dims[tid]
                    fmt = self._fmt(spec)
                    self.surfaces[name] = _Surface(self._new_off(w, h, fmt), self._new_off(w, h, fmt), fmt)
        # Each pooled texture gets a physical offscreen keyed by (phys, w, h, fmt). Textures that
        # share a phys but differ in LOGICAL size get SEPARATE physical textures — the allocator
        # guarantees same-phys lifetimes don't overlap, so this only costs memory. Sizing one slot
        # to the MAX envelope over aliased textures (the old approach) makes textureSize() report
        # the envelope, which silently corrupts any shader that derives atlas/UV coords from it:
        # flow3d's 64x4096 volume aliased with a 256x256 screen buffer inflated to 256x4096, so the
        # blend's `gl_FragCoord/textureSize` sampling stretched 4x in X and read unwritten columns
        # (vertical bars through the volume). Same-(phys,size) textures still share (real pooling).
        self.pool_key = {}
        for tid, spec in texspecs.items():
            if tid.startswith("global_"):
                continue
            w, h = self.tex_dims[tid]
            key = (graph.phys(tid), w, h, self._fmt(spec))
            self.pool_key[tid] = key
            if key not in self.pool:
                self.pool[key] = self._new_off(w, h, key[3])

    def frame_begin(self):
        for name, s in self.surfaces.items():
            self.frame_read[name] = s.read
            self.frame_write[name] = s.write

    def frame_persist(self):
        # end-of-frame double-buffer resolution (reference/04 §10.7). State surfaces persist
        # their within-frame final bindings (sims/particles continue from last frame's buffers).
        # Display/scratch surfaces SWAP read<->write (the frame-START persistent bindings, which
        # within-frame ping-pong left untouched): an odd within-frame write count works either
        # way, but an even count — lenia's clear+deposit — only stays fresh under the swap.
        for name, s in self.surfaces.items():
            if _is_state_surface(name):
                s.read = self.frame_read[name]
                s.write = self.frame_write[name]
            else:
                s.read, s.write = s.write, s.read

    def _read(self, tid, graph):
        if tid.startswith("global_"):
            return self.frame_read[tid[len("global_"):]]
        return self.pool[self.pool_key[tid]]

    def _write(self, tid, graph):
        if tid.startswith("global_"):
            return self.frame_write[tid[len("global_"):]]
        return self.pool[self.pool_key[tid]]

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
            frag, desc, vert, rel = _BLIT_FRAG, _BLIT_DESC, None, "blit"
        else:
            base = os.path.join(self.shaders_root, namespace, func, prog)
            frag = open(base + ".frag").read()
            desc = json.load(open(base + ".createinfo.json"))
            vert = open(base + ".vert").read() if desc.get("vertex") else None
            rel = namespace + "/" + func + "/" + prog
        key = (rel, tuple(sorted(defines.items())))
        if key not in self._shader_cache:
            if vert is not None:
                shader = shader_build.build_shader_vf(vert, frag, desc, defines)
            else:
                shader = shader_build.build_shader(frag, desc, defines)
            rev = {v: k for k, v in desc.get("uniformAliases", {}).items()}
            self._shader_cache[key] = (shader, desc, rev)
        return self._shader_cache[key]

    def _fs_batch(self, shader):
        if shader not in self._batch_cache:
            self._batch_cache[shader] = batch_for_shader(shader, 'TRIS', _FS_TRI)
        return self._batch_cache[shader]

    def _points_vbuf(self, count):
        vbo = self._vbuf_cache.get(count)
        if vbo is None:
            fmt = GPUVertFormat()
            fmt.attr_add(id="nm_dummy", comp_type='F32', len=1, fetch_mode='FLOAT')
            vbo = GPUVertBuf(len=count, format=fmt)
            vbo.attr_fill(id="nm_dummy", data=[0.0] * count)
            self._vbuf_cache[count] = vbo
        return vbo

    def _mrt_fb(self, write_offs):
        key = tuple(id(o) for o in write_offs)
        fb = self._fb_cache.get(key)
        if fb is None:
            fb = GPUFrameBuffer(color_slots=tuple(o.texture_color for o in write_offs))
            self._fb_cache[key] = fb
        return fb

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

    def _bind_inputs(self, shader, desc, rev, merged, inputs, graph):
        fields = desc.get("pushConstants", [])
        if desc.get("ubo"):
            # Over-128B block -> std140 UBO instead of push constants. Pack every field from
            # the merged engine+pass uniforms and bind one buffer. Hold a ref on self so the
            # GPUUniformBuf stays alive through the draw that follows this call.
            values = {name: merged.get(rev.get(name, name)) for _, name in fields}
            packed = std140.pack(fields, values)
            self._live_ubo = GPUUniformBuf(Buffer('FLOAT', len(packed), packed))
            shader.uniform_block(std140.INSTANCE, self._live_ubo)
        else:
            for ctype, name in fields:
                self._set_uniform(shader, ctype, name, merged.get(rev.get(name, name)))
        blk = desc.get("uniformBlock")
        if blk:
            # explicit std140 block (remap's zone-config UBO) bound alongside push constants. Pack
            # the logical zone uniforms into the array via the effect's layout (port of webgl2
            # packUniformsWithLayout). Hold the ref on self so it outlives the draw.
            slots = blk["members"][0][2]
            packed = std140.pack_with_layout(merged, blk["layout"], slots)
            self._live_block_ubo = GPUUniformBuf(Buffer('FLOAT', len(packed), packed))
            shader.uniform_block(blk["instance"], self._live_block_ubo)
        for slot, stype, name in desc.get("samplers", []):
            tid = inputs.get(rev.get(name, name))
            if tid is not None:
                shader.uniform_sampler(name, self._read(tid, graph).texture_color)

    # ---- pass execution ---------------------------------------------------
    def execute(self, p, graph, engine):
        pt = p.get("passType")
        if pt == "blit":
            compiled = self.compile(None, "blit", "blit", None)
            merged = {"resolution": [float(self.size), float(self.size)]}
            inputs = {"src": p["inputs"]["src"]}
        elif pt == "effect":
            compiled = self.compile(p.get("namespace"), p["func"], p["progName"], p.get("defines"))
            merged = dict(engine)
            merged.update(p.get("uniforms", {}))
            inputs = p.get("inputs", {})
        else:
            return
        mode = p.get("drawMode")
        if mode == "points":
            self._render_points(compiled, merged, inputs, p, graph, per_particle=1)
        elif mode == "billboards":
            self._render_points(compiled, merged, inputs, p, graph, per_particle=6, tris=True)
        else:
            self._render(compiled, merged, inputs, p, graph)

    def _resolve_outputs(self, desc, p, graph):
        """Resolve output offscreens in fragmentOut-slot order (MRT-aware), plus the LOGICAL
        (w,h) of the primary output. The viewport uses logical dims, not the physical slot
        size, so a small pooled texture (life's 8x8 forceMatrix) renders only its corner of a
        screen-sized shared slot — matching the reference's per-target viewport."""
        out_map = p.get("outputs", {})
        out_vals = list(out_map.values())
        fout = sorted(desc.get("fragmentOut", []), key=lambda x: x[0])
        offs, prim = [], None
        for idx, (_, _, fname) in enumerate(fout):
            tid = out_map.get(fname)
            if tid is None:                       # GLSL out name != graph output key
                if len(out_map) == 1:
                    tid = out_vals[0]
                elif idx < len(out_vals):
                    # MRT slot-position fallback: the descriptor's fragmentOut (sorted by slot) and
                    # the graph's outputs are both in declaration/slot order, so the Nth out maps to
                    # the Nth target. Fixes 3D render/precompute (`fragColor`@slot0 -> graph `color`),
                    # whose color MRT target was otherwise dropped -> empty volume -> black.
                    tid = out_vals[idx]
            if tid is not None:
                offs.append(self._write(tid, graph))
                if prim is None:
                    prim = tid
        if not offs:                                   # blit / unnamed single output
            prim = next(iter(out_map.values()))
            offs = [self._write(prim, graph)]
        lw, lh = self.tex_dims.get(prim, (self.size, self.size))
        return offs, lw, lh

    @staticmethod
    def _blend_mode(p):
        b = p.get("blend")
        if not b:
            return 'NONE'
        if isinstance(b, list):
            # Per-pass array blend [src, dst]. Blender's gpu module exposes presets only, so we
            # map the factor pairs the effects actually use to the matching preset:
            #   ['ONE','ONE']                 -> ADDITIVE_PREMULT (additive deposit)
            #   ['ONE','ONE_MINUS_SRC_ALPHA'] -> ALPHA_PREMULT    (premultiplied OVER)
            # (pointsBillboardRender's deposit_alpha uses the latter.)
            if b == ['ONE', 'ONE_MINUS_SRC_ALPHA']:
                return 'ALPHA_PREMULT'
            return 'ADDITIVE_PREMULT'
        # blend: true -> additive ONE/ONE.
        return 'ADDITIVE_PREMULT'

    def _render(self, compiled, merged, inputs, p, graph):
        shader, desc, rev = compiled
        write_offs, w, h = self._resolve_outputs(desc, p, graph)
        mrt = len(write_offs) > 1
        ctx = self._mrt_fb(write_offs).bind() if mrt else write_offs[0].bind()
        with ctx:
            gpu.state.viewport_set(0, 0, w, h)
            gpu.state.blend_set(self._blend_mode(p))
            shader.bind()
            self._bind_inputs(shader, desc, rev, merged, inputs, graph)
            self._fs_batch(shader).draw(shader)
            gpu.state.blend_set('NONE')

    def _render_points(self, compiled, merged, inputs, p, graph, per_particle=1, tris=False):
        shader, desc, rev = compiled
        offs, w, h = self._resolve_outputs(desc, p, graph)
        target = offs[0]
        # count='input' -> one primitive per agent texel (xyzTex dims product).
        src = inputs.get("xyzTex") or next(iter(inputs.values()))
        src_off = self._read(src, graph)
        count = src_off.width * src_off.height * per_particle
        with target.bind():
            gpu.state.viewport_set(0, 0, w, h)
            gpu.state.blend_set(self._blend_mode(p))
            shader.bind()
            self._bind_inputs(shader, desc, rev, merged, inputs, graph)
            batch = GPUBatch(type='TRIS' if tris else 'POINTS', buf=self._points_vbuf(count))
            batch.draw(shader)
            gpu.state.blend_set('NONE')

    def sync(self):
        """Force GPU command submission/completion. Blender batches draws within a single
        Python call without yielding to its event loop; an unsynced ping-pong loop of
        thousands of passes (navierStokes @ 1800 frames) overflows the command stream and
        the float state decays to NaN. A 1-px readback flushes the queue (this is why the
        sampling harness, which reads back periodically, stayed stable while a plain
        final-only read NaN'd). Cheap relative to a frame."""
        off = None
        if self.frame_read:
            off = next(iter(self.frame_read.values()))
        elif self.pool:
            off = next(iter(self.pool.values()))
        if off is None:
            return
        with off.bind():
            gpu.state.active_framebuffer_get().read_color(0, 0, 1, 1, 4, 0, 'FLOAT')

    # ---- readback ---------------------------------------------------------
    def read_surface(self, name):
        off = self.frame_read[name]
        w, h = off.width, off.height
        with off.bind():
            buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
        buf.dimensions = w * h * 4
        arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)[::-1]
        return np.round(np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)

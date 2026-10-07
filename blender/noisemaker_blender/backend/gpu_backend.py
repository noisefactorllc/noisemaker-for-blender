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
from contextlib import contextmanager

import gpu
import numpy as np
from gpu.types import (GPUOffScreen, GPUFrameBuffer, GPUVertFormat, GPUVertBuf, GPUBatch,
                       GPUUniformBuf, Buffer)
from gpu_extras.batch import batch_for_shader

from . import shader_build, std140
from ..runtime.diagnostics import DiagnosticCollector
from ..runtime.pipeline import (resolve_dimension, resolve_surface_format,
                                build_texture_pooling_plan)

_FS_TRI = {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]}
from .slab import _MAX_DRAW_SLAB, slab_ranges  # noqa: E402  (GPU-free helper)
_BLIT_FRAG = ("#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))),"
              " ivec2(0), textureSize((s),0)-ivec2(1)), 0))\n"
              "void main(){ fragColor = nmTex(src, gl_FragCoord.xy / resolution); }\n")
_BLIT_DESC = {"pushConstants": [["VEC2", "resolution"]], "samplers": [[0, "FLOAT_2D", "src"]],
              "fragmentOut": [[0, "VEC4", "fragColor"]], "uniformAliases": {}}

# (graph texture format map lives in runtime.pipeline — shared with the
# structured-format-fallback resolver; GPU-free)
# Precision rank: a pooled slot shared by mixed formats must hold the most demanding one.
_FMT_RANK = {"RGBA8": 1, "RGBA16F": 2, "RGBA32F": 3}

_WARNED_UNIFORMS = set()

_SCREEN_SPEC = {"width": "screen", "height": "screen"}
_VOLUME_SURFACE = re.compile(r"^global_vol[0-7]$")
_VOLUME_SURFACE_SPEC = {"width": 64, "height": 4096}
_DEFERRED_FREE = []  # GPU wrappers remain alive until their owning window returns.


def _window_context_token():
    # This is an RNA pointer check. Never query gpu.state or an active framebuffer
    # from a handler: Blender/Metal can crash before it raises a Python exception.
    import bpy
    window = getattr(bpy.context, "window", None)
    if window is None:
        raise RuntimeError("qualified Blender window GPU context required")
    return window.as_pointer()


@contextmanager
def _preserve_gpu_state():
    """Restore editor blend/viewport state after successful or failed GPU work."""
    blend = gpu.state.blend_get()
    viewport = gpu.state.viewport_get()
    try:
        yield
    finally:
        gpu.state.blend_set(blend)
        gpu.state.viewport_set(*viewport)


def _warn_uniform_once(name, ctype, value, detail="not set — value kept its shader default"):
    """Print the first failed/normalized uniform assignment per name, then stay quiet.

    A swallowed ValueError here means the uniform kept its default (usually zero).
    Most cases are benign — the shader compiler optimized the uniform out (e.g.
    gradient's `resolution`) — but the same swallow previously masked the all-black
    vec3-color defect, so the first occurrence is made visible in the log.
    """
    key = (name, ctype, detail.split(" —")[0])
    if key in _WARNED_UNIFORMS:
        return
    _WARNED_UNIFORMS.add(key)
    print("NMR WARN uniform %s (%s) %s — value=%r"
          % (name, ctype, detail, value))


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
    def __init__(self, shaders_root, size=256, *, width=None, height=None):
        self.context_token = _window_context_token()
        for owner in tuple(_DEFERRED_FREE):
            if owner.context_token == self.context_token:
                _DEFERRED_FREE.remove(owner)
                owner.free()
        self.shaders_root = shaders_root
        self.width = size if width is None else width
        self.height = size if height is None else height
        self.size = self.width  # square-API compatibility
        self.surfaces = {}        # surfaceName -> _Surface (offscreen pair), for global_*
        self.pool = {}            # phys_id -> GPUOffScreen, for pooled textures
        self.frame_read = {}      # surfaceName -> GPUOffScreen (current frame binding)
        self.frame_write = {}
        self._shader_cache = {}
        self._batch_cache = {}
        self._ubo_cache = {}
        self._fb_cache = {}       # tuple(id(off)..) -> GPUFrameBuffer (MRT)
        self._vbuf_cache = {}     # count -> GPUVertBuf (attribute-less points draw)
        self.external_inputs = {}
        # Queryable structured diagnostics for the historically-silent
        # unknown-dimension-form and unknown-format fallbacks.
        self.diagnostics = DiagnosticCollector()
        self._warned_dimension_fallbacks = set()
        self._warned_format_fallbacks = set()
        self.metrics = {"shader_compiles": 0, "shader_file_reads": 0,
                        "ubo_allocations": 0, "ubo_updates": 0}

    def assert_context(self):
        if _window_context_token() != self.context_token:
            raise RuntimeError("GPU context changed; recreate the render session")

    def _diagnostic_state(self):
        """Lazily-create the diagnostic state triple (collector, dimension
        dedup set, format dedup set). ``GpuBackend.__new__``-constructed
        backends skip ``__init__`` by design — blender/harness/
        test_backend_contract.py is deliberately GPU-free — so the resolvers
        must not assume ``__init__`` ran (review finding on aa3c53b: the
        harness's ``setup()`` hit resolve_dim first and raised
        AttributeError)."""
        state = getattr(self, "_diag_state", None)
        if state is None:
            # Seed from __init__ state when present so the collector identity
            # stays stable for real backends; __new__-built instances get a
            # fresh triple here.
            state = self._diag_state = (
                self.diagnostics if getattr(self, "diagnostics", None) is not None else DiagnosticCollector(),
                self._warned_dimension_fallbacks if getattr(self, "_warned_dimension_fallbacks", None) is not None else set(),
                self._warned_format_fallbacks if getattr(self, "_warned_format_fallbacks", None) is not None else set(),
            )
            self.diagnostics = state[0]
        return state

    def create_frame_export_queue(self, **_options):
        """Return no queue until Blender exposes non-blocking GPU readback primitives.

        Blender 5.1's public ``gpu.types`` provides synchronous ``read_color``/``GPUTexture.read``
        but no fence, pixel-buffer, or mapped-buffer API. Wrapping those reads in the generic queue
        would block during ``enqueue`` and violate the upstream asynchronous export contract.
        """
        return None

    def max_texture_size(self):
        """Return Blender's active GPU texture-dimension limit."""
        return gpu.capabilities.max_texture_size_get()

    # ---- dimension resolution (reference/04 §resolveDimension) -------------
    def resolve_dim(self, spec, uniforms, axis="width"):
        _, warned_dim, _ = self._diagnostic_state()
        screen_size = (getattr(self, "height", self.size) if axis == "height"
                       else getattr(self, "width", self.size))
        return resolve_dimension(spec, screen_size, uniforms,
                                 diagnostics=self.diagnostics,
                                 warned=warned_dim)

    def _fmt(self, spec):
        diag, _, warned_fmt = self._diagnostic_state()
        return resolve_surface_format(spec,
                                      diagnostics=diag,
                                      warned=warned_fmt)

    def _new_off(self, w, h, fmt):
        off = GPUOffScreen(w, h, format=fmt)
        try:
            with _preserve_gpu_state():
                with off.bind():              # reference/05: clear once to transparent
                    gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
        except Exception:
            off.free()
            raise
        return off

    # ---- surface/pool setup ----------------------------------------------
    def setup(self, graph, uniforms):
        texspecs = dict(graph.textures)
        for p in graph.passes:
            for tid in list(p.get("inputs", {}).values()) + list(p.get("outputs", {}).values()):
                if tid == "none":
                    continue
                # An unwritten volume surface keeps the native 64^3 atlas (64x4096);
                # write3d gives exported volumes their producer's spec.
                default = _VOLUME_SURFACE_SPEC if _VOLUME_SURFACE.match(tid) else _SCREEN_SPEC
                texspecs.setdefault(tid, dict(default))
        # Resolve every logical texture's dims once (drives per-pass viewport, not the
        # physical slot size — a small pooled texture renders only its corner of a shared slot).
        self.tex_dims = {}
        for tid, spec in texspecs.items():
            self.tex_dims[tid] = (self.resolve_dim(spec.get("width", "screen"), uniforms, "width"),
                                  self.resolve_dim(spec.get("height", "screen"), uniforms, "height"))
        for tid, spec in texspecs.items():
            if tid.startswith("global_"):
                name = tid[len("global_"):]
                w, h = self.tex_dims[tid]
                fmt = self._fmt(spec)
                existing = self.surfaces.get(name)
                if existing is not None:
                    if (existing.read.width == w and existing.read.height == h and
                        existing.write.width == w and existing.write.height == h and
                        existing.fmt == fmt):
                        continue
                    existing.read.free()
                    existing.write.free()
                    self.frame_read.pop(name, None)
                    self.frame_write.pop(name, None)
                    self._fb_cache.clear()
                self.surfaces[name] = _Surface(self._new_off(w, h, fmt), self._new_off(w, h, fmt), fmt)
        # Each pooled texture gets a physical offscreen keyed by (phys, w, h, fmt). Textures that
        # share a phys but differ in LOGICAL size get SEPARATE physical textures — the allocator
        # guarantees same-phys lifetimes don't overlap, so this only costs memory. Sizing one slot
        # to the MAX envelope over aliased textures (the old approach) makes textureSize() report
        # the envelope, which silently corrupts any shader that derives atlas/UV coords from it:
        # flow3d's 64x4096 volume aliased with a 256x256 screen buffer inflated to 256x4096, so the
        # blend's `gl_FragCoord/textureSize` sampling stretched 4x in X and read unwritten columns
        # (vertical bars through the volume). Same-(phys,size) textures still share (real pooling).
        # Physical slot sharing mirrors reference `Pipeline.buildTexturePoolingPlan`
        # (and upstream 95743621): only textures the plan marks poolable
        # (identical plain 2D specs, first touch a full-overwrite write, no
        # drawMode/blend/viewport-without-clear partial writes) share one
        # backend texture under the group's primary id; every excluded texture
        # gets its own standalone slot.
        self.texture_aliases = build_texture_pooling_plan(graph)
        self.pool_key = {}
        for tid, spec in texspecs.items():
            if tid.startswith("global_"):
                continue
            w, h = self.tex_dims[tid]
            # Pooled members share the storage texture created under the
            # group's primary id; every excluded texture keys by its own id,
            # so it owns a standalone slot even inside a shared phys group.
            if tid in self.texture_aliases:
                key = (graph.phys(self.texture_aliases[tid]), w, h, self._fmt(spec))
            else:
                key = (tid, w, h, self._fmt(spec))
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
        if tid in self.external_inputs:
            return self.external_inputs[tid]
        if tid.startswith("global_"):
            return self.frame_read[tid[len("global_"):]]
        return self.pool[self.pool_key[tid]]

    def set_external_inputs(self, frames):
        """Borrow caller-owned GPU textures for the next evaluation."""
        self.external_inputs = dict(frames)

    def _write(self, tid, graph):
        if tid.startswith("global_"):
            return self.frame_write[tid[len("global_"):]]
        return self.pool[self.pool_key[tid]]

    def swap_after_write(self, tid):
        if tid.startswith("global_"):
            n = tid[len("global_"):]
            self.frame_read[n], self.frame_write[n] = self.frame_write[n], self.frame_read[n]

    def free(self):
        try:
            self.assert_context()
        except RuntimeError:
            self.abandon()
            return
        if self in _DEFERRED_FREE:
            _DEFERRED_FREE.remove(self)
        for s in self.surfaces.values():
            s.read.free(); s.write.free()
        for off in self.pool.values():
            off.free()
        self.surfaces.clear(); self.pool.clear()
        self.frame_read.clear(); self.frame_write.clear()
        self._shader_cache.clear(); self._batch_cache.clear()
        self._ubo_cache.clear()
        self._fb_cache.clear(); self._vbuf_cache.clear()
        self.__dict__.pop("tex_dims", None)
        self.__dict__.pop("pool_key", None)
        self.__dict__.pop("texture_aliases", None)
        self.__dict__.pop("_live_ubo", None)
        self.__dict__.pop("_live_block_ubo", None)
        self.external_inputs.clear()

    def abandon(self):
        """Defer destruction when the GPU owner window is no longer current."""
        if self not in _DEFERRED_FREE:
            _DEFERRED_FREE.append(self)

    # ---- shaders ----------------------------------------------------------
    def compile(self, namespace, func, prog, defines):
        defines = defines or {}
        rel = "blit" if namespace is None and func == "blit" else (
            namespace + "/" + func + "/" + prog)
        key = (rel, tuple(sorted(defines.items())))
        cached = self._shader_cache.get(key)
        if cached is not None:
            return cached
        if namespace is None and func == "blit":
            frag, desc, vert = _BLIT_FRAG, _BLIT_DESC, None
        else:
            base = os.path.join(self.shaders_root, namespace, func, prog)
            with open(base + ".frag") as stream:
                frag = stream.read()
            with open(base + ".createinfo.json") as stream:
                desc = json.load(stream)
            vert = None
            if desc.get("vertex"):
                with open(base + ".vert") as stream:
                    vert = stream.read()
            self.metrics["shader_file_reads"] += 2 + int(vert is not None)
        if vert is not None:
            shader = shader_build.build_shader_vf(vert, frag, desc, defines)
        else:
            shader = shader_build.build_shader(frag, desc, defines)
        rev = {v: k for k, v in desc.get("uniformAliases", {}).items()}
        self._shader_cache[key] = (shader, desc, rev)
        self.metrics["shader_compiles"] += 1
        return self._shader_cache[key]

    def _update_ubo(self, shader, instance, packed):
        cache = getattr(self, "_ubo_cache", None)
        if cache is None:
            cache = self._ubo_cache = {}
        key = (id(shader), instance, len(packed))
        data = Buffer('FLOAT', len(packed), packed)
        ubo = cache.get(key)
        if ubo is None:
            ubo = GPUUniformBuf(data)
            cache[key] = ubo
            if hasattr(self, "metrics"):
                self.metrics["ubo_allocations"] += 1
        else:
            ubo.update(data)
            if hasattr(self, "metrics"):
                self.metrics["ubo_updates"] += 1
        return ubo

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
                # A vecN uniform rejects a sequence of the wrong length (e.g. a
                # 4-component color value for the declared `vec3 color1`): Blender
                # raises ValueError and the effect silently renders with default
                # (zero) colors — gradient came out all-black. Normalize any
                # sequence to exactly the declared component count.
                n = {"VEC2": 2, "VEC3": 3, "VEC4": 4}.get(ctype)
                if isinstance(value, str):
                    if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value) or n not in (3, 4):
                        raise TypeError("%s requires numeric components or a hex color" % name)
                    value = [int(value[index:index + 2], 16) / 255.0
                             for index in range(1, len(value), 2)]
                    if n == 4 and len(value) == 3:
                        value.append(1.0)
                if n is not None and not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
                    value = list(value)
                    if len(value) > n:
                        # Colors arrive as 4-component RGBA for a declared vec3 —
                        # the normal shape — but a genuine width mismatch would
                        # also land here, so the truncation is visible once.
                        _warn_uniform_once(name, ctype, value,
                                           "truncated — over-length value cut to the declared %d-component width" % n)
                        value = value[:n]
                shader.uniform_float(name, value)
            elif ctype == "INT":
                shader.uniform_int(name, int(value))
            elif ctype in ("IVEC2", "IVEC3", "IVEC4"):
                shader.uniform_int(name, [int(x) for x in value])
            elif ctype == "BOOL":
                shader.uniform_bool(name, [bool(value)])
        except ValueError:
            # Benign when the shader compiler optimized the uniform out (e.g.
            # gradient's `resolution`); visible once otherwise so a silently
            # dropped uniform can't masquerade as a correct render.
            _warn_uniform_once(name, ctype, value)

    def _bind_inputs(self, shader, desc, rev, merged, inputs, graph):
        fields = desc.get("pushConstants", [])
        if desc.get("ubo"):
            # Over-128B block -> std140 UBO instead of push constants. Pack every field from
            # the merged engine+pass uniforms and bind one buffer. Hold a ref on self so the
            # GPUUniformBuf stays alive through the draw that follows this call.
            values = {name: merged.get(rev.get(name, name)) for _, name in fields}
            packed = std140.pack(fields, values)
            self._live_ubo = self._update_ubo(shader, std140.INSTANCE, packed)
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
            self._live_block_ubo = self._update_ubo(shader, blk["instance"], packed)
            shader.uniform_block(blk["instance"], self._live_block_ubo)
        for slot, stype, name in desc.get("samplers", []):
            tid = inputs.get(rev.get(name, name))
            if tid is not None and tid != "none":
                shader.uniform_sampler(name, self._read(tid, graph).texture_color)

    # ---- pass execution ---------------------------------------------------
    def execute(self, p, graph, engine):
        pt = p.get("passType")
        if pt == "blit":
            compiled = self.compile(None, "blit", "blit", None)
            # The reference blit samples texture(src, v_texCoord): the whole source
            # maps onto the whole target, so the coordinate divides by the target's
            # size (a volume atlas is not screen-sized).
            target = next(iter(p.get("outputs", {}).values()), None)
            w, h = self.tex_dims.get(target, (getattr(self, "width", self.size),
                                              getattr(self, "height", self.size)))
            merged = {"resolution": [float(w), float(h)]}
            inputs = {"src": p["inputs"]["src"]}
        elif pt == "effect":
            compiled = self.compile(p.get("namespace"), p["func"], p["progName"], p.get("defines"))
            merged = dict(engine)
            merged.update(p.get("uniforms", {}))
            inputs = p.get("inputs", {})
        else:
            raise ValueError("unsupported pass type %r" % pt)
        mode = p.get("drawMode")
        if mode == "points":
            self._render_points(compiled, merged, inputs, p, graph, per_particle=1)
        elif mode == "billboards":
            self._render_points(compiled, merged, inputs, p, graph, per_particle=6, tris=True)
        elif mode == "triangles":
            self._render_triangles(compiled, merged, inputs, p, graph)
        elif mode is None:
            self._render(compiled, merged, inputs, p, graph)
        else:
            raise ValueError("unsupported draw mode %r" % mode)

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
        lw, lh = self.tex_dims.get(prim, (getattr(self, "width", self.size),
                                          getattr(self, "height", self.size)))
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

    def _resolve_pass_viewport_box(self, p, merged, default_w, default_h):
        vp = p.get("viewportResolved") or p.get("viewport")
        if not isinstance(vp, dict):
            return 0, 0, default_w, default_h
        vx_spec = vp.get("x", 0)
        vy_spec = vp.get("y", 0)
        w_spec = vp.get("w", vp.get("width"))
        h_spec = vp.get("h", vp.get("height"))
        # A viewportResolved box (set by runtime resolve_pass_viewport) already
        # holds concrete pixel ints — consume it directly. Re-resolving it here
        # clamped an authored 0 through resolve_dimension's max(1, ...) floor
        # and drew every viewport-spec pass at (1, 1) instead of (0, 0): the
        # leftmost column and the bottom GPU row of the 64x4096 volume-cache
        # atlas were silently unwritten (measured on the M4 host: box=(1,1,64,4096)).
        numeric = (isinstance(vx_spec, (int, float)) and not isinstance(vx_spec, bool) and
                   isinstance(vy_spec, (int, float)) and not isinstance(vy_spec, bool))
        if numeric:
            vx, vy = int(vx_spec), int(vy_spec)
        else:
            vx = self.resolve_dim(vx_spec, merged) if vp.get("x") is not None else 0
            vy = self.resolve_dim(vy_spec, merged) if vp.get("y") is not None else 0
        if isinstance(w_spec, (int, float)) and not isinstance(w_spec, bool) \
                and isinstance(h_spec, (int, float)) and not isinstance(h_spec, bool):
            return vx, vy, int(w_spec), int(h_spec)
        vw = self.resolve_dim(w_spec, merged) if w_spec is not None else default_w
        vh = self.resolve_dim(h_spec, merged) if h_spec is not None else default_h
        return int(vx), int(vy), int(vw), int(vh)

    def _render(self, compiled, merged, inputs, p, graph):
        shader, desc, rev = compiled
        write_offs, w, h = self._resolve_outputs(desc, p, graph)
        vx, vy, vw, vh = self._resolve_pass_viewport_box(p, merged, w, h)
        mrt = len(write_offs) > 1
        ctx = self._mrt_fb(write_offs).bind() if mrt else write_offs[0].bind()
        with _preserve_gpu_state():
            with ctx:
                if p.get("clear"):
                    gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
                gpu.state.blend_set(self._blend_mode(p))
                shader.bind()
                self._bind_inputs(shader, desc, rev, merged, inputs, graph)
                # Slab tall Metal viewports without changing gl_FragCoord.
                for slab_y, slab_h in slab_ranges(vy, vh):
                    gpu.state.viewport_set(vx, slab_y, vw, slab_h)
                    self._fs_batch(shader).draw(shader)

    def _render_points(self, compiled, merged, inputs, p, graph, per_particle=1, tris=False):
        shader, desc, rev = compiled
        offs, w, h = self._resolve_outputs(desc, p, graph)
        target = offs[0]
        vx, vy, vw, vh = self._resolve_pass_viewport_box(p, merged, w, h)
        # count='input' -> one primitive per agent texel (xyzTex dims product).
        src = inputs.get("xyzTex") or next(iter(inputs.values()))
        src_off = self._read(src, graph)
        count = src_off.width * src_off.height * per_particle
        with _preserve_gpu_state():
            with target.bind():
                if p.get("clear"):
                    gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
                gpu.state.viewport_set(vx, vy, vw, vh)
                gpu.state.blend_set(self._blend_mode(p))
                shader.bind()
                self._bind_inputs(shader, desc, rev, merged, inputs, graph)
                batch = GPUBatch(type='TRIS' if tris else 'POINTS', buf=self._points_vbuf(count))
                batch.draw(shader)

    def _render_triangles(self, compiled, merged, inputs, p, graph):
        shader, desc, rev = compiled
        offs, w, h = self._resolve_outputs(desc, p, graph)
        if len(offs) != 1:
            raise ValueError("mesh triangles require one color target")
        source = self._read(inputs["meshPositions"], graph)
        count = getattr(source, "vertex_count", None)
        if count is None:
            raise ValueError("mesh position input has no triangle vertex count")
        normal = self._read(inputs["meshNormals"], graph)
        if getattr(normal, "vertex_count", None) != count:
            raise ValueError("mesh position/normal vertex counts differ")
        vx, vy, vw, vh = self._resolve_pass_viewport_box(p, merged, w, h)
        old_depth_test = gpu.state.depth_test_get()
        old_depth_mask = gpu.state.depth_mask_get()
        try:
            with _preserve_gpu_state():
                with offs[0].bind():
                    gpu.state.active_framebuffer_get().clear(depth=1.0)
                    gpu.state.depth_test_set("LESS")
                    gpu.state.depth_mask_set(True)
                    gpu.state.viewport_set(vx, vy, vw, vh)
                    gpu.state.blend_set(self._blend_mode(p))
                    shader.bind()
                    self._bind_inputs(shader, desc, rev, merged, inputs, graph)
                    GPUBatch(type='TRIS', buf=self._points_vbuf(count)).draw(shader)
        finally:
            gpu.state.depth_test_set(old_depth_test)
            gpu.state.depth_mask_set(old_depth_mask)

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
        arr = self.read_surface_float(name)
        return np.round(np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)

    def read_surface_float(self, name):
        """Top-down scene-linear float32 pixels; preserve HDR and negative values."""
        off = self.frame_read[name]
        w, h = off.width, off.height
        with _preserve_gpu_state():
            with off.bind():
                buf = gpu.state.active_framebuffer_get().read_color(0, 0, w, h, 4, 0, 'FLOAT')
        buf.dimensions = w * h * 4
        arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)[::-1]
        return arr

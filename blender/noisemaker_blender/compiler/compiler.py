"""compiler.py -- Stage-5 graph assembly: ``compile_graph(source) -> dict``.

This is the back half of the reference pipeline. It ties the already-ported
stages together exactly as the reference ``shaders/src/runtime/compiler.js``
``compileGraph`` does, then applies the SAME normalisation the golden producer
``tools/export-graph.mjs`` applies before serialising. The result is the
*normalized render graph* -- byte-for-byte the JSON ``export-graph.mjs`` writes
to ``parity/out/<name>.graph.json`` and the object the addon's runtime
(``runtime/graph_loader.Graph``) consumes.

Pipeline (mirrors ``compileGraph``)::

    compilationResult = compile(source)        # lex -> parse -> validate
    if any error diagnostic: raise              # abort like the reference throw
    {passes, errors, programs, textureSpecs, renderSurface} = expand(compilationResult)
    if expand errors: raise
    allocations = allocate_resources(passes)
    graph = {
        id: hash_source(source), source,
        passes, programs, allocations,
        textures: extract_texture_specs(passes, options, textureSpecs),
        renderSurface, compiledAt: <dropped>
    }

Normalisation (mirrors ``export-graph.mjs`` ``normalizeGraph``)::

    {
      id, source, renderSurface,
      passes:      [normalize_pass(p) for p in passes],
      allocations: <Map -> object>,
      textures:    <Map -> object>,
      programs:    {id: {uniformLayout, defines}}    # source stripped
    }

The compile-time-define *promotion* (``noise.type=2 -> NOISE_TYPE:2`` moved out
of ``uniforms`` into ``defines``) is driven by a ``define_map`` built from the
effect registry -- the Python analogue of ``export-graph.mjs``'s walk over every
``effects/<ns>/<func>/definition.js`` collecting ``globals[key].define``.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

from .compile import compile
from .expander import expand
from .resources import allocate_resources
from . import registry


# ---------------------------------------------------------------------------
# define_map: "<namespace>.<func>" -> {globalKey: DEFINE_NAME}
#
# Mirrors export-graph.mjs bootstrapReference: for every effect, collect the
# globals declared with a ``define:`` field. normalize_pass promotes any such
# uniform into ``defines`` under its DEFINE name. The reference keeps these as
# plain uniforms in the compiled graph; the ports bind them by DEFINE name, so
# the normalized golden moves them.
#
# The per-effect mapping preserves the effect's ``globals`` key order (Python
# dict / json preserve insertion order), which is the promotion/insertion order
# of the resulting ``defines`` entries -- parity-critical for byte identity.
# ---------------------------------------------------------------------------
def _build_define_map():
    define_map = {}
    for definition in registry.all_effects():
        namespace = definition.get("namespace")
        func = definition.get("func")
        if not namespace or not func:
            continue
        globals_ = definition.get("globals")
        if not globals_:
            continue
        defs = {}
        for key, spec in globals_.items():
            if isinstance(spec, dict) and spec.get("define"):
                defs[key] = spec["define"]
        if defs:
            define_map["%s.%s" % (namespace, func)] = defs
    return define_map


# ---------------------------------------------------------------------------
# Graph assembly (port of compiler.js compileGraph + its helpers)
# ---------------------------------------------------------------------------
def hash_source(source):
    """Port of compiler.js ``hashSource`` (djb2-ish 32-bit, base36).

    Reproduces the JS exactly::

        hash = ((hash << 5) - hash) + charCode   // 32-bit signed wraparound
        hash = hash & hash                        // force to int32
        return hash.toString(36)

    Python ints are unbounded, so we mask to 32 bits and re-interpret as a
    signed int32 after each step, then base36-encode with the JS sign/letter
    convention (lowercase, leading '-' for negatives).
    """
    hash_val = 0
    for ch in source:
        char = ord(ch)
        hash_val = ((hash_val << 5) - hash_val) + char
        # Convert to 32-bit signed integer (JS `hash & hash` / bitwise ops).
        hash_val &= 0xFFFFFFFF
        if hash_val >= 0x80000000:
            hash_val -= 0x100000000
    return _to_base36(hash_val)


def _to_base36(n):
    """JS ``Number.prototype.toString(36)`` for an integer (lowercase, signed)."""
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    negative = n < 0
    n = -n if negative else n
    out = []
    while n:
        n, rem = divmod(n, 36)
        out.append(digits[rem])
    if negative:
        out.append("-")
    return "".join(reversed(out))


def extract_texture_specs(passes, options, texture_specs=None):
    """Port of compiler.js ``extractTextureSpecs``.

    Builds the ``textures`` map: first every effect-defined spec (including
    ``global_`` textures) from the expander's ``texture_specs`` -- preserving the
    original ``width``/``height`` dimension specs (which may be objects like
    ``{"param": ..., "default": 256}``) and defaulting to ``'screen'`` /
    ``rgba16f`` -- then every pass output texture not already defined (skipping
    ``global_`` ones, which are handled via surfaces).

    Insertion order = texture_specs order, then first-seen pass-output order;
    this is parity-critical (Map insertion order -> JSON key order).
    """
    if texture_specs is None:
        texture_specs = {}
    textures = {}

    # First: all effect-defined texture specs (incl. global_ textures).
    for tex_id, effect_spec in texture_specs.items():
        spec = {
            # Preserve original dimension specs; 'screen' default for resizing.
            "width": _or(effect_spec.get("width"), "screen"),
            "height": _or(effect_spec.get("height"), "screen"),
            "format": _or(effect_spec.get("format"), "rgba16f"),
            # copyDst required so chain-handoff/external writes can target it.
            "usage": ["render", "sample", "copySrc", "copyDst"],
        }
        # Handle 3D textures.
        if effect_spec.get("is3D"):
            spec["depth"] = _or(effect_spec.get("depth"), _or(effect_spec.get("width"), 64))
            spec["is3D"] = True
            spec["usage"] = ["storage", "sample", "copySrc", "copyDst"]
        textures[tex_id] = spec

    # Then: output textures from passes that aren't already defined.
    for pass_ in passes:
        outputs = pass_.get("outputs")
        if outputs:
            for tex_id in outputs.values():
                # Skip global_ textures (surfaces) and already-defined ones.
                if tex_id.startswith("global_"):
                    continue
                if tex_id in textures:
                    continue
                # 'screen' enables dynamic resizing.
                textures[tex_id] = {
                    "width": "screen",
                    "height": "screen",
                    "format": "rgba16f",
                    "usage": ["render", "sample", "copySrc", "copyDst"],
                }

    return textures


def _or(value, default):
    """JS ``value || default`` truthiness (None / 0 / '' / False / empty -> default).

    Mirrors ``effectSpec.width || 'screen'``. An object (non-empty dict) is
    truthy and kept; an empty dict is falsy in JS but never occurs for a real
    dimension spec -- still, ``{} or x`` would return x in Python too, matching.
    """
    return value if value else default


def compile_graph(source, options=None):
    """Compile DSL ``source`` into the NORMALIZED render graph dict.

    Equivalent to ``normalizeGraph(compileGraph(source))`` -- i.e. the exact
    object ``tools/export-graph.mjs`` writes. Raises on compile-time errors
    (mirroring the reference ``ERR_COMPILATION_FAILED`` throw) or expansion
    errors (``ERR_EXPANSION_FAILED``).

    Parameters
    ----------
    source : str
        DSL source code.
    options : dict, optional
        Compilation options. ``shaderOverrides`` is forwarded to ``expand``.
        (export-graph calls ``compileGraph(dsl)`` with no options, so the gate
        path uses defaults.)

    Returns
    -------
    dict
        The normalized graph: ``{id, source, renderSurface, passes,
        allocations, textures, programs}``.

    Raises
    ------
    CompilationError
        When ``compile`` reports any ``severity == 'error'`` diagnostic.
    ExpansionError
        When ``expand`` returns a non-empty ``errors`` list.
    """
    if options is None:
        options = {}

    # Stage 1: Parse + validate.
    compilation_result = compile(source)

    diagnostics = compilation_result.get("diagnostics") or []
    if diagnostics:
        errors = [d for d in diagnostics if d.get("severity") == "error"]
        if errors:
            raise CompilationError(diagnostics)

    # Stage 2: Expand logical graph into render passes.
    expanded = expand(compilation_result, {"shaderOverrides": options.get("shaderOverrides")})
    passes = expanded.get("passes") or []
    expand_errors = expanded.get("errors") or []
    programs = expanded.get("programs") or {}
    texture_specs = expanded.get("textureSpecs") or {}
    render_surface = expanded.get("renderSurface")

    if expand_errors:
        raise ExpansionError(expand_errors)

    # Stage 3: Allocate resources (texture pooling).
    allocations = allocate_resources(passes)

    # Stage 4: Build the (un-normalized) execution graph, then normalize it to
    # the golden shape (export-graph.mjs drops id/source/compiledAt only for the
    # serialized fields it doesn't need -- but normalizeGraph KEEPS id/source and
    # drops compiledAt and the raw program source). We build directly in the
    # normalized shape.
    graph = {
        "id": hash_source(source),
        "source": source,
        "passes": passes,
        "programs": programs,
        "allocations": allocations,
        "textures": extract_texture_specs(passes, options, texture_specs),
        "renderSurface": render_surface,
    }

    return _normalize_graph(graph)


# ---------------------------------------------------------------------------
# Normalisation (port of export-graph.mjs normalizeGraph + helpers)
# ---------------------------------------------------------------------------
_DEFINE_MAP = None


def _define_map():
    global _DEFINE_MAP
    if _DEFINE_MAP is None:
        _DEFINE_MAP = _build_define_map()
    return _DEFINE_MAP


def _derive_prog_name(pass_):
    """Port of ``deriveProgName``: bare program basename.

    Strips the ``node_<n>_`` prefix and any trailing ``__name_value`` define
    suffix from ``pass.program``. Falls back to ``effectFunc`` then ``'main'``.
    """
    raw = pass_.get("program") or ""
    s = raw
    node_id = pass_.get("nodeId")
    node_prefix = ("%s_" % node_id) if node_id else None
    if node_prefix and s.startswith(node_prefix):
        s = s[len(node_prefix):]
    # Strip a trailing define-variant suffix (a run of ``__name_value`` groups).
    suffix_idx = s.find("__")
    if suffix_idx > 0:
        s = s[:suffix_idx]
    return s or pass_.get("effectFunc") or "main"


def _defines_for_pass(pass_, programs):
    """Port of ``definesForPass``: compile-time defines from the program entry.

    The resolved program (``programs[pass.program]``) carries ``defines``
    (NOISE_TYPE, LOOP_OFFSET, ...). For this addon's effect definitions (no
    shader source -> only ``blit`` is in ``programs``) this is normally ``{}``
    and the defines arrive via the define_map promotion below.
    """
    program = programs.get(pass_.get("program")) if pass_.get("program") is not None else None
    d = program.get("defines") if isinstance(program, dict) else None
    if not d:
        return {}
    return dict(d)


def _normalize_pass(pass_, programs, define_map):
    """Port of ``normalizePass``: shape a render pass to the golden form."""
    is_blit = (
        pass_.get("type") == "blit"
        or pass_.get("program") == "blit"
        or pass_.get("effectFunc") == "blit"
    )

    out = {
        "id": pass_.get("id"),
        "passType": "blit" if is_blit else "effect",
        "namespace": None if is_blit else _coalesce(pass_.get("effectNamespace")),
        "func": "blit" if is_blit else _coalesce(pass_.get("effectFunc")),
        "progName": "blit" if is_blit else _derive_prog_name(pass_),
        "program": _coalesce(pass_.get("program")),
        "defines": {} if is_blit else _defines_for_pass(pass_, programs),
        "inputs": pass_.get("inputs") or {},
        "outputs": pass_.get("outputs") or {},
        "uniforms": dict(pass_.get("uniforms") or {}),
        "uniformSpecs": pass_.get("uniformSpecs") or {},
    }

    # Promote compile-time define globals (noise.type=2 -> NOISE_TYPE:2) from
    # uniforms into defines by DEFINE name.
    if not is_blit and define_map:
        dm = define_map.get("%s.%s" % (pass_.get("effectNamespace"), pass_.get("effectFunc")), {})
        for global_key, define_name in dm.items():
            if global_key in out["uniforms"]:
                v = out["uniforms"][global_key]
                if isinstance(v, bool):
                    out["defines"][define_name] = 1 if v else 0
                else:
                    out["defines"][define_name] = int(_trunc(float(v)))
                del out["uniforms"][global_key]

    # Optional execution modifiers -- only emit when present (key order matches
    # the reference: drawMode, count, countUniform, drawBuffers, blend, repeat,
    # clear), so the "absent vs null vs 0" model holds.
    if "drawMode" in pass_:
        out["drawMode"] = pass_["drawMode"]
    if "count" in pass_:
        out["count"] = pass_["count"]
    if "countUniform" in pass_:
        out["countUniform"] = pass_["countUniform"]
    if "drawBuffers" in pass_:
        out["drawBuffers"] = pass_["drawBuffers"]
    if "blend" in pass_:
        out["blend"] = pass_["blend"]
    if "repeat" in pass_:
        out["repeat"] = pass_["repeat"]
    if "clear" in pass_:
        out["clear"] = pass_["clear"]

    # Metadata.
    out["effectKey"] = _coalesce(pass_.get("effectKey"))
    out["nodeId"] = _coalesce(pass_.get("nodeId"))
    if "stepIndex" in pass_:
        out["stepIndex"] = pass_["stepIndex"]
    if "inheritsVolumeSize" in pass_:
        out["inheritsVolumeSize"] = pass_["inheritsVolumeSize"]
    out["scopedParams"] = pass_.get("scopedParams") or None

    return out


def _normalize_programs(programs):
    """Port of ``normalizePrograms``: strip shader source.

    Keeps only ``{uniformLayout: prog.uniformLayout || {}, defines: prog.defines
    || {}}``. NOTE the ``|| {}`` (JS truthiness): a missing key, ``None`` or an
    empty dict all fall through to ``{}`` -- this differs from the prior stage's
    ``check_expanded.normalize_programs`` (which used ``|| null`` for the layout,
    matching the *expanded* golden); the *graph* golden uses ``|| {}``.
    """
    out = {}
    for prog_id, prog in (programs or {}).items():
        if isinstance(prog, dict):
            layout = prog.get("uniformLayout")
            defines = prog.get("defines")
        else:
            layout = None
            defines = None
        out[prog_id] = {
            "uniformLayout": layout if layout else {},
            "defines": defines if defines else {},
        }
    return out


def _normalize_graph(graph):
    """Port of ``normalizeGraph``: top-level golden shaping.

    Output key order: id, source, renderSurface, passes, allocations, textures,
    programs (parity-critical for byte identity).
    """
    programs = graph.get("programs") or {}
    define_map = _define_map()
    return {
        "id": graph.get("id"),
        "source": graph.get("source"),
        "renderSurface": _coalesce(graph.get("renderSurface")),
        "passes": [_normalize_pass(p, programs, define_map) for p in (graph.get("passes") or [])],
        "allocations": dict(graph.get("allocations") or {}),
        "textures": dict(graph.get("textures") or {}),
        "programs": _normalize_programs(programs),
    }


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _coalesce(value):
    """JS ``value ?? null`` (nullish coalescing): only None/absent -> None.

    Unlike ``||``, this keeps falsy-but-present values (0, '', False). The
    reference uses ``?? null`` for namespace/func/program/effectKey/nodeId/
    renderSurface/scopedParams default-to-null.
    """
    return value if value is not None else None


def _trunc(x):
    """JS ``Math.trunc`` -- toward zero. ``int(x)`` in Python truncates toward
    zero for floats, matching."""
    return int(x)


class CompilationError(Exception):
    """Raised when ``compile`` reports error-severity diagnostics.

    Carries the full diagnostics list (mirrors the reference thrown object
    ``{code: 'ERR_COMPILATION_FAILED', diagnostics}``).
    """

    def __init__(self, diagnostics):
        self.code = "ERR_COMPILATION_FAILED"
        self.diagnostics = diagnostics
        errs = [d for d in diagnostics if d.get("severity") == "error"]
        msg = "; ".join(d.get("message", "compilation error") for d in errs) or "compilation failed"
        super().__init__(msg)


class ExpansionError(Exception):
    """Raised when ``expand`` returns errors.

    Carries the error list (mirrors ``{code: 'ERR_EXPANSION_FAILED', errors}``).
    """

    def __init__(self, errors):
        self.code = "ERR_EXPANSION_FAILED"
        self.errors = errors
        msg = "; ".join(
            (e.get("message") if isinstance(e, dict) else str(e)) for e in errors
        ) or "expansion failed"
        super().__init__(msg)

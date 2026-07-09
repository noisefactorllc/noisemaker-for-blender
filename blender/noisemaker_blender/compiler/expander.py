"""expander.py -- Stage-2 (expand) port of shaders/src/runtime/expander.js.

Expands the Logical Graph (``plans`` from ``compile()``) into a Render Graph
(``passes``). This is a faithful port of the reference ``expand()``; it consumes
the output of :func:`noisemaker_blender.compiler.compile.compile` and the effect
definitions from :mod:`noisemaker_blender.compiler.registry`.

    expand(compilation_result, options=None) -> {
        passes,         # list of pass dicts (the render graph)
        errors,         # list of {message, ...} (empty when clean)
        programs,       # program-name -> shader/program descriptor
        textureSpecs,   # virtual-texture-id -> {width, height, format, is3D?, depth?}
        renderSurface,  # surface name to present (e.g. 'o1'), or None
    }

Parity notes (intentional, do NOT "fix"):

* The reference ``Effect`` constructor silently drops ``outputXyz``/``outputVel``/
  ``outputRgba``/``outputTex``/``externalTexture`` for ``new Effect({...})``
  effects, so the registry's ``points/*`` agent defs OMIT those fields. The
  ``effectDef.outputXyz`` branches below are therefore DEAD for those effects;
  agent/particle state propagates via the pass ``outputs`` (e.g. ``global_xyz``)
  plus the ``createsParticleTextures = effectDef.textures.global_xyz`` scoping
  path (the ``_node_<n>`` / ``_chain_<n>`` suffixing). This is reproduced exactly
  given the omitted fields -- the dead branches are kept verbatim for fidelity.

* In this addon, the normalized effect-definition JSON files carry NO ``shaders``
  key (the GLSL/WGSL source lives in the transpiled shaders, not in the compiler
  metadata). The ``shadersSource`` program-collection branch is therefore inert
  for every catalog effect: ``programs`` ends up containing only the ``blit``
  copy program (registered by inline/final ``write`` blits). Each pass still
  references its variant program name (``node_<n>_<prog>[__DEFINE_value...]``) so
  the downstream assembler can wire the real shader. This matches the goldens.

* Palette ``COLOR`` data is NOT needed here. The expander only wires the
  classicNoisedeck palette *uniforms* (paletteOffset/Amp/Freq/Phase/Mode) via
  :func:`palette_expansion.expand_palette`, which carries the small uniform table
  verbatim from the reference. The actual palette color tables live in the
  shaders, not in the compiler -- the expander never touches them.

stdlib-only and self-contained: imports only sibling compiler modules + stdlib.
"""

from __future__ import annotations

import re

from .registry import get_effect
from .lang_data import STD_ENUMS
from .palette_expansion import expand_palette

# /^(?:o|vol|geo|xyz|vel|rgba)[0-7]$/
_SURFACE_REF_PATTERN = re.compile(r"^(?:o|vol|geo|xyz|vel|rgba)[0-7]$")
# /^global_(xyz|vel|rgba|points_trail|life_data)$/
_PARTICLE_TEX_PATTERN = re.compile(r"^global_(xyz|vel|rgba|points_trail|life_data)$")

# Sentinel distinguishing JS ``undefined`` (missing key) from JS ``null`` (None).
_UNDEFINED = object()


# Surface-arg "kinds" that name a texture rather than carry a scalar value. Used
# in three places to decide whether an arg is a texture binding vs a uniform.
# 'pipeline' is the validator's default-value fallback for a surface global
# whose default (e.g. "inputTex") isn't itself a resolvable surface reference
# (see filter/lighting's heightMap) -- it must be skipped here too, or its
# {"kind":"pipeline",...} dict leaks into pass_obj["uniforms"] as a bogus value.
_TEXTURE_ARG_KINDS = ("temp", "output", "source", "feedback", "vol", "geo", "xyz", "vel", "rgba", "pipeline")


def _is_texture_arg(arg):
    """Port of ``isTextureArg``."""
    return arg is not None and isinstance(arg, dict) and arg.get("kind") in _TEXTURE_ARG_KINDS


def _truthy(value):
    """JS truthiness: ``{}`` and ``[]`` are TRUTHY (non-null objects).

    Differs from Python's bool() for empty containers. Falsy values mirror JS:
    ``None``/``undefined`` sentinel, ``False``, ``0``/``0.0``, and ``""``.
    Notably an empty dict/list is truthy, so ``if (effectDef.globals)`` enters
    even when globals is ``{}`` -- which is observable via the ``uniformSpecs``
    initialization (the reference sets ``pass.uniformSpecs = {}`` for an effect
    whose globals is an empty object).
    """
    if value is _UNDEFINED or value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value != ""
    return True  # dicts, lists, and other objects are truthy (even when empty)


def _is_object_arg(arg):
    """JS ``arg !== null && typeof arg === 'object'`` -> a dict (incl. list)."""
    return arg is not None and isinstance(arg, (dict, list))


def _has_own(obj, key):
    """JS ``Object.prototype.hasOwnProperty.call(obj, key)``."""
    return isinstance(obj, dict) and key in obj


def _get(obj, key, default=_UNDEFINED):
    """JS property read returning the sentinel for a missing key (``undefined``)."""
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return default


def _defined(value):
    """JS ``value !== undefined`` for our sentinel convention."""
    return value is not _UNDEFINED


def _ensure_blit_program(programs):
    """Register the blit copy program if not already present (verbatim source)."""
    if "blit" in programs:
        return
    programs["blit"] = {
        "fragment": (
            "#version 300 es\n"
            "            precision highp float;\n"
            "            in vec2 v_texCoord;\n"
            "            uniform sampler2D src;\n"
            "            out vec4 fragColor;\n"
            "            void main() {\n"
            "                fragColor = texture(src, v_texCoord);\n"
            "            }"
        ),
        "wgsl": (
            "\n"
            "            struct FragmentInput {\n"
            "                @builtin(position) position: vec4<f32>,\n"
            "                @location(0) uv: vec2<f32>,\n"
            "            }\n"
            "\n"
            "            @group(0) @binding(0) var src: texture_2d<f32>;\n"
            "            @group(0) @binding(1) var srcSampler: sampler;\n"
            "\n"
            "            @fragment\n"
            "            fn main(in: FragmentInput) -> @location(0) vec4<f32> {\n"
            "                let uv = vec2<f32>(in.uv.x, 1.0 - in.uv.y);\n"
            "                return textureSample(src, srcSampler, uv);\n"
            "            }\n"
            "        "
        ),
        "fragmentEntryPoint": "main",
    }


def _register_passthrough(node_id, texture_map, cur, cur3d, cur_geo, cur_xyz, cur_vel, cur_rgba):
    """Register passthrough outputs for a node that doesn't generate passes."""
    if cur:
        texture_map["%s_out" % node_id] = cur
    if cur3d:
        texture_map["%s_out3d" % node_id] = cur3d
    if cur_geo:
        texture_map["%s_outGeo" % node_id] = cur_geo
    if cur_xyz:
        texture_map["%s_outXyz" % node_id] = cur_xyz
    if cur_vel:
        texture_map["%s_outVel" % node_id] = cur_vel
    if cur_rgba:
        texture_map["%s_outRgba" % node_id] = cur_rgba


def _resolve_global_surface_ref(name):
    """Resolve a surface-ref string to a ``global_`` prefixed name."""
    if name == "none":
        return "none"
    if name.startswith("global_"):
        return name
    if _SURFACE_REF_PATTERN.match(name):
        return "global_%s" % name
    return name


def _resolve_enum(path):
    """Resolve a dotted enum path (e.g. ``channel.r``) to its numeric value.

    Mirrors the reference ``resolveEnum``: walk ``stdEnums`` by dotted parts and
    return the terminal node's ``value`` (or ``None`` if not resolvable). The
    ported ``STD_ENUMS`` stores leaves as ``{"type": "Number", "value": N}``.
    """
    parts = path.split(".")
    node = STD_ENUMS
    for part in parts:
        if isinstance(node, dict) and node.get(part):
            node = node[part]
        else:
            return None
    if isinstance(node, dict) and node.get("value") is not None:
        return node["value"]
    return None


def expand(compilation_result, options=None):
    """Expand the logical graph (``plans``) into render passes. See module docs."""
    if options is None:
        options = {}
    shader_overrides = options.get("shaderOverrides") or {}
    passes = []
    errors = []
    programs = {}
    texture_specs = {}      # nodeId_texName -> {width, height, format, is3D?, depth?}
    texture_map = {}        # logical_id -> virtual_texture_id
    last_written_surface = None  # Track the last surface written to

    plans = compilation_result.get("plans") or []

    # 1. Expand each plan into passes
    for plan in plans:
        # Each plan is a chain of effects. Track the "current" output texture as
        # we traverse the chain.
        current_input = None       # 2D pipeline texture
        current_input3d = None     # 3D pipeline texture (for volumetric effects)
        current_input_geo = None   # Geometry buffer texture (normals + depth)
        current_input_xyz = None   # Agent position texture (for particle effects)
        current_input_vel = None   # Agent velocity texture (for particle effects)
        current_input_rgba = None  # Agent color texture (for particle effects)
        last_inline_write_target = None  # Last inline write target (skip redundant final blit)

        # Current particle pipeline scope. When an effect creates particle
        # textures (declares global_xyz), it becomes the scope owner; all global_
        # particle textures get suffixed with this id for isolation.
        current_particle_pipeline_id = None

        # Pipeline uniforms accumulate from upstream effects for downstream use.
        pipeline_uniforms = {}
        chain_scope_id = "chain_%d" % plans.index(plan)

        chain = plan.get("chain") or []
        for step in chain:
            step_args = step.get("args")  # may be None
            step_builtin = step.get("builtin")
            step_op = step.get("op")
            step_temp = step.get("temp")
            step_from = step.get("from")

            # --- builtin _read: just sets the current input -----------------
            if step_builtin and step_op == "_read":
                tex = _get(step_args, "tex") if isinstance(step_args, dict) else _UNDEFINED
                if _defined(tex) and tex and tex.get("kind") == "output":
                    current_input = "global_%s" % tex.get("name")  # e.g. 'global_o0'
                node_id = "node_%s" % step_temp
                texture_map["%s_out" % node_id] = current_input
                continue

            if step_builtin and step_op == "_read3d":
                tex3d = _get(step_args, "tex3d") if isinstance(step_args, dict) else _UNDEFINED
                geo = _get(step_args, "geo") if isinstance(step_args, dict) else _UNDEFINED
                if _defined(tex3d) and tex3d:
                    if isinstance(tex3d, dict) and (tex3d.get("kind") == "vol" or tex3d.get("type") == "VolRef"):
                        current_input3d = "global_%s" % tex3d.get("name")  # e.g. 'global_vol0'
                    else:
                        current_input3d = (tex3d.get("name") if isinstance(tex3d, dict) else None) or tex3d
                if _defined(geo) and geo:
                    if isinstance(geo, dict) and (geo.get("kind") == "geo" or geo.get("type") == "GeoRef"):
                        current_input_geo = "global_%s" % geo.get("name")  # e.g. 'global_geo0'
                    else:
                        current_input_geo = (geo.get("name") if isinstance(geo, dict) else None) or geo
                node_id = "node_%s" % step_temp
                if current_input3d:
                    texture_map["%s_out3d" % node_id] = current_input3d
                if current_input_geo:
                    texture_map["%s_outGeo" % node_id] = current_input_geo
                continue

            # --- builtin _write: output to a surface AND pass through --------
            if step_builtin and step_op == "_write":
                tex = _get(step_args, "tex") if isinstance(step_args, dict) else _UNDEFINED
                if _defined(tex) and tex and current_input:
                    if tex.get("name") != "none":
                        target_surface = "global_%s" % tex.get("name")
                        if current_input != target_surface:
                            node_id = "node_%s" % step_temp
                            blit_pass = {
                                "id": "%s_write_blit" % node_id,
                                "program": "blit",
                                "type": "render",
                                "inputs": {"src": current_input},
                                "outputs": {"color": target_surface},
                                "uniforms": {},
                                "nodeId": node_id,
                                "stepIndex": step_temp,
                            }
                            passes.append(blit_pass)
                            _ensure_blit_program(programs)
                            last_written_surface = tex.get("name")
                            last_inline_write_target = {"kind": tex.get("kind"), "name": tex.get("name")}
                    node_id = "node_%s" % step_temp
                    texture_map["%s_out" % node_id] = current_input
                continue

            # --- builtin _write3d: write 3D volume + geometry to surfaces ----
            if step_builtin and step_op == "_write3d":
                tex3d = _get(step_args, "tex3d") if isinstance(step_args, dict) else _UNDEFINED
                geo = _get(step_args, "geo") if isinstance(step_args, dict) else _UNDEFINED
                node_id = "node_%s" % step_temp

                if _defined(tex3d) and tex3d and tex3d.get("name") != "none" and current_input3d:
                    target_vol = "global_%s" % tex3d.get("name")
                    if current_input3d != target_vol:
                        blit_pass = {
                            "id": "%s_write3d_vol_blit" % node_id,
                            "program": "blit",
                            "type": "render",
                            "inputs": {"src": current_input3d},
                            "outputs": {"color": target_vol},
                            "uniforms": {},
                            "nodeId": node_id,
                            "stepIndex": step_temp,
                        }
                        passes.append(blit_pass)
                        _ensure_blit_program(programs)

                if _defined(geo) and geo and geo.get("name") != "none" and current_input_geo:
                    target_geo = "global_%s" % geo.get("name")
                    if current_input_geo != target_geo:
                        geo_blit_pass = {
                            "id": "%s_write3d_geo_blit" % node_id,
                            "program": "blit",
                            "type": "render",
                            "inputs": {"src": current_input_geo},
                            "outputs": {"color": target_geo},
                            "uniforms": {},
                            "nodeId": node_id,
                            "stepIndex": step_temp,
                        }
                        passes.append(geo_blit_pass)

                texture_map["%s_out" % node_id] = current_input
                texture_map["%s_out3d" % node_id] = current_input3d
                texture_map["%s_outGeo" % node_id] = current_input_geo
                continue

            # --- subchain begin/end markers: passthrough metadata nodes ------
            if step_builtin and step_op == "_subchain_begin":
                _register_passthrough("node_%s" % step_temp, texture_map, current_input, current_input3d,
                                      current_input_geo, current_input_xyz, current_input_vel, current_input_rgba)
                continue
            if step_builtin and step_op == "_subchain_end":
                _register_passthrough("node_%s" % step_temp, texture_map, current_input, current_input3d,
                                      current_input_geo, current_input_xyz, current_input_vel, current_input_rgba)
                continue

            # Clear lastInlineWriteTarget when we process any non-write step.
            last_inline_write_target = None

            # --- _skip flag: pass through current input unchanged ------------
            if isinstance(step_args, dict) and step_args.get("_skip") is True:
                _register_passthrough("node_%s" % step_temp, texture_map, current_input, current_input3d,
                                      current_input_geo, current_input_xyz, current_input_vel, current_input_rgba)
                continue

            effect_name = step_op
            effect_def = get_effect(effect_name)

            if not effect_def:
                errors.append({"message": "Effect '%s' not found" % effect_name, "step": step})
                continue

            effect_textures = effect_def.get("textures")
            effect_textures3d = effect_def.get("textures3d")
            effect_globals = effect_def.get("globals")
            effect_passes = effect_def.get("passes") or []

            # Helper to scope particle textures to current pipeline.
            def scope_particle_tex(tex_name):
                if not current_particle_pipeline_id:
                    return tex_name
                if _PARTICLE_TEX_PATTERN.match(tex_name):
                    return "%s_%s" % (tex_name, current_particle_pipeline_id)
                return tex_name

            # Helper to scope global state textures to chain level. Particle
            # scoping takes priority; all other global_ textures get chain scoping.
            def scope_chain_tex(tex_name):
                particle_result = scope_particle_tex(tex_name)
                if particle_result != tex_name:
                    return particle_result
                if tex_name.startswith("global_"):
                    return "%s_%s" % (tex_name, chain_scope_id)
                return tex_name

            node_id = "node_%s" % step_temp

            # Track scoped params for this node's particle/chain textures, in
            # insertion order (mirrors JS Map). orig -> scoped.
            scoped_param_map = {}

            # Does this effect CREATE particle textures (declares global_xyz in
            # textures)? Only the creator starts a new pipeline scope.
            creates_particle_textures = bool(effect_textures and effect_textures.get("global_xyz"))
            if creates_particle_textures:
                current_particle_pipeline_id = node_id
                current_input_xyz = None
                current_input_vel = None
                current_input_rgba = None

            # Compile-time defines: globals with ``define: 'MACRO'`` become
            # #defines baked into the shader; their value feeds the program cache
            # key so each variant gets its own compiled program.
            compile_time_defines = {}
            if _truthy(effect_globals):
                sorted_global_names = sorted(effect_globals.keys())
                for global_name in sorted_global_names:
                    d = effect_globals[global_name]
                    if not d or not d.get("define"):
                        continue
                    value = _get(d, "default")
                    if isinstance(step_args, dict) and _has_own(step_args, global_name):
                        arg_val = step_args[global_name]
                        if arg_val is not None and isinstance(arg_val, dict) and "value" in arg_val:
                            value = arg_val["value"]
                        else:
                            value = arg_val
                    if d.get("type") == "member" and isinstance(value, str):
                        resolved = _resolve_enum(value)
                        if resolved is not None:
                            value = resolved
                    if _defined(value) and value is not None:
                        compile_time_defines[d["define"]] = value

            # Deterministic suffix for the program cache key (Object.entries order).
            program_define_suffix = "".join(
                "__%s_%s" % (k, _js_value_str(v)) for k, v in compile_time_defines.items()
            )

            # Collect programs -- check per-step shader overrides first (keyed by
            # step.temp). Effect JSONs carry no ``shaders``, so this is normally
            # inert; only blit (from write) ends up in ``programs``.
            step_overrides = _get(shader_overrides, step_temp)
            shaders_source = step_overrides if _defined(step_overrides) and step_overrides else effect_def.get("shaders")

            if shaders_source:
                uniform_layouts = effect_def.get("uniformLayouts")
                for prog_name, shaders in shaders_source.items():
                    unique_prog_name = "%s_%s%s" % (node_id, prog_name, program_define_suffix)
                    if unique_prog_name not in programs:
                        program_layout = None
                        if uniform_layouts and prog_name in uniform_layouts:
                            program_layout = uniform_layouts[prog_name]
                        else:
                            program_layout = effect_def.get("uniformLayout")
                        entry = dict(shaders)
                        entry["uniformLayout"] = program_layout
                        entry["defines"] = dict(compile_time_defines)
                        programs[unique_prog_name] = entry

            # --- Collect 2D texture specs -----------------------------------
            if _truthy(effect_textures):
                for tex_name, spec in effect_textures.items():
                    is_particle_tex = bool(_PARTICLE_TEX_PATTERN.match(tex_name))
                    should_scope_as_particle = is_particle_tex and current_particle_pipeline_id
                    should_scope_as_chain = tex_name.startswith("global_") and not is_particle_tex

                    if tex_name.startswith("global_"):
                        if should_scope_as_particle:
                            virtual_tex_id = "%s_%s" % (tex_name, current_particle_pipeline_id)
                        else:
                            virtual_tex_id = "%s_%s" % (tex_name, chain_scope_id)
                    else:
                        virtual_tex_id = "%s_%s" % (node_id, tex_name)

                    def dim_references_param(dim):
                        return (isinstance(dim, dict) and dim is not None and
                                ("param" in dim or "screenDivide" in dim))

                    spec_width = spec.get("width") if isinstance(spec, dict) else None
                    spec_height = spec.get("height") if isinstance(spec, dict) else None
                    has_param_ref = dim_references_param(spec_width) or dim_references_param(spec_height)
                    resolved_spec = dict(spec) if isinstance(spec, dict) else spec
                    should_scope_params = (
                        should_scope_as_particle or should_scope_as_chain or
                        (current_particle_pipeline_id and not tex_name.startswith("global_")) or
                        has_param_ref
                    )
                    if should_scope_params:
                        scope_suffix = current_particle_pipeline_id if should_scope_as_particle else chain_scope_id

                        def scope_dim_spec(dim_spec):
                            if isinstance(dim_spec, dict) and "param" in dim_spec:
                                original_param = dim_spec["param"]
                                scoped_param = "%s_%s" % (original_param, scope_suffix)
                                scoped_param_map[original_param] = scoped_param
                                new_dim = dict(dim_spec)
                                new_dim["param"] = scoped_param
                                return new_dim
                            if isinstance(dim_spec, dict) and "screenDivide" in dim_spec:
                                original_param = dim_spec["screenDivide"]
                                scoped_param = "%s_%s" % (original_param, scope_suffix)
                                scoped_param_map[original_param] = scoped_param
                                new_dim = dict(dim_spec)
                                new_dim["screenDivide"] = scoped_param
                                return new_dim
                            return dim_spec

                        resolved_spec["width"] = scope_dim_spec(spec_width)
                        resolved_spec["height"] = scope_dim_spec(spec_height)
                    texture_specs[virtual_tex_id] = resolved_spec

            # --- Collect 3D texture specs -----------------------------------
            if _truthy(effect_textures3d):
                for tex_name, spec in effect_textures3d.items():
                    if tex_name.startswith("global_"):
                        virtual_tex_id = scope_chain_tex(tex_name)
                    else:
                        virtual_tex_id = "%s_%s" % (node_id, tex_name)
                    new_spec = dict(spec) if isinstance(spec, dict) else {}
                    new_spec["is3D"] = True
                    texture_specs[virtual_tex_id] = new_spec

            # --- Resolve inputs from step.from ------------------------------
            if step_from is not None:
                prev_node_id = "node_%s" % step_from
                current_input = texture_map.get("%s_out" % prev_node_id)

            # --- Process globals BEFORE passes (downstream inheritance) ------
            if _truthy(effect_globals):
                for global_name, d in effect_globals.items():
                    if d.get("uniform") and _defined(_get(d, "default")):
                        # Skip if already set from upstream (preserve inheritance).
                        # JS: ``if (pipelineUniforms[def.uniform] !== undefined)``.
                        if pipeline_uniforms.get(d["uniform"], _UNDEFINED) is not _UNDEFINED:
                            continue
                        val = d["default"]
                        if d.get("type") == "member" and isinstance(val, str):
                            resolved = _resolve_enum(val)
                            if resolved is not None:
                                val = resolved
                        pipeline_uniforms[d["uniform"]] = val

                    # surface-type globals with colorModeUniform: set colorMode
                    # from the default when the surface param isn't provided.
                    if d.get("type") == "surface" and d.get("colorModeUniform"):
                        if not (isinstance(step_args, dict) and _has_own(step_args, global_name)):
                            is_none = d.get("default") == "none"
                            pipeline_uniforms[d["colorModeUniform"]] = 0 if is_none else 1

            # --- Process step.args (user values) into pipeline_uniforms ------
            color_mode_controlled_uniforms = set()

            # FIRST PASS: surface args -> colorModeControlledUniforms
            if isinstance(step_args, dict):
                for arg_name, arg in step_args.items():
                    if _is_texture_arg(arg):
                        global_def = effect_globals.get(arg_name) if effect_globals else None
                        if global_def and global_def.get("colorModeUniform"):
                            is_none = arg.get("name") == "none"
                            pipeline_uniforms[global_def["colorModeUniform"]] = 0 if is_none else 1
                            color_mode_controlled_uniforms.add(global_def["colorModeUniform"])

            # SECOND PASS: non-surface args
            if isinstance(step_args, dict):
                for arg_name, arg in step_args.items():
                    is_object_arg = _is_object_arg(arg)
                    if _is_texture_arg(arg):
                        continue

                    uniform_name = arg_name
                    if effect_globals and effect_globals.get(arg_name) and effect_globals[arg_name].get("uniform"):
                        uniform_name = effect_globals[arg_name]["uniform"]

                    if uniform_name in color_mode_controlled_uniforms:
                        continue

                    if (uniform_name == "volumeSize" and current_input3d and
                            pipeline_uniforms.get("volumeSize", _UNDEFINED) is not _UNDEFINED):
                        continue

                    if is_object_arg and isinstance(arg, dict) and _get(arg, "value") is not _UNDEFINED:
                        resolved_value = arg["value"]
                    else:
                        resolved_value = arg
                    pipeline_uniforms[uniform_name] = resolved_value

            # --- Expand passes ----------------------------------------------
            for i in range(len(effect_passes)):
                pass_def = effect_passes[i]
                pass_id = "%s_pass_%d" % (node_id, i)
                program_name = "%s_%s%s" % (node_id, pass_def.get("program"), program_define_suffix)

                pass_obj = {
                    "id": pass_id,
                    "program": program_name,
                    "entryPoint": pass_def.get("entryPoint", _UNDEFINED),
                    "drawMode": pass_def.get("drawMode", _UNDEFINED),
                    "drawBuffers": pass_def.get("drawBuffers", _UNDEFINED),
                    "count": pass_def.get("count", _UNDEFINED),
                    "countUniform": pass_def.get("countUniform", _UNDEFINED),
                    "repeat": pass_def.get("repeat", _UNDEFINED),
                    "blend": pass_def.get("blend", _UNDEFINED),
                    "workgroups": pass_def.get("workgroups", _UNDEFINED),
                    "storageBuffers": pass_def.get("storageBuffers", _UNDEFINED),
                    "storageTextures": pass_def.get("storageTextures", _UNDEFINED),
                    "inputs": {},
                    "outputs": {},
                    "uniforms": {},
                }

                # Metadata so downstream consumers can map passes -> effect defs.
                pass_obj["effectKey"] = effect_name
                pass_obj["effectFunc"] = effect_def.get("func") or effect_name
                pass_obj["effectNamespace"] = effect_def.get("namespace") if effect_def.get("namespace") is not None else None
                pass_obj["nodeId"] = node_id
                pass_obj["stepIndex"] = step_temp

                if current_input3d and pipeline_uniforms.get("volumeSize", _UNDEFINED) is not _UNDEFINED:
                    pass_obj["inheritsVolumeSize"] = True

                # Start with pipeline uniforms inherited from upstream effects.
                pass_obj["uniforms"] = dict(pipeline_uniforms)

                # Initialize uniforms with defaults only if not already set.
                if _truthy(effect_globals):
                    for d in effect_globals.values():
                        if d.get("uniform") and _defined(_get(d, "default")):
                            if pass_obj["uniforms"].get(d["uniform"], _UNDEFINED) is not _UNDEFINED:
                                continue
                            val = d["default"]
                            if d.get("type") == "member" and isinstance(val, str):
                                resolved = _resolve_enum(val)
                                if resolved is not None:
                                    val = resolved
                            pass_obj["uniforms"][d["uniform"]] = val
                            pipeline_uniforms[d["uniform"]] = val

                # uniformSpecs for percentage-based automation scaling.
                if _truthy(effect_globals):
                    pass_obj["uniformSpecs"] = {}
                    for arg_name, d in effect_globals.items():
                        uniform_name = d.get("uniform") or arg_name
                        if d.get("type") in ("float", "int") and not d.get("choices"):
                            pass_obj["uniformSpecs"][uniform_name] = {
                                "min": d["min"] if d.get("min") is not None else 0,
                                "max": d["max"] if d.get("max") is not None else 100,
                            }

                # Map Uniforms from step.args.
                if isinstance(step_args, dict):
                    for arg_name, arg in step_args.items():
                        is_object_arg = _is_object_arg(arg)
                        if _is_texture_arg(arg):
                            continue

                        uniform_name = arg_name
                        if effect_globals and effect_globals.get(arg_name) and effect_globals[arg_name].get("uniform"):
                            uniform_name = effect_globals[arg_name]["uniform"]

                        if _truthy(effect_globals):
                            is_controlled = False
                            for global_def in effect_globals.values():
                                if global_def.get("colorModeUniform") == uniform_name:
                                    is_controlled = True
                                    break
                            if is_controlled:
                                continue

                        if (uniform_name == "volumeSize" and current_input3d and
                                pipeline_uniforms.get("volumeSize", _UNDEFINED) is not _UNDEFINED):
                            continue

                        if is_object_arg and isinstance(arg, dict) and _get(arg, "value") is not _UNDEFINED:
                            resolved_value = arg["value"]
                        else:
                            resolved_value = arg
                        pass_obj["uniforms"][uniform_name] = resolved_value
                        pipeline_uniforms[uniform_name] = resolved_value

                # Map pass-level uniforms from effect definition.
                pass_def_uniforms = pass_def.get("uniforms")
                if _truthy(pass_def_uniforms):
                    for uniform_name, global_ref in pass_def_uniforms.items():
                        if pipeline_uniforms.get(uniform_name, _UNDEFINED) is not _UNDEFINED:
                            pass_obj["uniforms"][uniform_name] = pipeline_uniforms[uniform_name]
                        elif pipeline_uniforms.get(global_ref, _UNDEFINED) is not _UNDEFINED:
                            pass_obj["uniforms"][uniform_name] = pipeline_uniforms[global_ref]
                        elif effect_globals and effect_globals.get(global_ref):
                            global_def = effect_globals[global_ref]
                            if _defined(_get(global_def, "default")):
                                val = global_def["default"]
                                if global_def.get("type") == "member" and isinstance(val, str):
                                    resolved = _resolve_enum(val)
                                    if resolved is not None:
                                        val = resolved
                                pass_obj["uniforms"][uniform_name] = val

                # Expand classicNoisedeck palette index into dependent uniforms.
                if _truthy(effect_globals):
                    for arg_name, global_def in effect_globals.items():
                        if global_def.get("type") != "palette":
                            continue
                        uniform_name = global_def.get("uniform") or arg_name
                        index = pass_obj["uniforms"].get(uniform_name, _UNDEFINED)
                        if not (isinstance(index, (int, float)) and not isinstance(index, bool)):
                            continue
                        expanded = expand_palette(index)
                        if not expanded:
                            continue
                        for u_name, u_value in expanded.items():
                            if u_name in pass_obj["uniforms"]:
                                pass_obj["uniforms"][u_name] = list(u_value) if isinstance(u_value, list) else u_value
                                pipeline_uniforms[u_name] = pass_obj["uniforms"][u_name]

                # Map Inputs.
                pass_def_inputs = pass_def.get("inputs")
                if _truthy(pass_def_inputs):
                    for uniform_name, tex_ref in pass_def_inputs.items():
                        is_pipeline_input = (
                            tex_ref == "inputTex" or
                            (tex_ref.startswith("o") and _is_int_str(tex_ref[1:]))
                        )
                        is_pipeline_input3d = tex_ref == "inputTex3d"
                        is_pipeline_input_geo = tex_ref == "inputGeo"
                        is_pipeline_input_xyz = tex_ref == "inputXyz"
                        is_pipeline_input_vel = tex_ref == "inputVel"
                        is_pipeline_input_rgba = tex_ref == "inputRgba"

                        if is_pipeline_input:
                            pass_obj["inputs"][uniform_name] = current_input or tex_ref
                        elif is_pipeline_input3d:
                            pass_obj["inputs"][uniform_name] = current_input3d or tex_ref
                        elif is_pipeline_input_geo:
                            pass_obj["inputs"][uniform_name] = current_input_geo or tex_ref
                        elif is_pipeline_input_xyz:
                            pass_obj["inputs"][uniform_name] = current_input_xyz or tex_ref
                        elif is_pipeline_input_vel:
                            pass_obj["inputs"][uniform_name] = current_input_vel or tex_ref
                        elif is_pipeline_input_rgba:
                            pass_obj["inputs"][uniform_name] = current_input_rgba or tex_ref
                        elif tex_ref == "noise":
                            pass_obj["inputs"][uniform_name] = "global_noise"
                        elif tex_ref == "midiNoteGrid":
                            pass_obj["inputs"][uniform_name] = "midiNoteGrid"
                        elif tex_ref == "feedback" or tex_ref == "selfTex":
                            if plan.get("write"):
                                pw = plan["write"]
                                out_name = pw["name"] if isinstance(pw, dict) else pw
                                out_kind = (pw.get("kind") if isinstance(pw, dict) else None) or "output"
                                prefix = "feedback" if out_kind == "feedback" else "global"
                                pass_obj["inputs"][uniform_name] = "%s_%s" % (prefix, out_name)
                            else:
                                pass_obj["inputs"][uniform_name] = current_input or "global_inputTex"
                        elif effect_def.get("externalTexture") and tex_ref == effect_def.get("externalTexture"):
                            pass_obj["inputs"][uniform_name] = "%s_step_%s" % (tex_ref, step_temp)
                        elif isinstance(step_args, dict) and _has_own(step_args, tex_ref):
                            arg = step_args[tex_ref]
                            if arg is None:
                                continue
                            if isinstance(arg, dict) and arg.get("kind") == "temp":
                                pass_obj["inputs"][uniform_name] = texture_map.get("node_%s_out" % arg.get("index"))
                            elif isinstance(arg, dict) and arg.get("kind") == "pipeline" and arg.get("name") in ("inputTex", "inputColor"):
                                pass_obj["inputs"][uniform_name] = current_input or arg.get("name")
                            elif isinstance(arg, dict) and arg.get("kind") in ("output", "source", "vol", "geo", "xyz", "vel", "rgba"):
                                pass_obj["inputs"][uniform_name] = "none" if arg.get("name") == "none" else "global_%s" % arg.get("name")
                            elif isinstance(arg, str):
                                pass_obj["inputs"][uniform_name] = _resolve_global_surface_ref(arg)
                        elif effect_globals and effect_globals.get(tex_ref) and _defined(_get(effect_globals[tex_ref], "default")):
                            default_val = effect_globals[tex_ref]["default"]
                            if default_val == "none":
                                pass_obj["inputs"][uniform_name] = "none"
                            elif default_val == "inputTex" or default_val == "inputColor":
                                pass_obj["inputs"][uniform_name] = current_input or default_val
                            elif isinstance(default_val, str) and _SURFACE_REF_PATTERN.match(default_val):
                                pass_obj["inputs"][uniform_name] = "global_%s" % default_val
                            elif isinstance(default_val, str) and default_val.startswith("global_"):
                                pass_obj["inputs"][uniform_name] = scope_chain_tex(default_val)
                            else:
                                pass_obj["inputs"][uniform_name] = default_val
                        elif tex_ref.startswith("global_"):
                            pass_obj["inputs"][uniform_name] = scope_chain_tex(tex_ref)
                        elif tex_ref == "outputTex":
                            pass_obj["inputs"][uniform_name] = "%s_out" % node_id
                        else:
                            pass_obj["inputs"][uniform_name] = "%s_%s" % (node_id, tex_ref)

                # Map Outputs.
                pass_def_outputs = pass_def.get("outputs")
                if _truthy(pass_def_outputs):
                    for attachment, tex_ref in pass_def_outputs.items():
                        if tex_ref == "outputTex":
                            is_last_step = step is chain[len(chain) - 1]
                            is_last_pass = i == len(effect_passes) - 1
                            if is_last_step and is_last_pass and plan.get("write"):
                                pw = plan["write"]
                                out_name = pw["name"] if isinstance(pw, dict) else pw
                                out_kind = (pw.get("kind") if isinstance(pw, dict) else None) or "output"
                                prefix = "feedback" if out_kind == "feedback" else "global"
                                virtual_tex = "%s_%s" % (prefix, out_name)
                                last_written_surface = out_name
                            else:
                                virtual_tex = "%s_out" % node_id
                            texture_map[virtual_tex] = virtual_tex
                            texture_map["%s_out" % node_id] = virtual_tex
                        elif tex_ref == "outputTex3d":
                            virtual_tex = "%s_out3d" % node_id
                            texture_map["%s_out3d" % node_id] = virtual_tex
                        elif tex_ref == "outputXyz":
                            virtual_tex = "%s_outXyz" % node_id
                            texture_map["%s_outXyz" % node_id] = virtual_tex
                        elif tex_ref == "outputVel":
                            virtual_tex = "%s_outVel" % node_id
                            texture_map["%s_outVel" % node_id] = virtual_tex
                        elif tex_ref == "outputRgba":
                            virtual_tex = "%s_outRgba" % node_id
                            texture_map["%s_outRgba" % node_id] = virtual_tex
                        elif tex_ref == "inputTex3d":
                            virtual_tex = current_input3d or "%s_inputTex3d" % node_id
                        elif tex_ref == "inputGeo":
                            virtual_tex = current_input_geo or "%s_inputGeo" % node_id
                        elif tex_ref == "inputXyz":
                            virtual_tex = current_input_xyz or "%s_inputXyz" % node_id
                        elif tex_ref == "inputVel":
                            virtual_tex = current_input_vel or "%s_inputVel" % node_id
                        elif tex_ref == "inputRgba":
                            virtual_tex = current_input_rgba or "%s_inputRgba" % node_id
                        elif tex_ref.startswith("global_"):
                            virtual_tex = scope_chain_tex(tex_ref)
                        elif tex_ref.startswith("feedback_"):
                            virtual_tex = tex_ref
                        else:
                            virtual_tex = "%s_%s" % (node_id, tex_ref)
                        pass_obj["outputs"][attachment] = virtual_tex

                # Propagate scoped param uniforms for texture sizing.
                for original_param, scoped_param in scoped_param_map.items():
                    if pass_obj["uniforms"].get(original_param, _UNDEFINED) is not _UNDEFINED:
                        pass_obj["uniforms"][scoped_param] = pass_obj["uniforms"][original_param]
                        pipeline_uniforms[scoped_param] = pass_obj["uniforms"][original_param]

                if len(scoped_param_map) > 0:
                    pass_obj["scopedParams"] = dict(scoped_param_map)

                # Drop sentinel (JS-undefined) keys so the emitted pass matches a
                # JSON.stringify of the reference object (undefined keys omitted).
                _strip_undefined(pass_obj)

                passes.append(pass_obj)

            # Update currentInput for the next step in the chain.
            current_input = texture_map.get("%s_out" % node_id)

            # Explicit outputTex passthrough property.
            if effect_def.get("outputTex") and not current_input:
                internal_tex_name = effect_def["outputTex"]
                if internal_tex_name == "inputTex":
                    if step_from is not None:
                        prev_node_id = "node_%s" % step_from
                        prev_output = texture_map.get("%s_out" % prev_node_id)
                        if prev_output:
                            texture_map["%s_out" % node_id] = prev_output
                            current_input = prev_output
                else:
                    virtual_tex_id = (scope_chain_tex(internal_tex_name)
                                      if internal_tex_name.startswith("global_")
                                      else "%s_%s" % (node_id, internal_tex_name))
                    texture_map["%s_out" % node_id] = virtual_tex_id
                    current_input = virtual_tex_id

            # Update currentInput3d/xyz/vel/rgba from produced outputs.
            out3d = texture_map.get("%s_out3d" % node_id)
            if out3d:
                current_input3d = out3d
            out_xyz = texture_map.get("%s_outXyz" % node_id)
            if out_xyz:
                current_input_xyz = out_xyz
            out_vel = texture_map.get("%s_outVel" % node_id)
            if out_vel:
                current_input_vel = out_vel
            out_rgba = texture_map.get("%s_outRgba" % node_id)
            if out_rgba:
                current_input_rgba = out_rgba

            # Explicit outputTex3d passthrough property.
            if effect_def.get("outputTex3d") and not out3d:
                internal_tex_name = effect_def["outputTex3d"]
                if internal_tex_name == "inputTex3d":
                    if current_input3d:
                        texture_map["%s_out3d" % node_id] = current_input3d
                else:
                    virtual_tex_id = (scope_chain_tex(internal_tex_name)
                                      if internal_tex_name.startswith("global_")
                                      else "%s_%s" % (node_id, internal_tex_name))
                    texture_map["%s_out3d" % node_id] = virtual_tex_id
                    current_input3d = virtual_tex_id

            # Explicit outputGeo property.
            if effect_def.get("outputGeo"):
                geo_tex_name = effect_def["outputGeo"]
                if geo_tex_name == "inputGeo":
                    if current_input_geo:
                        texture_map["%s_outGeo" % node_id] = current_input_geo
                else:
                    virtual_geo_id = "%s_%s" % (node_id, geo_tex_name)
                    texture_map["%s_outGeo" % node_id] = virtual_geo_id
                    current_input_geo = virtual_geo_id

            # Explicit agent-state output properties (DEAD for the agent effects;
            # see module docstring -- kept verbatim for fidelity).
            if effect_def.get("outputXyz") and not out_xyz:
                tex_name = effect_def["outputXyz"]
                if tex_name == "inputXyz":
                    if current_input_xyz:
                        texture_map["%s_outXyz" % node_id] = current_input_xyz
                else:
                    virtual_id = (scope_chain_tex(tex_name) if tex_name.startswith("global_")
                                  else "%s_%s" % (node_id, tex_name))
                    texture_map["%s_outXyz" % node_id] = virtual_id
                    current_input_xyz = virtual_id
            if effect_def.get("outputVel") and not out_vel:
                tex_name = effect_def["outputVel"]
                if tex_name == "inputVel":
                    if current_input_vel:
                        texture_map["%s_outVel" % node_id] = current_input_vel
                else:
                    virtual_id = (scope_chain_tex(tex_name) if tex_name.startswith("global_")
                                  else "%s_%s" % (node_id, tex_name))
                    texture_map["%s_outVel" % node_id] = virtual_id
                    current_input_vel = virtual_id
            if effect_def.get("outputRgba") and not out_rgba:
                tex_name = effect_def["outputRgba"]
                if tex_name == "inputRgba":
                    if current_input_rgba:
                        texture_map["%s_outRgba" % node_id] = current_input_rgba
                else:
                    virtual_id = (scope_chain_tex(tex_name) if tex_name.startswith("global_")
                                  else "%s_%s" % (node_id, tex_name))
                    texture_map["%s_outRgba" % node_id] = virtual_id
                    current_input_rgba = virtual_id

        # Handle the final output of the chain (.write(o0)).
        if plan.get("write") and current_input:
            pw = plan["write"]
            out_name = pw["name"] if isinstance(pw, dict) else pw
            last_written_surface = out_name

            already_written = (
                last_inline_write_target and
                last_inline_write_target.get("kind") == "output" and
                last_inline_write_target.get("name") == out_name
            )
            if already_written:
                continue

            target_surface = "global_%s" % out_name
            if current_input != target_surface:
                blit_pass = {
                    "id": "final_blit_%s" % out_name,
                    "program": "blit",
                    "type": "render",
                    "inputs": {"src": current_input},
                    "outputs": {"color": target_surface},
                    "uniforms": {},
                }
                passes.append(blit_pass)
                # NOTE: the reference does NOT call ensureBlitProgram() here. The
                # blit program is registered by the inline _write path; a chain
                # that reaches the final blit without an inline write still has a
                # 'blit'-program pass but no 'blit' program entry -- reproduced.

    # Determine the render surface.
    if compilation_result.get("render"):
        render_surface = compilation_result["render"]
    elif last_written_surface:
        render_surface = last_written_surface
    else:
        errors.append({"message": "No render surface specified and no write() found - add render(oN) or write(oN)"})
        render_surface = None

    return {
        "passes": passes,
        "errors": errors,
        "programs": programs,
        "textureSpecs": texture_specs,
        "renderSurface": render_surface,
    }


def _is_int_str(s):
    """JS ``!isNaN(parseInt(s))`` for the ``oN`` pipeline-input check.

    ``parseInt`` reads a leading integer (any base-10 digits, optional sign) and
    ignores trailing junk; it returns NaN only when there is no leading integer.
    """
    if not isinstance(s, str) or s == "":
        return False
    i = 0
    if s[0] in "+-":
        i = 1
    return i < len(s) and s[i].isdigit()


def _js_value_str(v):
    """Stringify a define value the way JS template literals do (for cache keys).

    Booleans become ``true``/``false``; everything else uses ``str``. Numbers in
    the corpus are ints, so this matches; floats would print like Python, but no
    define value in the catalog is a float.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _strip_undefined(obj):
    """Remove keys whose value is the JS-``undefined`` sentinel (in place).

    Mirrors ``JSON.stringify`` dropping ``undefined``-valued properties, so the
    emitted pass dict has exactly the keys the reference object serializes.
    """
    for key in [k for k, val in obj.items() if val is _UNDEFINED]:
        del obj[key]

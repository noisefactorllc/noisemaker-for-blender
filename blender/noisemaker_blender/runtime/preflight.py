"""Effect preflight — static, side-effect-free analysis of an effect definition
against device capabilities (GAP-016; reference commit 12b4d74fb4f2).

Reference `shaders/src/runtime/preflight.js` adds `preflightEffect()`, which
statically reports — before any pipeline initialization or compilation —

    {
      backends: { webgl2: {authorable, reasons}, webgpu: {authorable, reasons} },
      formatChanges: [{ texture, pass, from, to, budget }],
      clamps: [{ texture, field, requested, limit }]
    }

Ported here following that structure, adapted to the port's actual runtime (the
same truthfulness contract as the GAP-006/GAP-008 dispositions):

- The port has a single rendering backend (Blender's `gpu` module), so the
  per-backend verdict map carries one `blender` entry instead of the
  reference's `webgl2`/`webgpu` pair. Authorability means "the backend's own
  compile step would find a source": a program is authorable iff its shader
  bucket has a transpiled `.frag` body (`frag`/`glsl`/`fragment` truthy), the
  same field family the port's `GpuBackend.compile()` consumes. Without shader
  information (`shaders` absent or empty) the source check is SKIPPED —
  availability is unknown, never invented.
- MRT draw-buffer limit (`maxDrawBuffers`) and the MRT color-byte budget
  (`maxColorBytesPerSample`, predicting `Pipeline.applyMrtFormatBudget()`'s
  trailing rgba32f -> rgba16f demotions via the shared `mrt_format_bytes`)
  are mirrored verbatim. The port's Blender runtime applies no byte-budget
  demotion (Blender offscreens are allocated per texture with no
  per-sample color-byte limit exposed to Python), so the port's own pipeline
  wrapper never supplies `maxColorBytesPerSample` — the check then stays
  "not checked", matching the reference's rule that omitted or partial
  capabilities are simply not checked.
- `clamps` mirror the reference's explicit texture-dimension check against
  `maxTextureSize`.
- Pure: never mutates the definition, never throws on malformed input.
"""

GLSL_ONLY_HINT = "#version"  # reference preflight.js's WebGL2 source hint


def mrt_format_bytes(fmt):
    """Byte cost per sample of a color attachment format, for the MRT
    attachment budget. Mirrors reference `preflightEffect`'s shared
    `mrtFormatBytes()`: unlisted formats (including defaulted rgba16f) cost 8.
    """
    if fmt in ("rgba32f", "rgba32float"):
        return 16
    if fmt in ("rgba8", "rgba8unorm"):
        return 4
    return 8


def _is_glsl_source(text):
    return isinstance(text, str) and GLSL_ONLY_HINT in text


def _is_wgsl_bucket(bucket):
    # Reference heuristic, retained for bucket shapes that carry raw source
    # text: WebGPU falls back to generic source/fragment when they are not GLSL.
    if not bucket:
        return False
    if bucket.get("wgsl"):
        return True
    if bucket.get("source") and not _is_glsl_source(bucket["source"]):
        return True
    if bucket.get("fragment") and not _is_glsl_source(bucket["fragment"]):
        return True
    return False


def _is_glsl_bucket(bucket):
    if not bucket:
        return False
    if bucket.get("glsl") or bucket.get("fragment") or bucket.get("vertex"):
        return True
    if bucket.get("source") and not _is_wgsl_bucket(bucket):
        return True
    return False


def _is_authored_bucket(bucket):
    """Does this shader bucket carry a source the port's backend can compile?

    The port's compile step consumes a transpiled `.frag` body (plus its
    `.createinfo.json` descriptor). A bucket counts as authored when any of the
    source-bearing keys is truthy — either the reference's GLSL keys (`glsl`,
    `fragment`, `vertex`, or a non-WGSL generic `source`) or the port's
    resolved-source marker (`frag`).
    """
    if not bucket:
        return False
    if _is_glsl_bucket(bucket):
        return True
    if bucket.get("frag"):
        return True
    return False


def _definition_passes(definition):
    if not isinstance(definition, dict):
        return []
    passes = definition.get("passes")
    if isinstance(passes, list):
        return passes
    return []


def _definition_textures(definition):
    if not isinstance(definition, dict):
        return None
    textures = definition.get("textures")
    if isinstance(textures, dict):
        return textures
    return None


def preflight_effect(definition, capabilities, shaders=None):
    """Predict per-backend authorability and device-limit-driven format changes
    for an effect definition (reference `preflightEffect`, GAP-016).

    definition  — effect definition dict ({passes, textures, [shaders]})
    capabilities — device capabilities dict ({maxDrawBuffers, maxTextureSize,
                  maxColorBytesPerSample, ...}); omitted or partial
                  capabilities are simply not checked.
    shaders     — per-program shader buckets ({program: bucket}) as resolved by
                  the port's compile step; defaults to definition.shaders.
                  When absent, source availability is unknown and only
                  structural/limit checks are reported.
    """
    caps = capabilities or {}
    shaders_arg = shaders or (definition.get("shaders") if isinstance(definition, dict) else None)
    has_shader_info = isinstance(shaders_arg, dict) and len(shaders_arg) > 0
    buckets = shaders_arg if has_shader_info else {}
    passes = _definition_passes(definition)
    textures = _definition_textures(definition)

    blender_reasons = []
    format_changes = []
    clamps = []
    budget = caps.get("maxColorBytesPerSample")
    max_draw_buffers = caps.get("maxDrawBuffers")
    max_texture_size = caps.get("maxTextureSize")

    for render_pass in passes:
        program = render_pass.get("program") if isinstance(render_pass, dict) else None
        if not program:
            continue
        bucket = buckets.get(program)

        # Source availability for the port's backend (only when shader info
        # is provided — never invented).
        if has_shader_info and not _is_authored_bucket(bucket):
            blender_reasons.append(
                "program '%s' has no compiled source (pass '%s')"
                % (program, render_pass.get("name") or program)
            )

        # MRT draw-buffer limit.
        outputs = render_pass.get("outputs") or {}
        output_count = len(outputs)
        if isinstance(max_draw_buffers, (int, float)) and output_count > max_draw_buffers:
            blender_reasons.append(
                "pass '%s' writes %d color attachments, device allows %d"
                % (render_pass.get("name") or program, output_count, max_draw_buffers)
            )

        # Predict the reference applyMrtFormatBudget() demotion for this pass:
        # trailing rgba32f attachments demoted to rgba16f until the group fits
        # the budget (sharing mrt_format_bytes with the runtime's budget table).
        if budget and output_count > 1:
            entries = [{"tex_id": tid, "spec": textures.get(tid) if textures else None}
                       for tid in outputs.values()]
            total = sum(mrt_format_bytes(e["spec"].get("format") if e["spec"] else None)
                        for e in entries)
            if total > budget:
                for entry in reversed(entries):
                    if total <= budget:
                        break
                    spec = entry["spec"]
                    if not spec:
                        continue
                    fmt = spec.get("format")
                    if fmt in ("rgba32f", "rgba32float"):
                        format_changes.append({
                            "texture": entry["tex_id"],
                            "pass": render_pass.get("name") or render_pass.get("id") or program,
                            "from": fmt,
                            "to": "rgba16f",
                            "budget": budget,
                        })
                        total -= 8

    # Predict maxTextureSize clamps for explicit texture dimensions.
    if textures and isinstance(max_texture_size, (int, float)) and max_texture_size:
        for tex_id, spec in textures.items():
            if not isinstance(spec, dict):
                continue
            for field in ("width", "height", "depth"):
                value = spec.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value > max_texture_size:
                    clamps.append({
                        "texture": tex_id,
                        "field": field,
                        "requested": value,
                        "limit": max_texture_size,
                    })

    return {
        "backends": {
            "blender": {"authorable": len(blender_reasons) == 0, "reasons": blender_reasons},
        },
        "formatChanges": format_changes,
        "clamps": clamps,
    }

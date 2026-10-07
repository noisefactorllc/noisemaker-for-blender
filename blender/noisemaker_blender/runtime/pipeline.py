"""Render-graph pipeline — reference/04 §10 control flow.

Per frame: reset frame surface bindings, run each pass (honoring repeat-count and
skip conditions), ping-pong global outputs after each execution, persist state at
end of frame. Supports multi-frame settle and sampling for stateful effects.
"""
import json
import math
import os
import time as clock

from .diagnostics import DIAGNOSTIC_CODES
from .preflight import preflight_effect


_TAU = math.pi * 2
# graph texture format string -> GPUOffScreen format token, in both the WebGL2
# and the WebGPU spelling (the reference WebGL2 backend resolves both).
# GPUOffScreen has no single-channel formats, so r8/r16f/r32f keep the fallback.
_FORMAT = {
    "rgba8": "RGBA8", "rgba8unorm": "RGBA8",
    "rgba16f": "RGBA16F", "rgba16float": "RGBA16F",
    "rgba32f": "RGBA32F", "rgba32float": "RGBA32F",
}
_AUTOMATION_FIELD_RANGES = {
    "unit": {"min": 0, "max": 1},
    "oscillatorSpeed": {"min": -20, "max": 20},
    "oscillatorOffset": {"min": -1, "max": 1},
    "oscillatorSeed": {"min": 1, "max": 9999},
    "midiSensitivity": {"min": 0, "max": 10},
}
_MAX_AUTOMATION_DEPTH = 8
_INTEGRATION_RULES = (
    (
        (
            -0.9894009349916499, -0.9445750230732326, -0.8656312023878318,
            -0.755404408355003, -0.6178762444026438, -0.4580167776572274,
            -0.2816035507792589, -0.0950125098376374, 0.0950125098376374,
            0.2816035507792589, 0.4580167776572274, 0.6178762444026438,
            0.755404408355003, 0.8656312023878318, 0.9445750230732326,
            0.9894009349916499,
        ),
        (
            0.0271524594117541, 0.0622535239386479, 0.0951585116824928,
            0.1246289712555339, 0.1495959888165767, 0.1691565193950025,
            0.1826034150449236, 0.1894506104550685, 0.1894506104550685,
            0.1826034150449236, 0.1691565193950025, 0.1495959888165767,
            0.1246289712555339, 0.0951585116824928, 0.0622535239386479,
            0.0271524594117541,
        ),
    ),
    (
        (-0.9602898564975363, -0.7966664774136267, -0.525532409916329,
         -0.1834346424956498, 0.1834346424956498, 0.525532409916329,
         0.7966664774136267, 0.9602898564975363),
        (0.1012285362903763, 0.2223810344533745, 0.3137066458778873,
         0.362683783378362, 0.362683783378362, 0.3137066458778873,
         0.2223810344533745, 0.1012285362903763),
    ),
    (
        (-0.8611363115940526, -0.3399810435848563, 0.3399810435848563,
         0.8611363115940526),
        (0.3478548451374538, 0.6521451548625461, 0.6521451548625461,
         0.3478548451374538),
    ),
    ((-0.5773502691896257, 0.5773502691896257), (1, 1)),
)


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _member(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _method(value, *names):
    for name in names:
        candidate = _member(value, name)
        if callable(candidate):
            return candidate
    return None


def _automation_type(value):
    if not isinstance(value, dict):
        return None
    direct = value.get("type")
    if direct in ("Oscillator", "Midi", "Audio"):
        return direct
    ast = value.get("_ast")
    nested = ast.get("type") if isinstance(ast, dict) else None
    return nested if nested in ("Oscillator", "Midi", "Audio") else None


def _scale_automation_value(value, value_range):
    if not isinstance(value_range, dict):
        return value
    minimum = value_range.get("min")
    maximum = value_range.get("max")
    if not _finite_number(minimum) or not _finite_number(maximum):
        return value
    return minimum + value * (maximum - minimum)


def _resolve_automation_field(
    value, normalized_time, value_range, external_state, depth, stack,
    fallback, wall_time_ms,
):
    if _automation_type(value):
        return _evaluate_automation(
            value, normalized_time, value_range, external_state, depth + 1,
            stack, wall_time_ms,
        )
    return value if _finite_number(value) else fallback


def _has_dynamic_automation_fields(config):
    fields = ("min", "max", "sensitivity") if _automation_type(config) == "Midi" else ("min", "max")
    return any(_automation_type(config.get(field)) for field in fields)


def _osc_sine(value):
    return (1 - math.cos(value * _TAU)) * 0.5


def _osc_tri(value):
    fraction = value - math.floor(value)
    return 1 - abs(fraction * 2 - 1)


def _osc_saw(value):
    return value - math.floor(value)


def _osc_saw_inv(value):
    return 1 - (value - math.floor(value))


def _osc_square(value):
    return 1 if (value - math.floor(value)) >= 0.5 else 0


def _js_remainder(value, divisor):
    return math.fmod(value, divisor)


def _hash21(px, py, seed):
    x = _js_remainder(px * 234.34 + seed, 1)
    y = _js_remainder(py * 435.345 + seed, 1)
    if x < 0:
        x += 1
    if y < 0:
        y += 1
    value = x + y + (x + y) * 34.23
    return _js_remainder(x * y * value, 1)


def _noise2d(px, py, seed):
    ix = math.floor(px)
    iy = math.floor(py)
    fx = px - ix
    fy = py - iy
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a = _hash21(ix, iy, seed)
    b = _hash21(ix + 1, iy, seed)
    c = _hash21(ix, iy + 1, seed)
    d = _hash21(ix + 1, iy + 1, seed)
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy


def _osc_noise(value, seed):
    temporal = _js_remainder(value, 1)
    angle = temporal * _TAU
    loop_x = math.cos(angle) * 2
    loop_y = math.sin(angle) * 2
    first = _noise2d(loop_x + seed, loop_y + seed, seed)
    second = _noise2d(loop_x + seed * 2, loop_y + seed * 2, seed)
    return (first + second) / 2


def _osc_noise2d(time, speed, seed):
    # Two-stage periodic noise (noise2d, kind 6) - mirrors the osc2d effect:
    #   scaledTime = periodicValue(time, timeNoise) * speed
    #   value      = periodicValue(scaledTime, valueNoise)
    # ``time`` is the normalized loop time plus the phase offset; speed is
    # applied once, after the first periodic wrap, exactly as in the osc2d
    # shader. osc() has no spatial position, so both noise stages are sampled
    # at a fixed position derived from the seed (the osc2d shader salts the
    # second stage with +12345). periodicValue() has period 1 in time, so
    # whole-number speeds loop seamlessly.
    def periodic(value, noise):
        return (math.sin((value - noise) * _TAU) + 1) * 0.5

    px = (abs(_js_remainder(seed, 16)) + 0.5) / 16
    py = (abs(_js_remainder(math.floor(seed / 16), 16)) + 0.5) / 16
    time_noise = _noise2d(px, py, seed + 12345)
    value_noise = _noise2d(px, py, seed)
    scaled_time = periodic(time, time_noise) * speed
    return periodic(scaled_time, value_noise)


def _osc_primitive(osc_type, value):
    whole = math.floor(value)
    fraction = value - whole
    if osc_type == 0:
        return value * 0.5 - math.sin(value * _TAU) / (2 * _TAU)
    if osc_type == 1:
        partial = (
            fraction * fraction
            if fraction < 0.5
            else 2 * fraction - fraction * fraction - 0.5
        )
        return whole * 0.5 + partial
    if osc_type == 2:
        return whole * 0.5 + fraction * fraction * 0.5
    if osc_type == 3:
        return value - (whole * 0.5 + fraction * fraction * 0.5)
    if osc_type == 4:
        return whole * 0.5 + max(0, fraction - 0.5)
    return None


def _can_integrate_oscillator_exactly(config):
    return (
        config.get("oscType") in range(5)
        and all(_finite_number(config.get(field)) for field in ("min", "max", "speed", "offset", "seed"))
    )


def _integrate_simple_oscillator(config, normalized_time):
    speed = config["speed"]
    if speed == 0:
        return _evaluate_oscillator(config, 0, None, 0, set(), None) * normalized_time
    start = _osc_primitive(config["oscType"], config["offset"])
    end = _osc_primitive(
        config["oscType"], config["offset"] + speed * normalized_time
    )
    raw_integral = (end - start) / speed
    return config["min"] * normalized_time + (config["max"] - config["min"]) * raw_integral


def _integrate_automation(
    config, normalized_time, value_range, external_state, depth, stack,
    wall_time_ms,
):
    config_type = _automation_type(config)
    if config_type == "Oscillator" and _can_integrate_oscillator_exactly(config):
        integral = _integrate_simple_oscillator(config, normalized_time)
    elif config_type in ("Midi", "Audio") and not _has_dynamic_automation_fields(config):
        integral = _evaluate_automation(
            config, normalized_time, None, external_state, depth + 1, stack,
            wall_time_ms,
        ) * normalized_time
    else:
        nodes, weights = _INTEGRATION_RULES[min(depth, len(_INTEGRATION_RULES) - 1)]
        midpoint = normalized_time * 0.5
        half_width = normalized_time * 0.5
        total = 0
        for node, weight in zip(nodes, weights):
            sample_time = midpoint + half_width * node
            total += weight * _evaluate_automation(
                config, sample_time, None, external_state, depth + 1, stack,
                wall_time_ms,
            )
        integral = half_width * total

    if not isinstance(value_range, dict):
        return integral
    minimum = value_range.get("min")
    maximum = value_range.get("max")
    if not _finite_number(minimum) or not _finite_number(maximum):
        return integral
    return minimum * normalized_time + integral * (maximum - minimum)


def _evaluate_oscillator(
    config, normalized_time, external_state, depth, stack, wall_time_ms,
):
    minimum = _resolve_automation_field(
        config.get("min"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
        external_state, depth, stack, 0, wall_time_ms,
    )
    maximum = _resolve_automation_field(
        config.get("max"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
        external_state, depth, stack, 1, wall_time_ms,
    )
    offset = _resolve_automation_field(
        config.get("offset"), normalized_time,
        _AUTOMATION_FIELD_RANGES["oscillatorOffset"], external_state, depth,
        stack, 0, wall_time_ms,
    )
    seed = _resolve_automation_field(
        config.get("seed"), normalized_time,
        _AUTOMATION_FIELD_RANGES["oscillatorSeed"], external_state, depth,
        stack, 1, wall_time_ms,
    )
    speed = config.get("speed")
    if _automation_type(speed):
        phase = _integrate_automation(
            speed, normalized_time, _AUTOMATION_FIELD_RANGES["oscillatorSpeed"],
            external_state, depth, stack, wall_time_ms,
        )
    else:
        phase = normalized_time * (speed if _finite_number(speed) else 1)
    value = phase + offset
    osc_type = config.get("oscType")
    if osc_type == 0:
        raw = _osc_sine(value)
    elif osc_type == 1:
        raw = _osc_tri(value)
    elif osc_type == 2:
        raw = _osc_saw(value)
    elif osc_type == 3:
        raw = _osc_saw_inv(value)
    elif osc_type == 4:
        raw = _osc_square(value)
    elif osc_type == 5:
        raw = _osc_noise(value, seed)
    elif osc_type == 6:
        # noise2d (upstream eabb537e/5e68552a): speed is resolved as a plain
        # automation field (evaluated, not integrated) and applied exactly
        # once inside _osc_noise2d, on the normalized loop time plus the
        # phase offset — not on top of the phase, which already includes it.
        raw_speed = _resolve_automation_field(
            config.get("speed"), normalized_time,
            _AUTOMATION_FIELD_RANGES["oscillatorSpeed"], external_state,
            depth, stack, 1, wall_time_ms,
        )
        raw = _osc_noise2d(
            normalized_time + offset,
            raw_speed if _finite_number(raw_speed) else 1,
            seed,
        )
    else:
        raw = 0
    return minimum + raw * (maximum - minimum)


def _evaluate_midi(config, midi_state, wall_time_ms, minimum, maximum, sensitivity):
    if config.get("_invalid") or midi_state is None:
        return minimum

    def integer_in(value, low, high):
        return _finite_number(value) and float(value).is_integer() and low <= value <= high

    def indexed(values, key, default=0):
        if isinstance(values, dict):
            return values.get(key, default)
        if isinstance(values, (list, tuple)) and integer_in(key, 0, len(values) - 1):
            return values[int(key)]
        return default

    mode = config.get("mode", 4)
    has_zone = "zone" in config
    if has_zone and ("channel" in config or not integer_in(config["zone"], 0, 1)):
        return minimum
    if "members" in config and (not has_zone or not integer_in(config["members"], 1, 15)):
        return minimum
    if not has_zone and mode >= 5 and not integer_in(config.get("channel"), 1, 16):
        return minimum
    voice = None
    if has_zone:
        get_voice = _method(midi_state, "get_zone_voice", "getZoneVoice")
        voice = get_voice(config) if get_voice else None
        if voice is None:
            return minimum
        channel = _member(voice, "channel")
    else:
        get_channel = _method(midi_state, "get_channel", "getChannel")
        channel = get_channel(config.get("channel")) if get_channel else None
    if channel is None:
        return minimum
    note = voice if voice is not None else channel
    gate = 1 if voice is not None else _member(note, "gate", 0)
    key = _member(note, "key", 0)
    velocity = _member(note, "velocity", 0)
    if mode in (5, 6):
        cc = config.get("cc", 1)
        if not integer_in(cc, 0, 31 if mode == 6 else 127):
            return minimum
        raw = indexed(_member(channel, "cc14" if mode == 6 else "cc"), cc)
        return minimum + raw / (16383 if mode == 6 else 127) * (maximum - minimum)
    if mode == 7:
        parameter = config.get("nrpn")
        if not integer_in(parameter, 0, 16382):
            return minimum
        raw = indexed(_member(channel, "nrpn"), parameter)
        return minimum + raw / 16383 * (maximum - minimum)
    if mode == 8:
        return minimum + _member(channel, "pitchBend", 8192) / 16383 * (maximum - minimum)
    if mode == 9:
        return minimum + _member(channel, "pressure", 0) / 127 * (maximum - minimum)
    if mode == 10:
        return minimum + indexed(_member(channel, "polyPressure"), key) / 127 * (maximum - minimum)
    raw = 0
    if mode == 0:
        raw = key
    elif mode == 1 and gate == 1:
        raw = key
    elif mode == 2 and gate == 1:
        raw = velocity
    elif mode in (3, 4) and gate == 1:
        raw = key if mode == 3 else velocity
        elapsed = wall_time_ms - _member(note, "time", wall_time_ms)
        decay = min(1, elapsed * sensitivity * 0.001)
        raw *= 1 - decay
    return minimum + (raw / 127) * (maximum - minimum)


def _evaluate_audio(config, audio_state, minimum, maximum):
    if config.get("_invalid") or audio_state is None:
        return minimum
    source = config.get("_ast")
    if not isinstance(source, dict) or source.get("type") != "Audio":
        source = config
    has_selector = any(field in config or field in source for field in ("name", "id", "channel"))
    selected_state = audio_state
    if has_selector:
        if any(field in source and field not in config for field in ("name", "id", "channel")):
            return minimum
        if "name" in config and (not isinstance(config["name"], str) or not config["name"]):
            return minimum
        if "id" in config and (not isinstance(config["id"], str) or not config["id"] or not config.get("name")):
            return minimum
        channel = config.get("channel")
        if not _finite_number(channel) or not float(channel).is_integer() or not 1 <= channel <= 32:
            return minimum
        get_selected = _method(
            audio_state, "get_device_channel_state", "getDeviceChannelState"
        )
        selected_state = get_selected(config) if get_selected else None
    if selected_state is None:
        return minimum
    band = config.get("band")
    if band == 0:
        raw = _member(selected_state, "low", 0)
    elif band == 1:
        raw = _member(selected_state, "mid", 0)
    elif band == 2:
        raw = _member(selected_state, "high", 0)
    elif band == 3:
        raw = _member(selected_state, "vol", 0)
    elif band == 4:
        if _member(selected_state, "rawReady", False) is not True:
            return minimum
        raw = (max(-1, min(1, _member(selected_state, "raw", 0) or 0)) + 1) * 0.5
    else:
        raw = 0
    raw = max(0, min(1, raw))
    return minimum + raw * (maximum - minimum)


def _evaluate_automation(
    config, normalized_time, value_range, external_state, depth=0, stack=None,
    wall_time_ms=None,
):
    if stack is None:
        stack = set()
    identity = id(config)
    if (
        not _automation_type(config)
        or depth > _MAX_AUTOMATION_DEPTH
        or identity in stack
    ):
        return _scale_automation_value(0, value_range)
    if wall_time_ms is None:
        wall_time_ms = clock.time() * 1000

    stack.add(identity)
    try:
        config_type = _automation_type(config)
        if config_type == "Oscillator":
            value = _evaluate_oscillator(
                config, normalized_time, external_state, depth, stack, wall_time_ms
            )
        elif config_type == "Midi":
            midi_state = _member(external_state, "midi")
            get_port = _method(midi_state, "get_port_state", "getPortState")
            if get_port:
                midi_state = get_port(config)
            minimum = _resolve_automation_field(
                config.get("min"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
                external_state, depth, stack, 0, wall_time_ms,
            )
            maximum = _resolve_automation_field(
                config.get("max"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
                external_state, depth, stack, 1, wall_time_ms,
            )
            sensitivity = _resolve_automation_field(
                config.get("sensitivity"), normalized_time,
                _AUTOMATION_FIELD_RANGES["midiSensitivity"], external_state,
                depth, stack, 1, wall_time_ms,
            )
            value = _evaluate_midi(
                config, midi_state, wall_time_ms, minimum, maximum, sensitivity
            )
        elif config.get("_invalid"):
            value = config.get("min") if _finite_number(config.get("min")) else 0
        else:
            minimum = _resolve_automation_field(
                config.get("min"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
                external_state, depth, stack, 0, wall_time_ms,
            )
            maximum = _resolve_automation_field(
                config.get("max"), normalized_time, _AUTOMATION_FIELD_RANGES["unit"],
                external_state, depth, stack, 1, wall_time_ms,
            )
            value = _evaluate_audio(
                config, _member(external_state, "audio"), minimum, maximum
            )
    finally:
        stack.remove(identity)
    return _scale_automation_value(value, value_range)


def resolve_uniform_value(value, time, param_spec=None, external_state=None):
    """Resolve oscillator, MIDI, or audio descriptors at normalized ``time``."""
    if not _automation_type(value):
        return value
    return _evaluate_automation(value, time, param_spec, external_state or {})


def _resolve_pass_uniforms(render_pass, time, external_state):
    uniforms = render_pass.get("uniforms")
    if not uniforms:
        return render_pass
    specs = render_pass.get("uniformSpecs") or {}
    resolved = {
        name: resolve_uniform_value(value, time, specs.get(name), external_state)
        for name, value in uniforms.items()
    }
    if all(resolved[name] is value for name, value in uniforms.items()):
        return render_pass
    effective = dict(render_pass)
    effective["uniforms"] = resolved
    return effective


def default_engine(size, time, frame, delta_time=0.0, *, width=None, height=None):
    width = size if width is None else width
    height = size if height is None else height
    return {
        "resolution": [float(width), float(height)],
        "fullResolution": [float(width), float(height)],
        "tileOffset": [0.0, 0.0],
        "time": float(time),
        "deltaTime": float(delta_time),
        "frame": int(frame),
        "aspect": float(width) / float(height),
        "aspectRatio": float(width) / float(height),
        "renderScale": 1.0,
        "seed": 0,
    }


def collect_default_uniforms(graph):
    """Merge every pass.uniforms (last-write-wins) — used for dimension/repeat resolution."""
    out = {}
    for p in graph.passes:
        out.update(p.get("uniforms", {}))
    return out


def _is_volume_size_uniform(name):
    return (name == "volumeSize" or
            name.startswith("volumeSize_chain_") or
            name.startswith("volumeSize_node_"))


def _clamp_volume_size(value, max_texture_size):
    """Clamp a volume atlas edge power-of-two-down to the device texture limit."""
    if (not isinstance(value, (int, float)) or isinstance(value, bool) or
            not max_texture_size or value * value <= max_texture_size):
        return value
    clamped = 16
    while (clamped * 2) ** 2 <= max_texture_size and clamped * 2 < value:
        clamped *= 2
    return clamped


def _clamp_graph_volume_sizes(graph, max_texture_size):
    for render_pass in graph.passes:
        uniforms = render_pass.get("uniforms")
        if not uniforms:
            continue
        for name, value in uniforms.items():
            if _is_volume_size_uniform(name):
                uniforms[name] = _clamp_volume_size(value, max_texture_size)


def should_skip(p, lookup):
    """Mirror reference Pipeline.shouldSkipPass — conditions are read ONLY off the pass
    object. As of reference 0ed489ec, expander.js sets `conditions: passDef.conditions` on
    each graph pass it builds (pointsRender/pointsBillboardRender's per-viewMode deposit
    variants, and pointsBillboardRender's `deposit` (additive) vs `deposit_alpha`
    (premult-over) blendMode split, are what actually exercises this) — expander.py mirrors
    that, so `pass.conditions` IS set at runtime for any effect whose definition carries one.
    We do NOT resolve conditions from the registry/def; we only honor an inline `conditions`
    a pass dict literally carries, matching the reference exactly."""
    if p.get("skip") or p.get("_skip"):
        return True
    conds = p.get("conditions")
    if not conds:
        return False
    for c in conds.get("skipIf", []):
        v = lookup.get(c["uniform"], (p.get("uniforms") or {}).get(c["uniform"]))
        if v == c.get("equals"):
            return True
    for c in conds.get("runIf", []):
        v = lookup.get(c["uniform"], (p.get("uniforms") or {}).get(c["uniform"]))
        if v != c.get("equals"):
            return True
    return False


def _record_dimension_fallback(spec, screen_size, diagnostics, warned):
    """Record a structured ERR_DIMENSION_FALLBACK diagnostic for an
    unknown dimension form. The historical screen-size fallback is unchanged
    (no new rejection of previously accepted input); the record is deduplicated
    per serialized spec so per-frame resolution cannot grow it unboundedly,
    while the warning still fires on every occurrence (mirroring the
    reference's console.warn / diagnostics.add split)."""
    if warned is None or diagnostics is None:
        return
    if isinstance(spec, dict):
        try:
            key = json.dumps(spec, sort_keys=True)
        except (TypeError, ValueError):
            key = "[unserializable]"
    else:
        key = str(spec)
    print("NMR WARN dimension %s — falling back to screen size (%d)" % (key, screen_size))
    if key in warned:
        return
    warned.add(key)
    diagnostics.add({
        "code": DIAGNOSTIC_CODES["DIMENSION_FALLBACK"],
        "backend": "blender",
        "stage": "dimension",
        "spec": key,
        "fallback": "screen",
    })


def resolve_dimension(spec, screen_size, uniforms=None, diagnostics=None, warned=None):
    """Resolve an authored dimension expression against screen size and uniforms.

    ``'input'`` and ``'resolution'`` are validator-accepted dimension keywords
    (DIM_KEYWORDS in the reference effect-validator) whose historical
    resolution is the screen dimension; they are recognized forms, not unknown
    fallbacks, so they add no diagnostic.
    """
    if uniforms is None:
        uniforms = {}
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return max(1, int(math.floor(spec)))
    if isinstance(spec, str):
        if spec in ("screen", "auto", "input", "resolution"):
            return screen_size
        if spec.endswith("%"):
            return max(1, int(math.floor(screen_size * float(spec[:-1]) / 100.0)))
        _record_dimension_fallback(spec, screen_size, diagnostics, warned)
        return screen_size
    if isinstance(spec, dict):
        if spec.get("param") is not None:
            val = uniforms.get(spec["param"], spec.get("default", spec.get("paramDefault", 64)))
            if isinstance(val, dict):
                val = spec.get("default", 64)
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
            return max(1, int(round(screen_size / div)))
        if spec.get("scale") is not None:
            return max(1, int(math.floor(screen_size * spec["scale"])))
    # An unknown object form (no param/screenDivide/scale key) keeps the
    # historical screen-size fallback but records it; an absent spec
    # (None) is a default, not an unknown form, and adds no diagnostic.
    if spec is not None:
        _record_dimension_fallback(spec, screen_size, diagnostics, warned)
    return screen_size


def resolve_surface_format(spec, diagnostics=None, warned=None):
    """Resolve a graph texture format string to the GPUOffScreen format token.

    The historical silent rgba16f fallback is unchanged (no new rejection of
    previously accepted input), but an explicitly authored unknown format now
    surfaces a structured ERR_UNKNOWN_FORMAT_FALLBACK diagnostic
    instead of pure silence; the record is deduplicated per format string while
    the warning still fires on every occurrence. An absent format is the
    default, not a fallback, and adds no diagnostic.
    """
    fmt = str(spec.get("format", "rgba16f")).lower() if isinstance(spec, dict) else str(spec)
    token = _FORMAT.get(fmt)
    if token is not None:
        return token
    if warned is not None and diagnostics is not None:
        print("NMR WARN texture format '%s' — falling back to rgba16f" % fmt)
        if fmt not in warned:
            warned.add(fmt)
            diagnostics.add({
                "code": DIAGNOSTIC_CODES["UNKNOWN_FORMAT_FALLBACK"],
                "backend": "blender",
                "stage": "texture-create",
                "format": fmt,
                "fallback": "rgba16f",
            })
    return "RGBA16F"


def resolve_pass_viewport(pass_obj, width, height, cache_holder=None):
    """Mirror reference Pipeline.resolvePassViewport.

    Resolves an authored pass.viewport spec ({ x, y, width, height } or
    { x, y, w, h } with dimension expressions or raw numbers) into a concrete
    { x, y, w, h } integer pixel box on `viewportResolved`.
    """
    if cache_holder is None:
        cache_holder = pass_obj
    spec = cache_holder.get("viewport")
    if not spec or not isinstance(spec, dict):
        return None

    is_numeric_box = (
        isinstance(spec.get("x"), (int, float)) and not isinstance(spec.get("x"), bool) and
        isinstance(spec.get("y"), (int, float)) and not isinstance(spec.get("y"), bool) and
        isinstance(spec.get("w"), (int, float)) and not isinstance(spec.get("w"), bool) and
        isinstance(spec.get("h"), (int, float)) and not isinstance(spec.get("h"), bool)
    )
    if is_numeric_box:
        cache_holder["viewportResolved"] = spec
        if pass_obj is not cache_holder:
            pass_obj["viewportResolved"] = spec
        return spec

    uniforms = pass_obj.get("uniforms") or {}
    x = resolve_dimension(spec.get("x", 0), width, uniforms) if spec.get("x") is not None else 0
    y = resolve_dimension(spec.get("y", 0), height, uniforms) if spec.get("y") is not None else 0
    width_spec = spec.get("w", spec.get("width"))
    height_spec = spec.get("h", spec.get("height"))
    w = resolve_dimension(width_spec, width, uniforms) if width_spec is not None else width
    h = resolve_dimension(height_spec, height, uniforms) if height_spec is not None else height
    box = {"x": x, "y": y, "w": w, "h": h}
    cache_holder["viewportResolved"] = box
    if pass_obj is not cache_holder:
        pass_obj["viewportResolved"] = box
    return box


def build_texture_pooling_plan(graph):
    """Mirror reference ``Pipeline.buildTexturePoolingPlan`` plus its
    viewport follow-up (upstream `95743621`).

    Consumes the analyzer's physical allocation map (``graph.allocations``,
    produced by ``compiler.resources.allocate_resources``) and returns a
    ``{virtualId: storageId}`` dict for every poolable texture; members of a
    physical group share one backend texture created under the group's primary
    (first) member id.

    A group is poolable only when every member carries an identical plain 2D
    spec: persistent textures must keep their cross-frame contents, and
    mipmapped/3D textures carry policy state a shared record must not absorb.
    Groups with mismatched dimensions or formats fall back to standalone
    textures.

    First-read safety: a member whose first touch in the pass list is an input
    read (or that is sampled by its own producing pass) expects the
    zero-initialized/previous-frame contents a standalone texture would hold,
    so it is never pooled into a slot a group-mate writes earlier in the same
    frame. The same protection excludes textures written by partial/non-clearing
    passes — any explicit ``drawMode`` (points, billboards, triangles) scatters
    geometry without covering the surface, ``blend`` makes the result depend on
    the destination's previous contents, and a ``viewport`` pass without
    ``clear: true`` renders into a sub-region — because pooled storage would
    hand them a group-mate's content instead of their own accumulated state.

    Returns
    -------
    dict
        ``{virtualId: storageId}`` including each storage id mapping to itself
        (upstream sets the storage under its own key too); empty when the graph
        carries no allocation plan.
    """
    allocations = graph.allocations or {}
    textures = graph.textures or {}
    aliases = {}
    if not allocations or not textures:
        return aliases

    # First-touch classification from the pass list.
    first_touch_is_write = {}
    self_sampled = set()
    partially_written = set()
    for pass_ in graph.passes:
        inputs = set((pass_.get("inputs") or {}).values())
        outputs = list((pass_.get("outputs") or {}).values())
        # A pass that does not fully overwrite its target (scatter draw modes,
        # blending against the destination, a viewport sub-region without a
        # full clear) leaves the texture's previous contents observable, so
        # pooled storage is unsafe.
        if pass_.get("drawMode") or pass_.get("blend"):
            partially_written.update(outputs)
        elif pass_.get("viewport") is not None and not pass_.get("clear"):
            partially_written.update(outputs)
        for tex_id in outputs:
            if tex_id not in first_touch_is_write:
                first_touch_is_write[tex_id] = True
            if tex_id in inputs:
                self_sampled.add(tex_id)
        for tex_id in inputs:
            if tex_id not in first_touch_is_write:
                first_touch_is_write[tex_id] = False

    groups = {}  # physicalId -> [virtualIds]
    for tex_id, physical_id in allocations.items():
        if not physical_id or tex_id not in textures:
            continue
        # Global surfaces are double-buffered and never pooled
        if tex_id.startswith("global"):
            continue
        if first_touch_is_write.get(tex_id) is False:
            continue
        if tex_id in self_sampled:
            continue
        if tex_id in partially_written:
            continue
        groups.setdefault(physical_id, []).append(tex_id)

    for members in groups.values():
        if len(members) < 2:
            continue
        specs = [textures.get(m) for m in members]
        if any(spec is None or
               spec.get("persistent") is True or
               spec.get("mipmaps") is True or
               spec.get("is3D") is True for spec in specs):
            continue
        signature = {(repr(spec.get("width")), repr(spec.get("height")),
                      spec.get("format")) for spec in specs}
        if len(signature) > 1:
            continue
        storage_id = members[0]
        for member in members:
            aliases[member] = storage_id
    return aliases


def resource_plan(backend, graph):
    """Mirror reference ``Pipeline.getResourcePlan``.

    Query the actual runtime texture allocation/reuse plan: the analyzer's
    physical allocation map (``graph.allocations``) and the sharing the
    renderer actually materialized — non-global graph textures grouped by
    identical backend texture record. Members of a ``sharedTextures`` group
    are served by one physical texture.
    """
    textures = graph.textures or {}
    by_key = {}
    for tex_id in textures:
        if tex_id.startswith("global"):
            continue
        key = (backend.pool_key or {}).get(tex_id)
        record = (backend.pool or {}).get(key) if key is not None else None
        if record is None:
            continue
        by_key.setdefault(key, {"id": tex_id, "members": []})
        by_key[key]["members"].append(tex_id)

    texture_records = []
    shared_textures = []
    for key, entry in by_key.items():
        spec = (backend.tex_dims or {}).get(entry["id"], (None, None))
        format_name = key[3] if key is not None else None
        texture_records.append({
            "id": entry["id"],
            "width": spec[0],
            "height": spec[1],
            "format": format_name,
            "virtualTextures": entry["members"],
        })
        if len(entry["members"]) > 1:
            shared_textures.append(entry["members"])

    return {
        "pooling": True,  # the Blender backend always consumes the allocation plan
        "allocations": dict(graph.allocations or {}),
        "sharedTextures": shared_textures,
        "textures": texture_records,
    }


def _resolved_shader_buckets(backend, graph):
    """Resolve each pass program's source availability against the backend's
    own compile path (reference Pipeline.preflight's resolveProgramSpec step).

    The port's programs are transpiled `.frag` + `.createinfo.json` pairs under
    ``shaders_root/<namespace>/<func>/<progName>`` (or the builtin `blit`), so a
    bucket is present only when the backend's compile step would actually find
    its source. Programs the compile step would fail to locate stay out of the
    map — the report then reasons "no compiled source" instead of guessing.
    """
    buckets = {}
    for render_pass in (getattr(graph, "passes", None) or []):
        program = render_pass.get("program") if isinstance(render_pass, dict) else None
        if not program or program in buckets:
            continue
        namespace = render_pass.get("namespace")
        func = render_pass.get("func")
        prog_name = render_pass.get("progName")
        if namespace is None and func == "blit":
            buckets[program] = {"frag": "<builtin:blit>"}
            continue
        shaders_root = getattr(backend, "shaders_root", None)
        if not (shaders_root and namespace and func and prog_name):
            continue
        base = os.path.join(str(shaders_root), namespace, func, prog_name)
        if os.path.isfile(base + ".frag"):
            buckets[program] = {"frag": base + ".frag"}
    return buckets


def _predict_volume_clamps(graph, max_texture_size):
    """Predict the volumeSize clamps the pipeline applies at init (the
    preflight prediction/runtime lockstep, port side). Shares `_clamp_volume_size` with
    `FrameStepper.__init__`'s actual mutation, so the prediction and the
    runtime can never drift. Read-only; never mutates the graph."""
    clamps = []
    if not max_texture_size:
        return clamps
    for render_pass in (getattr(graph, "passes", None) or []):
        uniforms = (render_pass.get("uniforms") or {}) if isinstance(render_pass, dict) else {}
        for name, value in uniforms.items():
            if not _is_volume_size_uniform(name):
                continue
            clamped = _clamp_volume_size(value, max_texture_size)
            if clamped != value:
                clamps.append({
                    "pass": render_pass.get("name") or render_pass.get("id"),
                    "uniform": name,
                    "requested": value,
                    "clamped": clamped,
                    "limit": max_texture_size,
                })
    return clamps


def preflight(backend, graph, capabilities=None, shaders=None):
    """Static preflight of a graph against device capabilities, before any
    pipeline initialization or compilation (reference commit 12b4d74fb4f2). Port-side equivalent of reference `Pipeline.preflight`.

    Runs the same analysis as `preflight_effect` — per-backend authorability
    (the port's single Blender backend, judged against the backend's own
    compile path), predicted MRT format demotions (only when a
    `maxColorBytesPerSample` capability is supplied; the Blender runtime
    applies none), and predicted `maxTextureSize` clamps — plus, port-side,
    the `volumeClamps` the pipeline init actually applies (shared with the
    runtime's own clamp logic). Read-only; never mutates the graph.

    Returns a report dict:
      {backends: {blender: {authorable, reasons}}, formatChanges, clamps,
       volumeClamps}
    """
    caps = dict(capabilities or {})
    if caps.get("maxTextureSize") is None and callable(getattr(backend, "max_texture_size", None)):
        caps["maxTextureSize"] = backend.max_texture_size()
    if shaders is None:
        shaders = _resolved_shader_buckets(backend, graph)
    definition = {
        "passes": getattr(graph, "passes", None) or [],
        "textures": getattr(graph, "textures", None),
    }
    report = preflight_effect(definition, caps, shaders)
    report["volumeClamps"] = _predict_volume_clamps(graph, caps.get("maxTextureSize"))
    return report


def resolve_repeat_count(p, lookup):
    rep = p.get("repeat")
    if rep is None:
        return 1
    if isinstance(rep, bool):
        return 1
    if isinstance(rep, (int, float)):
        return max(1, int(math.floor(rep)))
    if isinstance(rep, str):
        v = lookup.get(rep, (p.get("uniforms") or {}).get(rep))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return max(1, int(math.floor(v)))
    return 1


class FrameStepper:
    """One-frame-at-a-time driver for the render loop in ``render``.

    Holds the per-render state ``render`` used to keep on the stack so a long bake can be
    stepped from a modal operator timer: the UI stays responsive between frames and the
    operator can abort (cancel) between frames. The frame body is byte-for-byte the loop
    body of ``render`` — the two paths must stay behaviorally identical.
    """

    def __init__(self, backend, graph, time=0.25, frames=1, timestep=0.0, samples=None,
                 sink_manager=None, external_state=None):
        max_texture_size = getattr(backend, "max_texture_size", None)
        if callable(max_texture_size):
            _clamp_graph_volume_sizes(graph, max_texture_size())
        self.backend = backend
        self.graph = graph
        self.time = time
        self.frames = frames
        self.timestep = timestep
        self.samples = samples
        self.sink_manager = sink_manager
        self.external_state = external_state
        self.sampled = {}
        self.frame = -1                     # last completed frame index
        self.prev_tt = None
        self.defaults = collect_default_uniforms(graph)
        backend.setup(graph, self.defaults)
        self.out_name = graph.render_surface  # surface name, e.g. "o1"
        if sink_manager is not None:
            sink_manager.configure({
                "width": backend.size,
                "height": backend.size,
                "format": "rgba8unorm",
                "colorSpace": "srgb",
                "alphaMode": "premultiplied",
                "fps": 60,
            })

    def step(self):
        """Render exactly one frame. True while another frame remains."""
        f = self.frame + 1
        if f >= self.frames:
            return False
        tt = (self.time + f * self.timestep) % 1.0 if self.timestep else self.time
        dt = 0.0 if (self.prev_tt is None) else (tt - self.prev_tt)
        self.prev_tt = tt
        backend = self.backend
        defaults = self.defaults
        out_name = self.out_name
        external_state = self.external_state
        if self.sink_manager is not None and callable(getattr(self.sink_manager, "should_defer_render", None)) and self.sink_manager.should_defer_render():
            self.frame = f
            return f + 1 < self.frames
        engine = default_engine(backend.size, tt, f, dt)
        lookup = dict(engine)
        lookup.update(defaults)
        backend.frame_begin()
        for p in self.graph.passes:
            if should_skip(p, lookup):
                continue
            effective_pass = _resolve_pass_uniforms(p, tt, external_state or {})
            resolve_pass_viewport(effective_pass, backend.size, backend.size, cache_holder=p)
            effective_lookup = dict(engine)
            effective_lookup.update(effective_pass.get("uniforms") or {})
            count = resolve_repeat_count(effective_pass, effective_lookup)
            for _ in range(count):
                backend.execute(effective_pass, self.graph, engine)
                for tid in effective_pass.get("outputs", {}).values():
                    backend.swap_after_write(tid)
        if self.sink_manager is not None:
            timestamp = clock.perf_counter() * 1000.0
            self.sink_manager.submit(backend.frame_read[out_name], timestamp)
        backend.frame_persist()
        # Force GPU submission periodically so long unsynced loops don't overflow Blender's
        # batched command stream (-> NaN / saturation). Read back the RENDER SURFACE (not an
        # arbitrary state surface): that forces the WHOLE frame's passes — including the
        # post-process chain — to complete, which a 1px read of an off-path surface does not
        # (the integration target's 32 passes/frame overflow otherwise). Every 30 frames.
        if self.timestep and (f % 30 == 29) and not (self.samples is not None and f in self.samples):
            backend.read_surface(out_name)
        if self.samples is not None and f in self.samples:
            self.sampled[f] = backend.read_surface(out_name)
        self.frame = f
        return f + 1 < self.frames

    def result(self):
        """The render() return value once every frame has been stepped."""
        if self.samples is not None:
            return self.sampled
        return self.backend.read_surface(self.out_name)


def render(backend, graph, time=0.25, frames=1, timestep=0.0, samples=None,
           sink_manager=None, external_state=None):
    """Run `frames` frames, matching the reference golden harness stepping EXACTLY
    (parity/batch-golden.mjs): per frame `tt = (time + i*timestep) % 1`, and engine
    deltaTime = 0 on frame 0 else (tt - tt_prev) — the `lastTime>0` guard, raw diff
    (can go negative at the time wrap, which the speed-driven sims ignore).

    - timestep=0  -> fixed-time deterministic render (deltaTime stays 0): single-pass
      effects and N-frames-from-zero (the 8-frame points/agents convention).
    - timestep>0  -> continuous-solver / agent evolution to steady state (navierStokes,
      points sims): the babylon `_EVO` recipe is frames=1800, timestep=0.0016667 (30s @ 1/600).

    If `samples` (set of frame indices) given, return {frame: array}; else the final
    render-surface array. An optional externally owned `sink_manager` receives the configured
    output descriptor and each completed render-surface binding with a monotonic timestamp in ms.

    Equivalent to driving a :class:`FrameStepper` to completion; the stepper exists so the
    bake operator can run the same loop from a modal timer (cancellable long bakes).
    """
    stepper = FrameStepper(backend, graph, time=time, frames=frames, timestep=timestep,
                           samples=samples, sink_manager=sink_manager,
                           external_state=external_state)
    while stepper.step():
        pass
    return stepper.result()

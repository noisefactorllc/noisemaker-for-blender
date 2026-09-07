"""Render-graph pipeline — reference/04 §10 control flow.

Per frame: reset frame surface bindings, run each pass (honoring repeat-count and
skip conditions), ping-pong global outputs after each execution, persist state at
end of frame. Supports multi-frame settle and sampling for stateful effects.
"""
import math
import time as clock


_TAU = math.pi * 2
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


def default_engine(size, time, frame, delta_time=0.0):
    return {
        "resolution": [float(size), float(size)],
        "fullResolution": [float(size), float(size)],
        "tileOffset": [0.0, 0.0],
        "time": float(time),
        "deltaTime": float(delta_time),
        "frame": int(frame),
        "aspect": 1.0,
        "aspectRatio": 1.0,
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
    object. The reference expander builds each graph pass from an explicit field list that
    OMITS `conditions` (shaders/src/runtime/expander.js), so `pass.conditions` is never set
    at runtime and skipping never fires from a definition's runIf/skipIf. In particular
    pointsBillboardRender's `deposit` (additive) and `deposit_alpha` (premult-over) carry
    their runIf only on the effect DEF, never on the graph pass, so BOTH always run every
    frame regardless of blendMode. We do NOT resolve conditions from the registry/def; we
    only honor an inline `conditions` if a pass dict ever literally carries one."""
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
    """
    max_texture_size = getattr(backend, "max_texture_size", None)
    if callable(max_texture_size):
        _clamp_graph_volume_sizes(graph, max_texture_size())
    defaults = collect_default_uniforms(graph)
    backend.setup(graph, defaults)
    out_name = graph.render_surface  # surface name, e.g. "o1"
    if sink_manager is not None:
        sink_manager.configure({
            "width": backend.size,
            "height": backend.size,
            "format": "rgba8unorm",
            "colorSpace": "srgb",
            "alphaMode": "premultiplied",
            "fps": 60,
        })
    sampled = {}
    prev_tt = None
    for f in range(frames):
        tt = (time + f * timestep) % 1.0 if timestep else time
        dt = 0.0 if (prev_tt is None) else (tt - prev_tt)
        prev_tt = tt
        engine = default_engine(backend.size, tt, f, dt)
        lookup = dict(engine)
        lookup.update(defaults)
        backend.frame_begin()
        for p in graph.passes:
            if should_skip(p, lookup):
                continue
            effective_pass = _resolve_pass_uniforms(p, tt, external_state or {})
            effective_lookup = dict(engine)
            effective_lookup.update(effective_pass.get("uniforms") or {})
            count = resolve_repeat_count(effective_pass, effective_lookup)
            for _ in range(count):
                backend.execute(effective_pass, graph, engine)
                for tid in effective_pass.get("outputs", {}).values():
                    backend.swap_after_write(tid)
        if sink_manager is not None:
            timestamp = clock.perf_counter() * 1000.0
            sink_manager.submit(backend.frame_read[out_name], timestamp)
        backend.frame_persist()
        # Force GPU submission periodically so long unsynced loops don't overflow Blender's
        # batched command stream (-> NaN / saturation). Read back the RENDER SURFACE (not an
        # arbitrary state surface): that forces the WHOLE frame's passes — including the
        # post-process chain — to complete, which a 1px read of an off-path surface does not
        # (the integration target's 32 passes/frame overflow otherwise). Every 30 frames.
        if timestep and (f % 30 == 29) and not (samples is not None and f in samples):
            backend.read_surface(out_name)
        if samples is not None and f in samples:
            sampled[f] = backend.read_surface(out_name)
    if samples is not None:
        return sampled
    return backend.read_surface(out_name)

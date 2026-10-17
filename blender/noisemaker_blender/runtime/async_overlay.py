"""The reference Effect.asyncInit overlays, generated on the CPU (GPU-free).

At the pinned reference three effects draw their ``overlayTex`` in an
``asyncInit`` handler instead of a render pass: ``filter/fibers``,
``filter/scratches`` and ``filter/strayHair``. Each traces worms on a 2D
canvas (``worm_tracer``, ``stroke_canvas``) and uploads the canvas with
``flipY``. The reference draws progressively over several frames; the port
generates the quiescent state, the completed overlay drawn from the step's
own parameter values, which is what the reference shows once its trace has
settled. An automated (non-scalar) value draws at the parameter's default,
as the reference does.
"""

import math

from .stroke_canvas import StrokeCanvas
from .worm_tracer import js_mod, trace_worms

# Each effect's parameter defaults (its definition's globals), as the
# reference asyncInit reads them.
_DEFAULTS = {
    "filter.fibers": {"seed": 1, "density": 0.5},
    "filter.scratches": {"seed": 1, "density": 0.3},
    "filter.strayHair": {"seed": 1, "density": 0.5},
}

OVERLAY_TEXTURE = "overlayTex"


def has_async_overlay(effect_key):
    """True when the reference definition of ``effect_key`` draws its overlay in asyncInit."""
    return effect_key in _DEFAULTS


def _scalar(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def step_uniforms(executed_pass, graph_passes):
    """The executed pass's uniforms, with each automated value as the graph holds it.

    The pipeline executes a copy of the graph's pass with automation resolved
    to the frame's value; the reference draws an automated overlay parameter
    at its default, so the graph's automation descriptor is restored.
    """
    uniforms = dict(executed_pass.get("uniforms") or {})
    for raw in graph_passes or ():
        if raw is executed_pass:
            break
        if raw.get("id") == executed_pass.get("id"):
            for name, value in (raw.get("uniforms") or {}).items():
                if isinstance(value, (dict, list)):
                    uniforms[name] = value
            break
    return uniforms


def overlay_params(effect_key, uniforms):
    """The ``params`` the reference asyncInit reads, from the step's uniforms.

    A missing or automated (non-scalar) value takes the definition default.
    """
    defaults = _DEFAULTS[effect_key]
    params = {}
    for name, default in defaults.items():
        value = (uniforms or {}).get(name, default)
        params[name] = value if _scalar(value) else default
    return params


def _seed(params):
    # `params.seed || 1`: a zero seed draws as seed 1.
    seed = params.get("seed")
    return seed if seed else 1


def _density(params, default):
    value = params.get("density")
    return default if value is None else value


def _fibers(canvas, width, height, params):
    seed = _seed(params)
    base_density = 0.5 + _density(params, 0.5) * 2.0
    line_width = max(1.5, width / 384)
    for layer in range(4):
        layer_seed = seed * 1000 + layer * 137
        trace_worms(canvas, width=width, height=height, seed=layer_seed,
                    density=base_density, kink=5 + js_mod(layer_seed, 5),
                    stride=0.75, stride_deviation=0.125, duration=1,
                    behavior="chaotic", flow_freq=4, line_width=line_width,
                    color_fn=lambda rng, _i: (math.floor(rng.float() * 200 + 55),
                                              math.floor(rng.float() * 200 + 55),
                                              math.floor(rng.float() * 200 + 55),
                                              0.5))


def _scratches(canvas, width, height, params):
    seed = _seed(params)
    density = _density(params, 0.3)
    line_width = max(0.5, width / 1024)
    for layer in range(4):
        layer_seed = seed * 1000 + layer * 251
        obedient = js_mod(layer_seed, 2) == 0
        trace_worms(canvas, width=width, height=height, seed=layer_seed,
                    density=0.1 + density * 0.4,
                    kink=0.125 + js_mod(layer_seed, 50) / 400,
                    stride=0.75, stride_deviation=0.5,
                    duration=2 + js_mod(layer_seed, 3),
                    behavior="obedient" if obedient else "unruly",
                    flow_freq=2 + js_mod(layer_seed, 3), line_width=line_width,
                    color_fn=lambda _rng, _i: (255, 255, 255, 1.0))


def _stray_hair(canvas, width, height, params):
    seed = _seed(params)
    layer_seed = seed * 1000 + 42
    trace_worms(canvas, width=width, height=height, seed=layer_seed,
                density=0.001 + _density(params, 0.5) * 0.004,
                kink=5 + js_mod(layer_seed, 45), stride=0.5, stride_deviation=0.25,
                duration=8 + js_mod(layer_seed, 8), behavior="unruly", flow_freq=4,
                line_width=max(1, width / 400),
                color_fn=lambda rng, _i: (math.floor(rng.float() * 30),
                                          math.floor(rng.float() * 30),
                                          math.floor(rng.float() * 30),
                                          0.666))


_TRACERS = {
    "filter.fibers": _fibers,
    "filter.scratches": _scratches,
    "filter.strayHair": _stray_hair,
}


def draw_overlay(effect_key, width, height, params):
    """Draw ``effect_key``'s completed overlay on a new canvas and return it."""
    canvas = StrokeCanvas(width, height)
    _TRACERS[effect_key](canvas, int(width), int(height), params)
    return canvas


def generate_overlay(effect_key, width, height, params):
    """The completed overlay: straight-alpha RGBA8, shape (height, width, 4), row 0 at the top."""
    return draw_overlay(effect_key, width, height, params).unpremultiplied_rgba8()

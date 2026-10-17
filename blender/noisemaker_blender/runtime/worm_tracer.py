"""CPU worm tracer of the reference asyncInit overlays (GPU-free).

A port of the pinned reference ``shaders/src/cpu/wormTracer.js``, which the
``filter/fibers``, ``filter/scratches`` and ``filter/strayHair`` effects call
to draw their overlay texture on a 2D canvas. The port keeps the reference's
JavaScript number semantics: double arithmetic, ``>>> 0`` and ``^`` as
ToUint32/ToInt32 conversions, ``%`` as a truncating remainder and a
``Float32Array`` flow field. The canvas is ``stroke_canvas.StrokeCanvas``.
"""

import math

import numpy as np

TAU = math.pi * 2
_TWO_32 = 4294967296


def to_uint32(value):
    """JavaScript ToUint32 (``value >>> 0``)."""
    value = float(value)
    if not math.isfinite(value):
        return 0
    return int(value) % _TWO_32


def to_int32(value):
    """JavaScript ToInt32 (the operand conversion of ``^``)."""
    unsigned = to_uint32(value)
    return unsigned - _TWO_32 if unsigned >= 0x80000000 else unsigned


def js_mod(a, b):
    """JavaScript ``a % b`` for numbers: the sign follows the dividend."""
    return math.fmod(a, b)


class SeededRNG:
    """The reference ``SeededRNG`` (a PCG-style generator in doubles)."""

    __slots__ = ("state",)

    def __init__(self, seed):
        self.state = to_uint32(float(to_uint32(seed)) * 747796405.0 + 2891336453.0)

    def next(self):
        state = to_uint32(float(self.state) * 747796405.0 + 2891336453.0)
        self.state = state
        mixed = to_int32((state >> ((state >> 28) + 4)) ^ state)
        word = to_uint32(float(mixed) * 277803737.0)
        return ((word >> 22) ^ word) & 0xFFFFFFFF

    def float(self):
        return self.next() / 4294967295.0

    def normal(self, mean=0.0, std=1.0):
        u1 = max(self.float(), 1e-10)
        u2 = self.float()
        return mean + std * math.sqrt(-2 * math.log(u1)) * math.cos(TAU * u2)


def value_noise_field(width, height, freq, rng):
    """The reference low-frequency value-noise field, float32 values in [0, 1].

    Returns a flat ``float32`` array of ``width * height`` values in row-major
    order, as the reference ``Float32Array``.
    """
    gw = math.ceil(freq) + 2
    gh = math.ceil(freq) + 2
    grid = np.array([rng.float() for _ in range(gw * gh)], dtype=np.float64)
    grid = grid.astype(np.float32).astype(np.float64)

    fx = (np.arange(width, dtype=np.float64) / width) * freq
    fy = (np.arange(height, dtype=np.float64) / height) * freq
    ix = np.floor(fx)
    iy = np.floor(fy)
    dx = fx - ix
    dy = fy - iy
    sx = dx * dx * (3 - 2 * dx)
    sy = dy * dy * (3 - 2 * dy)
    ix = ix.astype(np.int64)[None, :]
    iy = iy.astype(np.int64)[:, None]
    sx = sx[None, :]
    sy = sy[:, None]
    tl = grid[iy * gw + ix]
    tr = grid[iy * gw + ix + 1]
    bl = grid[(iy + 1) * gw + ix]
    br = grid[(iy + 1) * gw + ix + 1]
    field = (tl * (1 - sx) + tr * sx) * (1 - sy) + (bl * (1 - sx) + br * sx) * sy
    return field.astype(np.float32).reshape(-1)


def trace_worms(canvas, *, width, height, seed, density, kink, stride,
                stride_deviation, duration, behavior, flow_freq, line_width,
                color_fn, is_cancelled=None):
    """Trace worms onto ``canvas`` as the reference ``traceWorms`` does.

    ``color_fn(rng, index)`` returns ``(r, g, b, a)``. Returns False when
    ``is_cancelled()`` stopped the trace, True otherwise.
    """
    rng = SeededRNG(seed)
    min_dim = float(min(width, height))
    max_dim = float(max(width, height))
    stride_scale = max_dim / 1024

    flow = value_noise_field(width, height, flow_freq, SeededRNG(seed * 31337))
    flow_values = flow.astype(np.float64).tolist()

    count = max(1.0, math.floor(max_dim * density))
    shared_rot = rng.float() * TAU
    obedient = behavior == "obedient"

    worms = []
    index = 0
    while index < count:
        x = rng.float() * width
        y = rng.float() * height
        worm_stride = rng.normal(stride, stride_deviation) * stride_scale
        rot = shared_rot if obedient else rng.float() * TAU
        color = color_fn(rng, index)
        worms.append((x, y, worm_stride, rot, color))
        index += 1

    iterations = max(1, math.floor(math.sqrt(min_dim) * duration))
    canvas.set_line_width(line_width)

    wd = float(width)
    hd = float(height)
    last = iterations - 1
    fmod = math.fmod
    floor = math.floor
    sin = math.sin
    cos = math.cos
    set_color = canvas.set_stroke_color
    stroke = canvas.stroke_line
    for x, y, worm_stride, rot, (r, g, b, a) in worms:
        if is_cancelled is not None and is_cancelled():
            return False
        base = shared_rot if obedient else rot
        wx = x
        wy = y
        for it in range(iterations):
            t = it / last if iterations > 1 else 1
            exposure = 1 - abs(1 - t * 2)
            fx = floor(fmod(fmod(wx, wd) + wd, wd))
            fy = floor(fmod(fmod(wy, hd) + hd, hd))
            angle = flow_values[fy * width + fx] * TAU * kink
            angle += base
            new_x = wx + sin(angle) * worm_stride
            new_y = wy + cos(angle) * worm_stride
            set_color(r, g, b, a * exposure)
            stroke(wx, wy, new_x, new_y)
            wx = new_x
            wy = new_y
    return True

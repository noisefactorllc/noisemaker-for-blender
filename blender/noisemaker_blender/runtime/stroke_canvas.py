"""CPU model of the 2D canvas the reference asyncInit overlays draw on (GPU-free).

The reference traces worms and strokes each step as a round-capped line
segment on a 2D context created with ``willReadFrequently``, which pins the
canvas to Skia's CPU raster back end, then uploads the canvas as the overlay
texture. This module models that canvas:

- Blink culls a stroke whose bounding box, outset by ``lineWidth / 2``, does
  not meet the canvas, and prunes a path whose points coincide.
- ``rgba(r, g, b, a)`` becomes an 8-bit colour: channels clamp and round,
  alpha becomes ``floor(a * 255 + 0.5)``.
- A stroke at most 1 px wide is a hairline. A thinner width ``w`` scales the
  alpha by ``(int)(w * 256) >> 8``. Skia's ``SkScan::AntiHairRoundPath``
  draws it in 26.6 and 16.16 fixed point; this module ports it exactly.
- A wider stroke is filled by Skia's analytic anti-aliasing, which this
  module does not port. It approximates the coverage of the round-capped
  outline with a box-filtered edge at the distance to the segment, and
  blends that coverage with Skia's exact mask arithmetic.
- Pixels are the legacy N32 blitters in their integer arithmetic.
- The upload divides alpha out as Skia's raster pipeline does, in float32.

The hairline scan conversion, line clipping and blitters port Skia
(https://skia.org) at commit 9d07e5bad9e3e21da2426946e589daa647218271
(src/core/SkScan_Antihair.cpp, SkLineClipper.cpp, SkBlitter.cpp,
SkBlitter_ARGB32.cpp, SkColorData.h, SkColorPriv.h, src/opts/SkBlitRow_opts.h
and SkBlitMask_opts.h), following the noisemaker-for-qt port of the same code.

Skia's license:

Copyright (c) 2011 Google Inc. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in
    the documentation and/or other materials provided with the
    distribution.

  * Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived
    from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import math
import struct

import numpy as np

_F32 = struct.Struct("<f")
_U32 = 0xFFFFFFFF
_MASK = 0x00FF00FF
_INV_MASK = 0xFF00FF00
_INT32_MIN = -2147483648
_INT32_MAX = 2147483647

# Which legacy N32 blitter SkBlitter::Choose returns for the paint.
_TRANSLUCENT = 0  # SkARGB32_Blitter: alpha below 255
_OPAQUE = 1       # SkARGB32_Opaque_Blitter
_BLACK = 2        # SkARGB32_Black_Blitter: opaque black

# The four SkAntiHairBlitter strategies by slope.
_HLINE, _HORISH, _VLINE, _VERTISH = range(4)

_FDOT6_ONE = 64
_FDOT6_HALF = 32
_FIXED_HALF = 1 << 15
_SCALAR_NEARLY_ZERO = 1.0 / 4096.0

# Pixel-vertex pairs per vectorized fill batch: bounds the coverage arrays' memory.
_FILL_BUDGET = 1 << 20


def f32(value):
    """Round a double to the nearest float32 (as a C++ float store does)."""
    try:
        return _F32.unpack(_F32.pack(value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _to_i32(value):
    """Saturating float-to-int32 conversion, NaN giving 0."""
    if value != value:
        return 0
    if value >= 2147483647.0:
        return _INT32_MAX
    if value <= -2147483648.0:
        return _INT32_MIN
    return int(value)


def _to_u8(value):
    if value != value or value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return int(value)


def _wrap32(value):
    """Two's-complement wrap of an integer to int32."""
    value &= _U32
    return value - 0x100000000 if value & 0x80000000 else value


def _tdiv(a, b):
    """C++ integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


# ------------------------------------------------------------ pixel math

def _pack(a, r, g, b):
    return (a << 24) | (r << 16) | (g << 8) | b


def _mul_div_255_round(a, b):
    prod = a * b + 128
    return (prod + (prod >> 8)) >> 8


def _premultiply(color):
    r, g, b, a = color
    if a == 255:
        return _pack(a, r, g, b)
    return _pack(a, _mul_div_255_round(r, a), _mul_div_255_round(g, a),
                 _mul_div_255_round(b, a))


def _alpha_mul_q(c, scale):
    rb = ((c & _MASK) * scale) >> 8
    ag = ((c >> 8) & _MASK) * scale
    return ((rb & _MASK) | (ag & _INV_MASK)) & _U32


def _alpha_mul_inv256(value, alpha256):
    prod = (0xFFFF - value * alpha256) & _U32
    return (prod + (prod >> 8)) >> 8


def _blend_argb32(src, dst, aa):
    src_scale = aa + 1
    dst_scale = _alpha_mul_inv256(src >> 24, src_scale)
    src_rb = ((src & _MASK) * src_scale) & _U32
    src_ag = (((src >> 8) & _MASK) * src_scale) & _U32
    dst_rb = ((dst & _MASK) * dst_scale) & _U32
    dst_ag = (((dst >> 8) & _MASK) * dst_scale) & _U32
    return (((((src_rb + dst_rb) & _U32) >> 8) & _MASK)
            | ((src_ag + dst_ag) & _INV_MASK))


def _splay(c):
    return (((c >> 8) & _MASK) << 32) | (c & _MASK)


def _fast_four_byte_interp(src, dst, weight):
    scale = weight + (weight >> 7)
    agrb = (_splay(src) * scale + (256 - scale) * _splay(dst)) & 0xFFFFFFFFFFFFFFFF
    return (((agrb & _INV_MASK) >> 8) | ((agrb >> 32) & _INV_MASK)) & _U32


def _color32(dst, color):
    """SkBlitRow::Color32 on one pixel."""
    a = color >> 24
    if a == 0:
        return dst
    if a == 255:
        return color
    inv = 256 - a
    out = 0
    for shift in (0, 8, 16, 24):
        d = (dst >> shift) & 0xFF
        c = (color >> shift) & 0xFF
        out |= ((((d * inv) >> 8) + c) & 0xFF) << shift
    return out


# ------------------------------------------------------------ blitters

class _ArgbBlitter:
    """The device blitter: a solid colour over the canvas pixels."""

    __slots__ = ("pixels", "width", "pm", "src_a", "kind")

    def __init__(self, pixels, width, color):
        self.pixels = pixels
        self.width = width
        self.pm = _premultiply(color)
        self.src_a = color[3]
        if color == (0, 0, 0, 255):
            self.kind = _BLACK
        elif color[3] == 255:
            self.kind = _OPAQUE
        else:
            self.kind = _TRANSLUCENT

    def blit_h(self, x, y, width):
        px = self.pixels
        base = y * self.width
        for i in range(width):
            px[base + x + i] = _color32(px[base + x + i], self.pm)

    def blit_anti_h(self, x, y, aa):
        if self.kind == _TRANSLUCENT and self.src_a == 0:
            return
        px = self.pixels
        base = y * self.width + x
        for i, a in enumerate(aa):
            if a == 0:
                continue
            p = px[base + i]
            if self.kind == _BLACK:
                px[base + i] = 0xFF000000 if a == 255 else (
                    ((a << 24) + _alpha_mul_q(p, 256 - a)) & _U32)
            elif self.kind == _OPAQUE and a == 255:
                px[base + i] = self.pm
            else:
                px[base + i] = _color32(p, _alpha_mul_q(self.pm, a + 1))

    def blit_v(self, x, y, height, alpha):
        if alpha == 0 or self.src_a == 0:
            return
        color = self.pm
        if alpha != 255:
            color = _alpha_mul_q(color, alpha + 1)
        dst_scale = 256 - (color >> 24)
        px = self.pixels
        for row in range(height):
            i = (y + row) * self.width + x
            px[i] = (color + _alpha_mul_q(px[i], dst_scale)) & _U32

    def blit_rect(self, x, y, width, height):
        if self.src_a == 0:
            return
        for row in range(height):
            self.blit_h(x, y + row, width)

    def blit_anti_h2(self, x, y, a0, a1):
        self._blend_pixel(x, y, a0)
        self._blend_pixel(x + 1, y, a1)

    def blit_anti_v2(self, x, y, a0, a1):
        self._blend_pixel(x, y, a0)
        self._blend_pixel(x, y + 1, a1)

    def _blend_pixel(self, x, y, a):
        i = y * self.width + x
        p = self.pixels[i]
        if self.kind == _TRANSLUCENT:
            self.pixels[i] = _blend_argb32(self.pm, p, a)
        elif self.kind == _OPAQUE:
            self.pixels[i] = _fast_four_byte_interp(self.pm, p, a)
        else:
            self.pixels[i] = ((a << 24) + _alpha_mul_q(p, 256 - a)) & _U32


class _RectClipBlitter:
    """SkRectClipBlitter. blitAntiH2/blitAntiV2 take SkBlitter's defaults."""

    __slots__ = ("inner", "left", "top", "right", "bottom")

    def __init__(self, inner, clip):
        self.inner = inner
        self.left, self.top, self.right, self.bottom = clip

    def blit_h(self, x, y, width):
        if y < self.top or y >= self.bottom:
            return
        left = max(x, self.left)
        right = min(x + width, self.right)
        if right > left:
            self.inner.blit_h(left, y, right - left)

    def blit_anti_h(self, x, y, aa):
        if y < self.top or y >= self.bottom or x >= self.right:
            return
        x1 = x + len(aa)
        if x1 <= self.left:
            return
        x0 = max(x, self.left)
        end = min(x1, self.right)
        self.inner.blit_anti_h(x0, y, aa[x0 - x:end - x])

    def blit_v(self, x, y, height, alpha):
        if x < self.left or x >= self.right:
            return
        y0 = max(y, self.top)
        y1 = min(y + height, self.bottom)
        if y0 < y1:
            self.inner.blit_v(x, y0, y1 - y0, alpha)

    def blit_anti_h2(self, x, y, a0, a1):
        self.blit_anti_h(x, y, (a0, a1))

    def blit_anti_v2(self, x, y, a0, a1):
        self.blit_anti_h(x, y, (a0,))
        self.blit_anti_h(x, y + 1, (a1,))


# ------------------------------------------------- anti-aliased hairlines

def _fdot6_floor(x):
    return x >> 6


def _fdot6_ceil(x):
    return _wrap32(x + 63) >> 6


def _fdot6_to_fixed(x):
    return _wrap32(x << 10)


def _fixed_floor(x):
    return x >> 16


def _fixed_ceil(x):
    return _wrap32(x + 0xFFFF) >> 16


def _fast_fix_div(a, b):
    return _tdiv(_wrap32(a << 16), b)


def _fd6_frac(x):
    return x & (_FDOT6_ONE - 1)


def _partial_pixel_coverage(pos):
    return _fd6_frac(pos - 1) + 1


def _scale_alpha(value, coverage):
    return ((value * coverage) & _U32) >> 6 & 0xFF


def _fixed_to_alpha(f):
    return (f >> 8) & 0xFF


def _hline(blitter, x, y, count, alpha):
    blitter.blit_anti_h(x, y, (alpha,) * max(count, 0))


def _draw_cap(kind, blitter, x, f, slope, coverage):
    f = _wrap32(f + _FIXED_HALF)
    i = _fixed_floor(f)
    a = _fixed_to_alpha(f)
    if kind == _HLINE:
        ma = _scale_alpha(a, coverage)
        if ma:
            _hline(blitter, x, i, 1, ma)
        ma = _scale_alpha(255 - a, coverage)
        if ma:
            _hline(blitter, x, i - 1, 1, ma)
        return _wrap32(f - _FIXED_HALF)
    if kind == _HORISH:
        blitter.blit_anti_v2(x, i - 1, _scale_alpha(255 - a, coverage), _scale_alpha(a, coverage))
        return _wrap32(f + slope - _FIXED_HALF)
    if kind == _VLINE:
        ma = _scale_alpha(a, coverage)
        if ma:
            blitter.blit_v(i, x, 1, ma)
        ma = _scale_alpha(255 - a, coverage)
        if ma:
            blitter.blit_v(i - 1, x, 1, ma)
        return _wrap32(f - _FIXED_HALF)
    blitter.blit_anti_h2(i - 1, x, _scale_alpha(255 - a, coverage), _scale_alpha(a, coverage))
    return _wrap32(f + slope - _FIXED_HALF)


def _draw_line(kind, blitter, start, stop, f, slope):
    f = _wrap32(f + _FIXED_HALF)
    if kind == _HLINE:
        y = _fixed_floor(f)
        a = _fixed_to_alpha(f)
        if a:
            _hline(blitter, start, y, stop - start, a)
        a = 255 - a
        if a:
            _hline(blitter, start, y - 1, stop - start, a)
    elif kind == _HORISH:
        for x in range(start, stop):
            lower = _fixed_floor(f)
            a = _fixed_to_alpha(f)
            blitter.blit_anti_v2(x, lower - 1, 255 - a, a)
            f = _wrap32(f + slope)
    elif kind == _VLINE:
        x = _fixed_floor(f)
        a = _fixed_to_alpha(f)
        if a:
            blitter.blit_v(x, start, stop - start, a)
        a = 255 - a
        if a:
            blitter.blit_v(x - 1, start, stop - start, a)
    else:
        for y in range(start, stop):
            x = _fixed_floor(f)
            a = _fixed_to_alpha(f)
            blitter.blit_anti_h2(x - 1, y, 255 - a, a)
            f = _wrap32(f + slope)
    return _wrap32(f - _FIXED_HALF)


def _draw_hair(kind, blitter, istart, istop, fstart, slope, start_cov, stop_cov):
    f = _draw_cap(kind, blitter, istart, fstart, slope, start_cov)
    istart += 1
    full_spans = istop - istart - (1 if stop_cov > 0 else 0)
    if full_spans > 0:
        f = _draw_line(kind, blitter, istart, istart + full_spans, f, slope)
    if stop_cov > 0:
        _draw_cap(kind, blitter, istop - 1, f, slope, stop_cov)


def _do_anti_hairline(x0, y0, x1, y1, clip, blitter):
    """do_anti_hairline in 26.6 fixed point; ``clip`` (l, t, r, b) or None."""
    if _INT32_MIN in (x0, y0, x1, y1):
        return
    if (abs(_wrap32(x1 - x0)) > 511 * _FDOT6_ONE
            or abs(_wrap32(y1 - y0)) > 511 * _FDOT6_ONE):
        hx = (x0 >> 1) + (x1 >> 1)
        hy = (y0 >> 1) + (y1 >> 1)
        _do_anti_hairline(x0, y0, hx, hy, clip, blitter)
        _do_anti_hairline(hx, hy, x1, y1, clip, blitter)
        return

    clipped = clip is not None
    if clipped:
        cl, ct, cr, cb = clip
    if abs(x1 - x0) > abs(y1 - y0):
        # Mostly horizontal: left to right.
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        istart = _fdot6_floor(x0)
        istop = _fdot6_ceil(x1)
        if y0 == y1:
            slope = 0
            kind = _HLINE
            fstart = _fdot6_to_fixed(y0)
        else:
            slope = _fast_fix_div(y1 - y0, x1 - x0)
            dx_to_center = _FDOT6_HALF - _fd6_frac(x0)
            fstart = _wrap32(_fdot6_to_fixed(y0) + (_wrap32(slope * dx_to_center + _FDOT6_HALF) >> 6))
            kind = _HORISH
        if istop - istart == 1:
            start_cov = x1 - x0
            stop_cov = 0
        else:
            start_cov = _FDOT6_ONE - _fd6_frac(x0)
            stop_cov = _fd6_frac(x1)
        if clipped:
            if istart >= cr or istop <= cl:
                return
            if istart < cl:
                fstart = _wrap32(fstart + slope * (cl - istart))
                istart = cl
                start_cov = _FDOT6_ONE
                if istop - istart == 1:
                    start_cov = _partial_pixel_coverage(x1)
                    stop_cov = 0
            if istop > cr:
                istop = cr
                stop_cov = 0
            if istart == istop:
                return
            span = _wrap32(slope * (istop - istart - 1))
            if slope >= 0:
                top = _fixed_floor(_wrap32(fstart - _FIXED_HALF))
                bottom = _fixed_ceil(_wrap32(fstart + span + _FIXED_HALF))
            else:
                bottom = _fixed_ceil(_wrap32(fstart + _FIXED_HALF))
                top = _fixed_floor(_wrap32(fstart + span - _FIXED_HALF))
            top -= 1
            bottom += 1
            if top >= cb or bottom <= ct:
                return
            if ct <= top and cb >= bottom:
                clipped = False
    else:
        # Mostly vertical: top to bottom.
        if y0 > y1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        istart = _fdot6_floor(y0)
        istop = _fdot6_ceil(y1)
        if x0 == x1:
            if y0 == y1:
                return
            slope = 0
            kind = _VLINE
            fstart = _fdot6_to_fixed(x0)
        else:
            slope = _fast_fix_div(x1 - x0, y1 - y0)
            dy_to_center = _FDOT6_HALF - _fd6_frac(y0)
            fstart = _wrap32(_fdot6_to_fixed(x0) + (_wrap32(slope * dy_to_center + _FDOT6_HALF) >> 6))
            kind = _VERTISH
        if istop - istart == 1:
            start_cov = y1 - y0
            stop_cov = 0
        else:
            start_cov = _FDOT6_ONE - _fd6_frac(y0)
            stop_cov = _fd6_frac(y1)
        if clipped:
            if istart >= cb or istop <= ct:
                return
            if istart < ct:
                fstart = _wrap32(fstart + slope * (ct - istart))
                istart = ct
                start_cov = _FDOT6_ONE
                if istop - istart == 1:
                    start_cov = _partial_pixel_coverage(y1)
                    stop_cov = 0
            if istop > cb:
                istop = cb
                stop_cov = 0
            if istart == istop:
                return
            span = _wrap32(slope * (istop - istart - 1))
            if slope >= 0:
                left = _fixed_floor(_wrap32(fstart - _FIXED_HALF))
                right = _fixed_ceil(_wrap32(fstart + span + _FIXED_HALF))
            else:
                right = _fixed_ceil(_wrap32(fstart + _FIXED_HALF))
                left = _fixed_floor(_wrap32(fstart + span - _FIXED_HALF))
            left -= 1
            right += 1
            if left >= cr or right <= cl:
                return
            if cl <= left and cr >= right:
                clipped = False

    if clipped:
        blitter = _RectClipBlitter(blitter, clip)
    _draw_hair(kind, blitter, istart, istop, fstart, slope, start_cov, stop_cov)


# ------------------------------------------------------------ line clipper

def _midpoint(a, b):
    return f32((a + b) * 0.5)


def _pin_unsorted(value, lo, hi):
    if hi < lo:
        lo, hi = hi, lo
    return lo if value < lo else hi if value > hi else value


def _sect_with_horizontal(src, y):
    (x0, y0), (x1, y1) = src
    dy = f32(y1 - y0)
    if abs(dy) <= _SCALAR_NEARLY_ZERO:
        return _midpoint(x0, x1)
    result = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    return f32(_pin_unsorted(result, x0, x1))


def _sect_with_vertical(src, x):
    (x0, y0), (x1, y1) = src
    dx = f32(x1 - x0)
    if abs(dx) <= _SCALAR_NEARLY_ZERO:
        return _midpoint(y0, y1)
    return f32(y0 + (x - x0) * (y1 - y0) / (x1 - x0))


def _nested_lt(a, b, dim):
    return a <= b and (a < b or dim > 0.0)


def _intersect_line(src, clip):
    """SkLineClipper::IntersectLine; the clipped points, or None."""
    (sx0, sy0), (sx1, sy1) = src
    cl, ct, cr, cb = clip
    bl, bt = min(sx0, sx1), min(sy0, sy1)
    br, bb = max(sx0, sx1), max(sy0, sy1)
    if cl <= bl and ct <= bt and cr >= br and cb >= bb:
        return [src[0], src[1]]
    bw = f32(br - bl)
    bh = f32(bb - bt)
    if (_nested_lt(br, cl, bw) or _nested_lt(cr, bl, bw)
            or _nested_lt(bb, ct, bh) or _nested_lt(cb, bt, bh)):
        return None
    i0 = 0 if sy0 < sy1 else 1
    i1 = 1 - i0
    tmp = [src[0], src[1]]
    if tmp[i0][1] < ct:
        tmp[i0] = (_sect_with_horizontal(src, ct), ct)
    if tmp[i1][1] > cb:
        tmp[i1] = (_sect_with_horizontal(src, cb), cb)
    i0 = 0 if tmp[0][0] < tmp[1][0] else 1
    i1 = 1 - i0
    if ((tmp[i1][0] <= cl or tmp[i0][0] >= cr)
            and (tmp[0][0] != tmp[1][0] or tmp[0][0] < cl or tmp[0][0] > cr)):
        return None
    if tmp[i0][0] < cl:
        tmp[i0] = (cl, _sect_with_vertical(tmp, cl))
    if tmp[i1][0] > cr:
        tmp[i1] = (cr, _sect_with_vertical(tmp, cr))
    return tmp


def _to_fdot6(x):
    """SkScalarToFDot6: (int)(x * 64), truncating."""
    return _to_i32(f32(x * 64.0))


def _rect_intersects(a, b):
    return (a[0] < a[2] and a[1] < a[3] and b[0] < b[2] and b[1] < b[3]
            and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def _rect_contains(a, b):
    return (b[0] < b[2] and b[1] < b[3] and a[0] < a[2] and a[1] < a[3]
            and a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3])


def _anti_hair_line(pts, clip, blitter):
    """SkScan::AntiHairLineRgn for one segment; ``clip`` the canvas or None."""
    fixed = (-32767.0, -32767.0, 32767.0, 32767.0)
    pts = _intersect_line(pts, fixed)
    if pts is None:
        return
    if clip is not None:
        bounds = (f32(clip[0] - 1.0), f32(clip[1] - 1.0), f32(clip[2] + 1.0), f32(clip[3] + 1.0))
        pts = _intersect_line(pts, bounds)
        if pts is None:
            return
    x0 = _to_fdot6(pts[0][0])
    y0 = _to_fdot6(pts[0][1])
    x1 = _to_fdot6(pts[1][0])
    y1 = _to_fdot6(pts[1][1])
    if clip is not None:
        ir = (_fdot6_floor(min(x0, x1)) - 1, _fdot6_floor(min(y0, y1)) - 1,
              _fdot6_ceil(max(x0, x1)) + 1, _fdot6_ceil(max(y0, y1)) + 1)
        if not _rect_intersects(clip, ir):
            return
        if not _rect_contains(clip, ir):
            r = (max(clip[0], ir[0]), max(clip[1], ir[1]), min(clip[2], ir[2]), min(clip[3], ir[3]))
            if r[0] < r[2] and r[1] < r[3]:
                _do_anti_hairline(x0, y0, x1, y1, r, blitter)
            return
    _do_anti_hairline(x0, y0, x1, y1, None, blitter)


def _normalize(x, y):
    """SkPoint::normalize through doubles; None for a zero or non-finite vector."""
    dmag = math.sqrt(x * x + y * y)
    if dmag == 0.0:
        return None
    dscale = 1.0 / dmag
    nx = f32(x * dscale)
    ny = f32(y * dscale)
    if not (math.isfinite(nx) and math.isfinite(ny)) or (nx == 0.0 and ny == 0.0):
        return None
    return nx, ny


_CAP_OUTSET = f32(f32(math.pi) / 8.0)


def _anti_hair_round_line(x0, y0, x1, y1, canvas_rect, blitter):
    """SkScan::AntiHairRoundPath of a moveTo/lineTo path."""
    ib = (_to_i32(math.floor(min(x0, x1))) - 2, _to_i32(math.floor(min(y0, y1))) - 2,
          _to_i32(math.ceil(max(x0, x1))) + 2, _to_i32(math.ceil(max(y0, y1))) + 2)
    if not _rect_intersects(canvas_rect, ib):
        return
    clip = None if _rect_contains(canvas_rect, ib) else canvas_rect
    # extend_pts: each end moves out along its tangent by pi / 8; the end is
    # extended after the start has moved, from the moved start.
    first = _normalize(f32(x0 - x1), f32(y0 - y1)) or (1.0, 0.0)
    x0 = f32(x0 + f32(first[0] * _CAP_OUTSET))
    y0 = f32(y0 + f32(first[1] * _CAP_OUTSET))
    last = _normalize(f32(x1 - x0), f32(y1 - y0)) or (-1.0, 0.0)
    x1 = f32(x1 + f32(last[0] * _CAP_OUTSET))
    y1 = f32(y1 + f32(last[1] * _CAP_OUTSET))
    _anti_hair_line([(x0, y0), (x1, y1)], clip, blitter)


# ------------------------------------------------------------ wide strokes
#
# SkStroke outlines a round-capped segment as the outer line, two
# quarter-circle conics around the end, the reversed inner line and two
# conics around the start. Below about 4 px of radius each conic becomes one
# quad (its control point at the corner), which the analytic edge walker
# chops at its y extremum and flattens into 2^shift lines, and edge ends snap
# to quarter-pixel rows. The model below builds that polygon, snaps its
# vertices to quarter rows and takes the exact area of its intersection with
# each pixel. Skia's analytic accumulation differs from that exact area by a
# few coverage levels.

def _quad_points(q0x, q0y, qcx, qcy, q2x, q2y, segments):
    """Flattened points of each quad after its start: (count, 2 * segments) x and y.

    A quad with a y extremum inside (0, 1) is chopped there and each half is
    flattened into ``segments`` lines; a monotonic quad is flattened into
    ``segments`` lines and padded with repeated end points.
    """
    den = q0y - 2.0 * qcy + q2y
    with np.errstate(divide="ignore", invalid="ignore"):
        t_ext = np.where(den != 0.0, (q0y - qcy) / den, -1.0)
    chopped = (t_ext > 0.0) & (t_ext < 1.0)
    k = np.arange(1, segments + 1, dtype=np.float64) / segments
    first = t_ext[:, None] * k[None, :]
    second = t_ext[:, None] + (1.0 - t_ext[:, None]) * k[None, :]
    plain = np.concatenate([np.repeat(k[None, :], len(q0x), 0),
                            np.ones((len(q0x), segments))], axis=1)
    t = np.where(chopped[:, None], np.concatenate([first, second], axis=1), plain)
    u = 1.0 - t
    xs = u * u * q0x[:, None] + 2.0 * u * t * qcx[:, None] + t * t * q2x[:, None]
    ys = u * u * q0y[:, None] + 2.0 * u * t * qcy[:, None] + t * t * q2y[:, None]
    return xs, ys


def _quad_shift(radius):
    """diff_to_shift for a quarter-circle quad of ``radius`` at the AA scale."""
    d = radius * 256.0 / 4.0
    dist = int(d + d / 2.0)
    dist = (dist + 16) >> 5
    return min(max(dist.bit_length() >> 1, 1), 6)


def _stroke_outlines(x0, y0, x1, y1, radius):
    """Closed outline polygons of round-capped strokes: (count, vertices) x and y."""
    dx = x1 - x0
    dy = y1 - y0
    length = np.sqrt(dx * dx + dy * dy)
    ok = length > 0.0
    safe = np.where(ok, length, 1.0)
    nx = np.where(ok, dy / safe * radius, radius)
    ny = np.where(ok, -dx / safe * radius, 0.0)
    px = -ny
    py = nx
    segments = 1 << _quad_shift(radius)

    def cap(cx_, cy_, mx, my, ppx, ppy, sx, sy, ex, ey):
        tipx = cx_ + ppx
        tipy = cy_ + ppy
        a = _quad_points(sx, sy, tipx + mx, tipy + my, tipx, tipy, segments)
        b = _quad_points(tipx, tipy, tipx - mx, tipy - my, ex, ey, segments)
        return np.concatenate([a[0], b[0]], axis=1), np.concatenate([a[1], b[1]], axis=1)

    ax, ay = x0 + nx, y0 + ny
    bx, by = x1 + nx, y1 + ny
    cx, cy = x0 - nx, y0 - ny
    end_x, end_y = cap(x1, y1, nx, ny, px, py, bx, by, x1 - nx, y1 - ny)
    start_x, start_y = cap(x0, y0, -nx, -ny, -px, -py, cx, cy, ax, ay)
    xs = np.concatenate([ax[:, None], bx[:, None], end_x, cx[:, None], start_x[:, :-1]], axis=1)
    ys = np.concatenate([ay[:, None], by[:, None], end_y, cy[:, None], start_y[:, :-1]], axis=1)
    return xs, np.floor(ys * 4.0 + 0.5) / 4.0


def _clamped_ramp_integral(u):
    """Antiderivative of clamp(u, 0, 1)."""
    return np.where(u <= 0.0, 0.0, np.where(u >= 1.0, u - 0.5, 0.5 * u * u))


def _expand(counts):
    """For each item i repeated counts[i] times: the item index and the repeat index."""
    item = np.repeat(np.arange(counts.size), counts)
    step = np.arange(item.size) - np.repeat(np.cumsum(counts) - counts, counts)
    return item, step


def _polygon_coverage(xs, ys, left, top, bw, bh, base):
    """Exact area of each closed polygon (rows of xs, ys) inside each pixel of its box.

    Box ``i`` holds ``bw[i] * bh[i]`` pixels from (left[i], top[i]), stored
    row by row from ``base[i]`` in the result. A pixel's area is the sum over
    the polygon's edges of the signed integral of clamp(y(x) - py, 0, 1) over
    the part of the edge above the pixel's column; rows above a closed
    polygon sum to zero, so each edge is integrated from the box's top row
    down to the edge.
    """
    count, vertices = xs.shape
    xb = np.roll(xs, -1, axis=1)
    yb = np.roll(ys, -1, axis=1)
    dxe = xb - xs
    moving = dxe != 0.0
    slope = np.where(moving, (yb - ys) / np.where(moving, dxe, 1.0), 0.0)
    lo = np.minimum(xs, xb)
    hi = np.maximum(xs, xb)
    first_col = np.maximum(np.floor(lo), left[:, None].astype(np.float64))
    end_col = np.minimum(np.ceil(hi), (left + bw)[:, None].astype(np.float64))
    ncols = np.where(moving, np.maximum(end_col - first_col, 0.0), 0.0).astype(np.int64).ravel()
    edge, step = _expand(ncols)
    stroke = edge // vertices
    col = first_col.ravel()[edge] + step
    x_left = np.maximum(lo.ravel()[edge], col)
    x_right = np.minimum(hi.ravel()[edge], col + 1.0)
    keep = x_right > x_left
    edge, stroke, col, x_left, x_right = (v[keep] for v in (edge, stroke, col, x_left, x_right))
    m = slope.ravel()[edge]
    xa = xs.ravel()[edge]
    ya = ys.ravel()[edge]
    y_left = ya + (x_left - xa) * m
    y_right = ya + (x_right - xa) * m
    row_end = np.minimum(np.ceil(np.maximum(y_left, y_right)), (top + bh)[stroke])
    nrows = np.maximum(row_end - top[stroke], 0.0).astype(np.int64)
    pair, row_step = _expand(nrows)
    stroke = stroke[pair]
    row = top[stroke] + row_step
    g0 = y_left[pair] - row
    g1 = y_right[pair] - row
    m = m[pair]
    width = (x_right - x_left)[pair]
    flat = np.abs(m) < 1e-12
    ramp = np.where(flat, np.clip(g0, 0.0, 1.0) * width,
                    (_clamped_ramp_integral(g1) - _clamped_ramp_integral(g0))
                    / np.where(flat, 1.0, m))
    value = np.sign(dxe.ravel()[edge])[pair] * ramp
    cell = base[stroke] + row_step * bw[stroke] + (col[pair].astype(np.int64) - left[stroke])
    total = int(base[-1] + bw[-1] * bh[-1]) if count else 0
    return np.abs(np.bincount(cell, weights=value, minlength=total))


def _blit_masks(pixels, width, height, x0, y0, x1, y1, radius, pm, src_a, kind):
    """Fill wide strokes of one ``radius`` in order.

    ``pixels`` is the canvas as a flat uint32 array of premultiplied colours;
    ``pm``, ``src_a`` and ``kind`` are each stroke's premultiplied colour,
    straight alpha and blitter.
    """
    count = x0.size
    outline_x, outline_y = _stroke_outlines(x0, y0, x1, y1, radius)
    left = np.clip(np.floor(outline_x.min(axis=1)), 0, width).astype(np.int64)
    right = np.clip(np.ceil(outline_x.max(axis=1)), 0, width).astype(np.int64)
    top = np.clip(np.floor(outline_y.min(axis=1)), 0, height).astype(np.int64)
    bottom = np.clip(np.ceil(outline_y.max(axis=1)), 0, height).astype(np.int64)
    bw = np.maximum(right - left, 0)
    bh = np.maximum(bottom - top, 0)
    sizes = bw * bh
    total = int(sizes.sum())
    if total == 0:
        return
    base = np.cumsum(sizes) - sizes
    coverage = _polygon_coverage(outline_x, outline_y, left, top, bw, bh, base)
    seg, offset = _expand(sizes)
    row_w = bw[seg]
    px = left[seg] + offset % row_w
    py = top[seg] + offset // row_w
    m = np.clip(np.rint(coverage * 255.0), 0, 255).astype(np.int64)

    keep = m > 0
    seg = seg[keep]
    m = m[keep]
    index = (py * width + px)[keep]
    if index.size == 0:
        return
    # Strokes blend in order: rank each contribution within its pixel.
    order = np.argsort(index, kind="stable")
    index = index[order]
    seg = seg[order]
    m = m[order]
    first = np.r_[True, index[1:] != index[:-1]]
    group_start = np.maximum.accumulate(np.where(first, np.arange(index.size), 0))
    rank = np.arange(index.size) - group_start
    by_rank = np.argsort(rank, kind="stable")
    rank = rank[by_rank]
    index = index[by_rank]
    seg = seg[by_rank]
    m = m[by_rank]
    bounds = np.searchsorted(rank, np.arange(int(rank[-1]) + 2))
    for level in range(int(rank[-1]) + 1):
        lo_i, hi_i = bounds[level], bounds[level + 1]
        if lo_i == hi_i:
            continue
        idx = index[lo_i:hi_i]
        s = seg[lo_i:hi_i]
        mm = m[lo_i:hi_i]
        active = ~((kind[s] == _TRANSLUCENT) & (src_a[s] == 0))
        idx, s, mm = idx[active], s[active], mm[active]
        dst = pixels[idx].astype(np.int64)
        color = pm[s].astype(np.int64)
        k = kind[s]
        m256 = mm + 1
        scale = np.where(k == _TRANSLUCENT, 256 - (((color >> 24) * m256) >> 8), 256 - mm)
        out = np.zeros_like(dst)
        black = np.zeros_like(dst)
        for shift in (0, 8, 16, 24):
            c = (color >> shift) & 0xFF
            d = (dst >> shift) & 0xFF
            out |= ((((c * m256) >> 8) + ((d * scale) >> 8)) & 0xFF) << shift
            black |= (((d * (256 - mm)) >> 8) & 0xFF) << shift
        black = (black + (mm << 24)) & _U32
        pixels[idx] = np.where(k == _BLACK, black, out).astype(np.uint32)


# ------------------------------------------------------------ the canvas

def _premultiply_all(r, g, b, a):
    """_premultiply of colour arrays: SkPMColor uint32 values."""
    def channel(c):
        prod = c * a + 128
        return np.where(a == 255, c, (prod + (prod >> 8)) >> 8)

    return ((a << 24) | (channel(r) << 16) | (channel(g) << 8) | channel(b)).astype(np.uint32)


class StrokeCanvas:
    """The reference 2D canvas: a transparent RGBA8 surface, row 0 at the top.

    Strokes queue in drawing order and are drawn when the pixels are read
    (or the queue fills): the stroke tests, colour conversion and wide-stroke
    coverage run vectorized, and every stroke still blends in order.
    """

    _QUEUE_LIMIT = 1 << 16

    def __init__(self, width, height):
        if width <= 0 or height <= 0:
            raise ValueError("StrokeCanvas: width and height must be positive")
        self.width = int(width)
        self.height = int(height)
        self._pixels = np.zeros(self.width * self.height, dtype=np.uint32)
        self._line_width = 1.0
        self._style = (0.0, 0.0, 0.0, 1.0)
        self._queue = []

    def clear(self):
        """``clearRect(0, 0, width, height)``."""
        self._queue = []
        self._pixels = np.zeros(self.width * self.height, dtype=np.uint32)

    def set_line_width(self, width):
        """``ctx.lineWidth = width``; non-finite and non-positive values are ignored."""
        width = float(width)
        if math.isfinite(width) and width > 0.0:
            self._line_width = f32(width)

    def set_stroke_color(self, r, g, b, alpha):
        """``ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})```.

        A non-finite value makes the style string invalid, so the canvas
        keeps its previous style.
        """
        style = (float(r), float(g), float(b), float(alpha))
        if (math.isfinite(style[0]) and math.isfinite(style[1])
                and math.isfinite(style[2]) and math.isfinite(style[3])):
            self._style = style

    def stroke_line(self, x0, y0, x1, y1):
        """``beginPath(); moveTo(x0, y0); lineTo(x1, y1); stroke()``, round caps."""
        self._queue.append((x0, y0, x1, y1, self._line_width) + self._style)
        if len(self._queue) >= self._QUEUE_LIMIT:
            self._drain()

    def _drain(self):
        if not self._queue:
            return
        q = np.array(self._queue, dtype=np.float64).reshape(-1, 9)
        self._queue = []
        keep = np.isfinite(q[:, :4]).all(axis=1)
        q = q[keep]
        with np.errstate(over="ignore"):
            # Blink keeps path points as floats.
            x0 = q[:, 0].astype(np.float32)
            y0 = q[:, 1].astype(np.float32)
            x1 = q[:, 2].astype(np.float32)
            y1 = q[:, 3].astype(np.float32)
        lw = q[:, 4].astype(np.float32)
        # A path whose points coincide is pruned; a stroke whose bounds,
        # outset by lineWidth / 2 and rounded out, miss the canvas is culled.
        radius = np.float32(0.5) * lw
        lo_x = np.minimum(x0, x1)
        lo_y = np.minimum(y0, y1)
        left = lo_x - radius
        top = lo_y - radius
        span_w = (np.maximum(x0, x1) - lo_x) + np.float32(2.0) * radius
        span_h = (np.maximum(y0, y1) - lo_y) + np.float32(2.0) * radius
        visible = ~((x0 == x1) & (y0 == y1))
        visible &= ~((np.ceil(left + span_w) <= 0) | (np.ceil(top + span_h) <= 0)
                     | (np.floor(left) >= self.width) | (np.floor(top) >= self.height))
        rgb = np.floor(np.clip(q[:, 5:8], 0.0, 255.0) + 0.5).astype(np.int64)
        alpha = np.floor(np.clip(q[:, 8], 0.0, 1.0) * 255.0 + 0.5).astype(np.int64)
        visible &= alpha != 0
        hair = lw <= np.float32(1.0)
        # modifyPaintForHairlines: a thinner hairline scales alpha by (int)(w * 256) >> 8.
        thin = hair & (lw != np.float32(1.0))
        scale = (lw * np.float32(256.0)).astype(np.int64)
        alpha = np.where(thin, (alpha * scale) >> 8, alpha)
        visible &= ~(hair & (alpha == 0))
        index = np.nonzero(visible)[0]
        if index.size == 0:
            return
        r, g, b = rgb[index, 0], rgb[index, 1], rgb[index, 2]
        a = alpha[index]
        hair = hair[index]
        lw = lw[index]
        x0, y0, x1, y1 = x0[index], y0[index], x1[index], y1[index]
        # Runs of hairlines, and runs of wide strokes of one width, in order.
        breaks = np.nonzero((hair[1:] != hair[:-1]) | (lw[1:] != lw[:-1]))[0] + 1
        bounds = np.r_[0, breaks, index.size]
        for start, stop in zip(bounds[:-1].tolist(), bounds[1:].tolist()):
            if hair[start]:
                self._draw_hairlines(x0[start:stop], y0[start:stop], x1[start:stop],
                                     y1[start:stop], r[start:stop], g[start:stop],
                                     b[start:stop], a[start:stop])
            else:
                self._draw_wide(x0[start:stop], y0[start:stop], x1[start:stop],
                                y1[start:stop], float(lw[start]), r[start:stop],
                                g[start:stop], b[start:stop], a[start:stop])

    def _draw_hairlines(self, x0, y0, x1, y1, r, g, b, a):
        pixels = self._pixels.tolist()
        rect = (0, 0, self.width, self.height)
        for sx0, sy0, sx1, sy1, cr, cg, cb, ca in zip(
                x0.tolist(), y0.tolist(), x1.tolist(), y1.tolist(),
                r.tolist(), g.tolist(), b.tolist(), a.tolist()):
            blitter = _ArgbBlitter(pixels, self.width, (cr, cg, cb, ca))
            _anti_hair_round_line(sx0, sy0, sx1, sy1, rect, blitter)
        self._pixels = np.array(pixels, dtype=np.uint32)

    def _draw_wide(self, x0, y0, x1, y1, line_width, r, g, b, a):
        pm = _premultiply_all(r, g, b, a)
        kind = np.where((r == 0) & (g == 0) & (b == 0) & (a == 255), _BLACK,
                        np.where(a == 255, _OPAQUE, _TRANSLUCENT))
        radius = 0.5 * line_width
        vertices = 2 + 8 * (1 << _quad_shift(radius))
        footprint = (2.0 * radius + 4.0) ** 2
        batch = max(16, int(_FILL_BUDGET / (vertices * footprint)))
        x0, y0, x1, y1 = (v.astype(np.float64) for v in (x0, y0, x1, y1))
        for first in range(0, x0.size, batch):
            part = slice(first, first + batch)
            _blit_masks(self._pixels, self.width, self.height, x0[part], y0[part],
                        x1[part], y1[part], radius, pm[part], a[part], kind[part])

    def premultiplied(self):
        """Premultiplied RGBA8, shape (height, width, 4), row 0 at the top."""
        self._drain()
        p = self._pixels
        out = np.empty((p.size, 4), dtype=np.uint8)
        out[:, 0] = (p >> 16) & 0xFF
        out[:, 1] = (p >> 8) & 0xFF
        out[:, 2] = p & 0xFF
        out[:, 3] = p >> 24
        return out.reshape(self.height, self.width, 4)

    def unpremultiplied_rgba8(self):
        """Straight-alpha RGBA8, row 0 at the top: the bytes the WebGL upload sees."""
        return unpremultiply_for_upload(self.premultiplied())


def unpremultiply_for_upload(premultiplied):
    """Skia's raster-pipeline unpremultiply, as Chromium uploads the canvas.

    Each channel is read as ``c * (1 / 255.0f)``, multiplied by the float
    reciprocal of ``a * (1 / 255.0f)`` (0 where it is infinite), clamped to
    [0, 1] and stored as the product with 255, rounded to nearest even.
    """
    inv = np.float32(1.0) / np.float32(255.0)
    values = premultiplied.astype(np.float32) * inv
    with np.errstate(divide="ignore"):
        reciprocal = np.float32(1.0) / values[..., 3:4]
    scale = np.where(np.isinf(reciprocal), np.float32(0.0), reciprocal).astype(np.float32)
    out = np.empty_like(premultiplied)
    rgb = np.clip(values[..., :3] * scale, np.float32(0.0), np.float32(1.0))
    out[..., :3] = np.rint(rgb * np.float32(255.0)).astype(np.uint8)
    alpha = np.clip(values[..., 3], np.float32(0.0), np.float32(1.0))
    out[..., 3] = np.rint(alpha * np.float32(255.0)).astype(np.uint8)
    return out

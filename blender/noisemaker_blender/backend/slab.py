"""GPU-free draw-slab helper.

Very tall viewports lose their leftmost pixel column on the Metal backend
(measured on the M4 host: a 64x4096 atlas draw skips x=0 entirely; a
2048-tall viewport covers every column), so fullscreen passes draw in
vertical slabs of at most _MAX_DRAW_SLAB rows. Kept free of the `gpu`
import so engine-free suites can exercise the tiling logic.
"""

# Very tall viewports lose their leftmost pixel column on the Metal backend
# (measured: a 64x4096 atlas draw skips x=0 entirely; a 2048-tall viewport
# covers every column). FS passes draw in vertical slabs of this height.
_MAX_DRAW_SLAB = 2048


def slab_ranges(vy, vh, cap=None):
    """Vertical draw slabs covering [vy, vy+vh) with at most `cap` rows each.

    Returns (y, h) pairs that tile the full height exactly, in order, with
    no gaps or overlap.
    """
    cap = _MAX_DRAW_SLAB if cap is None else cap
    out = []
    offset = 0
    while offset < vh:
        slab = min(cap, vh - offset)
        out.append((vy + offset, slab))
        offset += slab
    return out

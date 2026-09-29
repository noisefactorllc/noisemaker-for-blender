"""Regression tests for the Metal tall-viewport draw-slab tiling.

The Metal backend drops the leftmost pixel column of fullscreen draws with
viewport height > 2048 (measured on the M4 host), so GpuBackend._render
draws FS passes in vertical slabs. These tests pin the tiling contract.
"""

import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

from noisemaker_blender.backend.slab import _MAX_DRAW_SLAB, slab_ranges


class TestSlabRanges(unittest.TestCase):
    def test_tiling_contract(self):
        for vy, vh in [(0, 4096), (0, 2048), (0, 2049), (37, 4097), (0, 1), (512, 63)]:
            ranges = slab_ranges(vy, vh)
            self.assertEqual(ranges[0][0], vy)
            for _, h in ranges:
                self.assertLessEqual(h, _MAX_DRAW_SLAB)
            self.assertEqual(ranges[-1][0] + ranges[-1][1], vy + vh)
            for (y0, h0), (y1, _) in zip(ranges, ranges[1:]):
                self.assertEqual(y1, y0 + h0)  # contiguous, ordered, no overlap

    def test_known_ranges(self):
        self.assertEqual(slab_ranges(0, 2048), [(0, 2048)])  # small passes: single draw
        self.assertEqual(slab_ranges(0, 4096), [(0, 2048), (2048, 2048)])
        self.assertEqual(slab_ranges(100, 3000, cap=1000),
                         [(100, 1000), (1100, 1000), (2100, 1000)])
        self.assertEqual(slab_ranges(100, 2900, cap=1000),
                         [(100, 1000), (1100, 1000), (2100, 900)])
        self.assertEqual(slab_ranges(0, 0), [])
        self.assertEqual(slab_ranges(5, 0), [])


if __name__ == "__main__":
    unittest.main()

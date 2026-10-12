"""Func-wrapper texture-dimension fallbacks (upstream ba20f72c).

Func wrappers and other nonnumeric uniform values are not evaluated by the
runtime: dimension specs must fall back to their authored numeric defaults
instead of allocating a NaN-sized texture.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.runtime.pipeline import resolve_dimension  # noqa: E402


class DimensionFuncDefaultTests(unittest.TestCase):
    def test_func_texture_dimensions_use_authored_numeric_defaults(self):
        # Func wrappers are represented structurally (no closure) and must
        # never be executed while resolving texture dimensions.
        wrapper = {"fn": {"_func_src": "zoom * 8"}, "min": 1, "max": 64}
        cases = [
            ({"screenDivide": "zoom_chain_0", "default": 32}, {"zoom_chain_0": wrapper}, 8),
            ({"param": "stateSize_node_1", "default": 256}, {"stateSize_node_1": wrapper}, 256),
            ({"param": "volumeSize_chain_0", "default": 64}, {"volumeSize_chain_0": wrapper}, 64),
            ({"param": "volumeSize_chain_0", "power": 2, "default": 4096},
             {"volumeSize_chain_0": wrapper}, 4096),
            ({"param": "size", "paramDefault": 3, "multiply": 2, "power": 2},
             {"size": wrapper}, 36),
            ({"screenDivide": "zoom_chain_0", "default": 32}, {"zoom_chain_0": 16}, 16),
            ({"param": "stateSize_node_1", "default": 256}, {"stateSize_node_1": 128}, 128),
            ({"param": "volumeSize_chain_0", "power": 2, "default": 4096},
             {"volumeSize_chain_0": 16}, 256),
        ]
        for spec, uniforms, expected in cases:
            self.assertEqual(
                resolve_dimension(spec, 256, uniforms), expected,
                "dimension %r: expected %d" % (spec, expected))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression tests for render-pipeline device-limit handling."""

import sys
import unittest
from pathlib import Path


BLENDER_ROOT = Path(__file__).resolve().parents[1] / "blender"
sys.path.insert(0, str(BLENDER_ROOT))

from noisemaker_blender.runtime import pipeline


class VolumeGraph:
    def __init__(self):
        self.passes = [{
            "uniforms": {
                "volumeSize": 128,
                "volumeSize_chain_0": 128,
                "volumeSize_node_0": 128,
                "unrelated": 128,
            },
            "outputs": {},
        }]
        self.render_surface = "o0"


class LimitBackend:
    size = 1
    frame_read = {"o0": object()}

    def __init__(self, max_texture_size):
        self._max_texture_size = max_texture_size
        self.setup_defaults = None

    def max_texture_size(self):
        return self._max_texture_size

    def setup(self, graph, defaults):
        self.setup_defaults = defaults.copy()

    def frame_begin(self):
        pass

    def frame_persist(self):
        pass

    def execute(self, render_pass, graph, engine):
        pass

    def read_surface(self, name):
        return "pixels"


class PipelineLimitTests(unittest.TestCase):
    def test_render_clamps_volume_uniform_family_before_setup_on_constrained_device(self):
        graph = VolumeGraph()
        backend = LimitBackend(8192)

        pipeline.render(backend, graph)

        uniforms = graph.passes[0]["uniforms"]
        self.assertEqual(uniforms["volumeSize"], 64)
        self.assertEqual(uniforms["volumeSize_chain_0"], 64)
        self.assertEqual(uniforms["volumeSize_node_0"], 64)
        self.assertEqual(uniforms["unrelated"], 128)
        self.assertEqual(backend.setup_defaults, uniforms)

    def test_render_preserves_volume_size_when_atlas_exactly_fits_device(self):
        graph = VolumeGraph()
        backend = LimitBackend(16384)

        pipeline.render(backend, graph)

        uniforms = graph.passes[0]["uniforms"]
        self.assertEqual(uniforms["volumeSize"], 128)
        self.assertEqual(uniforms["volumeSize_chain_0"], 128)
        self.assertEqual(uniforms["volumeSize_node_0"], 128)
        self.assertEqual(backend.setup_defaults, uniforms)


if __name__ == "__main__":
    unittest.main()

"""Rectangular engine uniforms and resource contracts, without a GPU context."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender import api
from noisemaker_blender.runtime import pipeline
from parity.test_render_session import FakeBackend, graph


class RectangularRuntimeTests(unittest.TestCase):
    def test_legacy_size_and_rectangular_engine_uniforms(self):
        square = pipeline.default_engine(64, 0.25, 2)
        self.assertEqual(square["resolution"], [64.0, 64.0])
        self.assertEqual(square["aspect"], 1.0)
        rectangular = pipeline.default_engine(257, 0.25, 2, width=257, height=129)
        self.assertEqual(rectangular["resolution"], [257.0, 129.0])
        self.assertEqual(rectangular["fullResolution"], [257.0, 129.0])
        self.assertAlmostEqual(rectangular["aspectRatio"], 257 / 129)

    def test_viewport_resolves_axis_specific_screen_dimensions(self):
        render_pass = {"viewport": {"x": 0, "y": 0, "w": "50%", "h": "50%"}}
        box = pipeline.resolve_pass_viewport(render_pass, 257, 129)
        self.assertEqual(box, {"x": 1, "y": 1, "w": 128, "h": 64})

    def test_size_alias_matches_explicit_square_session(self):
        program = api.Program.from_graph("square", graph())
        with api.open_session(program, size=64, backend_factory=FakeBackend) as legacy:
            with api.open_session(program, width=64, height=64,
                                  backend_factory=FakeBackend) as explicit:
                left = legacy.evaluate(api.FrameRequest(frame=1))
                right = explicit.evaluate(api.FrameRequest(frame=1))
                self.assertEqual(left.descriptor, right.descriptor)
                self.assertEqual(legacy.backend.last_engine, explicit.backend.last_engine)

    def test_odd_rectangular_output_and_engine_are_consistent(self):
        program = api.Program.from_graph("rect", graph())
        with api.open_session(program, width=257, height=129,
                              backend_factory=FakeBackend) as session:
            output = session.evaluate(api.FrameRequest(frame=2))
            self.assertEqual((output.descriptor.width, output.descriptor.height), (257, 129))
            self.assertEqual(session.backend.last_engine["resolution"], [257.0, 129.0])
            self.assertAlmostEqual(session.backend.last_engine["aspect"], 257 / 129)


if __name__ == "__main__":
    unittest.main()

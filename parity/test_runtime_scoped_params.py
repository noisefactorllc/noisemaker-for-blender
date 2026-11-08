#!/usr/bin/env python3
"""A runtime zoom change reaches each stateful instance's own sizing uniform."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402
from noisemaker_blender.runtime.session import Program, RenderSession  # noqa: E402


class RecordingBackend:
    def __init__(self, shaders_root=None, *, width=256, height=256):
        self.uniforms = None

    def setup(self, graph, uniforms):
        self.uniforms = uniforms

    def compile(self, *args):
        pass

    def free(self):
        pass


SOURCE = ("search synth, mixer, filter, render\n"
          "reactionDiffusion(zoom: x4)"
          ".blendMode(tex: reactionDiffusion(zoom: x16)).write(o0)\n"
          "render(o0)")

VOLUME_SOURCE = ("search synth3d, filter3d, render\n"
                 "read3d(vol1, geo1).palette3d().renderLandscape3d().write(o0)\n"
                 "read3d(vol0, geo0).write3d(vol1, geo1)\n"
                 "heightmap3d(volumeSize: x16).write3d(vol0, geo0)\n"
                 "render(o0)")


class ScopedRuntimeParameterTests(unittest.TestCase):
    def test_a_runtime_zoom_change_resizes_only_the_target_instance(self):
        program = Program.from_graph(SOURCE, compile_graph(SOURCE))
        session = RenderSession(program, size=256, backend_factory=RecordingBackend)

        self.assertEqual(session.backend.uniforms["zoom_chain_0"], 4)
        self.assertEqual(session.backend.uniforms["zoom_chain_0_node_1"], 16)

        invalidation = session.set_parameter("synth.reactionDiffusion#1.zoom", 2)

        self.assertEqual(invalidation, "resource",
                         "a scoped sizing param must rebuild the resources")
        self.assertEqual(session.backend.uniforms["zoom_chain_0"], 4)
        self.assertEqual(session.backend.uniforms["zoom_chain_0_node_1"], 2)
        for p in session.graph.passes:
            if "zoom_chain_0_node_1" in (p.get("uniforms") or {}):
                self.assertEqual(p["uniforms"]["zoom_chain_0_node_1"], 2)

        session.set_parameter("synth.reactionDiffusion#0.zoom", 32)

        self.assertEqual(session.backend.uniforms["zoom_chain_0"], 32)
        self.assertEqual(session.backend.uniforms["zoom_chain_0_node_1"], 2)

    def test_a_consumer_volume_size_write_never_reaches_an_inheriting_pass(self):
        program = Program.from_graph(VOLUME_SOURCE, compile_graph(VOLUME_SOURCE))
        session = RenderSession(program, size=256, backend_factory=RecordingBackend)

        self.assertEqual(session.backend.uniforms["volumeSize_chain_2"], 16)

        invalidation = session.set_parameter("filter3d.palette3d#0.volumeSize", 64)

        self.assertEqual(invalidation, "resource")
        self.assertEqual(session.backend.uniforms["volumeSize_chain_2"], 16,
                         "a consumer's local volumeSize must not resize the source")
        for p in session.graph.passes:
            if p.get("func") == "palette3d":
                self.assertEqual(p["uniforms"]["volumeSize"], 16,
                                 "an inheriting consumer keeps the chain value")
                self.assertEqual(p["uniforms"]["volumeSize_chain_2"], 16)
            if p.get("func") == "heightmap3d":
                self.assertEqual(p["uniforms"]["volumeSize"], 16)
                self.assertEqual(p["uniforms"]["volumeSize_chain_2"], 16)

        invalidation = session.set_parameter("render.renderLandscape3d#0.volumeSize", 64)

        self.assertEqual(invalidation, "resource")
        for p in session.graph.passes:
            if p.get("func") == "renderLandscape3d":
                self.assertEqual(p["uniforms"]["volumeSize"], 16,
                                 "a consumer that samples the volume keeps the chain size")
        self.assertEqual(session.backend.uniforms["volumeSize_chain_2"], 16)

        invalidation = session.set_parameter("synth3d.heightmap3d#0.volumeSize", 32)

        self.assertEqual(invalidation, "resource")
        self.assertEqual(session.backend.uniforms["volumeSize_chain_2"], 32,
                         "the chain source's own write sizes the whole chain")


if __name__ == "__main__":
    unittest.main()

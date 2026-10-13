"""Particle state dimensions follow the emitting node's authored size."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402
from noisemaker_blender.runtime.graph_loader import Graph  # noqa: E402
from noisemaker_blender.runtime.pipeline import FrameStepper  # noqa: E402
from noisemaker_blender.runtime.session import Program, RenderSession  # noqa: E402


class RecordingBackend:
    size = 256

    def __init__(self, shaders_root=None, *, width=256, height=256):
        self.size = width

    def setup(self, graph, uniforms):
        self.uniforms = uniforms

    def compile(self, *args):
        pass


class ParticleStateSizeTests(unittest.TestCase):
    def test_emitter_size_reaches_all_consumers_and_texture_setup(self):
        source = (ROOT / "parity" / "programs" / "north_star.dsl").read_text()
        graph = Graph(compile_graph(source))
        backend = RecordingBackend()

        FrameStepper(backend, graph)

        self.assertEqual(backend.uniforms["stateSize_node_2"], 1024)
        consumers = [p for p in graph.passes
                     if "stateSize_node_2" in p.get("uniforms", {})]
        self.assertTrue(consumers)
        self.assertTrue(all(p["uniforms"]["stateSize_node_2"] == 1024
                            for p in consumers))
        billboards = [p for p in consumers if p.get("func") == "pointsBillboardRender"]
        self.assertTrue(billboards)
        self.assertTrue(all(p["uniforms"]["stateSize"] == 256 for p in billboards))

    def test_render_session_allocates_authored_particle_state(self):
        source = (ROOT / "parity" / "programs" / "north_star.dsl").read_text()
        program = Program.from_graph(source, compile_graph(source))

        session = RenderSession(program, size=256, backend_factory=RecordingBackend)

        self.assertEqual(session.backend.uniforms["stateSize_node_2"], 1024)


if __name__ == "__main__":
    unittest.main()

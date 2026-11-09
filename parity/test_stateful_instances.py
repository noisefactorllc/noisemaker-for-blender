#!/usr/bin/env python3
"""Each stateful effect instance in a chain keeps its own state and size.

Ported from reference `shaders/tests/test_stateful_instances.js` (upstream
cf95f49c, GAP-059). Before that change the expander scoped every ``global_``
texture by chain position only, so two instances of a stateful effect in one
chain (an inline surface argument or a repeated filter) read and wrote one
state texture, and two zoom-sized simulations in one chain shared one
``zoom_chain_N`` size. A ``global_`` texture that only one effect in the chain
names, and that the effect writes, is now private state: the first instance
keeps the chain-scoped ID and each further instance appends its node. A sizing
parameter belongs to the first node that sizes private state from it; every
other node gets a node-scoped name. Textures that different effects share
(loopBegin/loopEnd accumulator, mesh buffers) keep the chain scope.

The reference suite also re-sizes state textures when a step's zoom changes at
runtime through the renderer's parameter-update path. That reallocation is
renderer-side, so this engine-free suite covers the render-graph facts it
depends on: distinct state textures, distinct sizing parameters and each
node's own zoom uniform value.
"""

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

SEARCH = "search synth, mixer, filter, render\n"

PROGRAM_A = ("reactionDiffusion(zoom: x4)"
             ".blendMode(tex: reactionDiffusion(zoom: x16)).write(o0)")
PROGRAM_B = ("perlin()"
             ".blendMode(tex: reactionDiffusion(zoom: x4))"
             ".blendMode(tex: reactionDiffusion(zoom: x16)).write(o0)")
PROGRAM_C = "perlin().watercolor().watercolor().write(o0)"


def build(chain):
    return compile_graph("%s%s\nrender(o0)" % (SEARCH, chain))


def instances(graph, effect_func, state_prefix):
    """Group the graph's passes into per-instance nodes, as the reference does.

    Every pass of one instance must name the same state texture; a node's
    state is the single ``state_prefix``-prefixed texture its passes touch.
    """
    nodes = {}
    for p in graph["passes"]:
        if p.get("func") != effect_func:
            continue
        node = nodes.setdefault(p["nodeId"],
                                {"passes": [], "textures": set(),
                                 "stepIndex": p["stepIndex"]})
        node["passes"].append(p)
        for value in list((p.get("inputs") or {}).values()) + \
                list((p.get("outputs") or {}).values()):
            if isinstance(value, str) and value.startswith(state_prefix):
                node["textures"].add(value)
    out = []
    for node in nodes.values():
        assert len(node["textures"]) == 1, \
            "all passes in an instance must use the same state"
        node["texture"] = next(iter(node["textures"]))
        out.append(node)
    return out


def zoom_param(graph, node):
    """The sizing parameter the node's state texture divides the screen by."""
    return graph["textures"][node["texture"]]["width"]["screenDivide"]


class StatefulInstanceTests(unittest.TestCase):
    def test_reaction_diffusion_instances_have_independent_state_and_zoom(self):
        for program in (PROGRAM_A, PROGRAM_B):
            graph = build(program)
            nodes = instances(graph, "reactionDiffusion", "global_rd_state")
            self.assertEqual(len(nodes), 2)
            self.assertNotEqual(nodes[0]["texture"], nodes[1]["texture"],
                                "state textures must be distinct")
            self.assertEqual(nodes[0]["texture"], "global_rd_state_chain_0",
                             "the first instance keeps the chain-scoped ID")
            self.assertTrue(nodes[1]["texture"].startswith(
                "global_rd_state_chain_0_node_"))
            for index, node in enumerate(nodes):
                sizing = zoom_param(graph, node)
                for p in node["passes"]:
                    self.assertEqual(p["scopedParams"]["zoom"], sizing)
                    self.assertEqual(p["uniforms"][sizing], [4, 16][index])

    def test_watercolor_instances_have_independent_ping_pong_state(self):
        graph = build(PROGRAM_C)
        nodes = instances(graph, "watercolor", "global_wc_state")
        self.assertEqual(len(nodes), 2)
        self.assertNotEqual(nodes[0]["texture"], nodes[1]["texture"],
                            "state textures must be distinct")
        self.assertTrue(nodes[1]["texture"].startswith(
            "global_wc_state_chain_0_node_"))

    def test_different_stateful_effects_size_from_their_own_zoom(self):
        for chain in (
            "reactionDiffusion(zoom: x4)"
            ".blendMode(tex: cellularAutomata(zoom: x16)).write(o0)",
            "perlin()"
            ".blendMode(tex: reactionDiffusion(zoom: x4))"
            ".blendMode(tex: cellularAutomata(zoom: x16)).write(o0)",
        ):
            graph = build(chain)
            rd = instances(graph, "reactionDiffusion", "global_rd_state")
            ca = instances(graph, "cellularAutomata", "global_ca_state")
            self.assertEqual(rd[0]["texture"], "global_rd_state_chain_0")
            self.assertEqual(ca[0]["texture"], "global_ca_state_chain_0")
            rd_param = zoom_param(graph, rd[0])
            ca_param = zoom_param(graph, ca[0])
            self.assertNotEqual(rd_param, ca_param,
                                "size parameters must be distinct")
            self.assertEqual(rd[0]["passes"][0]["uniforms"][rd_param], 4)
            self.assertEqual(ca[0]["passes"][0]["uniforms"][ca_param], 16)

            source = "%s%s\nrender(o0)" % (SEARCH, chain)
            session = RenderSession(
                Program.from_graph(source, compile_graph(source)),
                size=256, backend_factory=RecordingBackend)
            rd = instances(session.graph.data, "reactionDiffusion",
                           "global_rd_state")
            ca = instances(session.graph.data, "cellularAutomata",
                           "global_ca_state")
            rd_size = zoom_param(session.graph.data, rd[0])
            ca_size = zoom_param(session.graph.data, ca[0])
            self.assertEqual(session.backend.uniforms[rd_size], 4)
            self.assertEqual(session.backend.uniforms[ca_size], 16)

            session.set_parameter("synth.cellularAutomata#0.zoom", 2)

            self.assertEqual(session.backend.uniforms[rd_size], 4,
                             "the other effect's state size stays intact")
            self.assertEqual(session.backend.uniforms[ca_size], 2)

            session.set_parameter("synth.reactionDiffusion#0.zoom", 32)

            self.assertEqual(session.backend.uniforms[rd_size], 32)
            self.assertEqual(session.backend.uniforms[ca_size], 2,
                             "the other effect's state size stays intact")

    def test_loop_begin_and_loop_end_retain_their_shared_accumulator(self):
        for chain in (
            "perlin().loopBegin().loopEnd().write(o0)",
            "perlin().loopBegin().loopEnd().loopBegin().loopEnd().write(o0)",
        ):
            graph = build(chain)
            for p in graph["passes"]:
                if p["func"] == "loopBegin":
                    self.assertEqual(p["inputs"].get("accumTex"),
                                     "global_accum_chain_0")
                if (p["func"] == "loopEnd"
                        and str(p["outputs"].get("fragColor", ""))
                        .startswith("global_")):
                    self.assertEqual(p["outputs"]["fragColor"],
                                     "global_accum_chain_0")

    def test_mesh_loader_and_mesh_render_retain_their_shared_mesh_buffers(self):
        graph = build("meshLoader().meshRender().meshRender().write(o0)")
        loader = next(p for p in graph["passes"] if p["func"] == "meshLoader")
        renderers = [p for p in graph["passes"]
                     if p["func"] == "meshRender"
                     and "meshPositions" in (p.get("inputs") or {})]
        self.assertEqual(len(renderers), 2)
        self.assertEqual(loader["inputs"]["positionsTex"],
                         "global_mesh0_positions_chain_0")
        self.assertEqual(loader["inputs"]["normalsTex"],
                         "global_mesh0_normals_chain_0")
        for renderer in renderers:
            self.assertEqual(renderer["inputs"]["meshPositions"],
                             loader["inputs"]["positionsTex"])
            self.assertEqual(renderer["inputs"]["meshNormals"],
                             loader["inputs"]["normalsTex"])

    def test_repeated_state_preserves_each_explicit_or_default_zoom(self):
        graph = build("reactionDiffusion(zoom: x4)"
                      ".blendMode(tex: reactionDiffusion())"
                      ".blendMode(tex: reactionDiffusion(zoom: x16)).write(o0)")
        nodes = instances(graph, "reactionDiffusion", "global_rd_state")
        self.assertEqual(len({n["texture"] for n in nodes}), 3)
        zooms = [nodes[i]["passes"][0]["uniforms"][zoom_param(graph, nodes[i])]
                 for i in range(len(nodes))]
        self.assertEqual(zooms, [4, 8, 16])

    def test_repeated_mesh_renderers_keep_external_buffers_across_chains(self):
        graph = build("meshLoader().write(o0)\n"
                      "read(o0).meshRender().meshRender().write(o1)")
        renderers = [p for p in graph["passes"]
                     if p["func"] == "meshRender"
                     and "meshPositions" in (p.get("inputs") or {})]
        self.assertEqual(len(renderers), 2)
        for renderer in renderers:
            self.assertEqual(renderer["inputs"]["meshPositions"],
                             "global_mesh0_positions_chain_1")
            self.assertEqual(renderer["inputs"]["meshNormals"],
                             "global_mesh0_normals_chain_1")

    def test_single_instances_retain_their_existing_texture_ids(self):
        graph = build("perlin().write(o0)\n"
                      "reactionDiffusion(zoom: x4).watercolor().write(o1)")
        self.assertEqual(
            instances(graph, "reactionDiffusion", "global_rd_state")[0]
            ["texture"], "global_rd_state_chain_1")
        self.assertEqual(
            instances(graph, "watercolor", "global_wc_state")[0]["texture"],
            "global_wc_state_chain_1")


    def test_changing_one_instances_zoom_leaves_the_others_intact(self):
        for program in (PROGRAM_A, PROGRAM_B):
            source = "%s%s\nrender(o0)" % (SEARCH, program)
            session = RenderSession(
                Program.from_graph(source, compile_graph(source)),
                size=256, backend_factory=RecordingBackend)
            nodes = instances(session.graph.data, "reactionDiffusion",
                              "global_rd_state")
            sizes = [zoom_param(session.graph.data, node) for node in nodes]
            self.assertEqual(session.backend.uniforms[sizes[0]], 4)
            self.assertEqual(session.backend.uniforms[sizes[1]], 16)

            session.set_parameter("synth.reactionDiffusion#1.zoom", 2)

            nodes = instances(session.graph.data, "reactionDiffusion",
                              "global_rd_state")
            self.assertEqual(session.backend.uniforms[sizes[0]], 4,
                             "the other instance's state size stays intact")
            self.assertEqual(session.backend.uniforms[sizes[1]], 2)
            for p in nodes[1]["passes"]:
                self.assertEqual(p["uniforms"]["zoom"], 2)

            session.set_parameter("synth.reactionDiffusion#0.zoom", 32)

            self.assertEqual(session.backend.uniforms[sizes[0]], 32)
            self.assertEqual(session.backend.uniforms[sizes[1]], 2,
                             "the other instance's state size stays intact")


if __name__ == "__main__":
    unittest.main()

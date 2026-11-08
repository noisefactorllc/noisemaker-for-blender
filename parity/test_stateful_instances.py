#!/usr/bin/env python3
"""Each stateful effect instance in a chain keeps its own state and size."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402

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
    """Group the graph's passes into per-instance nodes, as the reference does."""
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


if __name__ == "__main__":
    unittest.main()

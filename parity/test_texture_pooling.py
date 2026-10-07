#!/usr/bin/env python3
"""Regression tests for runtime consumption of the resource allocation plan
— a port of reference shaders/tests/test_resource_pooling.js, plus the
viewport-without-clear guard (upstream `95743621`).

Two upstream pieces are mirrored:
  - the analyzer's physical allocation plan (graph.allocations, produced by
    allocate_resources) is consumed by the renderer: virtual textures with
    disjoint lifetimes and safe first-touch/overwrite contracts share one
    backend texture (the Blender backend always consumes the plan);
  - the actual runtime allocation/reuse plan is queryable
    (runtime.pipeline.resource_plan).

All logic is pure (no Blender gpu module): the plan builder takes a
graph-shaped object (passes/textures/allocations), resource_plan takes a
backend stub exposing pool_key/pool/tex_dims.

Run:  python3 parity/test_texture_pooling.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "blender"))

from noisemaker_blender.runtime.pipeline import (  # noqa: E402
    build_texture_pooling_plan,
    resource_plan,
)
from noisemaker_blender.compiler.resources import allocate_resources  # noqa: E402


class GraphStub:
    def __init__(self, passes, textures, allocations):
        self.passes = passes
        self.textures = textures
        self.allocations = allocations


SCREEN = {"width": "screen", "height": "screen", "format": "rgba16f"}


def chain_graph(extra_textures=None, mutate=None):
    """poolProbeA shape: A -> B -> C -> D chain; A/C and B/D share slots.

    `mutate(passes)` runs BEFORE the analyzer computes `allocations`, so the
    fixture always carries a representable (allocator-produced) plan.
    """
    textures = {
        "node_0_texA": dict(SCREEN),
        "node_0_texB": dict(SCREEN),
        "node_0_texC": dict(SCREEN),
        "node_0_texD": dict(SCREEN),
    }
    textures.update(extra_textures or {})
    passes = [
        {"program": "p0", "inputs": {}, "outputs": {"color": "node_0_texA"}},
        {"program": "p1", "inputs": {"src": "node_0_texA"},
         "outputs": {"color": "node_0_texB"}},
        {"program": "p2", "inputs": {"src": "node_0_texB"},
         "outputs": {"color": "node_0_texC"}},
        {"program": "p3", "inputs": {"src": "node_0_texC"},
         "outputs": {"color": "node_0_texD"}},
    ]
    if mutate:
        mutate(passes)
    allocations = allocate_resources(passes)
    return GraphStub(passes, textures, allocations)


class TexturePoolingPlanTests(unittest.TestCase):
    def test_disjoint_lifetimes_share_one_storage(self):
        plan = build_texture_pooling_plan(chain_graph())
        self.assertEqual(plan.get("node_0_texA"), "node_0_texA")
        self.assertEqual(plan.get("node_0_texC"), "node_0_texA")
        self.assertEqual(plan.get("node_0_texB"), "node_0_texB")
        self.assertEqual(plan.get("node_0_texD"), "node_0_texB")

    def test_overlapping_lifetime_stays_separate(self):
        # texA is still alive while texC is written (texC reads texA), so the
        # analyzer gives texC its own slot.
        def extend_a(passes):
            passes[2]["inputs"]["keep"] = "node_0_texA"
        g = chain_graph(mutate=extend_a)
        plan = build_texture_pooling_plan(g)
        self.assertEqual(g.allocations["node_0_texC"], "phys_2",
                         "precondition: analyzer must give texC a fresh slot")
        self.assertNotEqual(plan.get("node_0_texC"), "node_0_texA")

    def test_persistent_spec_blocks_pooling(self):
        # poolProbeB shape: the chain carries a persistent member; any physical
        # group containing it must not pool (a shared record must not absorb
        # its cross-frame contents), so upstream skips the whole group.
        g = chain_graph(
            extra_textures={"node_0_texB": dict(SCREEN, persistent=True)})
        plan = build_texture_pooling_plan(g)
        self.assertNotIn("node_0_texB", plan)
        self.assertNotIn("node_0_texD", plan)
        # The clean phys_0 pair still pools.
        self.assertEqual(plan.get("node_0_texC"), "node_0_texA")

    def test_mipmaps_and_is3d_specs_block_pooling(self):
        for field in ("mipmaps", "is3D"):
            g = chain_graph(
                extra_textures={"node_0_texC": dict(SCREEN, **{field: True})})
            plan = build_texture_pooling_plan(g)
            # The shared phys_0 pair carries a policy field -> whole group
            # stays standalone; the clean phys_1 pair still pools.
            self.assertNotIn("node_0_texA", plan, field)
            self.assertNotIn("node_0_texC", plan, field)
            self.assertEqual(plan.get("node_0_texB"), "node_0_texB", field)

    def test_mismatched_signature_blocks_pooling(self):
        g = chain_graph(extra_textures={
            "node_0_texC": {"width": 64, "height": 64, "format": "rgba32f"}})
        self.assertEqual(g.allocations["node_0_texC"], "phys_0",
                         "precondition: the analyzer reused texA's slot")
        plan = build_texture_pooling_plan(g)
        self.assertNotIn("node_0_texA", plan)
        self.assertNotIn("node_0_texC", plan)
        self.assertEqual(plan.get("node_0_texB"), "node_0_texB")

    def test_first_touch_read_blocks_pooling(self):
        # poolProbeE shape: texC is sampled at pass 1 before its producing
        # pass 2, so its first touch is a read; it must not share a slot a
        # group-mate writes earlier in the same frame even though the analyzer
        # reused texA's physical slot for it.
        def read_early(passes):
            passes.insert(1, {"program": "pre", "inputs": {"src": "node_0_texC"},
                              "outputs": {}})
        g = chain_graph(mutate=read_early)
        self.assertEqual(g.allocations["node_0_texA"], g.allocations["node_0_texC"],
                         "precondition: analyzer must reuse texA's slot for texC")
        plan = build_texture_pooling_plan(g)
        # texC excluded -> the shrunken group leaves texA standalone too; the
        # untouched phys_1 pair still pools.
        self.assertNotIn("node_0_texC", plan)
        self.assertNotIn("node_0_texA", plan)
        self.assertEqual(plan.get("node_0_texB"), "node_0_texB")

    def test_self_sampled_blocks_pooling(self):
        # poolProbeF shape: texA is both written and sampled by pass 0, so its
        # storage must keep the previous-frame contents a standalone holds.
        # texC reuses texA's physical slot, but the self-sampled member is
        # excluded, shrinking the group below 2 members: neither pools.
        def self_sample(passes):
            passes[0]["inputs"]["prev"] = "node_0_texA"
        g = chain_graph(mutate=self_sample)
        self.assertEqual(g.allocations["node_0_texC"], "phys_0",
                         "precondition: analyzer must reuse texA's slot for texC")
        plan = build_texture_pooling_plan(g)
        self.assertNotIn("node_0_texA", plan)
        self.assertNotIn("node_0_texC", plan)
        # The untouched phys_1 pair still pools.
        self.assertEqual(plan.get("node_0_texB"), "node_0_texB")

    def test_draw_mode_and_blend_are_partially_written(self):
        for field, value in (("drawMode", "points"), ("blend", True)):
            g = chain_graph()
            g.passes[2][field] = value  # p2 writes texC via scatter/blend
            plan = build_texture_pooling_plan(g)
            # The partially-written member must not pool into a group-mate's
            # slot; with texC excluded, its phys group has <2 members and texA
            # stays standalone too (upstream skips the shrunken group).
            self.assertNotIn("node_0_texC", plan, field)
            self.assertNotIn("node_0_texA", plan, field)
            # texB (full-overwrite write, p1) remains poolable with texD.
            self.assertEqual(plan.get("node_0_texB"), "node_0_texB", field)

    def test_viewport_without_clear_is_partially_written(self):
        # Upstream 95743621: a viewport pass without clear renders into a
        # sub-region — unwritten regions expose the previous contents.
        g = chain_graph()
        g.passes[2]["viewport"] = {"x": 0, "y": 0, "w": 16, "h": 16}
        plan = build_texture_pooling_plan(g)
        self.assertNotIn("node_0_texC", plan)
        self.assertNotIn("node_0_texA", plan)
        self.assertEqual(plan.get("node_0_texB"), "node_0_texB")

    def test_viewport_with_clear_stays_poolable(self):
        g = chain_graph()
        g.passes[2]["viewport"] = {"x": 0, "y": 0, "w": 16, "h": 16}
        g.passes[2]["clear"] = True
        plan = build_texture_pooling_plan(g)
        self.assertEqual(plan.get("node_0_texC"), "node_0_texA")

    def test_no_allocation_plan_means_empty(self):
        g = chain_graph()
        g.allocations = {}
        self.assertEqual(build_texture_pooling_plan(g), {})
        g.textures = {}
        self.assertEqual(build_texture_pooling_plan(g), {})

    def test_globals_never_pool(self):
        g = chain_graph()
        g.textures["global_o0"] = dict(SCREEN)
        g.allocations["global_o0"] = "phys_0"
        plan = build_texture_pooling_plan(g)
        self.assertNotIn("global_o0", plan)


class ResourcePlanTests(unittest.TestCase):
    def _backend(self, graph):
        # resource_plan() only consumes pool_key/pool/tex_dims — a plain stub
        # avoids importing the Blender-only GpuBackend (its `gpu` module is
        # unavailable outside Blender).
        class _StubBackend:
            pass
        backend = _StubBackend()
        backend.pool = {}
        backend.pool_key = {}
        backend.tex_dims = {}
        aliases = build_texture_pooling_plan(graph)
        for tid, spec in graph.textures.items():
            if tid.startswith("global_"):
                continue
            if tid in aliases:
                key = (graph.allocations.get(aliases[tid], aliases[tid]),
                       64, 64, "RGBA16F")
            else:
                key = (tid, 64, 64, "RGBA16F")
            backend.pool_key[tid] = key
            backend.tex_dims[tid] = (64, 64)
            backend.pool[key] = object()  # record identity
        return backend

    def test_plan_reports_shared_groups(self):
        g = chain_graph()
        backend = self._backend(g)
        plan = resource_plan(backend, g)
        self.assertTrue(plan["pooling"])
        self.assertEqual(plan["allocations"].get("node_0_texA"), "phys_0")
        shared = plan["sharedTextures"]
        self.assertEqual(len(shared), 2, str(shared))
        flat = [m for group in shared for m in group]
        self.assertIn("node_0_texA", flat)
        self.assertIn("node_0_texC", flat)
        for entry in plan["textures"]:
            self.assertIn("virtualTextures", entry)

    def test_plan_reports_no_sharing_when_excluded(self):
        def viewport_pass(passes):
            passes[2]["viewport"] = {"x": 0, "y": 0, "w": 16, "h": 16}
        g = chain_graph(mutate=viewport_pass)
        backend = self._backend(g)
        plan = resource_plan(backend, g)
        flat = [m for group in plan["sharedTextures"] for m in group]
        self.assertNotIn("node_0_texC", flat)


if __name__ == "__main__":
    unittest.main(verbosity=1)

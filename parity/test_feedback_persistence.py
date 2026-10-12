#!/usr/bin/env python3
"""Engine-free regression for cross-frame surface persistence (sync of
upstream noisemaker ba20f72..1da06b8: 5a8e8f67, fa0e6b35, 8aa4cf64).

Reference `Pipeline.swapBuffers` now persists the frame's final read/write
bindings — instead of swapping — for three kinds of global surfaces: state
surfaces (already ported), graph FEEDBACK surfaces (a pass reads the surface
before any pass writes it, and a later pass writes it: the writer consumes the
previous frame's contents), and surfaces whose global texture spec sets
`persistent: true`. A surface first WRITTEN then read is frame-local scratch
(lenia's clear/deposit density target) and must keep the end-of-frame swap, or
the additive deposit accumulates unbounded.

The classification lives in the GPU-free `feedback_surface_plan`; the backend
consumes it in `frame_persist`. Red-before holds against base 70ff898: no
feedback or persistent classification existed and every non-state surface
swapped.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.runtime.pipeline import feedback_surface_plan  # noqa: E402


class _Graph:
    def __init__(self, passes, textures=None):
        self.passes = passes
        self.textures = textures or {}


def _pass(inputs=None, outputs=None, storage=None):
    p = {}
    if inputs is not None:
        p["inputs"] = inputs
    if outputs is not None:
        p["outputs"] = outputs
    if storage is not None:
        p["storageTextures"] = storage
    return p


class FeedbackSurfacePlanTests(unittest.TestCase):
    def test_read_before_write_and_written_is_feedback(self):
        # Classic feedback: pass 1 reads the previous frame's contents, pass 2
        # writes the next frame's. End-of-frame must persist, not swap.
        graph = _Graph([
            _pass(inputs={"src": "global_o1"}),
            _pass(outputs={"color": "global_o1"}),
        ])
        feedback, persistent = feedback_surface_plan(graph)
        self.assertEqual(feedback, {"o1"})
        self.assertEqual(persistent, set())

    def test_written_then_read_is_frame_local_scratch_not_feedback(self):
        # Lenia's clear+deposit: the density target's first touch is a write
        # (clear) and the deposit then reads it. It must keep the swap.
        graph = _Graph([
            _pass(outputs={"color": "global_o1"}),
            _pass(inputs={"density": "global_o1"},
                  outputs={"color": "global_o1"}),
        ])
        feedback, _ = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())

    def test_read_only_surface_is_neither_feedback_nor_persistent(self):
        graph = _Graph([
            _pass(inputs={"src": "global_o1"}, outputs={"color": "global_o0"}),
        ])
        feedback, persistent = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())
        self.assertEqual(persistent, set())

    def test_explicit_persistent_texture_spec_is_collected(self):
        graph = _Graph(
            [_pass(outputs={"color": "global_o1"})],
            textures={"global_o1": {"width": "screen", "persistent": True}})
        feedback, persistent = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())
        self.assertEqual(persistent, {"o1"})

    def test_non_boolean_persistent_values_are_not_collected(self):
        graph = _Graph(
            [_pass(outputs={"color": "global_o1"})],
            textures={"global_o1": {"persistent": "true"}})
        _, persistent = feedback_surface_plan(graph)
        self.assertEqual(persistent, set())

    def test_storage_texture_write_counts_when_outputs_are_absent(self):
        # WebGL2's compute fallback writes through storageTextures only when
        # the pass has no explicit outputs (reference parity).
        graph = _Graph([
            _pass(inputs={"src": "global_o1"}),
            _pass(storage={"out": "global_o1"}),
        ])
        feedback, _ = feedback_surface_plan(graph)
        self.assertEqual(feedback, {"o1"})

    def test_outputs_win_over_storage_textures(self):
        graph = _Graph([
            _pass(inputs={"src": "global_o1"}),
            _pass(outputs={"color": "global_o2"},
                  storage={"out": "global_o1"}),
        ])
        feedback, _ = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())

    def test_non_global_and_mesh_texture_ids_are_ignored(self):
        graph = _Graph([
            _pass(inputs={"src": "o1"},
                  outputs={"color": "global_mesh0_positions"}),
            _pass(inputs={"positions": "global_mesh0_positions_chain_0"},
                  outputs={"color": "global_o1"}),
        ])
        feedback, _ = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())

    def test_empty_and_missing_pass_fields_are_tolerated(self):
        graph = _Graph([{}, _pass(outputs={"color": "global_o0"})])
        feedback, persistent = feedback_surface_plan(graph)
        self.assertEqual(feedback, set())
        self.assertEqual(persistent, set())
        self.assertEqual(feedback_surface_plan(_Graph([])), (set(), set()))


if __name__ == "__main__":
    unittest.main()

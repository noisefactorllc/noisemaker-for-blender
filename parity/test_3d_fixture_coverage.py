#!/usr/bin/env python3
"""Require a render3d chain covering every synth3d and filter3d effect."""

import json
import sys
import unittest
from pathlib import Path


PROGRAMS = Path(__file__).with_name("programs")
EXPECTED = Path(__file__).with_name("3d-expected.txt")
POLICY = Path(__file__).with_name("3d-near-policy.json")
sys.path.insert(0, str(PROGRAMS.parents[1] / "blender"))

from noisemaker_blender.compiler import compile_graph, ops  # noqa: E402


FIXTURE_EFFECTS = {
    "cell3d": "cell3d",
    "cellularAutomata3d": "cellularAutomata3d",
    "flythrough3d": "flythrough3d",
    "fractal3d": "fractal3d",
    "render3d": "noise3d",
    "reactionDiffusion3d": "reactionDiffusion3d",
    "shape3d": "shape3d",
    "flow3d": "flow3d",
    "palette3d": "palette3d",
}
FIXTURES = tuple(FIXTURE_EFFECTS)


class FixtureCoverage3dTests(unittest.TestCase):
    def test_3d_expected_manifest_is_exact_unique_and_resolves(self):
        self.assertTrue(EXPECTED.exists(), f"missing expected manifest: {EXPECTED}")
        names = [line.strip() for line in EXPECTED.read_text().splitlines() if line.strip()]
        self.assertEqual(list(FIXTURES), names)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([], [name for name in names if not (PROGRAMS / f"{name}.dsl").exists()])

    def test_3d_near_policy_is_tight_and_mechanism_bound(self):
        self.assertTrue(POLICY.exists(), f"missing 3D policy: {POLICY}")
        document = json.loads(POLICY.read_text())
        self.assertEqual(1, document["version"])
        self.assertEqual(["flythrough3d"], sorted(document["cases"]))
        policy = document["cases"]["flythrough3d"]
        self.assertEqual(87.001, policy["max_abs_diff"])
        self.assertEqual(0.0103, policy["mean_abs_diff"])
        self.assertEqual(0.999, policy["ssim_min"])
        self.assertIn("raymarch surface-boundary", policy["mechanism"])

    def test_every_3d_effect_reaches_render3d(self):
        for fixture, effect in FIXTURE_EFFECTS.items():
            with self.subTest(fixture=fixture, effect=effect):
                source = (PROGRAMS / f"{fixture}.dsl").read_text()
                self.assertIn(f"{effect}(", source)
                self.assertIn(".render3d(", source)

    def test_every_3d_fixture_compiles_in_blender(self):
        for name in FIXTURES:
            with self.subTest(name=name):
                compile_graph((PROGRAMS / f"{name}.dsl").read_text())

    def test_type_choice_tree_does_not_replace_sibling_choices(self):
        effect_choices = ops.enums()["synth3d"]["fractal3d"]
        self.assertEqual(64, effect_choices["volumeSize"]["x64"]["value"])
        self.assertEqual(0, effect_choices["type"]["mandelbulb"]["value"])


if __name__ == "__main__":
    unittest.main()

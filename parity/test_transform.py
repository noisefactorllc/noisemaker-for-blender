#!/usr/bin/env python3
"""Compiler parity tests for program transformation utilities (transform.py)."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import (  # noqa: E402
    compile,
    get_compatible_replacements,
    list_steps,
    replace_effect,
)


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            "search synth, synth3d, filter\n"
            "heightmap3d(heightTex: noise(), tex: gradient()).write(o0)\n"
            "render(o0)"
        )
        self.compiled = compile(self.source)

    def test_list_steps_inline_surface_producers_are_starter_position(self):
        steps = list_steps(self.compiled)
        step_by_name = {s["effectName"]: s for s in steps}

        self.assertIn("synth.noise", step_by_name)
        self.assertIn("synth.gradient", step_by_name)
        self.assertIn("synth3d.heightmap3d", step_by_name)

        noise_step = step_by_name["synth.noise"]
        gradient_step = step_by_name["synth.gradient"]
        heightmap_step = step_by_name["synth3d.heightmap3d"]

        self.assertTrue(noise_step["isStarterPosition"])
        self.assertTrue(gradient_step["isStarterPosition"])
        self.assertTrue(heightmap_step["isStarterPosition"])

        self.assertTrue(noise_step["canReplaceWithStarter"])
        self.assertFalse(noise_step["canReplaceWithNonStarter"])
        self.assertTrue(gradient_step["canReplaceWithStarter"])
        self.assertFalse(gradient_step["canReplaceWithNonStarter"])

    def test_replace_inline_surface_producer_with_starter_succeeds(self):
        steps = list_steps(self.compiled)
        gradient_step = next(s for s in steps if s["effectName"] == "synth.gradient")

        result = replace_effect(self.compiled, gradient_step["stepIndex"], "solid")
        self.assertTrue(result["success"], result.get("error"))

        replaced_step = next(
            s
            for s in result["program"]["plans"][0]["chain"]
            if s.get("temp") == gradient_step["stepIndex"]
        )
        self.assertEqual("synth.solid", replaced_step["op"])

    def test_replace_inline_surface_producer_with_non_starter_fails(self):
        steps = list_steps(self.compiled)
        gradient_step = next(s for s in steps if s["effectName"] == "synth.gradient")

        result = replace_effect(self.compiled, gradient_step["stepIndex"], "blur")
        self.assertFalse(result["success"])
        self.assertIn("starter", result["error"].lower())

    def test_get_compatible_replacements_for_inline_surface_producer(self):
        steps = list_steps(self.compiled)
        gradient_step = next(s for s in steps if s["effectName"] == "synth.gradient")

        result = get_compatible_replacements(self.compiled, gradient_step["stepIndex"])
        self.assertTrue(result["success"])
        self.assertIn("synth.solid", result["compatible"])
        self.assertIn("filter.blur", result["incompatible"])


    def test_standard_chain_replacements(self):
        compiled = compile("search synth, filter\nnoise().blur().write(o0)\nrender(o0)")
        steps = list_steps(compiled)
        self.assertTrue(steps[0]["isStarterPosition"])
        self.assertTrue(steps[0]["canReplaceWithStarter"])
        self.assertFalse(steps[0]["canReplaceWithNonStarter"])

        self.assertFalse(steps[1]["isStarterPosition"])
        self.assertFalse(steps[1]["canReplaceWithStarter"])
        self.assertTrue(steps[1]["canReplaceWithNonStarter"])

        # Replacing non-starter with non-starter succeeds
        res = replace_effect(compiled, steps[1]["stepIndex"], "invert")
        self.assertTrue(res["success"], res.get("error"))
        replaced_step = next(
            s
            for s in res["program"]["plans"][0]["chain"]
            if s.get("temp") == steps[1]["stepIndex"]
        )
        self.assertEqual("filter.invert", replaced_step["op"])

        # Replacing non-starter with starter fails
        res_fail = replace_effect(compiled, steps[1]["stepIndex"], "solid")
        self.assertFalse(res_fail["success"])
        self.assertIn("starter", res_fail["error"].lower())

        # Compatible replacements on non-starter step
        comp = get_compatible_replacements(compiled, steps[1]["stepIndex"])
        self.assertTrue(comp["success"])
        self.assertIn("filter.invert", comp["compatible"])
        self.assertIn("synth.solid", comp["incompatible"])

    def test_helpers_defensive_against_non_strings(self):
        from noisemaker_blender.compiler.transform import (
            _check_is_starter,
            _get_effect_spec,
        )

        self.assertFalse(_check_is_starter(None))
        self.assertFalse(_check_is_starter(123))
        self.assertIsNone(_get_effect_spec(None))
        self.assertIsNone(_get_effect_spec(123))


if __name__ == "__main__":
    unittest.main()

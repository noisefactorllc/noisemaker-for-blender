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

    def test_list_steps_excludes_builtin_steps(self):
        compiled = compile("search synth, filter\nnoise(10).blur().write(o0)\nrender(o0)")
        steps = list_steps(compiled)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["effectName"], "synth.noise")
        self.assertEqual(steps[0]["stepIndex"], 0)
        self.assertEqual(steps[1]["effectName"], "filter.blur")
        self.assertEqual(steps[1]["stepIndex"], 1)

    def test_replace_effect_builtin_step_fails(self):
        compiled = compile("search synth, filter\nnoise(10).write(o0)\nrender(o0)")
        builtin_step = next(s for s in compiled["plans"][0]["chain"] if s.get("builtin"))
        res = replace_effect(compiled, builtin_step["temp"], "bloom")
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "Step with index %s not found" % builtin_step["temp"])

    def test_get_compatible_replacements_builtin_step_fails(self):
        compiled = compile("search synth, filter\nnoise(10).write(o0)\nrender(o0)")
        builtin_step = next(s for s in compiled["plans"][0]["chain"] if s.get("builtin"))
        res = get_compatible_replacements(compiled, builtin_step["temp"])
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "Step with index %s not found" % builtin_step["temp"])


# ============================================================================
# Replacement preflight prediction tests (GAP-008, reference 403c2a4bf2cb)
# ============================================================================


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.compiled = compile("search synth, filter\nnoise(10).blur().write(o0)\nrender(o0)")
        self.steps = list_steps(self.compiled)

    def _step(self, index):
        return self.steps[index]

    def test_predictions_expose_candidate_dimensions(self):
        result = get_compatible_replacements(self.compiled, self._step(1)["stepIndex"])

        self.assertTrue(result["success"])
        self.assertIn("predictions", result)
        grain = result["predictions"]["filter.grain"]
        self.assertIsNotNone(grain)
        self.assertTrue(grain["available"], "Registered instance should be available")
        self.assertEqual(grain["arguments"]["unknown"], [], "No unknown arguments without provided args")
        self.assertEqual(grain["types"], [], "No type mismatches without provided args")
        self.assertEqual(grain["ranges"], [], "No range violations without provided args")
        self.assertEqual(grain["passes"][0]["program"], "grain", "Pass prediction should name the shader program")
        self.assertEqual(
            grain["passes"][0]["outputs"]["fragColor"], "outputTex", "Pass prediction should list outputs"
        )
        self.assertIsNone(grain["backendSupport"], "Backend support is unknown without a manifest")

    def test_manifest_predicts_backend_support(self):
        grain_manifest = {
            "filter/grain": {
                "description": "Grain",
                "glsl": {"grain": "combined"},
                "starter": False,
                # no wgsl entry: WebGPU unsupported
            }
        }
        result = get_compatible_replacements(
            self.compiled, self._step(1)["stepIndex"], {"manifest": grain_manifest}
        )
        grain = result["predictions"]["filter.grain"]
        self.assertTrue(grain["backendSupport"]["webgl2"], "GLSL-only manifest should mark WebGL2 supported")
        self.assertFalse(grain["backendSupport"]["webgpu"], "Missing WGSL entry should mark WebGPU unsupported")

        missing = get_compatible_replacements(
            self.compiled,
            self._step(1)["stepIndex"],
            {"manifest": {"filter/grain": {"glsl": {}, "wgsl": {}}}},
        )
        self.assertFalse(
            missing["predictions"]["filter.grain"]["backendSupport"]["webgl2"],
            "Empty program table is unsupported",
        )

    def test_default_classification_is_unchanged(self):
        result = get_compatible_replacements(self.compiled, self._step(1)["stepIndex"])
        self.assertIn("filter.bloom", result["compatible"], "Bloom stays compatible without preflight opt-in")
        self.assertIn("synth.noise", result["incompatible"], "Starters stay incompatible without preflight opt-in")

    def test_replace_default_behavior_unchanged_prediction_attached(self):
        # Unknown argument, out-of-range value: previously accepted, must stay accepted
        result = replace_effect(self.compiled, self._step(1)["stepIndex"], "grain", {"amnt": 9})
        self.assertTrue(result["success"], "Previously accepted input must still succeed without opt-in")
        self.assertIn("prediction", result, "Success should carry the prediction")
        self.assertIn("amnt", result["prediction"]["arguments"]["unknown"])
        self.assertEqual(result["prediction"]["ranges"], [], "Unknown arguments have no declared range to check")

    def test_replace_preflight_refuses_unknown_argument(self):
        result = replace_effect(
            self.compiled, self._step(1)["stepIndex"], "grain", {"amnt": 0.9}, {"preflight": True}
        )
        self.assertFalse(result["success"], "Preflight should refuse unknown arguments")
        self.assertIn("preflight", result["error"], "Error should mention preflight")
        self.assertIn("amnt", result["error"], "Error should name the unknown argument")
        self.assertNotIn("program", result, "No program should be produced on preflight failure")

    def test_replace_preflight_refuses_out_of_range_value(self):
        result = replace_effect(
            self.compiled, self._step(1)["stepIndex"], "grain", {"alpha": 5}, {"preflight": True}
        )
        self.assertFalse(result["success"], "Preflight should refuse out-of-range values")
        self.assertIn("outside range", result["error"], "Error should mention the range")

    def test_replace_preflight_refuses_choice_violation(self):
        # filter.invert mode choices: full=0, solarize=1
        result = replace_effect(
            self.compiled, self._step(1)["stepIndex"], "invert", {"mode": 7}, {"preflight": True}
        )
        self.assertFalse(result["success"], "Preflight should refuse invalid choice values")
        self.assertIn("not one of", result["error"], "Error should mention the choices")

    def test_replace_preflight_refuses_type_mismatch(self):
        result = replace_effect(
            self.compiled, self._step(1)["stepIndex"], "grain", {"alpha": "high"}, {"preflight": True}
        )
        self.assertFalse(result["success"], "Preflight should refuse type mismatches")
        self.assertIn("expects float", result["error"], "Error should mention the expected type")

    def test_replace_preflight_passes_valid_replacement_through_with_prediction(self):
        result = replace_effect(
            self.compiled, self._step(1)["stepIndex"], "grain", {"alpha": 0.75}, {"preflight": True}
        )
        self.assertTrue(result["success"], "Valid preflight replacement should succeed")
        chain = result["program"]["plans"][0]["chain"]
        replaced = next(s for s in chain if s.get("temp") == self._step(1)["stepIndex"])
        self.assertEqual("filter.grain", replaced["op"], "Effect should be replaced")
        self.assertEqual(0.75, replaced["args"]["alpha"], "Args should be applied")
        self.assertTrue(result["prediction"]["available"], "Prediction should mark the effect available")
        self.assertIsNotNone(result["prediction"]["samplerTopology"])

    def test_prediction_registered_param_alias_is_accepted_with_canonical_checks(self):
        # The lang-level alias registry is intentionally empty (Stage-1 golden
        # contract, see compiler/ops.py); mirror the reference test's
        # registerParamAliases by injecting a temporary map.
        from noisemaker_blender.compiler import ops as ops_mod

        ops_mod._ensure_built()
        ops_mod._PARAM_ALIASES["filter.grain"] = {"amt": "alpha"}
        try:
            # Supplied via deprecated alias: not unknown, range/type checked canonically
            via_alias = replace_effect(self.compiled, self._step(1)["stepIndex"], "grain", {"amt": 0.9})
            self.assertTrue(via_alias["success"], "Alias-supplied replacement should succeed without opt-in")
            self.assertEqual(
                via_alias["prediction"]["arguments"]["unknown"], [], "Alias name should not be predicted unknown"
            )
            self.assertEqual(
                via_alias["prediction"]["arguments"]["missing"], [], "No missing-argument issue for grain"
            )

            via_alias_preflight = replace_effect(
                self.compiled, self._step(1)["stepIndex"], "grain", {"amt": 0.9}, {"preflight": True}
            )
            self.assertTrue(via_alias_preflight["success"], "Alias-supplied replacement should pass preflight")
            self.assertEqual(
                via_alias_preflight["prediction"]["ranges"], [], "Alias value within range should not be flagged"
            )

            # Range violation through the alias still fires canonically
            out_of_range = replace_effect(
                self.compiled, self._step(1)["stepIndex"], "grain", {"amt": 5}, {"preflight": True}
            )
            self.assertFalse(out_of_range["success"], "Out-of-range value via alias should be refused under preflight")
            self.assertIn("alpha", out_of_range["error"], "Range error should name the canonical argument")
        finally:
            del ops_mod._PARAM_ALIASES["filter.grain"]

    def test_preflight_moves_unavailable_candidates_to_blocked(self):
        # Simulate a never-registered effect definition by hiding one from the
        # registry (reference test registers a fake instance; the port's
        # registry is fully populated from effects/*.json, so an *unavailable*
        # prediction needs a temporarily-shadowed key).
        from noisemaker_blender.compiler import registry as registry_mod
        from noisemaker_blender.compiler import transform as transform_mod

        registry_mod._ensure_loaded()
        saved = registry_mod._REGISTRY.pop("filter.bloom")
        try:
            result = get_compatible_replacements(self.compiled, self._step(1)["stepIndex"], {"preflight": True})
            self.assertNotIn("filter.bloom", result["compatible"], "Bloom should leave compatible under preflight")
            self.assertIn("filter.grain", result["compatible"], "Grain should stay compatible under preflight")
            self.assertIn("blocked", result, "Preflight should return a blocked list")
            bloom_block = next((b for b in result["blocked"] if b["effect"] == "filter.bloom"), None)
            self.assertIsNotNone(bloom_block, "Bloom should be blocked")
            self.assertTrue(
                any(i["dimension"] == "shader-availability" for i in bloom_block["issues"]),
                "Block reason should be shader availability",
            )
            self.assertIs(transform_mod._get_effect_instance("filter.bloom"), None)
        finally:
            registry_mod._REGISTRY["filter.bloom"] = saved


if __name__ == "__main__":
    unittest.main()

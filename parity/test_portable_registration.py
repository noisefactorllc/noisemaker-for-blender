#!/usr/bin/env python3
"""Portable effect registration tests (upstream cb22a05e, test_portable_registration.js).

The port's equivalent of CanvasRenderer.registerPortableEffect: a user-supplied
Portable definition registers into the compiler's effect/op/enum/starter
registries as ``user.<func>`` after the same registration-input validation.
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import (  # noqa: E402
    PortableEffectError,
    compile,
    expand,
    register_portable_effect,
)
from noisemaker_blender.compiler import ops, registry  # noqa: E402


def definition(func, overrides=None):
    raw = {
        "namespace": "user",
        "name": func,
        "func": func,
        "globals": {},
        "passes": [{"name": "main", "program": "main",
                    "inputs": {}, "outputs": {"fragColor": "outputTex"}}],
        "shaders": {"main": {"glsl": "#version 300 es\nvoid main() {}"}},
    }
    if overrides:
        raw.update(overrides)
    return raw


class PortableRegistrationTests(unittest.TestCase):
    def tearDown(self):
        ops.rebuild()

    def test_registration_preserves_the_definition_and_lookup_keys(self):
        raw = definition("portableContract", {
            "textures": {"history": {"width": 32, "height": 32, "format": "rgba16f"}},
            "outputTex3d": {"width": 8, "height": 8, "depth": 8},
            "outputGeo": {"count": 16},
            "uniformLayout": {"time": "float"},
            "uniformLayouts": {"main": {"time": "float"}},
            "passes": [{"name": "main", "program": "main", "type": "compute",
                        "drawMode": "points", "count": 16,
                        "inputs": {"previous": "history"},
                        "outputs": {"fragColor": "outputTex"}}],
            "defaultProgram": "search user\nportableContract().write(o0)\nrender(o0)",
        })
        registered = register_portable_effect(copy.deepcopy(raw))
        self.assertIs(registry.get_effect("user.portableContract"), registered)
        self.assertIs(registry.get_effect("user/portableContract"), registered)
        self.assertIsNone(registry.get_effect("portableContract"))
        for key in ["shaders", "textures", "outputTex3d", "outputGeo",
                    "uniformLayout", "uniformLayouts", "passes", "defaultProgram"]:
            self.assertEqual(registered[key], raw[key], key)

    def test_aliases_choice_names_and_explicit_enum_paths_compile_to_uniforms(self):
        ops.merge_enums({"portableExplicit": {"Keep": {"type": "Number", "value": 7}}})
        register_portable_effect(definition("portableParams", {
            "globals": {
                "mode": {"type": "int", "default": 0, "uniform": "modeUniform",
                         "choices": {"Modes:": -1, "Soft Light": 3}},
                "pinned": {"type": "int", "default": 0, "uniform": "pinnedUniform",
                           "enumPath": "portableExplicit", "choices": {"Keep": 99}},
                "primary": {"type": "int", "default": 0, "uniform": "primaryUniform",
                            "enum": "portableExplicit", "enumPath": "missing",
                            "choices": {"Keep": 99}},
            },
            "paramAliases": {"oldMode": "mode"},
        }))
        compiled = compile(
            "search user\nportableParams(oldMode: SoftLight, pinned: Keep, primary: Keep)"
            ".write(o0)\nrender(o0)")
        graph = expand(compiled)
        passes = [p for p in graph["passes"] if p.get("effectKey") == "user.portableParams"]
        self.assertTrue(passes, str(compiled.get("diagnostics")))
        uniforms = {}
        for p in passes:
            uniforms.update(p["uniforms"])
        self.assertEqual(uniforms.get("modeUniform"), 3)
        self.assertEqual(uniforms.get("pinnedUniform"), 7)
        self.assertEqual(uniforms.get("primaryUniform"), 7)
        soft_light = ops.enums()["user"]["portableParams"]["mode"]["SoftLight"]
        self.assertEqual(soft_light.get("value", soft_light), 3)

    def test_starter_inference_covers_every_pipeline_input_and_honors_overrides(self):
        bindings = ["inputTex", "inputTex3d", "inputGeo", "inputXyz", "inputVel",
                    "inputRgba", "src", "o0", "o1", "o2", "o3", "o4", "o5",
                    "o6", "o7"]
        for index, binding in enumerate(bindings):
            func = "portableInput%d" % index
            register_portable_effect(definition(func, {
                "passes": [{"program": "main", "inputs": {"source": binding},
                            "outputs": {"fragColor": "outputTex"}}]
            }))
            self.assertFalse(ops.is_starter_op("user.%s" % func), binding)
        register_portable_effect(definition("portableExplicitFilter", {"starter": False}))
        self.assertFalse(ops.is_starter_op("user.portableExplicitFilter"))
        register_portable_effect(definition("portableExplicitStarter", {
            "starter": True,
            "passes": [{"program": "main", "inputs": {"source": "inputTex"}}],
        }))
        self.assertTrue(ops.is_starter_op("user.portableExplicitStarter"))
        register_portable_effect(definition("portableInferredStarter"))
        self.assertTrue(ops.is_starter_op("user.portableInferredStarter"))
        self.assertFalse(ops.is_starter_op("portableInferredStarter"))

    def test_invalid_packages_fail_before_registration_and_leave_the_name_available(self):
        invalid = [
            None,
            [],
            definition("bad-name"),
            definition("portableInvalid", {"namespace": "synth"}),
            definition("portableInvalid", {"passes": []}),
            definition("portableInvalid", {"passes": [None]}),
            definition("portableInvalid", {"passes": [{"program": "main", "inputs": {"src": 42}}]}),
            definition("portableInvalid", {"passes": [{"program": "main", "outputs": None}]}),
            definition("portableInvalid", {"passes": [{"program": "main", "outputs": {"color": ""}}]}),
            definition("portableInvalid", {"shaders": {}}),
            definition("portableInvalid", {"shaders": {"main": {"glsl": " "}}}),
            definition("portableInvalid", {
                "passes": [{"program": "a"}, {"program": "b"}],
                "shaders": {"a": {"glsl": "source"}, "b": {"wgsl": "source"}},
            }),
            definition("portableInvalid", {"globals": {"amount": None}}),
            definition("portableInvalid", {"starter": "false"}),
            definition("portableInvalid", {"paramAliases": "bad"}),
            definition("portableInvalid", {"paramAliases": {"old": 42}}),
            definition("portableInvalid", {"paramAliases": {"old": "absent"}}),
            definition("portableInvalid", {"globals": {"mode": {"type": "int", "choices": "abc"}}}),
            definition("portableInvalid", {"globals": {"mode": {"type": "int", "choices": {"Broken": {}}}}}),
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(PortableEffectError, "Portable"):
                    register_portable_effect(raw)
                self.assertIsNone(registry.get_effect("user.portableInvalid"))
        register_portable_effect(definition("portableInvalid"))
        self.assertIsNotNone(registry.get_effect("user.portableInvalid"))

    def test_a_name_only_portable_effect_preserves_an_existing_bare_built_in_name(self):
        registry.load()  # populate the catalog before injecting a bare built-in
        prior = {"namespace": "synth", "func": "portableNameOnly"}
        registry._REGISTRY["portableNameOnly"] = prior
        raw = definition("portableNameOnly")
        del raw["func"]
        registered = register_portable_effect(raw)
        self.assertIs(registry.get_effect("portableNameOnly"), prior)
        self.assertIs(registry.get_effect("user.portableNameOnly"), registered)
        self.assertEqual(registered["func"], "portableNameOnly")
        self.assertTrue(ops.is_starter_op("user.portableNameOnly"))

    def test_duplicate_portable_names_cannot_replace_an_accepted_effect(self):
        first = register_portable_effect(definition("portableDuplicate"))
        with self.assertRaisesRegex(PortableEffectError, "already registered"):
            register_portable_effect(definition("portableDuplicate", {"starter": False}))
        self.assertIs(registry.get_effect("user.portableDuplicate"), first)
        self.assertTrue(ops.is_starter_op("user.portableDuplicate"))

    def test_portable_names_and_metadata_cannot_write_through_object_prototypes(self):
        choices = {"mode": {"type": "int", "default": 0, "choices": {"Choice": 1}}}
        for name in ["__proto__", "constructor", "prototype", "toString",
                     "valueOf", "hasOwnProperty"]:
            invalid_defs = [
                definition(name, {"globals": choices}),
                definition("portableReserved", {"globals": {name: choices["mode"]}}),
                definition("portableReserved", {
                    "globals": {"mode": dict(choices["mode"],
                                            choices={name: 1})},
                }),
            ]
            for raw in invalid_defs:
                with self.subTest(name=name, raw_keys=list(raw)):
                    with self.assertRaisesRegex(PortableEffectError, "reserved"):
                        register_portable_effect(raw)
                    self.assertIsNone(registry.get_effect("user.portableReserved"))


if __name__ == "__main__":
    unittest.main()

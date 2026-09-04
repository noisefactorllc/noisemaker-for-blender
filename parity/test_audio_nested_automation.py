#!/usr/bin/env python3
"""Compiler parity for selected audio inputs and nested automation."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import compile  # noqa: E402


def compile_scale_x(expression):
    source = "search synth\nnoise(scaleX: %s).write(o0)\nrender(o0)" % expression
    result = compile(source)
    return result, result["plans"][0]["chain"][0]["args"]["scaleX"]


class SelectedAudioCompilerTests(unittest.TestCase):
    def test_selected_raw_audio_preserves_dense_positionals_and_identity(self):
        _, descriptor = compile_scale_x(
            'audio(name: "Studio \\"Input\\"", id: "device\\\\2", '
            'channel: 2, audioBand.raw, 0.25, 0.75)'
        )

        self.assertEqual(4, descriptor["band"])
        self.assertEqual(0.25, descriptor["min"])
        self.assertEqual(0.75, descriptor["max"])
        self.assertEqual(2, descriptor["channel"])
        self.assertEqual('Studio "Input"', descriptor["name"])
        self.assertEqual(r"device\2", descriptor["id"])
        self.assertFalse(descriptor["_invalid"])

    def test_invalid_selected_audio_forms_are_rejected(self):
        cases = {
            'audio(band: audioBand.low, id: "device")': "requires readable 'name'",
            'audio(band: audioBand.low, name: "Input")': "requires both 'name' and 'channel'",
            'audio(band: audioBand.low, channel: 1)': "requires both 'name' and 'channel'",
            'audio(band: audioBand.low, channel: 1, name: "")': "must not be empty",
            'audio(band: audioBand.low, channel: 1, name: inputName)': "requires a quoted string",
            'audio(audioBand.low, 0, 1, 2)': "keyword-only",
            'audio(band: audioBand.low, vendor: "Noise Factor")': "unknown parameter 'vendor'",
        }

        for expression, message in cases.items():
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(SyntaxError, message):
                    compile_scale_x(expression)

    def test_invalid_audio_fields_fail_closed_with_diagnostics(self):
        result, descriptor = compile_scale_x(
            'audio(band: osc(), min: "not-a-number", channel: 0, name: "Input")'
        )

        messages = "\n".join(item["message"] for item in result["diagnostics"])
        self.assertIn("audio() band", messages)
        self.assertIn("String literal not allowed for audio() min", messages)
        self.assertIn("audio() channel must be a positive integer", messages)
        self.assertTrue(descriptor["_invalid"])
        self.assertNotIn("band", descriptor)


class NestedAutomationCompilerTests(unittest.TestCase):
    def test_nested_oscillator_descriptor_and_variable_reference_survive(self):
        source = """search synth
let rate = audio(band: audioBand.raw, min: 0.25, max: 0.75)
let carrier = osc(type: oscKind.saw, speed: rate)
noise(scaleX: carrier).write(o0)
render(o0)"""

        result = compile(source)
        descriptor = result["plans"][0]["chain"][0]["args"]["scaleX"]

        self.assertEqual([], result["diagnostics"])
        self.assertEqual("Oscillator", descriptor["type"])
        self.assertEqual("carrier", descriptor["_varRef"])
        self.assertEqual("Audio", descriptor["speed"]["type"])
        self.assertEqual("rate", descriptor["speed"]["_varRef"])
        self.assertEqual(4, descriptor["speed"]["band"])

    def test_automation_cycle_is_reported(self):
        source = """search synth
let first = osc(type: oscKind.sine, speed: second)
let second = osc(type: oscKind.tri, speed: first)
noise(scaleX: first).write(o0)
render(o0)"""

        result = compile(source)
        messages = "\n".join(item["message"] for item in result["diagnostics"])

        self.assertRegex(messages, r"(?i)automation cycle")

    def test_automation_nesting_beyond_eight_levels_is_rejected(self):
        lets = ["let rate9 = osc(type: oscKind.sine)"]
        for level in range(8, 0, -1):
            lets.append(
                "let rate%d = osc(type: oscKind.sine, speed: rate%d)"
                % (level, level + 1)
            )
        lets.append("let carrier = osc(type: oscKind.saw, speed: rate1)")
        source = "search synth\n%s\nnoise(scaleX: carrier).write(o0)\nrender(o0)" % "\n".join(lets)

        result = compile(source)
        messages = "\n".join(item["message"] for item in result["diagnostics"])

        self.assertIn("maximum depth of 8", messages)


if __name__ == "__main__":
    unittest.main()

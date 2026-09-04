#!/usr/bin/env python3
"""Compiler parity for device-qualified MIDI automation descriptors."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import compile  # noqa: E402


def compile_scale_x(expression):
    source = "search synth\nnoise(scaleX: %s).write(o0)\nrender(o0)" % expression
    result = compile(source)
    return result["plans"][0]["chain"][0]["args"]["scaleX"]


class MidiDeviceSelectionTests(unittest.TestCase):
    def test_identity_first_mixed_form_preserves_dense_positionals(self):
        descriptor = compile_scale_x(
            'midi(name: "Launch Control XL", id: "port-2", 2, 0, 0.25, 0.75, 3)'
        )

        self.assertEqual(2, descriptor["channel"])
        self.assertEqual(0, descriptor["mode"])
        self.assertEqual(0.25, descriptor["min"])
        self.assertEqual(0.75, descriptor["max"])
        self.assertEqual(3, descriptor["sensitivity"])
        self.assertEqual("Launch Control XL", descriptor["name"])
        self.assertEqual("port-2", descriptor["id"])

    def test_identity_strings_decode_escapes(self):
        descriptor = compile_scale_x(
            r'midi(channel: 1, name: "Launch \"Control\"", id: "port\\2")'
        )

        self.assertEqual('Launch "Control"', descriptor["name"])
        self.assertEqual(r"port\2", descriptor["id"])

    def test_integral_decimal_mode_is_preserved(self):
        descriptor = compile_scale_x("midi(channel: 1, mode: 2.0)")

        self.assertEqual(2, descriptor["mode"])

    def test_invalid_identity_forms_are_rejected(self):
        cases = {
            'midi(channel: 1, id: "port-2")': "requires readable 'name'",
            'midi(channel: 1, name: "")': "must not be empty",
            "midi(channel: 1, name: portName)": "requires a quoted string",
            'midi(1, 0, 0, 1, 1, "Controller")': "keyword-only",
            'midi(channel: 1, vendor: "Noise Factor")': "unknown parameter 'vendor'",
        }

        for expression, message in cases.items():
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(SyntaxError, message):
                    compile_scale_x(expression)

    def test_non_midi_calls_still_reject_mixed_arguments(self):
        source = "search synth\nnoise(scaleX: 1, 2).write(o0)\nrender(o0)"

        with self.assertRaisesRegex(SyntaxError, "Cannot mix positional and keyword arguments"):
            compile(source)


if __name__ == "__main__":
    unittest.main()

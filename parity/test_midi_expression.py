#!/usr/bin/env python3
"""MIDI expression and default audio channel contracts from upstream 246ff57."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.compiler import compile
from noisemaker_blender.runtime.pipeline import resolve_uniform_value


def descriptor(expression, declarations=""):
    result = compile("search synth\n%s\nnoise(scaleX: %s).write(o0)\nrender(o0)" % (declarations, expression))
    return result, result["plans"][0]["chain"][0]["args"]["scaleX"]


class MidiExpressionTests(unittest.TestCase):
    def test_modes_and_static_selector_variables(self):
        for mode, number in (("cc", 5), ("cc14", 6), ("nrpn", 7), ("pitchBend", 8), ("pressure", 9), ("polyPressure", 10)):
            with self.subTest(mode=mode):
                extra = ", nrpn: parameter" if mode == "nrpn" else ""
                result, value = descriptor(
                    "midi(zone: selected, members: count, mode: midiMode.%s%s)" % (mode, extra),
                    "let selected = midiZone.upper\nlet count = 7\nlet parameter = 1234")
                self.assertEqual([], result["diagnostics"])
                self.assertEqual(number, value["mode"])
                self.assertEqual(1, value["zone"])
                self.assertEqual(7, value["members"])
                self.assertNotIn("channel", value)
                if mode == "nrpn": self.assertEqual(1234, value["nrpn"])
                if mode in ("cc", "cc14"): self.assertEqual(1, value["cc"])

    def test_invalid_selectors_fail_closed(self):
        for args in ("channel: 0, mode: 5", "channel: true, mode: 8", "channel: 2, mode: 6, cc: 32", "channel: 2, mode: 5, cc: osc()", "channel: 2, mode: 7", "channel: 2, mode: 7, nrpn: 16383", "zone: 2", "zone: 0, members: 16"):
            with self.subTest(args=args):
                result, value = descriptor("midi(%s)" % args)
                self.assertTrue(result["diagnostics"])
                self.assertTrue(value["_invalid"])
                self.assertEqual(0, resolve_uniform_value(value, 0, external_state={"midi": self}))

    def test_mutually_exclusive_channel_and_zone(self):
        for args in ("channel: 2, zone: 0", "channel: 2, members: 3", "mode: 5"):
            with self.subTest(args=args), self.assertRaises(SyntaxError):
                descriptor("midi(%s)" % args)

    def test_controller_and_expression_values(self):
        channel = {"key": 60, "gate": 0, "cc": {74: 127}, "cc14": {31: 16383}, "nrpn": {1234: 8192}, "pitchBend": 0, "pressure": 127, "polyPressure": {60: 64}}
        class State:
            def get_channel(self, number): return channel
            def get_zone_voice(self, config): return {"channel": channel, "key": 60, "velocity": 100, "time": 0}
        state = {"midi": State()}
        for mode, extra, raw in ((5, {"cc": 74}, 1), (6, {"cc": 31}, 1), (7, {"nrpn": 1234}, 8192 / 16383), (8, {}, 0), (9, {}, 1), (10, {}, 64 / 127)):
            for selector in ({"channel": 2}, {"zone": 0, "members": 5}):
                with self.subTest(mode=mode, selector=selector):
                    value = {"type": "Midi", "mode": mode, "min": .25, "max": .75, **extra, **selector}
                    self.assertAlmostEqual(.25 + raw * .5, resolve_uniform_value(value, 0, external_state=state))

    def test_default_audio_channel_and_bounds(self):
        for channel in (1, 32):
            result, value = descriptor("audio(band: audioBand.raw, channel: %s)" % channel)
            self.assertEqual([], result["diagnostics"])
            self.assertEqual(channel, value["channel"])
            self.assertNotIn("name", value)
        for channel in (0, 33, 1.5):
            result, value = descriptor("audio(band: audioBand.raw, channel: %s)" % channel)
            self.assertTrue(result["diagnostics"])
            self.assertTrue(value["_invalid"])

    def test_selector_diagnostics_match_reference_scalar_spelling(self):
        result, _ = descriptor("midi(channel: 0, mode: 5)")
        self.assertEqual("[Number]", result["diagnostics"][0]["identifier"])
        result, _ = descriptor("audio(band: audioBand.raw, channel: true)")
        self.assertEqual(
            "audio() channel must be a positive integer from 1 to 32 (got true)",
            result["diagnostics"][0]["message"],
        )

    def test_malformed_audio_selector_does_not_fall_back(self):
        class State:
            def get_device_channel_state(self, config): return {"raw": 1, "rawReady": True}
        for fields in ({"channel": 33}, {"name": "Input"}, {"channel": 1, "id": "device"}, {"_ast": {"type": "Audio", "channel": {"type": "Number", "value": 1}}}):
            value = {"type": "Audio", "band": 4, "min": .25, "max": .75, **fields}
            self.assertEqual(.25, resolve_uniform_value(value, 0, external_state={"audio": State()}))


if __name__ == "__main__":
    unittest.main()

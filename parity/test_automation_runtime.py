#!/usr/bin/env python3
"""Runtime parity for recursive Noisemaker automation descriptors."""

import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.runtime.pipeline import render, resolve_uniform_value  # noqa: E402


def oscillator(osc_type=0, **overrides):
    value = {
        "type": "Oscillator",
        "oscType": osc_type,
        "min": 0,
        "max": 1,
        "speed": 1,
        "offset": 0,
        "seed": 1,
    }
    value.update(overrides)
    return value


class SelectedAudioState:
    def __init__(self, raw):
        self.raw = raw

    def get_device_channel_state(self, config):
        if config.get("id") != "device" or config.get("channel") != 2:
            return None
        return {
            "low": 0.1,
            "mid": 0.2,
            "high": 0.3,
            "vol": 0.4,
            "raw": self.raw,
            "rawReady": True,
        }


class CaptureBackend:
    size = 64

    def __init__(self):
        self.uniforms = []
        self.frame_read = {"o0": "surface"}

    def setup(self, graph, defaults):
        self.defaults = defaults

    def frame_begin(self):
        pass

    def execute(self, render_pass, graph, engine):
        self.uniforms.append(dict(render_pass["uniforms"]))

    def swap_after_write(self, texture_id):
        pass

    def frame_persist(self):
        pass

    def read_surface(self, name):
        return self.frame_read[name]


class AutomationRuntimeTests(unittest.TestCase):
    def test_simple_oscillator_scales_to_the_consumer_range(self):
        value = resolve_uniform_value(
            oscillator(), 0.25, {"min": 10, "max": 20}
        )

        self.assertAlmostEqual(15, value)

    def test_nested_oscillator_rate_is_seekable_and_deterministic(self):
        carrier = oscillator(2, speed=oscillator(0))
        first = resolve_uniform_value(carrier, 0.25)
        repeated = resolve_uniform_value(carrier, 0.25)
        expected = (-20 / (math.pi * 2)) % 1

        self.assertAlmostEqual(expected, first, places=9)
        self.assertEqual(first, repeated)

    def test_selected_raw_audio_uses_the_requested_device_channel(self):
        value = {
            "type": "Audio",
            "band": 4,
            "min": 0.25,
            "max": 0.75,
            "channel": 2,
            "name": "Interface",
            "id": "device",
            "_invalid": False,
        }

        low = resolve_uniform_value(
            value, 0.5, external_state={"audio": SelectedAudioState(-1)}
        )
        high = resolve_uniform_value(
            value, 0.5, external_state={"audio": SelectedAudioState(1)}
        )

        self.assertEqual(0.25, low)
        self.assertEqual(0.75, high)

    def test_missing_or_invalid_audio_fails_closed_to_minimum(self):
        missing = {"type": "Audio", "band": 0, "min": 0.2, "max": 0.8}
        invalid = {
            "type": "Audio", "band": None, "min": 0.3, "max": 0.9,
            "_invalid": True,
        }

        self.assertEqual(0.2, resolve_uniform_value(missing, 0.5))
        self.assertEqual(0.3, resolve_uniform_value(invalid, 0.5))

    def test_runtime_cycle_guard_fails_closed(self):
        cyclic = oscillator(2)
        cyclic["speed"] = cyclic

        self.assertEqual(0, resolve_uniform_value(cyclic, 0.5))

    def test_eight_nested_rate_modulators_stay_bounded_and_deterministic(self):
        rate = oscillator(0)
        for _ in range(7):
            rate = oscillator(0, speed=rate)
        carrier = oscillator(2, speed=rate)

        first = resolve_uniform_value(carrier, 0.61)
        repeated = resolve_uniform_value(carrier, 0.61)

        self.assertTrue(math.isfinite(first))
        self.assertGreaterEqual(first, 0)
        self.assertLessEqual(first, 1)
        self.assertEqual(first, repeated)

    def test_render_resolves_descriptors_before_backend_execution(self):
        backend = CaptureBackend()
        graph = SimpleNamespace(
            passes=[{
                "passType": "effect",
                "uniforms": {"amount": oscillator()},
                "uniformSpecs": {"amount": {"min": 10, "max": 20}},
                "outputs": {},
            }],
            render_surface="o0",
        )

        result = render(backend, graph, time=0.25)

        self.assertEqual("surface", result)
        self.assertAlmostEqual(15, backend.uniforms[0]["amount"])


if __name__ == "__main__":
    unittest.main()

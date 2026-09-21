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


class MultiChannelAudioState:
    def __init__(self, device_id):
        self.device_id = device_id
        self.channels = {}

    def set_channel_values(self, channel, values):
        val = dict(values)
        if "raw" in val:
            val["rawReady"] = True
        self.channels[channel] = val

    def get_device_channel_state(self, config):
        if config.get("id") != self.device_id:
            return None
        return self.channels.get(config.get("channel"))


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

    def test_32_discrete_channels_simultaneously_modulate_with_zero_crosstalk_and_zero_inversion(self):
        device_id = "audio-fuse-32"
        device_name = "Arturia AudioFuse 32"
        audio_state = MultiChannelAudioState(device_id)

        uniforms = {}
        for c in range(1, 33):
            uniforms["mod_%d" % c] = {
                "type": "Audio",
                "band": 4,
                "min": 0,
                "max": 1,
                "channel": c,
                "id": device_id,
                "name": device_name,
            }

        # Linear ramp: raw sample on channel c = (c / 16) - 1, mapping to (raw + 1) * 0.5 = c / 32
        for c in range(1, 33):
            raw = (c / 16.0) - 1.0
            audio_state.set_channel_values(c, {"raw": raw})

        ext_state = {"audio": audio_state}

        # Verify each uniform resolves to exactly c / 32
        for c in range(1, 33):
            expected = c / 32.0
            actual = resolve_uniform_value(uniforms["mod_%d" % c], 0, external_state=ext_state)
            self.assertAlmostEqual(
                actual, expected, places=6,
                msg="channel %d must resolve to %s, got %s" % (c, expected, actual),
            )

        # Zero crosstalk perturbation test: alter channel 17
        original17 = resolve_uniform_value(uniforms["mod_17"], 0, external_state=ext_state)
        audio_state.set_channel_values(17, {"raw": 1.0})
        new17 = resolve_uniform_value(uniforms["mod_17"], 0, external_state=ext_state)
        self.assertAlmostEqual(new17, 1.0, places=6)
        self.assertNotEqual(new17, original17)

        # Verify all other 31 channels have strictly 0.0 delta (zero crosstalk)
        for c in range(1, 33):
            if c == 17:
                continue
            expected = c / 32.0
            actual = resolve_uniform_value(uniforms["mod_%d" % c], 0, external_state=ext_state)
            self.assertEqual(
                actual, expected,
                "crosstalk detected on channel %d when channel 17 perturbed: expected %s, got %s"
                % (c, expected, actual),
            )

        # Channel inversion check: verify monotonicity
        previous = -1.0
        for c in range(1, 33):
            val = original17 if c == 17 else resolve_uniform_value(uniforms["mod_%d" % c], 0, external_state=ext_state)
            self.assertGreater(
                val, previous,
                "channel %d (%s) must be strictly greater than channel %d (%s)"
                % (c, val, c - 1, previous),
            )
            previous = val

    def test_32_discrete_channels_evaluate_fft_frequency_bands_independently(self):
        device_id = "audio-fft-32"
        device_name = "Multichannel Interface"
        audio_state = MultiChannelAudioState(device_id)

        for c in range(1, 33):
            audio_state.set_channel_values(c, {
                "low": c / 32.0,
                "mid": (33 - c) / 32.0,
                "high": 0.8 if c % 2 == 0 else 0.2,
                "vol": 0.5,
            })

        ext_state = {"audio": audio_state}

        for c in range(1, 33):
            low_config = {"type": "Audio", "band": 0, "min": 0, "max": 1, "channel": c, "id": device_id, "name": device_name}
            mid_config = {"type": "Audio", "band": 1, "min": 0, "max": 1, "channel": c, "id": device_id, "name": device_name}
            high_config = {"type": "Audio", "band": 2, "min": 0, "max": 1, "channel": c, "id": device_id, "name": device_name}
            vol_config = {"type": "Audio", "band": 3, "min": 0, "max": 1, "channel": c, "id": device_id, "name": device_name}

            self.assertAlmostEqual(resolve_uniform_value(low_config, 0, external_state=ext_state), c / 32.0, places=6)
            self.assertAlmostEqual(resolve_uniform_value(mid_config, 0, external_state=ext_state), (33 - c) / 32.0, places=6)
            self.assertAlmostEqual(resolve_uniform_value(high_config, 0, external_state=ext_state), 0.8 if c % 2 == 0 else 0.2, places=6)
            self.assertAlmostEqual(resolve_uniform_value(vol_config, 0, external_state=ext_state), 0.5, places=6)


if __name__ == "__main__":
    unittest.main()

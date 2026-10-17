"""The reference asyncInit overlays (filter/fibers, filter/scratches, filter/strayHair).

Reference vectors come from the pinned reference (parity/reference-revision,
6cb1a3c3): shaders/src/cpu/wormTracer.js and each effect's definition.js run in
Node with a recording 2D context. A stroke stream hash covers each stroke's
float32 end points and line width (Blink keeps path points as floats), its
rgb bytes and its alpha double, packed little-endian as '<5f3Bd'.

The overlay hashes are the canvas that the reference stroke streams draw on
noisemaker-for-qt's Skia model (qt/noisemaker/runtime/stroke_canvas.cpp at
e63ce6e5), which reproduces Chromium's software canvas for these strokes:
straight-alpha RGBA8, row 0 at the top.
"""

import hashlib
import json
import math
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.runtime import async_overlay  # noqa: E402
from noisemaker_blender.runtime.stroke_canvas import StrokeCanvas  # noqa: E402
from noisemaker_blender.runtime.worm_tracer import SeededRNG, value_noise_field  # noqa: E402

EFFECTS = ROOT / "blender" / "noisemaker_blender" / "effects" / "filter"

RNG_STREAMS = {
    1: [1892593347, 875373008, 2815485151, 3821519855, 47061707, 2057581738],
    1042: [1244341288, 1383730409, 784902715, 1361891460, 1073970240, 3946651500],
    31337: [2022276450, 1025216116, 991478700, 194985198, 1204475871, 3683767862],
    31337000: [717011962, 1534072173, 147532003, 804583167, 3147232238, 2547513183],
    2.5: [3303058579, 3934630378, 36756296, 3645992293, 535933823, 1012231441],
    0: [718263531, 106116617, 3991160471, 3974177571, 2146930047, 3958862447],
    -3: [3713416245, 1574104119, 2190894282, 925000860, 2051791913, 2819171584],
    4294967303: [3804330059, 2904172980, 1907180838, 439291944, 2011224319, 4068105737],
}
FLOATS_SEED_1000 = [0.3774137800506814, 0.8753900567245181, 0.7568582165420191,
                    0.6000252083409636]
NORMALS_SEED_1137 = [0.7441896534516672, 0.7223640589056195, 0.545424326892131,
                     0.8556936971937147]
FIELDS = {
    (256, 256, 4, 31337000): "943852f5e854523a8956e0fb9aa06ee45e808bcc964501cf22fb375e15051050",
    (64, 48, 3, 1251 * 31337): "e3e85b268b6fb235105d38024f862510db6958ba1982f68ec5d20e72de35d0e1",
    (37, 53, 2.5, 7): "731f32b1437f57c2b24b850011b8732c4eaff14d9e984c1be3aa63c12f07c3e6",
}
# (width, height, seed, density)
SMALL = (64, 48, 3, 0.7)
DEFAULT = (256, 256, 1, 0.5)
STREAMS = {
    ("filter.fibers", SMALL): (2904, "50dd768bf8942accd954441289c6437cba354211e5167168859c1d2116bd1bf7"),
    ("filter.fibers", DEFAULT): (24576, "e3cf59b5444e9aa53c6111270c6963d91cc0e34a4d6a9d638fa90e80c10128ef"),
    ("filter.scratches", SMALL): (1752, "97bbd53c7345869249c46e45e02ff29bd35760d33a60e0bbc098f63af462cf34"),
    ("filter.scratches", DEFAULT): (14592, "d582f87d7c8f96f2c3300c160a7ef2ba0e2f9329cf82a96815a664c6b82874a3"),
    ("filter.strayHair", SMALL): (69, "8dfde2ce89974a651ea6b4c2c1983970287974e8cc1f99f7bc2a9a7a33593d00"),
    ("filter.strayHair", DEFAULT): (160, "2cb3f416d75a92fe98a96be21d83550a68e9d737035fcf7996eaa63bc1453278"),
}
# Hairline overlays (lines at most 1 px wide), drawn exactly.
HAIRLINE_OVERLAYS = {
    ("filter.scratches", SMALL): "127d8eaa7f6251c207417576517e9ae8ed78c087fb29e94e729233e40472cc3a",
    ("filter.scratches", DEFAULT): "8c7ce9afcaef815f7bc745345f14706918573f179d341b797a0b78bec913150f",
    ("filter.strayHair", SMALL): "05b14825abe6c4cb36c2a19c44e3e34502ceed59d081f999fe48c2410583f3ba",
    ("filter.strayHair", DEFAULT): "651f767359ebb52192327d0d04cbea4a183ac65700b67f7a67d4e558ec9bd012",
}
# Wide-stroke overlays: Skia's analytic coverage is modelled, not ported.
# The model's alpha sum stays within 3 % of the Skia model's and its covered
# pixel count within 2 % (measured 2.1 % and 1.0 % at 256x256, 2.7 % and
# 0.9 % at 64x48).
WIDE_OVERLAYS = {
    ("filter.fibers", SMALL): (173441, 1743),
    ("filter.fibers", DEFAULT): (1510226, 14884),
}


class _RecordingCanvas:
    def __init__(self):
        self.line_width = 1.0
        self.style = None
        self.strokes = []

    def set_line_width(self, width):
        self.line_width = width

    def set_stroke_color(self, r, g, b, alpha):
        self.style = (r, g, b, alpha)

    def stroke_line(self, x0, y0, x1, y1):
        self.strokes.append((x0, y0, x1, y1, self.line_width) + self.style)


def _stream_digest(strokes):
    digest = hashlib.sha256()
    for x0, y0, x1, y1, lw, r, g, b, alpha in strokes:
        digest.update(struct.pack("<5f3Bd", x0, y0, x1, y1, lw, int(r), int(g), int(b), alpha))
    return digest.hexdigest()


def _record(effect_key, width, height, params):
    canvas = _RecordingCanvas()
    async_overlay._TRACERS[effect_key](canvas, width, height, params)
    return canvas.strokes


class WormTracerTests(unittest.TestCase):
    def test_rng_streams_match_the_reference(self):
        for seed, expected in RNG_STREAMS.items():
            rng = SeededRNG(seed)
            self.assertEqual(expected, [rng.next() for _ in expected], seed)

    def test_rng_floats_and_normals_match_the_reference(self):
        rng = SeededRNG(1000)
        self.assertEqual(FLOATS_SEED_1000, [rng.float() for _ in FLOATS_SEED_1000])
        rng = SeededRNG(1137)
        for expected in NORMALS_SEED_1137:
            self.assertAlmostEqual(expected, rng.normal(0.75, 0.125), delta=1e-14)

    def test_flow_fields_match_the_reference_bytes(self):
        for (width, height, freq, seed), expected in FIELDS.items():
            field = value_noise_field(width, height, freq, SeededRNG(seed))
            self.assertEqual(np.float32, field.dtype)
            self.assertEqual(expected, hashlib.sha256(field.tobytes()).hexdigest())

    def test_stroke_streams_match_the_reference(self):
        for (effect_key, (width, height, seed, density)), (count, digest) in STREAMS.items():
            strokes = _record(effect_key, width, height, {"seed": seed, "density": density})
            self.assertEqual(count, len(strokes), effect_key)
            self.assertEqual(digest, _stream_digest(strokes), (effect_key, width, height))


class OverlayTests(unittest.TestCase):
    def test_hairline_overlays_match_the_skia_model(self):
        for (effect_key, (width, height, seed, density)), expected in HAIRLINE_OVERLAYS.items():
            overlay = async_overlay.generate_overlay(effect_key, width, height,
                                                     {"seed": seed, "density": density})
            self.assertEqual((height, width, 4), overlay.shape)
            self.assertEqual(np.uint8, overlay.dtype)
            self.assertEqual(expected, hashlib.sha256(overlay.tobytes()).hexdigest(),
                             (effect_key, width, height))

    def test_wide_stroke_overlays_stay_near_the_skia_model(self):
        for (effect_key, (width, height, seed, density)), (alpha_sum, covered) in WIDE_OVERLAYS.items():
            overlay = async_overlay.generate_overlay(effect_key, width, height,
                                                     {"seed": seed, "density": density})
            alpha = overlay[..., 3].astype(np.int64)
            self.assertLess(abs(alpha.sum() / alpha_sum - 1.0), 0.03, effect_key)
            self.assertLess(abs((alpha > 0).sum() / covered - 1.0), 0.02, effect_key)
            self.assertGreater(len(np.unique(overlay.reshape(-1, 4), axis=0)), 1000)

    def test_overlay_row_zero_is_the_canvas_top(self):
        canvas = StrokeCanvas(16, 8)
        canvas.set_line_width(1.5)
        canvas.set_stroke_color(255, 255, 255, 1.0)
        canvas.stroke_line(3.0, 1.5, 12.0, 1.5)
        rows = np.nonzero(canvas.unpremultiplied_rgba8()[..., 3].max(axis=1))[0]
        self.assertEqual([0, 1, 2], rows.tolist())

    def test_overlay_params_follow_the_reference_asyncinit(self):
        for name in ("fibers", "scratches", "strayHair"):
            key = "filter." + name
            spec = json.loads((EFFECTS / (name + ".json")).read_text())["globals"]
            defaults = {"seed": spec["seed"]["default"], "density": spec["density"]["default"]}
            self.assertTrue(async_overlay.has_async_overlay(key))
            self.assertEqual(defaults, async_overlay.overlay_params(key, {}))
            automated = {"type": "oscillator", "min": 0, "max": 1}
            self.assertEqual(defaults, async_overlay.overlay_params(
                key, {"seed": automated, "density": [0.2, 0.3], "alpha": 0.1}))
            self.assertEqual({"seed": 7, "density": 0.25},
                             async_overlay.overlay_params(key, {"seed": 7, "density": 0.25}))
        self.assertFalse(async_overlay.has_async_overlay("filter.adjust"))
        # `params.seed || 1`: a zero seed draws as seed 1.
        self.assertEqual(_record("filter.strayHair", 64, 48, {"seed": 1, "density": 0.5}),
                         _record("filter.strayHair", 64, 48, {"seed": 0, "density": 0.5}))

    def test_step_uniforms_restore_graph_automation(self):
        automated = {"type": "oscillator", "min": 1, "max": 9}
        raw = {"id": "node_1_pass_0", "uniforms": {"seed": automated, "density": 0.4}}
        executed = {"id": "node_1_pass_0", "uniforms": {"seed": 4.2, "density": 0.4}}
        other = {"id": "node_0_pass_0", "uniforms": {"seed": automated}}
        self.assertEqual({"seed": automated, "density": 0.4},
                         async_overlay.step_uniforms(executed, [other, raw]))
        self.assertEqual({"seed": 3, "density": 0.4}, async_overlay.step_uniforms(
            {"id": "node_1_pass_0", "uniforms": {"seed": 3, "density": 0.4}}, None))


class StrokeCanvasTests(unittest.TestCase):
    STROKES = [
        (1.0, (200, 40, 10, 0.5), (2.3, 3.1, 9.7, 5.2)),
        (0.5, (255, 255, 255, 1.0), (1.0, 8.0, 14.0, 2.0)),
        (1.5, (30, 90, 255, 0.8), (8.2, 1.4, 8.4, 1.6)),
        (2.5, (0, 0, 0, 1.0), (5.0, 5.0, 6.0, 7.0)),
        (1.5, (255, 255, 255, 1.0), (-1.0, 4.0, 3.0, 4.5)),
        (1.0, (10, 200, 100, 0.25), (15.5, 0.2, 13.0, 9.6)),
        (2.0, (90, 90, 90, 0.4), (4.0, 9.0, 4.0, 9.0)),
    ]

    def _draw(self, drain_each):
        canvas = StrokeCanvas(16, 10)
        for width, color, line in self.STROKES:
            canvas.set_line_width(width)
            canvas.set_stroke_color(*color)
            canvas.stroke_line(*line)
            if drain_each:
                canvas._drain()
        return canvas.premultiplied()

    def test_queued_strokes_draw_in_order(self):
        np.testing.assert_array_equal(self._draw(True), self._draw(False))
        self.assertGreater(int((self._draw(False)[..., 3] > 0).sum()), 40)

    def test_invalid_input_keeps_the_canvas_state(self):
        canvas = StrokeCanvas(8, 8)
        canvas.set_line_width(1.0)
        canvas.set_stroke_color(255, 0, 0, 1.0)
        canvas.set_stroke_color(0, math.nan, 0, 1.0)   # invalid style: kept
        canvas.set_line_width(-2.0)                     # ignored
        canvas.set_line_width(math.inf)                 # ignored
        canvas.stroke_line(1.0, 1.0, math.nan, 4.0)     # nothing drawn
        canvas.stroke_line(2.0, 2.0, 2.0, 2.0)          # coincident: pruned
        canvas.stroke_line(-9.0, -9.0, -5.0, -5.0)      # off the canvas: culled
        self.assertEqual(0, int(canvas.premultiplied().any(axis=-1).sum()))
        canvas.stroke_line(1.0, 4.0, 6.0, 4.0)
        pixels = canvas.unpremultiplied_rgba8()
        lit = pixels[pixels[..., 3] > 0]
        self.assertTrue((lit[:, 0] == 255).all() and (lit[:, 1:3] == 0).all())


if __name__ == "__main__":
    unittest.main()

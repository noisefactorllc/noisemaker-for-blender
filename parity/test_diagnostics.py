#!/usr/bin/env python3
"""Regression tests for structured runtime diagnostics (reference
commits dd4606ea / a0e9bbff lineage, ported 2026-10 sync round).

Ported from reference `shaders/tests/test_backend_diagnostics.js` case shapes,
adapted to the port's single Blender backend (the webgl2/webgpu compile, link,
uniform-block, missing-render-target, GL-error and uncapturederror union
members have no analogue here — Blender's `gpu.types.GPUShader` raises on
compile error and exposes no info log, which test_backend_contract.py's
gpu.types probe asserts). The engine-independent members are covered:

  - DiagnosticCollector: add-returns-record, 64-cap shift, clear;
  - resolve_dimension: 'input'/'resolution' are validator-accepted keywords
    resolving to the screen dimension with NO diagnostic; unknown string and
    object forms keep the historical screen-size fallback and record one
    deduplicated ERR_DIMENSION_FALLBACK per distinct form; absent specs add
    none;
  - resolve_surface_format: unknown formats keep the historical rgba16f
    fallback and record one deduplicated ERR_UNKNOWN_FORMAT_FALLBACK; known
    formats and an absent format add none.

Red-before holds against base 93133eb: `resolve_dimension` had no
diagnostics/warned kwargs and `resolve_surface_format` did not exist.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.runtime.diagnostics import DiagnosticCollector  # noqa: E402
from noisemaker_blender.runtime.pipeline import (  # noqa: E402
    resolve_dimension,
    resolve_surface_format,
)


class TestDiagnosticCollector(unittest.TestCase):
    def test_add_returns_the_record(self):
        c = DiagnosticCollector()
        record = {"code": "ERR_DIMENSION_FALLBACK", "stage": "dimension"}
        self.assertIs(c.add(record), record)
        self.assertEqual(c.records, [record])

    def test_cap_keeps_the_latest_64_records(self):
        c = DiagnosticCollector()
        for i in range(65):
            c.add({"i": i})
        self.assertEqual(len(c.records), 64)
        self.assertEqual([r["i"] for r in c.records], list(range(1, 65)))

    def test_clear_empties_the_records(self):
        c = DiagnosticCollector()
        c.add({"i": 0})
        c.clear()
        self.assertEqual(c.records, [])


class TestDimensionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.collector = DiagnosticCollector()
        self.warned = set()

    def resolve(self, spec, screen=256):
        return resolve_dimension(spec, screen, diagnostics=self.collector,
                                 warned=self.warned)

    def test_validator_accepted_keywords_resolve_to_screen_without_diagnostic(self):
        for spec in ("screen", "auto", "input", "resolution"):
            self.assertEqual(self.resolve(spec, 256), 256)
        self.assertEqual(self.collector.records, [])

    def test_numeric_and_absent_specs_add_no_diagnostic(self):
        self.assertEqual(self.resolve(128), 128)
        self.assertEqual(self.resolve("50%"), 128)
        self.assertEqual(self.resolve(None), 256)
        self.assertEqual(self.collector.records, [])

    def test_unknown_string_form_keeps_the_screen_fallback_and_records_once(self):
        self.assertEqual(self.resolve("zoom"), 256)
        self.assertEqual(self.resolve("zoom"), 256)  # deduplicated
        self.assertEqual(self.resolve("banana"), 256)
        self.assertEqual(len(self.collector.records), 2,
                         "each distinct unknown form is recorded once")
        record = self.collector.records[0]
        self.assertEqual(record["code"], "ERR_DIMENSION_FALLBACK")
        self.assertEqual(record["backend"], "blender")
        self.assertEqual(record["stage"], "dimension")
        self.assertEqual(record["spec"], "zoom")
        self.assertEqual(record["fallback"], "screen")

    def test_unknown_object_form_records_the_serialized_spec(self):
        self.assertEqual(self.resolve({"wat": 1}), 256)
        self.assertEqual(len(self.collector.records), 1)
        self.assertEqual(self.collector.records[0]["spec"], '{"wat": 1}')

    def test_known_object_forms_add_no_diagnostic(self):
        self.assertEqual(self.resolve({"param": "n", "default": 64}), 64)
        self.assertEqual(self.resolve({"screenDivide": "n"}), 256,
                         "no uniforms below: the default divider 1 applies")
        self.assertEqual(resolve_dimension({"screenDivide": "n"}, 256, {"n": 2}), 128)
        self.assertEqual(self.resolve({"scale": 0.5}), 128)
        self.assertEqual(self.collector.records, [])

    def test_without_a_collector_the_fallback_stays_silent(self):
        self.assertEqual(resolve_dimension("zoom", 256), 256)


class TestFormatDiagnostics(unittest.TestCase):
    def setUp(self):
        self.collector = DiagnosticCollector()
        self.warned = set()

    def fmt(self, spec):
        return resolve_surface_format(spec, diagnostics=self.collector,
                                      warned=self.warned)

    def test_known_formats_resolve_without_diagnostic(self):
        self.assertEqual(self.fmt({"format": "rgba8"}), "RGBA8")
        self.assertEqual(self.fmt({"format": "RGBA16F"}), "RGBA16F")
        self.assertEqual(self.fmt({"format": "rgba32f"}), "RGBA32F")
        self.assertEqual(self.collector.records, [])

    def test_webgpu_spellings_resolve_to_the_same_formats(self):
        # The reference WebGL2 backend resolves the WebGPU spellings the
        # definition validator accepts (filter/bloom declares rgba16float,
        # points/buddhabrot rgba32float, the blur family rgba8unorm).
        self.assertEqual(self.fmt({"format": "rgba8unorm"}), "RGBA8")
        self.assertEqual(self.fmt({"format": "rgba16float"}), "RGBA16F")
        self.assertEqual(self.fmt({"format": "rgba32float"}), "RGBA32F")
        self.assertEqual(self.collector.records, [])

    def test_absent_format_is_the_default_not_a_fallback(self):
        self.assertEqual(self.fmt({}), "RGBA16F")
        self.assertEqual(self.collector.records, [])

    def test_unknown_format_keeps_the_rgba16f_fallback_and_records_once(self):
        self.assertEqual(self.fmt({"format": "banana"}), "RGBA16F")
        self.assertEqual(self.fmt({"format": "banana"}), "RGBA16F")  # deduplicated
        self.assertEqual(len(self.collector.records), 1)
        record = self.collector.records[0]
        self.assertEqual(record["code"], "ERR_UNKNOWN_FORMAT_FALLBACK")
        self.assertEqual(record["backend"], "blender")
        self.assertEqual(record["stage"], "texture-create")
        self.assertEqual(record["format"], "banana")
        self.assertEqual(record["fallback"], "rgba16f")

    def test_without_a_collector_the_fallback_stays_silent(self):
        self.assertEqual(resolve_surface_format({"format": "banana"}), "RGBA16F")


if __name__ == "__main__":
    unittest.main()

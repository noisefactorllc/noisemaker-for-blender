#!/usr/bin/env python3
"""Regression tests for effect preflight (reference commit 12b4d74fb4f2).

Ported from reference `shaders/tests/test_preflight.js`, adapted to the port's
single Blender backend (the reference's webgl2/webgpu pair has no analogue
here; the port's authorability is "the backend's compile step finds a source").

`preflight_effect(definition, capabilities, shaders)` statically reports,
before any pipeline initialization or compilation:
  1. authorability — a program whose shader bucket carries no source makes the
     port's backend not authorable;
  2. how device limits change formats — MRT attachments exceeding
     maxColorBytesPerSample are predicted to be demoted from rgba32f to
     rgba16f (sharing `mrt_format_bytes` with the reference budget table), and
     texture dimensions past maxTextureSize are reported as clamps;
  3. MRT passes writing more color attachments than maxDrawBuffers make the
     backend not renderable;
  plus, port-side, `volumeClamps` — the volumeSize clamps the pipeline init
  actually applies, predicted through the runtime's own clamp function.

Without shader information the source checks are skipped (unknown), so
preflight stays a structural/limit report — it never fabricates a verdict.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.runtime.preflight import (  # noqa: E402
    mrt_format_bytes,
    preflight_effect,
)
from noisemaker_blender.runtime.pipeline import (  # noqa: E402
    _clamp_graph_volume_sizes,
    _predict_volume_clamps,
    preflight,
)


class _Graph:
    """Minimal graph stand-in (Graph-shaped: passes list + textures dict)."""

    def __init__(self, passes, textures=None):
        self.passes = passes
        self.textures = textures or {}


class _StubBackend:
    def __init__(self, capabilities=None, shaders_root=None):
        self.capabilities = capabilities
        self.shaders_root = shaders_root
        self.size = 256

    def max_texture_size(self):
        caps = self.capabilities or {}
        return caps.get("maxTextureSize")

    def setup(self, graph, uniforms):
        pass


class PreflightTests(unittest.TestCase):
    def test_program_with_source_is_authorable(self):
        report = preflight_effect(
            {"passes": [{"name": "draw", "program": "p"}]},
            {},
            {"p": {"frag": "void main() {}"}},
        )
        self.assertTrue(report["backends"]["blender"]["authorable"], "blender")
        self.assertEqual(report["backends"]["blender"]["reasons"], [])

    def test_program_without_source_is_not_authorable(self):
        report = preflight_effect(
            {"passes": [{"name": "draw", "program": "p"}]},
            {},
            {"p": {}},
        )
        self.assertFalse(report["backends"]["blender"]["authorable"])
        self.assertEqual(len(report["backends"]["blender"]["reasons"]), 1)
        self.assertIn("p", report["backends"]["blender"]["reasons"][0])
        self.assertIn("draw", report["backends"]["blender"]["reasons"][0])

    def test_reference_glsl_bucket_shapes_count_as_authored(self):
        # The port accepts reference-shaped buckets (a glsl or fragment
        # source) so a definition carried over from the reference engine is
        # judged by the same field family its compile step consumes.
        for bucket in (
            {"glsl": "void main() {}"},
            {"fragment": "void main() {}"},
            {"vertex": "void main() {}", "fragment": "void main() {}"},
        ):
            report = preflight_effect(
                {"passes": [{"program": "p"}]}, {}, {"p": dict(bucket)}
            )
            self.assertTrue(report["backends"]["blender"]["authorable"], str(bucket))

    def test_a_vertex_shader_alone_is_not_a_program_source(self):
        # The backend compiles a fragment program; the reference WebGL2
        # compileProgram() likewise reads source, then glsl, then fragment.
        report = preflight_effect(
            {"passes": [{"program": "p"}]}, {},
            {"p": {"vertex": "#version 300 es\nvoid main() {}", "wgsl": "@fragment fn f() {}"}},
        )
        self.assertFalse(report["backends"]["blender"]["authorable"])

    def test_generic_source_is_judged_by_its_language(self):
        # A GLSL generic source beside WGSL is authorable; a WGSL generic
        # source is not, even beside a GLSL fragment (source is selected first).
        report = preflight_effect(
            {"passes": [{"program": "p"}]}, {},
            {"p": {"source": "#version 300 es\nvoid main() {}", "wgsl": "@fragment fn f() {}"}},
        )
        self.assertTrue(report["backends"]["blender"]["authorable"])
        report = preflight_effect(
            {"passes": [{"program": "p"}]}, {},
            {"p": {"source": "@fragment fn f() {}", "fragment": "#version 300 es\nvoid main() {}"}},
        )
        self.assertFalse(report["backends"]["blender"]["authorable"])

    def test_without_shader_info_source_availability_is_not_judged(self):
        report = preflight_effect({"passes": [{"program": "p"}]}, {})
        self.assertTrue(report["backends"]["blender"]["authorable"])
        self.assertEqual(report["backends"]["blender"]["reasons"], [])

    def test_mrt_outputs_past_max_draw_buffers_make_backend_not_renderable(self):
        report = preflight_effect(
            {"passes": [{"program": "p", "outputs": {"a": "t1", "b": "t2", "c": "t3"}}]},
            {"maxDrawBuffers": 2},
        )
        self.assertFalse(report["backends"]["blender"]["authorable"])
        self.assertIn("3 color attachments", report["backends"]["blender"]["reasons"][0])

    def test_over_budget_mrt_predicts_the_trailing_rgba32f_demotion(self):
        textures = {
            "xyz": {"format": "rgba32f"},
            "vel": {"format": "rgba32f"},
            "rgba": {"format": "rgba8"},
        }
        report = preflight_effect(
            {
                "passes": [{
                    "name": "emit",
                    "program": "p",
                    "outputs": {"pos": "xyz", "vel": "vel", "col": "rgba"},
                }],
                "textures": textures,
            },
            {"maxColorBytesPerSample": 32},
        )
        self.assertEqual(report["formatChanges"], [{
            "texture": "vel",
            "pass": "emit",
            "from": "rgba32f",
            "to": "rgba16f",
            "budget": 32,
        }])
        # The budget table the prediction shares with the reference runtime.
        self.assertEqual(mrt_format_bytes("rgba32f"), 16)
        self.assertEqual(mrt_format_bytes("rgba16f"), 8)
        self.assertEqual(mrt_format_bytes("rgba8"), 4)
        self.assertEqual(mrt_format_bytes(None), 8)
        # Single-channel formats cost their own size, in both spellings.
        for formats, size in ((("r32f", "r32float"), 4), (("r16f", "r16float"), 2), (("r8", "r8unorm"), 1)):
            for fmt in formats:
                self.assertEqual(mrt_format_bytes(fmt), size, fmt)

    def test_within_budget_mrt_predicts_no_format_changes(self):
        report = preflight_effect(
            {
                "passes": [{"program": "p", "outputs": {"a": "t1", "b": "t2"}}],
                "textures": {"t1": {"format": "rgba32f"}, "t2": {"format": "rgba16f"}},
            },
            {"maxColorBytesPerSample": 32},
        )
        self.assertEqual(report["formatChanges"], [])

    def test_without_a_budget_capability_no_demotion_is_predicted(self):
        # The port's Blender runtime applies no MRT byte budget; omitted
        # capabilities are simply not checked (reference contract).
        report = preflight_effect(
            {
                "passes": [{"program": "p", "outputs": {"a": "t1", "b": "t2"}}],
                "textures": {"t1": {"format": "rgba32f"}, "t2": {"format": "rgba32f"}},
            },
            {},
        )
        self.assertEqual(report["formatChanges"], [])

    def test_dimensions_past_max_texture_size_are_reported_as_clamps(self):
        report = preflight_effect({"passes": []}, {"maxTextureSize": 4096}, None)
        self.assertEqual(report["clamps"], [])
        report2 = preflight_effect(
            {
                "passes": [],
                "textures": {
                    "big": {"width": 8192, "height": 4096},
                    "ok": {"width": 1024, "height": 1024},
                    "vol": {"width": 8192, "height": 8192, "depth": 8192, "is3D": True},
                },
            },
            {"maxTextureSize": 4096},
        )
        self.assertEqual(report2["clamps"], [
            {"texture": "big", "field": "width", "requested": 8192, "limit": 4096},
            {"texture": "vol", "field": "width", "requested": 8192, "limit": 4096},
            {"texture": "vol", "field": "height", "requested": 8192, "limit": 4096},
            {"texture": "vol", "field": "depth", "requested": 8192, "limit": 4096},
        ])

    def test_preflight_never_mutates_the_definition(self):
        definition = {
            "passes": [{"program": "p", "outputs": {"a": "t1", "b": "t2"}}],
            "textures": {"t1": {"format": "rgba32f"}, "t2": {"format": "rgba32f"}},
        }
        snapshot = json.dumps(definition)
        preflight_effect(definition, {"maxColorBytesPerSample": 32}, {})
        self.assertEqual(json.dumps(definition), snapshot, "definition unchanged")

    def test_malformed_input_is_reported_not_thrown(self):
        for bad in (None, 42, "x"):
            report = preflight_effect(bad, {})
            self.assertEqual(report["formatChanges"], [])
            self.assertEqual(report["clamps"], [])
            self.assertTrue(report["backends"]["blender"]["authorable"])


class PipelinePreflightTests(unittest.TestCase):
    def test_source_availability_judged_against_the_backend_compile_path(self):
        root = Path(tempfile.mkdtemp())
        try:
            present = root / "filter" / "adjust" / "adjust.frag"
            present.parent.mkdir(parents=True)
            present.write_text("void main() {}\n")
            graph = _Graph([
                {"name": "have", "program": "haveProgram",
                 "namespace": "filter", "func": "adjust", "progName": "adjust"},
                {"name": "lack", "program": "lackProgram",
                 "namespace": "filter", "func": "missing", "progName": "missing"},
                {"name": "blit", "program": "blitProgram",
                 "namespace": None, "func": "blit", "passType": "blit"},
            ])
            backend = _StubBackend(shaders_root=str(root))
            report = preflight(backend, graph)
            self.assertTrue(report["backends"]["blender"]["authorable"] is False)
            reasons = report["backends"]["blender"]["reasons"]
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn("lackProgram", reasons[0])
            self.assertIn("lack", reasons[0])
        finally:
            shutil.rmtree(root)

    def test_lockstep_volume_clamps_match_the_runtime(self):
        graph = _Graph([{
            "name": "sim",
            "program": "p",
            "uniforms": {"volumeSize": 128, "volumeSize_chain_2": 64, "scaleX": 50},
        }])
        backend = _StubBackend({"maxTextureSize": 8192})
        predicted = preflight(backend, graph)["volumeClamps"]
        self.assertEqual(predicted, [{
            "pass": "sim",
            "uniform": "volumeSize",
            "requested": 128,
            "clamped": 64,
            "limit": 8192,
        }])
        # Runtime must agree: FrameStepper.__init__ actually applies the same
        # clamp through the shared function.
        _clamp_graph_volume_sizes(graph, 8192)
        self.assertEqual(graph.passes[0]["uniforms"]["volumeSize"], 64)
        self.assertEqual(graph.passes[0]["uniforms"]["volumeSize_chain_2"], 64)

    def test_preflight_does_not_mutate_the_graph(self):
        graph = _Graph([{
            "name": "sim",
            "program": "p",
            "uniforms": {"volumeSize": 128},
        }])
        snapshot = json.dumps(graph.passes)
        preflight(_StubBackend({"maxTextureSize": 8192}), graph)
        self.assertEqual(json.dumps(graph.passes), snapshot)

    def test_port_backend_supplies_no_byte_budget(self):
        # No maxColorBytesPerSample exists on the Blender backend, so the
        # pipeline-level report predicts no demotions.
        graph = _Graph(
            [{"name": "mrt", "program": "p",
              "namespace": "filter", "func": "adjust", "progName": "adjust",
              "outputs": {"a": "t1", "b": "t2"}}],
            {"t1": {"format": "rgba32f"}, "t2": {"format": "rgba32f"}},
        )
        root = Path(tempfile.mkdtemp())
        try:
            frag = root / "filter" / "adjust" / "adjust.frag"
            frag.parent.mkdir(parents=True)
            frag.write_text("void main() {}\n")
            backend = _StubBackend({"maxTextureSize": 8192}, shaders_root=str(root))
            report = preflight(backend, graph)
            self.assertEqual(report["formatChanges"], [])
            self.assertTrue(report["backends"]["blender"]["authorable"])
        finally:
            shutil.rmtree(root)

    def test_predict_volume_clamps_helper_is_read_only(self):
        graph = _Graph([{"name": "sim", "program": "p", "uniforms": {"volumeSize": 128}}])
        snapshot = json.dumps(graph.passes)
        clamps = _predict_volume_clamps(graph, 8192)
        self.assertEqual(len(clamps), 1)
        self.assertEqual(json.dumps(graph.passes), snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)

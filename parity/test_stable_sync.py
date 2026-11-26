"""Stable compiler and frame-clock contracts from the reference boundary."""

import ast
import builtins
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import compile, compile_graph, expand
from noisemaker_blender.compiler import expander
from noisemaker_blender.compiler.compiler import extract_texture_specs, _normalize_pass
from noisemaker_blender.compiler import ops
from noisemaker_blender.runtime import pipeline


class ElementIdTests(unittest.TestCase):
    def test_ids_survive_validation_without_becoming_uniforms(self):
        source = '''search synth, filter, synth3d
noise(_id: "pond").invert(_id: "flip").write(o1, _id: "out")
read(surface: o1, _id: "again").write(o0)
noise3d().write3d(vol0, geo0, _id: "volume")
read3d(tex3d: vol0, geo: geo0, _id: "readVolume").write(o2)
render(o0)
'''
        result = compile(source)
        self.assertEqual(result["diagnostics"], [])
        steps = [step for plan in result["plans"] for step in plan["chain"]]
        self.assertEqual(
            [(s["op"], s["args"]["_id"]) for s in steps if "_id" in s["args"]],
            [("synth.noise", "pond"), ("filter.invert", "flip"), ("_write", "out"),
             ("_read", "again"), ("_write3d", "volume"), ("_read3d", "readVolume")],
        )
        for render_pass in compile_graph(source)["passes"]:
            self.assertNotIn("_id", render_pass.get("uniforms", {}))

    def test_invalid_or_variable_ids_are_ignored(self):
        for value in ['5', '"9a"', '"a-b"', '""', 'pond', '"_a"']:
            with self.subTest(value=value):
                result = compile(f'search synth\nlet pond = "valid"\nnoise(_id: {value}).write(o0, _id: 7)\nrender(o0)')
                self.assertEqual(result["diagnostics"], [])
                for plan in result["plans"]:
                    for step in plan["chain"]:
                        self.assertNotIn("_id", step["args"])


class StoredColorTests(unittest.TestCase):
    def setUp(self):
        ops.ops()
        patcher = mock.patch.dict(ops._OPS, {"synth.rgbprobe": {
            "name": "synth.rgbprobe",
            "args": [{"name": k, "type": "float", "default": 0} for k in ("r", "g", "b")],
        }})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stored_color_preserves_components_with_keyword_overrides(self):
        for declaration, invocation, expected in [
            ('let tint = rgbprobe(#804020)', 'tint(g: 0.75)', [128 / 255, 0.75, 32 / 255]),
            ('let tint = rgbprobe(#804020)', 'tint(r: 0.75)', [0.75, 64 / 255, 32 / 255]),
            ('let tint = rgbprobe(#804020)\nlet next = tint(g: 0.75)', 'next(b: 0.5)', [128 / 255, 0.75, 0.5]),
            ('let tint = rgbprobe(r: 0.75)', 'tint(#804020)', [0.75, 0, 0]),
            ('let tint = rgbprobe(_id: "color")', 'tint(#804020)', [128 / 255, 64 / 255, 32 / 255]),
        ]:
            with self.subTest(declaration=declaration, invocation=invocation):
                result = compile(f'search synth\n{declaration}\nnoise().{invocation}.write(o0)\nrender(o0)')
                self.assertEqual(result["diagnostics"], [])
                args = result["plans"][0]["chain"][1]["args"]
                self.assertEqual([args[k] for k in ("r", "g", "b")], expected)

    def test_read_chain_argument_reports_the_value_location(self):
        source = 'search synth, filter, mixer\nnoise().write(o1)\nnoise().blendMode(tex: read(o1).invert()).write(o0)\nrender(o0)'
        result = compile(source)
        self.assertEqual(len(result["diagnostics"]), 1)
        error = result["diagnostics"][0]
        self.assertEqual(error["code"], "S001")
        self.assertEqual(error["location"], {"line": 3, "column": 24})
        self.assertIn("may contain only effect calls", error["message"])


class StorageTextureTests(unittest.TestCase):
    def test_empty_render_outputs_fall_back_to_storage_bindings(self):
        for outputs in ({}, None):
            with self.subTest(outputs=outputs):
                result = _normalize_pass({"outputs": outputs, "storageTextures": {"state": "global_o0"}}, {}, {})
                self.assertEqual(result["outputs"], {"state": "global_o0"})

    def test_storage_only_outputs_are_allocated_and_effect_usage_is_preserved(self):
        result = extract_texture_specs(
            [{"storageTextures": {"state": "node_0_state", "global": "global_vol0"}}], {},
            {"node_1_state": {"width": 12, "height": 13, "usage": ["storage", "sample"]}},
        )
        self.assertEqual(result["node_1_state"]["usage"], ["storage", "sample"])
        self.assertEqual(result["node_0_state"]["usage"], ["render", "sample", "storage", "copySrc", "copyDst"])
        self.assertNotIn("global_vol0", result)

    def test_null_usage_uses_defaults_and_empty_usage_is_preserved(self):
        for usage, expected in [(None, ["render", "sample", "copySrc", "copyDst"]), ([], [])]:
            with self.subTest(usage=usage):
                result = extract_texture_specs([], {}, {"work": {"usage": usage}})
                self.assertEqual(result["work"]["usage"], expected)

    def test_null_storage_usage_uses_defaults(self):
        definition = {"namespace": "synth", "func": "storageProbe", "globals": {},
                      "passes": [{"program": "fill", "type": "compute",
                                  "storageTextures": {"outputBuffer": "work"}}],
                      "textures": {"work": {"usage": None}}}
        plan = {"render": "o0", "plans": [{"chain": [{"op": "synth.storageProbe", "temp": 0, "args": {}}]}]}
        with mock.patch.object(expander, "get_effect", return_value=definition):
            result = expand(plan)
        self.assertEqual(result["textureSpecs"]["node_0_work"]["usage"], ["render", "sample", "copySrc", "copyDst", "storage"])

    def test_storage_targets_share_the_virtual_texture_namespace(self):
        for target in ("work", "outputTex", "global_vol0"):
            with self.subTest(target=target):
                definition = {"namespace": "synth", "func": "storageProbe", "globals": {},
                              "passes": [{"program": "fill", "type": "compute",
                                          "storageTextures": {"outputBuffer": target}}],
                              "textures": {"work": {"width": 12, "height": 13}}}
                plan = {"render": "o0", "plans": [{"chain": [{"op": "synth.storageProbe", "temp": 0, "args": {}}]}]}
                with mock.patch.object(expander, "get_effect", return_value=definition):
                    result = expand(plan)
                self.assertEqual(result["errors"], [])
                render_pass = result["passes"][0]
                expected = {"work": "node_0_work", "outputTex": "node_0_out", "global_vol0": "global_vol0_chain_0"}[target]
                self.assertEqual(render_pass["storageTextures"], {"outputBuffer": expected})
                self.assertNotIn("outputs", render_pass)
                if target == "work":
                    self.assertIn("storage", result["textureSpecs"][expected]["usage"])


class FrameClockTests(unittest.TestCase):
    def test_first_zero_frame_and_wrapped_delta(self):
        class Graph:
            passes = []
            render_surface = "o0"

        backend = mock.Mock(size=8)
        for start, expected in [(0.0, [0.0, 0.1, 0.1]), (0.95, [0.0, 0.1, 0.1])]:
            with self.subTest(start=start), mock.patch.object(pipeline, "default_engine", wraps=pipeline.default_engine) as engine:
                stepper = pipeline.FrameStepper(backend, Graph(), time=start, frames=3, timestep=0.1)
                while stepper.step():
                    pass
                self.assertEqual(engine.call_count, 3)
                for call, dt in zip(engine.call_args_list, expected):
                    self.assertAlmostEqual(call.args[3], dt)


class BlendFactorTests(unittest.TestCase):
    def test_overwrite_pair_keeps_zero_destination_contribution(self):
        # Load the pure selector without importing Blender's native GPU module.
        source = Path(__file__).resolve().parents[1] / "blender/noisemaker_blender/backend/gpu_backend.py"
        tree = ast.parse(source.read_text())
        backend = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GpuBackend")
        selector = next(node for node in backend.body if isinstance(node, ast.FunctionDef) and node.name == "_blend_mode")
        selector.decorator_list = []
        namespace = {}
        exec(builtins.compile(ast.Module(body=[selector], type_ignores=[]), str(source), "exec"), namespace)
        mode = namespace["_blend_mode"]
        for pair in (["ONE", "ZERO"], ["one", "zero"], ["ONE", "zero"]):
            with self.subTest(pair=pair):
                self.assertEqual(mode({"blend": pair}), "NONE")
        self.assertEqual(mode({"blend": ["ONE", "ONE"]}), "ADDITIVE_PREMULT")
        self.assertEqual(mode({"blend": ["ONE", "ONE_MINUS_SRC_ALPHA"]}), "ALPHA_PREMULT")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Compiler parity tests for DSL compilation and graph generation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import (  # noqa: E402
    CompilationError,
    compile,
    compile_graph,
)


class CompilerTests(unittest.TestCase):
    def test_chained_variable_alias_syntax(self):
        dsl = (
            "search synth, filter\n"
            "let eff = rotate(1, 0.1)\n"
            "noise().eff().write(o0)\n"
            "render(o0)"
        )
        result = compile(dsl)
        self.assertEqual(result.get("diagnostics", []), [])
        self.assertIn("plans", result)
        plan = result["plans"][0]
        self.assertEqual(len(plan["chain"]), 3)
        self.assertEqual(plan["chain"][0]["op"], "synth.noise")
        self.assertEqual(plan["chain"][1]["op"], "filter.rotate")
        self.assertEqual(plan["chain"][2]["op"], "_write")

    def test_multiple_chained_variable_aliases(self):
        dsl = (
            "search synth, filter\n"
            "let gen = noise(scaleX: 50)\n"
            "let eff = rotate(1, 0.1)\n"
            "gen().eff().write(o0)\n"
            "render(o0)"
        )
        result = compile(dsl)
        self.assertEqual(result.get("diagnostics", []), [])
        self.assertIn("plans", result)
        plan = result["plans"][0]
        self.assertEqual(len(plan["chain"]), 3)
        self.assertEqual(plan["chain"][0]["op"], "synth.noise")
        self.assertEqual(plan["chain"][1]["op"], "filter.rotate")
        self.assertEqual(plan["chain"][2]["op"], "_write")

    def test_chained_variable_compiles_valid_graph_with_terminal_write(self):
        dsl = (
            "search synth, filter\n"
            "let eff = rotate(1, 0.1)\n"
            "noise().eff().write(o0)\n"
            "render(o0)"
        )
        graph = compile_graph(dsl)
        self.assertEqual(graph["renderSurface"], "o0")
        self.assertEqual(len(graph["passes"]), 3)
        pass_ids = [p["id"] for p in graph["passes"]]
        self.assertEqual(pass_ids, ["node_0_pass_0", "node_1_pass_0", "node_2_write_blit"])

        self.assertIn("blit", graph["programs"])
        for prog_id, program in graph["programs"].items():
            self.assertIn("uniformLayout", program, f"Program {prog_id} missing uniformLayout")
            self.assertIn("defines", program, f"Program {prog_id} missing defines")

        self.assertEqual(graph["passes"][0]["defines"], {"LOOP_OFFSET": 300, "NOISE_TYPE": 10})
        self.assertEqual(graph["passes"][1]["uniforms"]["rotation"], 1)
        self.assertEqual(graph["passes"][1]["inputs"]["inputTex"], "node_0_out")
        self.assertEqual(graph["passes"][2]["inputs"]["src"], "node_1_out")
        self.assertEqual(graph["passes"][2]["outputs"]["color"], "global_o0")

    def test_compilation_failure_raises_compilation_error(self):
        with self.assertRaises(CompilationError) as ctx:
            compile_graph("search synth\nunknown_effect().write(o0)\nrender(o0)")
        self.assertEqual(ctx.exception.code, "ERR_COMPILATION_FAILED")
        self.assertTrue(any(d.get("code") == "S001" for d in ctx.exception.diagnostics))

    def test_compiler_rejects_output_surfaces_outside_o0_to_o7(self):
        cases = [
            ("render target", "search synth\nnoise().write(o0)\nrender(o8)", "o8"),
            ("read source", "search synth\nread(o99).write(o0)\nrender(o0)", "o99"),
            ("write target", "search synth\nnoise().write(o10)\nrender(o0)", "o10"),
        ]
        for name, dsl, ref in cases:
            with self.subTest(name=name):
                with self.assertRaises(SyntaxError) as ctx:
                    compile(dsl)
                self.assertIn(
                    f"Output surface reference '{ref}' is out of range; expected o0-o7",
                    str(ctx.exception),
                )

    def test_compiler_preserves_o0_and_o7_boundary_behavior(self):
        dsl = "search synth\nread(o0).write(o7)\nrender(o7)"
        result = compile(dsl)
        self.assertEqual(
            result["plans"][0]["chain"][0]["args"]["tex"],
            {"kind": "output", "name": "o0"},
        )
        self.assertEqual(result["plans"][0]["write"], {"kind": "output", "name": "o7"})
        self.assertEqual(result["render"], "o7")

    def test_output_shaped_member_segments_and_other_reference_families(self):
        dsl = (
            "search synth\n"
            "let low = foo.o0\n"
            "let high = foo.o7\n"
            "let extended = foo.o8\n"
            "let many = foo.o99\n"
            "let source = s99\n"
            "let vol = vol99\n"
            "let geo = geo99\n"
            "let xyz = xyz99\n"
            "let vel = vel99\n"
            "let rgba = rgba99\n"
            "let mesh = mesh99\n"
        )
        result = compile(dsl)
        vars_ = [
            v["expr"].get("path") or v["expr"].get("name")
            for v in result.get("vars", [])
        ]
        self.assertEqual(
            vars_,
            [
                ["foo", "o0"],
                ["foo", "o7"],
                ["foo", "o8"],
                ["foo", "o99"],
                "s99",
                "vol99",
                "geo99",
                "xyz99",
                "vel99",
                "rgba99",
                "mesh99",
            ],
        )


if __name__ == "__main__":
    unittest.main()

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
    lex,
    parse,
    validate,
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

    def test_compile_preserves_exact_read_and_write_diagnostic_columns(self):
        result = compile("search synth\n  read(123).write(o0)")
        self.assertEqual(
            [(d["code"], d.get("location")) for d in result["diagnostics"]],
            [
                ("S001", {"line": 2, "column": 3}),
                ("S005", {"line": 2, "column": 13}),
            ],
        )

    def test_compile_locates_inline_read_after_blank_lines_and_indentation(self):
        result = compile("search synth\n\n    noise().read(o0).write(o1)")
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(
            result["diagnostics"][0],
            {
                "code": "S001",
                "message": "read() is a starter node and cannot be chained inline. Use standalone read() to start a new chain.: '[Read]'",
                "severity": "error",
                "location": {"line": 3, "column": 13},
                "identifier": "[Read]",
            },
        )

    def test_validate_preserves_explicit_column_on_caller_supplied_ast_locations(self):
        ast = parse(lex("search synth\n  read(123).write(o0)"))
        ast["plans"][0]["chain"][0]["loc"]["column"] = 9
        result = validate(ast)
        self.assertEqual(result["diagnostics"][0]["location"], {"line": 2, "column": 9})

    def test_compile_does_not_invent_location_for_unlocated_ast_node(self):
        result = compile("search synth\n  missing().write(o0)")
        diagnostic = next(d for d in result["diagnostics"] if d.get("identifier") == "missing")
        self.assertEqual(diagnostic["code"], "S001")
        self.assertNotIn("location", diagnostic)

    def test_lexer_diagnostic_payloads(self):
        cases = [
            {
                "name": "unexpected character after CRLF, tab, and UTF-16 text",
                "source": "// 😀\r\n\t@",
                "code": "L001",
                "message": "Unexpected character '@' at line 2 col 2",
                "location": {"line": 2, "column": 2},
                "span": {"start": 8, "end": 9},
            },
            {
                "name": "unterminated double-quoted string at EOF",
                "source": '"abc',
                "code": "L002",
                "message": "Unterminated string literal at line 1 col 1",
                "location": {"line": 1, "column": 1},
                "span": {"start": 0, "end": 4},
            },
            {
                "name": "unterminated single-quoted string at LF",
                "source": " 'abc\nnext",
                "code": "L002",
                "message": "Unterminated string literal at line 1 col 2",
                "location": {"line": 1, "column": 2},
                "span": {"start": 1, "end": 5},
            },
            {
                "name": "unterminated triple-quoted string across lines",
                "source": '\n  """a\nb',
                "code": "L002",
                "message": "Unterminated triple-quoted string at line 2 col 3",
                "location": {"line": 2, "column": 3},
                "span": {"start": 3, "end": 9},
            },
            {
                "name": "unterminated block comment across lines",
                "source": "\n /* a\nb",
                "code": "L003",
                "message": "Unterminated comment at line 2 col 2",
                "location": {"line": 2, "column": 2},
                "span": {"start": 2, "end": 8},
            },
            {
                "name": "out-of-range output reference",
                "source": "search synth\nrender(o99)",
                "code": "L004",
                "message": "Output surface reference 'o99' is out of range; expected o0-o7 at line 2 col 8",
                "location": {"line": 2, "column": 8},
                "span": {"start": 20, "end": 23},
            },
            {
                "name": "UTF-16 columns after a string",
                "source": '"😀" @',
                "code": "L001",
                "message": "Unexpected character '@' at line 1 col 6",
                "location": {"line": 1, "column": 6},
                "span": {"start": 5, "end": 6},
            },
            {
                "name": "source coordinates after a multiline function token",
                "source": "() => (1\n + 2), @",
                "code": "L001",
                "message": "Unexpected character '@' at line 1 col 17",
                "location": {"line": 2, "column": 8},
                "span": {"start": 16, "end": 17},
            },
            {
                "name": "source coordinates after an escaped LF in a string",
                "source": '"a\\\nb" @',
                "code": "L001",
                "message": "Unexpected character '@' at line 1 col 8",
                "location": {"line": 2, "column": 4},
                "span": {"start": 7, "end": 8},
            },
        ]

        for case in cases:
            for entry_point in (lex, compile):
                with self.subTest(case=case["name"], entry_point=entry_point.__name__):
                    with self.assertRaises(SyntaxError) as cm:
                        entry_point(case["source"])
                    err = cm.exception
                    self.assertEqual(str(err), case["message"])
                    self.assertTrue(hasattr(err, "diagnostic"))
                    self.assertEqual(
                        err.diagnostic,
                        {
                            "code": case["code"],
                            "stage": "lexer",
                            "severity": "error",
                            "message": case["message"],
                            "location": case["location"],
                            "span": case["span"],
                        },
                    )

    def test_structured_lexer_failures_leave_successful_tokens_unchanged(self):
        self.assertEqual(
            lex('/*x*/\nfoo.o99 "😀"'),
            [
                {"type": "COMMENT", "lexeme": "/*x*/", "line": 1, "col": 1},
                {"type": "IDENT", "lexeme": "foo", "line": 2, "col": 1},
                {"type": "DOT", "lexeme": ".", "line": 2, "col": 4},
                {"type": "OUTPUT_REF", "lexeme": "o99", "line": 2, "col": 5},
                {"type": "STRING", "lexeme": "😀", "line": 2, "col": 9},
                {"type": "EOF", "lexeme": "", "line": 2, "col": 13},
            ],
        )

    def test_parser_expectation_diagnostics(self):
        cases = [
            ("opening parenthesis", "search synth\nrender o0", "P001", "Expect '(' at line 2 col 8", 2, 8),
            ("closing parenthesis at EOF", "search synth\nrender(o0", "P002", "Expect ')' at line 2 col 10", 2, 10),
            ("identifier", "search synth\nlet = 1", "P001", "Expected identifier at line 2 col 5", 2, 5),
            ("assignment sign", "search synth\nlet x 1", "P001", "Expect '=' at line 2 col 7", 2, 7),
            ("block opening", "search synth\nif(true) return 1", "P001", "Expect '{' at line 2 col 10", 2, 10),
            ("end of input", "search synth\nrender(o0) xyz", "P001", "Expected end of input at line 2 col 12", 2, 12),
            ("call closing parenthesis", "search synth\nfoo(1", "P002", "Expect ')' at line 2 col 6", 2, 6),
            ("write3d separator", "search synth\nfoo().write3d(tex3d0 geo0)", "P001", "Expect ',' between tex3d and geo in write3d() at line 2 col 22", 2, 22),
            ("CRLF and tab", "// 😀\r\nsearch synth\r\n\trender(o0", "P002", "Expect ')' at line 3 col 11", 3, 11),
            ("UTF-16 column", 'search synth\nlet x = "😀"; render o0', "P001", "Expect '(' at line 2 col 22", 2, 22),
        ]
        parse_entry = lambda s: parse(lex(s))
        parse_entry.__name__ = "parse"
        for name, source, code, message, line, column in cases:
            for entry_point in (parse_entry, compile):
                with self.subTest(case=name, entry_point=entry_point.__name__):
                    with self.assertRaises(SyntaxError) as cm:
                        entry_point(source)
                    err = cm.exception
                    self.assertEqual(str(err), message)
                    self.assertTrue(hasattr(err, "diagnostic"))
                    self.assertEqual(
                        err.diagnostic,
                        {
                            "code": code,
                            "stage": "parser",
                            "severity": "error",
                            "message": message,
                            "location": {"line": line, "column": column},
                            "span": None,
                        },
                    )

    def test_render_landscape_filtering_define(self):
        dsl_iso = (
            "search synth, synth3d, render\n"
            "noise(colorMode: mono).write(o1)\n"
            "gradient().write(o2)\n"
            "heightmap3d(heightTex: read(o1), tex: read(o2))\n"
            "  .renderLandscape3d(filtering: isosurface).write(o0)\n"
            "render(o0)\n"
        )
        graph_iso = compile_graph(dsl_iso)
        pass_iso = next(p for p in graph_iso["passes"] if "landscape" in p.get("program", ""))
        self.assertEqual(pass_iso["defines"].get("FILTERING"), 0)

        dsl_vox = (
            "search synth, synth3d, render\n"
            "noise(colorMode: mono).write(o1)\n"
            "gradient().write(o2)\n"
            "heightmap3d(heightTex: read(o1), tex: read(o2))\n"
            "  .renderLandscape3d(filtering: voxel).write(o0)\n"
            "render(o0)\n"
        )
        graph_vox = compile_graph(dsl_vox)
        pass_vox = next(p for p in graph_vox["passes"] if "landscape" in p.get("program", ""))
        self.assertEqual(pass_vox["defines"].get("FILTERING"), 1)

    def test_parser_expectation_diagnostics_represent_unavailable_caller_token_coordinates_explicitly(self):
        for coordinates in [{}, {"line": 1}, {"line": 0, "col": 1}, {"line": 1, "col": float("nan")}]:
            tokens = [
                {"type": tok["type"], "lexeme": tok["lexeme"], **coordinates} if tok["type"] == "OUTPUT_REF" else tok
                for tok in lex("search synth\nrender o0")
            ]
            with self.assertRaises(SyntaxError) as cm:
                parse(tokens)
            err = cm.exception
            expected_line = coordinates.get("line", "undefined")
            expected_col = coordinates.get("col", "undefined")
            self.assertEqual(str(err), f"Expect '(' at line {expected_line} col {expected_col}")
            self.assertEqual(
                err.diagnostic,
                {
                    "code": "P001",
                    "stage": "parser",
                    "severity": "error",
                    "message": str(err),
                    "location": None,
                    "span": None,
                },
            )

    def test_automation_argument_diagnostics(self):
        automation_failures = [
            ("osc(type: oscKind.sine, bogus: 1)", "osc() unknown parameter 'bogus'", ". Valid: type, min, max, speed, offset, seed"),
            ("midi(1, 2, 3, 4, 5, 6)", "midi() name, id, cc, nrpn, zone and members are keyword-only", ""),
            ("midi(bogus: 1)", "midi() unknown parameter 'bogus'", ". Valid: channel, mode, min, max, sensitivity, name, id, cc, nrpn, zone, members"),
            ("midi(1, 2, 3, 4, 5, channel: 1)", "midi() has an excess positional argument", ""),
            ("midi()", "midi() requires 'channel' or 'zone' argument", ""),
            ("midi(1, zone: 1)", "midi() 'channel' and 'zone' are mutually exclusive", ""),
            ("midi(1, members: 2)", "midi() 'members' requires 'zone'", ""),
            ('midi(1, id: "port")', "midi() 'id' requires readable 'name'", ""),
            ("midi(1, name: 1)", "midi() 'name' requires a quoted string", ""),
            ('midi(1, name: "")', "midi() 'name' must not be empty", ""),
            ('midi(1, name: "port", id: 1)', "midi() 'id' requires a quoted string", ""),
            ('midi(1, name: "port", id: "")', "midi() 'id' must not be empty", ""),
            ("audio(1, 2, 3, 4)", "audio() channel, name and id are keyword-only", ""),
            ("audio(bogus: 1)", "audio() unknown parameter 'bogus'", ". Valid: band, min, max, channel, name, id"),
            ("audio(1, 2, 3, band: 1)", "audio() has an excess positional argument", ""),
            ("audio()", "audio() requires 'band' argument", ""),
            ('audio(1, id: "device")', "audio() 'id' requires readable 'name'", ""),
            ('audio(1, name: "device")', "audio() selected device requires both 'name' and 'channel'", ""),
            ("audio(1, channel: 1, name: 1)", "audio() 'name' requires a quoted string", ""),
            ('audio(1, channel: 1, name: "")', "audio() 'name' must not be empty", ""),
            ('audio(1, channel: 1, name: "device", id: 1)', "audio() 'id' requires a quoted string", ""),
            ('audio(1, channel: 1, name: "device", id: "")', "audio() 'id' must not be empty", ""),
        ]
        parse_entry = lambda s: parse(lex(s))
        parse_entry.__name__ = "parse"
        for invocation, prefix, suffix in automation_failures:
            source = f"search synth\nlet x = {invocation}"
            message = f"{prefix} at line 2 col 9{suffix}"
            for entry_point in (parse_entry, compile):
                with self.subTest(invocation=invocation, entry_point=entry_point.__name__):
                    with self.assertRaises(SyntaxError) as cm:
                        entry_point(source)
                    err = cm.exception
                    self.assertEqual(str(err), message)
                    self.assertTrue(hasattr(err, "diagnostic"))
                    self.assertEqual(
                        err.diagnostic,
                        {
                            "code": "P003",
                            "stage": "parser",
                            "severity": "error",
                            "message": message,
                            "location": {"line": 2, "column": 9},
                            "span": None,
                        },
                    )

    def test_automation_argument_diagnostics_crlf_tabs_and_coordinates(self):
        source = 'search synth\r\n\tlet x = "😀"; let y = midi()'
        parse_entry = lambda s: parse(lex(s))
        parse_entry.__name__ = "parse"
        for entry_point in (parse_entry, compile):
            with self.subTest(entry_point=entry_point.__name__):
                with self.assertRaises(SyntaxError) as cm:
                    entry_point(source)
                err = cm.exception
                self.assertEqual(str(err), "midi() requires 'channel' or 'zone' argument at line 2 col 24")
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P003",
                        "stage": "parser",
                        "severity": "error",
                        "message": str(err),
                        "location": {"line": 2, "column": 24},
                        "span": None,
                    },
                )

        for invocation in ["osc(type: 1, bogus: 1)", "midi()", "audio()"]:
            for coordinates in [{}, {"line": 1}, {"line": 0, "col": 1}, {"line": 1, "col": float("nan")}]:
                tokens = [
                    {"type": tok["type"], "lexeme": tok["lexeme"], **coordinates}
                    if tok["lexeme"] in ("osc", "midi", "audio")
                    else tok
                    for tok in lex(f"search synth\nlet x = {invocation}")
                ]
                with self.subTest(invocation=invocation, coordinates=coordinates):
                    with self.assertRaises(SyntaxError) as cm:
                        parse(tokens)
                    err = cm.exception
                    expected_line = coordinates.get("line", "undefined")
                    expected_col = coordinates.get("col", "undefined")
                    self.assertIn(f"at line {expected_line} col {expected_col}", str(err))
                    self.assertEqual(
                        err.diagnostic,
                        {
                            "code": "P003",
                            "stage": "parser",
                            "severity": "error",
                            "message": str(err),
                            "location": None,
                            "span": None,
                        },
                    )

    def test_valid_automation_invocations_retain_ast_defaults(self):
        source = "search synth\nlet a = osc(); let b = midi(1); let c = audio(audioBand.low)"
        vars_ = parse(lex(source))["vars"]
        self.assertEqual(
            [v["expr"] for v in vars_],
            [
                {
                    "type": "Oscillator",
                    "oscType": {"type": "Member", "path": ["oscKind", "sine"]},
                    "min": {"type": "Number", "value": 0},
                    "max": {"type": "Number", "value": 1},
                    "speed": {"type": "Number", "value": 1},
                    "offset": {"type": "Number", "value": 0},
                    "seed": {"type": "Number", "value": 1},
                    "loc": {"line": 2, "col": 9},
                },
                {
                    "type": "Midi",
                    "channel": {"type": "Number", "value": 1},
                    "mode": {"type": "Member", "path": ["midiMode", "velocity"]},
                    "min": {"type": "Number", "value": 0},
                    "max": {"type": "Number", "value": 1},
                    "sensitivity": {"type": "Number", "value": 1},
                    "loc": {"line": 2, "col": 24},
                },
                {
                    "type": "Audio",
                    "band": {"type": "Member", "path": ["audioBand", "low"]},
                    "min": {"type": "Number", "value": 0},
                    "max": {"type": "Number", "value": 1},
                    "loc": {"line": 2, "col": 41},
                },
            ],
        )

    def test_parser_search_directive_diagnostics(self):
        missing_msg = (
            "Missing required 'search' directive. Every program must start with "
            "'search <namespace>, ...' to specify namespace search order."
        )
        cases = [
            ("empty program", "", missing_msg, 1, 1),
            ("missing directive after statements", "let x = 1", missing_msg, 1, 10),
            ("duplicate directive", "search synth search filter", "Only one search directive is allowed per program at line 1 col 14", 1, 14),
            ("invalid namespace", "search bogus", "Invalid namespace 'bogus' at line 1 col 8. Valid namespaces: io, classicNoisedeck, synth, mixer, filter, render, points, synth3d, filter3d, user", 1, 8),
            ("missing first namespace", "search", "Expected namespace identifier after search at line 1 col 7", 1, 7),
            ("missing additional namespace", "search synth,", "Expected namespace identifier after comma at line 1 col 14", 1, 14),
            ("misplaced directive", "let x = 1; search synth", "'search' directive must appear before other statements at line 1 col 12", 1, 12),
            ("nested directive", "search synth\nif(true) { search filter }", "'search' directive is only allowed at the start of the program at line 2 col 12", 2, 12),
            ("CRLF and tab", "// 😀\r\n\tsearch 1", "Expected namespace identifier after search at line 2 col 9", 2, 9),
            ("UTF-16 column", 'search synth\nlet x = "😀"; search filter', "'search' directive must appear before other statements at line 2 col 15", 2, 15),
        ]
        for name, source, message, expected_line, expected_col in cases:
            with self.subTest(name=name):
                with self.assertRaises(SyntaxError) as cm:
                    parse(lex(source))
                err = cm.exception
                self.assertEqual(str(err), message)
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P004",
                        "stage": "parser",
                        "severity": "error",
                        "message": message,
                        "location": {"line": expected_line, "column": expected_col},
                        "span": None,
                    },
                )

    def test_parser_search_diagnostics_preserve_unavailable_caller_token_coordinates(self):
        cases = [
            "",
            "search bogus",
            "search",
            "search synth search filter",
        ]
        for source in cases:
            for coords in [{}, {"line": 1}, {"line": 0, "col": 1}, {"line": 1, "col": float("nan")}]:
                tokens = [
                    {k: v for k, v in t.items() if k not in ("line", "col", "column")} | coords
                    for t in lex(source)
                ]
                with self.assertRaises(SyntaxError) as cm:
                    parse(tokens)
                err = cm.exception
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P004",
                        "stage": "parser",
                        "severity": "error",
                        "message": str(err),
                        "location": None,
                        "span": None,
                    },
                )


    def test_parser_output_operation_diagnostics(self):
        cases = [
            ("invalid render target", "search synth\nrender(1)", "Expected output reference in render()", 2, 8),
            ("render target at EOF", "search synth\nrender(", "Expected output reference in render()", 2, 8),
            (
                "write in expression",
                "search synth\nlet x = diagProbe().write(o0)",
                "'.write()' is only allowed in statement context at line 2 col 21",
                2,
                21,
            ),
            (
                "write3d in expression",
                "search synth\nlet x = diagProbe().write3d(vol0, geo0)",
                "'.write()' is only allowed in statement context at line 2 col 21",
                2,
                21,
            ),
            (
                "missing write surface",
                "search synth\ndiagProbe().write()",
                "write() requires an explicit surface reference (e.g., o0, o1, xyz0, vel0, rgba0, mesh0, none) at line 2 col 19",
                2,
                19,
            ),
            (
                "write surface at EOF",
                "search synth\ndiagProbe().write(",
                "write() requires an explicit surface reference (e.g., o0, o1, xyz0, vel0, rgba0, mesh0, none) at line 2 col 19",
                2,
                19,
            ),
            (
                "invalid write surface",
                "search synth\ndiagProbe().write(1)",
                "write() requires an explicit surface reference (e.g., o0, o1, xyz0, vel0, rgba0, mesh0, none) at line 2 col 19",
                2,
                19,
            ),
            (
                "invalid write3d texture",
                "search synth\ndiagProbe().write3d(1, geo0)",
                "Expected tex3d reference in write3d() at line 2 col 21",
                2,
                21,
            ),
            (
                "write3d texture at EOF",
                "search synth\ndiagProbe().write3d(",
                "Expected tex3d reference in write3d() at line 2 col 21",
                2,
                21,
            ),
            (
                "invalid write3d geometry",
                "search synth\ndiagProbe().write3d(vol0, 1)",
                "Expected geo reference in write3d() at line 2 col 27",
                2,
                27,
            ),
            (
                "write3d geometry at EOF",
                "search synth\ndiagProbe().write3d(vol0,",
                "Expected geo reference in write3d() at line 2 col 26",
                2,
                26,
            ),
            (
                "CRLF and tab render target",
                "// 😀\r\nsearch synth\r\n\trender(\"😀\")",
                "Expected output reference in render()",
                3,
                9,
            ),
            (
                "UTF-16 render target column",
                'search synth\nlet x = "😀"; render(none)',
                "Expected output reference in render()",
                2,
                22,
            ),
        ]
        for name, source, message, expected_line, expected_col in cases:
            with self.subTest(name=name):
                with self.assertRaises(SyntaxError) as cm:
                    parse(lex(source))
                err = cm.exception
                self.assertEqual(str(err), message)
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P005",
                        "stage": "parser",
                        "severity": "error",
                        "message": message,
                        "location": {"line": expected_line, "column": expected_col},
                        "span": None,
                    },
                )

    def test_parser_output_diagnostics_preserve_unavailable_caller_token_coordinates(self):
        cases = [
            "search synth\nrender(1)",
            "search synth\nlet x = diagProbe().write(o0)",
            "search synth\ndiagProbe().write(1)",
            "search synth\ndiagProbe().write3d(1, geo0)",
            "search synth\ndiagProbe().write3d(vol0, 1)",
        ]
        for source in cases:
            for coords in [{}, {"line": 1}, {"line": 0, "col": 1}, {"line": 1, "col": float("nan")}]:
                tokens = [
                    {k: v for k, v in t.items() if k not in ("line", "col", "column")} | coords
                    for t in lex(source)
                ]
                with self.assertRaises(SyntaxError) as cm:
                    parse(tokens)
                err = cm.exception
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P005",
                        "stage": "parser",
                        "severity": "error",
                        "message": str(err),
                        "location": None,
                        "span": None,
                    },
                )

    def test_parser_subchain_diagnostics_attach_metadata(self):
        cases = [
            (
                "non-string argument",
                "search synth\nread(o0).subchain(name: 1) { .diagProbe() }",
                "Expected string value for subchain name at line 2 col 25",
                2,
                25,
            ),
            (
                "argument at EOF",
                "search synth\nread(o0).subchain(name:",
                "Expected string value for subchain name at line 2 col 24",
                2,
                24,
            ),
            (
                "missing body dot",
                "search synth\nread(o0).subchain() { diagProbe() }",
                "Expected '.' before chain element in subchain body at line 2 col 23",
                2,
                23,
            ),
            (
                "body at EOF",
                "search synth\nread(o0).subchain() {",
                "Expected '.' before chain element in subchain body at line 2 col 22",
                2,
                22,
            ),
            (
                "empty body",
                "search synth\nread(o0).subchain() {}",
                "Subchain body cannot be empty at line 2 col 10",
                2,
                10,
            ),
            (
                "comment-only body",
                "search synth\nread(o0).subchain() { /* empty */ }",
                "Subchain body cannot be empty at line 2 col 10",
                2,
                10,
            ),
            (
                "CRLF tab and UTF-16 argument",
                '// 😀\r\nsearch synth\r\n\tread(o0).subchain(name: "😀", id: 1) { .diagProbe() }',
                "Expected string value for subchain id at line 3 col 36",
                3,
                36,
            ),
            (
                "missing dot after comment",
                "search synth\nread(o0).subchain() { /* 😀 */ missing() }",
                "Expected '.' before chain element in subchain body at line 2 col 32",
                2,
                32,
            ),
            (
                "unclosed nonempty body",
                "search synth\nread(o0).subchain() { .diagProbe()",
                "Expected '.' before chain element in subchain body at line 2 col 35",
                2,
                35,
            ),
        ]
        for name, source, message, expected_line, expected_col in cases:
            with self.subTest(name=name):
                with self.assertRaises(SyntaxError) as cm:
                    parse(lex(source))
                err = cm.exception
                self.assertEqual(str(err), message)
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P006",
                        "stage": "parser",
                        "severity": "error",
                        "message": message,
                        "location": {"line": expected_line, "column": expected_col},
                        "span": None,
                    },
                )

    def test_parser_subchain_diagnostics_preserve_unavailable_caller_token_coordinates(self):
        cases = [
            "search synth\nread(o0).subchain(name: 1) { .diagProbe() }",
            "search synth\nread(o0).subchain() { diagProbe() }",
            "search synth\nread(o0).subchain() {}",
        ]
        for source in cases:
            for coords in [{}, {"line": 1}, {"line": 0, "col": 1}, {"line": 1, "col": float("nan")}]:
                tokens = [
                    {k: v for k, v in t.items() if k not in ("line", "col", "column")} | coords
                    for t in lex(source)
                ]
                with self.assertRaises(SyntaxError) as cm:
                    parse(tokens)
                err = cm.exception
                self.assertEqual(
                    err.diagnostic,
                    {
                        "code": "P006",
                        "stage": "parser",
                        "severity": "error",
                        "message": str(err),
                        "location": None,
                        "span": None,
                    },
                )

    def test_parser_subchain_syntax_preserves_shared_expectation_precedence(self):
        cases = [
            ("search synth\nread(o0).subchain(1) {}", "P002", "Expect ')' after subchain arguments at line 2 col 19"),
            ("search synth\nread(o0).subchain() { . }", "P001", "Expected identifier at line 2 col 25"),
        ]
        for source, code, message in cases:
            with self.assertRaises(SyntaxError) as cm:
                parse(lex(source))
            err = cm.exception
            self.assertEqual(str(err), message)
            self.assertEqual(err.diagnostic["code"], code)

    def test_valid_subchains_parse_and_compile(self):
        cases = [
            ("", None, None),
            ('"positional"', "positional", None),
            ('name: "named", id: "s"', "named", "s"),
            ('foo: "x" name: "a" name: "b" id: "s"', "b", "s"),
        ]
        for args, expected_name, expected_id in cases:
            with self.subTest(args=args):
                source = f"search synth, filter\nread(o0).subchain({args}) {{ .invert() }}.write(o1)"
                ast = parse(lex(source))
                subchain_node = ast["plans"][0]["chain"][1]
                self.assertEqual(subchain_node["type"], "Subchain")
                self.assertEqual(subchain_node["name"], expected_name)
                self.assertEqual(subchain_node["id"], expected_id)
                self.assertEqual(subchain_node["loc"], {"line": 2, "col": 10})
                self.assertEqual(len(subchain_node["body"]), 1)
                self.assertEqual(subchain_node["body"][0]["name"], "invert")

                result = compile(source)
                self.assertEqual(result.get("diagnostics", []), [])
                chain = result["plans"][0]["chain"]
                self.assertEqual(chain[0]["op"], "_read")
                self.assertEqual(chain[1]["op"], "_subchain_begin")
                self.assertEqual(chain[1]["args"], {"name": expected_name, "id": expected_id})
                self.assertEqual(chain[3]["op"], "_subchain_end")
                self.assertEqual(chain[3]["args"], {"name": expected_name, "id": expected_id})
                self.assertEqual(chain[4]["op"], "_write")

        # Also verify end-to-end full program compile_graph
        full_source = 'search synth, filter\nnoise().write(o0)\nread(o0).subchain(name: "sub") { .invert() }.write(o1)\nrender(o1)'
        compiled = compile_graph(full_source)
        self.assertIn("passes", compiled)
        self.assertEqual(compiled["renderSurface"], "o1")


if __name__ == "__main__":
    unittest.main()

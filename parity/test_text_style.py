#!/usr/bin/env python3
"""Compiler parity for the font-family style selected by the text host."""

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender.compiler import compile  # noqa: E402


class TextStyleTests(unittest.TestCase):
    def test_text_style_survives_compilation(self):
        source = (
            'search synth, filter\n'
            'noise().text(text: "hello", style: "Extra Bold").write(o0)\n'
            'render(o0)'
        )

        result = compile(source)

        self.assertEqual([], result["diagnostics"])
        self.assertEqual("Extra Bold", result["plans"][0]["chain"][1]["args"]["style"])


if __name__ == "__main__":
    unittest.main()

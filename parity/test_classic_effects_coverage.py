"""Keep the upstream classic effects branches in the graded render set."""

import sys
import unittest
from pathlib import Path


PARITY = Path(__file__).resolve().parent
sys.path.insert(0, str(PARITY.parent / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402


EFFECTS = {
    "pixels": 100,
    "blur": 1,
    "cga": 200,
    "subpixel": 210,
    "bloom": 220,
    "zoomBlur": 230,
}


class ClassicEffectsCoverageTests(unittest.TestCase):
    def test_tiling_changed_branches_have_graded_render_fixtures(self):
        manifest = (PARITY / "artistic-expected.txt").read_text().splitlines()
        for effect, define in EFFECTS.items():
            with self.subTest(effect=effect):
                name = f"classic_effects_{effect}"
                self.assertEqual(1, manifest.count(name))
                source = (PARITY / "programs" / f"{name}.dsl").read_text()
                graph = compile_graph(source)
                passes = [p for p in graph["passes"]
                          if p.get("namespace") == "classicNoisedeck" and p.get("func") == "effects"]
                self.assertEqual(1, len(passes))
                self.assertEqual(define, passes[0]["defines"]["EFFECT"])


if __name__ == "__main__":
    unittest.main()

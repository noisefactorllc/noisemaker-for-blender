"""Explicit particle texture inputs (upstream 06ce0927..317c43cc,
test_particle_input_textures.mjs).

Each point behavior exposes explicit texture-input surfaces:
- flow/dla/physarum fieldTex, hydraulic heightTex: the movement field
  (fieldActive), falling back to the chained input when "none" or omitted
- every behavior's diffuseTex: the particle color source (diffuseActive),
  keeping the existing color when "none" or omitted
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402


def agent_pass(effect, params=""):
    prefix = "solid(color: #ff0000).write(o1)\n" if params else ""
    if effect == "pointsEmit":
        body = f"solid(color: #00ff00).pointsEmit({params}).write(o0)"
    else:
        body = f"solid(color: #00ff00).pointsEmit().{effect}({params}).write(o0)"
    dsl = "search synth, render, points\n" + prefix + body + "\nrender(o0)"
    graph = compile_graph(dsl)
    program = "_agentField" if effect == "lenia" else "_agent"
    agents = [p for p in graph["passes"]
              if str(p.get("effectKey") or "").endswith("." + effect)
              and p["program"].endswith(program)]
    assert agents, f"{effect}: agent pass exists"
    return graph, agents[0]


FIELD_EFFECTS = [("flow", "fieldTex"), ("hydraulic", "heightTex"),
                 ("dla", "fieldTex"), ("physarum", "fieldTex")]
DIFFUSE_EFFECTS = ["flow", "hydraulic", "dla", "physarum", "life",
                   "flock", "physical", "attractor", "buddhabrot", "lenia"]


class ParticleInputTextureTests(unittest.TestCase):
    def test_movement_field_defaults_to_the_chained_input(self):
        for effect, surface in FIELD_EFFECTS:
            with self.subTest(effect=effect):
                _, agent = agent_pass(effect)
                self.assertEqual(agent["inputs"]["inputTex"], "node_1_out")
                self.assertEqual(agent["uniforms"]["fieldActive"], 0)

    def test_movement_field_takes_an_independent_surface(self):
        for effect, surface in FIELD_EFFECTS:
            with self.subTest(effect=effect):
                _, agent = agent_pass(effect, f"{surface}: read(o1)")
                self.assertEqual(agent["inputs"]["inputTex"], "node_3_out")
                self.assertEqual(agent["inputs"][surface], "global_o1")
                self.assertEqual(agent["uniforms"]["fieldActive"], 1)
                _, agent = agent_pass(effect, f"{surface}: none")
                self.assertEqual(agent["inputs"]["inputTex"], "node_3_out")
                self.assertEqual(agent["uniforms"]["fieldActive"], 0)

    def test_heightGrid_resolves_each_optional_surface_independently(self):
        _, height_only = agent_pass("heightGrid", "heightTex: read(o1)")
        self.assertEqual(height_only["inputs"]["heightTex"], "global_o1")
        self.assertEqual(height_only["inputs"]["diffuseTex"], "node_3_out")
        _, diffuse_only = agent_pass("heightGrid", "diffuseTex: read(o1)")
        self.assertEqual(diffuse_only["inputs"]["heightTex"], "node_3_out")
        self.assertEqual(diffuse_only["inputs"]["diffuseTex"], "global_o1")

    def test_particle_color_keeps_the_existing_color_omitted_or_none(self):
        for effect in DIFFUSE_EFFECTS:
            with self.subTest(effect=effect):
                _, omitted = agent_pass(effect)
                _, none = agent_pass(effect, "diffuseTex: none")
                self.assertEqual(omitted["uniforms"]["diffuseActive"], 0)
                self.assertEqual(none["uniforms"]["diffuseActive"], 0)

    def test_particle_color_accepts_an_independent_diffuse_surface(self):
        for effect in DIFFUSE_EFFECTS:
            with self.subTest(effect=effect):
                _, agent = agent_pass(effect, "diffuseTex: read(o1)")
                self.assertEqual(agent["inputs"]["diffuseTex"], "global_o1")
                self.assertEqual(agent["uniforms"]["diffuseActive"], 1)

    def test_life_defaults_particle_color_to_the_chained_input(self):
        _, agent = agent_pass("life")
        self.assertEqual(agent["inputs"]["inputTex"], "node_1_out")
        self.assertEqual(agent["uniforms"]["diffuseActive"], 0)

    def test_surface_globals_carry_no_uniform_spec_entry(self):
        _, agent = agent_pass("flow")
        self.assertNotIn("fieldTex", agent.get("uniformSpecs", {}))
        self.assertNotIn("diffuseTex", agent.get("uniformSpecs", {}))


if __name__ == "__main__":
    unittest.main()

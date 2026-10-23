"""Explicit particle texture inputs (upstream test_particle_input_textures.mjs
at 27a2b58f4a17df2ab700bfc427cc16e27ba38ae4).

Each point behavior exposes explicit texture-input surfaces:
- flow/dla/physarum heightTex (renamed from fieldTex at 27a2b58f; fieldTex
  stays accepted as a deprecated alias), hydraulic heightTex: the movement
  field (fieldActive), falling back to the chained input when "none" or
  omitted
- every behavior's diffuseTex: the particle color source (diffuseActive),
  keeping the existing color when "none" or omitted
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile, compile_graph  # noqa: E402


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


FIELD_EFFECTS = [("flow", "heightTex"), ("hydraulic", "heightTex"),
                 ("dla", "heightTex"), ("physarum", "heightTex")]
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
        self.assertNotIn("heightTex", agent.get("uniformSpecs", {}))
        self.assertNotIn("diffuseTex", agent.get("uniformSpecs", {}))

    def test_fieldTex_alias_compiles_with_s007_to_the_same_graph(self):
        # Upstream 27a2b58f: fieldTex stays accepted as a deprecated alias for
        # heightTex until 2027-06-01; the validator rewrites it and warns S007.
        # The alias registry is a runtime-registration path (canvas.js), not
        # part of the compile() golden contract (the oracle's bootstrap never
        # registers aliases), so compile() reports the alias as unknown (S001)
        # exactly like the reference compile() does.
        for effect in ("flow", "dla", "physarum"):
            with self.subTest(effect=effect):
                aliased = compile(
                    f"search synth, render, points\n"
                    f"solid(color: #00ff00).pointsEmit().{effect}(fieldTex: read(o1)).write(o0)\n"
                    f"render(o0)"
                )
                self.assertTrue(
                    any(d.get("code") == "S001" and "fieldTex" in d.get("message", "")
                        for d in aliased["diagnostics"]),
                    aliased["diagnostics"],
                )
                self.assertFalse(any(d.get("code") == "S007" for d in aliased["diagnostics"]))
                canonical = compile(
                    f"search synth, render, points\n"
                    f"solid(color: #00ff00).pointsEmit().{effect}(heightTex: read(o1)).write(o0)\n"
                    f"render(o0)"
                )
                self.assertFalse(
                    any(d.get("severity") == "error" for d in canonical["diagnostics"]),
                    canonical["diagnostics"],
                )
                aliased_graph = compile_graph(
                    f"search synth, render, points\n"
                    f"solid(color: #00ff00).pointsEmit().{effect}(heightTex: read(o1)).write(o0)\n"
                    f"render(o0)"
                )
                agents = [p for p in aliased_graph["passes"]
                          if str(p.get("effectKey") or "").endswith("." + effect)
                          and p["program"].endswith("_agent")]
                self.assertEqual(agents[0]["inputs"]["heightTex"], "global_o1")

    def test_alias_resolution_rewrites_and_warns(self):
        # The registry-side resolver (paramAliases.resolveParamAliases) renames
        # in place, lets the canonical key win, and warns once per alias.
        from noisemaker_blender.compiler import ops as ops_mod
        ops_mod.rebuild()
        ops_mod._PARAM_ALIASES["points.flow"] = {"fieldTex": "heightTex"}
        try:
            kwargs = {"fieldTex": 1}
            warnings = ops_mod.resolve_param_aliases("points.flow", kwargs)
            self.assertEqual(kwargs, {"heightTex": 1})
            self.assertEqual(len(warnings), 1)
            self.assertIn("param 'fieldTex' is deprecated, use 'heightTex' instead", warnings[0])
            self.assertIn("2027-06-01", warnings[0])
            both = {"fieldTex": 1, "heightTex": 2}
            warnings = ops_mod.resolve_param_aliases("points.flow", both)
            self.assertEqual(both, {"heightTex": 2})
            self.assertEqual(len(warnings), 1)
        finally:
            ops_mod.rebuild()

    def test_height_map_is_listed_before_diffuse_map(self):
        # Upstream 663e7ab..12751c78: every particle behavior lists its height
        # map before its diffuse map, as heightGrid does.
        import json
        for name in ("flow", "dla", "physarum", "hydraulic", "heightGrid"):
            with self.subTest(effect=name):
                defn = json.load(open(ROOT / "blender/noisemaker_blender/effects/points" / f"{name}.json"))
                keys = list(defn["globals"].keys())
                self.assertIn("heightTex", keys)
                self.assertLess(keys.index("heightTex"), keys.index("diffuseTex"))

    def test_agent_base_color_contract(self):
        # Upstream 663e7ab..12751c78 adds a per-behavior base-color texture,
        # a fourth MRT slot, and keeps the agent's own color there while a
        # diffuse map recolors it. life keeps its data output and is excluded.
        import json
        effects = ("flow", "dla", "physarum", "hydraulic", "attractor",
                   "buddhabrot", "flock", "physical", "lenia")
        for name in effects:
            with self.subTest(effect=name):
                defn = json.load(open(ROOT / "blender/noisemaker_blender/effects/points" / f"{name}.json"))
                texture = defn["textures"]["global_%s_base_color" % name]
                self.assertEqual(texture["format"], "rgba8")
                self.assertEqual(texture["width"],
                                 {"param": "stateSize", "inherit": True, "default": 256})
                self.assertEqual(texture["height"],
                                 {"param": "stateSize", "inherit": True, "default": 256})
                agent = next(p for p in defn["passes"] if p["program"] in ("agent", "agentField"))
                self.assertEqual(agent["drawBuffers"], 4)
                self.assertEqual(agent["inputs"]["baseColorTex"], "global_%s_base_color" % name)
                self.assertEqual(agent["outputs"]["outBaseColor"], "global_%s_base_color" % name)
                frag_name = "agentField.frag" if name == "lenia" else "agent.frag"
                frag = (ROOT / "blender/noisemaker_blender/shaders/effects/points" / name / frag_name).read_text()
                self.assertIn("uniform sampler2D baseColorTex;", frag)
                self.assertIn("layout(location = 3) out vec4 outBaseColor;", frag)
                self.assertIn("outBaseColor = keptBaseColor(", frag)

    def test_agent_base_color_graph_scope(self):
        # The base-color texture scopes per particle pipeline like the other
        # particle state textures, and its stateSize dimension is inherited.
        graph = compile_graph(
            "search synth, render, points\n"
            "solid(color: #00ff00).pointsEmit().flow(heightTex: read(o1)).write(o0)\n"
            "render(o0)"
        )
        passes = [p for p in graph["passes"] if p["program"].endswith("_agent")]
        self.assertEqual(passes[0]["outputs"]["outBaseColor"], "global_flow_base_color_node_1")
        self.assertEqual(passes[0]["inputs"]["baseColorTex"], passes[0]["outputs"]["outBaseColor"])

    def test_base_color_memory_sizes_like_pointsEmit_when_stateSize_is_a_function(self):
        # Upstream 12751c78..32d8d3e6: the runtime does not evaluate a
        # function-valued stateSize, so each texture falls back to its spec's
        # default. pointsEmit's state textures fall back to 256; the base
        # color memory is an attachment of the same agent pass, so it must
        # fall back to the same size (WebGPU rejects mismatched attachments).
        from noisemaker_blender.runtime.pipeline import resolve_dimension
        for name in ("flow", "dla", "physarum", "hydraulic", "attractor",
                     "buddhabrot", "flock", "physical", "lenia"):
            with self.subTest(effect=name):
                dsl = (
                    "search synth, render, points\n"
                    "noise().pointsEmit(stateSize: () => 128).%s().write(o0)\n"
                    "render(o0)" % name
                )
                graph = compile_graph(dsl)
                specs = graph["textures"]
                state = specs["global_xyz_node_1"]
                memory = specs["global_%s_base_color_node_1" % name]
                wrapper = {"fn": {"_func_src": "128"}}
                state_size = resolve_dimension(state["width"], 512, {})
                memory_size = resolve_dimension(memory["width"], 512,
                                                {"stateSize_node_1": wrapper})
                self.assertEqual(state_size, 256)
                self.assertEqual(memory_size, state_size,
                                 "memory %d does not match agent state %d"
                                 % (memory_size, state_size))
                self.assertEqual(resolve_dimension(memory["height"], 512, {}),
                                 resolve_dimension(state["height"], 512, {}))


if __name__ == "__main__":
    unittest.main()

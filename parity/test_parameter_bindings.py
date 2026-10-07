"""Stable typed bindings survive graph edits and evaluated Blender properties."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.integration.parameters import (
    BindingStore, ParameterSpec, BlenderPropertyAdapter, specs_from_effects,
    seed_values_from_program, animated_parameter_keys,
)


NOISE = {"namespace": "synth", "func": "noise", "globals": {
    "seed": {"type": "int", "default": 1, "min": 1, "max": 100, "uniform": "seed"},
    "type": {"type": "int", "default": 10, "choices": {"simplex": 10, "sine": 11}, "define": "NOISE_TYPE"},
    "wrap": {"type": "boolean", "default": True, "uniform": "wrap"},
}}
BLOOM = {"namespace": "filter", "func": "bloom", "globals": {
    "amount": {"type": "float", "default": 0.5, "min": 0, "max": 1, "uniform": "amount"},
}}


class FakeUI:
    def __init__(self): self.metadata = {}
    def update(self, **kwargs): self.metadata.update(kwargs)


class FakeOwner(dict):
    def __init__(self):
        super().__init__()
        self.ui = {}
        self.evaluated = None
    def id_properties_ui(self, key): return self.ui.setdefault(key, FakeUI())
    def evaluated_get(self, depsgraph):
        assert depsgraph == "graph"
        return self.evaluated


class ParameterBindingTests(unittest.TestCase):
    def test_animated_parameter_detection_ignores_unrelated_scene_curves(self):
        from types import SimpleNamespace
        config = SimpleNamespace(path_from_id=lambda: "noisemaker_instances[0]")
        key = "solid#0.color"
        path = 'noisemaker_instances[0]["nm:solid#0.color"]'
        unrelated = SimpleNamespace(data_path='render.resolution_x')
        keyed = SimpleNamespace(data_path=path)
        action = SimpleNamespace(fcurves=[unrelated, keyed], layers=())
        scene = SimpleNamespace(animation_data=SimpleNamespace(
            action=action, action_slot=None, drivers=(), nla_tracks=()))
        self.assertEqual(animated_parameter_keys(scene, config, [key]), (key,))
        self.assertEqual(animated_parameter_keys(scene, config, ["solid#0.alpha"]), ())

    def test_layered_action_and_driver_detection(self):
        from types import SimpleNamespace
        config = SimpleNamespace(path_from_id=lambda: "noisemaker_instances[1]")
        key = "noise#0.seed"
        path = 'noisemaker_instances[1]["nm:noise#0.seed"]'
        slot = object()
        bag = SimpleNamespace(fcurves=[SimpleNamespace(data_path=path)])
        strip = SimpleNamespace(channelbags=(bag,), channelbag=lambda selected: bag if selected is slot else None)
        action = SimpleNamespace(layers=[SimpleNamespace(strips=[strip])])
        scene = SimpleNamespace(animation_data=SimpleNamespace(
            action=action, action_slot=slot, drivers=(), nla_tracks=()))
        self.assertEqual(animated_parameter_keys(scene, config, [key]), (key,))
        scene.animation_data.action = None
        scene.animation_data.drivers = [SimpleNamespace(data_path=path)]
        self.assertEqual(animated_parameter_keys(scene, config, [key]), (key,))

    def test_stable_keys_keep_values_and_orphans_across_other_effect_edits(self):
        store = BindingStore(specs_from_effects([NOISE, BLOOM]))
        store.set("noise#0.seed", 7)
        store.set("bloom#0.amount", 0.75)
        store.reconcile(specs_from_effects([BLOOM, NOISE]))
        self.assertEqual(store.value("noise#0.seed"), 7)
        self.assertEqual(store.value("bloom#0.amount"), 0.75)
        store.reconcile(specs_from_effects([BLOOM]))
        self.assertEqual(store.orphan_keys, ("noise#0.seed", "noise#0.type", "noise#0.wrap"))
        self.assertEqual(store.value("noise#0.seed"), 7)
        store.reconcile(specs_from_effects([NOISE, BLOOM]))
        self.assertEqual(store.value("noise#0.seed"), 7)
        self.assertEqual(store.orphan_keys, ())

    def test_types_ranges_enum_mapping_and_invalidation_class_are_explicit(self):
        store = BindingStore(specs_from_effects([NOISE, BLOOM]))
        self.assertEqual(store.set("noise#0.type", "sine"), "define")
        self.assertEqual(store.value("noise#0.type"), 11)
        self.assertEqual(store.set("noise#0.seed", 8), "scalar")
        with self.assertRaises(ValueError): store.set("noise#0.type", 9)
        with self.assertRaises(ValueError): store.set("noise#0.seed", 101)
        with self.assertRaises(TypeError): store.set("noise#0.seed", True)
        with self.assertRaises(TypeError): store.set("noise#0.wrap", 1)
        with self.assertRaises(KeyError): store.set("missing#0.x", 1)
        spec = ParameterSpec.from_metadata("crop#0.width", {"type": "int", "default": 64, "size": True})
        self.assertEqual(spec.invalidation, "resource")

    def test_grouped_and_string_choices_store_integer_codes_for_animation(self):
        grouped = ParameterSpec.from_metadata("noise#0.loopOffset", {
            "type": "int", "default": 300,
            "choices": {"Shapes:": None, "circle": 10, "Misc:": None, "noise": 300},
        })
        font = ParameterSpec.from_metadata("text#0.font", {
            "type": "string", "default": "Nunito",
            "choices": {"nunito": "Nunito", "serif": "serif"},
        })
        store = BindingStore([grouped, font])
        store.set("text#0.font", "serif")
        owner = FakeOwner()
        adapter = BlenderPropertyAdapter(owner)
        adapter.persist(store)
        font_prop = adapter.property_name("text#0.font")
        self.assertIsInstance(owner[font_prop], int)
        owner.evaluated = FakeOwner()
        owner.evaluated.update(owner)
        self.assertEqual(adapter.evaluated_values(store, "graph")["text#0.font"], "serif")
        self.assertEqual(adapter.enum_label(store, "noise#0.loopOffset"), "noise")

    def test_new_binding_starts_from_compiled_dsl_value(self):
        from noisemaker_blender.api import compile
        program = compile("search synth\nsolid(color: [0.2, 0.3, 0.4, 1]).write(o0)\nrender(o0)")
        definition = {"namespace": "synth", "func": "solid", "globals": {
            "color": {"type": "color", "default": [0.5, 0.5, 0.5], "uniform": "color"},
            "alpha": {"type": "float", "default": 1, "uniform": "alpha"},
        }}
        store = BindingStore(specs_from_effects([definition]))
        store.seed(seed_values_from_program(program, [definition]))
        self.assertEqual(store.value("solid#0.color"), (0.2, 0.3, 0.4, 1.0))
        self.assertEqual(store.value("solid#0.alpha"), 1)

    def test_compiled_boolean_uniforms_seed_typed_bool_controls(self):
        from noisemaker_blender.api import compile
        from noisemaker_blender.integration.lifecycle import LiveRegistry
        source = (Path(__file__).resolve().parent / "programs" / "flow3d.dsl").read_text()
        program = compile(source)
        seeds = seed_values_from_program(program, LiveRegistry._definitions(program))
        self.assertIsInstance(seeds["noise3d#0.ridges"], bool)

    def test_vector_binding_accepts_index_only_evaluated_id_property_array(self):
        class IndexOnlyArray:
            def __init__(self, values): self.values = values
            def __len__(self): return len(self.values)
            def __getitem__(self, index): return self.values[index]
        spec = ParameterSpec.from_metadata("solid#0.color", {
            "type": "color", "default": [0.5, 0.5, 0.5], "uniform": "color",
        })
        self.assertEqual(spec.validate(IndexOnlyArray([0.2, 0.3, 0.4])),
                         (0.2, 0.3, 0.4))

    def test_vector_binding_accepts_blender_array_values(self):
        from array import array
        spec = ParameterSpec.from_metadata("solid#0.color", {
            "type": "color", "default": [0.5, 0.5, 0.5], "uniform": "color",
        })
        result = spec.validate(array("f", [0.2, 0.3, 0.4]))
        for actual, expected in zip(result, (0.2, 0.3, 0.4)):
            self.assertAlmostEqual(actual, expected)

    def test_hex_color_metadata_preserves_source_color_value(self):
        spec = ParameterSpec.from_metadata("text#0.color", {"type": "color", "default": "#ffffff"})
        self.assertEqual(spec.validate("#8040ff"), "#8040ff")
        with self.assertRaises(ValueError):
            spec.validate("red")

    def test_blender_adapter_keeps_custom_properties_and_reads_evaluated_drivers(self):
        store = BindingStore(specs_from_effects([NOISE]))
        original = FakeOwner()
        adapter = BlenderPropertyAdapter(original)
        adapter.persist(store)
        prop = adapter.property_name("noise#0.seed")
        self.assertEqual(original[prop], 1)
        self.assertEqual(original.ui[prop].metadata["min"], 1)
        self.assertEqual(original.ui[prop].metadata["max"], 100)
        self.assertEqual(adapter.enum_label(store, "noise#0.type"), "simplex")
        evaluated = FakeOwner()
        evaluated.update(original)
        evaluated[prop] = 33  # A keyframe or driver on the evaluated depsgraph owner.
        original.evaluated = evaluated
        self.assertEqual(adapter.evaluated_values(store, "graph")["noise#0.seed"], 33)
        self.assertEqual(adapter.evaluated_values(store, "graph", evaluated_owner=evaluated)["noise#0.seed"], 33)
        store.reconcile([])
        adapter.persist(store)
        self.assertIn(prop, original)  # The orphaned keyframe/driver data path survives.


if __name__ == "__main__":
    unittest.main()

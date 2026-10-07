"""Persistent Blender-owned instance identity independent of display names."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.integration.persistence import ensure_unique_ids, source_for_instance, pack_outputs_before_save, set_image_binding

class Scene:
    def __init__(self, *records, library=None):
        self.noisemaker_instances = list(records)
        self.library = library

class PersistenceTests(unittest.TestCase):
    def test_duplicate_scene_instance_gets_new_identity_and_no_foreign_image(self):
        first = SimpleNamespace(instance_id="shared", output_image="original")
        duplicate = SimpleNamespace(instance_id="shared", output_image="original")
        ensure_unique_ids([Scene(first), Scene(duplicate)])
        self.assertEqual(first.instance_id, "shared")
        self.assertNotEqual(duplicate.instance_id, "shared")
        self.assertIsNone(duplicate.output_image)

    def test_linked_scene_identity_is_left_untouched(self):
        linked = SimpleNamespace(instance_id="shared", output_image="linked")
        local = SimpleNamespace(instance_id="shared", output_image="local")
        ensure_unique_ids([Scene(linked, library=object()), Scene(local)])
        self.assertEqual(linked.instance_id, "shared")
        self.assertEqual(linked.output_image, "linked")
        self.assertNotEqual(local.instance_id, "shared")

    def test_local_duplicate_yields_to_linked_identity_regardless_of_scene_order(self):
        local = SimpleNamespace(instance_id="shared", output_image="local")
        linked = SimpleNamespace(instance_id="shared", output_image="linked")
        ensure_unique_ids([Scene(local), Scene(linked, library=object())])
        self.assertNotEqual(local.instance_id, "shared")
        self.assertIsNone(local.output_image)
        self.assertEqual(linked.instance_id, "shared")
        self.assertEqual(linked.output_image, "linked")

    def test_save_packs_only_owned_opted_or_previously_packed_outputs(self):
        class Image(dict):
            library = None
            is_float = True
            def __init__(self, owner, packed=False):
                super().__init__(noisemaker_owner=owner)
                self.packed_file = object() if packed else None
                self.pack_count = 0
            def pack(self): self.pack_count += 1; self.packed_file = object()
        chosen = Image("a")
        existing = Image("b", packed=True)
        skipped = Image("c")
        foreign = Image("other", packed=True)
        scene = Scene(SimpleNamespace(instance_id="a", output_image=chosen, pack_output=True),
                      SimpleNamespace(instance_id="b", output_image=existing, pack_output=False),
                      SimpleNamespace(instance_id="c", output_image=skipped, pack_output=False),
                      SimpleNamespace(instance_id="d", output_image=foreign, pack_output=True))
        self.assertEqual(pack_outputs_before_save([scene]), 2)
        self.assertEqual([image.pack_count for image in (chosen, existing, skipped, foreign)],
                         [1, 1, 0, 0])

    def test_image_binding_is_saved_by_name_and_linked_config_refuses_mutation(self):
        class Collection(list):
            def add(self):
                item = SimpleNamespace(binding_name="", image=None)
                self.append(item)
                return item
            def remove(self, index):
                del self[index]
        image_a = SimpleNamespace(source="GENERATED")
        image_b = SimpleNamespace(source="FILE")
        config = SimpleNamespace(input_bindings=Collection())
        scene = Scene(config)
        set_image_binding(scene, config, "imageTex_step_0", image_a)
        set_image_binding(scene, config, "imageTex_step_0", image_b)
        self.assertEqual(len(config.input_bindings), 1)
        self.assertIs(config.input_bindings[0].image, image_b)
        with self.assertRaises(ValueError):
            set_image_binding(scene, config, "imageTex_step_1", SimpleNamespace(source="MOVIE"))
        with self.assertRaises(ValueError):
            set_image_binding(Scene(config, library=object()), config, "imageTex_step_1", image_a)
        set_image_binding(scene, config, "imageTex_step_0", None)
        self.assertEqual(len(config.input_bindings), 0)

    def test_selected_source_is_bounded_and_other_files_are_not_polled(self):
        instance = SimpleNamespace(source_mode="INLINE", source="noise()", text=None, filepath="")
        self.assertEqual(source_for_instance(instance, max_chars=20), "noise()")
        instance.source = "x" * 21
        with self.assertRaises(ValueError): source_for_instance(instance, max_chars=20)

if __name__ == "__main__": unittest.main()

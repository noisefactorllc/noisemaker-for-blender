"""Persistent Blender-owned instance identity independent of display names."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.integration.persistence import (ensure_unique_ids, source_for_instance,
    pack_outputs_before_save, set_image_binding, resolve_output_image, assign_output_image,
    migrate_legacy_output_refs)

class Scene:
    def __init__(self, *records, library=None):
        self.noisemaker_instances = list(records)
        self.library = library

class PersistenceTests(unittest.TestCase):
    def test_output_reference_is_owner_scoped_rename_safe_and_explicitly_clearable(self):
        class Image(dict):
            library = None
            is_float = True
            def __init__(self, name, owner):
                super().__init__(noisemaker_owner=owner)
                self.name = name
        image = Image("before", "one")
        config = SimpleNamespace(instance_id="one", output_image_ref="")
        assign_output_image(config, image, images=[image])
        self.assertEqual(resolve_output_image(config, images=[image]), image)
        self.assertTrue(config.output_image_ref)
        image.name = "after"
        self.assertEqual(resolve_output_image(config, images=[image]), image)
        assign_output_image(config, None, images=[image])
        self.assertEqual(config.output_image_ref, "")
        self.assertIsNone(resolve_output_image(config, images=[image]))
        self.assertNotIn("noisemaker_owner", image)

    def test_output_reference_rejects_ambiguous_and_foreign_images(self):
        class Image(dict):
            library = None
            is_float = True
        first = Image(noisemaker_owner="one", noisemaker_image_id="id")
        second = Image(noisemaker_owner="one", noisemaker_image_id="other")
        config = SimpleNamespace(instance_id="one", output_image_ref="id")
        with self.assertRaisesRegex(ValueError, "multiple output Images"):
            resolve_output_image(config, images=[first, second])
        with self.assertRaises(ValueError):
            assign_output_image(config, Image(noisemaker_owner="other"), images=[first])
        second.pop("noisemaker_owner")
        first["noisemaker_image_id"] = "different"
        with self.assertRaisesRegex(ValueError, "identity does not match"):
            resolve_output_image(config, images=[first, second])
        with self.assertRaisesRegex(ValueError, "identity does not match"):
            assign_output_image(config, None, images=[first, second])
        self.assertEqual(first["noisemaker_owner"], "one")
        self.assertEqual(config.output_image_ref, "id")
        config.output_image_ref = ""
        with self.assertRaisesRegex(ValueError, "no saved reference"):
            resolve_output_image(config, images=[first, second])

    def test_rejected_linked_output_assignment_and_clear_leave_markers_unchanged(self):
        class Image(dict):
            library = None
            is_float = True
        image = Image(noisemaker_owner="one", noisemaker_image_id="id")
        config = SimpleNamespace(instance_id="one", output_image_ref="id",
                                 id_data=SimpleNamespace(library=object()))
        for candidate in (None, image):
            with self.assertRaisesRegex(ValueError, "read-only"):
                assign_output_image(config, candidate, images=[image])
            self.assertEqual(config.output_image_ref, "id")
            self.assertEqual(image["noisemaker_owner"], "one")
            self.assertEqual(image["noisemaker_image_id"], "id")

    def test_legacy_reference_migration_deletes_raw_pointer_without_reading_it(self):
        class Config(dict):
            instance_id = "one"
            output_image_ref = ""
            library = None
            def __getitem__(self, key):
                if key == "output_image":
                    raise AssertionError("legacy pointer value must not be read")
                return super().__getitem__(key)
        class Image(dict):
            library = None
            is_float = True
        config = Config(output_image=object())
        image = Image(noisemaker_owner="one")
        migrate_legacy_output_refs([Scene(config)], images=[image])
        self.assertNotIn("output_image", config)
        self.assertEqual(config.output_image_ref, image["noisemaker_image_id"])
        self.assertIs(resolve_output_image(config, images=[image]), image)

    def test_legacy_ambiguous_owner_drops_unsafe_raw_pointer_then_rejects(self):
        class Config(dict):
            instance_id = "one"
            output_image_ref = ""
            library = None
        class Image(dict):
            library = None
            is_float = True
        config = Config(output_image=object())
        images = [Image(noisemaker_owner="one"), Image(noisemaker_owner="one")]
        with self.assertRaisesRegex(ValueError, "multiple output Images"):
            migrate_legacy_output_refs([Scene(config)], images=images)
        self.assertNotIn("output_image", config)
        self.assertEqual(config.output_image_ref, "")

    def test_migration_strips_all_local_raw_pointers_before_owner_validation(self):
        class Config(dict):
            library = None
            output_image_ref = ""
            def __init__(self, instance_id):
                super().__init__(output_image=object())
                self.instance_id = instance_id
        class Image(dict):
            library = None
            is_float = True
        corrupt = Config("a")
        valid = Config("b")
        images = [Image(noisemaker_owner="a"), Image(noisemaker_owner="a"),
                  Image(noisemaker_owner="b")]
        with self.assertRaisesRegex(ValueError, "multiple output Images"):
            migrate_legacy_output_refs([Scene(corrupt, valid)], images=images)
        self.assertNotIn("output_image", corrupt)
        self.assertNotIn("output_image", valid)
        self.assertEqual(valid.output_image_ref, images[2]["noisemaker_image_id"])

    def test_linked_legacy_reference_rejects_without_mutation(self):
        class Config(dict):
            instance_id = "one"
            output_image_ref = ""
            library = None
        config = Config(output_image=object())
        with self.assertRaisesRegex(ValueError, "linked legacy"):
            migrate_legacy_output_refs([Scene(config, library=object())], images=[])
        self.assertIn("output_image", config)

    def test_duplicate_scene_instance_gets_new_identity_and_no_foreign_image(self):
        first = SimpleNamespace(instance_id="shared", output_image="original")
        duplicate = SimpleNamespace(instance_id="shared", output_image="original")
        ensure_unique_ids([Scene(first), Scene(duplicate)])
        self.assertEqual(first.instance_id, "shared")
        self.assertNotEqual(duplicate.instance_id, "shared")
        self.assertIsNone(duplicate.output_image)

    def test_duplicate_repair_clears_pointer_without_reading_it(self):
        class UnsafePointer:
            def __init__(self):
                self.instance_id = "shared"
                self.cleared = False

            @property
            def output_image(self):
                raise AssertionError("nested PointerProperty getter must not run")

            @output_image.setter
            def output_image(self, value):
                self.cleared = value is None

        first = SimpleNamespace(instance_id="shared", output_image="original")
        duplicate = UnsafePointer()
        ensure_unique_ids([Scene(first), Scene(duplicate)])
        self.assertNotEqual(duplicate.instance_id, "shared")
        self.assertTrue(duplicate.cleared)

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

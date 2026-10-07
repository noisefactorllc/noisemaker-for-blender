"""Float publication ownership/precision contracts (native coherence has its own gate)."""
import pathlib
import sys
import types
import unittest
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'blender'))
from noisemaker_blender.integration.images import ImagePublisher


class Pixels:
    def foreach_set(self, values):
        self.values = np.array(values, dtype=np.float32)


class Image(dict):
    def __init__(self, name, width, height, **kwargs):
        super().__init__()
        self.name = name
        self.size = (width, height)
        self.is_float = kwargs['float_buffer']
        self.library = None
        self.pixels = Pixels()
        self.colorspace_settings = types.SimpleNamespace(name='sRGB')
        self.updates = 0

    def scale(self, width, height):
        self.size = (width, height)

    def update(self):
        self.updates += 1


class Images(list):
    def new(self, name, **kwargs):
        used = {image.name for image in self}
        base = name
        index = 1
        while name in used:
            name = '%s.%03d' % (base, index)
            index += 1
        image = Image(name, **kwargs)
        self.append(image)
        return image


class PackedPixels(Pixels):
    def __init__(self, image):
        self.image = image

    def foreach_set(self, values):
        if len(values) != self.image.size[0] * self.image.size[1] * 4:
            raise ValueError('pixel array length differs from Image buffer')
        super().foreach_set(values)


class PackedImage(Image):
    def __init__(self, name, width, height, **kwargs):
        super().__init__(name, width, height, **kwargs)
        self.pixels = PackedPixels(self)
        self.packed_file = None
        self._alpha_mode = 'STRAIGHT'
        self.source = 'GENERATED'

    @property
    def alpha_mode(self):
        return self._alpha_mode

    @alpha_mode.setter
    def alpha_mode(self, value):
        self._alpha_mode = value
        if self.packed_file is not None:
            self.size = self.packed_size  # Packed FILE data reloads on assignment.

    def pack(self):
        self.packed_size = self.size
        self.packed_file = object()
        self.source = 'FILE'


class PackedImages(Images):
    def new(self, name, **kwargs):
        image = PackedImage(name, **kwargs)
        self.append(image)
        return image


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.images = Images()
        self.bpy = types.SimpleNamespace(data=types.SimpleNamespace(images=self.images))

    def publisher(self, owner='one', **kwargs):
        return ImagePublisher(owner, bpy_module=self.bpy, **kwargs)

    def test_raw_hdr_alpha_and_orientation_survive(self):
        source = np.array([[[2., -.25, .0005, .25]], [[.1, .2, .3, .75]]], np.float32)
        image = self.publisher().publish(source, generation=1, provenance={'frame': 42}, name='Clouds')
        np.testing.assert_array_equal(image.pixels.values, np.array([.1, .2, .3, .75, 2., -.25, .0005, .25], dtype=np.float32))
        self.assertEqual(image.colorspace_settings.name, 'Linear Rec.709')
        self.assertEqual(image.alpha_mode, 'PREMUL')
        self.assertEqual(image['noisemaker_generation'], 1)
        self.assertEqual(image['noisemaker_provenance']['frame'], 42)

    def test_stable_pointer_and_buffer_across_updates_and_resize(self):
        pub = self.publisher()
        first = pub.publish(np.zeros((3, 5, 4)), generation=1, name='Clouds')
        buffer = pub.buffer
        first.name = 'User renamed output'
        second = pub.publish(np.ones((3, 5, 4)), generation=2, name='Clouds')
        self.assertIs(first, second)
        self.assertIs(pub.buffer, buffer)
        self.assertEqual(second.updates, 2)
        self.assertEqual(len(self.images), 1)
        resized = pub.publish(np.ones((7, 9, 4)), generation=3)
        self.assertIs(resized, first)
        self.assertEqual(resized.size, (9, 7))

    def test_packed_image_resize_keeps_pointer_and_new_pixel_capacity(self):
        images = PackedImages()
        bpy = types.SimpleNamespace(data=types.SimpleNamespace(images=images))
        image = ImagePublisher('one', bpy_module=bpy).publish(
            np.ones((2, 3, 4)), generation=1)
        image.pack()
        reopened = ImagePublisher('one', image=image, bpy_module=bpy)
        resized = reopened.publish(np.ones((4, 5, 4)), generation=2)
        self.assertIs(resized, image)
        self.assertEqual(resized.size, (5, 4))
        self.assertEqual(len(resized.pixels.values), 5 * 4 * 4)

    def test_name_collision_and_other_instance_are_never_overwritten(self):
        user = self.images.new('Clouds', width=8, height=8, float_buffer=True)
        a = self.publisher().publish(np.zeros((1, 2, 4)), generation=1, name='Clouds')
        b = self.publisher('two', image=a).publish(np.ones((1, 2, 4)), generation=1, name='Clouds')
        self.assertIsNot(a, user)
        self.assertIsNot(a, b)
        self.assertEqual(user.size, (8, 8))
        self.assertEqual(user.updates, 0)
        self.assertEqual(a.updates, 1)

    def test_reconstruction_reuses_owned_image_but_not_linked_image(self):
        image = self.publisher().publish(np.zeros((2, 2, 4)), generation=1)
        self.assertIs(self.publisher(image=image).publish(np.ones((2, 2, 4)), generation=2), image)
        image.library = object()
        replacement = self.publisher(image=image).publish(np.ones((2, 2, 4)), generation=3)
        self.assertIsNot(replacement, image)
        self.assertEqual(image['noisemaker_generation'], 2)

    def test_data_role_and_premultiplied_alpha_are_explicit(self):
        pub = self.publisher(role='data', alpha_mode='PREMUL')
        image = pub.publish(np.ones((1, 1, 4)), generation=7)
        self.assertEqual(image.colorspace_settings.name, 'Non-Color')
        self.assertEqual(image.alpha_mode, 'PREMUL')
        with self.assertRaises(ValueError):
            self.publisher(role='guess')

    def test_invalid_pixels_do_not_destroy_last_good_output(self):
        pub = self.publisher()
        image = pub.publish(np.ones((1, 1, 4)), generation=2)
        for invalid in [np.zeros((2, 2, 3)), np.full((1, 1, 4), np.nan), np.zeros((0, 1, 4))]:
            with self.assertRaises(ValueError):
                pub.publish(invalid, generation=3)
        self.assertEqual(image['noisemaker_generation'], 2)
        self.assertEqual(image.updates, 1)
        np.testing.assert_array_equal(image.pixels.values, [1, 1, 1, 1])


if __name__ == '__main__':
    unittest.main()

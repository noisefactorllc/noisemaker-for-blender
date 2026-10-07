"""Binary cache refuses stale or missing provenance instead of reusing a preview."""
import pathlib
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'blender'))
from noisemaker_blender.runtime.frame_cache import FrameCache, CacheError


def provenance(**changes):
    result = dict(source='abc', inputs='input-v1', parameters='seed=7', frame=42,
                  subframe=0., fps=24., fps_base=1., origin_frame=1,
                  loop_seconds=10., offset=0., width=3, height=2, color_role='color',
                  alpha_mode='STRAIGHT', simulation='fixed:1/24;seed=7', mode='timeline')
    result.update(changes)
    return result


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = FrameCache(self.tmp.name)
        self.pixels = np.full((2, 3, 4), 2.125, np.float32)
        self.pixels[0, 0] = [-.25, .0005, 2.5, .5]

    def test_binary_round_trip_preserves_hdr_and_identity(self):
        path = self.cache.write(self.pixels, provenance())
        self.assertEqual(path.suffix, '.npy')
        np.testing.assert_array_equal(self.cache.read(provenance()), self.pixels)
        self.assertTrue(path.read_bytes().startswith(b'\x93NUMPY'))

    def test_missing_stale_and_free_run_never_fall_back(self):
        self.cache.write(self.pixels, provenance())
        for change in [dict(source='new'), dict(frame=43), dict(subframe=.5),
                       dict(inputs='changed'), dict(parameters='seed=8'), dict(width=5),
                       dict(simulation='fixed:1/60;seed=7'), dict(color_role='data')]:
            with self.assertRaises(CacheError):
                self.cache.read(provenance(**change))
        with self.assertRaises(CacheError):
            self.cache.write(self.pixels, provenance(mode='free_run'))

    def test_missing_identity_fields_and_wrong_shape_fail_before_write(self):
        p = provenance()
        del p['inputs']
        with self.assertRaises(CacheError):
            self.cache.write(self.pixels, p)
        with self.assertRaises(CacheError):
            self.cache.write(self.pixels[:, :1], provenance())
        self.assertEqual(list(pathlib.Path(self.tmp.name).iterdir()), [])

    def test_corrupt_payload_and_metadata_fail_closed(self):
        path = self.cache.write(self.pixels, provenance())
        path.write_bytes(path.read_bytes()[:-2] + b'xx')
        with self.assertRaises(CacheError):
            self.cache.read(provenance())
        self.cache.write(self.pixels, provenance())
        path.with_suffix('.json').write_text('{}')
        with self.assertRaises(CacheError):
            self.cache.read(provenance())

    def test_structured_session_identity_round_trips_typed_values(self):
        identity = provenance(parameters={'solid#0.color': (.2, .4, .6)},
                              inputs={'imageTex_step_0': 'sha256:abc'},
                              simulation={'fixed_step_seconds': None, 'step': 41})
        self.cache.write(self.pixels, identity)
        np.testing.assert_array_equal(self.cache.read(identity), self.pixels)

    def test_preflight_checks_all_requested_frames(self):
        self.cache.write(self.pixels, provenance())
        with self.assertRaises(CacheError):
            self.cache.validate([provenance(), provenance(frame=43)])
        self.cache.write(self.pixels, provenance(frame=43))
        self.assertEqual(len(self.cache.validate([provenance(), provenance(frame=43)])), 2)


if __name__ == '__main__':
    unittest.main()

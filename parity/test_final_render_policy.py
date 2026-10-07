"""Final rendering is exact timeline evaluation and fails before renderer entry."""
import pathlib
import sys
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'blender'))
from noisemaker_blender.integration.render import render_animation, RenderPolicy, RenderPreparationError, PreparedRender, _publish_prepared, render_prepared, prepare_render


class Registry:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail
        self.record = types.SimpleNamespace(config=types.SimpleNamespace(
            instance_id='one', live_enabled=True, output_image=object(), render_width=0,
            render_height=0, origin_frame=1, loop_seconds=10., offset_seconds=0.,
            fixed_step_seconds=0., color_role='color', alpha_mode='STRAIGHT', last_error='', image_name='Output', name='One'))
        registry = self
        class Session:
            def evaluate(self, request):
                registry.events.append(('evaluate', request.frame, request.mode, request.purpose))
                if registry.fail:
                    raise ValueError('invalid source')
                return object()
            def publish_image(self, handle, **kwargs):
                registry.events.append(('publish',))
                return object()
        self.record.session = Session()
        self.record.publisher = types.SimpleNamespace(role='data', alpha_mode='NONE')

    def instances_for_scene(self, scene):
        return [self.record]
    def ensure_session(self, scene, identity, width, height, **kwargs):
        self.events.append(('ensure', width, height, kwargs['force_sync']))
        return self.record
    def current_identity(self, scene, config, request, width, height, role, alpha):
        record = next(record for record in self.instances_for_scene(scene) if record.config == config)
        return record.session.current_identity(request, color_role=role, alpha_mode=alpha)
    def suspend(self, reason):
        self.events.append(('suspend', reason))
    def resume(self, reason):
        self.events.append(('resume', reason))


class Scene:
    name = 'Scene'
    frame_current = 7
    frame_subframe = .25
    render = types.SimpleNamespace(resolution_x=257, resolution_y=129, resolution_percentage=100,
                                   fps=24, fps_base=1., use_lock_interface=False,
                                   use_motion_blur=False, filepath='output.png')
    def frame_set(self, frame, subframe=0.):
        self.frame_current, self.frame_subframe = frame, subframe


class FinalPolicyTests(unittest.TestCase):
    def test_evaluate_publish_then_render_at_final_size_and_restore_scene(self):
        registry = Registry()
        scene = Scene()
        def renderer(scene):
            self.assertEqual(registry.events[-1], ('publish',))
            registry.events.append(('render', scene.frame_current))
            self.assertTrue(scene.render.use_lock_interface)
            return {'FINISHED'}
        result = render_animation(scene, 1, 2, RenderPolicy(), registry=registry, renderer=renderer)
        self.assertEqual(result.frames, (1, 2))
        self.assertEqual([e for e in registry.events if e[0] == 'evaluate'],
                         [('evaluate', 1, 'timeline', 'final'), ('evaluate', 2, 'timeline', 'final')])
        self.assertIn(('ensure', 257, 129, True), registry.events)
        self.assertEqual(registry.record.publisher.role, 'color')
        self.assertEqual(registry.record.publisher.alpha_mode, 'STRAIGHT')
        self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
        self.assertFalse(scene.render.use_lock_interface)
        self.assertEqual(registry.events[-1], ('resume', 'scripted_render'))

    def test_failed_preparation_never_calls_renderer(self):
        registry = Registry(fail=True)
        calls = []
        with self.assertRaises(RenderPreparationError):
            render_animation(Scene(), 1, 2, registry=registry, renderer=lambda scene: calls.append(scene))
        self.assertEqual(calls, [])
        self.assertEqual(registry.events[-1], ('resume', 'scripted_render'))

    def test_cancellation_restores_state_and_stops_later_frames(self):
        registry = Registry()
        result = render_animation(Scene(), 1, 5, registry=registry, renderer=lambda scene: {'CANCELLED'})
        self.assertTrue(result.cancelled)
        self.assertEqual(result.frames, ())
        self.assertEqual(len([e for e in registry.events if e[0] == 'evaluate']), 1)

    def test_prepared_entry_cannot_supply_its_own_current_provenance(self):
        registry = Registry()
        scene = Scene()
        scene.frame_set(1)
        old = dict(source='old', inputs={}, parameters={}, frame=1, subframe=0.,
                   fps=24., fps_base=1., origin_frame=1, loop_seconds=10., offset=0.,
                   width=257, height=129, color_role='color', alpha_mode='PREMUL',
                   simulation={'step': 0}, mode='timeline')
        registry.record.session.current_identity = lambda request, **kwargs: dict(old, source='new')
        prepared = PreparedRender('/not-accessed', ({'instance_id': 'one', 'identity': old},))
        with self.assertRaisesRegex(RenderPreparationError, 'stale'):
            _publish_prepared(scene, prepared, registry)
        self.assertNotIn(('publish',), registry.events)

    def test_all_prepared_instances_are_checked_before_publication(self):
        from unittest.mock import patch
        import copy
        import numpy as np
        registry = Registry()
        scene = Scene()
        scene.frame_set(1)
        first = registry.record
        second = copy.copy(first)
        second.config = copy.copy(first.config)
        second.config.instance_id = 'two'
        second.session = types.SimpleNamespace()
        old = dict(source='old', inputs={}, parameters={}, frame=1, subframe=0.,
                   fps=24., fps_base=1., origin_frame=1, loop_seconds=10., offset=0.,
                   width=257, height=129, color_role='color', alpha_mode='PREMUL',
                   simulation={'step': 0}, mode='timeline')
        first.session.current_identity = lambda request, **kwargs: old
        first.session.generation = 1
        second.session.current_identity = lambda request, **kwargs: dict(old, source='changed')
        registry.instances_for_scene = lambda scene: [first, second]
        registry.ensure_session = lambda scene, identity, *args, **kwargs: first if identity == 'one' else second
        published = []
        first.publisher.publish = lambda *args, **kwargs: published.append('one')
        entries = tuple({'instance_id': identity, 'identity': old, 'generation': 1} for identity in ('one', 'two'))
        with patch('noisemaker_blender.runtime.frame_cache.FrameCache.read', return_value=np.zeros((129,257,4))):
            with self.assertRaisesRegex(RenderPreparationError, 'stale'):
                _publish_prepared(scene, PreparedRender('/unused', entries), registry)
        self.assertEqual(published, [])

    def test_prepared_render_never_constructs_session_and_restores_scene(self):
        from unittest.mock import patch
        registry = Registry()
        scene = Scene()
        published = []
        rendered = []
        prepared = PreparedRender('/unused', tuple(
            {'instance_id': 'one', 'identity': {'frame': frame, 'subframe': 0.}, 'generation': frame}
            for frame in (2, 1)))
        with patch.object(PreparedRender, 'validate', return_value=True), patch(
                'noisemaker_blender.integration.render._publish_prepared',
                side_effect=lambda scene, *_: published.append(scene.frame_current)):
            result = render_prepared(scene, prepared, frames=(2, 1), registry=registry,
                                     renderer=lambda scene: rendered.append(scene.frame_current) or {'FINISHED'})
        self.assertEqual(published, [2, 1])
        self.assertEqual(rendered, [2, 1])
        self.assertEqual(result.path, 'prepared_cache')
        self.assertFalse(any(event[0] == 'ensure' for event in registry.events))
        self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
        self.assertEqual(registry.events[-1], ('resume', 'prepared_render'))

    def test_duplicate_preparation_frames_fail_before_mutation(self):
        registry = Registry()
        with self.assertRaisesRegex(RenderPreparationError, 'unique'):
            prepare_render(Scene(), [1, 1], registry=registry)
        self.assertEqual(registry.events, [])

    def test_motion_blur_is_unqualified_not_silently_integer_frame(self):
        scene = Scene()
        scene.render = types.SimpleNamespace(**vars(Scene.render))
        scene.render.use_motion_blur = True
        with self.assertRaisesRegex(RenderPreparationError, 'motion blur'):
            render_animation(scene, 1, 2, registry=Registry(), renderer=lambda scene: {'FINISHED'})

    def test_prepared_sequence_keeps_cache_read_only_and_cleans_up_after_cancel(self):
        from unittest.mock import patch
        import numpy as np
        import tempfile
        from noisemaker_blender.integration import sequences

        pixels = np.array([[[.25, .5, .75, 1.]]], dtype=np.float32)
        identity = {'frame': 1, 'alpha_mode': 'PREMUL'}
        with tempfile.TemporaryDirectory() as cache_dir:
            cache_path = pathlib.Path(cache_dir)
            original = object()
            user = types.SimpleNamespace(frame_start=8, frame_duration=9,
                                         frame_offset=2, use_auto_refresh=False,
                                         use_cyclic=True)
            saved_user = dict(vars(user))
            node = types.SimpleNamespace(image=original, image_user=user)
            tree = types.SimpleNamespace(nodes=[node], library=None)
            temporary_paths = []
            removed_images = []

            class Pixels:
                def __init__(self, values):
                    self.values = np.asarray(values, dtype=np.float32)
                def foreach_set(self, values):
                    self.values = np.asarray(values, dtype=np.float32).copy()
                def foreach_get(self, values):
                    values[:] = self.values

            class Image:
                def __init__(self, values):
                    self.size = (1, 1)
                    self.pixels = Pixels(values)
                    self.colorspace_settings = types.SimpleNamespace(name='')
                    self.alpha_mode = 'PREMUL'
                    self.source = 'FILE'
                    self.filepath_raw = ''
                def update(self):
                    pass
                def save(self):
                    path = pathlib.Path(self.filepath_raw)
                    self_test.assertNotEqual(path.parent, cache_path)
                    path.write_bytes(self.pixels.values.tobytes())

            class Images:
                def new(self, *args, **kwargs):
                    return Image(np.zeros(4, dtype=np.float32))
                def load(self, path, **kwargs):
                    return Image(np.frombuffer(pathlib.Path(path).read_bytes(), dtype=np.float32))
                def remove(self, image):
                    removed_images.append(image)

            self_test = self
            bpy = types.SimpleNamespace(data=types.SimpleNamespace(images=Images()))
            config = types.SimpleNamespace(output_image=original)
            registry = types.SimpleNamespace(get=lambda _scene, _id: types.SimpleNamespace(config=config))
            prepared = PreparedRender(cache_dir, ({'instance_id': 'one', 'identity': identity},))
            real_temporary_directory = tempfile.TemporaryDirectory

            def temporary_directory(*args, **kwargs):
                result = real_temporary_directory(*args, **kwargs)
                temporary_paths.append(pathlib.Path(result.name))
                return result

            with patch.dict(sys.modules, {'bpy': bpy}), \
                    patch.object(PreparedRender, 'validate', return_value=True), \
                    patch.object(sequences.FrameCache, 'read', return_value=pixels), \
                    patch.object(sequences, '_trees', return_value=(tree,)), \
                    patch.object(tempfile, 'TemporaryDirectory', side_effect=temporary_directory):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    with sequences.prepared_sequences(Scene(), prepared, registry):
                        self.assertIsNot(node.image, original)
                        raise RuntimeError('cancelled')
            self.assertIs(node.image, original)
            self.assertEqual(vars(user), saved_user)
            self.assertEqual(tuple(cache_path.iterdir()), ())
            self.assertEqual(len(temporary_paths), 1)
            self.assertFalse(temporary_paths[0].exists())
            self.assertGreaterEqual(len(removed_images), 3)


if __name__ == '__main__':
    unittest.main()

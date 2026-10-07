"""Explicit, deterministic GPU preparation and scripted scene rendering.

GPU work runs before invoking Blender's render operator, never from a render
handler. This API does not claim that unprepared F12/native animation callbacks
can evaluate GPU programs safely. Prepared binary cache consumption is separate
from fresh GPU evaluation, and multi-state motion blur remains unqualified.
"""
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
import tempfile

from ..runtime.clock import FrameRequest
from ..runtime.frame_cache import FrameCache


class RenderPreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderPolicy:
    cache_directory: str | None = None
    subframe: float = 0.0


@dataclass(frozen=True)
class RenderResult:
    frames: tuple
    cancelled: bool = False
    path: str = 'scripted'


@dataclass(frozen=True)
class PreparedRender:
    directory: str
    entries: tuple
    path: str = 'prepared_cache'

    def validate(self):
        """Verify every payload before beginning cache-based scene rendering."""
        return FrameCache(self.directory).validate(entry['identity'] for entry in self.entries)


def _registry(value):
    if value is not None:
        return value
    from .lifecycle import registry
    return registry


def _validate(scene, policy):
    if getattr(scene.render, 'use_motion_blur', False):
        raise RenderPreparationError('Procedural multi-state motion blur is not qualified')
    if not 0 <= policy.subframe < 1:
        raise RenderPreparationError('Render subframe must be in [0, 1)')


def _request(scene, config, purpose):
    return FrameRequest(frame=scene.frame_current, subframe=scene.frame_subframe,
                        fps=scene.render.fps, fps_base=scene.render.fps_base,
                        origin_frame=config.origin_frame, loop_seconds=config.loop_seconds,
                        offset_seconds=config.offset_seconds,
                        fixed_step_seconds=config.fixed_step_seconds or None,
                        mode='timeline', purpose=purpose)


def _evaluate(scene, registry, *, cache=None):
    entries = []
    for record in registry.instances_for_scene(scene):
        config = record.config
        width = config.render_width or max(1, scene.render.resolution_x * scene.render.resolution_percentage // 100)
        height = config.render_height or max(1, scene.render.resolution_y * scene.render.resolution_percentage // 100)
        try:
            record = registry.ensure_session(scene, config.instance_id, width, height, force_sync=True)
            request = _request(scene, config, 'cache' if cache else 'final')
            output = record.session.evaluate(request)
            record.publisher.role = config.color_role
            record.publisher.alpha_mode = config.alpha_mode
            image = record.session.publish_image(output, publisher=record.publisher,
                                                  name=getattr(config, 'image_name', 'Noisemaker'),
                                                  role=config.color_role, alpha_mode=config.alpha_mode)
            config.output_image = image
            config.last_error = ''
            if cache is not None:
                identity = record.session.cache_identity(request, color_role=config.color_role,
                                                          alpha_mode=config.alpha_mode)
                cache.write(record.session.read_float(output), identity)
                entries.append({'instance_id': config.instance_id, 'identity': identity,
                                'generation': output.generation})
        except Exception as error:
            config.last_error = str(error)
            raise RenderPreparationError('Instance %s: %s' % (config.instance_id, error)) from error
    return entries


def prepare_render(scene, frames, policy=None, *, registry=None):
    """Evaluate exact timeline frames into binary float snapshots on a GPU host.

    Returns an immutable preparation record. It is not an F12 interception hook.
    The record's identities are required when consuming snapshots; stale or
    missing cache data fails before consumer output is rendered.
    """
    policy = policy or RenderPolicy()
    _validate(scene, policy)
    frames = tuple(frames)
    if not frames or any(type(frame) is not int for frame in frames):
        raise RenderPreparationError('Preparation requires integer frame numbers')
    if len(set(frames)) != len(frames):
        raise RenderPreparationError('Preparation frame numbers must be unique')
    registry = _registry(registry)
    directory = policy.cache_directory or tempfile.mkdtemp(prefix='noisemaker-frames-')
    cache = FrameCache(directory)
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    registry.suspend('prepare_render')
    entries = []
    try:
        for frame in frames:
            scene.frame_set(frame, subframe=policy.subframe)
            entries.extend(_evaluate(scene, registry, cache=cache))
        result = PreparedRender(str(Path(directory).resolve()), tuple(entries))
        result.validate()
        return result
    finally:
        try:
            scene.frame_set(old_frame, subframe=old_subframe)
        finally:
            registry.resume('prepare_render')


def publish_cached_frame(publisher, cache, identity, *, generation, name='Noisemaker'):
    """Publish one exact binary cached frame without GPU evaluation.

    Callers supply current source/input/parameter identity, rather than selecting
    a cache frame by number alone. This can run in Blender background mode.
    """
    pixels = cache.read(identity)
    return publisher.publish(pixels, generation=generation, name=name,
                             provenance={'frame': identity['frame'], 'subframe': identity['subframe'],
                                         'source_id': identity['source'], 'path': 'prepared_cache'})


def _publish_prepared(scene, prepared, registry):
    cache = FrameCache(prepared.directory)
    records = {record.config.instance_id: record for record in registry.instances_for_scene(scene)}
    selected = [entry for entry in prepared.entries
                if entry['identity']['frame'] == scene.frame_current
                and entry['identity']['subframe'] == scene.frame_subframe]
    if {entry['instance_id'] for entry in selected} != set(records):
        raise RenderPreparationError('Prepared instances differ from current scene instances')
    if len(selected) != len(records):
        raise RenderPreparationError('Prepared instances contain duplicate frame entries')
    pending = []
    for entry in selected:
        record = records[entry['instance_id']]
        config = record.config
        width = config.render_width or max(1, scene.render.resolution_x * scene.render.resolution_percentage // 100)
        height = config.render_height or max(1, scene.render.resolution_y * scene.render.resolution_percentage // 100)
        request = _request(scene, config, 'cache')
        expected = registry.current_identity(scene, config, request, width, height,
                                             config.color_role, config.alpha_mode)
        # Validate every instance and load every payload before mutating any Image.
        # This path must work after reopening a file without creating a GPU session.
        from ..runtime.frame_cache import _identity
        if _identity(expected)[1] != _identity(entry['identity'])[1]:
            raise RenderPreparationError('Prepared frame is stale for instance %s' % config.instance_id)
        generation = entry.get('generation')
        if type(generation) is not int or generation < 1:
            raise RenderPreparationError('Prepared frame has no valid output generation')
        pending.append((record, expected, generation, cache.read(expected)))
    for record, identity, generation, pixels in pending:
        config = record.config
        if record.publisher is None:
            from .images import ImagePublisher
            record.publisher = ImagePublisher(config.instance_id, image=config.output_image,
                                               role=config.color_role, alpha_mode=config.alpha_mode)
        record.publisher.role = config.color_role
        record.publisher.alpha_mode = config.alpha_mode
        config.output_image = record.publisher.publish(
            pixels, generation=generation, name=config.image_name or config.name,
            provenance={'frame': identity['frame'], 'subframe': identity['subframe'],
                        'source_id': identity['source'], 'path': 'prepared_cache'})
        config.last_error = ''


def render_animation(scene, frame_start, frame_end, policy=None, *, registry=None, renderer=None):
    """Evaluate → publish → render for each frame, with preview mutation suspended.

    This explicit scripted path is qualified independently of Blender's built-in
    animation operator. It never uses free-run preview time or preview resolution.
    """
    policy = policy or RenderPolicy()
    _validate(scene, policy)
    if type(frame_start) is not int or type(frame_end) is not int or frame_end < frame_start:
        raise RenderPreparationError('Render range must be increasing integer frames')
    registry = _registry(registry)
    if renderer is None:
        import bpy
        def renderer(target):
            return bpy.ops.render.render('EXEC_DEFAULT', scene=target.name, write_still=True)
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    old_lock, old_filepath = scene.render.use_lock_interface, scene.render.filepath
    registry.suspend('scripted_render')
    prepared = None
    completed = []
    cancelled = False
    try:
        scene.render.use_lock_interface = True
        if (getattr(scene.render, 'engine', '') == 'CYCLES'
                and getattr(scene.render, 'use_persistent_data', False)):
            prepared = prepare_render(scene, range(frame_start, frame_end + 1), policy, registry=registry)
            from .sequences import prepared_sequences
            consumption = prepared_sequences(scene, prepared, registry)
        else:
            consumption = nullcontext()
        with consumption:
            for frame in range(frame_start, frame_end + 1):
                scene.frame_set(frame, subframe=policy.subframe)
                if prepared is None:
                    _evaluate(scene, registry)
                else:
                    _publish_prepared(scene, prepared, registry)
                scene.render.filepath = old_filepath
                if hasattr(scene.render, 'frame_path'):
                    scene.render.filepath = scene.render.frame_path(frame=frame)
                result = renderer(scene)
                if result != {'FINISHED'}:
                    cancelled = True
                    break
                completed.append(frame)
        return RenderResult(tuple(completed), cancelled)
    finally:
        try:
            scene.render.filepath = old_filepath
            scene.render.use_lock_interface = old_lock
            scene.frame_set(old_frame, subframe=old_subframe)
        finally:
            registry.resume('scripted_render')


def render_prepared(scene, prepared, frames=None, policy=None, *, registry=None, renderer=None):
    """Render verified cached frames without constructing or evaluating GPU state.

    Reopened scene configuration supplies current identity; cache metadata alone
    cannot authorize a stale frame. Prepared Cycles Persistent Data uses the same
    numeric EXR sequence bridge as the scripted GPU preparation path.
    """
    policy = policy or RenderPolicy()
    _validate(scene, policy)
    frames = tuple(sorted({entry['identity']['frame'] for entry in prepared.entries})
                   if frames is None else frames)
    if not frames or any(type(frame) is not int for frame in frames) or len(set(frames)) != len(frames):
        raise RenderPreparationError('Prepared rendering requires unique integer frame numbers')
    prepared.validate()
    registry = _registry(registry)
    if renderer is None:
        import bpy
        def renderer(target):
            return bpy.ops.render.render('EXEC_DEFAULT', scene=target.name, write_still=True)
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    old_lock, old_filepath = scene.render.use_lock_interface, scene.render.filepath
    registry.suspend('prepared_render')
    completed = []
    cancelled = False
    try:
        scene.render.use_lock_interface = True
        if (getattr(scene.render, 'engine', '') == 'CYCLES'
                and getattr(scene.render, 'use_persistent_data', False)):
            from .sequences import prepared_sequences
            consumption = prepared_sequences(scene, prepared, registry)
        else:
            consumption = nullcontext()
        with consumption:
            for frame in frames:
                scene.frame_set(frame, subframe=policy.subframe)
                _publish_prepared(scene, prepared, registry)
                scene.render.filepath = old_filepath
                if hasattr(scene.render, 'frame_path'):
                    scene.render.filepath = scene.render.frame_path(frame=frame)
                result = renderer(scene)
                if result != {'FINISHED'}:
                    cancelled = True
                    break
                completed.append(frame)
        return RenderResult(tuple(completed), cancelled, path='prepared_cache')
    finally:
        try:
            scene.render.filepath = old_filepath
            scene.render.use_lock_interface = old_lock
            scene.frame_set(old_frame, subframe=old_subframe)
        finally:
            registry.resume('prepared_render')

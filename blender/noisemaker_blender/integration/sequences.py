"""Prepared float EXR sequences for Cycles' retained Image texture cache.

No GPU work occurs here. Source frames must already have a verified binary
FrameCache identity. Temporary sequence nodes are installed only for the render
scope and restored afterwards; the owned live Image and all node links survive.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import numpy as np

from ..runtime.frame_cache import FrameCache


def _trees(bpy):
    seen = set()
    candidates = list(bpy.data.node_groups)
    candidates.extend(owner.node_tree for owners in (bpy.data.materials, bpy.data.worlds, bpy.data.scenes)
                      for owner in owners if getattr(owner, 'node_tree', None) is not None)
    for tree in candidates:
        pointer = tree.as_pointer()
        if pointer not in seen:
            seen.add(pointer)
            yield tree


@contextmanager
def prepared_sequences(scene, prepared, registry):
    """Route shader Image users through frame-numbered float cache files.

    Blender identifies sequence frames independently with Persistent Data on;
    updating a generated Image's pixels alone does not invalidate that cache.
    Other consumers keep the stable live Image and receive CPU cache publication
    immediately before each scripted frame.
    """
    import bpy
    from .render import RenderPreparationError
    prepared.validate()
    cache = FrameCache(prepared.directory)
    groups = {}
    for entry in prepared.entries:
        groups.setdefault(entry['instance_id'], []).append(entry['identity'])
    replacements = []
    temporary_images = []
    try:
        for instance_id, entries in groups.items():
            entries.sort(key=lambda item: item['frame'])
            frames = [identity['frame'] for identity in entries]
            if frames != list(range(frames[0], frames[-1] + 1)):
                raise RenderPreparationError('Prepared sequence frames must be contiguous')
            config = registry.get(scene, instance_id).config
            original = config.output_image
            if original is None:
                raise RenderPreparationError('Prepared instance has no output Image')
            # Sequence file numbering starts at one even for negative scene frames.
            stem = hashlib.sha256(instance_id.encode()).hexdigest()[:20]
            paths = []
            writer = None
            try:
                for index, identity in enumerate(entries, 1):
                    pixels = cache.read(identity)
                    height, width = pixels.shape[:2]
                    if writer is None:
                        writer = bpy.data.images.new('Noisemaker cache writer', width=width,
                                                     height=height, alpha=True, float_buffer=True)
                        # Serialization is numeric: no display/input transfer function.
                        writer.colorspace_settings.name = 'Non-Color'
                        writer.alpha_mode = identity['alpha_mode']
                        writer.file_format = 'OPEN_EXR'
                    elif tuple(writer.size) != (width, height):
                        raise RenderPreparationError('A prepared sequence cannot change dimensions')
                    writer.pixels.foreach_set(np.ascontiguousarray(pixels[::-1]).reshape(-1))
                    writer.update()
                    path = Path(prepared.directory) / ('%s_%06d.exr' % (stem, index))
                    writer.filepath_raw = str(path)
                    writer.save()
                    # Inspect the saved transport, not just the source pixel array.
                    check = bpy.data.images.load(str(path), check_existing=False)
                    try:
                        check.colorspace_settings.name = 'Non-Color'
                        decoded = np.empty(pixels.size, np.float32)
                        check.pixels.foreach_get(decoded)
                        # GPU source surfaces default to half floats. EXR transport
                        # must retain every sample within that storage precision.
                        if not np.allclose(decoded.reshape(height,width,4)[::-1], pixels,
                                           atol=1e-6, rtol=1e-3):
                            raise RenderPreparationError('Float EXR cache changed numeric pixels')
                    finally:
                        bpy.data.images.remove(check)
                    paths.append(path)
            finally:
                if writer is not None:
                    bpy.data.images.remove(writer)
            sequence = bpy.data.images.load(str(paths[0]), check_existing=False)
            temporary_images.append(sequence)
            sequence.source = 'SEQUENCE'
            sequence.colorspace_settings.name = 'Non-Color'
            sequence.alpha_mode = entries[0]['alpha_mode']
            for tree in _trees(bpy):
                for node in tree.nodes:
                    if getattr(node, 'image', None) != original or not hasattr(node, 'image_user'):
                        continue
                    if tree.library is not None:
                        raise RenderPreparationError('Prepared rendering cannot modify linked Image nodes')
                    user = node.image_user
                    fields = ('frame_start', 'frame_duration', 'frame_offset', 'use_auto_refresh', 'use_cyclic')
                    saved = {field: getattr(user, field) for field in fields}
                    replacements.append((node, original, saved))
                    node.image = sequence
                    user.frame_start = frames[0]
                    user.frame_duration = len(frames)
                    user.frame_offset = 0
                    user.use_auto_refresh = True
                    user.use_cyclic = False
        yield
    finally:
        for node, original, saved in reversed(replacements):
            try:
                node.image = original
                for field, value in saved.items():
                    setattr(node.image_user, field, value)
            except ReferenceError:
                # A caller may remove a consumer during a canceled scripted render.
                pass
        for image in temporary_images:
            bpy.data.images.remove(image)

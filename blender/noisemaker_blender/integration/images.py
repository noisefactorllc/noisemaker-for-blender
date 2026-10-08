"""Coherent CPU float Image publication; no GPU-only Image storage assumptions."""
from __future__ import annotations

import numpy as np

OWNER = 'noisemaker_owner'
_COLOR_SPACES = {'color': 'Linear Rec.709', 'data': 'Non-Color', 'normal': 'Non-Color'}
_ALPHA_MODES = {'STRAIGHT', 'PREMUL', 'CHANNEL_PACKED', 'NONE'}


class ImagePublisher:
    """Publish top-down scene-linear float RGBA to a stable, instance-owned Image.

    Invoke on Blender's main thread in a qualified context. The caller controls
    scheduling and render barriers. Neither construction nor import requires bpy.
    A supplied image is reused only when it is local, float and owned by this
    instance. Display names are never authority to overwrite a datablock.
    """

    def __init__(self, owner_id, image=None, *, role='color', alpha_mode='PREMUL',
                 bpy_module=None):
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError('Image publication requires a stable instance identity')
        if role not in _COLOR_SPACES:
            raise ValueError('Output role must be color, data or normal')
        if alpha_mode not in _ALPHA_MODES:
            raise ValueError('Unsupported Image alpha mode: %s' % alpha_mode)
        self.owner_id = owner_id
        self.image = image
        self.role = role
        self.alpha_mode = alpha_mode
        self.buffer = None
        self._bpy = bpy_module

    def _owned(self, image):
        try:
            return (image is not None and image.library is None and image.is_float
                    and image.get(OWNER) == self.owner_id)
        except ReferenceError:
            return False

    def publish(self, pixels, *, generation, provenance=None, name='Noisemaker'):
        """Return an updated Image, retaining negative, HDR and alpha samples.

        Validate before mutation. Provenance contains small scalar metadata only;
        pixel payloads stay in the Image's native float buffer.
        """
        values = np.asarray(pixels, dtype=np.float32)
        if (values.ndim != 3 or values.shape[2] != 4 or min(values.shape[:2]) < 1
                or not np.isfinite(values).all()):
            raise ValueError('Image output must be a finite, nonempty HxWx4 float array')
        if not isinstance(generation, int) or generation < 0:
            raise ValueError('Output generation must be a nonnegative integer')
        metadata = dict(provenance or {})
        for key, value in metadata.items():
            if not isinstance(key, str) or not isinstance(value, (str, bool, int, float)):
                raise ValueError('Image provenance must contain only scalar metadata')
        if self._bpy is None:
            import bpy
            self._bpy = bpy
        height, width = values.shape[:2]
        if self.buffer is None or self.buffer.shape != values.shape:
            self.buffer = np.empty(values.shape, dtype=np.float32)
        # Blender Images are bottom-up; GPU capture/session output is top-down.
        np.copyto(self.buffer, values[::-1])
        image = self.image
        if not self._owned(image):
            image = self._bpy.data.images.new(name, width=width, height=height,
                                             alpha=True, float_buffer=True)
            image[OWNER] = self.owner_id
        # Image metadata can reload a packed FILE image at its packed dimensions.
        # Apply it before scale so the last operation establishes pixel capacity.
        color_space = _COLOR_SPACES[self.role]
        if image.colorspace_settings.name != color_space:
            image.colorspace_settings.name = color_space
        image.alpha_mode = self.alpha_mode
        image.use_fake_user = True
        if tuple(image.size) != (width, height):
            image.scale(width, height)
        image.pixels.foreach_set(self.buffer.reshape(-1))
        image.update()
        # Generated Image pixel updates do not invalidate cached Geometry Nodes
        # evaluation. Tag only local trees that sample this Image, keeping their
        # Image socket and consumer links unchanged.
        for tree in getattr(self._bpy.data, 'node_groups', ()):
            if tree.library is not None or tree.bl_idname != 'GeometryNodeTree':
                continue
            if any(node.bl_idname == 'GeometryNodeImageTexture'
                   and node.inputs['Image'].default_value == image for node in tree.nodes):
                tree.update_tag()
        image['noisemaker_generation'] = generation
        image['noisemaker_role'] = self.role
        image['noisemaker_provenance'] = metadata
        self.image = image
        return image

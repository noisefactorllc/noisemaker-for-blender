"""Blender-owned host data adapters for declared runtime input bindings."""

import hashlib
import inspect
import os

from ..runtime.inputs import InputFrame


class UnsupportedHostInput(RuntimeError):
    """The requested host data has no qualified texture conversion."""


class BlenderImageProvider:
    """Borrow a Blender Image's scene-linear GPU texture for one requested frame.

    A movie/sequence must supply a frame resolver because from_image(image)
    takes no ImageUser argument; setting ImageUser.frame_current alone cannot
    establish which frame the shared texture contains.

    Call ``mark_changed`` after editing generated or in-memory pixels. Dirty
    images and changed source-file metadata are detected automatically. The
    returned identity contains content, never a process-local RNA pointer.
    """

    def __init__(self, image, *, frame_provider=None, revision_provider=None,
                 texture_from_image=None):
        self.image = image
        self.frame_provider = frame_provider
        self.revision_provider = revision_provider
        self._texture_from_image = texture_from_image
        self._revision = 0
        self._content_cache = {}

    def mark_changed(self):
        self._revision += 1
        self._content_cache.clear()

    def _content_identity(self, image):
        source = getattr(image, "source", "")
        filepath = getattr(image, "filepath", "") or ""
        try:
            import bpy
            filepath = bpy.path.abspath(filepath) if filepath else ""
        except ImportError:
            pass
        filepath = os.path.abspath(filepath) if filepath else ""
        size = tuple(getattr(image, "size", ()))
        alpha_mode = getattr(image, "alpha_mode", "")
        color_space = getattr(getattr(image, "colorspace_settings", None), "name", "")
        dirty = bool(getattr(image, "is_dirty", False))
        packed = getattr(image, "packed_file", None)
        packed_data = getattr(packed, "data", None) if packed is not None else None
        packed_bytes = bytes(packed_data) if packed_data is not None else None
        packed_digest = hashlib.sha256(packed_bytes).hexdigest() if packed_bytes is not None else None
        stat = None
        if packed_data is None and filepath and os.path.isfile(filepath):
            info = os.stat(filepath)
            stat = (info.st_size, info.st_mtime_ns)
        key = (id(image), source, filepath, size, alpha_mode, color_space,
               stat, packed_digest, self._revision)
        if not dirty and key in self._content_cache:
            return self._content_cache[key]
        digest = hashlib.sha256()
        digest.update(repr((size, alpha_mode, color_space)).encode())
        pixels = getattr(image, "pixels", None)
        if hasattr(pixels, "foreach_get"):
            # Canonical decoded float samples survive a dirty generated Image
            # being packed and reopened under a different byte encoding.
            import numpy as np
            values = np.empty(len(pixels), dtype=np.float32)
            pixels.foreach_get(values)
            digest.update(values.tobytes())
        elif packed_bytes is not None and not dirty:
            digest.update(packed_bytes)
        elif stat is not None and not dirty:
            with open(filepath, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(repr((source, filepath,
                                getattr(image, "name_full", getattr(image, "name", "")),
                                self._revision)).encode())
        result = digest.hexdigest()
        if not dirty:
            self._content_cache[key] = result
        return result

    def source_identity(self):
        return self._content_identity(self.image)

    def _select_image(self, request):
        source = getattr(self.image, "source", None)
        if source in ("MOVIE", "SEQUENCE"):
            if self.frame_provider is None:
                raise UnsupportedHostInput(
                    "movie/sequence input requires an exact-frame image provider")
            image = self.frame_provider(request.frame, request.subframe)
        else:
            image = self.image
        if image is None or len(image.size) < 2 or min(image.size[:2]) < 1:
            raise ValueError("host Image is missing or has no pixels")
        return image

    def _revision_for_image(self, image, request):
        source = getattr(self.image, "source", None)
        has_pixels = hasattr(getattr(image, "pixels", None), "foreach_get")
        revision = (self.revision_provider(image, request) if self.revision_provider
                    else 0 if has_pixels else self._revision)
        frame_token = "%s:%s" % (request.frame, request.subframe) if source in (
            "MOVIE", "SEQUENCE") else "still"
        return "%s:%s:%s" % (self._content_identity(image), frame_token, revision)

    def revision_for(self, request):
        """Check source bytes/pixels and frame identity without creating a GPU texture."""
        return self._revision_for_image(self._select_image(request), request)

    def resolve(self, request):
        image = self._select_image(request)
        if self._texture_from_image is None:
            from gpu.texture import from_image
            texture_from_image = from_image
        else:
            texture_from_image = self._texture_from_image
        texture = texture_from_image(image)
        return InputFrame(
            texture=texture, width=int(image.size[0]), height=int(image.size[1]),
            revision=self._revision_for_image(image, request),
            color_space="scene_linear",
            alpha_mode=("premultiplied" if getattr(image, "alpha_mode", "") == "PREMUL"
                        else "straight"),
        )


class TextTextureProvider:
    """Rasterize text on a qualified Blender GPU context and retain the result."""

    def __init__(self, text, *, width, height, pixel_size=32, font_path=None,
                 rasterizer=None):
        if not isinstance(text, str) or not text:
            raise ValueError("text input must be a nonempty string")
        if min(width, height, pixel_size) < 1:
            raise ValueError("text dimensions and pixel size must be positive")
        self.text = text
        self.width, self.height = width, height
        self.pixel_size = pixel_size
        self.font_path = font_path
        self.rasterizer = rasterizer
        self._offscreen = None
        self._revision = 0
        self._cached = None

    def update(self, text):
        if not isinstance(text, str) or not text:
            raise ValueError("text input must be a nonempty string")
        if text != self.text:
            self.text = text
            self._revision += 1
            self._cached = None

    def source_identity(self):
        return "%s:%s:%s" % (self.text, self.font_path, self._revision)

    def revision_for(self, request):
        return "text:%s" % self._revision

    def resolve(self, request):
        if self._cached is None:
            renderer = self.rasterizer or self._rasterize
            texture = renderer(self.text, self.width, self.height, self.pixel_size,
                               self.font_path)
            if texture is None:
                raise UnsupportedHostInput("text rasterizer produced no GPU texture")
            self._cached = texture
        return InputFrame(self._cached, self.width, self.height,
                          self.revision_for(request), color_space="data",
                          alpha_mode="straight")

    def _rasterize(self, text, width, height, pixel_size, font_path):
        import blf
        import gpu
        from gpu.types import GPUOffScreen

        if self._offscreen is not None:
            self._offscreen.free()
        font_id = blf.load(font_path) if font_path else 0
        offscreen = GPUOffScreen(width, height, format="RGBA16F")
        blend = gpu.state.blend_get()
        viewport = gpu.state.viewport_get()
        try:
            with offscreen.bind():
                gpu.state.active_framebuffer_get().clear(color=(0, 0, 0, 0))
                gpu.state.blend_set("ALPHA_PREMULT")
                gpu.state.viewport_set(0, 0, width, height)
                blf.size(font_id, pixel_size)
                blf.color(font_id, 1, 1, 1, 1)
                blf.position(font_id, 0, max(0, height - pixel_size), 0)
                blf.draw(font_id, text)
        except Exception:
            offscreen.free()
            raise
        finally:
            gpu.state.blend_set(blend)
            gpu.state.viewport_set(*viewport)
            if font_path:
                blf.unload(font_id)
        self._offscreen = offscreen
        return offscreen.texture_color

    def close(self):
        if self._offscreen is not None:
            self._offscreen.free()
            self._offscreen = None
        self._cached = None


class EvaluatedMeshAdapter:
    """Pack evaluated mesh triangles into per-vertex RGBA32F textures."""

    def __init__(self, obj, depsgraph_provider, *, texture_factory=None,
                 max_texture_size=None):
        self.obj = obj
        self.depsgraph_provider = depsgraph_provider
        try:
            inspect.signature(depsgraph_provider).bind(object())
        except (TypeError, ValueError):
            self.historical_exact = False
        else:
            self.historical_exact = True
        self.texture_factory = texture_factory
        self.max_texture_size = max_texture_size
        self._revision = 0
        self._cache_key = None
        self._frames = {}

    def mark_changed(self):
        self._revision += 1
        self._cache_key = None

    def source_identity(self):
        return "%s:%s:%s" % (getattr(self.obj, "name_full", getattr(self.obj, "name", "")),
                              getattr(getattr(self.obj, "data", None), "name_full", ""),
                              self._revision)

    def _upload(self, values):
        if self.texture_factory is not None:
            return self.texture_factory(values)
        from gpu.types import Buffer, GPUTexture
        flat = values.reshape(-1).tolist()
        buffer = Buffer("FLOAT", len(flat), flat)
        return GPUTexture((values.shape[1], values.shape[0]), format="RGBA32F",
                          data=buffer)

    def _pack(self, request, *, upload=True):
        import math
        import numpy as np

        depsgraph = (self.depsgraph_provider(request) if self.historical_exact
                     else self.depsgraph_provider() if callable(self.depsgraph_provider)
                     else self.depsgraph_provider)
        evaluated = self.obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            if callable(getattr(mesh, "calc_loop_triangles", None)):
                mesh.calc_loop_triangles()
            triangles = list(mesh.loop_triangles)
            if not triangles:
                raise ValueError("evaluated mesh has no triangles")
            count = 3 * len(triangles)
            arrays = {name: np.zeros((count, 4), dtype=np.float32)
                      for name in ("positions", "normals", "uvs")}
            uv_data = (mesh.uv_layers.active.data if getattr(mesh.uv_layers, "active", None)
                       else None)
            corners = getattr(mesh, "corner_normals", None)
            for index, triangle in enumerate(triangles):
                for corner, loop_index in enumerate(triangle.loops):
                    item = index * 3 + corner
                    vertex_index = mesh.loops[loop_index].vertex_index
                    vertex = mesh.vertices[vertex_index]
                    normal = (corners[loop_index].vector if corners is not None
                              else vertex.normal)
                    position = tuple(vertex.co)
                    arrays["positions"][item] = (*position, 1.0)
                    arrays["normals"][item] = (*tuple(normal), 1.0)
                    if uv_data is not None:
                        arrays["uvs"][item] = (*tuple(uv_data[loop_index].uv), 0.0, 1.0)
            digest = hashlib.sha256()
            for name in ("positions", "normals", "uvs"):
                digest.update(arrays[name].tobytes())
            revision = "%s:%s:%s:%s" % (digest.hexdigest(), request.frame,
                                         request.subframe, self._revision)
            if not upload:
                return revision
            if self.max_texture_size is None:
                import gpu
                limit = gpu.capabilities.max_texture_size_get()
            else:
                limit = self.max_texture_size
            width = min(count, limit)
            height = math.ceil(count / width)
            if height > limit:
                raise ValueError("evaluated mesh exceeds GPU texture dimensions")
            frames = {
                name: InputFrame(self._upload(np.pad(values, ((0, width * height - count), (0, 0)))
                                              .reshape(height, width, 4)),
                                 width, height, revision,
                                 color_space="data", alpha_mode="none",
                                 vertex_count=count)
                for name, values in arrays.items()
            }
            return frames
        finally:
            evaluated.to_mesh_clear()

    def resolve(self, component, request):
        if component not in ("positions", "normals", "uvs"):
            raise KeyError(component)
        key = (request.frame, request.subframe, self._revision)
        if key != self._cache_key:
            self._frames = self._pack(request)
            self._cache_key = key
        return self._frames[component]

    def revision_for(self, component, request):
        if component not in ("positions", "normals", "uvs"):
            raise KeyError(component)
        key = (request.frame, request.subframe, self._revision)
        if key == self._cache_key:
            return self._frames[component].revision
        return self._pack(request, upload=False)


class MeshTextureProvider:
    def __init__(self, adapter, component):
        if component not in ("positions", "normals", "uvs"):
            raise ValueError("mesh component must be positions, normals or uvs")
        self.adapter = adapter
        self.component = component
        self.historical_exact = adapter.historical_exact

    def resolve(self, request):
        return self.adapter.resolve(self.component, request)

    def revision_for(self, request):
        return self.adapter.revision_for(self.component, request)

    def source_identity(self):
        return "%s:%s" % (self.adapter.source_identity(), self.component)

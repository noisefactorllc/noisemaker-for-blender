"""Declared host texture bindings and dependency ordering."""

import sys
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender import api
from noisemaker_blender.runtime.inputs import InputFrame, UnboundInputError, topological_order
from noisemaker_blender.integration.inputs import (
    BlenderImageProvider, TextTextureProvider, MeshTextureProvider,
    EvaluatedMeshAdapter, UnsupportedHostInput)
from parity.test_render_session import FakeBackend, graph


def media_graph():
    data = graph()
    data["passes"][0]["inputs"] = {
        "imageA": "imageTex_step_0", "imageB": "imageTex_step_1"}
    return data


class RecordingBackend(FakeBackend):
    def set_external_inputs(self, frames):
        self.external_inputs = frames


class InputBindingTests(unittest.TestCase):
    def test_repeated_media_ids_require_independent_named_bindings(self):
        program = api.Program.from_graph("media", media_graph())
        calls = []
        def provider(label):
            def resolve(request):
                calls.append((label, request.frame))
                return InputFrame(texture=object(), width=3, height=2,
                                  revision="%s-%s" % (label, request.frame))
            return resolve
        with api.open_session(program, size=8, backend_factory=RecordingBackend) as session:
            session.bind_input("imageTex_step_0", provider("a"))
            with self.assertRaises(UnboundInputError):
                session.evaluate(api.FrameRequest(frame=1))
            session.bind_input("imageTex_step_1", provider("b"))
            session.evaluate(api.FrameRequest(frame=1))
            self.assertEqual(calls, [("a", 1), ("b", 1)])
            self.assertEqual(set(session.backend.external_inputs),
                             {"imageTex_step_0", "imageTex_step_1"})
            session.evaluate(api.FrameRequest(frame=2))
            self.assertEqual(calls[-2:], [("a", 2), ("b", 2)])

    def test_binding_name_and_frame_shape_are_validated_before_execution(self):
        program = api.Program.from_graph("media", media_graph())
        with api.open_session(program, size=8, backend_factory=RecordingBackend) as session:
            with self.assertRaises(KeyError):
                session.bind_input("imageTex_step_9", lambda req: None)
            session.bind_input("imageTex_step_0", lambda req: InputFrame(
                texture=object(), width=0, height=2, revision=1))
            session.bind_input("imageTex_step_1", lambda req: InputFrame(
                texture=object(), width=3, height=2, revision=1))
            with self.assertRaises(ValueError):
                session.evaluate(api.FrameRequest(frame=1))
            self.assertEqual(session.backend.executions, 0)

    def test_unbind_requires_rebinding_before_next_evaluation(self):
        program = api.Program.from_graph("media", media_graph())
        with api.open_session(program, size=8, backend_factory=RecordingBackend) as session:
            provider = lambda request: InputFrame(object(), 3, 2, 1)
            session.bind_input("imageTex_step_0", provider)
            session.bind_input("imageTex_step_1", provider)
            session.evaluate(api.FrameRequest(frame=1))
            session.unbind_input("imageTex_step_0")
            with self.assertRaises(UnboundInputError):
                session.evaluate(api.FrameRequest(frame=2))

    def test_dependency_order_rejects_current_frame_cycle(self):
        self.assertEqual(topological_order({"a": {"b"}, "b": set()}), ("b", "a"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            topological_order({"a": {"b"}, "b": {"a"}})
        with self.assertRaisesRegex(ValueError, "unknown"):
            topological_order({"a": {"missing"}})

    def test_image_provider_preserves_still_revision_and_resolves_movie_frame(self):
        class Image:
            def __init__(self, pointer, source="FILE"):
                self.size = (5, 3)
                self.source = source
                self.alpha_mode = "PREMUL"
                self.pointer = pointer

            def as_pointer(self):
                return self.pointer

        still = BlenderImageProvider(Image(11), texture_from_image=lambda image: image)
        first = still.resolve(api.FrameRequest(frame=1))
        second = still.resolve(api.FrameRequest(frame=2))
        self.assertEqual(first.revision, second.revision)
        reopened = BlenderImageProvider(Image(999), texture_from_image=lambda image: image)
        self.assertEqual(still.source_identity(), reopened.source_identity())
        self.assertEqual(first.revision, reopened.resolve(api.FrameRequest(frame=1)).revision)
        self.assertEqual(first.alpha_mode, "premultiplied")
        still.mark_changed()
        self.assertNotEqual(first.revision, still.resolve(api.FrameRequest(frame=2)).revision)

        movie = Image(22, "MOVIE")
        with self.assertRaises(UnsupportedHostInput):
            BlenderImageProvider(movie, texture_from_image=lambda image: image).resolve(
                api.FrameRequest(frame=1))
        frames = []
        provider = BlenderImageProvider(
            movie, frame_provider=lambda frame, subframe: frames.append(frame) or Image(frame),
            texture_from_image=lambda image: image)
        self.assertNotEqual(provider.resolve(api.FrameRequest(frame=1)).revision,
                            provider.resolve(api.FrameRequest(frame=2)).revision)
        self.assertEqual(frames, [1, 2])

    def test_cpu_revision_snapshot_never_uploads_image_texture(self):
        image = SimpleNamespace(source="FILE", size=(3, 2), alpha_mode="STRAIGHT",
                                name="Input")
        calls = []
        provider = BlenderImageProvider(
            image, texture_from_image=lambda source: calls.append(source) or object())
        program = api.Program.from_graph("image", media_graph())
        with api.open_session(program, size=8, backend_factory=RecordingBackend) as session:
            session.bind_input("imageTex_step_0", provider)
            session.bind_input("imageTex_step_1", provider)
            request = api.FrameRequest(frame=1)
            revisions = session.inputs.revision_snapshot(request)
            self.assertEqual(len(revisions), 2)
            before = session.current_identity(request)
            self.assertEqual(calls, [])
            session.evaluate(request)
            self.assertEqual(len(calls), 2)
            self.assertEqual(session.cache_identity(request), before)
            self.assertEqual(len(calls), 2)

    def test_packed_image_identity_uses_embedded_bytes(self):
        first = SimpleNamespace(source="FILE", size=(1, 1), alpha_mode="STRAIGHT",
                                name="Packed", packed_file=SimpleNamespace(data=b"one"))
        second = SimpleNamespace(source="FILE", size=(1, 1), alpha_mode="STRAIGHT",
                                 name="Packed", packed_file=SimpleNamespace(data=b"two"))
        self.assertNotEqual(BlenderImageProvider(first).source_identity(),
                            BlenderImageProvider(second).source_identity())

    def test_repacked_image_same_byte_length_invalidates_identity(self):
        packed = SimpleNamespace(data=b"one")
        image = SimpleNamespace(source="FILE", size=(1, 1), alpha_mode="STRAIGHT",
                                name="Packed", packed_file=packed)
        provider = BlenderImageProvider(image)
        before = provider.source_identity()
        packed.data = b"two"
        self.assertNotEqual(provider.source_identity(), before)

    def test_image_color_space_and_alpha_mode_change_identity(self):
        image = SimpleNamespace(source="FILE", size=(1, 1), alpha_mode="STRAIGHT",
                                colorspace_settings=SimpleNamespace(name="sRGB"),
                                name="Input", packed_file=SimpleNamespace(data=b"same"))
        provider = BlenderImageProvider(image)
        original = provider.source_identity()
        image.alpha_mode = "PREMUL"
        alpha_changed = provider.source_identity()
        self.assertNotEqual(original, alpha_changed)
        image.colorspace_settings.name = "Non-Color"
        self.assertNotEqual(provider.source_identity(), alpha_changed)

    def test_generated_image_identity_survives_packing_same_float_samples(self):
        class Pixels:
            def __len__(self): return 4
            def foreach_get(self, target): target[:] = [0.25, 0.5, 0.75, 1.0]
        image = SimpleNamespace(source="GENERATED", size=(1, 1), alpha_mode="PREMUL",
                                colorspace_settings=SimpleNamespace(name="Linear Rec.709"),
                                pixels=Pixels(), is_dirty=True, packed_file=None, name="Input")
        before = BlenderImageProvider(image).source_identity()
        image.is_dirty = False
        image.packed_file = SimpleNamespace(data=b"encoded representation")
        self.assertEqual(BlenderImageProvider(image).source_identity(), before)

    def test_media_uniform_uses_bound_image_dimensions_and_alpha_contract(self):
        program = api.compile("search synth\nmedia().write(o0)\nrender(o0)")
        with api.open_session(program, width=16, height=8,
                              backend_factory=RecordingBackend) as session:
            session.bind_input("imageTex_step_0", lambda request: InputFrame(
                object(), 3, 2, "source", alpha_mode="premultiplied"))
            session.evaluate(api.FrameRequest(frame=1))
            media = next(item for item in session.backend.executed_passes
                         if item.get("func") == "media")
            self.assertEqual(media["uniforms"]["imageSize"], [3, 2])
            self.assertEqual(media["uniforms"]["inputPremultiplied"], 1)

    def test_shader_regeneration_preserves_host_premultiplied_media_path(self):
        converter = Path(__file__).resolve().parents[1] / "tools/convert-shaders-blender.mjs"
        source = """uniform sampler2D imageTex;
uniform vec2 imageSize;
out vec4 fragColor;
vec4 mediaTexel(ivec2 p, ivec2 size) {
    vec4 c = texelFetch(imageTex, clamp(p, ivec2(0), size - 1), 0);
    return vec4(c.rgb * c.a, c.a);
}
void main() { fragColor = mediaTexel(ivec2(0), ivec2(imageSize)); }
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            glsl = root / "reference/shaders/effects/synth/media/glsl"
            glsl.mkdir(parents=True)
            (glsl / "mediaInput.glsl").write_text(source)
            output = root / "output"
            env = dict(os.environ, NM_REFERENCE_ROOT=str(root / "reference"),
                       NM_OUT_DIR=str(output))
            subprocess.run(["node", str(converter), "synth/media"], env=env,
                           check=True, capture_output=True, text=True)
            generated = (output / "synth/media/mediaInput.frag").read_text()
            descriptor = json.loads((output / "synth/media/mediaInput.createinfo.json").read_text())
            self.assertIn("inputPremultiplied != 0 ? c : vec4(c.rgb * c.a, c.a)", generated)
            self.assertIn(["INT", "inputPremultiplied"], descriptor["pushConstants"])

    def test_text_provider_reuses_raster_until_changed(self):
        calls = []
        provider = TextTextureProvider(
            "A", width=6, height=4,
            rasterizer=lambda text, w, h, size, font: calls.append(text) or object())
        request = api.FrameRequest(frame=1)
        first = provider.resolve(request)
        self.assertIs(first.texture, provider.resolve(request).texture)
        self.assertEqual(calls, ["A"])
        provider.update("B")
        self.assertNotEqual(first.revision, provider.resolve(request).revision)
        self.assertEqual(calls, ["A", "B"])

    def test_evaluated_triangle_mesh_packs_positions_and_normals(self):
        class Evaluated:
            def __init__(self):
                self.cleared = 0
                self.mesh = SimpleNamespace(
                    loop_triangles=[SimpleNamespace(loops=(0, 1, 2))],
                    loops=[SimpleNamespace(vertex_index=i) for i in range(3)],
                    vertices=[
                        SimpleNamespace(co=coords, normal=(0, 0, 1))
                        for coords in ((0, 0, 0), (1, 0, 0), (0, 1, 0))],
                    uv_layers=SimpleNamespace(active=None),
                    corner_normals=None,
                )

            def to_mesh(self):
                return self.mesh

            def to_mesh_clear(self):
                self.cleared += 1

        evaluated = Evaluated()
        obj = SimpleNamespace(evaluated_get=lambda depsgraph: evaluated)
        adapter = EvaluatedMeshAdapter(
            obj, depsgraph_provider=object(), max_texture_size=2,
            texture_factory=lambda array: array.copy())
        request = api.FrameRequest(frame=1)
        positions = MeshTextureProvider(adapter, "positions").resolve(request)
        normals = MeshTextureProvider(adapter, "normals").resolve(request)
        self.assertEqual((positions.width, positions.height, positions.vertex_count),
                         (2, 2, 3))
        np.testing.assert_array_equal(positions.texture[0, 1], [1, 0, 0, 1])
        np.testing.assert_array_equal(normals.texture[1, 0], [0, 0, 1, 1])
        self.assertEqual(evaluated.cleared, 1)
        adapter.mark_changed()
        MeshTextureProvider(adapter, "positions").resolve(request)
        self.assertEqual(evaluated.cleared, 2)
        cpu_only = EvaluatedMeshAdapter(obj, depsgraph_provider=object())
        self.assertIsInstance(cpu_only.revision_for("positions", request), str)
        self.assertEqual(evaluated.cleared, 3)

    def test_stateful_mesh_requires_exact_frame_depsgraph_provider(self):
        data = graph()
        data["passes"][0]["inputs"] = {
            "stateTex": "global_state", "positionsTex": "global_mesh0_positions_chain_0"}
        data["passes"][0]["outputs"] = {"color": "global_state"}
        data["passes"].append({"passType": "blit", "inputs": {"src": "global_state"},
                               "outputs": {"color": "global_o0"}})
        adapter = EvaluatedMeshAdapter(object(), depsgraph_provider=object())
        with api.open_session(api.Program.from_graph("mesh-state", data), size=8,
                              backend_factory=RecordingBackend) as session:
            session.bind_input("global_mesh0_positions_chain_0",
                               MeshTextureProvider(adapter, "positions"))
            with self.assertRaisesRegex(ValueError, "exact-frame host input"):
                session.evaluate(api.FrameRequest(frame=2))
            with self.assertRaisesRegex(ValueError, "exact-frame host input"):
                session.current_identity(api.FrameRequest(frame=2))
            self.assertEqual(session.backend.executions, 0)


if __name__ == "__main__":
    unittest.main()

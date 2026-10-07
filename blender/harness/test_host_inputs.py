"""GUI-only native host-input probe; schedule with Blender's main-thread timer.

The harness writes evidence outside the checkout via NMR_INPUT_EVIDENCE.
It must run in a qualified interactive GPU context, never --background.
"""

import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from noisemaker_blender import api
from noisemaker_blender.integration.inputs import (
    BlenderImageProvider, TextTextureProvider, EvaluatedMeshAdapter,
    MeshTextureProvider)


def _image_graph():
    return {
        "renderSurface": "o0",
        "passes": [{
            "passType": "blit",
            "inputs": {"src": "imageTex_step_0"},
            "outputs": {"color": "global_o0"},
        }],
        "textures": {"global_o0": {
            "width": "screen", "height": "screen", "format": "rgba32f"}},
        "allocations": {}, "programs": {},
    }


def run():
    if (os.environ.get("NM_HARNESS_AUTOCLOSE") != "1"
            or "--factory-startup" not in sys.argv):
        raise RuntimeError("host-input probe requires a disposable --factory-startup process")
    record = {"blender": bpy.app.version_string}
    image = bpy.data.images.new("NMR host-input probe", width=3, height=2,
                                alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Linear Rec.709"
    try:
        # Bottom-up Image storage. Unequal corners reveal flips/transposes.
        pixels = np.array([
            [[0.2, 0.3, 0.4, 1], [0.4, 0.5, 0.6, 1], [0.6, 0.7, 0.8, 1]],
            [[0.8, 0.2, 0.1, 1], [0.1, 0.8, 0.2, 1], [0.2, 0.1, 0.8, 1]],
        ], dtype=np.float32)
        image.pixels.foreach_set(pixels[::-1].ravel())
        image.update()
        provider = BlenderImageProvider(image)
        program = api.Program.from_graph("host-image-probe", _image_graph())
        with api.open_session(program, width=3, height=2) as session:
            session.bind_input("imageTex_step_0", provider)
            first = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            record["image_first"] = first.tolist()
            image.pixels.foreach_set((pixels * np.float32([1, 1, 1, 0.5]))[::-1].ravel())
            image.update()
            provider.mark_changed()
            second = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            record["image_second"] = second.tolist()
            record["image_changed"] = bool(np.max(np.abs(second - first)) > 0.01)

        image.alpha_mode = 'PREMUL'
        premul_pixels = np.broadcast_to(
            np.float32([0.4, 0.2, 0.1, 0.5]), (2, 3, 4)).copy()
        image.pixels.foreach_set(premul_pixels[::-1].ravel())
        image.update()
        provider.mark_changed()
        media_program = api.compile("search synth\nmedia().write(o0)\nrender(o0)")
        with api.open_session(media_program, width=3, height=2) as session:
            session.bind_input("imageTex_step_0", provider)
            media = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            record["media_premul_frame"] = media.tolist()
            valid = media[:, :, 3] > 0.25
            record["media_premul"] = bool(valid.any() and np.any(
                np.all(np.abs(media[:, :, :3] - [0.4, 0.2, 0.1]) < 0.04,
                       axis=2) & valid))

        text_program = api.compile(
            'search synth, filter\n'
            'noise().text(text: "A").write(o0)\n'
            'render(o0)')
        text_provider = TextTextureProvider("A", width=128, height=64, pixel_size=48)
        with api.open_session(text_program, width=128, height=64) as session:
            session.bind_input("textTex_step_1", text_provider)
            first = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            text_provider.update("B")
            second = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            record["text_changed"] = bool(np.max(np.abs(second - first)) > 0.01)
            record["text_nonempty"] = bool(np.max(np.abs(first)) > 0.01)
        text_provider.close()
        audio_program = api.compile(
            "search synth\n"
            "solid(alpha: audio(audioBand.low, 0, 1)).write(o0)\n"
            "render(o0)")
        with api.open_session(audio_program, width=4, height=4) as session:
            session.set_external_state(lambda request: (
                {"audio": {"low": 0.25 if request.frame == 1 else 0.75}},
                request.frame))
            first = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
            second = session.read_float(session.evaluate(api.FrameRequest(frame=2)))
            record["audio_changed"] = bool(
                abs(float(first[2, 2, 3]) - 0.25) < 0.01
                and abs(float(second[2, 2, 3]) - 0.75) < 0.01)
        mesh = bpy.data.meshes.new("NMR input triangle")
        mesh.from_pydata([(-0.8, -0.8, 0), (0.8, -0.8, 0), (0, 0.8, 0)],
                         [], [(0, 1, 2)])
        mesh.update()
        obj = bpy.data.objects.new("NMR input triangle", mesh)
        bpy.context.scene.collection.objects.link(obj)
        try:
            mesh_program = api.compile(
                "search render\nmeshLoader().meshRender().write(o0)\nrender(o0)")
            adapter = EvaluatedMeshAdapter(
                obj, depsgraph_provider=lambda: bpy.context.evaluated_depsgraph_get())
            with api.open_session(mesh_program, width=128, height=128) as session:
                session.bind_input("global_mesh0_positions_chain_0",
                                   MeshTextureProvider(adapter, "positions"))
                session.bind_input("global_mesh0_normals_chain_0",
                                   MeshTextureProvider(adapter, "normals"))
                first = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
                mesh.vertices[2].co.x = 0.7
                mesh.update()
                adapter.mark_changed()
                second = session.read_float(session.evaluate(api.FrameRequest(frame=1)))
                record["mesh_changed"] = bool(np.max(np.abs(second - first)) > 0.01)
                record["mesh_nonempty"] = bool(np.max(np.abs(first)) > 0.01)
        finally:
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        if not all(record[key] for key in (
                "image_changed", "text_changed", "text_nonempty",
                "mesh_changed", "mesh_nonempty", "audio_changed",
                "media_premul")):
            raise AssertionError("host input did not alter rendered pixels")
        record["passed"] = True
    except Exception as error:
        record["passed"] = False
        record["error"] = "%s: %s" % (type(error).__name__, error)
        record["traceback"] = traceback.format_exc()
    finally:
        bpy.data.images.remove(image)
        path = Path(os.environ.get("NMR_INPUT_EVIDENCE", "/tmp/nmr-host-inputs.json"))
        path.write_text(json.dumps(record, indent=2))
        # Only the disposable --factory-startup process used by the native probe
        # opts into automatic exit. Never close an existing interactive session.
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":
    bpy.app.timers.register(run, first_interval=1.0)

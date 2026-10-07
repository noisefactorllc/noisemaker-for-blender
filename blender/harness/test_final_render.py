"""Native scripted animation markers, persistent Cycles data and binary preparation."""
import json
import os
from pathlib import Path
import sys
import traceback
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
AUTOCLOSE = os.environ.get('NM_HARNESS_AUTOCLOSE') == '1' and '--factory-startup' in sys.argv
if not AUTOCLOSE:
    raise RuntimeError('Run only in a disposable --factory-startup process with NM_HARNESS_AUTOCLOSE=1')

EVIDENCE = Path(os.environ['NM_EVIDENCE_DIR']).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


def read_center(path):
    assert path.is_file(), 'missing rendered output: %s' % path
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Linear Rec.709'
        width, height = image.size
        values = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape(height, width, 4)[height // 2, width // 2].copy()
    finally:
        bpy.data.images.remove(image)


def run():
    result = {'status': 'failed', 'renders': []}
    try:
        assert not bpy.app.background, 'fresh rendering requires a qualified GUI GPU context'
        import noisemaker_blender
        from noisemaker_blender import api
        from noisemaker_blender.integration.persistence import create_instance
        from noisemaker_blender.integration.lifecycle import registry
        from noisemaker_blender.integration.parameters import BlenderPropertyAdapter
        from noisemaker_blender.integration.materials import attach_material
        from noisemaker_blender.integration.render import render_animation, prepare_render, RenderPolicy
        noisemaker_blender.register()
        scene = bpy.context.scene
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        scene.camera = bpy.data.objects.new('MarkerCamera', bpy.data.cameras.new('MarkerCamera'))
        scene.collection.objects.link(scene.camera)
        scene.camera.location = (0, 0, 3)
        scene.camera.data.type = 'ORTHO'
        scene.camera.data.ortho_scale = 2
        mesh = bpy.data.meshes.new('MarkerPlane')
        mesh.from_pydata([(-2,-2,0), (2,-2,0), (2,2,0), (-2,2,0)], [], [(0,1,2,3)])
        plane = bpy.data.objects.new('MarkerPlane', mesh)
        scene.collection.objects.link(plane)
        material = bpy.data.materials.new('MarkerMaterial')
        material.use_nodes = True
        material.node_tree.nodes.clear()
        plane.data.materials.append(material)
        program = api.compile('search synth\nsolid(color: [0.2,0.4,0.6]).write(o0)\nrender(o0)')
        instance = create_instance(scene, program, name='Marker')
        instance.live_enabled = True
        instance.paused = True
        instance.preview_width = instance.preview_height = 8
        record = registry.ensure_session(scene, instance.instance_id, 32, 32, force_sync=True)
        output = record.session.evaluate(api.FrameRequest(frame=1))
        instance.output_image = record.session.publish_image(output, publisher=record.publisher)
        tex = attach_material(instance, material, instance.output_image)
        emit = material.node_tree.nodes.new('ShaderNodeEmission')
        final = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
        material.node_tree.links.new(tex.outputs['Color'], emit.inputs['Color'])
        material.node_tree.links.new(emit.outputs[0], final.inputs['Surface'])
        prop = BlenderPropertyAdapter.property_name('solid#0.color')
        markers = ([.2,.4,.6], [.6,.1,.3])
        for frame, value in enumerate(markers, 1):
            instance[prop] = value
            instance.keyframe_insert(data_path='["%s"]' % prop, frame=frame)
        for engine, persistent in [('BLENDER_EEVEE', False), ('CYCLES', False), ('CYCLES', True)]:
            scene.render.engine = engine
            scene.render.use_persistent_data = persistent
            if engine == 'CYCLES':
                scene.cycles.samples = 1
            prefix = '%s_%s_' % (engine, int(persistent))
            scene.render.filepath = str(EVIDENCE / (prefix + '####.exr'))
            rendered = render_animation(scene, 1, 2)
            assert rendered.frames == (1, 2) and not rendered.cancelled
            assert tex.image == instance.output_image, 'prepared sequence did not restore live Image'
            assert tex.image.source == 'GENERATED', 'live Image was replaced with file cache'
            for frame, expected in enumerate(markers, 1):
                actual = read_center(EVIDENCE / (prefix + '%04d.exr' % frame))
                np.testing.assert_allclose(actual[:3], expected, atol=.003)
                result['renders'].append(dict(engine=engine, persistent=persistent,
                                              frame=frame, center=actual.tolist()))
        prepared = prepare_render(scene, [2, 1], RenderPolicy(cache_directory=str(EVIDENCE / 'frames')))
        assert len(prepared.validate()) == 2
        result['cache_entries'] = list(prepared.entries)
        bpy.ops.wm.save_as_mainfile(filepath=str(EVIDENCE / 'prepared.blend'))
        result['status'] = 'passed'
        print('FINAL RENDER PASS', len(result['renders']), flush=True)
        registry.shutdown()
        noisemaker_blender.unregister()
    except Exception as error:
        result['error'] = repr(error)
        result['traceback'] = traceback.format_exc()
        print(result['traceback'], flush=True)
    finally:
        (EVIDENCE / 'final_render.json').write_text(json.dumps(result, indent=2) + '\n')
        if AUTOCLOSE:
            bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=.5)

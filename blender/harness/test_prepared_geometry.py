"""Native prepared-cache Geometry Nodes render gate.

Run prepare in a disposable Blender GUI, then consume in a fresh disposable
background process with the same NM_EVIDENCE_DIR. Both processes must use
--factory-startup and NM_HARNESS_AUTOCLOSE=1. The Image socket is assigned
once during setup; later frames change only through render_prepared.
"""
import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import numpy as np

if os.environ.get('NM_HARNESS_AUTOCLOSE') != '1' or '--factory-startup' not in sys.argv:
    raise RuntimeError('Run only in a disposable --factory-startup Blender process')

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
EVIDENCE = Path(os.environ['NM_EVIDENCE_DIR']).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


def _positions(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [list(vertex.co) for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _prepare():
    if bpy.app.background:
        raise RuntimeError('GPU preparation requires a disposable Blender GUI')
    from noisemaker_blender import api
    from noisemaker_blender.integration.geometry import attach_geometry_image
    from noisemaker_blender.integration.lifecycle import registry
    from noisemaker_blender.integration.parameters import BlenderPropertyAdapter
    from noisemaker_blender.integration.persistence import create_instance
    from noisemaker_blender.integration.render import prepare_render, RenderPolicy
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene.render.engine = 'CYCLES'
    scene.render.use_persistent_data = True
    scene.cycles.samples = 1
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '32'
    camera = bpy.data.objects.new('GNCamera', bpy.data.cameras.new('GNCamera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = (0, 0, 5)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 3
    program = api.compile('search synth\nsolid(color: [0.2,0.4,0.6]).write(o0)\nrender(o0)')
    instance = create_instance(scene, program, name='GN marker')
    instance.live_enabled = True
    instance.paused = True
    instance.preview_width = instance.preview_height = 8
    record = registry.ensure_session(scene, instance.instance_id, 16, 16, force_sync=True)
    output = record.session.evaluate(api.FrameRequest(frame=1))
    image = record.session.publish_image(output, publisher=record.publisher)
    instance.output_image = image
    group = bpy.data.node_groups.new('NM_GN_prepared', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    group_input = group.nodes.new('NodeGroupInput')
    group_output = group.nodes.new('NodeGroupOutput')
    texture = attach_geometry_image(instance, group, image)
    texture.inputs['Vector'].default_value = (0.5, 0.5, 0)
    set_position = group.nodes.new('GeometryNodeSetPosition')
    group.links.new(group_input.outputs['Geometry'], set_position.inputs['Geometry'])
    group.links.new(texture.outputs['Color'], set_position.inputs['Offset'])
    group.links.new(set_position.outputs['Geometry'], group_output.inputs['Geometry'])
    mesh = bpy.data.meshes.new('GNPlane')
    mesh.from_pydata([(-.25,-.25,0),(.25,-.25,0),(.25,.25,0),(-.25,.25,0)],
                     [], [(0,1,2,3)])
    obj = bpy.data.objects.new('GNProbePlane', mesh)
    scene.collection.objects.link(obj)
    modifier = obj.modifiers.new('GNImageOffset', 'NODES')
    modifier.node_group = group
    material = bpy.data.materials.new('GNWhite')
    material.diffuse_color = (1,1,1,1)
    obj.data.materials.append(material)
    assert texture.inputs['Image'].default_value == image
    initial = _positions(obj)
    np.testing.assert_allclose(np.array(initial[0]) - [-.25,-.25,0],
                               [.2,.4,.6], atol=.002)
    property_name = BlenderPropertyAdapter.property_name('solid#0.color')
    for frame, value in enumerate(([.2,.4,.6], [.6,.1,.3]), 1):
        instance[property_name] = value
        instance.keyframe_insert(data_path='["%s"]' % property_name, frame=frame)
    prepared = prepare_render(scene, [1,2], RenderPolicy(cache_directory=str(EVIDENCE/'frames')))
    assert len(prepared.validate()) == 2
    assert texture.inputs['Image'].default_value == image
    bpy.ops.wm.save_as_mainfile(filepath=str(EVIDENCE/'gn-prepared.blend'))
    return {'status':'passed', 'blender':bpy.app.version_string,
            'initial_positions':initial, 'cache_entries':list(prepared.entries),
            'image_user_available':hasattr(texture, 'image_user')}


def _consume(result):
    if not bpy.app.background:
        raise RuntimeError('Prepared cache consumption requires background Blender')
    from noisemaker_blender.integration.lifecycle import registry
    from noisemaker_blender.integration.render import PreparedRender, render_prepared
    from noisemaker_blender.runtime.frame_cache import FrameCache
    manifest = json.loads((EVIDENCE/'gn_prepare.json').read_text())
    assert manifest['status'] == 'passed'
    bpy.ops.wm.open_mainfile(filepath=str(EVIDENCE/'gn-prepared.blend'))
    scene = bpy.context.scene
    assert scene.render.engine == 'CYCLES' and scene.render.use_persistent_data
    obj = bpy.data.objects['GNProbePlane']
    texture = next(node for node in bpy.data.node_groups['NM_GN_prepared'].nodes
                   if node.bl_idname == 'GeometryNodeImageTexture')
    config = scene.noisemaker_instances[0]
    original = config.output_image
    assert texture.inputs['Image'].default_value == original
    original_pointer = original.as_pointer()
    registry.ensure_session = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('background created GPU session'))
    entries = manifest['cache_entries']
    prepared = PreparedRender(str(EVIDENCE/'frames'), tuple(entries))
    cache = FrameCache(EVIDENCE/'frames')
    expected = {}
    for entry in entries:
        pixels = cache.read(entry['identity'])
        expected[entry['identity']['frame']] = pixels[
            pixels.shape[0]//2, pixels.shape[1]//2, :3].tolist()
    result.update(blender=bpy.app.version_string,
                  original_image={'name':original.name, 'source':original.source},
                  expected_rgb=expected, runs=[])
    base_vertex = np.array([-.25,-.25,0], dtype=np.float32)
    for label, frames in (('reverse',(2,1)), ('forward',(1,2))):
        scene.render.filepath = str(EVIDENCE/(label+'_####.exr'))
        rows = []
        result['runs'].append({'order':label, 'rows':rows})
        def renderer(target):
            current = texture.inputs['Image'].default_value
            assert current is not None
            owned = config.output_image
            owned_pixels = np.empty(owned.size[0]*owned.size[1]*4, np.float32)
            owned.pixels.foreach_get(owned_pixels)
            center = owned_pixels.reshape(owned.size[1],owned.size[0],4)[
                owned.size[1]//2,owned.size[0]//2,:3]
            before = _positions(obj)
            outcome = bpy.ops.render.render('EXEC_DEFAULT', scene=target.name, write_still=True)
            after = _positions(obj)
            rows.append({'frame':target.frame_current, 'owned_center_rgb':center.tolist(),
                         'socket_source':current.source, 'socket_image':current.name,
                         'socket_pointer':current.as_pointer(),
                         'owned_image_pointer':owned.as_pointer(),
                         'before':before, 'after':after,
                         'render_result':sorted(outcome)})
            return outcome
        rendered = render_prepared(scene, prepared, frames=frames, renderer=renderer)
        assert rendered.frames == frames and not rendered.cancelled
        assert texture.inputs['Image'].default_value.as_pointer() == original_pointer
        for row in rows:
            anticipated = np.array(expected[row['frame']], np.float32)
            observed = np.array(row['after'][0], np.float32) - base_vertex
            row['anticipated_offset'] = anticipated.tolist()
            row['observed_offset'] = observed.tolist()
            row['offset_error_max'] = float(np.max(np.abs(observed-anticipated)))
            row['render_file_exists'] = (EVIDENCE/(label+'_%04d.exr'%row['frame'])).exists()
            np.testing.assert_allclose(row['owned_center_rgb'], anticipated, atol=.01)
            np.testing.assert_allclose(observed, anticipated, atol=.03)
            assert row['render_file_exists']
            assert row['socket_pointer'] == original_pointer
    result['status'] = 'passed'
    return result


def _write_result(name, result):
    (EVIDENCE/name).write_text(json.dumps(result, indent=2)+'\n')


def _run_prepare():
    result = {'status':'failed'}
    try:
        import noisemaker_blender
        noisemaker_blender.register()
        result = _prepare()
        print('GN PREPARE PASS', flush=True)
    except Exception as error:
        result.update(error=repr(error), traceback=traceback.format_exc())
        print(result['traceback'], flush=True)
    finally:
        _write_result('gn_prepare.json', result)
        bpy.ops.wm.quit_blender()


def _run_consume():
    result = {'status':'failed'}
    try:
        import noisemaker_blender
        noisemaker_blender.register()
        result = _consume(result)
        print('GN CONSUME PASS 4', flush=True)
    except Exception as error:
        result.update(error=repr(error), traceback=traceback.format_exc())
        print(result['traceback'], flush=True)
    finally:
        _write_result('gn_consume.json', result)
    if result['status'] != 'passed':
        raise AssertionError('GN prepared render gate failed: %s' % result.get('error'))


phase = os.environ.get('NM_GN_PHASE')
if phase == 'prepare':
    bpy.app.timers.register(_run_prepare, first_interval=.5)
elif phase == 'consume':
    _run_consume()
else:
    raise RuntimeError('Set NM_GN_PHASE=prepare or consume')

"""Prepared binary cache consumption in background Blender; no GPU evaluation."""
import json
import os
from pathlib import Path
import sys

import bpy
import numpy as np

if not bpy.app.background or '--factory-startup' not in sys.argv:
    raise RuntimeError('This gate requires an isolated --background --factory-startup process')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from noisemaker_blender.integration.images import ImagePublisher
from noisemaker_blender.integration.render import publish_cached_frame
from noisemaker_blender.runtime.frame_cache import FrameCache, CacheError

output = Path(os.environ['NM_EVIDENCE_DIR']).resolve()
manifest = json.loads((output / 'final_render.json').read_text())
assert manifest['status'] == 'passed', 'fresh GUI preparation must pass first'
entries = manifest['cache_entries']
assert len(entries) == 2
cache = FrameCache(output / 'frames')
cache.validate(entry['identity'] for entry in entries)
publisher = ImagePublisher('background-cache-test')
for generation, entry in enumerate(entries, 1):
    identity = entry['identity']
    image = publish_cached_frame(publisher, cache, identity, generation=generation)
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    expected = [.2,.4,.6,1] if identity['frame'] == 1 else [.6,.1,.3,1]
    np.testing.assert_allclose(pixels.reshape(height,width,4)[height//2,width//2], expected, atol=.001)
    stale = dict(identity, source='different-program')
    try:
        publish_cached_frame(publisher, cache, stale, generation=generation+1)
    except CacheError:
        pass
    else:
        raise AssertionError('stale frame was consumed')
# Consume the same prepared state in a newly reopened scene and render its
# material in Cycles with Persistent Data, while forbidding session creation.
import noisemaker_blender
from noisemaker_blender.integration.lifecycle import registry
from noisemaker_blender.integration.render import PreparedRender, render_prepared, RenderPreparationError
noisemaker_blender.register()
bpy.ops.wm.open_mainfile(filepath=str(output / 'prepared.blend'))
scene = bpy.context.scene
assert scene.render.engine == 'CYCLES' and scene.render.use_persistent_data
registry.ensure_session = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('background created GPU session'))
scene.render.filepath = str(output / 'background_####.exr')
prepared = PreparedRender(str(output / 'frames'), tuple(entries))
rendered = render_prepared(scene, prepared, frames=[2, 1])
assert rendered.frames == (2, 1) and rendered.path == 'prepared_cache'
for frame in rendered.frames:
    image = bpy.data.images.load(str(output / ('background_%04d.exr' % frame)), check_existing=False)
    try:
        image.colorspace_settings.name = 'Linear Rec.709'
        width, height = image.size
        pixels = np.empty(width*height*4, np.float32)
        image.pixels.foreach_get(pixels)
        expected = [.2,.4,.6] if frame == 1 else [.6,.1,.3]
        np.testing.assert_allclose(pixels.reshape(height,width,4)[height//2,width//2,:3], expected, atol=.003)
    finally:
        bpy.data.images.remove(image)
scene.noisemaker_instances[0].source += '\n// changed source revision'
calls = []
try:
    render_prepared(scene, prepared, frames=[1], renderer=lambda scene: calls.append(scene) or {'FINISHED'})
except RenderPreparationError:
    pass
else:
    raise AssertionError('changed source was accepted for cached scene render')
assert calls == [], 'stale source reached scene renderer'
(output / 'background_cache.json').write_text(json.dumps({
    'status': 'passed', 'frames': list(rendered.frames), 'scene_rendered': True,
    'fresh_gpu_evaluation': False, 'blender': bpy.app.version_string}) + '\n')
print('BACKGROUND CACHE PASS', len(entries), flush=True)

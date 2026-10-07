"""GUI GPU regression for persistent sessions, float output and legacy square parity."""
import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import gpu
import numpy as np

BLENDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BLENDER))
AUTOCLOSE = os.environ.get('NM_HARNESS_AUTOCLOSE') == '1' and '--factory-startup' in sys.argv
if not AUTOCLOSE:
    raise RuntimeError('Run only in a disposable --factory-startup process with NM_HARNESS_AUTOCLOSE=1')

EVIDENCE = Path(os.environ['NM_EVIDENCE_DIR']).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)


def run():
    result = {'status': 'failed', 'checks': []}
    try:
        assert not bpy.app.background, 'requires real GUI GPU context'
        from noisemaker_blender import api
        from noisemaker_blender.backend.gpu_backend import GpuBackend
        from noisemaker_blender.runtime import pipeline
        from noisemaker_blender.integration.images import ImagePublisher
        result['host'] = dict(blender=bpy.app.version_string,
                              gpu=gpu.platform.renderer_get(), backend=gpu.platform.backend_type_get())
        program = api.compile('search synth\nnoise(seed: 7).write(o0)\nrender(o0)')
        request = api.FrameRequest(frame=6, origin_frame=0, fps=24, loop_seconds=1)
        shaders = str(BLENDER / 'noisemaker_blender' / 'shaders' / 'effects')
        legacy = GpuBackend(shaders, 64)
        try:
            expected = pipeline.render(legacy, program.graph(), time=.25, frames=1)
        finally:
            legacy.free()
        with api.open_session(program, size=64) as session:
            handle = session.evaluate(request)
            np.testing.assert_array_equal(session.read_quantized(handle), expected)
            assert session.evaluate(request).generation == handle.generation
            session.set_parameter('noise#0.seed', 8)
            next_handle = session.evaluate(request)
            assert np.any(session.read_quantized(next_handle) != expected)
            try:
                session.read_float(handle)
                raise AssertionError('stale handle accepted')
            except api.StaleOutputError:
                pass
            result['checks'].append('square_legacy_equal_repeated_idempotent_parameter_change_stale_handle')
            session.resize(257, 129)
            resized = session.evaluate(request)
            assert (resized.descriptor.width, resized.descriptor.height) == (257, 129)
            assert session.read_float(resized).shape == (129, 257, 4)
            result['checks'].append('rectangular_257x129')
        solid = api.compile('search synth\nsolid(color: [4.0, -0.5, 0.001], alpha: 0.5).write(o0)\nrender(o0)')
        with api.open_session(solid, width=257, height=129) as session:
            handle = session.evaluate(request)
            floats = session.read_float(handle)
            # Graph storage is half-float. Test its precision, not float32 precision.
            np.testing.assert_allclose(floats[64,128], [2., -.25, .0005, .5], atol=1e-6)
            pub = ImagePublisher('native-session-test')
            image = session.publish_image(handle, publisher=pub)
            pixels = np.empty(floats.size, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            np.testing.assert_array_equal(pixels.reshape(129,257,4)[::-1], floats)
            result['checks'].append('hdr_negative_gradient_alpha_image_raw_equal')
        stateful = api.compile('search synth\nreactionDiffusion().write(o0)\nrender(o0)')
        assert stateful.graph().is_stateful(), 'fixture must exercise replay'
        with api.open_session(stateful, size=32) as sequence:
            for frame in range(1, 8):
                sequential = sequence.evaluate(api.FrameRequest(frame=frame))
            expected_seven = sequence.read_float(sequential).copy()
            at_three = sequence.evaluate(api.FrameRequest(frame=3))
            expected_three = sequence.read_float(at_three).copy()
        with api.open_session(stateful, size=32) as seek:
            jumped = seek.evaluate(api.FrameRequest(frame=7))
            np.testing.assert_array_equal(seek.read_float(jumped), expected_seven)
            rewound = seek.evaluate(api.FrameRequest(frame=3))
            np.testing.assert_array_equal(seek.read_float(rewound), expected_three)
        result['checks'].append('stateful_sequential_jump_and_backward_seek_equal')
        result['status'] = 'passed'
        print('NATIVE SESSION PASS', len(result['checks']), flush=True)
    except Exception as error:
        result['error'] = repr(error)
        result['traceback'] = traceback.format_exc()
        print(result['traceback'], flush=True)
    finally:
        (EVIDENCE / 'render_session.json').write_text(json.dumps(result, indent=2) + '\n')
        if AUTOCLOSE:
            bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=.5)

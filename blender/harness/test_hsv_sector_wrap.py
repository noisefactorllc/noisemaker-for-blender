"""Focused red/green test for feedback's hsv2rgb last-sector hue wrap.

The delivered noisemaker range (8395d1da, 6f98d26a) makes the last hue
sector of every hsv2rgb the else branch, so h = 1.0 renders as h = 0.0
does instead of black. The old code rendered black there, which Mesa
reaches by folding hsv2rgb's fract() into the fract() that wraps
hue + shift before the call. Backends that keep both fract() calls can
never reach h = 1.0 through fract(), so this test pins the fix in two
ways:

  structure  — the transpiled feedback.frag must not guard the last
               sector with `h < 1.0`; the else branch takes h = 1.0.
               This fails against the pre-fix source on every backend.
  render     — the real hsv2rgb from feedback.frag compiles and renders
               on this backend; hues at and just below the wrap point
               (h = 1.0 - 2^-24, h = 1.0) must give the h = 0.0 colour
               within 1/255, and h = 0.25, 0.5, 5/6 their expected
               colours. On a folding backend (Mesa) the old source also
               fails the render checks with black.

Usage: blender --factory-startup --python blender/harness/test_hsv_sector_wrap.py
"""
import os
import re
import sys

import bpy
import gpu
import numpy as np
from gpu.types import GPUOffScreen, GPUShaderCreateInfo
from gpu_extras.batch import batch_for_shader

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HARNESS))
FRAG = os.path.join(REPO, "blender", "noisemaker_blender", "shaders",
                    "effects", "filter", "feedback", "feedback.frag")
W = H = 4
TRI = ((-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0))


def extract_hsv2rgb(text):
    start = text.index("vec3 hsv2rgb(vec3 hsv) {")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]


def last_sector_is_unconditional_else(function_source):
    if re.search(r"5\.0/6\.0 <= h && h < 1\.0", function_source):
        return False
    # The else branch must carry the last sector's assignment.
    return bool(re.search(r"\}\s*else\s*\{\s*rgb = vec3\(c, 0\.0, x\);", function_source))


def draw_hsv(hsv, function):
    # uHsv is declared by the create-info push constant, not in the source.
    frag = (function +
            "void main(){ FragColor = vec4(hsv2rgb(uHsv), 1.0); }\n")
    info = GPUShaderCreateInfo()
    info.push_constant('VEC3', "uHsv")
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_source("void main(){ gl_Position = vec4(pos, 0.0, 1.0); }")
    info.fragment_source(frag)
    sh = gpu.shader.create_from_info(info)
    batch = batch_for_shader(sh, 'TRIS', {"pos": TRI})
    off = GPUOffScreen(W, H, format='RGBA16F')
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.0, 0.0, 0.0, 1.0))
        sh.bind()
        sh.uniform_float("uHsv", hsv)
        batch.draw(sh)
        buf = fb.read_color(0, 0, W, H, 4, 0, 'FLOAT')
    off.free()
    buf.dimensions = W * H * 4
    return np.array(buf, dtype=np.float32).reshape(H, W, 4)[0, 0, :3]


def expected_hsv(hsv):
    # hsv2rgb's own maths for a plain sector hue, in double precision.
    h, s, v = hsv
    c = v * s
    x = c * (1.0 - abs((h * 6.0 % 2.0) - 1.0))
    m = v - c
    table = [(c, x, 0.0), (x, c, 0.0), (0.0, c, x),
             (0.0, x, c), (x, 0.0, c), (c, 0.0, x)]
    sector = int(h * 6.0) % 6
    return np.array(table[sector], dtype=np.float32) + m


def main():
    with open(FRAG, "r", encoding="utf-8") as stream:
        function = extract_hsv2rgb(stream.read())
    fails = []
    if not last_sector_is_unconditional_else(function):
        fails.append("structure: last hue sector is guarded, not the else branch")
    red = np.array(draw_hsv((0.0, 1.0, 1.0), function), dtype=np.float32)
    checks = [
        ("h=1.0-2^-24 wraps to the h=0 colour", (1.0 - 2.0 ** -24, 1.0, 1.0), red),
        ("h=1.0 takes the else branch like h=0", (1.0, 1.0, 1.0), red),
        ("h=0.25 gives its sector colour", (0.25, 1.0, 1.0), None),
        ("h=0.5 gives its sector colour", (0.5, 1.0, 1.0), None),
        ("h=5/6 takes the else branch", (5.0 / 6.0, 1.0, 1.0), None),
    ]
    for name, hsv, expected in checks:
        got = np.array(draw_hsv(hsv, function), dtype=np.float32)
        if expected is None:
            expected = expected_hsv(hsv)
        if np.max(np.abs(got - expected)) > 1.0 / 255.0:
            fails.append("%s: got %s want %s" % (name, got.tolist(), expected.tolist()))
    if fails:
        for line in fails:
            print("HSV-WRAP FAIL: " + line)
        sys.stdout.flush()
        os._exit(1)
    print("HSV-WRAP PASS: structure and renders match the delivered wrap")
    sys.stdout.flush()


if __name__ == "__main__":
    def _run():
        try:
            main()
        except Exception:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            os._exit(1)
        bpy.ops.wm.quit_blender()
        return None
    # GPU drawing is unavailable in background mode; defer until the window
    # context is up, as the other GUI-mode harness tests do.
    bpy.app.timers.register(_run, first_interval=0.5)

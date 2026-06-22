"""De-risk shapeMixer: Metal has no SCALAR reflect/refract (only float2/3/4 + half2/3/4), so
GLSL's scalar reflect(float,float) is "ambiguous". Test injecting the missing scalar overloads
as user functions named reflect/refract:
  - does Blender's GLSL frontend allow user-defining a builtin name with a new signature?
  - does a scalar call then resolve to ours?
  - does a VECTOR call still resolve to the builtin (no new ambiguity from our overload)?

Usage: blender --factory-startup --python blender/harness/spike_reflect.py
"""
import os
import sys
import traceback

import bpy
import gpu
from gpu.types import GPUShaderCreateInfo

SCALAR_OVERLOADS = (
    "float reflect(float I, float N){ return I - 2.0 * (N * I) * N; }\n"
    "float refract(float I, float N, float eta){\n"
    "  float d = N * I;\n"
    "  float k = 1.0 - eta * eta * (1.0 - d * d);\n"
    "  if (k < 0.0) return 0.0;\n"
    "  return eta * I - (eta * d + sqrt(k)) * N;\n}\n")

SCALAR_USE = ("void main(){\n"
              "  float a = gl_FragCoord.x * 0.01, b = gl_FragCoord.y * 0.01;\n"
              "  float r = reflect(a, b);\n"
              "  float t = refract(a, b, 0.5);\n"
              "  fragColor = vec4(r, t, 0.0, 1.0);\n}\n")

VEC_USE = ("void main(){\n"
           "  vec3 a = vec3(gl_FragCoord.x * 0.01), b = vec3(gl_FragCoord.y * 0.01);\n"
           "  vec3 r = reflect(a, b);\n"
           "  vec3 t = refract(a, b, 0.5);\n"
           "  fragColor = vec4(r + t, 1.0);\n}\n")

VARIANTS = [
    ("scalar reflect/refract, NO overloads (REPRO)", SCALAR_USE),
    ("scalar reflect/refract, WITH overloads (FIX)", SCALAR_OVERLOADS + SCALAR_USE),
    ("vector reflect/refract, WITH overloads (no regress)", SCALAR_OVERLOADS + VEC_USE),
]


def compiles(frag):
    info = GPUShaderCreateInfo()
    info.fragment_out(0, 'VEC4', "fragColor")
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_source("void main(){ gl_Position = vec4(pos,0.0,1.0); }")
    info.fragment_source(frag)
    try:
        gpu.shader.create_from_info(info)
        return True, ""
    except Exception as e:
        return False, str(e).splitlines()[0]


def run():
    for name, frag in VARIANTS:
        ok, err = compiles(frag)
        print("SPIKE %-50s -> %s %s" % (name, "OK   " if ok else "FAIL ", "" if ok else err))
    sys.stdout.flush()


if bpy.app.background:
    print("SPIKE FAIL: GPU needs GUI")
else:
    def _t():
        try:
            run()
        except Exception:
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(_t, first_interval=0.5)

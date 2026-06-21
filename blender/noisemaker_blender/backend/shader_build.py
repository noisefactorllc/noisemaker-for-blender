"""Build a Blender GPUShader from a transpiled (.frag + .createinfo.json) pair.

This is the core of the backend's compileProgram step, factored out so the
compile-check harness and the executor share one code path. See PORTING-GUIDE.md.
"""
import gpu
from gpu.types import GPUShaderCreateInfo

# Fullscreen-triangle vertex shader shared by every effect (body uses gl_FragCoord).
VERT_SRC = "void main(){ gl_Position = vec4(pos, 0.0, 1.0); }"


def build_create_info(frag_src, descriptor, defines=None):
    """Assemble a GPUShaderCreateInfo from a transpiled descriptor + body."""
    info = GPUShaderCreateInfo()
    for ctype, name in descriptor.get("pushConstants", []):
        info.push_constant(ctype, name)
    for slot, stype, name in descriptor.get("samplers", []):
        info.sampler(slot, stype, name)
    for slot, otype, name in descriptor.get("fragmentOut", []):
        info.fragment_out(slot, otype, name)
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_source(VERT_SRC)
    header = ""
    if defines:
        header = "".join("#define %s %s\n" % (k, v) for k, v in defines.items())
    info.fragment_source(header + frag_src)
    return info


def build_shader(frag_src, descriptor, defines=None):
    """Compile and return a GPUShader (raises on MSL compile error)."""
    return gpu.shader.create_from_info(build_create_info(frag_src, descriptor, defines))

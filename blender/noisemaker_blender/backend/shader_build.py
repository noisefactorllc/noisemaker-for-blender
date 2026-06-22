"""Build a Blender GPUShader from a transpiled (.frag + .createinfo.json) pair.

This is the core of the backend's compileProgram step, factored out so the
compile-check harness and the executor share one code path. See PORTING-GUIDE.md.
"""
import gpu
from gpu.types import GPUShaderCreateInfo, GPUStageInterfaceInfo

from . import std140

# Fullscreen-triangle vertex shader shared by every effect (body uses gl_FragCoord).
VERT_SRC = "void main(){ gl_Position = vec4(pos, 0.0, 1.0); }"


def _uniforms(info, descriptor):
    """Declare a descriptor's scalar/vector uniforms — either as push constants, or (when the
    block exceeds Metal's 128-byte push-constant limit, descriptor['ubo']) as a std140 uniform
    block. Returns True iff the UBO path was taken (the body then needs its bare uniform refs
    qualified into the block). See backend/std140.py + docs/BLENDER-PLATFORM-NOTES.md."""
    fields = descriptor.get("pushConstants", [])
    if descriptor.get("ubo"):
        info.typedef_source(std140.struct_source(fields))
        info.uniform_buf(0, std140.STRUCT_NAME, std140.INSTANCE)
        return True
    for ctype, name in fields:
        info.push_constant(ctype, name)
    return False


def _header(defines):
    """Compile-time #defines (e.g. NOISE_TYPE) ahead of the body."""
    if not defines:
        return ""
    return "".join("#define %s %s\n" % (k, v) for k, v in defines.items())


def _body(src, is_ubo, descriptor):
    """Load-time GLSL->MSL-compat fix-ups (all no-ops when nothing matches):
      - drop forward prototypes that are later defined (Metal class-member redeclaration);
      - const-qualify `in` array function params (so const global arrays bind under Metal);
      - rename C++ alternative-token identifiers (`or`/`and`/...) — Metal keywords;
      - rename locals shadowing GLSL builtins (`float max = max(...)`) — Blender MSL rejects
        calling a builtin once a same-named local is in scope;
      - vecN==vecN(...) -> all(equal(...)) in bool contexts (compound case the transpiler misses);
      - scalar reflect/refract -> injected nm_reflect/nm_refract (Metal has no scalar overload);
      - for UBO effects, qualify bare uniform refs into the std140 block (scope-aware), last.
    See backend/std140.py + docs/BLENDER-PLATFORM-NOTES.md."""
    src = std140.remove_redundant_prototypes(src)
    src = std140.const_array_params(src)
    src = std140.fix_struct_constructors(src)
    src = std140.rename_cpp_alt_tokens(src)
    src = std140.rename_shadow_builtins(src)
    src = std140.fix_vec_bool_compare(src)
    src = std140.fix_mat2_vector_ctor(src)
    src = std140.fix_scalar_reflect_refract(src)
    if is_ubo:
        src = std140.rewrite_uniform_refs(src, descriptor.get("pushConstants", []))
    return src


def build_create_info(frag_src, descriptor, defines=None):
    """Assemble a GPUShaderCreateInfo from a transpiled descriptor + body."""
    info = GPUShaderCreateInfo()
    is_ubo = _uniforms(info, descriptor)
    for slot, stype, name in descriptor.get("samplers", []):
        info.sampler(slot, stype, name)
    for slot, otype, name in descriptor.get("fragmentOut", []):
        info.fragment_out(slot, otype, name)
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_source(VERT_SRC)
    info.fragment_source(_header(defines) + _body(frag_src, is_ubo, descriptor))
    return info


def build_shader(frag_src, descriptor, defines=None):
    """Compile and return a GPUShader (raises on MSL compile error)."""
    return gpu.shader.create_from_info(build_create_info(frag_src, descriptor, defines))


def build_create_info_vf(vert_src, frag_src, descriptor, defines=None):
    """Assemble a GPUShaderCreateInfo for a vertex+fragment program (points/billboards
    deposit, 3D render). Uses the program's own vertex shader (gl_VertexID-driven) plus a
    vertex->fragment varying interface, instead of the fullscreen-triangle VS."""
    info = GPUShaderCreateInfo()
    is_ubo = _uniforms(info, descriptor)
    for slot, stype, name in descriptor.get("samplers", []):
        info.sampler(slot, stype, name)
    for slot, otype, name in descriptor.get("fragmentOut", []):
        info.fragment_out(slot, otype, name)
    for slot, vtype, name in descriptor.get("vertexIn", []):
        info.vertex_in(slot, vtype, name)
    varyings = descriptor.get("varyings", [])
    if varyings:
        iface = GPUStageInterfaceInfo("nm_iface")
        for interp, vtype, name in varyings:
            getattr(iface, interp)(vtype, name)
        info.vertex_out(iface)
    header = _header(defines)
    info.vertex_source(header + _body(vert_src, is_ubo, descriptor))
    info.fragment_source(header + _body(frag_src, is_ubo, descriptor))
    return info


def build_shader_vf(vert_src, frag_src, descriptor, defines=None):
    """Compile and return a vertex+fragment GPUShader (raises on MSL compile error)."""
    return gpu.shader.create_from_info(build_create_info_vf(vert_src, frag_src, descriptor, defines))

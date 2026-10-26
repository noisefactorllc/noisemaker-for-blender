"""Build a Blender GPUShader from a transpiled (.frag + .createinfo.json) pair.

This is the core of the backend's compileProgram step, factored out so the
compile-check harness and the executor share one code path. See PORTING-GUIDE.md.
"""
import gpu
from gpu.types import GPUShaderCreateInfo, GPUStageInterfaceInfo

from . import std140

# Fullscreen-triangle vertex shader shared by every effect (body uses gl_FragCoord).
VERT_SRC = "void main(){ gl_Position = vec4(pos, 0.0, 1.0); }"

# Cached Metal-backend verdict (fixed per process once a GPU context exists).
_is_metal = None


def _is_metal_backend():
    """True only on Blender's Metal backend (macOS). Under Metal, shader functions become
    class members that are visible regardless of declaration order, so a forward prototype
    is pure redundancy and can be dropped. GL-class backends (OpenGL/Vulkan) have no such
    hoisting: GLSL requires declaration before use, so prototypes must stay."""
    global _is_metal
    if _is_metal is None:
        try:
            from gpu import platform
            _is_metal = platform.backend_type_get() == "METAL"
        except Exception:
            # No GPU context (or probe unavailable): behave like a GL-class backend and
            # keep prototypes — legal under every GLSL compiler.
            _is_metal = False
    return _is_metal


def _uniforms(info, descriptor):
    """Declare a descriptor's scalar/vector uniforms — either as push constants, or (when the
    block exceeds Metal's 128-byte push-constant limit, descriptor['ubo']) as a std140 uniform
    block. Returns True iff the UBO path was taken (the body then needs its bare uniform refs
    qualified into the block). An effect may ALSO declare an explicit `layout(std140) uniform {…}`
    block (descriptor['uniformBlock'], remap's zone-config `vec4 data[267]`); that is emitted as a
    second uniform_buf ALONGSIDE the push constants. See backend/std140.py + docs/BLENDER-PLATFORM-NOTES.md."""
    fields = descriptor.get("pushConstants", [])
    if descriptor.get("ubo"):
        info.typedef_source(std140.struct_source(fields))
        info.uniform_buf(0, std140.STRUCT_NAME, std140.INSTANCE)
        return True
    for ctype, name in fields:
        info.push_constant(ctype, name)
    blk = descriptor.get("uniformBlock")
    if blk:
        # an explicit `layout(std140) uniform {…}` block (remap's zone-config UBO), bound ALONGSIDE
        # the push constants. Verified to coexist by spike_remap_ubo.py.
        info.typedef_source(std140.block_struct_source(blk))
        info.uniform_buf(0, blk["struct"], blk["instance"])
    return False


def _header(defines):
    """Compile-time #defines (e.g. NOISE_TYPE) ahead of the body."""
    if not defines:
        return ""
    return "".join("#define %s %s\n" % (k, v) for k, v in defines.items())


def _int_condition_names(defines, descriptor, is_ubo):
    """Identifiers provably int-typed in this shader, for fix_int_bool_conditions.

    Sources: pass defines with int values (e.g. render3d's INVERT/FILTERING), INT/UINT push
    constants, and — under the UBO path — BOOL push constants too (the std140 block materializes
    them as int members, so `if (nm_ub.wrap)` is an int condition there)."""
    names = set()
    for name, value in (defines or {}).items():
        if isinstance(value, int) and not isinstance(value, bool):
            names.add(name)
    for ctype, name in descriptor.get("pushConstants", []):
        if ctype in ("INT", "UINT") or (is_ubo and ctype == "BOOL"):
            names.add(name)
    blk = descriptor.get("uniformBlock") or {}
    for ctype, _name, _count in blk.get("members", []):
        if ctype in ("int", "uint", "bool"):
            names.add(_name)
    return names


def _body(src, is_ubo, descriptor, defines=None):
    """Load-time GLSL->MSL-compat fix-ups (all no-ops when nothing matches):
      - drop source-level `uniform sampler2D` / `layout(location) out vec4` declarations that
        the descriptor already declares (the synced agent shaders keep the raw upstream lines);
      - drop forward prototypes that are later defined, Metal backend only (Metal class-member
        redeclaration; GL-class backends keep them — GLSL needs declaration before use);
      - const-qualify `in` array function params (so const global arrays bind under Metal);
      - rename C++ alternative-token identifiers (`or`/`and`/...) — Metal keywords;
      - rename locals shadowing GLSL builtins (`float max = max(...)`) — Blender MSL rejects
        calling a builtin once a same-named local is in scope;
      - vecN==vecN(...) -> all(equal(...)) in bool contexts (compound case the transpiler misses);
      - scalar reflect/refract -> injected nm_reflect/nm_refract (Metal has no scalar overload);
      - packHalf2x16/unpackHalf2x16 -> injected polyfill (no MSL-codegen builtin under either name);
      - conditions on provably-int names (`if (INVERT)`, `if (nm_ub.wrap)`) -> explicit `!= 0`
        comparisons — Metal's C++ semantics accept the implicit conversion, GL does not;
      - for UBO effects, qualify bare uniform refs into the std140 block (scope-aware);
      - for an explicit `layout(std140)` block (remap), qualify its member refs -> <instance>.<member>.
    See backend/std140.py + docs/BLENDER-PLATFORM-NOTES.md."""
    src = std140.strip_descriptor_declared(src, descriptor)
    src = std140.remove_redundant_prototypes(src, keep_prototypes=not _is_metal_backend())
    src = std140.const_array_params(src)
    src = std140.fix_struct_constructors(src)
    src = std140.rename_cpp_alt_tokens(src)
    src = std140.rename_shadow_builtins(src)
    src = std140.fix_vec_bool_compare(src)
    src = std140.fix_mat2_vector_ctor(src)
    src = std140.fix_scalar_reflect_refract(src)
    src = std140.inject_pack_half2x16(src)
    if is_ubo:
        src = std140.rewrite_uniform_refs(src, descriptor.get("pushConstants", []))
    src = std140.fix_int_bool_conditions(src, _int_condition_names(defines, descriptor, is_ubo))
    blk = descriptor.get("uniformBlock")
    if blk:                                    # qualify the block's member refs -> <instance>.<member>
        members = [(t, n) for t, n, _c in blk["members"]]
        src = std140.rewrite_uniform_refs(src, members, instance=blk["instance"])
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
    info.fragment_source(_header(defines) + _body(frag_src, is_ubo, descriptor, defines))
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
    info.vertex_source(header + _body(vert_src, is_ubo, descriptor, defines))
    info.fragment_source(header + _body(frag_src, is_ubo, descriptor, defines))
    return info


def build_shader_vf(vert_src, frag_src, descriptor, defines=None):
    """Compile and return a vertex+fragment GPUShader (raises on MSL compile error)."""
    return gpu.shader.create_from_info(build_create_info_vf(vert_src, frag_src, descriptor, defines))

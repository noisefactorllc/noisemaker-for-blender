"""std140 uniform-block layout + packing for the UBO path (PUSH_OVER_128 effects).

Effects whose push-constant block exceeds Metal's 128-byte limit are compiled with a std140
uniform buffer instead of push constants (see docs/BLENDER-PLATFORM-NOTES.md). This module is
the single source of truth for the block layout, shared by:
  - shader_build  — generates the GLSL struct typedef + the bare-name #defines, and
  - gpu_backend   — packs the uniform values into the matching std140 byte buffer.

Verified against Blender's actual struct layout by blender/harness/spike_ubo*.py (the std140
alignment traps — vec3 to 16, vec2 to 8 after a vec3 — land exactly where this computes them).
"""
import struct as _struct

import numpy as np

# std140 alignment/size in bytes. BOOL is declared as `int` in the block: std140 bool is a
# 4-byte uint but MSL bool is 1 byte, so declaring int avoids the cross-compiler ambiguity;
# the bare-name #define then expands a bool field to `(nm_ub.x != 0)` (a real bool expr).
_ALIGN = {"FLOAT": 4, "INT": 4, "BOOL": 4, "VEC2": 8, "VEC3": 16, "VEC4": 16,
          "IVEC2": 8, "IVEC3": 16, "IVEC4": 16}
# SIZE: a vec3 occupies 16 bytes here, NOT std140's 12. Blender's GLSL->MSL maps vec3 -> Metal
# `float3`, which is 16 bytes — so a scalar following a vec3 lands at +16, not +12. Using 12
# (textbook std140) silently shifts every field after the first vec3->scalar boundary (verified
# the hard way: noise's `wrap`/palette params read from the wrong offset — spike_ubo4.py).
_SIZE = {"FLOAT": 4, "INT": 4, "BOOL": 4, "VEC2": 8, "VEC3": 16, "VEC4": 16,
         "IVEC2": 8, "IVEC3": 16, "IVEC4": 16}
_GLSL = {"FLOAT": "float", "INT": "int", "BOOL": "int", "VEC2": "vec2", "VEC3": "vec3",
         "VEC4": "vec4", "IVEC2": "ivec2", "IVEC3": "ivec3", "IVEC4": "ivec4"}

STRUCT_NAME = "NmUniforms"
INSTANCE = "nm_ub"


def layout(fields):
    """fields: [(ctype, name)] in declaration order. Returns (entries, nfloats) where
    entries = [(ctype, name, byte_offset)] and nfloats = block size in floats (the block size
    is rounded up to a multiple of 16 bytes per std140)."""
    off = 0
    entries = []
    for ctype, name in fields:
        a = _ALIGN[ctype]
        off = (off + a - 1) // a * a
        entries.append((ctype, name, off))
        off += _SIZE[ctype]
    size = (off + 15) // 16 * 16
    return entries, size // 4


def struct_source(fields):
    """The GLSL struct typedef for these fields (declaration order)."""
    body = "".join("  %s %s;\n" % (_GLSL[t], n) for t, n in fields)
    return "struct %s {\n%s};\n" % (STRUCT_NAME, body)


# GLSL type keywords — a uniform name immediately preceded by one is a *declaration*
# (a local/param that shadows the uniform), not a reference to rewrite.
_TYPE_KW = frozenset((
    "float", "int", "bool", "uint", "double", "void",
    "vec2", "vec3", "vec4", "ivec2", "ivec3", "ivec4",
    "uvec2", "uvec3", "uvec4", "bvec2", "bvec3", "bvec4",
    "mat2", "mat3", "mat4", "mat2x2", "mat3x3", "mat4x4",
    "sampler2D", "sampler3D", "samplerCube", "isampler2D", "usampler2D"))

_TOKEN = __import__("re").compile(r"//[^\n]*|/\*.*?\*/|[A-Za-z_]\w*|\s+|.", __import__("re").DOTALL)

# GLSL builtin functions the corpus shadows with local variables, e.g. the inlined rgb->hsl
# helper's `float max = max(r, max(g, b)); float min = min(r, min(g, b));`. Blender's MSL
# backend rejects calling a builtin once a same-named local is in scope ("called object type
# 'float' is not a function"); ANGLE (the reference path) accepts it. We rename the LOCAL.
_SHADOWABLE = frozenset(("max", "min", "mod", "mix", "clamp", "step", "smoothstep",
                         "fract", "abs", "sign", "floor", "ceil", "round"))


# C++ alternative tokens (Metal compiles GLSL as C++): these are keywords there, so a GLSL
# function/variable named `or`/`and`/... fails with "expected member name or ';'". None are GLSL
# keywords or used builtins here, so renaming the identifier (not comments/members) is safe.
_CPP_ALT_TOKENS = frozenset(("and", "or", "xor", "not", "bitand", "bitor", "compl",
                             "and_eq", "or_eq", "xor_eq", "not_eq"))

# vecN ==/!= vecN comparisons: GLSL says these are a SCALAR bool, but Blender MSL makes a bvecN
# (rejected in bool contexts: `||`, `&&`, `?:`, `if`). Rewrite to all(equal(...))/any(notEqual)),
# exactly equivalent. Type-lite: an operand is a vector if it's a vecN(...) constructor, a
# >=2-char swizzle, or an identifier declared `vecN name` somewhere in the source. Only rewrite
# when BOTH operands are vectors — scalar `a == 1.0` / `coord.x == 1.0` stay untouched.
_VEC_DECL = __import__("re").compile(r"\bi?vec[234]\s+([A-Za-z_]\w*)")
# Constructor alternative FIRST so `vec2(1.0)` matches as a whole, not as the bare ident `vec2`.
_OPERAND = r"(?:i?vec[234]\s*\([^()]*\)|[A-Za-z_][\w.]*)"
_VEC_CMP = __import__("re").compile(r"(%s)\s*(==|!=)\s*(%s)" % (_OPERAND, _OPERAND))
_SWIZZLE = set("xyzwrgbastpq")


def _is_vec_operand(op, vecvars):
    op = op.strip()
    if __import__("re").match(r"i?vec[234]\s*\(", op):
        return True
    if "." in op:
        sw = op.rsplit(".", 1)[1]
        return len(sw) >= 2 and all(c in _SWIZZLE for c in sw)
    return op in vecvars


def fix_vec_bool_compare(src):
    """vecN ==/!= vecN -> all(equal(...)) / any(notEqual(...)) (incl. var==var like cellSplit's
    `cellId == nearestCell` and compound `a==vec2(1)||a==vec2(3)` like colorLab). The transpiler's
    fixVecBoolTernary only catches the single-compare-before-`?` constructor case."""
    vecvars = set(_VEC_DECL.findall(src))

    def repl(m):
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        if _is_vec_operand(lhs, vecvars) and _is_vec_operand(rhs, vecvars):
            return ("all(equal(%s, %s))" if op == "==" else "any(notEqual(%s, %s))") \
                % (lhs.strip(), rhs.strip())
        return m.group(0)
    return _VEC_CMP.sub(repl, src)


# mat2 built from a leading vec2 + scalars, e.g. fractal's `mat2(z, -z.y, z.x)`. Metal rejects
# the mixed vec2+float+float constructor; expand the vec2 to components. A 3-arg mat2 => its
# first arg supplies 2 components (the vec2). 4-scalar `mat2(c,-s,s,c)` has 4 args -> no match.
_MAT2_3ARG = __import__("re").compile(
    r"\bmat2\s*\(\s*([A-Za-z_]\w*)\s*,([^,()]+),([^,()]+)\)")


def fix_mat2_vector_ctor(src):
    """mat2(vec2, x, y) -> mat2(vec2.x, vec2.y, x, y) (Metal has no mixed vec2+scalar mat2 ctor)."""
    return _MAT2_3ARG.sub(
        lambda m: "mat2(%s.x, %s.y,%s,%s)" % (m.group(1), m.group(1), m.group(2), m.group(3)), src)


# GLSL struct constructors `Foo(a, b)` — Blender's MSL backend emits a C++ ctor call but never
# generates the constructor ("no matching constructor for initialization of 'Foo'"). For each
# `struct Foo { T a; U b; };` we inject a maker fn and rewrite the calls (e.g. newton's POIData).
_STRUCT_DEF = __import__("re").compile(r"\bstruct\s+([A-Za-z_]\w*)\s*\{([^{}]*)\}\s*;")
_STRUCT_FIELD = __import__("re").compile(r"\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*;")


def fix_struct_constructors(src):
    """`Foo(a, b)` -> `nm_make_Foo(a, b)` with an injected `Foo nm_make_Foo(T a, U b){ Foo r;
    r.a=a; r.b=b; return r; }` after each `struct Foo { T a; U b; };`. The `\\bFoo\\s*\\(` rewrite
    hits only constructor calls — never the struct def, a `Foo var` decl, or a `Foo f(...)` return
    type (no `(` directly after the name there), nor the maker (preceded by `nm_make_`)."""
    structs = []
    inserts = []
    for m in _STRUCT_DEF.finditer(src):
        name, body = m.group(1), m.group(2)
        fields = _STRUCT_FIELD.findall(body)
        if not fields:
            continue
        params = ", ".join("%s %s" % (t, n) for t, n in fields)
        assigns = " ".join("r.%s=%s;" % (n, n) for _, n in fields)
        inserts.append((m.end(), "\n%s nm_make_%s(%s){ %s r; %s return r; }"
                        % (name, name, params, name, assigns)))
        structs.append(name)
    if not structs:
        return src
    for pos, maker in sorted(inserts, reverse=True):   # back-to-front keeps offsets valid
        src = src[:pos] + maker + src[pos:]
    for name in structs:
        src = __import__("re").sub(r"\b%s\s*\(" % name, "nm_make_%s(" % name, src)
    return src


# Array-typed function parameters. Blender lowers `vec3 pal[4]` to a mutable `vec3*`, but the
# corpus passes `const` global arrays to them (dither's palettes) -> "cannot initialize a parameter
# of type 'vec3 *' with an lvalue of type 'const vec3[4]'". GLSL default (`in`) array params are
# read-only copies, so const-qualifying them is semantically exact and lets the const arg bind.
# Matches an array param right after a `(`/`,` separator (locals/globals start a statement, not a
# param list, so they're never touched); existing const/out/inout params are left as-is. Verified
# by spike_dither.py (non-const REPRO fails, const FIX compiles).
_ARRAY_PARAM = __import__("re").compile(
    r"([,(]\s*)((?:const\s+|in\s+|out\s+|inout\s+)*)"
    r"((?:i?vec[234]|u?vec[234]|bvec[234]|float|int|uint|bool|mat[234])\s+\w+\s*\[)")


def const_array_params(src):
    """Const-qualify `in` (unqualified) array function parameters so a `const` global array binds.
    A no-op for out/inout/already-const params and for anything not in a parameter list."""
    def repl(m):
        sep, quals, decl = m.group(1), m.group(2), m.group(3)
        if "const" in quals or "out" in quals:        # 'out' also matches 'inout'
            return m.group(0)
        return sep + "const " + quals + decl
    return _ARRAY_PARAM.sub(repl, src)


# Function prototypes (`T name(args);`) that are later DEFINED. Blender wraps every function as a
# member of one MSL class, where a prototype + definition is "class member cannot be redeclared"
# (ANGLE accepts it; members are visible regardless of order, so the prototype is pure redundancy).
# Anchored at line start with a real return type, so call statements (`return foo(x);`) never match.
_PROTO_LINE = __import__("re").compile(
    r"^[ \t]*(?:i?vec[234]|u?vec[234]|bvec[234]|float|int|uint|bool|void|mat[234])"
    r"\s+(\w+)\s*\([^()]*\)\s*;[ \t]*\n", __import__("re").M)


def remove_redundant_prototypes(src):
    """Drop a forward prototype when the same function is defined later (the definition stands on
    its own under Metal). Leaves prototypes with no in-file definition untouched. (dither.)"""
    def repl(m):
        name = m.group(1)
        if __import__("re").search(r"\b%s\s*\([^()]*\)\s*\{" % __import__("re").escape(name), src):
            return ""
        return m.group(0)
    return _PROTO_LINE.sub(repl, src)


# Scalar reflect/refract. Metal's geometric library defines reflect/refract ONLY for float2/3/4
# and half2/3/4 — there is NO scalar overload — so GLSL's legal `reflect(float, float)` is
# "ambiguous" (a float promotes to any of the vector types). We inject scalar helpers and rewrite
# ONLY the calls we can prove are scalar; vector calls keep the builtin (distortion/lighting and
# shapeMixer's vec3 blend stay byte-identical). De-risked by spike_reflect.py (naming them
# `reflect` HIDES the builtin and breaks the vector calls, so they must be nm_*-named + targeted).
_VEC_TYPES = frozenset(("vec2", "vec3", "vec4", "ivec2", "ivec3", "ivec4",
                        "uvec2", "uvec3", "uvec4", "bvec2", "bvec3", "bvec4"))
_REFLECT_HELPERS = (
    "\nfloat nm_reflect(float I, float N){ return I - 2.0 * (N * I) * N; }\n"
    "float nm_refract(float I, float N, float eta){ float d = N * I;\n"
    "  float k = 1.0 - eta * eta * (1.0 - d * d);\n"
    "  if (k < 0.0) return 0.0;\n"
    "  return eta * I - (eta * d + sqrt(k)) * N; }\n")


def fix_scalar_reflect_refract(src):
    """Rewrite scalar reflect/refract calls to injected nm_reflect/nm_refract (Metal has no scalar
    overload). An arg is classified with SCOPE-LOCAL types (the same name is vec3 in one overload
    and float in another, e.g. shapeMixer's two `blend`s), and a call is rewritten only when its
    first arg is *provably* scalar — a known scalar var, a single-component swizzle, or a numeric
    literal. Unknown/vector args keep the builtin, so working vector calls are never broken."""
    if "reflect" not in src and "refract" not in src:
        return src
    toks = [m.group(0) for m in _TOKEN.finditer(src)]
    n = len(toks)

    def is_ws(t):
        return t.startswith("//") or t.startswith("/*") or (t != "" and t.isspace())

    def nxt(i):
        j = i + 1
        while j < n and is_ws(toks[j]):
            j += 1
        return j

    scopes = [{}]        # stack of {name: is_vector}
    pending = {}         # params declared in current () -> enter next {}
    paren = 0
    last_sig = None
    member_next = False
    changed = False

    def lookup(name):
        for s in reversed(scopes):
            if name in s:
                return s[name]
        return None      # unknown

    i = 0
    while i < n:
        t = toks[i]
        if is_ws(t):
            i += 1
            continue
        if t == "{":
            scopes.append(dict(pending)); pending = {}; last_sig = "{"; member_next = False
        elif t == "}":
            if len(scopes) > 1:
                scopes.pop()
            last_sig = "}"; member_next = False
        elif t == "(":
            paren += 1; last_sig = "("; member_next = False
        elif t == ")":
            paren = max(0, paren - 1); last_sig = ")"; member_next = False
        elif t == ";":
            pending = {}; last_sig = ";"; member_next = False
        elif t == ".":
            last_sig = "."; member_next = True
        elif t[:1].isalpha() or t[:1] == "_":
            if member_next:
                member_next = False; last_sig = t
            elif last_sig in _TYPE_KW:                         # declaration: `TYPE t`
                (pending if paren > 0 else scopes[-1])[t] = last_sig in _VEC_TYPES
                last_sig = t
            elif t in ("reflect", "refract") and nxt(i) < n and toks[nxt(i)] == "(":
                k = nxt(nxt(i))                                # first significant arg token
                a = toks[k] if k < n else ""
                scalar = False
                if a[:1].isdigit() or a[:1] == ".":            # numeric literal
                    scalar = True
                elif a in _VEC_TYPES:                          # vecN(...) constructor
                    scalar = False
                elif a[:1].isalpha() or a[:1] == "_":          # identifier
                    m = nxt(k)
                    if m < n and toks[m] == ".":               # member/swizzle access
                        sw = toks[nxt(m)] if nxt(m) < n else ""
                        scalar = not (len(sw) >= 2 and all(c in _SWIZZLE for c in sw))
                    else:
                        scalar = lookup(a) is False            # known scalar (not None/True)
                if scalar:
                    toks[i] = "nm_" + t; changed = True
                last_sig = t
            else:
                last_sig = t
            member_next = False
        else:
            last_sig = t; member_next = False
        i += 1

    if not changed:
        return src
    out = "".join(toks)
    nl = out.find("\n")                                        # keep any leading directive first
    return out[:nl + 1] + _REFLECT_HELPERS + out[nl + 1:] if nl >= 0 else _REFLECT_HELPERS + out


# packHalf2x16/unpackHalf2x16 polyfill. Blender's GLSL->MSL codegen has no builtin under either
# name ("undeclared identifier") — unlike reflect/refract there's no Metal-side ambiguity to dodge,
# so we inject real functions under the EXACT reference names (no call-site rewriting needed).
# Built on floatBitsToUint/uintBitsToFloat + uint bitwise ops, both already proven to compile
# elsewhere in the catalog (e.g. every pcg() hash). Round-to-nearest (ties round up rather than
# ties-to-even — the GLSL spec doesn't mandate a tie rule, and median.glsl only uses the pack/
# unpack pair as an internal sort/reconstruction key, so any consistent rounding is equivalent).
# Values below half's normal range (|v| < 2^-14 — far darker than any perceptible color channel)
# flush to signed zero on pack instead of encoding a true subnormal; unpack is bit-exact for every
# value pack can produce (including its zero-flush), so the pair round-trips consistently for the
# color-channel range this shader actually sees.
_PACK_HALF_HELPERS = (
    "\nfloat nm_half2float(uint h){\n"
    "  uint sign = (h & 0x8000u) << 16u;\n"
    "  uint ex = (h >> 10u) & 0x1fu;\n"
    "  uint mant = h & 0x3ffu;\n"
    "  if (ex == 0u) { return uintBitsToFloat(sign); }\n"
    "  if (ex == 31u) { return uintBitsToFloat(sign | 0x7f800000u | (mant << 13u)); }\n"
    "  return uintBitsToFloat(sign | (((ex - 15u) + 127u) << 23u) | (mant << 13u));\n"
    "}\n"
    "uint nm_float2half(float f){\n"
    "  uint x = floatBitsToUint(f);\n"
    "  uint sign = (x >> 16u) & 0x8000u;\n"
    "  uint ax = x & 0x7fffffffu;\n"
    "  if (ax == 0u) { return sign; }\n"
    "  int e = int(ax >> 23u) - 127;\n"
    "  if (e <= -15) { return sign; }\n"
    "  if (e >= 16) { return sign | 0x7c00u; }\n"
    "  uint m = ax & 0x7fffffu;\n"
    "  uint rm = (m + 0x1000u) >> 13u;\n"
    "  uint he = uint(e + 15);\n"
    "  if (rm >= 0x400u) { rm = 0u; he += 1u; }\n"
    "  if (he >= 31u) { return sign | 0x7c00u; }\n"
    "  return sign | (he << 10u) | rm;\n"
    "}\n"
    "uint packHalf2x16(vec2 v){ return (nm_float2half(v.y) << 16u) | nm_float2half(v.x); }\n"
    "vec2 unpackHalf2x16(uint u){ return vec2(nm_half2float(u & 0xffffu), nm_half2float(u >> 16u)); }\n"
)
_PACK_HALF_RE = __import__("re").compile(r"\b(?:pack|unpack)Half2x16\b")


def inject_pack_half2x16(src):
    """Prepend the packHalf2x16/unpackHalf2x16 polyfill when the body calls either (median's
    packed-record sort key). No-op otherwise. See _PACK_HALF_HELPERS."""
    if not _PACK_HALF_RE.search(src):
        return src
    nl = src.find("\n")                                        # keep any leading directive first
    return src[:nl + 1] + _PACK_HALF_HELPERS + src[nl + 1:] if nl >= 0 else _PACK_HALF_HELPERS + src


def rename_cpp_alt_tokens(src):
    """Rename identifiers that are C++ alternative tokens (`or`/`and`/`xor`/...) to `nm_<name>`
    — they're keywords in Metal's C++ compiler. Tokenized so comments and member accesses are
    left alone; consistent global rename (these are user function names, e.g. bitEffects)."""
    out = []
    member_next = False
    for m in _TOKEN.finditer(src):
        t = m.group(0)
        if t.startswith("//") or t.startswith("/*") or t.isspace():
            out.append(t)
            continue
        if t == ".":
            out.append(t); member_next = True; continue
        if t[:1].isalpha() or t[:1] == "_":
            out.append("nm_" + t if (not member_next and t in _CPP_ALT_TOKENS) else t)
            member_next = False
        else:
            out.append(t); member_next = False
    return "".join(out)


def rename_shadow_builtins(src):
    """Rename local variables/params that shadow a GLSL builtin function (`_SHADOWABLE`) to
    `nm_<name>`, scope-aware: the rename covers the declaration and its in-scope uses, but NOT
    the builtin call in the local's own initializer (`float max = max(...)` -> `float nm_max =
    max(...)`). A no-op for sources without such a shadow (lossless tokenize+reconstruct), so
    it is safe to run on every effect. Verified non-regressing via compile_check.

    `pending` also covers a `for (int step = 0; step < N; step++)` init-declaration: unlike a
    function parameter (only visible once the body's `{` flushes `pending` into a new scope),
    the for-header's own condition/increment clauses are still inside the same open paren group
    and need the rename BEFORE that `{` — so a use checks `pending` too, and `;` only clears it
    at paren==0 (top-level statement end), not the for-header's own internal `;` separators."""
    out = []
    scopes = [{}]             # stack of {orig: renamed}
    pending = {}              # decl renames not yet in scope -> enter the next {}
    paren = 0
    last_sig = None
    member_next = False
    decl_name = None          # name being declared this statement; its initializer keeps the builtin
    for m in _TOKEN.finditer(src):
        t = m.group(0)
        if t.startswith("//") or t.startswith("/*") or t.isspace():
            out.append(t)
            continue
        if t == "{":
            scopes.append(dict(pending)); pending = {}; out.append(t); last_sig = "{"; member_next = False
        elif t == "}":
            if len(scopes) > 1:
                scopes.pop()
            out.append(t); last_sig = "}"; member_next = False
        elif t == "(":
            paren += 1; out.append(t); last_sig = "("; member_next = False
        elif t == ")":
            paren = max(0, paren - 1); out.append(t); last_sig = ")"; member_next = False
        elif t == ";":
            decl_name = None
            if paren == 0:
                pending = {}
            out.append(t); last_sig = ";"; member_next = False
        elif t == ".":
            out.append(t); last_sig = "."; member_next = True
        elif t[:1].isalpha() or t[:1] == "_":
            if member_next:
                out.append(t); member_next = False; last_sig = t
            elif last_sig in _TYPE_KW and t in _SHADOWABLE:        # decl of a builtin-named local
                new = "nm_" + t
                (pending if paren > 0 else scopes[-1])[t] = new
                if paren == 0:
                    decl_name = t                                  # keep the builtin in its initializer
                out.append(new); last_sig = t
            else:                                                  # a use
                ren = pending.get(t)
                if ren is None:
                    for s in reversed(scopes):
                        if t in s:
                            ren = s[t]; break
                out.append(ren if (ren and t != decl_name) else t)
                last_sig = t
            member_next = False
        else:
            out.append(t); last_sig = t; member_next = False
    return "".join(out)


def rewrite_uniform_refs(src, fields, instance=INSTANCE):
    """Rewrite references to the uniform names in `src` to `<instance>.<name>`, SCOPE-AWARE: a name
    declared as a function parameter or local variable shadows the uniform (GLSL scoping), so
    that declaration and its in-scope uses are left untouched. This is what an anonymous std140
    block would give for free — but Blender's create_from_info only supports a NAMED block, so
    we must qualify the references ourselves (verified necessary by spike_ubo3.py).

    Member accesses (`foo.name`), declaration names, and comments are never rewritten. Handles
    the real collisions in the corpus (noise's `octaves`, cellNoise's `scale`, shapes' `seed`
    are all function params)."""
    U = set(n for _, n in fields)
    if not U:
        return src
    out = []
    scopes = [set()]          # stack of shadowed-name sets; index 0 = global (no shadow)
    pending = set()           # params declared in the current () -> enter the next {}
    paren = 0
    last_sig = None           # last significant token (skips whitespace/comments)
    member_next = False       # the previous significant token was '.'
    for m in _TOKEN.finditer(src):
        t = m.group(0)
        if t.startswith("//") or t.startswith("/*") or t.isspace():
            out.append(t)
            continue
        if t == "{":
            scopes.append(set(pending)); pending = set(); out.append(t); last_sig = "{"; member_next = False
        elif t == "}":
            if len(scopes) > 1:
                scopes.pop()
            out.append(t); last_sig = "}"; member_next = False
        elif t == "(":
            paren += 1; out.append(t); last_sig = "("; member_next = False
        elif t == ")":
            paren = max(0, paren - 1); out.append(t); last_sig = ")"; member_next = False
        elif t == ";":
            pending = set(); out.append(t); last_sig = ";"; member_next = False   # end stmt/prototype
        elif t == ".":
            out.append(t); last_sig = "."; member_next = True
        elif t[:1].isalpha() or t[:1] == "_":
            if member_next:                                  # member access: leave as-is
                out.append(t); member_next = False; last_sig = t
            elif last_sig in _TYPE_KW:                       # declaration of `t`
                if t in U:
                    (pending if paren > 0 else scopes[-1]).add(t)
                out.append(t); last_sig = t
            elif t in U and not any(t in s for s in scopes):  # a genuine uniform reference
                out.append(instance + "." + t); last_sig = t
            else:
                out.append(t); last_sig = t
        else:
            out.append(t); last_sig = t; member_next = False
    return "".join(out)


def pack(fields, values):
    """Pack values (dict name->value) into a std140 float32 numpy array matching layout().
    Ints/bools are bit-cast into the float buffer — only the bytes matter; the shader reads
    them back per the struct's int/float field types. Missing values stay zero."""
    entries, nfloats = layout(fields)
    buf = bytearray(nfloats * 4)
    for ctype, name, off in entries:
        v = values.get(name)
        if v is None:
            continue
        if ctype == "FLOAT":
            _struct.pack_into("<f", buf, off, float(v))
        elif ctype == "INT":
            _struct.pack_into("<i", buf, off, int(v))
        elif ctype == "BOOL":
            _struct.pack_into("<i", buf, off, 1 if v else 0)
        elif ctype in ("VEC2", "VEC3", "VEC4"):
            for i, c in enumerate(list(v)):
                _struct.pack_into("<f", buf, off + 4 * i, float(c))
        elif ctype in ("IVEC2", "IVEC3", "IVEC4"):
            for i, c in enumerate(list(v)):
                _struct.pack_into("<i", buf, off + 4 * i, int(c))
    # np.frombuffer preserves the exact bytes (incl. int bit patterns that look like NaN
    # floats) — pure-Python float() round-trips would not.
    return np.frombuffer(bytes(buf), dtype=np.float32).copy()


# ---- explicit std140 block (remap's `layout(std140) uniform RemapUniforms { vec4 data[267]; }`) --
# A named block declared in the shader (not auto-lifted from scalar uniforms). Its single array
# member is filled by packing the effect's LOGICAL uniforms (bgColor, zoneN_vK, …) into vec4 slots
# per the effect's uniformLayout — a direct port of the reference webgl2 packUniformsWithLayout.
_COMP_IDX = {"x": 0, "y": 1, "z": 2, "w": 3}


def block_struct_source(blk):
    """GLSL struct typedef for an explicit std140 block: `struct <Struct> { <type> <name>[N]; … };`."""
    body = "".join("  %s %s%s;\n" % (t, n, ("[%d]" % c) if c else "") for t, n, c in blk["members"])
    return "struct %s {\n%s};\n" % (blk["struct"], body)


def pack_with_layout(uniforms, layout, slots):
    """Pack logical uniforms into a std140 block buffer using a {name: {slot, components}} layout
    (port of webgl2 packUniformsWithLayout). `slots` = the block array length (vec4 count); the
    buffer is slots*4 floats. Each entry writes its value's components starting at
    slot*4 + componentIndex(first component). Missing values stay zero; width/height/channels
    resolve from `resolution` like the reference."""
    buf = np.zeros(slots * 4, dtype=np.float32)
    for name, spec in layout.items():
        v = uniforms.get(name)
        if v is None:
            res = uniforms.get("resolution")
            if name == "width" and res is not None:
                v = res[0]
            elif name == "height" and res is not None:
                v = res[1]
            elif name == "channels":
                v = 4.0
            else:
                continue
        comps = spec["components"]
        base = spec["slot"] * 4 + _COMP_IDX[comps[0]]
        if len(comps) == 1:
            buf[base] = 1.0 if v is True else (0.0 if v is False else float(v))
        else:
            seq = list(v) if isinstance(v, (list, tuple)) else [v]
            for i in range(min(len(seq), len(comps))):
                buf[base + i] = float(seq[i])
    return buf

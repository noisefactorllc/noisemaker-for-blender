#!/usr/bin/env node
// convert-shaders-blender.mjs — reference GLSL → Blender gpu-module shader pair.
//
// Walks shaders/effects/<ns>/<name>/glsl/<program>.glsl (reference WebGL2 / GLSL-ES-300)
// and emits, per program:
//   blender/noisemaker_blender/shaders/effects/<ns>/<name>/<program>.frag           (cleaned body)
//   blender/noisemaker_blender/shaders/effects/<ns>/<name>/<program>.createinfo.json (descriptor)
//
// WHY a descriptor + cleaned body: on Metal you MUST build shaders with
// gpu.shader.create_from_info(GPUShaderCreateInfo) — the legacy inline-`uniform` ctor is
// rejected, and `uniform` is a reserved MSL keyword that cannot appear in the source. So all
// declarations are LIFTED out of the GLSL into the JSON descriptor; the body is reused VERBATIM
// (PCG/helpers/gl_FragCoord/math/#define-fallbacks untouched). See PORTING-GUIDE.md / BLENDER-PLATFORM-NOTES.md.
//
// The transform (and ONLY this):
//   1. strip `#version`, `precision …;`, and `#ifdef GL_ES … #endif` precision guards.
//   2. lift `uniform sampler2D <name>;`           -> descriptor.samplers   [slot,'FLOAT_2D',name]
//   3. lift `uniform <scalar/vec/mat> <name>;`    -> descriptor.pushConstants [TYPE,name]
//   4. lift `(layout(location=N))? out vec4 <name>;` -> descriptor.fragmentOut [slot,'VEC4',name]
//   5. delete those declaration lines from the body; keep `void main(){…}` and all else verbatim.
//   6. compute std140 push-constant size; if > 128 bytes flag `ubo:true` (UBO path staged).
//
// Flags (written to stderr, never auto-"fixed"): MRT (>1 out), uniform arrays (audio — skipped),
// fragment varyings (`in vec…`), missing out, missing main.
//
// Usage:  node convert-shaders-blender.mjs [ns/name] [--dry-run]
// Env:    NM_REFERENCE_ROOT (default ../noisemaker)   NM_OUT_DIR (default the addon shaders dir)

import { readdirSync, statSync, mkdirSync, writeFileSync, existsSync, readFileSync } from 'node:fs'
import { join, dirname, resolve, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
if (!process.env.NM_REFERENCE_ROOT) {
  console.error('NM_REFERENCE_ROOT must point at the Noisemaker reference engine source root')
  process.exit(1)
}
const REFERENCE_ROOT = resolve(process.env.NM_REFERENCE_ROOT)
const EFFECTS_DIR = join(REFERENCE_ROOT, 'shaders', 'effects')
const OUT_DIR = process.env.NM_OUT_DIR
  ? resolve(process.env.NM_OUT_DIR)
  : resolve(__dirname, '..', 'blender', 'noisemaker_blender', 'shaders', 'effects')

const NAMESPACES = [
  'classicNoisedeck', 'filter', 'filter3d', 'mixer', 'points', 'render', 'synth', 'synth3d',
]

// GLSL type -> (createInfo type, std140 size bytes, std140 align bytes)
const TYPE_MAP = {
  float: ['FLOAT', 4, 4], int: ['INT', 4, 4], bool: ['BOOL', 4, 4], uint: ['UINT', 4, 4],
  vec2: ['VEC2', 8, 8], vec3: ['VEC3', 12, 16], vec4: ['VEC4', 16, 16],
  ivec2: ['IVEC2', 8, 8], ivec3: ['IVEC3', 12, 16], ivec4: ['IVEC4', 16, 16],
  mat3: ['MAT3', 48, 16], mat4: ['MAT4', 64, 16],
}
const SCALAR_VEC_MAT = Object.keys(TYPE_MAP).join('|')

// MSL reserved keywords that the reference uses as plain GLSL identifiers (function/var/uniform
// names). On Metal these break translation ("…must reside in constant address space", "field may
// not be qualified with an address space"). We whole-word rename them to `nm_<word>` across the
// WHOLE source (so lifted uniform/sampler names stay consistent with the body). NEVER include GLSL
// builtins here (e.g. `texture`, `sampler`). `gradient`/`level`/`depth` compile fine — not listed.
const MSL_RESERVED = [
  'constant', 'kernel', 'buffer', 'sample', 'device', 'thread', 'threadgroup', 'fragment', 'vertex',
]
function renameReserved (src) {
  let out = src
  for (const w of MSL_RESERVED) out = out.replace(new RegExp(`\\b${w}\\b`, 'g'), `nm_${w}`)
  return out
}

// Blender's GLSL->MSL codegen treats a top-level `const int` as a non-static data member, so it
// can't size an array — `const Foo X[COUNT]` fails with "invalid use of non-static data member".
// Promote column-0 integer consts to #define (true compile-time literals). Function-local consts
// (indented) are untouched, so this can't collide with locals of the same name.
function constIntToDefine (src) {
  return src.replace(/^const[ \t]+int[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*(-?\d+)[ \t]*;[ \t]*(?:\/\/.*)?$/gm,
    '#define $1 $2')
}

// GLSL ES `vecN == vecN` yields a SCALAR bool (true iff ALL components equal). Blender's
// GLSL->MSL codegen instead emits a component-wise `bvecN` and then rejects it as a ternary
// condition ("vector condition ... do not have elements of the same size"). Make the scalar-bool
// intent explicit with all(equal(...)) / any(notEqual(...)) — identical semantics — wherever a
// vecN(...) constructor is compared and the result feeds a `? :` (feedback/coalesce/refract/
// applyMode blend-mode tables). Only fires when the comparison is directly parenthesised before a
// `?`, so scalar comparisons and `min(...,vecN(...))` args are untouched.
function fixVecBoolTernary (src) {
  let out = src
  out = out.replace(/\(\s*([^()]+?)\s*==\s*(vec[234]\([^()]*\))\s*\)(\s*\?)/g, '(all(equal($1, $2)))$3')
  out = out.replace(/\(\s*(vec[234]\([^()]*\))\s*==\s*([^()]+?)\s*\)(\s*\?)/g, '(all(equal($1, $2)))$3')
  out = out.replace(/\(\s*([^()]+?)\s*!=\s*(vec[234]\([^()]*\))\s*\)(\s*\?)/g, '(any(notEqual($1, $2)))$3')
  out = out.replace(/\(\s*(vec[234]\([^()]*\))\s*!=\s*([^()]+?)\s*\)(\s*\?)/g, '(any(notEqual($1, $2)))$3')
  return out
}

// The uniform/sampler lifters are line-anchored (^…;$ — one decl per line). The reference packs
// some uniforms multiple-per-line (mashup's `uniform int layer0_active; uniform int layer1_active;
// …`), which then match NEITHER the lift NOR the strip, so they survive into the body and break
// Metal ("use of class template 'uniform' requires template arguments"). Put each `uniform …;` on
// its own line first. Only fires on a `;` that is directly followed by another `uniform` token.
function splitMultiUniformLines (src) {
  return src.replace(/;[ \t]*(?=uniform\b)/g, ';\n')
}

// Explicit `layout(std140) uniform <Struct> { <members> };` block (synth/remap's `vec4 data[267]`
// zone-config UBO). Metal's create_from_info forbids inline `layout(...)`/`uniform` in the body, so
// lift the block into the descriptor (struct + members + the effect's packing layout) and strip it.
// The body's member refs are qualified to `<instance>.<member>` at shader-build time; the backend
// packs the logical zone uniforms into the block via the layout (mirrors webgl2 packUniformsWithLayout).
function liftUniformBlock (body, ns, name) {
  const blockRe = /layout\s*\(\s*std140\s*\)\s*uniform\s+(\w+)\s*\{([^}]*)\}\s*;/
  const bm = blockRe.exec(body)
  if (!bm) return { body, uniformBlock: null }
  const members = []
  for (const decl of bm[2].split(';')) {
    const mm = /^(\w+)\s+(\w+)\s*(?:\[\s*(\d+)\s*\])?$/.exec(decl.trim())
    if (mm) members.push([mm[1], mm[2], mm[3] ? Number(mm[3]) : 0])
  }
  body = body.replace(blockRe, '')
  // the packing map (uniform name -> {slot, components}) lives in the converted effect definition.
  let layout = null
  const effJson = resolve(OUT_DIR, '..', '..', 'effects', ns, name + '.json')
  if (existsSync(effJson)) {
    try { layout = JSON.parse(readFileSync(effJson, 'utf8')).uniformLayout || null } catch { /* leave null */ }
  }
  return { body, uniformBlock: { struct: bm[1], instance: 'nm_ub', members, layout } }
}

// The reference full-screen vertex shader supplies `v_texCoord = a_position*0.5+0.5` (the quad's
// 0..1 coord, bottom-up); the Blender port's full-screen VS does not. For a 1:1 full-screen filter
// that varying is exactly `gl_FragCoord.xy / vec2(textureSize(inputTex,0))` (pixel-center, bottom-up
// — same value the reference interpolates). Strip the decl + rewrite refs (grime/spookyTicker/
// texture/wobble). `textureSize` survives the later texture()->nmTex rewrite (it's not `texture(`).
function fixFragmentVarying (body, samplers) {
  if (!/\bin\s+vec2\s+v_texCoord\s*;/.test(body)) return body
  const s = samplers.find(x => x[2] === 'inputTex') || samplers[0]
  if (!s) return body
  body = body.replace(/^[ \t]*in\s+vec2\s+v_texCoord\s*;[ \t]*(?:\/\/.*)?\n?/m, '')
  return body.replace(/\bv_texCoord\b/g, `(gl_FragCoord.xy / vec2(textureSize(${s[2]}, 0)))`)
}

function splitTopLevel (s) {
  const out = []; let depth = 0, cur = ''
  for (const ch of s) {
    if (ch === '(' || ch === '[') depth++
    else if (ch === ')' || ch === ']') depth--
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = '' } else cur += ch
  }
  if (cur.trim()) out.push(cur.trim())
  return out
}

// Blender's GLSL->MSL has NO struct constructor (`Foo(a,b)` -> "no matching constructor"), so a
// const array of a POD-vec4 struct (palette/historicPalette tables: `const Foo T[N]=Foo[N](Foo(...),...)`)
// can't compile. Flatten each such table into parallel `const vec4 T_field[N]=vec4[N](...)` arrays
// (which DO compile) and rewrite `Foo e = T[expr]; e.field` -> `int e_idx=(expr); T_field[e_idx]`.
function flattenStructArrays (body) {
  const structRe = /\bstruct\s+(\w+)\s*\{([^}]*)\}\s*;/g
  const pods = []; let sm
  while ((sm = structRe.exec(body)) !== null) {
    const members = []; let allVec4 = true; const memRe = /\b(\w+)\s+(\w+)\s*;/g; let mm
    while ((mm = memRe.exec(sm[2])) !== null) { if (mm[1] !== 'vec4') { allVec4 = false; break } members.push(mm[2]) }
    if (allVec4 && members.length) pods.push({ name: sm[1], members, def: sm[0] })
  }
  for (const st of pods) body = flattenOneStruct(body, st)
  return body
}

function flattenOneStruct (body, st) {
  const { name, members, def } = st
  const head = new RegExp(`const\\s+${name}\\s+(\\w+)\\s*\\[\\s*(\\w+)\\s*\\]\\s*=\\s*${name}\\s*\\[`)
  const dm = head.exec(body)
  if (!dm) return body                                  // struct has no const-array table -> leave alone
  const arrName = dm[1], cnt = dm[2]
  let p = dm.index + dm[0].length
  while (p < body.length && body[p] !== '(') p++
  let depth = 0, end = -1
  for (let i = p; i < body.length; i++) { if (body[i] === '(') depth++; else if (body[i] === ')') { depth--; if (!depth) { end = i; break } } }
  if (end < 0) return body
  const semi = body.indexOf(';', end)
  const inner = body.slice(p + 1, end)
  const entries = []; const eRe = new RegExp(`${name}\\s*\\(`, 'g'); let em
  while ((em = eRe.exec(inner)) !== null) {
    let o = em.index + em[0].length - 1, d = 0, e2 = -1
    for (let i = o; i < inner.length; i++) { if (inner[i] === '(') d++; else if (inner[i] === ')') { d--; if (!d) { e2 = i; break } } }
    entries.push(splitTopLevel(inner.slice(o + 1, e2)))
  }
  let arrays = ''
  members.forEach((f, fi) => {
    arrays += `const vec4 ${arrName}_${f}[${cnt}] = vec4[${cnt}](${entries.map(e => e[fi]).join(', ')});\n`
  })
  body = body.slice(0, dm.index) + arrays + body.slice(semi + 1)
  body = body.replace(def, '')
  const asg = new RegExp(`${name}\\s+(\\w+)\\s*=\\s*${arrName}\\s*\\[([^\\]]+)\\]\\s*;`, 'g')
  const locals = []; let am
  while ((am = asg.exec(body)) !== null) locals.push({ local: am[1], idx: am[2], full: am[0] })
  for (const lo of locals) {
    body = body.replace(lo.full, `int ${lo.local}_idx = (${lo.idx});`)
    for (const f of members) body = body.replace(new RegExp(`\\b${lo.local}\\.${f}\\b`, 'g'), `${arrName}_${f}[${lo.local}_idx]`)
  }
  return body
}
const aliasOf = (name) => {
  const m = /^nm_(constant|kernel|buffer|sample|device|thread|threadgroup|fragment|vertex)$/.exec(name)
  return m ? m[1] : null
}

function std140Bytes (pushConstants) {
  let off = 0
  for (const [type] of pushConstants) {
    const [, size, align] = Object.values(TYPE_MAP).find(v => v[0] === type) || [null, 4, 4]
    off = Math.ceil(off / align) * align
    off += size
  }
  return Math.ceil(off / 16) * 16 // blocks round to 16
}

function transpile (src, ns, name) {
  const notes = []
  const lines = src.split('\n')

  // 1. strip #version / precision / GL_ES-only precision guards.
  const kept = []
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim()
    if (/^#version\b/.test(t)) continue
    if (/^precision\s+(highp|mediump|lowp)\b/.test(t)) continue
    if (/^#ifdef\s+GL_ES\b/.test(t)) {
      let j = i + 1; const inner = []
      while (j < lines.length && !/^\s*#endif\b/.test(lines[j])) { inner.push(lines[j]); j++ }
      if (inner.every(l => l.trim() === '' || /^precision\b/.test(l.trim())) && j < lines.length) { i = j; continue }
    }
    kept.push(lines[i])
  }
  let body = kept.join('\n')

  // 1b. rename MSL-reserved identifiers across the whole source (keeps lifted names consistent).
  body = renameReserved(body)
  body = constIntToDefine(body)
  body = fixVecBoolTernary(body)
  body = flattenStructArrays(body)
  body = splitMultiUniformLines(body)

  // lift an explicit `layout(std140) uniform {…}` block (remap's zone-config UBO) before the
  // generic uniform parse, so its inner members aren't mistaken for push constants.
  const blk = liftUniformBlock(body, ns, name)
  body = blk.body
  if (blk.uniformBlock && !blk.uniformBlock.layout) notes.push(`UNIFORM_BLOCK_NO_LAYOUT (${blk.uniformBlock.struct})`)

  // flag uniform arrays (audio waveform/spectrum — out of scope) before generic uniform parse.
  const arrayRe = /^[ \t]*uniform[ \t]+\w+[ \t]+([A-Za-z_]\w*)[ \t]*\[/gm
  let am; const arrays = []
  while ((am = arrayRe.exec(body)) !== null) arrays.push(am[1])
  if (arrays.length) notes.push(`UNIFORM_ARRAY (${arrays.join(',')}) — audio/media, skipped`)

  // 2. samplers (slot = declaration order).
  const samplerRe = /^[ \t]*uniform[ \t]+sampler2D[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  const samplers = []; let sm
  while ((sm = samplerRe.exec(body)) !== null) samplers.push([samplers.length, 'FLOAT_2D', sm[1]])
  body = body.replace(samplerRe, '')

  // 2b. resolve the reference full-screen `v_texCoord` varying to a gl_FragCoord expression
  // (needs the sampler list; do it before the FRAGMENT_VARYING flag check below).
  body = fixFragmentVarying(body, samplers)

  // 3. push-constants (scalars/vec/mat, excluding arrays which we leave + flag).
  const uniRe = new RegExp(`^[ \\t]*uniform[ \\t]+(${SCALAR_VEC_MAT})[ \\t]+([A-Za-z_]\\w*)[ \\t]*;[ \\t]*(?://.*)?$`, 'gm')
  const pushConstants = []; let um
  while ((um = uniRe.exec(body)) !== null) pushConstants.push([TYPE_MAP[um[1]][0], um[2]])
  body = body.replace(uniRe, '')

  // 4. fragment outputs.
  const outRe = /^[ \t]*(?:layout[ \t]*\([ \t]*location[ \t]*=[ \t]*(\d+)[ \t]*\)[ \t]*)?out[ \t]+vec4[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  const fragmentOut = []; let om
  while ((om = outRe.exec(body)) !== null) {
    fragmentOut.push([om[1] !== undefined ? Number(om[1]) : fragmentOut.length, 'VEC4', om[2]])
  }
  body = body.replace(outRe, '')

  // varyings (fragment `in vec…`) — staged categories only; flag.
  if (/^[ \t]*in[ \t]+(vec|float|int)/m.test(body)) notes.push('FRAGMENT_VARYING (in …) — needs interface info, staged')

  if (fragmentOut.length === 0) notes.push('NO_OUT (gl_FragColor-style?) — manual')
  if (fragmentOut.length > 1) notes.push(`MRT (${fragmentOut.length}) — staged`)
  if (!/\bvoid[ \t]+main[ \t]*\(/.test(body)) notes.push('NO_MAIN — manual')

  // aliases: graph-JSON uniform/sampler name -> renamed shader name (only for reserved collisions).
  const uniformAliases = {}
  for (const [, name] of pushConstants) { const a = aliasOf(name); if (a) uniformAliases[a] = name }
  for (const [, , name] of samplers) { const a = aliasOf(name); if (a) uniformAliases[a] = name }
  if (Object.keys(uniformAliases).length) notes.push(`ALIASED ${Object.keys(uniformAliases).join(',')}`)

  const bytes = std140Bytes(pushConstants)
  const ubo = bytes > 128
  if (ubo) notes.push(`PUSH_OVER_128 (${bytes}B) — UBO path (staged)`)

  // 5. force NEAREST+CLAMP sampling. Blender's gpu module has NO sampler-state API and defaults
  // to LINEAR/REPEAT, but the reference creates every surface NEAREST + CLAMP_TO_EDGE (load-bearing
  // for warp/resample effects). Rewrite each 2-arg texture(s,uv) to an exact texelFetch (all 567
  // reference calls are 2-arg; texelFetch/textureSize are already used by the reference directly).
  let nearestPreamble = ''
  if (samplers.length) {
    body = body.replace(/\btexture\s*\(/g, 'nmTex(')
    nearestPreamble =
      '#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))),'
      + ' ivec2(0), textureSize((s),0)-ivec2(1)), 0))\n'
  }

  // tidy: collapse the runs of blank lines the deletions leave behind.
  const frag = nearestPreamble + body.replace(/\n{3,}/g, '\n\n').trim() + '\n'
  const descriptor = { pushConstants, samplers, fragmentOut, uniformAliases, std140Bytes: bytes, ubo, notes }
  if (blk.uniformBlock) descriptor.uniformBlock = blk.uniformBlock
  return { frag, descriptor, notes }
}

// GLSL type -> createInfo type for vertex_in attributes and stage-interface varyings.
const IFACE_TYPE = {
  float: 'FLOAT', vec2: 'VEC2', vec3: 'VEC3', vec4: 'VEC4',
  int: 'INT', uint: 'UINT', ivec2: 'IVEC2', ivec3: 'IVEC3', ivec4: 'IVEC4',
  mat3: 'MAT3', mat4: 'MAT4',
}

// strip #version/precision + rename MSL-reserved identifiers (shared by both transpile paths).
function cleanAndRename (src) {
  const lines = src.split('\n')
  const kept = []
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim()
    if (/^#version\b/.test(t)) continue
    if (/^precision\s+(highp|mediump|lowp)\b/.test(t)) continue
    if (/^#ifdef\s+GL_ES\b/.test(t)) {
      let j = i + 1; const inner = []
      while (j < lines.length && !/^\s*#endif\b/.test(lines[j])) { inner.push(lines[j]); j++ }
      if (inner.every(l => l.trim() === '' || /^precision\b/.test(l.trim())) && j < lines.length) { i = j; continue }
    }
    kept.push(lines[i])
  }
  return splitMultiUniformLines(fixVecBoolTernary(constIntToDefine(renameReserved(kept.join('\n')))))
}

// lift sampler + push-constant uniforms from a stage body, deduped across stages by name.
function liftUniforms (body, samplerNames, pushNames, samplers, pushConstants) {
  const samplerRe = /^[ \t]*uniform[ \t]+sampler2D[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  let sm
  while ((sm = samplerRe.exec(body)) !== null) {
    if (!samplerNames.has(sm[1])) { samplerNames.add(sm[1]); samplers.push([samplers.length, 'FLOAT_2D', sm[1]]) }
  }
  body = body.replace(samplerRe, '')
  const uniRe = new RegExp(`^[ \\t]*uniform[ \\t]+(${SCALAR_VEC_MAT})[ \\t]+([A-Za-z_]\\w*)[ \\t]*;[ \\t]*(?://.*)?$`, 'gm')
  let um
  while ((um = uniRe.exec(body)) !== null) {
    if (!pushNames.has(um[2])) { pushNames.add(um[2]); pushConstants.push([TYPE_MAP[um[1]][0], um[2]]) }
  }
  return body.replace(uniRe, '')
}

// Vertex+fragment program (drawMode points/billboards/triangles deposit & 3D render). Same
// declaration-lifting as transpile(), but across two stages, plus vertex_in attributes and a
// vertex->fragment varying interface. Bodies (incl. gl_VertexID/gl_PointSize) kept verbatim.
function transpileVertFrag (vertSrc, fragSrc) {
  const notes = []
  let vbody = cleanAndRename(vertSrc)
  let fbody = cleanAndRename(fragSrc)

  // vertex attributes (`in`) and varyings (`out`) — parse before generic uniform lift.
  const inRe = /^[ \t]*in[ \t]+(\w+)[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  const outRe = /^[ \t]*out[ \t]+(\w+)[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  const vertexIn = []; let vi
  while ((vi = inRe.exec(vbody)) !== null) { const t = IFACE_TYPE[vi[1]]; if (t) vertexIn.push([vertexIn.length, t, vi[2]]) }
  vbody = vbody.replace(inRe, '')
  const varyings = []; let vo
  while ((vo = outRe.exec(vbody)) !== null) { const t = IFACE_TYPE[vo[1]]; if (t) varyings.push(['smooth', t, vo[2]]) }
  vbody = vbody.replace(outRe, '')
  fbody = fbody.replace(inRe, '')   // fragment `in <varying>;` — declared by the interface instead

  const samplerNames = new Set(), pushNames = new Set()
  const samplers = [], pushConstants = []
  vbody = liftUniforms(vbody, samplerNames, pushNames, samplers, pushConstants)  // VS first: stable sampler slots
  fbody = liftUniforms(fbody, samplerNames, pushNames, samplers, pushConstants)

  // fragment outputs (vec4, optional explicit location).
  const fragOutRe = /^[ \t]*(?:layout[ \t]*\([ \t]*location[ \t]*=[ \t]*(\d+)[ \t]*\)[ \t]*)?out[ \t]+vec4[ \t]+([A-Za-z_]\w*)[ \t]*;[ \t]*(?:\/\/.*)?$/gm
  const fragmentOut = []; let om
  while ((om = fragOutRe.exec(fbody)) !== null) fragmentOut.push([om[1] !== undefined ? Number(om[1]) : fragmentOut.length, 'VEC4', om[2]])
  fbody = fbody.replace(fragOutRe, '')

  // attribute-less draws (points/billboards) need a dummy attr so the vert buffer can size the draw.
  if (vertexIn.length === 0) vertexIn.push([0, 'FLOAT', 'nm_dummy'])

  // NEAREST+CLAMP rewrite, applied per stage only if it actually samples via 2-arg texture().
  let preamble = ''
  if (samplers.length) {
    const before = vbody + ' ' + fbody
    vbody = vbody.replace(/\btexture\s*\(/g, 'nmTex(')
    fbody = fbody.replace(/\btexture\s*\(/g, 'nmTex(')
    if ((vbody + ' ' + fbody) !== before) {
      preamble = '#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))),'
        + ' ivec2(0), textureSize((s),0)-ivec2(1)), 0))\n'
    }
  }

  const uniformAliases = {}
  for (const [, name] of pushConstants) { const a = aliasOf(name); if (a) uniformAliases[a] = name }
  for (const [, , name] of samplers) { const a = aliasOf(name); if (a) uniformAliases[a] = name }
  if (Object.keys(uniformAliases).length) notes.push(`ALIASED ${Object.keys(uniformAliases).join(',')}`)

  const bytes = std140Bytes(pushConstants)
  const ubo = bytes > 128
  if (ubo) notes.push(`PUSH_OVER_128 (${bytes}B) — UBO (staged)`)
  if (fragmentOut.length > 1) notes.push(`MRT (${fragmentOut.length})`)
  if (!/\bvoid[ \t]+main[ \t]*\(/.test(vbody)) notes.push('VERT_NO_MAIN — manual')

  const vert = (preamble + vbody.replace(/\n{3,}/g, '\n\n').trim() + '\n')
  const frag = (preamble + fbody.replace(/\n{3,}/g, '\n\n').trim() + '\n')
  const descriptor = {
    pushConstants, samplers, fragmentOut, vertexIn, varyings, vertex: true,
    uniformAliases, std140Bytes: bytes, ubo, notes,
  }
  return { vert, frag, descriptor, notes }
}

// Per-program host adaptations for Blender-gpu-codegen quirks the generic transform can't catch.
// Keyed "ns/name/program". Applied to the cleaned .frag after transpile(). Documented, narrow.
//
// (Previously held a render/pointsBillboardRender/blend clamp for the premultiplied-divide
// singularity — the additive trail has HDR alpha (>1) -> (1-trail.a) hugely negative, and
// Blender's MSL codegen amplifies float ULP near that singularity into +/-65504 explosions.
// Reference commit a0d8ea14/77e45a5e now `clamp(...)`s that output natively, so the host override
// is no longer needed; the generic transform carries the reference clamp through verbatim.)
const PROGRAM_OVERRIDES = {
}

function* enumeratePrograms (filter) {
  for (const ns of NAMESPACES) {
    const nsDir = join(EFFECTS_DIR, ns)
    if (!existsSync(nsDir)) continue
    for (const entry of readdirSync(nsDir).sort()) {
      const dir = join(nsDir, entry)
      if (!statSync(dir).isDirectory()) continue
      if (filter && `${ns}/${entry}` !== filter) continue
      const glslDir = join(dir, 'glsl')
      if (!existsSync(glslDir)) continue
      for (const g of readdirSync(glslDir).sort()) {
        if (g.endsWith('.vert')) {
          const base = basename(g, '.vert')
          const fragPath = join(glslDir, base + '.frag')
          if (existsSync(fragPath)) {
            yield { ns, name: entry, program: base, kind: 'vertfrag', vertPath: join(glslDir, g), fragPath }
          }
        } else if (g.endsWith('.glsl')) {
          yield { ns, name: entry, program: basename(g, '.glsl'), kind: 'frag', path: join(glslDir, g) }
        }
      }
    }
  }
}

function main () {
  const argv = process.argv.slice(2)
  const dryRun = argv.includes('--dry-run')
  const filter = argv.find(a => !a.startsWith('--')) || null
  let written = 0, flagged = 0, programs = 0
  const flags = []
  for (const prog of enumeratePrograms(filter)) {
    const { ns, name, program, kind } = prog
    programs++
    let res
    try {
      res = kind === 'vertfrag'
        ? transpileVertFrag(readFileSync(prog.vertPath, 'utf8'), readFileSync(prog.fragPath, 'utf8'))
        : transpile(readFileSync(prog.path, 'utf8'), ns, name)
    } catch (err) {
      flagged++; flags.push(`${ns}/${name}/${program}: THREW ${err?.message || err}`); continue
    }
    const override = PROGRAM_OVERRIDES[`${ns}/${name}/${program}`]
    if (override) res.frag = override(res.frag)
    if (res.notes.length) { flagged++; flags.push(`${ns}/${name}/${program}: ${res.notes.join('; ')}`) }
    if (!dryRun) {
      const outDir = join(OUT_DIR, ns, name)
      mkdirSync(outDir, { recursive: true })
      writeFileSync(join(outDir, `${program}.frag`), res.frag)
      if (kind === 'vertfrag') writeFileSync(join(outDir, `${program}.vert`), res.vert)
      writeFileSync(join(outDir, `${program}.createinfo.json`), JSON.stringify(res.descriptor, null, 2) + '\n')
    }
    written++
  }
  process.stderr.write(`\n[blender-shaders] ${dryRun ? 'would write' : 'wrote'} ${written}/${programs} program(s); ${flagged} flagged.\n`)
  for (const f of flags) process.stderr.write(`  ! ${f}\n`)
}

main()

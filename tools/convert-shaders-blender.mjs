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
const REFERENCE_ROOT = process.env.NM_REFERENCE_ROOT
  ? resolve(process.env.NM_REFERENCE_ROOT)
  : resolve(__dirname, '..', '..', 'noisemaker')
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

function transpile (src) {
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
  return { frag, descriptor, notes }
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
        if (!g.endsWith('.glsl')) continue
        yield { ns, name: entry, program: basename(g, '.glsl'), path: join(glslDir, g) }
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
  for (const { ns, name, program, path } of enumeratePrograms(filter)) {
    programs++
    let res
    try { res = transpile(readFileSync(path, 'utf8')) } catch (err) {
      flagged++; flags.push(`${ns}/${name}/${program}: THREW ${err?.message || err}`); continue
    }
    if (res.notes.length) { flagged++; flags.push(`${ns}/${name}/${program}: ${res.notes.join('; ')}`) }
    if (!dryRun) {
      const outDir = join(OUT_DIR, ns, name)
      mkdirSync(outDir, { recursive: true })
      writeFileSync(join(outDir, `${program}.frag`), res.frag)
      writeFileSync(join(outDir, `${program}.createinfo.json`), JSON.stringify(res.descriptor, null, 2) + '\n')
    }
    written++
  }
  process.stderr.write(`\n[blender-shaders] ${dryRun ? 'would write' : 'wrote'} ${written}/${programs} program(s); ${flagged} flagged.\n`)
  for (const f of flags) process.stderr.write(`  ! ${f}\n`)
}

main()

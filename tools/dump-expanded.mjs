#!/usr/bin/env node
// dump-expanded.mjs — REFERENCE expand() oracle.
//
// Runs the UNCHANGED reference compile(source) then expand(compilationResult) and
// dumps { passes, programs, textureSpecs, renderSurface } as canonical JSON. This
// is the golden the ported Python expander (stage 4) is diffed against — the
// Logical-Graph -> Render-Graph step that the resource allocator (stage 5) then
// consumes.
//
// expand() resolves effect definitions via getEffect(), so we run the SAME
// effect-registration bootstrap as tools/export-graph.mjs / dump-compile.mjs
// before calling compile()+expand(). The bootstrap is lifted from export-graph.mjs.
//
// `programs` entries carry the full shader source in the reference output. The
// graph-structure golden only needs the per-program uniformLayout + defines (the
// shader SOURCE is ported separately as .frag files), so we strip source and keep
// { uniformLayout, defines } — mirroring export-graph.mjs normalizePrograms().
//
// Usage:
//   node dump-expanded.mjs <file.dsl>          # prints JSON to stdout
//   node dump-expanded.mjs <file.dsl> out.json # writes JSON to out.json
//
// Env: NM_REFERENCE_ROOT  reference engine source root (REQUIRED; no `..` default)

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, resolve, basename } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

if (!process.env.NM_REFERENCE_ROOT) {
  console.error('NM_REFERENCE_ROOT must point at the Noisemaker reference engine source root')
  process.exit(1)
}
const REFERENCE_ROOT = resolve(process.env.NM_REFERENCE_ROOT)
const SRC_INDEX = join(REFERENCE_ROOT, 'shaders', 'src', 'index.js')
const EFFECTS_DIR = join(REFERENCE_ROOT, 'shaders', 'effects')

// ---------------------------------------------------------------------------
// Reference engine bootstrap — LIFTED from tools/export-graph.mjs
// bootstrapReference(). Identical to dump-compile.mjs's, but also returns
// `expand` (and `compile`).
// ---------------------------------------------------------------------------
async function bootstrapReference () {
  const mod = await import(pathToFileURL(SRC_INDEX).href)
  const {
    compile, registerEffect, registerOp, registerStarterOps,
    mergeIntoEnums, stdEnums, sanitizeEnumName
  } = mod

  if (mergeIntoEnums && stdEnums) await mergeIntoEnums(stdEnums)
  if (registerStarterOps) registerStarterOps()

  const allChoices = {}

  const namespaces = readdirSync(EFFECTS_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => d.name)

  for (const namespace of namespaces) {
    const nsDir = join(EFFECTS_DIR, namespace)
    let effectNames
    try {
      effectNames = readdirSync(nsDir, { withFileTypes: true })
        .filter(d => d.isDirectory())
        .map(d => d.name)
    } catch {
      continue
    }
    for (const name of effectNames) {
      const defPath = join(nsDir, name, 'definition.js')
      try { statSync(defPath) } catch { continue }
      let effectMod
      try {
        effectMod = await import(pathToFileURL(defPath).href)
      } catch (err) {
        process.stderr.write(`[dump-expanded] skip ${namespace}/${name}: ${err?.message || err}\n`)
        continue
      }
      const def = effectMod.default
      const instance = (typeof def === 'function') ? new def() : def
      if (!instance) continue
      if (!instance.namespace) instance.namespace = namespace

      const func = instance.func || name
      registerEffect(func, instance)
      registerEffect(`${namespace}.${func}`, instance)
      registerEffect(`${namespace}/${name}`, instance)
      registerEffect(`${namespace}.${name}`, instance)

      const args = Object.entries(instance.globals || {}).map(([key, spec]) => {
        let enumPath = spec.enum || spec.enumPath
        if (spec.choices && !enumPath) {
          enumPath = `${namespace}.${func}.${key}`
          allChoices[namespace] = allChoices[namespace] || {}
          allChoices[namespace][func] = allChoices[namespace][func] || {}
          allChoices[namespace][func][key] = allChoices[namespace][func][key] || {}
          for (const [nm, val] of Object.entries(spec.choices)) {
            if (typeof nm === 'string' && nm.endsWith(':')) continue // group header
            allChoices[namespace][func][key][nm] = { type: 'Number', value: val }
            const san = sanitizeEnumName ? sanitizeEnumName(nm) : nm
            if (san && san !== nm) allChoices[namespace][func][key][san] = { type: 'Number', value: val }
          }
        }
        return {
          name: key,
          type: spec.type === 'vec4' ? 'color' : spec.type,
          default: spec.default,
          enum: enumPath,
          enumPath,
          min: spec.min,
          max: spec.max,
          uniform: spec.uniform,
          choices: spec.choices
        }
      })
      if (registerOp) registerOp(`${namespace}.${func}`, { name: func, args })

      const isStarter = !((instance.passes || []).some(p =>
        p.inputs && Object.values(p.inputs).some(v =>
          ['inputTex', 'inputTex3d', 'src', 'o0', 'o1'].includes(v))))
      if (isStarter && registerStarterOps) registerStarterOps([`${namespace}.${func}`])
      if (instance.enums && mergeIntoEnums) await mergeIntoEnums(instance.enums)
    }
  }

  if (mergeIntoEnums && Object.keys(allChoices).length) await mergeIntoEnums(allChoices)

  const expanderMod = await import(pathToFileURL(join(REFERENCE_ROOT, 'shaders', 'src', 'runtime', 'expander.js')).href)
  return { compile, expand: expanderMod.expand }
}

// Strip shader source from programs; keep only uniformLayout + defines. The
// graph-structure golden never needs source (it's ported as .frag separately).
function normalizePrograms (programs) {
  const out = {}
  for (const [id, prog] of Object.entries(programs || {})) {
    out[id] = {
      uniformLayout: prog.uniformLayout || null,
      defines: prog.defines || {}
    }
  }
  return out
}

async function main () {
  const file = process.argv[2]
  if (!file) { process.stderr.write('usage: node dump-expanded.mjs <file.dsl> [out.json]\n'); process.exit(2) }
  const outPath = process.argv[3]

  const { compile, expand } = await bootstrapReference()
  const src = readFileSync(file, 'utf8')

  const compilationResult = compile(src)
  // Surface validation errors the same way compileGraph() does, so an invalid
  // program fails loudly instead of silently dumping a partial expansion.
  const errors = (compilationResult.diagnostics || []).filter(d => d.severity === 'error')
  if (errors.length) {
    throw { code: 'ERR_COMPILATION_FAILED', diagnostics: compilationResult.diagnostics }
  }

  const { passes, errors: expandErrors, programs, textureSpecs, renderSurface } = expand(compilationResult, {})
  if (expandErrors && expandErrors.length) {
    throw { code: 'ERR_EXPANSION_FAILED', errors: expandErrors }
  }

  const result = {
    passes,
    programs: normalizePrograms(programs),
    textureSpecs,
    renderSurface
  }
  const json = JSON.stringify(result)

  if (outPath) {
    writeFileSync(outPath, json + '\n')
    process.stderr.write(`[dump-expanded] wrote ${outPath} (${(passes || []).length} passes)\n`)
  } else {
    process.stdout.write(json + '\n')
  }
}

if (basename(process.argv[1] || '') === 'dump-expanded.mjs') {
  main().catch(err => {
    process.stderr.write(`[dump-expanded] FAILED: ${err?.stack || err?.message || JSON.stringify(err)}\n`)
    process.exit(1)
  })
}

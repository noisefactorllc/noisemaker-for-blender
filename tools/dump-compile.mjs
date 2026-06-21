#!/usr/bin/env node
// dump-compile.mjs — REFERENCE compile() oracle.
//
// Runs the UNCHANGED reference `compile(source)` (shaders/src/lang/index.js:
// lex -> parse -> validate) on a DSL file and dumps the validated
// compilationResult ({ plans, diagnostics, render, vars, searchNamespaces }) as
// canonical JSON. This is the golden the ported Python validator (stage 3) is
// diffed against — the intermediate between parse (stage 2) and expand (stage 4).
//
// validate() resolves effect ops via the `ops` registry, so we MUST run the same
// effect-registration bootstrap as tools/export-graph.mjs before calling compile()
// (otherwise every effect op fails S001 "Unknown effect"). The bootstrap is lifted
// from export-graph.mjs.
//
// Usage:
//   node dump-compile.mjs <file.dsl>          # prints JSON to stdout
//   node dump-compile.mjs <file.dsl> out.json # writes JSON to out.json
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
// bootstrapReference(). Registers every effect under all lookup-key forms,
// registers ops (so the validator resolves them), seeds std enums + starter ops,
// and registers each param's choices as resolvable enum members.
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
        process.stderr.write(`[dump-compile] skip ${namespace}/${name}: ${err?.message || err}\n`)
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

  return { compile }
}

async function main () {
  const file = process.argv[2]
  if (!file) { process.stderr.write('usage: node dump-compile.mjs <file.dsl> [out.json]\n'); process.exit(2) }
  const outPath = process.argv[3]

  const { compile } = await bootstrapReference()
  const src = readFileSync(file, 'utf8')
  const result = compile(src)
  const json = JSON.stringify(result)

  if (outPath) {
    writeFileSync(outPath, json + '\n')
    process.stderr.write(`[dump-compile] wrote ${outPath} (${(result.plans || []).length} plan(s))\n`)
  } else {
    process.stdout.write(json + '\n')
  }
}

if (basename(process.argv[1] || '') === 'dump-compile.mjs') {
  main().catch(err => {
    process.stderr.write(`[dump-compile] FAILED: ${err?.stack || err?.message || JSON.stringify(err)}\n`)
    process.exit(1)
  })
}

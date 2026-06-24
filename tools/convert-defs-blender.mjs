#!/usr/bin/env node
// convert-defs-blender.mjs — NORMALIZED effect-definition extractor for the
// in-Blender DSL->graph compiler port (stages 3-5: validator, expander, resources).
//
// Walks <ref>/shaders/effects/<ns>/<name>/definition.js, instantiates each
// reference Effect, and emits a NORMALIZED JSON port artifact to
//   blender/noisemaker_blender/effects/<namespace>/<func>.json
//
// This is a DERIVED artifact (exactly like the transpiled .frag shaders): it
// contains ONLY the fields the ported validator + expander + resource allocator
// read from an effect definition, re-serialized into the port's own stable shape.
// It is NOT a verbatim copy of definition.js — UI metadata, lifecycle hooks, and
// shader source are all dropped, and field order is fixed by this tool.
//
// The set of captured fields was derived by reading the reference:
//   * shaders/src/runtime/expander.js  — expand(): every effectDef.<X> access
//   * shaders/src/lang/validator.js     — validate(): consumes the `ops` registry,
//                                          which the bootstrap builds from globals
//   * shaders/src/runtime/effect.js     — the Effect class (assignable config keys)
//   * shaders/src/runtime/compiler.js   — extractTextureSpecs(): texture dims/format
// See SCHEMA below for the contract.
//
// Usage:
//   node convert-defs-blender.mjs            # extract ALL effects
//   node convert-defs-blender.mjs --dry-run  # count only, write nothing
//   node convert-defs-blender.mjs synth/noise  # one effect (ns/dirname)
//
// Env:
//   NM_REFERENCE_ROOT   reference engine source root (REQUIRED; no `..` default)

import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync, rmSync, existsSync } from 'node:fs'
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

// Output: the addon's effects/ package dir. The Python registry loads from here.
const OUT_DIR = process.env.NM_OUT_DIR
  ? resolve(process.env.NM_OUT_DIR)
  : resolve(__dirname, '..', 'blender', 'noisemaker_blender', 'effects')

// ---------------------------------------------------------------------------
// Reference engine bootstrap — LIFTED from tools/export-graph.mjs bootstrapReference().
//
// Effects do NOT self-register on import (definition.js only `export default new
// Effect(...)`). We mirror the registration the demo/tests perform: walk every
// effects/<ns>/<name>/definition.js, instantiate the Effect, infer the namespace
// from the directory when omitted, and register under all lookup-key forms.
//
// We DO NOT need compileGraph/registerOp/enums here (this tool emits data, not a
// graph), but we keep the same walk + namespace-inference + instantiation so the
// extracted set is identical to what the golden graph tooling registers.
// ---------------------------------------------------------------------------
async function collectEffects (filter) {
  // Import the index so the reference's module graph initializes identically to
  // export-graph.mjs (some effects pull shared helpers transitively). We don't
  // call into it, but importing keeps init side effects in lockstep.
  await import(pathToFileURL(SRC_INDEX).href)

  const out = []
  const namespaces = readdirSync(EFFECTS_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => d.name)
    .sort()

  for (const namespace of namespaces) {
    const nsDir = join(EFFECTS_DIR, namespace)
    let effectNames
    try {
      effectNames = readdirSync(nsDir, { withFileTypes: true })
        .filter(d => d.isDirectory())
        .map(d => d.name)
        .sort()
    } catch {
      continue
    }
    for (const name of effectNames) {
      if (filter && `${namespace}/${name}` !== filter) continue
      const defPath = join(nsDir, name, 'definition.js')
      try { statSync(defPath) } catch { continue }
      let effectMod
      try {
        effectMod = await import(pathToFileURL(defPath).href)
      } catch (err) {
        process.stderr.write(`[convert-defs] skip ${namespace}/${name}: ${err?.message || err}\n`)
        continue
      }
      const def = effectMod.default
      const instance = (typeof def === 'function') ? new def() : def
      if (!instance) continue
      // 17 effect definitions omit an explicit `namespace:` field; the reference
      // infers it from the directory at registration. Mirror that here so the
      // normalized def (and its registry keys) carry the authoritative namespace.
      if (!instance.namespace) instance.namespace = namespace
      out.push({ namespace, name, instance })
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// NORMALIZED SCHEMA. Each emitted JSON object has this shape (fields omitted when
// the source effect doesn't define them, EXCEPT name/namespace/func/globals/
// passes/textures which are always present so consumers can rely on them):
//
// {
//   name, namespace, func,            // identity
//   tags,                             // [string] (optional)
//   paramAliases,                     // { aliasName: realName } (validator: resolveParamAliases)
//   externalTexture,                  // string (expander: media/text/meshLoader external input)
//   defaultProgram,                   // string (optional, informational)
//   hidden, deprecatedBy,             // optional flags
//   // Pipeline passthrough declarations (expander reads all of these):
//   outputTex, outputTex3d, outputGeo, outputXyz, outputVel, outputRgba,
//   // Per-program / single uniform layouts (expander attaches to programs):
//   uniformLayout, uniformLayouts,
//   globals: {                        // name -> spec, DECLARATION ORDER PRESERVED
//     <name>: {
//       type,                         // float|int|boolean|vec2|vec3|vec4|color|surface|member|palette|string|volume|geometry
//       default, uniform, define,
//       min, max, zero,
//       choices,                      // { memberName: number|null }  (null = group header)
//       enum, enumPath,               // external enum table ref
//       colorModeUniform,             // surface params: which uniform tracks none/not-none
//       defaultFrom                   // numeric params: inherit default from sibling arg
//     }
//   },
//   passes: [ {                       // ORDER PRESERVED
//     name, program,
//     inputs, outputs, uniforms,      // {} when absent
//     drawMode, drawBuffers,
//     count, countUniform,
//     repeat, blend, clear,
//     type, entryPoint,               // pass execution type / compute entry (defensive)
//     workgroups, storageBuffers, storageTextures  // WebGPU (defensive; unused today)
//   } ],
//   textures: {                       // name -> spec  (2D + 3D merged; 3D carry is3D)
//     <name>: { width, height, depth, is3D, format }
//   }
// }
//
// Dimension specs (width/height/depth) are passed through verbatim: a number, the
// string 'screen', or an object { param: <name>, default: <n> } / { screenDivide: <n> }.
// ---------------------------------------------------------------------------

function projectGlobal (spec) {
  const out = {}
  if (spec.type !== undefined) out.type = spec.type
  if (spec.default !== undefined) out.default = spec.default
  if (spec.uniform !== undefined) out.uniform = spec.uniform
  if (spec.define !== undefined) out.define = spec.define
  if (spec.min !== undefined) out.min = spec.min
  if (spec.max !== undefined) out.max = spec.max
  if (spec.zero !== undefined) out.zero = spec.zero
  // choices: keep group-header (null-valued) entries too — the validator/expander
  // skip them, but preserving them keeps member-index ordering identical to source.
  if (spec.choices !== undefined) out.choices = spec.choices
  if (spec.enum !== undefined) out.enum = spec.enum
  if (spec.enumPath !== undefined) out.enumPath = spec.enumPath
  if (spec.colorModeUniform !== undefined) out.colorModeUniform = spec.colorModeUniform
  if (spec.defaultFrom !== undefined) out.defaultFrom = spec.defaultFrom
  return out
}

function projectGlobals (globals) {
  const out = {}
  if (!globals) return out
  // Object.entries preserves declaration order — parity-critical (palette index =
  // positional key order; compile-time-define suffix sorts names but defaults
  // resolve in declaration order). DO NOT sort.
  for (const [key, spec] of Object.entries(globals)) {
    out[key] = projectGlobal(spec || {})
  }
  return out
}

function projectPass (pass) {
  const out = { name: pass.name, program: pass.program }
  out.inputs = pass.inputs || {}
  out.outputs = pass.outputs || {}
  // Pass-level uniform->global mapping ({ uniformName: 'globalParamName' }).
  if (pass.uniforms !== undefined) out.uniforms = pass.uniforms
  else out.uniforms = {}
  // Execution modifiers (agent/compute/MRT/iterated passes). Captured only when
  // present so absence stays distinguishable from a 0/false value.
  if (pass.drawMode !== undefined) out.drawMode = pass.drawMode
  if (pass.drawBuffers !== undefined) out.drawBuffers = pass.drawBuffers
  if (pass.count !== undefined) out.count = pass.count
  if (pass.countUniform !== undefined) out.countUniform = pass.countUniform
  if (pass.repeat !== undefined) out.repeat = pass.repeat
  if (pass.blend !== undefined) out.blend = pass.blend
  // Pass-gating conditions ({ runIf:[{uniform,equals}], skipIf:[...] }). The runtime pipeline
  // (pipeline.should_skip) resolves these against the live uniform value to choose which of two
  // same-program passes executes (e.g. pointsBillboardRender deposit vs deposit_alpha). Captured
  // here from the effect def, but NOT baked into the expanded graph — the reference golden graph
  // omits conditions, so the in-engine expander must not emit them or graph parity breaks. The
  // pipeline reads them from this def via the registry at render time (matching the reference,
  // whose Pipeline.shouldSkipPass reads conditions off the effect-def pass, not the graph).
  if (pass.conditions !== undefined) out.conditions = pass.conditions
  if (pass.clear !== undefined) out.clear = pass.clear
  if (pass.type !== undefined) out.type = pass.type
  if (pass.entryPoint !== undefined) out.entryPoint = pass.entryPoint
  // WebGPU-only (no current effect uses these, but the expander forwards them).
  if (pass.workgroups !== undefined) out.workgroups = pass.workgroups
  if (pass.storageBuffers !== undefined) out.storageBuffers = pass.storageBuffers
  if (pass.storageTextures !== undefined) out.storageTextures = pass.storageTextures
  return out
}

function projectTexture (spec, is3D) {
  const t = {}
  if (spec.width !== undefined) t.width = spec.width
  if (spec.height !== undefined) t.height = spec.height
  if (spec.depth !== undefined) t.depth = spec.depth
  if (is3D || spec.is3D) t.is3D = true
  // Copy format ONLY when the reference declares it — the expander emits texture
  // specs verbatim (`{...spec}`), and its parity golden is dumped BEFORE the
  // `format || 'rgba16f'` default is applied (that default lives in the next
  // stage, extractTextureSpecs()). Baking the default in here would inject a
  // `format` key the reference spec doesn't have (e.g. navierStokes'
  // global_ns_smoothed), breaking expander parity. Defaulting stays downstream.
  if (spec.format !== undefined) t.format = spec.format
  return t
}

function projectTextures (instance) {
  const out = {}
  if (instance.textures) {
    for (const [id, spec] of Object.entries(instance.textures)) {
      out[id] = projectTexture(spec || {}, false)
    }
  }
  // textures3d (none present today, but the expander reads it and tags is3D).
  if (instance.textures3d) {
    for (const [id, spec] of Object.entries(instance.textures3d)) {
      out[id] = projectTexture(spec || {}, true)
    }
  }
  return out
}

function normalizeEffect (instance, namespace, name) {
  const func = instance.func || name
  const def = {
    name: instance.name || func,
    namespace: instance.namespace || namespace,
    func
  }
  if (instance.tags !== undefined) def.tags = instance.tags
  // paramAliases: validator.resolveParamAliases() rewrites deprecated kwarg names.
  def.paramAliases = instance.paramAliases || {}
  // externalTexture: expander binds `${texRef}_step_${i}` for media/text/meshLoader.
  if (instance.externalTexture !== undefined) def.externalTexture = instance.externalTexture
  if (instance.defaultProgram !== undefined) def.defaultProgram = instance.defaultProgram
  if (instance.hidden) def.hidden = true
  if (instance.deprecatedBy !== undefined) def.deprecatedBy = instance.deprecatedBy
  // Uniform layouts — the expander copies these onto each program entry.
  if (instance.uniformLayout !== undefined) def.uniformLayout = instance.uniformLayout
  if (instance.uniformLayouts !== undefined) def.uniformLayouts = instance.uniformLayouts
  // Pipeline passthrough declarations — expander updates 2D/3D/agent cursors.
  if (instance.outputTex !== undefined) def.outputTex = instance.outputTex
  if (instance.outputTex3d !== undefined) def.outputTex3d = instance.outputTex3d
  if (instance.outputGeo !== undefined) def.outputGeo = instance.outputGeo
  if (instance.outputXyz !== undefined) def.outputXyz = instance.outputXyz
  if (instance.outputVel !== undefined) def.outputVel = instance.outputVel
  if (instance.outputRgba !== undefined) def.outputRgba = instance.outputRgba
  def.globals = projectGlobals(instance.globals)
  def.passes = (instance.passes || []).map(projectPass)
  def.textures = projectTextures(instance)
  return def
}

async function main () {
  const argv = process.argv.slice(2)
  const dryRun = argv.includes('--dry-run')
  const filter = argv.find(a => !a.startsWith('--')) || null

  const collected = await collectEffects(filter)

  // Clean regen: remove stale per-namespace dirs so a renamed/removed effect
  // doesn't leave an orphan JSON behind. Only when doing a full (unfiltered) run.
  if (!dryRun && !filter && existsSync(OUT_DIR)) {
    for (const entry of readdirSync(OUT_DIR, { withFileTypes: true })) {
      if (entry.isDirectory()) rmSync(join(OUT_DIR, entry.name), { recursive: true, force: true })
    }
  }

  let written = 0
  for (const { namespace, name, instance } of collected) {
    const def = normalizeEffect(instance, namespace, name)
    const outNsDir = join(OUT_DIR, def.namespace)
    const outPath = join(outNsDir, `${def.func}.json`)
    if (!dryRun) {
      mkdirSync(outNsDir, { recursive: true })
      writeFileSync(outPath, JSON.stringify(def, null, 2) + '\n')
    }
    written++
  }

  process.stderr.write(
    `[convert-defs] ${dryRun ? 'would extract' : 'extracted'} ${written} effect(s) -> ${OUT_DIR}\n`
  )
  // Print the count to stdout for easy scripting/verification.
  process.stdout.write(`${written}\n`)
}

if (basename(process.argv[1] || '') === 'convert-defs-blender.mjs') {
  main().catch(err => {
    process.stderr.write(`[convert-defs] FAILED: ${err?.stack || err?.message || JSON.stringify(err)}\n`)
    process.exit(1)
  })
}

#!/usr/bin/env node
// dump-ast.mjs — dump the REFERENCE parser's AST for a DSL file as canonical JSON. The golden
// the Python parser port is diffed against (parity/compiler/check_parse.py). `parse(lex(src))`
// is self-contained for the builtin namespaces (shaders/src/runtime/tags.js seeds them), so no
// effect bootstrap is needed at the parse stage.
//
// Env: NM_REFERENCE_ROOT  reference repo root (default ../noisemaker)
import { readFileSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { importStableReference } from './stable-reference.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
if (!process.env.NM_REFERENCE_ROOT) {
  console.error('NM_REFERENCE_ROOT must point at the Noisemaker reference engine source root')
  process.exit(1)
}
const REF = resolve(process.env.NM_REFERENCE_ROOT)

const lang = await importStableReference(REF, join(REF, 'shaders', 'src', 'lang', 'index.js'))
const { lex, parse } = lang

const file = process.argv[2]
if (!file) { process.stderr.write('usage: node dump-ast.mjs <file.dsl>\n'); process.exit(2) }
const src = readFileSync(file, 'utf8')
const astNode = parse(lex(src))
process.stdout.write(JSON.stringify(astNode))

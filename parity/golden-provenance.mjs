// golden-provenance.mjs — the renderer authority and the provenance record for
// reference goldens, shared by parity/golden-cdp.mjs (minting) and checked by
// scripts/parity-summary (grading).
//
// parity/authority-renderer declares the renderer the authority goldens are
// minted on: a golden counts only when the WebGL2 renderer string it was
// minted on contains that declaration and is not SwiftShader. provenance.json
// binds each golden to its sha256, the reference revision it was rendered from
// and that renderer string.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const AUTHORITY_RENDERER = path.join(path.dirname(fileURLToPath(import.meta.url)), 'authority-renderer')

export function declaredRenderer () {
  const declared = fs.readFileSync(AUTHORITY_RENDERER, 'utf8').trim()
  if (!declared) throw new Error(`${AUTHORITY_RENDERER} declares no renderer`)
  return declared
}

export function isAuthorityRenderer (renderer, declared = declaredRenderer()) {
  return typeof renderer === 'string' && !/swiftshader/i.test(renderer) && renderer.includes(declared)
}

// Record <outDir>/<name>.golden.png in <outDir>/provenance.json. Refuses a
// renderer that is not the declared authority, so no golden from another
// renderer can be attributed to it.
export function recordGolden (outDir, name, { referenceRevision, renderer }) {
  const declared = declaredRenderer()
  if (!isAuthorityRenderer(renderer, declared)) {
    throw new Error(`${name}: renderer ${JSON.stringify(renderer ?? null)} is not the declared authority ` +
      `"${declared}" (parity/authority-renderer)`)
  }
  const png = fs.readFileSync(path.join(outDir, `${name}.golden.png`))
  const pvPath = path.join(outDir, 'provenance.json')
  let pv
  try { pv = JSON.parse(fs.readFileSync(pvPath, 'utf8')) } catch (e) { pv = { files: {} } }
  pv.reference_revision = referenceRevision || null
  pv.renderer = renderer
  pv.files = pv.files || {}
  pv.files[name] = {
    sha256: crypto.createHash('sha256').update(png).digest('hex'),
    bytes: png.length,
    reference_revision: referenceRevision || null,
    renderer,
  }
  fs.writeFileSync(pvPath, JSON.stringify(pv, null, 2) + '\n')
  return pv.files[name]
}

import { registerHooks } from 'node:module'
import { realpathSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const parserImports = new Map()

// Compare the port against the effect grammar of the pinned reference release.
// Load each reference parser once, before any graph tool imports the engine.
async function loadEffectParser (parser) {
  let verified = false
  const hooks = registerHooks({
    load (url, context, nextLoad) {
      const result = nextLoad(url, context)
      if (url !== parser) return result
      const source = Buffer.from(result.source).toString('utf8')
      const markers = [
        ["const allowMixed = true", "const allowMixed = nameToken.lexeme === 'midi' || nameToken.lexeme === 'audio'"],
        ["'LPAREN', 'LBRACKET', 'LBRACE',", "'LPAREN', 'LBRACKET',"],
        [/^            case 'LBRACE': \{[\s\S]*?^            }\n(?=            default:)/m, '']
      ]
      let stableSource = source
      for (const [marker, replacement] of markers) {
        if (stableSource.split(marker).length !== 2) throw new Error('Verify the pinned reference parser grammar before generating parity data')
        stableSource = stableSource.replace(marker, replacement)
      }
      verified = true
      return { ...result, source: stableSource }
    }
  })
  try {
    await import(parser)
    if (!verified) throw new Error('The reference parser was not loaded for the effect grammar parity check')
  } finally {
    hooks.deregister()
  }
}

export async function importStableReference (root, entry) {
  const parser = pathToFileURL(realpathSync(join(root, 'shaders/src/lang/parser.js'))).href
  if (!parserImports.has(parser)) parserImports.set(parser, loadEffectParser(parser))
  await parserImports.get(parser)
  return import(pathToFileURL(entry).href)
}

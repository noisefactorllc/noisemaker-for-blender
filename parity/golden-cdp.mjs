// golden-cdp.mjs — render reference-engine goldens over raw CDP (no npm installs).
//
// Replicates the reference demo's renderOne determinism against the reference
// served at NM_DEMO_URL, with a caller-configurable output dir and frame
// protocol so scripts/parity-summary can drive it.
//
// Usage: node parity/golden-cdp.mjs <name>=<dslPath>...
//   NM_GOLDEN_OUT   output dir (required) — writes <name>.golden.png + <name>.graph.json
//   NM_GOLDEN_FRAMES  frames per case (default 8; 0 timestep => every frame at the same time)
//   NM_GOLDEN_SIZE    render size (default 256)
//   NM_GOLDEN_TIME    normalized time (default 0.25)
//   NM_GOLDEN_TIMESTEP per-frame timestep (default 0; tt=(time+i*ts)%1 like batch-golden.mjs)
//   NM_CDP_PORT       Chromium DevTools port (default 9222)
//   NM_DEMO_URL       demo page URL (default http://127.0.0.1:$NM_SERVE_PORT/demo/shaders/, port 8777)
//   NM_REFERENCE_ROOT reference engine root (required, for the graph export)
//
// The caller must serve NM_REFERENCE_ROOT at the demo origin root (a static file
// server suffices: /demo/shaders/ is the app, /shaders/... its sources) and run
// headless Chromium on the host GPU with --remote-debugging-port=$NM_CDP_PORT
// --headless=new --use-angle=metal --no-sandbox.
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import crypto from 'node:crypto'
import { fileURLToPath, pathToFileURL } from 'node:url'

const OUT = process.env.NM_GOLDEN_OUT
if (!OUT) { console.error('NM_GOLDEN_OUT is required'); process.exit(2) }
const REFERENCE_ROOT = process.env.NM_REFERENCE_ROOT
if (!REFERENCE_ROOT) { console.error('NM_REFERENCE_ROOT is required'); process.exit(2) }
const CDP_PORT = process.env.NM_CDP_PORT || '9222'
const DEMO_URL = process.env.NM_DEMO_URL || `http://127.0.0.1:${process.env.NM_SERVE_PORT || '8777'}/demo/shaders/`
const SIZE = parseInt(process.env.NM_GOLDEN_SIZE || '256', 10)
const TIME = parseFloat(process.env.NM_GOLDEN_TIME || '0.25')
const FRAMES = parseInt(process.env.NM_GOLDEN_FRAMES || '8', 10)
const TIMESTEP = parseFloat(process.env.NM_GOLDEN_TIMESTEP || '0')
const EXPORT_GRAPH = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'tools', 'export-graph.mjs')

fs.mkdirSync(OUT, { recursive: true })

function encodePng (w, h, rgba) {
  function crc32 (buf) { let c = 0xffffffff; for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1) } return (c ^ 0xffffffff) >>> 0 }
  function chunk (type, data) { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type, 'ascii'), data]); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body)); return Buffer.concat([len, body, crc]) }
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6
  const raw = Buffer.alloc(h * (1 + w * 4))
  for (let y = 0; y < h; y++) { const di = y * (1 + w * 4); raw[di] = 0; rgba.copy(raw, di + 1, y * w * 4, (y + 1) * w * 4) }
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))])
}

async function getWsUrl () {
  const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json`)
  const tabs = await res.json()
  const page = tabs.find(t => t.type === 'page')
  if (!page) throw new Error('no page target')
  return page.webSocketDebuggerUrl
}

class CDP {
  constructor (ws) { this.ws = ws; this.id = 0; this.pending = new Map() }
  static async connect (url) {
    const ws = new WebSocket(url)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    const c = new CDP(ws)
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.id && c.pending.has(m.id)) { const { res, rej } = c.pending.get(m.id); c.pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result) }
    }
    return c
  }
  send (method, params = {}) {
    const id = ++this.id
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej })
      this.ws.send(JSON.stringify({ id, method, params }))
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); rej(new Error('timeout ' + method)) } }, 300000)
    })
  }
  async evaluate (expr, arg) {
    const args = arg === undefined ? [] : [{ value: arg }]
    const r = await this.send('Runtime.evaluate', { expression: `(async () => { return (${expr}) })(${arg === undefined ? '' : JSON.stringify(arg)})`, awaitPromise: true, returnByValue: true, userGesture: true })
    if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails).slice(0, 800))
    return r.result.value
  }
}

async function waitFor (cdp, expr, timeoutMs = 300000) {
  const t0 = Date.now()
  for (;;) {
    let v
    try { v = await cdp.evaluate(expr) } catch (e) { v = false }
    if (v) return v
    if (Date.now() - t0 > timeoutMs) throw new Error('waitFor timeout: ' + expr.slice(0, 120))
    await new Promise(r => setTimeout(r, 1000))
  }
}

const PAIR = process.argv.slice(2).map(s => { const i = s.indexOf('='); return { name: s.slice(0, i), dsl: fs.readFileSync(s.slice(i + 1), 'utf8') } })
if (!PAIR.length) { console.error('usage: node golden-cdp.mjs name=dslPath ...'); process.exit(2) }

const { exportGraph } = await import(pathToFileURL(EXPORT_GRAPH).href)

// The authority is the reference's WebGL2 backend on the GPU class the add-on
// renders on, ANGLE over Metal on Apple silicon, served from NM_REFERENCE_ROOT.
// SwiftShader is never the authority: a CPU rasterizer resolves thresholds and
// nearest picks differently from the Metal GPU Blender renders on.
// scripts/parity-summary reuses a browser or a server already listening on its
// ports, so check both before minting: a browser on another renderer, or a
// server rooted at another checkout, would otherwise mint goldens that
// provenance.json attributes to the pinned revision.
const ROOT_PROBES = ['shaders/effects/manifest.json', 'shaders/src/runtime/pipeline.js']

async function checkAuthority (cdp) {
  const renderer = await cdp.evaluate(`(() => {
    const gl = window.__noisemakerRenderingPipeline?.backend?.gl
    if (!gl) return null
    const ext = gl.getExtension('WEBGL_debug_renderer_info')
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER))
  })()`)
  if (/swiftshader/i.test(renderer || '')) {
    throw new Error(`the page renders on ${renderer}: goldens are minted on the GPU class the add-on ` +
      'renders on (ANGLE over Metal on Apple silicon), never on SwiftShader')
  }
  if (!/ANGLE Metal Renderer: Apple/i.test(renderer || '')) {
    throw new Error(`the page renders on ${renderer || 'no WebGL2 context'}, not ANGLE over Metal on ` +
      `Apple silicon; is another browser listening on NM_CDP_PORT ${CDP_PORT}?`)
  }
  for (const probe of ROOT_PROBES) {
    const res = await fetch(new URL(`../../${probe}`, DEMO_URL))
    const served = res.ok ? Buffer.from(await res.arrayBuffer()) : null
    if (!served || !served.equals(fs.readFileSync(path.join(REFERENCE_ROOT, probe)))) {
      throw new Error(`${DEMO_URL} does not serve NM_REFERENCE_ROOT (${probe} differs); ` +
        'is another server listening on NM_SERVE_PORT?')
    }
  }
}

async function main () {
  const cdp = await CDP.connect(await getWsUrl())
  await cdp.send('Page.enable')
  await cdp.send('Page.navigate', { url: DEMO_URL })
  await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)
  await checkAuthority(cdp)
  for (const it of PAIR) {
    // Determinism: reload between effects so every WebGL context starts from a
    // zero-initialized texture state (batch-golden.mjs renderOne contract).
    if (it !== PAIR[0]) {
      await cdp.send('Page.navigate', { url: DEMO_URL })
      await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)
    }
    try { const g = await exportGraph(it.dsl); fs.writeFileSync(path.join(OUT, `${it.name}.graph.json`), JSON.stringify(g, null, 2) + '\n') } catch (e) { console.error(`[golden] ${it.name} GRAPH-FAIL ${e?.message || e}`) }
    const baseId = await cdp.evaluate(`window.__noisemakerRenderingPipeline?.graph?.id ?? null`)
    await cdp.evaluate(`(() => { const ed = document.getElementById('dsl-editor'); const run = document.getElementById('dsl-run-btn'); ed.value = ${JSON.stringify(it.dsl)}; ed.dispatchEvent(new Event('input', { bubbles: true })); run.click(); return true })()`)
    await waitFor(cdp, `(() => {
      const s = (document.getElementById('status')?.textContent || '').toLowerCase()
      if (s.includes('error') || s.includes('failed')) throw new Error('DSL compile failed: ' + (document.getElementById('status')?.textContent || ''))
      const p = window.__noisemakerRenderingPipeline
      if (!(p && p.graph && p.graph.id !== ${JSON.stringify(baseId)} && p.isCompiling === false)) return false
      if (!s.includes('compiled')) return false
      if (window.__nmStableId === p.graph.id) { window.__nmStableCount = (window.__nmStableCount || 0) + 1 } else { window.__nmStableId = p.graph.id; window.__nmStableCount = 0 }
      return window.__nmStableCount >= 1
    })()`)
    await cdp.evaluate(`(() => { if (window.__noisemakerSetPaused) window.__noisemakerSetPaused(true); return true })()`)
    await cdp.evaluate(`(() => {
      const r = window.__noisemakerCanvasRenderer; const p = window.__noisemakerRenderingPipeline
      if (r && r.canvas) { r.canvas.width = ${SIZE}; r.canvas.height = ${SIZE}; if (r.canvas.style) { r.canvas.style.width = ${SIZE} + 'px'; r.canvas.style.height = ${SIZE} + 'px' } }
      if (p && typeof p.resize === 'function') p.resize(${SIZE}, ${SIZE})
      return true
    })()`)
    const res = await cdp.evaluate(`(() => {
      const p = window.__noisemakerRenderingPipeline
      if (window.__noisemakerSetPausedTime) window.__noisemakerSetPausedTime(${TIME})
      if (p) {
        const backend = p.backend
        if (backend?.textures && typeof backend.clearTexture === 'function') { for (const texId of backend.textures.keys()) backend.clearTexture(texId) }
        if (p.surfaces) {
          for (const [name, surface] of p.surfaces.entries()) {
            const readId = 'global_' + name + '_read', writeId = 'global_' + name + '_write'
            if (backend?.textures?.get?.(readId) && backend?.textures?.get?.(writeId)) { surface.read = readId; surface.write = writeId }
          }
        }
        p.frameIndex = 0; p.lastTime = 0
      }
      for (let i = 0; i < ${FRAMES}; i++) { const tt = (${TIME} + i * ${TIMESTEP}) % 1; if (p && p.render) p.render(tt); else if (window.__noisemakerCanvasRenderer && window.__noisemakerCanvasRenderer.render) window.__noisemakerCanvasRenderer.render(tt) }
      return true
    })()`)
    const out = await cdp.evaluate(`(() => {
      const pipeline = window.__noisemakerRenderingPipeline
      const gl = pipeline?.backend?.gl
      const surface = pipeline?.surfaces?.get(pipeline?.graph?.renderSurface || 'o0')
      if (!gl || !surface) return { error: 'no GL surface' }
      const info = pipeline.backend.textures?.get(surface.read)
      if (!info?.handle) return { error: 'no texture handle' }
      const { handle, width, height } = info
      const fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo)
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, handle, 0)
      if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo); return { error: 'FBO incomplete' } }
      const canFloat = !!(gl.getExtension('EXT_color_buffer_float') || gl.getExtension('WEBGL_color_buffer_float'))
      const isFloat = info.glFormat?.type === gl.HALF_FLOAT || info.glFormat?.type === gl.FLOAT
      gl.finish(); let rgba8
      if (isFloat && canFloat) { const buf = new Float32Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.FLOAT,buf); rgba8 = new Array(width*height*4); for (let i=0;i<buf.length;i++) rgba8[i]=Math.max(0,Math.min(255,Math.round(buf[i]*255))) }
      else { const buf = new Uint8Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,buf); rgba8 = Array.from(buf) }
      gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo)
      return { width, height, pixels: rgba8, graphId: pipeline.graph.id }
    })()`)
    if (out.error) throw new Error(it.name + ' readback: ' + out.error)
    const { width, height, pixels } = out
    const topDown = Buffer.alloc(width * height * 4)
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const s = ((height - 1 - y) * width + x) * 4, d = (y * width + x) * 4
      topDown[d] = pixels[s]; topDown[d + 1] = pixels[s + 1]; topDown[d + 2] = pixels[s + 2]; topDown[d + 3] = pixels[s + 3]
    }
    fs.writeFileSync(path.join(OUT, `${it.name}.golden.png`), encodePng(width, height, topDown))
    // Provenance manifest: binds every generated golden to its sha256 and the
    // reference revision the golden was rendered from, so a stale or foreign
    // golden in a reused work directory cannot pass as the authority image.
    const pvPath = path.join(OUT, 'provenance.json')
    let pv = {}
    try { pv = JSON.parse(fs.readFileSync(pvPath, 'utf8')) } catch (e) { pv = { files: {} } }
    pv.reference_revision = process.env.NM_GOLDEN_REF_REV || null
    pv.files = pv.files || {}
    pv.files[it.name] = { sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(OUT, `${it.name}.golden.png`))).digest('hex'), bytes: fs.statSync(path.join(OUT, `${it.name}.golden.png`)).size, reference_revision: process.env.NM_GOLDEN_REF_REV || null }
    fs.writeFileSync(pvPath, JSON.stringify(pv, null, 2) + '\n')
    console.log('OK', it.name, width + 'x' + height)
  }
  console.log('DONE')
  process.exit(0)
}

main().catch(e => { console.error('FATAL', e.message || e); process.exit(1) })

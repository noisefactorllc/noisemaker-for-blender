// CDP driver replicating parity/batch-golden.mjs renderOne against the reference
// demo, using system Chromium over the DevTools protocol (no npm installs).
// Usage: node cdp-golden.cjs <name=dslPath>... (pairs "name=/path/file.dsl")
// Writes <name>.golden.png + <name>.graph.json into /state/cache/scratch/refgoldens.
const http = require('http')
const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const OUT = '/state/cache/scratch/refgoldens'
const SIZE = 256
const TIME = 0.25
const FRAMES = 1 // render_all default NM_FRAMES=1

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
  const res = await fetch('http://127.0.0.1:9222/json')
  const tabs = await res.json()
  const page = tabs.find(t => t.type === 'page')
  if (!page) throw new Error('no page target')
  return page.webSocketDebuggerUrl
}

class CDP {
  constructor (ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = [] }
  static async connect (url) {
    const ws = new WebSocket(url)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    const c = new CDP(ws)
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.id && c.pending.has(m.id)) { const { res, rej } = c.pending.get(m.id); c.pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result) }
      else for (const h of c.handlers) h(m)
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

const PAIR = process.argv.slice(2).map(s => { const i = s.indexOf('='); return { name: s.slice(0, i), dsl: fs.readFileSync(s.slice(i + 1), 'utf8'), dslPath: s.slice(i + 1) } })

// export graph.json via the repo's exporter (same code path as batch-golden)
async function exportGraphs () {
  for (const it of PAIR) {
    const { exportGraph } = await import('/workspace/repos/noisemaker-for-blender/tools/export-graph.mjs')
    const g = await exportGraph(it.dsl)
    fs.writeFileSync(path.join(OUT, `${it.name}.graph.json`), JSON.stringify(g, null, 2) + '\n')
    console.log('graph', it.name)
  }
}

async function main () {
  await exportGraphs()
  const cdp = await CDP.connect(await getWsUrl())
  await cdp.send('Runtime.enable')
  await cdp.send('Page.enable')
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: SIZE, height: SIZE, deviceScaleFactor: 1, mobile: false })
  await cdp.send('Page.navigate', { url: 'http://127.0.0.1:8777/demo/shaders/' })
  await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)

  let first = true
  for (const it of PAIR) {
    if (!first) {
      await cdp.send('Page.navigate', { url: 'http://127.0.0.1:8777/demo/shaders/' })
      await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)
    }
    first = false
    // set DSL + run (same as renderOne)
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
      for (let i = 0; i < ${FRAMES}; i++) { const tt = ${TIME}; if (p && p.render) p.render(tt); else if (window.__noisemakerCanvasRenderer && window.__noisemakerCanvasRenderer.render) window.__noisemakerCanvasRenderer.render(tt) }
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
      const isFloat = glFormatCheck(info)
      function glFormatCheck (i) { return i.glFormat?.type === gl.HALF_FLOAT || i.glFormat?.type === gl.FLOAT }
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
    console.log('OK', it.name, width + 'x' + height)
  }
  console.log('DONE')
  process.exit(0)
}

main().catch(e => { console.error('FATAL', e.message || e); process.exit(1) })

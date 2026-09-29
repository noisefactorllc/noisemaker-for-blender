// golden-cdp-dump.mjs — dump reference-engine intermediate textures as raw
// float32 over CDP, for same-GPU texel diffing against the Blender port.
//
// Companion to golden-cdp.mjs: identical determinism protocol (fresh page per
// case, zero textures, frameIndex/lastTime reset, FRAMES renders at TIME),
// but instead of the final PNG it readbacks every named intermediate as raw
// RGBA float32 (top-down rows) plus the final image.
//
// Usage: node parity/golden-cdp-dump.mjs <name>=<dslPath>...
//   NM_DUMP_OUT      output dir (required) — writes <name>.<texid>.f32 (raw
//                    float32 LE, RGBA interleaved, top-down), <name>.final.png
//                    and <name>.dump.json {texId: {width, height, sha256}}
//   NM_DUMP_TEX      comma-separated texture ids to dump; special forms:
//                    "node:*" dumps every pass-internal node_* texture,
//                    "surface:<name>" dumps global surface <name> (its read
//                    buffer). Default "node:*,surface:o1,surface:o2,final".
//   Other env vars as golden-cdp.mjs (NM_GOLDEN_OUT is not used; NM_DUMP_OUT).
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import crypto from 'node:crypto'
import { fileURLToPath, pathToFileURL } from 'node:url'

const OUT = process.env.NM_DUMP_OUT
if (!OUT) { console.error('NM_DUMP_OUT is required'); process.exit(2) }
const CDP_PORT = process.env.NM_CDP_PORT || '9222'
const DEMO_URL = process.env.NM_DEMO_URL || 'http://127.0.0.1:8777/demo/shaders/'
const SIZE = parseInt(process.env.NM_GOLDEN_SIZE || '256', 10)
const TIME = parseFloat(process.env.NM_GOLDEN_TIME || '0.25')
const FRAMES = parseInt(process.env.NM_GOLDEN_FRAMES || '8', 10)
const TIMESTEP = parseFloat(process.env.NM_GOLDEN_TIMESTEP || '0')
const TEXSPEC = process.env.NM_DUMP_TEX || 'node:*,surface:o1,surface:o2,final'
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

const PAIR = process.argv.slice(2).map(s => {
  const i = s.indexOf('=')
  const name = s.slice(0, i)
  const src = s.slice(i + 1)
  const dsl = src.startsWith('@') ? process.env[src.slice(1)] : fs.readFileSync(src, 'utf8')
  return { name, dsl }
})
if (!PAIR.length) { console.error('usage: node golden-cdp-dump.mjs name=dslPath ...'); process.exit(2) }

const { exportGraph } = await import(pathToFileURL(EXPORT_GRAPH).href)

const READBACK_FN = `() => {
  function readTex (gl, info) {
    const { handle, width, height } = info
    const fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo)
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, handle, 0)
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo); return null }
    const canFloat = !!(gl.getExtension('EXT_color_buffer_float') || gl.getExtension('WEBGL_color_buffer_float'))
    const isFloat = info.glFormat?.type === gl.HALF_FLOAT || info.glFormat?.type === gl.FLOAT
    gl.finish()
    let buf
    if (isFloat && canFloat) { buf = new Float32Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.FLOAT,buf) }
    else { const b = new Uint8Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,b); const f = new Float32Array(b.length); for (let i=0;i<b.length;i++) f[i]=b[i]/255; buf = f }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo)
    // gl.readPixels is bottom-up; flip to top-down
    const out = new Float32Array(width*height*4)
    for (let y = 0; y < height; y++) out.set(buf.subarray((height-1-y)*width*4, (height-y)*width*4), y*width*4)
    return { width, height, data: out }
  }
  function b64 (f32) {
    const u = new Uint8Array(f32.buffer, f32.byteOffset, f32.byteLength); let s = ''
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, Math.min(i + 0x8000, u.length)))
    return btoa(s)
  }
  return { readTex, b64 }
}`

async function main () {
  const cdp = await CDP.connect(await getWsUrl())
  await cdp.send('Page.enable')
  await cdp.send('Page.navigate', { url: DEMO_URL })
  await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)
  for (const it of PAIR) {
    if (it !== PAIR[0]) {
      await cdp.send('Page.navigate', { url: DEMO_URL })
      await waitFor(cdp, `!!window.__noisemakerRenderingPipeline && !!document.getElementById('dsl-editor')`)
    }
    try { const g = await exportGraph(it.dsl); fs.writeFileSync(path.join(OUT, `${it.name}.graph.json`), JSON.stringify(g, null, 2) + '\n') } catch (e) { console.error(`[dump] ${it.name} GRAPH-FAIL ${e?.message || e}`) }
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
    await cdp.evaluate(`(() => {
      const p = window.__noisemakerRenderingPipeline
      const cap = ${JSON.stringify(process.env.NM_CAPTURE_PASS || null)}
      if (cap) {
        const be = p.backend
        window.__nmCapture = { log: [] }
        const origBind = be.bindUniforms.bind(be)
        be.bindUniforms = function (pass, program, state) {
          if (pass && pass.id === cap) {
            const j = v => Array.isArray(v) ? Array.from(v) : v
            window.__nmCapture.log = [{ passUniforms: pass.uniforms ? Object.fromEntries(Object.entries(pass.uniforms).map(([k, v]) => [k, j(v)])) : null,
              globalUniforms: state?.globalUniforms ? Object.fromEntries(Object.entries(state.globalUniforms).map(([k, v]) => [k, j(v)])) : null }]
          }
          return origBind(pass, program, state)
        }
        const origTex = be.bindTextures.bind(be)
        be.bindTextures = function (pass, program, state) {
          if (pass && pass.id === cap) {
            if (!window.__nmCapture.inputs || window.__nmCapture.inputs.__locked !== true) {
            window.__nmCapture.inputs = {}
            for (const [k, tid] of Object.entries(pass.inputs || {})) {
              const gi = typeof tid === 'string' ? be.parseGlobalName(tid) : null
              let info = be.textures.get(tid)
              let resolved = info ? 'textures:' + tid : null
              if (!info && gi) {
                const si = state.surfaces && state.surfaces[gi]
                if (si) { info = si; resolved = 'surfaces:' + gi } else resolved = 'DEFAULT_TEXTURE'
              } else if (!info) resolved = 'DEFAULT_TEXTURE'
              window.__nmCapture.inputs[k] = { tid, resolved, w: info?.width, h: info?.height, type: info?.glFormat?.type, handle: info?.handle }
            }
            if (!window.__nmCapture.readOnce) {
              window.__nmCapture.readOnce = true
              const gl = be.gl
              const canFloat = !!(gl.getExtension('EXT_color_buffer_float') || gl.getExtension('WEBGL_color_buffer_float'))
              for (const [k, rec] of Object.entries(window.__nmCapture.inputs)) {
                try {
                  const handle = rec.handle
                  const width = rec.w, height = rec.h
                  if (!handle) continue
                  const isFloat = rec.type === gl.HALF_FLOAT || rec.type === gl.FLOAT
                  const fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo)
                  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, handle, 0)
                  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo); rec.read = 'fbo' ; continue }
                  gl.finish()
                  let buf
                  if (isFloat && canFloat) { buf = new Float32Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.FLOAT,buf) }
                  else { const b = new Uint8Array(width*height*4); gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,b); const f = new Float32Array(b.length); for (let i=0;i<b.length;i++) f[i]=b[i]/255; buf = f }
                  gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo)
                  const out = new Float32Array(width*height*4)
                  for (let y = 0; y < height; y++) out.set(buf.subarray((height-1-y)*width*4, (height-y)*width*4), y*width*4)
                  const u = new Uint8Array(out.buffer, out.byteOffset, out.byteLength); let s = ''
                  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, Math.min(i + 0x8000, u.length)))
                  rec.b64 = btoa(s)
                  rec.flip = true
                } catch (e) { rec.read = 'err:' + (e?.message || e) }
              }
              window.__nmCapture.inputs.__locked = true
            }
            }
          }
          return origTex(pass, program, state)
        }
      }
      return true
    })()`)
    const FDT = process.env.NM_FRAME_DUMP_TEX // per-frame texture dumps
    if (FDT) {
      // Render frame by frame so each frame's texture state can be read back.
      for (let i = 0; i < FRAMES; i++) {
        await cdp.evaluate(`(() => { const p = window.__noisemakerRenderingPipeline; const tt = (${TIME} + ${i} * ${TIMESTEP}) % 1; if (p && p.render) p.render(tt); return true })()`)
        const ids = await cdp.evaluate(`(() => {
          const want = new Set(${JSON.stringify(FDT.split(','))})
          return Array.from(window.__noisemakerRenderingPipeline.backend.textures.keys()).filter(id => want.has(id))
        })()`)
        for (const id of ids) {
          const r = await cdp.evaluate(`(() => {
            const RB = (${READBACK_FN})()
            const p = window.__noisemakerRenderingPipeline
            const info = p.backend.textures.get(${JSON.stringify(id)})
            if (!info) return { error: 'missing' }
            const rt = RB.readTex(p.backend.gl, info)
            if (!rt) return { error: 'fbo' }
            return { width: rt.width, height: rt.height, b64: RB.b64(rt.data) }
          })()`)
          if (r.error) { console.error(`[dump] f${i} ${id}: ${r.error}`); continue }
          const buf = Buffer.from(r.b64, 'base64')
          fs.writeFileSync(path.join(OUT, `${it.name}.f${i}.${id}.f32`), buf)
        }
        console.error(`[dump] ${it.name} frame ${i} dumped ${ids.length}`)
      }
    } else {
      await cdp.evaluate(`(() => {
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
      window.__nmFrameInfo = { frameIndex: p.frameIndex, lastFramePasses: p.lastPassCount ?? null, passCount: p.passCount ?? null, graphId: p.graph?.id, isCompiling: p.isCompiling }
      return true
    })()`)
    }
    // Enumerate candidate texture ids, then dump each requested one.
    const texIds = await cdp.evaluate(`(() => {
      const p = window.__noisemakerRenderingPipeline
      return Array.from(p.backend.textures.keys()).filter(id => /^node_\\d+_/.test(id) || /_read$/.test(id) || /_write$/.test(id))
    })()`)
    const wanted = []
    for (const spec of TEXSPEC.split(',')) {
      if (spec === 'node:*') {
        for (const id of texIds) if (/^node_\d+_/.test(id)) wanted.push(id)
        if (!wanted.length) console.error(`[dump] ${it.name} texIds=${JSON.stringify(texIds)}`)
      } else if (spec.startsWith('surface:')) {
        const s = spec.slice(8)
        const rid = texIds.find(x => x === `global_${s}_read` || x === s)
        if (rid) wanted.push(rid); else console.error(`[dump] ${it.name} no surface ${s} (texIds=${JSON.stringify(texIds)})`)
      } else if (spec === 'final') { /* final handled separately */ } else if (texIds.includes(spec)) wanted.push(spec)
      else console.error(`[dump] ${it.name} no texture ${spec}`)
    }
    const manifest = {}
    for (const id of [...new Set(wanted)]) {
      console.error(`[dump] ${it.name} reading ${id}`)
      if (process.env.NM_DUMP_STAGES) {
        const stages = await cdp.evaluate(`(rb => {
          const RB = (${READBACK_FN})()
          const p = window.__noisemakerRenderingPipeline
          const info = p.backend.textures.get(${JSON.stringify(id)})
          if (!info) return { error: 'missing' }
          const t0 = Date.now()
          const { handle, width, height } = info
          const gl = p.backend.gl
          const fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo)
          gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, handle, 0)
          const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER)
          gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo)
          return { stage: 'info', width, height, status, ms: Date.now() - t0, type: info.glFormat?.type }
        })(0)`)
        console.error(`[dump] stages ${JSON.stringify(stages)}`)
        const t0 = Date.now()
        const probe = await cdp.evaluate(`(rb => {
          const RB = (${READBACK_FN})()
          const p = window.__noisemakerRenderingPipeline
          const info = p.backend.textures.get(${JSON.stringify(id)})
          const gl = p.backend.gl
          const { handle, width, height } = info
          const fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo)
          gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, handle, 0)
          const canFloat = !!(gl.getExtension('EXT_color_buffer_float') || gl.getExtension('WEBGL_color_buffer_float'))
          const isFloat = info.glFormat?.type === gl.HALF_FLOAT || info.glFormat?.type === gl.FLOAT
          const buf = isFloat && canFloat ? new Float32Array(width*height*4) : new Uint8Array(width*height*4)
          const fmt = isFloat && canFloat ? gl.FLOAT : gl.UNSIGNED_BYTE
          const t1 = Date.now()
          gl.readPixels(0, 0, width, height, gl.RGBA, fmt, buf)
          gl.finish()
          const t2 = Date.now()
          gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fbo)
          return { readMs: t2 - t1, sample: Array.from(buf.slice(0, 8)) }
        })(0)`)
        console.error(`[dump] read ${JSON.stringify(probe)}`)
        continue
      }
      const r0 = await cdp.evaluate(`(() => {
        const RB = (${READBACK_FN})()
        const p = window.__noisemakerRenderingPipeline
        const info = p.backend.textures.get(${JSON.stringify(id)})
        if (!info) return { error: 'missing ' + ${JSON.stringify(id)} }
        return { width: info.width, height: info.height }
      })()`)
      if (r0.error) { console.error(`[dump] ${it.name} ${id}: ${r0.error}`); continue }
      // Transfer in row chunks: a single multi-MB returnByValue payload can
      // stall the CDP evaluate round-trip.
      const { width: tw, height: th } = r0
      const parts = []
      const ROWS = 512
      for (let y0 = 0; y0 < th; y0 += ROWS) {
        const y1 = Math.min(y0 + ROWS, th)
        const r = await cdp.evaluate(`(() => {
          const RB = (${READBACK_FN})()
          const p = window.__noisemakerRenderingPipeline
          const info = p.backend.textures.get(${JSON.stringify(id)})
          const rt = RB.readTex(p.backend.gl, info)
          const b = new Float32Array(rt.data.buffer, ${y0} * rt.width * 16, (${y1} - ${y0}) * rt.width * 4)
          return RB.b64(b)
        })()`)
        parts.push(Buffer.from(r, 'base64'))
      }
      const buf = Buffer.concat(parts)
      fs.writeFileSync(path.join(OUT, `${it.name}.${id}.f32`), buf)
      manifest[id] = { width: tw, height: th, bytes: buf.length, sha256: crypto.createHash('sha256').update(buf).digest('hex') }
    }
    if (TEXSPEC.split(',').includes('final')) {
      const out = await cdp.evaluate(`(() => {
        const pipeline = window.__noisemakerRenderingPipeline
        const gl = pipeline?.backend?.gl
        const surface = pipeline?.surfaces?.get(pipeline?.graph?.renderSurface || 'o0')
        if (!gl || !surface) return { error: 'no GL surface' }
        const info = pipeline.backend.textures?.get(surface.read)
        if (!info?.handle) return { error: 'no texture handle' }
        const rt = (${READBACK_FN})().readTex(gl, info)
        if (!rt) return { error: 'FBO incomplete' }
        const u8 = new Uint8Array(rt.data.length)
        for (let i = 0; i < rt.data.length; i++) u8[i] = Math.max(0, Math.min(255, Math.round(rt.data[i] * 255)))
        return { width: rt.width, height: rt.height, b64: (${READBACK_FN})().b64(u8), graphId: pipeline.graph.id }
      })()`)
      if (!out.error) {
        const rgba = Buffer.from(out.b64, 'base64')
        fs.writeFileSync(path.join(OUT, `${it.name}.final.png`), encodePng(out.width, out.height, rgba))
        manifest['final'] = { width: out.width, height: out.height, graphId: out.graphId }
      } else console.error(`[dump] ${it.name} final: ${out.error}`)
    }
    fs.writeFileSync(path.join(OUT, `${it.name}.dump.json`), JSON.stringify(manifest, null, 2) + '\n')
    if (process.env.NM_CAPTURE_PASS) {
      const cap = await cdp.evaluate(`window.__nmCapture?.log ?? []`)
      fs.writeFileSync(path.join(OUT, `${it.name}.uniforms.json`), JSON.stringify(cap, null, 2) + '\n')
      const capIn = await cdp.evaluate(`window.__nmCapture?.inputs ?? null`)
      if (capIn) {
        for (const k of Object.keys(capIn)) {
          const b64 = capIn[k]?.b64
          if (b64) {
            fs.writeFileSync(path.join(OUT, `${it.name}.bindtex.${k}.f32`), Buffer.from(b64, 'base64'))
            delete capIn[k].b64
          }
        }
      }
      fs.writeFileSync(path.join(OUT, `${it.name}.inputs.json`), JSON.stringify(capIn, null, 2) + '\n')
      const fr = await cdp.evaluate(`window.__nmFrameInfo ?? null`)
      fs.writeFileSync(path.join(OUT, `${it.name}.frameinfo.json`), JSON.stringify(fr, null, 2) + '\n')
    }
    console.log('OK', it.name, Object.keys(manifest).length, 'textures')
  }
  console.log('DONE')
  process.exit(0)
}

main().catch(e => { console.error('FATAL', e.message || e); process.exit(1) })
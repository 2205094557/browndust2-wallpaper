// 导出壁纸运行时探针（槽级 node 模拟）：在 stub 的 DOM/WebGL 环境里按页面
// 顺序执行导出项目的全部脚本，跑若干渲染帧，抓启动/渲染期 JS 异常并打印
// 关键状态（骨架数/取景框/相机）。用法：node tools/_wp_runtime_probe.js <项目目录>
'use strict'
const fs = require('fs')
const path = require('path')

const dir = process.argv[2]
if (!dir) { console.error('usage: node _wp_runtime_probe.js <project_dir>'); process.exit(2) }
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8')

// ---- WebGL stub：常量给 1，查询给成功，其余 no-op ----
function makeGL() {
  const overrides = {
    getParameter: () => 4096,
    getShaderParameter: () => true,
    getProgramParameter: () => true,
    getShaderInfoLog: () => '',
    getProgramInfoLog: () => '',
    getExtension: () => null,
    getUniformLocation: () => ({}),
    getAttribLocation: () => 0,
    getSupportedExtensions: () => [],
  }
  return new Proxy({}, {
    get(_t, k) {
      if (k in overrides) return overrides[k]
      if (typeof k === 'string' && /^[A-Z][A-Z0-9_]*$/.test(k)) return 1
      // 默认 no-op 返回真值句柄（createShader/createTexture/createBuffer 等判空使用）
      return function () { return 1 }
    },
    set() { return true },
  })
}
const glStub = makeGL()

function makeCanvas() {
  return {
    width: 1600, height: 900, clientWidth: 1600, clientHeight: 900,
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    getContext: () => glStub,
    addEventListener() {}, removeEventListener() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1600, height: 900 }),
    toDataURL: () => 'data:image/png;base64,',
  }
}

// ---- 全局 stub ----
const errors = []
const consoleProxy = {
  error: (...a) => { errors.push(a.map(String).join(' ')) },
  warn: (...a) => { errors.push('[warn] ' + a.map(String).join(' ')) },
  log: () => {},
}
const listeners = {}
const rafQueue = []
class FakeImage {
  constructor() { this.width = 0; this.height = 0; this.onload = null; this.onerror = null }
  set src(v) {
    // 纹理/背景图“加载成功”：2048²（模板只读 width/height 与当绘制源传给 no-op GL）
    this.width = 2048; this.height = 2048
    if (this.onload) this.onload()
  }
}
class FakeAudio {
  constructor() { this.volume = 1 }
  play() { return Promise.resolve() }
  pause() {}
  addEventListener() {}
}

const g = globalThis
const realConsole = console // 探针自身输出用（页面脚本看到的是 consoleProxy）
Object.assign(g, {
  console: consoleProxy,
  window: g,
  document: {
    title: '',
    getElementById: (id) => (id === 'canvas' ? canvasStub : { style: {}, textContent: '' }),
    createElement: () => makeCanvas(),
    addEventListener() {},
    body: { appendChild() {}, style: {} },
    documentElement: { style: {} },
  },
  devicePixelRatio: 1,
  performance: { now: () => Date.now() },
  requestAnimationFrame: (cb) => { rafQueue.push(cb); return rafQueue.length },
  cancelAnimationFrame() {},
  Image: FakeImage,
  Audio: FakeAudio,
  // 让 GL Proxy 通过运行时的 instanceof 检查（走“直接用给定 context”分支）
  WebGLRenderingContext: Object.defineProperty(function () {}, Symbol.hasInstance, { value: () => true }),
  addEventListener: (ev, cb) => { (listeners[ev] = listeners[ev] || []).push(cb) },
  removeEventListener() {},
  fetch: () => Promise.reject(new Error('no network in probe')),
  setTimeout: (cb) => { cb(); return 0 },
  clearTimeout() {},
  XMLHttpRequest: function () { this.open = () => {}; this.send = () => { if (this.onerror) this.onerror() } },
})
const canvasStub = makeCanvas()
g.document.getElementById = (id) => (id === 'canvas' ? canvasStub : { style: {}, textContent: '', setAttribute() {} })

// ---- 按 HTML 顺序执行 <script src> 与内联脚本 ----
const srcs = [...html.matchAll(/<script[^>]*src="([^"]+)"[^>]*>/g)].map((m) => m[1])
const inlines = [...html.matchAll(/<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1])
realConsole.log('scripts src:', srcs.join(', '), '| inline:', inlines.length)

const vm = require('vm')
function run(code, name) {
  try {
    vm.runInThisContext(code, { filename: name })
  } catch (e) {
    console.error('BOOT THROW [' + name + ']:', e.stack || e)
  }
}
for (const s of srcs) {
  const p = path.join(dir, s)
  if (fs.existsSync(p)) run(fs.readFileSync(p, 'utf8'), s)
  else console.error('missing script file:', s)
}
for (let i = 0; i < inlines.length; i++) run(inlines[i], 'inline#' + i)

// ---- 触发 load → init ----
if (listeners.load && listeners.load.length) {
  for (const cb of listeners.load) cb()
} else {
  console.error('no load listener found (init not wired)')
}

// ---- 跑渲染帧（drain rAF 若干轮）----
for (let frame = 0; frame < 5; frame++) {
  const q = rafQueue.splice(0, rafQueue.length)
  if (!q.length) break
  for (const cb of q) {
    try { cb() } catch (e) { console.error('FRAME THROW:', e.stack || e) }
  }
}

// ---- 多预设回归：模拟 WE 属性推送（首推恢复保存的预设 + 变更推送切换）----
if (g.wallpaperPropertyListener && g.PRESETS && g.PRESETS.length > 1) {
  const cur = () => g.skeletons[0].state.getCurrent(0).animation.name
  const drain = () => {
    const q = rafQueue.splice(0, rafQueue.length)
    for (const cb of q) { try { cb() } catch (e) { console.error('FRAME THROW:', e.stack || e) } }
  }
  const p0 = g.PRESETS[0], p1 = g.PRESETS[1]
  // 首推：WE 保存过第 2 个预设 → 应恢复 p1（覆盖导出默认 p0）
  g.wallpaperPropertyListener.applyUserProperties({ voice: { value: true }, preset: { value: p1.name } })
  drain()
  const s1 = { anim: cur(), scale: g.SCALE, offX: g.OFFSET_X }
  // 变更推送：切回第 1 个
  g.wallpaperPropertyListener.applyUserProperties({ preset: { value: p0.name } })
  drain()
  const s2 = { anim: cur(), scale: g.SCALE, offX: g.OFFSET_X }
  const pass = s1.anim === p1.animation && s1.scale === p1.scale && s1.offX === p1.offsetX
    && s2.anim === p0.animation && s2.scale === p0.scale && s2.offX === p0.offsetX
  realConsole.log('PRESET-CHECK ' + (pass ? 'PASS' : 'FAIL') + ':', JSON.stringify({ afterFirstPush: s1, afterSwitchPush: s2 }))
  if (!pass) errors.push('preset switch mismatch')
}

// ---- 状态报告 ----
const st = {
  skeletons: (g.skeletons || []).length,
  CHAR_ROTATION: g.CHAR_ROTATION,
  SCALE: g.SCALE,
  boundsCache: g.boundsCache,
  charCenterCache: g.charCenterCache,
  anim: (g.skeletons && g.skeletons[0] && g.skeletons[0].state && g.skeletons[0].state.getCurrent(0) || { animation: { name: '?' } }).animation && (g.skeletons[0].state.getCurrent(0)).animation.name,
  rendererZoom: g.renderer && g.renderer.camera && g.renderer.camera.zoom,
  bgImages: (g.bgImages || []).length,
  documentTitle: g.document.title,
}
realConsole.log('STATE:', JSON.stringify(st, null, 1))
realConsole.log(errors.length ? ('ERRORS(' + errors.length + '):\n' + errors.slice(0, 20).join('\n')) : 'no JS errors')
process.exit(errors.length ? 1 : 0)

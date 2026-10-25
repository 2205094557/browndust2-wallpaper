// 「画面」模式滚轮缩放融合性数值验证（临时探针，可删）。
// 模拟 SpinePreview 实际代码路径：spineCamera 取景 + charOffset 骨架偏移 +
// 修复后的 CSS 背景锚点（autoBgStyle）+ WebGL 背景锚点（drawBg），
// 验证人物与背景在滚轮缩放后锚点重合、尺寸同比 = 融合缩放。
global.window = global
const fs = require('fs')
eval(fs.readFileSync('templates/wallpaper-layout.js', 'utf8'))
const WL = window.WallpaperLayout
const cw = 1600, ch = 900
const bounds = { minX: -800, maxX: 800, minY: -500, maxY: 500 }
const bgImg = { width: 1920, height: 1080 }

function charGeo(scale, ox, oy, charOffX, charOffY) {
  const a = WL.anchor('center')
  const cam = WL.spineCamera(bounds, cw, ch, { scale, offsetX: ox, offsetY: oy, alignX: a.x, alignY: a.y })
  const z = cam.zoom
  const co = WL.charOffsetWorld(charOffX, charOffY, cw, ch, z)
  const cx = (bounds.minX + bounds.maxX) / 2 + co.x
  const cy = (bounds.minY + bounds.maxY) / 2 + co.y
  return { x: (cx - cam.x) / z + cw / 2, y: ch / 2 - (cy - cam.y) / z, h: (bounds.maxY - bounds.minY) / z }
}
// 修复后的 CSS 背景锚点（autoBgStyle：px = (bgOff+整体)/100·sw；(整体-bgOff)/100·sh）
function cssBgGeo(bgScalePct, ox, oy, bgOffX, bgOffY) {
  const w = cw * (bgScalePct / 100), h = w * bgImg.height / bgImg.width
  return { x: cw / 2 + ((bgOffX + ox) / 100) * cw, y: ch / 2 + ((oy - bgOffY) / 100) * ch, w, h }
}
// WebGL 背景锚点（drawBg 世界矩形经相机投影）
function glBgGeo(bgScalePct, ox, oy, bgOffX, bgOffY, scale) {
  const a = WL.anchor('center')
  const cam = WL.spineCamera(bounds, cw, ch, { scale, offsetX: ox, offsetY: oy, alignX: a.x, alignY: a.y })
  const z = cam.zoom
  const bs = Math.max((bounds.maxX - bounds.minX) / bgImg.width, (bounds.maxY - bounds.minY) / bgImg.height) * 1.15 * (bgScalePct / 100)
  const bo = WL.charOffsetWorld(bgOffX, bgOffY, cw, ch, z)
  const cx = (bounds.minX + bounds.maxX) / 2 + bo.x
  const cy = (bounds.minY + bounds.maxY) / 2 + bo.y
  return { x: (cx - cam.x) / z + cw / 2, y: ch / 2 - (cy - cam.y) / z, w: bgImg.width * bs / z, h: bgImg.height * bs / z }
}

// 滚轮一步的完整状态迁移（镜像 onCanvasWheel stage 分支）：
// scale→next，三类偏移 ×k（四舍五入整值），CSS 路径 bgScale ×k
function wheelStep(s0, s1, st) {
  const k = s1 / s0
  const sc = (v) => Math.round(WL.clampOffset((v || 0) * k))
  return {
    scale: s1,
    ox: sc(st.ox), oy: sc(st.oy),
    chX: sc(st.chX), chY: sc(st.chY),
    bX: sc(st.bX), bY: sc(st.bY),
    bg: st.css ? Math.max(30, Math.min(300, Math.round(st.bg * k))) : st.bg,
  }
}

function scenario(name, s0, s1, ox, oy, chX, chY, bX, bY, bg0) {
  const st0 = { scale: s0, ox, oy, chX, chY, bX, bY, bg: bg0, css: true }
  const st1 = wheelStep(s0, s1, st0)
  const c0 = charGeo(st0.scale, st0.ox, st0.oy, st0.chX, st0.chY)
  const c1 = charGeo(st1.scale, st1.ox, st1.oy, st1.chX, st1.chY)
  const g0 = cssBgGeo(st0.bg, st0.ox, st0.oy, st0.bX, st0.bY)
  const g1 = cssBgGeo(st1.bg, st1.ox, st1.oy, st1.bX, st1.bY)
  const k = s1 / s0
  // 照片式融合判据：人物与背景锚点各自绕画面中心缩放 k 倍（有独立偏移时
  // 锚点本就不重合，重合判据只适用于全 0 偏移），且尺寸同比 k
  const dc0 = Math.hypot(c0.x - cw / 2, c0.y - ch / 2)
  const dc1 = Math.hypot(c1.x - cw / 2, c1.y - ch / 2)
  const dg0 = Math.hypot(g0.x - cw / 2, g0.y - ch / 2)
  const dg1 = Math.hypot(g1.x - cw / 2, g1.y - ch / 2)
  const charOk = Math.abs(dc1 - k * dc0) < 6 && Math.abs(c1.h / c0.h - k) < 0.01
  const bgOk = Math.abs(dg1 - k * dg0) < 6 && Math.abs(g1.h / g0.h - k) < 0.01
  console.log((charOk && bgOk ? 'PASS' : 'FAIL'), name,
    '| 人物锚距 ' + dc0.toFixed(0) + '→' + dc1.toFixed(0) + '(×' + (dc1 / dc0).toFixed(3) + ') h×' + (c1.h / c0.h).toFixed(3),
    '| bg锚距 ' + dg0.toFixed(0) + '→' + dg1.toFixed(0) + '(×' + (dg1 / dg0).toFixed(3) + ') h×' + (g1.h / g0.h).toFixed(3))
}

console.log('== CSS 背景路径（修复后），画面模式滚轮 100%→121% ==')
scenario('A 全默认 offset=0       ', 100, 121, 0, 0, 0, 0, 0, 0, 100)
scenario('B 整体平移 ox=20 oy=-15  ', 100, 121, 20, -15, 0, 0, 0, 0, 100)
scenario('C 平移+背景独立 bX=10    ', 100, 121, 20, -15, 0, 0, 10, 0, 100)
scenario('D 人物独立 chX=-25       ', 100, 121, 0, 0, -25, 0, 0, 0, 100)
scenario('E bgScale 已 140 起步    ', 100, 121, 0, 0, 0, 0, 0, 0, 140)
scenario('F 缩小 121%→100%         ', 121, 100, 20, -15, 0, 0, 0, 0, 121)

console.log('== 对照：WebGL 背景路径（drawBg 世界锚定 + 同样的偏移缩放），语义应与 CSS 一致 ==')
for (const [nm, ox, oy, bX] of [['A', 0, 0, 0], ['B', 20, 0, 0], ['C', 20, 0, 10], ['D', 0, 0, 0]]) {
  const st0 = { scale: 100, ox, oy, chX: nm === 'D' ? -25 : 0, chY: 0, bX, bY: 0, bg: 100 }
  const st1 = wheelStep(100, 121, st0)
  const c0 = charGeo(st0.scale, st0.ox, st0.oy, st0.chX, st0.chY)
  const c1 = charGeo(st1.scale, st1.ox, st1.oy, st1.chX, st1.chY)
  const g0 = glBgGeo(st0.bg, st0.ox, st0.oy, st0.bX, st0.bY, st0.scale)
  const g1 = glBgGeo(st1.bg, st1.ox, st1.oy, st1.bX, st1.bY, st1.scale)
  const k = 121 / 100
  const dc0 = Math.hypot(c0.x - cw / 2, c0.y - ch / 2), dc1 = Math.hypot(c1.x - cw / 2, c1.y - ch / 2)
  const dg0 = Math.hypot(g0.x - cw / 2, g0.y - ch / 2), dg1 = Math.hypot(g1.x - cw / 2, g1.y - ch / 2)
  const ok = Math.abs(dc1 - k * dc0) < 6 && Math.abs(dg1 - k * dg0) < 6
  console.log((ok ? 'PASS' : 'FAIL'), nm,
    '人物锚距 ' + dc0.toFixed(0) + '→' + dc1.toFixed(0) + '(×' + (dc1 / dc0).toFixed(3) + ')',
    '| bg锚距 ' + dg0.toFixed(0) + '→' + dg1.toFixed(0) + '(×' + (dg1 / dg0).toFixed(3) + ')')
}

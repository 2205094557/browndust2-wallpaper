// Ultimate 演出皮「动画名 → 背景组」映射覆盖扫描（临时探针）：
// 对每个 cutscene 皮肤：解析 skel 动画名 + local_skins bg_sets 组数，
// 用 WallpaperLayout.bgSetForAnim 计算每个动画映射到的组——找出
// 「多组背景但所有动画都映射到同一组（切动画背景不会换）」的皮肤。
'use strict'
const fs = require('fs')
const path = require('path')
const ROOT = path.resolve(__dirname, '..')
global.window = global
new Function(fs.readFileSync(path.join(ROOT, 'templates/wallpaper-layout.js'), 'utf8'))()
const WL = global.window.WallpaperLayout

const spineSrc = fs.readFileSync(path.join(ROOT, 'templates/spine41/spine-webgl-4.1.js'), 'utf8')
const spine = new Function(spineSrc + '\nreturn spine;')()
function att(n) {
  const a = { name: n, color: { r: 1, g: 1, b: 1, a: 1 }, path: n,
    region: { renderObject: null, width: 0, height: 0, degrees: 0, x: 0, y: 0, scaleX: 1, scaleY: 1,
      u: 0, v: 0, u2: 0, v2: 0, offsetX: 0, offsetY: 0, texture: { width: 2048, height: 2048 }, page: null, rotate: false } }
  a.updateRegion = () => {}; a.setParentMesh = () => {}; return a
}
const mockLoader = {
  newRegionAttachment: (_s, n) => att(n), newMeshAttachment: (_s, n) => att(n),
  newBoundingBoxAttachment: (_s, n) => att(n), newPathAttachment: (_s, n) => att(n),
  newPointAttachment: (_s, n) => att(n), newClippingAttachment: (_s, n) => att(n),
}

const loc = JSON.parse(fs.readFileSync(path.join(ROOT, 'resources/metadata/local_skins.json'), 'utf8'))
const ult = loc.filter((l) => String(l.painting || '').startsWith('cutscene'))

// 旧版映射（修复前），用于回归对比
function bgSetForAnimOld(name, maxSet) {
  if (!name) return 1
  let m = /(?:^|_)(\d+)$/.exec(name)
  if (m) return Math.min(parseInt(m[1], 10), Math.max(1, maxSet))
  m = /_([A-Z])(?:_|$)/.exec(name)
  if (m) return Math.min(m[1].charCodeAt(0) - 64, Math.max(1, maxSet))
  return 1
}

const multi = []
const dead = []
const regress = [] // 旧版能换、新版反而不换（回归 = 禁止）
let missingSkel = 0
for (const l of ult) {
  const sets = l.asset.bg_sets || {}
  const keys = Object.keys(sets)
  if (keys.length < 2) continue
  const dir = path.join(ROOT, 'resources', l.asset.dir)
  const skelPath = path.join(dir, l.painting + '.skel')
  if (!fs.existsSync(skelPath)) { missingSkel++; continue }
  let names = []
  try {
    const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1
    const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(skelPath)))
    names = data.animations.map((a) => a.name)
  } catch (e) { console.error('skel 解析失败', l.bundle, e.message); continue }
  const maxSet = keys.reduce((m, k) => Math.max(m, parseInt(k, 10) || 0), 0)
  const oldSets = new Set(names.map((n) => bgSetForAnimOld(n, maxSet)))
  const newMap = names.map((n) => WL.bgSetForAnim(n, maxSet))
  const newSets = new Set(newMap)
  multi.push(l.bundle)
  if (newSets.size < 2) dead.push({ bundle: l.bundle, maxSet, anims: names })
  // 回归：旧版不同动画映射到 ≥2 组、新版反而坍缩成 1 组
  if (oldSets.size >= 2 && newSets.size < oldSets.size) regress.push(l.bundle)
  // 逐动画回归：旧版映射到的组，新版丢失（换背景的动画对变少）
  for (let i = 0; i < names.length; i++) {
    if (bgSetForAnimOld(names[i], maxSet) !== WL.bgSetForAnim(names[i], maxSet)) {
      // 允许 dead 皮肤的改善；只报告原本正常皮肤的映射变化
      if (oldSets.size >= 2) regress.push(l.bundle + ':' + names[i] + ' ' + bgSetForAnimOld(names[i], maxSet) + '→' + newMap[i])
    }
  }
}
console.log(`多组背景皮肤: ${multi.length}（skel 缺失 ${missingSkel}）`)
console.log(`\n== 切动画背景不会换（新版仍全映射同一组）: ${dead.length} 个 ==`)
for (const d of dead) console.log(`  ${d.bundle}  组数=${d.maxSet}  动画=[${d.anims.join(',')}]`)
console.log(`\n== 回归（正常皮肤映射被改变）: ${regress.length} 条 ==`)
for (const r of [...new Set(regress)].slice(0, 10)) console.log('  ' + r)

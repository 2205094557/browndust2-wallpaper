// 人物旋转数学验证（临时探针，可删）：
// 1) charRotationMatrixValues 的世界语义：正角=屏幕顺时针、绕支点旋转
// 2) rotateBoundsAabb 与矩阵一致（四角变换落在 AABB 内）且 90° 交换宽高
// 3) 命中取逆（unrotateWorldPoint 公式）与矩阵互逆
global.window = global
const fs = require('fs')
eval(fs.readFileSync('templates/wallpaper-layout.js', 'utf8'))
const WL = window.WallpaperLayout

let fails = 0
function ok(name, cond, detail) {
  if (!cond) fails++
  console.log((cond ? 'PASS' : 'FAIL'), name, detail || '')
}
// 列主序 4x4 × (x,y)：取 col0/col1/col3
function applyM(m, x, y) {
  return { x: m[0] * x + m[4] * y + m[12], y: m[1] * x + m[5] * y + m[13] }
}
const near = (a, b, eps) => Math.abs(a - b) < (eps || 1e-6)

// 1) 90°（顺时针）绕原点：右侧点 (1,0) → (0,-1)（世界 y 向上，右→下=顺时针 ✓）
let m = WL.charRotationMatrixValues(90, 0, 0)
let p = applyM(m, 1, 0)
ok('M90 右侧点转到底部(顺时针)', near(p.x, 0) && near(p.y, -1), `(${p.x.toFixed(3)},${p.y.toFixed(3)})`)
// -90° 逆时针：右侧点 → 上方
m = WL.charRotationMatrixValues(-90, 0, 0)
p = applyM(m, 1, 0)
ok('M-90 右侧点转到顶部(逆时针)', near(p.x, 0) && near(p.y, 1), `(${p.x.toFixed(3)},${p.y.toFixed(3)})`)
// 绕支点 (10,20)：支点本身不动
m = WL.charRotationMatrixValues(37, 10, 20)
p = applyM(m, 10, 20)
ok('M 支点不动', near(p.x, 10) && near(p.y, 20), `(${p.x.toFixed(3)},${p.y.toFixed(3)})`)
// 0° 恒等
m = WL.charRotationMatrixValues(0, 5, 5)
p = applyM(m, 3, 7)
ok('M0 恒等', near(p.x, 3) && near(p.y, 7))

// 2) AABB 一致性：矩形四角经矩阵变换后都落在 rotateBoundsAabb 结果内，且边界触达
const b = { minX: 0, maxX: 100, minY: 0, maxY: 200 }
const piv = { x: 50, y: 100 }
for (const deg of [30, 90, -45, 180]) {
  const mm = WL.charRotationMatrixValues(deg, piv.x, piv.y)
  const aabb = WL.rotateBoundsAabb(b, deg, piv.x, piv.y)
  let inside = true, touched = { min: false, max: false }
  for (const cx of [b.minX, b.maxX]) for (const cy of [b.minY, b.maxY]) {
    const q = applyM(mm, cx, cy)
    if (q.x < aabb.minX - 1e-6 || q.x > aabb.maxX + 1e-6 || q.y < aabb.minY - 1e-6 || q.y > aabb.maxY + 1e-6) inside = false
  }
  ok(`AABB(${deg}°) 包住四角`, inside)
  // 90° 交换宽高：100x200 → 200x100
  if (deg === 90 || deg === -90 || deg === 180) {
    const w = aabb.maxX - aabb.minX, h = aabb.maxY - aabb.minY
    const swap = Math.abs(w - (deg === 180 ? 100 : 200)) < 1e-6 && Math.abs(h - (deg === 180 ? 200 : 100)) < 1e-6
    ok(`AABB(${deg}°) 宽高对调`, swap, `${w.toFixed(1)}x${h.toFixed(1)}`)
  }
}

// 3) 取逆互逆：unrotate(M(p)) = p（预览/模板 unrotateWorldPoint 公式：+θ 绕支点）
function unrotate(deg, piv, x, y) {
  const t = (deg * Math.PI) / 180
  const c = Math.cos(t), s = Math.sin(t)
  const dx = x - piv.x, dy = y - piv.y
  return { x: piv.x + dx * c - dy * s, y: piv.y + dx * s + dy * c }
}
for (const deg of [30, -120, 179]) {
  const mm = WL.charRotationMatrixValues(deg, piv.x, piv.y)
  const q = applyM(mm, 80, 30) // 渲染后的屏幕对应世界点
  const back = unrotate(deg, piv, q.x, q.y)
  ok(`取逆(${deg}°)还原`, near(back.x, 80, 1e-4) && near(back.y, 30, 1e-4), `(${back.x.toFixed(4)},${back.y.toFixed(4)})`)
}

process.exit(fails ? 1 : 0)

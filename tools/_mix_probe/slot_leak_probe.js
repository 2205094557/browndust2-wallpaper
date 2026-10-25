// 槽位泄漏探测：第二代 mix 皮肤里，每个"章"（idle{K} 阶段）的所有动画
// （idleK + mixK_* + motionK_*）都【从不改写】、但 setup 底稿非空的槽——
// 这些槽无论播哪段都会一直显示 setup 底稿组件；换章后"从不改写的集合"变化，
// 错误组件就会消失/换成另一个（用户描述: 同阶段每次都是同一个，进 idle2 后变）。
// 用法: node tools/_mix_probe/slot_leak_probe.js [皮肤目录名 默认全扫]
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const spineSrc = fs.readFileSync(path.join(ROOT, 'templates/spine41/spine-webgl-4.1.js'), 'utf8');
const spine = new Function(spineSrc + '\nreturn spine;')();
function att(n) {
  const a = { name: n, color: { r: 1, g: 1, b: 1, a: 1 }, path: n,
    region: { renderObject: null, width: 0, height: 0, degrees: 0, x: 0, y: 0, scaleX: 1, scaleY: 1,
      u: 0, v: 0, u2: 0, v2: 0, offsetX: 0, offsetY: 0, texture: { width: 2048, height: 2048 }, page: null, rotate: false } };
  a.updateRegion = () => {};
  a.setParentMesh = () => {};
  return a;
}
const mockLoader = {
  newRegionAttachment: (_s, n) => att(n), newMeshAttachment: (_s, n) => att(n),
  newBoundingBoxAttachment: (_s, n) => att(n), newPathAttachment: (_s, n) => att(n),
  newPointAttachment: (_s, n) => att(n), newClippingAttachment: (_s, n) => att(n),
};
const spineDir = path.join(ROOT, 'resources/extracted/spine');
const targets = process.argv[2] ? [process.argv[2]] :
  fs.readdirSync(spineDir).filter((d) => /^illust_dating/.test(d));
for (const d of targets) {
  const dir = path.join(spineDir, d);
  if (!fs.existsSync(dir)) { console.log('[缺失]', d); continue; }
  const skelFile = fs.readdirSync(dir).find((f) => f.endsWith('.skel') && !f.includes('.skel.skel'));
  if (!skelFile) continue;
  let data;
  try {
    const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
    data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, skelFile))));
  } catch (e) { console.log('[解析失败]', d, e.message); continue; }
  // 每个动画覆盖了哪些槽（有 AttachmentTimeline 即视为会改写该槽）
  const animCovers = {};
  for (const a of data.animations) {
    const s = new Set();
    for (const t of a.timelines) {
      if (t.constructor.name.includes('Attachment')) s.add(t.slotIndex);
    }
    animCovers[a.name] = s;
  }
  // 每章动画组 = idle{K} + mix{K}_* + motion{K}_*
  const chAnims = {};
  for (const a of data.animations) {
    let m = /^idle(\d+)$/.exec(a.name);
    if (m) { (chAnims[m[1]] = chAnims[m[1]] || []).push(a.name); continue; }
    m = /^mix(\d+)_/.exec(a.name);
    if (m) { (chAnims[m[1]] = chAnims[m[1]] || []).push(a.name); continue; }
    m = /^motion(\d+)/.exec(a.name);
    if (m) { (chAnims[m[1]] = chAnims[m[1]] || []).push(a.name); continue; }
  }
  // setup 底稿非空槽
  const sk = new spine.Skeleton(data);
  const setupNames = {};
  for (let i = 0; i < sk.slots.length; i++) {
    const s = sk.slots[i];
    const an = s.attachment ? s.attachment.name : null;
    if (an) setupNames[data.slots[i].name] = an;
  }
  console.log('\n===== ' + d + ' =====');
  const chapNums = Object.keys(chAnims).map(Number).sort((a, b) => a - b);
  for (const ch of chapNums) {
    const anims = chAnims[ch];
    if (!anims.includes('idle' + ch)) continue; // 该编号不成章
    const covered = new Set();
    for (const n of anims) for (const i of animCovers[n] || []) covered.add(i);
    const leaks = [];
    for (let i = 0; i < data.slots.length; i++) {
      if (covered.has(i)) continue;
      const an = sk.slots[i].attachment ? sk.slots[i].attachment.name : null;
      if (an) leaks.push(data.slots[i].name + '=' + an);
    }
    // 这些泄漏槽是否被【别章】的动画覆盖（能解释"来自很远的动画"的观感）
    let elsewhere = 0;
    for (const o of chapNums) {
      if (o === ch) continue;
      for (const n of chAnims[o]) {
        for (const i of animCovers[n] || []) {
          if (!covered.has(i) && sk.slots[i].attachment && sk.slots[i].attachment.name) { elsewhere++; }
        }
      }
    }
    console.log('  章' + ch + ': 动画 ' + anims.length + ' 个, 从不改写的槽 ' + leaks.length + ' 个' +
      (leaks.length ? ' (其中 ' + elsewhere + ' 个槽被别章动画改写)' : ''));
    if (leaks.length && leaks.length <= 12) console.log('    例: ' + leaks.slice(0, 8).join(', '));
  }
}

// 打断残留严格测试：idle1 稳态 → 播片段A到30%打断 → 片段B自然播完 → 回idle1，
// 在 B 播放期间多点采样，对比"从干净 idle1 直接播 B"的同刻状态——
// 任何差异 = 打断 A 留下的视觉残留（用户看到的"身上冒出别的东西"）
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
function snap(sk) { const m = {}; for (const s of sk.slots) m[s.data.name] = (s.attachment ? s.attachment.name : null); return m; }
function diff(a, b) { let d = 0; for (const k in a) if (a[k] !== b[k]) d++; return d; }
function diffSlots(a, b) { const d = []; for (const k in a) if (a[k] !== b[k]) d.push(k.replace(/^B_/, '') + '=' + (b[k] || 'null')); return d; }
const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
const rel = process.argv[2] || 'resources/extracted/spine/illust_dating11/illust_dating11.skel';
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
const sd = new spine.AnimationStateData(data);
const mk = () => { const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data); sk.setToSetupPose(); return { st, sk }; };
function anim(n) { return data.animations.find(x => x.name === n); }
function runFrom(idle, frames) { const c = mk(); c.st.setAnimation(0, idle, true); for (let i = 0; i < frames; i++) { c.st.update(1 / 60); c.st.apply(c.sk); } return c; }
const pairs = [
  ['mix1_2_1', 'mix1_3_1'],
  ['mix1_4_1', 'mix1_5_1'],
  ['mix3_2_1', 'mix3_3_1'],
  ['mix3_10_1', 'mix3_11_1'],
  ['mix4_2_1', 'mix4_3_1'],
];
let anyGhost = false;
for (const [A, B] of pairs) {
  // 干净参照：idle1 稳态 → 直接播 B（自然播完）
  const clean = runFrom('idle1', 300);
  const eB = clean.st.setAnimation(0, B, false); eB.mixDuration = 0.16;
  const durB = anim(B).duration;
  const cleanSamples = [];
  for (let t = 0.1; t <= durB; t += Math.max(0.1, durB / 8)) {
    while (clean.st.getCurrent(0).trackTime < t && clean.st.getCurrent(0).trackTime < durB) { clean.st.update(1 / 60); clean.st.apply(clean.sk); }
    cleanSamples.push({ t: +clean.st.getCurrent(0).trackTime.toFixed(2), s: snap(clean.sk) });
  }
  clean.st.update(durB); clean.st.apply(clean.sk);
  const cleanEnd = snap(clean.sk);
  // 打断路径：idle1 稳态 → A 播 30% 打断 → B
  const dirty = runFrom('idle1', 300);
  const eA = dirty.st.setAnimation(0, A, false); eA.mixDuration = 0.16;
  for (let i = 0; i < Math.ceil(anim(A).duration * 0.3 * 60); i++) { dirty.st.update(1 / 60); dirty.st.apply(dirty.sk); }
  const eB2 = dirty.st.setAnimation(0, B, false); eB2.mixDuration = 0.16;
  let maxGhost = 0, ghostAt = '', ghostEx = '';
  for (const cs of cleanSamples) {
    while (dirty.st.getCurrent(0).trackTime < cs.t && dirty.st.getCurrent(0).trackTime < durB) { dirty.st.update(1 / 60); dirty.st.apply(dirty.sk); }
    const s = snap(dirty.sk);
    const d = diff(cs.s, s);
    if (d > maxGhost) { maxGhost = d; ghostAt = cs.t; ghostEx = diffSlots(cs.s, s).slice(0, 5).join(' | '); }
  }
  while (dirty.st.getCurrent(0).trackTime < durB) { dirty.st.update(1 / 60); dirty.st.apply(dirty.sk); }
  const dirtyEnd = snap(dirty.sk);
  const endD = diff(cleanEnd, dirtyEnd);
  const flag = (maxGhost > 8 || endD > 8) ? '⚠' : '✓';
  if (flag === '⚠') anyGhost = true;
  console.log(flag + ' ' + A + '(打断@30%)→' + B.padEnd(12) + ' 播放中最大残留=' + String(maxGhost).padStart(3) + '@' + ghostAt + 's  播完终态差=' + endD + (maxGhost > 8 ? '  例: ' + ghostEx : ''));
}
console.log(anyGhost ? '\n结论: 打断会留下可见残留 → 需要清理机制' : '\n结论: 打断无残留，动画逻辑干净');

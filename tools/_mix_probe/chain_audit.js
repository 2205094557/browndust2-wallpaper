// 链式连续性审计：每章从 live idleK 出发，按官方顺序连续播放所有片段，
// 记录每一段结束态与各 idle 的距离——找出"结束态 ≠ idleK"的闪跳点
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const spineSrc = fs.readFileSync(path.join(ROOT, 'templates/spine41/spine-webgl-4.1.js'), 'utf8');
const spine = new Function(spineSrc + '\nreturn spine;')();
global.window = global;
new Function(fs.readFileSync(path.join(ROOT, 'templates/shared/bd2-interact.js'), 'utf8'))();
const BD2Interact = global.window.BD2Interact;
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
function snapshot(sk) { const m = {}; for (const s of sk.slots) m[s.data.name] = (s.attachment ? s.attachment.name : null); return m; }
function diff(a, b) { let d = 0; for (const k in a) if (a[k] !== b[k]) d++; return d; }
function closest(m, idleSnaps) {
  return Object.keys(idleSnaps).map(n => ({ n, d: diff(m, idleSnaps[n]) }))
    .sort((a, b) => a.d - b.d || a.n.localeCompare(b.n));
}
function audit(rel) {
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
  const sd = new spine.AnimationStateData(data);
  const profile = BD2Interact.detect(data.animations.map(a => a.name));
  if (profile.style !== 'mix') return;
  const idleSnaps = {};
  for (const idle of profile.idles) {
    const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data);
    sk.setToSetupPose();
    st.setAnimation(0, idle, true);
    for (let i = 0; i < 240; i++) { st.update(1 / 60); st.apply(sk); }
    idleSnaps[idle] = snapshot(sk);
  }
  console.log('=== ' + path.basename(rel));
  for (const poolKey of Object.keys(profile.mixPools)) {
    const chap = parseInt(poolKey.replace('mix', ''), 10);
    const idleName = 'idle' + chap;
    if (!idleSnaps[idleName]) continue;
    // 该章所有片段按官方顺序（与引擎同款排序）
    const frags = profile.mixPools[poolKey].map(n => {
      const m = /^mix\d+_(\d+)(?:_(\d+))?(?:_(long|loop|end)(\d*))?$/.exec(n);
      return { n, step: +m[1], variant: m[2] ? +m[2] : 0, mod: m[3] ? { long: 1, loop: 2, end: 3 }[m[3]] : 0, modN: m[4] ? +m[4] : 0 };
    }).sort((a, b) => (a.step - b.step) || ((a.variant > 0 ? 0 : 1) - (b.variant > 0 ? 0 : 1))
      || ((a.variant > 0 ? a.variant : a.modN) - (b.variant > 0 ? b.variant : b.modN)) || (a.mod - b.mod));
    // 从 live idleK 连续播放
    const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data);
    sk.setToSetupPose();
    st.setAnimation(0, idleName, true);
    for (let i = 0; i < 240; i++) { st.update(1 / 60); st.apply(sk); }
    for (const f of frags) {
      if (!data.animations.some(a => a.name === f.n)) continue;
      const a = data.animations.find(x => x.name === f.n);
      const e = st.setAnimation(0, f.n, false); e.mixDuration = 0;
      st.update(a.duration + 0.02); st.apply(sk);
      const end = snapshot(sk);
      const c = closest(end, idleSnaps);
      const bestIdle = 'idle' + chap;
      const best = c.find(x => x.n === bestIdle);
      const flag = (best && best.d <= c[0].d + 3) ? '' : ' ⚠落点=' + c[0].n + '(差' + c[0].d + ',本章差' + (best ? best.d : '?') + ')';
      if (flag) console.log('  ' + f.n.padEnd(16) + flag);
    }
  }
}
for (const d of fs.readdirSync(path.join(ROOT, 'resources/extracted/spine')).filter(d => /^illust_dating/.test(d)).sort()) {
  const f = fs.readdirSync(path.join(ROOT, 'resources/extracted/spine', d)).find(x => x.endsWith('.skel') && !x.includes('.skel.skel'));
  if (f) {
    try { audit('resources/extracted/spine/' + d + '/' + f); } catch (e) { console.log('=== ' + d + ' 解析失败: ' + e.message); }
  }
}

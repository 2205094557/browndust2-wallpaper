// 附件残留测试：片段自然播完 → 回 idle 后，附件是否残留（相对纯 idle 基线）
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
function diffList(a, b) { const d = []; for (const k in a) if (a[k] !== b[k]) d.push(k + '=' + (b[k] || 'null')); return d; }
const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
const rel = process.argv[2] || 'resources/extracted/spine/illust_dating11/illust_dating11.skel';
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
const sd = new spine.AnimationStateData(data);
const idleName = process.argv[3] || 'idle1';
function pureIdle() {
  const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data); sk.setToSetupPose();
  st.setAnimation(0, idleName, true); for (let i = 0; i < 300; i++) { st.update(1 / 60); st.apply(sk); }
  return snap(sk);
}
const pureSnap = pureIdle();
function testAfter(frag) {
  const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data); sk.setToSetupPose();
  st.setAnimation(0, idleName, true); for (let i = 0; i < 300; i++) { st.update(1 / 60); st.apply(sk); }
  const a = data.animations.find(x => x.name === frag);
  if (!a) return;
  const e = st.setAnimation(0, frag, false); e.mixDuration = 0.16;
  st.update(a.duration + 0.02); st.apply(sk);
  const afterFrag = snap(sk);
  const e2 = st.setAnimation(0, idleName, true); e2.mixDuration = 0.16;
  for (let i = 0; i < 40; i++) { st.update(1 / 60); st.apply(sk); }
  const afterIdle = snap(sk);
  const leaked = diffList(pureSnap, afterIdle);
  const dFrag = diff(afterFrag, pureSnap), dIdle = diff(afterIdle, pureSnap);
  console.log((leaked.length ? '⚠ ' : '✓ ') + frag.padEnd(14) + ' 播完瞬间差=' + String(dFrag).padStart(4) + ' 回idle后差=' + String(dIdle).padStart(4) + (leaked.length ? ' 残留: ' + leaked.slice(0, 8).join(' | ') : ''));
}
for (const f of process.argv.slice(4)) testAfter(f);
if (process.argv.length <= 4) {
  // 缺省: 审计 flagged + 每章抽查
  const defaults = ['mix1_2_1', 'mix1_4_1', 'mix1_8_1', 'mix3_5_1', 'mix3_13_1', 'mix4_6_1', 'mix4_9_1', 'mix4_20_1'];
  for (const f of defaults) testAfter(f);
}

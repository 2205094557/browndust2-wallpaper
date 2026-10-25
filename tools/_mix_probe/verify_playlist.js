// 验证新章节编排：打印实际点击序列（anim→idle），检查与附件状态指纹的一致性
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
  return a;
}
const mockLoader = {
  newRegionAttachment: (_s, n) => att(n), newMeshAttachment: (_s, n) => att(n),
  newBoundingBoxAttachment: (_s, n) => att(n), newPathAttachment: (_s, n) => att(n),
  newPointAttachment: (_s, n) => att(n), newClippingAttachment: (_s, n) => att(n),
};
function run(rel, clicks) {
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
  const sd = new spine.AnimationStateData(data); sd.defaultMix = 0;
  const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data);
  const profile = BD2Interact.detect(data.animations.map(a => a.name));
  BD2Interact.resetMix();
  console.log('=== ' + path.basename(rel));
  console.log('idles=' + profile.idles.join(',') + ' 章节(mix)=' + Object.keys(profile.mixPools).join(',')
    + ' motions=' + profile.motions.join(','));
  const seq = [];
  let full = false, idleAfter = '';
  st.addListener({ complete: (e) => {
    if (e.trackIndex !== 0 || e.loop) return;
    const n = e.animation ? e.animation.name : '';
    if (full && /^(motion|mix)/.test(n)) { full = false; if (idleAfter) { st.setAnimation(0, idleAfter, true); seq.push('  [自动] ' + idleAfter); } }
  } });
  let t = 0, next = 0.4, missing = 0;
  while (t < 1e9 && seq.filter(s => !s.includes('[自动]')).length < clicks) {
    const r = BD2Interact.decide(profile, [], null, { x: 0, y: 0 }, {});
    if (r && r.mode !== 'overlay') {
      const ok = data.animations.some(a => a.name === r.anim);
      if (!ok) missing++;
      full = true; idleAfter = r.idle;
      if (ok) { st.setAnimation(0, r.anim, false); st.update(0); st.apply(sk); }
      seq.push(r.anim + ' → ' + r.idle + (ok ? '' : '  [动画缺失!]'));
    }
    t += 1 / 60;
    // 快进当前动画到结束以触发 complete
    const cur = st.getCurrent(0);
    if (cur && !cur.loop) {
      const remain = cur.trackEnd - cur.trackTime;
      if (remain > 0) { st.update(remain + 0.01); st.apply(sk); }
    }
  }
  seq.slice(0, clicks + 12).forEach((s, i) => console.log(String(i + 1).padStart(3) + '. ' + s));
  console.log('缺失动画数:', missing, '| 序列总长:', seq.length);
}
run('resources/extracted/spine/illust_dating11/illust_dating11.skel', 60);
run('resources/extracted/spine/illust_dating14/illust_dating14.skel', 40);

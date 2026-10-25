// 打断残留批量扫描（推广自 interrupt_ghost_test.js）：全部第二代皮肤 × 播放列表
// 相邻片段对，测「播 A 到 30% 打断 → 接 B」相对「干净直播 B」的附件差异。
// 触发路径与宿主一致：base = 片段所在章的实测家 idle（若 homeIdle 缺省按 idle{章号}）。
// 用法: node tools/_mix_probe/interrupt_sweep.js [配对上限]
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
function snap(sk) { const m = {}; for (const s of sk.slots) m[s.data.name] = (s.attachment ? s.attachment.name : null); return m; }
function diff(a, b) { let d = 0; for (const k in a) if (a[k] !== b[k]) d++; return d; }
const PAIR_LIMIT = parseInt(process.argv[2] || '220', 10);
const spineDir = path.join(ROOT, 'resources/extracted/spine');
const dirs = fs.readdirSync(spineDir).filter((d) => /^illust_(dating|special)/.test(d));
let total = 0, flagged = 0;
const worst = [];
for (const d of dirs) {
  const skelFile = fs.readdirSync(path.join(spineDir, d)).find((f) => f.endsWith('.skel') && !f.includes('.skel.skel'));
  if (!skelFile) continue;
  let data;
  try {
    const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
    data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(spineDir, d, skelFile))));
  } catch (e) { console.log('[解析失败]', d, e.message); flagged++; continue; }
  const profile = BD2Interact.detect(data.animations.map((a) => a.name));
  if (profile.style !== 'mix') continue;
  const sd = new spine.AnimationStateData(data);
  BD2Interact.computeMotionTargets(profile, () => ({
    state: new spine.AnimationState(sd),
    skeleton: new spine.Skeleton(data),
  }));
  BD2Interact.resetMix();
  const mk = () => { const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data); sk.setToSetupPose(); return { st, sk }; };
  const anim = (n) => data.animations.find((x) => x.name === n);
  const idleOfNum = {};
  for (const n of profile.idles) { const m = /^idle(\d+)$/.exec(n); if (m) idleOfNum[parseInt(m[1], 10)] = n; }
  const home = (ch) => (profile.homeIdle && profile.homeIdle[ch]) || idleOfNum[ch];
  // 构建播放列表（decide 惰性构建；走一圈拿相邻对）
  const pl = [];
  {
    let guard = data.animations.length * 6 + 60;
    while (guard-- > 0) {
      const r = BD2Interact.decide(profile, [], null, { x: 0, y: 0 }, {});
      if (!r) break;
      pl.push(r);
      if (pl.length > data.animations.length * 4) break;
    }
  }
  if (pl.length < 2) continue;
  // base idle 缓存的干净样本一次算好：B 从 base 直播时段的附件快照
  function runTo(idleName, frames) { const c = mk(); c.st.setAnimation(0, idleName, true); for (let i = 0; i < frames; i++) { c.st.update(1 / 60); c.st.apply(c.sk); } return c; }
  function chapOf(animName) { const m = /^mix(\d+)_/.exec(animName); return m ? parseInt(m[1], 10) : 0; }
  const nPairs = Math.min(PAIR_LIMIT, pl.length - 1);
  let skinGhost = 0, worstEx = '', worstAt = '', worstPair = '';
  for (let pi = 0; pi < nPairs; pi++) {
    const A = pl[pi].anim;
    const B = pl[pi + 1].anim;
    if (!anim(A) || !anim(B)) continue;
    const base = home(chapOf(A)) || profile.idles[0];
    if (!base || !anim(base)) continue;
    // 干净参照：base 稳态 → 直播 B
    const clean = runTo(base, 240);
    clean.st.setAnimation(0, B, false);
    const durB = anim(B).duration;
    const cleanSamples = [];
    for (let t = 0.1; t <= durB; t += Math.max(0.1, durB / 8)) {
      while (clean.st.getCurrent(0).trackTime < t && clean.st.getCurrent(0).trackTime < durB) { clean.st.update(1 / 60); clean.st.apply(clean.sk); }
      cleanSamples.push(snap(clean.sk));
    }
    // 打断路径：base 稳态 → 播 A → 30% 处打断 → B
    const dirty = runTo(base, 240);
    dirty.st.setAnimation(0, A, false);
    for (let i = 0; i < Math.max(4, Math.ceil(anim(A).duration * 0.3 * 60)); i++) { dirty.st.update(1 / 60); dirty.st.apply(dirty.sk); }
    dirty.st.setAnimation(0, B, false);
    let maxGhost = 0, ghostAt = '';
    for (const s of cleanSamples) {
      while (dirty.st.getCurrent(0).trackTime < clean.st.getCurrent(0).trackTime && dirty.st.getCurrent(0).trackTime < durB) { dirty.st.update(1 / 60); dirty.st.apply(dirty.sk); }
      const d = diff(s, snap(dirty.sk));
      if (d > maxGhost) { maxGhost = d; ghostAt = clean.st.getCurrent(0).trackTime.toFixed(2); }
    }
    total++;
    if (maxGhost > 8) {
      flagged++;
      if (!skinGhost) skinGhost = maxGhost;
      if (maxGhost > 8) { worst.push({ d, pair: A + '→' + B, ghost: maxGhost, at: ghostAt }); }
      worstPair = A + '→' + B; worstAt = ghostAt;
    }
  }
  if (skinGhost) console.log('⚠', d.padEnd(22), '打断残留 max=', skinGhost, '对:', worstPair, '@' + worstAt + 's');
}
console.log('\n统计: 片段对=' + total, '残留对(>8槽)=' + flagged);
const top = worst.sort((a, b) => b.ghost - a.ghost).slice(0, 10);
for (const t of top) console.log('  最差残留:', t.ghost, '槽 @', t.at + 's  ', t.pair);

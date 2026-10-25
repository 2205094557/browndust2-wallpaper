// 批量扫描：所有第二代皮肤（有 mix/motion/idle 结构）跑新编排，验证播放列表完整
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
const spineDir = path.join(ROOT, 'resources/extracted/spine');
const dirs = fs.readdirSync(spineDir).filter(d => /^illust_(dating|special)/.test(d));
let mixStyle = 0, faceStyle = 0, none = 0, problems = 0;
for (const d of dirs) {
  // 阶段骨架（多章约会皮，2026-10 dating22 起）：目录内 skel 干名全部匹配
  // {目录名}_N 时合并全部骨架动画名做统一 profile（与宿主同路径）
  const allSkels = fs.readdirSync(path.join(spineDir, d)).filter(f => f.endsWith('.skel'));
  const phaseSkels = allSkels.filter(f => new RegExp(`^${d}_\\d+\\.skel$`).test(f) && fs.existsSync(path.join(spineDir, d, f.replace(/\.skel$/, '.atlas'))));
  const isPhase = phaseSkels.length >= 2 && phaseSkels.length === allSkels.length;
  const skelFiles = isPhase ? phaseSkels : allSkels.filter(f => !f.includes('.skel.skel')).slice(0, 1);
  if (!skelFiles.length) continue;
  const datas = [];
  try {
    for (const f of skelFiles) {
      const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
      datas.push(bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(spineDir, d, f)))));
    }
  } catch (e) { console.log('[解析失败]', d, e.message); problems++; continue; }
  const names = [];
  const animPhase = {};
  for (const data of datas) {
    for (const a of data.animations) {
      if (!names.includes(a.name)) names.push(a.name);
      if (isPhase) animPhase[a.name] = String(datas.indexOf(data) + 1);
    }
  }
  const profile = BD2Interact.detect(names);
  if (profile.style === 'face') { faceStyle++; continue; }
  if (profile.style !== 'mix') { none++; continue; }
  if (isPhase) { profile.animPhase = animPhase; profile.phases = datas.map((_, i) => String(i + 1)); }
  mixStyle++;
  // 实测 motion 终态（与宿主同路径：createState 按动画所属阶段出状态）
  const stateCache = datas.map(data => new spine.AnimationStateData(data));
  BD2Interact.computeMotionTargets(profile, (anim) => {
    const idx = isPhase ? (datas.findIndex(data => data.animations.some(a => a.name === anim)) || 0) : 0;
    const i = idx < 0 ? 0 : idx;
    return { state: new spine.AnimationState(stateCache[i]), skeleton: new spine.Skeleton(datas[i]) };
  });
  BD2Interact.resetMix();
  // 构建播放列表：用 decide 逐步走完一圈（loop 停留段是合法的 hold 待机）
  BD2Interact.resetMix();
  const seen = []; const missing = []; const idleWrong = [];
  const idleSet = new Set(profile.idles);
  const holdSet = new Set();
  for (const n of names) {
    if (/^mix\d+_\d+_(loop)\d*$/.test(n) || /^mix\d+_\d+_\d+_(loop)\d*$/.test(n)) holdSet.add(n);
  }
  // 章节行走模式校验：全部 mix/motion 内容应可达；回待机必须是合法章节 idle 或 hold
  let guard = names.length * 6 + 60;
  while (guard-- > 0) {
    const r = BD2Interact.decide(profile, [], null, { x: 0, y: 0 }, {});
    if (!r) { missing.push('(decide=null)'); break; }
    seen.push(r.anim);
    if (!names.includes(r.anim)) missing.push(r.anim);
    if (r.idle && !idleSet.has(r.idle) && !holdSet.has(r.idle)) idleWrong.push(r.anim + '→' + r.idle);
    if (seen.length > names.length * 6) break;
  }
  const unused = names.filter(n => /^(mix\d+_|motion\d)/.test(n) && !seen.includes(n) && !holdSet.has(n));
  const flag = (missing.length || idleWrong.length || unused.length) ? '⚠' : '✓';
  if (flag === '⚠') problems++;
  console.log(flag, d.padEnd(22), 'style=' + profile.style, 'idles=' + profile.idles.join(','),
    '章节数=' + new Set(seen.map(a => (a.match(/^mix(\d+)_/) || [])[1] || (a.match(/^motion(\d+)_?/) || [])[1])).size,
    '步数=' + seen.length,
    (missing.length ? ' 缺失:' + missing.join(',') : ''),
    (idleWrong.length ? ' 非法idle:' + idleWrong.join(',') : ''),
    (unused.length ? ' 未编排:' + unused.join(',') : ''));
}
console.log('\n统计: mix风格=' + mixStyle, 'face风格=' + faceStyle, '未识别=' + none, '问题皮肤=' + problems);

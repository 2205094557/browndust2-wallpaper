// 点击瞬闪定位：宿主路径（每步播完→回章家 idle dwell→下一步从家 idle 开播）
// vs 官方连续链（上一步末态直接接下一步）。宿主相对链条多出来的错位槽 =
// 点击瞬间闪现的错件；随时间收敛与否 = 自愈/持续。
// 用法: node tools/_mix_probe/flash_slot_trace.js [皮肤] [最多步数]
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
function diffSlots(a, b) { const d = []; for (const k in a) if (a[k] !== b[k]) d.push(k); return d; }
const spineDir = path.join(ROOT, 'resources/extracted/spine');
const target = process.argv[2] || 'illust_dating20';
const MAXSTEP = parseInt(process.argv[3] || '60', 10);
const dir = path.join(spineDir, target);
const skelFile = fs.readdirSync(dir).find((f) => f.endsWith('.skel') && !f.includes('.skel.skel'));
const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, skelFile))));
const profile = BD2Interact.detect(data.animations.map((a) => a.name));
if (profile.style !== 'mix') { console.log(target, '非 mix'); process.exit(0); }
const sd = new spine.AnimationStateData(data);
BD2Interact.computeMotionTargets(profile, () => ({
  state: new spine.AnimationState(sd),
  skeleton: new spine.Skeleton(data),
}));
BD2Interact.resetMix();
const mk = () => { const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data); sk.setToSetupPose(); return { st, sk }; };
const animDur = (n) => { const a = data.animations.find((x) => x.name === n); return a ? a.duration : 0; };
function stepN(st, sk, frames) { for (let i = 0; i < frames; i++) { st.update(1 / 60); st.apply(sk); } sk.updateWorldTransform(); }
function playClean(st, sk, name, loop) {
  const e = st.setAnimation(0, name, loop);
  if (e) e.mixDuration = 0.16;
  stepN(st, sk, 1);
}
BD2Interact.resetMix();
const pl = [];
{ let guard = data.animations.length * 6 + 60;
  while (guard-- > 0) { const r = BD2Interact.decide(profile, [], null, { x: 0, y: 0 }, {}); if (!r) break; pl.push(r); if (pl.length > data.animations.length * 4) break; } }
console.log('===== ' + target + ' ===== 列表 ' + pl.length + ' 步, 测前 ' + Math.min(MAXSTEP, pl.length) + ' 步');
const flashTotal = {};

const host = mk();   // 宿主：步间回 item.idle
const chain = mk();  // 链条：步间不回
const idle1 = profile.idles[0];
playClean(host.st, host.sk, idle1, true); stepN(host.st, host.sk, 240);
playClean(chain.st, chain.sk, idle1, true); stepN(chain.st, chain.sk, 240);

for (let si = 0; si < Math.min(MAXSTEP, pl.length); si++) {
  const item = pl[si];
  const dur = animDur(item.anim);
  const frames = Math.max(1, Math.round(dur * 60));
  // 点击前状态差（host 在 item.idle 上，chain 在上段末态；si=0 时相同）
  const preDiff = diffSlots(snap(chain.sk), snap(host.sk));
  // 各自播放新段
  playClean(host.st, host.sk, item.anim, false);
  playClean(chain.st, chain.sk, item.anim, false);
  // 段内多时刻采样
  const samples = [];
  const probeFrames = [1, 3, 7, 15, 30];
  let lastF = 0;
  for (const f of probeFrames) {
    if (f > frames) break;
    stepN(host.st, host.sk, f - lastF); stepN(chain.st, chain.sk, f - lastF); lastF = f;
    samples.push([f, diffSlots(snap(chain.sk), snap(host.sk))]);
  }
  // 播完：host v8 语义——item.idle 非 null（hold/反应/过桥）才回待机，否则保持末帧
  stepN(host.st, host.sk, Math.max(0, frames - lastF));
  stepN(chain.st, chain.sk, Math.max(0, frames - lastF));
  if (item.idle) {
    host.st.setAnimation(0, item.idle, true);
    stepN(host.st, host.sk, 30);
  } else {
    stepN(host.st, host.sk, 2); // 空轨保持末帧
  }
  const cur = samples[samples.length - 1] ? samples[samples.length - 1][1] : [];
  if (preDiff.length > 0 && cur.length < preDiff.length && si > 0) {
    // 点击瞬间有错位、且段内自愈 —— 用户看到的“闪现”窗口
    console.log('⚡' + si + ' 进入 ' + item.anim + ' (dur ' + dur.toFixed(1) + 's)' +
      ' 点击瞬间错位=' + preDiff.length + ' → ' + samples.map(([f, d]) => (f / 60).toFixed(2) + 's:' + d.length).join(' '));
    console.log('   例: ' + preDiff.slice(0, 6).join(' | '));
    for (const n of preDiff) flashTotal[n] = (flashTotal[n] || 0) + 1;
  } else if (preDiff.length > 0 && si > 0) {
    console.log('·' + si + ' 进入 ' + item.anim + ' 错位持续 ' + preDiff.length + '→' + (cur ? cur.length : '?'));
  }
}
const top = Object.entries(flashTotal).sort((a, b) => b[1] - a[1]).slice(0, 20);
console.log('\n闪现槽 TOP（出现步数）:');
for (const [n, c] of top) console.log('  ' + n + ' x' + c);
if (!top.length) console.log('  (无)');

// 插桩复现：用真实 spine 4.1 运行时 + 单源互动引擎，模拟宿主点击逻辑，
// 记录所有 track0 动画切换与 complete/interrupt 事件，找“规定外动画”的来源。
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');

// --- 加载 spine UMD ---
const spineSrc = fs.readFileSync(path.join(ROOT, 'templates/spine41/spine-webgl-4.1.js'), 'utf8');
const spine = new Function(spineSrc + '\nreturn spine;')();

// --- 加载单源互动引擎（mock window）---
global.window = global;
const interactSrc = fs.readFileSync(path.join(ROOT, 'templates/shared/bd2-interact.js'), 'utf8');
new Function(interactSrc)();
const BD2Interact = global.window.BD2Interact;

// --- 解析 dating14 skel（mock attachment loader，纯数据层不需要 GL）---
const color0 = { r: 0, g: 0, b: 0, a: 0 };
function att(name) {
  const a = { name, color: { r: 1, g: 1, b: 1, a: 1 }, path: name,
    region: { renderObject: null, width: 0, height: 0, degrees: 0,
      x: 0, y: 0, scaleX: 1, scaleY: 1, u: 0, v: 0, u2: 0, v2: 0, offsetX: 0, offsetY: 0,
      texture: { width: 2048, height: 2048 }, page: null, rotate: false } };
  a.updateRegion = () => {};
  return a;
}
const mockLoader = {
  newRegionAttachment(_s, n) { return att(n); },
  newMeshAttachment(_s, n) { return att(n); },
  newBoundingBoxAttachment(_s, n) { return att(n); },
  newPathAttachment(_s, n) { return att(n); },
  newPointAttachment(_s, n) { return att(n); },
  newClippingAttachment(_s, n) { return att(n); },
};
const bin = new spine.SkeletonBinary(mockLoader);
const skelPath = process.argv[2] || path.join(ROOT, 'resources/extracted/spine/illust_dating14/illust_dating14.skel');
bin.scale = 1;
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(skelPath)));
console.log('animations:', data.animations.map(a => a.name).join(', '));

const stateData = new spine.AnimationStateData(data);
stateData.defaultMix = 0;
const state = new spine.AnimationState(stateData);
const skeleton = new spine.Skeleton(data);

// --- 宿主逻辑复刻（SpinePreview.vue tryBd2Interact / onInteractComplete / playFull）---
let bd2Profile = null, bd2FullPlaying = false, bd2IdleAfter = '', bd2MotionCdUntil = 0;
BD2Interact.resetMix();

const events = [];
function ev(t, kind, name, extra) {
  events.push({ t: t.toFixed(2), kind, name, extra: extra || '' });
}

state.addListener({
  start: (e) => { if (e.trackIndex === 0) ev(simT, 'start', e.animation.name); },
  interrupt: (e) => { if (e.trackIndex === 0) ev(simT, 'INTERRUPT', e.animation ? e.animation.name : '?'); },
  end: (e) => { if (e.trackIndex === 0) ev(simT, 'end', e.animation ? e.animation.name : '?'); },
  complete: (e) => {
    if (e.trackIndex !== 0) return;
    if (e.loop) return;
    const name = e.animation ? e.animation.name : '';
    ev(simT, 'complete', name);
    if (bd2FullPlaying && /^(motion|mix\d+_|_face)/.test(name)) {
      bd2FullPlaying = false;
      ev(simT, 'host->idle', bd2IdleAfter);
      playFull(bd2IdleAfter, true);
      return;
    }
  },
});

function playFull(name, loop) {
  let exists = false;
  for (const a of data.animations) if (a.name === name) { exists = true; break; }
  if (!exists) { ev(simT, 'MISS', name); return false; }
  const entry = state.setAnimation(0, name, loop);
  entry.mixDuration = 0.16;
  state.update(0);
  state.apply(skeleton);
  skeleton.updateWorldTransform();
  return true;
}

function click() {
  if (!bd2Profile) {
    bd2Profile = BD2Interact.detect(data.animations.map(a => a.name));
    BD2Interact.resetMix();
  }
  const react = BD2Interact.decide(bd2Profile, [], null, { x: 0, y: 0 },
    { motionCooldownUntil: bd2MotionCdUntil });
  if (!react) { ev(simT, 'decide-null'); return; }
  if (react.mode === 'overlay') {
    state.clearTrack(1);
    state.setAnimation(1, react.anim, false);
    ev(simT, 'overlay-track1', react.anim);
    if (react.motion && data.animations.some(a => a.name === 'motion')) {
      bd2FullPlaying = true;
      bd2IdleAfter = 'idle';
      playFull('motion', false);
      bd2MotionCdUntil = simMs + 12000;
    }
  } else {
    bd2FullPlaying = true;
    bd2IdleAfter = react.idle;
    const ok = playFull(react.anim, false);
    if (!ok) { playFull(bd2IdleAfter, true); }
    bd2MotionCdUntil = simMs + 6000;
  }
}

// --- 主循环：60fps 推进，每 1.5s 慢速点击 ---
let simT = 0, simMs = 0, nextClick = 0.5;
const DT = 1 / 60, TOTAL = 300;
const started = new Set();
while (simT < TOTAL) {
  if (simT >= nextClick) { click(); nextClick += 1.5; }
  state.update(DT);
  state.apply(skeleton);
  const cur = state.getCurrent(0);
  const nm = cur && cur.animation ? cur.animation.name : '(none)';
  started.add(nm);
  simMs += DT * 1000; simT += DT;
}

console.log('\n=== track0 上出现过的动画 ===');
console.log([...started].join(', '));
console.log('\n=== 事件流（前 120 条）===');
for (const e of events.slice(0, 120)) console.log(`${e.t}s ${e.kind.padEnd(12)} ${e.name} ${e.extra}`);
console.log('total events:', events.length);

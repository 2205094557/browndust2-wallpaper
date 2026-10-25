// 验证章节图行走：computeMotionTargets 实测 + 打印完整播放序列
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
function run(rel, clicks) {
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
  const sd = new spine.AnimationStateData(data);
  const profile = BD2Interact.detect(data.animations.map(a => a.name));
  if (profile.style === 'mix') {
    BD2Interact.computeMotionTargets(profile, () => ({
      state: new spine.AnimationState(sd),
      skeleton: new spine.Skeleton(data),
    }));
  }
  BD2Interact.resetMix();
  console.log('=== ' + path.basename(rel), '| motionTargets:', JSON.stringify(profile.motionTargets || {}));
  const seq = [];
  for (let i = 0; i < clicks; i++) {
    const r = BD2Interact.decide(profile, [], null, { x: 0, y: 0 }, {});
    seq.push(r.anim + ' → ' + r.idle);
  }
  seq.forEach((s, i) => console.log(String(i + 1).padStart(3) + '. ' + s));
}
run('resources/extracted/spine/illust_dating11/illust_dating11.skel', 50);
run('resources/extracted/spine/illust_dating14/illust_dating14.skel', 20);

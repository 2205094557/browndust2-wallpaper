// 三皮肤结构速查：章节动画分布 / 各章 homeIdle / motion 分类 / 每动画覆盖槽数分布
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
const targets = process.argv[2] ? process.argv[2].split(',') : ['illust_dating12', 'illust_dating17', 'illust_dating20'];
const spineDir = path.join(ROOT, 'resources/extracted/spine');
for (const d of targets) {
  const dir = path.join(spineDir, d);
  const skelFile = fs.readdirSync(dir).find((f) => f.endsWith('.skel') && !f.includes('.skel.skel'));
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, skelFile))));
  const profile = BD2Interact.detect(data.animations.map((a) => a.name));
  const sd = new spine.AnimationStateData(data);
  BD2Interact.computeMotionTargets(profile, () => ({
    state: new spine.AnimationState(sd),
    skeleton: new spine.Skeleton(data),
  }));
  console.log('\n===== ' + d + ' ===== slots=' + data.slots.length + ' anims=' + data.animations.length);
  console.log('  style=' + profile.style + ' idles=' + JSON.stringify(profile.idles));
  console.log('  homeIdle(实测)=' + JSON.stringify(profile.homeIdle));
  const motionT = profile.motionTargets || {};
  const motions = profile.motions.filter((n) => /^motion\d+/.test(n)).map((n) => n + '→' + (motionT[n] || '?'));
  console.log('  motion终态(' + motions.length + '): ' + motions.slice(0, 24).join('  '));
  // 每章动画分组与各动画时长
  const chAnims = {};
  for (const a of data.animations) {
    let m = /^(?:idle|mix)(\d+)_?/.exec(a.name) || /^motion(\d+)/.exec(a.name);
    const ch = m ? m[1] : '?';
    (chAnims[ch] = chAnims[ch] || []).push([a.name, a.duration.toFixed(2)]);
  }
  for (const ch of Object.keys(chAnims)) {
    const list = chAnims[ch];
    console.log('  章' + ch + ' (' + list.length + ' 动画): ' + list.slice(0, 10).map((x) => x[0] + '=' + x[1] + 's').join(' ') + (list.length > 10 ? ' ...' : ''));
  }
  // 各动画覆盖槽数（AttachmentTimeline 的槽集合大小）分布：槽覆盖率
  const slotN = data.slots.length;
  const covers = data.animations.map((a) => {
    const s = new Set();
    for (const t of a.timelines) if (t.constructor.name.includes('Attachment')) s.add(t.slotIndex);
    return [a.name, s.size, Math.round((s.size / slotN) * 100) + '%'];
  }).filter((x) => /^(idle|mix\d+_|motion)/.test(x[0]));
  covers.sort((a, b) => a[1] - b[1]);
  console.log('  覆盖率最低 5 动画: ' + covers.slice(0, 5).map((x) => x[0] + '=' + x[2]).join('  '));
  console.log('  覆盖率最高 3 动画: ' + covers.slice(-3).map((x) => x[0] + '=' + x[2]).join('  '));
}

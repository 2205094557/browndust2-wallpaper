// 家 idle 泄漏判定：某章进入后先播家 idle{K}（宿主每步之间都回它），
// 之后点任意 mix 段——idle{K} 覆盖不到、且 setup 底稿非空的槽会一直显示
// 底稿默认组件（与当前章节无关，"每次都是它"）；换章后 idle{K+1} 覆盖不同槽，
// 错误组件消失或换成另一个。此探针列出每个"章"的这类槽及底稿附件名。
// 用法: node tools/_mix_probe/idle_leak_probe.js [皮肤目录...]
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
const spineDir = path.join(ROOT, 'resources/extracted/spine');
const targets = process.argv[2] ? process.argv[2].split(',') :
  ['illust_dating12', 'illust_dating17', 'illust_dating20'];
for (const d of targets) {
  const dir = path.join(spineDir, d);
  const skelFile = fs.readdirSync(dir).find((f) => f.endsWith('.skel') && !f.includes('.skel.skel'));
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, skelFile))));
  const sk = new spine.Skeleton(data);
  sk.setToSetupPose();
  const covers = {};
  for (const a of data.animations) {
    const s = new Set();
    for (const t of a.timelines) if (t.constructor.name.includes('Attachment')) s.add(t.slotIndex);
    covers[a.name] = s;
  }
  const slotName = data.slots.map((s) => s.name);
  console.log('\n===== ' + d + ' ===== 槽总数 ' + data.slots.length);
  const chapNums = new Set();
  for (const a of data.animations) {
    const m = /^idle(\d+)$/.exec(a.name);
    if (m) chapNums.add(parseInt(m[1], 10));
  }
  for (const ch of [...chapNums].sort((a, b) => a - b)) {
    const idle = 'idle' + ch;
    const cov = covers[idle] || new Set();
    const rows = [];
    for (let i = 0; i < data.slots.length; i++) {
      if (cov.has(i)) continue;
      const aName = sk.slots[i].attachment ? sk.slots[i].attachment.name : null;
      if (!aName) continue;
      const elsewhere = [];
      for (const n of data.animations) {
        if (n !== idle && (covers[n] || new Set()).has(i)) { elsewhere.push(n); if (elsewhere.length >= 3) break; }
      }
      rows.push({ slot: slotName[i], att: aName, elsewhere });
    }
    const meaningful = rows.filter((r) => !/^(bone\d+|pt_|root|_?)B?_?probe/i.test(r.slot));
    console.log('  idle' + ch + ' 覆盖 ' + Math.round((cov.size / data.slots.length) * 100) + '%,' +
      ' 未覆盖且有底稿附件 ' + rows.length + ' 个 (可读 ' + meaningful.length + ')');
    meaningful.slice(0, 12).forEach((r) => console.log('    ' + r.slot + ' = 底稿[' + r.att + ']' +
      (r.elwhere && r.elwhere.length ? ' 别处动画:' + r.elwhere.slice(0, 2).join(',') : ' 仅底稿(无动画使用)')));
    if (!meaningful.length && rows.length) {
      rows.slice(0, 6).forEach((r) => console.log('    [原始] ' + r.slot + ' = ' + r.att));
    }
  }
}

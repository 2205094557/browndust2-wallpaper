// 一次性探针：扫描全部 spine 提取目录（含主立绘 char*），列出每个骨架的
// 动画数 / 互动风格（BD2Interact.detect）/ faces / motions / mix 章节数，
// 用于排查「主立绘互动动画偏少」问题。
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
const dirs = fs.readdirSync(spineDir).filter(d => {
  try { return fs.statSync(path.join(spineDir, d)).isDirectory(); } catch { return false; }
});
const rows = [];
for (const d of dirs) {
  const dir = path.join(spineDir, d);
  const skelFile = fs.readdirSync(dir).find(f => f.endsWith('.skel'));
  if (!skelFile) continue;
  let data;
  try {
    const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
    data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, skelFile))));
  } catch (e) { rows.push({ d, err: e.message.slice(0, 60) }); continue; }
  const names = data.animations.map(a => a.name);
  const p = BD2Interact.detect(names);
  rows.push({
    d, n: names.length, style: p.style,
    faces: p.faces.length, talk: p.faceTalk.length,
    mixChaps: Object.keys(p.mixPools).length,
    mixAnims: Object.values(p.mixPools).reduce((s, a) => s + a.length, 0),
    idles: p.idles.length, motions: p.motions.length,
    hasMotion: p.hasMotion, idleTalk: p.hasIdleTalk,
    other: names.filter(n => !/^_face\d+(_talk)?$/.test(n) && !/^idle\d*$/.test(n)
      && !/^motion\d+(_\d+)?$/.test(n) && !parseMix(n)).slice(0, 12),
  });
}
function parseMix(n) { return /^mix(\d+)_(\d+)(?:_(\d+))?(?:_(long|loop|end)(\d*))?$/.test(n); }
const isMain = r => /^char\d+$/.test(r.d);
const mains = rows.filter(isMain).sort((a, b) => (b.n || 0) - (a.n || 0));
console.log('===== 主立绘 char* (按动画数排序) =====');
for (const r of mains) console.log(JSON.stringify(r));
const others = rows.filter(r => !isMain(r));
const mixy = others.filter(r => r.style === 'mix');
console.log(`\n===== 其余 ${others.length} 个皮肤：mix 型 ${mixy.length} 个 =====`);
for (const r of others.filter(r => r.style !== 'mix' || /dating(11|14|18|20|21)/.test(r.d)).slice(0, 8))
  console.log(JSON.stringify(r));

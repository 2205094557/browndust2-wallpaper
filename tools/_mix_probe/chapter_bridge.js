// 验证章节切换机制：每章 mix 首段/末段的附件结束态最接近哪个 idle
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
  return a;
}
const mockLoader = {
  newRegionAttachment: (_s, n) => att(n), newMeshAttachment: (_s, n) => att(n),
  newBoundingBoxAttachment: (_s, n) => att(n), newPathAttachment: (_s, n) => att(n),
  newPointAttachment: (_s, n) => att(n), newClippingAttachment: (_s, n) => att(n),
};
function analyze(rel, pools) {
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(ROOT, rel))));
  function stateOf(name, sec) {
    const sd = new spine.AnimationStateData(data);
    const st = new spine.AnimationState(sd), sk = new spine.Skeleton(data);
    sk.setToSetupPose();
    const a = data.animations.find(x => x.name === name);
    st.setAnimation(0, name, true);
    st.update(sec != null ? Math.min(sec, a.duration) : a.duration); st.apply(sk);
    const m = {}; for (const s of sk.slots) m[s.data.name] = (s.attachment ? s.attachment.name : null);
    return m;
  }
  const idles = data.animations.map(a => a.name).filter(n => /^idle\d+$/.test(n));
  const idlS = {}; for (const n of idles) idlS[n] = stateOf(n, 4);
  const closest = (m) => idles.map(n => n + ':' + (() => { let d = 0; for (const k in m) if (m[k] !== idlS[n][k]) d++; return d; })())
    .sort((a, b) => parseInt(a.split(':')[1]) - parseInt(b.split(':')[1])).slice(0, 2).join(' ');
  console.log('=== ' + path.basename(rel));
  for (const pool of pools) {
    const re = new RegExp('^' + pool + '_(\\d+)(?:_(\\d+|end))?$');
    const steps = data.animations.map(a => a.name).filter(n => re.test(n));
    steps.sort((a, b) => {
      const pa = a.match(re), pb = b.match(re);
      const ve = v => v === 'end' ? 9999 : parseInt(v);
      return (parseInt(pa[1]) - parseInt(pb[1])) || (ve(pa[2] || '0') - ve(pb[2] || '0'));
    });
    for (const n of [steps[0], steps[steps.length - 1]]) {
      const s = stateOf(n);
      const dur = data.animations.find(a => a.name === n).duration.toFixed(2);
      console.log('  ' + n.padEnd(14) + ' dur=' + dur + ' 结束态: ' + closest(s));
    }
  }
}
analyze('resources/extracted/spine/illust_dating11/illust_dating11.skel', ['mix1', 'mix3', 'mix4']);
analyze('resources/extracted/spine/illust_dating14/illust_dating14.skel', ['mix1', 'mix2']);

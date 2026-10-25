// 两端取景管线数值对比：预览（1000×562）vs 导出模板（1280×720）
// 完整复刻：playAnimation('curtain') → t0 姿态 → markMaskSlots → applyCharacterFit
//          → computeBounds（背景图分支优先）→ WL.spineCamera → 帷幕屏幕投影
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const spineSrc = fs.readFileSync(path.join(ROOT, 'templates/spine41/spine-webgl-4.1.js'), 'utf8');
const spine = new Function(spineSrc + '\nreturn spine;')();
global.window = global;
const layoutSrc = fs.readFileSync(path.join(ROOT, 'templates/wallpaper-layout.js'), 'utf8');
const WL = new Function(layoutSrc + '\nreturn WallpaperLayout;')();

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

// 与两端一致的槽位过滤/取景/标记逻辑（源自 SpinePreview.vue 与 wallpaper_spine.html）
function isBgLayerName(nm) {
  return nm === 'bk' || nm === 'bg' || nm.startsWith('b_bg') || nm.startsWith('bg_') || nm.startsWith('bg-');
}
function markMaskSlots(skeleton) {
  // 两端一致：巨型网格遮罩槽打标（FR/BK/black/hit_cut_BG 围板 + 大面积 mesh）
  const marked = [];
  for (const slot of skeleton.slots) {
    slot._maskPanel = false;
    const att = slot.getAttachment();
    if (!att) continue;
    if (slot.color && slot.color.a < 0.01) continue;
    const nm = (att.name || '').toLowerCase();
    if (nm.startsWith('kkkkk')) continue;
    if (nm.startsWith('hit_cut_bg') || nm.startsWith('fr') || nm.startsWith('bk') || nm.includes('black')) {
      slot._maskPanel = true;
      marked.push(slot.data.name + ':' + (att.name || ''));
    }
  }
  return marked;
}
function layerBounds(sk) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const slot of sk.slots) {
    const att = slot.getAttachment();
    if (!att) continue;
    if (slot.color && slot.color.a < 0.01) continue;
    if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue;
    if (slot._maskPanel) continue;
    const isRegion = att instanceof spine.RegionAttachment;
    if (!isRegion && !(att instanceof spine.MeshAttachment) && !(att instanceof spine.BoundingBoxAttachment)) continue;
    const len = isRegion ? 8 : att.worldVerticesLength;
    if (!len) continue;
    const verts = spine.Utils.newFloatArray(len);
    if (isRegion) att.computeWorldVertices(slot, verts, 0, 2);
    else att.computeWorldVertices(slot, 0, len, verts, 0, 2);
    for (let j = 0; j < len; j += 2) {
      if (verts[j] < minX) minX = verts[j];
      if (verts[j] > maxX) maxX = verts[j];
      if (verts[j + 1] < minY) minY = verts[j + 1];
      if (verts[j + 1] > maxY) maxY = verts[j + 1];
    }
  }
  return { minX, maxX, minY, maxY };
}
function isBgLayer(l) { return !!l.bg || isBgLayerName((l.name || '').toLowerCase()); }

function analyze(cw, ch, tag, bgImgW, bgImgH) {
  const bin = new spine.SkeletonBinary(mockLoader); bin.scale = 1;
  const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(
    path.join(ROOT, 'resources/extracted/spine/cutscene_char067103/cutscene_char067103.skel'))));
  const sd = new spine.AnimationStateData(data);
  const st = new spine.AnimationState(sd);
  const sk = new spine.Skeleton(data);
  // bestSkin：附件最多的皮肤（与两端 bestSkin 逻辑一致）
  let best = null, bestN = -1;
  for (const s of data.skins) {
    let n = 0;
    for (const entries of Object.values(s.attachments || {})) n += Object.keys(entries).length;
    if (n > bestN) { bestN = n; best = s.name; }
  }
  if (best) sk.setSkinByName(best);
  sk.setSlotsToSetupPose();
  sk.updateWorldTransform();
  const layer = { skeleton: sk, name: 'cutscene_char067103', bg: { width: bgImgW, height: bgImgH } };
  // playAnimation('curtain')（非表情 → track0 循环）
  st.setAnimation(0, 'curtain', true);
  st.update(0); st.apply(sk); sk.updateWorldTransform();
  const marked = markMaskSlots(sk);
  // applyCharacterFit：无背景 LAYER → no-op（两端一致）
  // computeBounds：背景图分支（bgImg 存在 → cover(角色bbox)×1.15，中心=角色bbox中心）
  const cb = layerBounds(sk);
  console.log('  [debug] charBBox:', JSON.stringify(cb));
  let bounds;
  if (cb.maxX > cb.minX && cb.maxY > cb.minY) {
    const bw = cb.maxX - cb.minX, bh = cb.maxY - cb.minY;
    const s = Math.max(bw / bgImgW, bh / bgImgH) * 1.15;
    const bw2 = bgImgW * s, bh2 = bgImgH * s;
    const cx = (cb.minX + cb.maxX) / 2, cy = (cb.minY + cb.maxY) / 2;
    bounds = { minX: cx - bw2 / 2, maxX: cx + bw2 / 2, minY: cy - bh2 / 2, maxY: cy + bh2 / 2 };
  }
  const cam = WL.spineCamera(bounds, cw, ch, { scale: 100, offsetX: 0, offsetY: 0, alignX: 0.5, alignY: 0.5 });
  // 帷幕屏幕投影（世界 → 屏幕，y 翻转）
  function toScreen(x, y) { return { x: (x - cam.x) * cam.zoom + cw / 2, y: ch / 2 - (y - cam.y) * cam.zoom }; }
  // 找帷幕与幽灵附件的世界框
  const find = [];
  for (const slot of sk.slots) {
    const att = slot.getAttachment();
    if (!att) continue;
    const nm = (att.name || '').toLowerCase();
    if (nm.includes('curtain') || nm === 'media' || nm.includes('body')) {
      const isRegion = att instanceof spine.RegionAttachment;
      const len = isRegion ? 8 : att.worldVerticesLength;
      const verts = spine.Utils.newFloatArray(len);
      if (isRegion) att.computeWorldVertices(slot, verts, 0, 2);
      else att.computeWorldVertices(slot, 0, len, verts, 0, 2);
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (let j = 0; j < len; j += 2) {
        minX = Math.min(minX, verts[j]); maxX = Math.max(maxX, verts[j]);
        minY = Math.min(minY, verts[j + 1]); maxY = Math.max(maxY, verts[j + 1]);
      }
      const p1 = toScreen(minX, maxY), p2 = toScreen(maxX, minY);
      find.push((att.name || '?') + ': 屏幕 x ' + Math.round(p1.x) + '~' + Math.round(p2.x) + ' y ' + Math.round(p1.y) + '~' + Math.round(p2.y));
    }
  }
  console.log('===', tag, cw + 'x' + ch);
  console.log('  marked:', marked.join(','), '| bounds:', JSON.stringify(Object.values(bounds).map(Math.round)), '| cam.zoom:', cam.zoom.toFixed(4), 'cam.x:', Math.round(cam.x), 'cam.y:', Math.round(cam.y));
  find.forEach(f => console.log('  ', f));
}

// 预览：1000×562 画布，bg 图 1024×1024
analyze(1000, 562, '预览 (1000x562)', 1024, 1024);
// 导出：1280×720 画布（headless 实测尺寸），同一张 bg 图
analyze(1280, 720, '导出 (1280x720)', 1024, 1024);

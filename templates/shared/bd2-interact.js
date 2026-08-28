// BD2 立绘互动引擎（单源共享：预览 SpinePreview.vue 与壁纸 wallpaper_spine.html
// 都加载本文件，改一处两边同步——与预乘 alpha 铁律同一维护模式）。
//
// 背景（2026-08 实测结论，见 AGENTS.md）：
//   BD2 skel/prefab 资产里【没有】官方分部位命中区数据（无 BoundingBoxAttachment、
//   VP_IllustViewer 只有全身锚点 BoxCollider）。官方的「摸头/摸身体→不同反应」逻辑
//   编译在游戏代码里。因此本引擎用"语义骨骼锚点 + 区域启发式"重建交互：
//   - 主立绘骨架骨骼名语义清晰（head/chest/hand_l/hip_trans/leg_l…）→ 锚点跟随动画姿态；
//   - 命中区测试在世界坐标做最近锚点分类（带合成兜底锚点 + 语义加成）；
//   - 反应 = 官方 _faceN 表情动画（track1 叠加）+ 按区域情绪组挑 Int_{Mood} 互动语音
//     （Smile/Sigh/Surprise/Excitement/Neutral，cue 全部是官方原声）。
// 本文件必须保持零依赖（不引用 spine 全局、不访问 DOM 之外的浏览器特性），
// 通过参数注入 skeleton / renderer 回调，保证在 Vue 组件与 WE 壁纸两个宿主中行为一致。

;(function () {
  'use strict';

  // ===== 动画集识别 ==========================================================
  // BD2 有两代互动立绘命名体系：
  //   第一代（主立绘 + 早期约会，如 illust_dating2）：idle / motion / _face0..N (+_talk)
  //     → 表情反应叠加 track1，body 保持 idle 循环
  //   第二代（互动约会，如 illust_dating14 Hedonist·约会 实测）：
  //     idle1/idle2 + mix{1,2}_N_M（几十组互动反应演出）+ motion1_N
  //     → 整段演出走 track0 单发，播完回待机循环
  // 返回 profile.style ∈ 'face' | 'mix' | 'none'（bd2 布尔保留兼容旧调用）。

  function detect(animNames) {
    var faces = [];
    var faceTalk = [];
    var hasMotion = false;
    var hasIdleTalk = false;
    var mixPools = {};        // { "1": [mix1_N_M,...], "2": [...] }
    var idles = [];           // 第二代多待机：['idle1','idle2']
    var motions = [];         // 第二代整身动作：motion1_22 等
    for (var i = 0; i < animNames.length; i++) {
      var n = animNames[i];
      if (/^_face\d+$/i.test(n)) faces.push(n);
      else if (/^_face\d+_talk$/i.test(n)) faceTalk.push(n);
      else if (n === 'motion') hasMotion = true;
      else if (n === 'idle_talk') hasIdleTalk = true;
      else if (/^idle\d*$/i.test(n)) idles.push(n);
      else if (/^motion\d+(_\d+)?$/i.test(n)) motions.push(n);
      else {
        var mm = /^(mix\d+)_(?:\d+)_(?:\d+)$/.exec(n);
        if (mm) {
          if (!mixPools[mm[1]]) mixPools[mm[1]] = [];
          mixPools[mm[1]].push(n);
        }
      }
    }
    faces.sort(function (a, b) {
      return parseInt(a.slice(5), 10) - parseInt(b.slice(5), 10);
    });
    var style = faces.length > 0 ? 'face' : (Object.keys(mixPools).length > 0 ? 'mix' : 'none');
    return {
      bd2: style !== 'none', style: style,
      faces: faces, faceTalk: faceTalk,
      hasMotion: hasMotion, hasIdleTalk: hasIdleTalk,
      mixPools: mixPools, idles: idles.sort(), motions: motions.sort(),
    };
  }

  // ===== 区域定义 ============================================================
  // pat 用于匹配骨骼名（主立绘骨骼命名实测有 head/neck/chest_r/hand_l/finger_*/…，
  // 约会立绘较匿名但有 touch_point 特效锚点）。patAll 为保底正则（后缀变体）。

  var ZONE_DEFS = [
    { id: 'head',  label: '头部', moods: ['Smile', 'Neutral'],
      pat: /^(head|head_\w*|b_head\w*|face\w*|eye\w*|eyebrow\w*|eyeline\w*|eyeball\w*|mouth\w*|ear\w*|hair_f\w*|cheek\w*)$/,
      anchorBiasY: 1.00 },
    { id: 'chest', label: '胸口', moods: ['Excitement', 'Surprise', 'Sigh'],
      pat: /^(chest\w*|bust\w*|breast\w*|b_body\w*|b_sh_\w*)$/, anchorBiasY: 0.72 },
    { id: 'belly', label: '腹部', moods: ['Neutral', 'Sigh'],
      pat: /^(belly|stomach|abdomen|body2?|b_body1)$/, anchorBiasY: 0.50 },
    { id: 'hip',   label: '腰部', moods: ['Surprise', 'Excitement'],
      pat: /^(hip\w*|waist\w*|skirt\w*|b_obi\w*)$/, anchorBiasY: 0.32 },
    { id: 'arm',   label: '手臂', moods: ['Neutral', 'Smile'],
      pat: /(arm|hand|finger|shoulder|sleeve)/, patAny: true, anchorBiasY: 0.62 },
    { id: 'leg',   label: '腿部', moods: ['Surprise', 'Neutral'],
      pat: /(leg|foot|knee|thigh|calf|shoe|sock|heel)/, patAny: true, anchorBiasY: 0.15 },
  ];

  // 无语义骨骼时按内容包围盒比例生成兜底锚点（y 相对 box 底部比例）
  var FALLBACK_RATIO = {
    head:  { x: 0.50, y: 0.90 },
    chest: { x: 0.50, y: 0.70 },
    belly: { x: 0.50, y: 0.52 },
    hip:   { x: 0.50, y: 0.36 },
    arm:   { x: 0.18, y: 0.64 },   // 取左臂位置（镜像由 bones 命中时解决）
    leg:   { x: 0.40, y: 0.12 },
  };

  function buildZones(skeleton) {
    var zones = [];
    for (var z = 0; z < ZONE_DEFS.length; z++) {
      var def = ZONE_DEFS[z];
      var bones = [];
      for (var i = 0; i < skeleton.bones.length; i++) {
        var b = skeleton.bones[i];
        // 统一小写后再匹配：第二代约会骨架骨骼是 B_ 前缀（B_head/B_arm_L_A…）
        var nm = (((b.data && b.data.name) || b.name || '') + '').toLowerCase();
        var hit = false;
        if (def.patAny) hit = def.pat.test(nm);
        else hit = def.pat.test(nm) || nm.indexOf(def.id) === 0;
        if (hit) bones.push({ name: nm, worldX: b.worldX || 0, worldY: b.worldY || 0 });
      }
      zones.push({
        id: def.id, label: def.label, moods: def.moods.slice(),
        biasY: def.anchorBiasY, bones: bones, matched: bones.length > 0,
      });
    }
    return zones;
  }

  // ===== 点击分类 ============================================================
  // 世界坐标 wp={x,y} → 最近语义锚点。评分 = 距离 / 半径 × 修正系数：
  //   - 有真实骨骼锚点的区域取所有命中骨骼里距点击最近的那个（天然跟随动画姿态）；
  //   - 无骨骼命中的区域用包围盒比例兜底锚点，且距离罚系数 1.6（能赢但让位于真锚点）。
  // 返回 {zone:{id,label,moods}} 或 null（点击落在角色框外不触发——壁纸场景
  // 不能一点背景就出声）。
  // box 允许传 null：引擎内部用锚点自身范围定界（第二代互动约会骨架内嵌整幅
  // 背景 mesh，宿主的逐附件包围盒会被背景撑爆导致框外判定完全失效）。

  function boxOf(zones) {
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (var i = 0; i < zones.length; i++) {
      var bs = zones[i].bones;
      for (var k = 0; k < bs.length; k++) {
        if (bs[k].worldX < minX) minX = bs[k].worldX;
        if (bs[k].worldX > maxX) maxX = bs[k].worldX;
        if (bs[k].worldY < minY) minY = bs[k].worldY;
        if (bs[k].worldY > maxY) maxY = bs[k].worldY;
      }
    }
    if (!Number.isFinite(minX)) return null;
    return { minX: minX, maxX: maxX, minY: minY, maxY: maxY };
  }

  function classify(zones, box, wp) {
    box = box || boxOf(zones);
    if (!box) return null;
    // 锚点范围外扩 15%（头/脚等边缘锚点不是几何边界）；
    // 宽度兜底 0.35H：正面直立姿锚点可能水平塌缩成一条线（头在身体正上方）
    var W0 = box.maxX - box.minX;
    var H0 = box.maxY - box.minY;
    if (!(Math.max(W0, H0) > 1)) return null;
    var cx = (box.minX + box.maxX) / 2, cy = (box.minY + box.maxY) / 2;
    var H = Math.max(H0 * 1.15, 2);
    var W = Math.max(W0 * 1.15, H * 0.35);
    var mx = 0.06 * Math.max(W, H); // 允许贴边的手感余量
    if (wp.x < cx - W / 2 - mx || wp.x > cx + W / 2 + mx ||
        wp.y < cy - H / 2 - mx || wp.y > cy + H / 2 + mx) return null;

    var best = null;
    for (var i = 0; i < zones.length; i++) {
      var zone = zones[i];
      var score = Infinity;
      if (zone.matched) {
        for (var k = 0; k < zone.bones.length; k++) {
          var bn = zone.bones[k];
          var dx = bn.worldX - wp.x, dy = bn.worldY - wp.y;
          // 横向距离加权 1.25：躯干左右分区主要靠水平轴
          var d = Math.sqrt(dx * dx * 1.5625 + dy * dy);
          if (d < score) score = d;
        }
        score /= (H * 0.42);
      } else {
        var fr = FALLBACK_RATIO[zone.id] || { x: 0.5, y: 0.5 };
        var fx = cx - W / 2 + fr.x * W;
        var fy = cy - H / 2 + fr.y * H;
        var dx2 = fx - wp.x, dy2 = fy - wp.y;
        score = Math.sqrt(dx2 * dx2 * 1.5625 + dy2 * dy2) / (H * 0.42) * 1.6;
      }
      if (!best || score < best.score) best = { zone: zone, score: score };
    }
    return best ? { zone: best.zone } : null;
  }

  // 决策入口：宿主每次点击调用。opts 由宿主保存传递：
  //   opts.motionCooldownUntil —— 整身大动作冷却截止
  // 顺序播放模型下【点击任意位置都触发】（旧的分部位命中已废弃）：
  //   mix 皮肤严格沿官方序列推进，位置不参与决策；语音情绪按点击次数在五类
  //   Int_{Mood} 间轮换，保证每种官方反应语音都会出现。
  // 返回 { zone, anim, mode, idle, motion }：
  //   mode='overlay' —— 表情类，叠加 track1（第一代 face 集）
  //   mode='full'    —— 整段演出，track0 单发播完回 idle 循环（mix/motion）
  //   idle —— full 模式建议回退的待机动画名
  var lastFaceIndex = -1;
  var _mixStep = 0; // mix 顺序播放的全局指针（resetMix 归零）
  var MOOD_CYCLE = ['Smile', 'Neutral', 'Sigh', 'Surprise', 'Excitement'];
  var _moodIdx = 0;

  function decide(profile, zones, box, wp, opts) {
    opts = opts || {};
    var zone = { id: 'tap', label: '', moods: [MOOD_CYCLE[_moodIdx % MOOD_CYCLE.length]] };
    var now = Date.now();

    var reacted = _decideInner(profile, zone, opts, now);
    if (reacted) _moodIdx++;
    return reacted;
  }

  function _decideInner(profile, zone, opts, now) {
    if (profile.style === 'face') {
      var pool = profile.faces;
      if (!pool.length) return null;
      var idx = Math.floor(Math.random() * pool.length);
      if (pool.length > 1 && idx === lastFaceIndex) idx = (idx + 1) % pool.length;
      lastFaceIndex = idx;
      var cdOk = now >= (opts.motionCooldownUntil || 0);
      return {
        zone: zone,
        anim: pool[idx],
        mode: 'overlay',
        motion: !!(profile.hasMotion && cdOk && Math.random() < 0.22),
      };
    }

    // mix 风格（第二代互动约会）：官方全局顺序播放——
    //   章节 k 的所有 mix 步进（每步回 idleK）→ 然后【motionK 过渡桥】
    //  （第 k 章全部 mix 走完后的那次点击先播 motion 变体，播完切到 idle(K+1)）
    //   → 进入章节 K+1 的 mix 循环……最后一张的桥切回第一章（循环）。
    // 排序必须按数值而非字典序（mix1_20 在 mix1_3 之后）；章节↔待机按数字匹配。
    if (!profile._playlist) {
      var chapters = Object.keys(profile.mixPools).map(function (g) {
        return parseInt(g.replace('mix', ''), 10);
      }).sort(function (a, b) { return a - b; });
      var motionsByChap = {};
      for (var mi = 0; mi < profile.motions.length; mi++) {
        var mm2 = /^motion(\d+)(?:_(\d+))?$/.exec(profile.motions[mi]);
        if (!mm2) continue;
        var chap = parseInt(mm2[1], 10);
        if (!motionsByChap[chap]) motionsByChap[chap] = [];
        motionsByChap[chap].push({ name: profile.motions[mi], seq: parseInt(mm2[2] || '0', 10) });
      }
      var playlist = [];
      function chapterIdleOf(chapIdx) {
        var name = profile.idles[0] || 'idle';
        for (var q = 0; q < profile.idles.length; q++) {
          var im = /^idle(\d+)$/.exec(profile.idles[q]);
          if (im && parseInt(im[1], 10) === chapIdx) { name = profile.idles[q]; break; }
        }
        return name;
      }
      for (var ci = 0; ci < chapters.length; ci++) {
        var ch = chapters[ci];
        var curIdle = chapterIdleOf(ch);
        var poolKey = 'mix' + ch;
        var steps = (profile.mixPools[poolKey] || []).map(function (n) {
          var pm = /^mix\d+_(\d+)_(\d+)$/.exec(n);
          return { n: n, idx: parseInt(pm[1], 10), sq: parseInt(pm[2], 10) };
        }).sort(function (a, b) { return (a.idx - b.idx) || (a.sq - b.sq); });
        for (var st = 0; st < steps.length; st++) {
          playlist.push({ anim: steps[st].n, idle: curIdle });
        }
        // 章末桥：该章的全部 motion 变体按序播放；播完进入下一章待机
        var nextChap = chapters[(ci + 1) % chapters.length];
        var nextIdle = chapterIdleOf(nextChap);
        var bridge = (motionsByChap[ch] || []).sort(function (a, b) { return a.seq - b.seq; });
        for (var bi = 0; bi < bridge.length; bi++) {
          playlist.push({ anim: bridge[bi].name, idle: nextIdle });
        }
      }
      profile._playlist = playlist;
    }
    var pl = profile._playlist;
    if (!pl || !pl.length) return null;
    if (!Number.isFinite(_mixStep)) _mixStep = 0;
    var item = pl[_mixStep % pl.length];
    _mixStep++;
    return {
      zone: zone,
      anim: item.anim,
      mode: 'full',
      idle: item.idle,
    };
  }

  // 外部在皮肤切换/重建 profile 时调用：新皮肤序列从头开始
  function resetMix() { _mixStep = 0; }

  // ===== 整段动画平滑播放 ====================================================
  // 宿主通用的 BD2 track0 播放器（预览 SpinePreview.vue 与壁纸 wallpaper_spine.html
  // 共用单源文件；旧的碧蓝 drag 状态机路径不经此处，不受影响）。
  // opts.cleanSwitch —— BD2 互动整段播放统一走本路径：
  //   1) 不做 setup 姿态/附件重置 —— 表情附件与肢体状态在动作间自然延续
  //      （摸完脸的红晕带进下一段反而更真实），也避免 setToSetupPose 把骨架弹回
  //      绑定姿态造成「一帧抽搐」；
  //   2) ~160ms 交叉淡化 —— 利用 spine AnimationState 原生混合，上一段末帧平滑
  //      溶接进 idle 循环；从 idle 进入 mix 演出、演出之间推进同样有淡化，
  //      整条链路不再有断点（回待机不再硬切跳变）。
  //   淡化时长可用 opts.smoothMs 覆盖（默认 160ms），预览/壁纸两端同步。

  function playFull(layers, name, loop, mixDur, opts) {
    opts = opts || {};
    var started = false;
    for (var i = 0; i < layers.length; i++) {
      var l = layers[i];
      if (!l || !l.skeleton || !l.state || !l.data) continue;
      var exists = false;
      for (var k = 0; k < l.data.animations.length; k++) {
        if (l.data.animations[k].name === name) { exists = true; break; }
      }
      if (!exists) continue;
      if (opts.cleanSwitch) {
        // 原生交叉淡化：不做任何 setup 重置，spine 在 160ms 窗口内平滑混合新旧位姿
        var prev = l.state.getCurrent(0);
        var entry = l.state.setAnimation(0, name, loop);
        entry.mixDuration = opts.smoothMs === undefined ? 0.16 : opts.smoothMs;
        // t=0 预施加：让首帧立即进入新动画起点（避免首帧滞留旧动画）
        l.state.update(0);
        l.state.apply(l.skeleton);
        l.skeleton.updateWorldTransform();
      } else {
        var entry2 = l.state.setAnimation(0, name, loop);
        var cur = l.state.getCurrent(0);
        if (cur && cur.animation && cur.animation.name !== name) {
          entry2.mixDuration = mixDur === undefined ? 0.16 : mixDur;
        }
      }
      started = true;
    }
    return started;
  }

  // ===== 语音挑选 ============================================================
  // cues 两组来源之一：
  //   数组（预览端 voiceStatus.cues）：['_Int_Smile1_1' 等 cue 名]
  //   映射（壁纸端 VOICE_JSON.moods）：{ Smile:[cue,...], Sigh:[...] }
  // moodKeys 按优先级排列，先抽第一组的随机项，全空回退任意 _Int_* cue 再回退任意 cue。

  function cueForMood(cues, moodKeys) {
    if (!cues) return null;
    var pools = [];
    if (Object.prototype.toString.call(cues) === '[object Array]') {
      var byMood = {};
      for (var i = 0; i < cues.length; i++) {
        var m = /_Int_([A-Za-z]+?)\d*_/.exec(cues[i]);
        if (m) {
          var key = m[1].toLowerCase();
          if (!byMood[key]) byMood[key] = [];
          byMood[key].push(cues[i]);
        }
      }
      cues = byMood;
    }
    for (var k = 0; k < moodKeys.length; k++) {
      var mk = String(moodKeys[k]).toLowerCase();
      var direct = null, loose = [];
      for (var g in cues) {
        if (!Object.prototype.hasOwnProperty.call(cues, g)) continue;
        if (g.toLowerCase() === mk) direct = cues[g];
        else if (g.toLowerCase().indexOf(mk) >= 0 || mk.indexOf(g.toLowerCase()) >= 0) loose = loose.concat(cues[g]);
      }
      if (direct && direct.length) pools.push(direct);
      if (loose.length) pools.push(loose);
      break; // 只看第一个候选 + 其宽松匹配；空了交给 fallback
    }
    if (!pools.length) {
      var anyInt = [];
      for (var g2 in cues) if (Object.prototype.hasOwnProperty.call(cues, g2)) anyInt = anyInt.concat(cues[g2]);
      if (anyInt.length) pools.push(anyInt);
    }
    if (!pools.length) return null;
    var pool = pools[0];
    return pool[Math.floor(Math.random() * pool.length)] || null;
  }

  // ===== 点击特效 ============================================================
  // 纯 DOM/CSS 实现（预览与 WE 都是 web 环境），按情绪换图案与颜色：
  //   Smile→粉心  Neutral→星尘  Sigh→水滴  Surprise→惊星  Excitement→红心火苗

  var FX_STYLE =
    '@keyframes bd2fx{0%{transform:translate(-50%,-50%) scale(.4);opacity:0}' +
    '12%{opacity:1}100%{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy))) scale(1.25);opacity:0}}' +
    '.bd2-fx-layer{position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:9}' +
    '.bd2-fx{position:absolute;left:0;top:0;font-size:20px;line-height:1;' +
    'animation:bd2fx .85s ease-out forwards;text-shadow:0 0 6px rgba(255,255,255,.8);will-change:transform,opacity}';

  var FX_GLYPHS = {
    Smile: '\u2661', Neutral: '\u2727',
    Sigh: '\u{1F4A7}', Surprise: '\u2727', Excitement: '\u2665',
  };
  var FX_COLORS = {
    Smile: '#ff8fb3', Neutral: '#ffe9a8', Sigh: '#8fc7ff',
    Surprise: '#ffd76e', Excitement: '#ff6f91',
  };

  var styleInjected = false;

  function spawnEffect(host, offsetX, offsetY, mood) {
    if (!host) return;
    if (!styleInjected) {
      var s = document.createElement('style');
      s.textContent = FX_STYLE;
      document.head.appendChild(s);
      styleInjected = true;
    }
    var layer = host.querySelector(':scope > .bd2-fx-layer');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'bd2-fx-layer';
      if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
      host.appendChild(layer);
    }
    var glyph = FX_GLYPHS[mood] || FX_GLYPHS.Neutral;
    var color = FX_COLORS[mood] || FX_COLORS.Neutral;
    var count = 5 + Math.floor(Math.random() * 3);
    for (var i = 0; i < count; i++) {
      var el = document.createElement('div');
      el.className = 'bd2-fx';
      el.textContent = glyph;
      el.style.left = offsetX + 'px';
      el.style.top = offsetY + 'px';
      el.style.color = color;
      var ang = Math.random() * Math.PI * 2;
      var rad = 24 + Math.random() * 34;
      el.style.setProperty('--dx', Math.cos(ang) * rad + 'px');
      el.style.setProperty('--dy', (Math.sin(ang) * rad - 30) + 'px');
      el.style.animationDelay = (i % 3) * 60 + 'ms';
      layer.appendChild(el);
    }
    setTimeout(function () {
      while (layer.firstChild) layer.removeChild(layer.firstChild);
    }, 1100);
  }

  // ===== 区域调试层（showHitAreas 开关共用） =================================
  // overlay 由引擎创建并持有；worldToScreen 由宿主注入（各自的 camera 实现不同）。
  // getFrame() 每帧被宿主 render loop 调用前更新一次即可（本文件不自带 rAF）。

  function createOverlay(worldToScreenFn) {
    var cv = document.createElement('canvas');
    cv.className = 'bd2-zone-overlay';
    cv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:8;';
    var ctx = cv.getContext('2d');
    return {
      canvas: cv,
      draw: function (zones, renderer, hostW, hostH, dpr) {
        if (cv.width !== hostW * dpr || cv.height !== hostH * dpr) {
          cv.width = hostW * dpr; cv.height = hostH * dpr;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, hostW, hostH);
        for (var i = 0; i < zones.length; i++) {
          var zone = zones[i];
          for (var k = 0; k < zone.bones.length; k++) {
            var sp = worldToScreenFn(renderer, hostW, hostH, zone.bones[k].worldX, zone.bones[k].worldY);
            if (!sp) continue;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, 16, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(120,200,255,.9)';
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.fillStyle = 'rgba(120,200,255,.14)';
            ctx.fill();
            ctx.fillStyle = 'rgba(180,230,255,.95)';
            ctx.font = '11px sans-serif';
            ctx.fillText(zone.label, sp.x + 19, sp.y + 4);
          }
        }
      },
      clear: function () { ctx.clearRect(0, 0, cv.width, cv.height); },
    };
  }

  window.BD2Interact = {
    detect: detect,
    buildZones: buildZones,
    boxOf: boxOf,
    classify: classify,
    decide: decide,
    resetMix: resetMix,
    playFull: playFull,
    cueForMood: cueForMood,
    spawnEffect: spawnEffect,
    createOverlay: createOverlay,
    ZONES_DEFS: ZONE_DEFS,
  };
})();

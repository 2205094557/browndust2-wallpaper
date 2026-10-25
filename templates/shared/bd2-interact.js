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
//   第二代（互动约会，如 illust_dating11/dating14/18 实测）：
//     idle1..N + mix{K}_(步)_[变体][_{long|loop|end}] + motion{K}_*
//     → 章节图行走（见 _decideInner 内注释）：mix 步进回本章 idleK；
//       motion 是【从本章 idleK 出发的过渡桥】（宿主 computeMotionTargets 用
//       附件状态指纹实测其终态，如 dating11 的 1_9→idle2、2_1→idle3、3_0→idle2），
//       播完待机=终态章 idle，指针推进；目标=本章的 motion 是章内反应。
  // 返回 profile.style ∈ 'face' | 'mix' | 'none'（bd2 布尔保留兼容旧调用）。

  // mix 段名语法（dating11/14/18/20/21 实测并集）：
  //   mix{章}_{步}[_{变体}][_{修饰}]，修饰 ∈ long|loop|end（long/loop 可带序号：
  //   mix1_1_long1..long20 + loop1..loop20 = 长演出分段+各自停留循环）。
  // 返回 { chap, step, variant(0=无), mod(0=无,1=long,2=loop,3=end), modN } 或 null。
  function parseMixName(n) {
    var m = /^mix(\d+)_(\d+)(?:_(\d+))?(?:_(long|loop|end)(\d*))?$/.exec(n);
    if (!m) return null;
    var modMap = { long: 1, loop: 2, end: 3 };
    return {
      chap: parseInt(m[1], 10),
      step: parseInt(m[2], 10),
      variant: m[3] ? parseInt(m[3], 10) : 0,
      mod: m[4] ? modMap[m[4]] : 0,
      modN: m[5] ? parseInt(m[5], 10) : 0,
    };
  }

  function detect(animNames) {
    var faces = [];
    var faceTalk = [];
    var hasMotion = false;
    var hasIdleTalk = false;
    var mixPools = {};        // { "1": [mix1_...], "2": [...] }
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
        var mm = parseMixName(n);
        if (mm) {
          var key = 'mix' + mm.chap;
          if (!mixPools[key]) mixPools[key] = [];
          mixPools[key].push(n);
        }
      }
    }
    faces.sort(function (a, b) {
      return parseInt(a.slice(5), 10) - parseInt(b.slice(5), 10);
    });
    var style = faces.length > 0 ? 'face'
      : ((Object.keys(mixPools).length > 0 || motions.length > 0) ? 'mix'
      : (hasMotion ? 'motion' : 'none'));
    // style 'motion'（2026-10 新世代互动皮肤实测，如魔都精兵联动 Special Date）：
    //   骨架只有 idle + motion（无 _faceN 无 mix），槽位带 *_touch 触点标记——
    //   点击播 motion 整身反应，与第一代表情皮同源但无表情可叠。
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
    if (profile.style === 'motion') {
      // 新世代互动皮肤（idle + motion）：点击播 motion 整身反应
      return { zone: zone, anim: 'motion', mode: 'full' };
    }
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

    // mix 风格（第二代互动约会）：章节模型（2026-08 附件状态指纹实测，dating11/dating14）：
    //   - 章节 = idle{K} + 内容（mix{K} 剧情段 和/或 motion{K}_* 反应动画）；
    //     没有对应 idle 的编号不成章（无处待机）。
    //   - mix{K}↔idle{K} 按数字配对（mix3_1_1 单播结束态=idle3 状态，0 槽位差）；
    //     mix 片段自带 t=0 附件键，跨章节播放时自己建立本章状态，无需过场桥。
    //   - motion{K}_* 是第 K 章的点击反应，起止状态都在本章（motion1_9 起止≈idle1、
    //     motion3_0 起止=idle3）——【不是】章节间的过渡桥；旧版把它们当桥播完硬切
    //     下一章 idle，造成状态相差 200+ 附件槽的大跳变（"闪现别的 idle"的根源）。
    //   - 每章的步进序列 = mix{K} 各步（数值序；数字变体在前，long 分段随后、
    //     loop 停留段配对为前一步的 hold——播完循环 hold 等下次点击而非回 idle，
    //     end 收尾垫底）+ motion{K} 反应（seq 序）追加在本章末尾，
    //     每步播完回本章 idle{K}（有 hold 则循环 hold）。
    //   - 章末不插桥：下一步自然进入 K+1 章的首段（其 t=0 附件键完成状态切换）。
    //   排序必须按数值而非字典序（mix1_20 在 mix1_3 之后）。
    if (!profile._playlist) {
      var idleOfNum = {};
      for (var q = 0; q < profile.idles.length; q++) {
        var im = /^idle(\d+)$/.exec(profile.idles[q]);
        if (im) idleOfNum[parseInt(im[1], 10)] = profile.idles[q];
      }
      var mixByChap = {};
      Object.keys(profile.mixPools).forEach(function (g) {
        var num = parseInt(g.replace('mix', ''), 10);
        mixByChap[num] = (profile.mixPools[g] || []).map(function (n) {
          var pm = parseMixName(n);
          if (!pm) return null;
          // 排序：同一步内，数字变体(_1/_2)在前（按变体号），修饰变体在后——
          // long/loop 按 modN 配对交错（long1→loop1→long2→loop2…），end 收尾垫底
          var grp = pm.variant > 0 ? 0 : 1;
          return {
            n: n, step: pm.step, mod: pm.mod, modN: pm.modN,
            k1: grp, k2: grp === 0 ? pm.variant : pm.modN, k3: pm.mod,
            hold: null,
          };
        }).filter(Boolean).sort(function (a, b) {
          return (a.step - b.step) || (a.k1 - b.k1) || (a.k2 - b.k2) || (a.k3 - b.k3);
        });
        // loop 停留段配对：挂到同一步内、同 modN、排序紧邻其前的那个变体上
        // （long1→loop1）；它不作为独立步进（避免重复播放）。
        for (var li = 0; li < mixByChap[num].length; li++) {
          var e = mixByChap[num][li];
          if (e.mod !== 2) continue;
          for (var lj = li - 1; lj >= 0; lj--) {
            var p = mixByChap[num][lj];
            if (p.step !== e.step || p.modN !== e.modN || p.mod === 2) continue;
            p.hold = e.n;
            e.consumed = true;
            break;
          }
        }
      });
      var motByChap = [];
      for (var mi = 0; mi < profile.motions.length; mi++) {
        var mm2 = /^motion(\d+)(?:_(\d+))?$/.exec(profile.motions[mi]);
        if (!mm2) continue;
        motByChap.push({
          chap: parseInt(mm2[1], 10),
          name: profile.motions[mi],
          seq: parseInt(mm2[2] || '0', 10),
        });
      }
      // 章节编号 = 有 mix 池或有 motion 的编号 ∩ 有对应 idle 的编号
      // （注意 motByChap 是数组，章节号要取条目的 chap 字段，不能拿数组下标）
      var chapSeen = {};
      Object.keys(mixByChap).forEach(function (k) { chapSeen[k] = 1; });
      for (var cm = 0; cm < motByChap.length; cm++) chapSeen[motByChap[cm].chap] = 1;
      var chapters = Object.keys(chapSeen).map(Number)
        .filter(function (n) { return idleOfNum[n]; })
        .sort(function (a, b) { return a - b; });
      // 【章节推进（默认开）】点击按章节图行走推进故事：本章 mix 步进 → 章内反应
      // → 过桥进下一章（桥的终态即新章待机，全程附件连续——已实测打断/自然播完
      // 均 0 残留）。"点着点着待机变了"是故事推进的正常表现。
      var LOCK_CHAPTER = false;
      if (LOCK_CHAPTER && chapters.length > 1) chapters = [chapters[0]];
      // 章↔待机配对：宿主实测的 homeIdle 优先（dating20 等皮肤故事链整体错一章，
      // 按数字回待机会闪现真正别章的样子），缺省回退按数字
      function homeIdleOf(ch) {
        return (profile.homeIdle && profile.homeIdle[ch]) || idleOfNum[ch];
      }
      var homeToChap = {};
      for (var hc = 0; hc < chapters.length; hc++) {
        var h = homeIdleOf(chapters[hc]);
        if (h != null && homeToChap[h] == null) homeToChap[h] = chapters[hc];
      }
      // motion 分拣（目标由宿主 computeMotionTargets 实测，缺省=本章反应）：
      //   目标 idle = 本章的实测家 → 章内反应（播完回本章待机）；
      //   目标 idle = 别章的家 → 过场桥（仅锁章模式关闭时用于章节推进；
      //     锁章模式下跨章桥直接不进播放列表——没有章节推进，桥就是孤儿动画）
      var targets = profile.motionTargets || {};
      function chapterOfIdleName(name) {
        var ch = name ? homeToChap[name] : null;
        return ch != null ? ch : null;
      }
      var motionsOf = {};
      for (var co = 0; co < chapters.length; co++) motionsOf[chapters[co]] = { react: [], bridge: [] };
      for (var mi2 = 0; mi2 < motByChap.length; mi2++) {
        var src = motByChap[mi2].chap;
        if (!motionsOf[src]) continue;
        var tn = motByChap[mi2].name;
        var tChap = chapterOfIdleName(targets[tn]);
        if (tChap != null && tChap !== src) {
          if (!LOCK_CHAPTER) motionsOf[src].bridge.push({ name: tn, seq: motByChap[mi2].seq, to: tChap, idle: targets[tn] || homeIdleOf(tChap) });
        } else if (LOCK_CHAPTER && (profile.motionReturnDist || {})[tn] > 30) {
          // 锁章模式：跨章桥播完拽回家会闪（距离过大），不进播放列表
          continue;
        } else {
          motionsOf[src].react.push({ name: tn, seq: motByChap[mi2].seq });
        }
      }
      for (var ck in motionsOf) {
        motionsOf[ck].react.sort(function (a, b) { return a.seq - b.seq; });
        motionsOf[ck].bridge.sort(function (a, b) { return a.seq - b.seq; });
      }
      // 章节图行走：播本章 mix 步进 → 本章反应 → 过一座桥（指针落到目标章；
      // 多桥按访问次数轮换）。桥的目标章必须【尚未访问】才走（否则全部内容
      // 访问完毕前不提前回环，防止 2→1 这类回基地桥把未访问章节绕过去）；
      // 全部章节都访问过后桥自由轮换。无桥时按编号推进到下一个【未访问】章
      // （其首段 t=0 附件键自行建立状态）。播放列表循环取用（%length）。
      var playlist = [];
      var cur = chapters[0];
      var visit = {};
      var seenChap = {};
      var rot = 0; // 全部章节访问完后的全局轮转（防卡死在相邻两章间）
      // 容量按【条目数】估算：全部内容 × 2 + 余量（守卫只防异常死循环）
      var cap = 32;
      for (var cv = 0; cv < chapters.length; cv++) cap += (mixByChap[chapters[cv]] || []).length;
      for (var ck2 in motionsOf) cap += motionsOf[ck2].react.length + motionsOf[ck2].bridge.length;
      cap = cap * 2 + 16;
      var guard = cap * 4;
      while (playlist.length < cap && guard-- > 0) {
        var curIdle2 = homeIdleOf(cur);
        var steps2 = mixByChap[cur] || [];
        for (var st2 = 0; st2 < steps2.length; st2++) {
          if (steps2[st2].consumed) continue; // loop 停留段已作为前一步的 hold
          playlist.push({ anim: steps2[st2].n, idle: steps2[st2].hold || curIdle2, hold: !!steps2[st2].hold });
        }
        visit[cur] = (visit[cur] || 0) + 1;
        seenChap[cur] = 1;
        var info = motionsOf[cur] || { react: [], bridge: [] };
        var moved = false;
        for (var ri = 0; ri < info.react.length; ri++) {
          // 章内反应 motion：实测起止态都≈本章家（returnDist 小），回自家安全且保呼吸
          playlist.push({ anim: info.react[ri].name, idle: curIdle2 });
        }
        var allSeen = Object.keys(seenChap).length >= chapters.length;
        for (var bi2 = 0; bi2 < info.bridge.length && !moved; bi2++) {
          var b = info.bridge[(visit[cur] - 1 + bi2) % info.bridge.length];
          if (!allSeen && seenChap[b.to]) continue; // 还有未访问章节时不提前回环
          // 过桥：终态=目标章家（实测），桥后回目标章家待机
          playlist.push({ anim: b.name, idle: b.idle || homeIdleOf(b.to) });
          cur = b.to;
          moved = true;
        }
        if (!moved) {
          // 无可走桥：优先推进到未访问章，否则全局轮转（保证每章的桥都会被走到）
          var nxt = null;
          for (var uu = 0; uu < chapters.length; uu++) {
            if (!seenChap[chapters[uu]]) { nxt = chapters[uu]; break; }
          }
          if (nxt == null) nxt = chapters[(rot++) % chapters.length];
          cur = nxt;
        }
      }
      profile._playlist = playlist;
      // 链式续播标记（buildChainNext 实测）：链上段播完自动续播下一段；
      // hold 停留段是官方编排的暂停点，不自动续。
      for (var ci = 0; ci < playlist.length; ci++) {
        var ce = playlist[ci];
        ce.chain = (ce.hold || !profile.chainNext) ? null : (profile.chainNext[ce.anim] || null);
      }
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
      chain: item.chain || null,
    };
  }

  // 外部在皮肤切换/重建 profile 时调用：新皮肤序列从头开始
  function resetMix() { _mixStep = 0; }

  // 链式续播：宿主在一段播完时调用，expected=该段实测的 chain 目标。
  // 下一播放列表条目正是目标段（中间没被 hold/反应隔开）才续播并推进指针；
  // 否则返回 null（宿主回待机等点击）。点击推进与自动续播共用同一指针，
  // 链式演出中点击 = 跳进下一段（cleanSwitch 无缝），不会错位。
  function advanceAuto(profile, expected) {
    if (!profile || !profile._playlist || !profile._playlist.length) return null;
    if (!expected) return null;
    if (!Number.isFinite(_mixStep)) _mixStep = 0;
    var item = profile._playlist[_mixStep % profile._playlist.length];
    if (!item || item.anim !== expected) return null;
    _mixStep++;
    return { anim: item.anim, idle: item.idle, chain: item.chain || null };
  }

  // ===== 附件状态指纹实测（章节配对 + motion 终态） =========================
  // 章节与待机的配对、motion 的终态都【无法从动画名推断】：
  //   - 多数皮肤 mix{K} 配 idle{K}，但 dating20 实测 mix7 的家是 idle6、mix5 的家
  //     是 idle4（故事链整体错一章）——按数字回待机 = 每段播完闪现真正别章的样子；
  //   - motion{K}_* 是从本章出发的过渡桥（dating11：1_9→idle2、2_1→idle3、
  //     3_0/4_0→回基地），终态各不相同。
  // 唯一可靠判据是附件状态指纹。判定算法（对正确配对的皮肤零影响）：
  //   家 idle = 让本章开场链（前 3 段连续播放）【入场跳变】最小的 idle
  //   （从 live idleI 接播首段，采样 0.05s 时的附件差；正确配对时接近 0，
  //    错配时是百级大跳变）。
  // motion 终态 = 从源章的【实测家 idle】接播，结束态与各 idle 实时状态比附件差。
  // 引擎保持零依赖：骨架/状态对象由宿主通过 createState() 注入，结果写回
  // profile.homeIdle（{章节号: idle 名}）与 profile.motionTargets（{motion 名: idle 名}）。
  //
  // 阶段骨架（2026-10 实测 illust_dating22 起，多章约会皮每章独立骨架）：
  //   宿主注入 profile.animPhase（{动画名: 阶段键}）与 profile.phases（有序阶段键），
  //   createState(animName) 按动画所属阶段返回对应骨架的状态。探测全部按阶段隔离：
  //   家 idle 只在动画同阶段的 idle 里选；motion 终态只与同阶段 idle 比对，
  //   最小差 > CROSS_PHASE_DIST(30) 视为【跨阶段桥】——目标 = 下一阶段的实测家
  //   idle（如 dating22 的 motion1_21 终态与 idle1 差 97，实为第一章终章演出，
  //   接第二章 idle2），由宿主在阶段切换时换渲染骨架。无 animPhase 时行为与
  //   单骨架皮肤完全一致。
  var CROSS_PHASE_DIST = 30;

  function computeMotionTargets(profile, createState) {
    if (!profile.motionTargets) profile.motionTargets = {};
    if (!profile.homeIdle) profile.homeIdle = {};
    var idleNum = function (name) { var m = /^idle(\d+)$/.exec(name); return m ? parseInt(m[1], 10) : 0; };
    var animPhase = profile.animPhase || null;
    var phaseOrder = profile.phases || null;
    function phaseOf(anim) {
      return (animPhase && animPhase[anim]) || '1';
    }
    function nextPhaseIdle(phase) {
      // 跨阶段桥的目标 = 下一阶段（按宿主给的顺序，末阶段回卷首）的实测家 idle
      if (!phaseOrder || !phaseOrder.length) return null;
      var idx = phaseOrder.indexOf(phase);
      if (idx < 0) return null;
      var nxt = phaseOrder[(idx + 1) % phaseOrder.length];
      for (var key in profile.homeIdle) {
        if (phaseOf(profile.homeIdle[key]) === nxt) return profile.homeIdle[key];
      }
      return null;
    }
    function snapshot(skeleton) {
      var m = {};
      for (var i = 0; i < skeleton.slots.length; i++) {
        var s = skeleton.slots[i];
        m[s.data.name] = s.attachment ? s.attachment.name : null;
      }
      return m;
    }
    function diff(a, b) {
      var d = 0;
      for (var k in a) if (a[k] !== b[k]) d++;
      return d;
    }
    function liveIdle(createState, idle, frames) {
      var ctx = createState(idle);
      if (!ctx || !ctx.state || !ctx.skeleton) return null;
      ctx.skeleton.setToSetupPose();
      try { ctx.state.setAnimation(0, idle, true); } catch (e) { return null; }
      for (var i = 0; i < frames; i++) { ctx.state.update(1 / 60); ctx.state.apply(ctx.skeleton); }
      return ctx;
    }
    if (!profile.idles.length) return profile.motionTargets;
    var WARM = 120; // 预热帧数：idle 的附件键基本都在循环前段，1.2s 足够稳定
    // 1) 章节配对实测：每个 mix 池用开场首段找入场跳变最小的家
    //   （首段 t=0.05 的附件差；正确配对时接近 0，错配是几十到几百的大跳变）
    var openFrag = {};
    Object.keys(profile.mixPools).forEach(function (g) {
      var num = parseInt(g.replace('mix', ''), 10);
      var frags = (profile.mixPools[g] || []).map(function (n) {
        var pm = parseMixName(n);
        return pm ? { n: n, step: pm.step, variant: pm.variant, mod: pm.mod, modN: pm.modN } : null;
      }).filter(Boolean).sort(function (a, b) {
        return (a.step - b.step) || ((a.variant > 0 ? 0 : 1) - (b.variant > 0 ? 0 : 1))
          || ((a.variant > 0 ? a.variant : a.modN) - (b.variant > 0 ? b.variant : b.modN)) || (a.mod - b.mod);
      }).slice(0, 1);
      if (frags.length) openFrag[num] = frags;
    });
    Object.keys(openFrag).forEach(function (k) {
      var num = parseInt(k, 10);
      var anim = openFrag[k][0].n;
      var ph = phaseOf(anim);
      var best = null, bestJump = Infinity;
      for (var q = 0; q < profile.idles.length; q++) {
        var idle = profile.idles[q];
        if (phaseOf(idle) !== ph) continue; // 阶段隔离：家 idle 只在骨架同阶段里找
        var ctx = liveIdle(createState, idle, WARM);
        if (!ctx) continue;
        var before = snapshot(ctx.skeleton);
        var jump;
        try {
          var e = ctx.state.setAnimation(0, anim, false);
          e.mixDuration = 0;
          ctx.state.update(0.05);
          ctx.state.apply(ctx.skeleton);
          jump = diff(snapshot(ctx.skeleton), before);
        } catch (err) { continue; } // 该 idle 所在骨架没有此片段：跳过该候选
        if (jump < bestJump) { bestJump = jump; best = idle; }
      }
      if (best) profile.homeIdle[num] = best;
    });
    // 2) motion 终态实测：从源章的【实测家 idle】接播，结束态归最近的 idle
    //   （阶段骨架：只与同阶段 idle 比对；最小差过大 = 跨阶段桥，目标取下一阶段家）
    var idleSnaps = {};
    for (var q3 = 0; q3 < profile.idles.length; q3++) {
      var ctxI = liveIdle(createState, profile.idles[q3], WARM);
      if (ctxI) idleSnaps[profile.idles[q3]] = snapshot(ctxI.skeleton);
    }
    for (var mi = 0; mi < profile.motions.length; mi++) {
      var m = profile.motions[mi];
      var mm = /^motion(\d+)/.exec(m);
      var home = (profile.homeIdle && profile.homeIdle[parseInt(mm[1], 10)]) || null;
      if (!home) {
        for (var q2 = 0; q2 < profile.idles.length; q2++) {
          if (idleNum(profile.idles[q2]) === parseInt(mm[1], 10)) { home = profile.idles[q2]; break; }
        }
      }
      if (!home) home = profile.idles[0];
      var ctx = liveIdle(createState, home, WARM);
      if (!ctx) continue;
      var dur = 2;
      var cur = ctx.state.getCurrent(0);
      if (cur && cur.animation) dur = cur.animation.duration;
      var end;
      try {
        var e2 = ctx.state.setAnimation(0, m, false);
        e2.mixDuration = 0;
        ctx.state.update(dur + 0.05);
        ctx.state.apply(ctx.skeleton);
        end = snapshot(ctx.skeleton);
      } catch (err) { continue; } // 该骨架没有此 motion：跳过
      var best2 = null, bestD = Infinity;
      for (var idle2 in idleSnaps) {
        if (phaseOf(idle2) !== phaseOf(m)) continue; // 阶段隔离：终态只在同阶段里归
        var d = diff(end, idleSnaps[idle2]);
        if (d < bestD || (d === bestD && best2 && idleNum(idle2) < idleNum(best2))) { bestD = d; best2 = idle2; }
      }
      if (best2 && bestD > CROSS_PHASE_DIST && phaseOrder && phaseOrder.length > 1) {
        // 跨阶段桥（如 dating22 motion1_21 终态差 97）：目标 = 下一阶段的实测家 idle
        var bridgeIdle = nextPhaseIdle(phaseOf(m));
        if (bridgeIdle) {
          profile.motionTargets[m] = bridgeIdle;
          profile.motionReturnDist = profile.motionReturnDist || {};
          profile.motionReturnDist[m] = 999;
          continue;
        }
      }
      profile.motionTargets[m] = best2;
      // 结束态到【源章家 idle】的距离：锁章模式下决定该 motion 能否当章内反应
      // （距离大 = 播完拽回家会闪，宁可不进播放列表）
      profile.motionReturnDist = profile.motionReturnDist || {};
      profile.motionReturnDist[m] = home && idleSnaps[home] ? diff(end, idleSnaps[home]) : 0;
    }
    buildChainNext(profile, createState, snapshot, diff, idleSnaps);
    return profile.motionTargets;
  }

  // ===== 段落链式检测（2026-10 dating12「Stranger Bunny」实测）===============
  // 两代章节模型并存： dating14/21/d22 等段落【锚定家 idle】（起点距家 ≈0，
  // 每步播完回家不闪）；dating12 章1、dating11 章1、dating20 章5/7 的段落是
  // 【连续演出】（相邻段终点→起点差 0~8，但段落起点距家 idle 达 100~300）——
  // 对它们按"每步回 idle"播放，每步边界会闪现别的姿态（用户报的
  // "动画不连贯跳出其他位置的动画"）。
  // 判据（对锚定皮肤零影响）：相邻段 end→start 差 ≤ CHAIN_DIST 且【后段不锚定
  // 家 idle】（起点距家 > CHAIN_DIST，插 idle 必闪）→ chainNext[A]=B，宿主播完
  // A 自动续播 B；否则保持点击步进回 idle。章节的跨章桥 motion 在链式章节里
  // 顺接末段（如 dating12 的 motion1_35 终点=idle2 差 0）。hold/loop 停留段是
  // 官方编排的暂停点，不参与链（宿主回 hold 循环等点击）。
  var CHAIN_DIST = 30;

  function buildChainNext(profile, createState, snapshot, diff, idleSnaps) {
    profile.chainNext = {};
    var idleNum = function (name) { var m = /^idle(\d+)$/.exec(name); return m ? parseInt(m[1], 10) : 0; };
    function st(name, t) {
      var ctx = createState(name);
      if (!ctx || !ctx.state || !ctx.skeleton) return null;
      try {
        ctx.skeleton.setToSetupPose();
        var e = ctx.state.setAnimation(0, name, false);
        e.mixDuration = 0;
        ctx.state.update(t);
        ctx.state.apply(ctx.skeleton);
      } catch (err) { return null; }
      return snapshot(ctx.skeleton);
    }
    function endState(name) {
      var ctx = createState(name);
      if (!ctx || !ctx.state || !ctx.skeleton) return null;
      try {
        ctx.skeleton.setToSetupPose();
        var e = ctx.state.setAnimation(0, name, false);
        e.mixDuration = 0;
        var dur = 2;
        try { dur = ctx.state.getCurrent(0).animation.duration; } catch (err2) { return null; }
        ctx.state.update(dur + 0.05);
        ctx.state.apply(ctx.skeleton);
      } catch (err) { return null; }
      return snapshot(ctx.skeleton);
    }
    function parse(n) {
      var m = /^mix(\d+)_(\d+)(?:_(\d+))?(?:_(long|loop|end)(\d*))?$/.exec(n);
      return m ? { chap: parseInt(m[1], 10), step: parseInt(m[2], 10), variant: m[3] ? parseInt(m[3], 10) : 0,
        mod: m[4] ? ({ long: 1, loop: 2, end: 3 })[m[4]] : 0, modN: m[5] ? parseInt(m[5], 10) : 0 } : null;
    }
    var byChap = {};
    var chapKeys = Object.keys(profile.mixPools).map(function (g) {
      var n = parseInt(String(g).replace('mix', ''), 10);
      return Number.isFinite(n) ? n : null;
    }).filter(function (n) { return n != null; });
    for (var i = 0; i < chapKeys.length; i++) {
      var chap = chapKeys[i];
      var list = (profile.mixPools['mix' + chap] || []).map(function (n) {
        var p = parse(n);
        if (!p) return null;
        // loop 停留段是 hold，不参与链（与播放列表构建的 hold 配对一致）
        return p.mod === 2 ? null : { n: n, step: p.step, variant: p.variant, mod: p.mod, modN: p.modN };
      }).filter(Boolean);
      list.sort(function (a, b) {
        return (a.step - b.step) || ((a.variant > 0 ? 0 : 1) - (b.variant > 0 ? 0 : 1))
          || ((a.variant > 0 ? a.variant : a.modN) - (b.variant > 0 ? b.variant : b.modN)) || (a.mod - b.mod);
      });
      byChap[chap] = list;
    }
    for (var c2 = 0; c2 < chapKeys.length; c2++) {
      var chap2 = chapKeys[c2];
      var home = profile.homeIdle[chap2];
      if (!home || !idleSnaps[home]) continue;
      var homeSnap = idleSnaps[home];
      var list2 = byChap[chap2];
      for (var s = 0; s < list2.length - 1; s++) {
        var A = list2[s].n, B = list2[s + 1].n;
        var endA = endState(A), startB = st(B, 0.02);
        if (!endA || !startB) continue;
        if (diff(endA, startB) <= CHAIN_DIST && diff(startB, homeSnap) > CHAIN_DIST) {
          profile.chainNext[A] = B;
        }
      }
      // 链式章节的跨章桥 motion 顺接末段（末段非锚定时；锚定章节保持点击步进）
      var last = list2[list2.length - 1];
      if (!last) continue;
      var lastStart = st(last.n, 0.02);
      if (!lastStart || diff(lastStart, homeSnap) <= CHAIN_DIST) continue;
      for (var mi = 0; mi < profile.motions.length; mi++) {
        var m = profile.motions[mi];
        var mm = /^motion(\d+)/.exec(m);
        if (!mm || parseInt(mm[1], 10) !== chap2) continue;
        var tgt = profile.motionTargets[m];
        if (!tgt) continue;
        var tgtChap = null;
        for (var key in profile.homeIdle) {
          if (profile.homeIdle[key] === tgt) { tgtChap = parseInt(key, 10); break; }
        }
        if (tgtChap != null && tgtChap !== chap2) {
          profile.chainNext[last.n] = m; // 末段播完自动接跨章桥
        }
      }
    }
  }

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
    VERSION: 'v8-20261025', // 便于确认页面加载的引擎版本（调试 HUD 会显示）
    detect: detect,
    computeMotionTargets: computeMotionTargets,
    buildZones: buildZones,
    boxOf: boxOf,
    classify: classify,
    decide: decide,
    advanceAuto: advanceAuto,
    resetMix: resetMix,
    playFull: playFull,
    cueForMood: cueForMood,
    spawnEffect: spawnEffect,
    createOverlay: createOverlay,
    ZONES_DEFS: ZONE_DEFS,
  };
})();

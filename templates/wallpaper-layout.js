/*
 * 壁纸布局统一模块（预览与导出共用，单一事实来源）。
 *
 * 语义约定：
 *  - scale：百分比，100 = 自适应（contain，模型占画布 90%），20~300。
 *  - offsetX / offsetY：画布宽/高的百分比，±100。
 *  - alignX / alignY：0=左/上，0.5=居中，1=右/下（画布坐标系，Y 向下）。
 *
 * 经典脚本（无 import/export），可被导出壁纸 <script> 直接加载；
 * 前端通过副作用 import 读取 window.WallpaperLayout。
 */
(function (root) {
  'use strict'

  var MARGIN = 0.98 // 模型包围盒最多占画布 98%（撑满预览框，参照 azurlane.nagami.moe）
  var ASPECT = 16 / 9 // 画布宽高比（预览 stage 恒为此比例；WE 侧按此推导等效取景框）
  var MIN_SCALE = 20
  var MAX_SCALE = 300
  var MAX_OFFSET = 100
  var ALIGN_ORDER = ['center', 'left-top', 'right-top', 'left-bottom', 'right-bottom']
  var ALIGNMENTS = {
    center: { x: 0.5, y: 0.5 },
    'left-top': { x: 0, y: 0 },
    'right-top': { x: 1, y: 0 },
    'left-bottom': { x: 0, y: 1 },
    'right-bottom': { x: 1, y: 1 },
  }

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v))
  }

  function clampScale(pct) {
    return clamp(pct == null ? 100 : pct, MIN_SCALE, MAX_SCALE)
  }

  function clampOffset(pct) {
    return clamp(pct == null ? 0 : pct, -MAX_OFFSET, MAX_OFFSET)
  }

  /*
   * 角色/背景独立偏移（世界坐标）：与 spineCamera 的偏移语义一致。
   * offsetX/offsetY 为画布宽/高百分比（±100），返回世界坐标偏移量。
   * 尺寸必须与 spineCamera 用同一个 16:9 取景框（见 viewportFrame），
   * 否则 WE 侧偏移量会随显示器宽高比漂移，与预览不一致。
   */
  function charOffsetWorld(offsetX, offsetY, canvasW, canvasH, zoom) {
    var frame = viewportFrame(canvasW, canvasH)
    return {
      x: (clampOffset(offsetX) / 100) * frame.w * zoom,
      y: (clampOffset(offsetY) / 100) * frame.h * zoom,
    }
  }

  /*
   * 人物旋转（度，正 = 屏幕顺时针）：渲染端把旋转并入相机投影（只转人物层，
   * 背景不转）所需的两个纯函数，预览 SpinePreview 与导出模板共用。
   */

  /*
   * 绕世界点 (px,py) 旋转 deg 的 4x4 变换，返回**列主序 16 值数组**
   * （与 spine OrthoCamera.projectionView.values 同布局），渲染端把它右乘进
   * projectionView：PV' = PV × M —— 顶点先经世界旋转再进相机。
   * 世界坐标 y 向上，屏幕顺时针 = 世界数学负角。
   */
  function charRotationMatrixValues(deg, px, py) {
    var t = (-(deg || 0) * Math.PI) / 180
    var c = Math.cos(t)
    var s = Math.sin(t)
    var tx = px - (px * c - py * s)
    var ty = py - (px * s + py * c)
    // col0=(c,s,0,0) col1=(-s,c,0,0) col2=(0,0,1,0) col3=(tx,ty,0,1)
    return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, tx, ty, 0, 1]
  }

  /*
   * bounds 绕 (px,py) 旋转 deg 后的 AABB（四角旋转取包络）。取景框随旋转
   * 外扩，保证任意角度人物完整可见；与 charRotationMatrixValues 同一符号约定。
   */
  function rotateBoundsAabb(bounds, deg, px, py) {
    var d = (deg || 0) % 360
    if (!d || !bounds) return bounds
    var t = (-d * Math.PI) / 180
    var c = Math.cos(t)
    var s = Math.sin(t)
    var xs = [bounds.minX, bounds.maxX]
    var ys = [bounds.minY, bounds.maxY]
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (var i = 0; i < 2; i++) {
      for (var j = 0; j < 2; j++) {
        var dx = xs[i] - px
        var dy = ys[j] - py
        var x = px + dx * c - dy * s
        var y = py + dx * s + dy * c
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
    return { minX: minX, maxX: maxX, minY: minY, maxY: maxY }
  }

  function fitFactor(scalePct) {
    return clampScale(scalePct) / 100
  }

  function anchor(name) {
    var a = ALIGNMENTS[name || 'center']
    return a ? { x: a.x, y: a.y } : { x: 0.5, y: 0.5 }
  }

  /*
   * 取景框尺寸（16:9 单一事实来源）。
   *
   * 预览端画布恒为 16:9（stage 由 fitStage 约束）；Wallpaper Engine 侧画布是
   * 100vw×100vh，宽高比随显示器而变（16:10 / 21:9 …）。而 spineCamera 只按
   * **高度**归一化（fitZoom = h/(canvasH*MARGIN)），偏移量也按画布宽/高的百分比
   * 换算——直接用实际画布尺寸会让同一组 scale/offset 在 WE 上呈现不同的
   * 人物视觉大小与位置（"预览和导出不一致"的根因）。
   *
   * 方案（用户确认「裁切保持构图一致」）：**始终按 16:9 取景框布局，再等比放大
   * 铺满实际画布并裁掉多余部分**（见 coverZoomFactor）。取景框以画布长边为基准：
   *   - 宽屏（21:9）：按高度定框（w = h*16/9），左右裁掉超出的世界；
   *   - 高屏（16:10 / 4:3）：按宽度定框（h = w*9/16），上下裁掉超出的世界；
   *   - 恰好 16:9：返回入参，预览端行为零变化（coverZoomFactor 恒为 1）。
   * 这样人物在屏幕上的**相对大小与位置**与预览完全一致，宽高比差异只体现为裁切。
   */
  function viewportFrame(canvasW, canvasH) {
    var w = Math.max(1, canvasW || 1)
    var h = Math.max(1, canvasH || 1)
    if (Math.abs(w / h - ASPECT) < 1e-3) return { w: w, h: h }
    // 16:9 画布铺满实际画布所需的放大系数（cover）：取两个方向比例的较大者
    var cover = Math.max(w / (h * ASPECT), (h * ASPECT) / w)
    return { w: w / cover, h: h / cover }
  }

  /*
   * 把 16:9 取景框等比放大铺满实际画布的系数（cover 语义）。
   * spineCamera 返回的 zoom 是「取景框像素/世界单位」；要让取景框铺满更大的
   * 实际画布，相机**视野要变大**（zoom 变小），所以 zoom 要除以该系数。
   * 预览端画布本身 16:9，恒返回 1。
   */
  function coverZoomFactor(canvasW, canvasH) {
    var w = Math.max(1, canvasW || 1)
    var h = Math.max(1, canvasH || 1)
    if (Math.abs(w / h - ASPECT) < 1e-3) return 1
    var frame = viewportFrame(w, h)
    return w / frame.w // = h / frame.h（等比，两者相等）
  }

  /*
   * Spine：把模型包围盒放进画布，返回相机参数（world 坐标）。
   * zoom 为“像素/世界单位”，越大看到的区域越大、模型越小，
   * 所以缩放比例作为除数：zoom = fitZoom / scaleFactor。
   *
   * 画布非 16:9 时（WE 全屏）：先按 16:9 取景框算出 zoom，再乘 cover 系数把
   * 取景框等比铺满实际画布（多余部分裁掉）。返回的 zoom 已是**实际画布**的
   * 像素/世界单位，调用方无需再换算；x/y 保持取景框中心语义（铺满后中心不变）。
   */
  function spineCamera(bounds, canvasW, canvasH, opts) {
    opts = opts || {}
    var scale = fitFactor(opts.scale)
    var ox = clampOffset(opts.offsetX)
    var oy = clampOffset(opts.offsetY)
    var ax = opts.alignX != null ? opts.alignX : 0.5
    var ay = opts.alignY != null ? opts.alignY : 0.5
    // 统一按 16:9 取景框布局（见 viewportFrame），保证预览与 WE 构图一致
    var frame = viewportFrame(canvasW, canvasH)
    var cover = coverZoomFactor(canvasW, canvasH)
    canvasW = frame.w
    canvasH = frame.h
    var w = Math.max(1e-3, bounds.maxX - bounds.minX)
    var h = Math.max(1e-3, bounds.maxY - bounds.minY)
    var cx = (bounds.maxX + bounds.minX) / 2
    var cy = (bounds.maxY + bounds.minY) / 2
    // 统一缩放基准：scale=100 时按高度铺满到 MARGIN（所有皮肤高度一致），
    // 宽度自然留白（横场景留宽、竖场景留高）。此前用 max(宽,高) 约束导致
    // 不同皮肤分别按宽/高贴图，scale=100 视觉大小不一致。
    var fitZoom = h / (canvasH * MARGIN)
    // cover：取景框铺满更大的实际画布 → 视野变大（zoom 变小），多余部分裁掉
    var zoom = Math.max(1e-6, fitZoom / scale) / cover
    var slackW = canvasW * zoom - w
    var slackH = canvasH * zoom - h
    return {
      zoom: zoom,
      x: cx + (0.5 - ax) * slackW - ((ox / 100) * canvasW) * zoom,
      y: cy + (ay - 0.5) * slackH + ((oy / 100) * canvasH) * zoom,
    }
  }

  /*
   * Live2D：把模型画布（moc 尺寸）放进画布，返回模型 scale/position（锚点 0.5,0.5）。
   */
  function l2dLayout(modelW, modelH, canvasW, canvasH, opts) {
    opts = opts || {}
    var scale = fitFactor(opts.scale)
    var ox = clampOffset(opts.offsetX)
    var oy = clampOffset(opts.offsetY)
    var ax = opts.alignX != null ? opts.alignX : 0.5
    var ay = opts.alignY != null ? opts.alignY : 0.5
    var fit = Math.min(canvasW / Math.max(1, modelW), canvasH / Math.max(1, modelH)) * MARGIN
    var sx = fit * scale
    return {
      sx: sx,
      x: (modelW * sx) / 2 + ax * (canvasW - modelW * sx) + ((ox / 100) * canvasW),
      y: (modelH * sx) / 2 + ay * (canvasH - modelH * sx) + ((oy / 100) * canvasH),
    }
  }

  /*
   * BD2 Ultimate 演出「阶段背景」选择：动画名 → 背景组号（1..maxSet）。
   * 演出骨架动画结构 chain/cut_A..C/loop/loop_N，每阶段配一组 backN：
   *   - 尾号：loop_2 / loop2 / cut_1 / loop_3 … → 尾部数字即组号；
   *   - 阶段字母可出现在三处（2026-10 实测 12 个演出皮用前缀/小写命名，此前
   *     全部映射组 1 =「切动画背景不会换」）：
   *       前缀  A_cut / B_cut_idle / A_loop      （字母开头 + 下划线）
   *       中缀  cut_A_fire / cut_a_hand          （_X_ 两侧下划线，取最左：
   *             阶段字母在变体后缀之前——cut_a_hand_f 取 a 不取 f）
   *       尾缀  cut_B / cut_a                    （_X 结尾，大小写都认）
   *   - 无号（chain/loop/cut 无尾号的 cut/ all/panties_* 变体）：组 1。
   * 预览 SpinePreview.vue、壁纸模板与 GalleryView 共用，保证三端切背景一致。
   */
  function bgSetForAnim(name, maxSet) {
    if (!name) return 1
    var cap = Math.max(1, maxSet || 1)
    var m
    // 1) 下划线锚定的尾号（旧版语义，cut_A_2/cut_A_3 这类「字母+尾号」并存时
    //    尾号是阶段——老皮肤实测行为，必须最优先保持）
    m = /(?:^|_)(\d+)$/.exec(name)  // loop_2 / cut_1 / cut_A_2
    if (m) return Math.min(parseInt(m[1], 10), cap)
    // 2) 前缀单字母：A_cut / B_cut_idle / C_loop / A_cut_w1（变体尾缀不干扰）
    m = /^([A-Za-z])_/.exec(name)
    if (m) return Math.min(m[1].toUpperCase().charCodeAt(0) - 64, cap)
    // 3) 中缀 _X_（取最左，阶段字母在变体后缀之前）：cut_B_fire / cut_a_hand
    m = /_([A-Za-z])_/.exec(name)
    if (m) return Math.min(m[1].toUpperCase().charCodeAt(0) - 64, cap)
    // 4) 尾缀 _X（大小写都认）：cut_B / cut_a
    m = /_([A-Za-z])$/.exec(name)
    if (m) return Math.min(m[1].toUpperCase().charCodeAt(0) - 64, cap)
    // 5) 紧贴尾号（字母后直接跟数字，前面无规则命中才认）：loop2 / cut_B2
    //    —— 不匹配 w1/v2 等已含字母规则的变体（那些在规则 2/3 已返回）
    m = /([A-Za-z])(\d+)$/.exec(name)
    if (m) return Math.min(parseInt(m[2], 10), cap)
    return 1
  }

  /*
   * Live2D 点击/拖拽互动（预览与导出共用，单一事实来源）。
   *
   * 碧蓝官方 model3.json 不声明 HitAreas，但每个 moc3 都内置官方命中部件
   * TouchHead / TouchSpecial / TouchBody；富互动模型还带 TouchDrag1..N /
   * TouchIdle1..N（对应 touch_dragN / touch_idleN 动作）。setupL2DHitAreas
   * 动态探测并注入 internalModel.settings.hitAreas，之后 model.hitTest() 即生效
   * （无需 fork 库）。
   * 动作播放/恢复由调用方（预览组件或导出运行时）通过回调实现，本模块只做状态机。
   */
  var L2D_DRAG_THRESHOLD = 6 // 位移超过该像素数判定为拖拽而非点击
  var L2D_MAX_NUM_AREAS = 40

  function probeDrawable(core, id) {
    return typeof core.getDrawableIndex === 'function' && core.getDrawableIndex(id) >= 0
  }

  /*
   * 发现并注入 moc3 自带的全部 Touch* 命中部件。
   * 命中区 Name 直接用动作名（touch_body / touch_drag11 / touch_idle16 …），
   * 这样 hitTest() 返回的就是可直接播放的动作名。
   * 返回注入的 {Id: 动作名} 映射；无任何命中部件返回 null。
   */
  function setupL2DHitAreas(model) {
    var im = model && model.internalModel
    if (!im || !im.settings || !im.coreModel) return null
    var core = im.coreModel
    var found = {}
    var fixed = {
      TouchBody: 'touch_body',
      TouchHead: 'touch_head',
      TouchSpecial: 'touch_special',
    }
    var id
    for (id in fixed) if (probeDrawable(core, id)) found[id] = fixed[id]
    var miss = 0
    for (var i = 1; i <= L2D_MAX_NUM_AREAS; i++) {
      id = 'TouchDrag' + i
      if (probeDrawable(core, id)) { found[id] = 'touch_drag' + i; miss = 0 }
      else if (++miss >= 3) break
    }
    miss = 0
    for (var j = 1; j <= L2D_MAX_NUM_AREAS; j++) {
      id = 'TouchIdle' + j
      if (probeDrawable(core, id)) { found[id] = 'touch_idle' + j; miss = 0 }
      else if (++miss >= 3) break
    }
    var defs = []
    for (id in found) defs.push({ Name: found[id], Id: id })
    if (!defs.length) return null
    im.settings.hitAreas = defs
    if (typeof im.setupHitAreas === 'function') im.setupHitAreas()
    return found
  }

  // 命中优先级：头 > 特殊 > 具体部位(拖拽/待机) > 身体兜底（TouchBody 包围盒通常覆盖全身）
  function hitPriority(label) {
    if (/^touch_head/i.test(label)) return 5
    if (/^touch_special/i.test(label)) return 4
    if (/^touch_drag/i.test(label)) return 3
    if (/^touch_idle/i.test(label)) return 2
    if (/^touch_body/i.test(label)) return 1
    return 0
  }

  function hitLabelAt(model, pt) {
    var names = []
    try { names = model.hitTest(pt.x, pt.y) || [] } catch (e) { names = [] }
    var best = null
    var bestP = -1
    for (var i = 0; i < names.length; i++) {
      var p = hitPriority(names[i])
      if (p > bestP) { bestP = p; best = names[i] }
    }
    return best
  }

  /*
   * l2dInteraction(model, el, opts) → { setEnabled(bool), hitAreas(), destroy() }
   *  opts:
   *    play(label, fromDrag) 播放动作；fromDrag=true 表示拖拽触发（调用方不要记为“当前动作”）
   *    dragLabels()          可用拖拽动作 label 列表（无则 []）
   *    revert()              拖拽结束恢复拖拽前的动作
   * 约定：按下起点必须在模型包围盒内；点按播放按下部位的 touch_*，
   * 拖拽优先播放该部位的 touch_dragN，没有则随机 touch_drag*。
   */
  function l2dInteraction(model, el, opts) {
    opts = opts || {}
    var enabled = false
    var down = null
    // 防御性：确保命中区已注入（导出模板可能已显式调用，重复注入无害）
    setupL2DHitAreas(model)

    function clientPoint(e) {
      var r = el.getBoundingClientRect()
      return { x: e.clientX - r.left, y: e.clientY - r.top }
    }

    function inModelBox(pt) {
      try {
        var b = model.getBounds()
        return b.x <= pt.x && pt.x <= b.x + b.width && b.y <= pt.y && pt.y <= b.y + b.height
      } catch (e) { return false }
    }

    function onPointerDown(e) {
      if (!enabled) return
      if (e.button != null && e.button !== 0) return
      var pt = clientPoint(e)
      // 不再要求按下起点必须在模型包围盒内：互动模式下任何按下都武装拖拽，
      // 避免按在角色边缘/模型框外时拖了没反应；点击仍按命中区判定（背景点击无反应）。
      down = { x: pt.x, y: pt.y, label: hitLabelAt(model, pt), dragged: false }
    }

    function onPointerMove(e) {
      if (!enabled || !down) return
      var pt = clientPoint(e)
      var dx = pt.x - down.x
      var dy = pt.y - down.y
      // 仍标记“已拖动”防止松手被当作点按；但 dragEnabled=false（导出壁纸只保留
      // 摸头/摸身体/特殊三部位点按）时拖拽不触发任何 drag 动画
      if (!down.dragged && Math.sqrt(dx * dx + dy * dy) > L2D_DRAG_THRESHOLD) {
        down.dragged = true
        if (opts.dragEnabled === false) return
        var label = null
        if (down.label && /^touch_drag/i.test(down.label)) label = down.label
        if (!label) {
          var labels = (opts.dragLabels && opts.dragLabels()) || []
          if (labels.length) label = labels[Math.floor(Math.random() * labels.length)]
        }
        if (label && opts.play) opts.play(label, true)
      }
    }

    // 点按互动只保留三个固定部位：摸头 / 摸身体 / 特殊。
    // 命中 touch_idleN（待机区）或 touch_dragN 时点按不播动作（待机点击不再互动）；
    // 拖拽（onPointerMove 超过阈值）仍走 touch_dragN，不在此过滤范围内。
    function isTapLabel(label) {
      return /^touch_(head|body|special)$/i.test(label || '')
    }

    function onPointerUp(e) {
      if (!enabled || !down) return
      var d = down
      down = null
      if (d.dragged) {
        // 松手后保持拖拽动画继续播放（不自动恢复），由下一次点击/拖动切换
        return
      }
      // 点击待机区（touch_idleN）不互动；只播三个固定部位的触摸动作
      if (d.label && isTapLabel(d.label) && opts.play) opts.play(d.label, false)
    }

    function onPointerCancel() {
      if (!enabled || !down) return
      down = null
    }

    el.addEventListener('pointerdown', onPointerDown)
    el.addEventListener('pointermove', onPointerMove)
    el.addEventListener('pointerup', onPointerUp)
    el.addEventListener('pointercancel', onPointerCancel)

    return {
      setEnabled: function (v) { enabled = !!v },
      hitAreas: function () {
        var im = model && model.internalModel
        return (im && im.hitAreas) ? Object.keys(im.hitAreas) : []
      },
      destroy: function () {
        el.removeEventListener('pointerdown', onPointerDown)
        el.removeEventListener('pointermove', onPointerMove)
        el.removeEventListener('pointerup', onPointerUp)
        el.removeEventListener('pointercancel', onPointerCancel)
      },
    }
  }

  /*
   * l2dHitAreaRects(model) → [{ label, kind, rect:{x,y,w,h} }]（画布坐标系，供命中区叠加显示）。
   * 命中区包围盒来自 drawable 顶点（模型空间），经模型世界变换换算到屏幕坐标。
   */
  function l2dHitAreaRects(model) {
    var im = model && model.internalModel
    if (!im || !im.hitAreas) return []
    var out = []
    var names = Object.keys(im.hitAreas)
    for (var i = 0; i < names.length; i++) {
      var def = im.hitAreas[names[i]]
      var b = null
      try { b = im.getDrawableBounds(def.index, {}) } catch (e) { b = null }
      if (!b || !isFinite(b.x) || !isFinite(b.y)) continue
      var corners = [
        model.toGlobal({ x: b.x, y: b.y }),
        model.toGlobal({ x: b.x + b.width, y: b.y }),
        model.toGlobal({ x: b.x, y: b.y + b.height }),
        model.toGlobal({ x: b.x + b.width, y: b.y + b.height }),
      ]
      var minX = Math.min(corners[0].x, corners[1].x, corners[2].x, corners[3].x)
      var maxX = Math.max(corners[0].x, corners[1].x, corners[2].x, corners[3].x)
      var minY = Math.min(corners[0].y, corners[1].y, corners[2].y, corners[3].y)
      var maxY = Math.max(corners[0].y, corners[1].y, corners[2].y, corners[3].y)
      if (maxX - minX < 1 || maxY - minY < 1) continue
      var label = names[i].replace(/^touch_/, '')
      var kind = /^drag/i.test(label) ? 'drag' : (/^idle/i.test(label) ? 'idle' : label)
      out.push({ label: label, kind: kind, rect: { x: minX, y: minY, w: maxX - minX, h: maxY - minY } })
    }
    return out
  }

  root.WallpaperLayout = {
    MARGIN: MARGIN,
    ASPECT: ASPECT,
    MIN_SCALE: MIN_SCALE,
    MAX_SCALE: MAX_SCALE,
    MAX_OFFSET: MAX_OFFSET,
    ALIGN_ORDER: ALIGN_ORDER,
    ALIGNMENTS: ALIGNMENTS,
    viewportFrame: viewportFrame,
    coverZoomFactor: coverZoomFactor,
    clampScale: clampScale,
    clampOffset: clampOffset,
    fitFactor: fitFactor,
    anchor: anchor,
    charOffsetWorld: charOffsetWorld,
    spineCamera: spineCamera,
    charRotationMatrixValues: charRotationMatrixValues,
    rotateBoundsAabb: rotateBoundsAabb,
    bgSetForAnim: bgSetForAnim,
    l2dLayout: l2dLayout,
    setupL2DHitAreas: setupL2DHitAreas,
    l2dInteraction: l2dInteraction,
    l2dHitAreaRects: l2dHitAreaRects,
  }
})(typeof window !== 'undefined' ? window : this)

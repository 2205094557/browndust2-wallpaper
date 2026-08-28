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

  function fitFactor(scalePct) {
    return clampScale(scalePct) / 100
  }

  function anchor(name) {
    var a = ALIGNMENTS[name || 'center']
    return a ? { x: a.x, y: a.y } : { x: 0.5, y: 0.5 }
  }

  /*
   * Spine：把模型包围盒放进画布，返回相机参数（world 坐标）。
   * zoom 为“像素/世界单位”，越大看到的区域越大、模型越小，
   * 所以缩放比例作为除数：zoom = fitZoom / scaleFactor。
   */
  function spineCamera(bounds, canvasW, canvasH, opts) {
    opts = opts || {}
    var scale = fitFactor(opts.scale)
    var ox = clampOffset(opts.offsetX)
    var oy = clampOffset(opts.offsetY)
    var ax = opts.alignX != null ? opts.alignX : 0.5
    var ay = opts.alignY != null ? opts.alignY : 0.5
    var w = Math.max(1e-3, bounds.maxX - bounds.minX)
    var h = Math.max(1e-3, bounds.maxY - bounds.minY)
    var cx = (bounds.maxX + bounds.minX) / 2
    var cy = (bounds.maxY + bounds.minY) / 2
    // 统一缩放基准：scale=100 时按高度铺满到 MARGIN（所有皮肤高度一致），
    // 宽度自然留白（横场景留宽、竖场景留高）。此前用 max(宽,高) 约束导致
    // 不同皮肤分别按宽/高贴满，scale=100 视觉大小不一致。
    var fitZoom = h / (canvasH * MARGIN)
    var zoom = Math.max(1e-6, fitZoom / scale)
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
    MIN_SCALE: MIN_SCALE,
    MAX_SCALE: MAX_SCALE,
    MAX_OFFSET: MAX_OFFSET,
    ALIGN_ORDER: ALIGN_ORDER,
    ALIGNMENTS: ALIGNMENTS,
    clampScale: clampScale,
    clampOffset: clampOffset,
    fitFactor: fitFactor,
    anchor: anchor,
    spineCamera: spineCamera,
    l2dLayout: l2dLayout,
    setupL2DHitAreas: setupL2DHitAreas,
    l2dInteraction: l2dInteraction,
    l2dHitAreaRects: l2dHitAreaRects,
  }
})(typeof window !== 'undefined' ? window : this)

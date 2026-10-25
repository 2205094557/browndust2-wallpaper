<template>
  <div ref="wrapRef" class="spine-wrap">
    <canvas ref="canvasRef" class="spine-canvas"></canvas>
    <!-- 诊断心跳：每帧更新时间/动画/暂停状态。定格时看它还在不在跳：在跳=渲染输出停；不跳=rAF 停 -->
    <div class="spine-dbg" :class="{ hidden: !debugOn }">{{ dbgText }}</div>
    <!-- 交互区域：复刻 L2D 显示——开启「显示交互区域」即显示全部 hitAreas 区域框，
         不依赖互动模式（与 L2D l2dHitAreaRects 行为一致）。区域世界框来自参考数据集。 -->
    <template v-if="showHitAreas && hitAreas.length">
      <div
        v-for="a in hitAreas"
        :key="a.label"
        class="spine-hit-overlay"
        :style="a.style"
      >{{ a.label }}</div>
    </template>
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { assetUrl, bridge } from '../bridge'
import { voiceEnabled } from '../utils/voice'
import '../../../templates/wallpaper-layout.js'
import '../../../templates/shared/bd2-interact.js' // BD2 互动引擎（与壁纸模板同一份）

const WL = window.WallpaperLayout

// ===== BD2 贴图 alpha 上传开关（与导出模板 templates/wallpaper_spine.html 一致，铁律 5）=====
// true = BD2 贴图是直通 alpha（RGB 未乘 A），texImage2D 时由浏览器预乘；
// drawSkeleton(..., true) 按预乘混合（ONE / ONE_MINUS_SRC_ALPHA）。
// 实测依据：false 时深色背景正常、浅色背景整体洗白发亮（2026-08-26 端到端截图）。
const BD2_PREMULTIPLY_UPLOAD = true

const props = defineProps({
  skin: { type: Object, required: true },
  animation: { type: String, default: '' },
  scale: { type: Number, default: 100 },
  // 背景图独立缩放（%）：100 = 默认（cover 铺满取景框）；>100 放大背景、<100 缩小。
  // 与角色缩放 scale 相互独立，可单独调节背景大小。
  bgScale: { type: Number, default: 100 },
  offsetX: { type: Number, default: 0 },
  offsetY: { type: Number, default: 0 },
  // 角色独立位置偏移（与整体偏移 offsetX/offsetY 区分）：只移动角色骨架，
  // 背景（背景图/背景层/CSS 背景）保持不动。单位同整体偏移：画布宽/高百分比 ±100。
  charOffsetX: { type: Number, default: 0 },
  charOffsetY: { type: Number, default: 0 },
  // 背景图独立位移（%）：只移动背景图，角色不动。与 bgScale 配套（背景缩放/位置独立调节）。
  bgOffsetX: { type: Number, default: 0 },
  bgOffsetY: { type: Number, default: 0 },
  // 人物旋转（度，正=屏幕顺时针）：只旋转人物层，背景/背景层不动；绕人物自身
  // 中心（含人物偏移后的位置）旋转。渲染端把旋转并入投影矩阵（clearRenderFrame
  // 两段式），取景框按旋转后 AABB 外扩保证任意角度完整可见。导出模板同步
  // （CHAR_ROTATION，见 wallpaper_spine.html / export_defaults）。
  rotation: { type: Number, default: 0 },
  // 版式拖拽调节目标：'stage'=整体平移（默认，拖动平移画面）；'char'=只调节人物；
  // 'bg'=只调节背景。选中人物/背景时，拖动移动所选目标、滚轮缩放所选目标，
  // 且点击不再触发皮肤互动（只调节当前选择）。
  adjustTarget: { type: String, default: 'stage' },
  alignment: { type: String, default: 'center' },
  // 互动模式：false=拖拽（平移画面）；true=互动（拖拽触发 drag 动画）
  interactionMode: { type: Boolean, default: false },
  // 鼠标追踪：角色眼睛/头部跟随鼠标（同 L2D 开关；spine 用 drag 相关骨骼响应）
  // 显示交互区域：互动皮肤在互动模式下画角色可拖拽提示框
  showHitAreas: { type: Boolean, default: false },
  // 开场动画：开启时互动皮肤先播 login 入场一次再回待机；关闭直接待机
  intro: { type: Boolean, default: true },
  // 隐藏骨架内置默认背景（当外部已选用自定义扩图/场景背景/纯色等样式时，避免重叠出现两个背景）
  hideDefaultBg: { type: Boolean, default: false },
})
const emit = defineEmits(['ready', 'error', 'animations', 'scaleChange', 'panChange', 'subtitle', 'bgScaleChange', 'charOffsetChange', 'bgOffsetChange'])

const wrapRef = ref(null)
const hitAreas = ref([]) // [{label, style, kind}] 部位提示框（head/body/drag）
const dbgText = ref('')
// 诊断心跳默认开启（软件无 F12 devtools，定格问题需要直观看到帧计数是否在跳）
const debugOn = ref(true)

const canvasRef = ref(null)

let gl = null
let renderer = null
let layers = []
let raf = 0
let lastFrame = 0
let disposed = false
let paused = false // keep-alive 切走（onDeactivated）时暂停渲染循环
let boundsCache = null
// 人物层并集包围盒中心（旋转支点的基础值，随 boundsCache 同生命周期失效）。
// 旋转是渲染期投影变换、不改骨骼世界坐标，所以旋转角度变化无需重建此缓存。
let charCenterCache = null

function computeCharCenter() {
  const per = layers
    .filter((l) => l.skeleton && !isBgLayer(l) && isActiveSkel(l))
    .map(layerBounds)
    .filter((b) => Number.isFinite(b.minX))
  if (!per.length) return null
  return {
    x: (Math.min(...per.map((b) => b.minX)) + Math.max(...per.map((b) => b.maxX))) / 2,
    y: (Math.min(...per.map((b) => b.minY)) + Math.max(...per.map((b) => b.maxY))) / 2,
  }
}

// 旋转支点 = 人物基础中心 + 人物独立偏移（%取景框 × zoom 的世界位移）——
// 偏移后再"原地"旋转，而不是绕取景中心打转
function charPivot() {
  const base = charCenterCache
  if (base) {
    const cv = canvasRef.value
    const _off = WL.charOffsetWorld(
      props.charOffsetX, props.charOffsetY,
      (cv && cv.clientWidth) || 0, (cv && cv.clientHeight) || 0,
      (renderer && renderer.camera.zoom) || 1,
    )
    return { x: base.x + _off.x, y: base.y + _off.y }
  }
  const b = boundsCache || { minX: -1, maxX: 1, minY: -1, maxY: 1 }
  return { x: (b.minX + b.maxX) / 2, y: (b.minY + b.maxY) / 2 }
}
let drag = null
// 远程交互区域数据（nagami 数据集 models/{asset}.json 的 hitAreas，游戏 prefab 提取）
let remoteHitAreas = []
// ---- Spine 互动状态机 ----
// 官方逻辑：normal 循环 →(拖身体)→ drag →(播完)→ ex 循环 →(ex 中再拖)→
// drag_ex →(播完)→ normal 循环。drag/drag_ex 是单次拖拽反应，ex 是互动后的展示。
let interactState = 'normal'
let _dragSeq = 0 // drag 变体序号（dragN → exN 对应） // 'normal' | 'drag' | 'ex' | 'drag_ex'
let interactTimer = 0
let voiceShipId = null
let voicePick = null // { touch_head/touch_body/touch_special/login/home: cue }
let voiceWords = {}
// ---- Ultimate 演出多阶段背景（asset.bg_sets）：按当前动画切背景组 ----
let bgSetImgs = null       // [{set, img}] 升序；null = 无多背景（走旧路径）
let bgSetReady = false
function curAnimName() {
  const l0 = layers.find((l) => l.skeleton && l.state)
  if (!l0) return ''
  const e = l0.state.getCurrent(0)
  return e && e.animation ? e.animation.name : ''
}
async function initBgSets() {
  const asset = props.skin && props.skin.asset
  const sets = (asset && asset.bg_sets) || {}
  const keys = Object.keys(sets)
  if (!keys.length) { bgSetReady = true; return }
  const base = assetUrl(asset.dir)
  try {
    const arr = await Promise.all(keys.map(async (k) => {
      const img = await new Promise((resolve, reject) => {
        const im = new Image()
        im.onload = () => resolve(im)
        im.onerror = () => reject(new Error(`bgset load fail ${sets[k]}`))
        im.src = `${base}/${sets[k]}`
      })
      return { set: parseInt(k, 10) || 0, img }
    }))
    if (disposed) return
    bgSetImgs = arr.sort((a, b) => a.set - b.set)
  } catch (e) {
    console.warn('[spine-render] bg_sets 加载失败:', e.message || e)
  }
  bgSetReady = true
}
function activeBgSetImg() {
  if (!bgSetReady || !bgSetImgs || !bgSetImgs.length) return null
  const maxSet = bgSetImgs[bgSetImgs.length - 1].set
  const want = WL.bgSetForAnim(curAnimName(), maxSet)
  return bgSetImgs.find((b) => b.set === want)?.img || bgSetImgs[0].img
}
// ---- BD2 拟官方互动（单源引擎 window.BD2Interact，与壁纸模板同一份文件） ----
let bd2Profile = null      // detect(动画名) 结果缓存（随皮肤加载重建）
let bd2FullPlaying = false // mix/motion 整段演出播放中（complete 回待机）
let bd2IdleAfter = ''      // 演出结束回退的待机动画名
let bd2ChainNext = null    // 链式续播目标（演出实测 chainNext；null=播完回待机）
// 多章约会皮阶段骨架（asset.skel_sets，2026-10 dating22 起）：每章场景是独立
// 骨架，全部预载但只渲染当前阶段；引擎按章节行走规则跨阶段推进，切幕由
// syncActivePhase 完成（换渲染骨架 + 按新场景重新取景）。
let skelPhaseOfLayer = new Map() // layer -> 阶段键
let animPhaseMap = {}            // 动画名 -> 阶段键
let phaseOrder = []              // 有序阶段键（['1','2']）
let activePhase = ''             // 当前渲染的阶段

function isActiveSkel(l) {
  return !skelPhaseOfLayer.size || !skelPhaseOfLayer.has(l) || skelPhaseOfLayer.get(l) === activePhase
}

function buildPhaseMaps() {
  skelPhaseOfLayer = new Map()
  animPhaseMap = {}
  phaseOrder = []
  activePhase = ''
  const sets = props.skin && props.skin.asset && props.skin.asset.skel_sets
  if (!sets) return
  phaseOrder = Object.keys(sets).sort((a, b) => Number(a) - Number(b))
  // 归一化去 .skel 后缀再比对：skel_sets 值是文件名（带 .skel），层名两种宿主
  // 不一致（预览带 .skel / 壁纸不带）——不归一化会全部漏配，引擎退回单骨架
  // 模式，跨章探测就会 "Animation not found"
  const norm = (s) => String(s || '').replace(/\.skel$/i, '')
  for (const l of layers) {
    if (!l.skeleton) continue
    const stem = norm(l.name)
    const ph = phaseOrder.find((k) => norm(sets[k]) === stem)
    if (!ph) continue
    skelPhaseOfLayer.set(l, ph)
    for (const a of l.data.animations) animPhaseMap[a.name] = ph
  }
  activePhase = phaseOrder[0] || ''
}

function skelLayerOfAnim(name) {
  return layers.find((l) => l.skeleton && l.data.animations.some((a) => a.name === name)) || null
}

// 统一的整段播放入口：跨阶段动画（别的章节骨架）开始时同步换幕
function playFullPhase(name, loop, opts) {
  const ok = window.BD2Interact.playFull(layers, name, loop, undefined, opts)
  if (ok) syncActivePhase(name)
  return ok
}

function syncActivePhase(animName) {
  if (!phaseOrder.length || !animName) return
  const ph = animPhaseMap[animName]
  if (!ph || ph === activePhase) return
  activePhase = ph
  boundsCache = charCenterCache = null // 新场景重新取景（旧边界是上一阶段的）
  applyCharacterFit()
  computeBounds()
}

// 阶段感知的合并 profile：全部骨架动画名取并集（阶段间动画名天然不重），
// animPhase/phases 注入后引擎按阶段隔离探测、跨阶段桥接
function ensureBd2Profile() {
  if (bd2Profile) return bd2Profile
  const l0 = layers.find((l) => l.skeleton)
  if (!l0 || !window.BD2Interact) return null
  const merged = []
  const animSeen = new Set()
  for (const l of layers) {
    if (!l.skeleton) continue
    for (const a of l.data.animations) {
      if (!animSeen.has(a.name)) { animSeen.add(a.name); merged.push(a.name) }
    }
  }
  bd2Profile = window.BD2Interact.detect(merged)
  if (skelPhaseOfLayer.size) {
    bd2Profile.animPhase = animPhaseMap
    bd2Profile.phases = phaseOrder.slice()
  }
  if (bd2Profile.style === 'mix' && l0.state) {
    window.BD2Interact.computeMotionTargets(bd2Profile, (anim) => {
      const owner = skelLayerOfAnim(anim) || l0
      const st = new owner.state.constructor(owner.state.data)
      const sk = new owner.skeleton.constructor(owner.skeleton.data)
      return { state: st, skeleton: sk }
    })
  }
  return bd2Profile
}
let bd2MotionCdUntil = 0   // 整身动作冷却
let bd2VoiceAt = 0         // 语音节流
let voiceCues = []         // 已解码 cue 名数组（mood 引擎按区域情绪过滤）
const subtitleText = ref('')
watch(subtitleText, (t) => emit('subtitle', t))
// 语音关闭时清字幕
watch(voiceEnabled, (on) => { if (!on) subtitleText.value = '' })
// 互动 cue → 语音基础名映射
const VOICE_BASE = { touch_head: 'touch_head', touch_body: 'touch_1', touch_special: 'touch_2', login: 'login', home: 'home' }
const VOICE_FALLBACK = {
  touch_head: ['touch_head', 'touch_1', 'touch_2'],
  touch_body: ['touch_1', 'touch_2', 'touch_head'],
  touch_special: ['touch_2', 'touch_1', 'touch_head'],
  login: ['login'],
  home: ['home'],
}
const WORDS_KEY = { touch_head: 'headtouch', touch_1: 'touch', touch_2: 'touch2', login: 'login', home: 'home' }
const WORDS_FALLBACK = {
  headtouch: ['headtouch', 'touch', 'touch2'],
  touch: ['touch', 'touch2', 'headtouch'],
  touch2: ['touch2', 'touch', 'headtouch'],
  login: ['login'],
  home: ['home'],
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v))
}

function parseAtlasPages(text) {
  return [...text.matchAll(/^([^\r\n]+\.png)\s*$/gm)].map((m) => m[1])
}

async function loadLayer(cfg) {
  const base = assetUrl(props.skin.asset.dir)
  const atlasText = await (await fetch(`${base}/${cfg.atlas}`)).text()
  const pages = parseAtlasPages(atlasText)
  const images = {}
  await Promise.all(
    pages.map((p) => {
      return new Promise((resolve, reject) => {
        const img = new Image()
        img.onload = () => {
          images[p] = img
          resolve()
        }
        img.onerror = () => reject(new Error(`texture load failed: ${p}`))
        img.src = `${base}/${p}`
      })
    }),
  )
  const texMap = {}
  // BD2 贴图按 BD2_PREMULTIPLY_UPLOAD 上传（默认 false = 预乘 alpha 原样上传，见开关注释）。
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, BD2_PREMULTIPLY_UPLOAD)
  for (const p of pages) texMap[p] = new spine.GLTexture(gl, images[p])

  // Spine 4.1：TextureAtlas 构造器不再接收 pageLoader；解析后逐页绑定 GLTexture
  //（page.name = atlas 声明的贴图文件名；setTexture 自动应用页头 filter/repeat）。
  const atlas = new spine.TextureAtlas(atlasText)
  atlas.pages.forEach((page) => page.setTexture(texMap[page.name] || null))
  const loader = new spine.AtlasAttachmentLoader(atlas)
  const skelBuf = await (await fetch(`${base}/${cfg.skel}`)).arrayBuffer()
  const data = new spine.SkeletonBinary(loader).readSkeletonData(new Uint8Array(skelBuf))
  const skeleton = new spine.Skeleton(data)
  // 选 skin：优先 default，但有些碧蓝皮肤的 default skin 是简略版（如
  // 阿罗芒什·足尖弓矢 default 只有脚部，skin "1"/"2" 才是完整全身）。
  // 比较各 skin 的附件数量，选可见部件最多的，保证预览显示完整角色。
  skeleton.setSkin(bestSkin(data))
  skeleton.setSlotsToSetupPose()
  skeleton.updateWorldTransform()
  const state = new spine.AnimationState(new spine.AnimationStateData(data))
  return { skeleton, state, data, name: cfg.skel }
}

// 选附件最多的 skin：默认优先，同数时保持 default；遍历计数（不含透明插槽与位置标记）
function bestSkin(data) {
  const skins = data.skins || []
  if (skins.length <= 1) return data.defaultSkin || skins[0]
  let best = data.defaultSkin || skins[0]
  let bestCount = -1
  for (const sk of skins) {
    let count = 0
    const skel = new spine.Skeleton(data)
    skel.setSkin(sk)
    skel.setSlotsToSetupPose()
    skel.updateWorldTransform()
    for (const slot of skel.slots) {
      const att = slot.getAttachment()
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      count++
    }
    if (count > bestCount) {
      bestCount = count
      best = sk
    }
  }
  return best
}

// 独立背景图层（*BG.png，无骨架）：加载为 Image，渲染时铺在角色层下面
async function loadBg(cfg) {
  const base = assetUrl(props.skin.asset.dir)
  const img = await new Promise((resolve, reject) => {
    const im = new Image()
    im.onload = () => resolve(im)
    im.onerror = () => reject(new Error(`bg load failed: ${cfg.bg}`))
    im.src = `${base}/${cfg.bg}`
  })
  return { bg: img, bgName: cfg.bg }
}

function pickAnim(data) {
  const names = data.animations.map((a) => a.name)
  // 与壁纸模板同步：优先角色常驻的循环/待机（loop_N/idle/normal），跳过转场
  // （chain/cut_*/login 等 t=0 人物不在构图，取其取景会框错——Ultimate 演出皮
  //  默认选到 chain 会导致导出后只见背景不见人物，已实测）
  const loop = names.find((n) => /^loop/i.test(n))
  const idle = names.find((n) => /idle/i.test(n)) || names.find((n) => n === 'normal')
  return loop || idle || names[0] || ''
}

// 表情类动画判定：碧蓝 spine 的数字动画（1/2/3...）是"表情集"——只含 1 帧
// AttachmentTimeline（duration=0），在 t=0 切换眼睛/嘴等附件，不是循环动作。
// 它们必须叠加到独立 track（track 1）上，与 track 0 的 normal 动作同时生效；
// 若用 setAnimation(0,...) 替换 track 0 的 normal，骨架会回到无动作状态变静态。
function isExpression(name, data) {
  const a = data && data.animations && data.animations.find((x) => x.name === name)
  return !!(a && a.duration <= 0)
}

function playAnimation(name) {
  if (!layers.length) return
  syncActivePhase(name) // 指定了别的阶段骨架的动画时换幕
  for (const l of layers) {
    if (!l.skeleton) continue
    if (!name) {
      // 无指定动画：播放默认（idle/normal）动作
      const t = pickAnim(l.data)
      if (t) l.state.setAnimation(0, t, true)
      continue
    }
    if (!l.data.animations.some((a) => a.name === name)) {
      // 当前层没有该动画：回退默认动作
      const t = pickAnim(l.data)
      if (t) l.state.setAnimation(0, t, true)
      continue
    }
    if (isExpression(name, l.data)) {
      // 表情：叠加到 track 1，不覆盖 track 0 的动作；播放一次即可（只切附件）。
      // 关键：若 track 0 当前无动作（如导出的初始动画本身就是表情），
      // 必须先播默认动作到 track 0，否则表情叠加在空 track 上 = 静态。
      const cur = l.state.getCurrent(0)
      if (!cur) {
        const def = pickAnim(l.data)
        if (def) l.state.setAnimation(0, def, true)
      }
      l.state.setAnimation(1, name, false)
    } else {
      // 常规动作：替换 track 0，循环播放；同时清掉 track 1 的表情残留
      l.state.clearTrack(1)
      l.state.setAnimation(0, name, true)
    }
  }
}

// ============ Spine 互动（drag/touch 两类互动皮肤） ============

function animNames() {
  // 所有骨架层动画名并集（单骨架皮肤与原来一致；阶段骨架皮肤覆盖全部章节）
  const names = []
  const seen = new Set()
  for (const l of layers) {
    if (!l.skeleton) continue
    for (const a of l.data.animations) {
      if (!seen.has(a.name)) { seen.add(a.name); names.push(a.name) }
    }
  }
  return names
}
function hasAnim(name) {
  const names = animNames()
  return !!name && names.includes(name)
}

// 互动皮肤两类：
// 1) drag 系：有 drag/ex 动画（拖拽反应状态机 drag → ex → drag_ex → normal）
// 2) touch 系：有 login/touch_body/touch_head/touch_special 等动画
//   （开场 login 撥一次回 normal；点击部位播对应 touch 动画一次回 normal，
//    如 腓特烈大帝·携心夜烛 feiteliedadi_5）
const TOUCH_ANIMS = ['touch_body', 'touch_head', 'touch_special']
// 动画名是否匹配前缀（drag → drag1/drag2/drag3；ex → ex1s/ex2f）
function hasPrefixAnim(n, prefix) {
  return n.some((a) => a === prefix || a.startsWith(prefix))
}
function isInteractiveSkin() {
  const n = animNames()
  if (hasPrefixAnim(n, 'drag') && hasPrefixAnim(n, 'ex')) return true
  if (TOUCH_ANIMS.some((t) => n.includes(t)) || n.includes('login')) return true
  // 远程数据集有该皮肤的 hitAreas 也视为互动皮肤（如 kaiersheng_2 等纯表情+hit 皮肤）
  return remoteHitAreas.length > 0
}

// 当前皮肤是哪类互动：'drag' | 'touch' | ''
function interactKind() {
  const n = animNames()
  if (hasPrefixAnim(n, 'drag') && hasPrefixAnim(n, 'ex')) return 'drag'
  if (TOUCH_ANIMS.some((t) => n.includes(t))) return 'touch'
  if (n.includes('login')) return 'touch'
  return ''
}

// 提取 drag 变体序号：drag1→1、drag2→2；ex1s→1、ex2f→2；drag_ex1→1
function variantSeqOf(name) {
  const m = /^(?:drag_ex|drag|ex)(\d+)/.exec(name || '')
  return m ? parseInt(m[1], 10) : 0
}

// 播放互动状态机动画（track 0 替换；表情不参与）。
// 前缀枚举所有变体并随机选一个（官方 action/change_idle 是数组语义）；
// 同时记住序号，保证 dragN 播完 → 对应序号的 exN（足尖弓矢 drag1→ex1s 等）。
function playInteractAnim(name, loop) {
  const first = layers.find((l) => l.skeleton)
  if (!first) return
  let list = []
  if (first.data.animations.some((a) => a.name === name)) list = [name]
  else list = first.data.animations.filter((a) => a.name.startsWith(name) && !a.name.startsWith(name + '_')).map((a) => a.name)
  // 非 drag 场景忽略序号逻辑（touch 系/普通动画无后缀对应需求）
  if (list.length === 1 && list[0] === name) list = [name]
  if (!list.length) return
  let target = list[Math.floor(Math.random() * list.length)]
  if (/^drag/.test(name) && !/^drag_ex/.test(name)) {
    _dragSeq = variantSeqOf(target) // 记 drag 序号（ex 将用同序号）
  }
  // ex 名称带序号偏好：若拖拽已定 dragN，ex 阶段优先播同序号 exN（有才用）
  if (/^ex/.test(name) && !/^drag_ex/.test(name) && _dragSeq > 0) {
    const match = list.filter((a) => variantSeqOf(a) === _dragSeq)
    if (match.length) target = match[Math.floor(Math.random() * match.length)]
  }
  // drag_ex 同样优先同序号（对应 exN 的反向拖拽）
  if (/^drag_ex/.test(name) && _dragSeq > 0) {
    const match = list.filter((a) => variantSeqOf(a) === _dragSeq)
    if (match.length) target = match[Math.floor(Math.random() * match.length)]
  }
  for (const l of layers) {
    if (!l.skeleton) continue
    if (!l.data.animations.some((a) => a.name === target)) continue
    // 先清 track1（表情）并复位骨架到 setup pose：表情的 AttachmentTimeline 已把
    // 眉毛/眼等附件切走，仅 clearTrack(1) 不会还原 attachment —— 必须 setToSetupPose
    // 复位表情切过的附件，下一帧 state.apply 会重新应用 track0 互动动画。
    l.state.clearTrack(1)
    l.skeleton.setToSetupPose()
    l.skeleton.updateWorldTransform()
    l.state.setAnimation(0, target, loop)
  }
}

// 进入互动状态
function enterInteract(state) {
  if (interactState === state) return
  interactState = state
  switch (state) {
    case 'drag': playInteractAnim('drag', false); break
    case 'ex': playInteractAnim('ex', true); break
    case 'drag_ex': playInteractAnim('drag_ex', false); break
    case 'normal': playInteractAnim('normal', true); break
  }
}

// 动画完成回调：drag → ex；drag_ex → normal；
// 官方规则动作（touch_* 等）播完 → 切到规则的 change_idle 循环
// spine AnimationState complete 回调参数是 TrackEntry 对象，trackIndex 在 entry.trackIndex。
// 注意：loop=true 的循环动画每圈结束也会触发 complete（如 touch_special_normal
// 待机循环），必须排除——否则循环待机一圈就被切回 normal。
function onInteractComplete(entry) {
  if (!entry || entry.trackIndex !== 0) return
  if (entry.loop) return // 循环动画每圈 complete 不处理（ex/normal 由 spine 自动续圈）
  const name = entry.animation ? entry.animation.name : ''
  // BD2 mix/motion 整段演出播完 → 链式续播或平滑淡入待机循环
  if (bd2FullPlaying && /^(motion|mix\d+_|_face)/.test(name)) {
    bd2FullPlaying = false
    const nxt = bd2ChainNext && window.BD2Interact.advanceAuto
      ? window.BD2Interact.advanceAuto(bd2Profile, bd2ChainNext) : null
    if (nxt) {
      // 链式章节（连续演出）：自动续播下一段，中间不回家 idle（回 idle 会闪）
      bd2IdleAfter = nxt.idle || bd2IdleAfter
      bd2ChainNext = nxt.chain || null
      bd2FullPlaying = true
      playFullPhase(nxt.anim, false, { cleanSwitch: true })
      return
    }
    bd2ChainNext = null
    playFullPhase(bd2IdleAfter, true, { cleanSwitch: true })
    return
  }
  if (interactState === 'drag') {
    enterInteract('ex')
  } else if (interactState === 'drag_ex') {
    enterInteract('normal')
  } else if (/^touch_|^login$/.test(name)) {
    // 官方规则：单次互动动画播完 → 进入 change_idle 待机循环
    // （currentIdle 已在播放时更新为 change_idle；无规则时回 normal）
    playInteractAnim(currentIdle, true)
  }
}

// 拖拽开始：互动模式下触发 drag（若在 ex 中则触发 drag_ex）
function startInteractDrag() {
  if (!isInteractiveSkin() || !props.interactionMode) return
  if (interactState === 'ex' || interactState === 'drag_ex') {
    enterInteract('drag_ex')
  } else {
    enterInteract('drag')
  }
}

// ---- 官方互动规则状态机（config_client）----
// 规则语义（来自游戏 drag_data.config_client）：
//   { hit, action, idle, change_idle, is_default, click, fold }
//   当前待机 = rule.idle 的皮肤被点击(hit) → 播 action 一次 → 切到
//   change_idle 循环（change_idle 可能是 normal 或特殊待机如 touch_special_normal）。
// 无远程规则时回退 cycleTouchInteract 轮换。
let currentIdle = 'normal' // 当前待机动画（规则匹配键）

function pickRule() {
  if (!remoteInteractRules.length) return null
  // 先精确匹配当前 idle；无则用 is_default 规则
  let rule = remoteInteractRules.find((r) => r.idle === currentIdle && r.click !== false && r.action)
  if (!rule) rule = remoteInteractRules.find((r) => r.is_default && r.action)
  return rule || null
}

// 点击 → 按官方规则播放（返回 true 表示已由规则处理）
function playRuleAction() {
  const rule = pickRule()
  if (!rule) return false
  const action = rule.action
  if (!hasAnim(action)) return false
  currentIdle = rule.change_idle || 'normal' // 动作播完后进入的新待机
  playInteractAnim(action, false)
  // 对应部位语音
  playVoice(/touch/.test(action) ? action : 'touch_body')
  return true
}

// ---- 互动语音（与 L2D 共用 cue 系统） ----
async function loadVoiceStatus() {
  try {
    const vs = await bridge.voiceStatus(props.skin.painting || '')
    if (vs && vs.ok && vs.shipId && vs.cues.length) {
      voiceShipId = vs.shipId
      voicePick = vs.pick || {}
      voiceWords = vs.words || {}
      voiceCues = vs.cues || [] // mood 引擎按区域情绪组过滤用
      console.log('[spine] 语音就绪：船', voiceShipId, 'pick', JSON.stringify(voicePick))
    }
  } catch (e) {
    console.log('[spine] 语音加载失败：', e.message || e)
  }
}

let voiceAudio = null

function playVoiceCue(cue, text) {
  if (!voiceShipId || !cue) return
  if (!voiceEnabled.value) return
  try {
    // 防重复：先停掉上一个语音（连续点击不叠加、不重复播放）
    if (voiceAudio) {
      voiceAudio.pause()
      voiceAudio.close && voiceAudio.close()
      voiceAudio = null
    }
    const a = new Audio(assetUrl(`voice/${voiceShipId}/${cue}.wav`))
    a.volume = 0.9
    a.play().catch(() => { if (voiceAudio === a) voiceAudio = null; subtitleText.value = '' })
    voiceAudio = a
    subtitleText.value = text || ''
  } catch (e) { /* 无语音不影响互动 */ }
}

function playVoice(label) {
  if (!voicePick) return
  const base = VOICE_BASE[label] || label
  let cue = null, cueBase = ''
  for (const b of VOICE_FALLBACK[base] || [base]) {
    if (voicePick[b]) { cue = voicePick[b]; cueBase = b; break }
  }
  if (!cue) return
  let text = ''
  const wk = WORDS_KEY[cueBase]
  if (wk) {
    for (const w of WORDS_FALLBACK[wk] || [wk]) {
      if (voiceWords[w]) { text = voiceWords[w]; break }
    }
  }
  playVoiceCue(cue, text)
}

// touch 系互动：点击轮换播 touch 动画（body → head → special → body...），
// 每个动画播一次自动回 normal（onInteractComplete 处理），并播对应类别语音
let touchIndex = -1
function cycleTouchInteract() {
  const n = animNames()
  const order = TOUCH_ANIMS.filter((t) => n.includes(t))
  if (!order.length) return
  touchIndex = (touchIndex + 1) % order.length
  const anim = order[touchIndex]
  playInteractAnim(anim, false)
  // 动画名 → 语音 label：touch_body/touch_head/touch_special 直接对应 VOICE_BASE
  playVoice(anim)
}

// 纯表情皮肤点击切表情时：随机播一句该船的触摸/摸头/特殊触摸语音（作点击音效）。
// 皮肤无 touch 动画，但语音包按船绑定有这些 cue；随机选择让反馈更自然。
function playVoiceRandomInteractive() {
  const bases = ['touch_head', 'touch_1', 'touch_2']
  const pick = bases[Math.floor(Math.random() * bases.length)]
  playVoice(pick)
}

function layerBounds(l) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const slot of l.skeleton.slots) {
    const att = slot.getAttachment()
    if (!att) continue
    // 透明插槽（动画初始不可见的部分）与 kkkkk 位置标记附件不参与取景，
    // 否则会把包围盒撑到巨大、角色被“挤”出视野（云龙-溶于重重夜色 的典型问题）
    if (slot.color && slot.color.a < 0.01) continue
    if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
    if (isBgPanelSlot(slot) || slot._maskPanel) continue // 背景网格/画幅遮罩不参与取景
    const isRegion = att instanceof spine.RegionAttachment
    if (!isRegion && !(att instanceof spine.MeshAttachment) && !(att instanceof spine.BoundingBoxAttachment)) continue
    const len = isRegion ? 8 : att.worldVerticesLength
    if (!len) continue
    const verts = spine.Utils.newFloatArray(len)
    if (isRegion) att.computeWorldVertices(slot, verts, 0, 2)
    else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
    for (let j = 0; j < len; j += 2) {
      if (verts[j] < minX) minX = verts[j]
      if (verts[j] > maxX) maxX = verts[j]
      if (verts[j + 1] < minY) minY = verts[j + 1]
      if (verts[j + 1] > maxY) maxY = verts[j + 1]
    }
  }
  return { minX, maxX, minY, maxY }
}

function contentFrame() {
  // 按附件面积加权的网格密度取景：只框住“内容密集”区域，
  // 用于骨架包围盒被大面积背景网格/稀疏光效撑爆、角色被“挤”小的皮肤
  const raw = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
  const items = []
  for (const l of layers) {
    if (!l.skeleton || !isActiveSkel(l)) continue
    for (const slot of l.skeleton.slots) {
      const att = slot.getAttachment()
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      if (isBgPanelSlot(slot) || slot._maskPanel) continue // 背景网格/画幅遮罩不参与取景
      const isRegion = att instanceof spine.RegionAttachment
      const isMesh = att instanceof spine.MeshAttachment
      if (!isRegion && !isMesh) continue
      const len = isRegion ? 8 : att.worldVerticesLength
      if (!len) continue
      const verts = spine.Utils.newFloatArray(len)
      if (isRegion) att.computeWorldVertices(slot, verts, 0, 2)
      else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
      const b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
      for (let j = 0; j < len; j += 2) {
        if (verts[j] < b.minX) b.minX = verts[j]
        if (verts[j] > b.maxX) b.maxX = verts[j]
        if (verts[j + 1] < b.minY) b.minY = verts[j + 1]
        if (verts[j + 1] > b.maxY) b.maxY = verts[j + 1]
      }
      items.push(b)
      if (b.minX < raw.minX) raw.minX = b.minX
      if (b.maxX > raw.maxX) raw.maxX = b.maxX
      if (b.minY < raw.minY) raw.minY = b.minY
      if (b.maxY > raw.maxY) raw.maxY = b.maxY
    }
  }
  if (!items.length) return null
  const rawW = raw.maxX - raw.minX
  const rawH = raw.maxY - raw.minY
  const N = 64
  const gw = rawW / N || 1
  const gh = rawH / N || 1
  const grid = new Float64Array(N * N)
  for (const b of items) {
    const cx = (b.minX + b.maxX) / 2
    const cy = (b.minY + b.maxY) / 2
    const gx = Math.min(N - 1, Math.max(0, Math.floor((cx - raw.minX) / gw)))
    const gy = Math.min(N - 1, Math.max(0, Math.floor((cy - raw.minY) / gh)))
    grid[gy * N + gx] += Math.max(1, (b.maxX - b.minX) * (b.maxY - b.minY))
  }
  let maxCell = 0
  for (const v of grid) if (v > maxCell) maxCell = v
  if (!maxCell) return null
  const threshold = maxCell * 0.02
  let fminX = raw.maxX, fmaxX = raw.minX, fminY = raw.maxY, fmaxY = raw.minY, kept = 0
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      if (grid[gy * N + gx] >= threshold) {
        kept++
        if (raw.minX + gx * gw < fminX) fminX = raw.minX + gx * gw
        if (raw.minX + (gx + 1) * gw > fmaxX) fmaxX = raw.minX + (gx + 1) * gw
        if (raw.minY + gy * gh < fminY) fminY = raw.minY + gy * gh
        if (raw.minY + (gy + 1) * gh > fmaxY) fmaxY = raw.minY + (gy + 1) * gh
      }
    }
  }
  const fW = fmaxX - fminX
  const fH = fmaxY - fminY
  const ratioW = fW / rawW
  const ratioH = fH / rawH
  // 只有内容明显小于原始包围盒时才裁剪（正常皮肤内容≈包围盒，不受影响）
  if (!kept || ratioW > 0.55 || ratioH > 0.55 || ratioW < 0.08 || ratioH < 0.08) return null
  const padX = fW * 0.15
  const padY = fH * 0.15
  return { minX: fminX - padX, maxX: fmaxX + padX, minY: fminY - padY, maxY: fmaxY + padY }
}

function computeBaseBounds() {
  // 边界只算一次并缓存：动画帧里的超大特效部件会瞬间撑爆边界，
  // 导致拖拽/缩放时相机拉远出现“全屏虚影”。
  if (boundsCache) return boundsCache
  // 旋转支点与取景同源：人物层并集中心（首次冷路径计算，随 boundsCache 失效）
  if (charCenterCache === null) charCenterCache = computeCharCenter()
  // 独立背景图（Ultimate 正方形背景图等）：以背景图世界尺寸为取景框，
  // 角色在背景内自然显示、不填满整个画面（避免“角色太大”）。
  // 背景世界尺寸与 drawBg 一致：cover 铺满角色取景框 + 15% 外扩，中心对齐
  // 角色中心——cover 保证背景必然包含角色，框背景不会裁角色。
  // 若启用了外部/自定义扩图等背景（hideDefaultBg），跳过默认背景图取景，按主体角色取景（与壁纸模板一致）
  const bgImg = (!props.hideDefaultBg)
    ? (activeBgSetImg() || layers.find((l) => l.bg)?.bg)
    : null
  if (bgImg && bgImg.width > 0) {
    const img = bgImg
    const skelPer = layers.filter((l) => l.skeleton && isActiveSkel(l)).map(layerBounds).filter((b) => Number.isFinite(b.minX))
    if (skelPer.length) {
      const cb = {
        minX: Math.min(...skelPer.map((b) => b.minX)),
        maxX: Math.max(...skelPer.map((b) => b.maxX)),
        minY: Math.min(...skelPer.map((b) => b.minY)),
        maxY: Math.max(...skelPer.map((b) => b.maxY)),
      }
      const bw = cb.maxX - cb.minX
      const bh = cb.maxY - cb.minY
      if (bw > 0 && bh > 0) {
        const bgScale = (Math.max(bw / img.width, bh / img.height)) * 1.15
        const bgW = img.width * bgScale
        const bgH = img.height * bgScale
        const cx = (cb.minX + cb.maxX) / 2
        const cy = (cb.minY + cb.maxY) / 2
        boundsCache = {
          minX: cx - bgW / 2,
          maxX: cx + bgW / 2,
          minY: cy - bgH / 2,
          maxY: cy + bgH / 2,
        }
        return boundsCache
      }
    }
  }
  // 有显式背景层（B/_B/bg/_bg 后缀）时以背景层为取景基准：
  // 背景定义整幅场景（月亮/舞台），人物渲染在其中；否则取景会被人物的大
  // 包围盒带偏（如 新泽西·月下起舞：人物巨大、背景被挤成一条）。
  // 护栏：背景面积超过主体层 8 倍时视为装饰性大背景，回退常规取景
  //（避免把云朵类大背景重新撑爆取景）。
  const bgLayers = props.hideDefaultBg ? [] : layers.filter(isBgLayer)
  if (bgLayers.length) {
    const bgFrame = layerBounds(bgLayers[0])
    const nonBg = layers
      .filter((l) => l.skeleton && !isBgLayer(l))
      .map(layerBounds)
      .filter((b) => Number.isFinite(b.minX))
    if (Number.isFinite(bgFrame.minX) && nonBg.length) {
      const bgArea = (bgFrame.maxX - bgFrame.minX) * (bgFrame.maxY - bgFrame.minY) || 1
      const maxOther = Math.max(...nonBg.map((b) => (b.maxX - b.minX) * (b.maxY - b.minY)))
      // 护栏：背景面积在主体层的 [0.15, 8] 倍之间才适用背景取景。
      // 过小（装饰性小背景）会把人物撑爆裁切；过大（云朵类大背景）会重新
      // 把角色挤小，两种情况都回退常规取景。
      const bgW = bgFrame.maxX - bgFrame.minX
      const bgH = bgFrame.maxY - bgFrame.minY
      // 背景必须横构图（宽≥高）：竖构图背景（如 华甲_2 的窄背板）是装饰
      // 性布景，按它取景会裁掉人物并留大片黑边。
      if (bgArea >= maxOther * 0.15 && bgArea <= maxOther * 8 && bgW >= bgH) {
        const padX = (bgFrame.maxX - bgFrame.minX) * 0.08
        const padY = (bgFrame.maxY - bgFrame.minY) * 0.08
        boundsCache = {
          minX: bgFrame.minX - padX,
          maxX: bgFrame.maxX + padX,
          minY: bgFrame.minY - padY,
          maxY: bgFrame.maxY + padY,
        }
        return boundsCache
      }
    }
  }
  const dense = contentFrame()
  if (dense) {
    boundsCache = dense
    return boundsCache
  }
  // 面积过滤兜底：contentFrame 放弃时，有些皮肤的包围盒被巨大的背景/云朵部件
  // 撑爆（如 DEAD MASTER·战士的小憩 两侧的云把宽撑到 1.2 万），角色被挤成很小。
  // 这里保留“面积 ≤ 最大附件 40%”的部件参与取景，滤掉超大背景附件；
  // 若过滤后仍占满 90% 以上或附件过少，说明不是背景撑爆，回退常规逻辑。
  const areaFrame = denseAreaFrame()
  if (areaFrame) {
    boundsCache = areaFrame
    return boundsCache
  }
  // 多部件皮肤（角色+背景）中，背景层面积远大于主体层；取景只按主体层算，
  // 背景/特效层照常渲染但不参与取景，避免角色被巨大的背景“挤”出视野。
  const per = layers.filter((l) => l.skeleton && isActiveSkel(l)).map(layerBounds).filter((b) => Number.isFinite(b.minX))
  if (!per.length) {
    boundsCache = { minX: -1, maxX: 1, minY: -1, maxY: 1 }
    return boundsCache
  }
  let small = per[0]
  for (const b of per) {
    const a = (b.maxX - b.minX) * (b.maxY - b.minY)
    const ra = (small.maxX - small.minX) * (small.maxY - small.minY)
    if (a < ra) small = b
  }
  const baseArea = (small.maxX - small.minX) * (small.maxY - small.minY) || 1
  const frame = per.filter((b) => (b.maxX - b.minX) * (b.maxY - b.minY) <= baseArea * 4)
  boundsCache = {
    minX: Math.min(...frame.map((b) => b.minX)),
    maxX: Math.max(...frame.map((b) => b.maxX)),
    minY: Math.min(...frame.map((b) => b.minY)),
    maxY: Math.max(...frame.map((b) => b.maxY)),
  }
  return boundsCache
}

// 面积过滤取景：保留面积 ≤ 最大附件 40% 的部件（跨所有层），滤掉超大背景/云朵。
// 返回 null 表示不适用（内容未被撑爆），调用方回退常规逻辑。
function denseAreaFrame() {
  const raw = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
  const items = []
  for (const l of layers) {
    if (!l.skeleton || !isActiveSkel(l)) continue
    for (const slot of l.skeleton.slots) {
      const att = slot.getAttachment()
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      if (isBgPanelSlot(slot) || slot._maskPanel) continue // 背景网格/画幅遮罩不参与取景
      const isRegion = att instanceof spine.RegionAttachment
      const isMesh = att instanceof spine.MeshAttachment
      if (!isRegion && !isMesh) continue
      const len = isRegion ? 8 : att.worldVerticesLength
      if (!len) continue
      const verts = spine.Utils.newFloatArray(len)
      if (isRegion) att.computeWorldVertices(slot, verts, 0, 2)
      else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
      const b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
      for (let j = 0; j < len; j += 2) {
        if (verts[j] < b.minX) b.minX = verts[j]
        if (verts[j] > b.maxX) b.maxX = verts[j]
        if (verts[j + 1] < b.minY) b.minY = verts[j + 1]
        if (verts[j + 1] > b.maxY) b.maxY = verts[j + 1]
      }
      items.push(b)
      if (b.minX < raw.minX) raw.minX = b.minX
      if (b.maxX > raw.maxX) raw.maxX = b.maxX
      if (b.minY < raw.minY) raw.minY = b.minY
      if (b.maxY > raw.maxY) raw.maxY = b.maxY
    }
  }
  if (!items.length) return null
  const rawW = raw.maxX - raw.minX
  const rawH = raw.maxY - raw.minY
  const areas = items.map((b) => (b.maxX - b.minX) * (b.maxY - b.minY))
  const maxA = Math.max(...areas)
  // 最大附件本身就占满画面（无超大背景）时不适用
  if (maxA >= rawW * rawH * 0.8) return null
  const keep = items.filter((b, i) => areas[i] <= maxA * 0.4)
  if (!keep.length) return null
  // 在过滤后的集合上再做一次网格密度裁剪：滤掉散落的浪花/骷髅/云朵等
  // 分散装饰（如 DEAD MASTER·战士的小憩），把取景收到角色主体。
  const N = 64
  const gw = rawW / N || 1
  const gh = rawH / N || 1
  const grid = new Float64Array(N * N)
  for (const b of keep) {
    const cx = (b.minX + b.maxX) / 2
    const cy = (b.minY + b.maxY) / 2
    const gx = Math.min(N - 1, Math.max(0, Math.floor((cx - raw.minX) / gw)))
    const gy = Math.min(N - 1, Math.max(0, Math.floor((cy - raw.minY) / gh)))
    grid[gy * N + gx] += Math.max(1, (b.maxX - b.minX) * (b.maxY - b.minY))
  }
  let maxCell = 0
  for (const v of grid) if (v > maxCell) maxCell = v
  if (!maxCell) return null
  const threshold = maxCell * 0.02
  let fminX = raw.maxX, fmaxX = raw.minX, fminY = raw.maxY, fmaxY = raw.minY, keptCells = 0
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      if (grid[gy * N + gx] >= threshold) {
        keptCells++
        if (raw.minX + gx * gw < fminX) fminX = raw.minX + gx * gw
        if (raw.minX + (gx + 1) * gw > fmaxX) fmaxX = raw.minX + (gx + 1) * gw
        if (raw.minY + gy * gh < fminY) fminY = raw.minY + gy * gh
        if (raw.minY + (gy + 1) * gh > fmaxY) fmaxY = raw.minY + (gy + 1) * gh
      }
    }
  }
  const fW = fmaxX - fminX
  const fH = fmaxY - fminY
  // 网格保留太少（内容过于稀疏）或过滤后仍占满 90%+：回退原逻辑
  if (!keptCells || fW >= rawW * 0.9 || fH >= rawH * 0.9) return null
  const padX = fW * 0.12
  const padY = fH * 0.12
  return { minX: fminX - padX, maxX: fmaxX + padX, minY: fminY - padY, maxY: fmaxY + padY }
}

// 取景 = 基础取景框（缓存）按人物旋转外扩。取景支点【不含人物独立偏移】：
// 偏移是旋转后的刚体平移（渲染支点 charPivot 才跟随偏移），若取景 AABB 用
// 含偏移的支点，拖动人物时 AABB 会跟着平移——背景矩形锚定在 AABB 中心，
// 会跟着人物一起挪（=“拖动人物背景跟着扭”的病根，2026-10 实测）。
// 取景框静态后，拖动行为与未旋转时完全一致（人物动、背景/取景不动）。
// 旋转为 0 时直接返回缓存，行为与旧版完全一致。
function computeBounds() {
  const base = computeBaseBounds()
  const deg = props.rotation || 0
  if (!deg) return base
  const piv = charCenterCache || { x: (base.minX + base.maxX) / 2, y: (base.minY + base.maxY) / 2 }
  const aabb = WL.rotateBoundsAabb(base, deg, piv.x, piv.y)
  // 取景按高度铺 MARGIN（spineCamera 语义），宽出 16:9 的旋转姿态（竖长人物
  // 转到接近 90°）会横向出界——把取景框高度对称补到 宽×MARGIN/16:9，让宽度
  // 约束生效（等效该角度下自动缩小）。常规倾角 AABB 高大于补足值，不受影响。
  const w = aabb.maxX - aabb.minX
  const h = aabb.maxY - aabb.minY
  const needH = (w * WL.MARGIN) / WL.ASPECT
  if (needH > h) {
    const cy = (aabb.minY + aabb.maxY) / 2
    aabb.minY = cy - needH / 2
    aabb.maxY = cy + needH / 2
  }
  return aabb
}

function applyLayout() {
  const canvas = canvasRef.value
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  if (!cw || !ch || !layers.length || !renderer) return // 布局未就绪时跳过，避免除零/无穷大
  const a = WL.anchor(props.alignment)
  const cam = WL.spineCamera(computeBounds(), cw, ch, {
    scale: props.scale,
    offsetX: props.offsetX,
    offsetY: props.offsetY,
    alignX: a.x,
    alignY: a.y,
  })
  renderer.camera.zoom = cam.zoom
  renderer.camera.position.x = cam.x
  renderer.camera.position.y = cam.y
  renderer.camera.position.z = 0
  updateInteractiveOverlay()
}

// 交互区域（精确部位）：区域数据来自 nagami 参考数据集（游戏 Unity prefab 提取）：
//   https://data.nagami.moe/spine/models/{asset}.json 的 hitAreas[]——
//   { name, position[x,y], size[w,h], pivot, rootPosition, rootSize }。
//   name 即互动名（touch_head/touch_body/touch_special/drag/数字表情），
//   position+size 是相对骨架 rootPosition/rootSize 的世界坐标框。
// 同时拉取 skins/{id}.json 的 interaction.drag_data.config_client（官方点击互动规则：
//   {hit, action, idle, change_idle, is_default}——按当前 idle 匹配规则，播 action
//   一次后切到 change_idle 循环）。
// 拉取失败（离线/皮肤不在数据集）时降级为整体拖拽区。
let remoteInteractRules = [] // config_client 规则（touch 系状态机用）
const DATASET_BASE = 'https://data.nagami.moe/spine'
let skinIdCache = null // asset → 官方 id 映射缓存

async function fetchSkinId(asset) {
  if (skinIdCache) return skinIdCache[asset] || null
  try {
    const res = await fetch(`${DATASET_BASE}/index.json`)
    if (!res.ok) return null
    const idx = await res.json()
    skinIdCache = {}
    for (const s of idx.skins || []) skinIdCache[s.asset] = s.id
  } catch (e) { return null }
  return skinIdCache[asset] || null
}

async function loadHitAreas() {
  remoteHitAreas = []
  remoteInteractRules = []
  const asset = props.skin && props.skin.painting
  if (!asset) return
  try {
    const url = `${DATASET_BASE}/models/${encodeURIComponent(asset)}.json`
    const res = await fetch(url, { signal: AbortSignal.timeout ? AbortSignal.timeout(8000) : undefined })
    if (!res.ok) return
    const data = await res.json()
    if (Array.isArray(data && data.hitAreas)) remoteHitAreas = data.hitAreas
    if (remoteHitAreas.length) updateInteractiveOverlay()
  } catch (e) { /* 离线/无数据：静默降级 */ }
  // 拉官方点击互动规则（touch_special_normal 等特殊待机循环依赖它）
  try {
    const id = await fetchSkinId(asset)
    if (!id) return
    const res2 = await fetch(`${DATASET_BASE}/skins/${encodeURIComponent(id)}.json`, { signal: AbortSignal.timeout ? AbortSignal.timeout(8000) : undefined })
    if (!res2.ok) return
    const cfg = await res2.json()
    const cc = cfg && cfg.interaction && cfg.interaction.drag_data && cfg.interaction.drag_data.config_client
    if (Array.isArray(cc)) {
      remoteInteractRules = cc.filter((r) => r && typeof r === 'object')
      updateInteractiveOverlay()
    }
  } catch (e) { /* 静默降级 */ }
}

// 单个 hitArea → 世界框（position 是框中心相对 root 中心；rootPosition/rootSize 是骨架根框）
function hitWorldBox(h) {
  const rp = h.rootPosition || [0, 0]
  const rs = h.rootSize || [1, 1]
  const pos = h.position || [0, 0]
  const size = h.size || [0, 0]
  const pivot = h.pivot || [0.5, 0.5]
  // root 框的左下角 = rootPosition - rootSize/2（rootPosition 为根框中心）
  const rootMinX = rp[0] - rs[0] / 2
  const rootMaxX = rp[0] + rs[0] / 2
  const rootMaxY = rp[1] + rs[1] / 2
  // 区域中心相对 root 中心偏移 pos；spine Y 向上
  const cx = (rootMinX + rootMaxX) / 2 + pos[0]
  const cy = rootMaxY - rs[1] / 2 + pos[1]
  const w = size[0], hh = size[1]
  return { minX: cx - w / 2, maxX: cx + w / 2, minY: cy - hh / 2, maxY: cy + hh / 2 }
}
function boxToScreen(box, cw, ch) {
  const cam = renderer.camera
  const z = cam.zoom || 1
  const sx1 = (box.minX - cam.position.x) / z + cw / 2
  const sx2 = (box.maxX - cam.position.x) / z + cw / 2
  const sy1 = ch / 2 - (box.maxY - cam.position.y) / z
  const sy2 = ch / 2 - (box.minY - cam.position.y) / z
  const left = Math.min(sx1, sx2), top = Math.min(sy1, sy2)
  const style = {
    left: left + 'px',
    top: top + 'px',
    width: Math.abs(sx2 - sx1) + 'px',
    height: Math.abs(sy2 - sy1) + 'px',
  }
  // 人物旋转时叠加框同步转：以支点的屏幕投影为 transform-origin 旋转（屏幕
  // 刚体变换与"世界绕支点旋转 → 相机投影"等价，相机本身无旋转）
  if (props.rotation) {
    const piv = charPivot()
    const pxs = (piv.x - cam.position.x) / z + cw / 2
    const pys = ch / 2 - (piv.y - cam.position.y) / z
    style.transform = `rotate(${props.rotation}deg)`
    style.transformOrigin = `${pxs - left}px ${pys - top}px`
  }
  return { style, world: box }
}

function updateInteractiveOverlay() {
  // 复刻 L2D：开启「显示交互区域」即显示全部 hitAreas 区域框，不要求互动模式。
  if (!props.showHitAreas) {
    hitAreas.value = []
    return
  }
  const canvas = canvasRef.value
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  if (!cw || !ch || !renderer) { hitAreas.value = []; return }

  const areas = []
  const names = animNames()
  let exprShown = false // 数字表情区只显示一个（脸上的），避免同皮肤出现多个表情框
  for (const h of remoteHitAreas) {
    const box = hitWorldBox(h)
    const labelMap = {
      touch_head: '摸头', touch_body: '摸身体', touch_special: '特殊',
      touch_special_2: '特殊②', touch_special_normal: '特殊待机',
      drag: '拖拽', drag_ex: '拖拽②', ex: '互动', login: '开场',
      // 足尖弓矢等：拖拽区命名 random，换装区 skin_1/skin_2（L2D 也显示真实区域名）
      random: '拖拽', skin_1: '换装①', skin_2: '换装②',
    }
    if (/^\d+$/.test(h.name)) {
      if (exprShown) continue // 已有表情框，跳过其余数字区
      exprShown = true
    }
    let label = labelMap[h.name] || ''
    if (/^\d+$/.test(h.name)) label = '表情' + h.name
    if (/^skin_/.test(h.name)) label = label || '换装'
    if (!label) label = h.name
    areas.push({ label, kind: h.name, ...boxToScreen(box, cw, ch) })
  }
  // 数据集无该皮肤时兜底：整体一个"拖拽"框（用角色包围盒）
  if (!areas.length) {
    const main = layers.filter((l) => l.skeleton && !isBgLayer(l) && isActiveSkel(l)).map(layerBounds).filter((b) => Number.isFinite(b.minX))
    if (main.length) {
      const box = {
        minX: Math.min(...main.map((b) => b.minX)),
        maxX: Math.max(...main.map((b) => b.maxX)),
        minY: Math.min(...main.map((b) => b.minY)),
        maxY: Math.max(...main.map((b) => b.maxY)),
      }
      areas.push({ label: '拖拽/点击', kind: '__all__', ...boxToScreen(box, cw, ch) })
    }
  }
  // BD2 互动为顺序播放（点击任意位置推进序列），已无分区显示
  hitAreas.value = areas
}

function isBgLayer(l) {
  // 背景层识别：skel 名去掉 .skel 后以 B/BG/_B/bg/_bg（可带数字）结尾，
  // 如 xinzexi_4B / duyisibao_2B / beikaluolaina_3_bg / bisimaiZB
  if (!l || !l.skeleton || !l.name) return false
  const stem = l.name.replace(/\.skel$/i, '')
  return /b(?:g)?\d*$/i.test(stem)
}

// 插槽级背景面板过滤：约会/演出皮肤骨架内嵌的全屏背景网格/黑边面板
//（BK / B_BG_* / bg_* / BG_*）不参与取景，但正常渲染（被裁剪不显示也不影响画面）。
// 缓存在骨架实例上避免重复计算（同骨架跨帧复用）。
function isBgPanelSlot(slot) {
  const cache = slot._bp
  if (cache !== undefined) return cache
  const nm = ((slot.data && slot.data.name) || '').toLowerCase().trim()
  slot._bp = nm === 'bk' || nm === 'bg' || nm.indexOf('b_bg') === 0 || nm.indexOf('bg_') === 0 || nm.indexOf('bg-') === 0
  return slot._bp
}

// 「画幅遮罩」插槽：约会皮骨架里贴在场景四周/外圈的巨型暗色面板（游戏用于
// 不同宽高比的画幅外遮盖），如 FR 边框（dating15/11）、BK2/3/4 三块围板
//（dating13）、black1-4 四侧板（dating9）、black glow side_re*（dating19）、
// hit_cut_BG1-5（dating21）。它们把取景包围盒撑到场景的 4~14 倍，角色被挤小、
// 画面只剩黑边框。判定 = 名字命中 + 面积 ≥ 全部附件面积中位数 8 倍（双门槛，
// 避免误伤 black_wings_l/r 翅膀、blackdress_N 裙等同名身体部件）。
// 命中者不参与取景（layerBounds/contentFrame/denseAreaFrame 跳过），照常渲染
// ——相机收进场景后它们在视野外，不会入画。与模板 wallpaper_spine.html 同步。
function isMaskSlotName(nm) {
  nm = (nm + '').toLowerCase().trim()
  if (nm === 'fr' || /^fr\s*\(\d+\)$/.test(nm)) return true // FR / fr (1013) 画幅边框
  if (nm.indexOf('bk') === 0) return true // BK / BK4 / BK _type2 围板
  if (nm === 'black' || /^black\d/.test(nm)) return true // black / black2-4 侧板
  if (nm === 'black_all' || nm === 'black_blur') return true
  if (nm.indexOf('black glow') === 0) return true // black glow side_re* 侧板
  if (nm.indexOf('hit_cut_bg') === 0) return true // hit_cut_BG1-5 四侧板
  return false
}

// 在骨架加载后（t=0 姿态）调用一次：给命中的插槽打 _maskPanel 标记
function markMaskSlots() {
  const areas = []
  const infos = []
  for (const l of layers) {
    if (!l.skeleton) continue
    for (const slot of l.skeleton.slots) {
      const att = slot.getAttachment()
      slot._maskPanel = false
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      if (isBgPanelSlot(slot)) continue
      const isRegion = att instanceof spine.RegionAttachment
      const isMesh = att instanceof spine.MeshAttachment
      if (!isRegion && !isMesh) continue
      const len = isRegion ? 8 : att.worldVerticesLength
      if (!len) continue
      const verts = spine.Utils.newFloatArray(len)
      if (isRegion) att.computeWorldVertices(slot, verts, 0, 2)
      else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
      for (let j = 0; j < len; j += 2) {
        if (verts[j] < minX) minX = verts[j]
        if (verts[j] > maxX) maxX = verts[j]
        if (verts[j + 1] < minY) minY = verts[j + 1]
        if (verts[j + 1] > maxY) maxY = verts[j + 1]
      }
      const a = (maxX - minX) * (maxY - minY)
      if (a > 0) { areas.push(a); infos.push({ slot, area: a }) }
    }
  }
  if (!areas.length) return
  areas.sort((x, y) => x - y)
  const median = areas[Math.floor(areas.length / 2)] || 1
  for (const it of infos) {
    if (it.area >= median * 8 && isMaskSlotName(it.slot.data && it.slot.data.name)) {
      it.slot._maskPanel = true
    }
  }
}

// 背景层永远先画：碧蓝多层皮肤的 layers 顺序来自文件名排序，不保证 B 在前
//（如 duyisibao_2 是 [主, B]，按原序画背景会盖住人物）。
// 阶段骨架（多章约会皮）：只渲染当前阶段，其余阶段骨架已预载但不画。
function renderOrder() {
  const skels = layers.filter((l) => l.skeleton && isActiveSkel(l))
  if (props.hideDefaultBg) {
    return skels.filter((l) => !isBgLayer(l))
  }
  return [...layers.filter(isBgLayer), ...skels.filter((l) => !isBgLayer(l))]
}

// 风景/场景型皮肤的“人物适配”：当人物（非背景层）从头到脚明显大于背景层时
//（如 新泽西·月下起舞 人物是背景 2 倍、多琳妮娅·两人的秘密特训 1.5 倍），
// 把人物等比缩小到背景高度的 70%，使其“不超过背景大小”并保持合适比例
//（与官方海报构图一致）。只缩不放；人物高度 ≤ 背景 1.15 倍时保持原样
//（如 B/M/T 舰装皮肤，人物本就与背景相当）。
// 锚点用人物包围盒中心：这两个皮肤人物与背景天然垂直居中，中心锚定能让人物
// 正确落位（月下起舞站树枝、秘密特训跪沙发）。Skeleton 变换 world = local*scale+(x,y)，
// 以中心 (cx, cy) 为锚点需设 x = cx*(1-s)。
function applyCharacterFit() {
  const bgLayers = layers.filter(isBgLayer)
  if (!bgLayers.length) return
  const bgFrame = layerBounds(bgLayers[0])
  if (!Number.isFinite(bgFrame.minX)) return
  const charLayers = layers.filter((l) => l.skeleton && !isBgLayer(l) && isActiveSkel(l))
  if (!charLayers.length) return
  const per = charLayers.map(layerBounds).filter((b) => Number.isFinite(b.minX))
  if (!per.length) return
  const charFrame = {
    minX: Math.min(...per.map((b) => b.minX)),
    maxX: Math.max(...per.map((b) => b.maxX)),
    minY: Math.min(...per.map((b) => b.minY)),
    maxY: Math.max(...per.map((b) => b.maxY)),
  }
  const bgH = bgFrame.maxY - bgFrame.minY
  const charH = charFrame.maxY - charFrame.minY
  if (!bgH || !charH || charH <= bgH * 1.15) return
  const s = (bgH * 0.7) / charH
  const cx = (charFrame.minX + charFrame.maxX) / 2
  const cy = (charFrame.minY + charFrame.maxY) / 2
  for (const l of charLayers) {
    l.skeleton.x = cx * (1 - s)
    l.skeleton.y = cy * (1 - s)
    l.skeleton.scaleX = s
    l.skeleton.scaleY = s
    l.skeleton.updateWorldTransform()
  }
}

let _dc = 0
function render() {
  // 诊断：帧计数 + 互动状态 + 第一个骨架 track0 的动画时间（判断「动画是否还在推进」）
  let _t = ''
  const _l0 = layers.find((l) => l.skeleton && l.state)
    if (_l0) {
      const _e = _l0.state.getCurrent(0)
      if (_e && _e.animation) _t = `${_e.animation.name}@${_e.trackTime.toFixed(1)}s${_e.loop ? '(loop)' : ''}`
      else _t = 'no-anim'
    } else _t = 'no-skel'
    const _v = window.BD2Interact && window.BD2Interact.VERSION ? ' 引擎' + window.BD2Interact.VERSION : ''
    dbgText.value = `帧${++_dc} ${interactState} ${_t}${_v}${paused ? ' PAUSED' : ''}${disposed ? ' DISPOSED' : ''}`.slice(0, 90)
  if (disposed || paused) {
    // 非 disposed 的暂停只是 keep-alive 切走，切回时会恢复 rAF；disposed 直接停
    if (!disposed && paused) raf = 0
    return
  }
  // 防御：渲染帧内任何一步抛错都不能让 rAF 链断掉（否则画面静默定格——用户已遇到过）。
  // 异常上报给父组件弹错误框，并继续预约下一帧。
  try {
    const now = performance.now() / 1000
    const delta = Math.min(0.1, now - lastFrame)
    lastFrame = now
    const canvas = canvasRef.value
    if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
      canvas.width = canvas.clientWidth
      canvas.height = canvas.clientHeight
      gl.viewport(0, 0, canvas.width, canvas.height)
      renderer.camera.setViewport(canvas.width, canvas.height)
      applyLayout()
    }
    // 骨骼/动画推进：即使某层异常也只影响该层，不中断整帧
    // 计算角色独立偏移（世界坐标），与整体偏移区分：只移动骨架，背景保持不动
    const _cw = canvas.clientWidth || 1
    const _ch = canvas.clientHeight || 1
    const _zoom = renderer.camera.zoom || 1
    const _charOff = WL.charOffsetWorld(props.charOffsetX, props.charOffsetY, _cw, _ch, _zoom)
    for (const l of layers) {
      if (!l.skeleton) continue
      try {
        // 角色独立位置偏移：只对非背景层（character）生效，背景层/BG 图保持不动
        if (!isBgLayer(l) && (_charOff.x || _charOff.y)) {
          l.skeleton.x = (l.charBaseX ?? l.skeleton.x) + _charOff.x
          l.skeleton.y = (l.charBaseY ?? l.skeleton.y) + _charOff.y
        } else {
          // 无偏移或背景层：恢复 base 位置，避免累积
          if (l.charBaseX !== undefined) l.skeleton.x = l.charBaseX
          if (l.charBaseY !== undefined) l.skeleton.y = l.charBaseY
        }
        l.state.update(delta)
        l.state.apply(l.skeleton)
        l.skeleton.updateWorldTransform()
      } catch (e) {
        console.warn('[spine-render] 层动画异常:', l.name, e)
      }
    }
    clearRenderFrame()
  } catch (e) {
    console.error('[spine-render] 帧内异常:', e.message || e)
    if (!disposed) emit('error', '[spine-render] ' + (e.message || String(e)))
  }
  raf = requestAnimationFrame(render)
}

// 把"绕世界点 (px,py) 旋转 deg"右乘进相机投影（列主序原地乘）：
// PV' = PV × M，顶点先经世界旋转再进相机。只在人物层绘制段生效——
// enableRenderer 在 end() 后重新绑定 MVP 读到的是改写后的矩阵，而下一帧
// begin() 的 camera.update() 会重建 projectionView，无需还原。
const _rotTmp = new Array(16)
function _applyProjectionRotation(deg, px, py) {
  const v = renderer.camera.projectionView.values
  const m = WL.charRotationMatrixValues(deg, px, py)
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      _rotTmp[c * 4 + r] = v[r] * m[c * 4] + v[4 + r] * m[c * 4 + 1] + v[8 + r] * m[c * 4 + 2] + v[12 + r] * m[c * 4 + 3]
    }
  }
  for (let i = 0; i < 16; i++) v[i] = _rotTmp[i]
}

// 每帧的实际绘制（独立成函数便于隔离 overlay/背景等辅助逻辑的异常）
function clearRenderFrame() {
  try { updateInteractiveOverlay() } catch (e) { console.warn('[spine-render] overlay 异常:', e.message || e) }
  gl.clearColor(0, 0, 0, 0)
  gl.clear(gl.COLOR_BUFFER_BIT)
  renderer.begin()
  // 独立背景图：铺在角色层下面，覆盖整个取景框。
  // Ultimate 多阶段背景（bg_sets）：只画当前动画对应组；否则逐张画默认背景。
  // 若启用了自定义背景/场景背景/纯色/渐变等样式（hideDefaultBg），隐藏内置默认背景，避免重叠出现两个背景
  if (!props.hideDefaultBg) {
    const setImg = activeBgSetImg()
    if (setImg) {
      try { drawBg(setImg) } catch (e) { console.warn('[spine-render] bg 异常:', e.message || e) }
    } else {
      for (const l of layers) {
        if (!l.bg) continue
        try { drawBg(l.bg) } catch (e) { console.warn('[spine-render] bg 异常:', e.message || e) }
      }
    }
  }
  // 背景骨架层（场景层）不参与人物旋转，与背景图同批绘制
  const order = renderOrder()
  for (const l of order) {
    if (!l.skeleton || !isBgLayer(l)) continue
    renderer.drawSkeleton(l.skeleton, true)
  }
  // 人物旋转：背景批 flush 后改写投影，再画人物层（旋转 0 时与旧版同批，无额外开销）
  const deg = props.rotation || 0
  if (deg && order.some((l) => l.skeleton && !isBgLayer(l))) {
    renderer.end()
    const piv = charPivot()
    _applyProjectionRotation(deg, piv.x, piv.y)
  }
  for (const l of order) {
    if (!l.skeleton || isBgLayer(l)) continue
    renderer.drawSkeleton(l.skeleton, true)
  }
  renderer.end()
}

// 背景图绘制：铺满整个画布可视区域（世界坐标）。
// 用相机反算画布对应的世界范围，背景等比 cover 铺满它。
// 关键：背景 PNG 是直通 alpha（非预乘）数据——alpha=0 的像素 RGB 仍有残留色
//（如俾斯麦Zwei 45% 透明但 RGB 均值 140+），必须用 SRC_ALPHA 混合：
// 残留 RGB × alpha(0) = 0，透明区正确透出下层；若误用 ONE（预乘混合）会把
// 残留 RGB 当不透明绘制，表现为破碎/花屏。
let bgTexCache = null

function drawBg(img) {
  if (!renderer) return
  if (!bgTexCache || bgTexCache._img !== img) {
    // 独立背景 PNG 是直通 alpha：恒原样上传（不预乘），与 BD2_PREMULTIPLY_UPLOAD 无关
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    bgTexCache = new spine.GLTexture(gl, img)
    bgTexCache._img = img
  }
  // 背景【世界空间锚定】：绘制在取景框（computeBounds 的背景图 cover 矩形）上，
  // 与角色同处一个世界坐标系——构图跨画布/跨设备恒定（预览画布宽高比 ≠ 显示器
  // 宽高比时，视口锚定画法的人物与舞台相对构图会漂移 = Ultimate 系"预览≠导出"
  // 的根源，勿改回视口锚定）。
  // 人物/背景独立调节在此画法下的实现：
  //   位置：charOffset 只移骨架 / bgOffset 只移本矩形（互相独立 ✓）
  //   缩放：scale 走相机 zoom（人物+背景联动）；人物模式滚轮缩放时宿主自动
  //         反向补偿 bgScale（见 onCanvasWheel），使背景屏幕大小恒定 = 真解耦
  const bounds = computeBounds()
  const bw = bounds.maxX - bounds.minX
  const bh = bounds.maxY - bounds.minY
  if (!bw || !bh) return
  const iw = img.width || 1
  const ih = img.height || 1
  const scale = (Math.max(bw / iw, bh / ih)) * 1.15 * (props.bgScale / 100)
  const w = iw * scale
  const h = ih * scale
  const cx = (bounds.minX + bounds.maxX) / 2
  const cy = (bounds.minY + bounds.maxY) / 2
  // 背景独立位移（bgOffsetX/Y % 画布 → 世界坐标，与角色独立偏移同一换算）：
  // 只移动背景矩形，角色不动
  const cv = canvasRef.value
  const bgOff = WL.charOffsetWorld(
    props.bgOffsetX, props.bgOffsetY,
    (cv && cv.clientWidth) || 0, (cv && cv.clientHeight) || 0,
    renderer.camera.zoom || 1,
  )
  // 直通 alpha 混合（透明区透出下层），画完恢复（角色 drawSkeleton 用自身混合）。
  // Spine 4.1 blend 三参：setBlendMode(srcColor, srcAlpha, dst) = blendFuncSeparate；
  // 直通 alpha = (SRC_ALPHA, ONE, ONE_MINUS_SRC_ALPHA)；预乘 = (ONE, ONE, ONE_MINUS_SRC_ALPHA)。
  renderer.batcher.setBlendMode(gl.SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
  renderer.drawTexture(bgTexCache, cx - w / 2 + bgOff.x, cy - h / 2 + bgOff.y, w, h)
  renderer.batcher.setBlendMode(gl.ONE, gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
}

watch(
  () => [props.scale, props.bgScale, props.offsetX, props.offsetY, props.alignment, props.rotation],
  () => applyLayout(),
)

watch(
  () => props.animation,
  (v) => {
    if (!v) return
    boundsCache = charCenterCache = null
    playAnimation(v)
    for (const l of layers) {
      if (!l.skeleton) continue
      l.state.update(0)
      l.state.apply(l.skeleton)
      l.skeleton.updateWorldTransform()
    }
    computeBounds()
    applyLayout()
  },
)

watch(
  () => props.hideDefaultBg,
  () => {
    boundsCache = charCenterCache = null
    computeBounds()
    applyLayout()
  },
)

function hasWebGlBg() {
  if (props.hideDefaultBg) return false
  return Boolean(activeBgSetImg()) || layers.some((l) => l.bg)
}

function onCanvasWheel(e) {
  e.preventDefault()
  const factor = Math.pow(1.1, -e.deltaY / 100)
  // 版式调节目标=背景：滚轮只缩放背景（30~300%，与背景缩放滑块同范围）
  if (props.adjustTarget === 'bg') {
    const nextBg = Math.max(30, Math.min(300, Math.round(props.bgScale * factor)))
    if (nextBg !== props.bgScale) emit('bgScaleChange', nextBg)
    return
  }
  const next = Math.round(WL.clampScale(props.scale * factor))
  emit('scaleChange', next)

  // 版式调节目标=画面（整体缩放：整张构图融合缩放）
  // 相机 zoom 缩放人物、bgScale 同步缩放 CSS 背景之外，三类偏移锚点（整体/
  // 人物/背景）也按同一比例 k 缩放：偏移是屏幕锚定语义（%取景框，不随 zoom
  // 变），若只放大不缩锚点，独立偏移过的人物/背景会绕各自锚点生长，相对排布
  // 越缩越散（= 用户报的"越缩放分离越大"）。锚点同步缩放后整张构图如照片般
  // 以画面中心为支点融合缩放。全部 0 偏移时 0×k 仍为 0，无副作用。
  // 中心对齐下精确；非中心对齐另有 (0.5-ax)·取景框 常数项不随缩放（既有限制）。
  if (props.adjustTarget === 'stage') {
    if (next !== props.scale && props.scale > 0) {
      const k = next / props.scale
      const sc = (v) => Math.round(WL.clampOffset((v || 0) * k))
      emit('panChange', { x: sc(props.offsetX), y: sc(props.offsetY) })
      emit('charOffsetChange', { x: sc(props.charOffsetX), y: sc(props.charOffsetY) })
      emit('bgOffsetChange', { x: sc(props.bgOffsetX), y: sc(props.bgOffsetY) })
      // CSS 背景（!hasWebGlBg）不受相机 zoom 影响，bgScale 按同一比例 k 同步
      //（scale 触顶/触底时 k=1，背景同步停住）；WebGL 背景在世界空间随相机自然联动。
      if (!hasWebGlBg()) {
        const nextBg = Math.max(30, Math.min(300, Math.round(props.bgScale * k)))
        if (nextBg !== props.bgScale) emit('bgScaleChange', nextBg)
      }
    }
    return
  }

  // 版式调节目标=人物（只缩放人物，背景保持不动）
  // 对于 CSS 背景（!hasWebGlBg）：相机 zoom 不影响 CSS，因此 bgScale 保持不变即可实现“背景不动”；
  // 仅对于 WebGL 独立背景（hasWebGlBg）：由于相机 zoom 会联动背景画面大小，需反向补偿 bgScale 抵消相机 zoom，保持背景屏幕大小恒定
  if (props.adjustTarget === 'char' && next !== props.scale && props.scale > 0) {
    if (hasWebGlBg()) {
      const comp = Math.max(30, Math.min(300, Math.round(props.bgScale * props.scale / next)))
      if (comp !== props.bgScale) emit('bgScaleChange', comp)
    }
  }
}

// 命中检测：点击点（世界坐标）落在哪个 hitArea 世界框内
function screenToWorld(px, py) {
  const canvas = canvasRef.value
  const cw = canvas.clientWidth || 1
  const ch = canvas.clientHeight || 1
  const cam = renderer.camera
  const z = cam.zoom || 1
  return {
    x: (px - cw / 2) * z + cam.position.x,
    y: (ch / 2 - py) * z + cam.position.y,
  }
}

// 旋转取逆：人物渲染时被绕支点旋转了 deg（正=顺时针），点击命中检测要用
// 未旋转的世界坐标——把屏幕→世界的点按支点转回去
function unrotateWorldPoint(wx, wy) {
  const deg = props.rotation || 0
  if (!deg) return { x: wx, y: wy }
  const piv = charPivot()
  const t = (deg * Math.PI) / 180
  const c = Math.cos(t)
  const s = Math.sin(t)
  const dx = wx - piv.x
  const dy = wy - piv.y
  return { x: piv.x + dx * c - dy * s, y: piv.y + dx * s + dy * c }
}
function hitAreaAt(wx, wy) {
  for (const a of hitAreas.value) {
    const w = a.world
    if (!w) continue
    if (wx >= w.minX && wx <= w.maxX && wy >= w.minY && wy <= w.maxY) return a
  }
  return null
}

// ===== BD2 拟官方互动（单源引擎 window.BD2Interact，与壁纸模板同一份文件） =====
// 分区：语义骨骼锚点（head/chest/hand/leg…）最近匹配 → 播 _faceN 表情(track1 叠加)
// + 按区域情绪挑 Int_{Mood} 官方语音 + 点击特效粒子。返回 false 时回落旧逻辑。
function tryBd2Interact(e) {
  if (!window.BD2Interact) return false
  const l0 = layers.find((l) => l.skeleton && isActiveSkel(l)) || layers.find((l) => l.skeleton)
  if (!l0) return false
  // 每点必触发：连续点击会中断当前 mix 演出，硬切到下一段互动（playFull cleanSwitch 硬切）。
  // 兜底：enableInteraction 的预热未跑时（异常路径）在此重建
  const profile = ensureBd2Profile()
  if (!profile || !profile.bd2) return false
  // 顺序播放模型：点击任意位置都触发，位置不再参与决策
  const canvas = canvasRef.value
  const rect = canvas.getBoundingClientRect()
  const wp = screenToWorld(e.clientX - rect.left, e.clientY - rect.top)
  const react = window.BD2Interact.decide(bd2Profile, [], null, unrotateWorldPoint(wp.x, wp.y),
                                          { motionCooldownUntil: bd2MotionCdUntil })
  if (!react) return false
  if (react.mode === 'overlay') {
    // 第一代 face 式：表情叠加 track1（不打断 track0 的 idle 身体循环）
    for (const l of layers) {
      if (!l.skeleton) continue
      const cur = l.state.getCurrent(0)
      if (!cur) { const def = pickAnim(l.data); if (def) l.state.setAnimation(0, def, true) }
      l.state.clearTrack(1)
      if (l.data.animations.some((a) => a.name === react.anim)) {
        l.state.setAnimation(1, react.anim, false)
      }
    }
    // 少概率整身 motion（官方大幅反应），12s 冷却；播完由 complete 回待机
    if (react.motion && hasAnim('motion')) {
      bd2FullPlaying = true
      bd2IdleAfter = pickAnim(l0.data)
      bd2ChainNext = null
      playFullPhase('motion', false, { cleanSwitch: true })
      interactState = 'normal'
      currentIdle = 'normal'
      bd2MotionCdUntil = Date.now() + 12000
    }
  } else {
    // 第二代 mix/motion 整段演出：track0 单发（playFull 交叉淡化进出，避免硬切闪帧），
    // complete 回待机循环（6s 冷却防连刷）；链式章节由 complete 自动续播下一段
    bd2FullPlaying = true
    bd2IdleAfter = react.idle || pickAnim(l0.data)
    bd2ChainNext = react.chain || null
    if (!playFullPhase(react.anim, false, { cleanSwitch: true })) {
      playAnimation(bd2IdleAfter) // 极端兜底：层缺动画则退回待机
    }
    interactState = 'normal'
    currentIdle = bd2IdleAfter
    bd2MotionCdUntil = Date.now() + 6000
  }
  // 区域情绪 → Int_{Mood} 官方语音（600ms 节流）
  const now = Date.now()
  if (voiceShipId && voiceEnabled.value && now - bd2VoiceAt > 600) {
    const cue = window.BD2Interact.cueForMood(voiceCues, react.zone.moods)
      || (voicePick && (voicePick.touch_1 || voicePick.touch_head)) || null
    if (cue) { playVoiceCue(cue); bd2VoiceAt = now }
  }
  // 特效：直接在鼠标落点（CSS 像素，相对包裹层）绽放
  window.BD2Interact.spawnEffect(wrapRef.value, e.clientX - rect.left, e.clientY - rect.top, react.zone.moods[0])
  return true
}

function onCanvasDown(e) {
  if (e.button !== 0) return
  e.preventDefault()
  // 版式拖拽调节（人物/背景）：选中目标后拖动只调节该目标，点击不触发皮肤互动
  //（"只调节当前选择的选项"——互动反应与版式调节互不干扰，切回"画面"恢复互动/平移）
  if (props.adjustTarget === 'char' || props.adjustTarget === 'bg') {
    const isChar = props.adjustTarget === 'char'
    drag = {
      x: e.clientX,
      y: e.clientY,
      target: props.adjustTarget,
      ox: isChar ? props.charOffsetX : props.bgOffsetX,
      oy: isChar ? props.charOffsetY : props.bgOffsetY,
    }
    canvasRef.value.style.cursor = 'move'
    return
  }
  // 互动模式下才触发互动逻辑（纯表情皮肤切表情、drag 皮肤拖拽反应、touch 系触摸）。
  // 注意：纯表情皮肤 isInteractiveSkin() 为 false 但同样需要互动（点击切表情），
  // 所以这里不 gate isInteractiveSkin——互动模式一律走互动逻辑，未命中区域再按皮肤类型分流。
  if (props.interactionMode) {
    // ★ BD2 拟官方互动优先（idle/motion/_faceN 动画集）：分区命中 → 表情+语音+特效。
    //   非 bd2 皮肤或点击在角色框外 → false 落到下方旧逻辑。
    if (tryBd2Interact(e)) {
      canvasRef.value.style.cursor = 'grabbing'
      return
    }
    // 精确部位命中：hitArea 世界框（数据来自游戏 prefab 提取的参考数据集）
    const rect = canvasRef.value.getBoundingClientRect()
    const wp0 = screenToWorld(e.clientX - rect.left, e.clientY - rect.top)
    const wp = unrotateWorldPoint(wp0.x, wp0.y)
    const area = hitAreaAt(wp.x, wp.y)
    // ★ drag 皮肤：直接走本地 drag 状态机（drag→ex→drag_ex→normal）。
    //   官方 config_client 对 drag 皮肤的规则也是 drag→ex / drag_ex→normal，
    //   但 playRuleAction 只播 action、不驱动完整状态机（complete 后不自动切
    //   ex/normal），会导致点击后播完 drag 不切 ex、状态机卡死。
    //   因此 drag 皮肤必须绕过官方规则分支，走本地 startInteractDrag。
    if (interactKind() === 'drag') {
      // ★ 数字表情命中：循环切换表情（叠加到 track1；表情是 duration=0 的
      //   静态单帧，替换 track0 会变无动作静态 → 卡）
      if (area && /^\d+$/.test(area.kind) && hasAnim(area.kind)) {
        cycleExpression()
        canvasRef.value.style.cursor = 'grabbing'
        return
      }
      // 命中非 drag 区域（如 touch_head 等）：按该动画播一次
      if (area && area.kind && area.kind !== 'drag' && hasAnim(area.kind)) {
        playInteractAnim(area.kind, false)
        playVoice(/^touch/.test(area.kind) ? area.kind : 'touch_body')
      } else {
        // drag 区域 / 未命中：本地 drag 状态机
        startInteractDrag()
        playVoice('touch_body')
      }
      canvasRef.value.style.cursor = 'grabbing'
      return
    }
    // 官方规则状态机优先（仅 touch 系走这里；config_client 的 touch 规则：
    // 按当前 idle 匹配规则 → 播 action → 切 change_idle 循环）
    if (remoteInteractRules.length) {
      if (area) {
        const kindName = area.kind
        if (/^\d+$/.test(kindName)) {
          // 数字表情 hit → track1 叠加
          for (const l of layers) {
            if (!l.skeleton) continue
            if (!l.data.animations.some((a) => a.name === kindName)) continue
            const cur = l.state.getCurrent(0)
            if (!cur) { const d2 = pickAnim(l.data); if (d2) l.state.setAnimation(0, d2, true) }
            l.state.setAnimation(1, kindName, false)
          }
          canvasRef.value.style.cursor = 'grabbing'
          return
        }
        // hit 名匹配对应规则（hit === action 名，如 touch_head/touch_special）
        const hitRule = remoteInteractRules.find(
          (r) => r && typeof r === 'object' && r.hit === kindName && r.action && r.click !== false,
        )
        if (hitRule && hasAnim(hitRule.action)) {
          currentIdle = hitRule.change_idle || 'normal'
          playInteractAnim(hitRule.action, false)
          playVoice(/^touch/.test(hitRule.action) ? hitRule.action : 'touch_body')
          canvasRef.value.style.cursor = 'grabbing'
          return
        }
      }
      // 无部位命中/无对应规则 → 按当前 idle 匹配官方规则
      if (playRuleAction()) {
        canvasRef.value.style.cursor = 'grabbing'
        return
      }
    }
    // 无官方规则：旧逻辑（drag 系状态机 / touch 系轮换）
    if (area) {
      const kindName = area.kind
      // 数字表情 hit：不固定播该表情，而是循环切换全部表情（点哪都能换）
      if (/^\d+$/.test(kindName)) {
        cycleExpression()
        canvasRef.value.style.cursor = 'grabbing'
        return
      }
      if (kindName === 'drag' && hasAnim('drag')) {
        startInteractDrag()
      } else if (hasAnim(kindName)) {
        playInteractAnim(kindName, false)
      } else if (interactKind() === 'drag') {
        startInteractDrag()
      } else {
        cycleTouchInteract()
      }
      playVoice(/^touch/.test(kindName) ? kindName : 'touch_body')
      canvasRef.value.style.cursor = 'grabbing'
      return
    }
    // 未命中任何区域：
    if (interactKind() === 'drag') {
      startInteractDrag()
      playVoice('touch_body')
    } else if (animNames().some((n) => isExpression(n, layers.find((l) => l.skeleton)?.data))) {
      // 无 drag/touch 但有表情：点击循环切全部表情，
      // 同时随机播一句该船的触摸/摸头/特殊触摸语音作点击反馈（用户需求）
      cycleExpression()
      playVoiceRandomInteractive()
    } else {
      cycleTouchInteract()
    }
    canvasRef.value.style.cursor = 'grabbing'
    return
  }
  drag = {
    x: e.clientX,
    y: e.clientY,
    ox: props.offsetX,
    oy: props.offsetY,
    camX: renderer.camera.position.x,
    camY: renderer.camera.position.y,
    zoom: renderer.camera.zoom,
  }
  canvasRef.value.style.cursor = 'grabbing'
}

// 非互动皮肤：点击循环切换数字表情（duration=0 的 AttachmentTimeline 动画）
let exprIndex = -1
function cycleExpression() {
  const exprs = animNames().filter((n) => isExpression(n, layers.find((l) => l.skeleton)?.data))
  if (!exprs.length) return
  exprIndex = (exprIndex + 1) % (exprs.length + 1) // +1 = 循环回"无表情"
  for (const l of layers) {
    if (!l.skeleton) continue
    // 先确保 track0 有动作（表情叠加的前提）
    const cur = l.state.getCurrent(0)
    if (!cur) {
      const def = pickAnim(l.data)
      if (def) l.state.setAnimation(0, def, true)
    }
    // 先清 track1（把上一张表情切过的附件全部还原），避免新表情叠在旧表情残留上
    l.state.clearTrack(1)
    if (exprIndex < exprs.length) {
      l.state.setAnimation(1, exprs[exprIndex], false)
    }
  }
}

function enableInteraction() {
  const canvas = canvasRef.value
  canvas.style.cursor = 'grab'
  canvas.addEventListener('wheel', onCanvasWheel, { passive: false })
  canvas.addEventListener('mousedown', onCanvasDown)
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  // BD2 互动状态随皮肤重建（profile 在首次点击时按动画集探测）
  bd2Profile = null
  bd2FullPlaying = false
  bd2ChainNext = null
  voiceCues = []
  // 预热：皮肤加载阶段就完成动画集探测 + 附件指纹实测（章节配对/motion 终态），
  // 避免首次点击时同步测量造成可感知的卡顿
  if (ensureBd2Profile()) {
    window.BD2Interact.resetMix() // 新皮肤 mix 序列从头开始
  }
  // 注册互动动画完成监听：drag → ex，drag_ex → normal
  for (const l of layers) {
    if (l.skeleton && l.state) {
      l.state.addListener({ complete: onInteractComplete })
    }
  }
  loadVoiceStatus()
  loadHitAreas() // 拉取精确交互区域数据（nagami 数据集，失败静默降级）
}

function onMove(e) {
  if (!drag) return
  drag.lastX = e.clientX
  drag.lastY = e.clientY
  // 版式拖拽调节：拖动实时更新所选目标（人物/背景）的独立偏移（%）
  // y 取反：向下拖 = 画面下方 = 世界坐标 y 减小，符合直觉
  if (drag.target === 'char' || drag.target === 'bg') {
    const canvas = canvasRef.value
    const cw = canvas.clientWidth || 1
    const ch = canvas.clientHeight || 1
    const nx = WL.clampOffset(drag.ox + ((e.clientX - drag.x) / cw) * 100)
    const ny = WL.clampOffset(drag.oy - ((e.clientY - drag.y) / ch) * 100)
    if (drag.target === 'char') emit('charOffsetChange', { x: nx, y: ny })
    else emit('bgOffsetChange', { x: nx, y: ny })
    return
  }
  // 互动模式：拖动不移动画面（只触发 drag 动画反应）
  if (props.interactionMode && isInteractiveSkin()) return
  // 像素级直拖：屏幕坐标 → 世界坐标换算，保证跟手。同时实时上报整体偏移，
  // 让宿主侧 CSS 背景/滑块同步跟随（直拖只动了相机=人物，CSS 背景靠 offsetX
  // 偏移锚点跟随；不上报的话拖动过程中人物动了、背景原地不动）。上报值经
  // spineCamera 重算的相机位置与直拖结果逐像素相等（dx*zoom 项恒等），无跳变。
  const cam = renderer.camera
  const dx = e.clientX - drag.x
  const dy = e.clientY - drag.y
  cam.position.x = drag.camX - dx * drag.zoom
  cam.position.y = drag.camY + dy * drag.zoom
  cam.position.z = 0
  const cw = canvasRef.value.clientWidth || 1
  const ch = canvasRef.value.clientHeight || 1
  emit('panChange', {
    x: WL.clampOffset(drag.ox + (dx / cw) * 100),
    y: WL.clampOffset(drag.oy + (dy / ch) * 100),
  })
}

function onUp() {
  if (!drag) return
  const canvas = canvasRef.value
  const cw = canvas.clientWidth || 1
  const ch = canvas.clientHeight || 1
  const lx = drag.lastX != null ? drag.lastX : drag.x
  const ly = drag.lastY != null ? drag.lastY : drag.y
  // 版式拖拽调节：松手时取整定值（滑块显示对齐），实时过程已按浮点跟手
  if (drag.target === 'char' || drag.target === 'bg') {
    const target = drag.target
    const nx = Math.round(WL.clampOffset(drag.ox + ((lx - drag.x) / cw) * 100))
    const ny = Math.round(WL.clampOffset(drag.oy - ((ly - drag.y) / ch) * 100))
    drag = null
    canvas.style.cursor = 'grab'
    if (target === 'char') emit('charOffsetChange', { x: nx, y: ny })
    else emit('bgOffsetChange', { x: nx, y: ny })
    return
  }
  const ox = Math.round(WL.clampOffset(drag.ox + ((lx - drag.x) / cw) * 100))
  const oy = Math.round(WL.clampOffset(drag.oy + ((ly - drag.y) / ch) * 100))
  drag = null
  canvas.style.cursor = 'grab'
  // 互动模式：拖动只触发动画，不平移画面
  if (props.interactionMode && isInteractiveSkin()) return
  emit('panChange', { x: ox, y: oy })
}

onMounted(async () => {
  try {
    const canvas = canvasRef.value
    canvas.width = canvas.clientWidth
    canvas.height = canvas.clientHeight
    gl =
      canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true }) ||
      canvas.getContext('experimental-webgl', { alpha: true })
    if (!gl) throw new Error('WebGL not supported')
    renderer = new spine.SceneRenderer(canvas, gl, false)
    const cfgs = props.skin.asset.layers || []
    const loaded = await Promise.all(
      cfgs.map((c) => (c.bg ? loadBg(c) : loadLayer(c))),
    )
    // 卸载发生在材质加载期间：不能再用已卸载的 canvas / GL 上下文
    if (disposed) return
    layers = loaded
    buildPhaseMaps() // 阶段骨架映射（多章约会皮 skel_sets；无则空操作）
    await initBgSets() // 多阶段背景异步预载，在 computeBounds 之前就绪（保证与导出端取景一致）
    // 骨架层播放动画；背景图层无骨架，跳过
    const skelLayers = loaded.filter((l) => l.skeleton)
    // 互动皮肤：开场播 login（一次）→ 播完自动切 normal 循环；无 login 则直接
    // normal 待机。上层页面切皮肤时 animation 默认为 'normal'，走开场逻辑；
    // 显式选了其他动画则直接播放。
    // 关键顺序：必须先用 normal 待机姿态构建取景缓存（computeBounds/适配），
    // 再切入 login——login 的 t=0 姿态含巨大转场件会让取景框算得巨大、相机
    // 拉远导致画面比例完全错位（手动切换正常正是因为那时取景已按 normal 缓存）。
    const defaultIdle = !props.animation || /^(normal|idle)$/i.test(props.animation)
    if (isInteractiveSkin() && defaultIdle) {
      // 1) 以 normal 待机姿态建立稳定的边界缓存与人物适配
      playInteractAnim('normal', true)
      for (const l of skelLayers) {
        l.state.update(0)
        l.state.apply(l.skeleton)
        l.skeleton.updateWorldTransform()
      }
      // 画幅遮罩插槽标记（约会皮 FR/BK/black/hit_cut_BG 巨型围板）：取景前打标
      markMaskSlots()
      applyCharacterFit()
      computeBounds()
      // 2) 再切入 login 开场（不重算取景，沿用 normal 的框）；
      //    intro 关闭时跳过 login，保持 normal 待机
      if (hasAnim('login') && props.intro) {
        playInteractAnim('login', false)
      }
    } else {
      playAnimation(props.animation || '')
      for (const l of skelLayers) {
        l.state.update(0)
        l.state.apply(l.skeleton)
        l.skeleton.updateWorldTransform()
      }
      markMaskSlots()
      applyCharacterFit()
      computeBounds()
    }
    // 记录角色独立偏移的基准位置（applyCharacterFit 之后）：渲染循环按
    // charBaseX/Y + 偏移 计算，背景层不参与（isBgLayer 判定）。
    for (const l of skelLayers) {
      l.charBaseX = l.skeleton.x
      l.charBaseY = l.skeleton.y
    }
    const anims = [...new Set(skelLayers.flatMap((l) => l.data.animations.map((a) => a.name)))]
    emit('animations', anims)
    applyLayout()
    enableInteraction()
    lastFrame = performance.now() / 1000
    emit('ready')
    raf = requestAnimationFrame(render)
  } catch (e) {
    if (!disposed) emit('error', e.message || String(e))
  }
})

// keep-alive 缓存（图鉴页）下切走时暂停渲染循环；切回时恢复
onDeactivated(() => {
  paused = true
  cancelAnimationFrame(raf)
  raf = 0
})
onActivated(() => {
  paused = false
  if (!disposed && layers.length && !raf) {
    lastFrame = performance.now() / 1000
    raf = requestAnimationFrame(render)
  }
})

onBeforeUnmount(() => {
  disposed = true
  paused = false
  cancelAnimationFrame(raf)
  raf = 0
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (canvasRef.value) {
    canvasRef.value.removeEventListener('wheel', onCanvasWheel)
    canvasRef.value.removeEventListener('mousedown', onCanvasDown)
  }
  // 背景纹理缓存随上下文一起释放：keep-alive 复活后旧 GLTexture 指向
  // 已销毁的上下文，复用会报错/花屏
  if (bgTexCache) {
    bgTexCache.dispose?.()
    bgTexCache = null
  }
  if (gl && renderer) renderer.dispose()
})

defineExpose({
  capture: () => {
    try {
      return canvasRef.value ? canvasRef.value.toDataURL('image/png') : null
    } catch (e) {
      return null
    }
  },
})
</script>

<style scoped>
.spine-wrap {
  position: relative;
  width: 100%;
  height: 100%;
}
.spine-canvas {
  width: 100%;
  height: 100%;
  display: block;
  touch-action: none;
  user-select: none;
}
.spine-hit-overlay {
  position: absolute;
  border: 2px dashed rgba(74, 111, 165, 0.65);
  background: rgba(74, 111, 165, 0.08);
  border-radius: 8px;
  color: #4a6fa5;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 4px;
  pointer-events: none;
  box-sizing: border-box;
  text-shadow: 0 1px 3px rgba(255, 255, 255, 0.7);
}
.spine-dbg {
  position: absolute;
  top: 2px;
  left: 2px;
  z-index: 5;
  background: rgba(10, 14, 20, 0.75);
  color: #9fe09f;
  font: 10px/1.4 ui-monospace, Consolas, monospace;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  pointer-events: none;
}
.spine-dbg.hidden { display: none; }
</style>

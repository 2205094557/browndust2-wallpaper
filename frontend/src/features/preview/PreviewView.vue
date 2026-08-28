<template>
  <div class="preview-page">
    <n-spin :show="loading" style="width: 100%; height: 100%">
      <template v-if="!ship && loadError">
        <div class="preview-load-error">
          <n-alert type="error" :show-icon="true">加载失败：{{ loadError }}</n-alert>
          <n-button style="margin-top: 12px" @click="router.push('/gallery')">返回图鉴</n-button>
        </div>
      </template>
      <template v-if="ship && currentSkin">
        <div class="preview-topbar">
          <n-button quaternary circle @click="router.push('/gallery')">←</n-button>
          <div class="preview-heading">
            <strong>{{ ship.name }}</strong>
            <span class="en">{{ ship.en }}</span>
            <span class="wc-pill green">Spine</span>
          </div>
          <n-button type="primary" @click="drawer = true">导出壁纸</n-button>
        </div>

        <div class="preview-body">
          <div ref="stageWrapRef" class="stage-wrap">
          <div ref="stageRef" class="preview-stage" :class="`bg-${bgStyle}`" :style="autoBgStyle">
              <n-alert
                v-if="engineError"
                type="error"
                :show-icon="true"
                closable
                class="engine-error"
                @close="engineError = ''"
              >
                预览引擎加载失败：{{ engineError }}
              </n-alert>
              <SpinePreview
                v-if="currentSkin.type === 'spine' && currentSkin.asset"
                :key="currentSkin.key"
                :skin="currentSkin"
                :animation="animation"
                :scale="scale"
                :bg-scale="bgScale"
                :offset-x="offsetX"
                :offset-y="offsetY"
                :alignment="alignment"
                :interaction-mode="interactionMode"
                :show-hit-areas="showHitAreas"
                :intro="introOn"
                @animations="onSpineAnims"
                @error="onEngineError"
                @scale-change="scale = $event"
                @pan-change="offsetX = $event.x; offsetY = $event.y"
                @subtitle="l2dSubtitle = $event"
              />
              <div v-else class="preview-placeholder">
                <div class="preview-halo"></div>
                <div class="preview-title">{{ ship.name }} · {{ currentSkin.name }}</div>
                <div class="preview-sub">
                  {{ currentSkin.status === 'remote' ? '未下载（下载后可预览）' : '引擎占位' }}
                </div>
              </div>
              <span class="zoom-hint">缩放 {{ scale }}%</span>
            </div>
          </div>

          <aside class="control-panel">
            <div class="panel-title">皮肤</div>
            <div class="skin-strip">
              <div
                v-for="(skin, i) in ship.skins"
                :key="skin.key"
                class="skin-chip"
                :class="{ active: i === currentIndex }"
                @click="currentIndex = i"
              >
                {{ skin.name }}
              </div>
            </div>

            <div class="panel-title">背景样式</div>
            <n-select v-model:value="bgStyle" :options="bgOptions" />
            <input
              v-if="bgStyle === 'solid'"
              v-model="solidColor"
              type="color"
              class="solid-picker"
              title="自定义纯色背景"
            />

            <div class="panel-title">动画</div>
            <n-select v-model:value="animation" :options="animOptions" :disabled="!animOptions.length" placeholder="无可用动画" />
            <div v-if="animOptions.length" class="anim-nav">
              <n-button size="small" quaternary circle @click="stepAnim(-1)">←</n-button>
              <span class="anim-nav-label">{{ animIndex + 1 }} / {{ animOptions.length }}</span>
              <n-button size="small" quaternary circle @click="stepAnim(1)">→</n-button>
            </div>

            <div class="panel-title">缩放</div>
            <n-slider v-model:value="scale" :min="20" :max="300" :step="5" />
            <div class="panel-title" title="独立调节背景图大小（100 = 默认铺满取景框）">背景缩放</div>
            <div class="bgscale-row">
              <n-slider v-model:value="bgScale" :min="30" :max="300" :step="5" style="flex: 1" />
              <n-button size="tiny" quaternary @click="bgScale = 100">重置</n-button>
            </div>
            <span class="zoom-hint" style="position: static; display: block; margin-top: -4px">角色 {{ scale }}% · 背景 {{ bgScale }}%</span>

            <div v-if="currentSkin.type === 'spine'" class="panel-title">交互模式</div>
            <div v-if="currentSkin.type === 'spine'" class="mode-toggle">
              <span class="mode-pill" :class="{ active: !interactionMode }" @click="interactionMode = false">拖拽</span>
              <span class="mode-pill" :class="{ active: interactionMode }" @click="interactionMode = true">互动</span>
              <span class="mode-pill" :class="{ active: voiceEnabled }" :title="voiceEnabled ? '关闭互动语音与台词' : '开启互动语音与台词'" @click="toggleVoice">
                {{ voiceEnabled ? '🔊 语音' : '🔇 语音' }}
              </span>
            </div>
            <div v-if="currentSkin.type === 'spine'" class="l2d-subtitle-box" :class="{ empty: !l2dSubtitle }">
              {{ l2dSubtitle || '点击角色互动，台词显示在这里' }}
            </div>
            <div v-if="currentSkin.type === 'spine'" class="mode-toggle" style="margin-top: 6px">
              <span
                class="mode-pill"
                :class="{ active: showHitAreas }"
                @click="showHitAreas = !showHitAreas"
              >显示交互区域</span>
              <span
                class="mode-pill"
                :class="{ active: introOn }"
                :title="introOn ? '关闭开场动画' : '开启开场动画'"
                @click="introOn = !introOn"
              >{{ introOn ? '🎬 开场' : '🎬 开场关' }}</span>
            </div>

            <div class="panel-title">多骨架分层</div>
            <n-checkbox v-model:checked="layersVisible">显示 _T / _B / _M 分层</n-checkbox>

            <n-button type="primary" block style="margin-top: 18px" @click="drawer = true">
              导出为壁纸
            </n-button>
          </aside>
        </div>

        <n-drawer v-model:show="drawer" :width="430" placement="right">
          <n-drawer-content title="导出壁纸" closable>
            <div class="export-form">
              <label>壁纸类型</label>
              <n-select value="spine" :options="[
                { label: 'Spine 动态壁纸', value: 'spine' },
              ]" disabled />

              <label>背景样式</label>
              <n-select v-model:value="bgStyle" :options="bgOptions" />
              <input
                v-if="bgStyle === 'solid'"
                v-model="solidColor"
                type="color"
                class="solid-picker"
                title="自定义纯色背景"
              />

              <label>缩放</label>
              <n-slider v-model:value="scale" :min="20" :max="300" :step="5" />
              <span class="bar-dim">缩放 {{ scale }}%（100 = 自适应）</span>

              <label>背景缩放（独立）</label>
              <n-slider v-model:value="bgScale" :min="30" :max="300" :step="5" />
              <span class="bar-dim">背景 {{ bgScale }}%（100 = 铺满取景框）</span>

              <label>水平偏移（占画布宽 %）</label>
              <n-slider v-model:value="offsetX" :min="-100" :max="100" :step="1" />

              <label>垂直偏移（占画布高 %）</label>
              <n-slider v-model:value="offsetY" :min="-100" :max="100" :step="1" />

              <label>对齐方式</label>
              <n-select v-model:value="alignment" :options="[
                { label: '居中', value: 'center' },
                { label: '左上', value: 'left-top' },
                { label: '右上', value: 'right-top' },
                { label: '左下', value: 'left-bottom' },
                { label: '右下', value: 'right-bottom' },
              ]" />

              <n-button type="primary" block :loading="exporting" @click="doExport">
                {{ exporting ? '导出中…' : '导出' }}
              </n-button>

              <n-button type="success" block style="margin-top: 8px" :loading="applying" @click="doApply">
                {{ applying ? '正在导出并应用…' : '导出并应用' }}
              </n-button>

              <template v-if="applyDone">
                <n-alert v-if="applyResult && applyResult.ok" type="success" :show-icon="true">
                  已应用：{{ applyResult.project }}
                  <br />
                  壁纸已直接应用到桌面（以当前预览的缩放/偏移为准）
                </n-alert>
                <n-alert v-else type="error" :show-icon="true">
                  应用失败：{{ (applyResult && applyResult.error) || '未知错误' }}
                </n-alert>
              </template>

              <template v-if="exportDone">
                <n-alert v-if="exportResult && exportResult.ok" type="success" :show-icon="true">
                  导出完成：{{ exportResult.project }}
                  <br />
                  已打开文件夹，请把 index.html 拖入 Wallpaper Engine
                </n-alert>
                <n-alert v-else type="error" :show-icon="true">
                  导出失败：{{ (exportResult && exportResult.error) || '未知错误' }}
                </n-alert>
              </template>
            </div>
          </n-drawer-content>
        </n-drawer>
      </template>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NSpin, NSelect, NSlider, NCheckbox,
  NDrawer, NDrawerContent, NAlert,
} from 'naive-ui'
import { bridge } from '../../bridge'
import { voiceEnabled, toggleVoice } from '../../utils/voice'
import SpinePreview from '../../components/SpinePreview.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const loadError = ref('')
const engineError = ref('')
const ship = ref(null)
const currentIndex = ref(0)
const drawer = ref(false)
const exporting = ref(false)
const exportDone = ref(false)
const exportResult = ref(null)
const applying = ref(false)
const applyDone = ref(false)
const applyResult = ref(null)

const bgStyle = ref('auto')
const animation = ref('normal')
const animOptions = ref([])
const scale = ref(100)
const bgScale = ref(100)
const offsetX = ref(0)
const offsetY = ref(0)
const alignment = ref('center')
const layersVisible = ref(true)
const interactionMode = ref(false)
const l2dSubtitle = ref('')
const showHitAreas = ref(false)
const introOn = ref(true)
const stageWrapRef = ref(null)
const stageRef = ref(null)
let stageRO = null

const STAGE_RATIO = 16 / 9

function fitStage() {
  const wrap = stageWrapRef.value
  const stage = stageRef.value
  if (!wrap || !stage) return
  const w = wrap.clientWidth
  const h = wrap.clientHeight
  if (!w || !h) return
  let sw = w
  let sh = sw / STAGE_RATIO
  if (sh > h) {
    sh = h
    sw = sh * STAGE_RATIO
  }
  stage.style.width = `${Math.floor(sw)}px`
  stage.style.height = `${Math.floor(sh)}px`
}

const bgOptions = [
  { label: '自动取色', value: 'auto' },
  { label: '纯色', value: 'solid' },
  { label: '莫奈渐变', value: 'monet' },
  { label: '毛玻璃', value: 'frost' },
  { label: '星空', value: 'star' },
]

const currentSkin = computed(() => ship.value?.skins[currentIndex.value] || null)
// 切换皮肤时清空右侧面板台词，避免残留上一个皮肤的语音文本
//（watch 注册时会立即求值一次 getter，必须放在 currentSkin 定义之后）
watch(
  () => currentSkin.value && currentSkin.value.key,
  () => { l2dSubtitle.value = '' },
)

const bgCss = ref('')
const solidColor = ref('')
const autoBgStyle = computed(() =>
  bgCss.value ? { background: bgCss.value } : {},
)

let bgSeq = 0
async function refreshBg() {
  const skin = currentSkin.value
  if (!skin) return
  const seq = ++bgSeq
  const res = await bridge.getPalette(skin.ship, skin.bundle, skin.name, {
    mode: bgStyle.value,
    bgColor: bgStyle.value === 'solid' ? solidColor.value || undefined : undefined,
  })
  if (seq !== bgSeq) return // 已有更新的取色请求：丢弃过期结果，避免旧皮肤/旧设置的颜色串到新皮肤上
  const raw = res && typeof res.css === 'string' ? res.css : ''
  // 后端返回的是完整声明（background: ...;），存进 CSS 变量时只保留值部分
  bgCss.value = raw.replace(/^background:\s*/, '').replace(/;\s*$/, '')
}

watch(currentSkin, () => refreshBg(), { immediate: true })
watch(bgStyle, () => refreshBg())
watch(solidColor, () => refreshBg())

function onSpineAnims(names) {
  animOptions.value = names.map((n) => ({ label: n, value: n }))
  if (!animation.value || !names.includes(animation.value)) {
    animation.value =
      names.find((n) => /^idle$/i.test(n)) || names.find((n) => n === 'home') || names[0] || ''
  }
}

const animIndex = computed(() => {
  const i = animOptions.value.findIndex((o) => o.value === animation.value)
  return i >= 0 ? i : 0
})

function stepAnim(dir) {
  const n = animOptions.value.length
  if (!n) return
  const next = (animIndex.value + dir + n) % n
  animation.value = animOptions.value[next].value
}

function onKeydown(e) {
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
  if (t && t.closest && t.closest('.n-select')) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  if (animOptions.value.length) {
    e.preventDefault()
    stepAnim(e.key === 'ArrowLeft' ? -1 : 1)
  }
}

function onEngineError(msg) {
  console.error('[preview]', msg)
  engineError.value = msg || '未知错误'
}

let loadSeq = 0
async function loadShip(id) {
  loading.value = true
  loadError.value = ''
  const seq = ++loadSeq
  try {
    ship.value = await bridge.getShip(id)
    if (seq !== loadSeq) return // 快速切换角色时丢弃过期响应，避免旧数据覆盖新数据
    currentIndex.value = 0
    animOptions.value = []
  } catch (e) {
    if (seq !== loadSeq) return
    ship.value = null
    loadError.value = e.message || '加载失败'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch(
  () => route.params.shipId,
  (id) => {
    if (id) loadShip(id)
  },
)

onMounted(() => {
  const wrap = stageWrapRef.value
  if (wrap) {
    fitStage()
    stageRO = new ResizeObserver(fitStage)
    stageRO.observe(wrap)
  }
  loadShip(route.params.shipId)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (stageRO) stageRO.disconnect()
  window.removeEventListener('keydown', onKeydown)
})

async function doExport() {
  const skin = currentSkin.value
  if (!skin) return
  exporting.value = true
  exportDone.value = false
  exportResult.value = null
  try {
    exportResult.value = await bridge.exportWallpaper(skin.ship, skin.bundle, skin.name, {
      bg: bgStyle.value,
      bgColor: bgStyle.value === 'solid' ? solidColor.value || undefined : undefined,
      scale: scale.value,
      bgScale: bgScale.value,
      offsetX: offsetX.value,
      offsetY: offsetY.value,
      alignment: alignment.value,
      animation: animation.value,
      // 预览页当前开关状态 → WE 侧默认值（编辑导入会覆盖，但一键应用保留）
      voice: voiceEnabled.value,
      intro: introOn.value,
      interact: true,
      showHitAreas: showHitAreas.value,
    })
  } catch (e) {
    exportResult.value = { ok: false, error: e.message || '导出失败' }
  } finally {
    exporting.value = false
    exportDone.value = true
  }
}

async function doApply() {
  const skin = currentSkin.value
  if (!skin) return
  applying.value = true
  applyDone.value = false
  applyResult.value = null
  try {
    applyResult.value = await bridge.applyWallpaper(skin.ship, skin.bundle, skin.name, {
      bg: bgStyle.value,
      bgColor: bgStyle.value === 'solid' ? solidColor.value || undefined : undefined,
      scale: scale.value,
      bgScale: bgScale.value,
      offsetX: offsetX.value,
      offsetY: offsetY.value,
      alignment: alignment.value,
      animation: animation.value,
      // 预览页当前开关状态 → WE 侧默认值（一键应用保留，不会被编辑导入历史值覆盖）
      voice: voiceEnabled.value,
      intro: introOn.value,
      interact: true,
      showHitAreas: showHitAreas.value,
    })
  } catch (e) {
    applyResult.value = { ok: false, error: e.message || '导出并应用失败' }
  } finally {
    applying.value = false
    applyDone.value = true
  }
}

</script>

<style scoped>
.preview-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.engine-error {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 5;
  max-width: 90%;
}

.preview-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.86);
  backdrop-filter: blur(6px);
}

.preview-heading {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.preview-heading strong {
  font-family: var(--font-serif);
  font-weight: 300;
  letter-spacing: 2px;
  font-size: 19px;
}

.preview-heading .en {
  color: var(--muted);
  font-size: 13px;
}

.preview-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 280px;
  min-height: 0;
}

.stage-wrap {
  min-height: 0;
  overflow: hidden;
  display: grid;
  place-items: center;
}

.zoom-hint {
  position: absolute;
  right: 16px;
  bottom: 14px;
  color: rgba(255, 255, 255, 0.55);
  font-size: 12px;
  background: rgba(0, 0, 0, 0.35);
  padding: 3px 10px;
  border-radius: 999px;
}

.control-panel {
  border-left: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.9);
  padding: 20px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 右侧控制面板台词文本框 */
.l2d-subtitle-box {
  max-height: 120px;
  overflow-y: auto;
  box-sizing: border-box;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #fff;
  background: rgba(10, 14, 24, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 10px;
  text-align: center;
}

.l2d-subtitle-box.empty {
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
}

.anim-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.anim-nav-label {
  color: var(--muted);
  font-size: 12px;
  min-width: 52px;
  text-align: center;
}

.mode-toggle {
  display: flex;
  gap: 6px;
  background: rgba(74, 111, 165, 0.1);
  border-radius: 999px;
  padding: 3px;
}

.mode-pill {
  flex: 1;
  text-align: center;
  font-size: 12px;
  line-height: 26px;
  border-radius: 999px;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
  transition: color 0.25s ease;
}

.mode-pill.active {
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.92), rgba(133, 205, 202, 0.85));
  color: #fff;
  box-shadow: 0 4px 14px rgba(74, 111, 165, 0.35);
  font-weight: 500;
}

.panel-title {
  color: var(--muted);
  font-size: 12px;
  margin-top: 8px;
}

.bgscale-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skin-strip {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.export-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.export-form label {
  color: var(--muted);
  font-size: 12px;
  margin-top: 4px;
}

/* 导出可切换动画多选：选中的标签改成圆润渐变淡色药丸 */
.anim-multi :deep(.n-base-selection-tag-wrapper .n-tag) {
  border-radius: 999px !important;
  border: 1px solid rgba(74, 111, 165, 0.28) !important;
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.14), rgba(133, 205, 202, 0.2)) !important;
  color: #3f5f8f;
}
.anim-multi :deep(.n-base-selection-tag-wrapper .n-tag .n-tag__close) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0 2px 0 4px;
  padding: 0;
  font-size: 14px;
  color: rgba(63, 95, 143, 0.7);
}
</style>

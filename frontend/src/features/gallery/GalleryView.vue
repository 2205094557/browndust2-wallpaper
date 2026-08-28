<template>
  <div class="main-view" :class="{ 'is-fullscreen': fullscreen }">
    <!-- 顶栏 -->
    <header class="main-topbar" v-if="!fullscreen">
      <div class="main-title">
        <h1>棕色尘埃2 · 壁纸工坊</h1>
        <span v-if="skinMode">共 {{ filteredSkins.length }} 个皮肤</span>
        <span v-else>共 {{ filtered.length }} 人 · {{ totalSkins }} 个皮肤</span>
      </div>
    </header>

    <div class="main-body">
      <!-- 左侧角色库 -->
      <aside class="ship-rail" v-if="!fullscreen">
        <n-input v-model:value="searchInput" placeholder="角色名 / 皮肤…" clearable size="small">
          <template #prefix>🔍</template>
        </n-input>
        <div class="rail-tools">
          <span class="rail-tool" :class="{ active: favOnly }" @click="favOnly = !favOnly">
            {{ favOnly ? '★ 只看收藏中' : '☆ 只看收藏' }}
          </span>
          <span class="rail-tool" :class="{ active: multiMode }" @click="toggleMulti">
            {{ multiMode ? '✓ 多选中' : '多选' }}
          </span>
        </div>
        <div class="filter-panel">
          <div class="filter-field">
            <label>阵营</label>
            <n-select v-model:value="filters.faction" :options="factionOptions" size="small" clearable placeholder="全部" />
          </div>
          <div class="filter-field">
            <label>类型</label>
            <n-select v-model:value="filters.hull" :options="hullOptions" size="small" clearable placeholder="全部" />
          </div>
          <div class="filter-field">
            <label>动态能力</label>
            <n-select v-model:value="filters.type" :options="typeOptions" size="small" />
          </div>
          <div class="filter-field">
            <label>皮肤系列</label>
            <n-select v-model:value="filters.theme" :options="themeOptions" size="small" clearable filterable placeholder="全部" />
          </div>
          <button class="wc-btn clear-filter-btn" @click="clearFilters">清空筛选</button>
        </div>
        <div ref="railListRef" class="rail-list">
          <template v-if="skinMode">
            <div
              v-for="item in filteredSkins"
              :key="item.skin.key"
              class="rail-card skin-row"
              :class="{ active: currentSkin && currentSkin.key === item.skin.key }"
              @click="onSkinClick(item)"
            >
              <div class="rail-avatar" :style="avatarStyle(item.ship)">
                <img v-if="avatarUrl(item.ship)" :src="avatarUrl(item.ship)" class="rail-avatar-img" @error="onAvatarError(item.ship)" />
                <span v-else class="rail-char">{{ item.ship.name[0] }}</span>
              </div>
              <div class="rail-info">
                <div class="rail-name">{{ item.ship.name }}</div>
                <div class="rail-skin" :title="item.skin.name">{{ item.skin.name }}</div>
                <div class="rail-meta">
                  <span class="wc-pill" :class="item.skin.type === 'spine' ? 'green' : 'blue'">
                    {{ item.skin.type === 'spine' ? 'Spine' : '静态' }}
                  </span>
                </div>
              </div>
              <span v-if="multiMode" class="rail-check" :class="{ on: isSelected(item.skin.key) }">✓</span>
            </div>
          </template>
          <template v-else>
            <div
              v-for="ship in filtered"
              :key="ship.id"
              class="rail-card"
              :class="{ active: ship.id === selectedId }"
              @click="onCardClick(ship)"
            >
              <div class="rail-avatar" :style="avatarStyle(ship)">
                <img v-if="avatarUrl(ship)" :src="avatarUrl(ship)" class="rail-avatar-img" @error="onAvatarError(ship)" />
                <span v-else class="rail-char">{{ ship.name[0] }}</span>
              </div>
              <div class="rail-info">
                <div class="rail-name">{{ ship.name }}</div>
                <div class="rail-meta">
                  <span class="wc-pill" :class="rarityClass(ship.rarity)">{{ ship.rarity }}</span>
                  <span v-for="t in shipTypes(ship)" :key="t" class="wc-pill green">Spine</span>
                </div>
              </div>
              <span v-if="multiMode" class="rail-check" :class="{ on: isSelected(ship.id) }">✓</span>
            </div>
          </template>
        </div>
      </aside>

      <!-- 中央预览区 -->
      <div class="preview-zone">
        <div ref="stageWrapRef" class="stage-wrap">
          <div ref="stageRef" class="preview-stage" :class="`bg-${bgStyle}`" :style="autoBgStyle">
            <SpinePreview
              v-if="currentSkin && currentSkin.type === 'spine' && currentSkin.asset"
              ref="previewEl"
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
            <StaticPreview
              v-else-if="currentSkin && currentSkin.type === 'static' && currentSkin.asset"
              :key="currentSkin.key"
              :skin="currentSkin"
              :scale="scale"
              :offset-x="offsetX"
              :offset-y="offsetY"
              @scale-change="scale = $event"
              @pan-change="offsetX = $event.x; offsetY = $event.y"
              @error="onEngineError"
            />
            <div v-else class="preview-placeholder">
              <div class="preview-halo"></div>
              <div class="preview-title">{{ selectedShip ? selectedShip.name : '选择角色' }} · {{ currentSkin ? currentSkin.name : '' }}</div>
              <div class="preview-sub">
                {{ currentSkin && currentSkin.status === 'remote' ? '未下载（下载后可预览）' : '点击左侧角色开始预览' }}
              </div>
            </div>
            <div v-if="selectedShip && currentSkin" class="stage-info">
              <span class="stage-info-name">{{ selectedShip.name }}</span>
              <span class="stage-info-skin">{{ currentSkin.name }}</span>
            </div>
            <div v-if="currentSkin && (currentSkin.type === 'spine')" class="l2d-panel-a" :class="{ collapsed: l2dPanelCollapsed }">
              <div class="l2d-panel-a-head">
                <span class="l2d-panel-a-title"><span class="l2d-panel-a-dot"></span>互动控制</span>
                <button class="l2d-panel-a-collapse" :title="l2dPanelCollapsed ? '展开互动面板' : '收起互动面板'" @click="l2dPanelCollapsed = !l2dPanelCollapsed">
                  {{ l2dPanelCollapsed ? '⚙' : '−' }}
                </button>
              </div>
              <div v-if="!l2dPanelCollapsed" class="l2d-panel-a-body">
                <div class="l2d-seg" :class="{ 'on-interact': interactionMode }">
                  <div class="l2d-seg-thumb"></div>
                  <button class="l2d-seg-item" :class="{ active: !interactionMode }" @click="interactionMode = false">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/></svg>
                    拖拽
                  </button>
                  <button class="l2d-seg-item" :class="{ active: interactionMode }" @click="interactionMode = true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 11v-2a2 2 0 0 1 4 0v2M7 11h4M9 11v5M13 8a2 2 0 0 1 4 0v4M15 12v5"/><path d="M15 12h2a2 2 0 0 1 2 2v2a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5v-1"/></svg>
                    互动
                  </button>
                </div>
                <div v-if="currentSkin.type === 'spine'" class="l2d-switch-row">
                  <div class="l2d-switch-txt" style="width:100%">
                    <small v-if="spineInteractive" style="color:#4a6fa5">✓ 该皮肤支持拖拽互动：拖动角色播放 drag 反应动画</small>
                    <small v-else style="opacity:.75">该皮肤无拖拽动画，互动模式下点击可切换表情</small>
                  </div>
                </div>
                <div class="l2d-switch-row">
                  <span class="l2d-switch-ico" :class="{ on: voiceEnabled }">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>
                  </span>
                  <div class="l2d-switch-txt">互动语音<small>点击角色时播放台词</small></div>
                  <span class="l2d-switch" :class="{ on: voiceEnabled }" :title="voiceEnabled ? '关闭互动语音与台词' : '开启互动语音与台词'" @click="toggleVoice"></span>
                </div>
                <div v-if="currentSkin.type === 'spine'" class="l2d-switch-row">
                  <span class="l2d-switch-ico" :class="{ on: showHitAreas }">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>
                  </span>
                  <div class="l2d-switch-txt">交互区域<small>显示点击可触发区域</small></div>
                  <span class="l2d-switch" :class="{ on: showHitAreas }" :title="showHitAreas ? '隐藏交互区域' : '显示交互区域'" @click="showHitAreas = !showHitAreas"></span>
                </div>
                <div v-if="currentSkin.type === 'spine' && spineHasLogin" class="l2d-switch-row">
                  <span class="l2d-switch-ico" :class="{ on: introOn }">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4v16l13-8-13-8z"/></svg>
                  </span>
                  <div class="l2d-switch-txt">
                    开场动画
                    <small>login 入场播一次再回待机</small>
                  </div>
                  <span class="l2d-switch" :class="{ on: introOn }" :title="introOn ? '关闭开场动画' : '开启开场动画'" @click="introOn = !introOn"></span>
                </div>
                <div class="l2d-subtitle-a" :class="{ empty: !l2dSubtitle }">
                  <span v-if="l2dSubtitle" class="l2d-subtitle-a-who">{{ selectedShip ? selectedShip.name : '' }} · {{ currentSkin ? currentSkin.name : '' }}</span>
                  {{ l2dSubtitle || '点击角色互动，台词显示在这里' }}
                </div>
              </div>
            </div>
            <span class="zoom-hint">角色 {{ scale }}% · 背景 {{ bgScale }}%</span>
            <button class="stage-fullscreen-btn" @click="toggleFullscreen" :title="fullscreen ? '退出全屏' : '全屏预览'">
              {{ fullscreen ? '✕' : '⛶' }}
            </button>
          </div>
        </div>

        <!-- 皮肤切换条 -->
        <div class="skin-bar">
          <div class="skin-strip">
            <div
              v-for="(skin, i) in (selectedShip ? selectedShip.skins : [])"
              :key="skin.key"
              class="skin-chip"
              :class="{ active: i === currentSkinIndex }"
              @click="currentSkinIndex = i"
            >
              {{ skin.name }}
            </div>
            <span v-if="selectedShip && !selectedShip.skins.length" class="bar-dim">无皮肤</span>
          </div>
          <div class="skin-status">
            <template v-if="selectedShip">
              <button
                v-if="currentSkin && currentSkin.status === 'remote' && canDownload(currentSkin)"
                class="wc-btn gradient dl-btn"
                :disabled="downloading"
                @click="downloadCurrent"
              >
                {{ downloading ? '下载中…' : '下载当前' }}
              </button>
              <span v-else-if="currentSkin && currentSkin.status === 'downloaded'" class="dl-ok">✓ 当前已下载</span>
              <span v-else-if="currentSkin && currentSkin.status === 'remote' && !canDownload(currentSkin)" class="bar-dim">
                暂不支持
              </span>
              <button
                v-if="hasRemote(selectedShip)"
                class="wc-btn gradient dl-btn"
                :disabled="allDownloading"
                @click="downloadAll"
              >
                {{ allDownloading ? `下载全部 ${allDone}/${allTotal}` : '下载全部' }}
              </button>
              <button
                v-if="currentSkin"
                class="skin-fav-btn"
                :class="{ on: isSkinFav(currentSkin.key) }"
                :title="isSkinFav(currentSkin.key) ? '取消收藏该皮肤' : '收藏该皮肤'"
                @click="toggleSkinFav(currentSkin.key)"
              >
                {{ isSkinFav(currentSkin.key) ? '★' : '☆' }}
              </button>
            </template>
          </div>
        </div>
      </div>

      <!-- 右侧控制面板 -->
      <aside class="control-panel" v-if="!fullscreen">
        <div class="panel-card">
          <div class="panel-title">外观</div>
          <div class="panel-field">
            <label>背景</label>
            <div class="panel-row">
              <n-select v-model:value="bgStyle" :options="bgOptions" size="small" style="flex: 1" />
              <input
                v-if="bgStyle === 'solid'"
                v-model="solidColor"
                type="color"
                class="solid-picker"
                title="自定义纯色背景"
              />
            </div>
          </div>
          <div class="panel-field">
            <label>动画</label>
            <n-select
              v-model:value="animation"
              :options="animOptions"
              size="small"
              :disabled="!animOptions.length"
              placeholder="无"
              style="width: 100%"
            />
            <div v-if="animOptions.length" class="anim-nav">
              <button class="wc-btn anim-nav-btn" @click="stepAnim(-1)">←</button>
              <span class="anim-nav-label">{{ animIndex + 1 }} / {{ animOptions.length }}</span>
              <button class="wc-btn anim-nav-btn" @click="stepAnim(1)">→</button>
            </div>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-title">导出</div>
          <template v-if="currentSkin">
            <div class="panel-field" v-if="currentSkin.type !== 'static'">
              <label>壁纸类型</label>
              <n-select
                value="spine"
                :options="[{ label: 'Spine 动态壁纸', value: 'spine' }]"
                size="small"
                disabled
              />
            </div>
            <div class="panel-field">
              <label>水平偏移（占画布宽 %）</label>
              <div class="offset-row">
                <n-slider v-model:value="offsetX" :min="-100" :max="100" :step="1" />
                <span class="bar-value" :class="{ zero: offsetX === 0 }">{{ offsetX > 0 ? '+' : '' }}{{ offsetX }}</span>
              </div>
            </div>
            <div class="panel-field">
              <label>垂直偏移（占画布高 %）</label>
              <div class="offset-row">
                <n-slider v-model:value="offsetY" :min="-100" :max="100" :step="1" />
                <span class="bar-value" :class="{ zero: offsetY === 0 }">{{ offsetY > 0 ? '+' : '' }}{{ offsetY }}</span>
              </div>
            </div>
            <div class="panel-field">
              <label>缩放 <span class="bar-dim">{{ scale }}%</span></label>
              <n-slider v-model:value="scale" :min="20" :max="300" :step="5" />
            </div>
            <div class="panel-field">
              <label title="独立调节背景图大小（100 = 默认铺满取景框）">背景缩放 <span class="bar-dim">{{ bgScale }}%</span></label>
              <div class="offset-row">
                <n-slider v-model:value="bgScale" :min="30" :max="300" :step="5" />
                <button class="wc-btn reset-bgscale" @click="bgScale = 100" title="重置背景缩放">重置</button>
              </div>
            </div>
            <div class="panel-field">
              <label>对齐方式</label>
              <n-select
                v-model:value="alignment"
                :options="[
                  { label: '居中', value: 'center' },
                  { label: '左上', value: 'left-top' },
                  { label: '右上', value: 'right-top' },
                  { label: '左下', value: 'left-bottom' },
                  { label: '右下', value: 'right-bottom' },
                ]"
                size="small"
                style="width: 100%"
              />
            </div>
            <div class="panel-field">
              <button class="wc-btn preset-import-btn" @click="openPresetImport">📥 导入 WE 预设 JSON</button>
            </div>
            <n-modal v-model:show="presetImportOpen" preset="card" title="导入 Wallpaper Engine 预设" style="width: 520px; max-width: 92vw">
              <p class="dim" style="margin-bottom: 10px">
                在 Wallpaper Engine 属性面板点「分享预设」复制内容（JSON 或 Base64 均可），
                粘贴到下面，即可把 缩放 / 偏移 / 对齐 / 语音 / 鼠标追踪 / 开场动画 应用到当前预览。
              </p>
              <n-input
                v-model:value="presetImportText"
                type="textarea"
                :rows="8"
                placeholder='{"scalectrl": 244, "offsetx": 8, "offsety": 4, "alignment": "center", "voice": true, "playintro": true}'
                style="font-family: var(--font-mono, Consolas, monospace); font-size: 12px"
              />
              <div class="preset-modal-actions">
                <n-button size="small" @click="presetImportOpen = false">取消</n-button>
                <n-button size="small" type="primary" @click="applyWePreset">应用</n-button>
              </div>
            </n-modal>
            <div class="export-actions">
              <button
                v-if="currentSkin.asset"
                class="wc-btn gradient block"
                :disabled="!currentSkin.asset || imageExporting"
                @click="doExportImage"
              >
                {{ imageExporting ? '导出中…' : '🖼 导出图片' }}
              </button>
              <button
                v-if="currentSkin.type !== 'static'"
                class="wc-btn gradient block"
                :disabled="!currentSkin.asset || exporting"
                @click="doExport"
              >
                {{ exporting ? '导出中…' : '导出壁纸' }}
              </button>
              <button class="wc-btn gradient block" :disabled="!currentSkin.asset || applying" @click="doApply">
                {{ applying ? '正在导出并应用…' : '导出并应用' }}
              </button>
            </div>
            <p v-if="currentSkin && !currentSkin.asset" class="panel-tip">请先下载该皮肤，再导出壁纸</p>
            <template v-if="applyDone">
              <n-alert v-if="applyResult && applyResult.ok" type="success" :show-icon="true" class="export-alert">
                已应用：{{ applyResult.project }}
              </n-alert>
              <n-alert v-else type="error" :show-icon="true" class="export-alert">
                应用失败：{{ (applyResult && applyResult.error) || '未知错误' }}
              </n-alert>
            </template>
            <template v-if="exportDone">
              <n-alert v-if="exportResult && exportResult.ok" type="success" :show-icon="true" class="export-alert">
                导出完成：{{ exportResult.project }}
              </n-alert>
              <n-alert v-else type="error" :show-icon="true" class="export-alert">
                导出失败：{{ (exportResult && exportResult.error) || '未知错误' }}
              </n-alert>
            </template>
          </template>
        </div>

        <div class="panel-card">
          <div class="panel-title">其他功能</div>
          <div class="panel-nav">
            <button
              class="wc-btn panel-nav-btn"
              :class="{ active: route.path === '/gallery' }"
              @click="router.push('/gallery')"
            >
              ⚓ 角色图鉴
            </button>
            <button
              class="wc-btn panel-nav-btn"
              :class="{ active: route.path === '/settings' }"
              @click="router.push('/settings')"
            >
              ⚙ 设置
            </button>
          </div>
        </div>
      </aside>
    </div>

    <div v-if="multiMode" class="batch-bar">
      <span>已选 {{ selectedSet.size }} {{ skinMode ? '个' : '人' }}</span>
      <n-button size="small" type="primary" :disabled="!selectedSet.size" :loading="batchDownloading" @click="batchDownload">
        {{ batchDownloading ? `下载中 ${batchDone}/${batchTotal}` : '批量下载所选' }}
      </n-button>
      <button class="wc-btn gold batch-btn" @click="selectAllFiltered">全选</button>
      <button class="wc-btn gold batch-btn" @click="clearSelection">清空</button>
    </div>

    <div v-if="downloadMsg" class="download-msg">{{ downloadMsg }}</div>

    <div v-if="dlProgress.active" class="dl-progress-card">
      <div class="dl-progress-head">
        <span class="dl-progress-label">{{ dlProgress.label }}</span>
        <button class="wc-btn danger-soft dl-progress-cancel" :disabled="cancelling" @click="onCancelDownloads">
          {{ cancelling ? '正在取消…' : '取消' }}
        </button>
      </div>
      <div class="dl-progress-track">
        <div class="dl-progress-fill" :style="{ width: dlPct + '%' }"></div>
      </div>
      <div class="dl-progress-meta">
        {{ dlProgress.done + dlProgress.failed }}/{{ dlProgress.total }}
        <span v-if="dlProgress.failed">（{{ dlProgress.failed }} 失败）</span>
        <span v-if="cancelling">正在停止…</span>
      </div>
      <div v-if="dlStage" class="dl-progress-stage">{{ dlStage }}</div>
    </div>

  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NModal, NSelect, NSlider, NAlert } from 'naive-ui'
import { assetUrl, bridge, metadataUrl, sseUrl } from '../../bridge'
import { playChime, warmAudio } from '../../utils/sound'
import { voiceEnabled, toggleVoice } from '../../utils/voice'
import SpinePreview from '../../components/SpinePreview.vue'
import StaticPreview from '../../components/StaticPreview.vue'

const route = useRoute()
const router = useRouter()

const ships = ref([])
const loading = ref(true)
const selectedId = ref(null)
const railListRef = ref(null)
const currentSkinIndex = ref(0)
const fullscreen = ref(false)
const exporting = ref(false)
const exportDone = ref(false)
const exportResult = ref(null)
const applying = ref(false)
const applyDone = ref(false)
const applyResult = ref(null)
const downloading = ref(false)
const imageExporting = ref(false)
const allDownloading = ref(false)
const allDone = ref(0)
const allTotal = ref(0)
const allFailed = ref(0)
const downloadMsg = ref('')
const skinFavs = ref(new Set())
const favOnly = ref(false)
const avatars = ref({})
const avatarFailed = ref(new Set())
// avatars.json 的加载时间戳：拼到图片 URL 上，头像更新后重新加载图片（避免浏览器缓存旧图）
const avatarsStamp = ref(0)
const multiMode = ref(false)
const selectedSet = ref(new Set())
const batchDownloading = ref(false)
const batchDone = ref(0)
const batchTotal = ref(0)
const batchFailed = ref(0)
const batchCancelled = ref(0)
const downloadBatchId = ref('')
const cancelling = ref(false)
const dlProgress = reactive({ active: false, done: 0, total: 0, failed: 0, cancelled: 0, label: '' })
const dlStage = ref('')
let dlSource = null
const previewEl = ref(null)

const batchPct = computed(() => {
  if (!batchTotal.value) return 0
  const d = batchDone.value + batchFailed.value + batchCancelled.value
  return Math.min(100, Math.round((d / batchTotal.value) * 100))
})
const dlPct = computed(() => {
  if (!dlProgress.total) return 0
  const d = dlProgress.done + dlProgress.failed + dlProgress.cancelled
  return Math.min(100, Math.round((d / dlProgress.total) * 100))
})
const SKIN_FAV_KEY = 'azl_wallpaper_skin_favs'
let msgTimer = null
let exportTimer = null
let applyTimer = null
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

function showMsg(text) {
  downloadMsg.value = text
  clearTimeout(msgTimer)
  msgTimer = setTimeout(() => {
    downloadMsg.value = ''
  }, 5000)
}

const filters = reactive({ search: '', type: 'all', faction: null, hull: null, theme: null })
const bgStyle = ref('auto')
const animation = ref('normal')
const animOptions = ref([])
const scale = ref(100)
const bgScale = ref(100)
const offsetX = ref(0)
const offsetY = ref(0)
const alignment = ref('center')
// L2D 导出选项：开场动画（login 播一次再回 idle）。关闭后壁纸只播 idle，
// 且 Wallpaper Engine 属性面板不再出现「开场动画」开关。
const introOn = ref(true)
// L2D 鼠标追踪：角色视线/头部跟随鼠标。预览实时生效，导出壁纸联动
//（WE 面板「鼠标追踪」开关默认值跟随此选项）。
// WE 预设导入：粘贴 Wallpaper Engine「分享 JSON」的预设，应用到预览布局与开关
const presetImportOpen = ref(false)
const presetImportText = ref('')
const ALIGN_VALUES = ['center', 'left-top', 'right-top', 'left-bottom', 'right-bottom']

function openPresetImport() {
  presetImportText.value = ''
  presetImportOpen.value = true
}

// 解析 WE 分享预设 JSON 并应用到预览（scalectrl/offsetx/offsety/alignment/开关）。
// 兼容两种格式：明文 JSON，或 WE「分享预设」的 Base64 编码（UTF-8）。
function applyWePreset() {
  let data
  const raw = (presetImportText.value || '').trim()
  try {
    data = JSON.parse(raw)
  } catch (e) {
    // 明文 JSON 解析失败 → 尝试 Base64 解码（WE 分享预设可切换 Base64 格式）
    try {
      const bin = atob(raw.replace(/\s+/g, ''))
      const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0))
      data = JSON.parse(new TextDecoder().decode(bytes))
    } catch (e2) {
      showMsg('无法解析：既不是 JSON，也不是 Base64 编码的 JSON')
      return
    }
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    showMsg('JSON 必须是对象格式')
    return
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
  const num = (v) => {
    const n = parseFloat(v)
    return Number.isFinite(n) ? n : null
  }
  let applied = 0
  const sc = num(data.scalectrl)
  if (sc !== null) { scale.value = Math.round(clamp(sc, 20, 300)); applied++ }
  const ox = num(data.offsetx)
  if (ox !== null) { offsetX.value = Math.round(clamp(ox, -100, 100)); applied++ }
  const oy = num(data.offsety)
  if (oy !== null) { offsetY.value = Math.round(clamp(oy, -100, 100)); applied++ }
  // alignment 兼容 WE 的两种格式：数字下标（旧）或字符串对齐名（新）
  if (data.alignment !== undefined && data.alignment !== null) {
    const a = data.alignment
    const name = typeof a === 'number'
      ? (ALIGN_VALUES[a] || null)
      : (typeof a === 'string' && ALIGN_VALUES.includes(a) ? a : null)
    if (name) { alignment.value = name; applied++ }
  }
  if (typeof data.playintro === 'boolean') { introOn.value = data.playintro; applied++ }
  if (typeof data.voice === 'boolean') {
    voiceEnabled.value = data.voice
    localStorage.setItem('azl_voice_play', data.voice ? '1' : '0')
    applied++
  }
  if (applied) {
    showMsg(`已应用 ${applied} 项 WE 预设`)
    presetImportOpen.value = false
  } else {
    showMsg('未识别到可应用属性（scalectrl / offsetx / offsety / alignment / voice / playintro）')
  }
}
const interactionMode = ref(false)
const l2dSubtitle = ref('')
const l2dPanelCollapsed = ref(false)
const showHitAreas = ref(false)
// 支持拖拽互动（drag/drag_ex/ex 动画）的 spine 皮肤清单：
// 由骨架动画扫描得出，这些皮肤互动模式下拖拽会触发 drag 反应动画；
// 不在名单内的 spine 皮肤无 drag 动画，互动模式下点击切换表情。
const SPINE_INTERACTIVE = new Set([
  'z15_2', 'yilisi_2_doa', 'kaiersheng_3', 'qiannai_2_doa', 'huali_2',
  'bojiateli_2', 'aimudeng_4', 'fulangxisike_2', 'jianye_5', 'paidi_2_doa',
  'haixiao_3_doa', 'haichou_2', 'telinida_2', 'zhuzi_2_doa', 'hongseshanmai_2',
  'weikesibao_2', 'weikesibao_3', 'molisen_3', 'molici_2', 'laimuhao_2',
  'alabama_3', 'na_2_doa', 'xiangdi_2_doa', 'gaoxiong_6', 'niaohai_3',
])
const spineInteractive = computed(() => {
  const sk = currentSkin.value
  return !!sk && sk.type === 'spine' && SPINE_INTERACTIVE.has(sk.painting)
})
// spine 是否有 login 动画（决定「开场动画」按钮是否显示/导出是否带该属性）
const spineHasLogin = computed(() => {
  const sk = currentSkin.value
  return !!sk && sk.type === 'spine' && animOptions.value.some((o) => o.value === 'login')
})

const bgOptions = [
  { label: '自动取色', value: 'auto' },
  { label: '纯色', value: 'solid' },
  { label: '莫奈渐变', value: 'monet' },
  { label: '毛玻璃', value: 'frost' },
  { label: '星空', value: 'star' },
]

const typeOptions = [
  { label: '全部', value: 'all' },
  { label: 'Spine', value: 'spine' },
  { label: '静态', value: 'static' },
]

const factionOptions = computed(() =>
  [...new Set(ships.value.map((s) => s.faction).filter(Boolean))].sort().map((v) => ({ label: v, value: v })),
)

const hullOptions = computed(() =>
  [...new Set(ships.value.map((s) => s.hull).filter(Boolean))].sort().map((v) => ({ label: v, value: v })),
)

const themeOptions = computed(() =>
  [...new Set(ships.value.flatMap((s) => s.skins.map((k) => k.theme)).filter(Boolean))].sort().map((v) => ({ label: v, value: v })),
)

const totalSkins = computed(() => ships.value.reduce((n, s) => n + s.skins.length, 0))

const filtered = computed(() => {
  return ships.value.filter((s) => {
    const kw = filters.search.trim().toLowerCase()
    const skinHit = kw && s.skins.some((k) => (k.name || '').toLowerCase().includes(kw))
    if (
      kw &&
      !s.name.toLowerCase().includes(kw) &&
      !(s.en || '').toLowerCase().includes(kw) &&
      !pyText(s.py).includes(kw) &&
      !s.skins.some((k) => pyText(k.py).includes(kw)) &&
      !skinHit
    ) return false
    const types = new Set(s.skins.map((k) => k.type))
    if (filters.type !== 'all' && !types.has(filters.type)) return false
    if (filters.faction && s.faction !== filters.faction) return false
    if (filters.hull && s.hull !== filters.hull) return false
    if (filters.theme && !s.skins.some((k) => k.theme === filters.theme)) return false
    return true
  })
})

// 按类型筛选时左侧改为皮肤级列表：直接展示具体的皮肤条目
// 只看收藏时同样切到皮肤级列表，展示的是收藏的单个皮肤
const skinMode = computed(() => filters.type !== 'all' || favOnly.value)

const filteredSkins = computed(() => {
  const out = []
  const kw = filters.search.trim().toLowerCase()
  for (const ship of filtered.value) {
    for (const skin of ship.skins) {
      if (filters.type !== 'all' && skin.type !== filters.type) continue
      if (favOnly.value && !skinFavs.value.has(skin.key)) continue
      if (filters.theme && skin.theme !== filters.theme) continue
      if (
        kw &&
        !ship.name.toLowerCase().includes(kw) &&
        !(ship.en || '').toLowerCase().includes(kw) &&
        !pyText(ship.py).includes(kw) &&
        !(skin.name || '').toLowerCase().includes(kw) &&
        !pyText(skin.py).includes(kw)
      ) {
        continue
      }
      out.push({ ship, skin })
    }
  }
  return out
})

function clearFilters() {
  searchInput.value = ''
  filters.search = ''
  filters.type = 'all'
  filters.faction = null
  filters.hull = null
  filters.theme = null
}

// 搜索框防抖：输入时不实时全量扫描数千条数据，停顿 250ms 后再过滤
const searchInput = ref('')
let searchTimer = null
watch(searchInput, (v) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    filters.search = v
  }, 250)
})

watch(() => filters.type, () => clearSelection())

const selectedShip = computed(() => ships.value.find((s) => s.id === selectedId.value) || null)
const currentSkin = computed(() => selectedShip.value?.skins[currentSkinIndex.value] || null)
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
watch(currentSkin, () => {
  exportDone.value = false
  applyDone.value = false
  clearTimeout(exportTimer)
  clearTimeout(applyTimer)
})
watch(bgStyle, () => refreshBg())
watch(solidColor, () => refreshBg())

const WC = ['74,111,165', '180,120,140', '120,160,130', '201,168,76']

function hashOf(name) {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) >>> 0
  return h
}

function avatarStyle(ship) {
  const c = WC[hashOf(ship.name) % 4]
  return { background: `linear-gradient(145deg, rgba(${c},0.42), rgba(240,235,227,0.7))` }
}

function avatarUrl(ship) {
  const f = avatars.value[ship.name]
  if (!f || avatarFailed.value.has(ship.name)) return ''
  // 拼时间戳：头像映射更新后（检查更新/重启）URL 变化，浏览器会重新拉取图片
  const stamp = avatarsStamp.value ? `?v=${avatarsStamp.value}` : ''
  return assetUrl(`avatars/${f}.jpg`) + stamp
}

function onAvatarError(ship) {
  const s = new Set(avatarFailed.value)
  s.add(ship.name)
  avatarFailed.value = s
}

function rarityClass(r) {
  if (r === '海上传奇') return 'rose'
  if (r === '超稀有') return 'gold'
  if (r === '精锐') return 'blue'
  return 'green'
}

// 拼音检索：匹配全拼（weikesibao）或首字母（wksb）
function pyText(py) {
  return py ? `${py.p || ''} ${py.i || ''}` : ''
}

function shipTypes(ship) {
  return [...new Set(ship.skins.map((k) => k.type))].filter((t) => t === 'spine')
}

function canDownload(skin) {
  return skin.type === 'spine' || skin.type === 'static'
}

function hasRemote(ship) {
  return ship.skins.some((k) => k.status === 'remote' && canDownload(k))
}

function getConcurrency() {
  try {
    const v = parseInt(localStorage.getItem('azl_concurrency') || '4', 10)
    return Math.min(8, Math.max(1, v || 4))
  } catch (e) {
    return 4
  }
}

let downloadCancelled = false

function newDownloadId() {
  return `dl_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function startDl(label, total) {
  downloadCancelled = false
  cancelling.value = false
  downloadBatchId.value = newDownloadId()
  dlProgress.active = true
  dlProgress.done = 0
  dlProgress.failed = 0
  dlProgress.cancelled = 0
  dlProgress.total = total
  dlProgress.label = label
  dlStage.value = ''
  if (dlSource) {
    dlSource.close()
    dlSource = null
  }
  // SSE：实时显示 下载立绘/合成/同步索引 等当前阶段（后端不支持时静默降级）
  try {
    dlSource = new EventSource(sseUrl())
    dlSource.addEventListener('stage', (e) => {
      try {
        const d = JSON.parse(e.data)
        dlStage.value = d.detail ? `${d.stage}：${d.detail}` : (d.stage || '')
      } catch (err) {
        /* 忽略异常事件 */
      }
    })
  } catch (err) {
    /* 后端未开 SSE 时静默 */
  }
}

function finishDl() {
  dlProgress.active = false
  downloadBatchId.value = ''
  if (dlSource) {
    dlSource.close()
    dlSource = null
  }
  dlStage.value = ''
}

async function onCancelDownloads() {
  if (downloadCancelled) return
  downloadCancelled = true
  cancelling.value = true
  if (downloadBatchId.value) {
    try {
      await bridge.cancelDownload(downloadBatchId.value)
    } catch (e) {
      /* 忽略取消请求失败，本地标志已生效 */
    }
  }
}

async function runDownloadPool(targets, limit, onProgress, batchId) {
  let done = 0
  const failedTargets = []
  let cancelledCount = 0
  let idx = 0
  const worker = async () => {
    while (idx < targets.length) {
      if (downloadCancelled) return
      const t = targets[idx++]
      try {
        const res = await bridge.downloadSkin(t.ship, t.bundle, t.name, batchId)
        if (res && res.cancelled) {
          cancelledCount++
        } else if (res && res.ok) {
          done++
        } else {
          failedTargets.push(t)
        }
      } catch (e) {
        if (downloadCancelled) cancelledCount++
        else failedTargets.push(t)
      }
      if (onProgress) onProgress({ done, failed: failedTargets.length, cancelled: cancelledCount })
    }
  }
  const n = Math.min(Math.max(1, limit), targets.length)
  await Promise.all(Array.from({ length: n }, worker))
  return { done, failedTargets, cancelled: downloadCancelled || cancelledCount > 0, cancelledCount }
}

// 失败的皮肤自动重试一轮，避免网络抖动导致批量下载"莫名失败"
async function runPoolWithRetry(targets, limit, onProgress, batchId) {
  const first = await runDownloadPool(targets, limit, (p) => {
    if (onProgress) onProgress(p)
  }, batchId)
  if (first.cancelled || !first.failedTargets.length) {
    return {
      done: first.done,
      failed: first.failedTargets.length,
      cancelled: first.cancelled,
      cancelledCount: first.cancelledCount,
    }
  }
  const second = await runDownloadPool(first.failedTargets, limit, (p) => {
    if (onProgress) onProgress({ done: first.done + p.done, failed: p.failed, cancelled: first.cancelledCount + p.cancelled })
  }, batchId)
  return {
    done: first.done + second.done,
    failed: second.failedTargets.length,
    cancelled: second.cancelled,
    cancelledCount: first.cancelledCount + second.cancelledCount,
  }
}

function selectShip(ship) {
  selectedId.value = ship.id
  currentSkinIndex.value = 0
  animOptions.value = []
  animation.value = 'normal'
}

function loadFavs() {
  try {
    skinFavs.value = new Set(JSON.parse(localStorage.getItem(SKIN_FAV_KEY) || '[]'))
  } catch (e) {
    skinFavs.value = new Set()
  }
}

function saveFavs() {
  localStorage.setItem(SKIN_FAV_KEY, JSON.stringify([...skinFavs.value]))
}

function isSkinFav(key) {
  return skinFavs.value.has(key)
}

function toggleSkinFav(key) {
  const s = new Set(skinFavs.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  skinFavs.value = s
  saveFavs()
}

function toggleMulti() {
  multiMode.value = !multiMode.value
  if (!multiMode.value) clearSelection()
}

function isSelected(id) {
  return selectedSet.value.has(id)
}

function toggleSelect(id) {
  const s = new Set(selectedSet.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedSet.value = s
}

function clearSelection() {
  selectedSet.value = new Set()
}

function selectAllFiltered() {
  if (skinMode.value) {
    for (const item of filteredSkins.value) selectedSet.value.add(item.skin.key)
  } else {
    for (const s of filtered.value) selectedSet.value.add(s.id)
  }
}

function onCardClick(ship) {
  if (multiMode.value) toggleSelect(ship.id)
  else selectShip(ship)
}

function selectSkinItem(item) {
  const ship = ships.value.find((s) => s.id === item.ship.id)
  if (!ship) return
  const idx = ship.skins.findIndex((k) => k.key === item.skin.key)
  if (idx < 0) return
  selectedId.value = ship.id
  currentSkinIndex.value = idx
  animOptions.value = []
  animation.value = 'normal'
}

function onSkinClick(item) {
  if (multiMode.value) {
    toggleSelect(item.skin.key)
    return
  }
  selectSkinItem(item)
}

// 上下键翻动左侧列表选中项（角色/皮肤切换）：按当前筛选列表移动选中位置，
// 再滚动到可见。与缩放无关（取景统一由方案 B 保证，切换角色不会缩放跳变）。
function railStep(dir) {
  const list = skinMode.value ? filteredSkins.value : filtered.value
  if (!list.length) return
  let cur = -1
  if (skinMode.value) {
    const key = currentSkin.value && currentSkin.value.key
    cur = list.findIndex((it) => it.skin.key === key)
  } else {
    cur = list.findIndex((s) => s.id === selectedId.value)
  }
  // 当前项不在筛选列表（搜索/筛选导致）时：next 从第一项开始，prev 从最后一项开始。
  // 原来的 (cur+dir+len)%len 在 cur=-1 时 prev 会算出 len-2，跳过头一项。
  const next = cur < 0 ? (dir > 0 ? 0 : list.length - 1) : (cur + dir + list.length) % list.length
  if (skinMode.value) selectSkinItem(list[next])
  else selectShip(list[next])
  // 键盘翻动后让左侧列表同步滚动到选中项（等 DOM 应用 .active 后再定位）
  nextTick(scrollRailToSelected)
}

// 让左侧角色库滚动到当前选中项（键盘翻动时保持选中项可见）。
// 用 getBoundingClientRect 差值计算，不受定位祖先影响；block=nearest 语义：
// 选中项在视口内就不动，只在越界时滚动到可见位置，连续翻动不会跳动。
function scrollRailToSelected() {
  const rail = railListRef.value
  if (!rail) return
  const active = rail.querySelector('.rail-card.active')
  if (!active) return
  const rTop = rail.getBoundingClientRect().top
  const rBottom = rail.getBoundingClientRect().bottom
  const eTop = active.getBoundingClientRect().top
  const eBottom = active.getBoundingClientRect().bottom
  if (eTop < rTop) {
    rail.scrollTop += eTop - rTop
  } else if (eBottom > rBottom) {
    rail.scrollTop += eBottom - rBottom
  }
}

async function batchDownload() {
  if (!selectedSet.value.size) return
  warmAudio()
  const targets = []
  if (skinMode.value) {
    for (const item of filteredSkins.value) {
      if (!selectedSet.value.has(item.skin.key)) continue
      const sk = item.skin
      if (sk.status === 'remote' && canDownload(sk)) {
        targets.push({ ship: item.ship.name, bundle: sk.bundle, name: sk.name })
      }
    }
  } else {
    for (const ship of ships.value) {
      if (!selectedSet.value.has(ship.id)) continue
      for (const sk of ship.skins) {
        if (sk.status === 'remote' && canDownload(sk)) {
          targets.push({ ship: ship.name, bundle: sk.bundle, name: sk.name })
        }
      }
    }
  }
  if (!targets.length) {
    showMsg(skinMode.value ? '所选皮肤没有可下载的资源' : '所选角色没有可下载的动态皮肤')
    return
  }
  startDl(`批量下载（${targets.length} 个皮肤）`, targets.length)
  batchDownloading.value = true
  batchDone.value = 0
  batchFailed.value = 0
  batchCancelled.value = 0
  batchTotal.value = targets.length
  const res = await runPoolWithRetry(targets, getConcurrency(), ({ done, failed, cancelled }) => {
    batchDone.value = done
    batchFailed.value = failed
    batchCancelled.value = cancelled
    dlProgress.done = done
    dlProgress.failed = failed
    dlProgress.cancelled = cancelled
  }, downloadBatchId.value)
  batchDownloading.value = false
  finishDl()
  ships.value = await bridge.listShips()
  clearSelection()
  if (res.done > 0) playChime()
  if (res.cancelled) {
    showMsg(
      `已取消：完成 ${res.done} 个，失败 ${res.failed} 个，取消 ${res.cancelledCount || 0} 个，未下载 ${Math.max(
        0,
        batchTotal.value - res.done - res.failed - (res.cancelledCount || 0),
      )} 个`,
    )
  } else {
    showMsg(res.failed
      ? `批量下载完成：${res.done} 成功，${res.failed} 失败（已自动重试一轮）`
      : `✓ 批量下载完成（${batchTotal.value} 个皮肤）`)
  }
}

function onSpineAnims(names) {
  animOptions.value = names.map((n) => ({ label: n, value: n }))
  if (!animation.value || !names.includes(animation.value)) {
    animation.value = names.find((n) => /^idle$/i.test(n)) || names.find((n) => n === 'home') || names[0] || ''
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

function onEngineError(msg) {
  console.error('[preview]', msg)
  showMsg(`✗ 预览引擎加载失败：${msg}`)
}

async function toggleFullscreen() {
  fullscreen.value = !fullscreen.value
  try {
    if (fullscreen.value) {
      await document.documentElement.requestFullscreen?.()
    } else {
      await document.exitFullscreen?.()
    }
  } catch (e) {
    // 浏览器/WebView 不支持时仅用 CSS 全屏
  }
}

// 以浏览器实际全屏状态为准同步 UI（用户按 Esc / 系统手势退出全屏时，状态不脱节）
function onFullscreenChange() {
  fullscreen.value = !!document.fullscreenElement
}

function onKeydown(e) {
  if (e.key === 'Escape' && fullscreen.value) {
    fullscreen.value = false
    return
  }
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
  if (t && t.closest && t.closest('.n-select')) return
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    if (animOptions.value.length) {
      e.preventDefault()
      stepAnim(e.key === 'ArrowLeft' ? -1 : 1)
    }
    return
  }
  // 上下键：切换左侧列表选中项（角色/皮肤），保持选中项滚动可见。
  // 注意：不在此处改缩放——不同皮肤显示大小由取景统一（方案 B），切换角色不会“缩放跳变”。
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  if (fullscreen.value) return
  e.preventDefault()
  railStep(e.key === 'ArrowDown' ? 1 : -1)
}

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
      intro: introOn.value,
      voice: voiceEnabled.value,
      showHitAreas: showHitAreas.value,
    })
  } catch (e) {
    exportResult.value = { ok: false, error: e.message || '导出失败' }
  } finally {
    exporting.value = false
    exportDone.value = true
    clearTimeout(exportTimer)
    exportTimer = setTimeout(() => {
      exportDone.value = false
    }, 8000)
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
      intro: introOn.value,
      voice: voiceEnabled.value,
      showHitAreas: showHitAreas.value,
    })
  } catch (e) {
    applyResult.value = { ok: false, error: e.message || '导出并应用失败' }
  } finally {
    applying.value = false
    applyDone.value = true
    clearTimeout(applyTimer)
    applyTimer = setTimeout(() => {
      applyDone.value = false
    }, 8000)
  }
}

async function downloadCurrent() {
  const skin = currentSkin.value
  if (!skin) return
  warmAudio()
  startDl(`下载：${skin.name}`, 1)
  downloading.value = true
  downloadMsg.value = ''
  try {
    const res = await bridge.downloadSkin(skin.ship, skin.bundle, skin.name, downloadBatchId.value)
    if (res && res.cancelled) {
      dlProgress.cancelled = 1
      showMsg('已取消下载')
    } else if (res && res.ok) {
      dlProgress.done = 1
      playChime()
      showMsg('✓ 下载完成，已自动提取入库')
      ships.value = await bridge.listShips()
    } else {
      dlProgress.failed = 1
      showMsg(`✗ 下载失败：${(res && res.error) || '未知错误'}`)
    }
  } catch (e) {
    showMsg(downloadCancelled ? '已取消下载' : `✗ 下载异常：${e.message}`)
  } finally {
    downloading.value = false
    finishDl()
  }
}

async function downloadAll() {
  const ship = selectedShip.value
  if (!ship) return
  warmAudio()
  const targets = ship.skins.filter((sk) => sk.status === 'remote' && canDownload(sk))
  if (!targets.length) {
    showMsg('该角色没有可下载的资源')
    return
  }
  startDl(`下载全部：${ship.name}`, targets.length)
  allDownloading.value = true
  allDone.value = 0
  allFailed.value = 0
  allTotal.value = targets.length
  const res = await runPoolWithRetry(targets, getConcurrency(), ({ done, failed, cancelled }) => {
    allDone.value = done
    allFailed.value = failed
    dlProgress.done = done
    dlProgress.failed = failed
    dlProgress.cancelled = cancelled
  }, downloadBatchId.value)
  allDownloading.value = false
  finishDl()
  ships.value = await bridge.listShips()
  if (res.done > 0) playChime()
  if (res.cancelled) {
    showMsg(`已取消：完成 ${res.done} 个，失败 ${res.failed} 个，取消 ${res.cancelledCount || 0} 个`)
  } else {
    showMsg(res.failed
      ? `下载全部完成：${res.done} 成功，${res.failed} 失败（已自动重试一轮）`
      : `✓ 已下载全部 ${allTotal.value} 个资源`)
  }
}

async function doExportImage() {
  const skin = currentSkin.value
  if (!skin) return
  imageExporting.value = true
  try {
    let res
    if (skin.type === 'static') {
      res = await bridge.exportImage(skin.ship, skin.bundle, skin.name)
    } else {
      // spine：导出当前预览帧（所选动画的当前姿态），与预览所见一致
      const dataUrl =
        previewEl.value && typeof previewEl.value.capture === 'function'
          ? previewEl.value.capture()
          : null
      if (!dataUrl) {
        showMsg('✗ 暂无法读取当前预览画面')
        return
      }
      // spine 导出时文件名带当前动画序号（角色名-N.png，N 为第几个动画）
      const animNo =
        skin.type === 'spine' && animOptions.value.length ? animIndex.value + 1 : null
      res = await bridge.exportImageData(skin.ship, skin.bundle, skin.name, dataUrl, animNo)
    }
    if (res && res.ok) {
      showMsg(`✓ 图片已导出：${res.message}`)
    } else {
      showMsg(`✗ 导出失败：${(res && res.error) || '未知错误'}`)
    }
  } catch (e) {
    showMsg(`✗ 导出异常：${e.message}`)
  } finally {
    imageExporting.value = false
  }
}

onMounted(async () => {
  const wrap = stageWrapRef.value
  if (wrap) {
    fitStage()
    stageRO = new ResizeObserver(fitStage)
    stageRO.observe(wrap)
  }
  loadFavs()
  try {
    avatars.value = await (await fetch(metadataUrl('avatars.json'), { cache: 'no-store' })).json()
    avatarsStamp.value = Date.now()
    avatarFailed.value = new Set()
  } catch (e) {
    avatars.value = {}
  }
  try {
    ships.value = await bridge.listShips()
  } catch (e) {
    showMsg(`✗ 加载资源库失败：${e.message}`)
    ships.value = []
  }
  loading.value = false
  const first =
    ships.value.find((s) => s.skins.some((k) => k.status === 'downloaded')) || ships.value[0]
  if (first) selectShip(first)
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('fullscreenchange', onFullscreenChange)
})

// keep-alive 缓存后从设置等页面返回时触发：刷新数据但保留当前选中的角色/皮肤
onActivated(async () => {
  try {
    const fresh = await bridge.listShips()
    if (fresh && fresh.length) {
      ships.value = fresh
      if (!selectedShip.value) selectShip(fresh[0])
    }
  } catch (e) {
    /* 忽略刷新失败，保留现有数据 */
  }
  try {
    avatars.value = await (await fetch(metadataUrl('avatars.json'), { cache: 'no-store' })).json()
    // 头像映射刷新：更新版本戳（图片 URL 变化强制重载），并清失败集合让占位角色重试
    avatarsStamp.value = Date.now()
    avatarFailed.value = new Set()
  } catch (e) {
    /* 头像缺失时回退首字 */
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  clearTimeout(msgTimer)
  clearTimeout(exportTimer)
  clearTimeout(applyTimer)
  clearTimeout(searchTimer)
  if (stageRO) stageRO.disconnect()
})
</script>

<style scoped>
.main-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.main-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.86);
  backdrop-filter: blur(8px);
  flex-shrink: 0;
}

.main-title h1 {
  margin: 0;
  font-family: var(--font-serif);
  font-weight: 300;
  letter-spacing: 2px;
  font-size: 20px;
}

.main-title span {
  color: var(--muted);
  font-size: 12px;
  margin-left: 10px;
}

.main-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

/* ---- 左侧角色库 ---- */
.ship-rail {
  width: 300px;
  flex-shrink: 0;
  border-right: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.8);
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 10px;
}

.rail-pills {
  display: flex;
  gap: 6px;
}

.rail-tools {
  display: flex;
  gap: 6px;
}

.filter-panel {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.filter-field label {
  color: var(--muted);
  font-size: 12px;
}

.clear-filter-btn {
  grid-column: span 2;
  padding: 7px 0;
}

.rail-tool {
  flex: 1;
  text-align: center;
  padding: 6px 0;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.7);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 300;
  transition: all 0.3s ease-out;
  user-select: none;
}

.rail-tool:hover {
  color: var(--blue);
  border-color: rgba(74, 111, 165, 0.5);
  background: #fff;
}

.rail-tool.active {
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(133, 205, 202, 0.14));
  border-color: rgba(74, 111, 165, 0.55);
  color: #3a5a88;
  box-shadow: 0 4px 16px rgba(74, 111, 165, 0.14);
}

.type-pill {
  flex: 1;
  text-align: center;
  padding: 7px 0;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.7);
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s ease-out;
  user-select: none;
}

.type-pill:hover {
  color: var(--blue);
  border-color: rgba(74, 111, 165, 0.5);
  background: #fff;
}

.type-pill.active {
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(133, 205, 202, 0.14));
  border-color: rgba(74, 111, 165, 0.55);
  color: #3a5a88;
  box-shadow: 0 4px 16px rgba(74, 111, 165, 0.14);
}

.rail-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.rail-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 16px;
  border: 1px solid transparent;
  background: rgba(250, 248, 245, 0.9);
  cursor: pointer;
  transition: all 0.3s ease-out;
}

.rail-card:hover {
  border-color: rgba(74, 111, 165, 0.3);
  transform: scale(1.015);
}

.rail-card.active {
  border-color: rgba(74, 111, 165, 0.5);
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(180, 120, 140, 0.12));
  box-shadow: var(--shadow-soft);
}

.rail-avatar {
  width: 40px;
  height: 40px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  overflow: hidden;
}

.rail-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.rail-char {
  font-family: var(--font-serif);
  font-size: 16px;
  color: rgba(58, 58, 58, 0.8);
}

.rail-info {
  min-width: 0;
  flex: 1;
}

.rail-name {
  font-family: var(--font-serif);
  font-size: 14px;
  letter-spacing: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.rail-skin {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.rail-meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.rail-star {
  position: absolute;
  top: 6px;
  right: 8px;
  z-index: 2;
  color: var(--gold);
  cursor: pointer;
  font-size: 14px;
  opacity: 0.6;
  transition: all 0.3s ease-out;
}

.rail-star:hover {
  opacity: 1;
  transform: scale(1.15);
}

.rail-star.fav {
  opacity: 1;
}

.rail-check {
  position: absolute;
  bottom: 6px;
  right: 8px;
  z-index: 2;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.7);
  display: grid;
  place-items: center;
  font-size: 11px;
  color: transparent;
}

.rail-check.on {
  background: rgba(74, 111, 165, 0.85);
  color: #fff;
  border-color: transparent;
}

/* ---- 中心预览区 ---- */
.preview-zone {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.stage-wrap {
  flex: 1;
  min-height: 0;
  display: grid;
  place-items: center;
  overflow: hidden;
}

.preview-stage {
  position: relative;
  overflow: hidden;
  display: grid;
  place-items: center;
  border-radius: 14px;
  box-shadow: var(--shadow-hover);
}

.stage-info {
  position: absolute;
  top: 14px;
  left: 16px;
  z-index: 4;
  display: flex;
  align-items: baseline;
  gap: 8px;
  pointer-events: none;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.45);
}

.stage-info-name {
  font-family: var(--font-serif);
  font-size: 20px;
  letter-spacing: 2px;
  color: rgba(250, 248, 245, 0.96);
}

.stage-info-skin {
  font-size: 13px;
  color: rgba(240, 235, 227, 0.75);
}

/* ---- L2D 互动控制面板（方案 A · 航海指挥面板） ---- */
.l2d-panel-a {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 6;
  width: 252px;
  background: linear-gradient(165deg, rgba(24, 34, 58, 0.78), rgba(10, 14, 24, 0.66));
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 18px;
  padding: 12px 12px 10px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(14px);
  font-family: var(--font-sans);
  transition: all 0.25s ease;
}

.l2d-panel-a.collapsed {
  width: 46px;
  padding: 10px 0;
}

.l2d-panel-a-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.l2d-panel-a-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-serif);
  font-size: 13px;
  letter-spacing: 3px;
  color: rgba(240, 235, 227, 0.92);
}

.l2d-panel-a-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--gold);
  box-shadow: 0 0 8px rgba(201, 168, 76, 0.8);
}

.l2d-panel-a-collapse {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.35);
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  transition: all 0.2s ease;
}

.l2d-panel-a-collapse:hover {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.l2d-panel-a.collapsed .l2d-panel-a-head {
  margin-bottom: 0;
  justify-content: center;
}

.l2d-panel-a.collapsed .l2d-panel-a-body {
  display: none;
}

/* 分段控件：拖拽 / 互动 */
.l2d-seg {
  position: relative;
  display: flex;
  background: rgba(0, 0, 0, 0.4);
  border-radius: 12px;
  padding: 3px;
  margin-bottom: 8px;
}

.l2d-seg-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: calc(50% - 3px);
  height: calc(100% - 6px);
  border-radius: 10px;
  background: linear-gradient(120deg, rgba(74, 111, 165, 0.9), rgba(133, 205, 202, 0.85));
  box-shadow: 0 4px 14px rgba(74, 111, 165, 0.45);
  transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.l2d-seg.on-interact .l2d-seg-thumb {
  transform: translateX(100%);
}

.l2d-seg-item {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 0;
  font-size: 12.5px;
  letter-spacing: 2px;
  font-family: var(--font-sans);
  color: rgba(255, 255, 255, 0.78);
  cursor: pointer;
  user-select: none;
  transition: color 0.25s ease;
  border: none;
  background: transparent;
}

.l2d-seg-item.active {
  color: #fff;
  font-weight: 500;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}

.l2d-seg-item svg {
  width: 15px;
  height: 15px;
  flex: none;
}

/* 开关行 */
.l2d-switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 4px;
  border-radius: 12px;
  transition: background 0.2s ease;
}

.l2d-switch-row:hover {
  background: rgba(255, 255, 255, 0.05);
}

.l2d-switch-ico {
  width: 26px;
  height: 26px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.07);
  color: rgba(240, 235, 227, 0.85);
}

.l2d-switch-ico.on {
  color: var(--gold);
  background: rgba(201, 168, 76, 0.22);
}

.l2d-switch-txt {
  flex: 1;
  font-size: 12.5px;
  letter-spacing: 1px;
  color: rgba(240, 235, 227, 0.9);
}

.l2d-switch-txt small {
  display: block;
  font-size: 10.5px;
  color: rgba(240, 235, 227, 0.5);
  letter-spacing: 0.5px;
  margin-top: 1px;
}

.l2d-switch {
  position: relative;
  width: 38px;
  height: 22px;
  flex: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  cursor: pointer;
  transition: background 0.25s ease;
}

.l2d-switch::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4);
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.l2d-switch.on {
  background: linear-gradient(120deg, rgba(201, 168, 76, 0.9), rgba(180, 120, 140, 0.85));
}

.l2d-switch.on::after {
  transform: translateX(16px);
}

/* 台词框 */
.l2d-subtitle-a {
  position: relative;
  margin-top: 9px;
  padding: 12px 14px 11px 18px;
  max-height: 120px;
  overflow-y: auto;
  box-sizing: border-box;
  border-radius: 14px;
  background: rgba(0, 0, 0, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.7);
}

.l2d-subtitle-a::before {
  content: '“';
  position: absolute;
  left: 6px;
  top: 2px;
  font-family: var(--font-serif);
  font-size: 26px;
  line-height: 1;
  color: rgba(201, 168, 76, 0.75);
}

.l2d-subtitle-a-who {
  display: block;
  font-size: 10.5px;
  letter-spacing: 2px;
  color: var(--gold);
  margin-bottom: 3px;
}

.l2d-subtitle-a.empty {
  color: rgba(255, 255, 255, 0.4);
  font-size: 12px;
}

.l2d-subtitle-a.empty::before {
  display: none;
}

.stage-fullscreen-btn {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 5;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  background: rgba(10, 14, 24, 0.42);
  backdrop-filter: blur(6px);
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s ease-out;
}

.stage-fullscreen-btn:hover {
  background: rgba(10, 14, 24, 0.62);
  transform: scale(1.08);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
}

/* ---- 皮肤切换条 ---- */
.skin-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-top: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.9);
}

.skin-strip {
  flex: 1;
  min-width: 0;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.skin-status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.dl-ok {
  color: #6b9d7a;
  font-size: 13px;
}

/* ---- 右侧控制面板 ---- */
.control-panel {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid var(--line);
  background: rgba(250, 248, 245, 0.86);
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  overflow-y: auto;
}

.panel-card {
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px;
  box-shadow: var(--shadow-soft);
}

.panel-title {
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 2px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px dashed rgba(120, 120, 120, 0.22);
}

.export-actions .wc-btn + .wc-btn {
  margin-top: 14px;
}

.dl-btn {
  padding: 6px 16px;
  font-size: 13px;
}

.export-alert {
  margin-top: 10px;
  font-size: 12px;
}

.panel-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.panel-field:last-child {
  margin-bottom: 0;
}

.panel-field label {
  color: var(--muted);
  font-size: 12px;
}

.panel-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.anim-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 8px;
}

.anim-nav-btn {
  padding: 4px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.4;
  min-width: 36px;
}

.anim-nav-label {
  color: var(--muted);
  font-size: 12px;
  min-width: 46px;
  text-align: center;
}

.panel-tip {
  color: #b07a3a;
  font-size: 12px;
  margin: 8px 0 0;
  line-height: 1.6;
}

.panel-nav {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(120, 120, 120, 0.22);
}

.panel-nav-btn {
  flex: 1;
  padding: 7px 10px;
  border-radius: 12px;
}

.panel-nav-btn.active {
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(133, 205, 202, 0.14));
  border-color: rgba(74, 111, 165, 0.55);
  color: #3a5a88;
}

.bar-dim {
  color: var(--muted);
  font-size: 12px;
}

/* 偏移滑块行：滑块 + 实时数值并排，数值右对齐等宽数字，0 弱化 */
.offset-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.reset-bgscale {
  font-size: 12px;
  padding: 2px 10px;
  white-space: nowrap;
}
.offset-row .n-slider {
  flex: 1;
  min-width: 0;
}
.bar-value {
  min-width: 42px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: var(--blue);
}
.bar-value.zero {
  color: var(--muted);
  font-weight: 400;
}

/* WE 预设导入 */
.preset-import-btn {
  width: 100%;
  justify-content: center;
  font-size: 13px;
  padding: 7px 12px;
  border-style: dashed;
}
.preset-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}

.download-msg {
  position: fixed;
  bottom: 60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  padding: 10px 20px;
  border-radius: 999px;
  background: rgba(250, 248, 245, 0.95);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
  font-size: 13px;
  color: var(--ink);
}

.batch-bar {
  position: fixed;
  bottom: 70px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  border-radius: 999px;
  background: rgba(250, 248, 245, 0.96);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-hover);
  font-size: 13px;
  color: var(--ink);
}

.batch-progress {
  width: 140px;
  height: 6px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.batch-progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #4a6fa5, #b4788c);
  transition: width 0.2s ease-out;
}

.batch-progress-text {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
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

.preview-placeholder {
  position: relative;
  text-align: center;
  user-select: none;
}

.preview-halo {
  width: 260px;
  height: 260px;
  margin: 0 auto 18px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(74, 111, 165, 0.35), rgba(180, 120, 140, 0.18) 45%, transparent 70%);
  filter: blur(2px);
  animation: halo-float 5s ease-in-out infinite;
}

@keyframes halo-float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-16px) scale(1.06); }
}

.preview-title {
  font-family: var(--font-serif);
  font-weight: 300;
  font-size: 28px;
  letter-spacing: 5px;
  margin-bottom: 10px;
  color: rgba(250, 248, 245, 0.96);
  text-shadow: 0 2px 16px rgba(0, 0, 0, 0.4);
}

.preview-sub {
  color: rgba(240, 235, 227, 0.7);
  font-size: 13px;
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

/* 皮肤收藏星标（皮肤切换条右侧，始终可点击） */
.skin-fav-btn {
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.14), rgba(133, 205, 202, 0.18));
  border: 1px solid rgba(74, 111, 165, 0.35);
  color: rgba(74, 111, 165, 0.75);
  font-size: 15px;
  cursor: pointer;
  display: inline-grid;
  place-items: center;
  transition: transform 0.25s ease-out, color 0.25s ease-out, box-shadow 0.25s ease-out;
}
.skin-fav-btn:hover {
  transform: scale(1.12);
  box-shadow: 0 4px 14px rgba(74, 111, 165, 0.25);
}
.skin-fav-btn.on {
  background: linear-gradient(135deg, rgba(201, 168, 76, 0.9), rgba(240, 200, 90, 0.95));
  border-color: rgba(201, 168, 76, 0.65);
  color: #fff;
  box-shadow: 0 4px 16px rgba(201, 168, 76, 0.4);
}

/* 批量操作栏内的渐变按钮 */
.batch-bar .batch-btn {
  padding: 6px 16px;
  font-size: 12px;
}

/* 右下角下载进度条 */
.dl-progress-card {
  position: fixed;
  right: 0;
  bottom: 24px;
  z-index: 30;
  width: 300px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(250, 248, 245, 0.97);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-hover);
  backdrop-filter: blur(8px);
}
.dl-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.dl-progress-label {
  font-size: 13px;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dl-progress-cancel {
  padding: 4px 14px;
  font-size: 12px;
  flex-shrink: 0;
}
.dl-progress-track {
  height: 8px;
  border-radius: 999px;
  background: rgba(74, 111, 165, 0.12);
  overflow: hidden;
}
.dl-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #4a6fa5, #85cdca);
  transition: width 0.3s ease-out;
}
.dl-progress-meta {
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}

.dl-progress-stage {
  margin-top: 6px;
  font-size: 12px;
  color: var(--blue);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

/* 全屏模式 */
.main-view.is-fullscreen .preview-zone {
  width: 100%;
}
</style>

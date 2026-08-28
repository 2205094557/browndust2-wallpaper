<template>
  <div ref="wrapRef" class="static-preview" @mousedown="onDown">
    <img
      v-if="imgUrl"
      :src="imgUrl"
      class="static-img"
      :style="imgStyle"
      draggable="false"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { assetUrl } from '../bridge'
import '../../../templates/wallpaper-layout.js'

const WL = window.WallpaperLayout

const props = defineProps({
  skin: { type: Object, required: true },
  scale: { type: Number, default: 100 },
  offsetX: { type: Number, default: 0 },
  offsetY: { type: Number, default: 0 },
})
const emit = defineEmits(['ready', 'error', 'scaleChange', 'panChange'])

const wrapRef = ref(null)
const stage = reactive({ w: 0, h: 0 })
const view = reactive({ scale: 100, ox: 0, oy: 0 })
let drag = null
let ro = null

const imgUrl = computed(() => {
  const asset = props.skin.asset
  return asset ? assetUrl(asset.dir + '/' + asset.image) : ''
})

const imgStyle = computed(() => {
  const px = (stage.w * view.ox) / 100
  const py = (stage.h * view.oy) / 100
  return {
    transform: `translate(${px}px, ${py}px) scale(${view.scale / 100})`,
  }
})

watch(
  () => [props.scale, props.offsetX, props.offsetY],
  ([s, x, y]) => {
    view.scale = WL.clampScale(s)
    view.ox = WL.clampOffset(x)
    view.oy = WL.clampOffset(y)
  },
  { immediate: true },
)

function onDown(e) {
  if (e.button !== 0) return
  drag = { x: e.clientX, y: e.clientY, ox: view.ox, oy: view.oy }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function onMove(e) {
  if (!drag) return
  drag.lastX = e.clientX
  drag.lastY = e.clientY
  view.ox = WL.clampOffset(drag.ox + ((e.clientX - drag.x) / (stage.w || 1)) * 100)
  view.oy = WL.clampOffset(drag.oy + ((e.clientY - drag.y) / (stage.h || 1)) * 100)
}

function onUp() {
  if (!drag) return
  const lx = drag.lastX != null ? drag.lastX : drag.x
  const ly = drag.lastY != null ? drag.lastY : drag.y
  view.ox = WL.clampOffset(drag.ox + ((lx - drag.x) / (stage.w || 1)) * 100)
  view.oy = WL.clampOffset(drag.oy + ((ly - drag.y) / (stage.h || 1)) * 100)
  drag = null
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  emit('panChange', { x: Math.round(view.ox), y: Math.round(view.oy) })
}

function onWheel(e) {
  e.preventDefault()
  const next = WL.clampScale(view.scale * Math.pow(1.1, -e.deltaY / 100))
  view.scale = Math.round(next)
  emit('scaleChange', view.scale)
}

onMounted(() => {
  const wrap = wrapRef.value
  if (!wrap) return
  const measure = () => {
    stage.w = wrap.clientWidth
    stage.h = wrap.clientHeight
  }
  measure()
  ro = new ResizeObserver(measure)
  ro.observe(wrap)
  wrap.addEventListener('wheel', onWheel, { passive: false })
  emit('ready')
})

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (ro) ro.disconnect()
  wrapRef.value?.removeEventListener('wheel', onWheel)
})
</script>

<style scoped>
.static-preview {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
}

.static-img {
  max-width: 92%;
  max-height: 92%;
  object-fit: contain;
  user-select: none;
  filter: drop-shadow(0 8px 30px rgba(0, 0, 0, 0.35));
}
</style>

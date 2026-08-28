<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="watercolor-bg"></div>
      <div class="watercolor-grain"></div>
      <div class="app-content">
        <router-view v-slot="{ Component }">
          <!-- 只缓存图鉴页：预览/设置页含 WebGL 渲染循环，全部缓存会导致
               隐藏页面的 rAF/WebGL 上下文持续运行（资源泄漏）。
               GalleryView 内嵌的 Spine/L2D 预览在 onDeactivated 时暂停渲染。 -->
          <keep-alive :include="['GalleryView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { NConfigProvider, NMessageProvider } from 'naive-ui'
import { themeKey } from './utils/theme'

// 开发/打包窗口都支持 F5 / Ctrl+R 强制刷新（WebView2 内没有浏览器工具栏）
function onRefreshKey(e) {
  if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r')) {
    e.preventDefault()
    window.location.reload()
  }
}
onMounted(() => window.addEventListener('keydown', onRefreshKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onRefreshKey))

// Naive UI 主题：随软件主题切换（水彩画风 / 少女漫画风）
const themeOverrides = computed(() => {
  if (themeKey.value === 'shoujo') {
    // 少女漫画风：樱花粉主调
    return {
      common: {
        primaryColor: '#ffb7c5',
        primaryColorHover: '#ff9fb4',
        primaryColorPressed: '#f472a0',
        borderRadius: '16px',
        bodyColor: 'transparent',
        cardColor: '#ffffff',
        modalColor: '#ffffff',
        popoverColor: '#fffdfd',
        inputColor: 'rgba(255, 255, 255, 0.85)',
        textColorBase: '#4a5568',
        textColor1: '#4a5568',
        textColor2: '#f472a0',
        textColor3: '#a98a97',
        borderColor: 'rgba(255, 183, 197, 0.3)',
        dividerColor: 'rgba(255, 183, 197, 0.22)',
        fontFamily: '"PingFang SC", "Yuanti SC", "Microsoft YaHei", sans-serif',
      },
      Button: {
        borderRadiusSmall: '999px',
        borderRadiusMedium: '999px',
        borderRadiusLarge: '999px',
        fontWeight: '500',
        color: '#ffb7c5',
        colorHoverPrimary: '#ff9fb4',
        colorPressedPrimary: '#f472a0',
        textColor: '#fff',
        textColorHover: '#fff',
        textColorPressed: '#fff',
        colorSecondary: 'rgba(255, 255, 255, 0.95)',
        colorHoverSecondary: '#ffffff',
        colorPressedSecondary: 'rgba(255, 233, 238, 0.95)',
        textColorSecondary: '#f472a0',
        textColorHoverSecondary: '#e0527e',
        textColorPressedSecondary: '#e0527e',
        borderSecondary: '1.5px solid rgba(255, 183, 197, 0.45)',
        borderHoverSecondary: '1.5px solid rgba(244, 114, 160, 0.65)',
        colorError: 'rgba(255, 233, 238, 0.95)',
        colorHoverError: 'rgba(255, 217, 225, 0.95)',
        colorPressedError: 'rgba(255, 201, 212, 0.95)',
        textColorError: '#e0527e',
        textColorHoverError: '#d14a72',
        textColorPressedError: '#d14a72',
        borderError: '1.5px solid rgba(244, 114, 160, 0.5)',
        borderHoverError: '1.5px solid rgba(224, 82, 126, 0.75)',
      },
    }
  }
  if (themeKey.value === 'cyberpunk') {
    // 赛博朋克霓虹：深色 + 青/品红/黄
    return {
      common: {
        primaryColor: '#22d3ee',
        primaryColorHover: '#67e8f9',
        primaryColorPressed: '#0ea5e9',
        borderRadius: '8px',
        bodyColor: 'transparent',
        cardColor: '#0d0d15',
        modalColor: '#0d0d15',
        popoverColor: '#0d0d15',
        inputColor: 'rgba(13, 13, 21, 0.9)',
        textColorBase: '#e5e7eb',
        textColor1: '#e5e7eb',
        textColor2: '#22d3ee',
        textColor3: '#cbd5e1',
        borderColor: 'rgba(34, 211, 238, 0.3)',
        dividerColor: 'rgba(34, 211, 238, 0.2)',
        fontFamily: '"Consolas", "PingFang SC", "Microsoft YaHei", monospace',
      },
      Button: {
        borderRadiusSmall: '8px',
        borderRadiusMedium: '8px',
        borderRadiusLarge: '8px',
        fontWeight: '500',
        color: '#22d3ee',
        colorHoverPrimary: '#67e8f9',
        colorPressedPrimary: '#0ea5e9',
        textColor: '#000',
        textColorHover: '#000',
        textColorPressed: '#000',
        colorSecondary: 'rgba(13, 13, 21, 0.95)',
        colorHoverSecondary: 'rgba(34, 211, 238, 0.1)',
        colorPressedSecondary: 'rgba(13, 13, 21, 1)',
        textColorSecondary: '#22d3ee',
        textColorHoverSecondary: '#67e8f9',
        textColorPressedSecondary: '#22d3ee',
        borderSecondary: '1px solid rgba(34, 211, 238, 0.45)',
        borderHoverSecondary: '1px solid rgba(34, 211, 238, 0.8)',
        colorError: 'rgba(232, 121, 249, 0.12)',
        colorHoverError: 'rgba(232, 121, 249, 0.2)',
        colorPressedError: 'rgba(232, 121, 249, 0.28)',
        textColorError: '#e879f9',
        textColorHoverError: '#f0abfc',
        textColorPressedError: '#f0abfc',
        borderError: '1px solid rgba(232, 121, 249, 0.6)',
        borderHoverError: '1px solid rgba(232, 121, 249, 0.85)',
      },
    }
  }
  if (themeKey.value === 'solarpunk') {
    // 太阳朋克：温暖浅色 + 叶绿/金黄/天蓝
    return {
      common: {
        primaryColor: '#22c55e',
        primaryColorHover: '#4ade80',
        primaryColorPressed: '#16a34a',
        borderRadius: '16px',
        bodyColor: 'transparent',
        cardColor: '#ffffff',
        modalColor: '#ffffff',
        popoverColor: '#ffffff',
        inputColor: 'rgba(255, 255, 255, 0.8)',
        textColorBase: '#1f2937',
        textColor1: '#1f2937',
        textColor2: '#15803d',
        textColor3: '#6b7280',
        borderColor: 'rgba(34, 197, 94, 0.28)',
        dividerColor: 'rgba(34, 197, 94, 0.2)',
        fontFamily: '"PingFang SC", "Yuanti SC", "Microsoft YaHei", sans-serif',
      },
      Button: {
        borderRadiusSmall: '12px',
        borderRadiusMedium: '16px',
        borderRadiusLarge: '18px',
        fontWeight: '400',
        color: '#22c55e',
        colorHoverPrimary: '#4ade80',
        colorPressedPrimary: '#16a34a',
        textColor: '#fff',
        textColorHover: '#fff',
        textColorPressed: '#fff',
        colorSecondary: 'rgba(255, 255, 255, 0.9)',
        colorHoverSecondary: 'rgba(74, 222, 128, 0.12)',
        colorPressedSecondary: 'rgba(74, 222, 128, 0.2)',
        textColorSecondary: '#15803d',
        textColorHoverSecondary: '#14532d',
        textColorPressedSecondary: '#14532d',
        borderSecondary: '1.5px solid rgba(34, 197, 94, 0.4)',
        borderHoverSecondary: '1.5px solid rgba(34, 197, 94, 0.7)',
        colorError: 'rgba(255, 247, 237, 0.95)',
        colorHoverError: 'rgba(255, 237, 213, 0.95)',
        colorPressedError: 'rgba(254, 215, 170, 0.95)',
        textColorError: '#c2410c',
        textColorHoverError: '#9a3412',
        textColorPressedError: '#9a3412',
        borderError: '1.5px solid rgba(251, 146, 60, 0.55)',
        borderHoverError: '1.5px solid rgba(251, 146, 60, 0.8)',
      },
    }
  }
  // 水彩画风（默认）
  return {
    common: {
      primaryColor: '#4a6fa5',
      primaryColorHover: '#5c82b8',
      primaryColorPressed: '#3f5f8f',
      borderRadius: '16px',
      bodyColor: 'transparent',
      cardColor: '#faf8f5',
      modalColor: '#faf8f5',
      popoverColor: '#fffdfa',
      inputColor: 'rgba(255, 255, 255, 0.6)',
      textColorBase: '#3a3a3a',
      textColor1: '#3a3a3a',
      textColor2: '#4a6fa5',
      textColor3: '#8a8a8a',
      borderColor: 'rgba(74, 111, 165, 0.2)',
      dividerColor: 'rgba(74, 111, 165, 0.16)',
      fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
    },
    Button: {
      borderRadiusSmall: '12px',
      borderRadiusMedium: '16px',
      borderRadiusLarge: '18px',
      fontWeight: '300',
      // primary：水彩蓝（主操作）。注意：Naive 主题变量只接受纯色，不接受渐变字符串；
      // hover/pressed 键名是 colorHoverPrimary / colorPressedPrimary（词序在中间）。
      color: '#4a6fa5',
      colorHoverPrimary: '#5c82b8',
      colorPressedPrimary: '#3f5f8f',
      textColor: '#fff',
      textColorHover: '#fff',
      textColorPressed: '#fff',
      // secondary：纸感浅底 + 蓝描边（与 wc-btn 默认观感一致）
      colorSecondary: 'rgba(250, 248, 245, 0.95)',
      colorHoverSecondary: '#ffffff',
      colorPressedSecondary: 'rgba(240, 235, 227, 0.9)',
      textColorSecondary: '#4a6fa5',
      textColorHoverSecondary: '#3a5a88',
      textColorPressedSecondary: '#3a5a88',
      borderSecondary: '1px solid rgba(74, 111, 165, 0.35)',
      borderHoverSecondary: '1px solid rgba(74, 111, 165, 0.6)',
      // error：玫红系（软警示，替代 Naive 默认红）
      colorError: 'rgba(180, 120, 140, 0.14)',
      colorHoverError: 'rgba(180, 120, 140, 0.22)',
      colorPressedError: 'rgba(180, 120, 140, 0.3)',
      textColorError: '#9c5f74',
      textColorHoverError: '#8a4a60',
      textColorPressedError: '#8a4a60',
      borderError: '1px solid rgba(180, 120, 140, 0.45)',
      borderHoverError: '1px solid rgba(180, 120, 140, 0.7)',
    },
  }
})

</script>

// 主题切换（水彩画风 / 少女漫画风 / 赛博朋克霓虹）
// localStorage 记忆；切换时给 <body> 挂对应主题类，全局 CSS 变量与覆盖层随之生效。
import { ref } from 'vue'

export const THEMES = [
  { key: 'watercolor', label: '水彩画风' },
  { key: 'shoujo', label: '少女漫画风' },
  { key: 'cyberpunk', label: '赛博朋克霓虹' },
  { key: 'solarpunk', label: '太阳朋克' },
]

const KEY = 'azl_theme'

export const themeKey = ref(localStorage.getItem(KEY) || 'watercolor')

function apply() {
  const cls = themeKey.value === 'watercolor' ? '' : 'theme-' + themeKey.value
  document.body.className = document.body.className
    .split(/\s+/)
    .filter((c) => c && !c.startsWith('theme-'))
    .concat(cls ? [cls] : [])
    .join(' ')
}

export function setTheme(key) {
  if (!THEMES.some((t) => t.key === key)) key = 'watercolor'
  themeKey.value = key
  localStorage.setItem(KEY, key)
  apply()
}

export function initTheme() {
  apply()
}

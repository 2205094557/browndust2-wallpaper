import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles.css'
import './themes/shoujo.css'
import './themes/cyberpunk.css'
import './themes/solarpunk.css'
import { initTheme } from './utils/theme'

// 运行时错误上报（排障用）：转发到后端 /api/log，同时显示在页面顶部
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8766'
function reportError(label, msg, stack) {
  const text = `${label}: ${msg}\n${stack || ''}`
  try {
    fetch(`${API_BASE}/api/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: label, message: String(msg).slice(0, 300), stack: String(stack || '').slice(0, 600) }),
    }).catch(() => {})
  } catch (e) { /* 后端不可用时忽略 */ }
  const div = document.createElement('div')
  div.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#7a1f1f;color:#fff;font:12px/1.5 monospace;padding:8px 12px;white-space:pre-wrap'
  div.textContent = text
  document.body.appendChild(div)
}
window.addEventListener('error', (e) => reportError('JS错误', e.message, `${e.filename}:${e.lineno}:${e.colno}`))
window.addEventListener('unhandledrejection', (e) => reportError('Promise错误', e.reason && e.reason.message ? e.reason.message : e.reason))

createApp(App).use(router).mount('#app')
initTheme()

// 预览区语音开关（与「拖拽/互动」控件组融合）：关闭后语音与台词都不播放/显示。
// localStorage 记忆；预览组件监听本模块的响应式状态。
import { ref } from 'vue'

export const voiceEnabled = ref(localStorage.getItem('azl_voice_play') !== '0')

export function toggleVoice() {
  voiceEnabled.value = !voiceEnabled.value
  localStorage.setItem('azl_voice_play', voiceEnabled.value ? '1' : '0')
}

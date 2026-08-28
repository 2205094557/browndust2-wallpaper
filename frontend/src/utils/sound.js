// 下载完成提示音：Web Audio 合成，多种音色 + 可调音量，设置持久化到 localStorage。

export const TIMBRES = [
  { id: 'chime', name: '清脆叮咚' },
  { id: 'bell', name: '柔和风铃' },
  { id: 'single', name: '清脆单音' },
  { id: 'pop', name: '轻快气泡' },
]

const STORAGE_KEY = 'azl_notify_sound'

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {}
  } catch (e) {
    return {}
  }
}

let prefs = { volume: 70, timbre: 'chime', ...loadPrefs() }
let audioCtx = null

function ensureCtx() {
  if (!audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) return null
    audioCtx = new AC()
  }
  if (audioCtx.state === 'suspended') audioCtx.resume()
  return audioCtx
}

export function getSoundPrefs() {
  return { ...prefs }
}

export function setSoundPrefs(patch) {
  prefs = { ...prefs, ...patch }
  if (prefs.volume < 0) prefs.volume = 0
  if (prefs.volume > 100) prefs.volume = 100
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
  } catch (e) {
    /* 忽略存储失败 */
  }
}

// 在用户点击时预热音频上下文（浏览器手势后才能出声）
export function warmAudio() {
  ensureCtx()
}

// 音量为 0~100 的全局增益（默认 70，整体偏柔和）
function master() {
  return (prefs.volume || 0) / 100
}

function tone(ac, t0, freq, type, gain, delay, dur) {
  const osc = ac.createOscillator()
  const g = ac.createGain()
  osc.type = type
  osc.frequency.value = freq
  const t = t0 + delay
  g.gain.setValueAtTime(0, t)
  g.gain.linearRampToValueAtTime(gain * master(), t + 0.012)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(g)
  g.connect(ac.destination)
  osc.start(t)
  osc.stop(t + dur + 0.05)
}

function playChimeTone(ac, t0) {
  // 清脆叮咚：E6 → A6 双音 + 一丝高频泛音
  tone(ac, t0, 1318.5, 'sine', 0.10, 0, 0.55)
  tone(ac, t0, 1760.0, 'sine', 0.08, 0.10, 0.70)
  tone(ac, t0, 2637.0, 'triangle', 0.025, 0.10, 0.38)
}

function playBell(ac, t0) {
  // 柔和风铃：G5 基音 + 高八度泛音，衰减稍长、音量更低
  tone(ac, t0, 784.0, 'sine', 0.09, 0, 1.0)
  tone(ac, t0, 1568.0, 'sine', 0.045, 0.02, 0.8)
  tone(ac, t0, 2093.0, 'triangle', 0.02, 0.12, 0.5)
}

function playSingle(ac, t0) {
  // 清脆单音：一个 E6，干净利落
  tone(ac, t0, 1318.5, 'sine', 0.12, 0, 0.35)
  tone(ac, t0, 2637.0, 'triangle', 0.02, 0.0, 0.2)
}

function playPop(ac, t0) {
  // 轻快气泡：短促上滑音
  const osc = ac.createOscillator()
  const g = ac.createGain()
  osc.type = 'triangle'
  osc.frequency.setValueAtTime(660, t0)
  osc.frequency.exponentialRampToValueAtTime(1320, t0 + 0.12)
  g.gain.setValueAtTime(0, t0)
  g.gain.linearRampToValueAtTime(0.11 * master(), t0 + 0.01)
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22)
  osc.connect(g)
  g.connect(ac.destination)
  osc.start(t0)
  osc.stop(t0 + 0.28)
}

export function playChime() {
  const ac = ensureCtx()
  if (!ac) return
  const t0 = ac.currentTime
  switch (prefs.timbre) {
    case 'bell':
      playBell(ac, t0)
      break
    case 'single':
      playSingle(ac, t0)
      break
    case 'pop':
      playPop(ac, t0)
      break
    default:
      playChimeTone(ac, t0)
  }
}

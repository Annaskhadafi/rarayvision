<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { sttService } from '../services/sttService'

const SpeechRecognition = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null

const field = ref(null)
const position = ref({ top: 0, left: 0 })
const recording = ref(false)
const busy = ref(false)
const error = ref('')

let activeRecognition = null
let recorder = null
let chunks = []

let initialFieldValue = ''
let finalTranscript = ''

const isEligible = (element) => {
  if (!element || element.disabled || element.readOnly) return false
  if (element.closest?.('[data-voice-test]')) return false
  if (element.tagName === 'TEXTAREA') return true
  return element.tagName === 'INPUT' && ['text', 'search'].includes(element.type)
}

const updatePosition = () => {
  if (!field.value) return
  const rect = field.value.getBoundingClientRect()
  position.value = { top: rect.top + 4, left: Math.max(8, rect.right - 42) }
}

const focusIn = (event) => {
  if (isEligible(event.target)) {
    field.value = event.target
    updatePosition()
  }
}

const focusOut = (event) => {
  if (!event.relatedTarget?.closest?.('.voice-dictation')) {
    // Jangan langsung hilangkan jika sedang recording
    if (!recording.value) {
      field.value = null
    }
  }
}

const setFieldValue = (val) => {
  const target = field.value
  if (!target) return
  const setter = Object.getOwnPropertyDescriptor(target.__proto__, 'value')?.set
  setter?.call(target, val)
  target.dispatchEvent(new Event('input', { bubbles: true }))
  nextTick(() => target.setSelectionRange(val.length, val.length))
}

const insertText = (text) => {
  const target = field.value
  if (!target) return
  const start = target.selectionStart ?? target.value.length
  const end = target.selectionEnd ?? start
  const value = target.value.slice(0, start) + (start && !/\s$/.test(target.value.slice(0, start)) ? ' ' : '') + text + target.value.slice(end)
  setFieldValue(value)
}

const stop = () => {
  if (activeRecognition) {
    try { activeRecognition.stop() } catch {}
    activeRecognition = null
  }
  if (recorder && recorder.state !== 'inactive') {
    try { recorder.stop() } catch {}
  }
  recording.value = false
}

// ─── Realtime Typing using Web Speech API ─────────────────────────────────────
const startRealtime = () => {
  const recognition = new SpeechRecognition()
  recognition.lang = 'id-ID'
  recognition.continuous = true
  recognition.interimResults = true

  const target = field.value
  initialFieldValue = target ? target.value : ''
  finalTranscript = ''

  recognition.onstart = () => {
    recording.value = true
    busy.value = false
  }

  recognition.onresult = (event) => {
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      const transcript = event.results[i][0].transcript
      if (event.results[i].isFinal) {
        finalTranscript += (finalTranscript ? ' ' : '') + transcript.trim()
      } else {
        interim += transcript
      }
    }

    const spokenText = (finalTranscript + (interim ? ' ' + interim : '')).trim()
    const separator = initialFieldValue && !/\s$/.test(initialFieldValue) ? ' ' : ''
    const fullText = initialFieldValue ? (initialFieldValue + separator + spokenText) : spokenText

    setFieldValue(fullText)
  }

  recognition.onerror = (event) => {
    if (event.error === 'no-speech') return
    if (event.error === 'not-allowed') {
      error.value = 'Izin mikrofon ditolak'
    } else {
      error.value = `Mic: ${event.error}`
    }
    recording.value = false
  }

  recognition.onend = () => {
    recording.value = false
  }

  activeRecognition = recognition
  recognition.start()
}

// ─── Fallback MediaRecorder for older browsers ────────────────────────────────
const startFallbackRecorder = async () => {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    error.value = 'Browser tidak mendukung perekaman suara'
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    chunks = []
    recorder = new MediaRecorder(stream)
    recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data)
    recorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop())
      recording.value = false
      busy.value = true
      try {
        const result = await sttService.transcribe(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
        insertText(result.text)
      } catch (err) {
        error.value = err.message
      } finally {
        busy.value = false
      }
    }
    recorder.start()
    recording.value = true
  } catch (err) {
    error.value = err.name === 'NotAllowedError' ? 'Izin mikrofon ditolak' : err.message
    recording.value = false
  }
}

const toggle = async () => {
  error.value = ''
  if (recording.value) {
    stop()
    return
  }

  if (SpeechRecognition) {
    startRealtime()
  } else {
    await startFallbackRecorder()
  }
}

onMounted(() => {
  document.addEventListener('focusin', focusIn)
  document.addEventListener('focusout', focusOut)
  window.addEventListener('resize', updatePosition)
  window.addEventListener('scroll', updatePosition, true)
})

onBeforeUnmount(() => {
  stop()
  document.removeEventListener('focusin', focusIn)
  document.removeEventListener('focusout', focusOut)
  window.removeEventListener('resize', updatePosition)
  window.removeEventListener('scroll', updatePosition, true)
})
</script>

<template>
  <div v-if="field" class="voice-dictation" :style="{ top: `${position.top}px`, left: `${position.left}px` }">
    <button
      type="button"
      :class="{ recording, busy }"
      :disabled="busy"
      :title="recording ? 'Klik untuk stop dikte' : 'Dikte suara realtime (bicara untuk langsung mengetik)'"
      :aria-label="recording ? 'Stop bicara' : 'Isi field dengan suara realtime'"
      @mousedown.prevent
      @click="toggle"
    >
      <svg v-if="!busy && !recording" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 1a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z" />
        <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v5M8 23h8" />
      </svg>
      <span v-else-if="recording" aria-hidden="true">■</span>
      <span v-else aria-hidden="true">…</span>
    </button>
    <span v-if="error" class="voice-error">{{ error }}</span>
  </div>
</template>

<style scoped>
.voice-dictation { position: fixed; z-index: 1000; display: flex; align-items: center; gap: 6px; }
.voice-dictation button { width: 40px; height: 40px; display: grid; place-items: center; border: 1px solid #cbd5e1; border-radius: 9px; background: white; cursor: pointer; box-shadow: 0 2px 8px #0f172a22; transition: transform .15s ease, box-shadow .15s ease, background .15s ease; }
.voice-dictation button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px #0f172a2e; }
.voice-dictation button:active { transform: scale(.96); }
.voice-dictation svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.voice-dictation button.recording { background: #fee2e2; border-color: #ef4444; color: #b91c1c; animation: pulse 1.2s infinite; }
.voice-dictation button.busy { cursor: wait; }
.voice-error { max-width: 240px; padding: 5px 8px; border-radius: 5px; color: #991b1b; background: #fee2e2; font-size: 12px; border: 1px solid #fca5a5; }

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}
</style>

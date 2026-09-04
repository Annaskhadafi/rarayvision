<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { sttService } from '../services/sttService'

const field = ref(null)
const position = ref({ top: 0, left: 0 })
const recording = ref(false)
const busy = ref(false)
const error = ref('')
let recorder
let chunks = []

const isEligible = (element) => {
  if (!element || element.disabled || element.readOnly) return false
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
  if (!event.relatedTarget?.closest?.('.voice-dictation')) field.value = null
}

const insertText = (text) => {
  const target = field.value
  if (!target) return
  const start = target.selectionStart ?? target.value.length
  const end = target.selectionEnd ?? start
  const value = target.value.slice(0, start) + (start && !/\s$/.test(target.value.slice(0, start)) ? ' ' : '') + text + target.value.slice(end)
  const setter = Object.getOwnPropertyDescriptor(target.__proto__, 'value')?.set
  setter?.call(target, value)
  target.dispatchEvent(new Event('input', { bubbles: true }))
  nextTick(() => target.setSelectionRange(value.length, value.length))
}

const stop = () => {
  if (recorder && recorder.state !== 'inactive') recorder.stop()
}

const toggle = async () => {
  error.value = ''
  if (recording.value) return stop()
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
    <button type="button" :class="{ recording, busy }" :disabled="busy" :aria-label="recording ? 'Stop bicara' : 'Isi field dengan suara'" @mousedown.prevent @click="toggle">
      {{ busy ? '…' : (recording ? '■' : '🎙') }}
    </button>
    <span v-if="error" class="voice-error">{{ error }}</span>
  </div>
</template>

<style scoped>
.voice-dictation { position: fixed; z-index: 1000; display: flex; align-items: center; gap: 6px; }
.voice-dictation button { width: 34px; height: 32px; border: 1px solid #cbd5e1; border-radius: 7px; background: white; cursor: pointer; box-shadow: 0 2px 8px #0f172a22; }
.voice-dictation button.recording { background: #fee2e2; border-color: #ef4444; color: #b91c1c; }
.voice-dictation button.busy { cursor: wait; }
.voice-error { max-width: 220px; padding: 5px 8px; border-radius: 5px; color: #991b1b; background: #fee2e2; font-size: 12px; }
</style>

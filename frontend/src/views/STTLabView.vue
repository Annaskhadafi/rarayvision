<script setup>
import { onMounted, ref } from 'vue'
import { sttService } from '../services/sttService'

const models = ref([])
const selected = ref([])
const activeModel = ref('')
const cpuThreads = ref(2)
const file = ref(null)
const results = ref([])
const busy = ref(false)
const message = ref('')
const testFields = ref([
  { model: 'fw-base-int8', text: '', recording: false, busy: false, error: '' },
  { model: 'fw-small-int8', text: '', recording: false, busy: false, error: '' }
])
const activeRecorders = new WeakMap()

const load = async () => {
  try {
    models.value = await sttService.models()
    const config = await sttService.config()
    activeModel.value = config.active_model
    cpuThreads.value = config.cpu_threads
    selected.value = models.value.map(model => model.id)
    testFields.value.forEach((field, index) => {
      field.model = models.value[index]?.id || models.value[0]?.id || field.model
    })
  } catch (error) { message.value = error.message }
}

const toggleTestField = async (field) => {
  field.error = ''
  const current = activeRecorders.get(field)
  if (field.recording) {
    current?.stop()
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    field.error = 'Browser tidak mendukung mikrofon'
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const chunks = []
    const recorder = new MediaRecorder(stream)
    activeRecorders.set(field, recorder)
    recorder.ondataavailable = event => event.data.size && chunks.push(event.data)
    recorder.onstop = async () => {
      stream.getTracks().forEach(track => track.stop())
      field.recording = false
      field.busy = true
      try {
        const result = await sttService.benchmark(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }), [field.model])
        if (result[0]?.error) throw new Error(result[0].error)
        field.text = result[0]?.text || ''
      } catch (error) { field.error = error.message }
      finally { field.busy = false }
    }
    recorder.start()
    field.recording = true
  } catch (error) {
    field.error = error.name === 'NotAllowedError' ? 'Izin mikrofon ditolak' : error.message
  }
}

const runBenchmark = async () => {
  if (!file.value || !selected.value.length) return
  busy.value = true
  message.value = ''
  try { results.value = await sttService.benchmark(file.value, selected.value) }
  catch (error) { message.value = error.message }
  finally { busy.value = false }
}

const activate = async (model) => {
  try {
    const config = await sttService.updateConfig({ active_model: model, cpu_threads: cpuThreads.value })
    activeModel.value = config.active_model
    message.value = `Model aktif: ${config.active_model}`
  } catch (error) { message.value = error.message }
}

onMounted(load)
</script>

<template>
  <section class="stt-lab">
    <header>
      <p class="eyebrow">Speech to Text</p>
      <h1>Voice Input Lab</h1>
      <p>Bandingkan model CPU Bahasa Indonesia, lalu pilih model aktif untuk tombol mikrofon di form.</p>
    </header>

    <div class="card realtime-card">
      <div class="section-heading">
        <div>
          <h2>Uji realtime dua model</h2>
          <p>Bicara pada masing-masing field, tekan stop, lalu bandingkan hasil transkripsinya.</p>
        </div>
        <span class="cpu-badge">CPU only</span>
      </div>
      <div class="test-grid">
        <div v-for="(field, index) in testFields" :key="index" class="test-field" data-voice-test>
          <div class="field-topline">
            <label>Field test {{ index + 1 }}</label>
            <select v-model="field.model" :disabled="field.recording || field.busy">
              <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
            </select>
          </div>
          <div class="textarea-wrap">
            <textarea v-model="field.text" rows="5" placeholder="Tekan mikrofon lalu mulai berbicara..." />
            <button type="button" class="test-mic" :class="{ recording: field.recording, busy: field.busy }" :disabled="field.busy" :aria-label="field.recording ? 'Stop field test' : 'Mulai field test'" @mousedown.prevent @click="toggleTestField(field)">
              <svg v-if="!field.busy && !field.recording" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v5M8 23h8"/></svg>
              <span v-else-if="field.recording">■</span><span v-else>…</span>
            </button>
          </div>
          <small v-if="field.recording" class="recording-label">● Sedang merekam — tekan untuk stop</small>
          <small v-if="field.error" class="field-error">{{ field.error }}</small>
        </div>
      </div>
    </div>

    <div class="card controls">
      <label>Audio uji <input type="file" accept="audio/*" @change="file = $event.target.files[0]; results = []" /></label>
      <label>CPU threads <input v-model.number="cpuThreads" type="number" min="1" max="16" /></label>
      <div class="models">
        <label v-for="model in models" :key="model.id" class="model-option">
          <input v-model="selected" type="checkbox" :value="model.id" />
          {{ model.id }} <small>{{ model.engine }} / {{ model.compute_type }}</small>
        </label>
      </div>
      <button class="primary" :disabled="busy || !file || !selected.length" @click="runBenchmark">
        {{ busy ? 'Menjalankan...' : 'Bandingkan model' }}
      </button>
    </div>
    <p v-if="message" class="message">{{ message }}</p>
    <div v-if="results.length" class="card results">
      <div v-for="result in results" :key="result.model" class="result-row">
        <div><strong>{{ result.model }}</strong><span v-if="result.model === activeModel" class="active">Aktif</span></div>
        <p v-if="result.error" class="error">{{ result.error }}</p>
        <template v-else>
          <p>{{ result.text || '(tidak ada teks)' }}</p>
          <small>{{ result.processing_ms }} ms · RTF {{ result.rtf ?? '-' }}</small>
          <button class="secondary" @click="activate(result.model)">Jadikan aktif</button>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.stt-lab { max-width: 900px; margin: 0 auto; padding: 16px 0 40px; color: #0f172a; }
.eyebrow { color: #2563eb; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 4px 0 8px; }
header p { color: #64748b; }
.card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-top: 20px; }
.realtime-card { box-shadow: 0 8px 24px #0f172a0a; }
.section-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.section-heading h2 { margin: 0 0 4px; font-size: 18px; }
.section-heading p { margin: 0; font-size: 13px; }
.cpu-badge { color: #166534; background: #dcfce7; border-radius: 999px; padding: 5px 9px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.test-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 18px; }
.test-field { min-width: 0; padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #f8fafc; }
.field-topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; }
.field-topline label { font-size: 13px; font-weight: 700; }
.field-topline select { max-width: 150px; padding: 5px 7px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; font-size: 12px; }
.textarea-wrap { position: relative; }
.textarea-wrap textarea { display: block; width: 100%; box-sizing: border-box; padding: 12px 52px 12px 12px; border: 1px solid #cbd5e1; border-radius: 8px; resize: vertical; font: inherit; line-height: 1.45; }
.textarea-wrap textarea:focus { outline: 2px solid #93c5fd; outline-offset: 1px; border-color: #2563eb; }
.test-mic { position: absolute; right: 9px; top: 9px; width: 40px; height: 40px; display: grid; place-items: center; border: 1px solid #bfdbfe; border-radius: 9px; background: #eff6ff; color: #1d4ed8; }
.test-mic:hover { background: #dbeafe; }
.test-mic:active { transform: scale(.96); }
.test-mic.recording { color: #b91c1c; border-color: #fecaca; background: #fee2e2; }
.test-mic svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.recording-label { display: block; margin-top: 7px; color: #b91c1c; }
.field-error { display: block; margin-top: 7px; color: #b91c1c; }
.controls { display: grid; gap: 16px; }
.controls label { display: grid; gap: 6px; font-weight: 600; }
input[type=number] { width: 80px; padding: 7px; }
.models { display: grid; gap: 8px; }
.model-option { display: flex !important; align-items: center; gap: 8px; font-weight: 500 !important; }
.model-option small { color: #64748b; font-weight: 400; }
button { border: 0; border-radius: 7px; padding: 9px 14px; cursor: pointer; font-weight: 600; }
button:disabled { opacity: .5; cursor: not-allowed; }
.primary { background: #2563eb; color: white; }
.secondary { background: #e2e8f0; color: #0f172a; }
.result-row { padding: 14px 0; border-bottom: 1px solid #e2e8f0; }
.result-row:last-child { border-bottom: 0; }
.result-row p { margin: 8px 0; white-space: pre-wrap; }
.result-row small { color: #64748b; margin-right: 12px; }
.active { margin-left: 8px; padding: 3px 7px; border-radius: 9px; color: #166534; background: #dcfce7; font-size: 11px; }
.message { color: #b45309; }
.error { color: #b91c1c; }
@media (max-width: 700px) { .test-grid { grid-template-columns: 1fr; } .section-heading { flex-direction: column; } }
</style>

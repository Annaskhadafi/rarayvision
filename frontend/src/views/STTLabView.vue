<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { sttService } from '../services/sttService'

const SpeechRecognition = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
const hasWebSpeech = !!SpeechRecognition

const inputMode = ref('realtime') // 'realtime' (langsung ngetik) or 'server' (rekam dulu baru model server)
const speechLang = ref('id-ID') // 'id-ID' (Bahasa Indonesia) or 'en-US'
const models = ref([])
const selected = ref([])
const activeModel = ref('')
const cpuThreads = ref(2)
const file = ref(null)
const results = ref([])
const busy = ref(false)
const message = ref('')

const testFields = ref([
  {
    model: 'fw-base-int8',
    text: '',
    baseText: '',
    interimText: '',
    recording: false,
    busy: false,
    error: '',
    copied: false
  },
  {
    model: 'fw-small-int8',
    text: '',
    baseText: '',
    interimText: '',
    recording: false,
    busy: false,
    error: '',
    copied: false
  }
])

const activeRecognitions = new WeakMap()
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
  } catch (error) {
    message.value = error.message
  }
}

// ─── Realtime Typing via Web Speech API ───────────────────────────────────────
const startRealtimeRecognition = (field) => {
  if (!SpeechRecognition) {
    field.error = 'Browser Anda tidak mendukung Web Speech API. Gunakan Google Chrome, Microsoft Edge, atau Safari.'
    return
  }

  try {
    const recognition = new SpeechRecognition()
    recognition.lang = speechLang.value
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    field.baseText = field.text ? field.text.trim() : ''
    field.interimText = ''
    field.error = ''

    recognition.onstart = () => {
      field.recording = true
      field.busy = false
    }

    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          field.baseText = (field.baseText ? field.baseText + ' ' : '') + transcript.trim()
        } else {
          interim += transcript
        }
      }
      field.interimText = interim
      field.text = (field.baseText ? field.baseText + (interim ? ' ' + interim : '') : interim).trim()
    }

    recognition.onerror = (event) => {
      if (event.error === 'no-speech') return
      if (event.error === 'not-allowed') {
        field.error = 'Izin mikrofon ditolak oleh browser.'
      } else {
        field.error = `Error mic (${event.error})`
      }
      field.recording = false
    }

    recognition.onend = () => {
      field.recording = false
      field.interimText = ''
    }

    activeRecognitions.set(field, recognition)
    recognition.start()
  } catch (err) {
    field.error = `Gagal memulai dictation: ${err.message}`
    field.recording = false
  }
}

const stopRealtimeRecognition = (field) => {
  const recognition = activeRecognitions.get(field)
  if (recognition) {
    try { recognition.stop() } catch {}
  }
  field.recording = false
  field.interimText = ''
}

// ─── Server Recording Mode (Audio File / Whisper) ─────────────────────────────
const startServerRecording = async (field) => {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    field.error = 'Browser tidak mendukung perekaman mikrofon.'
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
      } catch (error) {
        field.error = error.message
      } finally {
        field.busy = false
      }
    }
    recorder.start()
    field.recording = true
  } catch (error) {
    field.error = error.name === 'NotAllowedError' ? 'Izin mikrofon ditolak' : error.message
    field.recording = false
  }
}

const stopServerRecording = (field) => {
  const recorder = activeRecorders.get(field)
  if (recorder && recorder.state !== 'inactive') {
    recorder.stop()
  }
}

// ─── Universal Toggle for Microphone ─────────────────────────────────────────
const toggleTestField = (field) => {
  field.error = ''

  if (inputMode.value === 'realtime') {
    if (field.recording) {
      stopRealtimeRecognition(field)
    } else {
      // Hentikan field lain yang mungkin sedang aktif
      testFields.value.forEach(f => {
        if (f !== field && f.recording) stopRealtimeRecognition(f)
      })
      startRealtimeRecognition(field)
    }
  } else {
    // Mode server (rekam lalu kirim)
    if (field.recording) {
      stopServerRecording(field)
    } else {
      testFields.value.forEach(f => {
        if (f !== field && f.recording) stopServerRecording(f)
      })
      startServerRecording(field)
    }
  }
}

const clearField = (field) => {
  if (field.recording) {
    if (inputMode.value === 'realtime') stopRealtimeRecognition(field)
    else stopServerRecording(field)
  }
  field.text = ''
  field.baseText = ''
  field.interimText = ''
  field.error = ''
}

const copyField = async (field) => {
  if (!field.text) return
  try {
    await navigator.clipboard.writeText(field.text)
    field.copied = true
    setTimeout(() => { field.copied = false }, 2000)
  } catch {}
}

const runBenchmark = async () => {
  if (!file.value || !selected.value.length) return
  busy.value = true
  message.value = ''
  try {
    results.value = await sttService.benchmark(file.value, selected.value)
  } catch (error) {
    message.value = error.message
  } finally {
    busy.value = false
  }
}

const activate = async (model) => {
  try {
    const config = await sttService.updateConfig({ active_model: model, cpu_threads: cpuThreads.value })
    activeModel.value = config.active_model
    message.value = `Model aktif berhasil diperbarui: ${config.active_model}`
  } catch (error) {
    message.value = error.message
  }
}

onMounted(load)

onBeforeUnmount(() => {
  testFields.value.forEach(field => {
    stopRealtimeRecognition(field)
    stopServerRecording(field)
  })
})
</script>

<template>
  <section class="stt-lab">
    <header>
      <div class="header-content">
        <div>
          <p class="eyebrow">Speech to Text & Voice Lab</p>
          <h1>Voice Input Lab</h1>
          <p>Dikte suara langsung (realtime typing) serta pengujian model transkripsi Bahasa Indonesia.</p>
        </div>
      </div>
    </header>

    <!-- Mode Selector & Language Bar -->
    <div class="mode-bar card">
      <div class="mode-toggles">
        <button
          type="button"
          class="mode-btn"
          :class="{ active: inputMode === 'realtime' }"
          @click="inputMode = 'realtime'"
        >
          <span class="dot live"></span>
          <strong>Realtime Typing (Langsung Mengetik)</strong>
          <small>Zero delay · Huruf per huruf saat bicara</small>
        </button>

        <button
          type="button"
          class="mode-btn"
          :class="{ active: inputMode === 'server' }"
          @click="inputMode = 'server'"
        >
          <span class="dot cpu"></span>
          <strong>Mode Server Whisper (Rekam Dulu)</strong>
          <small>Batch model transkripsi CPU/Cloud</small>
        </button>
      </div>

      <div class="lang-selector">
        <label>Bahasa:</label>
        <select v-model="speechLang">
          <option value="id-ID">🇮🇩 Bahasa Indonesia</option>
          <option value="en-US">🇺🇸 English (US)</option>
        </select>
      </div>
    </div>

    <!-- Realtime Voice Test Cards -->
    <div class="card realtime-card">
      <div class="section-heading">
        <div>
          <h2>Uji Suara Dua Bidang</h2>
          <p v-if="inputMode === 'realtime'">
            Tekan mikrofon dan <strong>mulai berbicara</strong> — teks langsung terketik secara realtime tanpa perlu menunggu proses rekam!
          </p>
          <p v-else>
            Bicara pada masing-masing field, tekan tombol stop, lalu model server akan mentranskripsikannya.
          </p>
        </div>
        <span v-if="inputMode === 'realtime'" class="badge-realtime">⚡ Realtime Typing</span>
        <span v-else class="cpu-badge">Server Whisper</span>
      </div>

      <div class="test-grid">
        <div v-for="(field, index) in testFields" :key="index" class="test-field" data-voice-test>
          <div class="field-topline">
            <div class="field-title">
              <label>Field test {{ index + 1 }}</label>
              <span v-if="field.recording" class="live-pill">🔴 Mengetik Live...</span>
            </div>

            <div class="field-actions">
              <select
                v-if="inputMode === 'server'"
                v-model="field.model"
                :disabled="field.recording || field.busy"
              >
                <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
              </select>

              <button
                v-if="field.text"
                type="button"
                class="btn-icon"
                title="Salin teks"
                @click="copyField(field)"
              >
                {{ field.copied ? '✓ Tersalin' : '📋 Salin' }}
              </button>

              <button
                v-if="field.text"
                type="button"
                class="btn-icon danger"
                title="Hapus teks"
                @click="clearField(field)"
              >
                ✕ Hapus
              </button>
            </div>
          </div>

          <div class="textarea-wrap">
            <textarea
              v-model="field.text"
              rows="5"
              :placeholder="inputMode === 'realtime' ? 'Klik mikrofon, lalu bicara — kata akan otomatis diketik seketika...' : 'Tekan mikrofon, bicara, lalu tekan stop...'"
            />

            <button
              type="button"
              class="test-mic"
              :class="{ recording: field.recording, busy: field.busy }"
              :disabled="field.busy"
              :aria-label="field.recording ? 'Stop bicara' : 'Mulai bicara'"
              @mousedown.prevent
              @click="toggleTestField(field)"
            >
              <svg v-if="!field.busy && !field.recording" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 1a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z" />
                <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v5M8 23h8" />
              </svg>
              <span v-else-if="field.recording" class="mic-stop">■</span>
              <span v-else class="mic-dots">…</span>
            </button>
          </div>

          <small v-if="field.recording && inputMode === 'realtime'" class="recording-label">
            ● Sedang mendengarkan & langsung mengetik... (Bicara terus atau klik ■ untuk selesai)
          </small>
          <small v-else-if="field.recording" class="recording-label">
            ● Sedang merekam — tekan ■ untuk kirim ke model server
          </small>
          <small v-if="field.error" class="field-error">{{ field.error }}</small>
        </div>
      </div>
    </div>

    <!-- File Benchmark Controls -->
    <div class="card controls">
      <div class="section-heading">
        <div>
          <h2>Benchmark Audio File (Whisper)</h2>
          <p>Unggah file rekaman untuk mengukur akurasi dan kecepatan Real-Time Factor (RTF) model server.</p>
        </div>
      </div>

      <label>File Audio Uji <input type="file" accept="audio/*" @change="file = $event.target.files[0]; results = []" /></label>
      <label>CPU threads <input v-model.number="cpuThreads" type="number" min="1" max="16" /></label>

      <div class="models">
        <label v-for="model in models" :key="model.id" class="model-option">
          <input v-model="selected" type="checkbox" :value="model.id" />
          {{ model.id }} <small>{{ model.engine }} / {{ model.compute_type }}</small>
        </label>
      </div>

      <button class="primary" :disabled="busy || !file || !selected.length" @click="runBenchmark">
        {{ busy ? 'Menjalankan transkripsi...' : 'Bandingkan model' }}
      </button>
    </div>

    <p v-if="message" class="message">{{ message }}</p>

    <div v-if="results.length" class="card results">
      <h3>Hasil Benchmark</h3>
      <div v-for="result in results" :key="result.model" class="result-row">
        <div>
          <strong>{{ result.model }}</strong>
          <span v-if="result.model === activeModel" class="active">Aktif</span>
          <span v-if="result.note" class="note-pill">{{ result.note }}</span>
        </div>
        <p v-if="result.error" class="error">{{ result.error }}</p>
        <template v-else>
          <p class="result-text">{{ result.text || '(tidak ada teks terdeteksi)' }}</p>
          <small>{{ result.processing_ms }} ms · RTF {{ result.rtf ?? '-' }}</small>
          <button class="secondary" @click="activate(result.model)">Jadikan model aktif</button>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.stt-lab { max-width: 960px; margin: 0 auto; padding: 16px 0 50px; color: #0f172a; }
.eyebrow { color: #2563eb; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; margin: 0; }
h1 { margin: 4px 0 6px; font-size: 26px; }
header p { color: #64748b; margin: 0; }
.card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 22px; margin-top: 20px; box-shadow: 0 4px 16px #0f172a08; }

/* Mode Switcher Bar */
.mode-bar { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; background: #f8fafc; border-color: #cbd5e1; padding: 14px 18px; }
.mode-toggles { display: flex; gap: 10px; flex-wrap: wrap; }
.mode-btn { display: flex; flex-direction: column; align-items: flex-start; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; cursor: pointer; text-align: left; transition: all .15s ease; position: relative; }
.mode-btn strong { font-size: 13px; color: #1e293b; }
.mode-btn small { font-size: 11px; color: #64748b; font-weight: 400; margin-top: 2px; }
.mode-btn:hover { border-color: #93c5fd; background: #f0f7ff; }
.mode-btn.active { border-color: #2563eb; background: #eff6ff; box-shadow: 0 0 0 2px #bfdbfe; }
.mode-btn.active strong { color: #1d4ed8; }

.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; position: absolute; right: 10px; top: 12px; }
.dot.live { background: #22c55e; box-shadow: 0 0 6px #22c55e; animation: pulse 1.5s infinite; }
.dot.cpu { background: #64748b; }

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: .7; }
}

.lang-selector { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; }
.lang-selector select { padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; font-size: 13px; font-weight: 500; }

.section-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.section-heading h2 { margin: 0 0 4px; font-size: 18px; }
.section-heading p { margin: 0; font-size: 13px; color: #64748b; }
.badge-realtime { color: #166534; background: #dcfce7; border: 1px solid #bbf7d0; border-radius: 999px; padding: 4px 10px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.cpu-badge { color: #1e293b; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 999px; padding: 4px 10px; font-size: 11px; font-weight: 700; white-space: nowrap; }

.test-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }
.test-field { min-width: 0; padding: 16px; border: 1px solid #e2e8f0; border-radius: 10px; background: #f8fafc; }
.field-topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.field-title { display: flex; align-items: center; gap: 8px; }
.field-title label { font-size: 13px; font-weight: 700; color: #1e293b; }
.live-pill { font-size: 10px; font-weight: 700; background: #fee2e2; color: #dc2626; padding: 2px 6px; border-radius: 4px; animation: pulse 1s infinite; }

.field-actions { display: flex; align-items: center; gap: 6px; }
.field-actions select { max-width: 140px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; font-size: 11px; }
.btn-icon { padding: 4px 8px; font-size: 11px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; color: #475569; cursor: pointer; }
.btn-icon:hover { background: #f1f5f9; color: #0f172a; }
.btn-icon.danger:hover { background: #fee2e2; color: #b91c1c; border-color: #fca5a5; }

.textarea-wrap { position: relative; }
.textarea-wrap textarea { display: block; width: 100%; box-sizing: border-box; padding: 12px 54px 12px 12px; border: 1px solid #cbd5e1; border-radius: 8px; resize: vertical; font: inherit; font-size: 14px; line-height: 1.5; min-height: 120px; }
.textarea-wrap textarea:focus { outline: 2px solid #93c5fd; outline-offset: 1px; border-color: #2563eb; }

.test-mic { position: absolute; right: 9px; top: 9px; width: 42px; height: 42px; display: grid; place-items: center; border: 1px solid #bfdbfe; border-radius: 9px; background: #eff6ff; color: #1d4ed8; cursor: pointer; transition: all .15s ease; box-shadow: 0 2px 6px #2563eb18; }
.test-mic:hover { background: #dbeafe; transform: scale(1.03); }
.test-mic:active { transform: scale(.96); }
.test-mic.recording { color: #dc2626; border-color: #fca5a5; background: #fee2e2; animation: pulse 1.2s infinite; }
.test-mic svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.mic-stop { font-size: 18px; line-height: 1; }
.mic-dots { font-size: 18px; font-weight: 700; line-height: 1; }

.recording-label { display: block; margin-top: 8px; color: #dc2626; font-weight: 600; font-size: 12px; }
.field-error { display: block; margin-top: 8px; color: #b91c1c; font-size: 12px; background: #fef2f2; padding: 4px 8px; border-radius: 4px; border: 1px solid #fecaca; }

.controls { display: grid; gap: 16px; }
.controls label { display: grid; gap: 6px; font-weight: 600; font-size: 13px; }
input[type=number] { width: 90px; padding: 7px; border: 1px solid #cbd5e1; border-radius: 6px; }
input[type=file] { padding: 6px; border: 1px dashed #cbd5e1; border-radius: 6px; background: #f8fafc; }
.models { display: grid; gap: 8px; }
.model-option { display: flex !important; align-items: center; gap: 8px; font-weight: 500 !important; cursor: pointer; }
.model-option small { color: #64748b; font-weight: 400; }

button.primary { background: #2563eb; color: white; border: 0; border-radius: 8px; padding: 10px 18px; font-weight: 600; cursor: pointer; }
button.primary:hover:not(:disabled) { background: #1d4ed8; }
button.secondary { background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
button:disabled { opacity: .5; cursor: not-allowed; }

.results h3 { margin: 0 0 14px; font-size: 16px; }
.result-row { padding: 14px 0; border-bottom: 1px solid #e2e8f0; }
.result-row:last-child { border-bottom: 0; }
.result-text { margin: 8px 0; white-space: pre-wrap; font-size: 14px; line-height: 1.5; color: #1e293b; background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #f1f5f9; }
.result-row small { color: #64748b; margin-right: 12px; }
.active { margin-left: 8px; padding: 2px 8px; border-radius: 999px; color: #166534; background: #dcfce7; font-size: 11px; font-weight: 600; }
.note-pill { margin-left: 8px; padding: 2px 8px; border-radius: 999px; color: #9a3412; background: #ffedd5; font-size: 11px; }

.message { color: #2563eb; font-weight: 600; }
.error { color: #b91c1c; font-weight: 500; }

@media (max-width: 768px) {
  .test-grid { grid-template-columns: 1fr; }
  .section-heading { flex-direction: column; }
  .mode-bar { flex-direction: column; align-items: stretch; }
}
</style>

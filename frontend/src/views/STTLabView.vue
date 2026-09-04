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

const load = async () => {
  try {
    models.value = await sttService.models()
    const config = await sttService.config()
    activeModel.value = config.active_model
    cpuThreads.value = config.cpu_threads
    selected.value = models.value.map(model => model.id)
  } catch (error) { message.value = error.message }
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
</style>

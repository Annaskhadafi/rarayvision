<script setup>
import { ref, computed, onMounted } from 'vue'
import { automlService } from '../services/automlService'
import { API_BASE_URL } from '../utils'

// Ingestion Modes: 'api_url', 'json_paste', 'csv_upload', 'presets'
const ingestionMode = ref('api_url')

// Presets
const presets = ref([])
const selectedPresetId = ref('sales_revenue')

// External API Config
const externalApiUrl = ref('https://jsonplaceholder.typicode.com/posts')
const externalApiMethod = ref('GET')
const externalApiHeader = ref('')
const externalApiBody = ref('')
const externalDataPath = ref('')

// Raw JSON / CSV Config
const customJsonInput = ref('')
const selectedFile = ref(null)

// Shared Params
const datasetName = ref('Data API Eksternal')
const forecastHorizon = ref(14)
const targetColumn = ref('')
const dateColumn = ref('')

// State
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const resultData = ref(null)
const activeTab = ref('analytics') // 'analytics', 'simulation', 'chat_ai', 'table', 'api_integration'

// Tournament Leaderboard Modal
const showLeaderboardModal = ref(false)

// What-If Simulation State
const simGrowthBoost = ref(0)
const simSpikeMultiplier = ref(1.0)
const simSafetyBufferDays = ref(0)
const isSimulating = ref(false)
const isScenarioActive = ref(false)

// Ask AI Chat State
const aiQuestionsList = ref([
  'Berapa safety stock ideal yang harus disiapkan untuk periode proyeksi?',
  'Apa penjelasan dan potensi risiko di balik titik anomali yang terdeteksi?',
  'Rekomendasikan 3 langkah strategis untuk memaksimalkan performa tren saat ini.'
])
const chatInput = ref('')
const chatHistory = ref([])
const isAiThinking = ref(false)

// Integration snippet state
const copiedSnippet = ref(false)
const selectedSnippetLang = ref('curl')

// Interactive Chart Tooltip State
const hoveredPoint = ref(null)
const chartSvgRef = ref(null)

onMounted(async () => {
  try {
    const res = await automlService.getPresets()
    presets.value = res.presets || []
    if (presets.value.length > 0) {
      customJsonInput.value = JSON.stringify(presets.value[0].data, null, 2)
      loadPreset(presets.value[0])
    }
  } catch (err) {
    console.error('Failed to load presets:', err)
  }
})

const loadPreset = (preset) => {
  selectedPresetId.value = preset.id
  datasetName.value = preset.title
  forecastHorizon.value = preset.horizon || 14
  customJsonInput.value = JSON.stringify(preset.data, null, 2)
  selectedFile.value = null
  targetColumn.value = ''
  dateColumn.value = ''
  resetSimulationState()
  chatHistory.value = []
  runAnalysis()
}

const onFileSelect = (event) => {
  const file = event.target.files?.[0]
  if (file) {
    selectedFile.value = file
    datasetName.value = file.name.replace('.csv', '').replace(/_/g, ' ')
    errorMessage.value = ''
    resetSimulationState()
  }
}

const resetSimulationState = () => {
  simGrowthBoost.value = 0
  simSpikeMultiplier.value = 1.0
  simSafetyBufferDays.value = 0
  isScenarioActive.value = false
}

const runAnalysis = async () => {
  isLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  resetSimulationState()

  try {
    let res
    if (ingestionMode.value === 'api_url') {
      if (!externalApiUrl.value.trim()) {
        throw new Error('Harap masukkan URL Endpoint API Eksternal yang valid.')
      }

      let parsedHeaders = {}
      if (externalApiHeader.value.trim()) {
        try {
          parsedHeaders = JSON.parse(externalApiHeader.value)
        } catch (e) {
          // If simple string, assume Authorization header
          parsedHeaders = { "Authorization": externalApiHeader.value.trim() }
        }
      }

      let parsedBody = null
      if (externalApiMethod.value === 'POST' && externalApiBody.value.trim()) {
        try {
          parsedBody = JSON.parse(externalApiBody.value)
        } catch (e) {
          throw new Error('Format Request Body POST harus berupa JSON valid.')
        }
      }

      const payload = {
        api_url: externalApiUrl.value.trim(),
        method: externalApiMethod.value,
        headers: parsedHeaders,
        request_body: parsedBody,
        data_path: externalDataPath.value.trim() || null,
        dataset_name: datasetName.value || 'Data_API_Live',
        forecast_horizon: Number(forecastHorizon.value),
        target_column: targetColumn.value || null,
        date_column: dateColumn.value || null
      }
      res = await automlService.fetchExternalApi(payload)
    } else if (ingestionMode.value === 'csv_upload') {
      if (!selectedFile.value) {
        throw new Error('Silakan pilih atau upload file CSV terlebih dahulu.')
      }
      const formData = new FormData()
      formData.append('file', selectedFile.value)
      formData.append('dataset_name', datasetName.value)
      formData.append('forecast_horizon', forecastHorizon.value)
      if (targetColumn.value) formData.append('target_column', targetColumn.value)
      if (dateColumn.value) formData.append('date_column', dateColumn.value)
      res = await automlService.uploadCsv(formData)
    } else {
      let parsedData = []
      try {
        parsedData = JSON.parse(customJsonInput.value)
      } catch (e) {
        throw new Error('Format JSON data tidak valid. Pastikan berupa array of objects [ { ... } ].')
      }
      
      const payload = {
        dataset_name: datasetName.value,
        data: parsedData,
        forecast_horizon: Number(forecastHorizon.value),
        target_column: targetColumn.value || null,
        date_column: dateColumn.value || null
      }
      res = await automlService.analyzeData(payload)
    }

    resultData.value = res
    successMessage.value = `Berhasil! Model Juara: ${res.tournament_results?.winner?.name} (Akurasi: ${res.tournament_results?.accuracy_score}%) diproses dalam ${res.latency_ms} ms.`
  } catch (err) {
    errorMessage.value = err.message || 'Gagal menjalankan pemrosesan data.'
  } finally {
    isLoading.value = false
  }
}

// ── Real-Time What-If Simulation Trigger ─────────────────────────────────
const applyScenarioSimulation = async () => {
  if (!resultData.value?.job_id) return
  isSimulating.value = true
  try {
    const payload = {
      job_id: resultData.value.job_id,
      growth_boost_pct: Number(simGrowthBoost.value),
      spike_multiplier: Number(simSpikeMultiplier.value),
      safety_buffer_days: Number(simSafetyBufferDays.value)
    }
    const simRes = await automlService.simulateScenario(payload)
    
    resultData.value.table_data = simRes.table_data
    resultData.value.chart_payload = simRes.chart_payload
    resultData.value.summary_metrics = {
      ...resultData.value.summary_metrics,
      ...simRes.summary_metrics
    }
    isScenarioActive.value = (simGrowthBoost.value !== 0 || simSpikeMultiplier.value !== 1.0 || simSafetyBufferDays.value !== 0)
  } catch (err) {
    console.error('Simulation error:', err)
  } finally {
    isSimulating.value = false
  }
}

// ── Ask AI Interactive Chat ──────────────────────────────────────────────
const sendAiQuestion = async (presetQuestion = null) => {
  const query = (presetQuestion || chatInput.value).trim()
  if (!query || !resultData.value?.job_id || isAiThinking.value) return

  chatHistory.value.push({ role: 'user', content: query })
  chatInput.value = ''
  isAiThinking.value = true

  try {
    const payload = {
      job_id: resultData.value.job_id,
      question: query,
      chat_history: chatHistory.value
    }
    const aiRes = await automlService.askAiQuestion(payload)
    chatHistory.value.push({ role: 'assistant', content: aiRes.answer })
  } catch (err) {
    chatHistory.value.push({
      role: 'assistant',
      content: `⚠️ Maaf, terjadi kendala saat meminta analisis AI: ${err.message}`
    })
  } finally {
    isAiThinking.value = false
  }
}

// ── SVG Chart Geometry ──────────────────────────────────────────────────
const chartData = computed(() => {
  if (!resultData.value || !resultData.value.table_data) return null
  const table = resultData.value.table_data

  const allValues = []
  table.forEach(r => {
    if (r.actual_value !== null && r.actual_value !== undefined) allValues.push(r.actual_value)
    if (r.predicted_value !== null && r.predicted_value !== undefined) allValues.push(r.predicted_value)
    if (r.upper_bound !== null && r.upper_bound !== undefined) allValues.push(r.upper_bound)
    if (r.lower_bound !== null && r.lower_bound !== undefined) allValues.push(r.lower_bound)
  })

  if (allValues.length === 0) return null

  const rawMin = Math.min(...allValues)
  const rawMax = Math.max(...allValues)
  const padding = (rawMax - rawMin) * 0.12 || 10
  const yMin = Math.max(0, rawMin - padding)
  const yMax = rawMax + padding

  const width = 850
  const height = 340
  const padLeft = 75
  const padRight = 30
  const padTop = 25
  const padBottom = 45

  const chartW = width - padLeft - padRight
  const chartH = height - padTop - padBottom

  const getX = (index) => padLeft + (index / Math.max(1, table.length - 1)) * chartW
  const getY = (val) => padTop + chartH - ((val - yMin) / Math.max(1e-5, (yMax - yMin))) * chartH

  const actualPoints = []
  const forecastPoints = []
  const upperPoints = []
  const lowerPoints = []
  const anomalyMarkers = []

  let lastActualIndex = -1
  table.forEach((row, idx) => {
    const x = getX(idx)
    
    if (row.actual_value !== null && row.actual_value !== undefined) {
      const y = getY(row.actual_value)
      actualPoints.push({ x, y, row, index: idx })
      lastActualIndex = idx

      if (row.is_anomaly) {
        anomalyMarkers.push({ x, y, row, index: idx })
      }
    }
  })

  if (lastActualIndex >= 0 && actualPoints.length > 0) {
    const lastActual = actualPoints[actualPoints.length - 1]
    forecastPoints.push({ x: lastActual.x, y: lastActual.y, row: lastActual.row, index: lastActualIndex })
    upperPoints.push({ x: lastActual.x, y: lastActual.y, row: lastActual.row, index: lastActualIndex })
    lowerPoints.push({ x: lastActual.x, y: lastActual.y, row: lastActual.row, index: lastActualIndex })
  }

  table.forEach((row, idx) => {
    const x = getX(idx)
    if (row.is_future_forecast) {
      if (row.predicted_value !== null) {
        forecastPoints.push({ x, y: getY(row.predicted_value), row, index: idx })
      }
      if (row.upper_bound !== null) {
        upperPoints.push({ x, y: getY(row.upper_bound), row, index: idx })
      }
      if (row.lower_bound !== null) {
        lowerPoints.push({ x, y: getY(row.lower_bound), row, index: idx })
      }
    }
  })

  const makePath = (pts) => {
    if (pts.length === 0) return ''
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  }

  const actualPath = makePath(actualPoints)
  const forecastPath = makePath(forecastPoints)

  let confidenceAreaPath = ''
  if (upperPoints.length > 0 && lowerPoints.length > 0) {
    const upperStr = upperPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
    const lowerReversed = [...lowerPoints].reverse()
    const lowerStr = lowerReversed.map(p => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
    confidenceAreaPath = `${upperStr} ${lowerStr} Z`
  }

  const yTicks = []
  const tickCount = 5
  for (let i = 0; i <= tickCount; i++) {
    const val = yMin + (i / tickCount) * (yMax - yMin)
    const y = getY(val)
    yTicks.push({ val: Math.round(val), y })
  }

  const xTicks = []
  const step = Math.max(1, Math.floor(table.length / 6))
  for (let i = 0; i < table.length; i += step) {
    xTicks.push({ label: table[i].date, x: getX(i) })
  }
  if (table.length > 0 && xTicks[xTicks.length - 1].x < getX(table.length - 1) - 40) {
    xTicks.push({ label: table[table.length - 1].date, x: getX(table.length - 1) })
  }

  return {
    width,
    height,
    padLeft,
    padRight,
    padTop,
    padBottom,
    actualPath,
    forecastPath,
    confidenceAreaPath,
    actualPoints,
    forecastPoints,
    anomalyMarkers,
    yTicks,
    xTicks,
    table
  }
})

// Search & Pagination in Table Explorer
const tableSearch = ref('')
const tablePage = ref(1)
const pageSize = 10

const filteredTable = computed(() => {
  if (!resultData.value || !resultData.value.table_data) return []
  const list = resultData.value.table_data
  if (!tableSearch.value.trim()) return list
  const q = tableSearch.value.toLowerCase()
  return list.filter(r => 
    String(r.date).toLowerCase().includes(q) ||
    String(r.actual_value).includes(q) ||
    String(r.predicted_value).includes(q)
  )
})

const paginatedTable = computed(() => {
  const start = (tablePage.value - 1) * pageSize
  return filteredTable.value.slice(start, start + pageSize)
})

const totalTablePages = computed(() => Math.ceil(filteredTable.value.length / pageSize) || 1)

// Snippets
const getIntegrationSnippet = computed(() => {
  const apiUrl = `${API_BASE_URL}/api/v1/automl/analyze-and-predict`
  const widgetUrl = resultData.value ? resultData.value.embed_widget_url : `${API_BASE_URL}/api/v1/automl/widget/job_sample`
  const iframeCode = resultData.value ? resultData.value.embed_iframe_code : `<iframe src="${widgetUrl}" width="100%" height="600" frameborder="0"></iframe>`

  const sampleJson = {
    dataset_name: datasetName.value,
    forecast_horizon: forecastHorizon.value,
    data: presets.value.find(p => p.id === selectedPresetId.value)?.data?.slice(0, 3) || [
      { date: "2026-01-01", total_sales: 15000000 },
      { date: "2026-01-02", total_sales: 18500000 },
      { date: "2026-01-03", total_sales: 12000000 }
    ]
  }

  if (selectedSnippetLang.value === 'curl') {
    return `curl -X POST "${apiUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(sampleJson, null, 2)}'`
  } else if (selectedSnippetLang.value === 'python') {
    return `import requests

url = "${apiUrl}"
payload = ${JSON.stringify(sampleJson, null, 4)}

response = requests.post(url, json=payload)
data = response.json()

print("Model Juara:", data["tournament_results"]["winner"]["name"])
print("Akurasi:", data["tournament_results"]["accuracy_score"], "%")
print("AI Report:", data["ai_interpretation"])`
  } else if (selectedSnippetLang.value === 'javascript') {
    return `const response = await fetch("${apiUrl}", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${JSON.stringify(sampleJson, null, 2)})
});

const data = await response.json();
console.log("Accuracy:", data.tournament_results.accuracy_score + "%");
console.log("Forecasts:", data.table_data);`
  } else if (selectedSnippetLang.value === 'iframe') {
    return `<!-- Pasang di Website / Portal Klien Anda -->
${iframeCode}`
  }
  return ''
})

const copySnippet = () => {
  navigator.clipboard.writeText(getIntegrationSnippet.value)
  copiedSnippet.value = true
  setTimeout(() => { copiedSnippet.value = false }, 2000)
}

const openWidgetTab = () => {
  if (resultData.value && resultData.value.embed_widget_url) {
    window.open(resultData.value.embed_widget_url, '_blank')
  }
}

const downloadCsv = () => {
  if (!resultData.value || !resultData.value.table_data) return
  const headers = ['Date', 'Actual_Value', 'Predicted_Value', 'Lower_95', 'Upper_95', 'Is_Anomaly', 'Is_Forecast']
  const rows = resultData.value.table_data.map(r => [
    r.date,
    r.actual_value !== null ? r.actual_value : '',
    r.predicted_value !== null ? r.predicted_value : '',
    r.lower_bound !== null ? r.lower_bound : '',
    r.upper_bound !== null ? r.upper_bound : '',
    r.is_anomaly ? 'TRUE' : 'FALSE',
    r.is_future_forecast ? 'TRUE' : 'FALSE'
  ])
  const csvContent = [headers.join(','), ...rows.map(e => e.join(','))].join('\n')
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.setAttribute('href', url)
  link.setAttribute('download', `${datasetName.value.replace(/\s+/g, '_')}_forecast.csv`)
  link.click()
}
</script>

<template>
  <div class="automl-container">
    <!-- Header -->
    <div class="header-section">
      <div class="title-group">
        <div class="badge-tag">
          <span class="pulse-dot"></span>
          Ultra-Fast AutoML & Multi-Model Tournament Engine
        </div>
        <h1 class="page-title">Enterprise Forecasting & AI Data Analytics</h1>
        <p class="page-desc">
          Menganalisis pola deret waktu, turnamen multi-model akurasi otomatis, simulasi skenario bisnis *What-If* real-time (&lt;15ms), dan interpretasi strategis berbasis AI.
        </p>
      </div>

      <div class="header-actions">
        <button v-if="resultData?.tournament_results" class="btn-tournament" @click="showLeaderboardModal = true">
          🏆 Akurasi: {{ resultData.tournament_results.accuracy_score }}%
        </button>
        <button v-if="resultData?.embed_widget_url" class="btn-secondary" @click="openWidgetTab">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          Buka Widget
        </button>
        <button class="btn-primary" :disabled="isLoading" @click="runAnalysis">
          <svg v-if="isLoading" class="animate-spin" viewBox="0 0 24 24" width="16" height="16" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" class="opacity-25"></circle><path fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" class="opacity-75"></path></svg>
          <svg v-else viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
          {{ isLoading ? 'Memproses Data...' : 'Tarik & Analisis Data' }}
        </button>
      </div>
    </div>

    <!-- Feedback Alerts -->
    <div v-if="errorMessage" class="alert alert-error">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      <span>{{ errorMessage }}</span>
    </div>
    <div v-if="successMessage" class="alert alert-success">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
      <span>{{ successMessage }}</span>
    </div>

    <!-- Data Ingestion Control Card (Clean White Card) -->
    <div class="control-panel">
      <!-- Ingestion Mode Selector Tabs -->
      <div class="mode-nav-tabs">
        <button 
          class="mode-tab" 
          :class="{ active: ingestionMode === 'api_url' }"
          @click="ingestionMode = 'api_url'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
          1. Input Endpoint API Eksternal
        </button>
        <button 
          class="mode-tab" 
          :class="{ active: ingestionMode === 'json_paste' }"
          @click="ingestionMode = 'json_paste'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
          2. Paste Raw JSON Data
        </button>
        <button 
          class="mode-tab" 
          :class="{ active: ingestionMode === 'csv_upload' }"
          @click="ingestionMode = 'csv_upload'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
          3. Upload CSV File
        </button>
        <button 
          class="mode-tab" 
          :class="{ active: ingestionMode === 'presets' }"
          @click="ingestionMode = 'presets'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
          4. Preset Demo Cepat
        </button>
      </div>

      <!-- MODE 1: EXTERNAL API URL -->
      <div v-if="ingestionMode === 'api_url'" class="mode-content">
        <div class="api-inputs-grid">
          <div class="input-group-full">
            <label class="param-label">URL Endpoint API Eksternal (Website / Server Anda):</label>
            <div class="url-input-wrap">
              <select v-model="externalApiMethod" class="method-select">
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
              <input 
                type="text" 
                v-model="externalApiUrl" 
                placeholder="https://api.domainanda.com/v1/sales-records" 
                class="param-input url-field"
              >
            </div>
            <span class="field-hint">Sistem akan otomatis memanggil URL ini, membaca data tabel JSON, dan memproses analisis & prediksinya.</span>
          </div>

          <div class="param-box">
            <label class="param-label">Auth Token / Headers (Opsional):</label>
            <input 
              type="text" 
              v-model="externalApiHeader" 
              placeholder='Bearer token123 atau {"X-API-Key":"..."}' 
              class="param-input"
            >
          </div>

          <div class="param-box">
            <label class="param-label">Data Key Path (Jika data terbungkus):</label>
            <input 
              type="text" 
              v-model="externalDataPath" 
              placeholder='Contoh: "data" atau "items"' 
              class="param-input"
            >
          </div>
        </div>
      </div>

      <!-- MODE 2: RAW JSON PASTE -->
      <div v-if="ingestionMode === 'json_paste'" class="mode-content">
        <label class="param-label">Paste Array JSON Data Tabel di Sini:</label>
        <textarea 
          v-model="customJsonInput" 
          rows="5" 
          placeholder='[{"date": "2026-01-01", "total_sales": 15000000}, {"date": "2026-01-02", "total_sales": 18500000}]' 
          class="json-textarea font-mono"
        ></textarea>
      </div>

      <!-- MODE 3: CSV UPLOAD -->
      <div v-if="ingestionMode === 'csv_upload'" class="mode-content">
        <label class="param-label">Upload File CSV:</label>
        <div class="csv-dropzone">
          <input type="file" accept=".csv" @change="onFileSelect" class="file-input-hidden" id="csvFileInput">
          <label for="csvFileInput" class="csv-label">
            <svg viewBox="0 0 24 24" width="32" height="32" stroke="#2563eb" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            <span class="file-main-text">{{ selectedFile ? selectedFile.name : 'Klik untuk memilih file CSV (.csv)' }}</span>
            <span class="file-sub-text">Mendukung format CSV dengan header kolom tanggal dan angka</span>
          </label>
        </div>
      </div>

      <!-- MODE 4: PRESETS -->
      <div v-if="ingestionMode === 'presets'" class="mode-content">
        <label class="param-label">Pilih Dataset Contoh:</label>
        <div class="preset-pills">
          <button 
            v-for="p in presets" 
            :key="p.id" 
            class="preset-btn" 
            :class="{ active: selectedPresetId === p.id }"
            @click="loadPreset(p)"
          >
            {{ p.title }}
          </button>
        </div>
      </div>

      <!-- Shared Configuration Row -->
      <div class="control-row">
        <div class="param-box">
          <label class="param-label">Nama Dataset / Label:</label>
          <input type="text" v-model="datasetName" placeholder="Data Analitik 2026" class="param-input">
        </div>

        <div class="param-box">
          <label class="param-label">Horizon Prediksi (Hari ke Depan):</label>
          <div class="range-wrapper">
            <input type="range" min="7" max="45" step="1" v-model="forecastHorizon" class="range-slider">
            <span class="range-val">{{ forecastHorizon }} Hari</span>
          </div>
        </div>

        <div class="param-box">
          <label class="param-label">Target Nilai (Auto/Manual):</label>
          <input type="text" v-model="targetColumn" placeholder="Auto-detect (e.g. total_sales)" class="param-input">
        </div>

        <div class="param-box">
          <label class="param-label">Kolom Waktu (Auto/Manual):</label>
          <input type="text" v-model="dateColumn" placeholder="Auto-detect (e.g. date)" class="param-input">
        </div>
      </div>
    </div>

    <!-- Main Analytics Content -->
    <div v-if="resultData" class="analytics-content">
      <!-- Auto Detection & Tournament Winner Banner -->
      <div class="autodetect-banner">
        <div class="autodetect-info">
          <div class="banner-top-badges">
            <span class="badge-tech">
              <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
              {{ resultData.auto_detection.task_label }}
            </span>
            <span class="badge-winner">
              Model Juara: <b>{{ resultData.tournament_results.winner.name }}</b>
            </span>
          </div>
          <div class="autodetect-meta">
            Target: <b>{{ resultData.dataset_info.target_column }}</b> • 
            Waktu: <b>{{ resultData.dataset_info.date_column || 'Otomatis' }}</b> • 
            Ukuran Data: <b>{{ resultData.dataset_info.sample_size }} Baris</b> •
            Horizon: <b>{{ resultData.dataset_info.forecast_horizon }} Hari</b>
          </div>
        </div>
        <div class="banner-right">
          <div class="accuracy-highlight">
            <div class="acc-score">{{ resultData.tournament_results.accuracy_score }}%</div>
            <div class="acc-label">Akurasi Prediksi</div>
          </div>
        </div>
      </div>

      <!-- Key Metric Cards -->
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-header">
            <span class="m-label">Arah Tren Proyeksi</span>
            <span class="m-icon-box green">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="#059669" stroke-width="2.5" fill="none"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>
            </span>
          </div>
          <div class="m-value text-green">{{ resultData.summary_metrics.trend_direction }}</div>
          <div class="m-sub">
            Pertumbuhan: <b>{{ resultData.summary_metrics.simulated_growth_pct ?? resultData.summary_metrics.projected_growth_pct }}%</b>
            <span v-if="isScenarioActive" class="badge-sim-tag">(Simulasi)</span>
          </div>
        </div>

        <div class="metric-card">
          <div class="metric-header">
            <span class="m-label">Rata-Rata Historis</span>
            <span class="m-icon-box blue">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="#2563eb" stroke-width="2.5" fill="none"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
            </span>
          </div>
          <div class="m-value">{{ Number(resultData.summary_metrics.historical_mean).toLocaleString('id-ID') }}</div>
          <div class="m-sub">Baseline performa data riil</div>
        </div>

        <div class="metric-card">
          <div class="metric-header">
            <span class="m-label">Puncak Estimasi Masa Depan</span>
            <span class="m-icon-box purple">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="#7c3aed" stroke-width="2.5" fill="none"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
            </span>
          </div>
          <div class="m-value text-purple">{{ Number(resultData.summary_metrics.simulated_peak_forecast_value ?? resultData.summary_metrics.peak_forecast_value).toLocaleString('id-ID') }}</div>
          <div class="m-sub">Titik tertinggi pada periode prediksi</div>
        </div>

        <div class="metric-card">
          <div class="metric-header">
            <span class="m-label">Anomali Terdeteksi</span>
            <span class="m-icon-box red">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="#dc2626" stroke-width="2.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            </span>
          </div>
          <div class="m-value text-red">{{ resultData.summary_metrics.anomalies_detected_count }} Titik</div>
          <div class="m-sub">Penyimpangan data signifikan</div>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="nav-tabs">
        <button class="tab-btn" :class="{ active: activeTab === 'analytics' }" @click="activeTab = 'analytics'">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>
          Grafik & Interpretasi AI
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'simulation' }" @click="activeTab = 'simulation'">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
          Simulasi "What-If" Interaktif
          <span v-if="isScenarioActive" class="tab-dot-alert"></span>
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'chat_ai' }" @click="activeTab = 'chat_ai'">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          Tanya AI tentang Data Ini
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'table' }" @click="activeTab = 'table'">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="18" height="18" rx="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="3" y1="15" x2="21" y2="15"></line><line x1="9" y1="3" x2="9" y2="21"></line></svg>
          Tabel Prediksi ({{ resultData.table_data.length }})
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'api_integration' }" @click="activeTab = 'api_integration'">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
          Integrasi API & Iframe
        </button>
      </div>

      <!-- TAB 1: CHART & AI INTERPRETATION -->
      <div v-if="activeTab === 'analytics'" class="tab-content">
        <div class="chart-card">
          <div class="chart-card-header">
            <div>
              <h3 class="chart-title">Visualisasi Deret Waktu & Forecast Horizon</h3>
              <p class="chart-subtitle">Garis biru: data riil • Garis putus hijau: proyeksi prediksi • Area hijau muda: 95% Confidence Interval</p>
            </div>
            <div class="legend-group">
              <span class="legend-item"><span class="legend-box blue"></span> Aktual</span>
              <span class="legend-item"><span class="legend-box green dashed"></span> Prediksi ML</span>
              <span class="legend-item"><span class="legend-box green-area"></span> Interval 95%</span>
              <span class="legend-item"><span class="legend-box red-dot"></span> Anomali</span>
            </div>
          </div>

          <div class="svg-chart-container" ref="chartSvgRef">
            <svg v-if="chartData" :viewBox="`0 0 ${chartData.width} ${chartData.height}`" class="main-svg-chart">
              <defs>
                <linearGradient id="areaGradientLight" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#10B981" stop-opacity="0.30" />
                  <stop offset="100%" stop-color="#10B981" stop-opacity="0.05" />
                </linearGradient>
                <filter id="glowLight" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="2.5" result="glow" />
                  <feComposite in="SourceGraphic" in2="glow" operator="over" />
                </filter>
              </defs>

              <g class="grid-lines">
                <line 
                  v-for="(tick, i) in chartData.yTicks" 
                  :key="i" 
                  :x1="chartData.padLeft" 
                  :y1="tick.y" 
                  :x2="chartData.width - chartData.padRight" 
                  :y2="tick.y" 
                  stroke="#e2e8f0" 
                  stroke-dasharray="3,3" 
                  stroke-width="1"
                />
                <text 
                  v-for="(tick, i) in chartData.yTicks" 
                  :key="`lbl-${i}`" 
                  :x="chartData.padLeft - 10" 
                  :y="tick.y + 4" 
                  fill="#64748b" 
                  font-size="11" 
                  font-weight="500"
                  text-anchor="end"
                >
                  {{ tick.val.toLocaleString('id-ID') }}
                </text>
              </g>

              <path 
                v-if="chartData.confidenceAreaPath" 
                :d="chartData.confidenceAreaPath" 
                fill="url(#areaGradientLight)"
              />

              <path 
                :d="chartData.actualPath" 
                fill="none" 
                stroke="#2563EB" 
                stroke-width="3" 
                stroke-linecap="round" 
                stroke-linejoin="round"
              />

              <path 
                :d="chartData.forecastPath" 
                fill="none" 
                stroke="#059669" 
                stroke-width="3" 
                stroke-dasharray="6,5" 
                stroke-linecap="round" 
                stroke-linejoin="round"
              />

              <circle 
                v-for="p in chartData.actualPoints" 
                :key="`act-${p.index}`" 
                :cx="p.x" 
                :cy="p.y" 
                r="3.5" 
                fill="#FFFFFF" 
                stroke="#2563EB" 
                stroke-width="2.5" 
                class="hover-circle"
                @mouseenter="hoveredPoint = p"
                @mouseleave="hoveredPoint = null"
              />

              <circle 
                v-for="p in chartData.forecastPoints" 
                :key="`fc-${p.index}`" 
                :cx="p.x" 
                :cy="p.y" 
                r="3.5" 
                fill="#FFFFFF" 
                stroke="#059669" 
                stroke-width="2.5" 
                class="hover-circle"
                @mouseenter="hoveredPoint = p"
                @mouseleave="hoveredPoint = null"
              />

              <g v-for="anom in chartData.anomalyMarkers" :key="`anom-${anom.index}`">
                <circle :cx="anom.x" :cy="anom.y" r="8" fill="none" stroke="#DC2626" stroke-width="2" opacity="0.8" filter="url(#glowLight)" />
                <circle :cx="anom.x" :cy="anom.y" r="4.5" fill="#DC2626" stroke="#FFF" stroke-width="1.5" />
              </g>

              <g class="x-axis-labels">
                <text 
                  v-for="(tick, i) in chartData.xTicks" 
                  :key="`xtick-${i}`" 
                  :x="tick.x" 
                  :y="chartData.height - 10" 
                  fill="#64748b" 
                  font-size="10.5" 
                  font-weight="500"
                  text-anchor="middle"
                >
                  {{ tick.label }}
                </text>
              </g>
            </svg>

            <div 
              v-if="hoveredPoint" 
              class="chart-tooltip"
              :style="{
                left: `${(hoveredPoint.x / (chartData?.width || 1)) * 100}%`,
                top: `${(hoveredPoint.y / (chartData?.height || 1)) * 100}%`
              }"
            >
              <div class="tooltip-date">📅 {{ hoveredPoint.row.date }}</div>
              <div v-if="hoveredPoint.row.actual_value !== null" class="tooltip-val blue">
                Nilai Aktual: <b>{{ hoveredPoint.row.actual_value.toLocaleString('id-ID') }}</b>
              </div>
              <div v-if="hoveredPoint.row.predicted_value !== null" class="tooltip-val green">
                Prediksi ML: <b>{{ hoveredPoint.row.predicted_value.toLocaleString('id-ID') }}</b>
                <div class="tooltip-bounds">Interval 95%: {{ hoveredPoint.row.lower_bound?.toLocaleString('id-ID') }} – {{ hoveredPoint.row.upper_bound?.toLocaleString('id-ID') }}</div>
              </div>
              <div v-if="hoveredPoint.row.is_anomaly" class="tooltip-badge-anom">
                ⚠️ Titik Anomali (Skor: {{ Math.round(hoveredPoint.row.anomaly_score * 100) }}%)
              </div>
            </div>
          </div>
        </div>

        <!-- AI Executive Report Card -->
        <div class="ai-card">
          <div class="ai-header">
            <div class="ai-title-wrap">
              <span class="ai-sparkle">✨</span>
              <div>
                <h3 class="ai-title">Laporan Eksekutif & Interpretasi Bisnis AI</h3>
                <p class="ai-subtitle">Dianalisis secara otomatis berdasarkan perpaduan model statistika & LLM</p>
              </div>
            </div>
            <span class="ai-badge">{{ resultData.ai_source }}</span>
          </div>

          <div class="ai-body markdown-content">
            <div class="formatted-ai-text" v-html="resultData.ai_interpretation.replace(/\n/g, '<br>')"></div>
          </div>
        </div>
      </div>

      <!-- TAB 2: WHAT-IF SCENARIO SIMULATOR -->
      <div v-if="activeTab === 'simulation'" class="tab-content">
        <div class="sim-card">
          <div class="sim-header">
            <div>
              <h3 class="sim-title">🎛️ Real-Time "What-If" Scenario Simulator (&lt;15ms)</h3>
              <p class="sim-desc">Geser slider di bawah untuk melihat simulasi dampak lonjakan promo, perubahan pasar, atau penyesuaian buffer stock secara instan.</p>
            </div>
            <button class="btn-secondary" @click="resetSimulationState(); applyScenarioSimulation();">
              Reset Skenario
            </button>
          </div>

          <div class="sim-controls-grid">
            <div class="sim-control-box">
              <div class="sim-ctrl-label">
                <span>Penyesuaian Pertumbuhan Permintaan (+/- %)</span>
                <span class="sim-badge-val" :class="{ positive: simGrowthBoost > 0, negative: simGrowthBoost < 0 }">
                  {{ simGrowthBoost > 0 ? '+' : '' }}{{ simGrowthBoost }}%
                </span>
              </div>
              <input 
                type="range" 
                min="-40" 
                max="60" 
                step="5" 
                v-model="simGrowthBoost" 
                class="range-slider"
                @input="applyScenarioSimulation"
              >
              <div class="sim-hint">Simulasi kenaikan atau penurunan pasar secara keseluruhan.</div>
            </div>

            <div class="sim-control-box">
              <div class="sim-ctrl-label">
                <span>Pengali Lonjakan Promo / Event (Multiplier)</span>
                <span class="sim-badge-val">{{ simSpikeMultiplier }}x</span>
              </div>
              <input 
                type="range" 
                min="1.0" 
                max="2.5" 
                step="0.1" 
                v-model="simSpikeMultiplier" 
                class="range-slider"
                @input="applyScenarioSimulation"
              >
              <div class="sim-hint">Simulasi kampanye diskon besar / pesanan grosir mendadak.</div>
            </div>

            <div class="sim-control-box">
              <div class="sim-ctrl-label">
                <span>Kebutuhan Safety Stock Buffer (Hari)</span>
                <span class="sim-badge-val">{{ simSafetyBufferDays }} Hari</span>
              </div>
              <input 
                type="range" 
                min="0" 
                max="14" 
                step="1" 
                v-model="simSafetyBufferDays" 
                class="range-slider"
                @input="applyScenarioSimulation"
              >
              <div class="sim-hint">Estimasi stok cadangan untuk mencegah kehabisan barang.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 3: ASK AI CHAT -->
      <div v-if="activeTab === 'chat_ai'" class="tab-content">
        <div class="chat-card">
          <div class="chat-header">
            <div class="chat-title-wrap">
              <span class="ai-sparkle">💬</span>
              <div>
                <h3 class="chat-title">Tanya AI tentang Analitik Dataset Ini</h3>
                <p class="chat-subtitle">AI memahami matriks data, skor akurasi model, dan titik anomali yang baru saja diproses.</p>
              </div>
            </div>
          </div>

          <div class="quick-prompts">
            <span class="quick-label">Pertanyaan Cepat:</span>
            <button 
              v-for="(q, idx) in aiQuestionsList" 
              :key="idx" 
              class="quick-btn"
              :disabled="isAiThinking"
              @click="sendAiQuestion(q)"
            >
              💡 {{ q }}
            </button>
          </div>

          <div class="chat-messages-box">
            <div v-if="chatHistory.length === 0" class="chat-empty">
              <p>Pilih pertanyaan cepat di atas atau ketik pertanyaan spesifik seputar analisis data ini...</p>
            </div>
            <div 
              v-for="(msg, i) in chatHistory" 
              :key="i" 
              class="chat-bubble-wrap"
              :class="{ user: msg.role === 'user', assistant: msg.role === 'assistant' }"
            >
              <div class="chat-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
              <div class="chat-bubble">
                <div class="chat-sender">{{ msg.role === 'user' ? 'Anda' : 'Hero AI Analyst' }}</div>
                <div class="chat-text" v-html="msg.content.replace(/\n/g, '<br>')"></div>
              </div>
            </div>

            <div v-if="isAiThinking" class="chat-bubble-wrap assistant">
              <div class="chat-avatar">🤖</div>
              <div class="chat-bubble thinking">
                <span class="animate-pulse">Sedang menganalisis data dan menyusun jawaban...</span>
              </div>
            </div>
          </div>

          <form class="chat-input-bar" @submit.prevent="sendAiQuestion()">
            <input 
              type="text" 
              v-model="chatInput" 
              placeholder="Ketik pertanyaan analitik data di sini..." 
              class="chat-input"
              :disabled="isAiThinking"
            >
            <button type="submit" class="btn-primary" :disabled="!chatInput.trim() || isAiThinking">
              Kirim
            </button>
          </form>
        </div>
      </div>

      <!-- TAB 4: TABLE EXPLORER -->
      <div v-if="activeTab === 'table'" class="tab-content">
        <div class="table-card">
          <div class="table-toolbar">
            <div class="search-box">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <input type="text" v-model="tableSearch" placeholder="Cari tanggal atau nominal..." class="search-input">
            </div>
            <button class="btn-secondary" @click="downloadCsv">
              <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              Download CSV
            </button>
          </div>

          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Periode / Tanggal</th>
                  <th>Nilai Aktual</th>
                  <th>Prediksi ML</th>
                  <th>Batas Bawah (95%)</th>
                  <th>Batas Atas (95%)</th>
                  <th>Status / Keterangan</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in paginatedTable" :key="i" :class="{ 'row-forecast': row.is_future_forecast, 'row-anomaly': row.is_anomaly }">
                  <td class="font-mono">{{ row.date }}</td>
                  <td class="font-bold">{{ row.actual_value !== null ? row.actual_value.toLocaleString('id-ID') : '-' }}</td>
                  <td class="font-bold text-green">{{ row.predicted_value !== null ? row.predicted_value.toLocaleString('id-ID') : '-' }}</td>
                  <td class="text-muted">{{ row.lower_bound !== null ? row.lower_bound.toLocaleString('id-ID') : '-' }}</td>
                  <td class="text-muted">{{ row.upper_bound !== null ? row.upper_bound.toLocaleString('id-ID') : '-' }}</td>
                  <td>
                    <span v-if="row.is_anomaly" class="tag-status tag-anomaly">⚠️ Anomali</span>
                    <span v-else-if="row.is_future_forecast" class="tag-status tag-forecast">🔮 Forecast AI</span>
                    <span v-else class="tag-status tag-actual">✓ Data Riil</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="pagination-bar">
            <div class="page-info">Menampilkan {{ paginatedTable.length }} dari {{ filteredTable.length }} baris data</div>
            <div class="page-btns">
              <button class="btn-page" :disabled="tablePage <= 1" @click="tablePage--">Sebelumnya</button>
              <span class="page-num">{{ tablePage }} / {{ totalTablePages }}</span>
              <button class="btn-page" :disabled="tablePage >= totalTablePages" @click="tablePage++">Selanjutnya</button>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 5: API & INTEGRATION -->
      <div v-if="activeTab === 'api_integration'" class="tab-content">
        <div class="integration-card">
          <div class="int-header">
            <h3 class="int-title">Integrasikan ke Website atau Portal Lain</h3>
            <p class="int-desc">Gunakan REST API untuk data mentah atau gunakan iframe untuk memasang widget grafik interaktif di website klien Anda.</p>
          </div>

          <div class="lang-pills">
            <button class="lang-btn" :class="{ active: selectedSnippetLang === 'curl' }" @click="selectedSnippetLang = 'curl'">cURL / Terminal</button>
            <button class="lang-btn" :class="{ active: selectedSnippetLang === 'python' }" @click="selectedSnippetLang = 'python'">Python Requests</button>
            <button class="lang-btn" :class="{ active: selectedSnippetLang === 'javascript' }" @click="selectedSnippetLang = 'javascript'">JavaScript (Fetch / Axios)</button>
            <button class="lang-btn" :class="{ active: selectedSnippetLang === 'iframe' }" @click="selectedSnippetLang = 'iframe'">HTML &lt;iframe&gt; Embed</button>
          </div>

          <div class="code-wrapper">
            <div class="code-top">
              <span class="code-lang">{{ selectedSnippetLang.toUpperCase() }}</span>
              <button class="copy-btn" @click="copySnippet">
                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                {{ copiedSnippet ? 'Tersalin ke Clipboard!' : 'Salin Kode' }}
              </button>
            </div>
            <pre class="code-block"><code>{{ getIntegrationSnippet }}</code></pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Tournament Leaderboard Modal -->
    <div v-if="showLeaderboardModal" class="modal-backdrop" @click="showLeaderboardModal = false">
      <div class="modal-card" @click.stop>
        <div class="modal-header">
          <h3 class="modal-title">🏆 Turnamen Model ML & Leaderboard Akurasi</h3>
          <button class="modal-close" @click="showLeaderboardModal = false">✕</button>
        </div>
        <div class="modal-body">
          <p class="modal-desc">
            Sistem secara otomatis mengevaluasi 4 algoritma deret waktu in-memory menggunakan teknik *backtesting out-of-sample* untuk memilih model dengan nilai MAPE (Mean Absolute Percentage Error) terendah.
          </p>
          <table class="leaderboard-table">
            <thead>
              <tr>
                <th>Peringkat & Algoritma</th>
                <th>MAPE (Error %)</th>
                <th>RMSE</th>
                <th>MAE</th>
              </tr>
            </thead>
            <tbody>
              <tr 
                v-for="(m, idx) in resultData?.tournament_results?.leaderboard" 
                :key="m.model_id"
                :class="{ 'row-winner': idx === 0 }"
              >
                <td>
                  <div class="model-name">
                    <span v-if="idx === 0">🥇</span>
                    <span v-else>{{ idx + 1 }}.</span>
                    <b>{{ m.name }}</b>
                  </div>
                  <div class="model-desc">{{ m.desc }}</div>
                </td>
                <td><b :class="{ 'text-green': idx === 0 }">{{ m.mape }}%</b></td>
                <td>{{ m.rmse.toLocaleString('id-ID') }}</td>
                <td>{{ m.mae.toLocaleString('id-ID') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.automl-container {
  padding: 24px;
  max-width: 1350px;
  margin: 0 auto;
  color: #0f172a !important;
  background: transparent !important;
}

/* Header */
.header-section {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  padding: 4px 12px;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  margin-bottom: 8px;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 6px rgba(37, 99, 235, 0.6);
}

.page-title {
  font-size: 1.6rem;
  font-weight: 800;
  color: #0f172a !important;
  letter-spacing: -0.5px;
  margin: 0 0 6px 0;
}

.page-desc {
  font-size: 0.9rem;
  color: #475569 !important;
  max-width: 750px;
  margin: 0;
  line-height: 1.5;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-tournament {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #047857;
  padding: 9px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.btn-tournament:hover { background: #d1fae5; }

.btn-primary {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #ffffff !important;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.875rem;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
  transition: all 0.2s;
}
.btn-primary:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
}

.btn-secondary {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 9px 15px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.btn-secondary:hover { background: #f8fafc; border-color: #94a3b8; color: #0f172a; }

/* Alerts */
.alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; font-size: 0.875rem; }
.alert-error { background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c; }
.alert-success { background: #f0fdf4; border: 1px solid #bbf7d0; color: #15803d; }

/* Control Panel (Clean Light Card) */
.control-panel {
  background: #ffffff !important;
  border: 1px solid #e2e8f0 !important;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.02);
}

/* Ingestion Mode Navigation Tabs */
.mode-nav-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 12px;
  margin-bottom: 16px;
  overflow-x: auto;
}

.mode-tab {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.825rem;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
  white-space: nowrap;
}
.mode-tab:hover { background: #f1f5f9; color: #0f172a; }
.mode-tab.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
  box-shadow: 0 1px 3px rgba(59, 130, 246, 0.15);
}

.mode-content {
  margin-bottom: 16px;
}

/* API Inputs Grid */
.api-inputs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.input-group-full {
  grid-column: 1 / -1;
}

.url-input-wrap {
  display: flex;
  gap: 8px;
}

.method-select {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #0f172a;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
}

.url-field {
  flex: 1;
}

.field-hint {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 4px;
  display: block;
}

/* JSON Textarea */
.json-textarea {
  width: 100%;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #0f172a;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.5;
  resize: vertical;
}
.json-textarea:focus { outline: none; border-color: #2563eb; background: #ffffff; }

/* CSV Dropzone */
.file-input-hidden { display: none; }
.csv-dropzone {
  border: 2px dashed #94a3b8;
  border-radius: 8px;
  padding: 24px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s;
}
.csv-dropzone:hover { background: #eff6ff; border-color: #3b82f6; }
.csv-label { cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.file-main-text { font-size: 0.9rem; font-weight: 600; color: #0f172a; }
.file-sub-text { font-size: 0.775rem; color: #64748b; }

.preset-pills { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.preset-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.825rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.preset-btn:hover { background: #f1f5f9; border-color: #94a3b8; }
.preset-btn.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
  font-weight: 600;
}

.control-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.param-label { font-size: 0.775rem; font-weight: 700; color: #475569; margin-bottom: 6px; display: block; }
.range-wrapper { display: flex; align-items: center; gap: 10px; }
.range-slider { flex: 1; accent-color: #2563eb; cursor: pointer; }
.range-val { font-size: 0.85rem; font-weight: 700; color: #1d4ed8; min-width: 60px; }
.param-input { width: 100%; background: #f8fafc; border: 1px solid #cbd5e1; color: #0f172a; padding: 8px 12px; border-radius: 6px; font-size: 0.825rem; }
.param-input:focus { outline: none; border-color: #2563eb; background: #ffffff; }

/* Auto-detect Banner */
.autodetect-banner {
  background: linear-gradient(135deg, #f0f9ff, #f8fafc);
  border: 1px solid #bae6fd;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

.banner-top-badges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.badge-tech { display: inline-flex; align-items: center; gap: 6px; color: #0369a1; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
.badge-winner { background: #dcfce7; border: 1px solid #86efac; color: #15803d; padding: 3px 10px; border-radius: 6px; font-size: 0.775rem; font-weight: 500; }
.autodetect-meta { font-size: 0.825rem; color: #475569; margin-top: 6px; }

.accuracy-highlight {
  text-align: right;
  background: #ffffff;
  border: 1px solid #bfdbfe;
  padding: 8px 16px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.acc-score { font-size: 1.4rem; font-weight: 800; color: #059669; }
.acc-label { font-size: 0.7rem; font-weight: 600; color: #64748b; text-transform: uppercase; }

/* Metric Cards */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.metric-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
}
.metric-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.m-label { font-size: 0.75rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }

.m-icon-box { width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center; }
.m-icon-box.green { background: #ecfdf5; }
.m-icon-box.blue { background: #eff6ff; }
.m-icon-box.purple { background: #f5f3ff; }
.m-icon-box.red { background: #fef2f2; }

.m-value { font-size: 1.45rem; font-weight: 800; color: #0f172a; }
.text-green { color: #059669; }
.text-purple { color: #7c3aed; }
.text-red { color: #dc2626; }
.m-sub { font-size: 0.75rem; color: #64748b; margin-top: 4px; }
.badge-sim-tag { color: #2563eb; font-weight: 700; margin-left: 4px; }

/* Navigation Tabs */
.nav-tabs { display: flex; gap: 8px; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; overflow-x: auto; }
.tab-btn { background: transparent; border: none; border-bottom: 2px solid transparent; color: #64748b; padding: 10px 16px; font-size: 0.875rem; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; transition: all 0.2s; white-space: nowrap; }
.tab-btn:hover { color: #0f172a; }
.tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; }
.tab-dot-alert { width: 6px; height: 6px; border-radius: 50%; background: #2563eb; }

/* Chart Card */
.chart-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.chart-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }
.chart-title { font-size: 1.05rem; font-weight: 700; color: #0f172a; margin: 0; }
.chart-subtitle { font-size: 0.8rem; color: #64748b; margin: 2px 0 0 0; }

.legend-group { display: flex; gap: 14px; align-items: center; font-size: 0.8rem; color: #475569; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 6px; font-weight: 500; }
.legend-box { width: 14px; height: 4px; border-radius: 2px; }
.legend-box.blue { background: #2563eb; }
.legend-box.green { background: #059669; }
.legend-box.dashed { border-top: 2px dashed #059669; height: 0; }
.legend-box.green-area { background: rgba(16, 185, 129, 0.25); height: 10px; }
.legend-box.red-dot { width: 8px; height: 8px; border-radius: 50%; background: #dc2626; }

.svg-chart-container { position: relative; width: 100%; overflow-x: auto; }
.main-svg-chart { width: 100%; height: auto; display: block; }
.hover-circle { cursor: pointer; transition: r 0.15s ease; }
.hover-circle:hover { r: 6.5; }

.chart-tooltip {
  position: absolute;
  transform: translate(-50%, -115%);
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 10px 14px;
  pointer-events: none;
  font-size: 0.8rem;
  color: #ffffff;
  box-shadow: 0 8px 20px rgba(0,0,0,0.25);
  z-index: 10;
  min-width: 180px;
}
.tooltip-date { font-weight: 700; color: #fff; margin-bottom: 4px; }
.tooltip-val.blue { color: #93c5fd; }
.tooltip-val.green { color: #6ee7b7; margin-top: 2px; }
.tooltip-bounds { font-size: 0.725rem; color: #cbd5e1; margin-top: 2px; }
.tooltip-badge-anom { color: #fca5a5; font-weight: 700; margin-top: 6px; font-size: 0.75rem; }

/* AI Executive Card */
.ai-card {
  background: linear-gradient(135deg, #faf5ff, #ffffff);
  border: 1px solid #e9d5ff;
  border-radius: 12px;
  padding: 22px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}
.ai-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.ai-title-wrap { display: flex; align-items: center; gap: 12px; }
.ai-sparkle { font-size: 1.5rem; }
.ai-title { font-size: 1.1rem; font-weight: 700; color: #4c1d95; margin: 0; }
.ai-subtitle { font-size: 0.8rem; color: #7e22ce; margin: 2px 0 0 0; }
.ai-badge { background: #f3e8ff; border: 1px solid #d8b4fe; color: #7e22ce; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; }
.formatted-ai-text { font-size: 0.9rem; line-height: 1.7; color: #334155; }

/* Simulation Card */
.sim-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 22px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.sim-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
.sim-title { font-size: 1.15rem; font-weight: 700; color: #0f172a; margin: 0; }
.sim-desc { font-size: 0.85rem; color: #64748b; margin: 4px 0 0 0; }
.sim-controls-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
.sim-control-box { background: #f8fafc; border: 1px solid #cbd5e1; padding: 16px; border-radius: 8px; }
.sim-ctrl-label { display: flex; justify-content: space-between; font-size: 0.825rem; font-weight: 600; color: #334155; margin-bottom: 10px; }
.sim-badge-val { background: #eff6ff; color: #1d4ed8; padding: 2px 8px; border-radius: 4px; font-weight: 700; }
.sim-badge-val.positive { background: #ecfdf5; color: #047857; }
.sim-badge-val.negative { background: #fef2f2; color: #b91c1c; }
.sim-hint { font-size: 0.75rem; color: #64748b; margin-top: 8px; }

/* Chat Card */
.chat-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 22px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.chat-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.chat-title-wrap { display: flex; align-items: center; gap: 10px; }
.chat-title { font-size: 1.1rem; font-weight: 700; color: #0f172a; margin: 0; }
.chat-subtitle { font-size: 0.8rem; color: #64748b; margin: 2px 0 0 0; }

.quick-prompts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
.quick-label { font-size: 0.75rem; font-weight: 700; color: #64748b; text-transform: uppercase; }
.quick-btn { background: #f8fafc; border: 1px solid #cbd5e1; color: #334155; padding: 6px 12px; border-radius: 6px; font-size: 0.775rem; cursor: pointer; text-align: left; transition: all 0.2s; }
.quick-btn:hover:not(:disabled) { border-color: #2563eb; color: #1d4ed8; background: #eff6ff; }

.chat-messages-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  min-height: 280px;
  max-height: 440px;
  overflow-y: auto;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat-empty { display: flex; align-items: center; justify-content: center; height: 200px; color: #94a3b8; font-size: 0.875rem; }

.chat-bubble-wrap { display: flex; gap: 10px; max-width: 85%; }
.chat-bubble-wrap.user { align-self: flex-end; flex-direction: row-reverse; }
.chat-avatar { width: 32px; height: 32px; border-radius: 50%; background: #ffffff; display: flex; align-items: center; justify-content: center; font-size: 1rem; border: 1px solid #cbd5e1; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
.chat-bubble { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; font-size: 0.85rem; line-height: 1.6; color: #1e293b; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.chat-bubble-wrap.user .chat-bubble { background: #2563eb; border-color: #1d4ed8; color: #ffffff; }
.chat-sender { font-size: 0.7rem; font-weight: 700; color: #64748b; margin-bottom: 4px; }
.chat-bubble-wrap.user .chat-sender { color: #dbeafe; }
.chat-bubble.thinking { color: #64748b; font-style: italic; }

.chat-input-bar { display: flex; gap: 10px; }
.chat-input { flex: 1; background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; padding: 10px 14px; border-radius: 8px; font-size: 0.875rem; }
.chat-input:focus { outline: none; border-color: #2563eb; }

/* Table Card */
.table-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.table-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }
.search-box { display: flex; align-items: center; gap: 8px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; width: 280px; }
.search-input { background: transparent; border: none; color: #0f172a; font-size: 0.825rem; width: 100%; }
.search-input:focus { outline: none; }
.table-responsive { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: left; }
.data-table th { background: #f8fafc; color: #64748b; padding: 10px 14px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #e2e8f0; }
.data-table td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
.data-table tr:hover td { background: #f8fafc; }
.data-table tr.row-forecast td { background: rgba(16, 185, 129, 0.03); }
.data-table tr.row-anomaly td { background: rgba(239, 68, 68, 0.05); }

.tag-status { padding: 3px 8px; border-radius: 4px; font-size: 0.725rem; font-weight: 700; }
.tag-actual { background: #eff6ff; color: #1d4ed8; }
.tag-forecast { background: #ecfdf5; color: #047857; }
.tag-anomaly { background: #fef2f2; color: #b91c1c; }

.pagination-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 0.8rem; color: #64748b; }
.page-btns { display: flex; align-items: center; gap: 8px; }
.btn-page { background: #ffffff; border: 1px solid #cbd5e1; color: #334155; padding: 5px 10px; border-radius: 4px; font-size: 0.775rem; cursor: pointer; }
.btn-page:hover:not(:disabled) { background: #f8fafc; }
.btn-page:disabled { opacity: 0.4; cursor: not-allowed; }

/* Integration Card */
.integration-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 22px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.int-title { font-size: 1.1rem; font-weight: 700; color: #0f172a; margin: 0 0 4px 0; }
.int-desc { font-size: 0.85rem; color: #64748b; margin: 0 0 18px 0; }
.lang-pills { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.lang-btn { background: #f8fafc; border: 1px solid #cbd5e1; color: #475569; padding: 6px 14px; border-radius: 6px; font-size: 0.825rem; font-weight: 600; cursor: pointer; }
.lang-btn.active { background: #eff6ff; border-color: #3b82f6; color: #1d4ed8; }
.code-wrapper { background: #0f172a; border: 1px solid #334155; border-radius: 8px; overflow: hidden; }
.code-top { display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; background: #1e293b; border-bottom: 1px solid #334155; }
.code-lang { font-size: 0.75rem; font-weight: 700; color: #94a3b8; }
.copy-btn { background: transparent; border: 1px solid #475569; color: #cbd5e1; padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.copy-btn:hover { background: #334155; color: #fff; }
.code-block { padding: 16px; color: #e2e8f0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.85rem; line-height: 1.5; overflow-x: auto; margin: 0; }

/* Leaderboard Modal */
.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 999; padding: 20px; }
.modal-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; width: 100%; max-width: 680px; box-shadow: 0 20px 40px rgba(0,0,0,0.15); overflow: hidden; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
.modal-title { font-size: 1.1rem; font-weight: 700; color: #0f172a; margin: 0; }
.modal-close { background: transparent; border: none; color: #64748b; font-size: 1.2rem; cursor: pointer; }
.modal-body { padding: 20px; }
.modal-desc { font-size: 0.85rem; color: #64748b; margin-bottom: 16px; line-height: 1.5; }
.leaderboard-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: left; }
.leaderboard-table th { background: #f8fafc; color: #64748b; padding: 8px 12px; font-size: 0.75rem; text-transform: uppercase; border-bottom: 1px solid #e2e8f0; }
.leaderboard-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
.leaderboard-table tr.row-winner { background: #f0fdf4; }
.model-name { font-size: 0.875rem; color: #0f172a; display: flex; align-items: center; gap: 6px; }
.model-desc { font-size: 0.725rem; color: #64748b; margin-top: 2px; }
</style>

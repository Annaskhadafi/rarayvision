<script setup>
import { computed, ref } from 'vue'
import { forecastingService } from '../services/forecastingService'

const dbUrl = ref('')
const showDbUrl = ref(false)
const tables = ref([])
const tableName = ref('')
const timeColumn = ref('')
const valueColumn = ref('')
const horizon = ref(12)
const contextLength = ref(128)
const result = ref(null)
const errorMessage = ref('')
const isLoadingSchema = ref(false)
const isForecasting = ref(false)

const selectedTable = computed(() => tables.value.find(item => item.table_name === tableName.value))
const isReady = computed(() => Boolean(tableName.value && timeColumn.value && valueColumn.value))
const numericColumns = computed(() => (selectedTable.value?.columns || []).filter(item => [
  'smallint', 'integer', 'bigint', 'numeric', 'decimal', 'real', 'double precision'
].includes(item.type)))

const sliderProgress = (value, min, max) => `${((value - min) / (max - min)) * 100}%`

const chart = computed(() => {
  const history = result.value?.history || []
  const predictions = result.value?.predictions || []
  const allValues = [...history.map(item => item.value), ...predictions.map(item => item.forecast)]
  if (!allValues.length) return { history: '', forecast: '', split: 0, min: 0, max: 0 }

  const width = 1000
  const height = 280
  const padding = 20
  const min = Math.min(...allValues)
  const max = Math.max(...allValues)
  const spread = max - min || 1
  const point = (value, index) => {
    const x = padding + (index / Math.max(allValues.length - 1, 1)) * (width - padding * 2)
    const y = height - padding - ((value - min) / spread) * (height - padding * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }

  return {
    history: history.map((item, index) => point(item.value, index)).join(' '),
    forecast: predictions.map((item, index) => point(item.forecast, history.length + index)).join(' '),
    split: padding + ((Math.max(history.length - 1, 0)) / Math.max(allValues.length - 1, 1)) * (width - padding * 2),
    min,
    max
  }
})

const readSchema = async () => {
  if (!dbUrl.value.trim()) return (errorMessage.value = 'Isi PostgreSQL connection URL terlebih dahulu.')
  isLoadingSchema.value = true
  errorMessage.value = ''
  result.value = null
  try {
    const data = await forecastingService.inspectSchema(dbUrl.value)
    tables.value = data.tables || []
    tableName.value = tables.value[0]?.table_name || ''
    syncColumns()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isLoadingSchema.value = false
  }
}

const syncColumns = () => {
  const columns = selectedTable.value?.columns || []
  timeColumn.value = columns.find(item => ['timestamp without time zone', 'timestamp with time zone', 'date'].includes(item.type))?.name || columns[0]?.name || ''
  valueColumn.value = numericColumns.value[0]?.name || ''
}

const runForecast = async () => {
  if (!tableName.value || !timeColumn.value || !valueColumn.value) return (errorMessage.value = 'Pilih tabel, kolom waktu, dan kolom nilai.')
  isForecasting.value = true
  errorMessage.value = ''
  try {
    const response = await forecastingService.forecast({
      db_url: dbUrl.value,
      table_name: tableName.value,
      time_column: timeColumn.value,
      value_column: valueColumn.value,
      horizon: horizon.value,
      context_length: contextLength.value
    })
    result.value = response.data
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isForecasting.value = false
  }
}
</script>

<template>
  <div class="forecasting-page">
    <section class="hero-card">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="live-dot"></span> AI LAB <span>·</span> TIME SERIES</div>
        <h1>See what comes next.</h1>
        <p>Eksplorasi data PostgreSQL dengan TimesFM 2.5. Atur horizon, context, lalu lihat pola historis dan prediksi dalam satu ruang kerja.</p>
      </div>
      <div class="hero-side">
        <span class="model-chip"><span class="chip-icon">✦</span> TimesFM 2.5 · 200M</span>
        <a href="https://github.com/google-research/timesfm" target="_blank" rel="noopener">Dokumentasi model ↗</a>
      </div>
    </section>

    <div class="workspace-grid">
      <section class="panel setup-panel">
        <div class="section-heading"><div><span class="step">01</span><div><p class="section-kicker">DATA SOURCE</p><h2>Connect your database</h2></div></div><span class="badge"><span class="badge-dot"></span> READ ONLY</span></div>
        <label>PostgreSQL connection URL</label>
        <div class="url-row">
          <div class="input-wrap"><input v-model="dbUrl" :type="showDbUrl ? 'text' : 'password'" placeholder="postgresql://user:password@host:5432/database" autocomplete="off" /><button class="input-action" type="button" :aria-label="showDbUrl ? 'Sembunyikan URL' : 'Tampilkan URL'" @click="showDbUrl = !showDbUrl">{{ showDbUrl ? 'Hide' : 'Show' }}</button></div>
          <button class="primary" :disabled="isLoadingSchema" @click="readSchema"><span v-if="isLoadingSchema" class="spinner"></span>{{ isLoadingSchema ? 'Reading...' : 'Read tables' }}</button>
        </div>
        <small><span class="lock-icon">⌁</span> Kredensial hanya digunakan untuk membaca schema dan data. Tidak ada operasi tulis.</small>
      </section>

      <aside class="model-status">
        <div class="status-orbit"><span>✦</span></div>
        <p class="section-kicker">MODEL STATUS</p>
        <h2>{{ isForecasting ? 'Forecasting...' : isReady ? 'Ready to forecast' : 'Waiting for data' }}</h2>
        <p>{{ isForecasting ? 'TimesFM sedang membaca pola data Anda.' : isReady ? 'Konfigurasi lengkap. Model siap dijalankan.' : 'Hubungkan database untuk memulai.' }}</p>
        <div class="status-line"><span :class="['status-dot', { ready: isReady }]" />{{ isReady ? 'Configuration complete' : 'Configuration incomplete' }}</div>
      </aside>
    </div>

    <section class="panel config-panel">
      <div class="section-heading"><div><span class="step">02</span><div><p class="section-kicker">FORECAST CONFIGURATION</p><h2>Shape your prediction</h2></div></div><span class="config-count">{{ tables.length ? `${tables.length} tables found` : 'No source loaded' }}</span></div>
      <div class="form-grid">
        <label>Tabel<select v-model="tableName" @change="syncColumns"><option value="">Pilih tabel</option><option v-for="table in tables" :key="table.table_name" :value="table.table_name">{{ table.table_name }} · {{ table.estimated_rows }} rows</option></select></label>
        <label>Kolom waktu<select v-model="timeColumn"><option value="">Pilih kolom waktu</option><option v-for="column in (selectedTable?.columns || [])" :key="column.name" :value="column.name">{{ column.name }} · {{ column.type }}</option></select></label>
        <label>Kolom nilai<select v-model="valueColumn"><option value="">Pilih kolom numerik</option><option v-for="column in numericColumns" :key="column.name" :value="column.name">{{ column.name }} · {{ column.type }}</option></select></label>
      </div>

      <div class="slider-grid">
        <div class="slider-card">
          <div class="slider-label"><span><strong>Forecast horizon</strong><small>Berapa langkah ke depan?</small></span><output>{{ horizon }} <em>steps</em></output></div>
          <input v-model.number="horizon" class="range-input" type="range" min="1" max="96" step="1" :style="{ '--range-progress': sliderProgress(horizon, 1, 96) }" />
          <div class="range-scale"><span>1</span><span>Short</span><span>96 · Long</span></div>
        </div>
        <div class="slider-card">
          <div class="slider-label"><span><strong>Context window</strong><small>Data historis untuk dibaca model</small></span><output>{{ contextLength }} <em>points</em></output></div>
          <input v-model.number="contextLength" class="range-input" type="range" min="64" max="1024" step="64" :style="{ '--range-progress': sliderProgress(contextLength, 64, 1024) }" />
          <div class="range-scale"><span>64</span><span>Balanced</span><span>1024 · Deep</span></div>
        </div>
      </div>

      <button class="forecast-button" :disabled="isForecasting || !isReady" @click="runForecast"><span class="button-spark">✦</span>{{ isForecasting ? 'Running TimesFM...' : 'Run forecast' }}<span class="button-arrow">→</span></button>
    </section>

    <p v-if="errorMessage" class="error"><span>!</span>{{ errorMessage }}</p>

    <section v-if="result" class="result-area">
      <div class="result-heading"><div><p class="section-kicker">FORECAST OUTPUT</p><h2>Prediction overview</h2></div><span class="result-model"><span class="live-dot"></span>{{ result.model }}</span></div>
      <div class="stats-grid">
        <div class="stat-card"><span>HISTORICAL POINTS</span><strong>{{ result.rows_used }}</strong><small>used as context</small></div>
        <div class="stat-card"><span>FORECAST HORIZON</span><strong>{{ result.horizon }}</strong><small>steps ahead</small></div>
        <div class="stat-card"><span>LAST OBSERVATION</span><strong class="date-value">{{ result.last_timestamp }}</strong><small>{{ result.table }} · {{ result.value_column }}</small></div>
      </div>
      <div class="panel chart-panel">
        <div class="chart-heading"><div><h3>Signal & prediction</h3><p>Historis <span class="legend-history"></span><span class="legend-label">Forecast</span><span class="legend-forecast"></span></p></div><div class="chart-range"><span>{{ chart.min.toFixed(2) }}</span><span>{{ chart.max.toFixed(2) }}</span></div></div>
        <div class="chart-wrap"><svg viewBox="0 0 1000 280" role="img" aria-label="Grafik data historis dan forecast" preserveAspectRatio="none"><line x1="0" y1="70" x2="1000" y2="70" class="grid-line" /><line x1="0" y1="140" x2="1000" y2="140" class="grid-line" /><line x1="0" y1="210" x2="1000" y2="210" class="grid-line" /><line :x1="chart.split" y1="0" :x2="chart.split" y2="280" class="split-line" /><polyline :points="chart.history" class="history-line" /><polyline :points="chart.forecast" class="forecast-line" /></svg><span class="split-label" :style="{ left: `${chart.split / 10}%` }">NOW</span></div>
      </div>
      <div class="panel result-panel">
        <div class="table-heading"><div><h3>Forecast values</h3><p>Point forecast dan rentang confidence model.</p></div><span class="table-unit">{{ result.value_column }}</span></div>
        <div class="table-wrap"><table><thead><tr><th>Step</th><th>Forecast</th><th>P10 <small>lower</small></th><th>P50 <small>median</small></th><th>P90 <small>upper</small></th></tr></thead><tbody><tr v-for="row in result.predictions" :key="row.step"><td><span class="step-number">{{ String(row.step).padStart(2, '0') }}</span></td><td class="forecast-number">{{ row.forecast.toFixed(4) }}</td><td>{{ row.p10?.toFixed(4) ?? '-' }}</td><td class="median-number">{{ row.p50?.toFixed(4) ?? '-' }}</td><td>{{ row.p90?.toFixed(4) ?? '-' }}</td></tr></tbody></table></div>
      </div>
    </section>

    <section v-else class="empty-state"><div class="empty-icon">⌁</div><div><h2>Your forecast will appear here</h2><p>Connect a PostgreSQL source, choose your signal, and run the model to see the story in your data.</p></div></section>
  </div>
</template>

<style scoped>
:global(body) { -webkit-font-smoothing: antialiased; }
.forecasting-page { max-width: 1240px; margin: 0 auto; color: #172033; }
.hero-card { display: flex; justify-content: space-between; gap: 28px; min-height: 214px; box-sizing: border-box; margin-bottom: 18px; padding: 34px 38px; color: #f8fafc; border-radius: 26px; background: radial-gradient(circle at 84% 18%, rgba(45, 212, 191, .28), transparent 29%), radial-gradient(circle at 16% 100%, rgba(59, 130, 246, .22), transparent 34%), linear-gradient(130deg, #0f172a 0%, #102b3a 48%, #0f766e 150%); box-shadow: 0 18px 46px rgba(15, 23, 42, .18); overflow: hidden; }
.hero-copy { max-width: 680px; align-self: center; }.hero-kicker, .section-kicker { display: flex; align-items: center; gap: 8px; color: #5eead4; font-size: 10px; font-weight: 900; letter-spacing: .16em; }.hero-card h1 { margin: 12px 0 10px; font-size: clamp(34px, 5vw, 58px); line-height: .98; letter-spacing: -.06em; text-wrap: balance; }.hero-card p { max-width: 590px; margin: 0; color: #b8d8d7; font-size: 14px; line-height: 1.7; text-wrap: pretty; }.hero-side { display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between; min-width: 176px; }.hero-side a { color: #ccfbf1; font-size: 12px; font-weight: 750; text-decoration: none; }.model-chip { display: inline-flex; align-items: center; gap: 8px; padding: 9px 12px; border: 1px solid rgba(204, 251, 241, .22); border-radius: 999px; background: rgba(15, 23, 42, .24); color: #e6fffb; font-size: 11px; font-weight: 800; }.chip-icon { color: #5eead4; font-size: 16px; }.live-dot, .badge-dot { width: 7px; height: 7px; display: inline-block; border-radius: 50%; background: #5eead4; box-shadow: 0 0 0 4px rgba(94, 234, 212, .12); }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 272px; gap: 18px; }.panel, .model-status { border-radius: 20px; }.panel { background: rgba(255, 255, 255, .96); border: 1px solid #e6edf2; padding: 24px; margin-bottom: 18px; box-shadow: 0 14px 36px rgba(15, 23, 42, .045); }.section-heading, .slider-label, .chart-heading, .table-heading, .result-heading { display: flex; justify-content: space-between; align-items: center; gap: 14px; }.section-heading { margin-bottom: 22px; }.section-heading > div { display: flex; align-items: center; gap: 13px; }.section-heading .section-kicker { margin: 0 0 4px; color: #0f766e; }.section-heading h2, .result-heading h2 { margin: 0; font-size: 19px; letter-spacing: -.025em; }.step { display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 12px; background: #ccfbf1; color: #0f766e; font-size: 12px; font-weight: 950; }.badge { display: inline-flex; align-items: center; gap: 7px; padding: 7px 10px; border-radius: 999px; background: #ecfdf5; color: #047857; font-size: 10px; font-weight: 900; letter-spacing: .06em; }.config-count, .table-unit { color: #94a3b8; font-size: 11px; font-weight: 800; }
label { display: flex; flex-direction: column; gap: 8px; color: #475569; font-size: 12px; font-weight: 800; letter-spacing: .01em; } input, select { width: 100%; box-sizing: border-box; border: 1px solid #d7e1e8; border-radius: 11px; padding: 12px 13px; color: #172033; background: #fff; font: inherit; transition-property: border-color, box-shadow; transition-duration: .2s; } input:focus, select:focus { outline: none; border-color: #14b8a6; box-shadow: 0 0 0 4px rgba(20, 184, 166, .12); }.form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 13px; }
.url-row { display: flex; gap: 10px; margin: 8px 0 9px; }.input-wrap { position: relative; flex: 1; }.input-wrap input { padding-right: 58px; }.input-action { position: absolute; top: 50%; right: 5px; min-width: 48px; min-height: 34px; transform: translateY(-50%); border: 0; border-radius: 8px; background: #f1f5f9; color: #0f766e; font-size: 10px; font-weight: 900; cursor: pointer; }.primary { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 46px; padding: 0 18px; border: 0; border-radius: 11px; background: #0f766e; color: white; font-weight: 850; cursor: pointer; transition-property: transform, box-shadow, background; transition-duration: .2s; }.primary:hover:not(:disabled), .forecast-button:hover:not(:disabled) { background: #115e59; box-shadow: 0 8px 18px rgba(15, 118, 110, .2); }.primary:active:not(:disabled), .forecast-button:active:not(:disabled), .input-action:active { transform: scale(.96); }.primary:disabled, .forecast-button:disabled { opacity: .55; cursor: wait; }.setup-panel small { display: flex; align-items: center; gap: 7px; color: #94a3b8; font-size: 11px; }.lock-icon { color: #0f766e; font-size: 15px; }
.model-status { position: relative; display: flex; flex-direction: column; justify-content: flex-end; min-height: 210px; box-sizing: border-box; padding: 23px; background: #ecfdf5; border: 1px solid #b9eee0; overflow: hidden; }.model-status::before, .model-status::after { position: absolute; content: ''; border: 1px solid rgba(13, 148, 136, .12); border-radius: 50%; pointer-events: none; }.model-status::before { width: 220px; height: 220px; top: -110px; right: -76px; }.model-status::after { width: 150px; height: 150px; top: -74px; right: -42px; }.status-orbit { position: absolute; top: 25px; right: 28px; display: grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; background: #0f766e; color: #ccfbf1; font-size: 21px; box-shadow: 0 0 0 8px rgba(15, 118, 110, .1); }.model-status .section-kicker { margin: 0 0 8px; color: #0f766e; }.model-status h2 { margin: 0 0 8px; font-size: 20px; letter-spacing: -.03em; }.model-status p:not(.section-kicker) { max-width: 180px; margin: 0 0 17px; color: #51817a; font-size: 12px; line-height: 1.5; }.status-line { display: flex; align-items: center; gap: 8px; color: #51817a; font-size: 11px; font-weight: 800; }.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #f59e0b; }.status-dot.ready { background: #10b981; box-shadow: 0 0 0 4px rgba(16, 185, 129, .12); }
.config-panel { padding-bottom: 26px; }.slider-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 13px; margin-top: 18px; }.slider-card { padding: 17px; border: 1px solid #e6edf2; border-radius: 15px; background: #f8fafc; }.slider-label { align-items: flex-start; }.slider-label strong { display: block; color: #334155; font-size: 13px; }.slider-label small { display: block; margin-top: 4px; color: #94a3b8; font-size: 11px; font-weight: 500; }.slider-label output { color: #0f766e; font-size: 21px; font-weight: 900; font-variant-numeric: tabular-nums; }.slider-label output em { color: #64748b; font-size: 10px; font-style: normal; font-weight: 700; }.range-input { appearance: none; height: 5px; margin: 20px 0 10px; padding: 0; border: 0; border-radius: 99px; outline: 0; background: linear-gradient(90deg, #0f766e var(--range-progress), #dbe7e9 var(--range-progress)); cursor: pointer; }.range-input::-webkit-slider-thumb { appearance: none; width: 20px; height: 20px; border: 4px solid #fff; border-radius: 50%; background: #0f766e; box-shadow: 0 2px 8px rgba(15, 118, 110, .3); }.range-input::-moz-range-thumb { width: 13px; height: 13px; border: 4px solid #fff; border-radius: 50%; background: #0f766e; box-shadow: 0 2px 8px rgba(15, 118, 110, .3); }.range-scale { display: flex; justify-content: space-between; color: #94a3b8; font-size: 10px; font-variant-numeric: tabular-nums; }.range-scale span:nth-child(2) { color: #64748b; font-weight: 750; }.forecast-button { display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%; min-height: 52px; margin-top: 18px; border: 0; border-radius: 13px; background: #0f766e; color: #fff; font-size: 14px; font-weight: 900; cursor: pointer; transition-property: transform, box-shadow, background; transition-duration: .2s; }.button-spark { color: #99f6e4; font-size: 18px; }.button-arrow { margin-left: auto; margin-right: 17px; font-size: 19px; color: #99f6e4; }.spinner { width: 13px; height: 13px; border: 2px solid rgba(255,255,255,.35); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; }.error { display: flex; align-items: center; gap: 9px; color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; border-radius: 11px; padding: 13px 15px; }.error span { display: grid; place-items: center; width: 19px; height: 19px; border-radius: 50%; background: #fee2e2; font-size: 12px; font-weight: 900; }
.result-area { margin-top: 28px; }.result-heading { margin: 0 0 14px; }.result-heading .section-kicker { margin: 0 0 5px; color: #0f766e; }.result-heading h2 { font-size: 23px; }.result-model { display: inline-flex; align-items: center; gap: 9px; padding: 8px 11px; border: 1px solid #d7eee9; border-radius: 999px; color: #0f766e; background: #f0fdfa; font-size: 11px; font-weight: 850; }.stats-grid { display: grid; grid-template-columns: .8fr .8fr 1.4fr; gap: 13px; margin-bottom: 13px; }.stat-card { min-height: 100px; box-sizing: border-box; padding: 17px 19px; border-radius: 16px; background: #172033; color: #fff; box-shadow: 0 10px 24px rgba(15, 23, 42, .1); }.stat-card:nth-child(2) { background: #0f766e; }.stat-card:nth-child(3) { background: #eef7f6; color: #172033; }.stat-card span { display: block; color: #a8bacb; font-size: 9px; font-weight: 900; letter-spacing: .12em; }.stat-card:nth-child(2) span { color: #99f6e4; }.stat-card:nth-child(3) span { color: #0f766e; }.stat-card strong { display: block; margin: 9px 0 3px; font-size: 28px; line-height: 1; font-variant-numeric: tabular-nums; }.stat-card small { color: #94a3b8; font-size: 10px; }.stat-card:nth-child(2) small { color: #a7f3d0; }.date-value { font-size: 15px !important; padding-top: 7px; }.chart-panel { padding-bottom: 17px; }.chart-heading { margin-bottom: 16px; }.chart-heading h3, .table-heading h3 { margin: 0 0 5px; font-size: 15px; }.chart-heading p, .table-heading p { margin: 0; color: #94a3b8; font-size: 11px; }.legend-history, .legend-forecast { display: inline-block; width: 18px; height: 3px; margin: 0 5px 2px 13px; border-radius: 99px; background: #94a3b8; }.legend-forecast { margin-left: 14px; background: #0f766e; }.legend-label { color: #64748b; }.chart-range { display: flex; flex-direction: column; align-items: flex-end; gap: 34px; color: #94a3b8; font-size: 10px; font-variant-numeric: tabular-nums; }.chart-wrap { position: relative; height: 280px; padding: 0 2px; }.chart-wrap svg { display: block; width: 100%; height: 100%; overflow: visible; }.grid-line { stroke: #e9eff2; stroke-dasharray: 4 6; }.split-line { stroke: #0f766e; stroke-width: 1.5; stroke-dasharray: 5 5; opacity: .55; }.history-line, .forecast-line { fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-width: 3; }.history-line { stroke: #94a3b8; }.forecast-line { stroke: #0f766e; }.split-label { position: absolute; top: 7px; transform: translateX(-50%); padding: 3px 6px; border-radius: 4px; background: #ccfbf1; color: #0f766e; font-size: 9px; font-weight: 900; letter-spacing: .08em; }.table-heading { margin-bottom: 5px; }.table-unit { padding: 6px 9px; border-radius: 6px; background: #f1f5f9; font-variant-numeric: tabular-nums; }.table-wrap { overflow-x: auto; margin-top: 18px; } table { width: 100%; border-collapse: collapse; font-size: 13px; } th, td { padding: 12px 14px; border-bottom: 1px solid #edf1f3; text-align: right; font-variant-numeric: tabular-nums; } th:first-child, td:first-child { text-align: left; } th { color: #94a3b8; font-size: 10px; text-transform: uppercase; letter-spacing: .1em; } th small { display: block; margin-top: 3px; color: #cbd5e1; font-size: 8px; text-transform: none; letter-spacing: 0; }.step-number { color: #94a3b8; font-size: 11px; font-weight: 800; }.forecast-number { color: #0f766e; font-weight: 900; }.median-number { color: #334155; font-weight: 800; }
.empty-state { display: flex; align-items: center; gap: 18px; min-height: 126px; padding: 24px 28px; border: 1px dashed #c9d9dc; border-radius: 20px; background: rgba(240, 253, 250, .6); }.empty-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 15px; background: #ccfbf1; color: #0f766e; font-size: 25px; }.empty-state h2 { margin: 0 0 5px; font-size: 16px; }.empty-state p { margin: 0; color: #6b8690; font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; }.model-status { min-height: 180px; }.hero-side { min-width: 150px; }.stats-grid { grid-template-columns: repeat(2, 1fr); }.stats-grid .stat-card:last-child { grid-column: 1 / -1; } }
@media (max-width: 650px) { .hero-card { flex-direction: column; padding: 26px 22px; }.hero-side { align-items: flex-start; gap: 22px; }.panel { padding: 18px; }.url-row, .section-heading, .chart-heading { align-items: stretch; flex-direction: column; }.url-row .primary { width: 100%; }.form-grid, .slider-grid, .stats-grid { grid-template-columns: 1fr; }.stats-grid .stat-card:last-child { grid-column: auto; }.chart-wrap { height: 210px; }.chart-range { display: none; }.empty-state { align-items: flex-start; flex-direction: column; } }
</style>

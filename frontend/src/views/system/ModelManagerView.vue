<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { modelManagerService } from '../../services/modelManagerService'

// ─── State ───────────────────────────────────────────────────────────
const models = ref([])
const summary = ref({})
const systemRam = ref(null)
const filterCategory = ref('All')
const isLoading = ref(false)
const actionInProgress = ref({}) // { [model_id]: 'loading' | 'unloading' | null }
const lastRefreshedAt = ref(null)
let ramPollInterval = null

// ─── Categories ──────────────────────────────────────────────────────
const allCategories = computed(() => {
  const cats = new Set(models.value.map(m => m.category))
  return ['All', ...Array.from(cats)]
})

const filteredModels = computed(() => {
  if (filterCategory.value === 'All') return models.value
  return models.value.filter(m => m.category === filterCategory.value)
})

const loadedModels = computed(() => models.value.filter(m => m.loaded))
const totalRamLoaded = computed(() => loadedModels.value.reduce((s, m) => s + m.ram_estimate_mb, 0))
const totalRamAll = computed(() => models.value.reduce((s, m) => s + m.ram_estimate_mb, 0))

// ─── System RAM computed ─────────────────────────────────────────────
const ramPercent = computed(() => systemRam.value?.system?.percent ?? 0)
const ramBarColor = computed(() => {
  if (ramPercent.value > 85) return '#ef4444'
  if (ramPercent.value > 65) return '#f59e0b'
  return '#22c55e'
})

// ─── Fetch all model statuses ─────────────────────────────────────────
const fetchModels = async () => {
  isLoading.value = true
  const res = await modelManagerService.getModels()
  if (res?.success) {
    models.value = res.models || []
    summary.value = res.summary || {}
    lastRefreshedAt.value = new Date().toLocaleTimeString()
  }
  isLoading.value = false
}

const fetchRam = async () => {
  const res = await modelManagerService.getSystemRam()
  if (res?.success) {
    systemRam.value = res
  }
}

// ─── Per-model actions ────────────────────────────────────────────────
const loadModel = async (model) => {
  actionInProgress.value[model.id] = 'loading'
  const res = await modelManagerService.loadModel(model.id)
  if (res?.success) {
    model.loaded = true
    model.load_time_ms = res.load_time_ms
    model.error = null
  } else {
    model.error = res?.error || 'Load failed'
  }
  delete actionInProgress.value[model.id]
  fetchModels()
  fetchRam()
}

const unloadModel = async (model) => {
  actionInProgress.value[model.id] = 'unloading'
  const res = await modelManagerService.unloadModel(model.id)
  if (res?.success) {
    model.loaded = false
    model.error = null
  } else {
    model.error = res?.error || 'Unload failed'
  }
  delete actionInProgress.value[model.id]
  fetchModels()
  fetchRam()
}

// ─── Batch actions ────────────────────────────────────────────────────
const isBatchLoading = ref(false)
const isBatchUnloading = ref(false)

const loadAll = async () => {
  isBatchLoading.value = true
  await modelManagerService.loadAll()
  await fetchModels()
  await fetchRam()
  isBatchLoading.value = false
}

const unloadAll = async () => {
  if (!confirm('Bongkar semua model dari RAM? Semua fitur AI akan butuh inisialisasi ulang saat dipakai.')) return
  isBatchUnloading.value = true
  await modelManagerService.unloadAll()
  await fetchModels()
  await fetchRam()
  isBatchUnloading.value = false
}

// ─── Helpers ──────────────────────────────────────────────────────────
const formatRam = (mb) => {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return mb + ' MB'
}

const categoryColor = (cat) => {
  const map = {
    'Face Recognition': '#818cf8',
    'Anti-Spoofing': '#fb923c',
    'Computer Vision': '#34d399',
    'NLP / RAG': '#60a5fa',
  }
  return map[cat] || '#94a3b8'
}

const categoryBg = (cat) => {
  const map = {
    'Face Recognition': 'rgba(129,140,248,0.12)',
    'Anti-Spoofing': 'rgba(251,146,60,0.12)',
    'Computer Vision': 'rgba(52,211,153,0.12)',
    'NLP / RAG': 'rgba(96,165,250,0.12)',
  }
  return map[cat] || 'rgba(148,163,184,0.10)'
}

onMounted(async () => {
  await fetchModels()
  await fetchRam()
  ramPollInterval = setInterval(fetchRam, 4000) // Poll RAM every 4s
})

onUnmounted(() => {
  if (ramPollInterval) clearInterval(ramPollInterval)
})
</script>

<template>
  <div class="mm-container">
    <!-- ── Header ──────────────────────────────────────────────── -->
    <div class="mm-header">
      <div class="mm-title-group">
        <div class="mm-badge-tag">SISTEM MANAJEMEN AI</div>
        <h1>🧠 AI Model Manager</h1>
        <p class="mm-subtitle">
          Kendalikan semua model AI/ML/Computer Vision yang terdaftar di sistem Raray Vision.
          Aktifkan hanya model yang dibutuhkan untuk meminimalkan penggunaan RAM.
        </p>
      </div>

      <div class="mm-header-actions">
        <button class="mm-btn-outline" @click="fetchModels(); fetchRam()" :disabled="isLoading">
          {{ isLoading ? '⏳ Refresh...' : '🔄 Refresh Status' }}
        </button>
        <button class="mm-btn-success" @click="loadAll" :disabled="isBatchLoading">
          {{ isBatchLoading ? '⏳ Memuat...' : '▶️ Load All Models' }}
        </button>
        <button class="mm-btn-danger" @click="unloadAll" :disabled="isBatchUnloading">
          {{ isBatchUnloading ? '⏳ Membongkar...' : '🗑️ Unload All' }}
        </button>
      </div>
    </div>

    <!-- ── System RAM Monitor Bar ──────────────────────────────── -->
    <div class="mm-ram-monitor" v-if="systemRam?.system">
      <div class="ram-monitor-header">
        <div class="ram-title">
          <span class="ram-icon">💾</span>
          <span>RAM Sistem Real-time</span>
          <span class="ram-refresh-tag">↻ Auto-refresh 4s</span>
        </div>
        <div class="ram-values">
          <span class="ram-used">{{ formatRam(systemRam.system.used_mb) }}</span>
          <span class="ram-sep">/</span>
          <span class="ram-total">{{ formatRam(systemRam.system.total_mb) }}</span>
          <span :class="['ram-pct', ramPercent > 85 ? 'pct-critical' : ramPercent > 65 ? 'pct-warning' : 'pct-ok']">
            {{ ramPercent }}%
          </span>
        </div>
      </div>
      <div class="ram-bar-track">
        <div class="ram-bar-fill" :style="{ width: ramPercent + '%', background: ramBarColor }"></div>
      </div>
      <div class="ram-footer">
        <span>Process (FastAPI): <strong>{{ formatRam(systemRam.process?.rss_mb ?? 0) }}</strong></span>
        <span>Available: <strong>{{ formatRam(systemRam.system.available_mb) }}</strong></span>
        <span>Models loaded (est.): <strong>{{ formatRam(totalRamLoaded) }}</strong></span>
      </div>
    </div>

    <!-- ── Summary Cards ───────────────────────────────────────── -->
    <div class="mm-stats-row">
      <div class="mm-stat-card mm-stat-green">
        <div class="stat-icon">✅</div>
        <div class="stat-body">
          <div class="stat-val">{{ loadedModels.length }}</div>
          <div class="stat-lbl">Model Aktif (RAM)</div>
        </div>
      </div>
      <div class="mm-stat-card mm-stat-slate">
        <div class="stat-icon">⭕</div>
        <div class="stat-body">
          <div class="stat-val">{{ models.length - loadedModels.length }}</div>
          <div class="stat-lbl">Model Tidak Aktif</div>
        </div>
      </div>
      <div class="mm-stat-card mm-stat-amber">
        <div class="stat-icon">📊</div>
        <div class="stat-body">
          <div class="stat-val">{{ formatRam(totalRamLoaded) }}</div>
          <div class="stat-lbl">RAM Terpakai (Est.)</div>
        </div>
      </div>
      <div class="mm-stat-card mm-stat-blue">
        <div class="stat-icon">💡</div>
        <div class="stat-body">
          <div class="stat-val">{{ formatRam(totalRamAll - totalRamLoaded) }}</div>
          <div class="stat-lbl">RAM Bisa Dihemat</div>
        </div>
      </div>
    </div>

    <!-- ── Category Filter Pills ───────────────────────────────── -->
    <div class="mm-category-pills">
      <button
        v-for="cat in allCategories"
        :key="cat"
        :class="['mm-pill', { active: filterCategory === cat }]"
        @click="filterCategory = cat"
      >
        <span
          v-if="cat !== 'All'"
          class="pill-dot"
          :style="{ background: categoryColor(cat) }"
        ></span>
        {{ cat }}
        <span class="pill-count">
          {{ cat === 'All' ? models.length : models.filter(m => m.category === cat).length }}
        </span>
      </button>
    </div>

    <!-- ── Model Cards Grid ────────────────────────────────────── -->
    <div class="mm-grid">
      <div
        v-for="model in filteredModels"
        :key="model.id"
        :class="['mm-card', { 'mm-card-loaded': model.loaded, 'mm-card-error': model.error }]"
      >
        <!-- Card Header -->
        <div class="mc-header">
          <div class="mc-icon-wrap" :style="{ background: categoryBg(model.category) }">
            <span class="mc-icon">{{ model.icon }}</span>
          </div>
          <div class="mc-title-group">
            <div class="mc-name">{{ model.name }}</div>
            <div class="mc-category-tag" :style="{ color: categoryColor(model.category), background: categoryBg(model.category) }">
              {{ model.category }}
            </div>
          </div>
          <!-- Status Badge -->
          <div class="mc-status-badge">
            <span v-if="actionInProgress[model.id] === 'loading'" class="badge-loading">⏳ Loading...</span>
            <span v-else-if="actionInProgress[model.id] === 'unloading'" class="badge-loading">⏳ Unloading...</span>
            <span v-else-if="model.loaded" class="badge-on">🟢 AKTIF</span>
            <span v-else class="badge-off">⭕ NONAKTIF</span>
          </div>
        </div>

        <!-- Description -->
        <p class="mc-desc">{{ model.description }}</p>

        <!-- RAM Info Row -->
        <div class="mc-info-row">
          <div class="mc-info-item">
            <span class="info-label">RAM Estimasi</span>
            <span class="info-val" :class="{ 'val-active': model.loaded }">{{ formatRam(model.ram_estimate_mb) }}</span>
          </div>
          <div class="mc-info-item" v-if="model.load_time_ms">
            <span class="info-label">Load Time</span>
            <span class="info-val">{{ model.load_time_ms }} ms</span>
          </div>
          <div class="mc-info-item" v-if="model.loaded_at">
            <span class="info-label">Loaded At</span>
            <span class="info-val">{{ new Date(model.loaded_at * 1000).toLocaleTimeString() }}</span>
          </div>
        </div>

        <!-- RAM Bar (visual weight indicator) -->
        <div class="mc-ram-bar-track">
          <div
            class="mc-ram-bar-fill"
            :style="{
              width: Math.min((model.ram_estimate_mb / 1000) * 100, 100) + '%',
              background: model.loaded ? categoryColor(model.category) : '#334155'
            }"
          ></div>
        </div>

        <!-- Error msg -->
        <div v-if="model.error" class="mc-error">
          ⚠️ {{ model.error }}
        </div>

        <!-- Actions -->
        <div class="mc-actions">
          <button
            v-if="!model.loaded && !actionInProgress[model.id]"
            class="mc-btn mc-btn-load"
            @click="loadModel(model)"
          >
            ▶️ Aktifkan Model
          </button>
          <button
            v-if="model.loaded && !actionInProgress[model.id]"
            class="mc-btn mc-btn-unload"
            @click="unloadModel(model)"
          >
            ⏹️ Nonaktifkan
          </button>
          <button
            v-if="actionInProgress[model.id]"
            class="mc-btn mc-btn-busy"
            disabled
          >
            ⏳ {{ actionInProgress[model.id] === 'loading' ? 'Memuat...' : 'Membongkar...' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Last refreshed -->
    <div class="mm-footer-note">
      Terakhir diperbarui: {{ lastRefreshedAt || '—' }} &nbsp;·&nbsp;
      Total {{ models.length }} model terdaftar
    </div>
  </div>
</template>

<style scoped>
.mm-container {
  min-height: 100vh;
  background: #0a0f1e;
  padding: 28px;
  color: #f1f5f9;
  font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
}

/* ── Header ──────────────────────────────────────────────────────── */
.mm-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 28px;
  flex-wrap: wrap;
}

.mm-badge-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #818cf8;
  background: rgba(129, 140, 248, 0.1);
  border: 1px solid rgba(129, 140, 248, 0.3);
  border-radius: 6px;
  padding: 3px 10px;
  margin-bottom: 10px;
}

.mm-header h1 {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 8px;
  background: linear-gradient(135deg, #f1f5f9 0%, #818cf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.mm-subtitle {
  color: #64748b;
  font-size: 14px;
  max-width: 680px;
  line-height: 1.6;
  margin: 0;
}

.mm-header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: flex-start;
  padding-top: 4px;
}

.mm-btn-outline {
  padding: 9px 18px;
  border: 1px solid #334155;
  background: transparent;
  color: #94a3b8;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}
.mm-btn-outline:hover:not(:disabled) { border-color: #818cf8; color: #818cf8; }

.mm-btn-success {
  padding: 9px 18px;
  border: none;
  background: linear-gradient(135deg, #166534 0%, #16a34a 100%);
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}
.mm-btn-success:hover:not(:disabled) { filter: brightness(1.15); }

.mm-btn-danger {
  padding: 9px 18px;
  border: none;
  background: linear-gradient(135deg, #7f1d1d 0%, #dc2626 100%);
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}
.mm-btn-danger:hover:not(:disabled) { filter: brightness(1.15); }
button:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── RAM Monitor ─────────────────────────────────────────────────── */
.mm-ram-monitor {
  background: linear-gradient(135deg, #0d1526 0%, #111827 100%);
  border: 1px solid #1e293b;
  border-radius: 14px;
  padding: 18px 22px;
  margin-bottom: 24px;
}

.ram-monitor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.ram-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #94a3b8;
}

.ram-icon { font-size: 18px; }
.ram-refresh-tag {
  font-size: 10px;
  color: #475569;
  font-weight: 400;
  background: #1e293b;
  border-radius: 4px;
  padding: 2px 6px;
}

.ram-values {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.ram-used { color: #f1f5f9; font-weight: 700; }
.ram-sep { color: #475569; }
.ram-total { color: #64748b; }
.ram-pct {
  font-size: 13px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 20px;
}
.pct-ok { background: rgba(34,197,94,0.15); color: #22c55e; }
.pct-warning { background: rgba(245,158,11,0.15); color: #f59e0b; }
.pct-critical { background: rgba(239,68,68,0.15); color: #ef4444; }

.ram-bar-track {
  height: 10px;
  background: #1e293b;
  border-radius: 5px;
  overflow: hidden;
  margin-bottom: 10px;
}

.ram-bar-fill {
  height: 100%;
  border-radius: 5px;
  transition: width 0.6s ease, background 0.4s;
}

.ram-footer {
  display: flex;
  gap: 24px;
  font-size: 12px;
  color: #475569;
}

.ram-footer strong { color: #94a3b8; }

/* ── Stats Row ───────────────────────────────────────────────────── */
.mm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}

@media (max-width: 900px) {
  .mm-stats-row { grid-template-columns: repeat(2, 1fr); }
}

.mm-stat-card {
  border-radius: 12px;
  border: 1px solid #1e293b;
  padding: 16px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.mm-stat-green { background: rgba(34,197,94,0.07); border-color: rgba(34,197,94,0.2); }
.mm-stat-slate { background: rgba(100,116,139,0.07); border-color: rgba(100,116,139,0.2); }
.mm-stat-amber { background: rgba(245,158,11,0.07); border-color: rgba(245,158,11,0.2); }
.mm-stat-blue { background: rgba(96,165,250,0.07); border-color: rgba(96,165,250,0.2); }

.stat-icon { font-size: 28px; }
.stat-val { font-size: 22px; font-weight: 700; color: #f1f5f9; }
.stat-lbl { font-size: 12px; color: #64748b; margin-top: 2px; }

/* ── Category Pills ──────────────────────────────────────────────── */
.mm-category-pills {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 22px;
}

.mm-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid #1e293b;
  background: #0d1526;
  color: #64748b;
  border-radius: 20px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
}

.mm-pill:hover { border-color: #334155; color: #94a3b8; }
.mm-pill.active { border-color: #818cf8; color: #818cf8; background: rgba(129,140,248,0.1); }
.pill-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.pill-count {
  background: #1e293b;
  border-radius: 10px;
  padding: 1px 7px;
  font-size: 11px;
  color: #475569;
}
.mm-pill.active .pill-count { background: rgba(129,140,248,0.2); color: #818cf8; }

/* ── Model Grid ──────────────────────────────────────────────────── */
.mm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.mm-card {
  background: #0d1526;
  border: 1px solid #1e293b;
  border-radius: 14px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.mm-card-loaded {
  border-color: rgba(34,197,94,0.35);
  box-shadow: 0 0 20px rgba(34,197,94,0.06);
}

.mm-card-error {
  border-color: rgba(239,68,68,0.4);
}

/* Card Header */
.mc-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.mc-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.mc-icon { font-size: 22px; }

.mc-title-group { flex: 1; min-width: 0; }
.mc-name {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  line-height: 1.3;
  margin-bottom: 5px;
}

.mc-category-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 4px;
}

.mc-status-badge {
  flex-shrink: 0;
}

.badge-on {
  font-size: 11px;
  font-weight: 700;
  color: #22c55e;
  background: rgba(34,197,94,0.1);
  border: 1px solid rgba(34,197,94,0.3);
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
}

.badge-off {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  background: rgba(71,85,105,0.1);
  border: 1px solid #1e293b;
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
}

.badge-loading {
  font-size: 11px;
  font-weight: 600;
  color: #f59e0b;
  background: rgba(245,158,11,0.1);
  border: 1px solid rgba(245,158,11,0.3);
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
}

/* Description */
.mc-desc {
  font-size: 12.5px;
  color: #64748b;
  line-height: 1.6;
  margin: 0;
}

/* Info Row */
.mc-info-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.mc-info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #475569;
  text-transform: uppercase;
}

.info-val {
  font-size: 14px;
  font-weight: 700;
  color: #94a3b8;
}

.info-val.val-active { color: #22c55e; }

/* RAM bar mini */
.mc-ram-bar-track {
  height: 5px;
  background: #1e293b;
  border-radius: 3px;
  overflow: hidden;
}

.mc-ram-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s, background 0.3s;
  opacity: 0.75;
}

/* Error */
.mc-error {
  font-size: 12px;
  color: #f87171;
  background: rgba(248,113,113,0.08);
  border: 1px solid rgba(248,113,113,0.2);
  border-radius: 6px;
  padding: 8px 12px;
}

/* Actions */
.mc-actions { margin-top: auto; }

.mc-btn {
  width: 100%;
  padding: 10px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  transition: all 0.2s;
}

.mc-btn-load {
  background: linear-gradient(135deg, #1e3a5f 0%, #1d4ed8 100%);
  color: #fff;
}
.mc-btn-load:hover { filter: brightness(1.15); }

.mc-btn-unload {
  background: linear-gradient(135deg, #3b1a1a 0%, #7f1d1d 100%);
  color: #fca5a5;
  border: 1px solid rgba(239,68,68,0.3);
}
.mc-btn-unload:hover { filter: brightness(1.2); }

.mc-btn-busy {
  background: #1e293b;
  color: #64748b;
  cursor: not-allowed;
}

/* ── Footer ──────────────────────────────────────────────────────── */
.mm-footer-note {
  text-align: center;
  font-size: 12px;
  color: #334155;
  padding: 12px 0 4px;
}
</style>

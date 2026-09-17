<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { API_BASE_URL } from '../../utils'

const route = useRoute()

const activeTab = ref('offline') // 'offline' | 'production'
const models = ref([])
const endpoints = ref([])
const selectedModelId = ref(null)
const filterModelId = ref('')
const filterEndpointSlug = ref('')
const evaluationData = ref(null)
const productionAnalytics = ref(null)
const isLoading = ref(false)
const isSyncing = ref(false)
const syncMessage = ref('')
const zoomImage = ref(null)

const fetchModels = async () => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models`)
    const data = await res.json()
    if (res.ok) {
      models.value = data.models || []
      const paramModelId = route.query.model_id ? parseInt(route.query.model_id) : null
      if (paramModelId && models.value.some(m => m.id === paramModelId)) {
        selectedModelId.value = paramModelId
      } else if (models.value.length > 0) {
        const active = models.value.find(m => m.is_active)
        selectedModelId.value = active ? active.id : models.value[0].id
      }
    }
  } catch (err) {
    console.error('Failed to fetch models list:', err)
  }
}

const fetchEvaluation = async (modelId) => {
  if (!modelId) return
  isLoading.value = true
  evaluationData.value = null
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/evaluation`)
    const data = await res.json()
    if (res.ok) {
      evaluationData.value = data
    }
  } catch (err) {
    console.error('Failed to fetch model evaluation:', err)
  } finally {
    isLoading.value = false
  }
}

const fetchEndpoints = async () => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints`)
    const data = await res.json()
    if (res.ok) {
      endpoints.value = data.endpoints || []
    }
  } catch (err) {
    console.error('Failed to fetch endpoints:', err)
  }
}

const fetchProductionAnalytics = async () => {
  try {
    const params = new URLSearchParams()
    if (filterModelId.value) params.append('model_id', filterModelId.value)
    if (filterEndpointSlug.value) params.append('endpoint_slug', filterEndpointSlug.value)
    const res = await fetch(`${API_BASE_URL}/api/v1/models/analytics/production?${params.toString()}`)
    const data = await res.json()
    if (res.ok) {
      productionAnalytics.value = data
    }
  } catch (err) {
    console.error('Failed to fetch production analytics:', err)
  }
}

const triggerSyncToLabelStudio = async () => {
  if (!confirm('Kirim seluruh gambar yang ditandai butuh review dan auto-labeled ke Label Studio?')) return
  isSyncing.value = true
  syncMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/data/sync-label-studio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        include_bad: true,
        include_good: true,
        model_id: filterModelId.value ? parseInt(filterModelId.value) : null,
        endpoint_slug: filterEndpointSlug.value || null
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      syncMessage.value = data.message || `Berhasil mensinkronkan ${data.synced_count} task ke Label Studio!`
      await fetchProductionAnalytics()
    } else {
      alert(data.message || data.error || 'Gagal sinkronisasi ke Label Studio.')
    }
  } catch (err) {
    alert('Koneksi backend error saat sinkronisasi.')
  } finally {
    isSyncing.value = false
  }
}

const downloadModelWeights = () => {
  if (!selectedModelId.value) return
  window.open(`${API_BASE_URL}/api/v1/models/${selectedModelId.value}/download-weights`, '_blank')
}

const downloadEvaluationZip = () => {
  if (!selectedModelId.value) return
  window.open(`${API_BASE_URL}/api/v1/models/${selectedModelId.value}/download-evaluation`, '_blank')
}

const getFullAssetUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE_URL}${url}`
}

watch(selectedModelId, (newId) => {
  if (newId) fetchEvaluation(newId)
})

onMounted(async () => {
  await fetchModels()
  await fetchEndpoints()
  if (selectedModelId.value) {
    await fetchEvaluation(selectedModelId.value)
  }
  await fetchProductionAnalytics()
})
</script>

<template>
  <div class="eval-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Model Evaluation & Production Analytics</h1>
        <p class="page-subtitle">
          Evaluasi performa model hasil training (mAP50, Precision, Recall, Confusion Matrix) serta pantau akurasi produksi online dari user feedback.
        </p>
      </div>

      <!-- Tab Switcher -->
      <div class="tab-switcher">
        <button 
          class="tab-btn" 
          :class="{ active: activeTab === 'offline' }" 
          @click="activeTab = 'offline'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 20V10"></path><path d="M12 20V4"></path><path d="M6 20v-6"></path></svg>
          Offline Training Evaluation
        </button>
        <button 
          class="tab-btn" 
          :class="{ active: activeTab === 'production' }" 
          @click="activeTab = 'production'"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
          Online Production & Flywheel
        </button>
      </div>
    </div>

    <!-- TAB 1: OFFLINE TRAINING EVALUATION -->
    <div v-if="activeTab === 'offline'" class="tab-content">
      <!-- Model Selector Bar -->
      <div class="selector-bar">
        <div class="selector-left">
          <label class="selector-label">Pilih Versi Model:</label>
          <select v-model="selectedModelId" class="model-select">
            <option v-for="m in models" :key="m.id" :value="m.id">
              {{ m.name }} ({{ m.version }}) {{ m.is_active ? '— [AKTIF]' : '' }}
            </option>
          </select>
        </div>

        <div class="selector-actions" v-if="evaluationData">
          <button 
            v-if="evaluationData.has_weights !== false" 
            class="btn btn-sm btn-outline-secondary" 
            @click="downloadModelWeights"
            title="Download file weights model (.pt)"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Download Weights (.pt)
          </button>
          <button 
            v-if="evaluationData.has_evaluation" 
            class="btn btn-sm btn-primary" 
            @click="downloadEvaluationZip"
            title="Download arsip hasil evaluasi training (.zip)"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Download Arsip Evaluasi (.zip)
          </button>
        </div>
      </div>

      <div v-if="isLoading" class="loading-state">
        <div class="spinner"></div>
        <span>Memuat data evaluasi model...</span>
      </div>

      <div v-else-if="evaluationData">
        <!-- Training Settings & Metadata Banner -->
        <div class="model-meta-card">
          <div class="meta-row">
            <div class="meta-col">
              <span class="meta-title">Nama & Versi Model</span>
              <div class="meta-main">{{ evaluationData.name }} <span class="font-mono text-xs px-2 py-0.5 bg-slate-100 rounded ml-1">{{ evaluationData.version }}</span></div>
            </div>
            <div class="meta-col">
              <span class="meta-title">Tanggal Training</span>
              <div class="meta-main text-blue-600 font-semibold">
                {{ evaluationData.metrics?.training_date || (evaluationData.created_at ? new Date(evaluationData.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '-') }}
              </div>
            </div>
            <div class="meta-col flex-2">
              <span class="meta-title">Keterangan Setting / Hyperparameters</span>
              <div class="meta-main text-slate-700">
                {{ evaluationData.metrics?.training_settings || evaluationData.description || 'Pengaturan training default (200 Epochs, imgsz 640)' }}
              </div>
            </div>
            <div class="meta-col" v-if="evaluationData.metrics?.epochs">
              <span class="meta-title">Epochs Dilatih</span>
              <div class="meta-main font-mono text-emerald-600 font-bold">
                {{ evaluationData.metrics.epochs }} Epochs
              </div>
            </div>
          </div>
        </div>

        <!-- Metric KPI Cards -->
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">mAP @ 0.50</div>
            <div class="kpi-val text-emerald-600">
              {{ evaluationData.metrics?.map50 ? (evaluationData.metrics.map50 * 100).toFixed(1) + '%' : '-' }}
            </div>
            <div class="kpi-desc">Mean Average Precision pada IoU 50%</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">mAP @ 0.50:0.95</div>
            <div class="kpi-val text-blue-600">
              {{ evaluationData.metrics?.map50_95 ? (evaluationData.metrics.map50_95 * 100).toFixed(1) + '%' : '-' }}
            </div>
            <div class="kpi-desc">Comprehensive mAP range</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Precision</div>
            <div class="kpi-val text-indigo-600">
              {{ evaluationData.metrics?.precision ? (evaluationData.metrics.precision * 100).toFixed(1) + '%' : '-' }}
            </div>
            <div class="kpi-desc">Rasio deteksi benar terhadap total prediksi</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Recall</div>
            <div class="kpi-val text-amber-600">
              {{ evaluationData.metrics?.recall ? (evaluationData.metrics.recall * 100).toFixed(1) + '%' : '-' }}
            </div>
            <div class="kpi-desc">Rasio objek terdeteksi dari seluruh ground truth</div>
          </div>
        </div>

        <!-- Visual Training Artifacts Gallery -->
        <div class="visuals-section">
          <h2 class="section-title">Visualisasi Evaluasi & Confusion Matrix</h2>
          <p class="section-desc">Grafik yang diekstrak dari arsip zip hasil training YOLO (runs/detect/train/). Klik gambar untuk memperbesar.</p>

          <div v-if="Object.keys(evaluationData.visuals || {}).length === 0" class="empty-visuals">
            <svg viewBox="0 0 24 24" width="48" height="48" stroke="#94a3b8" stroke-width="1.5" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
            <p>Arsip evaluasi (results.zip) belum diunggah untuk versi model ini. Saat mengunggah model di halaman <strong>Models</strong>, sertakan file zip dari folder training untuk otomatis menampilkan grafik di sini.</p>
          </div>

          <div v-else class="visuals-grid">
            <!-- Confusion Matrix -->
            <div v-if="evaluationData.visuals.confusion_matrix" class="visual-card" @click="zoomImage = getFullAssetUrl(evaluationData.visuals.confusion_matrix)">
              <div class="visual-header">Confusion Matrix</div>
              <img :src="getFullAssetUrl(evaluationData.visuals.confusion_matrix)" alt="Confusion Matrix" class="visual-thumb" />
            </div>

            <!-- Normalized Confusion Matrix -->
            <div v-if="evaluationData.visuals.confusion_matrix_norm" class="visual-card" @click="zoomImage = getFullAssetUrl(evaluationData.visuals.confusion_matrix_norm)">
              <div class="visual-header">Normalized Confusion Matrix</div>
              <img :src="getFullAssetUrl(evaluationData.visuals.confusion_matrix_norm)" alt="Normalized Confusion Matrix" class="visual-thumb" />
            </div>

            <!-- PR Curve -->
            <div v-if="evaluationData.visuals.pr_curve" class="visual-card" @click="zoomImage = getFullAssetUrl(evaluationData.visuals.pr_curve)">
              <div class="visual-header">Precision-Recall Curve</div>
              <img :src="getFullAssetUrl(evaluationData.visuals.pr_curve)" alt="PR Curve" class="visual-thumb" />
            </div>

            <!-- F1 Curve -->
            <div v-if="evaluationData.visuals.f1_curve" class="visual-card" @click="zoomImage = getFullAssetUrl(evaluationData.visuals.f1_curve)">
              <div class="visual-header">F1-Confidence Curve</div>
              <img :src="getFullAssetUrl(evaluationData.visuals.f1_curve)" alt="F1 Curve" class="visual-thumb" />
            </div>

            <!-- Results Loss Curves -->
            <div v-if="evaluationData.visuals.results_png" class="visual-card col-span-2" @click="zoomImage = getFullAssetUrl(evaluationData.visuals.results_png)">
              <div class="visual-header">Training & Validation Loss Curves (results.png)</div>
              <img :src="getFullAssetUrl(evaluationData.visuals.results_png)" alt="Training Curves" class="visual-thumb" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: ONLINE PRODUCTION ANALYTICS & FLYWHEEL -->
    <div v-else-if="activeTab === 'production'" class="tab-content">
      <!-- Sync Alert Banner -->
      <div v-if="syncMessage" class="alert alert-success">
        <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
        {{ syncMessage }}
      </div>

      <div v-if="productionAnalytics" class="prod-dashboard">
        <!-- Production Filter Bar -->
        <div class="filter-strip">
          <div class="filter-item">
            <label class="filter-label">Filter Berdasarkan Model:</label>
            <select v-model="filterModelId" @change="fetchProductionAnalytics" class="filter-select">
              <option value="">Semua Model Registry</option>
              <option v-for="m in models" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.version }}) {{ m.is_active ? '★ Aktif' : '' }}
              </option>
            </select>
          </div>
          <div class="filter-item">
            <label class="filter-label">Filter Berdasarkan Serving Endpoint:</label>
            <select v-model="filterEndpointSlug" @change="fetchProductionAnalytics" class="filter-select">
              <option value="">Semua Serving Endpoints</option>
              <option v-for="ep in endpoints" :key="ep.id" :value="ep.slug">
                🌐 {{ ep.name }} ({{ ep.slug }})
              </option>
            </select>
          </div>
          <button class="btn btn-sm btn-secondary" @click="() => { filterModelId = ''; filterEndpointSlug = ''; fetchProductionAnalytics(); }">
            Reset Filter
          </button>
        </div>

        <!-- Flywheel Status Overview Cards -->
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Total Prediksi API</div>
            <div class="kpi-val text-slate-800">{{ productionAnalytics.total_predictions }}</div>
            <div class="kpi-desc">Total request inferensi yang dilayani</div>
          </div>
          <div class="kpi-card highlight-green">
            <div class="kpi-label">Feedback Akurasi (Good / Auto)</div>
            <div class="kpi-val text-emerald-600">
              {{ productionAnalytics.feedback.accuracy_ratio }}%
            </div>
            <div class="kpi-desc">{{ productionAnalytics.feedback.good + productionAnalytics.feedback.auto_labeled }} dari {{ productionAnalytics.total_predictions }} data terverifikasi baik</div>
          </div>
          <div class="kpi-card highlight-red">
            <div class="kpi-label">Antrean Review Ulang (Bad Feedback)</div>
            <div class="kpi-val text-rose-600">
              {{ productionAnalytics.review_queue.pending_human_review }}
            </div>
            <div class="kpi-desc">Gambar yang dilaporkan tidak akurat</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Rata-Rata Latensi Model</div>
            <div class="kpi-val text-indigo-600">
              {{ productionAnalytics.performance.avg_latency_ms }} ms
            </div>
            <div class="kpi-desc">Inference speed pada model aktif</div>
          </div>
        </div>

        <!-- Flywheel Action Banner -->
        <div class="flywheel-action-card">
          <div class="flywheel-left">
            <div class="flywheel-icon">
              <svg viewBox="0 0 24 24" width="28" height="28" stroke="currentColor" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
            </div>
            <div>
              <h3 class="flywheel-title">Siklus Retraining Bulanan (Active Learning)</h3>
              <p class="flywheel-desc">
                Ada <strong>{{ productionAnalytics.review_queue.unsynced_to_label_studio }}</strong> gambar review baru dan <strong>{{ productionAnalytics.review_queue.unsynced_auto_labeled }}</strong> gambar auto-labeled di S3 yang siap disinkronkan ke Label Studio untuk proses anotasi ulang & training versi berikutnya.
              </p>
            </div>
          </div>
          <button 
            class="btn btn-primary btn-sync" 
            @click="triggerSyncToLabelStudio" 
            :disabled="isSyncing || (productionAnalytics.review_queue.unsynced_to_label_studio === 0 && productionAnalytics.review_queue.unsynced_auto_labeled === 0)"
          >
            <span v-if="isSyncing" class="spinner-sm"></span>
            {{ isSyncing ? 'Mengirim ke Label Studio...' : 'Sync ke Label Studio Sekarang' }}
          </button>
        </div>

        <!-- Breakdown Tables -->
        <div class="flywheel-details-grid">
          <div class="card detail-card">
            <h3 class="card-header-title">Distribusi Feedback Pengguna</h3>
            <div class="distribution-list">
              <div class="dist-row">
                <span class="dist-label text-emerald-700">Akurat (Verified Good)</span>
                <span class="dist-val font-semibold">{{ productionAnalytics.feedback.good }}</span>
              </div>
              <div class="dist-row">
                <span class="dist-label text-blue-700">Auto-Labeled (High Conf)</span>
                <span class="dist-val font-semibold">{{ productionAnalytics.feedback.auto_labeled }}</span>
              </div>
              <div class="dist-row">
                <span class="dist-label text-indigo-700">Human Audit Queue (10% Sample)</span>
                <span class="dist-val font-semibold">{{ productionAnalytics.feedback.audit_required || 0 }}</span>
              </div>
              <div class="dist-row">
                <span class="dist-label text-rose-700">Tidak Akurat (Needs Re-labeling)</span>
                <span class="dist-val font-semibold">{{ productionAnalytics.feedback.bad }}</span>
              </div>
              <div class="dist-row">
                <span class="dist-label text-slate-500">Menunggu Feedback (Pending)</span>
                <span class="dist-val font-semibold">{{ productionAnalytics.feedback.pending }}</span>
              </div>
            </div>
          </div>

          <div class="card detail-card">
            <h3 class="card-header-title">Status Model Serving Saat Ini</h3>
            <div class="serving-info-list">
              <div class="serving-row">
                <span class="serving-label">Nama Model</span>
                <span class="serving-val font-semibold">{{ productionAnalytics.performance.active_model.name }}</span>
              </div>
              <div class="serving-row">
                <span class="serving-label">Versi</span>
                <span class="serving-val font-mono">{{ productionAnalytics.performance.active_model.version }}</span>
              </div>
              <div class="serving-row">
                <span class="serving-label">Jumlah Kelas</span>
                <span class="serving-val font-semibold">{{ productionAnalytics.performance.active_model.classes_count }} Kelas</span>
              </div>
              <div class="serving-row">
                <span class="serving-label">Endpoint URL</span>
                <span class="serving-val font-mono text-xs text-blue-600">/api/v1/models/predict</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent Inferences & Flywheel Stream -->
        <div v-if="productionAnalytics.recent_predictions && productionAnalytics.recent_predictions.length > 0" class="card recent-preds-card mt-4">
          <div class="card-header-clean">
            <h3 class="card-header-title">Live Inferences & Feedback Stream (12 Terakhir)</h3>
            <span class="text-xs text-slate-500">Hasil deteksi langsung dari endpoint produksi yang tersimpan di S3</span>
          </div>
          <div class="recent-preds-grid">
            <div v-for="p in productionAnalytics.recent_predictions" :key="p.id" class="pred-thumb-card">
              <div class="pred-thumb-wrapper" @click="zoomImage = getFullAssetUrl(p.annotated_image_url || p.original_image_url)">
                <img :src="getFullAssetUrl(p.annotated_image_url || p.original_image_url)" alt="Prediction" class="pred-img" />
                <span class="zoom-hint">Perbesar</span>
              </div>
              <div class="pred-meta">
                <div class="meta-row-top">
                  <span class="badge-endpoint">{{ p.endpoint_slug }}</span>
                  <span class="text-xs font-mono text-slate-500">{{ p.latency_ms ? `${p.latency_ms}ms` : '' }}</span>
                </div>
                <div class="text-xs font-semibold text-slate-800">
                  {{ p.detection_count }} objek ({{ (p.top_confidence * 100).toFixed(0) }}%)
                </div>
                <div class="status-badge-row mt-1">
                  <span v-if="p.feedback_status === 'good'" class="badge-status-good">👍 Akurat</span>
                  <span v-else-if="p.feedback_status === 'bad'" class="badge-status-bad">👎 Meleset</span>
                  <span v-else-if="p.feedback_status === 'auto_labeled'" class="badge-status-auto">⚡ Auto-Labeled</span>
                  <span v-else-if="p.feedback_status === 'audit_required'" class="badge-status-audit">🔍 Audit Sample</span>
                  <span v-else class="badge-status-pending">⏳ Pending</span>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- Image Zoom Modal -->
    <div v-if="zoomImage" class="modal-overlay" @click="zoomImage = null">
      <div class="modal-zoom">
        <img :src="zoomImage" alt="Zoomed Asset" class="zoomed-image" />
      </div>
    </div>

  </div>
</template>

<style scoped>
.eval-container {
  padding: 8px 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 6px 0;
}

.page-subtitle {
  font-size: 0.875rem;
  color: #64748b;
  margin: 0;
  max-width: 650px;
  line-height: 1.5;
}

.tab-switcher {
  display: flex;
  background: #f1f5f9;
  padding: 4px;
  border-radius: 8px;
  gap: 4px;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 0.85rem;
  font-weight: 500;
  border: none;
  background: none;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn.active {
  background: white;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.selector-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
  background: white;
  padding: 12px 18px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.selector-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.selector-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.model-meta-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}

.meta-col {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.meta-col.flex-2 {
  flex: 2;
  min-width: 240px;
}

.meta-title {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  color: #64748b;
  letter-spacing: 0.04em;
}

.meta-main {
  font-size: 0.88rem;
  color: #1e293b;
}

.selector-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.model-select {
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 0.875rem;
  min-width: 280px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  background: white;
  border-radius: 10px;
  padding: 16px 20px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

.kpi-card.highlight-green {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.kpi-card.highlight-red {
  border-color: #fecaca;
  background: #fef2f2;
}

.kpi-label {
  font-size: 0.8rem;
  color: #64748b;
  font-weight: 500;
  margin-bottom: 6px;
}

.kpi-val {
  font-size: 1.6rem;
  font-weight: 700;
  margin-bottom: 4px;
}

.kpi-desc {
  font-size: 0.75rem;
  color: #94a3b8;
}

.text-emerald-600 { color: #059669; }
.text-blue-600 { color: #2563eb; }
.text-indigo-600 { color: #4f46e5; }
.text-amber-600 { color: #d97706; }
.text-rose-600 { color: #e11d48; }

.visuals-section {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 24px;
}

.section-title {
  font-size: 1.15rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 6px 0;
}

.section-desc {
  font-size: 0.85rem;
  color: #64748b;
  margin: 0 0 20px 0;
}

.visuals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.col-span-2 {
  grid-column: span 2;
}

@media (max-width: 768px) {
  .col-span-2 { grid-column: span 1; }
}

.visual-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  background: #f8fafc;
}

.visual-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 12px rgba(0,0,0,0.06);
}

.visual-header {
  padding: 10px 14px;
  background: white;
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  border-bottom: 1px solid #e2e8f0;
}

.visual-thumb {
  width: 100%;
  max-height: 280px;
  object-fit: contain;
  display: block;
  background: white;
}

.empty-visuals {
  text-align: center;
  padding: 48px 24px;
  color: #64748b;
  font-size: 0.875rem;
  max-width: 500px;
  margin: 0 auto;
}

.flywheel-action-card {
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  color: white;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.flywheel-left {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 700px;
}

.flywheel-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  background: rgba(37, 99, 235, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #60a5fa;
  flex-shrink: 0;
}

.flywheel-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 6px 0;
}

.flywheel-desc {
  font-size: 0.85rem;
  color: #cbd5e1;
  margin: 0;
  line-height: 1.4;
}

.btn-sync {
  background: #2563eb;
  padding: 12px 24px;
  font-weight: 600;
  font-size: 0.9rem;
}

.flywheel-details-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 768px) {
  .flywheel-details-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 20px;
}

.card-header-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 16px 0;
}

.dist-row, .serving-row {
  display: flex;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.85rem;
}

.dist-row:last-child, .serving-row:last-child {
  border-bottom: none;
}

/* Zoom Modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
  cursor: pointer;
}

.modal-zoom {
  max-width: 90vw;
  max-height: 90vh;
}

.zoomed-image {
  max-width: 100%;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e2e8f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>

<style scoped>

.filter-strip { display: flex; align-items: center; gap: 16px; background: white; padding: 12px 18px; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 20px; flex-wrap: wrap; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.filter-select { padding: 6px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.825rem; min-width: 200px; background: white; }

.recent-preds-card { background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 20px; margin-top: 24px; }
.card-header-clean { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid #f1f5f9; padding-bottom: 12px; }
.recent-preds-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
.pred-thumb-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.pred-thumb-wrapper { position: relative; height: 110px; background: #0f172a; cursor: pointer; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.pred-img { width: 100%; height: 100%; object-fit: cover; }
.zoom-hint { position: absolute; bottom: 4px; right: 4px; background: rgba(0,0,0,0.6); color: white; font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; opacity: 0; transition: opacity 0.2s; }
.pred-thumb-wrapper:hover .zoom-hint { opacity: 1; }
.pred-meta { padding: 8px 10px; }
.meta-row-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.badge-endpoint { background: #eff6ff; color: #1d4ed8; font-family: monospace; font-size: 0.65rem; padding: 1px 6px; border-radius: 4px; border: 1px solid #dbeafe; font-weight: 600; }
.badge-status-good { font-size: 0.7rem; color: #15803d; font-weight: 600; }
.badge-status-bad { font-size: 0.7rem; color: #b91c1c; font-weight: 600; }
.badge-status-auto { font-size: 0.7rem; color: #2563eb; font-weight: 600; }
.badge-status-audit { font-size: 0.7rem; color: #7c3aed; font-weight: 600; }
.badge-status-pending { font-size: 0.7rem; color: #64748b; font-weight: 500; }
</style>

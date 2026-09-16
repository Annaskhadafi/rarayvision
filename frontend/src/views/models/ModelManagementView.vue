<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

const models = ref([])
const isLoading = ref(false)
const isActivating = ref(false)
const isExporting = ref(false)
const showUploadModal = ref(false)
const uploadLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// Upload form state
const uploadForm = ref({
  name: '',
  version: '',
  task_type: 'detection',
  framework: 'yolo',
  description: '',
  model_file: null,
  onnx_file: null,
  results_file: null
})

// Selected classes modal
const selectedClasses = ref([])
const showClassesModal = ref(false)
const selectedModelName = ref('')

const fetchModels = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models`)
    const data = await res.json()
    if (res.ok) {
      models.value = data.models || []
    } else {
      errorMessage.value = data.detail || 'Gagal memuat daftar model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi ke backend gagal.'
  } finally {
    isLoading.value = false
  }
}

const activeModel = computed(() => {
  return models.value.find(m => m.is_active) || null
})

const handleActivate = async (modelId) => {
  if (isActivating.value) return
  isActivating.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/activate`, {
      method: 'PUT'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Model aktif berhasil diubah.'
      await fetchModels()
    } else {
      errorMessage.value = data.detail || data.error || 'Gagal mengaktifkan model.'
    }
  } catch (err) {
    errorMessage.value = 'Gagal menghubungi server untuk hot-swap model.'
  } finally {
    isActivating.value = false
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

const handleRollback = async () => {
  if (!confirm('Apakah Anda yakin ingin membalikkan (Rollback) ke model aktif versi sebelumnya?')) return
  isActivating.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/rollback`, {
      method: 'POST'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = `Rollback Berhasil: ${data.message}`
      await fetchModels()
    } else {
      errorMessage.value = data.detail || data.error || 'Gagal melakukan rollback model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi error saat melakukan rollback.'
  } finally {
    isActivating.value = false
  }
}

const handleExportOnnx = async (modelId) => {
  isExporting.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/export-onnx`, {
      method: 'POST'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message
      await fetchModels()
    } else {
      errorMessage.value = data.detail || data.error || 'Gagal mengeksport model ke ONNX.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend gagal.'
  } finally {
    isExporting.value = false
  }
}

const handleDelete = async (model) => {
  if (model.is_active) {
    alert('Model yang sedang aktif tidak dapat dihapus. Silakan aktifkan model lain terlebih dahulu.')
    return
  }
  if (!confirm(`Hapus model "${model.name} (${model.version})"?`)) return

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${model.id}`, {
      method: 'DELETE'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = `Model ${model.name} berhasil dihapus.`
      await fetchModels()
    } else {
      errorMessage.value = data.detail || 'Gagal menghapus model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend error.'
  }
}

const openClassesModal = (model) => {
  selectedModelName.value = `${model.name} (${model.version})`
  selectedClasses.value = model.classes || []
  showClassesModal.value = true
}

const handleModelFileChange = (e) => {
  const file = e.target.files[0]
  if (file) {
    uploadForm.value.model_file = file
    if (!uploadForm.value.name) {
      uploadForm.value.name = file.name.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ')
    }
    if (!uploadForm.value.version) {
      uploadForm.value.version = 'v1.0.0'
    }
    // Auto-detect framework
    if (file.name.endsWith('.onnx')) {
      uploadForm.value.framework = 'onnx'
    } else {
      uploadForm.value.framework = 'yolo'
    }
  }
}

const handleOnnxFileChange = (e) => {
  const file = e.target.files[0]
  if (file) {
    uploadForm.value.onnx_file = file
  }
}

const handleResultsFileChange = (e) => {
  const file = e.target.files[0]
  if (file) {
    uploadForm.value.results_file = file
  }
}

const submitUpload = async () => {
  if (!uploadForm.value.model_file) {
    alert('Silakan pilih file model (.pt atau .onnx)!')
    return
  }
  if (!uploadForm.value.name || !uploadForm.value.version) {
    alert('Nama model dan versi wajib diisi!')
    return
  }

  uploadLoading.value = true
  errorMessage.value = ''
  successMessage.value = ''

  const formData = new FormData()
  formData.append('name', uploadForm.value.name)
  formData.append('version', uploadForm.value.version)
  formData.append('task_type', uploadForm.value.task_type)
  formData.append('framework', uploadForm.value.framework)
  if (uploadForm.value.description) {
    formData.append('description', uploadForm.value.description)
  }
  formData.append('model_file', uploadForm.value.model_file)
  if (uploadForm.value.onnx_file) {
    formData.append('onnx_file', uploadForm.value.onnx_file)
  }
  if (uploadForm.value.results_file) {
    formData.append('results_file', uploadForm.value.results_file)
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/upload`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = `Model "${data.model.name}" berhasil diunggah.`
      showUploadModal.value = false
      uploadForm.value = {
        name: '',
        version: '',
        task_type: 'detection',
        framework: 'yolo',
        description: '',
        model_file: null,
        onnx_file: null,
        results_file: null
      }
      await fetchModels()
    } else {
      errorMessage.value = data.detail || 'Gagal mengunggah model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi error saat mengunggah model.'
  } finally {
    uploadLoading.value = false
  }
}

onMounted(() => {
  fetchModels()
})
</script>

<template>
  <div class="models-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">ML Models & Serving Registry</h1>
        <p class="page-subtitle">
          Kelola versi model Object Detection (YOLO .pt & ONNX), unggah model hasil training, serta ganti atau rollback model aktif secara instan tanpa downtime.
        </p>
      </div>
      <div class="header-actions">
        <button class="btn btn-warning" @click="handleRollback" :disabled="isActivating || models.length < 2">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M1 4v6h6"></path><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>
          Rollback Model
        </button>
        <button class="btn btn-secondary" @click="fetchModels" :disabled="isLoading">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
          Refresh
        </button>
        <button class="btn btn-primary" @click="showUploadModal = true">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          Upload Model (.pt / .onnx)
        </button>
      </div>
    </div>

    <!-- Alert Notifications -->
    <div v-if="successMessage" class="alert alert-success">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
      {{ successMessage }}
    </div>
    <div v-if="errorMessage" class="alert alert-danger">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ errorMessage }}
    </div>

    <!-- Stats Summary Cards -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Model Terdaftar</div>
        <div class="stat-val">{{ models.length }}</div>
        <div class="stat-desc">Versi tersimpan di registry</div>
      </div>
      <div class="stat-card highlight">
        <div class="stat-label">Model Aktif (Hot-Swapped)</div>
        <div class="stat-val text-primary">{{ activeModel ? activeModel.name : 'None' }}</div>
        <div class="stat-desc font-mono">{{ activeModel ? activeModel.version : '-' }} ({{ activeModel ? activeModel.framework : '-' }})</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Jumlah Kelas Terdeteksi</div>
        <div class="stat-val">{{ activeModel ? activeModel.classes_count : 0 }}</div>
        <div class="stat-desc">Kategori objek model aktif</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Serving Endpoint Status</div>
        <div class="stat-val text-success">ONLINE</div>
        <div class="stat-desc">POST /api/v1/models/predict</div>
      </div>
    </div>

    <!-- Models Table Card -->
    <div class="card table-card">
      <div class="card-header">
        <h2 class="card-title">Daftar Versi Model</h2>
        <span class="badge badge-info">{{ models.length }} Model</span>
      </div>

      <div v-if="isLoading" class="table-loading">
        <div class="spinner"></div>
        <span>Memuat data model...</span>
      </div>

      <div v-else-if="models.length === 0" class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48" stroke="#94a3b8" stroke-width="1.5" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
        <p>Belum ada model terdaftar. Klik "Upload Model (.pt / .onnx)" untuk menambahkan bobot model YOLO/ONNX.</p>
      </div>

      <div v-else class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Nama Model</th>
              <th>Versi</th>
              <th>Framework / Format</th>
              <th>Kelas (Labels)</th>
              <th>mAP50</th>
              <th>Tanggal Ditambahkan</th>
              <th class="text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in models" :key="m.id" :class="{ 'row-active': m.is_active }">
              <td>
                <span v-if="m.is_active" class="badge badge-active">
                  <span class="status-dot pulse"></span> Aktif Melayani
                </span>
                <span v-else class="badge badge-inactive">Standby</span>
              </td>
              <td>
                <div class="font-semibold text-slate-800">{{ m.name }}</div>
                <div class="text-xs text-slate-500">{{ m.description || 'Tidak ada deskripsi' }}</div>
              </td>
              <td>
                <span class="font-mono text-sm px-2 py-0.5 bg-slate-100 rounded">{{ m.version }}</span>
              </td>
              <td>
                <span class="badge badge-framework">
                  {{ m.framework }}
                </span>
              </td>
              <td>
                <button 
                  v-if="m.classes_count > 0" 
                  class="btn-text" 
                  @click="openClassesModal(m)"
                >
                  {{ m.classes_count }} Kelas (Lihat)
                </button>
                <span v-else class="text-xs text-slate-400">0 Kelas</span>
              </td>
              <td>
                <span v-if="m.metrics && m.metrics.map50" class="font-mono text-sm font-semibold text-emerald-600">
                  {{ (m.metrics.map50 * 100).toFixed(1) }}%
                </span>
                <span v-else class="text-xs text-slate-400">-</span>
              </td>
              <td class="text-xs text-slate-500">
                {{ m.created_at ? new Date(m.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '-' }}
              </td>
              <td class="text-right">
                <div class="actions-group">
                  <button 
                    v-if="!m.is_active" 
                    class="btn btn-sm btn-outline-primary" 
                    @click="handleActivate(m.id)"
                    :disabled="isActivating"
                  >
                    Aktifkan
                  </button>
                  <button 
                    v-if="m.framework === 'yolo'" 
                    class="btn btn-sm btn-outline-secondary" 
                    @click="handleExportOnnx(m.id)"
                    :disabled="isExporting"
                    title="Export ke ONNX Runtime untuk akselerasi CPU"
                  >
                    Export ONNX
                  </button>
                  <button 
                    class="btn btn-sm btn-outline-secondary" 
                    @click="router.push(`/models/evaluation?model_id=${m.id}`)"
                  >
                    Evaluasi
                  </button>
                  <button 
                    v-if="!m.is_active" 
                    class="btn btn-sm btn-outline-danger" 
                    @click="handleDelete(m)"
                  >
                    Hapus
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Upload Model Modal -->
    <div v-if="showUploadModal" class="modal-overlay" @click.self="showUploadModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3 class="modal-title">Unggah Model (.pt / .onnx) & Hasil Training</h3>
          <button class="btn-close" @click="showUploadModal = false">&times;</button>
        </div>
        <form @submit.prevent="submitUpload" class="modal-body">
          <div class="form-group">
            <label class="form-label">Nama Model *</label>
            <input 
              v-model="uploadForm.name" 
              type="text" 
              class="form-input" 
              placeholder="Contoh: YOLO Defect Detection" 
              required 
            />
          </div>

          <div class="form-row">
            <div class="form-group flex-1">
              <label class="form-label">Versi *</label>
              <input 
                v-model="uploadForm.version" 
                type="text" 
                class="form-input" 
                placeholder="v1.0.0" 
                required 
              />
            </div>
            <div class="form-group flex-1">
              <label class="form-label">Framework</label>
              <select v-model="uploadForm.framework" class="form-input">
                <option value="yolo">Ultralytics YOLO (.pt)</option>
                <option value="onnx">ONNX Runtime (.onnx)</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">File Bobot Model (.pt atau .onnx) *</label>
            <input 
              type="file" 
              accept=".pt,.onnx" 
              class="form-file-input" 
              @change="handleModelFileChange" 
              required 
            />
            <span class="form-hint">Upload file weights hasil training (misal: best.pt atau best.onnx).</span>
          </div>

          <div class="form-group">
            <label class="form-label">File ONNX Pendamping (.onnx opsional)</label>
            <input 
              type="file" 
              accept=".onnx" 
              class="form-file-input" 
              @change="handleOnnxFileChange" 
            />
            <span class="form-hint">Jika model utama adalah .pt, Anda dapat sekaligus menyertakan file .onnx untuk akselerasi serving di CPU.</span>
          </div>

          <div class="form-group">
            <label class="form-label">File Arsip Evaluasi Training (.zip opsional)</label>
            <input 
              type="file" 
              accept=".zip" 
              class="form-file-input" 
              @change="handleResultsFileChange" 
            />
            <span class="form-hint">Zip folder training YOLO yang berisi results.csv, confusion_matrix.png, PR_curve.png untuk otomatis ditampilkan di Halaman Evaluasi.</span>
          </div>

          <div class="form-group">
            <label class="form-label">Deskripsi / Catatan Model</label>
            <textarea 
              v-model="uploadForm.description" 
              class="form-textarea" 
              rows="2" 
              placeholder="Keterangan dataset, augmentasi, atau tujuan training..."
            ></textarea>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="showUploadModal = false">Batal</button>
            <button type="submit" class="btn btn-primary" :disabled="uploadLoading">
              <span v-if="uploadLoading" class="spinner-sm"></span>
              {{ uploadLoading ? 'Mengunggah & Memproses...' : 'Simpan Model' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- View Classes Modal -->
    <div v-if="showClassesModal" class="modal-overlay" @click.self="showClassesModal = false">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3 class="modal-title">Daftar Kelas: {{ selectedModelName }}</h3>
          <button class="btn-close" @click="showClassesModal = false">&times;</button>
        </div>
        <div class="modal-body classes-list-wrapper">
          <div class="classes-badges">
            <span v-for="(cls, idx) in selectedClasses" :key="idx" class="class-pill">
              <span class="class-idx">{{ idx }}</span> {{ cls }}
            </span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showClassesModal = false">Tutup</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.models-container { padding: 8px 0; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.page-title { font-size: 1.5rem; font-weight: 700; color: #0f172a; margin: 0 0 6px 0; }
.page-subtitle { font-size: 0.875rem; color: #64748b; margin: 0; max-width: 650px; line-height: 1.5; }
.header-actions { display: flex; gap: 12px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: white; border-radius: 10px; padding: 16px 20px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
.stat-card.highlight { border-color: #cbd5e1; background: linear-gradient(to bottom right, #ffffff, #f8fafc); }
.stat-label { font-size: 0.8rem; color: #64748b; font-weight: 500; margin-bottom: 6px; }
.stat-val { font-size: 1.5rem; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.stat-desc { font-size: 0.75rem; color: #94a3b8; }
.text-primary { color: #2563eb; }
.text-success { color: #16a34a; }
.card { background: white; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.02); overflow: hidden; }
.card-header { padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; }
.card-title { font-size: 1.1rem; font-weight: 600; color: #1e293b; margin: 0; }
.table-responsive { width: 100%; overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; text-align: left; }
.data-table th { background: #f8fafc; padding: 12px 20px; font-size: 0.75rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #e2e8f0; }
.data-table td { padding: 14px 20px; border-bottom: 1px solid #f1f5f9; font-size: 0.875rem; vertical-align: middle; }
.row-active { background: #f0fdf4; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
.badge-active { background: #dcfce7; color: #15803d; }
.badge-inactive { background: #f1f5f9; color: #64748b; }
.badge-info { background: #e0f2fe; color: #0369a1; }
.badge-framework { background: #f1f5f9; color: #334155; text-transform: uppercase; font-size: 0.7rem; border-radius: 4px; padding: 2px 6px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
.status-dot.pulse { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); animation: pulse-ring 1.8s infinite; }
@keyframes pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); } 70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); } }
.actions-group { display: flex; gap: 6px; justify-content: flex-end; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; font-size: 0.875rem; font-weight: 500; border-radius: 6px; border: none; cursor: pointer; transition: all 0.2s; }
.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }
.btn-warning { background: #fef3c7; color: #b45309; border: 1px solid #fde68a; }
.btn-warning:hover { background: #fde68a; }
.btn-secondary { background: #f1f5f9; color: #475569; }
.btn-secondary:hover { background: #e2e8f0; }
.btn-sm { padding: 5px 10px; font-size: 0.75rem; }
.btn-outline-primary { background: white; border: 1px solid #bfdbfe; color: #2563eb; }
.btn-outline-primary:hover { background: #eff6ff; }
.btn-outline-secondary { background: white; border: 1px solid #e2e8f0; color: #64748b; }
.btn-outline-secondary:hover { background: #f8fafc; }
.btn-outline-danger { background: white; border: 1px solid #fecaca; color: #dc2626; }
.btn-outline-danger:hover { background: #fef2f2; }
.btn-text { background: none; border: none; color: #2563eb; text-decoration: underline; cursor: pointer; padding: 0; font-size: 0.85rem; }
.alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; font-size: 0.875rem; }
.alert-success { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
.alert-danger { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 999; padding: 16px; }
.modal-content { background: white; border-radius: 12px; width: 100%; max-width: 580px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1); overflow: hidden; }
.modal-sm { max-width: 440px; }
.modal-header { padding: 18px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; }
.modal-title { font-size: 1.15rem; font-weight: 600; color: #1e293b; margin: 0; }
.btn-close { background: none; border: none; font-size: 1.5rem; color: #94a3b8; cursor: pointer; line-height: 1; }
.modal-body { padding: 24px; }
.form-group { margin-bottom: 16px; }
.form-row { display: flex; gap: 16px; }
.flex-1 { flex: 1; }
.form-label { display: block; font-size: 0.825rem; font-weight: 600; color: #334155; margin-bottom: 6px; }
.form-input, .form-textarea { width: 100%; padding: 10px 14px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.875rem; box-sizing: border-box; }
.form-input:focus, .form-textarea:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15); }
.form-file-input { width: 100%; font-size: 0.875rem; color: #475569; }
.form-hint { display: block; font-size: 0.75rem; color: #94a3b8; margin-top: 4px; }
.modal-footer { padding: 16px 24px; background: #f8fafc; display: flex; justify-content: flex-end; gap: 12px; border-top: 1px solid #f1f5f9; }
.classes-badges { display: flex; flex-wrap: wrap; gap: 8px; max-height: 280px; overflow-y: auto; }
.class-pill { display: inline-flex; align-items: center; gap: 6px; background: #f1f5f9; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 500; color: #334155; }
.class-idx { font-size: 0.7rem; color: #64748b; background: #e2e8f0; padding: 1px 5px; border-radius: 4px; }
.table-loading, .empty-state { padding: 48px 24px; text-align: center; color: #64748b; font-size: 0.875rem; }
.spinner { width: 28px; height: 28px; border: 3px solid #e2e8f0; border-top-color: #2563eb; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
.spinner-sm { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>

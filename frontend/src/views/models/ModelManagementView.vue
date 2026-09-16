<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

// Active tab: 'models' | 'endpoints'
const activeTab = ref('models')

// Models state
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

// Edit Model state
const showEditModelModal = ref(false)
const editModelLoading = ref(false)
const editModelForm = ref({
  id: null,
  name: '',
  version: '',
  task_type: 'detection',
  framework: 'yolo',
  description: ''
})

// Classes modal
const selectedClasses = ref([])
const showClassesModal = ref(false)
const selectedModelName = ref('')

// Endpoints state
const endpoints = ref([])
const isLoadingEndpoints = ref(false)
const showCreateEndpointModal = ref(false)
const showEditEndpointModal = ref(false)
const showSwitchModelModal = ref(false)
const showCurlModal = ref(false)
const endpointFormLoading = ref(false)

const selectedEndpoint = ref(null)
const switchTargetModelId = ref(null)
const selectedCurlEndpoint = ref(null)
const curlTab = ref('curl_file')
const copiedCode = ref(false)

const endpointForm = ref({
  id: null,
  name: '',
  slug: '',
  description: '',
  model_id: null,
  default_conf: 0.25,
  default_iou: 0.45,
  is_active: true
})

// ==========================================
// Models Actions
// ==========================================

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

const openEditModelModal = (model) => {
  editModelForm.value = {
    id: model.id,
    name: model.name,
    version: model.version,
    task_type: model.task_type || 'detection',
    framework: model.framework || 'yolo',
    description: model.description || ''
  }
  showEditModelModal.value = true
}

const submitEditModel = async () => {
  if (!editModelForm.value.name || !editModelForm.value.version) {
    alert('Nama model dan versi wajib diisi!')
    return
  }
  editModelLoading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${editModelForm.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editModelForm.value.name,
        version: editModelForm.value.version,
        task_type: editModelForm.value.task_type,
        framework: editModelForm.value.framework,
        description: editModelForm.value.description
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Model berhasil diperbarui.'
      showEditModelModal.value = false
      await fetchModels()
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal memperbarui model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend error saat edit model.'
  } finally {
    editModelLoading.value = false
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

const handleDelete = async (model) => {
  if (model.is_active && models.value.length === 1) {
    alert('Model ini adalah satu-satunya model aktif. Silakan unggah model pengganti terlebih dahulu sebelum menghapus.')
    return
  }
  const promptText = model.is_active
    ? `PERHATIAN: Model "${model.name} (${model.version})" sedang aktif melayani!\nSistem akan otomatis mengaktifkan model lain. Apakah Anda yakin ingin menghapus?`
    : `Apakah Anda yakin ingin menghapus model "${model.name} (${model.version})"? File bobot dan evaluasi akan dihapus permanen.`

  if (!confirm(promptText)) return

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/${model.id}?force=true`, {
      method: 'DELETE'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || `Model ${model.name} berhasil dihapus.`
      await fetchModels()
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal menghapus model.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend error saat menghapus model.'
  } finally {
    setTimeout(() => { successMessage.value = '' }, 4000)
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
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

// ==========================================
// Serving Endpoints Actions (API Hub)
// ==========================================

const fetchEndpoints = async () => {
  isLoadingEndpoints.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints`)
    const data = await res.json()
    if (res.ok) {
      endpoints.value = data.endpoints || []
    }
  } catch (err) {
    console.error('Failed to fetch endpoints:', err)
  } finally {
    isLoadingEndpoints.value = false
  }
}

const openCreateEndpointModal = () => {
  endpointForm.value = {
    id: null,
    name: '',
    slug: '',
    description: '',
    model_id: activeModel.value ? activeModel.value.id : (models.value[0]?.id || null),
    default_conf: 0.25,
    default_iou: 0.45,
    is_active: true
  }
  showCreateEndpointModal.value = true
}

const onEndpointNameChange = () => {
  if (!endpointForm.value.id && endpointForm.value.name) {
    endpointForm.value.slug = endpointForm.value.name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
  }
}

const submitCreateEndpoint = async () => {
  if (!endpointForm.value.name) {
    alert('Nama endpoint wajib diisi!')
    return
  }
  endpointFormLoading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: endpointForm.value.name,
        slug: endpointForm.value.slug || undefined,
        description: endpointForm.value.description || undefined,
        model_id: endpointForm.value.model_id,
        default_conf: parseFloat(endpointForm.value.default_conf),
        default_iou: parseFloat(endpointForm.value.default_iou),
        is_active: endpointForm.value.is_active
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Endpoint berhasil dibuat!'
      showCreateEndpointModal.value = false
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal membuat endpoint.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi error saat membuat endpoint.'
  } finally {
    endpointFormLoading.value = false
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

const openEditEndpointModal = (ep) => {
  endpointForm.value = {
    id: ep.id,
    name: ep.name,
    slug: ep.slug,
    description: ep.description || '',
    model_id: ep.model_id,
    default_conf: ep.default_conf ?? 0.25,
    default_iou: ep.default_iou ?? 0.45,
    is_active: ep.is_active
  }
  showEditEndpointModal.value = true
}

const submitEditEndpoint = async () => {
  if (!endpointForm.value.name) {
    alert('Nama endpoint wajib diisi!')
    return
  }
  endpointFormLoading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints/${endpointForm.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: endpointForm.value.name,
        slug: endpointForm.value.slug,
        description: endpointForm.value.description,
        model_id: endpointForm.value.model_id,
        default_conf: parseFloat(endpointForm.value.default_conf),
        default_iou: parseFloat(endpointForm.value.default_iou),
        is_active: endpointForm.value.is_active
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Endpoint berhasil diperbarui.'
      showEditEndpointModal.value = false
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal memperbarui endpoint.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi error saat memperbarui endpoint.'
  } finally {
    endpointFormLoading.value = false
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

const toggleEndpointActive = async (ep) => {
  try {
    const newStatus = !ep.is_active
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints/${ep.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: newStatus })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      ep.is_active = newStatus
      successMessage.value = `Endpoint '${ep.name}' sekarang ${newStatus ? 'AKTIF' : 'NONAKTIF'}.`
    }
  } catch (err) {
    console.error('Failed to toggle status:', err)
  } finally {
    setTimeout(() => { successMessage.value = '' }, 3000)
  }
}

// Model Switch Modal
const openSwitchModelModal = (ep) => {
  selectedEndpoint.value = ep
  switchTargetModelId.value = ep.model_id || (models.value[0]?.id || null)
  showSwitchModelModal.value = true
}

const submitSwitchModel = async () => {
  if (!switchTargetModelId.value) {
    alert('Pilih model target!')
    return
  }
  endpointFormLoading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints/${selectedEndpoint.value.id}/switch-model`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: switchTargetModelId.value })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Model berhasil dialihkan!'
      showSwitchModelModal.value = false
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal mengalihkan model endpoint.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend error saat switch model.'
  } finally {
    endpointFormLoading.value = false
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

const handleDeleteEndpoint = async (ep) => {
  if (!confirm(`Hapus serving endpoint "${ep.name}" (${ep.slug})?\nAplikasi luar yang memanggil endpoint ini tidak akan dapat mengaksesnya lagi.`)) return

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/endpoints/${ep.id}`, {
      method: 'DELETE'
    })
    const data = await res.json()
    if (res.ok && data.success) {
      successMessage.value = data.message || 'Endpoint berhasil dihapus.'
      await fetchEndpoints()
    } else {
      errorMessage.value = data.detail || 'Gagal menghapus endpoint.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi backend error.'
  } finally {
    setTimeout(() => { successMessage.value = '' }, 4000)
  }
}

// cURL Snippet Modal
const openCurlModal = (ep) => {
  selectedCurlEndpoint.value = ep
  showCurlModal.value = true
}

const copyToClipboard = (text) => {
  navigator.clipboard.writeText(text)
  copiedCode.value = true
  setTimeout(() => { copiedCode.value = false }, 2500)
}

const getFullEndpointUrl = (slug) => {
  return `${window.location.origin}${API_BASE_URL}/api/v1/models/endpoints/${slug}/predict`
}

const getFullEndpointVideoUrl = (slug) => {
  return `${window.location.origin}${API_BASE_URL}/api/v1/models/endpoints/${slug}/predict-video`
}

onMounted(() => {
  fetchModels()
  fetchEndpoints()
})
</script>

<template>
  <div class="models-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">ML Models & Serving Registry</h1>
        <p class="page-subtitle">
          Kelola versi model Object Detection (YOLO .pt & ONNX), buat Custom Serving Endpoints independen, dan ganti atau rollback model aktif secara instan tanpa downtime.
        </p>
      </div>
      <div class="header-actions">
        <button class="btn btn-warning" @click="handleRollback" :disabled="isActivating || models.length < 2">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M1 4v6h6"></path><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>
          Rollback Model
        </button>
        <button class="btn btn-secondary" @click="() => { fetchModels(); fetchEndpoints(); }" :disabled="isLoading">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
          Refresh
        </button>
        <button v-if="activeTab === 'models'" class="btn btn-primary" @click="showUploadModal = true">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          Upload Model (.pt / .onnx)
        </button>
        <button v-else class="btn btn-primary" @click="openCreateEndpointModal">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          + Buat Serving Endpoint
        </button>
      </div>
    </div>

    <!-- Sub-Tabs Switcher -->
    <div class="tabs-nav">
      <button 
        class="tab-item" 
        :class="{ active: activeTab === 'models' }" 
        @click="activeTab = 'models'"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
        <span>Model Registry (Weights & Training)</span>
        <span class="tab-badge">{{ models.length }}</span>
      </button>
      <button 
        class="tab-item" 
        :class="{ active: activeTab === 'endpoints' }" 
        @click="activeTab = 'endpoints'"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
        <span>Serving Endpoints (API Hub & Model Switcher)</span>
        <span class="tab-badge text-primary">{{ endpoints.length }}</span>
      </button>
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

    <!-- ============================================================== -->
    <!-- TAB 1: MODEL REGISTRY                                         -->
    <!-- ============================================================== -->
    <div v-if="activeTab === 'models'">
      <!-- Stats Summary Cards -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Total Model Terdaftar</div>
          <div class="stat-val">{{ models.length }}</div>
          <div class="stat-desc">Versi tersimpan di registry</div>
        </div>
        <div class="stat-card highlight">
          <div class="stat-label">Model Aktif (Global Default)</div>
          <div class="stat-val text-primary">{{ activeModel ? activeModel.name : 'None' }}</div>
          <div class="stat-desc font-mono">{{ activeModel ? activeModel.version : '-' }} ({{ activeModel ? activeModel.framework : '-' }})</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Jumlah Kelas Terdeteksi</div>
          <div class="stat-val">{{ activeModel ? activeModel.classes_count : 0 }}</div>
          <div class="stat-desc">Kategori objek model aktif</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Default Serving Endpoint</div>
          <div class="stat-val text-success">ONLINE</div>
          <div class="stat-desc">POST /api/v1/models/predict</div>
        </div>
      </div>

      <!-- Models Table Card -->
      <div class="card table-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">Daftar Versi Model</h2>
            <p class="card-desc-sub">Semua weights (.pt / .onnx) yang terdaftar. Anda bisa mengedit nama/deskripsi, mengaktifkan, atau menghapus model.</p>
          </div>
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
                  <div class="text-xs text-slate-500 line-clamp-1">{{ m.description || 'Tidak ada deskripsi' }}</div>
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
                      title="Jadikan model aktif utama untuk API global"
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
                      title="Lihat Confusion Matrix & Kurva Metrik"
                    >
                      Evaluasi
                    </button>
                    <button 
                      class="btn btn-sm btn-outline-secondary" 
                      @click="openEditModelModal(m)"
                      title="Edit Nama, Versi, & Deskripsi Model"
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                      Edit
                    </button>
                    <button 
                      class="btn btn-sm btn-outline-danger" 
                      @click="handleDelete(m)"
                      title="Hapus Model dari Registry"
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                      Hapus
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- TAB 2: SERVING ENDPOINTS (API HUB & MODEL SWITCHER)           -->
    <!-- ============================================================== -->
    <div v-else-if="activeTab === 'endpoints'">
      <!-- Stats Summary Cards -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Total Serving Endpoints</div>
          <div class="stat-val text-primary">{{ endpoints.length }}</div>
          <div class="stat-desc">Endpoint API aktif terdaftar</div>
        </div>
        <div class="stat-card highlight">
          <div class="stat-label">Model Terpasang di Endpoints</div>
          <div class="stat-val text-indigo-600">{{ new Set(endpoints.map(e => e.model_id).filter(Boolean)).size }}</div>
          <div class="stat-desc">Model unik yang sedang melayani traffic</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Permintaan Prediksi</div>
          <div class="stat-val text-emerald-600">
            {{ endpoints.reduce((acc, e) => acc + (e.total_requests || 0), 0) }}
          </div>
          <div class="stat-desc">Akumulasi request via endpoints</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Status Gateway API</div>
          <div class="stat-val text-success">READY</div>
          <div class="stat-desc">Multi-Model Hot-Swap Support</div>
        </div>
      </div>

      <!-- Endpoints Table Card -->
      <div class="card table-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">Daftar Custom Serving Endpoints</h2>
            <p class="card-desc-sub">
              Setiap endpoint memiliki URL permanen. Anda dapat mengalihkan (switch) model lama ke model baru kapan saja tanpa mengubah URL di aplikasi klien.
            </p>
          </div>
          <button class="btn btn-sm btn-primary" @click="openCreateEndpointModal">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            Tambah Endpoint Baru
          </button>
        </div>

        <div v-if="isLoadingEndpoints" class="table-loading">
          <div class="spinner"></div>
          <span>Memuat data endpoints...</span>
        </div>

        <div v-else-if="endpoints.length === 0" class="empty-state">
          <svg viewBox="0 0 24 24" width="48" height="48" stroke="#94a3b8" stroke-width="1.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
          <p>Belum ada custom serving endpoint. Buat endpoint baru untuk memisahkan service deteksi (misal APD, Api, Kendaraan, atau QC Defect).</p>
          <button class="btn btn-primary mt-3" @click="openCreateEndpointModal">+ Buat Endpoint Pertama</button>
        </div>

        <div v-else class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Nama Endpoint & Path</th>
                <th>Model yang Melayani (Terkoneksi)</th>
                <th>Threshold Default</th>
                <th>Total Traffic</th>
                <th>Terakhir Diakses</th>
                <th class="text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ep in endpoints" :key="ep.id" :class="{ 'row-inactive-opacity': !ep.is_active }">
                <td>
                  <button 
                    class="status-toggle-btn" 
                    :class="ep.is_active ? 'toggle-active' : 'toggle-inactive'"
                    @click="toggleEndpointActive(ep)"
                    :title="ep.is_active ? 'Klik untuk nonaktifkan' : 'Klik untuk aktifkan'"
                  >
                    <span class="status-dot" :class="{ pulse: ep.is_active }"></span>
                    {{ ep.is_active ? 'ONLINE' : 'OFFLINE' }}
                  </button>
                </td>
                <td>
                  <div class="font-semibold text-slate-800">{{ ep.name }}</div>
                  <div class="text-xs font-mono text-blue-600 bg-blue-50 px-2 py-0.5 rounded inline-block mt-0.5">
                    POST {{ ep.predict_url }}
                  </div>
                  <div class="text-xs text-slate-500 mt-1 line-clamp-1">{{ ep.description || 'Tidak ada catatan' }}</div>
                </td>
                <td>
                  <!-- Connected Model Card -->
                  <div class="connected-model-badge">
                    <div class="model-info-block">
                      <span class="model-name-text">{{ ep.model_name }}</span>
                      <span class="model-ver-pill">{{ ep.model_version }}</span>
                    </div>
                    <button 
                      class="btn btn-xs btn-switch-model" 
                      @click="openSwitchModelModal(ep)"
                      title="Ganti model yang melayani endpoint ini (Switch Model lama/baru)"
                    >
                      <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M7 16V4m0 0L3 8m4-4l4 4m6 4v12m0 0l4-4m-4 4l-4-4"></path></svg>
                      Switch Model
                    </button>
                  </div>
                </td>
                <td>
                  <div class="text-xs font-mono text-slate-700">Conf: {{ (ep.default_conf * 100).toFixed(0) }}%</div>
                  <div class="text-xs font-mono text-slate-500">IoU: {{ (ep.default_iou * 100).toFixed(0) }}%</div>
                </td>
                <td>
                  <span class="font-mono text-sm font-semibold text-slate-800">{{ ep.total_requests || 0 }}</span>
                  <span class="text-xs text-slate-400 block">requests</span>
                </td>
                <td class="text-xs text-slate-500">
                  {{ ep.last_accessed_at ? new Date(ep.last_accessed_at).toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'short' }) : 'Belum pernah' }}
                </td>
                <td class="text-right">
                  <div class="actions-group">
                    <button 
                      class="btn btn-sm btn-outline-primary" 
                      @click="openCurlModal(ep)"
                      title="Lihat cURL & Dokumentasi API"
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
                      API / cURL
                    </button>
                    <button 
                      class="btn btn-sm btn-outline-secondary" 
                      @click="router.push(`/models/playground?endpoint=${ep.slug}`)"
                      title="Coba deteksi langsung di Playground"
                    >
                      Playground
                    </button>
                    <button 
                      class="btn btn-sm btn-outline-secondary" 
                      @click="openEditEndpointModal(ep)"
                      title="Edit Nama / Konfigurasi Endpoint"
                    >
                      Edit
                    </button>
                    <button 
                      class="btn btn-sm btn-outline-danger" 
                      @click="handleDeleteEndpoint(ep)"
                      title="Hapus Endpoint"
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
    </div>

    <!-- ============================================================== -->
    <!-- MODALS SECTION                                                 -->
    <!-- ============================================================== -->

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
            <span class="form-hint">Jika model utama adalah .pt, Anda dapat menyertakan file .onnx untuk akselerasi serving di CPU.</span>
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

    <!-- Edit Model Modal -->
    <div v-if="showEditModelModal" class="modal-overlay" @click.self="showEditModelModal = false">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3 class="modal-title">Edit Metadata Model</h3>
          <button class="btn-close" @click="showEditModelModal = false">&times;</button>
        </div>
        <form @submit.prevent="submitEditModel" class="modal-body">
          <div class="form-group">
            <label class="form-label">Nama Model *</label>
            <input 
              v-model="editModelForm.name" 
              type="text" 
              class="form-input" 
              required 
            />
          </div>

          <div class="form-row">
            <div class="form-group flex-1">
              <label class="form-label">Versi *</label>
              <input 
                v-model="editModelForm.version" 
                type="text" 
                class="form-input" 
                required 
              />
            </div>
            <div class="form-group flex-1">
              <label class="form-label">Framework</label>
              <select v-model="editModelForm.framework" class="form-input">
                <option value="yolo">YOLO (.pt)</option>
                <option value="onnx">ONNX (.onnx)</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Deskripsi Model</label>
            <textarea 
              v-model="editModelForm.description" 
              class="form-textarea" 
              rows="3" 
              placeholder="Deskripsi peruntukan model..."
            ></textarea>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="showEditModelModal = false">Batal</button>
            <button type="submit" class="btn btn-primary" :disabled="editModelLoading">
              <span v-if="editModelLoading" class="spinner-sm"></span>
              {{ editModelLoading ? 'Menyimpan...' : 'Simpan Perubahan' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Create / Edit Serving Endpoint Modal -->
    <div v-if="showCreateEndpointModal || showEditEndpointModal" class="modal-overlay" @click.self="() => { showCreateEndpointModal = false; showEditEndpointModal = false; }">
      <div class="modal-content">
        <div class="modal-header">
          <h3 class="modal-title">
            {{ showCreateEndpointModal ? 'Buat Custom Serving Endpoint' : 'Edit Serving Endpoint' }}
          </h3>
          <button class="btn-close" @click="() => { showCreateEndpointModal = false; showEditEndpointModal = false; }">&times;</button>
        </div>
        <form @submit.prevent="showCreateEndpointModal ? submitCreateEndpoint() : submitEditEndpoint()" class="modal-body">
          <div class="form-group">
            <label class="form-label">Nama Endpoint *</label>
            <input 
              v-model="endpointForm.name" 
              type="text" 
              class="form-input" 
              placeholder="Contoh: CCTV APD Gate 1 API" 
              @input="onEndpointNameChange"
              required 
            />
          </div>

          <div class="form-group">
            <label class="form-label">URL Slug *</label>
            <div class="slug-input-wrapper">
              <span class="slug-prefix">/api/v1/models/endpoints/</span>
              <input 
                v-model="endpointForm.slug" 
                type="text" 
                class="form-input slug-input" 
                placeholder="cctv-apd-gate-1" 
                required 
              />
              <span class="slug-suffix">/predict</span>
            </div>
            <span class="form-hint">Slug URL unik yang akan dipanggil oleh sistem luar.</span>
          </div>

          <div class="form-group">
            <label class="form-label">Model Terhubung (Target Model) *</label>
            <select v-model="endpointForm.model_id" class="form-input" required>
              <option :value="null" disabled>Pilih model yang akan melayani endpoint ini...</option>
              <option v-for="m in models" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.version }}) - [{{ m.framework }}] {{ m.is_active ? '★ Global Active' : '' }}
              </option>
            </select>
            <span class="form-hint">Model ini akan otomatis dieksekusi saat ada request inferensi ke endpoint ini.</span>
          </div>

          <div class="form-row">
            <div class="form-group flex-1">
              <label class="form-label">Default Confidence Threshold</label>
              <input 
                v-model="endpointForm.default_conf" 
                type="number" 
                step="0.05" 
                min="0.05" 
                max="1.0" 
                class="form-input" 
              />
              <span class="form-hint">Standar: 0.25</span>
            </div>
            <div class="form-group flex-1">
              <label class="form-label">Default IoU / NMS Threshold</label>
              <input 
                v-model="endpointForm.default_iou" 
                type="number" 
                step="0.05" 
                min="0.10" 
                max="0.90" 
                class="form-input" 
              />
              <span class="form-hint">Standar: 0.45</span>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Deskripsi Endpoint</label>
            <textarea 
              v-model="endpointForm.description" 
              class="form-textarea" 
              rows="2" 
              placeholder="Contoh: Digunakan untuk streaming CCTV pos satpam memverifikasi rompi dan helm..."
            ></textarea>
          </div>

          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="endpointForm.is_active" />
              <span>Aktifkan endpoint ini segera setelah disimpan</span>
            </label>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="() => { showCreateEndpointModal = false; showEditEndpointModal = false; }">Batal</button>
            <button type="submit" class="btn btn-primary" :disabled="endpointFormLoading">
              <span v-if="endpointFormLoading" class="spinner-sm"></span>
              {{ endpointFormLoading ? 'Menyimpan...' : (showCreateEndpointModal ? 'Buat Endpoint' : 'Simpan Perubahan') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Switch Model Modal -->
    <div v-if="showSwitchModelModal && selectedEndpoint" class="modal-overlay" @click.self="showSwitchModelModal = false">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3 class="modal-title">Switch Model: {{ selectedEndpoint.name }}</h3>
          <button class="btn-close" @click="showSwitchModelModal = false">&times;</button>
        </div>
        <form @submit.prevent="submitSwitchModel" class="modal-body">
          <div class="alert alert-info">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
            <div>
              <strong>Instant Hot-Swap:</strong> Klien luar yang memanggil endpoint <code>{{ selectedEndpoint.slug }}</code> akan langsung dialihkan ke model baru tanpa perlu merubah endpoint URL atau me-restart server!
            </div>
          </div>

          <div class="current-model-box">
            <div class="text-xs text-slate-500 font-semibold mb-1">MODEL SAAT INI:</div>
            <div class="text-sm font-bold text-slate-800">{{ selectedEndpoint.model_name }} ({{ selectedEndpoint.model_version }})</div>
          </div>

          <div class="form-group mt-4">
            <label class="form-label">Pilih Model Pengganti (Model Baru / Alternatif) *</label>
            <select v-model="switchTargetModelId" class="form-input" required>
              <option v-for="m in models" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.version }}) - [{{ m.framework }}] {{ m.id === selectedEndpoint.model_id ? '(Sedang Digunakan)' : '' }}
              </option>
            </select>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="showSwitchModelModal = false">Batal</button>
            <button type="submit" class="btn btn-primary" :disabled="endpointFormLoading || switchTargetModelId === selectedEndpoint.model_id">
              <span v-if="endpointFormLoading" class="spinner-sm"></span>
              {{ endpointFormLoading ? 'Mengalihkan...' : 'Alihkan Model Sekarang' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- cURL / API Documentation Modal -->
    <div v-if="showCurlModal && selectedCurlEndpoint" class="modal-overlay" @click.self="showCurlModal = false">
      <div class="modal-content modal-lg">
        <div class="modal-header">
          <div>
            <h3 class="modal-title">API Endpoint: {{ selectedCurlEndpoint.name }}</h3>
            <span class="font-mono text-xs text-slate-500">Slug: {{ selectedCurlEndpoint.slug }}</span>
          </div>
          <button class="btn-close" @click="showCurlModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="url-display-box">
            <span class="http-badge">POST</span>
            <input 
              readonly 
              :value="getFullEndpointUrl(selectedCurlEndpoint.slug)" 
              class="url-input" 
            />
            <button class="btn btn-sm btn-primary" @click="copyToClipboard(getFullEndpointUrl(selectedCurlEndpoint.slug))">
              {{ copiedCode ? 'Tersalin!' : 'Copy URL' }}
            </button>
          </div>

          <div class="curl-tabs">
            <button 
              class="curl-tab-btn" 
              :class="{ active: curlTab === 'curl_file' }" 
              @click="curlTab = 'curl_file'"
            >
              cURL (Upload File)
            </button>
            <button 
              class="curl-tab-btn" 
              :class="{ active: curlTab === 'curl_url' }" 
              @click="curlTab = 'curl_url'"
            >
              cURL (Image URL)
            </button>
            <button 
              class="curl-tab-btn" 
              :class="{ active: curlTab === 'python' }" 
              @click="curlTab = 'python'"
            >
              Python Requests
            </button>
            <button 
              class="curl-tab-btn" 
              :class="{ active: curlTab === 'video' }" 
              @click="curlTab = 'video'"
            >
              Video Stream API
            </button>
          </div>

          <div class="code-container">
            <pre v-if="curlTab === 'curl_file'" class="code-block"><code>curl -X POST "{{ getFullEndpointUrl(selectedCurlEndpoint.slug) }}" \
  -F "file=@/path/to/gambar.jpg" \
  -F "conf_threshold={{ selectedCurlEndpoint.default_conf }}" \
  -F "iou_threshold={{ selectedCurlEndpoint.default_iou }}"</code></pre>

            <pre v-else-if="curlTab === 'curl_url'" class="code-block"><code>curl -X POST "{{ getFullEndpointUrl(selectedCurlEndpoint.slug) }}" \
  -F "image_url=https://domain.com/photo.jpg" \
  -F "conf_threshold={{ selectedCurlEndpoint.default_conf }}"</code></pre>

            <pre v-else-if="curlTab === 'python'" class="code-block"><code>import requests

url = "{{ getFullEndpointUrl(selectedCurlEndpoint.slug) }}"
with open("test.jpg", "rb") as f:
    files = {"file": f}
    data = {"conf_threshold": {{ selectedCurlEndpoint.default_conf }}}
    response = requests.post(url, files=files, data=data)
    result = response.json()
    print("Detections:", result["detections"])
    print("Annotated URL:", result["annotated_image_url"])</code></pre>

            <pre v-else-if="curlTab === 'video'" class="code-block"><code>curl -X POST "{{ getFullEndpointVideoUrl(selectedCurlEndpoint.slug) }}" \
  -F "video=@/path/to/cctv_clip.mp4" \
  -F "conf_threshold={{ selectedCurlEndpoint.default_conf }}"</code></pre>
          </div>

          <div class="endpoint-meta-grid">
            <div class="meta-item">
              <span class="meta-label">Model Aktif Endpoint:</span>
              <span class="meta-val font-semibold">{{ selectedCurlEndpoint.model_name }} ({{ selectedCurlEndpoint.model_version }})</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Output:</span>
              <span class="meta-val">Bounding boxes JSON + Annotated JPG di S3</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Format Media:</span>
              <span class="meta-val">JPG, PNG, WebP (Image) & MP4, AVI, MOV (Video)</span>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showCurlModal = false">Tutup</button>
          <button class="btn btn-primary" @click="router.push(`/models/playground?endpoint=${selectedCurlEndpoint.slug}`)">
            Uji Langsung di Playground
          </button>
        </div>
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
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-title { font-size: 1.5rem; font-weight: 700; color: #0f172a; margin: 0 0 6px 0; }
.page-subtitle { font-size: 0.875rem; color: #64748b; margin: 0; max-width: 650px; line-height: 1.5; }
.header-actions { display: flex; gap: 12px; }

/* Sub-Tabs Navigation */
.tabs-nav { display: flex; gap: 8px; border-bottom: 2px solid #e2e8f0; margin-bottom: 24px; }
.tab-item { display: flex; align-items: center; gap: 8px; padding: 12px 18px; font-size: 0.9rem; font-weight: 600; color: #64748b; background: none; border: none; border-bottom: 2px solid transparent; margin-bottom: -2px; cursor: pointer; transition: all 0.2s; }
.tab-item:hover { color: #1e293b; }
.tab-item.active { color: #2563eb; border-bottom-color: #2563eb; }
.tab-badge { background: #f1f5f9; padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; }
.tab-item.active .tab-badge { background: #dbeafe; color: #1d4ed8; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: white; border-radius: 10px; padding: 16px 20px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
.stat-card.highlight { border-color: #cbd5e1; background: linear-gradient(to bottom right, #ffffff, #f8fafc); }
.stat-label { font-size: 0.8rem; color: #64748b; font-weight: 500; margin-bottom: 6px; }
.stat-val { font-size: 1.45rem; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.stat-desc { font-size: 0.75rem; color: #94a3b8; }
.text-primary { color: #2563eb; }
.text-success { color: #16a34a; }
.text-indigo-600 { color: #4f46e5; }
.text-emerald-600 { color: #059669; }

.card { background: white; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.02); overflow: hidden; }
.card-header { padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; }
.card-title { font-size: 1.1rem; font-weight: 600; color: #1e293b; margin: 0; }
.card-desc-sub { font-size: 0.8rem; color: #64748b; margin: 4px 0 0 0; }

.table-responsive { width: 100%; overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; text-align: left; }
.data-table th { background: #f8fafc; padding: 12px 18px; font-size: 0.75rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #e2e8f0; }
.data-table td { padding: 14px 18px; border-bottom: 1px solid #f1f5f9; font-size: 0.875rem; vertical-align: middle; }
.row-active { background: #f0fdf4; }
.row-inactive-opacity { opacity: 0.7; }

.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
.badge-active { background: #dcfce7; color: #15803d; }
.badge-inactive { background: #f1f5f9; color: #64748b; }
.badge-info { background: #e0f2fe; color: #0369a1; }
.badge-framework { background: #f1f5f9; color: #334155; text-transform: uppercase; font-size: 0.7rem; border-radius: 4px; padding: 2px 6px; font-weight: 600; }

.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
.status-dot.pulse { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); animation: pulse-ring 1.8s infinite; }
@keyframes pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); } 70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); } }

/* Connected model badge with switch button */
.connected-model-badge { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: #f8fafc; border: 1px solid #e2e8f0; padding: 6px 10px; border-radius: 8px; min-width: 220px; }
.model-info-block { display: flex; flex-direction: column; }
.model-name-text { font-size: 0.85rem; font-weight: 600; color: #1e293b; }
.model-ver-pill { font-size: 0.7rem; font-family: monospace; color: #64748b; }
.btn-switch-model { background: #eff6ff; border: 1px solid #bfdbfe; color: #1d4ed8; font-size: 0.7rem; font-weight: 600; padding: 4px 8px; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.btn-switch-model:hover { background: #dbeafe; }

/* Status toggle button */
.status-toggle-btn { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; border: none; cursor: pointer; transition: all 0.2s; }
.toggle-active { background: #dcfce7; color: #15803d; }
.toggle-inactive { background: #fee2e2; color: #b91c1c; }
.toggle-inactive .status-dot { background: #ef4444; }

.actions-group { display: flex; gap: 6px; justify-content: flex-end; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; font-size: 0.875rem; font-weight: 500; border-radius: 6px; border: none; cursor: pointer; transition: all 0.2s; }
.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }
.btn-warning { background: #fef3c7; color: #b45309; border: 1px solid #fde68a; }
.btn-warning:hover { background: #fde68a; }
.btn-secondary { background: #f1f5f9; color: #475569; }
.btn-secondary:hover { background: #e2e8f0; }
.btn-sm { padding: 5px 10px; font-size: 0.75rem; }
.btn-xs { padding: 3px 6px; font-size: 0.7rem; }
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
.alert-info { background: #eff6ff; color: #1d4ed8; border: 1px solid #dbeafe; }

.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 999; padding: 16px; }
.modal-content { background: white; border-radius: 12px; width: 100%; max-width: 580px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1); overflow: hidden; max-height: 90vh; display: flex; flex-direction: column; }
.modal-sm { max-width: 440px; }
.modal-lg { max-width: 680px; }
.modal-header { padding: 18px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; }
.modal-title { font-size: 1.15rem; font-weight: 600; color: #1e293b; margin: 0; }
.btn-close { background: none; border: none; font-size: 1.5rem; color: #94a3b8; cursor: pointer; line-height: 1; }
.modal-body { padding: 24px; overflow-y: auto; }
.form-group { margin-bottom: 16px; }
.form-row { display: flex; gap: 16px; }
.flex-1 { flex: 1; }
.form-label { display: block; font-size: 0.825rem; font-weight: 600; color: #334155; margin-bottom: 6px; }
.form-input, .form-textarea { width: 100%; padding: 10px 14px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.875rem; box-sizing: border-box; }
.form-input:focus, .form-textarea:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15); }
.form-file-input { width: 100%; font-size: 0.875rem; color: #475569; }
.form-hint { display: block; font-size: 0.75rem; color: #94a3b8; margin-top: 4px; }
.checkbox-label { display: flex; align-items: center; gap: 8px; font-size: 0.875rem; color: #334155; cursor: pointer; }
.modal-footer { padding: 16px 24px; background: #f8fafc; display: flex; justify-content: flex-end; gap: 12px; border-top: 1px solid #f1f5f9; }

/* Slug input styling */
.slug-input-wrapper { display: flex; align-items: center; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; background: #f8fafc; }
.slug-prefix, .slug-suffix { padding: 10px 10px; font-size: 0.8rem; font-family: monospace; color: #64748b; white-space: nowrap; }
.slug-input { border: none !important; box-shadow: none !important; border-radius: 0 !important; background: white; font-family: monospace; font-weight: 600; color: #1e293b; padding: 10px 6px; }

/* Current model box */
.current-model-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; }

/* URL display & cURL Modal */
.url-display-box { display: flex; align-items: center; gap: 8px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 8px; margin-bottom: 16px; }
.http-badge { background: #16a34a; color: white; font-size: 0.7rem; font-weight: 700; padding: 3px 6px; border-radius: 4px; font-family: monospace; }
.url-input { flex: 1; border: none; background: transparent; font-family: monospace; font-size: 0.825rem; color: #1e293b; outline: none; }
.curl-tabs { display: flex; gap: 6px; border-bottom: 1px solid #e2e8f0; margin-bottom: 12px; }
.curl-tab-btn { background: none; border: none; padding: 6px 12px; font-size: 0.8rem; font-weight: 600; color: #64748b; border-bottom: 2px solid transparent; cursor: pointer; }
.curl-tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; }
.code-container { background: #0f172a; border-radius: 8px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.code-block { margin: 0; font-family: monospace; font-size: 0.8rem; color: #e2e8f0; line-height: 1.5; }
.endpoint-meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; }
.meta-item { display: flex; flex-direction: column; gap: 2px; }
.meta-label { font-size: 0.75rem; color: #64748b; }
.meta-val { font-size: 0.825rem; color: #1e293b; }

.classes-badges { display: flex; flex-wrap: wrap; gap: 8px; max-height: 280px; overflow-y: auto; }
.class-pill { display: inline-flex; align-items: center; gap: 6px; background: #f1f5f9; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 500; color: #334155; }
.class-idx { font-size: 0.7rem; color: #64748b; background: #e2e8f0; padding: 1px 5px; border-radius: 4px; }
.table-loading, .empty-state { padding: 48px 24px; text-align: center; color: #64748b; font-size: 0.875rem; }
.spinner { width: 28px; height: 28px; border: 3px solid #e2e8f0; border-top-color: #2563eb; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
.spinner-sm { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>

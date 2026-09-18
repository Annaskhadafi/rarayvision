<script setup>
import { ref, computed, onMounted } from 'vue'
import { API_BASE_URL } from '../../utils'

const datasetName = ref('')
const cocoJsonFile = ref(null)
const imagesZipFile = ref(null)
const targetProjectId = ref('')

const models = ref([])
const endpoints = ref([])
const selectedTargetModel = ref('')
const syncFilterModelId = ref('')
const syncFilterEndpointSlug = ref('')

const isImporting = ref(false)
const importResult = ref(null)
const errorMessage = ref('')
const copiedKey = ref('')
const activeTrainingTab = ref('yolo')

const colabModelMap = {
  yolo: {
    key: 'yolox',
    label: 'YOLO-X',
    githubUrl: 'https://colab.research.google.com/github/Annaskhadafi/rarayvision/blob/main/raray_vision_yolox_colab.ipynb',
    filename: 'raray_vision_yolox_colab.ipynb'
  },
  yolo26: {
    key: 'yolo26',
    label: 'YOLO-26',
    githubUrl: 'https://colab.research.google.com/github/Annaskhadafi/rarayvision/blob/main/raray_vision_yolo26_colab.ipynb',
    filename: 'raray_vision_yolo26_colab.ipynb'
  },
  rfdetr: {
    key: 'rfdetr',
    label: 'RF-DETR',
    githubUrl: 'https://colab.research.google.com/github/Annaskhadafi/rarayvision/blob/main/raray_vision_rfdetr_colab.ipynb',
    filename: 'raray_vision_rfdetr_colab.ipynb'
  }
}

// ─── Training Configuration State ──────────────────────────────────────────
// Mode: "local_cpu" | "local_gpu" | "colab"
const nbMode = ref('local_cpu')
// Base pretrained weights: empty = use model default
const nbWeights = ref('')
// Epochs: null = use model default
const nbEpochs = ref(null)
// Batch: null = use model default
const nbBatch = ref(null)
// Image size
const nbImgsz = ref(640)
// Optimizer: null = use model default
const nbOptimizer = ref(null)
// Learning rate: null = use model default
const nbLr = ref(null)
// Workers: null = use platform default
const nbWorkers = ref(null)
// Patience: null = use model default
const nbPatience = ref(null)
// Show advanced settings panel
const showAdvanced = ref(false)

const groupedWeightsOptions = computed(() => {
  if (activeTrainingTab.value === 'rfdetr') {
    return [
      {
        group: '🎯 RF-DETR / RT-DETR (Vision Transformer)',
        options: [
          { value: 'rtdetr-l.pt', label: 'RT-DETR Large (32M) — Default Transformer Real-Time' },
          { value: 'rtdetr-x.pt', label: 'RT-DETR XLarge (67M) — Akurasi Maksimal Transformer' }
        ]
      }
    ]
  }

  return [
    {
      group: '⚡ YOLO11 (Generasi Terbaru — Rekomendasi Utama)',
      options: [
        { value: 'yolo11n.pt', label: '⚡ YOLO11 Nano (2.6M params) — Paling Ringan, Rekomendasi CPU PC / Laptop' },
        { value: 'yolo11s.pt', label: '🚀 YOLO11 Small (9.4M params) — Cepat & Akurat, Cocok CPU / GPU' },
        { value: 'yolo11m.pt', label: '⚖️ YOLO11 Medium (20.1M params) — Seimbang Speed & Akurasi' },
        { value: 'yolo11l.pt', label: '🎯 YOLO11 Large (25.3M params) — Akurasi Tinggi' },
        { value: 'yolo11x.pt', label: '🏆 YOLO11 XLarge (56.9M params) — Akurasi Maksimal, Butuh GPU' }
      ]
    },
    {
      group: '📦 YOLOv8 (Klasik Stabil)',
      options: [
        { value: 'yolov8n.pt', label: '📦 YOLOv8 Nano (3.2M params) — Ringan Klasik' },
        { value: 'yolov8s.pt', label: '📦 YOLOv8 Small (11.2M params) — Standar Populer' },
        { value: 'yolov8m.pt', label: '📦 YOLOv8 Medium (25.9M params) — Menengah' },
        { value: 'yolov8l.pt', label: '📦 YOLOv8 Large (43.7M params) — Besar' },
        { value: 'yolov8x.pt', label: '📦 YOLOv8 XLarge (68.2M params) — Terbesar' }
      ]
    }
  ]
})

// Default epochs per model for display hint
const modelDefaultEpochs = { yolox: 100, yolo26: 100, rfdetr: 100 }
const epochsPlaceholder = computed(() => {
  const key = currentColabModel.value?.key || 'yolox'
  const isLocal = nbMode.value !== 'colab'
  return isLocal ? (modelDefaultEpochs[key] || 100) : 200
})
// ────────────────────────────────────────────────────────────────────────────

const currentColabModel = computed(() => {
  return colabModelMap[activeTrainingTab.value] || colabModelMap.yolo
})

const currentColabGithubUrl = computed(() => {
  return currentColabModel.value.githubUrl
})

const currentColabDownloadUrl = computed(() => {
  if (!importResult.value) return ''
  const m = currentColabModel.value

  // Build base URL
  let baseUrl = ''
  if (importResult.value.colab_notebooks && importResult.value.colab_notebooks[m.key]) {
    baseUrl = getFullUrl(importResult.value.colab_notebooks[m.key])
  } else if (importResult.value.colab_training?.notebook_urls?.[m.key]) {
    baseUrl = getFullUrl(importResult.value.colab_training.notebook_urls[m.key])
  } else if (importResult.value.dataset_id) {
    baseUrl = `${API_BASE_URL}/api/v1/models/data/datasets/${importResult.value.dataset_id}/colab-notebook.ipynb`
  } else if (importResult.value.colab_notebook_url) {
    baseUrl = getFullUrl(importResult.value.colab_notebook_url)
  }

  if (!baseUrl) return ''

  // Strip existing model param and append all config params
  const url = new URL(baseUrl, window.location.origin)
  url.searchParams.set('model', m.key)
  url.searchParams.set('mode', nbMode.value)
  if (nbWeights.value) url.searchParams.set('weights', nbWeights.value)
  if (nbEpochs.value) url.searchParams.set('epochs', nbEpochs.value)
  if (nbBatch.value) url.searchParams.set('batch', nbBatch.value)
  url.searchParams.set('imgsz', nbImgsz.value || 640)
  if (nbOptimizer.value) url.searchParams.set('optimizer', nbOptimizer.value)
  if (nbLr.value) url.searchParams.set('lr0', nbLr.value)
  if (nbWorkers.value) url.searchParams.set('workers', nbWorkers.value)
  if (nbPatience.value) url.searchParams.set('patience', nbPatience.value)

  return url.toString()
})

const datasets = ref([])
const selectedDataset = ref(null)
const isLoadingDatasets = ref(false)
let jobPollTimer = null

// Real-time Upload Progress & Zero-Timeout state
const uploadProgress = ref({
  loaded: 0,
  total: 0,
  percentage: 0,
  speed: '',
  eta: '',
  statusText: ''
})
const xhrInstance = ref(null)

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const cancelUpload = () => {
  if (xhrInstance.value) {
    xhrInstance.value.abort()
    xhrInstance.value = null
    isImporting.value = false
    errorMessage.value = 'Proses pengunggahan dataset dibatalkan oleh pengguna.'
  }
}

const isSyncing = ref(false)
const syncResult = ref(null)

const fetchModelsAndEndpoints = async () => {
  try {
    const [mRes, epRes] = await Promise.all([
      fetch(`${API_BASE_URL}/api/v1/models`),
      fetch(`${API_BASE_URL}/api/v1/models/endpoints`)
    ])
    if (mRes.ok) {
      const mData = await mRes.json()
      models.value = mData.models || []
    }
    if (epRes.ok) {
      const epData = await epRes.json()
      endpoints.value = epData.endpoints || []
    }
  } catch (err) {
    console.error('Failed to load models/endpoints in DataStudio:', err)
  }
}

const onTargetModelChange = () => {
  if (selectedTargetModel.value) {
    const safeName = selectedTargetModel.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
    datasetName.value = `dataset_${safeName}`
  }
}

const handleJsonChange = (e) => {
  const file = e.target.files[0]
  if (file) {
    cocoJsonFile.value = file
    if (!datasetName.value) {
      datasetName.value = file.name.replace(/\.[^/.]+$/, '').replace(/[_-]/g, '_')
    }
  }
}

const handleZipChange = (e) => {
  const file = e.target.files[0]
  if (file) imagesZipFile.value = file
}

const copyToClipboard = async (text, key) => {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    setTimeout(() => {
      copiedKey.value = ''
    }, 2500)
  } catch (err) {
    // Fallback
    const textArea = document.createElement('textarea')
    textArea.value = text
    document.body.appendChild(textArea)
    textArea.select()
    document.execCommand('copy')
    document.body.removeChild(textArea)
    copiedKey.value = key
    setTimeout(() => {
      copiedKey.value = ''
    }, 2500)
  }
}

const getFullUrl = (url) => {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  return new URL(url, API_BASE_URL || window.location.origin).toString()
}

const fetchDatasets = async () => {
  isLoadingDatasets.value = true
  errorMessage.value = ''
  let lastError = null
  try {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/models/data/datasets`)
        if (!response.ok) throw new Error('Gagal mengambil riwayat dataset.')
        datasets.value = (await response.json()).datasets || []
        return
      } catch (error) {
        lastError = error
        if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 2000))
      }
    }
    errorMessage.value = lastError?.message || 'Gagal mengambil riwayat dataset.'
  } finally {
    isLoadingDatasets.value = false
  }
}

const openDataset = async (dataset) => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/models/data/datasets/${dataset.id}`)
    if (!response.ok) throw new Error('Detail dataset gagal dimuat.')
    selectedDataset.value = await response.json()
    importResult.value = selectedDataset.value
  } catch (error) {
    errorMessage.value = error.message
  }
}

const renameDataset = async (dataset) => {
  const name = window.prompt('Nama dataset baru:', dataset.name)
  if (!name || name.trim() === dataset.name) return
  const response = await fetch(`${API_BASE_URL}/api/v1/models/data/datasets/${dataset.id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() })
  })
  if (response.ok) await fetchDatasets()
  else errorMessage.value = (await response.json()).detail || 'Dataset gagal diubah.'
}

const deleteDataset = async (dataset) => {
  if (!window.confirm(`Hapus "${dataset.name}" dari riwayat?`)) return
  const response = await fetch(`${API_BASE_URL}/api/v1/models/data/datasets/${dataset.id}`, { method: 'DELETE' })
  if (response.ok) {
    if (selectedDataset.value?.id === dataset.id) selectedDataset.value = null
    if (importResult.value?.id === dataset.id) importResult.value = null
    await fetchDatasets()
  } else errorMessage.value = (await response.json()).detail || 'Dataset gagal dihapus.'
}

const pollDatasetJob = async (jobId) => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/models/data/jobs/${jobId}`)
    const job = await response.json()
    if (!response.ok) throw new Error(job.detail || 'Status proses tidak dapat dibaca.')
    uploadProgress.value.percentage = job.percentage || 0
    uploadProgress.value.statusText = job.message
    uploadProgress.value.eta = job.status === 'processing' ? 'Ekstraksi & upload storage berjalan...' : 'Menunggu worker...'
    if (job.status === 'completed') {
      isImporting.value = false
      importResult.value = job.result
      selectedDataset.value = job.result
      uploadProgress.value.percentage = 100
      uploadProgress.value.statusText = 'Dataset siap digunakan!'
      await fetchDatasets()
      return
    }
    if (job.status === 'failed') {
      isImporting.value = false
      errorMessage.value = job.error || job.message
      return
    }
    jobPollTimer = window.setTimeout(() => pollDatasetJob(jobId), 2000)
  } catch (error) {
    isImporting.value = false
    errorMessage.value = error.message
  }
}

const submitCvatImport = () => {
  if (!cocoJsonFile.value || !imagesZipFile.value) {
    alert('Silakan pilih file COCO JSON anotasi dan file zip gambar dari CVAT!')
    return
  }

  isImporting.value = true
  errorMessage.value = ''
  importResult.value = null

  const formData = new FormData()
  formData.append('dataset_name', datasetName.value || 'cvat_dataset')
  formData.append('coco_json_file', cocoJsonFile.value)
  formData.append('images_zip_file', imagesZipFile.value)
  if (targetProjectId.value) {
    formData.append('project_id', targetProjectId.value)
  }

  const totalBytesEstimate = (imagesZipFile.value?.size || 0) + (cocoJsonFile.value?.size || 0)

  uploadProgress.value = {
    loaded: 0,
    total: totalBytesEstimate,
    percentage: 0,
    speed: 'Menghitung...',
    eta: 'Menghitung...',
    statusText: 'Mempersiapkan pengunggahan dataset multi-GB...'
  }

  const xhr = new XMLHttpRequest()
  xhrInstance.value = xhr
  xhr.timeout = 0 // ZERO TIMEOUT: Biarkan proses upload multi-GB berjalan hingga selesai tanpa batas waktu

  const startTime = Date.now()
  let lastLoaded = 0
  let lastTime = startTime

  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const now = Date.now()
      const elapsedSec = (now - lastTime) / 1000
      const percent = Math.min(100, Math.round((e.loaded / e.total) * 100))

      // Always update loaded, total, and percentage immediately on every tick
      uploadProgress.value.loaded = e.loaded
      uploadProgress.value.total = e.total
      uploadProgress.value.percentage = percent

      if (elapsedSec >= 0.3 && e.loaded > lastLoaded) {
        const bytesDiff = e.loaded - lastLoaded
        const speedBps = bytesDiff / (elapsedSec || 1)
        const speedMBps = (speedBps / (1024 * 1024)).toFixed(1)
        uploadProgress.value.speed = `${speedMBps} MB/s`

        const remainingBytes = e.total - e.loaded
        const remainingSec = Math.round(remainingBytes / (speedBps || 1))
        if (remainingSec < 60) {
          uploadProgress.value.eta = `${remainingSec} detik lagi`
        } else {
          const mins = Math.floor(remainingSec / 60)
          const secs = remainingSec % 60
          uploadProgress.value.eta = `${mins}m ${secs}s lagi`
        }

        lastLoaded = e.loaded
        lastTime = now
      }

      if (percent < 100) {
        uploadProgress.value.statusText = `Mengunggah file dataset (${percent}%)...`
      } else {
        uploadProgress.value.statusText = 'File terunggah (100%). Server sedang mengekstrak zip & mengunggah gambar ke S3 secara paralel...'
        uploadProgress.value.eta = 'Sedang diproses server...'
      }
    }
  }

  xhr.onload = () => {
    isImporting.value = false
    xhrInstance.value = null
    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        const data = JSON.parse(xhr.responseText)
        if (xhr.status === 202 && data.job_id) {
          isImporting.value = true
          cocoJsonFile.value = null
          imagesZipFile.value = null
          uploadProgress.value.percentage = 0
          uploadProgress.value.statusText = data.message
          pollDatasetJob(data.job_id)
        } else if (data.success) {
          importResult.value = data
          isImporting.value = false
        } else {
          errorMessage.value = data.detail || data.message || 'Gagal mengimpor dataset CVAT.'
        }
      } catch (err) {
        errorMessage.value = 'Gagal memproses response server.'
      }
    } else {
      try {
        const errData = JSON.parse(xhr.responseText)
        errorMessage.value = errData.detail || errData.message || `Server error: HTTP ${xhr.status}`
      } catch (e) {
        if (xhr.status === 413) {
          errorMessage.value = 'Ukuran file melampaui batas server reverse proxy (HTTP 413 Payload Too Large). Pastikan client_max_body_size pada Dokploy / Traefik / Nginx diatur ke 0 (unlimited).'
        } else if (xhr.status === 502) {
          errorMessage.value = 'Backend server sedang down atau restart (HTTP 502 Bad Gateway).'
        } else if (xhr.status === 504) {
          errorMessage.value = 'Request timeout (HTTP 504 Gateway Timeout). Pastikan timeout proxy Dokploy diatur lebih panjang.'
        } else {
          errorMessage.value = `Server error: HTTP ${xhr.status}`
        }
      }
    }
  }

  xhr.onerror = () => {
    isImporting.value = false
    xhrInstance.value = null
    errorMessage.value = 'Koneksi jaringan terputus, reverse proxy menolak payload besar (HTTP 413 / Connection Reset), atau backend tidak dapat dijangkau.'
  }

  xhr.onabort = () => {
    isImporting.value = false
    xhrInstance.value = null
  }

  xhr.open('POST', `${API_BASE_URL}/api/v1/models/data/import-cvat`, true)
  xhr.send(formData)
}

const triggerSync = async () => {
  isSyncing.value = true
  syncResult.value = null
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/data/sync-label-studio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: targetProjectId.value || null,
        include_bad: true,
        include_good: true,
        model_id: syncFilterModelId.value ? parseInt(syncFilterModelId.value) : null,
        endpoint_slug: syncFilterEndpointSlug.value || null
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      syncResult.value = data
    } else {
      alert(data.message || data.error || 'Gagal sinkronisasi data ke Label Studio.')
    }
  } catch (err) {
    alert('Koneksi backend error.')
  } finally {
    isSyncing.value = false
  }
}

onMounted(() => {
  fetchModelsAndEndpoints()
  fetchDatasets()
})
</script>

<template>
  <div class="data-studio-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Dataset Studio & Label Studio Bridge</h1>
        <p class="page-subtitle">
          Unggah dataset CVAT langsung dari Web UI, simpan ke folder khusus di S3, dan salin URL / Prefix untuk langsung dihubungkan ke Label Studio.
        </p>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert alert-danger">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ errorMessage }}
    </div>

    <!-- Persistent upload history -->
    <section class="history-card">
      <div class="history-header">
        <div>
          <h2 class="card-title">Riwayat Dataset</h2>
          <p class="desc-text">Klik dataset untuk melihat gambar dan menyalin link training / Label Studio.</p>
        </div>
        <span class="badge badge-primary">{{ datasets.length }} dataset</span>
      </div>
      <div v-if="isLoadingDatasets" class="empty-state">Memuat riwayat...</div>
      <div v-else-if="!datasets.length" class="empty-state">Belum ada dataset. Upload dataset pertama Anda di bawah.</div>
      <div v-else class="dataset-list">
        <div v-for="dataset in datasets" :key="dataset.id" class="dataset-row" role="button" tabindex="0" @click="openDataset(dataset)" @keydown.enter="openDataset(dataset)">
          <div class="dataset-icon">▦</div>
          <div class="dataset-main">
            <strong>{{ dataset.name }}</strong>
            <span>{{ dataset.images_uploaded_count }} gambar · {{ dataset.tasks_created_count }} task · {{ new Date(dataset.created_at).toLocaleString('id-ID') }}</span>
          </div>
          <span class="status-ready">Siap</span>
          <button class="row-action" title="Ubah nama" @click.stop="renameDataset(dataset)">Edit</button>
          <button class="row-action danger" title="Hapus" @click.stop="deleteDataset(dataset)">Hapus</button>
        </div>
      </div>
    </section>

    <!-- SUCCESS MODAL / CARD: S3 URL & COPYABLE INFOS FOR LABEL STUDIO -->
    <div v-if="importResult" class="success-result-card">
      <div class="result-header">
        <div class="result-badge">
          <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Folder Dataset S3 Berhasil Dibuat!
        </div>
        <button class="btn-close" @click="importResult = null">&times;</button>
      </div>

      <p class="result-intro">
        Dataset telah diekstrak dan disimpan ke folder khusus di S3: <strong>{{ importResult.dataset_folder }}</strong>. Total <strong>{{ importResult.images_uploaded_count }} gambar</strong> dan <strong>{{ importResult.tasks_created_count }} anotasi</strong> siap digunakan.
      </p>

      <div v-if="importResult.images?.length" class="gallery-section">
        <div class="gallery-title-row">
          <h3>Isi Dataset ({{ importResult.images.length }} gambar)</h3>
          <span>Klik gambar untuk membuka ukuran penuh</span>
        </div>
        <div class="image-grid">
          <a v-for="image in importResult.images" :key="image.url" :href="getFullUrl(image.url)" target="_blank" class="image-tile">
            <img :src="getFullUrl(image.url)" :alt="image.name" loading="lazy" />
            <span :title="image.name">{{ image.name }}</span>
          </a>
        </div>
      </div>

      <!-- Copyable URLs Section -->
      <div class="copy-fields-grid">
        
        <!-- Field 1: S3 Bucket Prefix (Folder) -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">S3 Folder Prefix (Untuk Cloud Storage Source)</span>
            <span v-if="copiedKey === 'prefix'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="importResult.s3_folder_prefix" class="copy-input" />
            <button class="btn-copy" @click="copyToClipboard(importResult.s3_folder_prefix, 'prefix')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin Prefix
            </button>
          </div>
        </div>

        <!-- Field 2: Full S3 URI -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">Full S3 URI (Folder Gambar)</span>
            <span v-if="copiedKey === 's3_uri'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="importResult.s3_uri" class="copy-input font-mono" />
            <button class="btn-copy" @click="copyToClipboard(importResult.s3_uri, 's3_uri')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin S3 URI
            </button>
          </div>
        </div>

        <!-- Field 3: Tasks JSON Direct URL -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">Link Siap Import Label Studio</span>
            <span v-if="copiedKey === 'tasks_url'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="getFullUrl(importResult.label_studio_import_url || importResult.tasks_json_url)" class="copy-input text-blue-600" />
            <button class="btn-copy" @click="copyToClipboard(getFullUrl(importResult.label_studio_import_url || importResult.tasks_json_url), 'tasks_url')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin URL
            </button>
          </div>
        </div>

        <!-- Field 4: YOLO data.yaml URL (Colab / Local Training) -->
        <div v-if="importResult.yolo_yaml_url" class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title font-semibold text-amber-700">YOLO data.yaml URL (Untuk Google Colab Training)</span>
            <span v-if="copiedKey === 'yolo_yaml'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="getFullUrl(importResult.yolo_yaml_url)" class="copy-input text-amber-700 font-mono" />
            <button class="btn-copy bg-amber-600 hover:bg-amber-700" @click="copyToClipboard(getFullUrl(importResult.yolo_yaml_url), 'yolo_yaml')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin data.yaml
            </button>
          </div>
        </div>

        <!-- Field 5: COCO Annotations JSON URL (RF-DETR / PyTorch Training) -->
        <div v-if="importResult.coco_json_url" class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title font-semibold text-purple-700">COCO Annotations URL (Untuk RF-DETR Training & Validasi)</span>
            <span v-if="copiedKey === 'coco_url'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="getFullUrl(importResult.coco_json_url)" class="copy-input text-purple-700 font-mono" />
            <button class="btn-copy bg-purple-600 hover:bg-purple-700" @click="copyToClipboard(getFullUrl(importResult.coco_json_url), 'coco_url')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin COCO URL
            </button>
          </div>
        </div>

      </div>

      <!-- Quick Setup Guide for Label Studio -->
      <div class="ls-guide-card">
        <h3 class="guide-title">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
          Cara Memasukkan ke Label Studio:
        </h3>
        <div class="guide-options">
          <div class="guide-option">
            <strong>Opsi 1: Import Langsung via URL</strong>
            <ol>
              <li>Buka Project di Label Studio &gt; Klik <strong>Import</strong>.</li>
              <li>Pilih tab <strong>URL</strong>, lalu paste <em>Link Siap Import Label Studio</em> di atas.</li>
              <li>Klik <strong>Load</strong>. Seluruh gambar dan bounding box CVAT langsung muncul sebagai task teranotasi!</li>
            </ol>
          </div>

          <div class="guide-option">
            <strong>Opsi 2: Sinkronisasi S3 Cloud Storage</strong>
            <ol>
              <li>Buka Project &gt; <strong>Settings &gt; Cloud Storage &gt; Add Source Storage</strong>.</li>
              <li>Pilih Storage Type: <strong>AWS S3</strong>.</li>
              <li>Bucket Name: <code>{{ importResult.s3_bucket }}</code>.</li>
              <li>Bucket Prefix: <code>{{ importResult.s3_folder_prefix }}</code>.</li>
              <li>Centang <em>"Treat every bucket object as a source file"</em> lalu klik <strong>Sync Storage</strong>.</li>
            </ol>
          </div>
        </div>
      </div>

      <!-- Training Hub Card (Local PC + Google Colab) -->
      <div v-if="importResult.colab_training" class="colab-training-card">
        <div class="colab-header">
          <div class="flex items-center gap-2">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="#d97706" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8"></polygon></svg>
            <h3 class="colab-title">
              <template v-if="nbMode === 'local_cpu'">🖥️ Training Hub — Lokal CPU</template>
              <template v-else-if="nbMode === 'local_gpu'">⚡ Training Hub — Lokal GPU (CUDA)</template>
              <template v-else>☁️ Training Hub — Google Colab T4 GPU</template>
            </h3>
          </div>

          <div class="flex items-center gap-2">
            <!-- 1-Click Open in Google Colab (shown only for colab mode) -->
            <a
              v-if="nbMode === 'colab'"
              :href="currentColabGithubUrl"
              target="_blank"
              class="btn-open-colab"
              :title="`Buka langsung notebook training ${currentColabModel.label} di Google Colab via GitHub`"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
              Buka {{ currentColabModel.label }} di Colab
            </a>

            <!-- Download .ipynb Button -->
            <a
              v-if="currentColabDownloadUrl"
              :href="currentColabDownloadUrl"
              target="_blank"
              :download="currentColabModel.filename"
              class="btn-download-ipynb"
              :title="`Generate & unduh notebook .ipynb ${currentColabModel.label} untuk ${nbMode}`"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              <template v-if="nbMode === 'local_cpu'">⬇️ Unduh .ipynb (Lokal CPU)</template>
              <template v-else-if="nbMode === 'local_gpu'">⬇️ Unduh .ipynb (Lokal GPU)</template>
              <template v-else>⬇️ Unduh .ipynb (Colab T4)</template>
            </a>

            <div class="colab-tabs">
              <button
                type="button"
                class="colab-tab-btn"
                :class="{ 'active': activeTrainingTab === 'yolo' }"
                @click="activeTrainingTab = 'yolo'"
              >
                ⚡ 1. YOLO-X
              </button>
              <button
                type="button"
                class="colab-tab-btn"
                :class="{ 'active': activeTrainingTab === 'yolo26' }"
                @click="activeTrainingTab = 'yolo26'"
              >
                🔥 2. YOLO-26
              </button>
              <button
                type="button"
                class="colab-tab-btn"
                :class="{ 'active': activeTrainingTab === 'rfdetr' }"
                @click="activeTrainingTab = 'rfdetr'"
              >
                🎯 3. RF-DETR
              </button>
            </div>
          </div>
        </div>

        <!-- ⚙️ Training Configuration Panel -->
        <div class="nb-config-panel">
          <div class="nb-config-row">
            <!-- Mode Selector -->
            <div class="nb-config-group">
              <label class="nb-config-label">🖥️ Mode Running</label>
              <div class="nb-mode-btns">
                <button
                  type="button"
                  class="nb-mode-btn"
                  :class="{ 'active': nbMode === 'local_cpu' }"
                  @click="nbMode = 'local_cpu'"
                  title="Jalankan di Jupyter / VS Code lokal tanpa GPU (CPU)"
                >
                  🖥️ Lokal CPU
                </button>
                <button
                  type="button"
                  class="nb-mode-btn"
                  :class="{ 'active': nbMode === 'local_gpu' }"
                  @click="nbMode = 'local_gpu'"
                  title="Jalankan lokal dengan GPU NVIDIA (CUDA)"
                >
                  ⚡ Lokal GPU
                </button>
                <button
                  type="button"
                  class="nb-mode-btn"
                  :class="{ 'active': nbMode === 'colab' }"
                  @click="nbMode = 'colab'"
                  title="Jalankan di Google Colab T4 GPU gratis"
                >
                  ☁️ Colab T4
                </button>
              </div>
              <div class="nb-mode-info">
                <template v-if="nbMode === 'local_cpu'">📋 File .ipynb dijalankan di <strong>Jupyter Notebook</strong> / VS Code PC Anda. Tidak perlu GPU, tidak perlu Google Drive.</template>
                <template v-else-if="nbMode === 'local_gpu'">⚡ Menggunakan GPU NVIDIA lokal (CUDA). Auto-detect — jika GPU tidak tersedia, fallback ke CPU.</template>
                <template v-else>☁️ Jalankan di Google Colab gratis. Termasuk Google Drive mount dan auto-resume.</template>
              </div>
            </div>
          </div>

          <!-- Model Variant / Pretrained Weights Selector -->
          <div class="nb-config-row">
            <div class="nb-config-group">
              <div class="flex items-center justify-between flex-wrap gap-1">
                <label class="nb-config-label">🎯 Varian Bobot Model (Nano, Small, Medium, Large, X-Large)</label>
                <span v-if="nbMode === 'local_cpu'" class="text-xs text-amber-900 bg-amber-200/80 px-2 py-0.5 rounded font-medium">
                  💡 Tips CPU: Pilih varian <strong>Nano (yolo11n)</strong> atau <strong>Small (yolo11s)</strong> agar proses cepat
                </span>
              </div>
              <select v-model="nbWeights" class="nb-config-input">
                <option value="">Default (Sesuai Tab {{ currentColabModel.label }})</option>
                <optgroup v-for="grp in groupedWeightsOptions" :key="grp.group" :label="grp.group">
                  <option v-for="opt in grp.options" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </optgroup>
              </select>
            </div>
          </div>

          <div class="nb-config-row nb-config-params">
            <!-- Epochs -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">🔄 Epoch</label>
              <input
                v-model.number="nbEpochs"
                type="number"
                min="1"
                max="1000"
                :placeholder="epochsPlaceholder"
                class="nb-config-input"
                title="Jumlah epoch training. Kosongkan untuk pakai default model."
              />
              <span class="nb-config-hint">Default: {{ epochsPlaceholder }}</span>
            </div>

            <!-- Batch Size -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">📦 Batch Size</label>
              <input
                v-model.number="nbBatch"
                type="number"
                min="1"
                max="128"
                placeholder="Auto"
                class="nb-config-input"
                title="Batch size. Kosongkan untuk pakai default model. CPU: gunakan nilai kecil (4-8)."
              />
              <span class="nb-config-hint">CPU: 4–8 | GPU: 16–32</span>
            </div>

            <!-- Image Size -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">🖼️ Image Size</label>
              <select v-model.number="nbImgsz" class="nb-config-input">
                <option :value="320">320</option>
                <option :value="416">416</option>
                <option :value="512">512</option>
                <option :value="640">640 (Default)</option>
                <option :value="1280">1280</option>
              </select>
            </div>

            <!-- Optimizer -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">⚙️ Optimizer</label>
              <select v-model="nbOptimizer" class="nb-config-input">
                <option value="">Auto (default)</option>
                <option value="AdamW">AdamW</option>
                <option value="Adam">Adam</option>
                <option value="SGD">SGD</option>
                <option value="auto">auto</option>
              </select>
            </div>
          </div>

          <!-- Advanced Settings Toggle -->
          <div class="nb-advanced-toggle" @click="showAdvanced = !showAdvanced">
            <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"
              :style="{ transform: showAdvanced ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }">
              <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
            {{ showAdvanced ? 'Sembunyikan' : 'Tampilkan' }} Pengaturan Lanjutan
          </div>

          <div v-if="showAdvanced" class="nb-config-row nb-config-params">
            <!-- LR -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">📈 Learning Rate (lr0)</label>
              <input
                v-model.number="nbLr"
                type="number"
                step="0.0001"
                min="0.00001"
                max="0.1"
                placeholder="Auto"
                class="nb-config-input"
              />
            </div>

            <!-- Workers -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">🧵 Workers</label>
              <input
                v-model.number="nbWorkers"
                type="number"
                min="0"
                max="16"
                :placeholder="nbMode === 'local_cpu' ? '2' : '4'"
                class="nb-config-input"
              />
              <span class="nb-config-hint">CPU: 2 | GPU: 4</span>
            </div>

            <!-- Patience -->
            <div class="nb-config-group nb-config-group-sm">
              <label class="nb-config-label">⏱️ Patience</label>
              <input
                v-model.number="nbPatience"
                type="number"
                min="1"
                max="200"
                :placeholder="nbMode === 'colab' ? '50' : '30'"
                class="nb-config-input"
                title="Early stopping patience. Training berhenti jika tidak ada improvement dalam N epoch."
              />
              <span class="nb-config-hint">Early stop epochs</span>
            </div>

            <!-- Reset -->
            <div class="nb-config-group nb-config-group-sm" style="justify-content: flex-end; padding-top: 18px;">
              <button
                type="button"
                class="nb-reset-btn"
                @click="nbWeights=''; nbEpochs=null; nbBatch=null; nbImgsz=640; nbOptimizer=null; nbLr=null; nbWorkers=null; nbPatience=null"
              >
                🔄 Reset ke Default
              </button>
            </div>
          </div>
        </div>
        <!-- END Training Configuration Panel -->


        <!-- Direct S3 Notebook URL Info Row -->
        <div v-if="currentColabDownloadUrl" class="ipynb-url-row">
          <span class="text-xs text-amber-900 font-medium">Link Notebook ({{ currentColabModel.label }}):</span>
          <input type="text" readonly :value="currentColabDownloadUrl" class="copy-input text-xs font-mono py-1" />
          <button class="btn-copy py-1 text-xs" @click="copyToClipboard(currentColabDownloadUrl, 'colab_ipynb_url')">
            {{ copiedKey === 'colab_ipynb_url' ? '✓ Tersalin!' : 'Salin URL .ipynb' }}
          </button>
        </div>

        <!-- TAB 1: YOLO-X Snippet -->
        <div v-if="activeTrainingTab === 'yolo'" class="colab-code-box">
          <div class="code-box-header">
            <span class="text-xs text-amber-300 font-semibold">⚡ 1. YOLO-X Training Pipeline (200 Epochs, T4 GPU, AdamW, Auto-Resume):</span>
            <div class="flex items-center gap-2">
              <a 
                :href="currentColabGithubUrl" 
                target="_blank" 
                class="btn-xs-copy bg-amber-500 hover:bg-amber-600 text-neutral-950 font-bold"
              >
                🚀 Buka YOLO-X di Colab
              </a>
              <button 
                class="btn-xs-copy" 
                @click="copyToClipboard(importResult.colab_training.yolo_code, 'colab_yolo')"
              >
                {{ copiedKey === 'colab_yolo' ? '✓ Tersalin!' : 'Salin Script' }}
              </button>
            </div>
          </div>
          <pre class="code-block"><code>{{ importResult.colab_training.yolo_code }}</code></pre>
        </div>

        <!-- TAB 2: YOLO-26 Snippet -->
        <div v-else-if="activeTrainingTab === 'yolo26'" class="colab-code-box">
          <div class="code-box-header">
            <span class="text-xs text-sky-300 font-semibold">🔥 2. YOLO-26 Training Pipeline (200 Epochs, T4 GPU, Fast Edge, Auto-Resume):</span>
            <div class="flex items-center gap-2">
              <a 
                :href="currentColabGithubUrl" 
                target="_blank" 
                class="btn-xs-copy bg-sky-500 hover:bg-sky-600 text-neutral-950 font-bold"
              >
                🚀 Buka YOLO-26 di Colab
              </a>
              <button 
                class="btn-xs-copy bg-sky-600 hover:bg-sky-700" 
                @click="copyToClipboard(importResult.colab_training.yolo26_code || importResult.colab_training.yolo_code, 'colab_yolo26')"
              >
                {{ copiedKey === 'colab_yolo26' ? '✓ Tersalin!' : 'Salin Script' }}
              </button>
            </div>
          </div>
          <pre class="code-block"><code>{{ importResult.colab_training.yolo26_code || importResult.colab_training.yolo_code }}</code></pre>
        </div>

        <!-- TAB 3: RF-DETR Snippet -->
        <div v-else class="colab-code-box">
          <div class="code-box-header">
            <span class="text-xs text-purple-300 font-semibold">🎯 3. RF-DETR Transformer Pipeline (200 Epochs, T4 GPU, Auto-Resume):</span>
            <div class="flex items-center gap-2">
              <a 
                :href="currentColabGithubUrl" 
                target="_blank" 
                class="btn-xs-copy bg-purple-500 hover:bg-purple-600 text-neutral-950 font-bold"
              >
                🚀 Buka RF-DETR di Colab
              </a>
              <button 
                class="btn-xs-copy bg-purple-600 hover:bg-purple-700" 
                @click="copyToClipboard(importResult.colab_training.rfdetr_code, 'colab_rfdetr')"
              >
                {{ copiedKey === 'colab_rfdetr' ? '✓ Tersalin!' : 'Salin Script' }}
              </button>
            </div>
          </div>
          <pre class="code-block"><code>{{ importResult.colab_training.rfdetr_code }}</code></pre>
        </div>

        <div class="colab-footer-hint">
          💡 <strong>Panduan Menjalankan Notebook Terpisah di Google Colab:</strong>
          <ul class="mt-1.5 space-y-1 text-xs text-amber-950 list-disc list-inside">
            <li><strong>Cara 1 (Paling Cepat &amp; Mudah 1-Klik):</strong> Pilih tab model yang diinginkan (<strong>YOLO-X</strong>, <strong>YOLO-26</strong>, atau <strong>RF-DETR</strong>), lalu klik tombol <strong>"Buka [Model] di Colab (1-Klik)"</strong>. Notebook khusus model tersebut akan langsung terbuka tanpa tercampur dengan model lain.</li>
            <li><strong>Cara 2 (Upload File .ipynb):</strong> Klik tombol <strong>"Unduh .ipynb ([Model])"</strong>. Di Google Colab, pilih menu <em>File &gt; Upload notebook</em> lalu upload file yang baru diunduh.</li>
            <li><strong>Cara 3 (Salin Script Manual):</strong> Buka Google Colab baru, salin script dari kotak tab di atas, lalu jalankan langsung.</li>
          </ul>
        </div>
      </div>

    </div>

    <!-- Main Grid: Upload Form & Flywheel Sync -->
    <div class="studio-grid">
      <!-- Left Card: CVAT Upload Form -->
      <div class="card">
        <div class="card-header">
          <div class="flex items-center gap-2">
            <svg viewBox="0 0 24 24" width="20" height="20" stroke="#2563eb" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            <h2 class="card-title">Unggah Dataset dari CVAT</h2>
          </div>
          <span class="badge badge-primary">COCO Format</span>
        </div>

        <div class="card-body">
          <p class="desc-text">
            Unggah hasil ekspor CVAT (file JSON anotasi COCO dan file Zip gambar). Sistem akan membuat folder khusus di S3 dan menyediakan URL siap pakai untuk Label Studio.
          </p>

          <form @submit.prevent="submitCvatImport">
            <div class="form-group">
              <label class="form-label">Tautkan ke Model / Kategori AI (Opsional)</label>
              <select v-model="selectedTargetModel" @change="onTargetModelChange" class="form-input">
                <option value="">-- Dataset Mandiri / Kategori Baru --</option>
                <option v-for="m in models" :key="m.id" :value="m.name">
                  {{ m.name }} ({{ m.version }})
                </option>
              </select>
              <span class="form-hint">Memilih model akan otomatis merekomendasikan nama folder S3.</span>
            </div>

            <div class="form-group">
              <label class="form-label">Nama Folder / Dataset</label>
              <input 
                type="text" 
                v-model="datasetName" 
                class="form-input" 
                placeholder="Contoh: dataset_cvat_defect" 
              />
              <span class="form-hint">Folder khusus akan dibuat di S3 dengan nama ini.</span>
            </div>

            <div class="form-group">
              <label class="form-label">File Anotasi CVAT (.json) *</label>
              <input 
                type="file" 
                accept=".json" 
                class="form-file" 
                @change="handleJsonChange" 
                required 
              />
              <span class="form-hint">File JSON format COCO 1.0 dari CVAT.</span>
            </div>

            <div class="form-group">
              <label class="form-label">File Arsip Gambar (.zip) *</label>
              <input 
                type="file" 
                accept=".zip" 
                class="form-file" 
                @change="handleZipChange" 
                required 
              />
              <span class="form-hint">Arsip zip berisi gambar-gambar dataset CVAT.</span>
            </div>

            <div class="form-group">
              <label class="form-label">Label Studio Project ID (Opsional)</label>
              <input 
                type="text" 
                v-model="targetProjectId" 
                class="form-input" 
                placeholder="Misal: 1 (opsional jika ingin auto-push via API)" 
              />
            </div>

            <!-- Real-time Progress Bar Card -->
            <div v-if="isImporting" class="upload-progress-card">
              <div class="progress-header">
                <div class="flex items-center gap-2">
                  <div class="spinner-sm"></div>
                  <span class="progress-status-text font-semibold">{{ uploadProgress.statusText }}</span>
                </div>
                <span class="progress-percentage-pill">{{ uploadProgress.percentage }}%</span>
              </div>

              <div class="progress-track">
                <div 
                  class="progress-fill" 
                  :style="{ width: `${uploadProgress.percentage}%` }"
                  :class="{ 'pulse-mode': uploadProgress.percentage === 100 }"
                ></div>
              </div>

              <div class="progress-details-grid">
                <div class="detail-box">
                  <span class="detail-title">Terunggah:</span>
                  <strong class="detail-val font-mono">{{ formatBytes(uploadProgress.loaded) }} / {{ formatBytes(uploadProgress.total) }}</strong>
                </div>
                <div class="detail-box">
                  <span class="detail-title">Kecepatan:</span>
                  <strong class="detail-val font-mono text-blue-600">{{ uploadProgress.speed || 'Menghitung...' }}</strong>
                </div>
                <div class="detail-box">
                  <span class="detail-title">Estimasi Sisa:</span>
                  <strong class="detail-val font-mono text-emerald-600">{{ uploadProgress.eta || 'Menghitung...' }}</strong>
                </div>
              </div>

              <div class="progress-footer">
                <div class="flex items-center gap-1 text-xs text-slate-500">
                  <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                  <span>Mode Tanpa Timeout: Upload multi-GB diproses secara streaming ke disk & S3.</span>
                </div>
                <button type="button" class="btn btn-xs btn-outline-danger" @click="cancelUpload">
                  Batalkan
                </button>
              </div>
            </div>

            <button v-else type="submit" class="btn btn-primary btn-block">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
              Unggah ke S3 & Dapatkan URL
            </button>
          </form>
        </div>
      </div>

      <!-- Right Card: Active Learning Retraining Cycle -->
      <div class="card">
        <div class="card-header">
          <div class="flex items-center gap-2">
            <svg viewBox="0 0 24 24" width="20" height="20" stroke="#16a34a" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
            <h2 class="card-title">Alur Active Retraining (Flywheel)</h2>
          </div>
          <span class="badge badge-success">Automated Bridge</span>
        </div>

        <div class="card-body">
          <p class="desc-text">
            Bagaimana data dari inferensi dan umpan balik pengguna di web berputar kembali untuk retraining model:
          </p>

          <div class="pipeline-steps">
            <div class="pipe-step">
              <div class="step-num">1</div>
              <div>
                <strong>Inferensi dari Web Klien</strong>
                <p>Web lain memanggil <code>POST /api/v1/models/predict</code>. Semua gambar disimpan otomatis di S3.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">2</div>
              <div>
                <strong>Pengumpulan Feedback</strong>
                <p>Jika pengguna memberi feedback <em>Tidak Akurat</em>, gambar masuk ke <em>Review Queue</em> di S3.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">3</div>
              <div>
                <strong>Sinkronisasi Bulanan ke Label Studio</strong>
                <p>Data yang butuh anotasi ulang dikirim ke Label Studio untuk diperbaiki oleh tim annotator.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">4</div>
              <div>
                <strong>Retrain & Hot-Swap Model</strong>
                <p>Model baru dilatih di GPU/Colab, lalu diunggah kembali ke sistem ini tanpa mengubah endpoint API!</p>
              </div>
            </div>
          </div>

          <div class="sync-action-wrap">
            <div class="form-row mb-3">
              <div class="flex-1">
                <label class="form-label text-xs">Filter Model Feedback</label>
                <select v-model="syncFilterModelId" class="form-input text-xs">
                  <option value="">Semua Model</option>
                  <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
                </select>
              </div>
              <div class="flex-1">
                <label class="form-label text-xs">Filter Endpoint</label>
                <select v-model="syncFilterEndpointSlug" class="form-input text-xs">
                  <option value="">Semua Endpoints</option>
                  <option v-for="ep in endpoints" :key="ep.id" :value="ep.slug">{{ ep.name }}</option>
                </select>
              </div>
            </div>

            <button class="btn btn-secondary btn-block" @click="triggerSync" :disabled="isSyncing">
              <span v-if="isSyncing" class="spinner-sm"></span>
              {{ isSyncing ? 'Mensinkronkan...' : 'Sinkronkan Data Review ke Label Studio' }}
            </button>
            <div v-if="syncResult" class="text-xs text-emerald-600 mt-2 text-center">
              ✓ {{ syncResult.message }}
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.data-studio-container {
  padding: 8px 0;
}

.page-header {
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
  max-width: 680px;
  line-height: 1.5;
}

/* Success Card */
.success-result-card {
  background: white;
  border: 2px solid #86efac;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 28px;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.08);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #dcfce7;
  color: #15803d;
  font-weight: 700;
  font-size: 1.05rem;
  padding: 6px 14px;
  border-radius: 9999px;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
}

.result-intro {
  font-size: 0.9rem;
  color: #334155;
  margin: 0 0 20px 0;
  line-height: 1.5;
}

.copy-fields-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 24px;
}

.copy-field-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}

.field-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.field-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.copied-indicator {
  font-size: 0.75rem;
  font-weight: 700;
  color: #16a34a;
}

.copy-input-group {
  display: flex;
  gap: 8px;
}

.copy-input {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: white;
  font-size: 0.85rem;
  color: #1e293b;
}

.btn-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}
.btn-copy:hover { background: #1d4ed8; }

/* Colab Training Card */
/* Download ipynb and URL row */
.btn-download-ipynb {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #059669;
  color: white;
  text-decoration: none;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 5px 11px;
  border-radius: 6px;
  transition: background 0.2s;
  white-space: nowrap;
}
.btn-download-ipynb:hover {
  background: #047857;
  color: white;
}

.ipynb-url-row {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fef3c7;
  border: 1px dashed #f59e0b;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
}

.colab-training-card {
  margin-top: 18px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-left: 4px solid #d97706;
  border-radius: 8px;
  padding: 16px 20px;
}

.colab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 10px;
}

.colab-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #92400e;
  margin: 0;
}

.btn-open-colab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #ea580c;
  color: white;
  border: 1px solid #c2410c;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  text-decoration: none;
  transition: all 0.2s;
}
.btn-open-colab:hover {
  background: #c2410c;
  color: white;
}

.btn-download-ipynb {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #ffffff;
  color: #92400e;
  border: 1px solid #d97706;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  text-decoration: none;
  transition: all 0.2s;
}
.btn-download-ipynb:hover {
  background: #fef3c7;
  color: #78350f;
}

.colab-tabs {
  display: flex;
  gap: 6px;
}

.colab-tab-btn {
  background: #fef3c7;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.colab-tab-btn.active {
  background: #d97706;
  color: white;
  border-color: #d97706;
}

.colab-code-box {
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
  margin-top: 8px;
}

.code-box-header {
  background: #0f172a;
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #334155;
}

.btn-xs-copy {
  background: #3b82f6;
  color: white;
  border: none;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.btn-xs-copy:hover { background: #2563eb; }

.code-block {
  margin: 0;
  padding: 12px 14px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  color: #f1f5f9;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow-y: auto;
}

.colab-footer-hint {
  font-size: 0.8rem;
  color: #78350f;
  margin-top: 10px;
  line-height: 1.4;
}

.ls-guide-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 16px 20px;
}

.guide-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #166534;
  margin: 0 0 12px 0;
}

.guide-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 768px) {
  .guide-options {
    grid-template-columns: 1fr;
  }
}

.guide-option strong {
  display: block;
  font-size: 0.85rem;
  color: #14532d;
  margin-bottom: 6px;
}

.guide-option ol {
  margin: 0;
  padding-left: 18px;
  font-size: 0.8rem;
  color: #166534;
  line-height: 1.5;
}

.guide-option li {
  margin-bottom: 4px;
}

/* Studio Grid */
.studio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 900px) {
  .studio-grid { grid-template-columns: 1fr; }
}

.card {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
  overflow: hidden;
}

.card-header {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
}

.card-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.card-body { padding: 20px; }

.desc-text {
  font-size: 0.85rem;
  color: #64748b;
  margin: 0 0 18px 0;
  line-height: 1.5;
}

.form-group { margin-bottom: 16px; }

.form-label {
  display: block;
  font-size: 0.825rem;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 0.875rem;
  box-sizing: border-box;
}

.form-file {
  width: 100%;
  font-size: 0.85rem;
  color: #475569;
}

.form-hint {
  display: block;
  font-size: 0.725rem;
  color: #94a3b8;
  margin-top: 4px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  font-size: 0.875rem;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }

.btn-secondary {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #e2e8f0;
}
.btn-secondary:hover { background: #e2e8f0; }

.btn-block { width: 100%; }

.badge {
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}
.badge-primary { background: #dbeafe; color: #1e40af; }
.badge-success { background: #dcfce7; color: #166534; }

.pipeline-steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 24px;
}

.pipe-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.pipe-step strong {
  display: block;
  font-size: 0.85rem;
  color: #1e293b;
}

.pipe-step p {
  font-size: 0.78rem;
  color: #64748b;
  margin: 2px 0 0 0;
  line-height: 1.4;
}

.sync-action-wrap {
  margin-top: 16px;
  border-top: 1px solid #f1f5f9;
  padding-top: 16px;
}

.alert {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.875rem;
}

.alert-danger { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }

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

.upload-progress-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 16px; margin-top: 14px; }
.progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.progress-status-text { font-size: 0.825rem; color: #1e293b; line-height: 1.4; }
.progress-percentage-pill { background: #dbeafe; color: #1d4ed8; font-family: monospace; font-size: 0.85rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.progress-track { width: 100%; height: 10px; background: #e2e8f0; border-radius: 9999px; overflow: hidden; margin-bottom: 12px; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #2563eb, #3b82f6); border-radius: 9999px; transition: width 0.25s ease-out; }
.progress-fill.pulse-mode { background: linear-gradient(90deg, #10b981, #059669); animation: bar-pulse 1.5s infinite; }
@keyframes bar-pulse { 0% { opacity: 0.8; } 50% { opacity: 1; } 100% { opacity: 0.8; } }

.progress-details-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
.detail-box { display: flex; flex-direction: column; gap: 2px; }
.detail-title { font-size: 0.7rem; color: #64748b; font-weight: 500; }
.detail-val { font-size: 0.775rem; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.progress-footer { display: flex; justify-content: space-between; align-items: center; }
.btn-xs { padding: 3px 8px; font-size: 0.725rem; border-radius: 4px; }
.history-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; margin-bottom: 24px; padding: 20px; }
.history-header, .gallery-title-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.history-header .desc-text { margin: 5px 0 0; }
.dataset-list { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.dataset-row { display: flex; align-items: center; gap: 12px; border: 1px solid #e2e8f0; border-radius: 9px; padding: 12px; cursor: pointer; transition: .2s; }
.dataset-row:hover { border-color: #93c5fd; background: #f8fbff; }
.dataset-icon { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; color: #2563eb; background: #dbeafe; font-size: 20px; }
.dataset-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.dataset-main strong { color: #0f172a; }
.dataset-main span { color: #64748b; font-size: .75rem; margin-top: 3px; }
.status-ready { color: #15803d; background: #dcfce7; border-radius: 999px; padding: 4px 9px; font-size: .72rem; font-weight: 700; }
.row-action { border: 1px solid #cbd5e1; background: white; color: #334155; border-radius: 6px; padding: 6px 9px; cursor: pointer; }
.row-action.danger { color: #dc2626; border-color: #fecaca; }
.empty-state { color: #64748b; text-align: center; padding: 28px; }
.gallery-section { margin: 18px 0 24px; border-top: 1px solid #e2e8f0; padding-top: 18px; }
.gallery-title-row h3 { margin: 0; font-size: 1rem; color: #0f172a; }
.gallery-title-row span { color: #64748b; font-size: .75rem; }
.image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; margin-top: 12px; max-height: 480px; overflow: auto; }
.image-tile { color: #334155; text-decoration: none; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #f8fafc; }
.image-tile img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; background: #e2e8f0; }
.image-tile span { display: block; font-size: .7rem; padding: 7px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 700px) { .dataset-row { flex-wrap: wrap; } .dataset-main { min-width: calc(100% - 60px); } .status-ready { margin-left: 50px; } }

/* ─── Training Configuration Panel ──────────────────────────────────────── */
.nb-config-panel {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 14px 16px 10px;
  margin: 10px 0 0;
}

.nb-config-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 10px;
}

.nb-config-params {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-start;
}

.nb-config-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  flex: 1;
}

.nb-config-group-sm {
  flex: 0 1 140px;
  min-width: 120px;
}

.nb-config-label {
  font-size: 0.7rem;
  font-weight: 700;
  color: #92400e;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.nb-config-input {
  border: 1px solid #fcd34d;
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 0.8rem;
  background: #fff;
  color: #1e293b;
  width: 100%;
  box-sizing: border-box;
  outline: none;
}
.nb-config-input:focus {
  border-color: #d97706;
  box-shadow: 0 0 0 2px rgba(217,119,6,0.15);
}

.nb-config-hint {
  font-size: 0.67rem;
  color: #a16207;
}

.nb-mode-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.nb-mode-btn {
  border: 1px solid #fcd34d;
  border-radius: 6px;
  padding: 5px 11px;
  font-size: 0.78rem;
  background: #fff;
  color: #78350f;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.nb-mode-btn:hover {
  background: #fef3c7;
  border-color: #d97706;
}
.nb-mode-btn.active {
  background: #d97706;
  border-color: #b45309;
  color: #fff;
  font-weight: 700;
}

.nb-mode-info {
  font-size: 0.73rem;
  color: #78350f;
  background: #fef9c3;
  border-radius: 6px;
  padding: 6px 10px;
  margin-top: 4px;
  line-height: 1.4;
}

.nb-advanced-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.73rem;
  color: #a16207;
  cursor: pointer;
  user-select: none;
  margin-top: 4px;
  margin-bottom: 4px;
  width: fit-content;
}
.nb-advanced-toggle:hover {
  color: #d97706;
}

.nb-reset-btn {
  border: 1px solid #fcd34d;
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 0.75rem;
  background: #fff;
  color: #92400e;
  cursor: pointer;
  white-space: nowrap;
}
.nb-reset-btn:hover {
  background: #fef3c7;
}
/* ──────────────────────────────────────────────────────────────────────────── */
</style>

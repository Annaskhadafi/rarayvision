<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { API_BASE_URL } from '../utils'

const activeTab = ref('live') // 'live', 'upload', 'logs'

// Multi-select State
const selectedIds = ref(new Set())
const isBulkDeleting = ref(false)

// Live Camera State
const videoRef = ref(null)
const canvasRef = ref(null)
const overlayCanvasRef = ref(null)
const isCameraActive = ref(false)
const isAutoScanning = ref(false)
const isProcessing = ref(false)
const devices = ref([])
const selectedDeviceId = ref('')
const scanIntervalId = ref(null)
const scanCooldown = ref(false)

// Scan Results & Logs State
const latestScan = ref(null)
const scanLogs = ref([])
const isLoadingLogs = ref(false)
const isClearingEmpty = ref(false)
const searchQuery = ref('')
const selectedScanDetail = ref(null)
const imageErrors = ref({})

// File Upload State
const uploadFile = ref(null)
const uploadPreview = ref(null)
const isUploading = ref(false)

// Audio Beep generator using Web Audio API
const playBeep = () => {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(880, ctx.currentTime) // A5 note
    gain.gain.setValueAtTime(0.12, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + 0.25)
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.25)
  } catch (e) {
    console.log('Audio feedback not supported:', e)
  }
}

// Camera Initialization
const initCamera = async () => {
  try {
    const mediaDevices = await navigator.mediaDevices.enumerateDevices()
    devices.value = mediaDevices.filter(d => d.kind === 'videoinput')
    if (devices.value.length > 0) {
      selectedDeviceId.value = devices.value[0].deviceId
    }
    await startCamera()
  } catch (err) {
    console.error('Camera access error:', err)
  }
}

const startCamera = async () => {
  stopCamera()
  try {
    const constraints = {
      video: selectedDeviceId.value ? { deviceId: { exact: selectedDeviceId.value } } : { facingMode: 'environment' }
    }
    const stream = await navigator.mediaDevices.getUserMedia(constraints)
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      isCameraActive.value = true
    }
  } catch (err) {
    console.error('Failed to start camera:', err)
    isCameraActive.value = false
  }
}

const stopCamera = () => {
  stopAutoScan()
  clearOverlay()
  if (videoRef.value && videoRef.value.srcObject) {
    const tracks = videoRef.value.srcObject.getTracks()
    tracks.forEach(track => track.stop())
    videoRef.value.srcObject = null
  }
  isCameraActive.value = false
}

// Clear real-time detection overlay
const clearOverlay = () => {
  const overlay = overlayCanvasRef.value
  if (overlay) {
    const ctx = overlay.getContext('2d')
    ctx.clearRect(0, 0, overlay.width, overlay.height)
  }
}

// Draw bounding boxes on real-time detection overlay
const drawDetections = (detections = []) => {
  const overlay = overlayCanvasRef.value
  const video = videoRef.value
  if (!overlay || !video) return

  const ctx = overlay.getContext('2d')
  const width = video.clientWidth || 640
  const height = video.clientHeight || 480

  if (overlay.width !== width || overlay.height !== height) {
    overlay.width = width
    overlay.height = height
  }

  ctx.clearRect(0, 0, width, height)

  if (!detections || detections.length === 0) return

  detections.forEach(det => {
    const pts = det.norm_box
    if (!pts || pts.length < 4) return

    // Draw polygon bounding box
    ctx.beginPath()
    ctx.moveTo(pts[0][0] * width, pts[0][1] * height)
    for (let i = 1; i < pts.length; i++) {
      ctx.lineTo(pts[i][0] * width, pts[i][1] * height)
    }
    ctx.closePath()

    // Vibrant cyan box with translucent background
    ctx.strokeStyle = '#06b6d4'
    ctx.lineWidth = 2.5
    ctx.stroke()
    ctx.fillStyle = 'rgba(6, 182, 212, 0.15)'
    ctx.fill()

    // Draw text tag pill
    const x = Math.max(8, pts[0][0] * width)
    const y = Math.max(22, pts[0][1] * height - 8)
    const textLabel = det.text || ''
    
    ctx.font = 'bold 12px Inter, sans-serif'
    const textWidth = ctx.measureText(textLabel).width

    ctx.fillStyle = 'rgba(15, 23, 42, 0.88)'
    ctx.beginPath()
    ctx.roundRect(x - 4, y - 14, textWidth + 10, 18, 4)
    ctx.fill()

    ctx.fillStyle = '#38bdf8'
    ctx.fillText(textLabel, x + 1, y)
  })
}

// Auto Scanner Loop
const toggleAutoScan = () => {
  if (isAutoScanning.value) {
    stopAutoScan()
  } else {
    startAutoScan()
  }
}

const scanStatusText = ref('')

const startAutoScan = () => {
  if (!isCameraActive.value) return
  isAutoScanning.value = true
  scanStatusText.value = 'Auto Scanning...'
  scanIntervalId.value = setInterval(() => {
    if (!isProcessing.value && !scanCooldown.value) {
      captureAndExtractFrame('fast_ocr')
    }
  }, 600)
}

const stopAutoScan = () => {
  isAutoScanning.value = false
  scanStatusText.value = ''
  clearOverlay()
  if (scanIntervalId.value) {
    clearInterval(scanIntervalId.value)
    scanIntervalId.value = null
  }
}

// Fast Client-Side Image Compression for Field Mobile Networks (<30KB payload)
const compressImageForUpload = (file, maxWidth = 1200, quality = 0.80) => {
  return new Promise((resolve) => {
    const img = new Image()
    img.src = URL.createObjectURL(file)
    img.onload = () => {
      let width = img.width
      let height = img.height
      if (width > maxWidth) {
        height = Math.round((height * maxWidth) / width)
        width = maxWidth
      }
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      ctx.drawImage(img, 0, 0, width, height)
      canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality)
    }
    img.onerror = () => resolve(file)
  })
}

// Frame Capture & API Dispatch
const captureAndExtractFrame = async (mode = 'fast_ocr') => {
  if (!videoRef.value || !canvasRef.value) return
  const video = videoRef.value
  
  if (video.readyState < 2 || video.videoWidth === 0 || video.paused) {
    return
  }

  isProcessing.value = true
  scanStatusText.value = 'Processing Frame...'
  const canvas = canvasRef.value
  
  let w = video.videoWidth || 640
  let h = video.videoHeight || 480
  if (w > 1200) {
    h = Math.round((h * 1200) / w)
    w = 1200
  }
  canvas.width = w
  canvas.height = h
  
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, w, h)
  
  canvas.toBlob(async (blob) => {
    if (!blob) {
      isProcessing.value = false
      return
    }
    
    const formData = new FormData()
    formData.append('image', blob, 'frame.jpg')
    formData.append('mode', mode)
    
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/tire/extract`, {
        method: 'POST',
        body: formData
      })
      const data = await res.json()
      
      if (data.status === 'success' && data.data) {
        const detections = data.data.detections || []
        drawDetections(detections)

        const sn = data.data.serial_number || ''
        const brand = data.data.manufacturer || ''
        const size = data.data.size || ''
        const raw = data.data.raw_text || ''

        const hasValidData = (
          (sn && sn !== 'Tidak Ada Teks Terbaca' && !sn.toLowerCase().includes('safety')) ||
          (brand && brand !== 'Tidak Ditemukan') ||
          (size && size !== 'Tidak Ditemukan')
        )
        
        if (hasValidData) {
          latestScan.value = data.data
          scanStatusText.value = `SUCCESS: ${sn !== 'Tidak Ada Teks Terbaca' ? sn : brand + ' ' + size}`
          playBeep()

          if (data.data.saved) {
            fetchLogs()
          }
          
          // Cooldown trigger to prevent double scanning identical frame
          scanCooldown.value = true
          setTimeout(() => {
            scanCooldown.value = false
            if (isAutoScanning.value) scanStatusText.value = 'Auto Scanning...'
          }, 2500)
        } else if (raw) {
          scanStatusText.value = `Mendeteksi teks: ${raw.slice(0, 25)}...`
        } else {
          scanStatusText.value = isAutoScanning.value ? 'Auto Scanning...' : 'Frame Processed'
        }
      }
    } catch (e) {
      console.error('Extraction request failed:', e)
      scanStatusText.value = 'Connection error'
    } finally {
      isProcessing.value = false
    }
  }, 'image/jpeg', 0.80)
}

// File Upload Handler
const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) {
    uploadFile.value = file
    uploadPreview.value = URL.createObjectURL(file)
  }
}

const processUploadedFile = async () => {
  if (!uploadFile.value) return
  isUploading.value = true
  
  try {
    const compressedBlob = await compressImageForUpload(uploadFile.value, 1600, 0.85)
    const formData = new FormData()
    formData.append('image', compressedBlob, 'upload.jpg')
    formData.append('mode', 'upload')
    
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 15000)

    const res = await fetch(`${API_BASE_URL}/api/v1/tire/extract`, {
      method: 'POST',
      body: formData,
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    const data = await res.json()
    if (data.status === 'success' && data.data) {
      latestScan.value = data.data
      playBeep()
      await fetchLogs()
      activeTab.value = 'logs'
    }
  } catch (e) {
    console.error('File upload extraction error:', e)
    if (e.name === 'AbortError') {
      alert('OCR request timed out. Please check server connection.')
    } else {
      alert('Gagal mengekstrak teks ban dari file.')
    }
  } finally {
    isUploading.value = false
  }
}

// Fetch Logs
const fetchLogs = async () => {
  isLoadingLogs.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/tire/scans`)
    const data = await res.json()
    if (data.status === 'success') {
      scanLogs.value = data.data
    }
  } catch (e) {
    console.error('Error fetching tire logs:', e)
  } finally {
    isLoadingLogs.value = false
  }
}

const deleteScan = async (id) => {
  if (!confirm('Apakah Anda yakin ingin menghapus catatan ban ini?')) return
  try {
    await fetch(`${API_BASE_URL}/api/v1/tire/scans/${id}`, { method: 'DELETE' })
    fetchLogs()
    if (selectedScanDetail.value && selectedScanDetail.value.id === id) {
      selectedScanDetail.value = null
    }
  } catch (e) {
    console.error('Error deleting record:', e)
  }
}

// Clear Empty Logs (purges 200+ empty scans)
const clearEmptyLogs = async () => {
  if (!confirm('Hapus semua catatan scan yang gagal atau kosong (Tidak Ada Teks Terbaca)?')) return
  isClearingEmpty.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/tire/scans/clear-empty`, {
      method: 'DELETE'
    })
    const data = await res.json()
    if (data.status === 'success') {
      alert(data.message || `Berhasil menghapus ${data.deleted_count} log kosong`)
      await fetchLogs()
    }
  } catch (e) {
    console.error('Error clearing empty scans:', e)
    alert('Gagal membersihkan log kosong')
  } finally {
    isClearingEmpty.value = false
  }
}

const getImageUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return `${API_BASE_URL}${url}`
}

const filteredLogs = computed(() => {
  if (!searchQuery.value) return scanLogs.value
  const q = searchQuery.value.toLowerCase()
  return scanLogs.value.filter(s =>
    (s.serial_number && s.serial_number.toLowerCase().includes(q)) ||
    (s.dot_code && s.dot_code.toLowerCase().includes(q)) ||
    (s.manufacturer && s.manufacturer.toLowerCase().includes(q)) ||
    (s.size && s.size.toLowerCase().includes(q))
  )
})

const allSelected = computed(() => {
  return filteredLogs.value.length > 0 && filteredLogs.value.every(s => selectedIds.value.has(s.id))
})

const someSelected = computed(() => {
  return filteredLogs.value.some(s => selectedIds.value.has(s.id)) && !allSelected.value
})

const toggleSelectAll = () => {
  if (allSelected.value) {
    // Deselect all visible rows
    filteredLogs.value.forEach(s => selectedIds.value.delete(s.id))
  } else {
    // Select all visible rows
    filteredLogs.value.forEach(s => selectedIds.value.add(s.id))
  }
  // trigger reactivity
  selectedIds.value = new Set(selectedIds.value)
}

const toggleSelect = (id) => {
  const copy = new Set(selectedIds.value)
  if (copy.has(id)) {
    copy.delete(id)
  } else {
    copy.add(id)
  }
  selectedIds.value = copy
}

const bulkDelete = async () => {
  const count = selectedIds.value.size
  if (count === 0) return
  if (!confirm(`Apakah Anda yakin ingin menghapus ${count} catatan ban yang dipilih?`)) return
  isBulkDeleting.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const res = await fetch(`${API_BASE_URL}/api/v1/tire/scans/bulk-delete`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids })
    })
    const data = await res.json()
    if (data.status === 'success') {
      selectedIds.value = new Set()
      await fetchLogs()
    } else {
      // Fallback: delete one-by-one
      await Promise.all(ids.map(id =>
        fetch(`${API_BASE_URL}/api/v1/tire/scans/${id}`, { method: 'DELETE' })
      ))
      selectedIds.value = new Set()
      await fetchLogs()
    }
  } catch (e) {
    // Fallback: delete one-by-one
    try {
      const ids = Array.from(selectedIds.value)
      await Promise.all(ids.map(id =>
        fetch(`${API_BASE_URL}/api/v1/tire/scans/${id}`, { method: 'DELETE' })
      ))
      selectedIds.value = new Set()
      await fetchLogs()
    } catch (e2) {
      console.error('Bulk delete error:', e2)
      alert('Gagal menghapus catatan yang dipilih.')
    }
  } finally {
    isBulkDeleting.value = false
  }
}

onMounted(() => {
  fetchLogs()
  initCamera()
})

onUnmounted(() => {
  stopCamera()
})
</script>

<template>
  <div class="tire-container">
    <div class="page-header">
      <div class="title-wrap">
        <h2>Tire Sidewall OCR & Serial Number Extraction</h2>
        <p class="subtitle">Live continuous camera scanner & tire data management engine</p>
      </div>

      <!-- Navigation Tabs -->
      <div class="tab-pills">
        <button :class="{ active: activeTab === 'live' }" @click="activeTab = 'live'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
          Live Auto-Scanner
        </button>
        <button :class="{ active: activeTab === 'upload' }" @click="activeTab = 'upload'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          Image Upload
        </button>
        <button :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          Data Logs ({{ scanLogs.length }})
        </button>
      </div>
    </div>

    <!-- TAB 1: LIVE SCANNER -->
    <div v-if="activeTab === 'live'" class="live-grid">
      <div class="video-card glass-panel">
        <div class="video-header">
          <div class="status-badge" :class="{ scanning: isAutoScanning, active: isCameraActive }">
            <span class="pulse-dot"></span>
            {{ scanStatusText || (isAutoScanning ? (scanCooldown ? 'COOLDOWN (NEXT TIRE)' : 'AUTO SCANNING...') : (isCameraActive ? 'CAMERA READY' : 'CAMERA OFF')) }}
          </div>
          <div class="device-select" v-if="devices.length > 1">
            <select v-model="selectedDeviceId" @change="startCamera">
              <option v-for="d in devices" :key="d.deviceId" :value="d.deviceId">
                {{ d.label || 'Camera ' + d.deviceId.slice(0, 4) }}
              </option>
            </select>
          </div>
        </div>

        <div class="viewfinder">
          <video ref="videoRef" autoplay playsinline muted></video>
          <canvas ref="canvasRef" style="display: none;"></canvas>
          <!-- Real-Time Detection Bounding Box Overlay Canvas -->
          <canvas ref="overlayCanvasRef" class="detection-overlay"></canvas>

          <!-- Target Bounding Reticle -->
          <div class="target-box" :class="{ detected: latestScan && !scanCooldown }">
            <div class="corner tl"></div>
            <div class="corner tr"></div>
            <div class="corner bl"></div>
            <div class="corner br"></div>
            <div class="scan-line" v-if="isAutoScanning"></div>
            <div class="target-hint" v-if="!latestScan">Arahkan kamera ke dinding samping ban (sidewall)</div>
          </div>
        </div>

        <div class="controls-bar">
          <button class="btn btn-primary" :class="{ 'btn-danger': isAutoScanning }" @click="toggleAutoScan">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8" v-if="!isAutoScanning"/><rect x="9" y="9" width="6" height="6" v-else/>
            </svg>
            {{ isAutoScanning ? 'Stop Auto-Scan' : 'Mulai Realtime Auto-Scan' }}
          </button>
          
          <button class="btn btn-secondary" :disabled="isProcessing" @click="captureAndExtractFrame('manual')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            Snapshot Manual
          </button>
        </div>
      </div>

      <!-- Live Result Preview -->
      <div class="result-card glass-panel">
        <h3>Hasil Ekstraksi Ban</h3>
        <div v-if="latestScan" class="extracted-details">
          <div class="serial-hero">
            <span class="label">SERIAL NUMBER / DOT</span>
            <div class="value-badge">{{ latestScan.serial_number || latestScan.dot_code }}</div>
          </div>

          <div class="field-grid">
            <div class="field-item">
              <span class="field-label">Manufacturer / Merek</span>
              <span class="field-val highlight">{{ latestScan.manufacturer || '-' }}</span>
            </div>
            <div class="field-item">
              <span class="field-label">Model Ban</span>
              <span class="field-val">{{ latestScan.model_name || '-' }}</span>
            </div>
            <div class="field-item">
              <span class="field-label">Ukuran (Size)</span>
              <span class="field-val highlight">{{ latestScan.size || '-' }}</span>
            </div>
            <div class="field-item">
              <span class="field-label">Load / Speed Index</span>
              <span class="field-val">{{ latestScan.load_speed || '-' }}</span>
            </div>
            <div class="field-item">
              <span class="field-label">DOT Date Code</span>
              <span class="field-val">{{ latestScan.dot_code || '-' }}</span>
            </div>
            <div class="field-item">
              <span class="field-label">Tanda Khusus (Markings)</span>
              <span class="field-val">{{ latestScan.special_markings || '-' }}</span>
            </div>
          </div>

          <div class="image-thumb" v-if="latestScan.image_url">
            <img :src="getImageUrl(latestScan.image_url)" alt="Tire Crop" />
          </div>
        </div>

        <div v-else class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
          <p>Belum ada ban yang terpindai. Arahkan kamera ke ban untuk memulai deteksi realtime.</p>
        </div>
      </div>
    </div>

    <!-- TAB 2: IMAGE UPLOAD -->
    <div v-if="activeTab === 'upload'" class="upload-section glass-panel">
      <h3>Unggah Foto Ban untuk Analisis OCR</h3>
      <div class="dropzone" @click="$refs.fileInput.click()">
        <input type="file" ref="fileInput" accept="image/*" style="display: none;" @change="handleFileSelect" />
        <img v-if="uploadPreview" :src="uploadPreview" class="upload-preview-img" />
        <div v-else class="drop-text">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <p>Klik atau geser file gambar ban ke sini</p>
        </div>
      </div>

      <button v-if="uploadFile" class="btn btn-primary mt-4" :disabled="isUploading" @click="processUploadedFile">
        {{ isUploading ? 'Mengekstrak OCR...' : 'Jalankan Ekstraksi OCR' }}
      </button>
    </div>

    <!-- TAB 3: DATA LOGS TABLE -->
    <div v-if="activeTab === 'logs'" class="logs-section glass-panel">
      <div class="logs-header">
        <input type="text" v-model="searchQuery" placeholder="Cari berdasarkan Serial Number, Brand, Ukuran..." class="search-input" />
        <div class="header-actions">
          <button class="btn btn-outline-danger" :disabled="isClearingEmpty" @click="clearEmptyLogs" title="Hapus semua log yang tidak terbaca / kosong">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            {{ isClearingEmpty ? 'Membersihkan...' : 'Bersihkan Log Kosong' }}
          </button>
          <button class="btn btn-secondary" @click="fetchLogs">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            Refresh
          </button>
        </div>
      </div>

      <!-- Bulk Action Toolbar (shows when items selected) -->
      <div v-if="selectedIds.size > 0" class="bulk-toolbar">
        <span class="bulk-count">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          {{ selectedIds.size }} item dipilih
        </span>
        <div class="bulk-actions">
          <button class="btn btn-sm btn-outline-muted" @click="selectedIds = new Set()">
            Batalkan Pilihan
          </button>
          <button class="btn btn-sm btn-bulk-danger" :disabled="isBulkDeleting" @click="bulkDelete">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            {{ isBulkDeleting ? 'Menghapus...' : `Hapus ${selectedIds.size} Data` }}
          </button>
        </div>
      </div>

      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th class="cb-col">
                <input
                  type="checkbox"
                  class="row-checkbox"
                  :checked="allSelected"
                  :indeterminate="someSelected"
                  @change="toggleSelectAll"
                  title="Pilih Semua"
                />
              </th>
              <th>Foto</th>
              <th>Serial Number / DOT</th>
              <th>Manufacturer</th>
              <th>Model</th>
              <th>Ukuran (Size)</th>
              <th>Waktu Pindai</th>
              <th>Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="scan in filteredLogs" :key="scan.id" :class="{ 'row-selected': selectedIds.has(scan.id) }">
              <td class="cb-col">
                <input
                  type="checkbox"
                  class="row-checkbox"
                  :checked="selectedIds.has(scan.id)"
                  @change="toggleSelect(scan.id)"
                />
              </td>
              <td>
                <div class="thumb-wrapper" @click="selectedScanDetail = scan">
                  <img 
                    v-if="scan.image_url && !imageErrors[scan.id]" 
                    :src="getImageUrl(scan.image_url)" 
                    class="tbl-thumb" 
                    @error="imageErrors[scan.id] = true" 
                    alt="Tire"
                  />
                  <div v-else class="thumb-fallback" title="Tidak ada foto">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><path d="M4.93 4.93l4.24 4.24"/><path d="M14.83 14.83l4.24 4.24"/></svg>
                  </div>
                </div>
              </td>
              <td>
                <span class="sn-tag" :class="{ 'empty-tag': !scan.serial_number || scan.serial_number === 'Tidak Ada Teks Terbaca' }">
                  {{ scan.serial_number || scan.dot_code || 'Tidak Ada Teks' }}
                </span>
              </td>
              <td><strong>{{ scan.manufacturer || '-' }}</strong></td>
              <td>{{ scan.model_name || '-' }}</td>
              <td><span class="size-badge">{{ scan.size || '-' }}</span></td>
              <td>{{ new Date(scan.created_at).toLocaleString() }}</td>
              <td>
                <button class="icon-btn" @click="selectedScanDetail = scan" title="Lihat Detail">👁️</button>
                <button class="icon-btn danger" @click="deleteScan(scan.id)" title="Hapus">🗑️</button>
              </td>
            </tr>
            <tr v-if="filteredLogs.length === 0">
              <td colspan="8" class="text-center">Tidak ada catatan pemindaian ban.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- DETAIL MODAL -->
    <div v-if="selectedScanDetail" class="modal-overlay" @click.self="selectedScanDetail = null">
      <div class="modal-card glass-panel">
        <div class="modal-header">
          <h3>Detail Ban - {{ selectedScanDetail.serial_number }}</h3>
          <button class="close-btn" @click="selectedScanDetail = null">&times;</button>
        </div>
        <div class="modal-body">
          <div class="modal-img-wrap" v-if="selectedScanDetail.image_url">
            <img :src="getImageUrl(selectedScanDetail.image_url)" class="modal-img" alt="Tire Photo" />
          </div>
          <div class="modal-info">
            <p><strong>Manufacturer:</strong> {{ selectedScanDetail.manufacturer }}</p>
            <p><strong>Model:</strong> {{ selectedScanDetail.model_name }}</p>
            <p><strong>Size:</strong> {{ selectedScanDetail.size }}</p>
            <p><strong>Load/Speed:</strong> {{ selectedScanDetail.load_speed }}</p>
            <p><strong>DOT Date Code:</strong> {{ selectedScanDetail.dot_code }}</p>
            <p><strong>Raw OCR:</strong> <code>{{ selectedScanDetail.raw_text }}</code></p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tire-container {
  padding: 1.5rem;
  max-width: 1400px;
  margin: 0 auto;
  color: #0f172a;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}
.title-wrap h2 { margin: 0; font-size: 1.6rem; font-weight: 700; background: linear-gradient(135deg, #1e293b, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.subtitle { margin: 0.25rem 0 0; color: #64748b; font-size: 0.9rem; }

.tab-pills { display: flex; gap: 0.5rem; background: #e2e8f0; padding: 4px; border-radius: 12px; }
.tab-pills button { border: none; background: none; padding: 0.6rem 1rem; border-radius: 8px; font-weight: 600; font-size: 0.9rem; color: #475569; cursor: pointer; display: flex; align-items: center; gap: 0.5rem; transition: all 0.2s; }
.tab-pills button.active { background: #ffffff; color: #2563eb; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }

.glass-panel { background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(226, 232, 240, 0.8); border-radius: 16px; padding: 1.25rem; box-shadow: 0 4px 20px rgba(0,0,0,0.04); }

.live-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; }
@media (max-width: 900px) { .live-grid { grid-template-columns: 1fr; } }

.video-card { display: flex; flex-direction: column; gap: 1rem; }
.video-header { display: flex; justify-content: space-between; align-items: center; }
.status-badge { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.8rem; border-radius: 20px; font-size: 0.8rem; font-weight: 700; background: #f1f5f9; color: #64748b; }
.status-badge.active { background: #dcfce7; color: #166534; }
.status-badge.scanning { background: #dbeafe; color: #1e40af; }
.pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

.viewfinder { position: relative; width: 100%; aspect-ratio: 4/3; background: #0f172a; border-radius: 12px; overflow: hidden; }
.viewfinder video { width: 100%; height: 100%; object-fit: cover; }

.detection-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
}

.target-box { position: absolute; inset: 15%; border: 2px dashed rgba(255,255,255,0.4); border-radius: 12px; transition: border-color 0.3s; z-index: 2; }
.target-box.detected { border-color: #22c55e; border-style: solid; box-shadow: 0 0 20px rgba(34,197,94,0.5); }
.corner { position: absolute; width: 16px; height: 16px; border: 3px solid #3b82f6; }
.tl { top: -2px; left: -2px; border-right: none; border-bottom: none; }
.tr { top: -2px; right: -2px; border-left: none; border-bottom: none; }
.bl { bottom: -2px; left: -2px; border-right: none; border-top: none; }
.br { bottom: -2px; right: -2px; border-left: none; border-top: none; }

.scan-line { position: absolute; width: 100%; height: 2px; background: linear-gradient(90deg, transparent, #3b82f6, transparent); animation: scanAnim 2s infinite linear; }
@keyframes scanAnim { 0% { top: 0; } 100% { top: 100%; } }

.target-hint { position: absolute; bottom: 10px; width: 100%; text-align: center; color: rgba(255,255,255,0.8); font-size: 0.8rem; text-shadow: 0 1px 3px rgba(0,0,0,0.8); }

.controls-bar { display: flex; gap: 1rem; justify-content: center; }
.btn { padding: 0.75rem 1.25rem; border-radius: 10px; font-weight: 600; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: 0.5rem; transition: all 0.2s; font-size: 0.9rem; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover { background: #1d4ed8; }
.btn-danger { background: #dc2626 !important; }
.btn-secondary { background: #f1f5f9; color: #334155; }
.btn-outline-danger { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
.btn-outline-danger:hover { background: #fee2e2; }

.serial-hero { text-align: center; background: #eff6ff; padding: 1rem; border-radius: 12px; border: 1px solid #bfdbfe; margin-bottom: 1rem; }
.serial-hero .label { font-size: 0.75rem; font-weight: 700; color: #1e40af; }
.value-badge { font-size: 1.5rem; font-weight: 800; color: #1e3a8a; letter-spacing: 1px; margin-top: 0.25rem; }

.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1rem; }
.field-item { background: #f8fafc; padding: 0.6rem; border-radius: 8px; }
.field-label { font-size: 0.7rem; color: #64748b; display: block; }
.field-val { font-size: 0.9rem; font-weight: 600; color: #0f172a; }
.field-val.highlight { color: #2563eb; font-weight: 700; }

.image-thumb img { width: 100%; border-radius: 8px; max-height: 140px; object-fit: cover; }

.dropzone { border: 2px dashed #cbd5e1; border-radius: 12px; padding: 3rem; text-align: center; cursor: pointer; background: #f8fafc; }
.upload-preview-img { max-height: 300px; border-radius: 8px; }

.logs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; gap: 1rem; flex-wrap: wrap; }
.header-actions { display: flex; gap: 0.5rem; }
.search-input { flex: 1; min-width: 260px; padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #cbd5e1; font-size: 0.9rem; }

.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; text-align: left; }
.data-table th, .data-table td { padding: 0.75rem 1rem; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; }

.thumb-wrapper { width: 44px; height: 44px; border-radius: 6px; overflow: hidden; display: flex; align-items: center; justify-content: center; background: #f1f5f9; cursor: pointer; border: 1px solid #e2e8f0; }
.tbl-thumb { width: 100%; height: 100%; object-fit: cover; }
.thumb-fallback { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; background: #f8fafc; }

.sn-tag { background: #dbeafe; color: #1e40af; padding: 0.25rem 0.6rem; border-radius: 6px; font-weight: 700; font-family: monospace; font-size: 0.85rem; }
.sn-tag.empty-tag { background: #f1f5f9; color: #94a3b8; font-weight: 500; }
.size-badge { background: #f8fafc; border: 1px solid #e2e8f0; padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 600; }
.icon-btn { border: none; background: none; cursor: pointer; font-size: 1.1rem; padding: 0.2rem 0.4rem; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal-card { width: 90%; max-width: 600px; background: #fff; border-radius: 16px; padding: 1.5rem; max-height: 90vh; overflow-y: auto; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.close-btn { background: none; border: none; font-size: 1.5rem; cursor: pointer; }
.modal-img { width: 100%; max-height: 280px; object-fit: cover; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #e2e8f0; }

/* ─── Multi-Select & Bulk Delete ─── */
.cb-col { width: 44px; text-align: center; padding: 0 0.5rem !important; }
.row-checkbox {
  width: 16px; height: 16px; cursor: pointer;
  accent-color: #2563eb;
  border-radius: 4px;
}
.row-selected td { background: #eff6ff !important; }
.row-selected:hover td { background: #dbeafe !important; }

.bulk-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  padding: 0.6rem 1rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
  gap: 0.5rem;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.bulk-count {
  display: flex; align-items: center; gap: 0.4rem;
  font-weight: 700; color: #1e40af; font-size: 0.9rem;
}
.bulk-actions { display: flex; gap: 0.5rem; align-items: center; }
.btn-sm { padding: 0.4rem 0.85rem; font-size: 0.82rem; border-radius: 7px; }
.btn-outline-muted { background: #fff; color: #475569; border: 1px solid #cbd5e1; }
.btn-outline-muted:hover { background: #f1f5f9; }
.btn-bulk-danger {
  background: #dc2626; color: #fff; border: none;
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.btn-bulk-danger:hover:not(:disabled) { background: #b91c1c; }
.btn-bulk-danger:disabled { opacity: 0.65; cursor: not-allowed; }
</style>

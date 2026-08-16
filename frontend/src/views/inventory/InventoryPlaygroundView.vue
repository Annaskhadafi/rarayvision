<script setup>
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { inventoryService } from '../../services/inventoryService'
import { cameraService } from '../../services/cameraService'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

const getMediaUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http') || url.startsWith('data:')) return url
  return `${API_BASE_URL}${url}`
}

const activeTab = ref('count_boxes')
const outputMode = ref('image') // 'image' | 'video'
const imageFile = ref(null)
const imagePreview = ref('')
const isMediaVideo = ref(false)
const isProcessing = ref(false)
const confidenceOverride = ref(0.4)
const gridRows = ref(3)
const gridCols = ref(4)

const auditResult = ref(null)
const errorMsg = ref('')

// Camera Modal & Dual-Mode State
const showCameraModal = ref(false)
const cameraTab = ref('webcam') // 'webcam' | 'rtsp'
const webcamVideoRef = ref(null)
const webcamCanvasRef = ref(null)
const isWebcamActive = ref(false)
const webcamAnnotatedImg = ref('')
const webcamErrorMsg = ref('')
let isSendingFrame = false

// RTSP CCTV Stream State
const customRtspUrl = ref('')
const rtspFeedUrl = ref('')
const isConnectingRtsp = ref(false)

const startBrowserWebcam = async () => {
  webcamErrorMsg.value = ''
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true })
    if (webcamVideoRef.value) {
      webcamVideoRef.value.srcObject = stream
      webcamVideoRef.value.play()
    }
    isWebcamActive.value = true
    startAiInferenceLoop()
  } catch (err) {
    console.error('Webcam access error:', err)
    let msg = err.message || ''
    if (err.name === 'NotReadableError' || msg.includes('Could not start video source') || msg.includes('in use')) {
      webcamErrorMsg.value = '⚠️ Kamera webcam sedang digunakan/dikunci oleh tab browser lain (seperti Zoom/Meet/Tab Kamera aktif). Silakan tutup tab tersebut atau pindah ke Tab "🎥 RTSP / IP Camera CCTV" di atas.'
    } else if (err.name === 'NotAllowedError' || msg.includes('Permission denied')) {
      webcamErrorMsg.value = '⚠️ Izin kamera ditolak di browser. Silakan izinkan akses kamera di ikon gembok/kamera URL browser.'
    } else {
      webcamErrorMsg.value = `⚠️ Gagal mengakses webcam: ${msg}. Silakan coba Tab "🎥 RTSP / IP Camera CCTV".`
    }
  }
}

const stopBrowserWebcam = () => {
  isWebcamActive.value = false
  if (webcamVideoRef.value && webcamVideoRef.value.srcObject) {
    const tracks = webcamVideoRef.value.srcObject.getTracks()
    tracks.forEach(track => track.stop())
    webcamVideoRef.value.srcObject = null
  }
  webcamAnnotatedImg.value = ''
}

const startAiInferenceLoop = () => {
  const processNextFrame = async () => {
    if (!isWebcamActive.value) return
    if (!webcamVideoRef.value || !webcamCanvasRef.value) return

    if (!isSendingFrame) {
      isSendingFrame = true
      try {
        const video = webcamVideoRef.value
        const canvas = webcamCanvasRef.value
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          canvas.width = video.videoWidth
          canvas.height = video.videoHeight
          const ctx = canvas.getContext('2d')
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

          canvas.toBlob(async (blob) => {
            if (blob && isWebcamActive.value) {
              const formData = new FormData()
              formData.append('image', blob, 'webcam.jpg')
              formData.append('confidence_override', confidenceOverride.value)

              let res = null
              if (activeTab.value === 'count_boxes') {
                res = await inventoryService.countBoxes(formData)
              } else if (activeTab.value === 'defect_check') {
                res = await inventoryService.defectCheck(formData)
              } else {
                formData.append('grid_rows', gridRows.value)
                formData.append('grid_cols', gridCols.value)
                res = await inventoryService.shelfOccupancy(formData)
              }

              if (res && res.annotated_image) {
                webcamAnnotatedImg.value = res.annotated_image
              }
            }
            isSendingFrame = false
          }, 'image/jpeg', 0.75)
        } else {
          isSendingFrame = false
        }
      } catch (err) {
        console.error('Webcam AI frame error:', err)
        isSendingFrame = false
      }
    }

    if (isWebcamActive.value) {
      setTimeout(processNextFrame, 150)
    }
  }
  processNextFrame()
}

const connectRtspCamera = async () => {
  if (!customRtspUrl.value) {
    alert('Silakan masukkan URL RTSP / Stream Kamera IP terlebih dahulu.')
    return
  }
  isConnectingRtsp.value = true
  const mod = activeTab.value === 'count_boxes' ? 'inventory_count' : (activeTab.value === 'defect_check' ? 'inventory_defect' : 'inventory_shelf')

  try {
    const cam = await cameraService.addCamera({
      name: 'RTSP Testing Camera',
      stream_url: customRtspUrl.value,
      location: 'Gudang RTSP Testing',
      camera_type: 'rtsp',
      preset_brand: 'custom',
      enable_ai_overlay: true,
      ai_module: mod
    })
    rtspFeedUrl.value = cameraService.getFeedUrl(cam.id) + '?t=' + Date.now()
  } catch (err) {
    alert('Gagal menghubungkan ke RTSP stream: ' + err.message)
  }
  isConnectingRtsp.value = false
}

const switchCameraTab = (tab) => {
  cameraTab.value = tab
  if (tab === 'webcam') {
    rtspFeedUrl.value = ''
    setTimeout(startBrowserWebcam, 200)
  } else {
    stopBrowserWebcam()
  }
}

const openLiveCameraTest = () => {
  showCameraModal.value = true
  cameraTab.value = 'webcam'
  webcamAnnotatedImg.value = ''
  webcamErrorMsg.value = ''
  setTimeout(startBrowserWebcam, 300)
}

const closeLiveCameraModal = () => {
  stopBrowserWebcam()
  rtspFeedUrl.value = ''
  showCameraModal.value = false
}

const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) {
    imageFile.value = file
    imagePreview.value = URL.createObjectURL(file)
    isMediaVideo.value = file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)
    auditResult.value = null
    errorMsg.value = ''
  }
}

const runInventoryAudit = async () => {
  if (!imageFile.value) {
    errorMsg.value = 'Silakan pilih foto atau video gudang terlebih dahulu.'
    return
  }

  isProcessing.value = true
  errorMsg.value = ''
  auditResult.value = null

  const formData = new FormData()
  formData.append('image', imageFile.value)
  formData.append('confidence_override', confidenceOverride.value)
  formData.append('output_mode', outputMode.value)

  let res = null
  if (activeTab.value === 'count_boxes') {
    res = await inventoryService.countBoxes(formData)
  } else if (activeTab.value === 'defect_check') {
    res = await inventoryService.defectCheck(formData)
  } else if (activeTab.value === 'shelf_occupancy') {
    formData.append('grid_rows', gridRows.value)
    formData.append('grid_cols', gridCols.value)
    res = await inventoryService.shelfOccupancy(formData)
  }

  isProcessing.value = false

  if (res) {
    auditResult.value = res
  } else {
    errorMsg.value = 'Gagal memproses audit inventory. Pastikan file valid dan server terhubung.'
  }
}

onUnmounted(() => {
  stopBrowserWebcam()
})
</script>

<template>
  <div class="view-container">
    <!-- Header Navigation -->
    <div class="module-header">
      <div>
        <h1 class="page-title">📦 Smart Warehouse Inventory Vision</h1>
        <p class="page-subtitle">Penghitungan dus/pallet otomatis, analisis kepenuhan rak, dan deteksi kemasan cacat.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn active" @click="router.push('/inventory/playground')">🧪 Testing Playground</button>
        <button class="nav-btn" @click="router.push('/inventory/config')">⚙️ Target Config</button>
        <button class="nav-btn" @click="router.push('/inventory/history')">📜 Audit History</button>
      </div>
    </div>

    <!-- Sub-module Mode Tabs -->
    <div class="mode-selector">
      <button :class="['mode-tab', { active: activeTab === 'count_boxes' }]" @click="activeTab = 'count_boxes'; auditResult = null">
        🔢 Automatic Box / Pallet Count
      </button>
      <button :class="['mode-tab', { active: activeTab === 'defect_check' }]" @click="activeTab = 'defect_check'; auditResult = null">
        ⚠️ Packaging Defect Inspection
      </button>
      <button :class="['mode-tab', { active: activeTab === 'shelf_occupancy' }]" @click="activeTab = 'shelf_occupancy'; auditResult = null">
        📊 Shelf Occupancy Grid Analytics
      </button>
    </div>

    <div class="grid-layout">
      <!-- File Upload & Controls -->
      <div class="panel upload-panel">
        <h2>Upload Media Stock / Kamera Gudang</h2>

        <div class="drop-zone" @click="$refs.fileInput.click()">
          <input type="file" ref="fileInput" accept="image/*,video/*" class="file-input" @change="handleFileSelect" />
          
          <div v-if="!imagePreview" class="drop-content">
            <span class="upload-icon">📸</span>
            <p class="drop-title">Klik atau drag & drop foto / video di sini</p>
            <span class="file-hint">Mendukung JPG, PNG, WebP, MP4, MOV, AVI (Max 50MB)</span>
          </div>

          <video v-else-if="isMediaVideo" :src="imagePreview" controls autoplay loop class="preview-media"></video>
          <img v-else :src="imagePreview" alt="Preview" class="preview-media" />
        </div>

        <div class="controls">
          <div class="form-group">
            <label>Confidence Threshold: <strong>{{ confidenceOverride }}</strong></label>
            <input type="range" v-model.number="confidenceOverride" min="0.1" max="0.9" step="0.05" class="slider" />
          </div>

          <div v-if="activeTab === 'shelf_occupancy'" class="form-row">
            <div class="form-group flex-1">
              <label>Baris Grid</label>
              <input type="number" v-model.number="gridRows" min="1" max="10" class="input-field" />
            </div>
            <div class="form-group flex-1">
              <label>Kolom Grid</label>
              <input type="number" v-model.number="gridCols" min="1" max="10" class="input-field" />
            </div>
          </div>

          <div class="form-group">
            <label>Format Mode Output:</label>
            <div class="mode-radio-group">
              <label :class="['radio-pill', { active: outputMode === 'image' }]">
                <input type="radio" v-model="outputMode" value="image" class="radio-input" />
                🖼️ Snapshot Gambar (Cepat & Instan)
              </label>
              <label :class="['radio-pill', { active: outputMode === 'video' }]">
                <input type="radio" v-model="outputMode" value="video" class="radio-input" />
                🎬 Video Full Tracking (H.264 MP4)
              </label>
            </div>
          </div>

          <div class="action-btn-row">
            <button class="btn-primary flex-1" :disabled="isProcessing" @click="runInventoryAudit">
              <span v-if="isProcessing">⏳ Memproses Inference...</span>
              <span v-else>🚀 Jalankan Audit API</span>
            </button>

            <button class="btn-camera flex-1" @click="openLiveCameraTest">
              📷 Test Live Camera / Webcam
            </button>
          </div>
        </div>

        <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
      </div>

      <!-- Results Display Panel -->
      <div class="panel result-panel">
        <h2>Hasil Inference & Supervised Annotations</h2>

        <div v-if="!auditResult && !isProcessing" class="empty-state">
          <span class="empty-icon">📊</span>
          <p>Pilih foto atau video dan klik "Jalankan Audit API" untuk melihat visual hasil deteksi.</p>
        </div>

        <div v-if="isProcessing" class="loading-state">
          <div class="spinner"></div>
          <p>Memproses gambar via Roboflow / YOLO model...</p>
        </div>

        <div v-if="auditResult" class="result-content">
          <!-- Key Metrics -->
          <div class="metrics-grid">
            <div v-if="activeTab === 'count_boxes'" class="metric-card">
              <span class="metric-label">Total Dus / Pallet</span>
              <span class="metric-value">{{ auditResult.total_count }} pcs</span>
            </div>

            <div v-if="activeTab === 'defect_check'" :class="['metric-card', auditResult.defects_count > 0 ? 'danger' : 'success']">
              <span class="metric-label">Cacat Kemasan</span>
              <span class="metric-value">{{ auditResult.defects_count }} item</span>
            </div>

            <div v-if="activeTab === 'shelf_occupancy'" class="metric-card">
              <span class="metric-label">Occupancy Rate</span>
              <span class="metric-value">{{ auditResult.occupancy_rate }}%</span>
            </div>

            <div class="metric-card info">
              <span class="metric-label">Waktu Pemrosesan</span>
              <span class="metric-value">{{ auditResult.processing_ms }} ms</span>
            </div>
          </div>

          <!-- Visual Canvas Overlay or Video Player -->
          <div class="image-wrapper">
            <h3 v-if="auditResult.is_video">📹 Video Hasil Output (Object Tracking):</h3>
            <h3 v-else>Annotated Image (Supervision Output):</h3>

            <video v-if="auditResult.is_video" :src="getMediaUrl(auditResult.video_url)" controls autoplay loop class="annotated-img"></video>
            <img v-else :src="auditResult.annotated_image" alt="Supervised Result" class="annotated-img" />
          </div>

          <!-- Raw JSON Accordion -->
          <details class="json-details">
            <summary>🔍 Raw API Response Payload (JSON)</summary>
            <pre class="json-code">{{ JSON.stringify(auditResult, null, 2) }}</pre>
          </details>
        </div>
      </div>
    </div>

    <!-- Dual-Mode Live Camera Testing Modal -->
    <div v-if="showCameraModal" class="modal-backdrop" @click="closeLiveCameraModal">
      <div class="modal-content camera-modal" @click.stop>
        <div class="modal-header-row">
          <h2>📹 Testing Live Camera / Feed Real-Time</h2>
          <button class="close-btn" @click="closeLiveCameraModal">✖</button>
        </div>
        <p class="modal-subtitle">Uji coba deteksi AI langsung via Webcam Browser atau Stream RTSP CCTV IP Camera.</p>

        <!-- Camera Source Mode Tabs -->
        <div class="cam-tab-row">
          <button :class="['cam-tab-btn', { active: cameraTab === 'webcam' }]" @click="switchCameraTab('webcam')">
            💻 Webcam Laptop / Browser
          </button>
          <button :class="['cam-tab-btn', { active: cameraTab === 'rtsp' }]" @click="switchCameraTab('rtsp')">
            🎥 RTSP / IP Camera CCTV
          </button>
        </div>

        <!-- WEBCAM TAB -->
        <div v-if="cameraTab === 'webcam'" class="tab-body">
          <video ref="webcamVideoRef" muted playsinline style="display:none"></video>
          <canvas ref="webcamCanvasRef" style="display:none"></canvas>

          <div v-if="webcamErrorMsg" class="camera-error-box">
            <p>{{ webcamErrorMsg }}</p>
            <button class="btn-retry mt-10" @click="startBrowserWebcam">🔄 Coba Sambungkan Ulang Webcam</button>
          </div>

          <div v-else class="live-stream-box">
            <img v-if="webcamAnnotatedImg" :src="webcamAnnotatedImg" alt="Live AI Stream" class="live-mjpeg-stream" />
            <div v-else class="webcam-loading">
              <div class="spinner"></div>
              <p>Memulai webcam & menyambungkan AI overlay loop...</p>
            </div>
          </div>
        </div>

        <!-- RTSP CCTV TAB -->
        <div v-if="cameraTab === 'rtsp'" class="tab-body">
          <div class="rtsp-input-box">
            <label>Masukkan Stream URL RTSP / HTTP Kamera IP:</label>
            <div class="input-row">
              <input type="text" v-model="customRtspUrl" placeholder="rtsp://admin:pass@192.168.1.100:554/live" class="input-field flex-1" />
              <button class="btn-primary" :disabled="isConnectingRtsp" @click="connectRtspCamera">
                <span v-if="isConnectingRtsp">⏳ Sambungkan...</span>
                <span v-else>📡 Sambungkan RTSP</span>
              </button>
            </div>
          </div>

          <div class="live-stream-box mt-16">
            <img v-if="rtspFeedUrl" :src="rtspFeedUrl" alt="RTSP Live Feed" class="live-mjpeg-stream" />
            <div v-else class="webcam-loading">
              <span class="empty-icon">📡</span>
              <p>Masukkan URL RTSP di atas dan klik "Sambungkan RTSP" untuk memulai stream.</p>
            </div>
          </div>
        </div>

        <div class="modal-actions justify-end mt-16">
          <button class="btn-secondary" @click="closeLiveCameraModal">Tutup Stream</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view-container { padding: 24px; max-width: 1400px; margin: 0 auto; }
.module-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }
.page-title { font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
.page-subtitle { color: #475569; font-size: 14px; }
.sub-nav { display: flex; gap: 8px; }
.nav-btn { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; padding: 9px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.nav-btn.active, .nav-btn:hover { background: #2563eb; color: #ffffff; border-color: #2563eb; box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25); }

.mode-selector { display: flex; gap: 12px; margin-bottom: 24px; }
.mode-tab { flex: 1; background: #ffffff; border: 1px solid #cbd5e1; color: #334155; padding: 14px 18px; border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); transition: all 0.2s; }
.mode-tab.active { background: linear-gradient(135deg, #2563eb, #3b82f6); color: #ffffff; border-color: #2563eb; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); }

.grid-layout { display: grid; grid-template-columns: 400px 1fr; gap: 24px; }
.panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.panel h2 { font-size: 17px; font-weight: 700; color: #0f172a; margin-bottom: 18px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }

.drop-zone { border: 2px dashed #cbd5e1; background: #f8fafc; border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; margin-bottom: 20px; min-height: 220px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
.drop-zone:hover { border-color: #2563eb; background: #eff6ff; }
.file-input { display: none; }
.upload-icon { font-size: 40px; display: block; margin-bottom: 8px; }
.drop-title { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 4px; }
.file-hint { font-size: 12px; color: #64748b; }
.preview-media { max-width: 100%; max-height: 240px; border-radius: 8px; border: 1px solid #e2e8f0; }

.controls { display: flex; flex-direction: column; gap: 18px; }
.form-group { display: flex; flex-direction: column; gap: 8px; font-size: 14px; color: #0f172a; font-weight: 600; }
.form-row { display: flex; gap: 12px; }
.input-field { padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
.slider { width: 100%; accent-color: #2563eb; }
.btn-primary { background: #2563eb; color: #ffffff; border: none; padding: 12px 18px; border-radius: 10px; font-weight: 700; font-size: 14px; cursor: pointer; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25); transition: all 0.2s; }
.btn-primary:hover { background: #1d4ed8; }

.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-bottom: 20px; }
.metric-card { background: #f8fafc; padding: 16px; border-radius: 10px; display: flex; flex-direction: column; border: 1px solid #e2e8f0; border-left: 5px solid #2563eb; }
.metric-card.danger { border-left-color: #ef4444; }
.metric-card.success { border-left-color: #10b981; }
.metric-label { font-size: 12px; color: #64748b; font-weight: 600; margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: 800; color: #0f172a; }

.image-wrapper h3 { font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }
.annotated-img { width: 100%; border-radius: 10px; border: 1px solid #cbd5e1; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.empty-state, .loading-state { text-align: center; padding: 60px 20px; color: #475569; font-weight: 500; }
.empty-icon { font-size: 48px; display: block; margin-bottom: 12px; }
.spinner { width: 36px; height: 36px; border: 4px solid #e2e8f0; border-top-color: #2563eb; border-radius: 50%; animation: spin 1s infinite linear; margin: 0 auto 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
.json-details { margin-top: 24px; background: #0f172a; padding: 14px; border-radius: 10px; color: #f8fafc; }
.json-details summary { cursor: pointer; font-weight: 600; color: #38bdf8; }
.json-code { font-size: 12px; overflow-x: auto; color: #38bdf8; margin-top: 12px; }

.mode-radio-group { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.radio-pill { display: flex; align-items: center; gap: 10px; background: #f8fafc; border: 1px solid #cbd5e1; padding: 10px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; color: #334155; cursor: pointer; transition: all 0.2s; }
.radio-pill.active { background: #eff6ff; border-color: #2563eb; color: #1d4ed8; }
.radio-input { accent-color: #2563eb; }

.action-btn-row { display: flex; gap: 12px; margin-top: 12px; }
.flex-1 { flex: 1; }
.btn-camera { background: #334155; color: white; border: none; padding: 14px; border-radius: 10px; font-weight: 700; font-size: 14px; cursor: pointer; transition: all 0.2s; text-align: center; }
.btn-camera:hover { background: #1e293b; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.camera-modal { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; width: 780px; max-width: 95vw; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
.modal-header-row { display: flex; justify-content: space-between; align-items: center; }
.close-btn { background: transparent; border: none; font-size: 18px; cursor: pointer; color: #64748b; }
.modal-subtitle { font-size: 13px; color: #64748b; margin-top: 4px; margin-bottom: 16px; }

.cam-tab-row { display: flex; gap: 10px; margin-bottom: 16px; background: #f1f5f9; padding: 4px; border-radius: 8px; }
.cam-tab-btn { flex: 1; padding: 10px; border: none; background: transparent; color: #475569; font-weight: 600; font-size: 13px; border-radius: 6px; cursor: pointer; transition: all 0.2s; }
.cam-tab-btn.active { background: #ffffff; color: #0f172a; box-shadow: 0 2px 6px rgba(0,0,0,0.1); font-weight: 700; }

.live-stream-box { background: #0f172a; border-radius: 10px; overflow: hidden; display: flex; justify-content: center; align-items: center; min-height: 380px; }
.live-mjpeg-stream { width: 100%; max-height: 520px; object-fit: contain; border-radius: 8px; }
.webcam-loading { text-align: center; color: #94a3b8; padding: 40px; }

.camera-error-box { background: #fef2f2; border: 1px solid #fca5a5; border-radius: 10px; padding: 20px; color: #991b1b; font-size: 14px; font-weight: 600; text-align: center; line-height: 1.5; }
.btn-retry { background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 700; font-size: 13px; cursor: pointer; }
.mt-10 { margin-top: 10px; }

.rtsp-input-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
.rtsp-input-box label { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 8px; display: block; }
.input-row { display: flex; gap: 10px; }
.input-field { padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
.btn-secondary { background: #e2e8f0; color: #334155; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; }

.justify-end { justify-content: flex-end; }
.mt-16 { margin-top: 16px; }
</style>

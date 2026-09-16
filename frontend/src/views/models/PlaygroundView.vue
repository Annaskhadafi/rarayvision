<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { API_BASE_URL } from '../../utils'

// Active Model
const activeModel = ref(null)
const isModelLoading = ref(false)

// Source Mode: 'image' | 'video' | 'webcam' (Ultralytics Streamlit style)
const sourceMode = ref('image')

// Sliders (Ultralytics Hyperparameters)
const confThreshold = ref(0.25)
const iouThreshold = ref(0.45)

// Image Mode State
const selectedFile = ref(null)
const previewUrl = ref('')
const imageUrlInput = ref('')
const isPredicting = ref(false)
const predictionResult = ref(null)
const errorMessage = ref('')
const feedbackSubmitted = ref(null)
const isSubmittingFeedback = ref(false)
const feedbackNotes = ref('')
const showFeedbackModal = ref(false)

// Video Mode State
const videoFile = ref(null)
const isProcessingVideo = ref(false)
const videoResult = ref(null)
const videoProgressText = ref('')

// Webcam Mode State
const webcamVideo = ref(null)
const webcamCanvas = ref(null)
const webcamStream = ref(null)
const isWebcamActive = ref(false)
const isWebcamProcessing = ref(false)
const webcamDetections = ref([])
let webcamTimer = null
let webcamAnimationFrame = null
let lastDetectionAt = 0
const BOX_HOLD_MS = 1500

const fetchActiveModel = async () => {
  isModelLoading.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models`)
    const data = await res.json()
    if (res.ok) {
      activeModel.value = (data.models || []).find(m => m.is_active) || null
    }
  } catch (err) {
    console.error('Failed to fetch active model:', err)
  } finally {
    isModelLoading.value = false
  }
}

// -------------------------------------------------------------
// 1. IMAGE MODE HANDLERS
// -------------------------------------------------------------
const handleFileSelect = (e) => {
  const file = e.target.files[0]
  if (file) {
    selectedFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    predictionResult.value = null
    feedbackSubmitted.value = null
  }
}

const handleDrop = (e) => {
  e.preventDefault()
  const file = e.dataTransfer.files[0]
  if (file && file.type.startsWith('image/')) {
    selectedFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    predictionResult.value = null
    feedbackSubmitted.value = null
  }
}

const runImagePrediction = async () => {
  if (!selectedFile.value && !imageUrlInput.value) {
    alert('Pilih file gambar atau masukkan URL gambar terlebih dahulu!')
    return
  }

  isPredicting.value = true
  errorMessage.value = ''
  predictionResult.value = null
  feedbackSubmitted.value = null

  const formData = new FormData()
  if (selectedFile.value) {
    formData.append('file', selectedFile.value)
  } else if (imageUrlInput.value) {
    formData.append('image_url', imageUrlInput.value)
  }
  formData.append('conf_threshold', confThreshold.value)
  formData.append('iou_threshold', iouThreshold.value)

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/predict`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    if (res.ok) {
      predictionResult.value = data
      if (data.feedback_status === 'auto_labeled') {
        feedbackSubmitted.value = {
          status: 'auto_labeled',
          message: 'Sistem menandai hasil ini dengan kepercayaan tinggi (>88%).'
        }
      }
    } else {
      errorMessage.value = data.detail || 'Gagal menjalankan inferensi deteksi.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi ke backend inference endpoint gagal.'
  } finally {
    isPredicting.value = false
  }
}

const submitFeedback = async (statusVal) => {
  if (!predictionResult.value) return

  if (statusVal === 'bad' && !showFeedbackModal.value) {
    showFeedbackModal.value = true
    return
  }

  isSubmittingFeedback.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/feedback/${predictionResult.value.prediction_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback: statusVal,
        notes: feedbackNotes.value || null
      })
    })
    const data = await res.json()
    if (res.ok) {
      feedbackSubmitted.value = {
        status: statusVal,
        message: statusVal === 'good'
          ? 'Feedback "Akurat" tersimpan! Data ini masuk verifikasi auto-label di Label Studio.'
          : 'Feedback "Tidak Akurat" tersimpan! Gambar otomatis dimasukkan ke antrean Label Studio untuk re-labeling bulanan.'
      }
      showFeedbackModal.value = false
      feedbackNotes.value = ''
    } else {
      alert(data.detail || 'Gagal mengirimkan feedback.')
    }
  } catch (err) {
    alert('Koneksi backend error saat mengirim feedback.')
  } finally {
    isSubmittingFeedback.value = false
  }
}

// -------------------------------------------------------------
// 2. VIDEO MODE HANDLERS
// -------------------------------------------------------------
const handleVideoSelect = (e) => {
  const file = e.target.files[0]
  if (file) {
    videoFile.value = file
    videoResult.value = null
  }
}

const runVideoPrediction = async () => {
  if (!videoFile.value) {
    alert('Silakan pilih file video (MP4, AVI, MOV) terlebih dahulu!')
    return
  }

  isProcessingVideo.value = true
  videoProgressText.value = 'Mengunggah dan memproses frame video dengan YOLO...'
  videoResult.value = null
  errorMessage.value = ''

  const formData = new FormData()
  formData.append('video', videoFile.value)
  formData.append('conf_threshold', confThreshold.value)
  formData.append('iou_threshold', iouThreshold.value)

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/predict-video`, {
      method: 'POST',
      body: formData
    })
    const json = await res.json()
    if (res.ok && json.status === 'success') {
      videoResult.value = json.data
    } else {
      errorMessage.value = json.detail || json.message || 'Gagal memproses deteksi video.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi error saat memproses video.'
  } finally {
    isProcessingVideo.value = false
  }
}

// -------------------------------------------------------------
// 3. WEBCAM LIVE MODE HANDLERS (Ultralytics Streamlit style)
// -------------------------------------------------------------
const startWebcam = async () => {
  errorMessage.value = ''
  try {
    webcamStream.value = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30 } },
      audio: false
    })
    isWebcamActive.value = true
    await nextTick()
    if (webcamVideo.value) {
      webcamVideo.value.srcObject = webcamStream.value
      await webcamVideo.value.play()
    }
    webcamRenderLoop()
    processWebcamFrame()
  } catch (err) {
    errorMessage.value = `Gagal mengakses webcam: ${err.message}`
  }
}

const stopWebcam = () => {
  isWebcamActive.value = false
  if (webcamStream.value) {
    webcamStream.value.getTracks().forEach(track => track.stop())
    webcamStream.value = null
  }
  if (webcamTimer) {
    clearTimeout(webcamTimer)
    webcamTimer = null
  }
  if (webcamAnimationFrame) {
    cancelAnimationFrame(webcamAnimationFrame)
    webcamAnimationFrame = null
  }
  webcamDetections.value = []
}

const captureWebcamBlob = () => {
  const video = webcamVideo.value
  if (!video || !video.videoWidth) return null
  const offCanvas = document.createElement('canvas')
  offCanvas.width = 640
  offCanvas.height = Math.round((640 / video.videoWidth) * video.videoHeight)
  const ctx = offCanvas.getContext('2d')
  ctx.drawImage(video, 0, 0, offCanvas.width, offCanvas.height)
  return new Promise(resolve => offCanvas.toBlob(resolve, 'image/jpeg', 0.82))
}

const processWebcamFrame = async () => {
  if (!isWebcamActive.value) return
  if (isWebcamProcessing.value || !webcamVideo.value?.videoWidth) {
    webcamTimer = setTimeout(processWebcamFrame, 150)
    return
  }

  isWebcamProcessing.value = true
  try {
    const blob = await captureWebcamBlob()
    if (blob) {
      const formData = new FormData()
      formData.append('file', blob, 'frame.jpg')
      formData.append('conf_threshold', confThreshold.value)
      formData.append('iou_threshold', iouThreshold.value)

      const res = await fetch(`${API_BASE_URL}/api/v1/models/predict`, {
        method: 'POST',
        body: formData
      })
      const data = await res.json()
      if (res.ok && data.detections) {
        webcamDetections.value = data.detections
        if (data.detections.length > 0) {
          lastDetectionAt = performance.now()
        }
      }
    }
  } catch (err) {
    console.error('Webcam frame inference error:', err)
  } finally {
    isWebcamProcessing.value = false
    if (isWebcamActive.value) {
      webcamTimer = setTimeout(processWebcamFrame, 180)
    }
  }
}

const webcamRenderLoop = () => {
  if (!isWebcamActive.value) return
  drawWebcamCanvas()
  webcamAnimationFrame = requestAnimationFrame(webcamRenderLoop)
}

const drawWebcamCanvas = () => {
  const video = webcamVideo.value
  const canvas = webcamCanvas.value
  if (!video?.videoWidth || !canvas) return

  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
  }
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

  const detections = (performance.now() - lastDetectionAt <= BOX_HOLD_MS) ? webcamDetections.value : []
  const scaleX = canvas.width / (webcamVideo.value.videoWidth || 640)
  const scaleY = canvas.height / (webcamVideo.value.videoHeight || 480)

  ctx.lineWidth = Math.max(2, canvas.width / 320)
  ctx.font = `bold ${Math.max(14, canvas.width / 45)}px sans-serif`

  detections.forEach((det) => {
    const [x1, y1, x2, y2] = det.box
    const left = x1 * scaleX
    const top = y1 * scaleY
    const width = (x2 - x1) * scaleX
    const height = (y2 - y1) * scaleY
    const tag = `${det.label} ${(det.confidence * 100).toFixed(0)}%`

    ctx.strokeStyle = '#22c55e'
    ctx.fillStyle = '#22c55e'
    ctx.strokeRect(left, top, width, height)

    const tagWidth = ctx.measureText(tag).width + 10
    const tagY = Math.max(22, top)
    ctx.fillRect(left, tagY - 22, tagWidth, 22)
    ctx.fillStyle = '#ffffff'
    ctx.fillText(tag, left + 5, tagY - 6)
  })
}

const getFullUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE_URL}${url}`
}

onMounted(() => {
  fetchActiveModel()
})

onUnmounted(() => {
  stopWebcam()
})
</script>

<template>
  <div class="playground-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Ultralytics Object Detection Playground</h1>
        <p class="page-subtitle">
          Uji coba model aktif dengan 3 mode sumber (Foto, Video, atau Live Webcam) dan atur parameter deteksi secara real-time seperti di Streamlit Ultralytics.
        </p>
      </div>

      <!-- Active Model Banner -->
      <div class="active-model-pill">
        <span class="pulse-indicator"></span>
        <div class="model-info-text">
          <span class="caption">Model Aktif</span>
          <strong class="name">{{ activeModel ? `${activeModel.name} (${activeModel.version})` : 'YOLO Default' }}</strong>
        </div>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert alert-danger">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ errorMessage }}
    </div>

    <!-- Layout Grid -->
    <div class="playground-grid">
      <!-- Left Column: Controls & Configuration Panel (Streamlit Sidebar Style) -->
      <div class="panel control-panel">
        
        <!-- Source Selector Tabs (Streamlit Radio Buttons) -->
        <div class="source-selector-section">
          <label class="section-label">Pilih Sumber Input (Select Source)</label>
          <div class="source-pills">
            <button 
              class="source-pill-btn" 
              :class="{ active: sourceMode === 'image' }" 
              @click="sourceMode = 'image'; stopWebcam()"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
              Foto / Image
            </button>
            <button 
              class="source-pill-btn" 
              :class="{ active: sourceMode === 'video' }" 
              @click="sourceMode = 'video'; stopWebcam()"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              Video File
            </button>
            <button 
              class="source-pill-btn" 
              :class="{ active: sourceMode === 'webcam' }" 
              @click="sourceMode = 'webcam'"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              Live Camera
            </button>
          </div>
        </div>

        <hr class="panel-divider" />

        <!-- Ultralytics Hyperparameters Sliders -->
        <h3 class="subsection-title">Pengaturan Model (Model Config)</h3>
        
        <div class="control-group">
          <div class="slider-header">
            <label class="control-label">Model Confidence Threshold</label>
            <span class="slider-val">{{ (confThreshold * 100).toFixed(0) }}%</span>
          </div>
          <input 
            type="range" 
            min="0.05" 
            max="0.95" 
            step="0.05" 
            v-model.number="confThreshold" 
            class="slider" 
          />
          <span class="slider-hint">Ambang batas keyakinan objek minimum agar bounding box ditampilkan.</span>
        </div>

        <div class="control-group">
          <div class="slider-header">
            <label class="control-label">NMS / IoU Threshold</label>
            <span class="slider-val">{{ (iouThreshold * 100).toFixed(0) }}%</span>
          </div>
          <input 
            type="range" 
            min="0.1" 
            max="0.9" 
            step="0.05" 
            v-model.number="iouThreshold" 
            class="slider" 
          />
          <span class="slider-hint">Non-Maximum Suppression untuk menggabungkan kotak tumpang tindih.</span>
        </div>

        <hr class="panel-divider" />

        <!-- Source Specific Inputs -->

        <!-- 1. IMAGE MODE INPUTS -->
        <div v-if="sourceMode === 'image'">
          <h3 class="subsection-title">Unggah Foto</h3>
          <div 
            class="dropzone" 
            @dragover.prevent 
            @drop="handleDrop"
            @click="$refs.fileInput.click()"
          >
            <input 
              type="file" 
              ref="fileInput" 
              accept="image/*" 
              class="hidden-input" 
              @change="handleFileSelect" 
            />
            <svg viewBox="0 0 24 24" width="36" height="36" stroke="#94a3b8" stroke-width="1.5" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
            <div class="drop-text">
              <strong>Pilih atau Tarik Foto</strong>
              <span>Mendukung JPG, PNG, WebP</span>
            </div>
            <div v-if="selectedFile" class="selected-filename">
              {{ selectedFile.name }} ({{ (selectedFile.size / 1024).toFixed(0) }} KB)
            </div>
          </div>

          <div class="url-divider"><span>atau URL Foto</span></div>
          <div class="url-input-wrap">
            <input type="text" v-model="imageUrlInput" placeholder="https://example.com/image.jpg" class="form-input" />
          </div>

          <button 
            class="btn btn-primary btn-block btn-predict" 
            @click="runImagePrediction" 
            :disabled="isPredicting || (!selectedFile && !imageUrlInput)"
          >
            <span v-if="isPredicting" class="spinner-sm"></span>
            {{ isPredicting ? 'Menganalisis Gambar...' : 'Jalankan Deteksi Foto' }}
          </button>
        </div>

        <!-- 2. VIDEO MODE INPUTS -->
        <div v-else-if="sourceMode === 'video'">
          <h3 class="subsection-title">Unggah File Video</h3>
          <div class="dropzone" @click="$refs.videoInput.click()">
            <input 
              type="file" 
              ref="videoInput" 
              accept="video/mp4,video/avi,video/quicktime,video/webm" 
              class="hidden-input" 
              @change="handleVideoSelect" 
            />
            <svg viewBox="0 0 24 24" width="36" height="36" stroke="#94a3b8" stroke-width="1.5" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
            <div class="drop-text">
              <strong>Pilih File Video</strong>
              <span>MP4, AVI, MOV, WEBM</span>
            </div>
            <div v-if="videoFile" class="selected-filename">
              {{ videoFile.name }} ({{ (videoFile.size / (1024*1024)).toFixed(1) }} MB)
            </div>
          </div>

          <button 
            class="btn btn-primary btn-block btn-predict" 
            @click="runVideoPrediction" 
            :disabled="isProcessingVideo || !videoFile"
          >
            <span v-if="isProcessingVideo" class="spinner-sm"></span>
            {{ isProcessingVideo ? 'Memproses Deteksi Video...' : 'Proses Video dengan YOLO' }}
          </button>

          <p v-if="isProcessingVideo" class="text-xs text-blue-600 mt-2 text-center">
            {{ videoProgressText }}
          </p>
        </div>

        <!-- 3. WEBCAM MODE CONTROLS -->
        <div v-else-if="sourceMode === 'webcam'">
          <h3 class="subsection-title">Kontrol Live Kamera</h3>
          <p class="text-xs text-slate-500 mb-3">
            Preview browser berjalan 30 FPS; frame dikirim ke model untuk tracking kotak deteksi secara real-time.
          </p>
          <div class="webcam-btn-wrap">
            <button v-if="!isWebcamActive" class="btn btn-success btn-block" @click="startWebcam">
              📷 Nyalakan Kamera Webcam
            </button>
            <button v-else class="btn btn-danger btn-block" @click="stopWebcam">
              ⏹ Matikan Kamera
            </button>
          </div>
        </div>

        <!-- API Consumption Box -->
        <div class="api-info-box">
          <div class="api-info-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
            Inference Endpoints
          </div>
          <div class="api-code-snippet">POST /api/v1/models/predict</div>
          <div class="api-code-snippet">POST /api/v1/models/predict-video</div>
        </div>

      </div>

      <!-- Right Column: Visual Preview & Live Output Display -->
      <div class="panel preview-panel">
        
        <!-- HEADER PREVIEW -->
        <div class="preview-header">
          <h2 class="panel-title">Tampilan Hasil Prediksi</h2>
          
          <div v-if="sourceMode === 'image' && predictionResult" class="metrics-badges">
            <span class="badge badge-latency">{{ predictionResult.latency_ms }} ms</span>
            <span class="badge badge-count">{{ predictionResult.detection_count }} Objek</span>
            <span class="badge badge-conf">Top Conf: {{ (predictionResult.top_confidence * 100).toFixed(0) }}%</span>
            <span class="badge" :class="predictionResult.quality?.is_usable ? 'badge-good-quality' : 'badge-bad-quality'">
              {{ predictionResult.quality?.is_usable ? '✓ Quality Gate Pass' : '⚠ Quality Degraded' }}
            </span>
          </div>

          <div v-else-if="sourceMode === 'video' && videoResult" class="metrics-badges">
            <span class="badge badge-count">{{ videoResult.total_detections }} Detections</span>
            <span class="badge badge-latency">{{ videoResult.fps }} FPS</span>
            <span class="badge badge-conf">{{ videoResult.processed_frames }} Frames</span>
          </div>

          <div v-else-if="sourceMode === 'webcam' && isWebcamActive" class="metrics-badges">
            <span class="badge badge-active"><span class="status-dot pulse"></span> LIVE STREAMING</span>
            <span class="badge badge-count">{{ webcamDetections.length }} Objek</span>
          </div>
        </div>

        <!-- VIEWER WRAPPER -->
        <div class="image-viewer-wrap">
          
          <!-- 1. IMAGE DISPLAY -->
          <div v-if="sourceMode === 'image'">
            <div v-if="predictionResult" class="rendered-image-box">
              <img :src="getFullUrl(predictionResult.annotated_image_url)" alt="Predicted Output" class="main-image" />
            </div>
            <div v-else-if="previewUrl" class="rendered-image-box">
              <img :src="previewUrl" alt="Raw Preview" class="main-image opacity-80" />
              <div class="overlay-ready">Klik tombol "Jalankan Deteksi Foto"</div>
            </div>
            <div v-else class="empty-viewer">
              <svg viewBox="0 0 24 24" width="64" height="64" stroke="#cbd5e1" stroke-width="1" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
              <p>Pilih foto untuk memulai uji deteksi objek.</p>
            </div>
          </div>

          <!-- 2. VIDEO DISPLAY -->
          <div v-else-if="sourceMode === 'video'" class="w-full">
            <div v-if="videoResult" class="video-player-box">
              <video :src="getFullUrl(videoResult.video_url)" controls autoplay loop class="main-video"></video>
            </div>
            <div v-else class="empty-viewer">
              <svg viewBox="0 0 24 24" width="64" height="64" stroke="#cbd5e1" stroke-width="1" fill="none"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              <p>Unggah file video dan klik "Proses Video" untuk melihat deteksi bounding box per frame.</p>
            </div>
          </div>

          <!-- 3. WEBCAM DISPLAY -->
          <div v-else-if="sourceMode === 'webcam'" class="webcam-viewer-box">
            <video ref="webcamVideo" class="hidden-video" playsinline muted></video>
            <canvas ref="webcamCanvas" class="webcam-canvas"></canvas>
            <div v-if="!isWebcamActive" class="empty-viewer">
              <svg viewBox="0 0 24 24" width="64" height="64" stroke="#cbd5e1" stroke-width="1" fill="none"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              <p>Kamera belum aktif. Klik "Nyalakan Kamera Webcam" di sebelah kiri.</p>
            </div>
          </div>

        </div>

        <!-- QUALITY WARNING (IMAGE MODE) -->
        <div v-if="sourceMode === 'image' && predictionResult && !predictionResult.quality?.is_usable" class="quality-alert-banner">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          <div>
            <strong>Peringatan Kualitas Gambar (CV-Ops Gate):</strong>
            <div>{{ predictionResult.quality?.warnings?.join(', ') || 'Kualitas gambar rendah.' }}</div>
          </div>
        </div>

        <div v-if="sourceMode === 'image' && predictionResult && predictionResult.is_audit_sample" class="audit-sample-banner">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          <div>
            <strong>10% Random Human Audit Sample:</strong>
            <div>Gambar ini terpilih secara acak untuk diverifikasi manusia di Label Studio guna mencegah <em>confirmation bias</em>.</div>
          </div>
        </div>

        <!-- FEEDBACK SECTION (IMAGE MODE) -->
        <div v-if="sourceMode === 'image' && predictionResult" class="feedback-section">
          <div class="feedback-banner">
            <div class="feedback-prompt">
              <strong>Apakah hasil deteksi ini akurat?</strong>
              <span>Umpan balik Anda secara langsung melatih model generasi berikutnya via Label Studio & S3 Flywheel.</span>
            </div>

            <div class="feedback-buttons">
              <button class="btn btn-feedback-good" @click="submitFeedback('good')" :disabled="isSubmittingFeedback || feedbackSubmitted?.status === 'good'">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>
                Akurat (Thumbs Up)
              </button>
              <button class="btn btn-feedback-bad" @click="submitFeedback('bad')" :disabled="isSubmittingFeedback || feedbackSubmitted?.status === 'bad'">
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>
                Tidak Akurat (Koreksi)
              </button>
            </div>
          </div>

          <div v-if="feedbackSubmitted" class="feedback-status-box" :class="feedbackSubmitted.status">
            <span>{{ feedbackSubmitted.message }}</span>
          </div>
        </div>

        <!-- DETECTIONS BREAKDOWN (IMAGE MODE) -->
        <div v-if="sourceMode === 'image' && predictionResult && predictionResult.detections.length > 0" class="detections-card">
          <div class="detections-card-title">Objek Terdeteksi ({{ predictionResult.detections.length }})</div>
          <table class="sub-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Confidence</th>
                <th>Bounding Box [x1, y1, x2, y2]</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="det in predictionResult.detections" :key="det.id">
                <td><span class="label-pill">{{ det.label }}</span></td>
                <td>
                  <div class="conf-bar-wrap">
                    <div class="conf-bar" :style="{ width: `${det.confidence * 100}%` }"></div>
                    <span class="conf-text">{{ (det.confidence * 100).toFixed(1) }}%</span>
                  </div>
                </td>
                <td class="font-mono text-xs text-slate-500">[{{ det.box.join(', ') }}]</td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>

    <!-- Modal Feedback Notes (Bad feedback) -->
    <div v-if="showFeedbackModal" class="modal-overlay" @click.self="showFeedbackModal = false">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3 class="modal-title">Koreksi & Feedback Model</h3>
          <button class="btn-close" @click="showFeedbackModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <p class="text-sm text-slate-600 mb-3">
            Jelaskan kesalahan deteksi. Gambar ini akan dialirkan ke antrean Label Studio untuk dianotasi ulang pada siklus training bulanan.
          </p>
          <div class="form-group">
            <label class="form-label">Catatan Kesalahan (Opsional)</label>
            <textarea v-model="feedbackNotes" class="form-textarea" rows="3" placeholder="Contoh: Bounding box terpotong, atau objek terlewat..."></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showFeedbackModal = false">Batal</button>
          <button class="btn btn-primary" @click="submitFeedback('bad')">Kirim ke Review Queue</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.playground-container { padding: 8px 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-size: 1.5rem; font-weight: 700; color: #0f172a; margin: 0 0 6px 0; }
.page-subtitle { font-size: 0.875rem; color: #64748b; margin: 0; max-width: 650px; line-height: 1.5; }
.active-model-pill { display: flex; align-items: center; gap: 12px; background: white; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 9999px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.pulse-indicator { width: 10px; height: 10px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); animation: pulse-ring 1.8s infinite; }
@keyframes pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); } 70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); } }
.model-info-text .caption { display: block; font-size: 0.65rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
.model-info-text .name { font-size: 0.85rem; color: #1e293b; }
.playground-grid { display: grid; grid-template-columns: 360px 1fr; gap: 24px; }
@media (max-width: 1024px) { .playground-grid { grid-template-columns: 1fr; } }
.panel { background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
.panel-divider { border: none; border-top: 1px solid #f1f5f9; margin: 18px 0; }
.section-label { display: block; font-size: 0.8rem; font-weight: 700; color: #334155; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }
.subsection-title { font-size: 0.95rem; font-weight: 600; color: #1e293b; margin: 0 0 12px 0; }
.source-pills { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
.source-pill-btn { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 4px; font-size: 0.75rem; font-weight: 600; border: 1px solid #e2e8f0; border-radius: 6px; background: #f8fafc; color: #64748b; cursor: pointer; transition: all 0.2s; }
.source-pill-btn.active { background: #2563eb; color: white; border-color: #2563eb; box-shadow: 0 2px 4px rgba(37,99,235,0.2); }
.control-group { margin-bottom: 14px; }
.slider-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
.control-label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.slider-val { font-size: 0.8rem; font-weight: 600; color: #2563eb; }
.slider { width: 100%; accent-color: #2563eb; cursor: pointer; }
.slider-hint { display: block; font-size: 0.7rem; color: #94a3b8; margin-top: 2px; }
.dropzone { border: 2px dashed #cbd5e1; border-radius: 8px; padding: 20px 16px; text-align: center; cursor: pointer; background: #f8fafc; transition: all 0.2s; display: flex; flex-direction: column; align-items: center; gap: 8px; margin-bottom: 12px; }
.dropzone:hover { border-color: #2563eb; background: #eff6ff; }
.hidden-input { display: none; }
.drop-text strong { display: block; font-size: 0.85rem; color: #334155; }
.drop-text span { font-size: 0.75rem; color: #94a3b8; }
.selected-filename { font-size: 0.75rem; color: #16a34a; font-weight: 500; background: #dcfce7; padding: 4px 10px; border-radius: 4px; word-break: break-all; }
.url-divider { display: flex; align-items: center; text-align: center; margin: 10px 0; color: #94a3b8; font-size: 0.75rem; }
.url-divider::before, .url-divider::after { content: ''; flex: 1; border-bottom: 1px solid #e2e8f0; }
.url-divider span { padding: 0 8px; }
.url-input-wrap { margin-bottom: 16px; }
.form-input { width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.85rem; box-sizing: border-box; }
.btn-predict { padding: 11px; font-size: 0.9rem; font-weight: 600; }
.btn-block { width: 100%; }
.api-info-box { margin-top: 20px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; }
.api-info-title { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; font-weight: 600; color: #334155; margin-bottom: 6px; }
.api-code-snippet { background: #1e293b; color: #38bdf8; padding: 4px 8px; border-radius: 4px; font-size: 0.72rem; font-family: monospace; margin-bottom: 4px; }
.preview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.metrics-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.badge-latency { background: #f1f5f9; color: #475569; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 500; }
.badge-count { background: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
.badge-conf { background: #fef3c7; color: #b45309; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
.badge-active { background: #dcfce7; color: #166534; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; }
.badge-good-quality { background: #dcfce7; color: #15803d; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
.badge-bad-quality { background: #fee2e2; color: #b91c1c; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
.image-viewer-wrap { width: 100%; min-height: 420px; background: #0f172a; border-radius: 8px; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; }
.rendered-image-box { width: 100%; display: flex; justify-content: center; align-items: center; position: relative; }
.main-image { max-width: 100%; max-height: 560px; object-fit: contain; display: block; }
.video-player-box { width: 100%; display: flex; justify-content: center; }
.main-video { width: 100%; max-height: 540px; background: black; }
.webcam-viewer-box { width: 100%; display: flex; justify-content: center; position: relative; }
.hidden-video { display: none; }
.webcam-canvas { width: 100%; max-height: 540px; object-fit: contain; display: block; }
.overlay-ready { position: absolute; bottom: 20px; background: rgba(15, 23, 42, 0.85); color: white; padding: 6px 14px; border-radius: 9999px; font-size: 0.8rem; }
.empty-viewer { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #64748b; font-size: 0.875rem; padding: 40px; text-align: center; }
.quality-alert-banner { margin-top: 14px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 10px 14px; display: flex; gap: 10px; align-items: center; font-size: 0.825rem; color: #991b1b; }
.audit-sample-banner { margin-top: 10px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 10px 14px; display: flex; gap: 10px; align-items: center; font-size: 0.825rem; color: #1e40af; }
.feedback-section { margin-top: 18px; }
.feedback-banner { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
.feedback-prompt strong { display: block; font-size: 0.875rem; color: #1e293b; }
.feedback-prompt span { font-size: 0.75rem; color: #64748b; }
.feedback-buttons { display: flex; gap: 8px; }
.btn-feedback-good { background: #22c55e; color: white; display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 6px; border: none; font-size: 0.825rem; font-weight: 600; cursor: pointer; }
.btn-feedback-good:hover { background: #16a34a; }
.btn-feedback-bad { background: #ef4444; color: white; display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 6px; border: none; font-size: 0.825rem; font-weight: 600; cursor: pointer; }
.btn-feedback-bad:hover { background: #dc2626; }
.feedback-status-box { margin-top: 10px; padding: 8px 14px; border-radius: 6px; font-size: 0.825rem; }
.feedback-status-box.good { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
.feedback-status-box.bad { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
.feedback-status-box.auto_labeled { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
.detections-card { margin-top: 20px; border-top: 1px solid #f1f5f9; padding-top: 14px; }
.detections-card-title { font-size: 0.9rem; font-weight: 600; color: #1e293b; margin-bottom: 10px; }
.sub-table { width: 100%; border-collapse: collapse; }
.sub-table th { background: #f8fafc; padding: 6px 10px; font-size: 0.7rem; color: #64748b; text-transform: uppercase; text-align: left; }
.sub-table td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 0.8rem; }
.label-pill { background: #f1f5f9; color: #334155; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; }
.conf-bar-wrap { display: flex; align-items: center; gap: 6px; }
.conf-bar { height: 5px; background: #22c55e; border-radius: 9999px; min-width: 4px; }
.conf-text { font-size: 0.72rem; font-weight: 600; color: #475569; }
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 999; padding: 16px; }
.modal-content { background: white; border-radius: 12px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1); overflow: hidden; }
.modal-sm { max-width: 460px; }
.modal-header { padding: 16px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; }
.modal-title { font-size: 1.1rem; font-weight: 600; color: #1e293b; margin: 0; }
.btn-close { background: none; border: none; font-size: 1.4rem; color: #94a3b8; cursor: pointer; }
.modal-body { padding: 20px; }
.form-textarea { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.85rem; box-sizing: border-box; }
.modal-footer { padding: 14px 20px; background: #f8fafc; display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid #f1f5f9; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 16px; font-size: 0.85rem; font-weight: 500; border-radius: 6px; border: none; cursor: pointer; }
.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }
.btn-secondary { background: #f1f5f9; color: #475569; }
.btn-success { background: #16a34a; color: white; font-weight: 600; padding: 10px; }
.btn-success:hover { background: #15803d; }
.btn-danger { background: #dc2626; color: white; font-weight: 600; padding: 10px; }
.btn-danger:hover { background: #b91c1c; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
.status-dot.pulse { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); animation: pulse-ring 1.8s infinite; }
.spinner-sm { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>

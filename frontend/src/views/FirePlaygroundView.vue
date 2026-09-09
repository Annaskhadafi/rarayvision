<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { API_BASE_URL } from '../utils'
import { fireService } from '../services/fireService'

const fileInput = ref(null)
const selectedFile = ref(null)
const previewUrl = ref('')
const inputType = ref('image')
const result = ref(null)
const videoResult = ref(null)
const models = ref([])
const selectedModel = ref('onnx')
const confidence = ref(0.35)
const iou = ref(0.45)
const isProcessing = ref(false)
const errorMessage = ref('')
const webcamVideo = ref(null)
const webcamCanvas = ref(null)
const webcamCaptureCanvas = ref(null)
const webcamStream = ref(null)
const webcamResult = ref(null)
const webcamDetections = ref([])
const isWebcamActive = ref(false)
const isWebcamProcessing = ref(false)
let webcamTimer = null
let webcamAnimationFrame = null
let lastPositiveDetectionAt = 0
const BOX_HOLD_MS = 700

const selectedModelLabel = computed(() => {
  const item = models.value.find(model => model.id === selectedModel.value)
  return item ? `${item.label} · ${item.file}` : 'memuat...'
})

const annotatedVideoUrl = computed(() => {
  const path = videoResult.value?.video_url
  if (!path || /^https?:\/\//.test(path)) return path || ''
  return `${API_BASE_URL}${path}`
})

const drawWebcamFrame = () => {
  const video = webcamVideo.value
  const canvas = webcamCanvas.value
  if (!video?.videoWidth || !canvas) return
  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
  }
  const context = canvas.getContext('2d')
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  context.lineWidth = Math.max(2, canvas.width / 320)
  context.font = `bold ${Math.max(14, canvas.width / 45)}px sans-serif`
  const detections = performance.now() - lastPositiveDetectionAt <= BOX_HOLD_MS
    ? webcamDetections.value
    : []
  const sourceWidth = webcamResult.value?.image_width || canvas.width
  const sourceHeight = webcamResult.value?.image_height || canvas.height
  const scaleX = canvas.width / sourceWidth
  const scaleY = canvas.height / sourceHeight
  detections.forEach((detection) => {
    const [x1, y1, x2, y2] = detection.bbox
    const label = `${detection.class_name} ${(detection.confidence * 100).toFixed(1)}%`
    const left = x1 * scaleX
    const top = y1 * scaleY
    const width = (x2 - x1) * scaleX
    const height = (y2 - y1) * scaleY
    context.strokeStyle = '#ef4444'
    context.fillStyle = '#ef4444'
    context.strokeRect(left, top, width, height)
    const labelY = Math.max(24, top)
    context.fillRect(left, labelY - 24, context.measureText(label).width + 12, 24)
    context.fillStyle = '#ffffff'
    context.fillText(label, left + 6, labelY - 6)
  })
  if (isWebcamActive.value) {
    webcamAnimationFrame = window.requestAnimationFrame(drawWebcamFrame)
  }
}

const captureWebcamFrame = () => {
  const video = webcamVideo.value
  const canvas = webcamCaptureCanvas.value
  if (!video?.videoWidth || !canvas) return null
  const scale = Math.min(1, 640 / video.videoWidth)
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas
}

const updateWebcamDetections = (detectionResult) => {
  webcamResult.value = detectionResult
  if (detectionResult.detections.length) {
    webcamDetections.value = detectionResult.detections
    lastPositiveDetectionAt = performance.now()
  } else if (performance.now() - lastPositiveDetectionAt > BOX_HOLD_MS) {
    webcamDetections.value = []
  }
}

const chooseFile = (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  inputType.value = file.type.startsWith('video/') ? 'video' : 'image'
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  result.value = null
  videoResult.value = null
  errorMessage.value = ''
}

const detect = async () => {
  if (!selectedFile.value) {
    errorMessage.value = 'Pilih gambar atau video terlebih dahulu.'
    return
  }
  isProcessing.value = true
  errorMessage.value = ''
  try {
    if (inputType.value === 'video') {
      videoResult.value = await fireService.detectVideo(selectedFile.value, confidence.value, iou.value, selectedModel.value)
    } else {
      result.value = await fireService.detect(selectedFile.value, confidence.value, iou.value, selectedModel.value)
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isProcessing.value = false
  }
}

const processWebcamFrame = async () => {
  if (!isWebcamActive.value) return
  if (isWebcamProcessing.value || !webcamVideo.value?.videoWidth) {
    webcamTimer = window.setTimeout(processWebcamFrame, 250)
    return
  }
  isWebcamProcessing.value = true
  const canvas = captureWebcamFrame()
  try {
    const blob = canvas && await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.68))
    if (blob && isWebcamActive.value) {
      const detectionResult = await fireService.detect(blob, confidence.value, iou.value, selectedModel.value, false)
      updateWebcamDetections(detectionResult)
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isWebcamProcessing.value = false
    if (isWebcamActive.value) webcamTimer = window.setTimeout(processWebcamFrame, 250)
  }
}

const startWebcam = async () => {
  errorMessage.value = ''
  try {
    webcamStream.value = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    isWebcamActive.value = true
    await nextTick()
    webcamVideo.value.srcObject = webcamStream.value
    await webcamVideo.value.play()
    webcamAnimationFrame = window.requestAnimationFrame(drawWebcamFrame)
    processWebcamFrame()
  } catch (error) {
    stopWebcam()
    errorMessage.value = error.name === 'NotAllowedError'
      ? 'Izin webcam ditolak. Izinkan kamera dari pengaturan browser.'
      : `Webcam tidak dapat digunakan: ${error.message}`
  }
}

const stopWebcam = () => {
  isWebcamActive.value = false
  if (webcamTimer) window.clearTimeout(webcamTimer)
  webcamTimer = null
  if (webcamAnimationFrame) window.cancelAnimationFrame(webcamAnimationFrame)
  webcamAnimationFrame = null
  webcamDetections.value = []
  lastPositiveDetectionAt = 0
  webcamStream.value?.getTracks().forEach(track => track.stop())
  webcamStream.value = null
  if (webcamVideo.value) webcamVideo.value.srcObject = null
}

onMounted(async () => {
  try {
    models.value = await fireService.getModels()
    const selectedIsAvailable = models.value.some(model => model.id === selectedModel.value && model.available)
    if (!selectedIsAvailable) {
      const firstAvailable = models.value.find(model => model.available)
      if (firstAvailable) selectedModel.value = firstAvailable.id
    }
  } catch (error) {
    errorMessage.value = error.message
  }
})

onUnmounted(() => {
  stopWebcam()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <div class="fire-page">
    <div class="fire-header">
      <div>
        <p class="eyebrow">Computer Vision AI</p>
        <h1>🔥 Fire Detection Playground</h1>
        <p class="subtitle">Uji model YOLO hasil training Anda pada gambar, video, atau webcam.</p>
      </div>
      <div class="docs-actions">
        <a :href="`${API_BASE_URL}/docs#/Fire%20Detection`" target="_blank">Swagger</a>
        <a :href="`${API_BASE_URL}/redoc#tag/Fire-Detection`" target="_blank">ReDoc</a>
      </div>
    </div>

    <div class="model-strip">
      <span class="status-dot"></span>
      <label for="fire-model">Model uji:</label>
      <select id="fire-model" v-model="selectedModel" class="model-select" :disabled="isProcessing || isWebcamActive">
        <option v-for="item in models" :key="item.id" :value="item.id" :disabled="!item.available">
          {{ item.label }} · {{ item.file }}{{ item.available ? '' : ' (tidak tersedia)' }}
        </option>
      </select>
      <span>{{ selectedModelLabel }}</span>
    </div>

    <div class="fire-grid">
      <section class="panel">
        <h2>Input gambar atau video</h2>
        <div class="dropzone" role="button" tabindex="0" @click="fileInput.click()" @keydown.enter="fileInput.click()" @keydown.space.prevent="fileInput.click()">
          <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/x-msvideo,video/webm" hidden @change="chooseFile" />
          <video v-if="previewUrl && inputType === 'video'" :src="previewUrl" controls muted playsinline @click.stop />
          <img v-else-if="previewUrl" :src="previewUrl" alt="Preview input" />
          <template v-else>
            <span class="upload-icon">🎬</span>
            <strong>Klik untuk memilih gambar atau video</strong>
            <small>Gambar maks. 15 MB · Video MP4, MOV, AVI, WEBM maks. 100 MB</small>
          </template>
        </div>

        <div class="control">
          <label>Confidence <strong>{{ confidence.toFixed(2) }}</strong></label>
          <input v-model.number="confidence" type="range" min="0.05" max="0.95" step="0.05" />
        </div>
        <div class="control">
          <label>IoU <strong>{{ iou.toFixed(2) }}</strong></label>
          <input v-model.number="iou" type="range" min="0.05" max="0.95" step="0.05" />
        </div>

        <button class="detect-button" type="button" :disabled="isProcessing" @click="detect">
          {{ isProcessing ? (inputType === 'video' ? '⏳ Memproses video...' : '⏳ Memproses...') : `🔍 Deteksi Api${inputType === 'video' ? ' di Video' : ''}` }}
        </button>
        <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
      </section>

      <section class="panel result-panel">
        <div class="result-heading">
          <div>
            <h2>Hasil deteksi</h2>
            <p v-if="result">{{ result.detection_count }} objek · {{ result.processing_ms }} ms · {{ result.engine }}</p>
            <p v-else-if="videoResult">{{ videoResult.processed_frames }} frame · {{ videoResult.processing_ms }} ms · {{ videoResult.engine }}</p>
          </div>
          <span v-if="result" :class="['result-badge', result.detection_count ? 'found' : 'clear']">
            {{ result.detection_count ? 'API TERDETEKSI' : 'TIDAK ADA API' }}
          </span>
          <span v-else-if="videoResult" :class="['result-badge', videoResult.fire_frames ? 'found' : 'clear']">
            {{ videoResult.fire_frames ? 'API TERDETEKSI' : 'TIDAK ADA API' }}
          </span>
        </div>

        <div v-if="result" class="result-body">
          <img :src="result.annotated_image" alt="Hasil anotasi deteksi api" class="result-image" />
          <div v-if="result.detections.length" class="detections">
            <div v-for="(detection, index) in result.detections" :key="`${detection.class_id}-${index}`" class="detection-row">
              <strong>{{ detection.class_name }}</strong>
              <span>{{ (detection.confidence * 100).toFixed(1) }}%</span>
              <code>[{{ detection.bbox.join(', ') }}]</code>
            </div>
          </div>
        </div>
        <div v-else-if="videoResult" class="result-body">
          <video :src="annotatedVideoUrl" class="result-video" controls playsinline />
          <div class="video-stats">
            <div><strong>{{ videoResult.fire_frames }}</strong><span>Frame dengan api</span></div>
            <div><strong>{{ videoResult.processed_frames }}</strong><span>Frame diproses</span></div>
            <div><strong>{{ videoResult.total_detections }}</strong><span>Total deteksi</span></div>
            <div><strong>{{ videoResult.duration_seconds }} dtk</strong><span>Durasi video</span></div>
          </div>
          <a class="download-video" :href="annotatedVideoUrl" download>⬇ Unduh video hasil deteksi</a>
        </div>
        <div v-else class="empty-result">
          <span>🔥</span>
          <p>Hasil gambar atau video beranotasi akan tampil di sini.</p>
        </div>
      </section>
    </div>

    <section class="panel webcam-panel">
      <div class="result-heading">
        <div>
          <h2>Webcam live</h2>
          <p>Frame webcam dikirim ke API setiap ±1,2 detik.</p>
        </div>
        <button v-if="!isWebcamActive" class="webcam-button start" type="button" @click="startWebcam">📷 Mulai Webcam</button>
        <button v-else class="webcam-button stop" type="button" @click="stopWebcam">⏹ Stop Webcam</button>
      </div>
      <div v-if="isWebcamActive || webcamResult" class="webcam-grid">
        <video ref="webcamVideo" class="webcam-source" muted playsinline></video>
        <canvas ref="webcamCanvas" class="webcam-canvas"></canvas>
        <canvas ref="webcamCaptureCanvas" hidden></canvas>
      </div>
      <div v-else class="webcam-empty">Klik “Mulai Webcam” untuk menguji deteksi api dari kamera browser.</div>
      <p v-if="webcamResult" class="webcam-meta">
        {{ webcamResult.detection_count }} objek · {{ webcamResult.processing_ms }} ms
        <strong :class="webcamResult.detection_count ? 'fire-found' : 'fire-clear'">
          {{ webcamResult.detection_count ? 'API TERDETEKSI' : 'AMAN' }}
        </strong>
      </p>
    </section>
  </div>
</template>

<style scoped>
.fire-page { max-width: 1280px; margin: 0 auto; color: #172033; }
.fire-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.eyebrow { margin: 0 0 6px; color: #d97706; font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 6px; font-size: clamp(1.7rem, 3vw, 2.35rem); }
h2 { margin-bottom: 16px; font-size: 1.05rem; }
.subtitle { margin-bottom: 0; color: #64748b; }
.docs-actions { display: flex; gap: 8px; }
.docs-actions a { padding: 9px 12px; border: 1px solid #dbe3ef; border-radius: 9px; color: #334155; background: white; text-decoration: none; font-size: .85rem; font-weight: 700; }
.model-strip { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; padding: 11px 14px; margin-bottom: 18px; border: 1px solid #fde68a; border-radius: 10px; color: #713f12; background: #fffbeb; font-size: .9rem; }
.model-select { padding: 6px 9px; border: 1px solid #fbbf24; border-radius: 7px; color: #713f12; background: white; font-weight: 700; }
.model-strip span:last-child { color: #92400e; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #16a34a; }
.fire-grid { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); gap: 18px; }
.panel { padding: 20px; border: 1px solid #e2e8f0; border-radius: 16px; background: white; box-shadow: 0 8px 24px rgba(15, 23, 42, .05); }
.dropzone { display: grid; place-items: center; width: 100%; min-height: 275px; padding: 16px; border: 1.5px dashed #cbd5e1; border-radius: 12px; color: #475569; background: #f8fafc; }
.dropzone:hover { border-color: #f59e0b; background: #fffbeb; }
.dropzone img, .dropzone video { display: block; width: 100%; max-height: 310px; object-fit: contain; border-radius: 9px; }
.upload-icon { margin-bottom: 10px; font-size: 2.5rem; }
.dropzone small { margin-top: 7px; color: #94a3b8; }
.control { margin-top: 19px; }
.control label { display: flex; justify-content: space-between; margin-bottom: 7px; color: #475569; font-size: .88rem; }
.control input { width: 100%; accent-color: #f59e0b; }
.detect-button { width: 100%; margin-top: 22px; padding: 12px 16px; border: 0; border-radius: 10px; color: white; background: #d97706; font-weight: 800; }
.detect-button:hover { background: #b45309; }
.detect-button:disabled { cursor: wait; opacity: .65; }
.error { margin: 14px 0 0; color: #b91c1c; font-size: .9rem; }
.result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.result-heading p { margin: -9px 0 0; color: #64748b; font-size: .84rem; }
.result-badge { white-space: nowrap; padding: 6px 9px; border-radius: 999px; font-size: .72rem; font-weight: 800; }
.result-badge.found { color: #991b1b; background: #fee2e2; }
.result-badge.clear { color: #166534; background: #dcfce7; }
.result-image { display: block; width: 100%; max-height: 500px; object-fit: contain; border-radius: 10px; background: #0f172a; }
.result-video { display: block; width: 100%; max-height: 500px; border-radius: 10px; background: #0f172a; }
.video-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 13px; }
.video-stats div { display: flex; flex-direction: column; padding: 10px; border-radius: 9px; background: #fff7ed; }
.video-stats strong { color: #9a3412; font-size: 1rem; }
.video-stats span { margin-top: 3px; color: #64748b; font-size: .72rem; }
.download-video { display: block; margin-top: 12px; padding: 10px; border-radius: 9px; color: #fff; background: #2563eb; text-align: center; text-decoration: none; font-size: .85rem; font-weight: 800; }
.detections { margin-top: 13px; }
.detection-row { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; padding: 10px 0; border-bottom: 1px solid #eef2f7; }
.detection-row span { color: #b45309; font-weight: 800; }
.detection-row code { grid-column: 1 / -1; color: #64748b; font-size: .76rem; }
.empty-result { display: grid; place-items: center; min-height: 380px; color: #94a3b8; text-align: center; }
.empty-result span { font-size: 3.2rem; opacity: .65; }
.webcam-panel { margin-top: 18px; }
.webcam-panel h2 { margin-bottom: 4px; }
.webcam-panel .result-heading p { margin: 0; }
.webcam-button { padding: 9px 13px; border: 0; border-radius: 9px; color: white; font-size: .85rem; font-weight: 800; }
.webcam-button.start { background: #2563eb; }
.webcam-button.stop { background: #dc2626; }
.webcam-grid { position: relative; margin-top: 16px; overflow: hidden; border-radius: 10px; background: #0f172a; }
.webcam-source { display: none; }
.webcam-canvas { display: block; width: 100%; max-height: 560px; object-fit: contain; }
.webcam-empty { padding: 34px 16px; border: 1px dashed #cbd5e1; border-radius: 10px; color: #94a3b8; text-align: center; }
.webcam-meta { margin: 12px 0 0; color: #64748b; font-size: .86rem; }
.webcam-meta strong { margin-left: 8px; }
.fire-found { color: #b91c1c; }
.fire-clear { color: #15803d; }
@media (max-width: 840px) { .fire-header { align-items: flex-start; flex-direction: column; } .fire-grid { grid-template-columns: 1fr; } .video-stats { grid-template-columns: repeat(2, 1fr); } }
</style>

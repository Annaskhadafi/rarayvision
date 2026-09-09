<script setup>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { API_BASE_URL } from '../utils'
import { fireService } from '../services/fireService'

const fileInput = ref(null)
const selectedFile = ref(null)
const previewUrl = ref('')
const result = ref(null)
const model = ref(null)
const confidence = ref(0.35)
const iou = ref(0.45)
const isProcessing = ref(false)
const errorMessage = ref('')
const webcamVideo = ref(null)
const webcamCanvas = ref(null)
const webcamStream = ref(null)
const webcamResult = ref(null)
const isWebcamActive = ref(false)
const isWebcamProcessing = ref(false)
let webcamTimer = null

const chooseFile = (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  result.value = null
  errorMessage.value = ''
}

const detect = async () => {
  if (!selectedFile.value) {
    errorMessage.value = 'Pilih gambar terlebih dahulu.'
    return
  }
  isProcessing.value = true
  errorMessage.value = ''
  try {
    result.value = await fireService.detect(selectedFile.value, confidence.value, iou.value)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isProcessing.value = false
  }
}

const processWebcamFrame = async () => {
  if (!isWebcamActive.value || isWebcamProcessing.value || !webcamVideo.value?.videoWidth) return
  isWebcamProcessing.value = true
  const canvas = webcamCanvas.value
  const video = webcamVideo.value
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
  try {
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.78))
    if (blob && isWebcamActive.value) webcamResult.value = await fireService.detect(blob, confidence.value, iou.value)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    isWebcamProcessing.value = false
    if (isWebcamActive.value) webcamTimer = window.setTimeout(processWebcamFrame, 1200)
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
  webcamStream.value?.getTracks().forEach(track => track.stop())
  webcamStream.value = null
  if (webcamVideo.value) webcamVideo.value.srcObject = null
}

onMounted(async () => {
  try {
    model.value = await fireService.getModel()
  } catch (error) {
    errorMessage.value = error.message
  }
})

onUnmounted(stopWebcam)
</script>

<template>
  <div class="fire-page">
    <div class="fire-header">
      <div>
        <p class="eyebrow">Computer Vision AI</p>
        <h1>🔥 Fire Detection Playground</h1>
        <p class="subtitle">Uji model YOLO hasil training Anda pada gambar api/asap.</p>
      </div>
      <div class="docs-actions">
        <a :href="`${API_BASE_URL}/docs#/Fire%20Detection`" target="_blank">Swagger</a>
        <a :href="`${API_BASE_URL}/redoc#tag/Fire-Detection`" target="_blank">ReDoc</a>
      </div>
    </div>

    <div class="model-strip">
      <span class="status-dot"></span>
      <span>Model aktif: <strong>{{ model?.model || 'memuat...' }}</strong></span>
      <span v-if="model?.classes">Class: {{ Object.values(model.classes).join(', ') }}</span>
    </div>

    <div class="fire-grid">
      <section class="panel">
        <h2>Input gambar</h2>
        <button class="dropzone" type="button" @click="fileInput.click()">
          <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="chooseFile" />
          <img v-if="previewUrl" :src="previewUrl" alt="Preview input" />
          <template v-else>
            <span class="upload-icon">📷</span>
            <strong>Klik untuk memilih gambar</strong>
            <small>JPG, PNG, atau WEBP — maksimal 15 MB</small>
          </template>
        </button>

        <div class="control">
          <label>Confidence <strong>{{ confidence.toFixed(2) }}</strong></label>
          <input v-model.number="confidence" type="range" min="0.05" max="0.95" step="0.05" />
        </div>
        <div class="control">
          <label>IoU <strong>{{ iou.toFixed(2) }}</strong></label>
          <input v-model.number="iou" type="range" min="0.05" max="0.95" step="0.05" />
        </div>

        <button class="detect-button" type="button" :disabled="isProcessing" @click="detect">
          {{ isProcessing ? '⏳ Memproses...' : '🔍 Deteksi Api' }}
        </button>
        <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
      </section>

      <section class="panel result-panel">
        <div class="result-heading">
          <div>
            <h2>Hasil deteksi</h2>
            <p v-if="result">{{ result.detection_count }} objek terdeteksi · {{ result.processing_ms }} ms</p>
          </div>
          <span v-if="result" :class="['result-badge', result.detection_count ? 'found' : 'clear']">
            {{ result.detection_count ? 'API TERDETEKSI' : 'TIDAK ADA API' }}
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
        <div v-else class="empty-result">
          <span>🔥</span>
          <p>Hasil gambar beranotasi akan tampil di sini.</p>
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
        <div>
          <video ref="webcamVideo" class="webcam-video" muted playsinline></video>
          <canvas ref="webcamCanvas" hidden></canvas>
        </div>
        <div class="webcam-output">
          <img v-if="webcamResult" :src="webcamResult.annotated_image" alt="Hasil webcam deteksi api" />
          <span v-else>Menunggu frame pertama...</span>
        </div>
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
.model-strip span:last-child { color: #92400e; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #16a34a; }
.fire-grid { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); gap: 18px; }
.panel { padding: 20px; border: 1px solid #e2e8f0; border-radius: 16px; background: white; box-shadow: 0 8px 24px rgba(15, 23, 42, .05); }
.dropzone { display: grid; place-items: center; width: 100%; min-height: 275px; padding: 16px; border: 1.5px dashed #cbd5e1; border-radius: 12px; color: #475569; background: #f8fafc; }
.dropzone:hover { border-color: #f59e0b; background: #fffbeb; }
.dropzone img { display: block; width: 100%; max-height: 310px; object-fit: contain; border-radius: 9px; }
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
.webcam-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 16px; }
.webcam-video, .webcam-output { display: block; width: 100%; min-height: 230px; border-radius: 10px; background: #0f172a; object-fit: contain; }
.webcam-output { display: grid; place-items: center; color: #94a3b8; }
.webcam-output img { display: block; width: 100%; height: 100%; min-height: 230px; border-radius: 10px; object-fit: contain; }
.webcam-empty { padding: 34px 16px; border: 1px dashed #cbd5e1; border-radius: 10px; color: #94a3b8; text-align: center; }
.webcam-meta { margin: 12px 0 0; color: #64748b; font-size: .86rem; }
.webcam-meta strong { margin-left: 8px; }
.fire-found { color: #b91c1c; }
.fire-clear { color: #15803d; }
@media (max-width: 840px) { .fire-header { align-items: flex-start; flex-direction: column; } .fire-grid { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .webcam-grid { grid-template-columns: 1fr; } }
</style>

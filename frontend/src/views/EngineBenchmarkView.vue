<template>
  <div class="benchmark-view">
    <!-- Header -->
    <div class="header-section">
      <div>
        <h1 class="page-title">
          <span class="icon">⚡</span>
          Engine Benchmark & Model Switcher
        </h1>
        <p class="page-subtitle">
          Bandingkan performa kecepatan (latensi ms) dan akurasi antara <strong>Engine V1 (Standard Buffalo_L + FP32)</strong> dan <strong>Engine V2 (CPU Turbo Buffalo_S + INT8 Quantized)</strong> secara langsung di VPS Anda.
        </p>
      </div>
      <div class="header-actions">
        <!-- Global Engine Switcher Badge -->
        <div class="engine-switch-card">
          <div class="engine-info">
            <span class="engine-label">Global Active Engine:</span>
            <span class="engine-badge" :class="currentEngine">
              {{ currentEngine === 'v2' ? '🚀 Engine V2 (CPU Turbo)' : '🛡️ Engine V1 (Standard)' }}
            </span>
          </div>
          <button 
            class="btn-toggle-engine"
            :class="{ 'btn-v2': currentEngine === 'v1', 'btn-v1': currentEngine === 'v2' }"
            :disabled="isSwitchingEngine"
            @click="toggleGlobalEngine"
          >
            <span v-if="isSwitchingEngine">Switching...</span>
            <span v-else>
              Switch to {{ currentEngine === 'v1' ? 'Engine V2 (CPU Turbo)' : 'Engine V1 (Standard)' }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- Alert Status -->
    <div v-if="notificationMsg" class="alert-info">
      <span>{{ notificationMsg }}</span>
      <button @click="notificationMsg = ''" class="btn-close">×</button>
    </div>

    <!-- Main Grid -->
    <div class="main-grid">
      <!-- Left Panel: Input Image / Camera -->
      <div class="card input-card">
        <h2 class="card-title">1. Pilih Citra Wajah Uji</h2>

        <!-- Input Tabs -->
        <div class="input-tabs">
          <button 
            class="tab-btn" 
            :class="{ active: inputMethod === 'upload' }" 
            @click="inputMethod = 'upload'"
          >
            📁 Upload Foto
          </button>
          <button 
            class="tab-btn" 
            :class="{ active: inputMethod === 'camera' }" 
            @click="startCamera"
          >
            📷 Capture Webcam
          </button>
        </div>

        <!-- Upload Mode -->
        <div v-if="inputMethod === 'upload'" class="upload-section">
          <div 
            class="dropzone" 
            :class="{ active: isDragging, 'has-file': !!selectedFile }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleFileDrop"
            @click="$refs.fileInput.click()"
          >
            <input 
              ref="fileInput" 
              type="file" 
              accept="image/jpeg,image/png,image/webp" 
              class="hidden-input" 
              @change="handleFileChange"
            />
            <div v-if="!selectedFile" class="drop-placeholder">
              <span class="upload-icon">📸</span>
              <p class="drop-text">Drag & drop foto wajah di sini atau klik untuk browse</p>
              <span class="file-hint">JPG, PNG, WebP (Maks 5MB)</span>
            </div>
            <div v-else class="file-selected-box">
              <span class="file-icon">🖼️</span>
              <div class="file-details">
                <span class="file-name">{{ selectedFile.name }}</span>
                <span class="file-size">{{ (selectedFile.size / 1024).toFixed(1) }} KB</span>
              </div>
              <button class="btn-clear" @click.stop="clearFile">✕</button>
            </div>
          </div>
        </div>

        <!-- Camera Capture Mode -->
        <div v-if="inputMethod === 'camera'" class="camera-section">
          <div class="video-container">
            <video ref="videoEl" autoplay playsinline muted class="camera-video"></video>
            <canvas ref="canvasEl" class="hidden-canvas"></canvas>
          </div>
          <button class="btn btn-capture" @click="captureWebcamFrame">
            📸 Capture Frame Ini
          </button>
        </div>

        <!-- Image Preview -->
        <div v-if="previewUrl" class="preview-box">
          <div class="preview-header">
            <span>Preview Foto Uji</span>
          </div>
          <div class="image-wrapper">
            <img :src="previewUrl" alt="Face Preview" class="preview-image" />
          </div>
        </div>

        <!-- Run Benchmark Button -->
        <div class="action-footer">
          <button 
            class="btn btn-benchmark" 
            :disabled="(!selectedFile && !capturedBlob) || isRunningBenchmark"
            @click="runBenchmark"
          >
            <span v-if="isRunningBenchmark" class="spinner"></span>
            <span>{{ isRunningBenchmark ? 'Sedang Menjalankan Benchmark V1 vs V2...' : '⚡ Jalankan Benchmark Komparasi' }}</span>
          </button>
        </div>
      </div>

      <!-- Right Panel: Benchmark Results -->
      <div class="card result-card">
        <h2 class="card-title">2. Hasil Komparasi Performa (Side-by-Side)</h2>

        <div v-if="!benchmarkResult && !isRunningBenchmark" class="empty-state">
          <span class="empty-icon">📊</span>
          <h3>Belum ada data benchmark</h3>
          <p>Pilih atau capture foto wajah di panel sebelah kiri lalu klik <strong>Jalankan Benchmark Komparasi</strong> untuk menguji latensi dan akurasi kedua model secara real-time.</p>
        </div>

        <div v-if="isRunningBenchmark" class="loading-state">
          <div class="large-spinner"></div>
          <h3>Mengeksekusi model V1 (Standard) & V2 (CPU Turbo)...</h3>
          <p>Mengukur inferensi face detection, ArcFace embedding, dan ONNX anti-spoofing.</p>
        </div>

        <!-- Benchmark Display -->
        <div v-if="benchmarkResult && !isRunningBenchmark" class="results-container">
          <!-- Summary Banner -->
          <div class="summary-banner" :class="{ 'fast-win': benchmarkResult.comparison.speedup_ratio }">
            <div class="summary-metric">
              <span class="metric-title">Akselerasi Kecepatan</span>
              <span class="metric-val highlight">{{ benchmarkResult.comparison.speedup_ratio }}</span>
            </div>
            <div class="summary-metric">
              <span class="metric-title">Reduksi Latensi</span>
              <span class="metric-val green">{{ benchmarkResult.comparison.latency_reduction_percent }}% Lebih Cepat</span>
            </div>
            <div class="summary-metric">
              <span class="metric-title">Keselarasan Embedding</span>
              <span class="metric-val blue">{{ (benchmarkResult.comparison.embedding_similarity * 100).toFixed(1) }}% Match</span>
            </div>
          </div>

          <!-- Comparison Cards Grid -->
          <div class="comparison-grid">
            <!-- Engine V1 Card -->
            <div class="engine-box v1-box">
              <div class="box-header">
                <h3>🛡️ Engine V1 (Standard)</h3>
                <span class="badge-tag">Default / High-Res</span>
              </div>
              <div class="box-specs">
                <div class="spec-item"><strong>Detection:</strong> {{ benchmarkResult.v1_standard.model_detection }}</div>
                <div class="spec-item"><strong>ArcFace:</strong> {{ benchmarkResult.v1_standard.model_recognition }}</div>
                <div class="spec-item"><strong>Anti-Spoof:</strong> {{ benchmarkResult.v1_standard.model_antispoof }}</div>
              </div>
              
              <div class="box-metrics">
                <div class="metric-row">
                  <span>Total Latensi:</span>
                  <strong class="latency-value text-orange">{{ benchmarkResult.v1_standard.data.total_latency_ms }} ms</strong>
                </div>
                <div class="metric-row sub">
                  <span>• Face Deteksi:</span>
                  <span>{{ benchmarkResult.v1_standard.data.det_latency_ms }} ms</span>
                </div>
                <div class="metric-row sub">
                  <span>• Liveness Check:</span>
                  <span>{{ benchmarkResult.v1_standard.data.liveness_latency_ms }} ms</span>
                </div>
                <div class="metric-row">
                  <span>Status Liveness:</span>
                  <span :class="benchmarkResult.v1_standard.data.is_real ? 'text-green' : 'text-red'">
                    {{ benchmarkResult.v1_standard.data.is_real ? '✅ Real Face' : '❌ Spoof' }} ({{ (benchmarkResult.v1_standard.data.liveness_score * 100).toFixed(1) }}%)
                  </span>
                </div>
              </div>
            </div>

            <!-- Engine V2 Card -->
            <div class="engine-box v2-box">
              <div class="box-header">
                <h3>🚀 Engine V2 (CPU Turbo)</h3>
                <span class="badge-tag green">Optimized for Non-GPU VPS</span>
              </div>
              <div class="box-specs">
                <div class="spec-item"><strong>Detection:</strong> {{ benchmarkResult.v2_cpu_turbo.model_detection }}</div>
                <div class="spec-item"><strong>ArcFace:</strong> {{ benchmarkResult.v2_cpu_turbo.model_recognition }}</div>
                <div class="spec-item"><strong>Anti-Spoof:</strong> {{ benchmarkResult.v2_cpu_turbo.model_antispoof }}</div>
              </div>
              
              <div class="box-metrics">
                <div class="metric-row">
                  <span>Total Latensi:</span>
                  <strong class="latency-value text-green">{{ benchmarkResult.v2_cpu_turbo.data.total_latency_ms }} ms</strong>
                </div>
                <div class="metric-row sub">
                  <span>• Face Deteksi:</span>
                  <span>{{ benchmarkResult.v2_cpu_turbo.data.det_latency_ms }} ms</span>
                </div>
                <div class="metric-row sub">
                  <span>• Liveness Check:</span>
                  <span>{{ benchmarkResult.v2_cpu_turbo.data.liveness_latency_ms }} ms</span>
                </div>
                <div class="metric-row">
                  <span>Status Liveness:</span>
                  <span :class="benchmarkResult.v2_cpu_turbo.data.is_real ? 'text-green' : 'text-red'">
                    {{ benchmarkResult.v2_cpu_turbo.data.is_real ? '✅ Real Face' : '❌ Spoof' }} ({{ (benchmarkResult.v2_cpu_turbo.data.liveness_score * 100).toFixed(1) }}%)
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Recommendation Note -->
          <div class="note-box">
            <span class="note-icon">💡</span>
            <div class="note-text">
              <strong>Rekomendasi Implementasi:</strong>
              <p>Engine V2 menghasilkan embedding yang memiliki tingkat kesamaan tinggi dengan Engine V1, namun dengan beban CPU yang jauh lebih ringan dan eksekusi beberapa kali lebih cepat. Jika Anda menggunakan VPS tanpa GPU, <strong>Engine V2 adalah pilihan terbaik</strong> untuk menjaga latensi < 100ms dan RAM tetap hemat.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { API_BASE_URL } from '../utils'

const currentEngine = ref('v1')
const isSwitchingEngine = ref(false)
const notificationMsg = ref('')

const inputMethod = ref('upload')
const isDragging = ref(false)
const selectedFile = ref(null)
const capturedBlob = ref(null)
const previewUrl = ref(null)

const videoEl = ref(null)
const canvasEl = ref(null)
const mediaStream = ref(null)

const isRunningBenchmark = ref(false)
const benchmarkResult = ref(null)

const authHeaders = () => {
  const token = localStorage.getItem('rarayvision-token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

const fetchEngineMode = async () => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/system/engine-mode`, { headers: authHeaders() })
    const data = await res.json()
    if (data.status === 'success') {
      currentEngine.value = data.engine_mode || 'v1'
    }
  } catch (e) {
    console.error('Failed to fetch engine mode', e)
  }
}

const toggleGlobalEngine = async () => {
  const targetMode = currentEngine.value === 'v1' ? 'v2' : 'v1'
  isSwitchingEngine.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/system/engine-mode`, {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ engine_mode: targetMode })
    })
    const data = await res.json()
    if (res.ok && data.status === 'success') {
      currentEngine.value = data.engine_mode
      notificationMsg.value = `Engine berhasil diubah ke ${data.engine_mode === 'v2' ? 'Engine V2 (CPU Turbo)' : 'Engine V1 (Standard)'}!`
      setTimeout(() => { notificationMsg.value = '' }, 4000)
    }
  } catch (e) {
    notificationMsg.value = `Gagal mengubah engine: ${e.message}`
  } finally {
    isSwitchingEngine.value = false
  }
}

const handleFileChange = (e) => {
  const file = e.target.files[0]
  if (file) setInputFile(file)
}

const handleFileDrop = (e) => {
  isDragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) setInputFile(file)
}

const setInputFile = (file) => {
  selectedFile.value = file
  capturedBlob.value = null
  previewUrl.value = URL.createObjectURL(file)
  benchmarkResult.value = null
}

const clearFile = () => {
  selectedFile.value = null
  capturedBlob.value = null
  previewUrl.value = null
  benchmarkResult.value = null
}

const startCamera = async () => {
  inputMethod.value = 'camera'
  clearFile()
  try {
    mediaStream.value = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
    })
    if (videoEl.value) {
      videoEl.value.srcObject = mediaStream.value
    }
  } catch (e) {
    console.error('Camera error', e)
    notificationMsg.value = 'Gagal mengakses webcam: ' + e.message
  }
}

const stopCamera = () => {
  if (mediaStream.value) {
    mediaStream.value.getTracks().forEach(t => t.stop())
    mediaStream.value = null
  }
}

const captureWebcamFrame = () => {
  if (!videoEl.value || !canvasEl.value) return
  const video = videoEl.value
  const canvas = canvasEl.value
  canvas.width = video.videoWidth || 640
  canvas.height = video.videoHeight || 480
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  
  canvas.toBlob((blob) => {
    capturedBlob.value = blob
    previewUrl.value = URL.createObjectURL(blob)
    stopCamera()
    inputMethod.value = 'upload'
  }, 'image/jpeg', 0.92)
}

const runBenchmark = async () => {
  const fileToUpload = selectedFile.value || capturedBlob.value
  if (!fileToUpload) return

  isRunningBenchmark.value = true
  benchmarkResult.value = null
  notificationMsg.value = ''

  try {
    const fd = new FormData()
    fd.append('file', fileToUpload, 'benchmark_face.jpg')

    const res = await fetch(`${API_BASE_URL}/api/v1/faces/benchmark`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd
    })

    const data = await res.json()
    if (res.ok && data.status === 'success') {
      benchmarkResult.value = data
    } else {
      notificationMsg.value = `Benchmark Error: ${data.message || 'Unknown error'}`
    }
  } catch (e) {
    notificationMsg.value = `Benchmark Request Failed: ${e.message}`
  } finally {
    isRunningBenchmark.value = false
  }
}

onMounted(() => {
  fetchEngineMode()
})

onUnmounted(() => {
  stopCamera()
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
})
</script>

<style scoped>
.benchmark-view {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

.page-title {
  font-size: 1.6rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-color, #f1f5f9);
}

.page-subtitle {
  color: #94a3b8;
  font-size: 0.95rem;
  margin-top: 4px;
  max-width: 700px;
}

.engine-switch-card {
  background: rgba(30, 41, 59, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 12px 18px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.engine-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.engine-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 600;
}

.engine-badge {
  font-weight: 700;
  font-size: 0.9rem;
  padding: 3px 8px;
  border-radius: 6px;
}
.engine-badge.v1 {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.4);
}
.engine-badge.v2 {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.btn-toggle-engine {
  padding: 8px 16px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}
.btn-toggle-engine.btn-v2 {
  background: #10b981;
  color: white;
}
.btn-toggle-engine.btn-v2:hover {
  background: #059669;
}
.btn-toggle-engine.btn-v1 {
  background: #3b82f6;
  color: white;
}
.btn-toggle-engine.btn-v1:hover {
  background: #2563eb;
}

.alert-info {
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.3);
  color: #93c5fd;
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-close {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 1.2rem;
  cursor: pointer;
}

.main-grid {
  display: grid;
  grid-template-columns: 440px 1fr;
  gap: 24px;
}

@media (max-width: 1024px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 20px;
}

.card-title {
  font-size: 1.15rem;
  font-weight: 600;
  margin-bottom: 16px;
  color: #f8fafc;
}

.input-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 8px;
}

.tab-btn {
  background: transparent;
  border: none;
  padding: 8px 14px;
  border-radius: 6px;
  color: #94a3b8;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tab-btn.active {
  background: rgba(255, 255, 255, 0.1);
  color: #38bdf8;
}

.dropzone {
  border: 2px dashed rgba(255, 255, 255, 0.15);
  border-radius: 12px;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
}
.dropzone.active {
  border-color: #38bdf8;
  background: rgba(56, 189, 248, 0.05);
}
.dropzone.has-file {
  padding: 14px;
  border-style: solid;
  border-color: rgba(16, 185, 129, 0.4);
}

.hidden-input {
  display: none;
}

.drop-placeholder .upload-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 8px;
}

.drop-text {
  font-size: 0.9rem;
  color: #cbd5e1;
  margin-bottom: 4px;
}

.file-hint {
  font-size: 0.75rem;
  color: #64748b;
}

.file-selected-box {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.file-details {
  flex: 1;
  overflow: hidden;
}

.file-name {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #f1f5f9;
}

.file-size {
  font-size: 0.75rem;
  color: #94a3b8;
}

.camera-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.camera-video {
  width: 100%;
  border-radius: 10px;
  background: #000;
}

.hidden-canvas {
  display: none;
}

.btn-capture {
  background: #3b82f6;
  color: white;
  padding: 10px;
  border-radius: 8px;
  border: none;
  font-weight: 600;
  cursor: pointer;
}

.preview-box {
  margin-top: 16px;
  border-radius: 10px;
  overflow: hidden;
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.preview-header {
  padding: 8px 12px;
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #64748b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.image-wrapper {
  max-height: 220px;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #020617;
}

.preview-image {
  max-height: 220px;
  max-width: 100%;
  object-fit: contain;
}

.action-footer {
  margin-top: 20px;
}

.btn-benchmark {
  width: 100%;
  padding: 12px;
  border-radius: 10px;
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%);
  color: white;
  border: none;
  font-weight: 700;
  font-size: 0.95rem;
  cursor: pointer;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  transition: opacity 0.2s ease;
}
.btn-benchmark:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-state, .loading-state {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

.empty-icon {
  font-size: 3rem;
  display: block;
  margin-bottom: 12px;
}

.large-spinner {
  width: 48px;
  height: 48px;
  border: 4px solid rgba(255, 255, 255, 0.1);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.summary-banner {
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 12px;
  padding: 16px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.summary-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.metric-title {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: #94a3b8;
  margin-bottom: 4px;
}

.metric-val {
  font-size: 1.15rem;
  font-weight: 700;
}
.metric-val.highlight { color: #f59e0b; }
.metric-val.green { color: #10b981; }
.metric-val.blue { color: #38bdf8; }

.comparison-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}

@media (max-width: 768px) {
  .comparison-grid {
    grid-template-columns: 1fr;
  }
}

.engine-box {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 16px;
}
.engine-box.v2-box {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.03);
}

.box-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.box-header h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #f1f5f9;
}

.badge-tag {
  font-size: 0.7rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.1);
  color: #94a3b8;
}
.badge-tag.green {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.box-specs {
  font-size: 0.78rem;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
  background: rgba(0, 0, 0, 0.2);
  padding: 8px 10px;
  border-radius: 6px;
}

.box-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  color: #cbd5e1;
}

.metric-row.sub {
  font-size: 0.78rem;
  color: #64748b;
  padding-left: 8px;
}

.latency-value {
  font-size: 1.05rem;
}

.text-orange { color: #fb923c; }
.text-green { color: #34d399; }
.text-red { color: #f87171; }

.note-box {
  display: flex;
  gap: 12px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 10px;
  padding: 14px;
}

.note-icon {
  font-size: 1.4rem;
}

.note-text strong {
  color: #fbbf24;
  font-size: 0.85rem;
  display: block;
  margin-bottom: 2px;
}

.note-text p {
  color: #cbd5e1;
  font-size: 0.8rem;
  line-height: 1.4;
}
</style>

<template>
  <div class="anti-spoof-view">
    <!-- Header -->
    <div class="header-section">
      <div>
        <h1 class="page-title">
          <span class="icon">🛡️</span>
          Anti-Spoofing & Liveness Quality Lab
        </h1>
        <p class="page-subtitle">
          Komparasi kualitas dan akurasi deteksi pemalsuan wajah (Real vs Spoof Attack) antara engine <strong>Raray Vision Native ONNX</strong> dan <strong>UniFace MiniFASNet (V2 & V1SE)</strong>.
        </p>
      </div>
      <div class="header-actions">
        <a href="/docs#/Anti-Spoofing%20%26%20Liveness" target="_blank" class="btn-docs">
          <span class="doc-icon">📖</span> OpenAPI Docs
        </a>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert-error">
      <span>⚠️ {{ errorMessage }}</span>
      <button @click="errorMessage = ''" class="btn-close">×</button>
    </div>

    <!-- Main Grid -->
    <div class="main-grid">
      <!-- Input Panel -->
      <div class="card input-card">
        <h2 class="card-title">1. Input Citra / Kamera</h2>
        
        <!-- Input Method Tabs -->
        <div class="input-tabs">
          <button 
            class="tab-btn" 
            :class="{ active: inputMethod === 'upload' }" 
            @click="setInputMethod('upload')"
          >
            📁 Upload Foto
          </button>
          <button 
            class="tab-btn" 
            :class="{ active: inputMethod === 'camera' }" 
            @click="setInputMethod('camera')"
          >
            📷 Live Realtime Camera
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
              <span class="file-hint">Mendukung format JPG, PNG, WebP (maks 10MB)</span>
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

          <!-- Image Preview for Upload Mode -->
          <div v-if="previewUrl" class="preview-box">
            <div class="preview-header">
              <span>Preview Foto Masukan</span>
              <span v-if="result && result.detected_face_bbox" class="badge-bbox">
                Face Box: {{ result.detected_face_bbox.width }}×{{ result.detected_face_bbox.height }}px
              </span>
            </div>
            <div class="image-wrapper">
              <img ref="previewImg" :src="previewUrl" alt="Face Preview" class="preview-image" />
            </div>
          </div>

          <!-- Benchmark Action Button (Upload Mode) -->
          <div class="action-footer">
            <button 
              class="btn btn-benchmark" 
              :disabled="!selectedFile || isProcessing" 
              @click="runComparison"
            >
              <span v-if="isProcessing" class="spinner"></span>
              <span v-else>⚡ Jalankan Multi-Model Benchmark</span>
            </button>
          </div>
        </div>

        <!-- Live Camera Mode -->
        <div v-else class="camera-section">
          <div class="camera-wrapper">
            <video 
              v-show="isCameraStreaming" 
              ref="videoElement" 
              autoplay 
              playsinline 
              muted 
              class="camera-video"
              @loadedmetadata="onVideoMetadata"
            ></video>
            <!-- Canvas Overlay for Real-Time Bounding Box -->
            <canvas ref="overlayCanvas" class="camera-overlay"></canvas>
            <canvas ref="captureCanvas" style="display: none;"></canvas>

            <div v-if="!isCameraStreaming" class="camera-offline">
              <span class="cam-icon">📹</span>
              <p>Kamera belum aktif</p>
              <button class="btn btn-primary" @click="startCamera">Nyalakan Kamera</button>
            </div>

            <!-- Live Status HUD -->
            <div v-if="isCameraStreaming" class="camera-hud">
              <span class="hud-item" :class="isLiveDetecting ? 'hud-live' : 'hud-idle'">
                ● {{ isLiveDetecting ? 'LIVE DETECTION ON' : 'STANDBY' }}
              </span>
              <span v-if="isLiveDetecting" class="hud-item hud-fps">
                ⚡ {{ currentFps }} FPS | {{ lastLatency }} ms
              </span>
            </div>
          </div>

          <!-- Camera Action Controls -->
          <div v-if="isCameraStreaming" class="camera-controls-grid">
            <button 
              class="btn" 
              :class="isLiveDetecting ? 'btn-danger' : 'btn-success'" 
              @click="toggleLiveDetection"
            >
              {{ isLiveDetecting ? '⏹ Stop Live Detection' : '▶ Mulai Live Detection' }}
            </button>
            <button class="btn btn-secondary" @click="takeSnapshot">
              📸 Snapshot Single
            </button>
            <button class="btn btn-outline" @click="stopCamera">
              Tutup Kamera
            </button>
          </div>
        </div>
      </div>

      <!-- Results Panel -->
      <div class="card results-card">
        <div class="card-header-flex">
          <h2 class="card-title">2. Hasil Komparasi Kualitas Model</h2>
          <span v-if="isLiveDetecting" class="badge-live-pulse">🔴 Real-Time Stream</span>
        </div>

        <div v-if="!result && !isProcessing && !isLiveDetecting" class="empty-state">
          <span class="empty-icon">📊</span>
          <p class="empty-text">Pilih foto atau nyalakan kamera lalu jalankan benchmark.</p>
        </div>

        <div v-if="isProcessing && !isLiveDetecting" class="processing-state">
          <div class="pulse-spinner"></div>
          <p>Mengevaluasi foto pada 3 engine Anti-Spoofing secara bersamaan...</p>
          <span class="sub-proc">Raray Native ONNX • UniFace MiniFASNet V2 • UniFace V1SE</span>
        </div>

        <div v-if="result" class="results-content">
          <!-- Consensus Hero Card -->
          <div 
            class="consensus-card" 
            :class="result.consensus.verdict === 'REAL_PERSON' ? 'verdict-real' : 'verdict-spoof'"
          >
            <div class="consensus-badge">
              <span class="status-icon">
                {{ result.consensus.verdict === 'REAL_PERSON' ? '✅' : '🚨' }}
              </span>
              <div class="status-meta">
                <span class="consensus-title">
                  {{ result.consensus.verdict === 'REAL_PERSON' ? 'REAL PERSON (LIVE)' : 'SPOOF / ATTACK DETECTED' }}
                </span>
                <span class="consensus-sub">
                  Konsensus: {{ result.consensus.real_votes }}/{{ result.consensus.total_models }} Model Menyatakan Real ({{ result.consensus.agreement_rate }}% Agreement)
                </span>
              </div>
            </div>
            <div class="consensus-tags">
              <span class="tag-metric">⚡ Tercepat: {{ result.consensus.fastest_model }}</span>
              <span class="tag-metric">🎯 Keyakinan Tertinggi: {{ result.consensus.highest_confidence_model }}</span>
            </div>
          </div>

          <!-- Side-by-Side Model Cards -->
          <div class="models-grid">
            <!-- Model 1: Raray Vision Native -->
            <div class="model-card" :class="getModelCardClass(result.models.raray_native)">
              <div class="model-card-header">
                <span class="model-tag tag-raray">Native Engine</span>
                <span class="latency-badge">⏱️ {{ result.models.raray_native.latency_ms }} ms</span>
              </div>
              <h3 class="model-name">Raray Vision Native</h3>
              <p class="model-arch">MiniFASNetV2 (ONNX Runtime, Scale 2.7)</p>
              
              <div class="verdict-banner" :class="result.models.raray_native.is_real ? 'banner-real' : 'banner-spoof'">
                {{ result.models.raray_native.is_real ? 'REAL FACE' : 'SPOOF' }}
              </div>

              <div class="meter-group">
                <div class="meter-labels">
                  <span>Confidence Score</span>
                  <span class="score-val">{{ result.models.raray_native.confidence }}%</span>
                </div>
                <div class="meter-bar">
                  <div 
                    class="meter-fill" 
                    :class="result.models.raray_native.is_real ? 'fill-real' : 'fill-spoof'" 
                    :style="{ width: result.models.raray_native.confidence + '%' }"
                  ></div>
                </div>
              </div>
            </div>

            <!-- Model 2: UniFace V2 -->
            <div class="model-card" :class="getModelCardClass(result.models.uniface_v2)">
              <div class="model-card-header">
                <span class="model-tag tag-uniface">UniFace v4.0</span>
                <span class="latency-badge">⏱️ {{ result.models.uniface_v2.latency_ms }} ms</span>
              </div>
              <h3 class="model-name">UniFace MiniFASNet V2</h3>
              <p class="model-arch">Multi-Scale Contextual Engine (Scale 2.7)</p>
              
              <div class="verdict-banner" :class="result.models.uniface_v2.is_real ? 'banner-real' : 'banner-spoof'">
                {{ result.models.uniface_v2.is_real ? 'REAL FACE' : 'SPOOF' }}
              </div>

              <div class="meter-group">
                <div class="meter-labels">
                  <span>Confidence Score</span>
                  <span class="score-val">{{ result.models.uniface_v2.confidence }}%</span>
                </div>
                <div class="meter-bar">
                  <div 
                    class="meter-fill" 
                    :class="result.models.uniface_v2.is_real ? 'fill-real' : 'fill-spoof'" 
                    :style="{ width: result.models.uniface_v2.confidence + '%' }"
                  ></div>
                </div>
              </div>
            </div>

            <!-- Model 3: UniFace V1SE -->
            <div class="model-card" :class="getModelCardClass(result.models.uniface_v1se)">
              <div class="model-card-header">
                <span class="model-tag tag-se">UniFace SE-Attention</span>
                <span class="latency-badge">⏱️ {{ result.models.uniface_v1se.latency_ms }} ms</span>
              </div>
              <h3 class="model-name">UniFace MiniFASNet V1SE</h3>
              <p class="model-arch">Squeeze-and-Excitation (Wide Scale 4.0)</p>
              
              <div class="verdict-banner" :class="result.models.uniface_v1se.is_real ? 'banner-real' : 'banner-spoof'">
                {{ result.models.uniface_v1se.is_real ? 'REAL FACE' : 'SPOOF' }}
              </div>

              <div class="meter-group">
                <div class="meter-labels">
                  <span>Confidence Score</span>
                  <span class="score-val">{{ result.models.uniface_v1se.confidence }}%</span>
                </div>
                <div class="meter-bar">
                  <div 
                    class="meter-fill" 
                    :class="result.models.uniface_v1se.is_real ? 'fill-real' : 'fill-spoof'" 
                    :style="{ width: result.models.uniface_v1se.confidence + '%' }"
                  ></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Comparison Table -->
          <div class="metrics-table-wrapper">
            <h4 class="table-heading">Tabel Detail Parameter & Benchmark</h4>
            <table class="metrics-table">
              <thead>
                <tr>
                  <th>Model / Engine</th>
                  <th>Verdict</th>
                  <th>Confidence</th>
                  <th>Raw Score</th>
                  <th>Latency (ms)</th>
                  <th>Scale</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Raray Vision Native (ONNX)</strong></td>
                  <td>
                    <span :class="result.models.raray_native.is_real ? 'badge-real' : 'badge-spoof'">
                      {{ result.models.raray_native.verdict }}
                    </span>
                  </td>
                  <td>{{ result.models.raray_native.confidence }}%</td>
                  <td>{{ result.models.raray_native.score_raw }}</td>
                  <td>{{ result.models.raray_native.latency_ms }} ms</td>
                  <td>2.7</td>
                </tr>
                <tr>
                  <td><strong>UniFace MiniFASNet V2</strong></td>
                  <td>
                    <span :class="result.models.uniface_v2.is_real ? 'badge-real' : 'badge-spoof'">
                      {{ result.models.uniface_v2.verdict }}
                    </span>
                  </td>
                  <td>{{ result.models.uniface_v2.confidence }}%</td>
                  <td>{{ result.models.uniface_v2.score_raw }}</td>
                  <td>{{ result.models.uniface_v2.latency_ms }} ms</td>
                  <td>2.7</td>
                </tr>
                <tr>
                  <td><strong>UniFace MiniFASNet V1SE</strong></td>
                  <td>
                    <span :class="result.models.uniface_v1se.is_real ? 'badge-real' : 'badge-spoof'">
                      {{ result.models.uniface_v1se.verdict }}
                    </span>
                  </td>
                  <td>{{ result.models.uniface_v1se.confidence }}%</td>
                  <td>{{ result.models.uniface_v1se.score_raw }}</td>
                  <td>{{ result.models.uniface_v1se.latency_ms }} ms</td>
                  <td>4.0</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- API Integration Snippet -->
          <div class="code-snippet-box">
            <div class="snippet-header">
              <span>Integrasi API (cURL)</span>
              <button class="btn-copy" @click="copySnippet">
                {{ copyStatus ? 'Copied! ✓' : 'Copy' }}
              </button>
            </div>
            <pre class="snippet-code"><code>curl -X POST https://vision.chitraparatama.com/api/v1/anti-spoof/compare \
  -H "Authorization: Bearer &lt;YOUR_API_TOKEN&gt;" \
  -F "file=@face_photo.jpg"</code></pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { antiSpoofService } from '../services/antiSpoofService'

export default {
  name: 'AntiSpoofCompareView',
  data() {
    return {
      inputMethod: 'upload',
      selectedFile: null,
      previewUrl: '',
      isDragging: false,
      isProcessing: false,
      errorMessage: '',
      result: null,
      copyStatus: false,
      // Camera & Live Detection
      isCameraStreaming: false,
      isLiveDetecting: false,
      mediaStream: null,
      liveLoopTimer: null,
      isFrameInFlight: false,
      frameCount: 0,
      currentFps: 0,
      fpsTimer: null,
      lastLatency: 0
    }
  },
  beforeUnmount() {
    this.stopCamera()
    if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.previewUrl)
    }
    if (this.fpsTimer) clearInterval(this.fpsTimer)
  },
  methods: {
    setInputMethod(method) {
      this.inputMethod = method
      if (method === 'camera') {
        this.startCamera()
      } else {
        this.stopLiveDetection()
        this.stopCamera()
      }
    },
    handleFileChange(e) {
      const file = e.target.files[0]
      if (file) this.setFile(file)
    },
    handleFileDrop(e) {
      this.isDragging = false
      const file = e.dataTransfer.files[0]
      if (file) this.setFile(file)
    },
    setFile(file) {
      this.selectedFile = file
      this.errorMessage = ''
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl)
      }
      this.previewUrl = URL.createObjectURL(file)
      this.result = null
    },
    clearFile() {
      this.selectedFile = null
      if (this.previewUrl && this.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(this.previewUrl)
      }
      this.previewUrl = ''
      this.result = null
      if (this.$refs.fileInput) this.$refs.fileInput.value = ''
    },
    async startCamera() {
      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
        })
        if (this.$refs.videoElement) {
          this.$refs.videoElement.srcObject = this.mediaStream
        }
        this.isCameraStreaming = true
        this.errorMessage = ''
      } catch (err) {
        this.errorMessage = 'Gagal mengakses webcam: ' + err.message
      }
    },
    onVideoMetadata() {
      this.resizeOverlay()
    },
    resizeOverlay() {
      const video = this.$refs.videoElement
      const overlay = this.$refs.overlayCanvas
      if (video && overlay) {
        overlay.width = video.videoWidth || 640
        overlay.height = video.videoHeight || 480
      }
    },
    stopCamera() {
      this.stopLiveDetection()
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => track.stop())
        this.mediaStream = null
      }
      this.isCameraStreaming = false
      this.clearOverlay()
    },
    clearOverlay() {
      const overlay = this.$refs.overlayCanvas
      if (overlay) {
        const ctx = overlay.getContext('2d')
        ctx.clearRect(0, 0, overlay.width, overlay.height)
      }
    },
    toggleLiveDetection() {
      if (this.isLiveDetecting) {
        this.stopLiveDetection()
      } else {
        this.startLiveDetection()
      }
    },
    startLiveDetection() {
      if (!this.isCameraStreaming) return
      this.isLiveDetecting = true
      this.errorMessage = ''
      this.frameCount = 0
      this.currentFps = 0

      // FPS Counter
      if (this.fpsTimer) clearInterval(this.fpsTimer)
      this.fpsTimer = setInterval(() => {
        this.currentFps = this.frameCount
        this.frameCount = 0
      }, 1000)

      // Start continuous processing loop
      this.processLiveFrame()
    },
    stopLiveDetection() {
      this.isLiveDetecting = false
      if (this.liveLoopTimer) {
        clearTimeout(this.liveLoopTimer)
        this.liveLoopTimer = null
      }
      if (this.fpsTimer) {
        clearInterval(this.fpsTimer)
        this.fpsTimer = null
      }
      this.clearOverlay()
    },
    async processLiveFrame() {
      if (!this.isLiveDetecting || !this.isCameraStreaming) return

      const video = this.$refs.videoElement
      const canvas = this.$refs.captureCanvas
      if (!video || !canvas || video.readyState < 2) {
        this.liveLoopTimer = setTimeout(() => this.processLiveFrame(), 200)
        return
      }

      if (this.isFrameInFlight) {
        this.liveLoopTimer = setTimeout(() => this.processLiveFrame(), 100)
        return
      }

      this.isFrameInFlight = true
      const t0 = performance.now()

      canvas.width = 480
      canvas.height = 360
      const ctx = canvas.getContext('2d')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

      canvas.toBlob(async blob => {
        if (!blob || !this.isLiveDetecting) {
          this.isFrameInFlight = false
          return
        }

        try {
          const file = new File([blob], 'live_frame.jpg', { type: 'image/jpeg' })
          const res = await antiSpoofService.compare(file)
          
          if (res.status === 'success' && res.data) {
            this.result = res.data
            this.frameCount++
            this.lastLatency = Math.round(performance.now() - t0)
            this.drawLiveOverlay(res.data)
          }
        } catch {
          // Ignore transient frame errors during live stream
        } finally {
          this.isFrameInFlight = false
          if (this.isLiveDetecting) {
            // Schedule next frame with ~250ms throttle for smooth continuous stream
            this.liveLoopTimer = setTimeout(() => this.processLiveFrame(), 200)
          }
        }
      }, 'image/jpeg', 0.85)
    },
    drawLiveOverlay(data) {
      const overlay = this.$refs.overlayCanvas
      const video = this.$refs.videoElement
      if (!overlay || !video || !data.detected_face_bbox) return

      const ctx = overlay.getContext('2d')
      ctx.clearRect(0, 0, overlay.width, overlay.height)

      // Scale coordinates from captured size (480x360) to overlay size
      const scaleX = overlay.width / 480
      const scaleY = overlay.height / 360

      const bbox = data.detected_face_bbox
      const x = bbox.x1 * scaleX
      const y = bbox.y1 * scaleY
      const w = bbox.width * scaleX
      const h = bbox.height * scaleY

      const isReal = data.consensus.verdict === 'REAL_PERSON'
      const color = isReal ? '#22c55e' : '#ef4444'

      // Draw Box
      ctx.strokeStyle = color
      ctx.lineWidth = 4
      ctx.strokeRect(x, y, w, h)

      // Draw Header Tag
      const label = isReal 
        ? `REAL FACE (${data.consensus.agreement_rate}%)` 
        : `SPOOF ATTACK (${data.consensus.agreement_rate}%)`
      
      ctx.fillStyle = color
      ctx.fillRect(x, Math.max(0, y - 30), w, 30)

      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(label, x + w / 2, Math.max(20, y - 9))
    },
    takeSnapshot() {
      const video = this.$refs.videoElement
      const canvas = this.$refs.captureCanvas
      if (!video || !canvas) return

      canvas.width = video.videoWidth || 640
      canvas.height = video.videoHeight || 480
      const ctx = canvas.getContext('2d')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

      canvas.toBlob(blob => {
        const file = new File([blob], 'snapshot.jpg', { type: 'image/jpeg' })
        this.setFile(file)
        this.stopCamera()
        this.inputMethod = 'upload'
      }, 'image/jpeg', 0.95)
    },
    async runComparison() {
      if (!this.selectedFile) return
      this.isProcessing = true
      this.errorMessage = ''
      this.result = null

      try {
        const res = await antiSpoofService.compare(this.selectedFile)
        if (res.status === 'success' && res.data) {
          this.result = res.data
        } else {
          throw new Error(res.message || 'Gagal memproses perbandingan.')
        }
      } catch (err) {
        this.errorMessage = err.message || 'Terjadi kesalahan saat memproses anti-spoofing.'
      } finally {
        this.isProcessing = false
      }
    },
    getModelCardClass(model) {
      if (!model) return ''
      return model.is_real ? 'card-real' : 'card-spoof'
    },
    copySnippet() {
      const code = `curl -X POST https://vision.chitraparatama.com/api/v1/anti-spoof/compare \\\n  -H "Authorization: Bearer <YOUR_API_TOKEN>" \\\n  -F "file=@face_photo.jpg"`
      navigator.clipboard.writeText(code)
      this.copyStatus = true
      setTimeout(() => { this.copyStatus = false }, 2000)
    }
  }
}
</script>

<style scoped>
.anti-spoof-view {
  padding: 1.5rem;
  max-width: 1400px;
  margin: 0 auto;
  font-family: inherit;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.page-title {
  font-size: 1.6rem;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.4rem 0;
}

.page-subtitle {
  color: #64748b;
  font-size: 0.95rem;
  margin: 0;
}

.btn-docs {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.9rem;
  background: #f1f5f9;
  color: #334155;
  border-radius: 6px;
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  border: 1px solid #e2e8f0;
  transition: all 0.2s;
}

.btn-docs:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.alert-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  padding: 0.8rem 1rem;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.btn-close {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  color: #b91c1c;
  cursor: pointer;
}

.main-grid {
  display: grid;
  grid-template-columns: 460px 1fr;
  gap: 1.5rem;
}

@media (max-width: 1100px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.25rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.card-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.badge-live-pulse {
  background: #fee2e2;
  color: #ef4444;
  font-weight: 700;
  font-size: 0.75rem;
  padding: 3px 8px;
  border-radius: 20px;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.card-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 1rem 0;
}

.input-tabs {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 8px;
  margin-bottom: 1rem;
}

.tab-btn {
  flex: 1;
  padding: 0.5rem;
  border: none;
  background: transparent;
  font-size: 0.85rem;
  font-weight: 500;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 1.5rem 1rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.dropzone:hover, .dropzone.active {
  border-color: #3b82f6;
  background: #f8fafc;
}

.hidden-input {
  display: none;
}

.upload-icon {
  font-size: 2.2rem;
  margin-bottom: 0.4rem;
}

.drop-text {
  font-size: 0.88rem;
  font-weight: 500;
  color: #334155;
  margin: 0 0 0.3rem 0;
}

.file-hint {
  font-size: 0.75rem;
  color: #94a3b8;
}

.file-selected-box {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  text-align: left;
}

.file-icon {
  font-size: 1.8rem;
}

.file-details {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.file-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 0.85rem;
  word-break: break-all;
}

.file-size {
  font-size: 0.75rem;
  color: #64748b;
}

.btn-clear {
  background: #fee2e2;
  border: none;
  color: #ef4444;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  cursor: pointer;
}

.camera-wrapper {
  position: relative;
  background: #0f172a;
  border-radius: 10px;
  overflow: hidden;
  height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.camera-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.camera-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.camera-hud {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  display: flex;
  justify-content: space-between;
  pointer-events: none;
}

.hud-item {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 6px;
  backdrop-filter: blur(4px);
}

.hud-live {
  background: rgba(239, 68, 68, 0.85);
  color: white;
}

.hud-idle {
  background: rgba(15, 23, 42, 0.75);
  color: #94a3b8;
}

.hud-fps {
  background: rgba(15, 23, 42, 0.75);
  color: #38bdf8;
}

.camera-offline {
  color: #94a3b8;
  text-align: center;
}

.cam-icon {
  font-size: 2.5rem;
}

.camera-controls-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.camera-controls-grid .btn-outline {
  grid-column: span 2;
}

.preview-box {
  margin-top: 1rem;
  border-top: 1px solid #f1f5f9;
  padding-top: 1rem;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 0.5rem;
}

.badge-bbox {
  background: #e0f2fe;
  color: #0369a1;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
}

.image-wrapper {
  border-radius: 8px;
  overflow: hidden;
  max-height: 220px;
  display: flex;
  justify-content: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.preview-image {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
}

.action-footer {
  margin-top: 1.25rem;
}

.btn {
  padding: 0.6rem 1rem;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.88rem;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.btn-primary {
  background: #2563eb;
  color: white;
}

.btn-success {
  background: #16a34a;
  color: white;
}

.btn-danger {
  background: #dc2626;
  color: white;
}

.btn-secondary {
  background: #f1f5f9;
  color: #334155;
}

.btn-outline {
  background: transparent;
  border: 1px solid #cbd5e1;
  color: #64748b;
}

.btn-benchmark {
  width: 100%;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  padding: 0.8rem;
  font-size: 0.95rem;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(37,99,235,0.2);
}

.btn-benchmark:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-state {
  text-align: center;
  padding: 3rem 1.5rem;
  color: #94a3b8;
}

.empty-icon {
  font-size: 3rem;
}

.processing-state {
  text-align: center;
  padding: 3rem 1.5rem;
  color: #334155;
}

.sub-proc {
  display: block;
  font-size: 0.8rem;
  color: #94a3b8;
  margin-top: 0.5rem;
}

.pulse-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e2e8f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 1rem auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.consensus-card {
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1.25rem;
  border: 1px solid transparent;
}

.verdict-real {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.verdict-spoof {
  background: #fef2f2;
  border-color: #fecaca;
}

.consensus-badge {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}

.status-icon {
  font-size: 2.2rem;
}

.status-meta {
  display: flex;
  flex-direction: column;
}

.consensus-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.consensus-sub {
  font-size: 0.85rem;
  color: #64748b;
}

.consensus-tags {
  display: flex;
  gap: 0.6rem;
  margin-top: 0.8rem;
  flex-wrap: wrap;
}

.tag-metric {
  font-size: 0.78rem;
  font-weight: 600;
  background: rgba(255,255,255,0.8);
  padding: 3px 8px;
  border-radius: 6px;
  color: #334155;
  border: 1px solid rgba(0,0,0,0.06);
}

.models-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-bottom: 1.5rem;
}

@media (max-width: 900px) {
  .models-grid {
    grid-template-columns: 1fr;
  }
}

.model-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem;
}

.model-card.card-real {
  border-top: 4px solid #22c55e;
}

.model-card.card-spoof {
  border-top: 4px solid #ef4444;
}

.model-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.model-tag {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
}

.tag-raray { background: #e0e7ff; color: #4338ca; }
.tag-uniface { background: #e0f2fe; color: #0284c7; }
.tag-se { background: #fef3c7; color: #b45309; }

.latency-badge {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
}

.model-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 0.2rem 0;
}

.model-arch {
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 0 0 0.8rem 0;
}

.verdict-banner {
  text-align: center;
  padding: 0.4rem;
  font-weight: 700;
  font-size: 0.85rem;
  border-radius: 6px;
  margin-bottom: 0.8rem;
}

.banner-real {
  background: #dcfce7;
  color: #15803d;
}

.banner-spoof {
  background: #fee2e2;
  color: #b91c1c;
}

.meter-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.score-val {
  font-weight: 700;
  color: #0f172a;
}

.meter-bar {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}

.meter-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}

.fill-real { background: #22c55e; }
.fill-spoof { background: #ef4444; }

.metrics-table-wrapper {
  margin-bottom: 1.5rem;
}

.table-heading {
  font-size: 0.9rem;
  font-weight: 600;
  color: #334155;
  margin: 0 0 0.5rem 0;
}

.metrics-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.metrics-table th, .metrics-table td {
  padding: 0.6rem 0.75rem;
  border: 1px solid #e2e8f0;
  text-align: left;
}

.metrics-table th {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
}

.badge-real {
  background: #dcfce7;
  color: #15803d;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.badge-spoof {
  background: #fee2e2;
  color: #b91c1c;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.code-snippet-box {
  background: #0f172a;
  border-radius: 8px;
  padding: 0.8rem 1rem;
}

.snippet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #94a3b8;
  font-size: 0.75rem;
  margin-bottom: 0.4rem;
}

.btn-copy {
  background: #334155;
  color: white;
  border: none;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  cursor: pointer;
}

.snippet-code {
  margin: 0;
  color: #e2e8f0;
  font-family: 'Consolas', monospace;
  font-size: 0.78rem;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

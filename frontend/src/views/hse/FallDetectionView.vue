<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { fallDetectionService } from '../../services/fallDetectionService'
import { API_BASE_URL } from '../../utils'

const activeMode = ref('live') // 'live' | 'upload' | 'incidents'

// Audio Alarm Siren using Web Audio API
const soundEnabled = ref(true)
let audioCtx = null

const playAlertSiren = () => {
  if (!soundEnabled.value) return
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume()
    }
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.type = 'sawtooth'
    osc.frequency.setValueAtTime(880, audioCtx.currentTime)
    osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.4)
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4)
    osc.connect(gain)
    gain.connect(audioCtx.destination)
    osc.start()
    osc.stop(audioCtx.currentTime + 0.4)
  } catch (err) {
    console.error('Audio alert error:', err)
  }
}

// ---------------- LIVE WEBCAM STATE ----------------
const videoRef = ref(null)
const canvasRef = ref(null)
const isCameraActive = ref(false)
const isAnalyzingFrame = ref(false)
const cameraStream = ref(null)
let streamLoopRunning = false   // flag for non-overlapping async loop

const liveResult = ref(null)
const liveAnnotatedImg = ref('')  // holds latest annotated base64 image
const liveStatus = computed(() => {
  if (!liveResult.value) return 'IDLE'
  return liveResult.value.overall_status || 'SAFE'
})

// Sensitivity Settings
const angleThreshold = ref(45.0)
const ratioThreshold = ref(1.05)
const autoLogIncidents = ref(true)

// Stats & Telemetry
const liveFps = ref(0)
const liveProcessingMs = ref(0)
const lastIncidentLoggedAt = ref(null)

const startWebcam = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
    })
    cameraStream.value = stream
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      await videoRef.value.play()
    }
    isCameraActive.value = true
    streamLoopRunning = true

    // Start non-overlapping async inference loop
    runInferenceLoop()
  } catch (err) {
    alert('Gagal mengakses webcam: ' + err.message)
  }
}

const stopWebcam = () => {
  streamLoopRunning = false
  if (cameraStream.value) {
    cameraStream.value.getTracks().forEach(t => t.stop())
    cameraStream.value = null
  }
  isCameraActive.value = false
  liveResult.value = null
  liveAnnotatedImg.value = ''
}

/**
 * Non-overlapping async inference loop:
 * Sends one frame, waits for result, then immediately captures the next frame.
 * This prevents piling up parallel requests when backend is slower than capture rate.
 */
const runInferenceLoop = async () => {
  while (streamLoopRunning && isCameraActive.value) {
    if (videoRef.value && videoRef.value.videoWidth > 0 && canvasRef.value) {
      const canvas = canvasRef.value
      canvas.width = videoRef.value.videoWidth
      canvas.height = videoRef.value.videoHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(videoRef.value, 0, 0, canvas.width, canvas.height)

      const imageBase64 = canvas.toDataURL('image/jpeg', 0.75)

      isAnalyzingFrame.value = true
      const startMs = performance.now()
      const res = await fallDetectionService.analyzeFrame({
        imageBase64,
        angleThreshold: angleThreshold.value,
        ratioThreshold: ratioThreshold.value,
        autoLog: autoLogIncidents.value
      })
      const elapsed = performance.now() - startMs
      isAnalyzingFrame.value = false

      if (res && streamLoopRunning) {
        liveResult.value = res
        liveProcessingMs.value = Math.round(elapsed)
        liveFps.value = Math.round(1000 / Math.max(elapsed, 1))

        // Update annotated image only when available
        if (res.annotated_image) {
          liveAnnotatedImg.value = res.annotated_image
        }

        if (res.has_fall) {
          playAlertSiren()
          lastIncidentLoggedAt.value = new Date().toLocaleTimeString()
          if (res.incident_id) {
            fetchIncidents()
          }
        }
      }
    } else {
      // Video not ready yet — wait a tick before retrying
      await new Promise(resolve => setTimeout(resolve, 50))
    }
  }
}

// ---------------- VIDEO / FILE UPLOAD STATE ----------------
const uploadFile = ref(null)
const uploadPreview = ref('')
const isVideoFile = ref(false)
const isProcessingUpload = ref(false)
const uploadResult = ref(null)

const handleFileSelect = (e) => {
  const file = e.target.files[0]
  if (!file) return
  uploadFile.value = file
  uploadResult.value = null
  isVideoFile.value = file.type.startsWith('video/')

  const reader = new FileReader()
  reader.onload = (ev) => {
    uploadPreview.value = ev.target.result
  }
  reader.readAsDataURL(file)
}

const runUploadAnalysis = async () => {
  if (!uploadFile.value) return
  isProcessingUpload.value = true
  uploadResult.value = null

  if (isVideoFile.value) {
    const res = await fallDetectionService.analyzeVideo({
      file: uploadFile.value,
      angleThreshold: angleThreshold.value,
      ratioThreshold: ratioThreshold.value,
      autoLog: true
    })
    uploadResult.value = res
  } else {
    const res = await fallDetectionService.analyzeFrame({
      file: uploadFile.value,
      angleThreshold: angleThreshold.value,
      ratioThreshold: ratioThreshold.value,
      autoLog: true
    })
    uploadResult.value = res
  }

  isProcessingUpload.value = false
  fetchIncidents()
}

// ---------------- INCIDENT LOGS STATE ----------------
const incidents = ref([])
const totalIncidents = ref(0)
const isLoadingIncidents = ref(false)
const selectedSnapshot = ref('')

const fetchIncidents = async () => {
  isLoadingIncidents.value = true
  const res = await fallDetectionService.getIncidents(1, 30)
  if (res && res.success) {
    incidents.value = res.items || []
    totalIncidents.value = res.total || 0
  }
  isLoadingIncidents.value = false
}

const deleteIncident = async (id) => {
  if (!confirm('Hapus riwayat insiden ini?')) return
  const ok = await fallDetectionService.deleteIncident(id)
  if (ok) {
    incidents.value = incidents.value.filter(i => i.id !== id)
    totalIncidents.value = Math.max(0, totalIncidents.value - 1)
  }
}

const getFullMediaUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http') || url.startsWith('data:')) return url
  return `${API_BASE_URL}${url}`
}

onMounted(() => {
  fetchIncidents()
})

onUnmounted(() => {
  stopWebcam()
  if (audioCtx) {
    try { audioCtx.close() } catch (e) {}
  }
})
</script>

<template>
  <div class="fall-view-container">
    <!-- Top Header -->
    <div class="header-section">
      <div class="title-group">
        <div class="badge-tag">K3 & WORKPLACE SAFETY AI</div>
        <h1>🚨 AI Fall Detection Monitor</h1>
        <p class="subtitle">
          Deteksi otomatis orang terjatuh / kolaps secara real-time berbasis <strong>Google MediaPipe Pose (33 Landmarks)</strong> & Analisis Kinematika Sudut Tubuh.
        </p>
      </div>

      <!-- Mode Selector Tabs -->
      <div class="nav-pills">
        <button
          :class="['nav-pill', { active: activeMode === 'live' }]"
          @click="activeMode = 'live'"
        >
          📹 Live Webcam / CCTV
        </button>
        <button
          :class="['nav-pill', { active: activeMode === 'upload' }]"
          @click="activeMode = 'upload'"
        >
          📂 Upload Video / Foto
        </button>
        <button
          :class="['nav-pill', { active: activeMode === 'incidents' }]"
          @click="activeMode = 'incidents'; fetchIncidents()"
        >
          📋 Log Insiden K3
          <span v-if="totalIncidents > 0" class="counter-badge">{{ totalIncidents }}</span>
        </button>
      </div>
    </div>

    <!-- Critical Fall Alert Banner (Active when fall detected in live mode) -->
    <transition name="fade">
      <div v-if="liveStatus === 'FALL_DETECTED'" class="critical-alarm-banner">
        <div class="alarm-icon">⚠️</div>
        <div class="alarm-content">
          <h3>BAHAYA K3: TERDETEKSI PERSONEL TERJATUH!</h3>
          <p>Sistem mendeteksi sudut tubuh mendatar (< {{ angleThreshold }}°) atau kolaps ke lantai. Segera periksa area!</p>
        </div>
        <div class="alarm-actions">
          <button class="btn-siren-toggle" @click="soundEnabled = !soundEnabled">
            {{ soundEnabled ? '🔊 Alarm Aktif' : '🔇 Alarm Muted' }}
          </button>
        </div>
      </div>
    </transition>

    <!-- Main Workspace Grid -->
    <div class="main-grid">
      <!-- LEFT COLUMN: Live or Upload Player -->
      <div class="player-card">
        <!-- MODE 1: LIVE WEBCAM -->
        <div v-if="activeMode === 'live'" class="live-wrapper">
          <div class="live-header">
            <div class="status-indicator">
              <span :class="['dot', {
                'dot-active': isCameraActive && liveStatus === 'SAFE',
                'dot-warning': isCameraActive && liveStatus === 'WARNING',
                'dot-critical': isCameraActive && liveStatus === 'FALL_DETECTED',
                'dot-idle': !isCameraActive
              }]"></span>
              <span class="status-text">
                {{ isCameraActive ? (liveStatus === 'FALL_DETECTED' ? 'CRITICAL: FALL DETECTED!' : (liveStatus === 'WARNING' ? 'WARNING: BENDING/SITTING' : 'STATUS: NORMAL (SAFE)')) : 'Kamera Nonaktif' }}
              </span>
            </div>
            <div class="fps-tag" v-if="isCameraActive">
              ⚡ {{ liveFps }} FPS
            </div>
          </div>

          <div class="video-container">
            <!-- Raw webcam video — always visible as background when camera is active -->
            <video
              ref="videoRef"
              playsinline
              muted
              :class="isCameraActive ? 'live-video-bg' : 'hidden-video'"
            ></video>

            <!-- Hidden canvas for frame capture (template ref) -->
            <canvas ref="canvasRef" class="hidden-canvas"></canvas>

            <!-- AI Annotated Overlay — drawn on top of raw video once first result arrives -->
            <img
              v-if="isCameraActive && liveAnnotatedImg"
              :src="liveAnnotatedImg"
              alt="AI Fall Detection Overlay"
              class="annotated-overlay"
            />

            <!-- Processing indicator badge (top-right) -->
            <div v-if="isCameraActive && isAnalyzingFrame" class="processing-badge">
              ⏳ Analyzing...
            </div>

            <!-- Empty state — camera off -->
            <div v-if="!isCameraActive" class="empty-camera-placeholder">
              <div class="placeholder-icon">📷</div>
              <h3>Kamera Pemantau Belum Dinyalakan</h3>
              <p>Klik tombol <strong>"Aktifkan Live Webcam"</strong> untuk mulai memantau deteksi jatuh real-time.</p>
            </div>
          </div>

          <div class="camera-controls-bar">
            <button
              v-if="!isCameraActive"
              class="btn-primary btn-lg"
              @click="startWebcam"
            >
              ▶️ Aktifkan Live Webcam
            </button>
            <button
              v-else
              class="btn-danger btn-lg"
              @click="stopWebcam"
            >
              ⏹️ Hentikan Pemantauan
            </button>

            <button
              class="btn-outline"
              :class="{ 'btn-active': soundEnabled }"
              @click="soundEnabled = !soundEnabled"
              title="Aktifkan / Matikan Suara Sirine"
            >
              {{ soundEnabled ? '🔊 Suara Sirine ON' : '🔇 Suara Sirine OFF' }}
            </button>
          </div>
        </div>

        <!-- MODE 2: UPLOAD VIDEO / IMAGE -->
        <div v-else-if="activeMode === 'upload'" class="upload-wrapper">
          <div class="drop-zone" @click="$refs.fileInput.click()">
            <input
              type="file"
              ref="fileInput"
              accept="image/*,video/*"
              class="hidden-file-input"
              @change="handleFileSelect"
            />

            <div v-if="!uploadPreview" class="drop-placeholder">
              <div class="drop-icon">📹</div>
              <h4>Pilih atau Drag & Drop Video / Foto CCTV</h4>
              <p>Format yang didukung: MP4, MOV, AVI, JPG, PNG (Maks 100MB)</p>
              <button class="btn-select-file">Pilih File</button>
            </div>

            <div v-else class="preview-box">
              <video
                v-if="isVideoFile"
                :src="uploadPreview"
                controls
                class="file-preview-media"
              ></video>
              <img
                v-else
                :src="uploadPreview"
                alt="File Preview"
                class="file-preview-media"
              />
            </div>
          </div>

          <div class="upload-action-row">
            <button
              class="btn-primary btn-lg"
              :disabled="!uploadFile || isProcessingUpload"
              @click="runUploadAnalysis"
            >
              <span v-if="isProcessingUpload">⏳ Memproses AI Pose Analysis...</span>
              <span v-else>🔍 Jalankan Audit Deteksi Jatuh</span>
            </button>
          </div>

          <!-- Video / Image Analysis Result -->
          <div v-if="uploadResult" class="upload-result-card">
            <div class="result-header">
              <h4>📊 Hasil Audit Rekaman CCTV</h4>
              <span :class="['result-badge', uploadResult.has_fall ? 'badge-danger' : 'badge-success']">
                {{ uploadResult.has_fall ? '🚨 TERDETEKSI JATUH' : '✅ AMAN (TIDAK ADA JATUH)' }}
              </span>
            </div>

            <!-- Annotated Video Playback -->
            <div v-if="uploadResult.video_url" class="annotated-video-box">
              <p class="section-label">🎬 Video Hasil Tracking MediaPipe:</p>
              <video
                :src="getFullMediaUrl(uploadResult.video_url)"
                controls
                autoplay
                class="annotated-video-player"
              ></video>
            </div>

            <!-- Snapshot for Frame Upload -->
            <div v-if="uploadResult.annotated_image" class="annotated-img-box">
              <img :src="uploadResult.annotated_image" alt="Hasil Anotasi" class="annotated-snapshot" />
            </div>

            <!-- Fall Timeline Events -->
            <div v-if="uploadResult.timeline_events && uploadResult.timeline_events.length > 0" class="timeline-box">
              <h5>⏱️ Kejadian Jatuh Terdeteksi ({{ uploadResult.timeline_events.length }} Event):</h5>
              <div class="timeline-scroll">
                <div
                  v-for="(ev, idx) in uploadResult.timeline_events"
                  :key="idx"
                  class="timeline-item"
                >
                  <span class="timestamp-tag">Detik ke-{{ ev.timestamp }}s (Frame {{ ev.frame }})</span>
                  <span class="event-desc">
                    Sudut Torso: <strong>{{ ev.details[0]?.angle }}°</strong> | Rasio Aspek: <strong>{{ ev.details[0]?.ar }}</strong>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- MODE 3: INCIDENT LOGS TAB -->
        <div v-else-if="activeMode === 'incidents'" class="incidents-wrapper">
          <div class="incidents-header">
            <h3>Riwayat Insiden Keselamatan (Fall Events)</h3>
            <button class="btn-refresh" @click="fetchIncidents">🔄 Muat Ulang</button>
          </div>

          <div v-if="isLoadingIncidents" class="loading-state">
            <div class="loader-spinner"></div>
            <p>Mengambil log insiden...</p>
          </div>

          <div v-else-if="incidents.length === 0" class="empty-incidents">
            <div class="empty-icon">🛡️</div>
            <h4>Belum Ada Insiden Jatuh yang Tercatat</h4>
            <p>Semua personel terpantau aman dan beraktivitas normal.</p>
          </div>

          <div v-else class="incidents-table-wrapper">
            <table class="incidents-table">
              <thead>
                <tr>
                  <th>Waktu</th>
                  <th>Snapshot</th>
                  <th>Status</th>
                  <th>Subjek</th>
                  <th>Aksi</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in incidents" :key="item.id">
                  <td>{{ item.created_at ? new Date(item.created_at).toLocaleString() : '-' }}</td>
                  <td>
                    <img
                      v-if="item.result_image_url"
                      :src="getFullMediaUrl(item.result_image_url)"
                      alt="Incident Snapshot"
                      class="table-snapshot-thumb"
                      @click="selectedSnapshot = getFullMediaUrl(item.result_image_url)"
                    />
                    <span v-else>-</span>
                  </td>
                  <td>
                    <span class="badge-critical">{{ item.severity }}</span>
                  </td>
                  <td>{{ item.persons_count }} Orang</td>
                  <td>
                    <button class="btn-delete-row" @click="deleteIncident(item.id)">🗑️ Hapus</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- RIGHT COLUMN: Telemetry HUD & Sensitivity Calibration -->
      <div class="sidebar-card">
        <!-- Live Posture Telemetry -->
        <div class="panel-section">
          <h3>📐 Telemetri Postur Real-Time</h3>

          <div class="telemetry-cards">
            <div class="telemetry-card">
              <span class="telemetry-label">Status Postur</span>
              <span :class="['telemetry-value', {
                'text-critical': liveStatus === 'FALL_DETECTED',
                'text-warning': liveStatus === 'WARNING',
                'text-safe': liveStatus === 'SAFE'
              }]">
                {{ liveStatus }}
              </span>
            </div>

            <div class="telemetry-card">
              <span class="telemetry-label">Jumlah Orang Terdeteksi</span>
              <span class="telemetry-value">
                {{ liveResult?.persons_count || 0 }} Orang
              </span>
            </div>

            <div class="telemetry-card" v-if="liveResult?.persons?.length > 0">
              <span class="telemetry-label">Sudut Torso Utama</span>
              <span class="telemetry-value">
                {{ liveResult.persons[0].torso_angle }}°
              </span>
              <span class="telemetry-hint">(Berdiri: 70°-90° | Jatuh: < 45°)</span>
            </div>

            <div class="telemetry-card" v-if="liveResult?.persons?.length > 0">
              <span class="telemetry-label">Rasio Aspek Bounding Box (W/H)</span>
              <span class="telemetry-value">
                {{ liveResult.persons[0].aspect_ratio }}
              </span>
              <span class="telemetry-hint">(Berdiri: < 0.8 | Jatuh: > 1.05)</span>
            </div>
          </div>
        </div>

        <!-- Sensitivity Settings -->
        <div class="panel-section">
          <h3>⚙️ Sensitivitas & Ambang Batas</h3>

          <div class="form-group">
            <div class="label-row">
              <label>Ambang Batas Sudut Torso:</label>
              <span class="value-tag">{{ angleThreshold }}°</span>
            </div>
            <input
              type="range"
              v-model.number="angleThreshold"
              min="20"
              max="65"
              step="1"
              class="range-slider"
            />
            <p class="input-desc">Jika sudut torso di bawah derajat ini, AI mengklasifikasikan sebagai posisi rebah/terjatuh.</p>
          </div>

          <div class="form-group">
            <div class="label-row">
              <label>Ambang Batas Rasio Lebar/Tinggi (W/H):</label>
              <span class="value-tag">{{ ratioThreshold }}</span>
            </div>
            <input
              type="range"
              v-model.number="ratioThreshold"
              min="0.8"
              max="1.5"
              step="0.05"
              class="range-slider"
            />
            <p class="input-desc">Rasio W/H melebihi angka ini menandakan tubuh membujur horizontal di lantai.</p>
          </div>

          <div class="checkbox-group">
            <label class="custom-checkbox">
              <input type="checkbox" v-model="autoLogIncidents" />
              <span>Otomatis Catat ke Log Insiden K3 saat Terjadi Jatuh</span>
            </label>
          </div>
        </div>

        <!-- Engine Information -->
        <div class="panel-section info-section">
          <h4>💡 Cara Kerja AI Fall Detection</h4>
          <ul class="info-list">
            <li><strong>MediaPipe Pose:</strong> Memetakan 33 titik anatomi tubuh secara real-time langsung pada CPU/GPU.</li>
            <li><strong>Vektor Torso:</strong> Menghubungkan titik tengah kedua bahu (Landmark 11, 12) ke titik tengah kedua pinggul (Landmark 23, 24).</li>
            <li><strong>Filtering False-Positive:</strong> Membedakan aktivitas duduk/membungkuk dari jatuh mendadak melalui kombinasi sudut dan rasio aspek bounding box.</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Snapshot Preview Modal -->
    <div v-if="selectedSnapshot" class="modal-overlay" @click="selectedSnapshot = ''">
      <div class="modal-card" @click.stop>
        <div class="modal-header">
          <h4>Snapshot Insiden Terkonfirmasi</h4>
          <button class="modal-close" @click="selectedSnapshot = ''">&times;</button>
        </div>
        <div class="modal-body">
          <img :src="selectedSnapshot" alt="Full Snapshot" class="modal-img" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fall-view-container {
  padding: 24px;
  max-width: 1440px;
  margin: 0 auto;
  color: #e2e8f0;
}

/* Header Section */
.header-section {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.badge-tag {
  display: inline-block;
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 4px 10px;
  border-radius: 9999px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  margin-bottom: 8px;
}

.title-group h1 {
  font-size: 26px;
  font-weight: 800;
  color: #ffffff;
  margin: 0 0 6px 0;
}

.subtitle {
  font-size: 14px;
  color: #94a3b8;
  max-width: 720px;
  margin: 0;
  line-height: 1.5;
}

/* Nav Pills */
.nav-pills {
  display: flex;
  background: #1e293b;
  padding: 4px;
  border-radius: 12px;
  border: 1px solid #334155;
  gap: 4px;
}

.nav-pill {
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}

.nav-pill:hover {
  color: #f1f5f9;
}

.nav-pill.active {
  background: #3b82f6;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
}

.counter-badge {
  background: #ef4444;
  color: #ffffff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 9999px;
  font-weight: 700;
}

/* Critical Alarm Banner */
.critical-alarm-banner {
  background: linear-gradient(90deg, #991b1b 0%, #dc2626 100%);
  border: 1px solid #ef4444;
  color: #ffffff;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 4px 20px rgba(220, 38, 38, 0.4);
  animation: pulse-danger 1.5s infinite;
}

@keyframes pulse-danger {
  0%, 100% { box-shadow: 0 0 15px rgba(239, 68, 68, 0.5); }
  50% { box-shadow: 0 0 30px rgba(239, 68, 68, 0.9); }
}

.alarm-icon {
  font-size: 32px;
}

.alarm-content h3 {
  margin: 0 0 4px 0;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.alarm-content p {
  margin: 0;
  font-size: 13px;
  color: #fee2e2;
}

.btn-siren-toggle {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: #ffffff;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

/* Main Grid Layout */
.main-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 24px;
}

@media (max-width: 1080px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

/* Cards */
.player-card, .sidebar-card {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 16px;
  padding: 20px;
}

/* Live Webcam UI */
.live-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-idle { background: #64748b; }
.dot-active { background: #22c55e; box-shadow: 0 0 8px #22c55e; }
.dot-warning { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; }
.dot-critical { background: #ef4444; box-shadow: 0 0 12px #ef4444; animation: blink 0.8s infinite; }

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.status-text {
  font-size: 13px;
  font-weight: 700;
}

.fps-tag {
  background: #1e293b;
  color: #38bdf8;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #334155;
}

.video-container {
  background: #020617;
  border-radius: 12px;
  border: 1px solid #1e293b;
  height: 480px;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Raw webcam video — fills container as background layer */
.live-video-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}

/* AI annotated skeleton overlay — sits on top of raw video, slightly transparent */
.annotated-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 2;
  opacity: 0.92;
}

/* Processing badge indicator top-right corner */
.processing-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #f59e0b;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  z-index: 5;
  backdrop-filter: blur(4px);
}

.hidden-video, .hidden-canvas, .hidden-file-input {
  display: none;
}

.active-video-frame {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.waiting-frame, .empty-camera-placeholder {
  text-align: center;
  color: #64748b;
  padding: 30px;
}

.placeholder-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-camera-placeholder h3 {
  color: #f1f5f9;
  font-size: 16px;
  margin-bottom: 6px;
}

.empty-camera-placeholder p {
  font-size: 13px;
  max-width: 360px;
  margin: 0 auto;
}

.camera-controls-bar {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

/* Upload UI */
.drop-zone {
  border: 2px dashed #334155;
  border-radius: 12px;
  background: #020617;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.2s ease;
  overflow: hidden;
}

.drop-zone:hover {
  border-color: #3b82f6;
}

.drop-placeholder {
  text-align: center;
  padding: 30px;
}

.drop-icon {
  font-size: 40px;
  margin-bottom: 10px;
}

.drop-placeholder h4 {
  color: #f1f5f9;
  margin: 0 0 6px 0;
  font-size: 15px;
}

.drop-placeholder p {
  color: #64748b;
  font-size: 12px;
  margin: 0 0 16px 0;
}

.btn-select-file {
  background: #1e293b;
  color: #f1f5f9;
  border: 1px solid #334155;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.preview-box {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.file-preview-media {
  max-width: 100%;
  max-height: 400px;
  border-radius: 8px;
}

.upload-action-row {
  margin-top: 16px;
}

/* Upload Results */
.upload-result-card {
  margin-top: 20px;
  background: #1e293b;
  border-radius: 12px;
  border: 1px solid #334155;
  padding: 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.result-header h4 {
  margin: 0;
  font-size: 15px;
  color: #ffffff;
}

.result-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
}

.badge-danger { background: #ef4444; color: #ffffff; }
.badge-success { background: #22c55e; color: #ffffff; }
.badge-critical { background: #ef4444; color: #ffffff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }

.annotated-video-player, .annotated-snapshot {
  width: 100%;
  border-radius: 8px;
  background: #000;
  max-height: 380px;
}

.section-label {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
  font-weight: 600;
}

.timeline-box {
  margin-top: 14px;
}

.timeline-box h5 {
  font-size: 13px;
  color: #f1f5f9;
  margin: 0 0 8px 0;
}

.timeline-scroll {
  max-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.timeline-item {
  background: #0f172a;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  display: flex;
  justify-content: space-between;
}

.timestamp-tag {
  color: #f87171;
  font-weight: 700;
}

.event-desc {
  color: #cbd5e1;
}

/* Incidents Table */
.incidents-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.incidents-header h3 {
  margin: 0;
  font-size: 16px;
}

.btn-refresh {
  background: #1e293b;
  border: 1px solid #334155;
  color: #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.incidents-table-wrapper {
  overflow-x: auto;
}

.incidents-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.incidents-table th {
  text-align: left;
  padding: 10px 12px;
  background: #1e293b;
  color: #94a3b8;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.incidents-table td {
  padding: 12px;
  border-bottom: 1px solid #1e293b;
  color: #e2e8f0;
}

.table-snapshot-thumb {
  width: 60px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid #334155;
}

.table-snapshot-thumb:hover {
  transform: scale(1.05);
}

.btn-delete-row {
  background: transparent;
  border: none;
  color: #f87171;
  cursor: pointer;
  font-size: 12px;
}

/* Right Column Sidebar */
.panel-section {
  border-bottom: 1px solid #1e293b;
  padding-bottom: 18px;
  margin-bottom: 18px;
}

.panel-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.panel-section h3 {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 14px 0;
}

.telemetry-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.telemetry-card {
  background: #1e293b;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #334155;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.telemetry-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.telemetry-value {
  font-size: 18px;
  font-weight: 800;
  color: #ffffff;
}

.telemetry-hint {
  font-size: 10px;
  color: #64748b;
}

.text-critical { color: #ef4444 !important; }
.text-warning { color: #f59e0b !important; }
.text-safe { color: #22c55e !important; }

/* Sliders */
.form-group {
  margin-bottom: 14px;
}

.label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #cbd5e1;
  margin-bottom: 6px;
}

.value-tag {
  font-weight: 700;
  color: #38bdf8;
  background: #0f172a;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #334155;
}

.range-slider {
  width: 100%;
  accent-color: #3b82f6;
  cursor: pointer;
}

.input-desc {
  font-size: 11px;
  color: #64748b;
  margin: 4px 0 0 0;
  line-height: 1.4;
}

.custom-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #cbd5e1;
  cursor: pointer;
}

.custom-checkbox input {
  accent-color: #3b82f6;
  width: 16px;
  height: 16px;
}

/* Info Section */
.info-section h4 {
  font-size: 13px;
  margin: 0 0 8px 0;
  color: #f1f5f9;
}

.info-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  flex-direction: column;
  gap: 8px;
  line-height: 1.4;
}

/* Common Buttons */
.btn-primary {
  background: #3b82f6;
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-danger {
  background: #ef4444;
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}

.btn-danger:hover {
  background: #dc2626;
}

.btn-outline {
  background: #1e293b;
  color: #cbd5e1;
  border: 1px solid #334155;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.btn-outline.btn-active {
  border-color: #38bdf8;
  color: #38bdf8;
}

.btn-lg {
  padding: 12px 24px;
  font-size: 14px;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 20px;
}

.modal-card {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 16px;
  max-width: 800px;
  width: 100%;
  overflow: hidden;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #1e293b;
}

.modal-header h4 {
  margin: 0;
  font-size: 15px;
  color: #ffffff;
}

.modal-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 24px;
  cursor: pointer;
}

.modal-body {
  padding: 16px;
  display: flex;
  justify-content: center;
}

.modal-img {
  max-width: 100%;
  max-height: 70vh;
  border-radius: 8px;
}

.loader-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(59, 130, 246, 0.2);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

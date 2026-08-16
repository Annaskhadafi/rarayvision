<script setup>
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { hseService } from '../../services/hseService'
import { cameraService } from '../../services/cameraService'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

const getMediaUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http') || url.startsWith('data:')) return url
  return `${API_BASE_URL}${url}`
}

const activeTab = ref('ppe_check')
const outputMode = ref('image') // 'image' | 'video'
const imageFile = ref(null)
const imagePreview = ref('')
const isMediaVideo = ref(false)
const isProcessing = ref(false)
const confidenceOverride = ref(0.4)

const hseResult = ref(null)
const errorMsg = ref('')

// Camera Modal & Dual-Mode State
const showCameraModal = ref(false)
const cameraTab = ref('webcam') // 'webcam' | 'rtsp' | 'public_url'
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

// Public URL / City Camera State
const publicStreamUrl = ref('')
const publicFeedUrl = ref('')
const isConnectingPublic = ref(false)
const publicUrlPresets = [
  { label: '── Paste URL sendiri di bawah ──', value: '' },
  { label: '🧪 Test HLS Stream (Mux)', value: 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8' },
  { label: '🧪 Test MP4 HTTP (BigBuckBunny)', value: 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4' },
  { label: '▶ YouTube Live / Video (paste link)', value: 'https://www.youtube.com/watch?v=' },
  { label: '🎮 Twitch Live (paste link)', value: 'https://www.twitch.tv/' },
  { label: '📘 Facebook Live (paste link)', value: 'https://www.facebook.com/videos/' },
  { label: '📡 IP Cam MJPEG (ganti IP)', value: 'http://192.168.x.x/videostream.cgi' },
  { label: '📡 RTSP IP Cam (ganti IP)', value: 'rtsp://admin:password@192.168.x.x:554/stream' },
  { label: '📡 RTMP Stream (ganti server)', value: 'rtmp://live.example.com/live/stream_key' },
]


const startBrowserWebcam = async () => {
  webcamErrorMsg.value = ''
  try {
    // Flexible video constraint to prevent "Could not start video source" when resolution locked
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
              if (activeTab.value === 'ppe_check') {
                res = await hseService.ppeCheck(formData)
              } else if (activeTab.value === 'danger_zone') {
                res = await hseService.dangerZoneAlert(formData)
              } else {
                res = await hseService.nearMissLog(formData)
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
  const mod = activeTab.value === 'ppe_check' ? 'hse_ppe' : (activeTab.value === 'danger_zone' ? 'hse_danger_zone' : 'hse_near_miss')

  try {
    const cam = await cameraService.addCamera({
      name: 'RTSP Testing Camera',
      stream_url: customRtspUrl.value,
      location: 'Area RTSP Testing',
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

const connectPublicCamera = async () => {
  const url = publicStreamUrl.value.trim()
  if (!url) {
    alert('Silakan masukkan URL stream publik terlebih dahulu.')
    return
  }
  const allowedSchemes = ['rtsp://', 'rtmp://', 'http://', 'https://', 'udp://', 'tcp://']
  if (!allowedSchemes.some(s => url.startsWith(s))) {
    alert(`URL harus dimulai dengan salah satu dari: ${allowedSchemes.join(', ')}`)
    return
  }
  isConnectingPublic.value = true
  publicFeedUrl.value = ''
  const mod = activeTab.value === 'ppe_check' ? 'hse_ppe' : (activeTab.value === 'danger_zone' ? 'hse_danger_zone' : 'hse_near_miss')

  try {
    const cam = await cameraService.addCamera({
      name: 'Public URL Testing Camera',
      stream_url: url,
      location: 'Public Stream / City Camera',
      camera_type: 'rtsp',
      preset_brand: 'custom',
      enable_ai_overlay: true,
      ai_module: mod
    })
    publicFeedUrl.value = cameraService.getFeedUrl(cam.id) + '?t=' + Date.now()
  } catch (err) {
    alert('Gagal menghubungkan ke stream publik: ' + err.message)
  }
  isConnectingPublic.value = false
}

const applyPublicPreset = (val) => {
  if (val) publicStreamUrl.value = val
}

const switchCameraTab = (tab) => {
  cameraTab.value = tab
  if (tab === 'webcam') {
    rtspFeedUrl.value = ''
    publicFeedUrl.value = ''
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
  publicFeedUrl.value = ''
  showCameraModal.value = false
}

const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) {
    imageFile.value = file
    imagePreview.value = URL.createObjectURL(file)
    isMediaVideo.value = file.type.startsWith('video/') || file.name.match(/\.(mp4|mov|avi|webm|mkv)$/i)
    hseResult.value = null
    errorMsg.value = ''
  }
}

const runHSEAudit = async () => {
  if (!imageFile.value) {
    errorMsg.value = 'Silakan pilih foto atau video CCTV/lapangan terlebih dahulu.'
    return
  }

  isProcessing.value = true
  errorMsg.value = ''
  hseResult.value = null

  const formData = new FormData()
  formData.append('image', imageFile.value)
  formData.append('confidence_override', confidenceOverride.value)
  formData.append('output_mode', outputMode.value)

  let res = null
  if (activeTab.value === 'ppe_check') {
    res = await hseService.ppeCheck(formData)
  } else if (activeTab.value === 'danger_zone') {
    res = await hseService.dangerZoneAlert(formData)
  } else if (activeTab.value === 'near_miss') {
    res = await hseService.nearMissLog(formData)
  }

  isProcessing.value = false

  if (res) {
    hseResult.value = res
  } else {
    errorMsg.value = 'Gagal memproses audit HSE. Pastikan file valid dan server terhubung.'
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
        <h1 class="page-title">🛟 Occupational Health & Safety (HSE/K3)</h1>
        <p class="page-subtitle">Otomatisasi pengawasan APD, deteksi intrusi zona berbahaya, dan logging near-miss.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn active" @click="router.push('/hse/playground')">🧪 Testing Playground</button>
        <button class="nav-btn" @click="router.push('/hse/zone-editor')">📐 Polygon Zone Editor</button>
        <button class="nav-btn" @click="router.push('/hse/rules')">📋 APD Rules</button>
        <button class="nav-btn" @click="router.push('/hse/incidents')">🚨 Incident Logs</button>
      </div>
    </div>

    <!-- Mode Selector Tabs -->
    <div class="mode-selector">
      <button :class="['mode-tab', { active: activeTab === 'ppe_check' }]" @click="activeTab = 'ppe_check'; hseResult = null">
        🦺 PPE Compliance Check
      </button>
      <button :class="['mode-tab', { active: activeTab === 'danger_zone' }]" @click="activeTab = 'danger_zone'; hseResult = null">
        ⚠️ Danger Zone Intrusion Alert
      </button>
      <button :class="['mode-tab', { active: activeTab === 'near_miss' }]" @click="activeTab = 'near_miss'; hseResult = null">
        🚨 Comprehensive Near-Miss Log
      </button>
    </div>

    <div class="grid-layout">
      <!-- Upload & Form -->
      <div class="panel upload-panel">
        <h2>Upload Frame / Video CCTV Lapangan</h2>

        <div class="drop-zone" @click="$refs.fileInput.click()">
          <input type="file" ref="fileInput" accept="image/*,video/*" class="file-input" @change="handleFileSelect" />
          
          <div v-if="!imagePreview" class="drop-content">
            <span class="upload-icon">📹</span>
            <p class="drop-title">Klik atau drag & drop foto / video CCTV di sini</p>
            <span class="file-hint">Mendukung JPG, PNG, MP4, MOV, AVI (Max 50MB)</span>
          </div>

          <video v-else-if="isMediaVideo" :src="imagePreview" controls autoplay loop class="preview-media"></video>
          <img v-else :src="imagePreview" alt="Upload Preview" class="preview-media" />
        </div>

        <div class="controls">
          <div class="form-group">
            <label>Confidence Threshold: <strong>{{ confidenceOverride }}</strong></label>
            <input type="range" v-model.number="confidenceOverride" min="0.1" max="0.9" step="0.05" class="slider" />
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
            <button class="btn-primary flex-1" :disabled="isProcessing" @click="runHSEAudit">
              <span v-if="isProcessing">⏳ Memproses Audit K3...</span>
              <span v-else>🛡️ Jalankan Audit K3 API</span>
            </button>

            <button class="btn-camera flex-1" @click="openLiveCameraTest">
              📷 Test Live Camera / Webcam
            </button>
          </div>
        </div>

        <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
      </div>

      <!-- Results Display -->
      <div class="panel result-panel">
        <h2>Hasil Inspeksi Visual & Status Kepatuhan</h2>

        <div v-if="!hseResult && !isProcessing" class="empty-state">
          <span class="empty-icon">🦺</span>
          <p>Pilih foto atau video CCTV dan klik "Jalankan Audit K3 API" untuk memverifikasi APD dan Zona Bahaya.</p>
        </div>

        <div v-if="isProcessing" class="loading-state">
          <div class="spinner"></div>
          <p>Menjalankan model deteksi manusia & evaluasi Supervision PolygonZone...</p>
        </div>

        <div v-if="hseResult" class="result-content">
          <!-- Summary Metrics Cards -->
          <div class="metrics-grid">
            <div v-if="activeTab === 'ppe_check'" :class="['metric-card', hseResult.overall_result === 'PASS' ? 'success' : 'danger']">
              <span class="metric-label">Status Kepatuhan</span>
              <span class="metric-value">{{ hseResult.overall_result }}</span>
            </div>

            <div v-if="activeTab === 'danger_zone'" :class="['metric-card', hseResult.has_intrusion ? 'danger' : 'success']">
              <span class="metric-label">Status Zona</span>
              <span class="metric-value">{{ hseResult.status }}</span>
            </div>

            <div v-if="activeTab === 'near_miss'" :class="['metric-card', hseResult.is_near_miss ? 'danger' : 'success']">
              <span class="metric-label">Tingkat Risiko</span>
              <span class="metric-value">{{ hseResult.severity }}</span>
            </div>

            <div class="metric-card info">
              <span class="metric-label">Waktu Pemrosesan</span>
              <span class="metric-value">{{ hseResult.processing_ms }} ms</span>
            </div>
          </div>

          <!-- Annotated Image or Video Player -->
          <div class="image-wrapper">
            <h3 v-if="hseResult.is_video">📹 Video Hasil Output (Object & Zone Tracking):</h3>
            <h3 v-else>Supervised Safety Canvas Overlay:</h3>

            <video v-if="hseResult.is_video" :src="getMediaUrl(hseResult.video_url)" controls autoplay loop class="annotated-img"></video>
            <img v-else :src="hseResult.annotated_image" alt="Supervised HSE Result" class="annotated-img" />
          </div>

          <!-- Raw JSON Accordion -->
          <details class="json-details">
            <summary>🔍 Raw API Response Payload (JSON)</summary>
            <pre class="json-code">{{ JSON.stringify(hseResult, null, 2) }}</pre>
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
            💻 Webcam Browser
          </button>
          <button :class="['cam-tab-btn', { active: cameraTab === 'rtsp' }]" @click="switchCameraTab('rtsp')">
            📡 RTSP / IP Camera
          </button>
          <button :class="['cam-tab-btn', { active: cameraTab === 'public_url' }]" @click="switchCameraTab('public_url')">
            🌐 Public URL / Kamera Kota
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
            <label>URL RTSP / HTTP Kamera IP:</label>
            <div class="input-row">
              <input type="text" v-model="customRtspUrl" placeholder="rtsp://admin:pass@192.168.1.100:554/live" class="input-field flex-1" />
              <button class="btn-primary" :disabled="isConnectingRtsp" @click="connectRtspCamera">
                <span v-if="isConnectingRtsp">⏳ Sambungkan...</span>
                <span v-else>📡 Sambungkan</span>
              </button>
            </div>
          </div>

          <div class="live-stream-box mt-16">
            <img v-if="rtspFeedUrl" :src="rtspFeedUrl" alt="RTSP Live Feed" class="live-mjpeg-stream" />
            <div v-else class="webcam-loading">
              <span class="empty-icon">📡</span>
              <p>Masukkan URL RTSP di atas dan klik "Sambungkan" untuk memulai stream.</p>
            </div>
          </div>
        </div>

        <!-- PUBLIC URL / CITY CAMERA TAB -->
        <div v-if="cameraTab === 'public_url'" class="tab-body">
          <div class="public-url-info-box">
            <strong>🌐 Mendukung semua format URL stream publik:</strong>
            <div class="url-chips">
              <code>http://</code><code>https://</code><code>rtsp://</code><code>rtmp://</code><code>.m3u8 (HLS)</code><code>MJPEG</code>
            </div>
            <span class="url-note">Ideal untuk kamera kota, traffic monitoring, IP cam publik, feed HLS, dan surveillance berbasis internet.</span>
          </div>

          <div class="rtsp-input-box" style="margin-top:0.75rem;">
            <label>Preset URL Cepat (opsional):</label>
            <select class="input-field" style="width:100%;" @change="e => applyPublicPreset(e.target.value)">
              <option v-for="p in publicUrlPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>

          <div class="rtsp-input-box" style="margin-top:0.5rem;">
            <label>URL Stream Publik:</label>
            <div class="input-row">
              <input
                type="text"
                v-model="publicStreamUrl"
                placeholder="https://stream.kota.go.id/cam/live.m3u8 atau rtsp://cctv.jalan.id/live"
                class="input-field flex-1"
                style="font-family:monospace; font-size:13px;"
                spellcheck="false"
              />
              <button class="btn-primary" :disabled="isConnectingPublic || !publicStreamUrl.trim()" @click="connectPublicCamera">
                <span v-if="isConnectingPublic">⏳ Menyambungkan...</span>
                <span v-else>🌐 Sambungkan & Deteksi</span>
              </button>
            </div>
          </div>

          <div class="live-stream-box mt-16">
            <img v-if="publicFeedUrl" :src="publicFeedUrl" alt="Public Camera Live Feed" class="live-mjpeg-stream" />
            <div v-else class="webcam-loading">
              <span class="empty-icon">🌐</span>
              <p>Masukkan URL kamera publik atau kota di atas, lalu klik <strong>Sambungkan & Deteksi</strong> untuk memulai AI overlay K3.</p>
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
.nav-btn.active, .nav-btn:hover { background: #059669; color: #ffffff; border-color: #059669; box-shadow: 0 2px 8px rgba(5, 150, 105, 0.25); }

.mode-selector { display: flex; gap: 12px; margin-bottom: 24px; }
.mode-tab { flex: 1; background: #ffffff; border: 1px solid #cbd5e1; color: #334155; padding: 14px 18px; border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); transition: all 0.2s; }
.mode-tab.active { background: linear-gradient(135deg, #059669, #10b981); color: #ffffff; border-color: #059669; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3); }

.grid-layout { display: grid; grid-template-columns: 400px 1fr; gap: 24px; }
.panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.panel h2 { font-size: 17px; font-weight: 700; color: #0f172a; margin-bottom: 18px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }

.drop-zone { border: 2px dashed #cbd5e1; background: #f8fafc; border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; margin-bottom: 20px; min-height: 220px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
.drop-zone:hover { border-color: #10b981; background: #ecfdf5; }
.file-input { display: none; }
.upload-icon { font-size: 40px; display: block; margin-bottom: 8px; }
.drop-title { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 4px; }
.file-hint { font-size: 12px; color: #64748b; }
.preview-media { max-width: 100%; max-height: 240px; border-radius: 8px; border: 1px solid #e2e8f0; }

.controls { display: flex; flex-direction: column; gap: 18px; }
.form-group { display: flex; flex-direction: column; gap: 8px; font-size: 14px; color: #0f172a; font-weight: 600; }
.slider { width: 100%; accent-color: #10b981; }
.btn-primary { background: #059669; color: #ffffff; border: none; padding: 12px 18px; border-radius: 10px; font-weight: 700; font-size: 14px; cursor: pointer; box-shadow: 0 4px 12px rgba(5, 150, 105, 0.25); transition: all 0.2s; }
.btn-primary:hover { background: #047857; }

.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-bottom: 20px; }
.metric-card { background: #f8fafc; padding: 16px; border-radius: 10px; display: flex; flex-direction: column; border: 1px solid #e2e8f0; border-left: 5px solid #10b981; }
.metric-card.danger { border-left-color: #ef4444; }
.metric-card.success { border-left-color: #10b981; }
.metric-label { font-size: 12px; color: #64748b; font-weight: 600; margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: 800; color: #0f172a; }

.image-wrapper h3 { font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }
.annotated-img { width: 100%; border-radius: 10px; border: 1px solid #cbd5e1; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.empty-state, .loading-state { text-align: center; padding: 60px 20px; color: #475569; font-weight: 500; }
.empty-icon { font-size: 48px; display: block; margin-bottom: 12px; }
.spinner { width: 36px; height: 36px; border: 4px solid #e2e8f0; border-top-color: #10b981; border-radius: 50%; animation: spin 1s infinite linear; margin: 0 auto 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
.json-details { margin-top: 24px; background: #0f172a; padding: 14px; border-radius: 10px; color: #f8fafc; }
.json-details summary { cursor: pointer; font-weight: 600; color: #38bdf8; }
.json-code { font-size: 12px; overflow-x: auto; color: #38bdf8; margin-top: 12px; }

.mode-radio-group { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.radio-pill { display: flex; align-items: center; gap: 10px; background: #f8fafc; border: 1px solid #cbd5e1; padding: 10px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; color: #334155; cursor: pointer; transition: all 0.2s; }
.radio-pill.active { background: #ecfdf5; border-color: #059669; color: #047857; }
.radio-input { accent-color: #059669; }

.action-btn-row { display: flex; gap: 12px; margin-top: 12px; }
.flex-1 { flex: 1; }
.btn-camera { background: #334155; color: white; border: none; padding: 14px; border-radius: 10px; font-weight: 700; font-size: 14px; cursor: pointer; transition: all 0.2s; text-align: center; }
.btn-camera:hover { background: #1e293b; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.camera-modal { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; width: 920px; max-width: 96vw; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
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

.public-url-info-box { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #1e40af; }
.url-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.url-chips code { background: #dbeafe; color: #1d4ed8; border-radius: 5px; padding: 2px 8px; font-size: 11px; font-family: monospace; font-weight: 700; }
.url-note { font-size: 12px; color: #3b82f6; font-style: italic; }

.justify-end { justify-content: flex-end; }
.mt-16 { margin-top: 16px; }
</style>

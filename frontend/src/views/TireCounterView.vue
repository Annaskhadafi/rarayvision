<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

// Dynamic API base URL: Use Nginx reverse proxy /tire-api in Docker/Dokploy production, or localhost:8001 for local Vite dev
const isLocalVite = typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') && window.location.port === '5173'
const TIRE_API = isLocalVite ? 'http://localhost:8001' : '/tire-api'

// Stream & Status
const streamSrc = ref('')
const sourceBadge = ref('SIMULATED MINING YARD')
const fps = ref('0.0')
const statusActive = ref(false)
const activeSourceUrl = ref('')

// Telemetry
const totalLive = ref(0)
const inflow = ref(0)
const outflow = ref(0)
const netDelta = ref('+0')
const zoneCounts = ref({})
const recentEvents = ref([])

// Tab state
const activeTab = ref('sample')

// Universal model list — available across ALL source modes
const MODEL_OPTIONS = [
  { value: 'yolov8s-worldv2.pt', label: '🌍 YOLO-World v2 Small (Zero-Shot · Tire/OTR/Wheel)' },
  { value: 'yolov8x-worldv2.pt', label: '🌍 YOLO-World v2 X-Large (Zero-Shot · Max Accuracy)' },
  { value: 'yolov8n.pt',         label: '⚡ YOLOv8 Nano (Fastest · Low Resource)' },
  { value: 'yolov8s.pt',         label: '⚡ YOLOv8 Small (Fast · Balanced)' },
  { value: 'yolov8m.pt',         label: '🔎 YOLOv8 Medium (High Accuracy)' },
  { value: 'yolov8l.pt',         label: '🔎 YOLOv8 Large (Very High Accuracy)' },
  { value: 'yolov8x.pt',         label: '🔎 YOLOv8 X-Large (Maximum Accuracy)' },
  { value: 'yolov9c.pt',         label: '🆕 YOLOv9 C (Gen 9 · High Recall)' },
  { value: 'yolov9e.pt',         label: '🆕 YOLOv9 E (Gen 9 · Extra Large)' },
  { value: 'yolo11n.pt',         label: '🚀 YOLO11 Nano (Latest Gen · Ultra Fast)' },
  { value: 'yolo11s.pt',         label: '🚀 YOLO11 Small (Latest Gen)' },
  { value: 'yolo11m.pt',         label: '🚀 YOLO11 Medium (Latest Gen · Balanced)' },
]

// Shared settings across all sources
const selectedModel = ref('yolov8n.pt')
const confThresh = ref(0.25)
const iouThresh = ref(0.45)

// Source-specific fields
const webcamIndex = ref(0)
const rtspUrl = ref('')
const publicUrl = ref('')
const uploadFile = ref(null)
const uploadFileName = ref('')
const isApplying = ref(false)
const serverOffline = ref(false)

// City / public camera URL presets
const CITY_CAM_PRESETS = [
  { label: '── Paste your own URL below ──', value: '' },
  { label: '🧪 Test HLS Stream (Mux)', value: 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8' },
  { label: '🧪 Test MP4 HTTP Stream (BigBuckBunny)', value: 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4' },
  { label: '▶ YouTube Live (paste URL below)', value: 'https://www.youtube.com/watch?v=' },
  { label: '🎮 Twitch Live (paste URL below)', value: 'https://www.twitch.tv/' },
  { label: '📘 Facebook Live (paste URL below)', value: 'https://www.facebook.com/videos/' },
  { label: '📡 Generic IP Cam MJPEG (replace IP)', value: 'http://192.168.x.x/videostream.cgi' },
  { label: '📡 Generic RTSP IP Cam (replace IP)', value: 'rtsp://admin:password@192.168.x.x:554/stream' },
  { label: '📡 Generic RTMP Stream (replace server)', value: 'rtmp://live.example.com/live/stream_key' },
]

const bayColors = ['#3b82f6', '#f97316', '#10b981', '#a855f7', '#ef4444', '#eab308']

// ---- Actions ----

function reloadStream() {
  streamSrc.value = `${TIRE_API}/api/stream?t=${Date.now()}`
}

function applyPreset(val) {
  if (val) publicUrl.value = val
}

async function applySource(type, extra = {}) {
  isApplying.value = true
  try {
    const fd = new FormData()
    fd.append('source_type', type)
    if (extra.camera_index !== undefined) fd.append('camera_index', extra.camera_index)
    if (extra.rtsp_url)   fd.append('rtsp_url', extra.rtsp_url)
    if (extra.public_url) fd.append('public_url', extra.public_url)
    fd.append('model_name', selectedModel.value)
    fd.append('conf', confThresh.value)
    fd.append('iou', iouThresh.value)
    const res = await fetch(`${TIRE_API}/api/source/select`, { method: 'POST', body: fd })
    if (res.ok) {
      const badgeMap = {
        sample:          '🚜 SIMULATED MINING YARD',
        sample_conveyor: '📦 SIMULATED CONVEYOR',
        webcam:          `📹 WEBCAM #${extra.camera_index ?? 0}`,
        rtsp:            '📡 CCTV RTSP LIVE',
        public_url:      `🌐 ${(extra.public_url || '').length > 38 ? (extra.public_url || '').substring(0, 38) + '…' : (extra.public_url || '')}`,
      }
      sourceBadge.value = badgeMap[type] || type.toUpperCase()
      activeSourceUrl.value = extra.public_url || extra.rtsp_url || ''
      setTimeout(reloadStream, 450)
    } else {
      const err = await res.json().catch(() => ({}))
      alert(`Error: ${err.detail || 'Failed to switch source'}`)
    }
  } catch {
    serverOffline.value = true
  } finally {
    isApplying.value = false
  }
}

async function uploadAndStart() {
  if (!uploadFile.value) return
  isApplying.value = true
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    fd.append('model_name', selectedModel.value)
    fd.append('conf', confThresh.value)
    fd.append('iou', iouThresh.value)
    const res = await fetch(`${TIRE_API}/api/source/upload`, { method: 'POST', body: fd })
    if (res.ok) {
      const data = await res.json()
      sourceBadge.value = `📁 UPLOADED: ${data.filename}`
      setTimeout(reloadStream, 500)
    }
  } catch {
    serverOffline.value = true
  } finally {
    isApplying.value = false
  }
}

async function resetCounts() {
  await fetch(`${TIRE_API}/api/reset`, { method: 'POST' }).catch(() => {})
}

function exportJson() {
  window.open(`${TIRE_API}/api/export/json`, '_blank')
}

function onFileChange(e) {
  uploadFile.value = e.target.files?.[0] || null
  uploadFileName.value = uploadFile.value?.name || ''
}

// ---- Telemetry Polling ----
let pollingTimer = null

async function pollTelemetry() {
  try {
    const res = await fetch(`${TIRE_API}/api/telemetry`)
    if (res.ok) {
      serverOffline.value = false
      const data = await res.json()
      const s = data.summary || {}
      fps.value = (s.fps || 0).toFixed(1)
      statusActive.value = s.status === 'running'
      totalLive.value = s.total_live_count || 0
      inflow.value = s.in_count || 0
      outflow.value = s.out_count || 0
      const net = (s.in_count || 0) - (s.out_count || 0)
      netDelta.value = net >= 0 ? `+${net}` : `${net}`
      zoneCounts.value = s.zone_counts || {}
      recentEvents.value = (data.recent_events || []).slice(-10).reverse()
    } else {
      serverOffline.value = true
    }
  } catch {
    serverOffline.value = true
  }
}

onMounted(() => {
  pollTelemetry()
  pollingTimer = setInterval(pollTelemetry, 1000)
  // Attach stream after initial DOM mount to complete browser document load state and stop tab spinner
  setTimeout(() => {
    streamSrc.value = `${TIRE_API}/api/stream?t=${Date.now()}`
  }, 350)
})

onBeforeUnmount(() => {
  clearInterval(pollingTimer)
  streamSrc.value = ''
})
</script>

<template>
  <section class="tc-page">
    <!-- Page Header -->
    <div class="tc-page-header">
      <div>
        <p class="eyebrow">Computer Vision · YOLO</p>
        <h2>Mining OTR & Warehouse Tire Counter</h2>
        <p class="tc-subtitle">Object detection & multi-zone stock tracking for mining giant tires (OTR) and warehouse inventory using Ultralytics YOLO + ByteTrack</p>
      </div>
      <div class="tc-header-actions">
        <div :class="['tc-status-badge', statusActive && !serverOffline ? 'online' : 'offline']">
          <span class="tc-dot"></span>
          {{ serverOffline ? 'Service Offline' : statusActive ? 'LIVE RUNNING' : 'Initializing...' }}
        </div>
        <div class="tc-fps-chip">
          <span class="tc-fps-label">FPS</span>
          <span class="tc-fps-val">{{ fps }}</span>
        </div>
      </div>
    </div>

    <!-- Offline Banner -->
    <div v-if="serverOffline" class="tc-offline-banner">
      ⚠️ Tire Counter microservice sedang tidak aktif / connecting ke <strong>{{ isLocalVite ? 'localhost:8001' : '/tire-api' }}</strong>.
      <span v-if="isLocalVite">
        &nbsp;Jalankan: <code>python "d:/[01] PROJECT/Raray VIsion/warehouse-tire-counter/app.py"</code> lalu refresh.
      </span>
      <span v-else>
        &nbsp;Pastikan container <code>rarayvision-tire-counter</code> aktif di Dokploy.
      </span>
    </div>


    <div class="tc-grid">
      <!-- LEFT: Video Feed + Source Controls -->
      <div class="tc-left">
        <!-- Video Stream -->
        <div class="tc-video-wrap">
          <img v-if="streamSrc" :src="streamSrc" alt="Tire Detection Live Stream" class="tc-video-img" />
          <div v-else class="tc-video-img" style="display:flex; align-items:center; justify-content:center; background:#0b1120; color:#94a3b8; font-size:14px;">
            <span>⏳ Loading video stream...</span>
          </div>
          <div class="tc-video-badge">{{ sourceBadge }}</div>

          <div class="tc-stream-actions">
            <button class="tc-icon-btn" @click="reloadStream" title="Refresh Stream">
              <svg viewBox="0 0 24 24" width="17" height="17" stroke="currentColor" stroke-width="2" fill="none"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19"/></svg>
            </button>
            <button class="tc-icon-btn danger" @click="resetCounts" title="Reset All Counts">
              <svg viewBox="0 0 24 24" width="17" height="17" stroke="currentColor" stroke-width="2" fill="none"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            </button>
          </div>
        </div>

        <!-- Source Selector Panel -->
        <div class="tc-source-panel">

          <!-- Global Settings Bar: Model + Conf + IOU — shared across ALL source types -->
          <div class="tc-global-settings">
            <div class="tc-form-group" style="flex:2">
              <label>Detection Model (Applied to all sources)</label>
              <select v-model="selectedModel" class="tc-select">
                <option v-for="m in MODEL_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </div>
            <div class="tc-form-group">
              <label>Confidence: <strong>{{ confThresh.toFixed(2) }}</strong></label>
              <input type="range" v-model.number="confThresh" min="0.05" max="0.95" step="0.05" class="tc-range" />
            </div>
            <div class="tc-form-group">
              <label>IoU Threshold: <strong>{{ iouThresh.toFixed(2) }}</strong></label>
              <input type="range" v-model.number="iouThresh" min="0.20" max="0.90" step="0.05" class="tc-range" />
            </div>
          </div>

          <!-- Tabs -->
          <div class="tc-tabs">
            <button v-for="tab in [
              { key: 'sample',           label: '🚜 Mining Yard' },
              { key: 'sample_conveyor',  label: '📦 Conveyor' },
              { key: 'webcam',           label: '📹 Webcam' },
              { key: 'upload',           label: '📁 Upload Video' },
              { key: 'rtsp',             label: '📡 CCTV RTSP' },
              { key: 'public_url',       label: '🌐 Public URL / City Cam' },
            ]" :key="tab.key"
              :class="['tc-tab', activeTab === tab.key ? 'active' : '']"
              @click="activeTab = tab.key"
            >{{ tab.label }}</button>
          </div>

          <!-- Mining Yard Simulation -->
          <div v-if="activeTab === 'sample'" class="tc-form-row">
            <div class="tc-form-group tc-form-action" style="align-self:flex-end">
              <button class="tc-btn-primary" :disabled="isApplying" @click="applySource('sample')">
                {{ isApplying ? 'Switching...' : '▶ Stream Mining Yard' }}
              </button>
            </div>
          </div>

          <!-- Conveyor -->
          <div v-if="activeTab === 'sample_conveyor'" class="tc-form-row">
            <div class="tc-form-group tc-form-action" style="align-self:flex-end">
              <button class="tc-btn-primary" :disabled="isApplying" @click="applySource('sample_conveyor')">
                {{ isApplying ? 'Switching...' : '▶ Stream Conveyor' }}
              </button>
            </div>
          </div>

          <!-- Webcam -->
          <div v-if="activeTab === 'webcam'" class="tc-form-row">
            <div class="tc-form-group">
              <label>Camera Index</label>
              <select v-model.number="webcamIndex" class="tc-select">
                <option :value="0">Camera 0 (Default / Integrated)</option>
                <option :value="1">Camera 1 (External USB)</option>
                <option :value="2">Camera 2</option>
              </select>
            </div>
            <div class="tc-form-group tc-form-action">
              <button class="tc-btn-primary" :disabled="isApplying" @click="applySource('webcam', { camera_index: webcamIndex })">
                {{ isApplying ? 'Connecting...' : '▶ Start Live Camera' }}
              </button>
            </div>
          </div>

          <!-- Upload Video -->
          <div v-if="activeTab === 'upload'" class="tc-form-col">
            <div class="tc-dropzone" @click="$refs.fileInput.click()">
              <svg viewBox="0 0 24 24" width="30" height="30" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
              <p><strong>Click to browse</strong> or drag & drop CCTV / drone video (.mp4, .avi, .mov)</p>
              <span v-if="uploadFileName" class="tc-file-name">📄 {{ uploadFileName }}</span>
            </div>
            <input type="file" ref="fileInput" accept="video/*" hidden @change="onFileChange" />
            <div class="tc-form-row" style="margin-top:0.6rem;">
              <div class="tc-form-group tc-form-action">
                <button class="tc-btn-primary" :disabled="isApplying || !uploadFile" @click="uploadAndStart">
                  {{ isApplying ? 'Uploading...' : '▶ Upload & Count' }}
                </button>
              </div>
            </div>
          </div>

          <!-- CCTV RTSP -->
          <div v-if="activeTab === 'rtsp'" class="tc-form-row">
            <div class="tc-form-group" style="flex:3">
              <label>RTSP Stream URL</label>
              <input v-model="rtspUrl" class="tc-input" placeholder="rtsp://admin:password@192.168.1.100:554/stream1" />
            </div>
            <div class="tc-form-group tc-form-action">
              <button class="tc-btn-primary" :disabled="isApplying || !rtspUrl" @click="applySource('rtsp', { rtsp_url: rtspUrl })">
                {{ isApplying ? 'Connecting...' : '▶ Connect RTSP' }}
              </button>
            </div>
          </div>

          <!-- Public URL / City Camera -->
          <div v-if="activeTab === 'public_url'" class="tc-form-col">
            <div class="tc-url-info-box">
              <strong>🌐 Supports any public stream URL:</strong>
              <span class="tc-url-chips">
                <code>http://</code><code>https://</code><code>rtsp://</code><code>rtmp://</code><code>.m3u8</code><code>.mjpeg</code>
              </span>
              <span class="tc-url-note">Ideal for city CCTV cameras, traffic monitoring, public IP cameras, HLS streams, and surveillance feeds.</span>
            </div>

            <div class="tc-form-row" style="margin-top:0.6rem;">
              <div class="tc-form-group" style="flex:2">
                <label>Quick Presets (optional)</label>
                <select class="tc-select" @change="e => applyPreset(e.target.value)">
                  <option v-for="p in CITY_CAM_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
                </select>
              </div>
            </div>

            <div class="tc-form-row" style="margin-top:0.5rem; align-items:flex-end;">
              <div class="tc-form-group" style="flex:3">
                <label>Stream URL</label>
                <input
                  v-model="publicUrl"
                  class="tc-input tc-url-input"
                  placeholder="https://stream.city.gov/cam01/stream.m3u8 or rtsp://cam.example.com/live"
                  spellcheck="false"
                />
              </div>
              <div class="tc-form-group tc-form-action">
                <button class="tc-btn-primary" :disabled="isApplying || !publicUrl.trim()" @click="applySource('public_url', { public_url: publicUrl.trim() })">
                  {{ isApplying ? 'Connecting...' : '▶ Connect & Detect' }}
                </button>
              </div>
            </div>

            <div v-if="activeSourceUrl" class="tc-active-url">
              🔴 Live: <code>{{ activeSourceUrl }}</code>
            </div>
          </div>

        </div>
      </div>


      <!-- RIGHT: Telemetry Panel -->
      <div class="tc-right">
        <!-- KPI Cards Grid -->
        <div class="tc-kpi-grid">
          <div class="tc-kpi-card tc-kpi-main">
            <div class="tc-kpi-row">
              <span class="tc-kpi-label">TOTAL LIVE IN-YARD</span>
              <span>🚜</span>
            </div>
            <div class="tc-kpi-value tc-kpi-big">{{ totalLive }}</div>
            <div class="tc-kpi-sub">Active OTR Tires in Camera View</div>
          </div>
          <div class="tc-kpi-card">
            <div class="tc-kpi-row">
              <span class="tc-kpi-label">LINE IN (Inflow)</span>
              <span class="green">⬇</span>
            </div>
            <div class="tc-kpi-value green">{{ inflow }}</div>
            <div class="tc-kpi-sub">Crossed Inward Gate</div>
          </div>
          <div class="tc-kpi-card">
            <div class="tc-kpi-row">
              <span class="tc-kpi-label">LINE OUT (Outflow)</span>
              <span class="orange">⬆</span>
            </div>
            <div class="tc-kpi-value orange">{{ outflow }}</div>
            <div class="tc-kpi-sub">Crossed Outward Gate</div>
          </div>
          <div class="tc-kpi-card">
            <div class="tc-kpi-row">
              <span class="tc-kpi-label">NET STOCK DELTA</span>
              <span class="blue">∑</span>
            </div>
            <div class="tc-kpi-value blue">{{ netDelta }}</div>
            <div class="tc-kpi-sub">Inflow − Outflow Balance</div>
          </div>
        </div>

        <!-- Yard Bay Breakdown -->
        <div class="tc-card">
          <div class="tc-card-header">
            <h3>Yard Bay Inventory Breakdown</h3>
            <span class="tc-card-tag">ZONED STOCK</span>
          </div>
          <div class="tc-card-body">
            <div v-if="Object.keys(zoneCounts).length === 0" class="tc-empty">
              No zones configured or no detections yet.
            </div>
            <div v-for="(count, zone, idx) in zoneCounts" :key="zone" class="tc-bay-item">
              <div class="tc-bay-info">
                <span class="tc-bay-dot" :style="{ background: bayColors[idx % bayColors.length] }"></span>
                <span class="tc-bay-name">{{ zone }}</span>
              </div>
              <span class="tc-bay-count">{{ count }} units</span>
            </div>
          </div>
        </div>

        <!-- Event Log -->
        <div class="tc-card">
          <div class="tc-card-header">
            <h3>Recent Movements & Detections</h3>
            <button class="tc-text-btn" @click="exportJson">Export JSON</button>
          </div>
          <div class="tc-card-body tc-card-scroll">
            <table class="tc-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Track ID</th>
                  <th>Class</th>
                  <th>Direction</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="recentEvents.length === 0">
                  <td colspan="4" class="tc-empty-cell">Waiting for events…</td>
                </tr>
                <tr v-for="e in recentEvents" :key="`${e.track_id}-${e.timestamp}`">
                  <td>{{ e.timestamp?.split('T')[1]?.split('.')[0] ?? '--' }}</td>
                  <td>#{{ e.track_id }}</td>
                  <td>{{ e.class || 'tire' }}</td>
                  <td :style="{ color: e.direction === 'IN' ? '#16a34a' : '#ea580c', fontWeight: 700 }">{{ e.direction }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* Page shell */
.tc-page {
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  min-height: 100%;
}

.tc-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: #64748b;
  margin-bottom: 4px;
}

.tc-page-header h2 {
  font-size: 1.5rem;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.tc-subtitle {
  font-size: 0.83rem;
  color: #64748b;
  margin-top: 4px;
  max-width: 560px;
}

.tc-header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}

.tc-status-badge {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.35rem 0.85rem;
  border-radius: 999px;
  font-size: 0.73rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #94a3b8;
}

.tc-status-badge.online {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #16a34a;
}

.tc-status-badge.offline {
  background: #fff7ed;
  border-color: #fed7aa;
  color: #ea580c;
}

.tc-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.online .tc-dot {
  animation: pulse-dot 2s infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.tc-fps-chip {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.3rem 0.65rem;
  font-size: 0.82rem;
}

.tc-fps-label { color: #94a3b8; font-weight: 500; }
.tc-fps-val { color: #2563eb; font-weight: 700; font-family: monospace; }

/* Offline Banner */
.tc-offline-banner {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  padding: 0.85rem 1.25rem;
  font-size: 0.83rem;
  color: #9a3412;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.tc-offline-banner code {
  background: #ffedd5;
  border-radius: 4px;
  padding: 0.1rem 0.45rem;
  font-size: 0.78rem;
  font-family: monospace;
}

/* Two-column layout */
.tc-grid {
  display: grid;
  grid-template-columns: 1fr 400px;
  gap: 1.25rem;
}

@media (max-width: 1100px) {
  .tc-grid { grid-template-columns: 1fr; }
}

/* --- Video section --- */
.tc-left {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.tc-video-wrap {
  position: relative;
  width: 100%;
  min-height: 420px;
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.tc-video-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.tc-video-badge {
  position: absolute;
  top: 0.75rem;
  left: 0.75rem;
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(8px);
  color: #f8fafc;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 0.28rem 0.65rem;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.12);
}

.tc-stream-actions {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  display: flex;
  gap: 0.4rem;
}

.tc-icon-btn {
  width: 34px;
  height: 34px;
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 7px;
  color: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.18s;
}

.tc-icon-btn:hover { background: rgba(37, 99, 235, 0.85); }
.tc-icon-btn.danger:hover { background: rgba(220, 38, 38, 0.85); }

/* Source Panel */
.tc-source-panel {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.25rem;
}

.tc-tabs {
  display: flex;
  gap: 0.4rem;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.75rem;
  margin-bottom: 1rem;
  overflow-x: auto;
}

.tc-tab {
  background: transparent;
  border: 1px solid transparent;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.45rem 0.9rem;
  border-radius: 7px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.tc-tab:hover { background: #f8fafc; color: #2563eb; }
.tc-tab.active { background: #eff6ff; border-color: #bfdbfe; color: #2563eb; }

.tc-form-row {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  flex-wrap: wrap;
}

.tc-form-col {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.tc-form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
  min-width: 160px;
}

.tc-form-action { flex: 0 0 auto; min-width: auto; }

.tc-form-group label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
}

.tc-select, .tc-input {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  color: #0f172a;
  font-size: 0.82rem;
  padding: 0.5rem 0.75rem;
  outline: none;
  transition: border-color 0.15s;
}

.tc-select:focus, .tc-input:focus { border-color: #2563eb; }

.tc-range { accent-color: #2563eb; cursor: pointer; width: 100%; }

.tc-btn-primary {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 7px;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.55rem 1.1rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.tc-btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.tc-btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }

/* Dropzone */
.tc-dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  color: #64748b;
  background: #f8fafc;
  transition: all 0.15s;
}

.tc-dropzone:hover { border-color: #2563eb; background: #eff6ff; }
.tc-dropzone svg { color: #94a3b8; }
.tc-dropzone p { font-size: 0.82rem; text-align: center; }
.tc-file-name { font-size: 0.78rem; color: #2563eb; font-weight: 600; font-family: monospace; }

/* Global Settings Bar */
.tc-global-settings {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  flex-wrap: wrap;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.75rem;
}

/* Public URL Info Box */
.tc-url-info-box {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  padding: 0.75rem 1rem;
  font-size: 0.82rem;
  color: #1e40af;
}

.tc-url-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.2rem;
}

.tc-url-chips code {
  background: #dbeafe;
  color: #1d4ed8;
  border-radius: 5px;
  padding: 0.15rem 0.45rem;
  font-size: 0.76rem;
  font-family: monospace;
  font-weight: 700;
}

.tc-url-note {
  font-size: 0.78rem;
  color: #3b82f6;
  font-style: italic;
}

.tc-url-input {
  font-family: monospace;
  font-size: 0.8rem;
  letter-spacing: 0;
}

.tc-active-url {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 7px;
  padding: 0.5rem 0.85rem;
  font-size: 0.78rem;
  color: #991b1b;
  margin-top: 0.4rem;
  flex-wrap: wrap;
}

.tc-active-url code {
  font-family: monospace;
  font-size: 0.76rem;
  color: #dc2626;
  word-break: break-all;
}


/* --- Right column --- */
.tc-right {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* KPI */
.tc-kpi-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.tc-kpi-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  transition: border-color 0.15s;
}

.tc-kpi-card:hover { border-color: #cbd5e1; }

.tc-kpi-main {
  grid-column: span 2;
  background: linear-gradient(135deg, #eff6ff 0%, #fff 100%);
  border-color: #bfdbfe;
}

.tc-kpi-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tc-kpi-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #94a3b8;
  text-transform: uppercase;
}

.tc-kpi-value {
  font-family: monospace;
  font-size: 1.65rem;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.1;
  margin-top: 2px;
}

.tc-kpi-big { font-size: 2rem; }
.tc-kpi-sub { font-size: 0.72rem; color: #94a3b8; }

.green { color: #16a34a !important; }
.orange { color: #ea580c !important; }
.blue { color: #2563eb !important; }

/* Cards */
.tc-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}

.tc-card-header {
  padding: 0.8rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tc-card-header h3 { font-size: 0.85rem; font-weight: 700; color: #0f172a; }

.tc-card-tag {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.18rem 0.45rem;
  border-radius: 4px;
  background: #f1f5f9;
  color: #64748b;
  letter-spacing: 0.04em;
}

.tc-text-btn {
  background: none;
  border: none;
  font-size: 0.75rem;
  font-weight: 700;
  color: #2563eb;
  cursor: pointer;
}

.tc-text-btn:hover { text-decoration: underline; }

.tc-card-body { padding: 0.85rem 1rem; }
.tc-card-scroll { max-height: 210px; overflow-y: auto; padding: 0; }

.tc-bay-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.55rem 0.85rem;
  background: #f8fafc;
  border-radius: 7px;
  border: 1px solid #f1f5f9;
  margin-bottom: 0.4rem;
}

.tc-bay-info { display: flex; align-items: center; gap: 0.55rem; }
.tc-bay-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.tc-bay-name { font-size: 0.8rem; font-weight: 600; color: #334155; }
.tc-bay-count { font-size: 0.83rem; font-weight: 800; color: #2563eb; font-family: monospace; }

/* Table */
.tc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}

.tc-table th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  padding: 0.55rem 0.9rem;
  font-weight: 700;
  color: #64748b;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

.tc-table td {
  padding: 0.5rem 0.9rem;
  color: #334155;
  border-bottom: 1px solid #f1f5f9;
  font-family: monospace;
}

.tc-empty { font-size: 0.8rem; color: #94a3b8; font-style: italic; text-align: center; padding: 1rem; }
.tc-empty-cell { text-align: center; padding: 1.5rem !important; color: #94a3b8; font-style: italic; }
</style>

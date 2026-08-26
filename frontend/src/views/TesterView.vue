<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { API_BASE_URL } from '../utils'

const activeTab = ref('test') // 'test' | 'config'
const testMode = ref('recognize') // 'recognize' | 'compare' | 'liveness'
const selectedUserId = ref('')
const uploadFile = ref(null)
const uploadPreviewUrl = ref(null)
const isCameraActive = ref(false)
const videoEl = ref(null)
const canvasEl = ref(null)
const stream = ref(null)
const isTesting = ref(false)
const testResult = ref(null)
const rawJsonResponse = ref('')

// User selector
const registeredUsers = ref([])
const loadingUsers = ref(false)

// Config variables (shared with SettingsView.vue)
const config = ref({
  threshold: 0.40,
  engine_mode: 'v1',
  check_liveness: true,
  liveness_threshold: 0.55,
  laplacian_threshold: 0.35
})
const isFetchingConfig = ref(false)
const isSavingConfig = ref(false)
const configMessage = ref('')
const configError = ref('')

// MediaPipe facial mesh mapping
let mediaPipeFaceMesh = null
const mediaPipeLoading = ref(false)
const hasMediaPipeFace = ref(false)
const faceRafId = ref(null)

const authHeaders = () => ({
  'Authorization': `Bearer ${localStorage.getItem('rarayvision-token')}`
})

// Fetch current configuration
const fetchConfig = async () => {
  isFetchingConfig.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/system/face-config`, { headers: authHeaders() })
    const data = await res.json()
    if (res.ok && data.status === 'success') {
      config.value = {
        threshold: data.threshold,
        engine_mode: data.engine_mode,
        check_liveness: data.check_liveness,
        liveness_threshold: data.liveness_threshold,
        laplacian_threshold: data.laplacian_threshold
      }
    }
  } catch (e) {
    console.error('Failed to fetch config', e)
  } finally {
    isFetchingConfig.value = false
  }
}

// Save configuration
const saveConfig = async () => {
  isSavingConfig.value = true
  configMessage.value = ''
  configError.value = ''
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/system/face-config`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(config.value)
    })
    const data = await res.json()
    if (res.ok && data.status === 'success') {
      configMessage.value = 'Settings saved successfully!'
      setTimeout(() => { configMessage.value = '' }, 3000)
    } else {
      configError.value = data.detail || data.message || 'Failed to save config'
    }
  } catch (e) {
    configError.value = e.message
  } finally {
    isSavingConfig.value = false
  }
}

// Fetch users
const fetchUsers = async () => {
  loadingUsers.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/users`, { headers: authHeaders() })
    const data = await res.json()
    if (res.ok && data.status === 'success') {
      registeredUsers.value = data.users || []
      // Auto select first user with a registered face
      const faceUser = registeredUsers.value.find(u => u.has_face)
      if (faceUser) {
        selectedUserId.value = faceUser.id
      }
    }
  } catch (e) {
    console.error('Failed to fetch users', e)
  } finally {
    loadingUsers.value = false
  }
}

onMounted(() => {
  fetchConfig()
  fetchUsers()
})

onUnmounted(() => {
  stopCamera()
})

const startCamera = async () => {
  testResult.value = null
  rawJsonResponse.value = ''
  try {
    const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
    stream.value = s
    isCameraActive.value = true
    await nextTick()
    videoEl.value.srcObject = s
    await videoEl.value.play()
    
    startMediaPipeLoop()
  } catch (e) {
    alert(`Camera error: ${e.message}`)
  }
}

const stopCamera = () => {
  if (stream.value) {
    stream.value.getTracks().forEach(t => t.stop())
    stream.value = null
  }
  cancelAnimationFrame(faceRafId.value)
  isCameraActive.value = false
  hasMediaPipeFace.value = false
  const canvas = canvasEl.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
  }
}

const ensureMediaPipe = async () => {
  if (mediaPipeFaceMesh) return
  mediaPipeLoading.value = true
  if (!window.FaceMesh) {
    await new Promise((resolve) => {
      const s1 = document.createElement('script')
      s1.src = 'https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js'
      document.head.appendChild(s1)
      s1.onload = () => {
        const s2 = document.createElement('script')
        s2.src = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/face_mesh.js'
        document.head.appendChild(s2)
        s2.onload = () => {
          const s3 = document.createElement('script')
          s3.src = 'https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js'
          document.head.appendChild(s3)
          s3.onload = resolve
        }
      }
    })
  }
  mediaPipeFaceMesh = new window.FaceMesh({locateFile: (file) => {
    return `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`;
  }});
  mediaPipeFaceMesh.setOptions({ maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5, minTrackingConfidence: 0.5 });
  mediaPipeFaceMesh.onResults((results) => {
    const canvas = canvasEl.value
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (results.multiFaceLandmarks && results.multiFaceLandmarks.length > 0) {
      hasMediaPipeFace.value = true
      ctx.save()
      ctx.translate(canvas.width, 0)
      ctx.scale(-1, 1)
      for (const landmarks of results.multiFaceLandmarks) {
        window.drawConnectors(ctx, landmarks, window.FACEMESH_TESSELATION, {color: '#06b6d4', lineWidth: 1});
        window.drawConnectors(ctx, landmarks, window.FACEMESH_RIGHT_EYE, {color: '#22d3ee', lineWidth: 2});
        window.drawConnectors(ctx, landmarks, window.FACEMESH_LEFT_EYE, {color: '#22d3ee', lineWidth: 2});
        window.drawConnectors(ctx, landmarks, window.FACEMESH_FACE_OVAL, {color: '#22d3ee', lineWidth: 2});
      }
      ctx.restore()
    } else {
      hasMediaPipeFace.value = false
    }
  });
  mediaPipeLoading.value = false
}

const startMediaPipeLoop = () => {
  let isSending = false
  const loop = async () => {
    faceRafId.value = requestAnimationFrame(loop)
    if (!isCameraActive.value) return
    if (!window.FaceMesh && !mediaPipeLoading.value) {
      ensureMediaPipe()
    } else if (mediaPipeFaceMesh && !mediaPipeLoading.value && !isSending) {
      const video = videoEl.value
      if (video && video.readyState >= 2) {
        if (canvasEl.value && canvasEl.value.width !== video.videoWidth) {
          canvasEl.value.width = video.videoWidth
          canvasEl.value.height = video.videoHeight
        }
        isSending = true
        await mediaPipeFaceMesh.send({image: video}).catch(e => console.error(e))
        isSending = false
      }
    }
  }
  loop()
}

const handleFileChange = (e) => {
  const file = e.target.files?.[0] || null
  uploadFile.value = file
  testResult.value = null
  rawJsonResponse.value = ''
  if (file) {
    uploadPreviewUrl.value = URL.createObjectURL(file)
  } else {
    uploadPreviewUrl.value = null
  }
}

const runTest = async () => {
  if (isCameraActive.value) {
    // Capture webcam snapshot first
    const video = videoEl.value
    if (!video || video.readyState < 2) return
    const offscreen = document.createElement('canvas')
    offscreen.width = video.videoWidth
    offscreen.height = video.videoHeight
    offscreen.getContext('2d').drawImage(video, 0, 0)
    offscreen.toBlob((blob) => {
      executeTestRequest(blob)
    }, 'image/jpeg', 0.9)
  } else {
    if (!uploadFile.value) {
      alert('Please upload an image file first or start the camera.')
      return
    }
    executeTestRequest(uploadFile.value)
  }
}

const executeTestRequest = async (imageBlob) => {
  isTesting.value = true
  testResult.value = null
  rawJsonResponse.value = ''
  
  const fd = new FormData()
  fd.append('file', imageBlob, 'test_face.jpg')

  let url = ''
  if (testMode.value === 'recognize') {
    url = `${API_BASE_URL}/api/v1/faces/recognize`
  } else if (testMode.value === 'compare') {
    url = `${API_BASE_URL}/api/v1/faces/compare`
    fd.append('user_id', selectedUserId.value)
  } else if (testMode.value === 'liveness') {
    url = `${API_BASE_URL}/api/v1/faces/liveness`
  }

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('rarayvision-token')}` },
      body: fd
    })
    const data = await res.json()
    rawJsonResponse.value = JSON.stringify(data, null, 2)

    if (res.ok) {
      testResult.value = data
    } else {
      testResult.value = {
        status: 'error',
        message: data.detail || data.message || 'Verification endpoint returned an error.'
      }
    }
  } catch (e) {
    testResult.value = {
      status: 'error',
      message: `Failed to connect to server: ${e.message}`
    }
  } finally {
    isTesting.value = false
  }
}
</script>

<template>
  <section class="tester-page">
    <!-- Header -->
    <div class="tester-page-header">
      <div>
        <p class="eyebrow">Tools</p>
        <h2>Face Biometric Lab</h2>
      </div>
      <!-- Tab Selector -->
      <div style="display: flex; gap: 8px; background: #e2e8f0; padding: 4px; border-radius: 8px;">
        <button 
          @click="activeTab = 'test'"
          :class="['tab-btn', { active: activeTab === 'test' }]"
        >
          🧪 Testing Lab
        </button>
        <button 
          @click="activeTab = 'config'"
          :class="['tab-btn', { active: activeTab === 'config' }]"
        >
          ⚙️ Biometric Settings
        </button>
      </div>
    </div>

    <!-- Active Configurations Display Bar -->
    <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; font-size: 13.5px; color: #1e40af;">
      <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
        <span><strong>Active Engine:</strong> {{ config.engine_mode === 'v2' ? 'Engine V2 (CPU Turbo)' : 'Engine V1 (Standard)' }}</span>
        <span><strong>Similarity Threshold:</strong> {{ config.threshold }} ({{ Math.round(config.threshold * 100) }}%)</span>
        <span><strong>Liveness Check:</strong> {{ config.check_liveness ? `Active (Threshold ${config.liveness_threshold})` : 'Disabled' }}</span>
      </div>
      <button @click="activeTab = 'config'" style="background: none; border: none; font-weight: 700; color: #2563eb; cursor: pointer; display: flex; align-items: center; gap: 4px;">
        Configure Settings ➔
      </button>
    </div>

    <!-- CONFIGURATION TAB -->
    <section v-if="activeTab === 'config'" class="tester-panel tester-panel-full card">
      <div>
        <h3>⚙️ Biometric & Anti-Spoofing Settings</h3>
        <p style="font-size: 13px; color: #64748b; margin-top: 4px; margin-bottom: 20px;">
          Sesuaikan nilai ambang batas kecocokan (*threshold similarity*) dan pengaturan liveness secara instan.
        </p>
      </div>

      <div v-if="configMessage" style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; color: #166534; margin-bottom: 16px; font-weight: 500;">
        {{ configMessage }}
      </div>
      <div v-if="configError" style="background: #fef2f2; border: 1px solid #fca5a5; padding: 12px; border-radius: 8px; color: #b91c1c; margin-bottom: 16px; font-weight: 500;">
        {{ configError }}
      </div>

      <div style="display: flex; flex-direction: column; gap: 20px; max-width: 600px;">
        <!-- Engine selection -->
        <div>
          <label style="display:block; font-size:12px; font-weight:700; color:#475569; text-transform:uppercase; margin-bottom:8px;">Face Engine Mode</label>
          <div style="display: flex; gap: 12px;">
            <button 
              @click="config.engine_mode = 'v1'"
              type="button"
              :style="{
                flex: 1, padding: '12px', borderRadius: '8px', border: config.engine_mode === 'v1' ? '2px solid #3b82f6' : '1px solid #cbd5e1',
                background: config.engine_mode === 'v1' ? '#eff6ff' : 'white', fontWeight: 600, color: '#1e3a8a', cursor: 'pointer'
              }"
            >
              🛡️ V1 (Standard Buffalo_L)
            </button>
            <button 
              @click="config.engine_mode = 'v2'"
              type="button"
              :style="{
                flex: 1, padding: '12px', borderRadius: '8px', border: config.engine_mode === 'v2' ? '2px solid #10b981' : '1px solid #cbd5e1',
                background: config.engine_mode === 'v2' ? '#ecfdf5' : 'white', fontWeight: 600, color: '#064e3b', cursor: 'pointer'
              }"
            >
              🚀 V2 (CPU Turbo Buffalo_S)
            </button>
          </div>
        </div>

        <!-- Similarity threshold -->
        <div>
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <label style="font-size:12.5px; font-weight:600; color:#1e293b;">Similarity Threshold (Kemiripan Wajah)</label>
            <strong style="color:#2563eb;">{{ config.threshold }} ({{ Math.round(config.threshold * 100) }}%)</strong>
          </div>
          <input type="range" min="0.20" max="0.80" step="0.01" v-model.number="config.threshold" style="width:100%; accent-color:#2563eb; cursor:pointer;" />
          <span style="font-size:11.5px; color:#16a34a; font-weight:600; display:block; margin-top:4px;">Rekomendasi batas agar g gagal login: 0.40 (kemiripan 0.45 - 0.48 akan berhasil login)</span>
        </div>

        <!-- Liveness check toggle -->
        <div style="display:flex; align-items:center; justify-content:space-between; padding:12px; background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0;">
          <div>
            <strong style="font-size:13px; color:#1e293b;">Check Liveness (Anti-Spoofing)</strong>
            <p style="margin:2px 0 0; font-size:11.5px; color:#64748b;">Mendeteksi apakah wajah di kamera adalah foto/hp atau wajah asli.</p>
          </div>
          <label style="position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink:0;">
            <input type="checkbox" v-model="config.check_liveness" style="opacity: 0; width: 0; height: 0;">
            <span :style="{
              position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
              backgroundColor: config.check_liveness ? '#10b981' : '#cbd5e1',
              transition: '.3s', borderRadius: '34px'
            }">
              <span :style="{
                position: 'absolute', height: '18px', width: '18px', left: '3px', bottom: '3px',
                backgroundColor: 'white', transition: '.3s', borderRadius: '50%',
                transform: config.check_liveness ? 'translateX(20px)' : 'translateX(0)'
              }"></span>
            </span>
          </label>
        </div>

        <!-- Extra thresholds -->
        <div v-if="config.check_liveness" style="display:flex; flex-direction:column; gap:14px; padding-left:12px; border-left:2px solid #e2e8f0;">
          <div>
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
              <span style="font-size:12px; font-weight:600; color:#475569;">Liveness Threshold (MiniFASNetV2)</span>
              <strong style="font-size:12px; color:#10b981;">{{ config.liveness_threshold }}</strong>
            </div>
            <input type="range" min="0.30" max="0.80" step="0.01" v-model.number="config.liveness_threshold" style="width:100%; accent-color:#10b981;" />
          </div>
          <div>
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
              <span style="font-size:12px; font-weight:600; color:#475569;">Fallback Laplacian Threshold (Deteksi Tekstur & Ketajaman)</span>
              <strong style="font-size:12px; color:#10b981;">{{ config.laplacian_threshold }}</strong>
            </div>
            <input type="range" min="0.20" max="0.60" step="0.01" v-model.number="config.laplacian_threshold" style="width:100%; accent-color:#10b981;" />
          </div>
        </div>

        <!-- Submit -->
        <button 
          class="send-btn" 
          @click="saveConfig" 
          :disabled="isSavingConfig" 
          style="margin-top: 10px; background: #0f172a; color: white;"
        >
          {{ isSavingConfig ? 'Saving Settings...' : 'Save Settings & Threshold' }}
        </button>
      </div>
    </section>

    <!-- TESTING LAB TAB -->
    <div v-else style="display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 24px;">
      
      <!-- Input and Controls Panel -->
      <section class="tester-panel card">
        <div class="tester-header" style="margin-bottom: 20px;">
          <div>
            <p class="eyebrow">Verify Face</p>
            <h3>1. Select Test Mode & Image</h3>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 16px;">
          <!-- Select Mode -->
          <div>
            <label class="field-label" style="margin-bottom: 6px; color: #475569;">Pilih Metode Pengujian</label>
            <div style="display: flex; gap: 8px;">
              <button 
                v-for="mode in [
                  { id: 'recognize', name: '1:N Identify', desc: 'Identifikasi wajah terhadap semua database' },
                  { id: 'compare', name: '1:1 Verify', desc: 'Verifikasi wajah dengan user tertentu' },
                  { id: 'liveness', name: 'Liveness Check', desc: 'Analisis liveness/keaslian wajah saja' }
                ]" 
                :key="mode.id"
                @click="testMode = mode.id"
                type="button"
                :style="{
                  flex: 1, padding: '10px 8px', borderRadius: '6px', cursor: 'pointer',
                  border: testMode === mode.id ? '2px solid #2563eb' : '1px solid #cbd5e1',
                  background: testMode === mode.id ? '#eff6ff' : 'white',
                  fontWeight: testMode === mode.id ? '700' : '500',
                  color: testMode === mode.id ? '#1e40af' : '#475569'
                }"
                :title="mode.desc"
              >
                {{ mode.name }}
              </button>
            </div>
          </div>

          <!-- User selector if Compare mode is selected -->
          <div v-if="testMode === 'compare'" style="padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
            <label class="field-label" style="margin-bottom: 6px; color: #475569;">Pilih User Target</label>
            <div v-if="loadingUsers" style="font-size: 13px; color: #64748b;">Memuat user...</div>
            <select v-else v-model="selectedUserId" style="width: 100%; padding: 8px; border-radius: 6px; border: 1px solid #cbd5e1;">
              <option v-for="user in registeredUsers" :key="user.id" :value="user.id">
                {{ user.name || 'User' }} ({{ user.email }}) {{ user.has_face ? '[Face OK]' : '[No Face]' }}
              </option>
            </select>
          </div>

          <!-- Image Source Selector (Camera or File) -->
          <div>
            <label class="field-label" style="margin-bottom: 6px; color: #475569;">Image Input Source</label>
            <div style="display: flex; gap: 12px; margin-bottom: 12px;">
              <button 
                type="button" 
                @click="stopCamera(); uploadFile = null; uploadPreviewUrl = null;"
                :style="{
                  flex: 1, padding: '8px', border: !isCameraActive ? '2px solid #0f172a' : '1px solid #cbd5e1',
                  background: !isCameraActive ? '#f8fafc' : 'white', cursor: 'pointer', borderRadius: '6px', fontWeight: '600'
                }"
              >
                📁 Upload Photo File
              </button>
              <button 
                type="button" 
                @click="startCamera"
                :style="{
                  flex: 1, padding: '8px', border: isCameraActive ? '2px solid #0f172a' : '1px solid #cbd5e1',
                  background: isCameraActive ? '#f8fafc' : 'white', cursor: 'pointer', borderRadius: '6px', fontWeight: '600'
                }"
              >
                📷 Use Live Camera
              </button>
            </div>

            <!-- Webcam Viewer -->
            <div v-if="isCameraActive" style="position: relative; aspect-ratio: 4/3; background: #0f172a; border-radius: 8px; overflow: hidden; max-width: 400px; margin: 0 auto;">
              <video ref="videoEl" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1);" autoplay playsinline muted></video>
              <canvas ref="canvasEl" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;"></canvas>
              <div v-if="mediaPipeLoading" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.5); color: white; font-size: 13px;">Warming mesh model...</div>
            </div>

            <!-- File Upload Viewer -->
            <div v-else style="border: 2px dashed #cbd5e1; padding: 20px; border-radius: 8px; text-align: center; background: #f8fafc;">
              <input type="file" accept="image/*" @change="handleFileChange" style="display: none;" id="tester-file-input" />
              <label for="tester-file-input" style="cursor: pointer; display: block;">
                <div v-if="uploadPreviewUrl" style="max-width: 250px; margin: 0 auto 10px;">
                  <img :src="uploadPreviewUrl" style="width: 100%; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);" />
                </div>
                <div v-else style="padding: 10px 0;">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" style="margin: 0 auto 8px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                  <span style="font-size: 13.5px; color: #475569; font-weight: 500;">Pilih atau drop file foto wajah di sini</span>
                </div>
              </label>
            </div>
          </div>

          <!-- Run test button -->
          <button 
            class="send-btn" 
            @click="runTest" 
            :disabled="isTesting || (isCameraActive && !hasMediaPipeFace)" 
            style="width: 100%; font-weight: 700; height: 44px; display: flex; align-items: center; justify-content: center; gap: 8px; background: #2563eb; color: white;"
          >
            <svg v-if="isTesting" class="spinner-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
            {{ isTesting ? 'Running Biometric Tests...' : 'Lakukan Pengujian (Run Test)' }}
          </button>
        </div>
      </section>

      <!-- Results Display Panel -->
      <section class="tester-panel card" style="display: flex; flex-direction: column;">
        <div class="tester-header" style="margin-bottom: 20px;">
          <div>
            <p class="eyebrow">Analysis</p>
            <h3>2. Test Results</h3>
          </div>
        </div>

        <!-- No result placeholder -->
        <div v-if="!testResult && !isTesting" style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #94a3b8; text-align: center; padding: 40px 0;">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 12px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
          <p style="margin: 0; font-size: 14px; font-weight: 500;">Belum ada hasil pengujian.</p>
          <p style="margin: 4px 0 0; font-size: 12.5px; max-width: 200px;">Masukkan gambar dan jalankan tes untuk melihat analisis kecocokan wajah.</p>
        </div>

        <!-- Loading state -->
        <div v-else-if="isTesting" style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #64748b; padding: 40px 0;">
          <div class="dot-typing" style="margin-bottom: 24px;"></div>
          <p style="font-size: 14px; font-weight: 500;">Memproses gambar di server...</p>
        </div>

        <!-- Real Results container -->
        <div v-else style="flex: 1; display: flex; flex-direction: column; gap: 16px;">
          <!-- Error Results -->
          <div v-if="testResult.status === 'error'" style="background: #fef2f2; border: 1px solid #fca5a5; padding: 14px; border-radius: 8px; color: #b91c1c;">
            <strong style="display:block; font-size:14px; margin-bottom:4px;">❌ Error</strong>
            <span style="font-size:13px; line-height:1.4;">{{ testResult.message }}</span>
          </div>

          <!-- Successful Results -->
          <template v-else>
            
            <!-- A. Match status banner -->
            <div 
              v-if="testMode !== 'liveness'"
              :style="{
                background: testResult.match ? '#f0fdf4' : '#fef2f2',
                border: testResult.match ? '1px solid #bbf7d0' : '1px solid #fca5a5',
                padding: '16px', borderRadius: '8px',
                color: testResult.match ? '#15803d' : '#b91c1c'
              }"
            >
              <div style="font-size: 20px; font-weight: 800; display: flex; align-items: center; gap: 8px;">
                <span>{{ testResult.match ? '✅ MATCH SUCCESS' : '❌ NO MATCH' }}</span>
              </div>
              <p style="margin: 6px 0 0; font-size: 13px; line-height: 1.4; color: inherit; opacity: 0.9;">
                {{ testResult.match ? 'Wajah berhasil dikenali dengan identitas terdaftar!' : 'Wajah tidak cocok dengan data terdaftar di database.' }}
              </p>
            </div>

            <!-- B. Metric Rows -->
            <div style="display: flex; flex-direction: column; gap: 10px; border: 1px solid #e2e8f0; padding: 14px; border-radius: 8px; background: #f8fafc;">
              
              <!-- 1. Similarity Score -->
              <div v-if="testResult.similarity !== undefined || (testResult.data && testResult.data.similarity !== undefined)" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Similarity Score (Kecocokan)</span>
                <strong style="font-size: 15px; color: #0f172a;">
                  {{ Math.round((testResult.similarity || testResult.data.similarity) * 100) }}%
                  <span style="font-size: 12px; font-weight: 500; color: #64748b;">({{ (testResult.similarity || testResult.data.similarity).toFixed(4) }})</span>
                </strong>
              </div>

              <!-- 2. Target Match Info -->
              <div v-if="testResult.match && (testResult.data || testResult.name || testResult.user_id)" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Identitas Terdeteksi</span>
                <strong style="font-size: 14px; color: #1e40af;">
                  {{ testResult.name || (testResult.data && testResult.data.name) || testResult.user_id || 'Face Login Profile' }}
                </strong>
              </div>

              <!-- 3. Liveness Check Results -->
              <div v-if="testResult.is_real !== undefined || (testResult.data && testResult.data.is_real !== undefined)" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Liveness Status</span>
                <span 
                  :style="{
                    fontSize: '12px', fontWeight: '700', padding: '2px 8px', borderRadius: '4px',
                    background: (testResult.is_real || (testResult.data && testResult.data.is_real)) ? '#dcfce7' : '#fee2e2',
                    color: (testResult.is_real || (testResult.data && testResult.data.is_real)) ? '#15803d' : '#b91c1c'
                  }"
                >
                  {{ (testResult.is_real || (testResult.data && testResult.data.is_real)) ? 'REAL (Asli)' : 'SPOOF (Palsu/Layar)' }}
                </span>
              </div>

              <!-- 4. Liveness Score -->
              <div v-if="testResult.score !== undefined || (testResult.data && testResult.data.liveness_score !== undefined)" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Liveness Score</span>
                <strong style="font-size: 14px; color: #0f172a;">
                  {{ Math.round((testResult.score || testResult.data.liveness_score) * 100) }}%
                </strong>
              </div>

              <!-- 5. Latency -->
              <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Latency Server</span>
                <strong style="font-size: 13.5px; color: #64748b;">
                  {{ testResult.latency_ms || '—' }} ms
                </strong>
              </div>

              <!-- 6. Engine Used -->
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 13px; font-weight: 600; color: #475569;">Face Engine Mode</span>
                <strong style="font-size: 13.5px; color: #64748b;">
                  {{ testResult.engine_mode === 'v2' ? 'V2 CPU Turbo (Buffalo_S)' : 'V1 Standard (Buffalo_L)' }}
                </strong>
              </div>

            </div>

            <!-- C. Collapsible Raw JSON Response -->
            <div style="margin-top: auto;">
              <details style="border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; background: white;">
                <summary style="padding: 10px; font-size: 12.5px; font-weight: 600; color: #475569; background: #f1f5f9; cursor: pointer; user-select: none;">
                  🔍 Lihat Response JSON Server
                </summary>
                <div style="padding: 12px; font-size: 11px; overflow-x: auto; max-height: 250px; background: #0f172a; color: #38bdf8; font-family: monospace;">
                  <pre style="margin: 0; line-height: 1.4;">{{ rawJsonResponse }}</pre>
                </div>
              </details>
            </div>

          </template>
        </div>
      </section>

    </div>
  </section>
</template>

<style scoped>
.tester-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
}
.tester-page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}
.tester-page-header h2 {
  font-size: 32px;
  letter-spacing: -0.02em;
  margin: 8px 0;
  color: #0f172a;
}
.eyebrow {
  color: #6366f1;
  font-weight: 600;
  font-size: 14px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}
.card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.tab-btn {
  padding: 6px 14px;
  font-size: 13.5px;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  background: transparent;
  color: #475569;
  transition: all 0.2s;
}
.tab-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.tester-panel {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.tester-panel-full {
  width: 100%;
}
.field-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94a3b8;
  margin-bottom: 4px;
}
.send-btn {
  background: #0f172a;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.send-btn:hover {
  background: #1e293b;
}
.send-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.spinner-icon {
  animation: spin 1s linear infinite;
}

.dot-typing {
  position: relative;
  left: -9999px;
  width: 10px;
  height: 10px;
  border-radius: 5px;
  background-color: #2563eb;
  color: #2563eb;
  box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  animation: dot-typing 1.5s infinite linear;
}

@keyframes dot-typing {
  0% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
  16.667% {
    box-shadow: 9984px -10px 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
  33.333% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
  50% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px -10px 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
  66.667% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
  83.333% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px -10px 0 0 #2563eb;
  }
  100% {
    box-shadow: 9984px 0 0 0 #2563eb, 9999px 0 0 0 #2563eb, 10014px 0 0 0 #2563eb;
  }
}
</style>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { cameraService } from '../../services/cameraService'

const cameras = ref([])
const isLoading = ref(false)
const gridLayout = ref('2x2') // '1x1' | '2x2' | '3x3'

// Modal & Form State
const showAddModal = ref(false)
const showEditModal = ref(false)
const editingCameraId = ref(null)

const formName = ref('')
const formLocation = ref('Gudang Utama')
const formBrand = ref('generic')
const formIp = ref('192.168.1.100')
const formPort = ref('554')
const formUsername = ref('admin')
const formPassword = ref('')
const formChannel = ref('101')
const formCustomUrl = ref('')
const formAiModule = ref('hse')
const formEnableAi = ref(true)

const showPassword = ref(false)
const isCopiedPass = ref(false)
const isCopiedUrl = ref(false)

const togglePasswordVisibility = () => {
  showPassword.value = !showPassword.value
}

const copyPassword = () => {
  if (!formPassword.value) return
  navigator.clipboard.writeText(formPassword.value)
  isCopiedPass.value = true
  setTimeout(() => { isCopiedPass.value = false }, 2000)
}

const copyStreamUrl = () => {
  if (!generatedStreamUrl.value) return
  navigator.clipboard.writeText(generatedStreamUrl.value)
  isCopiedUrl.value = true
  setTimeout(() => { isCopiedUrl.value = false }, 2000)
}

const isTesting = ref(false)
const testResult = ref(null)

const parseRtspUrl = (url) => {
  if (!url || typeof url !== 'string' || !url.toLowerCase().startsWith('rtsp://')) {
    return null
  }
  try {
    const cleanUrl = url.trim()
    const match = cleanUrl.match(/^rtsp:\/\/(?:([^:]+):([^@]+)@)?([^:\/]+)(?::(\d+))?(\/.*)?$/i)
    if (!match) return null

    const user = match[1] ? decodeURIComponent(match[1]) : 'admin'
    const rawPass = match[2] || ''
    const pass = rawPass.includes('%') ? decodeURIComponent(rawPass) : rawPass
    const ip = match[3] || '192.168.1.100'
    const port = match[4] || '554'
    const path = match[5] || ''

    let channel = '101'
    const channelMatch = path.match(/\/Streaming\/Channels\/(\d+)/i)
    if (channelMatch) {
      channel = channelMatch[1]
    }

    return { user, pass, ip, port, channel }
  } catch (e) {
    return null
  }
}

const generatedStreamUrl = computed(() => {
  if (formBrand.value === 'webcam') {
    return '0'
  }
  if (formBrand.value === 'custom') {
    return formCustomUrl.value
  }
  
  // Safe URL encoding for special characters in username & password (e.g., '#' becomes '%23')
  const safeUser = formUsername.value ? encodeURIComponent(formUsername.value) : ''
  const safePass = formPassword.value ? encodeURIComponent(formPassword.value) : ''
  const userPass = safeUser && safePass ? `${safeUser}:${safePass}@` : ''

  if (formBrand.value === 'hikvision') {
    const ch = formChannel.value ? formChannel.value.trim() : '101'
    return `rtsp://${userPass}${formIp.value}:${formPort.value}/Streaming/Channels/${ch}`
  } else if (formBrand.value === 'dahua') {
    return `rtsp://${userPass}${formIp.value}:${formPort.value}/cam/realmonitor?channel=1&subtype=0`
  } else if (formBrand.value === 'uniview') {
    return `rtsp://${userPass}${formIp.value}:${formPort.value}/unicast/c1/s0/live`
  }
  return `rtsp://${userPass}${formIp.value}:${formPort.value}/live`
})

const loadCameras = async () => {
  isLoading.value = true
  const list = await cameraService.getCameras()
  isLoading.value = false
  cameras.value = list
}

const handleTestConnection = async () => {
  isTesting.value = true
  testResult.value = null
  const res = await cameraService.testConnection(generatedStreamUrl.value)
  isTesting.value = false
  testResult.value = res
}

const handleSaveCamera = async () => {
  if (!formName.value) {
    alert('Silakan masukkan nama kamera.')
    return
  }

  const payload = {
    name: formName.value,
    stream_url: generatedStreamUrl.value,
    location: formLocation.value,
    camera_type: formBrand.value === 'webcam' ? 'webcam' : 'rtsp',
    preset_brand: formBrand.value,
    enable_ai_overlay: formEnableAi.value,
    ai_module: formAiModule.value
  }

  let saved = null
  if (showEditModal.value && editingCameraId.value) {
    saved = await cameraService.updateCamera(editingCameraId.value, payload)
  } else {
    saved = await cameraService.addCamera(payload)
  }

  if (saved) {
    closeModal()
    loadCameras()
  } else {
    alert('Gagal menyimpan kamera. Pastikan data valid.')
  }
}

const openAddModal = () => {
  showEditModal.value = false
  editingCameraId.value = null
  formName.value = `CCTV ${cameras.value.length + 1}`
  formLocation.value = 'Gudang Utama'
  formBrand.value = 'hikvision'
  formIp.value = '192.168.1.100'
  formPort.value = '554'
  formUsername.value = 'admin'
  formPassword.value = ''
  formChannel.value = '101'
  formCustomUrl.value = ''
  formAiModule.value = 'hse'
  formEnableAi.value = true
  testResult.value = null
  showAddModal.value = true
}

const editCamera = (cam) => {
  showAddModal.value = false
  showEditModal.value = true
  editingCameraId.value = cam.id
  formName.value = cam.name
  formLocation.value = cam.location
  formBrand.value = cam.preset_brand || 'hikvision'
  formAiModule.value = cam.ai_module || 'hse'
  formEnableAi.value = cam.enable_ai_overlay
  testResult.value = null

  if (cam.stream_url) {
    const parsed = parseRtspUrl(cam.stream_url)
    if (parsed && formBrand.value !== 'custom') {
      formUsername.value = parsed.user
      formPassword.value = parsed.pass
      formIp.value = parsed.ip
      formPort.value = parsed.port
      formChannel.value = parsed.channel
      formCustomUrl.value = ''
    } else {
      formCustomUrl.value = cam.stream_url
    }
  } else {
    formCustomUrl.value = ''
  }
}

const deleteCamera = async (id) => {
  if (confirm('Apakah Anda yakin ingin menghapus kamera ini?')) {
    const ok = await cameraService.deleteCamera(id)
    if (ok) loadCameras()
  }
}

const closeModal = () => {
  showAddModal.value = false
  showEditModal.value = false
  testResult.value = null
}

const feedUrl = (id) => cameraService.getFeedUrl(id)

onMounted(() => {
  loadCameras()
})
</script>

<template>
  <div class="view-container">
    <!-- Module Header & Controls -->
    <div class="module-header">
      <div>
        <h1 class="page-title">📹 Live CCTV Multi-Grid Monitoring</h1>
        <p class="page-subtitle">Hubungkan kamera IP/RTSP industri dan pantau analitik AI secara real-time.</p>
      </div>

      <div class="header-actions">
        <!-- Grid Layout Selector -->
        <div class="grid-switcher">
          <button :class="['grid-btn', { active: gridLayout === '1x1' }]" @click="gridLayout = '1x1'">1x1</button>
          <button :class="['grid-btn', { active: gridLayout === '2x2' }]" @click="gridLayout = '2x2'">2x2 Grid</button>
          <button :class="['grid-btn', { active: gridLayout === '3x3' }]" @click="gridLayout = '3x3'">3x3 Grid</button>
        </div>

        <button class="btn-primary" @click="openAddModal">
          ➕ Hubungkan CCTV Baru
        </button>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!isLoading && cameras.length === 0" class="empty-card">
      <span class="empty-icon">📹</span>
      <h3>Belum Ada Kamera CCTV Terhubung</h3>
      <p>Hubungkan kamera IP, Hikvision, Dahua, Uniview, atau webcam lokal untuk mulai pemantauan AI real-time.</p>
      <button class="btn-primary mt-16" @click="openAddModal">Hubungkan Kamera Pertama</button>
    </div>

    <!-- Live Stream Grid Display -->
    <div v-else :class="['cctv-grid', `layout-${gridLayout}`]">
      <div v-for="cam in cameras" :key="cam.id" class="cctv-card">
        <!-- CCTV Top Info Bar -->
        <div class="cctv-header">
          <div class="cctv-title">
            <span class="status-dot online"></span>
            <strong>{{ cam.name }}</strong>
            <span class="location-tag">{{ cam.location }}</span>
          </div>

          <div class="cctv-badges">
            <span class="badge-ai" v-if="cam.enable_ai_overlay">AI: {{ cam.ai_module.toUpperCase() }}</span>
            <button class="btn-icon" @click="editCamera(cam)">⚙️</button>
            <button class="btn-icon danger" @click="deleteCamera(cam.id)">🗑️</button>
          </div>
        </div>

        <!-- Video Stream Player -->
        <div class="video-container">
          <img :src="feedUrl(cam.id)" :alt="cam.name" class="mjpeg-stream" />
        </div>
      </div>
    </div>

    <!-- Connect Camera Modal -->
    <div v-if="showAddModal || showEditModal" class="modal-backdrop" @click="closeModal">
      <div class="modal-content" @click.stop>
        <h2>{{ showEditModal ? '⚙️ Update Setting CCTV' : '🎥 Hubungkan Kamera CCTV Baru' }}</h2>

        <div class="form-grid">
          <div class="form-group">
            <label>Nama Kamera</label>
            <input type="text" v-model="formName" class="input-field" placeholder="e.g. CCTV Gudang Utama 01" />
          </div>

          <div class="form-group">
            <label>Lokasi / Area</label>
            <input type="text" v-model="formLocation" class="input-field" placeholder="e.g. Gudang Rak A, Area Mesin" />
          </div>

          <div class="form-group">
            <label>Preset Merk Kamera IP</label>
            <select v-model="formBrand" class="input-field">
              <option value="hikvision">Hikvision IP Camera (RTSP)</option>
              <option value="dahua">Dahua Technology (RTSP)</option>
              <option value="uniview">Uniview / UNV (RTSP)</option>
              <option value="generic">Universal RTSP Stream</option>
              <option value="webcam">Webcam Lokal (Laptop / USB Cam)</option>
              <option value="custom">URL RTSP / HTTP Custom</option>
            </select>
          </div>

          <div v-if="formBrand !== 'custom' && formBrand !== 'webcam'" class="form-row">
            <div class="form-group flex-3">
              <label>IP Address Kamera</label>
              <input type="text" v-model="formIp" class="input-field" placeholder="192.168.1.100" />
            </div>
            <div class="form-group flex-1">
              <label>Port</label>
              <input type="text" v-model="formPort" class="input-field" placeholder="554" />
            </div>
          </div>

          <div v-if="formBrand === 'hikvision'" class="form-group">
            <label>Channel Stream Hikvision</label>
            <div class="channel-input-wrapper">
              <select v-model="formChannel" class="input-field channel-select">
                <option value="101">Ch 1 - Main Stream (101 HD)</option>
                <option value="102">Ch 1 - Sub Stream (102 Smooth AI)</option>
                <option value="201">Ch 2 - Main Stream (201 HD)</option>
                <option value="202">Ch 2 - Sub Stream (202 Smooth AI)</option>
                <option value="301">Ch 3 - Main Stream (301)</option>
                <option value="302">Ch 3 - Sub Stream (302)</option>
                <option value="401">Ch 4 - Main Stream (401)</option>
                <option value="402">Ch 4 - Sub Stream (402)</option>
                <option value="501">Ch 5 - Main Stream (501)</option>
                <option value="502">Ch 5 - Sub Stream (502)</option>
                <option value="601">Ch 6 - Main Stream (601)</option>
                <option value="602">Ch 6 - Sub Stream (602)</option>
                <option value="701">Ch 7 - Main Stream (701)</option>
                <option value="702">Ch 7 - Sub Stream (702)</option>
                <option value="801">Ch 8 - Main Stream (801)</option>
                <option value="802">Ch 8 - Sub Stream (802)</option>
                <option value="901">Ch 9 - Main Stream (901)</option>
                <option value="902">Ch 9 - Sub Stream (902)</option>
                <option value="1001">Ch 10 - Main Stream (1001)</option>
                <option value="1002">Ch 10 - Sub Stream (1002)</option>
                <option value="1601">Ch 16 - Main Stream (1601)</option>
                <option value="1602">Ch 16 - Sub Stream (1602)</option>
              </select>
              <input 
                type="text" 
                v-model="formChannel" 
                class="input-field channel-custom-input" 
                placeholder="e.g. 101" 
                title="Ketik Kode Channel Hikvision (contoh: 101, 102, 201)"
              />
            </div>
          </div>

          <div v-if="formBrand !== 'custom' && formBrand !== 'webcam'" class="form-row">
            <div class="form-group flex-1">
              <label>Username CCTV</label>
              <input type="text" v-model="formUsername" class="input-field" placeholder="admin" />
            </div>
            <div class="form-group flex-1">
              <label>Password CCTV</label>
              <div class="password-input-wrapper">
                <input 
                  :type="showPassword ? 'text' : 'password'" 
                  v-model="formPassword" 
                  class="input-field password-input" 
                  placeholder="••••••••" 
                />
                <div class="password-action-btns">
                  <button 
                    type="button" 
                    class="btn-icon-field" 
                    @click="togglePasswordVisibility" 
                    :title="showPassword ? 'Sembunyikan Password' : 'Lihat Password'"
                  >
                    {{ showPassword ? '🙈' : '👁️' }}
                  </button>
                  <button 
                    type="button" 
                    class="btn-icon-field" 
                    @click="copyPassword" 
                    :title="isCopiedPass ? 'Password Disalin!' : 'Salin Password'"
                  >
                    {{ isCopiedPass ? '✅' : '📋' }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="formBrand === 'custom'" class="form-group">
            <label>Full Stream URL (RTSP / HTTP / HLS)</label>
            <input type="text" v-model="formCustomUrl" class="input-field" placeholder="rtsp://admin:pass@192.168.1.100:554/live" />
          </div>

          <!-- Generated RTSP URL Preview -->
          <div class="form-group">
            <div class="url-label-row">
              <label>Generated Stream Target URL</label>
              <button type="button" class="btn-copy-url" @click="copyStreamUrl">
                {{ isCopiedUrl ? '✅ URL Disalin!' : '📋 Copy URL' }}
              </button>
            </div>
            <input type="text" :value="generatedStreamUrl" readonly class="input-field readonly" />
          </div>

          <!-- AI Overlay Settings -->
          <div class="form-row">
            <div class="form-group">
              <label>Aktifkan AI Overlay Stream</label>
              <select v-model="formEnableAi" class="input-field">
                <option :value="true">YA (Tampilkan Deteksi AI)</option>
                <option :value="false">TIDAK (Video Raw Biasa)</option>
              </select>
            </div>

            <div class="form-group">
              <label>Modul Analitik AI</label>
              <select v-model="formAiModule" class="input-field">
                <option value="hse_danger_zone">🛟 HSE: Danger Zone Intrusion Alert</option>
                <option value="hse_ppe">🦺 HSE: PPE Safety Compliance Check</option>
                <option value="hse_near_miss">🚨 HSE: Comprehensive Near-Miss Log</option>
                <option value="inventory_count">🔢 Inventory: Count Boxes & Pallets</option>
                <option value="inventory_defect">⚠️ Inventory: Packaging Defect Check</option>
                <option value="inventory_shelf">📊 Inventory: Shelf Occupancy Grid</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Connection Test Results -->
        <div v-if="testResult" :class="['test-alert', testResult.online ? 'success' : 'danger']">
          {{ testResult.message }}
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" :disabled="isTesting" @click="handleTestConnection">
            <span v-if="isTesting">⏳ Memeriksa Connection...</span>
            <span v-else>🔍 Test Connection Stream</span>
          </button>
          
          <button class="btn-primary" @click="handleSaveCamera">
            💾 Simpan Kamera
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view-container { padding: 0; width: 100%; max-width: 100%; margin: 0; }
.module-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }
.page-title { font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
.page-subtitle { color: #475569; font-size: 14px; }

.header-actions { display: flex; gap: 16px; align-items: center; }
.grid-switcher { display: flex; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px; gap: 4px; }
.grid-btn { background: transparent; color: #475569; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 700; }
.grid-btn.active { background: #2563eb; color: #ffffff; }

.btn-primary { background: #2563eb; color: #ffffff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; box-shadow: 0 4px 12px rgba(37,99,235,0.25); }
.btn-secondary { background: #475569; color: #ffffff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; }

.empty-card { background: #ffffff; border: 2px dashed #cbd5e1; border-radius: 14px; padding: 60px; text-align: center; color: #475569; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05); }
.empty-card h3 { color: #0f172a; font-weight: 700; }
.empty-icon { font-size: 54px; display: block; margin-bottom: 12px; }
.mt-16 { margin-top: 16px; }

/* Grid Layouts */
.cctv-grid { display: grid; gap: 20px; }
.layout-1x1 { grid-template-columns: 1fr; }
.layout-2x2 { grid-template-columns: repeat(2, 1fr); }
.layout-3x3 { grid-template-columns: repeat(3, 1fr); }

.cctv-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.cctv-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #0f172a; }
.cctv-title { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.status-dot.online { background: #10b981; box-shadow: 0 0 8px #10b981; }
.location-tag { font-size: 11px; color: #475569; background: #e2e8f0; padding: 2px 8px; border-radius: 4px; font-weight: 600; }

.cctv-badges { display: flex; align-items: center; gap: 8px; }
.badge-ai { background: #ecfdf5; color: #059669; font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 4px; border: 1px solid #a7f3d0; }
.btn-icon { background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; cursor: pointer; font-size: 13px; padding: 4px 8px; }
.btn-icon.danger { background: #fee2e2; border-color: #fca5a5; color: #dc2626; }

.video-container { position: relative; width: 100%; background: #000; min-height: 260px; display: flex; align-items: center; justify-content: center; }
.mjpeg-stream { width: 100%; height: auto; display: block; object-fit: contain; }

/* Modal Styling */
.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-content { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 28px; width: 650px; max-width: 90vw; max-height: 90vh; overflow-y: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
.modal-content h2 { font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 20px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }
.form-grid { display: flex; flex-direction: column; gap: 14px; }
.form-group { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #0f172a; font-weight: 700; }
.form-row { display: flex; gap: 12px; }
.flex-1 { flex: 1; }
.flex-2 { flex: 2; }
.flex-3 { flex: 3; }
.input-field { background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; padding: 10px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; }
.input-field.readonly { background: #f1f5f9; color: #2563eb; font-family: monospace; font-weight: 600; width: 100%; }

.channel-input-wrapper { display: flex; gap: 6px; width: 100%; }
.channel-select { flex: 2; }
.channel-custom-input { flex: 1; min-width: 75px; text-align: center; font-family: monospace; font-weight: 700; color: #2563eb; }

.password-input-wrapper { position: relative; display: flex; align-items: center; width: 100%; }
.password-input { width: 100%; padding-right: 68px; }
.password-action-btns { position: absolute; right: 6px; display: flex; gap: 2px; align-items: center; }
.btn-icon-field { background: transparent; border: none; cursor: pointer; font-size: 14px; padding: 4px 6px; border-radius: 4px; transition: background 0.2s; }
.btn-icon-field:hover { background: #f1f5f9; }

.url-label-row { display: flex; justify-content: space-between; align-items: center; }
.btn-copy-url { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s; }
.btn-copy-url:hover { background: #dbeafe; }

.test-alert { padding: 12px; border-radius: 8px; font-size: 13px; margin-top: 16px; font-weight: 600; }
.test-alert.success { background: #dcfce7; color: #15803d; border: 1px solid #86efac; }
.test-alert.danger { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }

.modal-actions { display: flex; justify-content: space-between; margin-top: 24px; }
</style>

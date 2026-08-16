<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { hseService } from '../../services/hseService'

const router = useRouter()

const canvasRef = ref(null)
const bgImage = ref(null)
const bgImageSrc = ref('')

const zones = ref([])

// Current polygon being drawn
const currentPoints = ref([])
const currentZoneName = ref('Zona Bahaya Baru')
const currentZoneType = ref('danger')
const currentColor = ref('#FF0000')

const isSaving = ref(false)
const toastMsg = ref('')

const handleBgUpload = (event) => {
  const file = event.target.files[0]
  if (file) {
    const url = URL.createObjectURL(file)
    bgImageSrc.value = url
    const img = new Image()
    img.onload = () => {
      bgImage.value = img
      redrawCanvas()
    }
    img.src = url
  }
}

const handleCanvasClick = (event) => {
  const canvas = canvasRef.value
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height

  const x = Math.round((event.clientX - rect.left) * scaleX)
  const y = Math.round((event.clientY - rect.top) * scaleY)

  currentPoints.value.push([x, y])
  redrawCanvas()
}

const closePolygon = () => {
  if (currentPoints.value.length < 3) {
    alert('Poligon membutuhkan minimal 3 titik koordinat.')
    return
  }

  zones.value.push({
    id: 'temp-' + Date.now(),
    zone_name: currentZoneName.value,
    zone_type: currentZoneType.value,
    color_hex: currentColor.value,
    polygon_points: [...currentPoints.value]
  })

  // Reset current drawing state
  currentPoints.value = []
  currentZoneName.value = `Zona ${zones.value.length + 1}`
  redrawCanvas()
}

const removeZone = (index) => {
  zones.value.splice(index, 1)
  redrawCanvas()
}

const redrawCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')

  // Set standard internal resolution
  canvas.width = bgImage.value ? bgImage.value.width : 800
  canvas.height = bgImage.value ? bgImage.value.height : 500

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  // Draw background image if loaded
  if (bgImage.value) {
    ctx.drawImage(bgImage.value, 0, 0)
  } else {
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = '#94a3b8'
    ctx.font = '16px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('Upload foto referensi CCTV untuk mulai menggambar zona', canvas.width / 2, canvas.height / 2)
  }

  // Draw existing saved zones
  zones.value.forEach((z) => {
    const pts = z.polygon_points
    if (pts.length < 3) return

    ctx.beginPath()
    ctx.moveTo(pts[0][0], pts[0][1])
    for (let i = 1; i < pts.length; i++) {
      ctx.lineTo(pts[i][0], pts[i][1])
    }
    ctx.closePath()

    ctx.fillStyle = z.color_hex + '40' // 25% opacity fill
    ctx.fill()
    ctx.strokeStyle = z.color_hex
    ctx.lineWidth = 3
    ctx.stroke()

    // Draw label
    ctx.fillStyle = '#ffffff'
    ctx.font = 'bold 14px sans-serif'
    ctx.fillText(z.zone_name, pts[0][0], pts[0][1] - 8)
  })

  // Draw currently active points being drawn
  if (currentPoints.value.length > 0) {
    ctx.beginPath()
    ctx.moveTo(currentPoints.value[0][0], currentPoints.value[0][1])
    for (let i = 1; i < currentPoints.value.length; i++) {
      ctx.lineTo(currentPoints.value[i][0], currentPoints.value[i][1])
    }

    ctx.strokeStyle = currentColor.value
    ctx.lineWidth = 2
    ctx.setLineDash([6, 6])
    ctx.stroke()
    ctx.setLineDash([])

    // Draw vertex dots
    currentPoints.value.forEach(([px, py]) => {
      ctx.beginPath()
      ctx.arc(px, py, 5, 0, 2 * Math.PI)
      ctx.fillStyle = currentColor.value
      ctx.fill()
    })
  }
}

const loadZones = async () => {
  const loaded = await hseService.getZones()
  if (loaded && loaded.length > 0) {
    zones.value = loaded
  }
  nextTick(() => redrawCanvas())
}

const saveAllZones = async () => {
  isSaving.value = true
  toastMsg.value = ''
  const ok = await hseService.batchSyncZones(zones.value)
  isSaving.value = false
  if (ok) {
    toastMsg.value = '✅ Semua Polygon Zone K3 berhasil disimpan ke Database & Sync API!'
    setTimeout(() => toastMsg.value = '', 4000)
  }
}

onMounted(() => {
  loadZones()
})
</script>

<template>
  <div class="view-container">
    <div class="module-header">
      <div>
        <h1 class="page-title">📐 Interactive Polygon Zone Editor</h1>
        <p class="page-subtitle">Gambar dan kelola zona bahaya secara visual langsung pada gambar CCTV.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn" @click="router.push('/hse/playground')">🧪 Testing Playground</button>
        <button class="nav-btn active" @click="router.push('/hse/zone-editor')">📐 Polygon Zone Editor</button>
        <button class="nav-btn" @click="router.push('/hse/rules')">📋 APD Rules</button>
        <button class="nav-btn" @click="router.push('/hse/incidents')">🚨 Incident Logs</button>
      </div>
    </div>

    <div class="editor-grid">
      <!-- Canvas Area -->
      <div class="canvas-panel">
        <div class="canvas-toolbar">
          <label class="btn-upload">
            📷 Upload Referensi CCTV
            <input type="file" accept="image/*" @change="handleBgUpload" style="display:none" />
          </label>

          <button v-if="currentPoints.length >= 3" class="btn-success" @click="closePolygon">
            ✅ Tutup & Simpan Poligon Ini
          </button>
          
          <button v-if="currentPoints.length > 0" class="btn-danger" @click="currentPoints = []; redrawCanvas()">
            ❌ Batal Gambar
          </button>
        </div>

        <div class="canvas-wrapper">
          <canvas ref="canvasRef" @click="handleCanvasClick" @contextmenu.prevent="closePolygon" class="drawing-canvas"></canvas>
        </div>
        <p class="canvas-hint">💡 Klik kiri pada gambar untuk menambah titik sudut. Klik kanan atau tombol 'Tutup Poligon' jika selesai 1 zona.</p>
      </div>

      <!-- Controls & List Sidebar -->
      <div class="sidebar-panel">
        <h2>Aturan Zona Baru</h2>

        <div class="form-group">
          <label>Nama Zona</label>
          <input type="text" v-model="currentZoneName" class="input-field" />
        </div>

        <div class="form-group">
          <label>Tipe Zona</label>
          <select v-model="currentZoneType" class="input-field">
            <option value="danger">Danger Zone (Merah)</option>
            <option value="warning">Warning Zone (Kuning)</option>
            <option value="safe">Safe Zone (Hijau)</option>
          </select>
        </div>

        <div class="form-group">
          <label>Warna Overlay</label>
          <input type="color" v-model="currentColor" class="color-picker" />
        </div>

        <hr class="divider" />

        <h2>Daftar Zona Aktif ({{ zones.length }})</h2>

        <div class="zones-list">
          <div v-for="(z, idx) in zones" :key="idx" class="zone-item">
            <div class="zone-info">
              <span class="color-dot" :style="{ backgroundColor: z.color_hex }"></span>
              <div>
                <strong>{{ z.zone_name }}</strong>
                <span class="zone-type-tag">{{ z.zone_type }}</span>
              </div>
            </div>
            <button class="btn-icon danger" @click="removeZone(idx)">🗑️</button>
          </div>
        </div>

        <button class="btn-primary full-width mt-20" :disabled="isSaving" @click="saveAllZones">
          <span v-if="isSaving">⏳ Menyimpan...</span>
          <span v-else>💾 Simpan & Sync ke DB</span>
        </button>

        <p v-if="toastMsg" class="success-banner mt-12">{{ toastMsg }}</p>
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
.nav-btn.active, .nav-btn:hover { background: #059669; color: white; border-color: #059669; }

.editor-grid { display: grid; grid-template-columns: 1fr 360px; gap: 24px; }
.canvas-panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.canvas-toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
.btn-upload { background: #475569; color: white; padding: 10px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-success { background: #059669; color: white; border: none; padding: 10px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-danger { background: #dc2626; color: white; border: none; padding: 10px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }

.canvas-wrapper { overflow: auto; background: #0f172a; border-radius: 10px; border: 1px solid #cbd5e1; text-align: center; }
.drawing-canvas { cursor: crosshair; max-width: 100%; height: auto; }
.canvas-hint { font-size: 12px; color: #64748b; margin-top: 10px; }

.sidebar-panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 24px; display: flex; flex-direction: column; gap: 16px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.sidebar-panel h2 { font-size: 16px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; }
.form-group { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #0f172a; font-weight: 600; }
.input-field { background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; padding: 10px 12px; border-radius: 6px; font-weight: 500; }
.color-picker { border: 1px solid #cbd5e1; width: 100%; height: 40px; cursor: pointer; border-radius: 6px; background: transparent; padding: 2px; }
.divider { border: 0; border-top: 1px solid #e2e8f0; }

.zones-list { display: flex; flex-direction: column; gap: 8px; max-height: 250px; overflow-y: auto; }
.zone-item { display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px 12px; border-radius: 8px; }
.zone-info { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #0f172a; }
.color-dot { width: 14px; height: 14px; border-radius: 50%; display: inline-block; border: 1px solid rgba(0,0,0,0.1); }
.zone-type-tag { font-size: 10px; color: #64748b; display: block; text-transform: uppercase; font-weight: 600; }
.btn-icon.danger { background: #fee2e2; border: 1px solid #fca5a5; color: #dc2626; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
.btn-primary { background: #059669; color: white; border: none; padding: 14px; border-radius: 8px; font-weight: 700; cursor: pointer; }
.full-width { width: 100%; }
.mt-20 { margin-top: 20px; }
.mt-12 { margin-top: 12px; }
.success-banner { background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 10px; border-radius: 6px; font-size: 12px; text-align: center; font-weight: 600; }
</style>

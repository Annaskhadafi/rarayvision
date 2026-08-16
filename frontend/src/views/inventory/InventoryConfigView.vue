<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { inventoryService } from '../../services/inventoryService'

const router = useRouter()

const modelName = ref('yolov8n')
const confidence = ref(0.4)
const iouThreshold = ref(0.45)
const targetClassesText = ref('box, pallet, container, suitcase')

const isSaving = ref(false)
const toastMsg = ref('')
const errorMsg = ref('')

const loadConfig = async () => {
  const cfg = await inventoryService.getConfig()
  if (cfg) {
    modelName.value = cfg.model_name || 'yolov8n'
    confidence.value = cfg.confidence || 0.4
    iouThreshold.value = cfg.iou_threshold || 0.45
    if (Array.isArray(cfg.target_classes)) {
      targetClassesText.value = cfg.target_classes.join(', ')
    }
  }
}

const saveConfig = async () => {
  isSaving.value = true
  toastMsg.value = ''
  errorMsg.value = ''

  const classesArray = targetClassesText.value
    .split(',')
    .map(c => c.trim())
    .filter(c => c.length > 0)

  const payload = {
    model_name: modelName.value,
    confidence: confidence.value,
    iou_threshold: iouThreshold.value,
    target_classes: classesArray
  }

  const updated = await inventoryService.updateConfig(payload)
  isSaving.value = false

  if (updated) {
    toastMsg.value = '✅ Konfigurasi Inventory berhasil disimpan & sinkron dengan REST API!'
    setTimeout(() => toastMsg.value = '', 4000)
  } else {
    errorMsg.value = 'Gagal menyimpan konfigurasi.'
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="view-container">
    <div class="module-header">
      <div>
        <h1 class="page-title">⚙️ Inventory API Configuration</h1>
        <p class="page-subtitle">Atur model AI, sensitivitas, dan kelas objek yang tersinkron langsung ke REST API.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn" @click="router.push('/inventory/playground')">🧪 Testing Playground</button>
        <button class="nav-btn active" @click="router.push('/inventory/config')">⚙️ Configuration</button>
        <button class="nav-btn" @click="router.push('/inventory/history')">📜 History Logs</button>
      </div>
    </div>

    <div class="config-card">
      <h2>Model & Inference Settings</h2>
      
      <div class="form-group">
        <label>Model Detector Utama</label>
        <select v-model="modelName" class="input-field">
          <option value="yolov8n">YOLOv8 Nano (Fastest, Lightest)</option>
          <option value="yolov8s">YOLOv8 Small (Balanced)</option>
          <option value="yolov8m">YOLOv8 Medium (High Accuracy)</option>
          <option value="yolov8x">YOLOv8 Extra Large (Maximum Precision)</option>
        </select>
        <span class="help-text">Pilih arsitektur YOLOv8 yang berjalan di server.</span>
      </div>

      <div class="form-group">
        <label>Default Confidence Threshold: <strong>{{ confidence }}</strong></label>
        <input type="range" v-model.number="confidence" min="0.1" max="0.9" step="0.05" class="slider" />
        <span class="help-text">Minimal skor keyakinan agar objek dihitung. Nilai lebih rendah mendeteksi objek lebih banyak.</span>
      </div>

      <div class="form-group">
        <label>NMS IoU Threshold: <strong>{{ iouThreshold }}</strong></label>
        <input type="range" v-model.number="iouThreshold" min="0.1" max="0.9" step="0.05" class="slider" />
        <span class="help-text">Threshold tumpang-tindih (Intersection over Union) untuk Non-Maximum Suppression.</span>
      </div>

      <div class="form-group">
        <label>Target Class Filter (Dipisahkan koma)</label>
        <input type="text" v-model="targetClassesText" class="input-field" placeholder="box, pallet, container" />
        <span class="help-text">Kosongkan jika ingin menghitung semua objek yang terdeteksi.</span>
      </div>

      <div class="action-row">
        <button class="btn-primary" :disabled="isSaving" @click="saveConfig">
          <span v-if="isSaving">⏳ Menyimpan & Sync...</span>
          <span v-else>💾 Simpan & Sinkronkan ke API</span>
        </button>
      </div>

      <p v-if="toastMsg" class="success-banner">{{ toastMsg }}</p>
      <p v-if="errorMsg" class="error-banner">{{ errorMsg }}</p>
    </div>
  </div>
</template>

<style scoped>
.view-container { padding: 24px; max-width: 900px; margin: 0 auto; }
.module-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }
.page-title { font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
.page-subtitle { color: #475569; font-size: 14px; }
.sub-nav { display: flex; gap: 8px; }
.nav-btn { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; padding: 9px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.nav-btn.active, .nav-btn:hover { background: #2563eb; color: #ffffff; border-color: #2563eb; }
.config-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 28px; display: flex; flex-direction: column; gap: 20px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.config-card h2 { font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }
.form-group { display: flex; flex-direction: column; gap: 8px; }
.form-group label { font-size: 14px; font-weight: 700; color: #0f172a; }
.help-text { font-size: 12px; color: #64748b; }
.input-field { background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; padding: 10px 14px; border-radius: 8px; font-size: 14px; font-weight: 500; }
.slider { width: 100%; accent-color: #2563eb; }
.btn-primary { background: #2563eb; color: #ffffff; border: none; padding: 14px 24px; border-radius: 8px; font-weight: 700; cursor: pointer; }
.success-banner { background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.error-banner { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
</style>

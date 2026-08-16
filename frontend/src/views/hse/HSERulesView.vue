<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { hseService } from '../../services/hseService'

const router = useRouter()

const ruleName = ref('Standard Warehouse Safety PPE')
const requireHelmet = ref(true)
const requireVest = ref(true)
const requireMask = ref(false)
const requireGloves = ref(false)
const requireBoots = ref(false)

const isSaving = ref(false)
const toastMsg = ref('')

const loadRules = async () => {
  const data = await hseService.getPpeRules()
  if (data) {
    ruleName.value = data.rule_name || 'Standard Warehouse Safety PPE'
    requireHelmet.value = data.require_helmet
    requireVest.value = data.require_vest
    requireMask.value = data.require_mask
    requireGloves.value = data.require_gloves
    requireBoots.value = data.require_boots
  }
}

const saveRules = async () => {
  isSaving.value = true
  toastMsg.value = ''
  
  const payload = {
    rule_name: ruleName.value,
    require_helmet: requireHelmet.value,
    require_vest: requireVest.value,
    require_mask: requireMask.value,
    require_gloves: requireGloves.value,
    require_boots: requireBoots.value
  }

  const updated = await hseService.updatePpeRules(payload)
  isSaving.value = false

  if (updated) {
    toastMsg.value = '✅ Aturan Wajib APD K3 berhasil diperbarui & tersinkronkan ke API!'
    setTimeout(() => toastMsg.value = '', 4000)
  }
}

onMounted(() => {
  loadRules()
})
</script>

<template>
  <div class="view-container">
    <div class="module-header">
      <div>
        <h1 class="page-title">📋 APD Safety Rules Configuration</h1>
        <p class="page-subtitle">Tentukan kelengkapan APD (Alat Pelindung Diri) yang wajib dipakai di area kerja.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn" @click="router.push('/hse/playground')">🧪 Testing Playground</button>
        <button class="nav-btn" @click="router.push('/hse/zone-editor')">📐 Polygon Zone Editor</button>
        <button class="nav-btn active" @click="router.push('/hse/rules')">📋 APD Rules</button>
        <button class="nav-btn" @click="router.push('/hse/incidents')">🚨 Incident Logs</button>
      </div>
    </div>

    <div class="config-card">
      <h2>Aturan APD K3 Aktif</h2>

      <div class="form-group">
        <label>Nama Aturan APD</label>
        <input type="text" v-model="ruleName" class="input-field" />
      </div>

      <div class="rules-list">
        <label class="checkbox-label">
          <input type="checkbox" v-model="requireHelmet" />
          <span>🪖 Helm Keselamatan (Safety Helmet) — <strong>WAJIB</strong></span>
        </label>

        <label class="checkbox-label">
          <input type="checkbox" v-model="requireVest" />
          <span>🦺 Rompi High-Visibility (Safety Vest) — <strong>WAJIB</strong></span>
        </label>

        <label class="checkbox-label">
          <input type="checkbox" v-model="requireMask" />
          <span>😷 Masker Pernapasan (Face Mask)</span>
        </label>

        <label class="checkbox-label">
          <input type="checkbox" v-model="requireGloves" />
          <span>🧤 Sarung Tangan Kerja (Safety Gloves)</span>
        </label>

        <label class="checkbox-label">
          <input type="checkbox" v-model="requireBoots" />
          <span>🥾 Sepatu Safety (Safety Boots)</span>
        </label>
      </div>

      <button class="btn-primary" :disabled="isSaving" @click="saveRules">
        <span v-if="isSaving">⏳ Menyimpan Aturan...</span>
        <span v-else">💾 Simpan Aturan APD & Sync API</span>
      </button>

      <p v-if="toastMsg" class="success-banner">{{ toastMsg }}</p>
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
.nav-btn.active, .nav-btn:hover { background: #059669; color: white; border-color: #059669; }

.config-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 28px; display: flex; flex-direction: column; gap: 20px; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.config-card h2 { font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; }
.form-group { display: flex; flex-direction: column; gap: 6px; font-weight: 700; color: #0f172a; }
.input-field { background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; padding: 10px 14px; border-radius: 8px; font-weight: 500; }

.rules-list { display: flex; flex-direction: column; gap: 14px; background: #f8fafc; border: 1px solid #e2e8f0; padding: 20px; border-radius: 10px; }
.checkbox-label { display: flex; align-items: center; gap: 12px; font-size: 14px; cursor: pointer; color: #0f172a; font-weight: 500; }
.checkbox-label input[type="checkbox"] { width: 18px; height: 18px; accent-color: #059669; }

.btn-primary { background: #059669; color: white; border: none; padding: 14px 24px; border-radius: 8px; font-weight: 700; cursor: pointer; }
.success-banner { background: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
</style>

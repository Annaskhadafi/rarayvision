<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { hseService } from '../../services/hseService'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

const incidents = ref([])
const totalItems = ref(0)
const currentPage = ref(1)
const filterSeverity = ref('')
const isLoading = ref(false)

const selectedIncident = ref(null)

const loadIncidents = async () => {
  isLoading.value = true
  const res = await hseService.getIncidents(currentPage.value, filterSeverity.value)
  isLoading.value = false
  if (res && res.success) {
    incidents.value = res.items
    totalItems.value = res.total
  }
}

const deleteItem = async (id) => {
  if (confirm('Apakah Anda yakin ingin menghapus record insiden K3 ini?')) {
    const ok = await hseService.deleteIncident(id)
    if (ok) {
      loadIncidents()
    }
  }
}

const exportCSV = () => {
  const token = localStorage.getItem('rarayvision-token')
  window.open(`${API_BASE_URL}/api/v1/hse/export?token=${token}`, '_blank')
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('id-ID')
}

onMounted(() => {
  loadIncidents()
})
</script>

<template>
  <div class="view-container">
    <div class="module-header">
      <div>
        <h1 class="page-title">🚨 HSE Incident & Near-Miss Logs</h1>
        <p class="page-subtitle">Pencatatan otomatis kejadian pelanggaran APD, intrusi zona bahaya, dan bukti foto snapshot.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn" @click="router.push('/hse/playground')">🧪 Testing Playground</button>
        <button class="nav-btn" @click="router.push('/hse/zone-editor')">📐 Polygon Zone Editor</button>
        <button class="nav-btn" @click="router.push('/hse/rules')">📋 APD Rules</button>
        <button class="nav-btn active" @click="router.push('/hse/incidents')">🚨 Incident Logs</button>
      </div>
    </div>

    <div class="toolbar">
      <div class="filter-group">
        <label>Filter Severity:</label>
        <select v-model="filterSeverity" @change="currentPage = 1; loadIncidents()" class="select-field">
          <option value="">Semua Tingkat Risiko</option>
          <option value="CRITICAL">CRITICAL</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>
      </div>

      <button class="btn-secondary" @click="exportCSV">📥 Export CSV Log</button>
    </div>

    <div class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Waktu Kejadian</th>
            <th>Tipe Insiden</th>
            <th>Tingkat Risiko</th>
            <th>Personil</th>
            <th>Pelanggaran</th>
            <th>Bukti Snapshot</th>
            <th>Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td colspan="7" class="loading-cell">Memuat log kejadian K3...</td>
          </tr>
          <tr v-else-if="incidents.length === 0">
            <td colspan="7" class="empty-cell">Belum ada insiden terdeteksi. Sistem berjalan aman!</td>
          </tr>
          <tr v-for="item in incidents" :key="item.id">
            <td>{{ formatDate(item.created_at) }}</td>
            <td><span class="badge-type">{{ item.incident_type }}</span></td>
            <td>
              <span :class="['severity-tag', item.severity.toLowerCase()]">{{ item.severity }}</span>
            </td>
            <td>{{ item.persons_count }} orang</td>
            <td><strong>{{ item.violations_count }}</strong></td>
            <td>
              <img v-if="item.annotated_image" :src="item.annotated_image" alt="Snapshot" class="thumb-img" @click="selectedIncident = item" />
              <span v-else>-</span>
            </td>
            <td>
              <button class="btn-icon danger" @click="deleteItem(item.id)">🗑️ Hapus</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Modal Snapshot -->
    <div v-if="selectedIncident" class="modal-backdrop" @click="selectedIncident = null">
      <div class="modal-content" @click.stop>
        <h3>Bukti Snapshot Insiden K3</h3>
        <img :src="selectedIncident.annotated_image" alt="Snapshot Detail" class="modal-img" />
        <button class="btn-secondary mt-12" @click="selectedIncident = null">Tutup</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view-container { padding: 24px; max-width: 1200px; margin: 0 auto; }
.module-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; }
.page-title { font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
.page-subtitle { color: #475569; font-size: 14px; }
.sub-nav { display: flex; gap: 8px; }
.nav-btn { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; padding: 9px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.nav-btn.active, .nav-btn:hover { background: #059669; color: white; border-color: #059669; }

.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.filter-group { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #0f172a; font-weight: 600; }
.select-field { background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; padding: 8px 12px; border-radius: 6px; font-weight: 500; }
.btn-secondary { background: #475569; color: white; border: none; padding: 9px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; }

.table-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.data-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
.data-table th, .data-table td { padding: 14px 18px; border-bottom: 1px solid #e2e8f0; color: #0f172a; }
.data-table th { background: #f8fafc; color: #475569; font-weight: 700; border-bottom: 2px solid #e2e8f0; }
.badge-type { background: #ecfdf5; color: #059669; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid #a7f3d0; }

.severity-tag { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 800; display: inline-block; }
.severity-tag.critical { background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; }
.severity-tag.high { background: #fef3c7; color: #d97706; border: 1px solid #fde68a; }
.severity-tag.medium { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.severity-tag.low { background: #f1f5f9; color: #475569; }

.thumb-img { width: 54px; height: 54px; object-fit: cover; border-radius: 6px; cursor: pointer; border: 1px solid #cbd5e1; }
.btn-icon.danger { background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 6px 10px; border-radius: 6px; cursor: pointer; font-weight: 600; }
.loading-cell, .empty-cell { text-align: center; color: #64748b; padding: 40px; font-weight: 500; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-content { background: #ffffff; padding: 24px; border-radius: 14px; max-width: 90vw; max-height: 90vh; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
.modal-content h3 { color: #0f172a; font-weight: 700; }
.modal-img { max-width: 100%; max-height: 70vh; border-radius: 8px; margin-top: 12px; border: 1px solid #cbd5e1; }
.mt-12 { margin-top: 12px; }
</style>

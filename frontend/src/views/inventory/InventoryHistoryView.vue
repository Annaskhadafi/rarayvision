<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { inventoryService } from '../../services/inventoryService'
import { API_BASE_URL } from '../../utils'

const router = useRouter()

const historyItems = ref([])
const totalItems = ref(0)
const currentPage = ref(1)
const filterType = ref('')
const isLoading = ref(false)

const selectedScan = ref(null)

const loadHistory = async () => {
  isLoading.value = true
  const res = await inventoryService.getHistory(currentPage.value, filterType.value)
  isLoading.value = false
  if (res && res.success) {
    historyItems.value = res.items
    totalItems.value = res.total
  }
}

const deleteItem = async (id) => {
  if (confirm('Apakah Anda yakin ingin menghapus record scan ini?')) {
    const success = await inventoryService.deleteHistory(id)
    if (success) {
      loadHistory()
    }
  }
}

const exportCSV = () => {
  const token = localStorage.getItem('rarayvision-token')
  window.open(`${API_BASE_URL}/api/v1/inventory/export?token=${token}`, '_blank')
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('id-ID')
}

onMounted(() => {
  loadHistory()
})
</script>

<template>
  <div class="view-container">
    <div class="module-header">
      <div>
        <h1 class="page-title">📜 Inventory Audit History Logs</h1>
        <p class="page-subtitle">Riwayat lengkap semua pengujian dan panggillan REST API Inventory.</p>
      </div>
      <div class="sub-nav">
        <button class="nav-btn" @click="router.push('/inventory/playground')">🧪 Testing Playground</button>
        <button class="nav-btn" @click="router.push('/inventory/config')">⚙️ Configuration</button>
        <button class="nav-btn active" @click="router.push('/inventory/history')">📜 History Logs</button>
      </div>
    </div>

    <div class="toolbar">
      <div class="filter-group">
        <label>Filter Tipe Scan:</label>
        <select v-model="filterType" @change="currentPage = 1; loadHistory()" class="select-field">
          <option value="">Semua Scan</option>
          <option value="count_boxes">Count Boxes</option>
          <option value="defect_check">Defect Check</option>
          <option value="shelf_occupancy">Shelf Occupancy</option>
        </select>
      </div>

      <button class="btn-secondary" @click="exportCSV">📥 Export CSV</button>
    </div>

    <div class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>Waktu</th>
            <th>Tipe Scan</th>
            <th>Total Objek / Status</th>
            <th>Model</th>
            <th>Waktu AI</th>
            <th>Preview</th>
            <th>Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td colspan="7" class="loading-cell">Memuat riwayat...</td>
          </tr>
          <tr v-else-if="historyItems.length === 0">
            <td colspan="7" class="empty-cell">Belum ada riwayat scan.</td>
          </tr>
          <tr v-for="item in historyItems" :key="item.id">
            <td>{{ formatDate(item.created_at) }}</td>
            <td><span class="badge-type">{{ item.scan_type }}</span></td>
            <td><strong>{{ item.total_count }}</strong></td>
            <td><code>{{ item.model_used }}</code></td>
            <td>{{ item.processing_ms }} ms</td>
            <td>
              <img v-if="item.annotated_image" :src="item.annotated_image" alt="Preview" class="thumb-img" @click="selectedScan = item" />
              <span v-else>-</span>
            </td>
            <td>
              <button class="btn-icon danger" @click="deleteItem(item.id)">🗑️ Hapus</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Image Detail Modal -->
    <div v-if="selectedScan" class="modal-backdrop" @click="selectedScan = null">
      <div class="modal-content" @click.stop>
        <h3>Hasil Annotasi Detail</h3>
        <img :src="selectedScan.annotated_image" alt="Detail Image" class="modal-img" />
        <button class="btn-secondary mt-12" @click="selectedScan = null">Tutup</button>
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
.nav-btn.active, .nav-btn:hover { background: #2563eb; color: #ffffff; border-color: #2563eb; }

.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.filter-group { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #0f172a; font-weight: 600; }
.select-field { background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; padding: 8px 12px; border-radius: 6px; font-weight: 500; }
.btn-secondary { background: #475569; color: white; border: none; padding: 9px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; }

.table-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06); }
.data-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
.data-table th, .data-table td { padding: 14px 18px; border-bottom: 1px solid #e2e8f0; color: #0f172a; }
.data-table th { background: #f8fafc; color: #475569; font-weight: 700; border-bottom: 2px solid #e2e8f0; }
.badge-type { background: #eff6ff; color: #2563eb; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid #bfdbfe; }
.thumb-img { width: 54px; height: 54px; object-fit: cover; border-radius: 6px; cursor: pointer; border: 1px solid #cbd5e1; }
.btn-icon.danger { background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; padding: 6px 10px; border-radius: 6px; cursor: pointer; font-weight: 600; }
.loading-cell, .empty-cell { text-align: center; color: #64748b; padding: 40px; font-weight: 500; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-content { background: #ffffff; padding: 24px; border-radius: 14px; max-width: 90vw; max-height: 90vh; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
.modal-content h3 { color: #0f172a; font-weight: 700; }
.modal-img { max-width: 100%; max-height: 70vh; border-radius: 8px; margin-top: 12px; border: 1px solid #cbd5e1; }
.mt-12 { margin-top: 12px; }
</style>

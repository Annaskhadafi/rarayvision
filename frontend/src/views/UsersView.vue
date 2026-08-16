<script setup>
import { ref, computed, onMounted } from 'vue'
import { authService } from '../services/authService'
import { store } from '../store'
import { formatDate } from '../utils'

const users = ref([])
const isLoading = ref(true)
const searchQuery = ref('')
const toastMessage = ref('')
const toastType = ref('success') // 'success' | 'error'

const showToast = (msg, type = 'success') => {
  toastMessage.value = msg
  toastType.value = type
  setTimeout(() => { toastMessage.value = '' }, 3500)
}

// Modal States
const showAddModal = ref(false)
const showEditModal = ref(false)
const showDeleteModal = ref(false)

// Form States
const formAdd = ref({ name: '', email: '', password: '' })
const formEdit = ref({ id: null, name: '', email: '' })
const userToDelete = ref(null)

const isSubmitting = ref(false)
const formError = ref('')

const fetchUsersList = async () => {
  isLoading.value = true
  const res = await authService.fetchUsers()
  if (res.success) {
    users.value = res.users
  } else {
    showToast(res.error || 'Gagal memuat daftar pengguna', 'error')
  }
  isLoading.value = false
}

onMounted(() => {
  fetchUsersList()
})

const filteredUsers = computed(() => {
  if (!searchQuery.value.trim()) return users.value
  const query = searchQuery.value.toLowerCase()
  return users.value.filter(u => 
    (u.name && u.name.toLowerCase().includes(query)) ||
    (u.email && u.email.toLowerCase().includes(query))
  )
})

const faceCountTotal = computed(() => users.value.filter(u => u.has_face).length)
const apiKeyCountTotal = computed(() => users.value.reduce((acc, u) => acc + (u.api_key_count || 0), 0))

// Add User Handlers
const openAddModal = () => {
  formAdd.value = { name: '', email: '', password: '' }
  formError.value = ''
  showAddModal.value = true
}

const handleAddUser = async () => {
  if (!formAdd.value.email || !formAdd.value.password) {
    formError.value = 'Email dan password wajib diisi'
    return
  }
  formError.value = ''
  isSubmitting.value = true
  const res = await authService.createUser(formAdd.value.name, formAdd.value.email, formAdd.value.password)
  if (res.success) {
    showAddModal.value = false
    showToast('Pengguna baru berhasil ditambahkan!')
    fetchUsersList()
  } else {
    formError.value = res.error || 'Gagal menambahkan pengguna'
  }
  isSubmitting.value = false
}

// Edit User Handlers
const openEditModal = (u) => {
  formEdit.value = { id: u.id, name: u.name, email: u.email }
  formError.value = ''
  showEditModal.value = true
}

const handleEditUser = async () => {
  if (!formEdit.value.name.trim()) {
    formError.value = 'Nama tidak boleh kosong'
    return
  }
  formError.value = ''
  isSubmitting.value = true
  const res = await authService.updateUser(formEdit.value.id, formEdit.value.name, formEdit.value.email)
  if (res.success) {
    showEditModal.value = false
    showToast('Data pengguna berhasil diperbarui!')
    // Update local current user if current logged in user modified themself
    if (store.user && store.user.id === formEdit.value.id) {
      store.user.name = formEdit.value.name
      store.user.email = formEdit.value.email
    }
    fetchUsersList()
  } else {
    formError.value = res.error || 'Gagal memperbarui pengguna'
  }
  isSubmitting.value = false
}

// Delete User Handlers
const openDeleteModal = (u) => {
  userToDelete.value = u
  showDeleteModal.value = true
}

const handleDeleteUser = async () => {
  if (!userToDelete.value) return
  isSubmitting.value = true
  const res = await authService.deleteUser(userToDelete.value.id)
  if (res.success) {
    showDeleteModal.value = false
    showToast(`Pengguna ${userToDelete.value.email} telah dihapus`)
    userToDelete.value = null
    fetchUsersList()
  } else {
    showToast(res.error || 'Gagal menghapus pengguna', 'error')
    showDeleteModal.value = false
  }
  isSubmitting.value = false
}
</script>

<template>
  <section class="users-layout">
    <!-- Toast Notification -->
    <div v-if="toastMessage" class="toast-notification" :class="toastType">
      <svg v-if="toastType === 'success'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
      <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ toastMessage }}
    </div>

    <!-- Header Section -->
    <div class="page-header">
      <div>
        <span class="eyebrow">Manajemen Sistem</span>
        <h2>Daftar Pengguna (User CRUD)</h2>
        <p class="subtitle">Kelola daftar akun pengguna terdaftar, perbarui nama & email, serta hapus akun.</p>
      </div>
      <button class="primary-btn" @click="openAddModal" style="display: flex; align-items: center; gap: 8px;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
        Tambah Pengguna
      </button>
    </div>

    <!-- Summary Stats Bar -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon-wrapper blue">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
        </div>
        <div>
          <span class="stat-label">Total Pengguna</span>
          <span class="stat-value">{{ users.length }}</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon-wrapper green">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"></path><circle cx="12" cy="13" r="3"></circle></svg>
        </div>
        <div>
          <span class="stat-label">Pengguna Face Login</span>
          <span class="stat-value">{{ faceCountTotal }}</span>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon-wrapper purple">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
        </div>
        <div>
          <span class="stat-label">Total API Keys</span>
          <span class="stat-value">{{ apiKeyCountTotal }}</span>
        </div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="table-container-card">
      <div class="table-toolbar">
        <div class="search-box">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <input type="text" v-model="searchQuery" placeholder="Cari berdasarkan nama atau email..." />
        </div>
        <span class="results-count" v-if="filteredUsers.length !== users.length">
          Menampilkan {{ filteredUsers.length }} dari {{ users.length }} pengguna
        </span>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" style="padding: 48px; text-align: center; color: #64748b;">
        <svg class="spinner-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-bottom: 12px; color: #3b82f6;"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
        <p>Memuat data pengguna...</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="!filteredUsers.length" style="padding: 48px; text-align: center; color: #64748b;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5" style="margin-bottom: 12px;"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><line x1="18" y1="8" x2="23" y2="13"></line><line x1="23" y1="8" x2="18" y2="13"></line></svg>
        <p style="font-weight: 500; margin-bottom: 4px;">Tidak ada pengguna ditemukan</p>
        <p style="font-size: 0.85rem; color: #94a3b8;">Coba ubah kata kunci pencarian Anda.</p>
      </div>

      <!-- Users Table -->
      <div v-else class="table-responsive">
        <table class="custom-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Pengguna</th>
              <th>Status Face Login</th>
              <th>API Keys</th>
              <th>Tanggal Daftar</th>
              <th style="text-align: right;">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in filteredUsers" :key="u.id">
              <td style="font-weight: 600; color: #64748b;">#{{ u.id }}</td>
              <td>
                <div class="user-info-cell">
                  <div class="avatar-circle">
                    {{ (u.name || u.email).charAt(0).toUpperCase() }}
                  </div>
                  <div>
                    <div class="user-name">
                      {{ u.name || '-' }}
                      <span v-if="store.user && store.user.id === u.id" class="you-badge">Anda</span>
                    </div>
                    <div class="user-email">{{ u.email }}</div>
                  </div>
                </div>
              </td>
              <td>
                <span v-if="u.has_face" class="badge badge-success">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"></path><circle cx="12" cy="13" r="3"></circle></svg>
                  Face Active ({{ u.face_count }})
                </span>
                <span v-else class="badge badge-neutral">Belum Set</span>
              </td>
              <td>
                <span class="badge badge-info">{{ u.api_key_count }} Keys</span>
              </td>
              <td style="font-size: 0.85rem; color: #64748b;">
                {{ u.created_at ? formatDate(u.created_at) : '-' }}
              </td>
              <td style="text-align: right;">
                <div class="action-buttons">
                  <button class="btn-icon edit" @click="openEditModal(u)" title="Edit Nama / Email">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                    Edit
                  </button>
                  <button class="btn-icon delete" @click="openDeleteModal(u)" title="Hapus Pengguna">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    Hapus
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal Add User -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>Tambah Pengguna Baru</h3>
          <button class="close-btn" @click="showAddModal = false">&times;</button>
        </div>
        <form @submit.prevent="handleAddUser" class="modal-body">
          <label class="form-label">
            Nama Lengkap
            <input type="text" v-model="formAdd.name" placeholder="John Doe" class="form-input" />
          </label>
          <label class="form-label">
            Email <span style="color: #ef4444;">*</span>
            <input type="email" v-model="formAdd.email" required placeholder="user@domain.com" class="form-input" />
          </label>
          <label class="form-label">
            Password <span style="color: #ef4444;">*</span>
            <input type="password" v-model="formAdd.password" required placeholder="••••••••" class="form-input" />
          </label>
          <p v-if="formError" class="form-error">{{ formError }}</p>

          <div class="modal-footer">
            <button type="button" class="cancel-btn" @click="showAddModal = false">Batal</button>
            <button type="submit" class="primary-btn" :disabled="isSubmitting">
              <svg v-if="isSubmitting" class="spinner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
              {{ isSubmitting ? 'Menyimpan...' : 'Tambah Pengguna' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal Edit User -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>Edit Pengguna</h3>
          <button class="close-btn" @click="showEditModal = false">&times;</button>
        </div>
        <form @submit.prevent="handleEditUser" class="modal-body">
          <label class="form-label">
            Nama Lengkap <span style="color: #ef4444;">*</span>
            <input type="text" v-model="formEdit.name" required placeholder="John Doe" class="form-input" />
          </label>
          <label class="form-label">
            Email Address
            <input type="email" v-model="formEdit.email" required placeholder="user@domain.com" class="form-input" />
          </label>
          <p v-if="formError" class="form-error">{{ formError }}</p>

          <div class="modal-footer">
            <button type="button" class="cancel-btn" @click="showEditModal = false">Batal</button>
            <button type="submit" class="primary-btn" :disabled="isSubmitting">
              <svg v-if="isSubmitting" class="spinner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
              {{ isSubmitting ? 'Menyimpan...' : 'Simpan Perubahan' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal Delete User Confirmation -->
    <div v-if="showDeleteModal" class="modal-overlay" @click.self="showDeleteModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3 style="color: #dc2626; display: flex; align-items: center; gap: 8px;">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
            Konfirmasi Hapus Pengguna
          </h3>
          <button class="close-btn" @click="showDeleteModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <p style="color: #334155; margin-bottom: 12px;">
            Apakah Anda yakin ingin menghapus pengguna <strong>{{ userToDelete?.name || userToDelete?.email }}</strong> (<code>{{ userToDelete?.email }}</code>)?
          </p>
          <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 12px; font-size: 0.85rem; color: #991b1b;">
            ⚠️ <strong>Tindakan ini permanen!</strong> Semua data terkait pengguna ini termasuk API Keys dan pendaftaran Face Login akan turut terhapus secara menyeluruh dari database.
          </div>
        </div>
        <div class="modal-footer">
          <button class="cancel-btn" @click="showDeleteModal = false">Batal</button>
          <button class="danger-btn" :disabled="isSubmitting" @click="handleDeleteUser">
            <svg v-if="isSubmitting" class="spinner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
            {{ isSubmitting ? 'Menghapus...' : 'Ya, Hapus Pengguna' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.users-layout {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 16px;
}

.page-header h2 {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
  margin: 4px 0 6px 0;
}

.subtitle {
  color: #64748b;
  font-size: 0.95rem;
  margin: 0;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.stat-icon-wrapper {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.stat-icon-wrapper.blue { background: #eff6ff; color: #2563eb; }
.stat-icon-wrapper.green { background: #f0fdf4; color: #16a34a; }
.stat-icon-wrapper.purple { background: #faf5ff; color: #9333ea; }

.stat-label {
  display: block;
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

/* Table Card */
.table-container-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.table-toolbar {
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 360px;
}
.search-box svg {
  position: absolute;
  left: 12px;
  color: #94a3b8;
}
.search-box input {
  width: 100%;
  padding: 8px 12px 8px 38px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.9rem;
  outline: none;
  transition: border 0.2s;
}
.search-box input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.results-count {
  font-size: 0.85rem;
  color: #64748b;
}

.table-responsive {
  overflow-x: auto;
}

.custom-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.custom-table th {
  background: #f8fafc;
  padding: 12px 20px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #e2e8f0;
}

.custom-table td {
  padding: 16px 20px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.custom-table tbody tr:hover {
  background: #f8fafc;
}

.user-info-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar-circle {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.25);
}

.user-name {
  font-weight: 600;
  color: #0f172a;
  font-size: 0.95rem;
  display: flex;
  align-items: center;
  gap: 6px;
}

.you-badge {
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #bfdbfe;
}

.user-email {
  font-size: 0.85rem;
  color: #64748b;
}

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
}
.badge-success { background: #dcfce7; color: #15803d; }
.badge-neutral { background: #f1f5f9; color: #64748b; }
.badge-info { background: #e0f2fe; color: #0369a1; }

/* Actions */
.action-buttons {
  display: inline-flex;
  gap: 8px;
  justify-content: flex-end;
}

.btn-icon {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  border: 1px solid #cbd5e1;
  background: white;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-icon.edit { color: #2563eb; }
.btn-icon.edit:hover { background: #eff6ff; border-color: #93c5fd; }

.btn-icon.delete { color: #dc2626; }
.btn-icon.delete:hover { background: #fef2f2; border-color: #fca5a5; }

/* Buttons */
.primary-btn {
  background: #1e293b;
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.2s;
}
.primary-btn:hover { background: #0f172a; }

.danger-btn {
  background: #dc2626;
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.danger-btn:hover { background: #b91c1c; }

.cancel-btn {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
}
.cancel-btn:hover { background: #e2e8f0; }

/* Modal Styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 16px;
}

.modal-card {
  background: white;
  border-radius: 12px;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-header h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
}
.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
}

.modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.form-input {
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.9rem;
  outline: none;
  transition: border 0.2s;
}
.form-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.form-error {
  color: #dc2626;
  font-size: 0.85rem;
  margin: 0;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

/* Toast */
.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: 8px;
  color: white;
  font-weight: 600;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
  z-index: 200;
}
.toast-notification.success { background: #16a34a; }
.toast-notification.error { background: #dc2626; }
</style>

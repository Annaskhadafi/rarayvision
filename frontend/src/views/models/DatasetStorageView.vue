<script setup>
import { reactive, ref, onMounted } from 'vue'
import { API_BASE_URL, formatDate } from '../../utils'

const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem('rarayvision-token')}` })
const jsonHeaders = () => ({ ...authHeaders(), 'Content-Type': 'application/json' })

const config = reactive({ endpoint_url: '', bucket: '', region: 'us-east-1', prefix: 'datasets', access_key_id: '', secret_access_key: '' })
const configMeta = ref({ configured: false, access_key_id: '', secret_access_key_configured: false })
const datasets = ref([])
const selectedDataset = ref(null)
const fileInput = ref(null)
const isSaving = ref(false)
const isTesting = ref(false)
const isLoading = ref(false)
const isUploading = ref(false)
const notice = ref('')
const errorMessage = ref('')
const copied = ref(false)
const isMarkingImport = ref(false)
const importSnapshotIds = ref([])
const importSnapshotUrl = ref('')
const importSnapshotBatchId = ref('')

const showError = (message) => { errorMessage.value = message; notice.value = '' }
const clearMessage = () => { errorMessage.value = ''; notice.value = '' }

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || data.message || `Server error (${response.status})`)
  return data
}

const loadConfig = async () => {
  const data = await request('/api/v1/datasets/storage/config')
  Object.assign(config, { endpoint_url: data.endpoint_url || '', bucket: data.bucket || '', region: data.region || 'us-east-1', prefix: data.prefix || 'datasets', access_key_id: '', secret_access_key: '' })
  configMeta.value = data
}

const loadDatasets = async () => {
  isLoading.value = true
  try {
    datasets.value = (await request('/api/v1/datasets/raw')).datasets || []
    if (selectedDataset.value) {
      const match = datasets.value.find(item => item.id === selectedDataset.value.id)
      if (match) await openDataset(match)
      else selectedDataset.value = null
    }
  } finally {
    isLoading.value = false
  }
}

const saveConfig = async () => {
  clearMessage()
  isSaving.value = true
  try {
    const payload = { endpoint_url: config.endpoint_url, bucket: config.bucket, region: config.region, prefix: config.prefix }
    if (config.access_key_id) payload.access_key_id = config.access_key_id
    if (config.secret_access_key) payload.secret_access_key = config.secret_access_key
    const data = await request('/api/v1/datasets/storage/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    config.access_key_id = ''
    config.secret_access_key = ''
    configMeta.value = data.config
    notice.value = 'Konfigurasi S3 dataset tersimpan.'
  } catch (error) {
    showError(error.message)
  } finally {
    isSaving.value = false
  }
}

const testConfig = async () => {
  clearMessage()
  isTesting.value = true
  try {
    const payload = { endpoint_url: config.endpoint_url, bucket: config.bucket, region: config.region, prefix: config.prefix }
    if (config.access_key_id) payload.access_key_id = config.access_key_id
    if (config.secret_access_key) payload.secret_access_key = config.secret_access_key
    notice.value = (await request('/api/v1/datasets/storage/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })).message
  } catch (error) {
    showError(error.message)
  } finally {
    isTesting.value = false
  }
}

const createDataset = async () => {
  const name = window.prompt('Nama dataset raw:')?.trim()
  if (!name) return
  clearMessage()
  try {
    const dataset = await request('/api/v1/datasets/raw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
    await loadDatasets()
    await openDataset(dataset)
  } catch (error) {
    showError(error.message)
  }
}

const openDataset = async (dataset) => {
  const previousId = selectedDataset.value?.id
  try {
    selectedDataset.value = await request(`/api/v1/datasets/raw/${dataset.id}`)
    if (previousId !== dataset.id) {
      importSnapshotIds.value = []
      importSnapshotUrl.value = ''
      importSnapshotBatchId.value = ''
    }
  } catch (error) {
    showError(error.message)
  }
}

const renameDataset = async (dataset) => {
  const name = window.prompt('Nama dataset baru:', dataset.name)?.trim()
  if (!name || name === dataset.name) return
  try {
    await request(`/api/v1/datasets/raw/${dataset.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
    await loadDatasets()
  } catch (error) { showError(error.message) }
}

const deleteDataset = async (dataset) => {
  if (!window.confirm(`Hapus dataset "${dataset.name}" beserta file S3-nya?`)) return
  try {
    await request(`/api/v1/datasets/raw/${dataset.id}`, { method: 'DELETE' })
    if (selectedDataset.value?.id === dataset.id) {
      selectedDataset.value = null
      importSnapshotIds.value = []
      importSnapshotUrl.value = ''
      importSnapshotBatchId.value = ''
    }
    await loadDatasets()
  } catch (error) { showError(error.message) }
}

const chooseFiles = (dataset) => {
  selectedDataset.value = dataset
  fileInput.value?.click()
}

const uploadFiles = async (event) => {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length || !selectedDataset.value) return
  isUploading.value = true
  clearMessage()
  try {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    await request(`/api/v1/datasets/raw/${selectedDataset.value.id}/files`, { method: 'POST', body })
    notice.value = `${files.length} file berhasil diunggah ke S3 dataset.`
    await loadDatasets()
  } catch (error) { showError(error.message) }
  finally { isUploading.value = false }
}

const renameFile = async (file) => {
  const filename = window.prompt('Nama file baru:', file.filename)?.trim()
  if (!filename || filename === file.filename) return
  try {
    await request(`/api/v1/datasets/raw/${selectedDataset.value.id}/files/${file.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename }) })
    await openDataset(selectedDataset.value)
    await loadDatasets()
  } catch (error) { showError(error.message) }
}

const deleteFile = async (file) => {
  if (!window.confirm(`Hapus file "${file.filename}" dari S3?`)) return
  try {
    await request(`/api/v1/datasets/raw/${selectedDataset.value.id}/files/${file.id}`, { method: 'DELETE' })
    await openDataset(selectedDataset.value)
    await loadDatasets()
  } catch (error) { showError(error.message) }
}

const copyImportUrl = async () => {
  try {
    if (!selectedDataset.value?.pending_file_count) return
    const datasetId = selectedDataset.value.id
    let url = importSnapshotUrl.value
    let prepared = { batch_id: importSnapshotBatchId.value, file_ids: importSnapshotIds.value }
    if (!prepared.batch_id) {
      prepared = await request(`/api/v1/datasets/raw/${datasetId}/label-studio/prepare`, { method: 'POST' })
      if (selectedDataset.value?.id !== datasetId) return
      url = prepared.url
    }
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      const input = document.createElement('textarea')
      input.value = url
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    importSnapshotIds.value = prepared.file_ids
    importSnapshotUrl.value = url
    importSnapshotBatchId.value = prepared.batch_id
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1800)
  } catch (error) { showError(error.message) }
}

const markImported = async () => {
  if (!selectedDataset.value) return
  const fileIds = importSnapshotIds.value
  if (!fileIds.length || !importSnapshotBatchId.value) return
  const datasetId = selectedDataset.value.id
  isMarkingImport.value = true
  clearMessage()
  try {
    const data = await request(`/api/v1/datasets/raw/${datasetId}/label-studio/mark-imported`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch_id: importSnapshotBatchId.value })
    })
    if (selectedDataset.value?.id !== datasetId) return
    selectedDataset.value = data.dataset
    importSnapshotIds.value = []
    importSnapshotUrl.value = ''
    importSnapshotBatchId.value = ''
    notice.value = `${fileIds.length} file ditandai sudah di-import ke Label Studio.`
    await loadDatasets()
  } catch (error) { showError(error.message) }
  finally { isMarkingImport.value = false }
}

const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1 }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`
}

onMounted(async () => {
  try { await Promise.all([loadConfig(), loadDatasets()]) } catch (error) { showError(error.message) }
})
</script>

<template>
  <div class="storage-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">DATASET WORKSPACE</p>
        <h1>Raw Dataset Storage</h1>
        <p class="subtitle">Kelola S3-compatible storage khusus dataset raw, lalu kirim manifest siap import ke Label Studio.</p>
      </div>
      <button class="primary-btn" @click="createDataset">＋ Dataset raw baru</button>
    </header>

    <div v-if="errorMessage" class="alert error">{{ errorMessage }}</div>
    <div v-if="notice" class="alert success">{{ notice }}</div>

    <section class="settings-card panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">ISOLATED STORAGE</p>
          <h2>Pengaturan S3-compatible</h2>
          <p>Credential disimpan di backend dan tidak pernah dikirim kembali ke browser.</p>
        </div>
        <span :class="['status-pill', configMeta.configured ? 'ready' : 'pending']">{{ configMeta.configured ? 'Terkonfigurasi' : 'Belum dikonfigurasi' }}</span>
      </div>
      <div class="form-grid">
        <label>Endpoint URL<input v-model="config.endpoint_url" placeholder="https://s3.example.com" /></label>
        <label>Bucket<input v-model="config.bucket" placeholder="raray-datasets" /></label>
        <label>Region<input v-model="config.region" placeholder="us-east-1" /></label>
        <label>Prefix folder<input v-model="config.prefix" placeholder="datasets" /><small>File disimpan di prefix/raw/nama-dataset.</small></label>
        <label>Access key<input v-model="config.access_key_id" placeholder="Masukkan untuk mengganti" autocomplete="off" /><small v-if="configMeta.access_key_id">Tersimpan: {{ configMeta.access_key_id }}</small></label>
        <label>Secret key<input v-model="config.secret_access_key" type="password" placeholder="Masukkan untuk mengganti" autocomplete="new-password" /><small v-if="configMeta.secret_access_key_configured">Secret key tersimpan.</small></label>
      </div>
      <div class="form-actions">
        <button class="secondary-btn" :disabled="isTesting" @click="testConfig">{{ isTesting ? 'Menguji…' : 'Test koneksi' }}</button>
        <button class="primary-btn" :disabled="isSaving" @click="saveConfig">{{ isSaving ? 'Menyimpan…' : 'Simpan pengaturan' }}</button>
      </div>
    </section>

    <section class="workspace-grid">
      <div class="panel dataset-panel">
        <div class="panel-heading compact"><div><h2>Dataset raw</h2><p>{{ datasets.length }} workspace tersimpan</p></div><span class="count-badge">{{ datasets.length }}</span></div>
        <div v-if="isLoading" class="empty">Memuat dataset…</div>
        <div v-else-if="!datasets.length" class="empty">Belum ada dataset. Buat workspace pertama.</div>
        <button v-for="dataset in datasets" :key="dataset.id" :class="['dataset-item', { active: selectedDataset?.id === dataset.id }]" @click="openDataset(dataset)">
          <span class="folder-icon">▰</span><span class="dataset-info"><strong>{{ dataset.name }}</strong><small>{{ dataset.file_count }} file · {{ formatBytes(dataset.total_bytes) }}</small><small>{{ formatDate(dataset.updated_at || dataset.created_at) }}</small></span>
        </button>
      </div>

      <div class="panel explorer-panel">
        <div v-if="selectedDataset" class="explorer-content">
          <div class="explorer-heading"><div><p class="eyebrow">RAW DATASET / {{ selectedDataset.folder }}</p><h2>{{ selectedDataset.name }}</h2><p>{{ selectedDataset.files?.length || 0 }} file · dibuat {{ formatDate(selectedDataset.created_at) }}</p></div><div class="row-actions"><button class="icon-btn" title="Edit nama" @click="renameDataset(selectedDataset)">Edit</button><button class="icon-btn danger-action" title="Hapus dataset" @click="deleteDataset(selectedDataset)">Hapus dataset</button><button class="primary-btn" :disabled="isUploading" @click="chooseFiles(selectedDataset)">{{ isUploading ? 'Mengunggah…' : '＋ Upload file' }}</button><input ref="fileInput" type="file" multiple hidden @change="uploadFiles" /></div></div>
          <div class="import-box"><div><strong>URL incremental import Label Studio</strong><code>{{ importSnapshotUrl || 'Klik “Salin URL” untuk membuat snapshot aman' }}</code><small v-if="selectedDataset.pending_file_count">{{ selectedDataset.pending_file_count }} file pending. Snapshot tidak berubah walau ada upload baru.</small><small v-else>Semua file sudah ditandai pernah di-import.</small></div><div class="import-actions"><button class="secondary-btn" :disabled="!selectedDataset.pending_file_count" @click="copyImportUrl">{{ copied ? '✓ Tersalin' : 'Salin URL' }}</button><button v-if="importSnapshotIds.length" class="primary-btn" :disabled="isMarkingImport" @click="markImported">{{ isMarkingImport ? 'Menyimpan…' : `Tandai ${importSnapshotIds.length} file sudah di-import` }}</button></div></div>
          <div class="file-table-wrap"><table><thead><tr><th>Nama file</th><th>Status import</th><th>Ukuran</th><th>Diunggah</th><th></th></tr></thead><tbody><tr v-for="file in selectedDataset.files" :key="file.id"><td><a :href="file.url" target="_blank" rel="noopener">▧ {{ file.filename }}</a></td><td><span :class="['import-status', file.label_studio_imported_at ? 'done' : 'pending']">{{ file.label_studio_imported_at ? 'Sudah diimport' : 'Belum diimport' }}</span></td><td>{{ formatBytes(file.size_bytes) }}</td><td>{{ formatDate(file.created_at) }}</td><td class="actions"><button @click="renameFile(file)">Edit</button><button class="danger" @click="deleteFile(file)">Hapus</button></td></tr><tr v-if="!selectedDataset.files?.length"><td colspan="5" class="empty">Folder masih kosong. Upload file pertama.</td></tr></tbody></table></div>
        </div>
        <div v-else class="empty large">Pilih dataset di kiri untuk membuka file explorer.</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.storage-page { color: #172033; max-width: 1440px; margin: 0 auto; }
.page-header, .panel-heading, .explorer-heading, .form-actions, .row-actions, .import-box { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.page-header { margin-bottom: 24px; }
.page-header h1 { margin: 3px 0 7px; font-size: 1.8rem; letter-spacing: -.03em; text-wrap: balance; }
.subtitle, .panel-heading p, .explorer-heading p { margin: 0; color: #6b7890; line-height: 1.5; }
.subtitle { max-width: 680px; }
.eyebrow { color: #5872a1 !important; font-size: .68rem !important; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.panel { background: #fff; border: 1px solid #e5eaf2; border-radius: 16px; box-shadow: 0 10px 30px rgba(30, 50, 90, .06); }
.settings-card { padding: 22px; margin-bottom: 22px; }
.panel-heading { align-items: flex-start; margin-bottom: 20px; }
.panel-heading h2, .explorer-heading h2 { margin: 3px 0 5px; font-size: 1.1rem; }
.panel-heading.compact { margin-bottom: 12px; }
.form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
label { color: #41506a; font-size: .78rem; font-weight: 700; }
input { display: block; width: 100%; box-sizing: border-box; margin-top: 7px; padding: 10px 12px; border: 1px solid #d7dfeb; border-radius: 9px; color: #172033; outline: none; }
input:focus { border-color: #6488c4; box-shadow: 0 0 0 3px rgba(100,136,196,.14); }
small { display: block; color: #8390a4; font-size: .72rem; font-weight: 400; margin-top: 5px; }
.form-actions { justify-content: flex-end; margin-top: 20px; }
button { border: 0; cursor: pointer; font: inherit; }
button:disabled { opacity: .6; cursor: wait; }
.primary-btn, .secondary-btn, .icon-btn { min-height: 40px; border-radius: 9px; padding: 0 14px; font-weight: 700; transition: transform .15s ease, background-color .15s ease, box-shadow .15s ease; }
.primary-btn { background: #2463c5; color: #fff; box-shadow: 0 5px 12px rgba(36,99,197,.18); }
.primary-btn:hover, .secondary-btn:hover, .icon-btn:hover { transform: translateY(-1px); }
.secondary-btn, .icon-btn { background: #f2f5fa; color: #40516f; }
.status-pill, .count-badge { border-radius: 999px; font-size: .72rem; font-weight: 800; padding: 6px 10px; white-space: nowrap; }
.status-pill.ready { background: #def7e8; color: #197548; }.status-pill.pending { background: #fff2d5; color: #a86600; }.count-badge { background: #eaf1ff; color: #2463c5; }
.workspace-grid { display: grid; grid-template-columns: minmax(250px, .8fr) minmax(0, 2fr); gap: 22px; }
.dataset-panel { padding: 18px 12px; }.explorer-panel { min-height: 440px; padding: 22px; }.dataset-item { display: flex; gap: 11px; width: 100%; text-align: left; padding: 12px 10px; border-radius: 10px; background: transparent; color: inherit; }.dataset-item:hover, .dataset-item.active { background: #eef5ff; }.folder-icon { color: #e49b28; font-size: 1.15rem; }.dataset-info { min-width: 0; }.dataset-info strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.dataset-info small { margin-top: 3px; }.empty { color: #8793a6; text-align: center; padding: 34px 14px; }.empty.large { display: grid; min-height: 380px; place-items: center; }.import-box { margin: 20px 0; padding: 14px; background: #f5f8fd; border-radius: 10px; }.import-box strong { display: block; font-size: .78rem; }.import-box code { display: block; max-width: 720px; margin-top: 6px; color: #4a628b; font-size: .74rem; word-break: break-all; }.import-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }.import-status { border-radius: 999px; padding: 5px 8px; font-size: .68rem; font-weight: 800; }.import-status.done { color: #197548; background: #def7e8; }.import-status.pending { color: #a86600; background: #fff2d5; }.file-table-wrap { overflow-x: auto; }table { width: 100%; border-collapse: collapse; font-size: .82rem; }th, td { padding: 12px 9px; border-bottom: 1px solid #edf0f5; text-align: left; white-space: nowrap; }th { color: #8290a6; font-size: .69rem; text-transform: uppercase; letter-spacing: .06em; }td a { color: #275fae; text-decoration: none; }.actions { text-align: right; }.actions button { padding: 6px 8px; background: transparent; color: #476892; }.actions .danger { color: #c44949; }.alert { padding: 12px 14px; border-radius: 10px; margin-bottom: 16px; font-size: .84rem; }.alert.error { color: #a63737; background: #fff0f0; border: 1px solid #ffd2d2; }.alert.success { color: #23764d; background: #effbf4; border: 1px solid #cdeedb; }
 .danger-action { color: #c44949; }
@media (max-width: 900px) { .form-grid { grid-template-columns: repeat(2, 1fr); }.workspace-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .page-header, .explorer-heading { align-items: flex-start; flex-direction: column; }.page-header .primary-btn { width: 100%; }.form-grid { grid-template-columns: 1fr; }.settings-card, .explorer-panel { padding: 16px; }.import-box { align-items: flex-start; flex-direction: column; }.import-actions, .import-box .secondary-btn, .import-box .primary-btn { width: 100%; }.import-actions { flex-direction: column; } }
</style>

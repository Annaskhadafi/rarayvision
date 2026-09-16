<script setup>
import { ref } from 'vue'
import { API_BASE_URL } from '../../utils'

const datasetName = ref('')
const cocoJsonFile = ref(null)
const imagesZipFile = ref(null)
const targetProjectId = ref('')

const isImporting = ref(false)
const importResult = ref(null)
const errorMessage = ref('')
const copiedKey = ref('')

const isSyncing = ref(false)
const syncResult = ref(null)

const handleJsonChange = (e) => {
  const file = e.target.files[0]
  if (file) {
    cocoJsonFile.value = file
    if (!datasetName.value) {
      datasetName.value = file.name.replace(/\.[^/.]+$/, '').replace(/[_-]/g, '_')
    }
  }
}

const handleZipChange = (e) => {
  const file = e.target.files[0]
  if (file) imagesZipFile.value = file
}

const copyToClipboard = async (text, key) => {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    setTimeout(() => {
      copiedKey.value = ''
    }, 2500)
  } catch (err) {
    // Fallback
    const textArea = document.createElement('textarea')
    textArea.value = text
    document.body.appendChild(textArea)
    textArea.select()
    document.execCommand('copy')
    document.body.removeChild(textArea)
    copiedKey.value = key
    setTimeout(() => {
      copiedKey.value = ''
    }, 2500)
  }
}

const getFullUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE_URL}${url}`
}

const submitCvatImport = async () => {
  if (!cocoJsonFile.value || !imagesZipFile.value) {
    alert('Silakan pilih file COCO JSON anotasi dan file zip gambar dari CVAT!')
    return
  }

  isImporting.value = true
  errorMessage.value = ''
  importResult.value = null

  const formData = new FormData()
  formData.append('dataset_name', datasetName.value || 'cvat_dataset')
  formData.append('coco_json_file', cocoJsonFile.value)
  formData.append('images_zip_file', imagesZipFile.value)
  if (targetProjectId.value) {
    formData.append('project_id', targetProjectId.value)
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/data/import-cvat`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    if (res.ok && data.success) {
      importResult.value = data
      cocoJsonFile.value = null
      imagesZipFile.value = null
    } else {
      errorMessage.value = data.detail || data.message || 'Gagal mengimpor dataset CVAT.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi ke backend gagal saat proses impor.'
  } finally {
    isImporting.value = false
  }
}

const triggerSync = async () => {
  isSyncing.value = true
  syncResult.value = null
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/data/sync-label-studio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: targetProjectId.value || null,
        include_bad: true,
        include_good: true
      })
    })
    const data = await res.json()
    if (res.ok && data.success) {
      syncResult.value = data
    } else {
      alert(data.message || data.error || 'Gagal sinkronisasi data ke Label Studio.')
    }
  } catch (err) {
    alert('Koneksi backend error.')
  } finally {
    isSyncing.value = false
  }
}
</script>

<template>
  <div class="data-studio-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Dataset Studio & Label Studio Bridge</h1>
        <p class="page-subtitle">
          Unggah dataset CVAT langsung dari Web UI, simpan ke folder khusus di S3, dan salin URL / Prefix untuk langsung dihubungkan ke Label Studio.
        </p>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert alert-danger">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ errorMessage }}
    </div>

    <!-- SUCCESS MODAL / CARD: S3 URL & COPYABLE INFOS FOR LABEL STUDIO -->
    <div v-if="importResult" class="success-result-card">
      <div class="result-header">
        <div class="result-badge">
          <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Folder Dataset S3 Berhasil Dibuat!
        </div>
        <button class="btn-close" @click="importResult = null">&times;</button>
      </div>

      <p class="result-intro">
        Dataset telah diekstrak dan disimpan ke folder khusus di S3: <strong>{{ importResult.dataset_folder }}</strong>. Total <strong>{{ importResult.images_uploaded_count }} gambar</strong> dan <strong>{{ importResult.tasks_created_count }} anotasi</strong> siap digunakan.
      </p>

      <!-- Copyable URLs Section -->
      <div class="copy-fields-grid">
        
        <!-- Field 1: S3 Bucket Prefix (Folder) -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">S3 Folder Prefix (Untuk Cloud Storage Source)</span>
            <span v-if="copiedKey === 'prefix'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="importResult.s3_folder_prefix" class="copy-input" />
            <button class="btn-copy" @click="copyToClipboard(importResult.s3_folder_prefix, 'prefix')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin Prefix
            </button>
          </div>
        </div>

        <!-- Field 2: Full S3 URI -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">Full S3 URI (Folder Gambar)</span>
            <span v-if="copiedKey === 's3_uri'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="importResult.s3_uri" class="copy-input font-mono" />
            <button class="btn-copy" @click="copyToClipboard(importResult.s3_uri, 's3_uri')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin S3 URI
            </button>
          </div>
        </div>

        <!-- Field 3: Tasks JSON Direct URL -->
        <div class="copy-field-item">
          <div class="field-label-row">
            <span class="field-title">Tasks Anotasi URL (Untuk Tab 'Import' di Label Studio)</span>
            <span v-if="copiedKey === 'tasks_url'" class="copied-indicator">✓ Tersalin!</span>
          </div>
          <div class="copy-input-group">
            <input type="text" readonly :value="getFullUrl(importResult.tasks_json_url)" class="copy-input text-blue-600" />
            <button class="btn-copy" @click="copyToClipboard(getFullUrl(importResult.tasks_json_url), 'tasks_url')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              Salin URL
            </button>
          </div>
        </div>

      </div>

      <!-- Quick Setup Guide for Label Studio -->
      <div class="ls-guide-card">
        <h3 class="guide-title">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
          Cara Memasukkan ke Label Studio:
        </h3>
        <div class="guide-options">
          <div class="guide-option">
            <strong>Opsi 1: Import Langsung via URL</strong>
            <ol>
              <li>Buka Project di Label Studio &gt; Klik <strong>Import</strong>.</li>
              <li>Pilih tab <strong>URL</strong>, lalu paste <em>Tasks Anotasi URL</em> di atas.</li>
              <li>Klik <strong>Load</strong>. Seluruh gambar dan bounding box CVAT langsung muncul sebagai task teranotasi!</li>
            </ol>
          </div>

          <div class="guide-option">
            <strong>Opsi 2: Sinkronisasi S3 Cloud Storage</strong>
            <ol>
              <li>Buka Project &gt; <strong>Settings &gt; Cloud Storage &gt; Add Source Storage</strong>.</li>
              <li>Pilih Storage Type: <strong>AWS S3</strong>.</li>
              <li>Bucket Name: <code>{{ importResult.s3_bucket }}</code>.</li>
              <li>Bucket Prefix: <code>{{ importResult.s3_folder_prefix }}</code>.</li>
              <li>Centang <em>"Treat every bucket object as a source file"</em> lalu klik <strong>Sync Storage</strong>.</li>
            </ol>
          </div>
        </div>
      </div>

    </div>

    <!-- Main Grid: Upload Form & Flywheel Sync -->
    <div class="studio-grid">
      <!-- Left Card: CVAT Upload Form -->
      <div class="card">
        <div class="card-header">
          <div class="flex items-center gap-2">
            <svg viewBox="0 0 24 24" width="20" height="20" stroke="#2563eb" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            <h2 class="card-title">Unggah Dataset dari CVAT</h2>
          </div>
          <span class="badge badge-primary">COCO Format</span>
        </div>

        <div class="card-body">
          <p class="desc-text">
            Unggah hasil ekspor CVAT (file JSON anotasi COCO dan file Zip gambar). Sistem akan membuat folder khusus di S3 dan menyediakan URL siap pakai untuk Label Studio.
          </p>

          <form @submit.prevent="submitCvatImport">
            <div class="form-group">
              <label class="form-label">Nama Folder / Dataset</label>
              <input 
                type="text" 
                v-model="datasetName" 
                class="form-input" 
                placeholder="Contoh: dataset_cvat_defect" 
              />
              <span class="form-hint">Folder khusus akan dibuat di S3 dengan nama ini.</span>
            </div>

            <div class="form-group">
              <label class="form-label">File Anotasi CVAT (.json) *</label>
              <input 
                type="file" 
                accept=".json" 
                class="form-file" 
                @change="handleJsonChange" 
                required 
              />
              <span class="form-hint">File JSON format COCO 1.0 dari CVAT.</span>
            </div>

            <div class="form-group">
              <label class="form-label">File Arsip Gambar (.zip) *</label>
              <input 
                type="file" 
                accept=".zip" 
                class="form-file" 
                @change="handleZipChange" 
                required 
              />
              <span class="form-hint">Arsip zip berisi gambar-gambar dataset CVAT.</span>
            </div>

            <div class="form-group">
              <label class="form-label">Label Studio Project ID (Opsional)</label>
              <input 
                type="text" 
                v-model="targetProjectId" 
                class="form-input" 
                placeholder="Misal: 1 (opsional jika ingin auto-push via API)" 
              />
            </div>

            <button type="submit" class="btn btn-primary btn-block" :disabled="isImporting">
              <span v-if="isImporting" class="spinner-sm"></span>
              {{ isImporting ? 'Mengunggah ke S3 & Memproses Folder...' : 'Unggah ke S3 & Dapatkan URL' }}
            </button>
          </form>
        </div>
      </div>

      <!-- Right Card: Active Learning Retraining Cycle -->
      <div class="card">
        <div class="card-header">
          <div class="flex items-center gap-2">
            <svg viewBox="0 0 24 24" width="20" height="20" stroke="#16a34a" stroke-width="2" fill="none"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
            <h2 class="card-title">Alur Active Retraining (Flywheel)</h2>
          </div>
          <span class="badge badge-success">Automated Bridge</span>
        </div>

        <div class="card-body">
          <p class="desc-text">
            Bagaimana data dari inferensi dan umpan balik pengguna di web berputar kembali untuk retraining model:
          </p>

          <div class="pipeline-steps">
            <div class="pipe-step">
              <div class="step-num">1</div>
              <div>
                <strong>Inferensi dari Web Klien</strong>
                <p>Web lain memanggil <code>POST /api/v1/models/predict</code>. Semua gambar disimpan otomatis di S3.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">2</div>
              <div>
                <strong>Pengumpulan Feedback</strong>
                <p>Jika pengguna memberi feedback <em>Tidak Akurat</em>, gambar masuk ke <em>Review Queue</em> di S3.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">3</div>
              <div>
                <strong>Sinkronisasi Bulanan ke Label Studio</strong>
                <p>Data yang butuh anotasi ulang dikirim ke Label Studio untuk diperbaiki oleh tim annotator.</p>
              </div>
            </div>

            <div class="pipe-step">
              <div class="step-num">4</div>
              <div>
                <strong>Retrain & Hot-Swap Model</strong>
                <p>Model baru dilatih di GPU/Colab, lalu diunggah kembali ke sistem ini tanpa mengubah endpoint API!</p>
              </div>
            </div>
          </div>

          <div class="sync-action-wrap">
            <button class="btn btn-secondary btn-block" @click="triggerSync" :disabled="isSyncing">
              <span v-if="isSyncing" class="spinner-sm"></span>
              {{ isSyncing ? 'Mensinkronkan...' : 'Sinkronkan Data Review ke Label Studio' }}
            </button>
            <div v-if="syncResult" class="text-xs text-emerald-600 mt-2 text-center">
              ✓ {{ syncResult.message }}
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.data-studio-container {
  padding: 8px 0;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 6px 0;
}

.page-subtitle {
  font-size: 0.875rem;
  color: #64748b;
  margin: 0;
  max-width: 680px;
  line-height: 1.5;
}

/* Success Card */
.success-result-card {
  background: white;
  border: 2px solid #86efac;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 28px;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.08);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #dcfce7;
  color: #15803d;
  font-weight: 700;
  font-size: 1.05rem;
  padding: 6px 14px;
  border-radius: 9999px;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
}

.result-intro {
  font-size: 0.9rem;
  color: #334155;
  margin: 0 0 20px 0;
  line-height: 1.5;
}

.copy-fields-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 24px;
}

.copy-field-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}

.field-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.field-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.copied-indicator {
  font-size: 0.75rem;
  font-weight: 700;
  color: #16a34a;
}

.copy-input-group {
  display: flex;
  gap: 8px;
}

.copy-input {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: white;
  font-size: 0.85rem;
  color: #1e293b;
}

.btn-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}
.btn-copy:hover { background: #1d4ed8; }

.ls-guide-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 16px 20px;
}

.guide-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #166534;
  margin: 0 0 12px 0;
}

.guide-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 768px) {
  .guide-options {
    grid-template-columns: 1fr;
  }
}

.guide-option strong {
  display: block;
  font-size: 0.85rem;
  color: #14532d;
  margin-bottom: 6px;
}

.guide-option ol {
  margin: 0;
  padding-left: 18px;
  font-size: 0.8rem;
  color: #166534;
  line-height: 1.5;
}

.guide-option li {
  margin-bottom: 4px;
}

/* Studio Grid */
.studio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 900px) {
  .studio-grid { grid-template-columns: 1fr; }
}

.card {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
  overflow: hidden;
}

.card-header {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
}

.card-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.card-body { padding: 20px; }

.desc-text {
  font-size: 0.85rem;
  color: #64748b;
  margin: 0 0 18px 0;
  line-height: 1.5;
}

.form-group { margin-bottom: 16px; }

.form-label {
  display: block;
  font-size: 0.825rem;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 0.875rem;
  box-sizing: border-box;
}

.form-file {
  width: 100%;
  font-size: 0.85rem;
  color: #475569;
}

.form-hint {
  display: block;
  font-size: 0.725rem;
  color: #94a3b8;
  margin-top: 4px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  font-size: 0.875rem;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }

.btn-secondary {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #e2e8f0;
}
.btn-secondary:hover { background: #e2e8f0; }

.btn-block { width: 100%; }

.badge {
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}
.badge-primary { background: #dbeafe; color: #1e40af; }
.badge-success { background: #dcfce7; color: #166534; }

.pipeline-steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 24px;
}

.pipe-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.step-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.pipe-step strong {
  display: block;
  font-size: 0.85rem;
  color: #1e293b;
}

.pipe-step p {
  font-size: 0.78rem;
  color: #64748b;
  margin: 2px 0 0 0;
  line-height: 1.4;
}

.sync-action-wrap {
  margin-top: 16px;
  border-top: 1px solid #f1f5f9;
  padding-top: 16px;
}

.alert {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.875rem;
}

.alert-danger { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>

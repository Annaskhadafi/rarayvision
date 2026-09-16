<script setup>
import { ref, onMounted, computed } from 'vue'
import { API_BASE_URL } from '../../utils'

const activeModel = ref(null)
const isModelLoading = ref(false)

const selectedFile = ref(null)
const previewUrl = ref('')
const imageUrlInput = ref('')
const confThreshold = ref(0.25)
const iouThreshold = ref(0.45)

const isPredicting = ref(false)
const predictionResult = ref(null)
const errorMessage = ref('')
const feedbackSubmitted = ref(null)
const isSubmittingFeedback = ref(false)
const feedbackNotes = ref('')
const showFeedbackModal = ref(false)

const fetchActiveModel = async () => {
  isModelLoading.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models`)
    const data = await res.json()
    if (res.ok) {
      activeModel.value = (data.models || []).find(m => m.is_active) || null
    }
  } catch (err) {
    console.error('Failed to fetch active model:', err)
  } finally {
    isModelLoading.value = false
  }
}

const handleFileSelect = (e) => {
  const file = e.target.files[0]
  if (file) {
    selectedFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    predictionResult.value = null
    feedbackSubmitted.value = null
  }
}

const handleDrop = (e) => {
  e.preventDefault()
  const file = e.dataTransfer.files[0]
  if (file && file.type.startsWith('image/')) {
    selectedFile.value = file
    previewUrl.value = URL.createObjectURL(file)
    predictionResult.value = null
    feedbackSubmitted.value = null
  }
}

const runPrediction = async () => {
  if (!selectedFile.value && !imageUrlInput.value) {
    alert('Pilih file gambar atau masukkan URL gambar terlebih dahulu!')
    return
  }

  isPredicting.value = true
  errorMessage.value = ''
  predictionResult.value = null
  feedbackSubmitted.value = null

  const formData = new FormData()
  if (selectedFile.value) {
    formData.append('file', selectedFile.value)
  } else if (imageUrlInput.value) {
    formData.append('image_url', imageUrlInput.value)
  }
  formData.append('conf_threshold', confThreshold.value)
  formData.append('iou_threshold', iouThreshold.value)

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/predict`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    if (res.ok) {
      predictionResult.value = data
      // Pre-set feedback status if auto-labeled
      if (data.feedback_status === 'auto_labeled') {
        feedbackSubmitted.value = {
          status: 'auto_labeled',
          message: 'Sistem menandai hasil ini dengan kepercayaan tinggi (>88%).'
        }
      }
    } else {
      errorMessage.value = data.detail || 'Gagal menjalankan inferensi deteksi.'
    }
  } catch (err) {
    errorMessage.value = 'Koneksi ke backend inference endpoint gagal.'
  } finally {
    isPredicting.value = false
  }
}

const submitFeedback = async (statusVal) => {
  if (!predictionResult.value) return

  if (statusVal === 'bad' && !showFeedbackModal.value) {
    // Open modal to optionally take notes
    showFeedbackModal.value = true
    return
  }

  isSubmittingFeedback.value = true
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/models/feedback/${predictionResult.value.prediction_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback: statusVal,
        notes: feedbackNotes.value || null
      })
    })
    const data = await res.json()
    if (res.ok) {
      feedbackSubmitted.value = {
        status: statusVal,
        message: statusVal === 'good'
          ? 'Feedback "Akurat" tersimpan! Data ini masuk verifikasi auto-label di Label Studio.'
          : 'Feedback "Tidak Akurat" tersimpan! Gambar otomatis dimasukkan ke antrean Label Studio untuk re-labeling bulanan.'
      }
      showFeedbackModal.value = false
      feedbackNotes.value = ''
    } else {
      alert(data.detail || 'Gagal mengirimkan feedback.')
    }
  } catch (err) {
    alert('Koneksi backend error saat mengirim feedback.')
  } finally {
    isSubmittingFeedback.value = false
  }
}

// Convert relative static URL to full URL if needed
const getFullImageUrl = (url) => {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  return `${API_BASE_URL}${url}`
}

onMounted(() => {
  fetchActiveModel()
})
</script>

<template>
  <div class="playground-container">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">Object Detection Playground & Live Feedback</h1>
        <p class="page-subtitle">
          Uji coba model aktif secara interaktif, lihat visualisasi bounding box, dan kirim umpan balik (Akurat / Tidak Akurat) untuk memutar siklus Active Learning.
        </p>
      </div>

      <!-- Active Model Banner -->
      <div class="active-model-pill">
        <span class="pulse-indicator"></span>
        <div class="model-info-text">
          <span class="caption">Model Aktif</span>
          <strong class="name">{{ activeModel ? `${activeModel.name} (${activeModel.version})` : 'YOLO Default' }}</strong>
        </div>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert alert-danger">
      <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      {{ errorMessage }}
    </div>

    <!-- Layout Grid -->
    <div class="playground-grid">
      <!-- Left Column: Controls & Input -->
      <div class="panel control-panel">
        <h2 class="panel-title">Parameter & Unggah Gambar</h2>

        <!-- Thresholds -->
        <div class="control-group">
          <div class="slider-header">
            <label class="control-label">Confidence Threshold</label>
            <span class="slider-val">{{ (confThreshold * 100).toFixed(0) }}%</span>
          </div>
          <input 
            type="range" 
            min="0.05" 
            max="0.95" 
            step="0.05" 
            v-model.number="confThreshold" 
            class="slider" 
          />
        </div>

        <div class="control-group">
          <div class="slider-header">
            <label class="control-label">NMS / IoU Threshold</label>
            <span class="slider-val">{{ (iouThreshold * 100).toFixed(0) }}%</span>
          </div>
          <input 
            type="range" 
            min="0.1" 
            max="0.9" 
            step="0.05" 
            v-model.number="iouThreshold" 
            class="slider" 
          />
        </div>

        <!-- Dropzone -->
        <div 
          class="dropzone" 
          @dragover.prevent 
          @drop="handleDrop"
          @click="$refs.fileInput.click()"
        >
          <input 
            type="file" 
            ref="fileInput" 
            accept="image/*" 
            class="hidden-input" 
            @change="handleFileSelect" 
          />
          <svg viewBox="0 0 24 24" width="36" height="36" stroke="#94a3b8" stroke-width="1.5" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
          <div class="drop-text">
            <strong>Klik atau Tarik Gambar ke Sini</strong>
            <span>Mendukung JPG, PNG, WebP</span>
          </div>
          <div v-if="selectedFile" class="selected-filename">
            {{ selectedFile.name }} ({{ (selectedFile.size / 1024).toFixed(0) }} KB)
          </div>
        </div>

        <!-- Or URL Input -->
        <div class="url-divider">
          <span>atau gunakan URL</span>
        </div>
        <div class="url-input-wrap">
          <input 
            type="text" 
            v-model="imageUrlInput" 
            placeholder="https://example.com/image.jpg" 
            class="form-input" 
          />
        </div>

        <!-- Run Button -->
        <button 
          class="btn btn-primary btn-block btn-predict" 
          @click="runPrediction" 
          :disabled="isPredicting || (!selectedFile && !imageUrlInput)"
        >
          <span v-if="isPredicting" class="spinner-sm"></span>
          {{ isPredicting ? 'Menganalisis Gambar...' : 'Jalankan Deteksi Objek' }}
        </button>

        <!-- API Consumption Info Card -->
        <div class="api-info-box">
          <div class="api-info-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>
            Konsumsi via Web Eksternal
          </div>
          <div class="api-code-snippet">
            <code>POST {{ API_BASE_URL }}/api/v1/models/predict</code>
          </div>
          <p class="api-desc">
            Kirim gambar via multipart form <code>file</code> atau <code>image_url</code>. Output akan mengembalikan <code>prediction_id</code> dan URL gambar hasil anotasi.
          </p>
        </div>
      </div>

      <!-- Right Column: Visual Preview & Feedback -->
      <div class="panel preview-panel">
        <div class="preview-header">
          <h2 class="panel-title">Hasil Prediksi & Anotasi</h2>
          <div v-if="predictionResult" class="metrics-badges">
            <span class="badge badge-latency">
              <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              {{ predictionResult.latency_ms }} ms
            </span>
            <span class="badge badge-count">{{ predictionResult.detection_count }} Terdeteksi</span>
            <span class="badge badge-conf">Top Conf: {{ (predictionResult.top_confidence * 100).toFixed(0) }}%</span>
            <!-- CV-Ops Quality Gate Badge -->
            <span v-if="predictionResult.quality" class="badge" :class="predictionResult.quality.is_usable ? 'badge-good-quality' : 'badge-bad-quality'">
              {{ predictionResult.quality.is_usable ? '✓ Kualitas Baik' : '⚠ Gambar Terdegradasi' }}
            </span>
          </div>
        </div>

        <!-- Image Viewer Container -->
        <div class="image-viewer-wrap">
          <!-- Predicted Image -->
          <div v-if="predictionResult" class="rendered-image-box">
            <img :src="getFullImageUrl(predictionResult.annotated_image_url)" alt="Predicted Output" class="main-image" />
          </div>

          <!-- Raw Preview before prediction -->
          <div v-else-if="previewUrl" class="rendered-image-box">
            <img :src="previewUrl" alt="Raw Preview" class="main-image opacity-80" />
            <div class="overlay-ready">Klik tombol "Jalankan Deteksi Objek"</div>
          </div>

          <!-- Empty placeholder -->
          <div v-else class="empty-viewer">
            <svg viewBox="0 0 24 24" width="64" height="64" stroke="#cbd5e1" stroke-width="1" fill="none"><circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8"></polygon></svg>
            <p>Pilih atau unggah gambar untuk memulai uji deteksi objek.</p>
          </div>
        </div>

        <!-- CV-Ops Warning & Audit Banner -->
        <div v-if="predictionResult && !predictionResult.quality?.is_usable" class="quality-alert-banner">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          <div>
            <strong>Peringatan Kualitas Gambar (CV-Ops Gate):</strong>
            <div>{{ predictionResult.quality?.warnings?.join(', ') || 'Kualitas gambar rendah (buram atau pencahayaan kurang).' }}</div>
          </div>
        </div>

        <div v-if="predictionResult && predictionResult.is_audit_sample" class="audit-sample-banner">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          <div>
            <strong>10% Random Human Audit Sample:</strong>
            <div>Gambar ini terpilih secara acak untuk diverifikasi manusia di Label Studio guna mencegah <em>confirmation bias</em>.</div>
          </div>
        </div>

        <!-- Feedback Loop Interaction Area -->
        <div v-if="predictionResult" class="feedback-section">
          <div class="feedback-banner">
            <div class="feedback-prompt">
              <strong>Apakah hasil deteksi ini akurat?</strong>
              <span>Umpan balik Anda secara langsung melatih model generasi berikutnya via Label Studio & S3 Flywheel.</span>
            </div>

            <div class="feedback-buttons">
              <button 
                class="btn btn-feedback-good" 
                @click="submitFeedback('good')"
                :disabled="isSubmittingFeedback || feedbackSubmitted?.status === 'good'"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>
                Akurat (Thumbs Up)
              </button>
              <button 
                class="btn btn-feedback-bad" 
                @click="submitFeedback('bad')"
                :disabled="isSubmittingFeedback || feedbackSubmitted?.status === 'bad'"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>
                Tidak Akurat (Koreksi)
              </button>
            </div>
          </div>

          <!-- Feedback Status Toast -->
          <div v-if="feedbackSubmitted" class="feedback-status-box" :class="feedbackSubmitted.status">
            <div class="flex items-center gap-2">
              <svg v-if="feedbackSubmitted.status === 'good'" viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
              <svg v-else viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
              <span>{{ feedbackSubmitted.message }}</span>
            </div>
          </div>
        </div>

        <!-- Detections Breakdown List -->
        <div v-if="predictionResult && predictionResult.detections.length > 0" class="detections-card">
          <div class="detections-card-title">Objek Terdeteksi ({{ predictionResult.detections.length }})</div>
          <div class="detections-table-wrap">
            <table class="sub-table">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Confidence</th>
                  <th>Koordinat [x1, y1, x2, y2]</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="det in predictionResult.detections" :key="det.id">
                  <td>
                    <span class="label-pill">{{ det.label }}</span>
                  </td>
                  <td>
                    <div class="conf-bar-wrap">
                      <div class="conf-bar" :style="{ width: `${det.confidence * 100}%` }"></div>
                      <span class="conf-text">{{ (det.confidence * 100).toFixed(1) }}%</span>
                    </div>
                  </td>
                  <td class="font-mono text-xs text-slate-500">
                    [{{ det.box.join(', ') }}]
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>

    <!-- Modal Feedback Notes (Bad feedback) -->
    <div v-if="showFeedbackModal" class="modal-overlay" @click.self="showFeedbackModal = false">
      <div class="modal-content modal-sm">
        <div class="modal-header">
          <h3 class="modal-title">Koreksi & Feedback Model</h3>
          <button class="btn-close" @click="showFeedbackModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <p class="text-sm text-slate-600 mb-3">
            Jelaskan apa yang salah pada deteksi ini (misal: objek terlewat, salah label kelas, atau bounding box meleset). Gambar ini akan dimasukkan ke antrean Label Studio untuk dianotasi ulang.
          </p>
          <div class="form-group">
            <label class="form-label">Catatan Kesalahan (Opsional)</label>
            <textarea 
              v-model="feedbackNotes" 
              class="form-textarea" 
              rows="3" 
              placeholder="Contoh: Bounding box mobil terpotong, atau orang di background tidak terdeteksi..."
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showFeedbackModal = false">Batal</button>
          <button class="btn btn-primary" @click="submitFeedback('bad')">
            Kirim ke Review Queue
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.playground-container {
  padding: 8px 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
  max-width: 650px;
  line-height: 1.5;
}

.active-model-pill {
  display: flex;
  align-items: center;
  gap: 12px;
  background: white;
  border: 1px solid #e2e8f0;
  padding: 8px 16px;
  border-radius: 9999px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.pulse-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);
  animation: pulse-ring 1.8s infinite;
}

@keyframes pulse-ring {
  0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
  70% { box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); }
  100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}

.model-info-text .caption {
  display: block;
  font-size: 0.65rem;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.model-info-text .name {
  font-size: 0.85rem;
  color: #1e293b;
}

.playground-grid {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 24px;
}

@media (max-width: 1024px) {
  .playground-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 24px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
}

.panel-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 16px 0;
}

.control-group {
  margin-bottom: 18px;
}

.slider-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.control-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.slider-val {
  font-size: 0.8rem;
  font-weight: 600;
  color: #2563eb;
}

.slider {
  width: 100%;
  accent-color: #2563eb;
  cursor: pointer;
}

.dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  background: #f8fafc;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.dropzone:hover {
  border-color: #2563eb;
  background: #eff6ff;
}

.hidden-input {
  display: none;
}

.drop-text strong {
  display: block;
  font-size: 0.85rem;
  color: #334155;
}

.drop-text span {
  font-size: 0.75rem;
  color: #94a3b8;
}

.selected-filename {
  font-size: 0.75rem;
  color: #16a34a;
  font-weight: 500;
  background: #dcfce7;
  padding: 4px 10px;
  border-radius: 4px;
}

.url-divider {
  display: flex;
  align-items: center;
  text-align: center;
  margin: 12px 0;
  color: #94a3b8;
  font-size: 0.75rem;
}

.url-divider::before, .url-divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid #e2e8f0;
}

.url-divider span {
  padding: 0 10px;
}

.url-input-wrap {
  margin-bottom: 20px;
}

.form-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 0.85rem;
  box-sizing: border-box;
}

.btn-predict {
  padding: 12px;
  font-size: 0.95rem;
  font-weight: 600;
}

.btn-block {
  width: 100%;
}

.api-info-box {
  margin-top: 24px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px;
}

.api-info-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}

.api-code-snippet {
  background: #1e293b;
  color: #38bdf8;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: monospace;
  overflow-x: auto;
  margin-bottom: 8px;
}

.api-desc {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
  line-height: 1.4;
}

/* Preview Panel */
.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.metrics-badges {
  display: flex;
  gap: 8px;
}

.badge-latency {
  background: #f1f5f9;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.badge-count {
  background: #e0f2fe;
  color: #0369a1;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
}

.badge-conf {
  background: #fef3c7;
  color: #b45309;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
}

.image-viewer-wrap {
  width: 100%;
  min-height: 420px;
  background: #0f172a;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.rendered-image-box {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
}

.main-image {
  max-width: 100%;
  max-height: 600px;
  object-fit: contain;
  display: block;
}

.overlay-ready {
  position: absolute;
  bottom: 20px;
  background: rgba(15, 23, 42, 0.85);
  color: white;
  padding: 8px 16px;
  border-radius: 9999px;
  font-size: 0.85rem;
}

.empty-viewer {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #64748b;
  font-size: 0.875rem;
  padding: 40px;
}

/* Feedback Section */
.feedback-section {
  margin-top: 20px;
}

.feedback-banner {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.feedback-prompt strong {
  display: block;
  font-size: 0.9rem;
  color: #1e293b;
  margin-bottom: 2px;
}

.feedback-prompt span {
  font-size: 0.78rem;
  color: #64748b;
}

.feedback-buttons {
  display: flex;
  gap: 10px;
}

.btn-feedback-good {
  background: #22c55e;
  color: white;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-feedback-good:hover { background: #16a34a; }

.btn-feedback-bad {
  background: #ef4444;
  color: white;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-feedback-bad:hover { background: #dc2626; }

.feedback-status-box {
  margin-top: 12px;
  padding: 10px 16px;
  border-radius: 6px;
  font-size: 0.85rem;
}

.feedback-status-box.good {
  background: #dcfce7;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.feedback-status-box.bad {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.feedback-status-box.auto_labeled {
  background: #e0f2fe;
  color: #0369a1;
  border: 1px solid #bae6fd;
}

/* Detections Breakdown Table */
.detections-card {
  margin-top: 24px;
  border-top: 1px solid #f1f5f9;
  padding-top: 16px;
}

.detections-card-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 12px;
}

.sub-table {
  width: 100%;
  border-collapse: collapse;
}

.sub-table th {
  background: #f8fafc;
  padding: 8px 12px;
  font-size: 0.72rem;
  color: #64748b;
  text-transform: uppercase;
  text-align: left;
}

.sub-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.825rem;
}

.label-pill {
  background: #f1f5f9;
  color: #334155;
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.conf-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.conf-bar {
  height: 6px;
  background: #22c55e;
  border-radius: 9999px;
  min-width: 4px;
}

.conf-text {
  font-size: 0.75rem;
  font-weight: 600;
  color: #475569;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  padding: 16px;
}

.modal-content {
  background: white;
  border-radius: 12px;
  width: 100%;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.modal-sm { max-width: 460px; }

.modal-header {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
}

.modal-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.4rem;
  color: #94a3b8;
  cursor: pointer;
}

.modal-body {
  padding: 20px;
}

.form-textarea {
  width: 100%;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 0.85rem;
  box-sizing: border-box;
}

.modal-footer {
  padding: 14px 20px;
  background: #f8fafc;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid #f1f5f9;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 0.85rem;
  font-weight: 500;
  border-radius: 6px;
  border: none;
  cursor: pointer;
}

.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }
.btn-secondary { background: #f1f5f9; color: #475569; }

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

.badge-good-quality { background: #dcfce7; color: #15803d; }
.badge-bad-quality { background: #fee2e2; color: #b91c1c; }
.quality-alert-banner {
  margin-top: 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 0.85rem;
  color: #991b1b;
}
.audit-sample-banner {
  margin-top: 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 0.85rem;
  color: #1e40af;
}

</style>

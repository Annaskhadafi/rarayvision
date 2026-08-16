<script setup>
import { ref, computed } from 'vue'
import { pdfInspectorService } from '../services/pdfInspectorService'
import { API_BASE_URL } from '../utils'

const selectedFile = ref(null)
const pageFilter = ref('')
const activeMode = ref('process') // process, force_ocr, classify, extract-text, extract-markdown, extract-positions, extract-structure
const autoOcr = ref(true)
const isProcessing = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const activeTab = ref('markdown') // markdown, text, positions, raw_json, api_code
const copiedSnippet = ref(false)

const resultData = ref(null)
const executionTime = ref(null)

const isDragging = ref(false)

const onFileSelect = (event) => {
  const file = event.target.files?.[0]
  if (file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      errorMessage.value = 'Please select a valid PDF document (.pdf)'
      return
    }
    selectedFile.value = file
    errorMessage.value = ''
    successMessage.value = ''
  }
}

const onDropFile = (event) => {
  isDragging.value = false
  const file = event.dataTransfer.files?.[0]
  if (file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      errorMessage.value = 'Please drop a valid PDF document (.pdf)'
      return
    }
    selectedFile.value = file
    errorMessage.value = ''
    successMessage.value = ''
  }
}

const clearFile = () => {
  selectedFile.value = null
  resultData.value = null
  errorMessage.value = ''
  successMessage.value = ''
  executionTime.value = null
}

const inspectPdf = async () => {
  if (!selectedFile.value) {
    errorMessage.value = 'Please upload a PDF document first.'
    return
  }

  isProcessing.value = true
  errorMessage.value = ''
  successMessage.value = ''
  const startTime = performance.now()

  try {
    let response
    if (activeMode.value === 'process') {
      response = await pdfInspectorService.process(selectedFile.value, pageFilter.value, autoOcr.value)
      activeTab.value = 'markdown'
    } else if (activeMode.value === 'force_ocr') {
      response = await pdfInspectorService.ocrScanned(selectedFile.value, pageFilter.value)
      activeTab.value = 'markdown'
    } else if (activeMode.value === 'classify') {
      response = await pdfInspectorService.classify(selectedFile.value)
      activeTab.value = 'raw_json'
    } else if (activeMode.value === 'extract-text') {
      response = await pdfInspectorService.extractText(selectedFile.value)
      activeTab.value = 'text'
    } else if (activeMode.value === 'extract-markdown') {
      response = await pdfInspectorService.extractMarkdown(selectedFile.value, pageFilter.value)
      activeTab.value = 'markdown'
    } else if (activeMode.value === 'extract-positions') {
      response = await pdfInspectorService.extractPositions(selectedFile.value)
      activeTab.value = 'positions'
    } else if (activeMode.value === 'extract-structure') {
      response = await pdfInspectorService.extractStructure(selectedFile.value)
      activeTab.value = 'raw_json'
    }

    resultData.value = response.data
    executionTime.value = (performance.now() - startTime).toFixed(1)
    
    const ocrPages = resultData.value?.ocr_applied_pages || []
    if (ocrPages.length > 0) {
      successMessage.value = `PDF inspected & Hybrid OCR applied on page(s) ${ocrPages.join(', ')} in ${executionTime.value} ms!`
    } else {
      successMessage.value = `PDF processed successfully via native engine in ${executionTime.value} ms!`
    }
  } catch (err) {
    errorMessage.value = err.message || 'Error occurred while processing PDF.'
  } finally {
    isProcessing.value = false
  }
}

// Computed Badges & Statuses
const pdfType = computed(() => resultData.value?.pdf_type || (activeMode.value === 'force_ocr' ? 'scanned_ocr' : 'unknown'))
const confidencePct = computed(() => {
  if (resultData.value?.confidence !== undefined) {
    return Math.round(resultData.value.confidence * 100)
  }
  return null
})

const pdfTypeClass = computed(() => {
  switch (pdfType.value.toLowerCase()) {
    case 'text_based': return 'badge-success'
    case 'scanned': return 'badge-warning'
    case 'scanned_ocr': return 'badge-warning'
    case 'image_based': return 'badge-danger'
    case 'mixed': return 'badge-info'
    default: return 'badge-secondary'
  }
})

const formatTypeLabel = (type) => {
  if (!type) return 'Unknown'
  return type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

const copyToClipboard = (text) => {
  if (!text) return
  navigator.clipboard.writeText(text)
  copiedSnippet.value = true
  setTimeout(() => { copiedSnippet.value = false }, 2000)
}

// Microservice API Code Snippets generator for external sites
const apiToken = computed(() => localStorage.getItem('rarayvision-token') || 'YOUR_API_KEY_OR_TOKEN')

const curlCode = computed(() => {
  return `curl -X POST "${API_BASE_URL}/api/v1/pdf-inspector/process" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -F "file=@${selectedFile.value?.name || 'document.pdf'}" \\
  -F "auto_ocr=${autoOcr.value ? 'true' : 'false'}"`
})

const pythonCode = computed(() => {
  return `import requests

url = "${API_BASE_URL}/api/v1/pdf-inspector/process"
headers = {
    "Authorization": "Bearer ${apiToken.value}"
}
files = {
    "file": open("${selectedFile.value?.name || 'document.pdf'}", "rb")
}
data = {
    "auto_ocr": "${autoOcr.value ? 'true' : 'false'}"
}

response = requests.post(url, headers=headers, files=files, data=data)
result = response.json()
print("PDF Type:", result["data"]["pdf_type"])
print("OCR Applied Pages:", result["data"].get("ocr_applied_pages", []))
print("Markdown Result:\\n", result["data"]["markdown"])`
})

const jsCode = computed(() => {
  return `const formData = new FormData();
formData.append("file", pdfFileInput.files[0]);
formData.append("auto_ocr", "${autoOcr.value ? 'true' : 'false'}");

const response = await fetch("${API_BASE_URL}/api/v1/pdf-inspector/process", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ${apiToken.value}"
  },
  body: formData
});

const result = await response.json();
console.log("PDF Result:", result.data);`
})
</script>

<template>
  <div class="pdf-inspector-view">
    <!-- View Header -->
    <div class="view-header">
      <div>
        <h1 class="view-title">
          <svg viewBox="0 0 24 24" width="28" height="28" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="header-icon">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
          PDF Inspector & Hybrid OCR Microservice
        </h1>
        <p class="view-subtitle">
          Engine hybrid: Ekstraksi teks super cepat via native parser (<50ms) + Auto OCR Fallback (RapidOCR ONNX) untuk dokumen scan dengan output Markdown terstruktur.
        </p>
      </div>
      <div class="header-actions">
        <a :href="`${API_BASE_URL}/docs#/PDF%20Inspector%20Microservice`" target="_blank" class="btn btn-outline">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          OpenAPI Docs
        </a>
      </div>
    </div>

    <!-- Alert Notifications -->
    <div v-if="errorMessage" class="alert alert-error">
      <span>❌ {{ errorMessage }}</span>
    </div>
    <div v-if="successMessage" class="alert alert-success">
      <span>✅ {{ successMessage }}</span>
    </div>

    <!-- Main Grid Layout -->
    <div class="inspector-grid">
      <!-- Left Column: Upload & Options -->
      <div class="card upload-card">
        <h2 class="card-title">Document Inspection Inputs</h2>

        <!-- Drag & Drop Zone -->
        <div 
          :class="['drop-zone', { active: isDragging, 'has-file': selectedFile }]"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDropFile"
          @click="$refs.fileInput.click()"
        >
          <input 
            type="file" 
            ref="fileInput" 
            accept=".pdf" 
            style="display: none" 
            @change="onFileSelect"
          />

          <div v-if="!selectedFile" class="drop-prompt">
            <svg viewBox="0 0 24 24" width="48" height="48" stroke="#3b82f6" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            <p class="drop-text">Click or drag & drop a <strong>PDF Document</strong> here</p>
            <span class="drop-hint">Supports text-based & scanned PDFs up to 50MB</span>
          </div>

          <div v-else class="selected-file-info">
            <svg viewBox="0 0 24 24" width="40" height="40" stroke="#10b981" stroke-width="1.5" fill="none">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <div class="file-details">
              <div class="file-name">{{ selectedFile.name }}</div>
              <div class="file-meta">{{ (selectedFile.size / 1024).toFixed(1) }} KB</div>
            </div>
            <button type="button" class="btn-clear" @click.stop="clearFile" title="Remove File">✕</button>
          </div>
        </div>

        <!-- Options Form -->
        <div class="form-group">
          <label class="form-label">Inspection Mode:</label>
          <select v-model="activeMode" class="form-control">
            <option value="process">⚡ Hybrid Process (Fast Inspector + Auto OCR Scanned Pages)</option>
            <option value="force_ocr">🔍 Force Full OCR to Markdown (RapidOCR)</option>
            <option value="classify">📊 Fast Classification & OCR Routing Only</option>
            <option value="extract-text">📝 Raw Plain Text Extraction</option>
            <option value="extract-markdown">📄 Page-by-Page Markdown</option>
            <option value="extract-positions">📍 Text Positions & Coordinate Map (X, Y)</option>
            <option value="extract-structure">🏷️ Tagged PDF Structure Elements</option>
          </select>
        </div>

        <!-- Auto OCR Toggle for Hybrid Mode -->
        <div class="form-group" v-if="activeMode === 'process'">
          <label class="checkbox-label">
            <input type="checkbox" v-model="autoOcr" />
            <span class="checkbox-text">
              <strong>Auto OCR Fallback (RapidOCR ONNX)</strong>
              <small>Otomatis jalankan OCR untuk halaman scan & susun ke Markdown</small>
            </span>
          </label>
        </div>

        <div class="form-group" v-if="['process', 'force_ocr', 'extract-markdown'].includes(activeMode)">
          <label class="form-label">Page Filter (Optional):</label>
          <input 
            type="text" 
            v-model="pageFilter" 
            placeholder="e.g. 1,2,5 (Leave empty for all pages)" 
            class="form-control"
          />
        </div>

        <button 
          class="btn btn-primary btn-block" 
          :disabled="!selectedFile || isProcessing" 
          @click="inspectPdf"
        >
          <span v-if="isProcessing" class="spinner"></span>
          <span v-else>🚀 Inspect PDF</span>
        </button>
      </div>

      <!-- Right Column: Results & Inspection Output -->
      <div class="card result-card">
        <!-- Overview Banner / Badges -->
        <div v-if="resultData" class="overview-banner">
          <div class="metric-box">
            <span class="metric-label">Document Type</span>
            <span :class="['badge', pdfTypeClass]">{{ formatTypeLabel(pdfType) }}</span>
          </div>

          <div class="metric-box" v-if="confidencePct !== null">
            <span class="metric-label">Confidence</span>
            <span class="metric-value">{{ confidencePct }}%</span>
          </div>

          <div class="metric-box" v-if="resultData.page_count !== undefined || resultData.total_pages !== undefined">
            <span class="metric-label">Total Pages</span>
            <span class="metric-value">{{ resultData.page_count || resultData.total_pages }}</span>
          </div>

          <div class="metric-box" v-if="executionTime">
            <span class="metric-label">Total Latency</span>
            <span class="metric-value highlight">{{ executionTime }} ms</span>
          </div>

          <div class="metric-box" v-if="resultData.ocr_applied_pages && resultData.ocr_applied_pages.length > 0">
            <span class="metric-label">OCR Applied</span>
            <span class="badge badge-warning">Page {{ resultData.ocr_applied_pages.join(', ') }} (RapidOCR)</span>
          </div>
        </div>

        <!-- OCR Notice -->
        <div v-if="resultData && resultData.pages_needing_ocr && resultData.pages_needing_ocr.length > 0 && !autoOcr" class="ocr-notice">
          ⚠️ <strong>Pages Needing OCR:</strong> Pages <code>{{ resultData.pages_needing_ocr.join(', ') }}</code> require OCR scanning. Turn on <em>"Auto OCR Fallback"</em> to automatically convert them to Markdown.
        </div>

        <!-- Navigation Tabs -->
        <div class="tab-header" v-if="resultData">
          <button :class="['tab-btn', { active: activeTab === 'markdown' }]" @click="activeTab = 'markdown'">📄 Markdown Preview</button>
          <button :class="['tab-btn', { active: activeTab === 'text' }]" @click="activeTab = 'text'">📝 Plain Text</button>
          <button :class="['tab-btn', { active: activeTab === 'positions' }]" @click="activeTab = 'positions'">📍 Positions (X,Y)</button>
          <button :class="['tab-btn', { active: activeTab === 'raw_json' }]" @click="activeTab = 'raw_json'">🔍 Raw JSON</button>
          <button :class="['tab-btn', { active: activeTab === 'api_code' }]" @click="activeTab = 'api_code'">💻 Microservice API Snippets</button>
        </div>

        <!-- Empty State -->
        <div v-if="!resultData" class="empty-state">
          <svg viewBox="0 0 24 24" width="64" height="64" stroke="#94a3b8" stroke-width="1" fill="none">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
          <h3>No PDF Inspected Yet</h3>
          <p>Upload a PDF document on the left panel to test microservice classification and Markdown text extraction.</p>
        </div>

        <!-- Tab 1: Markdown Preview -->
        <div v-else-if="activeTab === 'markdown'" class="tab-body">
          <div class="tab-toolbar">
            <span>Markdown Content (Headings, Tables, Lists)</span>
            <button class="btn-copy" @click="copyToClipboard(resultData.markdown || JSON.stringify(resultData))">
              📋 {{ copiedSnippet ? 'Copied!' : 'Copy Markdown' }}
            </button>
          </div>
          <pre class="code-box">{{ resultData.markdown || 'No Markdown output for this mode.' }}</pre>
        </div>

        <!-- Tab 2: Plain Text -->
        <div v-else-if="activeTab === 'text'" class="tab-body">
          <div class="tab-toolbar">
            <span>Text Length: {{ (resultData.text || resultData.markdown || '').length }} characters</span>
            <button class="btn-copy" @click="copyToClipboard(resultData.text || resultData.markdown)">
              📋 {{ copiedSnippet ? 'Copied!' : 'Copy Text' }}
            </button>
          </div>
          <pre class="code-box">{{ resultData.text || resultData.markdown || 'No text extracted.' }}</pre>
        </div>

        <!-- Tab 3: Positions -->
        <div v-else-if="activeTab === 'positions'" class="tab-body">
          <div class="tab-toolbar">
            <span>Total Positioned Text Tokens: {{ resultData.count || 0 }}</span>
          </div>
          <div class="table-wrapper" v-if="resultData.items && resultData.items.length > 0">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Page</th>
                  <th>Text Token</th>
                  <th>X</th>
                  <th>Y</th>
                  <th>Width</th>
                  <th>Height</th>
                  <th>Font</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in resultData.items.slice(0, 200)" :key="idx">
                  <td>{{ item.page }}</td>
                  <td class="font-mono"><strong>{{ item.text }}</strong></td>
                  <td>{{ item.x.toFixed(1) }}</td>
                  <td>{{ item.y.toFixed(1) }}</td>
                  <td>{{ item.width.toFixed(1) }}</td>
                  <td>{{ item.height.toFixed(1) }}</td>
                  <td>{{ item.font || '-' }}</td>
                  <td>{{ item.font_size ? item.font_size.toFixed(1) : '-' }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="resultData.items.length > 200" class="table-footer-hint">
              Showing first 200 tokens out of {{ resultData.items.length }}.
            </div>
          </div>
          <div v-else class="empty-state-small">No position items extracted.</div>
        </div>

        <!-- Tab 4: Raw JSON -->
        <div v-else-if="activeTab === 'raw_json'" class="tab-body">
          <div class="tab-toolbar">
            <span>JSON Output</span>
            <button class="btn-copy" @click="copyToClipboard(JSON.stringify(resultData, null, 2))">
              📋 {{ copiedSnippet ? 'Copied!' : 'Copy JSON' }}
            </button>
          </div>
          <pre class="code-box">{{ JSON.stringify(resultData, null, 2) }}</pre>
        </div>

        <!-- Tab 5: Microservice API Code Snippets -->
        <div v-else-if="activeTab === 'api_code'" class="tab-body">
          <div class="api-snippet-section">
            <h3>cURL Request</h3>
            <pre class="code-box">{{ curlCode }}</pre>

            <h3>Python (requests)</h3>
            <pre class="code-box">{{ pythonCode }}</pre>

            <h3>JavaScript / Node.js (fetch)</h3>
            <pre class="code-box">{{ jsCode }}</pre>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-inspector-view {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.view-title {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 6px 0;
}

.header-icon {
  color: #3b82f6;
}

.view-subtitle {
  color: #64748b;
  font-size: 14px;
  margin: 0;
}

.alert {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 14px;
}

.alert-error {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.alert-success {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.inspector-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 24px;
}

@media (max-width: 992px) {
  .inspector-grid {
    grid-template-columns: 1fr;
  }
}

.card {
  background: #ffffff;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 16px 0;
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #f8fafc;
  margin-bottom: 20px;
}

.drop-zone:hover, .drop-zone.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

.drop-zone.has-file {
  border-style: solid;
  border-color: #10b981;
  background: #f0fdf4;
}

.drop-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.drop-text {
  margin: 0;
  color: #334155;
  font-size: 14px;
}

.drop-hint {
  font-size: 12px;
  color: #94a3b8;
}

.selected-file-info {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.file-details {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-weight: 600;
  font-size: 14px;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  font-size: 12px;
  color: #64748b;
}

.btn-clear {
  background: none;
  border: none;
  color: #ef4444;
  font-size: 16px;
  cursor: pointer;
  padding: 4px;
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}

.form-control {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.form-control:focus {
  border-color: #3b82f6;
}

.checkbox-label {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.checkbox-label input {
  margin-top: 3px;
  width: 16px;
  height: 16px;
}

.checkbox-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  color: #1e293b;
}

.checkbox-text small {
  color: #64748b;
  font-size: 11px;
}

.btn {
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  transition: background 0.2s;
}

.btn-outline {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  text-decoration: none;
}

.btn-outline:hover {
  background: #f8fafc;
}

.btn-primary {
  background: #2563eb;
  color: #ffffff;
}

.btn-primary:hover {
  background: #1d4ed8;
}

.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.btn-block {
  width: 100%;
  justify-content: center;
}

.overview-banner {
  display: flex;
  gap: 16px;
  background: #f8fafc;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.metric-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 110px;
}

.metric-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #64748b;
}

.metric-value {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.metric-value.highlight {
  color: #2563eb;
}

.badge {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}

.badge-success { background: #dcfce7; color: #166534; }
.badge-warning { background: #fef9c3; color: #854d0e; }
.badge-danger { background: #fee2e2; color: #991b1b; }
.badge-info { background: #e0f2fe; color: #075985; }
.badge-secondary { background: #f1f5f9; color: #475569; }

.ocr-notice {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 16px;
}

.tab-header {
  display: flex;
  gap: 8px;
  border-bottom: 2px solid #e2e8f0;
  margin-bottom: 16px;
  overflow-x: auto;
}

.tab-btn {
  background: none;
  border: none;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  white-space: nowrap;
}

.tab-btn.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
}

.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.btn-copy {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.btn-copy:hover {
  background: #e2e8f0;
}

.code-box {
  background: #0f172a;
  color: #f8fafc;
  padding: 16px;
  border-radius: 8px;
  font-family: monospace;
  font-size: 13px;
  max-height: 450px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.table-wrapper {
  overflow-x: auto;
  max-height: 450px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th, .data-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.data-table th {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  position: sticky;
  top: 0;
}

.font-mono {
  font-family: monospace;
}

.table-footer-hint {
  padding: 8px 12px;
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  text-align: center;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

.empty-state h3 {
  margin: 12px 0 6px 0;
  color: #334155;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

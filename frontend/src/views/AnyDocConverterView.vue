<script setup>
import { ref, computed, onMounted } from 'vue'
import { anydocService } from '../services/anydocService'
import { API_BASE_URL } from '../utils'

// Input states
const uploadMode = ref('file') // 'file', 'url', 'batch'
const selectedFile = ref(null)
const batchFiles = ref([])
const documentUrl = ref('')
const autoOcr = ref(true)
const forceOcr = ref(false)
const formatOverride = ref('')

// Execution states
const isProcessing = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const copiedType = ref('')

// Result states
const resultData = ref(null)
const batchResults = ref(null)
const activeTab = ref('rendered') // 'rendered', 'markdown', 'metrics', 'api_code', 'raw_json'
const apiLanguage = ref('curl') // 'curl', 'python', 'js', 'axios', 'php'

// Supported formats info
const supportedFormats = ref([])
const enginesInfo = ref([])

const isDragging = ref(false)

const resolveStorageUrl = (storage) => {
  if (!storage) return '#'
  if (storage.local_url && storage.local_url.startsWith('/api/v1/uploads/')) return storage.local_url
  const raw = storage.s3_url || ''
  if (!raw) return '#'
  if (raw.startsWith('/api/v1/uploads/')) return raw
  const filename = decodeURIComponent(raw.split('?')[0].split('/').pop() || '')
  return `/api/v1/uploads/${encodeURIComponent(filename)}`
}

onMounted(async () => {
  try {
    const res = await anydocService.getSupportedFormats()
    if (res?.data) {
      supportedFormats.value = res.data.all_supported || []
      enginesInfo.value = res.data.engines || []
    }
  } catch (err) {
    console.warn('Could not fetch supported formats:', err)
  }
})

// File handling
const onFileSelect = (event) => {
  const file = event.target.files?.[0]
  if (file) {
    selectedFile.value = file
    errorMessage.value = ''
    successMessage.value = ''
  }
}

const onBatchSelect = (event) => {
  const files = Array.from(event.target.files || [])
  if (files.length > 0) {
    batchFiles.value = files
    errorMessage.value = ''
    successMessage.value = ''
  }
}

const onDropFile = (event) => {
  isDragging.value = false
  const files = Array.from(event.dataTransfer.files || [])
  if (files.length === 1 && uploadMode.value !== 'batch') {
    selectedFile.value = files[0]
    errorMessage.value = ''
    successMessage.value = ''
  } else if (files.length > 0) {
    uploadMode.value = 'batch'
    batchFiles.value = files
    errorMessage.value = ''
    successMessage.value = ''
  }
}

const clearAll = () => {
  selectedFile.value = null
  batchFiles.value = []
  documentUrl.value = ''
  resultData.value = null
  batchResults.value = null
  errorMessage.value = ''
  successMessage.value = ''
}

// Action Trigger
const convertDocument = async () => {
  if (uploadMode.value === 'file' && !selectedFile.value) {
    errorMessage.value = 'Please select or drop a document file first.'
    return
  }
  if (uploadMode.value === 'url' && !documentUrl.value) {
    errorMessage.value = 'Please enter a valid document URL.'
    return
  }
  if (uploadMode.value === 'batch' && (!batchFiles.value || batchFiles.value.length === 0)) {
    errorMessage.value = 'Please select files for batch conversion.'
    return
  }

  isProcessing.value = true
  errorMessage.value = ''
  successMessage.value = ''
  resultData.value = null
  batchResults.value = null

  try {
    if (uploadMode.value === 'file') {
      const res = await anydocService.convert(selectedFile.value, {
        autoOcr: autoOcr.value,
        forceOcr: forceOcr.value,
        formatOverride: formatOverride.value
      })
      resultData.value = res
      successMessage.value = `Successfully converted "${res.filename}" to Markdown in ${res.metrics?.processing_time_ms} ms!`
    } else if (uploadMode.value === 'url') {
      const res = await anydocService.convertUrl({
        url: documentUrl.value,
        autoOcr: autoOcr.value,
        forceOcr: forceOcr.value,
        formatOverride: formatOverride.value
      })
      resultData.value = res
      successMessage.value = `Successfully downloaded & converted "${res.filename}" in ${res.metrics?.processing_time_ms} ms!`
    } else if (uploadMode.value === 'batch') {
      const res = await anydocService.batchConvert(batchFiles.value, {
        autoOcr: autoOcr.value
      })
      batchResults.value = res
      successMessage.value = `Batch conversion completed! ${res.successful_conversions}/${res.total_files} documents converted in ${res.total_processing_time_ms} ms.`
    }
  } catch (err) {
    errorMessage.value = err.message || 'Error occurred during document conversion.'
  } finally {
    isProcessing.value = false
  }
}

// Download markdown file
const downloadMarkdown = (content, filename = 'document.md') => {
  if (!content) return
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.md') ? filename : `${filename}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// Copy helper
const copyToClipboard = async (text, type = 'general') => {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copiedType.value = type
    setTimeout(() => {
      if (copiedType.value === type) copiedType.value = ''
    }, 2000)
  } catch (e) {
    console.error('Failed to copy', e)
  }
}

// Format bytes
const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// Simple client-side Markdown to HTML renderer for clean preview
const renderMarkdownToHtml = (md) => {
  if (!md) return ''
  let html = md
    // Escape HTML tags slightly
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks (```lang ... ```)
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre class="md-code-block"><div class="md-code-lang">${lang || 'code'}</div><code>${code.trim()}</code></pre>`
  })

  // Inline code (`...`)
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')

  // Tables
  const lines = html.split('\n')
  const newLines = []
  let inTable = false
  let tableHeaderParsed = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (line.startsWith('|') && line.endsWith('|')) {
      const cells = line.split('|').slice(1, -1).map(c => c.trim())
      // Check if it's separator line (e.g. |---|---|)
      if (cells.every(c => /^:?-+:?$/.test(c))) {
        continue
      }
      if (!inTable) {
        inTable = true
        tableHeaderParsed = true
        newLines.push('<div class="md-table-wrap"><table class="md-table"><thead><tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>')
      } else {
        newLines.push('<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>')
      }
    } else {
      if (inTable) {
        newLines.push('</tbody></table></div>')
        inTable = false
        tableHeaderParsed = false
      }
      newLines.push(lines[i])
    }
  }
  if (inTable) {
    newLines.push('</tbody></table></div>')
  }
  html = newLines.join('\n')

  // Headings
  html = html.replace(/^### (.*$)/gim, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^## (.*$)/gim, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^# (.*$)/gim, '<h1 class="md-h1">$1</h1>')

  // Bold & Italic
  html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')

  // Blockquotes
  html = html.replace(/^\> (.*$)/gim, '<blockquote class="md-blockquote">$1</blockquote>')

  // Unordered list
  html = html.replace(/^\s*[\-\*]\s+(.*$)/gim, '<li class="md-li">$1</li>')
  html = html.replace(/(<li class="md-li">[\s\S]*?<\/li>)/g, '<ul class="md-ul">$1</ul>')
  // Clean duplicate consecutive ULs
  html = html.replace(/<\/ul>\s*<ul class="md-ul">/g, '')

  // Line breaks in paragraphs
  html = html.replace(/\n\n/g, '<p class="md-p"></p>')

  return html
}

const renderedHtml = computed(() => {
  if (!resultData.value?.markdown) return ''
  return renderMarkdownToHtml(resultData.value.markdown)
})

// Dynamic API Snippets
const apiToken = computed(() => localStorage.getItem('rarayvision-token') || 'YOUR_API_TOKEN_HERE')

const snippetFilename = computed(() => selectedFile.value?.name || 'document.docx')

const curlCode = computed(() => {
  return `# Convert any Office Doc, PDF, or Image to Markdown
curl -X POST "${API_BASE_URL}/api/v1/anydoc/convert" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -F "file=@${snippetFilename.value}" \\
  -F "auto_ocr=${autoOcr.value ? 'true' : 'false'}" \\
  -F "force_ocr=${forceOcr.value ? 'true' : 'false'}"`
})

const pythonCode = computed(() => {
  return `import requests

url = "${API_BASE_URL}/api/v1/anydoc/convert"
headers = {
    "Authorization": "Bearer ${apiToken.value}"
}
files = {
    "file": open("${snippetFilename.value}", "rb")
}
data = {
    "auto_ocr": "${autoOcr.value ? 'true' : 'false'}",
    "force_ocr": "${forceOcr.value ? 'true' : 'false'}"
}

response = requests.post(url, headers=headers, files=files, data=data)
result = response.json()

print(f"Format: {result['format']} | Engine: {result['engine']}")
print(f"S3 Stored URL: {result['storage']['s3_url']}")
print(f"Processing Time: {result['metrics']['processing_time_ms']} ms")
print("\\n--- Markdown Output ---\\n")
print(result['markdown'])`
})

const jsCode = computed(() => {
  return `// Native Fetch API (Browser or Node 18+)
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("auto_ocr", "${autoOcr.value ? 'true' : 'false'}");

const response = await fetch("${API_BASE_URL}/api/v1/anydoc/convert", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ${apiToken.value}"
  },
  body: formData
});

const result = await response.json();
console.log("Markdown output:", result.markdown);
console.log("S3 Storage URL:", result.storage.s3_url);`
})

const axiosCode = computed(() => {
  return `// JavaScript with Axios
import axios from 'axios';
import fs from 'fs';
import FormData from 'form-data';

const form = new FormData();
form.append('file', fs.createReadStream('${snippetFilename.value}'));
form.append('auto_ocr', '${autoOcr.value ? 'true' : 'false'}');

const res = await axios.post('${API_BASE_URL}/api/v1/anydoc/convert', form, {
  headers: {
    ...form.getHeaders(),
    'Authorization': 'Bearer ${apiToken.value}'
  }
});

console.log(res.data.markdown);`
})

const phpCode = computed(() => {
  return `<?php
$ch = curl_init();
$file = new CURLFile('${snippetFilename.value}');

curl_setopt_array($ch, [
    CURLOPT_URL => '${API_BASE_URL}/api/v1/anydoc/convert',
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => ['Authorization: Bearer ${apiToken.value}'],
    CURLOPT_POSTFIELDS => [
        'file' => $file,
        'auto_ocr' => '${autoOcr.value ? 'true' : 'false'}'
    ]
]);

$response = curl_exec($ch);
curl_close($ch);

$data = json_decode($response, true);
echo "S3 URL: " . $data['storage']['s3_url'] . "\\n";
echo "Markdown:\\n" . $data['markdown'];
?>`
})
</script>

<template>
  <div class="anydoc-container">
    <!-- Header Section -->
    <div class="page-header">
      <div class="header-left">
        <div class="title-with-badge">
          <h1 class="page-title">
            <svg viewBox="0 0 24 24" width="28" height="28" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="header-svg">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            AnyDoc Document-to-Markdown Converter
          </h1>
          <span class="engine-pill">Rust AnyDoc + Hybrid RapidOCR + S3</span>
        </div>
        <p class="page-subtitle">
          Konversi berbagai format dokumen (Word <code>.docx</code>, Excel <code>.xlsx</code>, PowerPoint <code>.pptx</code>, <code>.pdf</code>, <code>.csv</code>, <code>.epub</code>, <code>.odt</code>, dan Gambar OCR) ke GitHub-Flavored Markdown dalam hitungan milidetik secara instan. File otomatis tersimpan ke Object Storage / S3.
        </p>
      </div>

      <div class="header-badges">
        <div class="stat-badge">
          <span class="stat-dot green"></span>
          <span class="stat-text">S3 Cloud Storage Enabled</span>
        </div>
        <div class="stat-badge">
          <span class="stat-dot blue"></span>
          <span class="stat-text">30+ Supported Formats</span>
        </div>
      </div>
    </div>

    <!-- Alert Notifications -->
    <div v-if="errorMessage" class="alert-box alert-error">
      <span class="alert-icon">⚠️</span>
      <span>{{ errorMessage }}</span>
    </div>
    <div v-if="successMessage" class="alert-box alert-success">
      <span class="alert-icon">✅</span>
      <span>{{ successMessage }}</span>
    </div>

    <!-- Main Workspace Grid -->
    <div class="converter-grid">
      <!-- Left Panel: Input & Options -->
      <div class="panel input-panel">
        <!-- Input Mode Switcher -->
        <div class="mode-tabs">
          <button 
            type="button" 
            :class="['mode-tab', { active: uploadMode === 'file' }]" 
            @click="uploadMode = 'file'"
          >
            📁 File Upload
          </button>
          <button 
            type="button" 
            :class="['mode-tab', { active: uploadMode === 'url' }]" 
            @click="uploadMode = 'url'"
          >
            🌐 Web URL
          </button>
          <button 
            type="button" 
            :class="['mode-tab', { active: uploadMode === 'batch' }]" 
            @click="uploadMode = 'batch'"
          >
            📦 Batch (Multi-File)
          </button>
        </div>

        <!-- Mode 1: Single File Upload -->
        <div v-if="uploadMode === 'file'" class="input-section">
          <div 
            :class="['drop-zone', { active: isDragging, 'has-file': selectedFile }]"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDropFile"
            @click="$refs.singleFileInput.click()"
          >
            <input 
              type="file" 
              ref="singleFileInput" 
              style="display: none" 
              @change="onFileSelect"
            />

            <div v-if="!selectedFile" class="drop-content">
              <div class="drop-icon-circle">
                <svg viewBox="0 0 24 24" width="32" height="32" stroke="#2563eb" stroke-width="1.8" fill="none">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
              </div>
              <h3 class="drop-title">Drop your document here or <span class="browse-link">browse</span></h3>
              <p class="drop-desc">Support: DOCX, XLSX, PPTX, PDF, CSV, EPUB, RTF, ODT, PNG, JPG, etc.</p>
            </div>

            <div v-else class="file-chosen-box" @click.stop>
              <div class="file-type-icon">
                {{ selectedFile.name.split('.').pop().toUpperCase() }}
              </div>
              <div class="file-details">
                <span class="file-name" :title="selectedFile.name">{{ selectedFile.name }}</span>
                <span class="file-meta">{{ formatBytes(selectedFile.size) }}</span>
              </div>
              <button type="button" class="btn-remove" @click.stop="selectedFile = null" title="Remove file">✕</button>
            </div>
          </div>
        </div>

        <!-- Mode 2: Remote URL -->
        <div v-else-if="uploadMode === 'url'" class="input-section">
          <div class="form-group">
            <label class="form-label">Document Public URL:</label>
            <input 
              type="url" 
              v-model="documentUrl" 
              placeholder="https://example.com/document.docx or .pdf" 
              class="form-input"
            />
            <p class="form-hint">AnyDoc will fetch the document directly and stream into the Markdown parser.</p>
          </div>
        </div>

        <!-- Mode 3: Batch Multi-File -->
        <div v-else-if="uploadMode === 'batch'" class="input-section">
          <div 
            :class="['drop-zone batch-drop', { active: isDragging }]"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDropFile"
            @click="$refs.batchFileInput.click()"
          >
            <input 
              type="file" 
              multiple 
              ref="batchFileInput" 
              style="display: none" 
              @change="onBatchSelect"
            />
            <div class="drop-content">
              <svg viewBox="0 0 24 24" width="32" height="32" stroke="#2563eb" stroke-width="1.8" fill="none">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
              <h3 class="drop-title">Select multiple files for batch conversion</h3>
              <p class="drop-desc">All files will be converted and saved to S3 in parallel.</p>
            </div>
          </div>

          <!-- Batch Files List -->
          <div v-if="batchFiles.length > 0" class="batch-list">
            <div class="batch-list-header">
              <span>Selected Files ({{ batchFiles.length }})</span>
              <button type="button" class="btn-link-danger" @click="batchFiles = []">Clear all</button>
            </div>
            <div class="batch-scroll">
              <div v-for="(f, idx) in batchFiles" :key="idx" class="batch-item">
                <span class="badge-ext">{{ f.name.split('.').pop().toUpperCase() }}</span>
                <span class="batch-name">{{ f.name }}</span>
                <span class="batch-size">{{ formatBytes(f.size) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Options Card -->
        <div class="options-box">
          <h4 class="options-title">Engine & Parser Settings</h4>
          
          <label class="checkbox-label">
            <input type="checkbox" v-model="autoOcr" />
            <div class="checkbox-text">
              <span class="checkbox-title">Auto OCR Fallback (RapidOCR)</span>
              <span class="checkbox-desc">Automatically trigger RapidOCR for scanned PDF pages and images.</span>
            </div>
          </label>

          <label class="checkbox-label">
            <input type="checkbox" v-model="forceOcr" />
            <div class="checkbox-text">
              <span class="checkbox-title">Force Full OCR Layout</span>
              <span class="checkbox-desc">Run full vision layout OCR across all document pages.</span>
            </div>
          </label>

          <div class="form-group" style="margin-top: 10px;">
            <label class="form-label">Explicit Format Override (Optional):</label>
            <input 
              type="text" 
              v-model="formatOverride" 
              placeholder="e.g. docx, csv, xlsx, pdf" 
              class="form-input form-input-sm"
            />
          </div>
        </div>

        <!-- Action Button -->
        <div class="action-btn-row">
          <button 
            type="button" 
            class="btn-convert" 
            :disabled="isProcessing || (uploadMode === 'file' && !selectedFile) || (uploadMode === 'url' && !documentUrl) || (uploadMode === 'batch' && batchFiles.length === 0)"
            @click="convertDocument"
          >
            <svg v-if="isProcessing" class="spinner-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
            <span v-if="isProcessing">Converting Document...</span>
            <span v-else>⚡ Convert to Markdown</span>
          </button>

          <button type="button" class="btn-clear" @click="clearAll" title="Clear inputs and results">Reset</button>
        </div>

        <!-- Supported Formats Catalog Preview -->
        <div class="supported-formats-footer">
          <div class="formats-title">⚡ Supported Extensions:</div>
          <div class="format-tags">
            <span class="tag">DOCX</span>
            <span class="tag">XLSX</span>
            <span class="tag">PPTX</span>
            <span class="tag">PDF</span>
            <span class="tag">CSV</span>
            <span class="tag">ODT</span>
            <span class="tag">EPUB</span>
            <span class="tag">RTF</span>
            <span class="tag">PNG/JPG (OCR)</span>
          </div>
        </div>
      </div>

      <!-- Right Panel: Conversion Results & Preview -->
      <div class="panel result-panel">
        <!-- Single Result View -->
        <div v-if="resultData" class="result-wrapper">
          <!-- Result Overview Bar -->
          <div class="result-metrics-bar">
            <div class="metric-item">
              <span class="metric-lbl">Format</span>
              <span class="badge badge-format">{{ resultData.format?.toUpperCase() }}</span>
            </div>

            <div class="metric-item">
              <span class="metric-lbl">Engine</span>
              <span class="badge badge-engine">{{ resultData.engine }}</span>
            </div>

            <div class="metric-item">
              <span class="metric-lbl">Processing Time</span>
              <span class="metric-val highlight">{{ resultData.metrics?.processing_time_ms }} ms</span>
            </div>

            <div class="metric-item">
              <span class="metric-lbl">Characters / Words</span>
              <span class="metric-val">{{ resultData.metrics?.characters?.toLocaleString() }} / {{ resultData.metrics?.words?.toLocaleString() }}</span>
            </div>

            <div class="metric-item" v-if="resultData.storage?.s3_url || resultData.storage?.local_url">
              <span class="metric-lbl">File Storage</span>
              <a :href="resolveStorageUrl(resultData.storage)" target="_blank" rel="noopener" class="s3-link" title="Open file">
                <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                Buka File
              </a>
            </div>
          </div>

          <!-- Tabs Header -->
          <div class="result-tab-bar">
            <div class="tab-buttons">
              <button :class="['tab-btn', { active: activeTab === 'rendered' }]" @click="activeTab = 'rendered'">
                👁️ Rendered Preview
              </button>
              <button :class="['tab-btn', { active: activeTab === 'markdown' }]" @click="activeTab = 'markdown'">
                📝 Raw Markdown (.md)
              </button>
              <button :class="['tab-btn', { active: activeTab === 'api_code' }]" @click="activeTab = 'api_code'">
                ⚡ API Code Snippets
              </button>
              <button :class="['tab-btn', { active: activeTab === 'raw_json' }]" @click="activeTab = 'raw_json'">
                🔍 JSON Response
              </button>
            </div>

            <div class="tab-actions">
              <button 
                type="button" 
                class="btn-action" 
                @click="copyToClipboard(resultData.markdown, 'markdown')"
              >
                {{ copiedType === 'markdown' ? '✅ Copied!' : '📋 Copy Markdown' }}
              </button>
              <button 
                type="button" 
                class="btn-action primary" 
                @click="downloadMarkdown(resultData.markdown, resultData.filename)"
              >
                ⬇️ Download .md
              </button>
            </div>
          </div>

          <!-- Tab 1: Rendered HTML/Markdown -->
          <div v-if="activeTab === 'rendered'" class="tab-pane rendered-pane">
            <div class="markdown-body" v-html="renderedHtml"></div>
          </div>

          <!-- Tab 2: Raw Markdown Source -->
          <div v-else-if="activeTab === 'markdown'" class="tab-pane">
            <pre class="code-viewer">{{ resultData.markdown || 'No Markdown output.' }}</pre>
          </div>

          <!-- Tab 3: API Code Integration -->
          <div v-else-if="activeTab === 'api_code'" class="tab-pane api-code-pane">
            <div class="api-lang-selector">
              <button :class="['lang-btn', { active: apiLanguage === 'curl' }]" @click="apiLanguage = 'curl'">cURL</button>
              <button :class="['lang-btn', { active: apiLanguage === 'python' }]" @click="apiLanguage = 'python'">Python (requests)</button>
              <button :class="['lang-btn', { active: apiLanguage === 'js' }]" @click="apiLanguage = 'js'">JavaScript (Fetch)</button>
              <button :class="['lang-btn', { active: apiLanguage === 'axios' }]" @click="apiLanguage = 'axios'">Node.js / Axios</button>
              <button :class="['lang-btn', { active: apiLanguage === 'php' }]" @click="apiLanguage = 'php'">PHP</button>
            </div>

            <div class="snippet-box">
              <div class="snippet-header">
                <span>Code for your other pages / backend services</span>
                <button 
                  class="btn-copy-small" 
                  @click="copyToClipboard(
                    apiLanguage === 'curl' ? curlCode : 
                    apiLanguage === 'python' ? pythonCode : 
                    apiLanguage === 'js' ? jsCode : 
                    apiLanguage === 'axios' ? axiosCode : phpCode, 
                    'api'
                  )"
                >
                  {{ copiedType === 'api' ? '✅ Copied!' : '📋 Copy Code' }}
                </button>
              </div>
              <pre class="code-viewer" v-if="apiLanguage === 'curl'">{{ curlCode }}</pre>
              <pre class="code-viewer" v-else-if="apiLanguage === 'python'">{{ pythonCode }}</pre>
              <pre class="code-viewer" v-else-if="apiLanguage === 'js'">{{ jsCode }}</pre>
              <pre class="code-viewer" v-else-if="apiLanguage === 'axios'">{{ axiosCode }}</pre>
              <pre class="code-viewer" v-else-if="apiLanguage === 'php'">{{ phpCode }}</pre>
            </div>
          </div>

          <!-- Tab 4: Raw JSON -->
          <div v-else-if="activeTab === 'raw_json'" class="tab-pane">
            <pre class="code-viewer">{{ JSON.stringify(resultData, null, 2) }}</pre>
          </div>
        </div>

        <!-- Batch Results View -->
        <div v-else-if="batchResults" class="result-wrapper">
          <div class="batch-summary-header">
            <h3>Batch Conversion Results</h3>
            <span class="badge badge-success">
              {{ batchResults.successful_conversions }} / {{ batchResults.total_files }} Converted
            </span>
          </div>

          <div class="batch-table-wrap">
            <table class="batch-table">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Format</th>
                  <th>Engine</th>
                  <th>Time</th>
                  <th>Characters</th>
                  <th>S3 Storage</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in batchResults.results" :key="idx">
                  <td><strong>{{ item.filename }}</strong></td>
                  <td><span class="badge badge-format">{{ item.format?.toUpperCase() || '-' }}</span></td>
                  <td><span class="badge badge-engine">{{ item.engine || '-' }}</span></td>
                  <td>{{ item.metrics?.processing_time_ms ? `${item.metrics.processing_time_ms} ms` : '-' }}</td>
                  <td>{{ item.metrics?.characters?.toLocaleString() || '-' }}</td>
                  <td>
                    <a v-if="item.storage?.s3_url || item.storage?.local_url" :href="resolveStorageUrl(item.storage)" target="_blank" class="s3-link">Buka File</a>
                    <span v-else>-</span>
                  </td>
                  <td>
                    <button 
                      v-if="item.markdown" 
                      class="btn-table-action" 
                      @click="downloadMarkdown(item.markdown, item.filename)"
                      title="Download .md"
                    >
                      ⬇️ .md
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Empty State -->
        <div v-else class="empty-state">
          <div class="empty-icon-box">
            <svg viewBox="0 0 24 24" width="56" height="56" stroke="#94a3b8" stroke-width="1.2" fill="none">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
          </div>
          <h3 class="empty-title">Ready for Any Document</h3>
          <p class="empty-desc">
            Upload any Word (.docx), Excel (.xlsx), PowerPoint (.pptx), PDF, CSV, EPUB, or Image file on the left panel to convert it into clean GitHub-Flavored Markdown.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.anydoc-container {
  padding: 24px 32px;
  max-width: 1600px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 20px;
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-svg {
  color: #2563eb;
}

.engine-pill {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 9999px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.page-subtitle {
  color: #475569;
  font-size: 13.5px;
  margin: 6px 0 0;
  max-width: 900px;
  line-height: 1.5;
}

.page-subtitle code {
  background: #f1f5f9;
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 12px;
  color: #0f172a;
  font-family: monospace;
}

.header-badges {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.stat-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.stat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.stat-dot.green { background: #10b981; }
.stat-dot.blue { background: #3b82f6; }

/* Alerts */
.alert-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 20px;
}

.alert-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.alert-success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
}

/* Grid Layout */
.converter-grid {
  display: grid;
  grid-template-columns: 430px 1fr;
  gap: 24px;
  align-items: start;
}

@media (max-width: 1100px) {
  .converter-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

/* Left Panel Modes */
.mode-tabs {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 8px;
  margin-bottom: 16px;
  gap: 3px;
}

.mode-tab {
  flex: 1;
  padding: 7px 10px;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 600;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.mode-tab.active {
  background: #ffffff;
  color: #2563eb;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Drop Zone */
.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #f8fafc;
}

.drop-zone:hover, .drop-zone.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.drop-zone.has-file {
  border-color: #93c5fd;
  background: #f0fdf4;
  padding: 16px;
}

.drop-icon-circle {
  width: 52px;
  height: 52px;
  background: #eff6ff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
}

.drop-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 4px;
}

.browse-link {
  color: #2563eb;
  text-decoration: underline;
}

.drop-desc {
  font-size: 11.5px;
  color: #64748b;
  margin: 0;
}

.file-chosen-box {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.file-type-icon {
  background: #2563eb;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  padding: 8px 10px;
  border-radius: 8px;
  letter-spacing: 0.5px;
}

.file-details {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.file-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}

.file-meta {
  font-size: 11px;
  color: #64748b;
}

.btn-remove {
  background: #fee2e2;
  border: none;
  color: #ef4444;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
}

/* Forms */
.form-group {
  margin-bottom: 12px;
}

.form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 5px;
}

.form-input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37,99,235,0.15);
}

.form-input-sm {
  padding: 6px 10px;
  font-size: 12px;
}

.form-hint {
  font-size: 11px;
  color: #64748b;
  margin: 4px 0 0;
}

/* Batch List */
.batch-list {
  margin-top: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.batch-list-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 8px;
}

.btn-link-danger {
  background: none;
  border: none;
  color: #ef4444;
  font-size: 11px;
  cursor: pointer;
}

.batch-scroll {
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.batch-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  padding: 4px 6px;
  background: #f8fafc;
  border-radius: 4px;
}

.badge-ext {
  background: #e2e8f0;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
}

.batch-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-size {
  color: #64748b;
  font-size: 10.5px;
}

/* Options Box */
.options-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px;
  margin-top: 16px;
}

.options-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: #475569;
  letter-spacing: 0.5px;
  margin: 0 0 10px;
}

.checkbox-label {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  margin-bottom: 10px;
}

.checkbox-label input {
  margin-top: 3px;
}

.checkbox-text {
  display: flex;
  flex-direction: column;
}

.checkbox-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #1e293b;
}

.checkbox-desc {
  font-size: 11px;
  color: #64748b;
}

/* Action Buttons */
.action-btn-row {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

.btn-convert {
  flex: 1;
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 11px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.15s;
}

.btn-convert:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-convert:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-clear {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 11px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-clear:hover {
  background: #e2e8f0;
}

.spinner-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}

/* Supported Formats Footer */
.supported-formats-footer {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.formats-title {
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 6px;
}

.format-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tag {
  background: #f1f5f9;
  color: #475569;
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Right Panel: Results */
.result-panel {
  min-height: 580px;
  display: flex;
  flex-direction: column;
}

.result-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.result-metrics-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 14px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-lbl {
  font-size: 10.5px;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.metric-val {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.metric-val.highlight {
  color: #2563eb;
}

.badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-block;
}

.badge-format {
  background: #dbeafe;
  color: #1e40af;
}

.badge-engine {
  background: #fef3c7;
  color: #92400e;
}

.badge-success {
  background: #dcfce7;
  color: #166534;
}

.s3-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}

.s3-link:hover {
  text-decoration: underline;
}

/* Result Tab Bar */
.result-tab-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}

.tab-buttons {
  display: flex;
  gap: 6px;
}

.tab-btn {
  background: none;
  border: none;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn:hover {
  color: #0f172a;
}

.tab-btn.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 700;
}

.tab-actions {
  display: flex;
  gap: 8px;
}

.btn-action {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.btn-action:hover {
  background: #e2e8f0;
}

.btn-action.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

.btn-action.primary:hover {
  background: #1d4ed8;
}

/* Tab Panes */
.tab-pane {
  flex: 1;
  overflow: auto;
}

.rendered-pane {
  background: #ffffff;
  padding: 16px;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  max-height: 600px;
  overflow-y: auto;
}

.code-viewer {
  background: #0f172a;
  color: #f8fafc;
  padding: 16px;
  border-radius: 8px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  max-height: 600px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

/* API Code Snippets */
.api-lang-selector {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.lang-btn {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.lang-btn.active {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
}

.snippet-box {
  border-radius: 8px;
  overflow: hidden;
}

.snippet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #1e293b;
  color: #94a3b8;
  padding: 8px 14px;
  font-size: 11.5px;
}

.btn-copy-small {
  background: #334155;
  color: #f8fafc;
  border: none;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}

.btn-copy-small:hover {
  background: #475569;
}

/* Batch Results Table */
.batch-summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.batch-table-wrap {
  overflow-x: auto;
}

.batch-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.batch-table th, .batch-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.batch-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
}

.btn-table-action {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  flex: 1;
}

.empty-icon-box {
  width: 80px;
  height: 80px;
  background: #f1f5f9;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 6px;
}

.empty-desc {
  font-size: 13px;
  color: #64748b;
  max-width: 480px;
  line-height: 1.5;
  margin: 0;
}

/* Rendered Markdown Styling */
:deep(.markdown-body) {
  font-size: 13.5px;
  color: #1e293b;
  line-height: 1.7;
}

:deep(.md-h1) {
  font-size: 20px;
  font-weight: 800;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 6px;
  margin: 16px 0 10px;
  color: #0f172a;
}

:deep(.md-h2) {
  font-size: 16.5px;
  font-weight: 700;
  margin: 14px 0 8px;
  color: #1e293b;
}

:deep(.md-h3) {
  font-size: 14.5px;
  font-weight: 600;
  margin: 12px 0 6px;
  color: #334155;
}

:deep(.md-p) {
  margin: 8px 0;
}

:deep(.md-blockquote) {
  border-left: 4px solid #3b82f6;
  background: #eff6ff;
  padding: 8px 14px;
  margin: 10px 0;
  color: #1e40af;
  border-radius: 0 6px 6px 0;
}

:deep(.md-inline-code) {
  background: #f1f5f9;
  color: #ef4444;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
}

:deep(.md-code-block) {
  background: #0f172a;
  color: #f8fafc;
  padding: 12px 16px;
  border-radius: 8px;
  font-family: monospace;
  font-size: 12px;
  position: relative;
  margin: 12px 0;
  overflow-x: auto;
}

:deep(.md-code-lang) {
  position: absolute;
  top: 4px;
  right: 8px;
  font-size: 10px;
  color: #64748b;
  text-transform: uppercase;
}

:deep(.md-table-wrap) {
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

:deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

:deep(.md-table th) {
  background: #f8fafc;
  padding: 8px 12px;
  border-bottom: 2px solid #cbd5e1;
  font-weight: 700;
  color: #0f172a;
  text-align: left;
}

:deep(.md-table td) {
  padding: 8px 12px;
  border-bottom: 1px solid #e2e8f0;
  color: #334155;
}

:deep(.md-ul) {
  padding-left: 20px;
  margin: 8px 0;
}

:deep(.md-li) {
  margin: 4px 0;
}
</style>

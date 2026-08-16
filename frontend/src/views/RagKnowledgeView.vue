<script setup>
import { ref, computed, onMounted } from 'vue'
import { ragService } from '../services/ragService'
import { API_BASE_URL } from '../utils'

// Active View Tab
const mainTab = ref('library') // 'library', 'ingest', 'chat', 'integration'

// Knowledge Library State
const documents = ref([])
const totalDocuments = ref(0)
const totalChunks = ref(0)
const isLoadingLibrary = ref(false)
const searchQuery = ref('')
const selectedDocForChunks = ref(null)
const docChunks = ref([])
const isLoadingChunks = ref(false)
const showChunksModal = ref(false)

// Ingest State
const ingestFile = ref(null)
const autoOcr = ref(true)
const forceOcr = ref(false)
const isIngesting = ref(false)
const ingestSuccess = ref('')
const ingestError = ref('')
const isDragging = ref(false)

// Chatbot Playground State
const chatMessages = ref([
  {
    role: 'assistant',
    content: 'Halo! Saya adalah AI Chatbot RAG terhubung ke basis pengetahuan Anda. Tanyakan apa saja mengenai dokumen yang telah Anda upload.',
    sources: []
  }
])
const userPrompt = ref('')
const isGenerating = ref(false)
const chatTopK = ref(4)
const selectedDocFilter = ref('')

// Integration Tab
const apiLanguage = ref('nextjs') // 'nextjs', 'nextjs_upload', 'curl', 'python'
const copiedType = ref('')

// Engine Info
const ragInfo = ref(null)

onMounted(async () => {
  await fetchLibrary()
  try {
    const res = await ragService.getInfo()
    if (res?.data) ragInfo.value = res.data
  } catch (err) {
    console.warn('Could not fetch RAG info:', err)
  }
})

const fetchLibrary = async () => {
  isLoadingLibrary.value = true
  try {
    const res = await ragService.getDocuments(0, 100)
    if (res?.status === 'success') {
      documents.value = res.documents || []
      totalDocuments.value = res.total_documents || 0
      totalChunks.value = res.total_chunks || 0
    }
  } catch (err) {
    console.error('Failed to fetch documents:', err)
  } finally {
    isLoadingLibrary.value = false
  }
}

const filteredDocuments = computed(() => {
  if (!searchQuery.value.trim()) return documents.value
  const q = searchQuery.value.toLowerCase()
  return documents.value.filter(d => d.filename?.toLowerCase().includes(q) || d.format?.toLowerCase().includes(q))
})

// File Ingest handlers
const onFileSelect = (e) => {
  const file = e.target.files?.[0]
  if (file) {
    ingestFile.value = file
    ingestError.value = ''
    ingestSuccess.value = ''
  }
}

const onDropFile = (e) => {
  isDragging.value = false
  const file = e.dataTransfer.files?.[0]
  if (file) {
    ingestFile.value = file
    ingestError.value = ''
    ingestSuccess.value = ''
  }
}

const handleIngest = async () => {
  if (!ingestFile.value) {
    ingestError.value = 'Silakan pilih file dokumen terlebih dahulu.'
    return
  }

  isIngesting.value = true
  ingestError.value = ''
  ingestSuccess.value = ''

  try {
    const res = await ragService.ingest(ingestFile.value, {
      autoOcr: autoOcr.value,
      forceOcr: forceOcr.value
    })
    ingestSuccess.value = `Berhasil! Dokumen "${res.filename}" telah diubah ke Markdown, disimpan di S3, dan diindeks menjadi ${res.total_chunks} vektor dalam ${res.processing_time_ms} ms.`
    ingestFile.value = null
    await fetchLibrary()
  } catch (err) {
    ingestError.value = err.message || 'Gagal mengindeks dokumen ke basis pengetahuan.'
  } finally {
    isIngesting.value = false
  }
}

// Inspect chunks modal
const openChunksModal = async (doc) => {
  selectedDocForChunks.value = doc
  showChunksModal.value = true
  isLoadingChunks.value = true
  try {
    const res = await ragService.getDocumentChunks(doc.id)
    if (res?.chunks) {
      docChunks.value = res.chunks
    }
  } catch (err) {
    console.error('Error fetching chunks:', err)
  } finally {
    isLoadingChunks.value = false
  }
}

// Delete document
const handleDeleteDocument = async (doc) => {
  if (!confirm(`Hapus dokumen "${doc.filename}" dan seluruh vektornya dari basis pengetahuan?`)) {
    return
  }
  try {
    await ragService.deleteDocument(doc.id)
    await fetchLibrary()
  } catch (err) {
    alert('Gagal menghapus dokumen: ' + err.message)
  }
}

// Chatbot Send
const handleSendMessage = async () => {
  const q = userPrompt.value.trim()
  if (!q || isGenerating.value) return

  userPrompt.value = ''
  chatMessages.value.push({
    role: 'user',
    content: q,
    sources: []
  })

  isGenerating.value = true

  try {
    const res = await ragService.chat({
      query: q,
      topK: chatTopK.value,
      documentId: selectedDocFilter.value || null
    })

    if (res?.data) {
      chatMessages.value.push({
        role: 'assistant',
        content: res.data.answer || 'Tidak ada jawaban.',
        sources: res.data.sources || [],
        latency: res.data.latency_ms
      })
    }
  } catch (err) {
    chatMessages.value.push({
      role: 'assistant',
      content: `❌ Terjadi kesalahan: ${err.message}`,
      sources: []
    })
  } finally {
    isGenerating.value = false
  }
}

const formatMarkdown = (text) => {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre class="chat-code-block"><code>${code.trim()}</code></pre>`
  })

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>')

  // Headings
  html = html.replace(/^### (.*$)/gim, '<h4 class="chat-h4">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="chat-h3">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="chat-h2">$1</h2>')

  // Bold (***, **, *)
  html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')

  // Bullet points
  html = html.replace(/^\s*[\-\*]\s+(.*$)/gim, '<li class="chat-li">$1</li>')
  html = html.replace(/(<li class="chat-li">[\s\S]*?<\/li>)/g, '<ul class="chat-ul">$1</ul>')
  html = html.replace(/<\/ul>\s*<ul class="chat-ul">/g, '')

  // Line breaks
  html = html.replace(/\n\n/g, '<div class="chat-spacer"></div>')
  html = html.replace(/\n/g, '<br>')

  return html
}

const copyToClipboard = async (text, type = 'code') => {
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

const apiToken = computed(() => localStorage.getItem('rarayvision-token') || 'YOUR_RARAY_VISION_TOKEN')

// Next.js Route.ts Code Snippet
const nextjsChatCode = computed(() => {
  return `// app/api/chat/route.ts (Next.js App Router)
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { messages } = await req.json();
    const lastUserMessage = messages[messages.length - 1]?.content;

    if (!lastUserMessage) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    // 1. Panggil RAG API Raray Vision untuk mengambil context + jawaban LLM
    const ragResponse = await fetch("${API_BASE_URL}/api/v1/rag/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer \${process.env.RARAY_VISION_API_KEY}"
      },
      body: JSON.stringify({
        query: lastUserMessage,
        top_k: 4
      })
    });

    const data = await ragResponse.json();

    return NextResponse.json({
      role: "assistant",
      content: data.data.answer,
      sources: data.data.sources,
      latency_ms: data.data.latency_ms
    });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}`
})

const nextjsUploadCode = computed(() => {
  return `// app/actions/upload-knowledge.ts (Next.js Server Action)
"use server";

export async function uploadToKnowledgeBase(formData: FormData) {
  // formData berisi file dari input form <input type="file" name="file" />
  const res = await fetch("${API_BASE_URL}/api/v1/rag/ingest", {
    method: "POST",
    headers: {
      "Authorization": "Bearer \${process.env.RARAY_VISION_API_KEY}"
    },
    body: formData
  });

  const result = await res.json();
  return result; // mengembalikan document_id, total_chunks, s3_url, dll.
}`
})

const curlCode = computed(() => {
  return `# 1. Upload & Ingest Dokumen ke pgvector
curl -X POST "${API_BASE_URL}/api/v1/rag/ingest" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -F "file=@panduan.docx" \\
  -F "auto_ocr=true"

# 2. Semantic Search (Pencarian Vektor)
curl -X POST "${API_BASE_URL}/api/v1/rag/search" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "Berapa biaya produk X?", "top_k": 4}'

# 3. Chatbot Generation
curl -X POST "${API_BASE_URL}/api/v1/rag/chat" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "Jelaskan isi Bab 2 secara ringkas", "top_k": 4}'`
})

const pythonCode = computed(() => {
  return `import requests

API_URL = "${API_BASE_URL}/api/v1/rag"
HEADERS = {"Authorization": "Bearer ${apiToken.value}"}

# 1. Ingest Dokumen
with open("laporan.pdf", "rb") as f:
    res = requests.post(f"{API_URL}/ingest", headers=HEADERS, files={"file": f}, data={"auto_ocr": "true"}).json()
print("Ingested Doc:", res["filename"], "Total Chunks:", res["total_chunks"], "S3:", res["s3_url"])

# 2. Chatbot Query
chat_res = requests.post(f"{API_URL}/chat", headers=HEADERS, json={
    "query": "Apa kesimpulan utama dokumen ini?",
    "top_k": 4
}).json()

print("Jawaban:", chat_res["data"]["answer"])
print("Sumber:", [s["filename"] for s in chat_res["data"]["sources"]])`
})
</script>

<template>
  <div class="rag-container">
    <!-- Header -->
    <div class="rag-header">
      <div>
        <div class="title-row">
          <h1 class="page-title">
            <svg viewBox="0 0 24 24" width="28" height="28" stroke="currentColor" stroke-width="2" fill="none" class="title-icon">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
            </svg>
            RAG Knowledge Base & pgvector
          </h1>
          <span class="pill-badge">AnyDoc + pgvector + FastEmbed ONNX</span>
        </div>
        <p class="page-subtitle">
          Basis pengetahuan cerdas untuk Chatbot: Upload dokumen (Word, PDF, Excel, PPTX, CSV, Gambar OCR), konversi otomatis ke Markdown via AnyDoc, simpan ke S3, dan indeks vektor ke PostgreSQL untuk semantic retrieval real-time di Next.js.
        </p>
      </div>

      <!-- Stats Pill Bar -->
      <div class="header-stats">
        <div class="stat-card">
          <span class="stat-val">{{ totalDocuments }}</span>
          <span class="stat-lbl">Dokumen Ingested</span>
        </div>
        <div class="stat-card">
          <span class="stat-val">{{ totalChunks }}</span>
          <span class="stat-lbl">Vektor Chunks</span>
        </div>
        <div class="stat-card engine-stat">
          <span class="stat-val">384-D</span>
          <span class="stat-lbl">Free FastEmbed ONNX</span>
        </div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="rag-nav-tabs">
      <button :class="['tab-item', { active: mainTab === 'library' }]" @click="mainTab = 'library'">
        📚 Knowledge Library ({{ totalDocuments }})
      </button>
      <button :class="['tab-item', { active: mainTab === 'ingest' }]" @click="mainTab = 'ingest'">
        ⚡ Ingest & Upload File
      </button>
      <button :class="['tab-item', { active: mainTab === 'chat' }]" @click="mainTab = 'chat'">
        💬 RAG Chatbot Playground
      </button>
      <button :class="['tab-item', { active: mainTab === 'integration' }]" @click="mainTab = 'integration'">
        🔗 Next.js & API Integration
      </button>
    </div>

    <!-- Tab 1: Knowledge Library -->
    <div v-if="mainTab === 'library'" class="tab-content">
      <div class="library-toolbar">
        <div class="search-box">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="#94a3b8" stroke-width="2" fill="none"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <input type="text" v-model="searchQuery" placeholder="Cari nama dokumen atau format..." class="search-input" />
        </div>
        <div class="toolbar-actions">
          <button class="btn-refresh" @click="fetchLibrary" title="Refresh library">🔄 Refresh</button>
          <button class="btn-primary" @click="mainTab = 'ingest'">+ Upload Dokumen Baru</button>
        </div>
      </div>

      <div class="table-card">
        <div v-if="isLoadingLibrary" class="loading-state">
          <div class="spinner"></div>
          <span>Memuat dokumen basis pengetahuan...</span>
        </div>

        <div v-else-if="filteredDocuments.length === 0" class="empty-library">
          <svg viewBox="0 0 24 24" width="48" height="48" stroke="#cbd5e1" stroke-width="1.5" fill="none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
          <h3>Belum ada dokumen di basis pengetahuan</h3>
          <p>Unggah file dokumen pertama Anda untuk mulai mengisi knowledge base chatbot.</p>
          <button class="btn-primary" @click="mainTab = 'ingest'">Upload Sekarang</button>
        </div>

        <table v-else class="library-table">
          <thead>
            <tr>
              <th>Dokumen</th>
              <th>Format</th>
              <th>Total Chunks</th>
              <th>Karakter / Kata</th>
              <th>Penyimpanan S3</th>
              <th>Waktu Dibuat</th>
              <th>Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in filteredDocuments" :key="doc.id">
              <td>
                <div class="doc-title-cell">
                  <strong>{{ doc.filename }}</strong>
                  <span class="doc-id-sub">ID: {{ doc.id.substring(0, 8) }}...</span>
                </div>
              </td>
              <td>
                <span class="badge-format">{{ doc.format?.toUpperCase() }}</span>
              </td>
              <td>
                <span class="chunk-badge">{{ doc.total_chunks }} Chunks</span>
              </td>
              <td>
                {{ doc.char_count?.toLocaleString() }} / {{ doc.word_count?.toLocaleString() }}
              </td>
              <td>
                <a v-if="doc.s3_url" :href="doc.s3_url" target="_blank" rel="noopener" class="s3-btn" title="Buka file asli di S3">
                  <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                  S3 File
                </a>
                <span v-else>-</span>
              </td>
              <td class="time-cell">
                {{ doc.created_at ? new Date(doc.created_at).toLocaleString('id-ID') : '-' }}
              </td>
              <td>
                <div class="row-actions">
                  <button class="btn-inspect" @click="openChunksModal(doc)" title="Lihat potongan chunk & vektor">
                    🔍 Chunks
                  </button>
                  <button class="btn-delete" @click="handleDeleteDocument(doc)" title="Hapus dokumen">
                    🗑️
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 2: Ingest & Upload File -->
    <div v-else-if="mainTab === 'ingest'" class="tab-content">
      <div class="ingest-grid">
        <div class="ingest-panel card">
          <h2 class="section-title">Upload & Ingest Dokumen ke Vektor</h2>
          <p class="section-desc">
            File akan otomatis diubah ke format Markdown oleh AnyDoc, diunggah ke S3, dipotong secara semantik, dan di-vektorisasi ke basis data PostgreSQL.
          </p>

          <div v-if="ingestError" class="alert-box alert-error">❌ {{ ingestError }}</div>
          <div v-if="ingestSuccess" class="alert-box alert-success">✅ {{ ingestSuccess }}</div>

          <div 
            :class="['drop-box', { active: isDragging, 'has-file': ingestFile }]"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDropFile"
            @click="$refs.ingestFileInput.click()"
          >
            <input 
              type="file" 
              ref="ingestFileInput" 
              style="display: none" 
              @change="onFileSelect"
            />

            <div v-if="!ingestFile" class="drop-prompt">
              <div class="drop-circle">
                <svg viewBox="0 0 24 24" width="36" height="36" stroke="#2563eb" stroke-width="1.8" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
              </div>
              <h3>Pilih atau tarik dokumen ke sini</h3>
              <p>Mendukung: Word (.docx, .doc), Excel (.xlsx, .xls), PDF (.pdf), PowerPoint (.pptx), CSV, EPUB, RTF, Gambar OCR.</p>
            </div>

            <div v-else class="file-card" @click.stop>
              <div class="file-icon-box">{{ ingestFile.name.split('.').pop().toUpperCase() }}</div>
              <div class="file-meta-box">
                <span class="file-name">{{ ingestFile.name }}</span>
                <span class="file-size">{{ (ingestFile.size / 1024).toFixed(1) }} KB</span>
              </div>
              <button class="btn-close" @click.stop="ingestFile = null">✕</button>
            </div>
          </div>

          <div class="options-box">
            <label class="check-row">
              <input type="checkbox" v-model="autoOcr" />
              <div>
                <strong>Auto OCR Fallback (RapidOCR)</strong>
                <p>Otomatis mengekstrak teks & tabel pada halaman PDF scan atau gambar.</p>
              </div>
            </label>
          </div>

          <button 
            class="btn-submit" 
            :disabled="!ingestFile || isIngesting" 
            @click="handleIngest"
          >
            <span v-if="isIngesting" class="spinner"></span>
            <span v-if="isIngesting">Memproses Dokumen & Vektorisasi...</span>
            <span v-else>🚀 Mulai Ingest & Vektorisasi Dokumen</span>
          </button>
        </div>

        <div class="info-panel card">
          <h3 class="info-title">💡 Cara Kerja RAG Knowledge Pipeline</h3>
          <ul class="info-list">
            <li>
              <strong>1. Konversi AnyDoc</strong>
              <p>Dokumen dikonversi ke GitHub-Flavored Markdown dengan struktur heading dan tabel tetap rapi.</p>
            </li>
            <li>
              <strong>2. S3 Cloud Storage</strong>
              <p>File asli diarsipkan secara persisten di S3 Object Storage.</p>
            </li>
            <li>
              <strong>3. Semantic Markdown Chunking</strong>
              <p>Teks dipotong per bagian heading (750 karakter) sehingga konteks makna tidak terpotong sembarangan.</p>
            </li>
            <li>
              <strong>4. Free FastEmbed Vectorizing</strong>
              <p>Setiap potongan diubah menjadi vektor 384 dimensi dan disimpan di database untuk pencarian instan.</p>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Tab 3: RAG Chatbot Playground -->
    <div v-else-if="mainTab === 'chat'" class="tab-content">
      <div class="chat-layout">
        <!-- Chat Left Panel -->
        <div class="chat-main card">
          <div class="chat-header">
            <div class="chat-title-box">
              <span class="status-indicator"></span>
              <h3>RAG Knowledge Chatbot</h3>
            </div>
            <div class="chat-controls">
              <select v-model="selectedDocFilter" class="filter-select">
                <option value="">Semua Dokumen Basis Pengetahuan</option>
                <option v-for="d in documents" :key="d.id" :value="d.id">{{ d.filename }}</option>
              </select>
            </div>
          </div>

          <!-- Messages Scroll View -->
          <div class="messages-area">
            <div 
              v-for="(msg, idx) in chatMessages" 
              :key="idx" 
              :class="['chat-bubble-wrap', msg.role]"
            >
              <div class="chat-bubble">
                <div class="bubble-sender">{{ msg.role === 'user' ? 'Anda' : 'AI Assistant' }}</div>
                <div class="bubble-content" v-html="formatMarkdown(msg.content)"></div>

                <!-- Sources Footnote -->
                <div v-if="msg.sources && msg.sources.length > 0" class="sources-box">
                  <div class="sources-title">📎 Sumber Rujukan Dokumen:</div>
                  <div class="sources-tags">
                    <span v-for="(s, sIdx) in msg.sources" :key="sIdx" class="source-tag">
                      📄 {{ s.filename }} <span v-if="s.heading">({{ s.heading }})</span> - Skor: {{ (s.similarity_score * 100).toFixed(0) }}%
                    </span>
                  </div>
                </div>

                <div v-if="msg.latency" class="bubble-latency">
                  ⏱️ {{ msg.latency }} ms
                </div>
              </div>
            </div>

            <div v-if="isGenerating" class="chat-bubble-wrap assistant">
              <div class="chat-bubble loading">
                <div class="typing-dots"><span></span><span></span><span></span></div>
                <span>Mencari vektor dokumen & menyusun jawaban...</span>
              </div>
            </div>
          </div>

          <!-- Input Bar -->
          <div class="chat-input-bar">
            <input 
              type="text" 
              v-model="userPrompt" 
              placeholder="Tanyakan sesuatu tentang dokumen Anda (contoh: 'Apa kesimpulan dari dokumen X?')..." 
              class="chat-input"
              @keydown.enter="handleSendMessage"
            />
            <button 
              class="btn-send" 
              :disabled="!userPrompt.trim() || isGenerating" 
              @click="handleSendMessage"
            >
              Kirim 🚀
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 4: Next.js & API Integration -->
    <div v-else-if="mainTab === 'integration'" class="tab-content">
      <div class="card integration-card">
        <h2 class="section-title">Integrasi ke Next.js & API Eksternal</h2>
        <p class="section-desc">
          Gunakan endpoint ini di aplikasi Next.js Anda untuk meng-upload dokumen ke basis pengetahuan atau menghubungkan Chatbot secara langsung.
        </p>

        <div class="lang-nav">
          <button :class="['lang-tab', { active: apiLanguage === 'nextjs' }]" @click="apiLanguage = 'nextjs'">
            Next.js Chat API (route.ts)
          </button>
          <button :class="['lang-tab', { active: apiLanguage === 'nextjs_upload' }]" @click="apiLanguage = 'nextjs_upload'">
            Next.js Upload Action
          </button>
          <button :class="['lang-tab', { active: apiLanguage === 'curl' }]" @click="apiLanguage = 'curl'">
            cURL Endpoints
          </button>
          <button :class="['lang-tab', { active: apiLanguage === 'python' }]" @click="apiLanguage = 'python'">
            Python
          </button>
        </div>

        <div class="code-container">
          <div class="code-header">
            <span>{{ apiLanguage === 'nextjs' ? 'Next.js App Router (app/api/chat/route.ts)' : apiLanguage === 'nextjs_upload' ? 'Next.js Server Action (app/actions/upload-knowledge.ts)' : 'Code Snippet' }}</span>
            <button 
              class="btn-copy-code" 
              @click="copyToClipboard(
                apiLanguage === 'nextjs' ? nextjsChatCode : 
                apiLanguage === 'nextjs_upload' ? nextjsUploadCode : 
                apiLanguage === 'curl' ? curlCode : pythonCode, 
                'code'
              )"
            >
              {{ copiedType === 'code' ? '✅ Copied!' : '📋 Copy Code' }}
            </button>
          </div>
          <pre class="code-box" v-if="apiLanguage === 'nextjs'">{{ nextjsChatCode }}</pre>
          <pre class="code-box" v-else-if="apiLanguage === 'nextjs_upload'">{{ nextjsUploadCode }}</pre>
          <pre class="code-box" v-else-if="apiLanguage === 'curl'">{{ curlCode }}</pre>
          <pre class="code-box" v-else-if="apiLanguage === 'python'">{{ pythonCode }}</pre>
        </div>

        <!-- Free Embedding Guide Box -->
        <div class="embedding-guide-box">
          <h3>🔑 Panduan API Key Embedding Gratis</h3>
          <p>
            Raray Vision secara *default* sudah menjalankan <strong>FastEmbed ONNX (BAAI/bge-small-en-v1.5)</strong> yang <strong>100% GRATIS</strong> dan berjalan lokal di server tanpa memerlukan API Key eksternal apapun.
          </p>
          <p>
            Jika Anda ingin menggunakan Google Gemini Cloud Embedding gratis (1.500 requests/menit):
          </p>
          <ol>
            <li>Buka <a href="https://aistudio.google.com/" target="_blank" rel="noopener">Google AI Studio</a>.</li>
            <li>Klik <strong>"Get API key"</strong> dan buat API Key baru secara gratis.</li>
            <li>Tambahkan ke file <code>.env</code> Anda:
              <pre class="env-code">GEMINI_API_KEY=AIzaSy...your_key_here</pre>
            </li>
          </ol>
        </div>
      </div>
    </div>

    <!-- Modal: Inspect Chunks -->
    <div v-if="showChunksModal" class="modal-overlay" @click.self="showChunksModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <div>
            <h3>Potongan Vektor Chunks: {{ selectedDocForChunks?.filename }}</h3>
            <span class="modal-sub">{{ selectedDocForChunks?.total_chunks }} Total Chunks</span>
          </div>
          <button class="btn-close-modal" @click="showChunksModal = false">✕</button>
        </div>

        <div class="modal-body">
          <div v-if="isLoadingChunks" class="loading-state">
            <div class="spinner"></div>
            <span>Memuat chunk data...</span>
          </div>
          <div v-else class="chunks-list">
            <div v-for="c in docChunks" :key="c.id" class="chunk-card">
              <div class="chunk-card-header">
                <span class="chunk-index">Chunk #{{ c.chunk_index + 1 }}</span>
                <span class="chunk-heading" v-if="c.heading">📌 {{ c.heading }}</span>
                <span class="chunk-token">{{ c.token_count }} tokens</span>
              </div>
              <pre class="chunk-content">{{ c.content }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rag-container {
  padding: 24px 32px;
  max-width: 1600px;
  margin: 0 auto;
}

.rag-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 20px;
}

.title-row {
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

.title-icon {
  color: #2563eb;
}

.pill-badge {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 9999px;
  text-transform: uppercase;
}

.page-subtitle {
  color: #475569;
  font-size: 13.5px;
  margin: 6px 0 0;
  max-width: 900px;
  line-height: 1.5;
}

.header-stats {
  display: flex;
  gap: 12px;
}

.stat-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.stat-val {
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
}

.stat-lbl {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.engine-stat .stat-val {
  color: #2563eb;
}

/* Nav Tabs */
.rag-nav-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 2px solid #e2e8f0;
  margin-bottom: 20px;
  overflow-x: auto;
}

.tab-item {
  background: none;
  border: none;
  padding: 10px 16px;
  font-size: 13.5px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s;
  white-space: nowrap;
}

.tab-item:hover {
  color: #0f172a;
}

.tab-item.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 700;
}

/* Card */
.card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

/* Library Toolbar */
.library-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 8px 14px;
  border-radius: 8px;
  width: 320px;
}

.search-input {
  border: none;
  outline: none;
  font-size: 13px;
  width: 100%;
}

.toolbar-actions {
  display: flex;
  gap: 10px;
}

.btn-refresh {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.btn-primary:hover {
  background: #1d4ed8;
}

/* Table */
.table-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow-x: auto;
}

.library-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.library-table th, .library-table td {
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.library-table th {
  background: #f8fafc;
  font-weight: 700;
  color: #475569;
}

.doc-title-cell {
  display: flex;
  flex-direction: column;
}

.doc-id-sub {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

.badge-format {
  background: #dbeafe;
  color: #1e40af;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.chunk-badge {
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.s3-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.s3-btn:hover {
  text-decoration: underline;
}

.row-actions {
  display: flex;
  gap: 6px;
}

.btn-inspect {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.btn-delete {
  background: #fee2e2;
  border: 1px solid #fca5a5;
  color: #dc2626;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}

/* Ingest Layout */
.ingest-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 24px;
}

@media (max-width: 1000px) {
  .ingest-grid {
    grid-template-columns: 1fr;
  }
}

.section-title {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 6px;
}

.section-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0 0 16px;
  line-height: 1.5;
}

.drop-box {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 36px 20px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s;
}

.drop-box:hover, .drop-box.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.drop-circle {
  width: 60px;
  height: 60px;
  background: #eff6ff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
}

.drop-prompt h3 {
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 4px;
  color: #1e293b;
}

.drop-prompt p {
  font-size: 12px;
  color: #64748b;
  margin: 0;
}

.file-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  padding: 12px 16px;
  border-radius: 8px;
  text-align: left;
}

.file-icon-box {
  background: #2563eb;
  color: #ffffff;
  font-weight: 800;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.file-meta-box {
  flex: 1;
}

.file-name {
  font-size: 13.5px;
  font-weight: 700;
  display: block;
}

.file-size {
  font-size: 11.5px;
  color: #64748b;
}

.btn-close {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 16px;
  cursor: pointer;
}

.options-box {
  margin: 16px 0;
}

.check-row {
  display: flex;
  gap: 10px;
  cursor: pointer;
}

.check-row p {
  font-size: 11.5px;
  color: #64748b;
  margin: 2px 0 0;
}

.btn-submit {
  width: 100%;
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.info-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px;
}

.info-list {
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.info-list li strong {
  font-size: 12.5px;
  color: #1e293b;
}

.info-list li p {
  font-size: 11.5px;
  color: #64748b;
  margin: 3px 0 0;
}

/* Chatbot Layout */
.chat-main {
  display: flex;
  flex-direction: column;
  height: 650px;
  padding: 0;
}

.chat-header {
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chat-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-title-box h3 {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
}

.status-indicator {
  width: 8px;
  height: 8px;
  background: #10b981;
  border-radius: 50%;
}

.filter-select {
  padding: 6px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.messages-area {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #f8fafc;
}

.chat-bubble-wrap {
  display: flex;
  flex-direction: column;
}

.chat-bubble-wrap.user {
  align-items: flex-end;
}

.chat-bubble-wrap.assistant {
  align-items: flex-start;
}

.chat-bubble {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.5;
}

.chat-bubble-wrap.user .chat-bubble {
  background: #2563eb;
  color: #ffffff;
  border-bottom-right-radius: 2px;
}

.chat-bubble-wrap.assistant .chat-bubble {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #0f172a;
  border-bottom-left-radius: 2px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.bubble-sender {
  font-size: 10.5px;
  font-weight: 700;
  margin-bottom: 4px;
  opacity: 0.8;
}

:deep(.bubble-content) {
  word-break: break-word;
}

:deep(.bubble-content strong) {
  font-weight: 800;
  color: inherit;
}

:deep(.bubble-content em) {
  font-style: italic;
}

:deep(.chat-inline-code) {
  background: rgba(0, 0, 0, 0.08);
  padding: 2px 5px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
}

:deep(.chat-code-block) {
  background: #0f172a;
  color: #f8fafc;
  padding: 10px 14px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 12px;
  margin: 6px 0;
  overflow-x: auto;
}

:deep(.chat-h2), :deep(.chat-h3), :deep(.chat-h4) {
  font-weight: 800;
  margin: 8px 0 4px;
  color: inherit;
}

:deep(.chat-spacer) {
  height: 8px;
}

:deep(.chat-ul) {
  padding-left: 18px;
  margin: 6px 0;
}

:deep(.chat-li) {
  margin: 2px 0;
}

.sources-box {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}

.sources-title {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 4px;
}

.sources-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.source-tag {
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #bfdbfe;
}

.bubble-latency {
  font-size: 10px;
  color: #94a3b8;
  margin-top: 6px;
  text-align: right;
}

.chat-input-bar {
  padding: 14px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  gap: 10px;
  background: #ffffff;
  border-radius: 0 0 12px 12px;
}

.chat-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 13.5px;
  outline: none;
}

.chat-input:focus {
  border-color: #2563eb;
}

.btn-send {
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}

.btn-send:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Integration Tab */
.lang-nav {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.lang-tab {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.lang-tab.active {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
}

.code-container {
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 24px;
}

.code-header {
  background: #1e293b;
  color: #94a3b8;
  padding: 8px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.btn-copy-code {
  background: #334155;
  color: #f8fafc;
  border: none;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}

.code-box {
  background: #0f172a;
  color: #f8fafc;
  padding: 16px;
  margin: 0;
  font-family: monospace;
  font-size: 12.5px;
  line-height: 1.6;
  max-height: 480px;
  overflow: auto;
}

.embedding-guide-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.embedding-guide-box h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.embedding-guide-box p, .embedding-guide-box li {
  font-size: 12.5px;
  color: #475569;
  line-height: 1.6;
}

.env-code {
  background: #0f172a;
  color: #38bdf8;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin: 6px 0;
  display: inline-block;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-card {
  background: #ffffff;
  border-radius: 12px;
  width: 100%;
  max-width: 800px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 10px 25px rgba(0,0,0,0.1);
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
}

.modal-sub {
  font-size: 12px;
  color: #64748b;
}

.btn-close-modal {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chunk-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  background: #f8fafc;
}

.chunk-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11.5px;
  margin-bottom: 8px;
}

.chunk-index {
  background: #e2e8f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}

.chunk-heading {
  font-weight: 600;
  color: #2563eb;
}

.chunk-token {
  color: #94a3b8;
}

.chunk-content {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
}

/* Spinner & Alerts */
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.alert-box {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 14px;
}

.alert-error { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; }
.alert-success { background: #f0fdf4; border: 1px solid #bbf7d0; color: #16a34a; }

.loading-state, .empty-library {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
  gap: 10px;
}
</style>

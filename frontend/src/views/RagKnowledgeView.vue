<script setup>
import { ref, computed, onMounted } from 'vue'
import { ragService } from '../services/ragService'
import { API_BASE_URL } from '../utils'

// Active View Tab
const mainTab = ref('library') // 'library', 'ingest', 'external_db', 'chat', 'integration'

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
const uploadProgressPercent = ref(0)
const uploadStatsText = ref('')
const processingStage = ref('idle') // 'idle', 'uploading', 'converting', 'storage', 'vectorizing', 'completed', 'error'
const elapsedSeconds = ref(0)
let timerInterval = null

// External PostgreSQL State
const externalDatabases = ref([])
const isLoadingDatabases = ref(false)
const isTestingDb = ref(false)
const testDbMessage = ref(null)
const isIntrospecting = ref(false)
const availableTables = ref([])
const selectedTables = ref([])
const tableSearchFilter = ref('')
const isSavingDb = ref(false)
const isSyncingDb = ref(false)
const syncingDbId = ref(null)
const syncStatusMessage = ref(null)
const dbViewMode = ref('list') // 'list' or 'form'

const dbForm = ref({
  id: null,
  name: '',
  inputType: 'url', // 'url' or 'params'
  dbUrl: '',
  host: 'localhost',
  port: 5432,
  database: '',
  username: 'postgres',
  password: '',
  maxRowsPerTable: 500,
  autoSync: false,
  syncIntervalHours: 24
})

// Chatbot Playground State & Persistent Memory Session
const currentSessionId = ref(localStorage.getItem('raray_rag_session_id') || ('sess_' + Math.random().toString(36).substring(2, 12)))
localStorage.setItem('raray_rag_session_id', currentSessionId.value)
const redisStatus = ref(null)

const chatMessages = ref([
  {
    role: 'assistant',
    content: 'Halo! Saya adalah Hero Assistant terhubung ke basis pengetahuan Anda. Tanyakan apa saja mengenai dokumen dan data database yang telah Anda sinkronkan.',
    sources: []
  }
])
const userPrompt = ref('')
const isGenerating = ref(false)
const chatTopK = ref(4)
const selectedDocFilter = ref('')

// Persistent Sessions & Self-Growth Memory State
const learnedFacts = ref([])
const isLoadingFacts = ref(false)
const sessionsList = ref([])
const activeFeedbackMsg = ref(null)
const showFeedbackModal = ref(false)
const feedbackRating = ref(1)
const feedbackCorrection = ref('')
const feedbackNotes = ref('')
const isSubmittingFeedback = ref(false)
const feedbackSuccessToast = ref('')

// Memory History Manager State
const memoryTab = ref('all')         // 'all', 'correction', 'manual'
const memorySearchQuery = ref('')
const selectedFactIds = ref(new Set())
const isBulkDeleting = ref(false)

const filteredMemoryFacts = computed(() => {
  let base = learnedFacts.value
  if (memoryTab.value === 'correction') base = base.filter(f => f.fact_type === 'user_correction')
  else if (memoryTab.value === 'manual') base = base.filter(f => f.learned_from === 'direct_input')
  if (memorySearchQuery.value.trim()) {
    const q = memorySearchQuery.value.toLowerCase()
    base = base.filter(f => (f.subject || '').toLowerCase().includes(q) || (f.content || '').toLowerCase().includes(q))
  }
  return base
})

const allFilteredSelected = computed(() => {
  return filteredMemoryFacts.value.length > 0 && filteredMemoryFacts.value.every(f => selectedFactIds.value.has(f.id))
})

const newFactForm = ref({
  subject: '',
  content: '',
  factType: 'learned_knowledge'
})
const isSavingFact = ref(false)

// Integration Tab
const apiLanguage = ref('nextjs') // 'nextjs', 'nextjs_upload', 'curl', 'python'
const copiedType = ref('')

// Engine Info
const ragInfo = ref(null)

onMounted(async () => {
  await Promise.all([
    fetchLibrary(),
    fetchExternalDatabases(),
    fetchLearnedFacts(),
    fetchSessions()
  ])
  try {
    const res = await ragService.getInfo()
    if (res?.data) {
      ragInfo.value = res.data
      if (res.data.redis) redisStatus.value = res.data.redis
    }
  } catch (err) {
    console.warn('Could not fetch RAG info:', err)
  }

  // Restore persistent conversation history (try DB first, then Redis)
  try {
    const sessionRes = await ragService.getSessionMessages(currentSessionId.value)
    if (sessionRes?.data && sessionRes.data.length > 0) {
      chatMessages.value = sessionRes.data
    } else {
      const histRes = await ragService.getChatSessionHistory(currentSessionId.value)
      if (histRes?.history && histRes.history.length > 0) {
        chatMessages.value = histRes.history
      }
    }
  } catch (e) {
    console.warn('Could not restore chat session:', e)
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

const fetchExternalDatabases = async () => {
  isLoadingDatabases.value = true
  try {
    const res = await ragService.getExternalDatabases()
    if (res?.databases) {
      externalDatabases.value = res.databases
    }
  } catch (err) {
    console.error('Failed to fetch external databases:', err)
  } finally {
    isLoadingDatabases.value = false
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
  uploadProgressPercent.value = 0
  uploadStatsText.value = 'Menyiapkan berkas...'
  processingStage.value = 'uploading'
  elapsedSeconds.value = 0

  if (timerInterval) clearInterval(timerInterval)
  timerInterval = setInterval(() => {
    elapsedSeconds.value = Number((elapsedSeconds.value + 0.5).toFixed(1))
    if (processingStage.value === 'converting' && elapsedSeconds.value > 8) {
      processingStage.value = 'storage'
    }
    if (processingStage.value === 'storage' && elapsedSeconds.value > 16) {
      processingStage.value = 'vectorizing'
    }
  }, 500)

  try {
    const res = await ragService.ingest(
      ingestFile.value,
      {
        autoOcr: autoOcr.value,
        forceOcr: forceOcr.value
      },
      (percent, loaded, total) => {
        uploadProgressPercent.value = percent
        const loadedMb = (loaded / (1024 * 1024)).toFixed(1)
        const totalMb = (total / (1024 * 1024)).toFixed(1)
        uploadStatsText.value = `${loadedMb} MB / ${totalMb} MB (${percent}%)`
        if (percent >= 100) {
          processingStage.value = 'converting'
        }
      }
    )

    processingStage.value = 'completed'
    uploadProgressPercent.value = 100
    ingestSuccess.value = `Berhasil! Dokumen "${res.filename}" (${res.word_count?.toLocaleString() || 0} kata) telah diubah ke Markdown, disimpan di S3, dan diindeks menjadi ${res.total_chunks} vektor dalam ${res.processing_time_ms} ms.`
    ingestFile.value = null
    await fetchLibrary()
  } catch (err) {
    processingStage.value = 'error'
    ingestError.value = err.message || 'Gagal mengindeks dokumen ke basis pengetahuan.'
  } finally {
    isIngesting.value = false
    if (timerInterval) {
      clearInterval(timerInterval)
      timerInterval = null
    }
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

// Resolve secure document preview / download URL (routing via FastAPI presigned redirect)
const resolveDocUrl = (doc) => {
  if (!doc) return '#'
  if (doc.local_url && doc.local_url.startsWith('/api/v1/uploads/')) return doc.local_url
  const raw = doc.s3_url || doc.filename || ''
  if (!raw) return '#'
  if (raw.startsWith('/api/v1/uploads/')) return raw
  const filename = decodeURIComponent(raw.split('?')[0].split('/').pop() || '')
  return `/api/v1/uploads/${encodeURIComponent(filename)}`
}


// --- External PostgreSQL DB Handlers ---
const computedDbUrl = computed(() => {
  if (dbForm.value.inputType === 'url') {
    return dbForm.value.dbUrl.trim()
  }
  const u = encodeURIComponent(dbForm.value.username || '')
  const p = encodeURIComponent(dbForm.value.password || '')
  const h = dbForm.value.host || 'localhost'
  const port = dbForm.value.port || 5432
  const d = dbForm.value.database || ''
  return `postgresql://${u}:${p}@${h}:${port}/${d}`
})

const filteredAvailableTables = computed(() => {
  if (!tableSearchFilter.value.trim()) return availableTables.value
  const q = tableSearchFilter.value.toLowerCase()
  return availableTables.value.filter(t => t.table_name.toLowerCase().includes(q))
})

const handleTestConnection = async () => {
  const url = computedDbUrl.value
  if (!url) {
    testDbMessage.value = { success: false, text: 'Silakan isi parameter koneksi database terlebih dahulu.' }
    return
  }

  isTestingDb.value = true
  testDbMessage.value = null

  try {
    const res = await ragService.testDatabaseConnection(url)
    if (res.success) {
      testDbMessage.value = {
        success: true,
        text: `✅ ${res.message} (${res.latency_ms} ms) - Versi DB: ${res.db_version?.substring(0, 45)}...`
      }
    } else {
      testDbMessage.value = { success: false, text: `❌ ${res.message}` }
    }
  } catch (err) {
    testDbMessage.value = { success: false, text: `❌ ${err.message}` }
  } finally {
    isTestingDb.value = false
  }
}

const handleIntrospectTables = async () => {
  const url = computedDbUrl.value
  if (!url) {
    testDbMessage.value = { success: false, text: 'Silakan isi parameter koneksi database terlebih dahulu.' }
    return
  }

  isIntrospecting.value = true
  testDbMessage.value = null

  try {
    const res = await ragService.introspectDatabaseSchema(url)
    if (res.success && res.tables) {
      availableTables.value = res.tables
      testDbMessage.value = {
        success: true,
        text: `✅ Berhasil membaca schema: Ditemukan ${res.total_tables} tabel publik pada database.`
      }
    } else {
      testDbMessage.value = { success: false, text: `❌ ${res.message || 'Gagal membaca tabel database.'}` }
    }
  } catch (err) {
    testDbMessage.value = { success: false, text: `❌ ${err.message}` }
  } finally {
    isIntrospecting.value = false
  }
}

const toggleSelectAllTables = (selectAll) => {
  if (selectAll) {
    selectedTables.value = availableTables.value.map(t => t.table_name)
  } else {
    selectedTables.value = []
  }
}

const isTableSelected = (tableName) => {
  return selectedTables.value.includes(tableName)
}

const toggleTableSelection = (tableName) => {
  const idx = selectedTables.value.indexOf(tableName)
  if (idx > -1) {
    selectedTables.value.splice(idx, 1)
  } else {
    selectedTables.value.push(tableName)
  }
}

const handleSaveDatabase = async () => {
  if (!dbForm.value.name.trim()) {
    alert('Silakan masukkan nama koneksi database (misal: "Database ERP Produksi").')
    return
  }
  const url = computedDbUrl.value
  if (!url) {
    alert('Silakan isi connection string database.')
    return
  }

  isSavingDb.value = true
  syncStatusMessage.value = null

  const payload = {
    name: dbForm.value.name.trim(),
    db_url: url,
    host: dbForm.value.host,
    port: Number(dbForm.value.port) || 5432,
    database_name: dbForm.value.database,
    username: dbForm.value.username,
    selected_tables: selectedTables.value,
    auto_sync: dbForm.value.autoSync,
    sync_interval_hours: Number(dbForm.value.syncIntervalHours) || 24
  }

  try {
    let savedDb
    if (dbForm.value.id) {
      const res = await ragService.updateExternalDatabase(dbForm.value.id, payload)
      savedDb = res.database
    } else {
      const res = await ragService.createExternalDatabase(payload)
      savedDb = res.database
    }

    await fetchExternalDatabases()

    // Trigger sync automatically if user selected tables
    if (selectedTables.value.length > 0) {
      await handleSyncDatabase(savedDb)
    } else {
      dbViewMode.value = 'list'
      resetDbForm()
    }
  } catch (err) {
    alert('Gagal menyimpan database: ' + err.message)
  } finally {
    isSavingDb.value = false
  }
}

let syncPollInterval = null

const startSyncPolling = (dbId, dbName) => {
  if (syncPollInterval) clearInterval(syncPollInterval)
  let attempts = 0

  syncPollInterval = setInterval(async () => {
    attempts++
    try {
      await fetchExternalDatabases()
      const currentDb = externalDatabases.value.find(d => d.id === dbId)
      if (currentDb) {
        if (currentDb.status === 'active' && currentDb.last_sync_status === 'success') {
          clearInterval(syncPollInterval)
          syncPollInterval = null
          isSyncingDb.value = false
          syncingDbId.value = null
          syncStatusMessage.value = {
            type: 'success',
            text: `✅ Sukses! Tabel database "${dbName}" (${currentDb.total_chunks_synced || 0} chunks) telah selesai disinkronkan ke Knowledge Base.`
          }
          await fetchLibrary()
        } else if (currentDb.status === 'error') {
          clearInterval(syncPollInterval)
          syncPollInterval = null
          isSyncingDb.value = false
          syncingDbId.value = null
          syncStatusMessage.value = {
            type: 'error',
            text: `❌ Sinkronisasi database gagal: ${currentDb.last_error_message || 'Terjadi kesalahan saat memproses data tabel.'}`
          }
        }
      }
      if (attempts > 50) { // Stop polling after ~2.5 minutes
        clearInterval(syncPollInterval)
        syncPollInterval = null
        isSyncingDb.value = false
        syncingDbId.value = null
      }
    } catch (e) {
      console.warn('Sync poll error:', e)
    }
  }, 3000)
}

const handleSyncDatabase = async (dbRecord) => {
  syncingDbId.value = dbRecord.id
  isSyncingDb.value = true
  syncStatusMessage.value = {
    type: 'info',
    text: `⚡ Sinkronisasi tabel untuk "${dbRecord.name}" telah dimulai di latar belakang...`
  }

  try {
    const res = await ragService.syncExternalDatabase(dbRecord.id, {
      max_rows_per_table: dbForm.value.maxRowsPerTable || 300
    })

    if (res?.status === 'success') {
      dbViewMode.value = 'list'
      await fetchExternalDatabases()
      startSyncPolling(dbRecord.id, dbRecord.name)
    } else {
      syncStatusMessage.value = {
        type: 'error',
        text: `❌ ${res?.message || 'Gagal memulai sinkronisasi.'}`
      }
      isSyncingDb.value = false
      syncingDbId.value = null
    }
  } catch (err) {
    syncStatusMessage.value = {
      type: 'error',
      text: `❌ Gagal sinkronisasi: ${err.message}`
    }
    isSyncingDb.value = false
    syncingDbId.value = null
  }
}

const handleEditDatabase = async (dbRecord) => {
  dbForm.value = {
    id: dbRecord.id,
    name: dbRecord.name,
    inputType: 'url',
    dbUrl: dbRecord.db_url,
    host: dbRecord.host || 'localhost',
    port: dbRecord.port || 5432,
    database: dbRecord.database_name || '',
    username: dbRecord.username || 'postgres',
    password: '',
    maxRowsPerTable: 500,
    autoSync: dbRecord.auto_sync || false,
    syncIntervalHours: dbRecord.sync_interval_hours || 24
  }
  selectedTables.value = [...(dbRecord.selected_tables || [])]
  dbViewMode.value = 'form'
  testDbMessage.value = null

  // Auto load tables for this DB
  await handleIntrospectTables()
}

const handleDeleteDatabase = async (dbRecord) => {
  if (!confirm(`Hapus konfigurasi koneksi database "${dbRecord.name}"? Dokumen vektor yang sudah tersinkronisasi akan tetap tersimpan.`)) {
    return
  }
  try {
    await ragService.deleteExternalDatabase(dbRecord.id)
    await fetchExternalDatabases()
  } catch (err) {
    alert('Gagal menghapus database: ' + err.message)
  }
}

const resetDbForm = () => {
  dbForm.value = {
    id: null,
    name: '',
    inputType: 'url',
    dbUrl: '',
    host: 'localhost',
    port: 5432,
    database: '',
    username: 'postgres',
    password: '',
    maxRowsPerTable: 500,
    autoSync: false,
    syncIntervalHours: 24
  }
  selectedTables.value = []
  availableTables.value = []
  testDbMessage.value = null
}

const startNewDatabase = () => {
  resetDbForm()
  dbViewMode.value = 'form'
}

// Persistent Sessions & Self-Growth Memory Handlers
const fetchLearnedFacts = async () => {
  isLoadingFacts.value = true
  try {
    const res = await ragService.getLearnedFacts({ limit: 200 })
    if (res?.data) {
      learnedFacts.value = res.data
    }
  } catch (err) {
    console.warn('Failed to fetch learned facts:', err)
  } finally {
    isLoadingFacts.value = false
  }
}

const fetchSessions = async () => {
  try {
    const res = await ragService.getSessions(30)
    if (res?.data) {
      sessionsList.value = res.data
    }
  } catch (err) {
    console.warn('Failed to fetch sessions:', err)
  }
}

const selectSession = async (sessId) => {
  if (!sessId || sessId === currentSessionId.value) return
  currentSessionId.value = sessId
  localStorage.setItem('raray_rag_session_id', sessId)
  try {
    const res = await ragService.getSessionMessages(sessId)
    if (res?.data && res.data.length > 0) {
      chatMessages.value = res.data
    } else {
      chatMessages.value = []
    }
  } catch (err) {
    console.error('Error loading session messages:', err)
  }
}

const handleDeleteSession = async (sessId) => {
  if (!confirm('Hapus sesi percakapan ini secara permanen?')) return
  try {
    await ragService.deleteSession(sessId)
    await fetchSessions()
    if (currentSessionId.value === sessId) {
      clearChat()
    }
  } catch (err) {
    alert('Gagal menghapus sesi: ' + err.message)
  }
}

const handleSaveNewFact = async () => {
  if (!newFactForm.value.content.trim()) {
    alert('Isi konten fakta / aturan terlebih dahulu.')
    return
  }
  isSavingFact.value = true
  try {
    await ragService.teachFact({
      content: newFactForm.value.content,
      subject: newFactForm.value.subject || null,
      factType: newFactForm.value.factType || 'learned_knowledge'
    })
    newFactForm.value = { subject: '', content: '', factType: 'learned_knowledge' }
    await fetchLearnedFacts()
    alert('🧠 Fakta baru berhasil dipelajari dan disimpan ke dalam memori RAG!')
  } catch (err) {
    alert('Gagal menyimpan fakta: ' + err.message)
  } finally {
    isSavingFact.value = false
  }
}

const handleDeleteFact = async (factId) => {
  if (!confirm('Hapus fakta / aturan memori ini?')) return
  try {
    await ragService.deleteLearnedFact(factId)
    selectedFactIds.value.delete(factId)
    await fetchLearnedFacts()
  } catch (err) {
    alert('Gagal menghapus fakta: ' + err.message)
  }
}

const toggleFactSelection = (factId) => {
  const s = new Set(selectedFactIds.value)
  if (s.has(factId)) s.delete(factId)
  else s.add(factId)
  selectedFactIds.value = s
}

const toggleSelectAll = () => {
  if (allFilteredSelected.value) {
    const s = new Set(selectedFactIds.value)
    filteredMemoryFacts.value.forEach(f => s.delete(f.id))
    selectedFactIds.value = s
  } else {
    const s = new Set(selectedFactIds.value)
    filteredMemoryFacts.value.forEach(f => s.add(f.id))
    selectedFactIds.value = s
  }
}

const handleBulkDelete = async () => {
  const ids = Array.from(selectedFactIds.value)
  if (!ids.length) return
  if (!confirm(`Hapus ${ids.length} memori yang dipilih secara permanen?`)) return
  isBulkDeleting.value = true
  try {
    await ragService.deleteLearnedFactsBulk(ids)
    selectedFactIds.value = new Set()
    await fetchLearnedFacts()
  } catch (err) {
    alert('Gagal bulk delete: ' + err.message)
  } finally {
    isBulkDeleting.value = false
  }
}

// Chatbot Send with Multi-Turn Memory & Persistent DB Session
const getUniqueSources = (sources) => {
  if (!sources || !Array.isArray(sources)) return []
  const map = new Map()
  for (const s of sources) {
    const key = `${s.filename}__${s.heading || ''}`
    if (!map.has(key) || (s.similarity_score > map.get(key).similarity_score)) {
      map.set(key, s)
    }
  }
  return Array.from(map.values())
}

const clearChat = async () => {
  currentSessionId.value = 'sess_' + Math.random().toString(36).substring(2, 12)
  localStorage.setItem('raray_rag_session_id', currentSessionId.value)
  chatMessages.value = [
    {
      role: 'assistant',
      content: 'Halo! Sesi percakapan baru telah dibuat. Saya adalah Hero Assistant terhubung ke basis pengetahuan Anda. Tanyakan apa saja mengenai dokumen dan data database yang telah Anda sinkronkan.',
      sources: []
    }
  ]
  await fetchSessions()
}

const handleSendMessage = async () => {
  const q = userPrompt.value.trim()
  if (!q || isGenerating.value) return

  userPrompt.value = ''

  // Collect previous conversation turns for LLM context
  const previousTurns = chatMessages.value
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => ({
      role: m.role,
      content: m.content
    }))

  const userMsgObj = {
    role: 'user',
    content: q,
    sources: []
  }
  chatMessages.value.push(userMsgObj)

  isGenerating.value = true

  try {
    const res = await ragService.chat({
      query: q,
      messages: previousTurns,
      sessionId: currentSessionId.value,
      topK: chatTopK.value,
      documentId: selectedDocFilter.value || null
    })

    if (res?.data) {
      userMsgObj.id = res.data.user_message_id
      chatMessages.value.push({
        id: res.data.assistant_message_id,
        role: 'assistant',
        content: res.data.answer || 'Tidak ada jawaban.',
        sources: res.data.sources || [],
        learned_facts: res.data.learned_facts || [],
        latency: res.data.latency_ms,
        from_cache: res.data.from_cache,
        rating: null
      })
      fetchSessions()
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

// Feedback & Self-Growth Actions
const openFeedbackModal = (msg, defaultRating = null) => {
  activeFeedbackMsg.value = msg
  feedbackRating.value = defaultRating !== null ? defaultRating : (msg.rating || 1)
  feedbackCorrection.value = msg.correction_text || ''
  feedbackNotes.value = msg.feedback_notes || ''
  showFeedbackModal.value = true
}

const quickThumbsUp = async (msg) => {
  if (!msg.id) return
  msg.rating = 1
  try {
    await ragService.submitFeedback({
      messageId: msg.id,
      rating: 1
    })
  } catch (e) {
    console.warn('Feedback error:', e)
  }
}

const submitFeedbackAction = async () => {
  if (!activeFeedbackMsg.value?.id) {
    showFeedbackModal.value = false
    return
  }
  isSubmittingFeedback.value = true
  try {
    const res = await ragService.submitFeedback({
      messageId: activeFeedbackMsg.value.id,
      rating: feedbackRating.value,
      feedbackNotes: feedbackNotes.value,
      correctionText: feedbackCorrection.value
    })
    activeFeedbackMsg.value.rating = feedbackRating.value
    activeFeedbackMsg.value.feedback_notes = feedbackNotes.value
    activeFeedbackMsg.value.correction_text = feedbackCorrection.value
    showFeedbackModal.value = false

    if (res?.data?.learned_fact) {
      await fetchLearnedFacts()
      alert('🧠 Koreksi Anda telah disimpan ke memori! AI akan mengingat perbaikan ini untuk pertanyaan berikutnya.')
    } else {
      alert('Terima kasih atas masukan Anda!')
    }
  } catch (err) {
    alert('Gagal mengirim feedback: ' + err.message)
  } finally {
    isSubmittingFeedback.value = false
  }
}

const formatInlineMarkdown = (text) => {
  if (!text) return ''
  return text
    .replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>')
    .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
}

const renderTableHtml = (tableLines) => {
  if (!tableLines || tableLines.length < 2) return ''
  let tableHtml = '<div class="chat-table-wrapper"><table class="chat-table">'
  let isFirstRow = true
  let hasBody = false

  for (let r = 0; r < tableLines.length; r++) {
    const rawLine = tableLines[r].trim()
    if (!rawLine) continue
    let rowCells = rawLine.split('|')
    if (rawLine.startsWith('|')) rowCells.shift()
    if (rawLine.endsWith('|') && rowCells.length > 0) rowCells.pop()
    rowCells = rowCells.map(c => c.trim())

    // Skip separator lines like |:---|:---|
    if (rowCells.every(c => /^:?-+:?$/.test(c))) {
      continue
    }

    if (isFirstRow) {
      tableHtml += '<thead><tr>' + rowCells.map(c => `<th>${formatInlineMarkdown(c)}</th>`).join('') + '</tr></thead><tbody>'
      isFirstRow = false
      hasBody = true
    } else {
      tableHtml += '<tr>' + rowCells.map(c => `<td>${formatInlineMarkdown(c)}</td>`).join('') + '</tr>'
    }
  }

  if (hasBody) {
    tableHtml += '</tbody>'
  }
  tableHtml += '</table></div>'
  return tableHtml
}

const formatMarkdown = (text) => {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks (preserve placeholder)
  const codeBlocks = []
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`
    codeBlocks.push(`<pre class="chat-code-block"><code>${code.trim()}</code></pre>`)
    return placeholder
  })

  // Parse Markdown Tables and store in placeholders
  const tableBlocks = []
  const lines = html.split('\n')
  const newLines = []
  let currentTable = []

  const isTableRow = (line) => {
    const trimmed = line.trim()
    return trimmed.startsWith('|') && (trimmed.endsWith('|') || trimmed.includes('|', 1))
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (isTableRow(line)) {
      currentTable.push(line)
    } else {
      if (currentTable.length >= 2) {
        const placeholder = `__TABLE_BLOCK_${tableBlocks.length}__`
        tableBlocks.push(renderTableHtml(currentTable))
        newLines.push(placeholder)
        currentTable = []
      } else if (currentTable.length === 1) {
        newLines.push(currentTable[0])
        currentTable = []
      }
      newLines.push(line)
    }
  }

  if (currentTable.length >= 2) {
    const placeholder = `__TABLE_BLOCK_${tableBlocks.length}__`
    tableBlocks.push(renderTableHtml(currentTable))
    newLines.push(placeholder)
  } else if (currentTable.length === 1) {
    newLines.push(currentTable[0])
  }

  html = newLines.join('\n')

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

  // Images: ![alt](url) -> <img>
  html = html.replace(/!\[(.*?)\]\((.*?)\)/g, '<img class="chat-image" src="$2" alt="$1" style="max-width: 100%; max-height: 350px; border-radius: 8px; margin: 12px 0; display: block; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);" />')

  // Links: [text](url) -> <a>
  html = html.replace(/\[(.*?)\]\((.*?)\)/g, '<a class="chat-link" href="$2" target="_blank" style="color: #3b82f6; text-decoration: underline;">$1</a>')

  // Bullet points
  html = html.replace(/^\s*[\-\*]\s+(.*$)/gim, '<li class="chat-li">$1</li>')
  html = html.replace(/(<li class="chat-li">[\s\S]*?<\/li>)/g, '<ul class="chat-ul">$1</ul>')
  html = html.replace(/<\/ul>\s*<ul class="chat-ul">/g, '')

  // Line breaks
  html = html.replace(/\n\n/g, '<div class="chat-spacer"></div>')
  html = html.replace(/\n/g, '<br>')

  // Restore table blocks
  tableBlocks.forEach((tb, idx) => {
    html = html.replace(`__TABLE_BLOCK_${idx}__`, tb)
  })

  // Restore code blocks
  codeBlocks.forEach((cb, idx) => {
    html = html.replace(`__CODE_BLOCK_${idx}__`, cb)
  })

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

    // 1. Panggil RAG API Raray Vision dengan multi-turn context memory & self-growth
    // Jawaban otomatis mengutamakan data koreksi / SOP terbaru dari Memory History Manager
    const ragResponse = await fetch("${API_BASE_URL}/api/v1/rag/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer \${process.env.RARAY_VISION_API_KEY}"
      },
      body: JSON.stringify({
        query: lastUserMessage,
        messages: messages, // Riwayat percakapan sebelumnya
        top_k: 4
      })
    });

    const data = await ragResponse.json();

    return NextResponse.json({
      role: "assistant",
      content: data.data.answer,
      sources: data.data.sources, // Memuat chunk dokumen & memori koreksi
      learned_facts: data.data.learned_facts,
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
  // Upload dokumen file ke pgvector
  const res = await fetch("${API_BASE_URL}/api/v1/rag/ingest", {
    method: "POST",
    headers: {
      "Authorization": "Bearer \${process.env.RARAY_VISION_API_KEY}"
    },
    body: formData
  });

  const result = await res.json();
  return result; // mengembalikan document_id, total_chunks, s3_url, dll.
}

export async function teachMemoryFact(content: string, subject?: string, factType: string = "learned_knowledge") {
  // Tambahkan aturan / koreksi / SOP langsung ke memori jangka panjang RAG
  const res = await fetch("${API_BASE_URL}/api/v1/rag/memory/learn", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer \${process.env.RARAY_VISION_API_KEY}"
    },
    body: JSON.stringify({ content, subject, fact_type: factType })
  });
  return await res.json();
}`
})

const curlCode = computed(() => {
  return `# 1. Upload & Ingest Dokumen ke pgvector
curl -X POST "${API_BASE_URL}/api/v1/rag/ingest" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -F "file=@panduan.docx" \\
  -F "auto_ocr=true"

# 2. Semantic Search (Pencarian Vektor Gabungan: Dokumen + Memori Koreksi)
curl -X POST "${API_BASE_URL}/api/v1/rag/search" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "Berapa tekanan ban WA500?", "top_k": 4}'

# 3. Chatbot Generation (Didukung Groq Qwen & Memori Prioritas)
curl -X POST "${API_BASE_URL}/api/v1/rag/chat" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "Jelaskan prosedur pergantian ban", "top_k": 4}'

# 4. Tambahkan Aturan / Koreksi Baru ke Memory History Manager
curl -X POST "${API_BASE_URL}/api/v1/rag/memory/learn" \\
  -H "Authorization: Bearer ${apiToken.value}" \\
  -H "Content-Type: application/json" \\
  -d '{"content": "Form izin kerja panas wajib disetujui Dept Head.", "subject": "SOP Izin Panas", "fact_type": "rule"}'`
})

const pythonCode = computed(() => {
  return `import requests

API_URL = "${API_BASE_URL}/api/v1/rag"
HEADERS = {"Authorization": "Bearer ${apiToken.value}"}

# 1. Semantic Search (Mencakup Dokumen & Memori Terkoreksi)
search_res = requests.post(f"{API_URL}/search", headers=HEADERS, json={
    "query": "Tekanan angin Komatsu WA500",
    "top_k": 4
}).json()
print("Hasil Chunks:", search_res["results"])

# 2. Chatbot Query
chat_res = requests.post(f"{API_URL}/chat", headers=HEADERS, json={
    "query": "Berapa tekanan ban loader di Pit A?",
    "top_k": 4
}).json()

print("Jawaban:", chat_res["data"]["answer"])
print("Sumber Terkait:", chat_res["data"]["sources"])

# 3. Tambahkan SOP / Koreksi Langsung ke Memori
mem_res = requests.post(f"{API_URL}/memory/learn", headers=HEADERS, json={
    "content": "Ban ukuran 29.5R25 merk Bridgestone digunakan khusus untuk Loader di Pit A.",
    "subject": "Spesifikasi Ban Pit A",
    "fact_type": "rule"
}).json()
print("Memory Ingested:", mem_res)`
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
          <span class="pill-badge">AnyDoc + pgvector + External DB</span>
        </div>
        <p class="page-subtitle">
          Basis pengetahuan cerdas untuk Chatbot: Konversi otomatis dokumen (Word, PDF, Excel, OCR) & sinkronisasi tabel database PostgreSQL eksternal ke vektor semantik untuk retrieval instan di Next.js.
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
          <span class="stat-val">Hero AI</span>
          <span class="stat-lbl">AI Assistant Engine</span>
        </div>
        <div class="stat-card redis-stat">
          <span class="stat-val">{{ redisStatus?.available ? '⚡ Connected' : '⚡ Redis Active' }}</span>
          <span class="stat-lbl">{{ redisStatus?.ping_ms ? `${redisStatus.ping_ms} ms Latency` : 'Fast Memory Cache' }}</span>
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
      <button :class="['tab-item', { active: mainTab === 'external_db' }]" @click="mainTab = 'external_db'">
        🗄️ External PostgreSQL Sync ({{ externalDatabases.length }})
      </button>
      <button :class="['tab-item', { active: mainTab === 'chat' }]" @click="mainTab = 'chat'">
        💬 RAG Chatbot Playground
      </button>
      <button :class="['tab-item', { active: mainTab === 'memory' }]" @click="mainTab = 'memory'">
        🧠 Memori & Self-Growth ({{ learnedFacts.length }})
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
          <button class="btn-primary" @click="mainTab = 'ingest'">+ Upload File</button>
          <button class="btn-secondary" @click="mainTab = 'external_db'; startNewDatabase()">+ Connect Database</button>
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
          <p>Unggah file dokumen atau hubungkan database PostgreSQL eksternal untuk mulai mengisi basis pengetahuan.</p>
          <div class="empty-actions">
            <button class="btn-primary" @click="mainTab = 'ingest'">Upload Dokumen</button>
            <button class="btn-secondary" @click="mainTab = 'external_db'">Koneksikan PostgreSQL</button>
          </div>
        </div>

        <table v-else class="library-table">
          <thead>
            <tr>
              <th>Dokumen</th>
              <th>Format</th>
              <th>Total Chunks</th>
              <th>Karakter / Kata</th>
              <th>Penyimpanan</th>
              <th>Waktu Dibuat</th>
              <th>Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in filteredDocuments" :key="doc.id">
              <td>
                <div class="doc-title-cell">
                  <span class="doc-name-row">
                    <span v-if="doc.filename.startsWith('db_')" class="db-indicator-icon">🗄️</span>
                    <strong>{{ doc.filename }}</strong>
                  </span>
                  <span class="doc-id-sub">ID: {{ doc.id.substring(0, 8) }}...</span>
                </div>
              </td>
              <td>
                <span :class="['badge-format', { 'db-format': doc.filename.startsWith('db_') }]">
                  {{ doc.filename.startsWith('db_') ? 'DB TABLE' : doc.format?.toUpperCase() }}
                </span>
              </td>
              <td>
                <span class="chunk-badge">{{ doc.total_chunks }} Chunks</span>
              </td>
              <td>
                {{ doc.char_count?.toLocaleString() }} / {{ doc.word_count?.toLocaleString() }}
              </td>
              <td>
                <a v-if="doc.s3_url || doc.local_url || doc.filename" :href="resolveDocUrl(doc)" target="_blank" rel="noopener" class="s3-btn" title="Buka / Download file dokumen">
                  <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                  Dokumen
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

          <!-- Active Progress Tracker Card -->
          <div v-if="isIngesting" class="ingest-progress-card">
            <div class="progress-header-row">
              <div class="progress-title-col">
                <span class="progress-step-title">
                  <span v-if="processingStage === 'uploading'">📤 Mengunggah Berkas ke Server...</span>
                  <span v-else-if="processingStage === 'converting'">📄 Mengekstrak Format & Tabel ke Markdown via AnyDoc...</span>
                  <span v-else-if="processingStage === 'storage'">☁️ Mengunggah Arsip Dokumen ke S3 Object Storage...</span>
                  <span v-else-if="processingStage === 'vectorizing'">🧠 Memotong Teks Semantik & Vektorisasi pgvector...</span>
                  <span v-else>⚙️ Memproses Dokumen...</span>
                </span>
                <span class="progress-stats-sub">{{ uploadStatsText || `${uploadProgressPercent}%` }}</span>
              </div>
              <div class="progress-timer-col">
                ⏱️ {{ elapsedSeconds }}s
              </div>
            </div>

            <!-- Animated Progress Bar -->
            <div class="progress-bar-track">
              <div 
                class="progress-bar-fill animated"
                :style="{ width: `${processingStage === 'uploading' ? (uploadProgressPercent || 5) : (processingStage === 'converting' ? 50 : (processingStage === 'storage' ? 75 : 92))}%` }"
              ></div>
            </div>

            <!-- Stage Steps Indicator -->
            <div class="stage-steps-list">
              <div :class="['stage-step', { done: processingStage !== 'uploading', active: processingStage === 'uploading' }]">
                <span class="stage-dot">{{ processingStage !== 'uploading' ? '✓' : '1' }}</span>
                <span>Upload File</span>
              </div>
              <div :class="['stage-step', { done: ['storage', 'vectorizing', 'completed'].includes(processingStage), active: processingStage === 'converting' }]">
                <span class="stage-dot">{{ ['storage', 'vectorizing', 'completed'].includes(processingStage) ? '✓' : '2' }}</span>
                <span>AnyDoc Markdown</span>
              </div>
              <div :class="['stage-step', { done: ['vectorizing', 'completed'].includes(processingStage), active: processingStage === 'storage' }]">
                <span class="stage-dot">{{ ['vectorizing', 'completed'].includes(processingStage) ? '✓' : '3' }}</span>
                <span>S3 Storage</span>
              </div>
              <div :class="['stage-step', { done: processingStage === 'completed', active: processingStage === 'vectorizing' }]">
                <span class="stage-dot">{{ processingStage === 'completed' ? '✓' : '4' }}</span>
                <span>pgvector Embed</span>
              </div>
            </div>

            <p class="large-file-hint">
              💡 <em>Dokumen berukuran besar diproses secara mendalam oleh AI engine. Mohon tetap berada di halaman ini hingga selesai.</em>
            </p>
          </div>

          <button 
            class="btn-submit" 
            :disabled="!ingestFile || isIngesting" 
            @click="handleIngest"
          >
            <span v-if="isIngesting" class="spinner"></span>
            <span v-if="isIngesting">Sedang Memproses Dokumen ({{ elapsedSeconds }}s)...</span>
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

    <!-- Tab 3: External PostgreSQL Database Sync (NEW) -->
    <div v-else-if="mainTab === 'external_db'" class="tab-content">
      <!-- Top Action Bar -->
      <div class="db-sync-header">
        <div>
          <h2 class="section-title">Koneksi Database PostgreSQL Eksternal</h2>
          <p class="section-desc">
            Hubungkan database PostgreSQL lain (ERP, Penjualan, CRM, Keuangan), pilih tabel mana saja yang ingin disinkronkan secara selektif dengan centang, lalu konversi ke RAG Knowledge Base.
          </p>
        </div>
        <div class="db-nav-actions">
          <button 
            :class="['btn-toggle-view', { active: dbViewMode === 'list' }]" 
            @click="dbViewMode = 'list'"
          >
            📋 Daftar Koneksi Tersimpan ({{ externalDatabases.length }})
          </button>
          <button 
            :class="['btn-toggle-view', { active: dbViewMode === 'form' }]" 
            @click="startNewDatabase"
          >
            ➕ Tambah Koneksi Database Baru
          </button>
        </div>
      </div>

      <!-- Sync Status Notification Banner -->
      <div v-if="syncStatusMessage" :class="['alert-box', `alert-${syncStatusMessage.type}`]">
        <div class="alert-content-row">
          <span>{{ syncStatusMessage.text }}</span>
          <button class="btn-close-alert" @click="syncStatusMessage = null">✕</button>
        </div>
      </div>

      <!-- Mode 1: List Saved Databases -->
      <div v-if="dbViewMode === 'list'" class="db-list-section">
        <div class="table-card">
          <div v-if="isLoadingDatabases" class="loading-state">
            <div class="spinner"></div>
            <span>Memuat daftar database eksternal...</span>
          </div>

          <div v-else-if="externalDatabases.length === 0" class="empty-library">
            <svg viewBox="0 0 24 24" width="48" height="48" stroke="#cbd5e1" stroke-width="1.5" fill="none"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
            <h3>Belum ada database eksternal yang terhubung</h3>
            <p>Tambahkan koneksi database PostgreSQL Anda untuk mulai mengambil data tabel secara selektif.</p>
            <button class="btn-primary" @click="startNewDatabase">+ Hubungkan Database Baru</button>
          </div>

          <table v-else class="library-table">
            <thead>
              <tr>
                <th>Nama Database</th>
                <th>Koneksi Host</th>
                <th>Tabel Terpilih</th>
                <th>Status</th>
                <th>Terakhir Disinkronkan</th>
                <th>Total Chunks</th>
                <th>Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="dbItem in externalDatabases" :key="dbItem.id">
                <td>
                  <div class="doc-title-cell">
                    <strong>{{ dbItem.name }}</strong>
                    <span class="doc-id-sub">{{ dbItem.database_name || 'PostgreSQL' }}</span>
                  </div>
                </td>
                <td>
                  <code class="db-url-pill">{{ dbItem.db_url }}</code>
                </td>
                <td>
                  <div class="selected-tables-tags">
                    <span v-for="tbl in dbItem.selected_tables" :key="tbl" class="table-tag">
                      🗄️ {{ tbl }}
                    </span>
                    <span v-if="!dbItem.selected_tables || dbItem.selected_tables.length === 0" class="text-muted">
                      Belum ada tabel
                    </span>
                  </div>
                </td>
                <td>
                  <span :class="['status-badge', dbItem.status]">
                    <span class="status-dot"></span>
                    {{ dbItem.status?.toUpperCase() }}
                  </span>
                </td>
                <td class="time-cell">
                  {{ dbItem.last_synced_at ? new Date(dbItem.last_synced_at).toLocaleString('id-ID') : 'Belum pernah' }}
                </td>
                <td>
                  <span class="chunk-badge">{{ dbItem.total_chunks_synced || 0 }} Chunks</span>
                </td>
                <td>
                  <div class="row-actions">
                    <button 
                      class="btn-sync-action" 
                      :disabled="isSyncingDb && syncingDbId === dbItem.id"
                      @click="handleSyncDatabase(dbItem)" 
                      title="Sinkronisasi data tabel sekarang"
                    >
                      <span v-if="isSyncingDb && syncingDbId === dbItem.id" class="spinner"></span>
                      <span v-else>⚡ Sync Now</span>
                    </button>
                    <button class="btn-inspect" @click="handleEditDatabase(dbItem)" title="Edit konfigurasi tabel">
                      ✏️ Edit
                    </button>
                    <button class="btn-delete" @click="handleDeleteDatabase(dbItem)" title="Hapus koneksi database">
                      🗑️
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Mode 2: Form Add / Edit Database Connection & Selective Tables Checklist -->
      <div v-else-if="dbViewMode === 'form'" class="db-form-section">
        <div class="form-and-tables-grid">
          <!-- Left Column: Database Connection Details -->
          <div class="card db-config-card">
            <h3 class="form-block-title">
              {{ dbForm.id ? '✏️ Edit Konfigurasi Database' : '➕ Konfigurasi Koneksi PostgreSQL' }}
            </h3>

            <div class="form-group">
              <label class="form-label">Nama Identifikasi Koneksi *</label>
              <input 
                type="text" 
                v-model="dbForm.name" 
                placeholder="Contoh: Database ERP Keuangan & Sales" 
                class="form-control"
              />
            </div>

            <div class="form-group">
              <label class="form-label">Format Input Koneksi</label>
              <div class="radio-row">
                <label class="radio-label">
                  <input type="radio" value="url" v-model="dbForm.inputType" />
                  <span>Connection String URL</span>
                </label>
                <label class="radio-label">
                  <input type="radio" value="params" v-model="dbForm.inputType" />
                  <span>Parameter Terpisah (Host/Port/DB/User/Pass)</span>
                </label>
              </div>
            </div>

            <!-- Input Type 1: URL -->
            <div v-if="dbForm.inputType === 'url'" class="form-group">
              <label class="form-label">PostgreSQL Connection String URL *</label>
              <input 
                type="text" 
                v-model="dbForm.dbUrl" 
                placeholder="postgresql://username:password@hostname:5432/database_name" 
                class="form-control font-mono"
              />
              <span class="help-text">Format: <code>postgresql://user:password@host:5432/dbname</code></span>
            </div>

            <!-- Input Type 2: Separate Params -->
            <div v-else class="params-grid">
              <div class="form-group">
                <label class="form-label">Host / IP *</label>
                <input type="text" v-model="dbForm.host" placeholder="localhost atau IP" class="form-control" />
              </div>
              <div class="form-group">
                <label class="form-label">Port</label>
                <input type="number" v-model="dbForm.port" placeholder="5432" class="form-control" />
              </div>
              <div class="form-group">
                <label class="form-label">Database Name *</label>
                <input type="text" v-model="dbForm.database" placeholder="nama_database" class="form-control" />
              </div>
              <div class="form-group">
                <label class="form-label">Username *</label>
                <input type="text" v-model="dbForm.username" placeholder="postgres" class="form-control" />
              </div>
              <div class="form-group full-width">
                <label class="form-label">Password *</label>
                <input type="password" v-model="dbForm.password" placeholder="••••••••" class="form-control" />
              </div>
            </div>

            <div class="db-test-actions">
              <button 
                class="btn-test-conn" 
                :disabled="isTestingDb || isIntrospecting" 
                @click="handleTestConnection"
              >
                <span v-if="isTestingDb" class="spinner"></span>
                <span v-else>🔌 Test Koneksi</span>
              </button>

              <button 
                class="btn-introspect" 
                :disabled="isIntrospecting || isTestingDb" 
                @click="handleIntrospectTables"
              >
                <span v-if="isIntrospecting" class="spinner"></span>
                <span v-else>🔍 Baca Daftar Tabel Database</span>
              </button>
            </div>

            <!-- Test Connection Result Alert -->
            <div v-if="testDbMessage" :class="['test-result-box', testDbMessage.success ? 'success' : 'error']">
              {{ testDbMessage.text }}
            </div>

            <div class="form-group mt-16">
              <label class="form-label">Batas Maksimal Baris per Tabel (Row Limit)</label>
              <input 
                type="number" 
                v-model="dbForm.maxRowsPerTable" 
                placeholder="500" 
                class="form-control"
              />
              <span class="help-text">Membatasi jumlah baris per tabel agar token AI tetap efisien (default: 500 baris).</span>
            </div>

            <div class="form-footer-actions">
              <button class="btn-cancel" @click="dbViewMode = 'list'">Batal</button>
              <button 
                class="btn-save-db" 
                :disabled="isSavingDb || isSyncingDb || selectedTables.length === 0" 
                @click="handleSaveDatabase"
              >
                <span v-if="isSavingDb || isSyncingDb" class="spinner"></span>
                <span v-else>💾 Simpan & Ingest {{ selectedTables.length }} Tabel ke RAG</span>
              </button>
            </div>
          </div>

          <!-- Right Column: Interactive Selective Tables Checklist -->
          <div class="card db-tables-card">
            <div class="tables-header-row">
              <div>
                <h3 class="form-block-title">Pilih Tabel yang Ingin Dijadikan RAG</h3>
                <span class="tables-sub">
                  Centang tabel yang relevan ({{ selectedTables.length }} dari {{ availableTables.length }} tabel dipilih).
                </span>
              </div>
              <div class="bulk-select-buttons" v-if="availableTables.length > 0">
                <button class="btn-bulk" @click="toggleSelectAllTables(true)">Pilih Semua</button>
                <button class="btn-bulk" @click="toggleSelectAllTables(false)">Batalkan Semua</button>
              </div>
            </div>

            <!-- Search Filter for Tables -->
            <div v-if="availableTables.length > 0" class="table-search-bar">
              <input 
                type="text" 
                v-model="tableSearchFilter" 
                placeholder="Cari nama tabel (contoh: 'customer', 'invoice')..." 
                class="table-search-input"
              />
            </div>

            <!-- Empty State when not loaded yet -->
            <div v-if="availableTables.length === 0 && !isIntrospecting" class="empty-tables-prompt">
              <div class="icon-circle">🔍</div>
              <h4>Daftar tabel belum dimuat</h4>
              <p>Klik tombol <strong>"Baca Daftar Tabel Database"</strong> di samping kiri untuk menampilkan seluruh tabel PostgreSQL yang tersedia.</p>
            </div>

            <!-- Loading Tables -->
            <div v-else-if="isIntrospecting" class="loading-tables-state">
              <div class="spinner dark"></div>
              <span>Membaca schema dan struktur tabel PostgreSQL...</span>
            </div>

            <!-- Checkbox List of Tables -->
            <div v-else class="tables-checklist-box">
              <div 
                v-for="tbl in filteredAvailableTables" 
                :key="tbl.table_name" 
                :class="['table-check-item', { selected: isTableSelected(tbl.table_name) }]"
                @click="toggleTableSelection(tbl.table_name)"
              >
                <div class="check-left">
                  <input 
                    type="checkbox" 
                    :checked="isTableSelected(tbl.table_name)" 
                    @click.stop="toggleTableSelection(tbl.table_name)"
                    class="checkbox-input"
                  />
                  <div class="table-meta-text">
                    <strong class="table-name-label">🗄️ {{ tbl.table_name }}</strong>
                    <span class="table-cols-sub">{{ tbl.columns_count }} kolom ({{ tbl.columns.map(c => c.name).slice(0, 4).join(', ') }}{{ tbl.columns_count > 4 ? '...' : '' }})</span>
                  </div>
                </div>

                <div class="check-right">
                  <span class="rows-count-badge">{{ tbl.estimated_rows.toLocaleString() }} baris</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 4: RAG Chatbot Playground -->
    <div v-else-if="mainTab === 'chat'" class="tab-content">
      <div class="chat-layout">
        <!-- Chat Main Panel -->
        <div class="chat-main card">
          <div class="chat-header">
            <div class="chat-title-box">
              <span class="status-indicator"></span>
              <div>
                <h3>RAG Knowledge Chatbot</h3>
                <span class="context-memory-sub">🧠 Basis Pengetahuan & Memori Aktif</span>
              </div>
            </div>
            <div class="chat-controls">
              <!-- Session Switcher -->
              <select :value="currentSessionId" @change="selectSession($event.target.value)" class="filter-select session-select" title="Pilih riwayat percakapan">
                <option :value="currentSessionId">💬 Sesi Aktif ({{ currentSessionId.slice(0, 10) }}...)</option>
                <option v-for="s in sessionsList" :key="s.id" :value="s.id">
                  {{ s.title }} ({{ s.message_count }} pesan)
                </option>
              </select>

              <select v-model="selectedDocFilter" class="filter-select">
                <option value="">Semua Dokumen Basis Pengetahuan</option>
                <option v-for="d in documents" :key="d.id" :value="d.id">{{ d.filename }}</option>
              </select>
              <button class="btn-clear-chat" @click="clearChat" title="Mulai percakapan baru">
                🧹 Percakapan Baru
              </button>
            </div>
          </div>

          <!-- Messages Scroll View -->
          <div class="messages-area">
            <div 
              v-for="(msg, idx) in chatMessages" 
              :key="msg.id || idx" 
              :class="['chat-bubble-wrap', msg.role]"
            >
              <div class="chat-bubble">
                <div class="bubble-sender">{{ msg.role === 'user' ? 'Anda' : 'Hero Assistant' }}</div>
                <div class="bubble-content" v-html="formatMarkdown(msg.content)"></div>

                <!-- Sources Footnote -->
                <div v-if="msg.sources && msg.sources.length > 0" class="sources-box">
                  <div class="sources-title">📎 Sumber Rujukan Dokumen / Database:</div>
                  <div class="sources-tags">
                    <span v-for="(s, sIdx) in getUniqueSources(msg.sources)" :key="sIdx" :class="['source-tag', { 'memory-source': s.source_type === 'memory' }]">
                      <span v-if="s.source_type === 'memory' || s.filename.includes('🧠')">🧠</span>
                      <span v-else-if="s.filename.startsWith('db_')">🗄️</span>
                      <span v-else>📄</span>
                      {{ s.filename }} <span v-if="s.heading">({{ s.heading }})</span> - Skor: {{ (s.similarity_score * 100).toFixed(0) }}%
                    </span>
                  </div>
                </div>

                <div v-if="msg.latency" class="bubble-latency">
                  <span v-if="msg.from_cache" class="cache-badge">⚡ Instant Cache Hit ({{ msg.latency }} ms)</span>
                  <span v-else>⏱️ {{ msg.latency }} ms</span>
                </div>

                <!-- Interactive Feedback & Self-Growth Bar -->
                <div v-if="msg.role === 'assistant' && msg.id" class="message-feedback-bar">
                  <div class="feedback-actions">
                    <button 
                      class="btn-feedback" 
                      :class="{ active: msg.rating === 1 }" 
                      @click="quickThumbsUp(msg)" 
                      title="Jawaban Akurat / Membantu"
                    >
                      👍
                    </button>
                    <button 
                      class="btn-feedback" 
                      :class="{ active: msg.rating === -1 }" 
                      @click="openFeedbackModal(msg, -1)" 
                      title="Jawaban Kurang Tepat"
                    >
                      👎
                    </button>
                    <button 
                      class="btn-feedback btn-correct" 
                      @click="openFeedbackModal(msg)" 
                      title="Beri Koreksi / Ajari AI"
                    >
                      ✏️ Koreksi / Ajari AI
                    </button>
                  </div>
                  <span v-if="msg.correction_text" class="correction-saved-tag">
                    ✅ Koreksi dipelajari AI
                  </span>
                </div>
              </div>
            </div>

            <div v-if="isGenerating" class="chat-bubble-wrap assistant">
              <div class="chat-bubble loading">
                <div class="typing-dots"><span></span><span></span><span></span></div>
                <span>Mencari jawaban dalam basis pengetahuan...</span>
              </div>
            </div>
          </div>

          <!-- Input Bar -->
          <div class="chat-input-bar">
            <input 
              type="text" 
              v-model="userPrompt" 
              placeholder="Tanyakan sesuatu tentang dokumen, database, atau beri instruksi baru..." 
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

    <!-- Tab 5: Memori & Self-Growth -->
    <div v-else-if="mainTab === 'memory'" class="tab-content">
      <div class="memory-container">
        <!-- Header Card -->
        <div class="card memory-header-card">
          <div class="memory-header-info">
            <h2 class="section-title">🧠 Memory History Manager</h2>
            <p class="section-desc">
              Semua pengetahuan yang dipelajari AI tersimpan di sini — otomatis dari koreksi pengguna maupun input manual. AI memprioritaskan memori ini di atas dokumen.
            </p>
          </div>
          <div class="memory-stats-grid">
            <div class="mem-stat-box">
              <span class="mem-stat-val">{{ learnedFacts.length }}</span>
              <span class="mem-stat-lbl">Total Memori</span>
            </div>
            <div class="mem-stat-box">
              <span class="mem-stat-val corr-val">{{ learnedFacts.filter(f => f.fact_type === 'user_correction').length }}</span>
              <span class="mem-stat-lbl">Koreksi (Auto-Save)</span>
            </div>
            <div class="mem-stat-box">
              <span class="mem-stat-val manual-val">{{ learnedFacts.filter(f => f.learned_from === 'direct_input').length }}</span>
              <span class="mem-stat-lbl">Manual</span>
            </div>
            <div class="mem-stat-box autosave-info-box" title="Koreksi otomatis dipelajari AI saat Anda memberikan feedback koreksi">
              <span class="autosave-pill active">
                <span class="autosave-dot"></span>
                ACTIVE
              </span>
              <span class="mem-stat-lbl">Auto-Save Koreksi</span>
            </div>
          </div>
        </div>

        <div class="memory-content-grid">
          <!-- Left: Input manual fakta baru -->
          <div class="card memory-form-card">
            <h3 class="form-block-title">💡 Ajari AI Fakta / Aturan Baru</h3>
            <p class="form-block-sub">Tambahkan informasi penting atau SOP langsung tanpa mengunggah berkas.</p>

            <div class="form-group">
              <label class="form-label">Tipe Memori</label>
              <select v-model="newFactForm.factType" class="form-control">
                <option value="learned_knowledge">💡 Pengetahuan / Fakta Operasional</option>
                <option value="rule">⚖️ Aturan / SOP Khusus</option>
                <option value="user_correction">✏️ Koreksi / Klarifikasi Data</option>
                <option value="preference">⚙️ Preferensi Sistem</option>
              </select>
            </div>

            <div class="form-group">
              <label class="form-label">Judul / Topik (Opsional)</label>
              <input type="text" v-model="newFactForm.subject" placeholder="Contoh: Kode Part Loader WA500" class="form-control" />
            </div>

            <div class="form-group">
              <label class="form-label">Isi Fakta / Aturan yang Harus Diingat AI *</label>
              <textarea
                v-model="newFactForm.content"
                rows="4"
                placeholder="Contoh: Ban ukuran 29.5R25 merk Bridgestone digunakan khusus untuk unit Wheel Loader Komatsu WA500 di Pit A."
                class="form-control"
              ></textarea>
            </div>

            <button class="btn-primary full-width" :disabled="isSavingFact || !newFactForm.content.trim()" @click="handleSaveNewFact">
              <span v-if="isSavingFact" class="spinner"></span>
              <span v-else>💾 Simpan ke Memori RAG</span>
            </button>
          </div>

          <!-- Right: Memory History Manager -->
          <div class="card memory-list-card">
            <!-- Toolbar row -->
            <div class="mem-toolbar">
              <div class="mem-toolbar-left">
                <h3 class="form-block-title" style="margin:0">📋 History Memori</h3>
                <span class="mem-count-badge">{{ filteredMemoryFacts.length }}</span>
              </div>
              <div class="mem-toolbar-right">
                <button
                  v-if="selectedFactIds.size > 0"
                  class="btn-bulk-delete"
                  :disabled="isBulkDeleting"
                  @click="handleBulkDelete"
                >
                  <span v-if="isBulkDeleting" class="spinner"></span>
                  <span v-else>🗑️ Hapus ({{ selectedFactIds.size }})</span>
                </button>
                <button class="btn-refresh" @click="fetchLearnedFacts">🔄</button>
              </div>
            </div>

            <!-- Tab Filter -->
            <div class="mem-tab-bar">
              <button :class="['mem-tab-btn', { active: memoryTab === 'all' }]" @click="memoryTab = 'all'; selectedFactIds = new Set()">Semua</button>
              <button :class="['mem-tab-btn corr', { active: memoryTab === 'correction' }]" @click="memoryTab = 'correction'; selectedFactIds = new Set()">✏️ Koreksi (Auto-Save)</button>
              <button :class="['mem-tab-btn manual', { active: memoryTab === 'manual' }]" @click="memoryTab = 'manual'; selectedFactIds = new Set()">💡 Manual</button>
            </div>

            <!-- Search -->
            <div class="mem-search-bar">
              <span class="mem-search-icon">🔍</span>
              <input
                type="text"
                v-model="memorySearchQuery"
                placeholder="Cari berdasarkan judul atau isi memori..."
                class="mem-search-input"
              />
              <button v-if="memorySearchQuery" class="mem-search-clear" @click="memorySearchQuery = ''">✕</button>
            </div>

            <!-- Select all row -->
            <div v-if="filteredMemoryFacts.length > 0" class="mem-select-all-row">
              <label class="mem-checkbox-label">
                <input type="checkbox" :checked="allFilteredSelected" @change="toggleSelectAll" />
                <span>Pilih Semua ({{ filteredMemoryFacts.length }})</span>
              </label>
            </div>

            <!-- Loading -->
            <div v-if="isLoadingFacts" class="loading-state">
              <div class="spinner"></div>
              <span>Memuat history memori...</span>
            </div>

            <!-- Empty -->
            <div v-else-if="filteredMemoryFacts.length === 0" class="empty-memory">
              <div class="empty-mem-icon">🧠</div>
              <p v-if="memoryTab === 'correction'">Belum ada koreksi tersimpan. Gunakan tombol ✏️ Koreksi pada jawaban chat untuk otomatis menyimpan.</p>
              <p v-else-if="memoryTab === 'manual'">Belum ada fakta manual. Gunakan form di samping kiri.</p>
              <p v-else>Belum ada memori yang dipelajari.</p>
            </div>

            <!-- Memory items -->
            <div v-else class="memory-items-list">
              <div
                v-for="fact in filteredMemoryFacts"
                :key="fact.id"
                class="memory-fact-card"
                :class="{ selected: selectedFactIds.has(fact.id) }"
                @click.self="toggleFactSelection(fact.id)"
              >
                <div class="fact-top-row">
                  <label class="mem-item-checkbox" @click.stop>
                    <input
                      type="checkbox"
                      :checked="selectedFactIds.has(fact.id)"
                      @change="toggleFactSelection(fact.id)"
                    />
                  </label>
                  <span :class="['fact-type-badge', fact.fact_type]">
                    {{ fact.fact_type === 'user_correction' ? '✏️ Koreksi' : fact.fact_type === 'rule' ? '⚖️ Aturan' : '💡 Manual' }}
                  </span>
                  <button class="btn-delete-fact" @click.stop="handleDeleteFact(fact.id)" title="Hapus dari memori">🗑️</button>
                </div>
                <h4 class="fact-subject">{{ fact.subject || 'Memori RAG' }}</h4>
                <p class="fact-content">{{ fact.content.length > 180 ? fact.content.slice(0, 180) + '…' : fact.content }}</p>
                <div class="fact-meta">
                  <span>{{ fact.learned_from === 'direct_input' ? 'Input manual' : 'Koreksi pengguna (Auto-Save)' }}</span>
                  <span v-if="fact.created_at">{{ new Date(fact.created_at).toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'short' }) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 5: Next.js & API Integration -->
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
          <h3>🔑 Panduan Konfigurasi RAG & LLM Engine</h3>
          <p>
            Raray Vision secara *default* sudah menjalankan <strong>FastEmbed ONNX (BAAI/bge-small-en-v1.5)</strong> yang <strong>100% GRATIS</strong> dan berjalan lokal di server tanpa memerlukan API Key eksternal apapun.
          </p>
          <p>
            Untuk mesin LLM Chatbot, sistem menggunakan **Groq API LPU (`qwen/qwen3.6-27b`)** yang memberikan respons ultra-cepat dan akurat.
          </p>
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

    <!-- Modal: Feedback & Koreksi AI (Self-Growth) -->
    <div v-if="showFeedbackModal" class="modal-overlay" @click.self="showFeedbackModal = false">
      <div class="modal-card feedback-modal">
        <div class="modal-header">
          <div>
            <h3>✏️ Koreksi Jawaban & Ajari AI (Self-Growth)</h3>
            <span class="modal-sub">AI akan mengingat fakta koreksi ini untuk pertanyaan berikutnya</span>
          </div>
          <button class="btn-close-modal" @click="showFeedbackModal = false">✕</button>
        </div>

        <div class="modal-body">
          <p class="feedback-modal-desc">
            Beri tahu AI jika ada informasi yang salah, kurang lengkap, atau aturan baru yang harus dipatuhi. Koreksi Anda akan diubah menjadi embedding semantik dan disimpan ke memori jangka panjang.
          </p>

          <div class="form-group">
            <label class="form-label">Rating Kualitas Jawaban</label>
            <div class="rating-btn-group">
              <button 
                type="button"
                :class="['btn-rate-choice', { active: feedbackRating === 1 }]" 
                @click="feedbackRating = 1"
              >
                👍 Bagus / Perlu Tambahan
              </button>
              <button 
                type="button"
                :class="['btn-rate-choice', { active: feedbackRating === -1 }]" 
                @click="feedbackRating = -1"
              >
                👎 Salah / Kurang Tepat
              </button>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Koreksi Jawaban / Fakta yang Benar *</label>
            <textarea 
              v-model="feedbackCorrection" 
              rows="4" 
              placeholder="Tuliskan fakta yang benar di sini. Contoh: Untuk permohonan material ganti ban, form yang digunakan adalah F-MAT-01 dan wajib ditandatangani oleh Site Supervisor..." 
              class="form-control"
            ></textarea>
          </div>

          <div class="form-group">
            <label class="form-label">Catatan Tambahan (Opsional)</label>
            <input 
              type="text" 
              v-model="feedbackNotes" 
              placeholder="Catatan evaluasi untuk sistem..." 
              class="form-control" 
            />
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-secondary" @click="showFeedbackModal = false">Batal</button>
          <button 
            class="btn-primary" 
            :disabled="isSubmittingFeedback || !feedbackCorrection.trim()" 
            @click="submitFeedbackAction"
          >
            <span v-if="isSubmittingFeedback" class="spinner"></span>
            <span v-else>🧠 Simpan & Ajarkan ke AI</span>
          </button>
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

.redis-stat .stat-val {
  color: #dc2626;
  font-size: 16px;
}

.cache-badge {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #bbf7d0;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 700;
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

.btn-secondary {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #0f172a;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-secondary:hover {
  background: #f1f5f9;
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

.doc-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.db-indicator-icon {
  font-size: 14px;
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

.badge-format.db-format {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.chunk-badge {
  background: #f1f5f9;
  color: #334155;
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
  align-items: center;
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

/* Ingest Progress Card */
.ingest-progress-card {
  background: #f8fafc;
  border: 1.5px solid #bfdbfe;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
}

.progress-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
}

.progress-title-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.progress-step-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #1e293b;
}

.progress-stats-sub {
  font-size: 11.5px;
  color: #2563eb;
  font-weight: 600;
}

.progress-timer-col {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  background: #e2e8f0;
  padding: 3px 8px;
  border-radius: 6px;
}

.progress-bar-track {
  width: 100%;
  height: 10px;
  background: #e2e8f0;
  border-radius: 9999px;
  overflow: hidden;
  margin-bottom: 14px;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #3b82f6, #60a5fa);
  border-radius: 9999px;
  transition: width 0.3s ease;
}

.progress-bar-fill.animated {
  background-size: 200% 100%;
  animation: progressShimmer 2s linear infinite;
}

@keyframes progressShimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.stage-steps-list {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

@media (max-width: 640px) {
  .stage-steps-list {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stage-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #64748b;
  font-weight: 600;
}

.stage-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #cbd5e1;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

.stage-step.active {
  color: #2563eb;
}

.stage-step.active .stage-dot {
  background: #2563eb;
  animation: pulseDot 1s infinite alternate;
}

.stage-step.done {
  color: #16a34a;
}

.stage-step.done .stage-dot {
  background: #16a34a;
}

@keyframes pulseDot {
  from { transform: scale(1); }
  to { transform: scale(1.15); }
}

.large-file-hint {
  font-size: 11px;
  color: #64748b;
  margin: 0;
  line-height: 1.4;
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

/* External Database Section Styles */
.db-sync-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 16px;
  flex-wrap: wrap;
}

.db-nav-actions {
  display: flex;
  gap: 8px;
}

.btn-toggle-view {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-toggle-view.active {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
}

.form-and-tables-grid {
  display: grid;
  grid-template-columns: 480px 1fr;
  gap: 24px;
}

@media (max-width: 1100px) {
  .form-and-tables-grid {
    grid-template-columns: 1fr;
  }
}

.form-block-title {
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 14px;
}

.form-group {
  margin-bottom: 14px;
}

.form-group.mt-16 {
  margin-top: 16px;
}

.form-label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 5px;
}

.form-control {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}

.form-control:focus {
  border-color: #2563eb;
}

.font-mono {
  font-family: monospace;
  font-size: 12px;
}

.radio-row {
  display: flex;
  gap: 16px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: #475569;
  cursor: pointer;
}

.params-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.params-grid .full-width {
  grid-column: span 2;
}

.help-text {
  font-size: 11px;
  color: #64748b;
  margin-top: 4px;
  display: block;
}

.db-test-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.btn-test-conn {
  flex: 1;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #1e293b;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.btn-introspect {
  flex: 1.5;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.test-result-box {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}

.test-result-box.success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #16a34a;
}

.test-result-box.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
}

.form-footer-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.btn-cancel {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 9px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-save-db {
  flex: 1;
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 9px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.btn-save-db:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Tables Checklist Column */
.tables-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  gap: 10px;
}

.tables-sub {
  font-size: 12px;
  color: #64748b;
}

.bulk-select-buttons {
  display: flex;
  gap: 6px;
}

.btn-bulk {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.table-search-bar {
  margin-bottom: 10px;
}

.table-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12.5px;
  outline: none;
}

.tables-checklist-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}

.table-check-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.15s;
}

.table-check-item:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.table-check-item.selected {
  background: #eff6ff;
  border-color: #2563eb;
}

.check-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.checkbox-input {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
  cursor: pointer;
}

.table-meta-text {
  display: flex;
  flex-direction: column;
}

.table-name-label {
  font-size: 13px;
  color: #0f172a;
}

.table-cols-sub {
  font-size: 11px;
  color: #64748b;
}

.rows-count-badge {
  background: #e2e8f0;
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
}

.empty-tables-prompt {
  text-align: center;
  padding: 50px 20px;
  color: #64748b;
}

.icon-circle {
  font-size: 32px;
  margin-bottom: 8px;
}

.loading-tables-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 12px;
  color: #64748b;
}

.spinner.dark {
  border-color: rgba(37,99,235,0.2);
  border-top-color: #2563eb;
}

.db-url-pill {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
}

.selected-tables-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.table-tag {
  background: #eff6ff;
  color: #1e40af;
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #dbeafe;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 9999px;
}

.status-badge.active { background: #f0fdf4; color: #15803d; }
.status-badge.syncing { background: #eff6ff; color: #2563eb; }
.status-badge.error { background: #fef2f2; color: #b91c1c; }

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.btn-sync-action {
  background: #0f172a;
  color: #ffffff;
  border: none;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-sync-action:hover {
  background: #1e293b;
}

.btn-sync-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.context-memory-sub {
  font-size: 11px;
  color: #16a34a;
  font-weight: 600;
}

.status-indicator {
  width: 8px;
  height: 8px;
  background: #10b981;
  border-radius: 50%;
}

.chat-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-select {
  padding: 6px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.btn-clear-chat {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-clear-chat:hover {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #b91c1c;
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

.alert-content-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-close-alert {
  background: none;
  border: none;
  font-size: 14px;
  cursor: pointer;
  opacity: 0.7;
}

.alert-error { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; }
.alert-success { background: #f0fdf4; border: 1px solid #bbf7d0; color: #16a34a; }
.alert-info { background: #eff6ff; border: 1px solid #bfdbfe; color: #1d4ed8; }

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

.empty-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

/* Chat Markdown Table Styles */
.chat-table-wrapper {
  overflow-x: auto;
  margin: 12px 0;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.chat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  text-align: left;
}

.chat-table th {
  background: #f8fafc;
  color: #334155;
  font-weight: 600;
  padding: 10px 14px;
  border-bottom: 2px solid #cbd5e1;
  border-right: 1px solid #f1f5f9;
  white-space: nowrap;
}

.chat-table th:last-child {
  border-right: none;
}

.chat-table td {
  padding: 8px 14px;
  border-bottom: 1px solid #f1f5f9;
  border-right: 1px solid #f8fafc;
  color: #475569;
}

.chat-table td:last-child {
  border-right: none;
}

.chat-table tbody tr:last-child td {
  border-bottom: none;
}

.chat-table tbody tr:nth-child(even) {
  background: #fafafa;
}

.chat-table tbody tr:hover {
  background: #f1f5f9;
}

/* Persistent Session Switcher */
.session-select {
  max-width: 200px;
  background: #f8fafc;
  font-weight: 600;
  border-color: #cbd5e1;
}

/* Learned Facts Box in Chat */
.learned-facts-box {
  margin-top: 10px;
  padding: 8px 12px;
  background: #fdf4ff;
  border: 1px solid #f5d0fe;
  border-radius: 8px;
}

.learned-title {
  font-size: 11px;
  font-weight: 700;
  color: #a21caf;
  margin-bottom: 4px;
}

.learned-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.learned-tag {
  background: #fae8ff;
  color: #86198f;
  border: 1px solid #f0abfc;
  font-size: 11.5px;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 600;
}

/* Message Feedback Bar */
.message-feedback-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #f1f5f9;
}

.feedback-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-feedback {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-feedback:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-feedback.active {
  background: #dbeafe;
  border-color: #3b82f6;
  font-weight: 700;
}

.btn-correct {
  color: #475569;
  font-weight: 600;
}

.btn-correct:hover {
  color: #2563eb;
  background: #eff6ff;
  border-color: #bfdbfe;
}

.correction-saved-tag {
  font-size: 11px;
  font-weight: 600;
  color: #16a34a;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Memori & Self-Growth Tab */
.memory-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.memory-header-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  background: linear-gradient(135deg, #ffffff 0%, #fdf4ff 100%);
  border-color: #f5d0fe;
}

.memory-header-info {
  max-width: 800px;
}

.memory-stats-grid {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.mem-stat-box {
  background: #ffffff;
  border: 1px solid #f0abfc;
  border-radius: 10px;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 110px;
}

.mem-stat-val {
  font-size: 20px;
  font-weight: 800;
  color: #a21caf;
}

.mem-stat-lbl {
  font-size: 11px;
  color: #701a75;
  font-weight: 600;
}

.memory-content-grid {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: 20px;
}

@media (max-width: 1024px) {
  .memory-content-grid {
    grid-template-columns: 1fr;
  }
}

.memory-form-card {
  height: fit-content;
}

.memory-list-card {
  min-height: 450px;
}

.memory-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.memory-items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.memory-fact-card {
  background: #fafafa;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  transition: all 0.15s;
}

.memory-fact-card:hover {
  border-color: #cbd5e1;
  background: #ffffff;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.04);
}

.fact-top-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.fact-type-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 9999px;
}

.fact-type-badge.user_correction {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
}

.fact-type-badge.rule {
  background: #e0e7ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
}

.fact-type-badge.learned_knowledge,
.fact-type-badge.preference {
  background: #fae8ff;
  color: #86198f;
  border: 1px solid #f0abfc;
}

.btn-delete-fact {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.btn-delete-fact:hover {
  opacity: 1;
}

.fact-subject {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 6px;
}

.fact-content {
  font-size: 13px;
  color: #334155;
  margin: 0 0 8px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.fact-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #94a3b8;
}

.empty-memory {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
  font-size: 13.5px;
}

/* Feedback Modal Styles */
.feedback-modal {
  max-width: 550px;
}

.feedback-modal-desc {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 16px;
  line-height: 1.5;
}

.rating-btn-group {
  display: flex;
  gap: 10px;
}

.btn-rate-choice {
  flex: 1;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  font-size: 12.5px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-rate-choice:hover {
  background: #e2e8f0;
}

.btn-rate-choice.active {
  background: #eff6ff;
  border-color: #2563eb;
  color: #1d4ed8;
  font-weight: 700;
}

/* ── Memory History Manager ─────────────────── */

/* Stat value color variants */
.mem-stat-val.auto-val   { color: #0d9488; }
.mem-stat-val.corr-val   { color: #b45309; }
.mem-stat-val.manual-val { color: #6d28d9; }

/* Auto-Save Toggle Box */
.autosave-toggle-box {
  cursor: pointer;
  transition: background 0.15s;
  user-select: none;
}
.autosave-toggle-box:hover { background: #f0fdf4; border-color: #86efac; }

.autosave-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 9999px;
  background: #fee2e2;
  color: #b91c1c;
  transition: all 0.2s;
}
.autosave-pill.active {
  background: #dcfce7;
  color: #15803d;
}
.autosave-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  display: inline-block;
}

/* Auto-save toast */
.auto-save-toast {
  position: fixed;
  top: 72px;
  right: 24px;
  z-index: 9999;
  background: #1e293b;
  color: #f1f5f9;
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  pointer-events: none;
}
.toast-fade-enter-active, .toast-fade-leave-active { transition: all 0.3s ease; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translateY(-8px); }

/* Toolbar */
.mem-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  gap: 10px;
  flex-wrap: wrap;
}
.mem-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.mem-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mem-count-badge {
  background: #e2e8f0;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 9999px;
}

/* Tab filter bar */
.mem-tab-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.mem-tab-btn {
  padding: 5px 13px;
  border-radius: 9999px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}
.mem-tab-btn:hover { background: #e2e8f0; }
.mem-tab-btn.active { background: #0f172a; color: #fff; border-color: #0f172a; }
.mem-tab-btn.auto.active   { background: #0f766e; border-color: #0f766e; }
.mem-tab-btn.corr.active   { background: #b45309; border-color: #b45309; }
.mem-tab-btn.manual.active { background: #6d28d9; border-color: #6d28d9; }

/* Search bar */
.mem-search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px 12px;
  margin-bottom: 12px;
  transition: border-color 0.15s;
}
.mem-search-bar:focus-within { border-color: #94a3b8; }
.mem-search-icon { font-size: 14px; opacity: 0.5; }
.mem-search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13px;
  color: #334155;
}
.mem-search-clear {
  background: none;
  border: none;
  cursor: pointer;
  color: #94a3b8;
  font-size: 13px;
  padding: 0;
  line-height: 1;
}
.mem-search-clear:hover { color: #475569; }

/* Select all row */
.mem-select-all-row {
  padding: 6px 4px;
  margin-bottom: 10px;
  border-bottom: 1px solid #f0f4f8;
}
.mem-checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
}
.mem-checkbox-label input { cursor: pointer; accent-color: #0f172a; }

/* Per-item checkbox */
.mem-item-checkbox {
  cursor: pointer;
  display: flex;
  align-items: center;
}
.mem-item-checkbox input { accent-color: #0f172a; cursor: pointer; }

/* Selected card state */
.memory-fact-card.selected {
  border-color: #94a3b8;
  background: #f0f9ff;
  box-shadow: 0 0 0 2px #bfdbfe;
}

/* Fact top row with checkbox */
.fact-top-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

/* Badge for auto_chat type */
.fact-type-badge.auto_chat {
  background: #ccfbf1;
  color: #0f766e;
  border: 1px solid #99f6e4;
}

/* Bulk delete button */
.btn-bulk-delete {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  color: #b91c1c;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-bulk-delete:hover:not(:disabled) {
  background: #fee2e2;
  border-color: #f87171;
}
.btn-bulk-delete:disabled { opacity: 0.6; cursor: not-allowed; }

/* Empty memory icon */
.empty-mem-icon {
  font-size: 40px;
  margin-bottom: 10px;
}

</style>

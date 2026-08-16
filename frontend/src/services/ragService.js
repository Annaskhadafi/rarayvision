import { API_BASE_URL } from '../utils'

export const ragService = {
  getAuthHeaders() {
    const token = localStorage.getItem('rarayvision-token')
    return token ? { 'Authorization': `Bearer ${token}` } : {}
  },

  async _handleResponse(res) {
    const text = await res.text()
    let data
    try {
      data = JSON.parse(text)
    } catch {
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status} (${res.statusText || 'Bad Gateway'}). Backend service is starting up or unreachable.`)
      }
      throw new Error('Invalid response format from server.')
    }
    if (!res.ok) {
      throw new Error(data.detail || data.message || `Request failed with status ${res.status}`)
    }
    return data
  },

  async getInfo() {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/info`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async getDocuments(skip = 0, limit = 50) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/documents?skip=${skip}&limit=${limit}`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async getDocumentChunks(documentId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/documents/${documentId}/chunks`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async deleteDocument(documentId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/documents/${documentId}`, {
      method: 'DELETE',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  ingest(file, { autoOcr = true, forceOcr = false, formatOverride = '' } = {}, onUploadProgress = null) {
    return new Promise((resolve, reject) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('auto_ocr', autoOcr ? 'true' : 'false')
      formData.append('force_ocr', forceOcr ? 'true' : 'false')
      if (formatOverride) {
        formData.append('format_override', formatOverride)
      }

      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${API_BASE_URL}/api/v1/rag/ingest`)

      const headers = this.getAuthHeaders()
      for (const [key, value] of Object.entries(headers)) {
        xhr.setRequestHeader(key, value)
      }

      if (onUploadProgress && xhr.upload) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            const percent = Math.round((event.loaded / event.total) * 100)
            onUploadProgress(percent, event.loaded, event.total)
          }
        }
      }

      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText)
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(data)
          } else {
            reject(new Error(data.detail || data.message || `Request failed with status ${xhr.status}`))
          }
        } catch {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve({ status: 'success' })
          } else {
            reject(new Error(`Server returned HTTP ${xhr.status} (${xhr.statusText || 'Bad Gateway'}).`))
          }
        }
      }

      xhr.onerror = () => {
        reject(new Error('Network error saat mengunggah file dokumen.'))
      }

      xhr.ontimeout = () => {
        reject(new Error('Upload timeout: Koneksi terputus saat memproses dokumen.'))
      }

      xhr.send(formData)
    })
  },

  async search({ query, topK = 4, documentId = null }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({
        query,
        top_k: topK,
        document_id: documentId
      })
    })
    return this._handleResponse(res)
  },

  async chat({ query, messages = null, sessionId = null, topK = 4, documentId = null, systemPrompt = null }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({
        query,
        messages,
        session_id: sessionId,
        top_k: topK,
        document_id: documentId,
        system_prompt: systemPrompt
      })
    })
    return this._handleResponse(res)
  },

  async getRedisStatus() {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/redis/status`, {
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async getChatSessionHistory(sessionId, limit = 15) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/chat/session/${sessionId}/history?limit=${limit}`, {
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async clearChatSession(sessionId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/chat/session/${sessionId}`, {
      method: 'DELETE',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  // External PostgreSQL Database Endpoints
  async testDatabaseConnection(dbUrl) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases/test`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({ db_url: dbUrl })
    })
    return this._handleResponse(res)
  },

  async introspectDatabaseSchema(dbUrl) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases/introspect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({ db_url: dbUrl })
    })
    return this._handleResponse(res)
  },

  async getExternalDatabases() {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async createExternalDatabase(payload) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify(payload)
    })
    return this._handleResponse(res)
  },

  async updateExternalDatabase(id, payload) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases/${id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify(payload)
    })
    return this._handleResponse(res)
  },

  async deleteExternalDatabase(id) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases/${id}`, {
      method: 'DELETE',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async syncExternalDatabase(id, payload = {}) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/databases/${id}/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify(payload)
    })
    return this._handleResponse(res)
  }
}

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

  async ingest(file, { autoOcr = true, forceOcr = false, formatOverride = '' } = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('auto_ocr', autoOcr ? 'true' : 'false')
    formData.append('force_ocr', forceOcr ? 'true' : 'false')
    if (formatOverride) {
      formData.append('format_override', formatOverride)
    }

    const res = await fetch(`${API_BASE_URL}/api/v1/rag/ingest`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
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

  async chat({ query, topK = 4, documentId = null, systemPrompt = null }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/rag/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({
        query,
        top_k: topK,
        document_id: documentId,
        system_prompt: systemPrompt
      })
    })
    return this._handleResponse(res)
  }
}

import { API_BASE_URL } from '../utils'

export const pdfInspectorService = {
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

  async process(file, pages = '', autoOcr = true) {
    const formData = new FormData()
    formData.append('file', file)
    if (pages) formData.append('pages', pages)
    formData.append('auto_ocr', autoOcr ? 'true' : 'false')

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/process`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async ocrScanned(file, pages = '') {
    const formData = new FormData()
    formData.append('file', file)
    if (pages) formData.append('pages', pages)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/ocr-scanned`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async classify(file) {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/classify`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async extractText(file) {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/extract-text`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async extractMarkdown(file, pages = '') {
    const formData = new FormData()
    formData.append('file', file)
    if (pages) formData.append('pages', pages)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/extract-markdown`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async extractPositions(file) {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/extract-positions`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async extractStructure(file) {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_BASE_URL}/api/v1/pdf-inspector/extract-structure`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  }
}

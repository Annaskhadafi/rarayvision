import { API_BASE_URL } from '../utils'

export const anydocService = {
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

  async getSupportedFormats() {
    const res = await fetch(`${API_BASE_URL}/api/v1/anydoc/supported-formats`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async convert(file, { autoOcr = true, forceOcr = false, formatOverride = '' } = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('auto_ocr', autoOcr ? 'true' : 'false')
    formData.append('force_ocr', forceOcr ? 'true' : 'false')
    if (formatOverride) {
      formData.append('format_override', formatOverride)
    }

    const res = await fetch(`${API_BASE_URL}/api/v1/anydoc/convert`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async convertUrl({ url, autoOcr = true, forceOcr = false, formatOverride = '' } = {}) {
    const res = await fetch(`${API_BASE_URL}/api/v1/anydoc/convert-url`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders()
      },
      body: JSON.stringify({
        url,
        auto_ocr: autoOcr,
        force_ocr: forceOcr,
        format_override: formatOverride || null
      })
    })
    return this._handleResponse(res)
  },

  async batchConvert(files, { autoOcr = true } = {}) {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    formData.append('auto_ocr', autoOcr ? 'true' : 'false')

    const res = await fetch(`${API_BASE_URL}/api/v1/anydoc/batch`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  }
}

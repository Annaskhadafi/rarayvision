import { API_BASE_URL } from '../utils'

export const antiSpoofService = {
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

  async getModels() {
    const res = await fetch(`${API_BASE_URL}/api/v1/anti-spoof/models`, {
      method: 'GET',
      headers: this.getAuthHeaders()
    })
    return this._handleResponse(res)
  },

  async compare(file) {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_BASE_URL}/api/v1/anti-spoof/compare`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  },

  async predictSingle(file, modelKey = 'uniface_v2') {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('model_key', modelKey)

    const res = await fetch(`${API_BASE_URL}/api/v1/anti-spoof/predict`, {
      method: 'POST',
      headers: this.getAuthHeaders(),
      body: formData
    })
    return this._handleResponse(res)
  }
}

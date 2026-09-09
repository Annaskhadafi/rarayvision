import { API_BASE_URL } from '../utils'

export const forecastingService = {
  authHeaders() {
    const token = localStorage.getItem('rarayvision-token')
    return token ? { Authorization: `Bearer ${token}` } : {}
  },

  async request(path, body) {
    const response = await fetch(`${API_BASE_URL}/api/v1/forecasting/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...this.authHeaders() },
      body: JSON.stringify(body)
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || data.message || `Request gagal (${response.status})`)
    return data
  },

  inspectSchema(dbUrl) {
    return this.request('schema', { db_url: dbUrl })
  },

  forecast(payload) {
    return this.request('forecast', payload)
  }
}

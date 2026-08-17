import { API_BASE_URL } from '../utils'

export const automlService = {
  /**
   * Fetches realistic preset datasets (Sales, Inventory, Attendance)
   */
  async getPresets() {
    const res = await fetch(`${API_BASE_URL}/api/v1/automl/presets`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Gagal memuat preset dataset.')
    }
    return await res.json()
  },

  /**
   * Sends raw tabular JSON array to AutoML pipeline
   */
  async analyzeData(payload) {
    const res = await fetch(`${API_BASE_URL}/api/v1/automl/analyze-and-predict`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Gagal menganalisis data.')
    }
    return await res.json()
  },

  /**
   * Uploads CSV file to AutoML pipeline
   */
  async uploadCsv(formData) {
    const res = await fetch(`${API_BASE_URL}/api/v1/automl/upload-csv`, {
      method: 'POST',
      body: formData
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Gagal memproses file CSV.')
    }
    return await res.json()
  },

  /**
   * Returns standalone widget URL
   */
  getWidgetUrl(jobId) {
    return `${API_BASE_URL}/api/v1/automl/widget/${jobId}`
  }
}

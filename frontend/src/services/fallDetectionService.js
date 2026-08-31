import { API_BASE_URL } from '../utils'

export const fallDetectionService = {
  /**
   * Mengirim frame gambar atau base64 snapshot ke backend untuk deteksi jatuh
   */
  async analyzeFrame({ file = null, imageBase64 = null, angleThreshold = 45.0, ratioThreshold = 1.05, autoLog = false }) {
    const token = localStorage.getItem('rarayvision-token')
    const formData = new FormData()

    if (file) {
      formData.append('file', file)
    }
    if (imageBase64) {
      formData.append('image_base64', imageBase64)
    }
    formData.append('angle_threshold', angleThreshold)
    formData.append('ratio_threshold', ratioThreshold)
    formData.append('auto_log', autoLog)

    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/fall-detection/analyze-frame`, {
        method: 'POST',
        headers,
        body: formData
      })
      const json = await res.json()
      return json.success ? json.data : null
    } catch (err) {
      console.error('[FallDetectionService] Frame analysis failed:', err)
      return null
    }
  },

  /**
   * Mengunggah file video CCTV/MP4 untuk audit komprehensif kejadian jatuh
   */
  async analyzeVideo({ file, angleThreshold = 45.0, ratioThreshold = 1.05, autoLog = true }) {
    const token = localStorage.getItem('rarayvision-token')
    const formData = new FormData()
    formData.append('file', file)
    formData.append('angle_threshold', angleThreshold)
    formData.append('ratio_threshold', ratioThreshold)
    formData.append('auto_log', autoLog)

    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/fall-detection/analyze-video`, {
        method: 'POST',
        headers,
        body: formData
      })
      const json = await res.json()
      return json.success ? json.data : null
    } catch (err) {
      console.error('[FallDetectionService] Video analysis failed:', err)
      return null
    }
  },

  /**
   * Mengambil riwayat insiden jatuh yang tercatat di sistem K3
   */
  async getIncidents(page = 1, limit = 20) {
    const token = localStorage.getItem('rarayvision-token')
    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/fall-detection/incidents?page=${page}&limit=${limit}`, {
        headers
      })
      return await res.json()
    } catch (err) {
      console.error('[FallDetectionService] Get incidents failed:', err)
      return { success: false, items: [], total: 0 }
    }
  },

  /**
   * Mencatat insiden jatuh terkonfirmasi secara manual atau via event stream
   */
  async logIncident(payload) {
    const token = localStorage.getItem('rarayvision-token')
    const headers = { 'Content-Type': 'application/json' }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/fall-detection/log-incident`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      })
      return await res.json()
    } catch (err) {
      console.error('[FallDetectionService] Manual log failed:', err)
      return null
    }
  },

  /**
   * Menghapus catatan insiden dari database
   */
  async deleteIncident(incidentId) {
    const token = localStorage.getItem('rarayvision-token')
    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/fall-detection/incidents/${incidentId}`, {
        method: 'DELETE',
        headers
      })
      return res.ok
    } catch (err) {
      console.error('[FallDetectionService] Delete incident failed:', err)
      return false
    }
  }
}

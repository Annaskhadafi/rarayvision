import { API_BASE_URL } from '../utils'

export const cameraService = {
  async getCameras() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cameras`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      return data.success ? data.data : []
    } catch (err) {
      console.error(err)
      return []
    }
  },

  async addCamera(payload) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cameras`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async updateCamera(id, payload) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cameras/${id}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async deleteCamera(id) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cameras/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      return res.ok
    } catch (err) {
      console.error(err)
      return false
    }
  },

  async testConnection(streamUrl) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cameras/test-connection`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ stream_url: streamUrl })
      })
      const data = await res.json()
      return data.data
    } catch (err) {
      console.error(err)
      return { online: false, message: 'Gagal menguji koneksi.' }
    }
  },

  getFeedUrl(cameraId) {
    return `${API_BASE_URL}/api/v1/cameras/${cameraId}/feed`
  }
}

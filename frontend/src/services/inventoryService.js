import { API_BASE_URL } from '../utils'

export const inventoryService = {
  async getConfig() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/config`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async updateConfig(payload) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/config`, {
        method: 'PATCH',
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

  async countBoxes(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/count-boxes`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async defectCheck(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/defect-check`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async shelfOccupancy(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/shelf-occupancy`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async getHistory(page = 1, scanType = '') {
    const token = localStorage.getItem('rarayvision-token')
    try {
      let url = `${API_BASE_URL}/api/v1/inventory/history?page=${page}&limit=20`
      if (scanType) url += `&scan_type=${scanType}`
      const res = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      return await res.json()
    } catch (err) {
      console.error(err)
      return { success: false, items: [], total: 0 }
    }
  },

  async deleteHistory(scanId) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/inventory/history/${scanId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      return res.ok
    } catch (err) {
      console.error(err)
      return false
    }
  }
}

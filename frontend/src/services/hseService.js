import { API_BASE_URL } from '../utils'

export const hseService = {
  async getConfig() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/config`, {
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
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/config`, {
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

  async getZones() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/zones`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      return data.success ? data.data : []
    } catch (err) {
      console.error(err)
      return []
    }
  },

  async batchSyncZones(zonesList) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/zones/batch`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(zonesList)
      })
      const data = await res.json()
      return data.success
    } catch (err) {
      console.error(err)
      return false
    }
  },

  async getPpeRules() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/ppe-rules`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      return data.success ? data.data : null
    } catch (err) {
      console.error(err)
      return null
    }
  },

  async updatePpeRules(payload) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/ppe-rules`, {
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

  async ppeCheck(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/ppe-check`, {
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

  async dangerZoneAlert(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/danger-zone-alert`, {
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

  async nearMissLog(formData) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/near-miss-log`, {
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

  async getIncidents(page = 1, severity = '') {
    const token = localStorage.getItem('rarayvision-token')
    try {
      let url = `${API_BASE_URL}/api/v1/hse/incidents?page=${page}&limit=20`
      if (severity) url += `&severity=${severity}`
      const res = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      return await res.json()
    } catch (err) {
      console.error(err)
      return { success: false, items: [], total: 0 }
    }
  },

  async deleteIncident(incidentId) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/hse/incidents/${incidentId}`, {
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

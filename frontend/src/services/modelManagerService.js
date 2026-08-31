import { API_BASE_URL } from '../utils'

const getHeaders = () => {
  const token = localStorage.getItem('rarayvision-token')
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  }
}

const handleResponse = async (res) => {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errJson = await res.json()
      detail = errJson.detail || detail
    } catch {}
    return { success: false, error: detail }
  }
  return res.json()
}

export const modelManagerService = {
  /**
   * Get all registered AI models with their status and RAM info.
   */
  async getModels() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models`, {
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error('modelManagerService.getModels error:', e)
      return null
    }
  },

  /**
   * Load a specific model into RAM.
   * @param {string} modelId
   */
  async loadModel(modelId) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/load`, {
        method: 'POST',
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error(`modelManagerService.loadModel(${modelId}) error:`, e)
      return { success: false, error: e.message }
    }
  },

  /**
   * Unload a specific model from RAM.
   * @param {string} modelId
   */
  async unloadModel(modelId) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/unload`, {
        method: 'POST',
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error(`modelManagerService.unloadModel(${modelId}) error:`, e)
      return { success: false, error: e.message }
    }
  },

  /**
   * Load all registered models into RAM.
   */
  async loadAll() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/batch/load-all`, {
        method: 'POST',
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error('modelManagerService.loadAll error:', e)
      return { success: false, error: e.message }
    }
  },

  /**
   * Unload all models from RAM.
   */
  async unloadAll() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/batch/unload-all`, {
        method: 'POST',
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error('modelManagerService.unloadAll error:', e)
      return { success: false, error: e.message }
    }
  },

  /**
   * Unload only currently loaded models.
   */
  async unloadUnused() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/batch/unload-unused`, {
        method: 'POST',
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error('modelManagerService.unloadUnused error:', e)
      return { success: false, error: e.message }
    }
  },

  /**
   * Get real-time system RAM statistics.
   */
  async getSystemRam() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/models/system/ram`, {
        headers: getHeaders()
      })
      return handleResponse(res)
    } catch (e) {
      console.error('modelManagerService.getSystemRam error:', e)
      return null
    }
  },
}

import { API_BASE_URL } from '../utils'

const authHeaders = () => ({
  Authorization: `Bearer ${localStorage.getItem('rarayvision-token')}`
})

export const fireService = {
  async getModel() {
    const response = await fetch(`${API_BASE_URL}/api/v1/fire/model`, { headers: authHeaders() })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Model Fire tidak tersedia')
    return data.data
  },

  async detect(file, confidence, iou) {
    const formData = new FormData()
    formData.append('image', file)
    formData.append('confidence', confidence)
    formData.append('iou', iou)
    const response = await fetch(`${API_BASE_URL}/api/v1/fire/detect`, {
      method: 'POST',
      headers: authHeaders(),
      body: formData
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Deteksi Fire gagal')
    return data.data
  }
}

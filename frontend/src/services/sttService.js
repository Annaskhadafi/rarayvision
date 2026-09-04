import { API_BASE_URL } from '../utils'

const authHeaders = () => ({
  Authorization: `Bearer ${localStorage.getItem('rarayvision-token')}`
})

const readResponse = async (response, fallback) => {
  const body = await response.text()
  let data
  try { data = body ? JSON.parse(body) : {} }
  catch { throw new Error(`${response.status} ${response.statusText}: ${body.slice(0, 120) || fallback}`) }
  if (!response.ok) throw new Error(data.detail || fallback)
  return data
}

export const sttService = {
  async transcribe(blob) {
    const body = new FormData()
    body.append('file', blob, 'voice.webm')
    const response = await fetch(`${API_BASE_URL}/api/v1/stt/transcriptions`, {
      method: 'POST', headers: authHeaders(), body
    })
    const data = await readResponse(response, 'Transkripsi gagal')
    return data.result
  },

  async benchmark(blob, models) {
    const body = new FormData()
    body.append('file', blob, blob.name || 'sample.webm')
    body.append('models', JSON.stringify(models))
    const response = await fetch(`${API_BASE_URL}/api/v1/stt/benchmark`, {
      method: 'POST', headers: authHeaders(), body
    })
    const data = await readResponse(response, 'Benchmark gagal')
    return data.results || []
  },

  async config() {
    const response = await fetch(`${API_BASE_URL}/api/v1/stt/config`, { headers: authHeaders() })
    return (await readResponse(response, 'Konfigurasi STT gagal dimuat')).config
  },

  async updateConfig(config) {
    const body = new FormData()
    Object.entries(config).forEach(([key, value]) => body.append(key, value))
    const response = await fetch(`${API_BASE_URL}/api/v1/stt/config`, {
      method: 'PATCH', headers: authHeaders(), body
    })
    const data = await readResponse(response, 'Konfigurasi gagal disimpan')
    return data.config
  },

  async models() {
    const response = await fetch(`${API_BASE_URL}/api/v1/stt/models`, { headers: authHeaders() })
    return (await readResponse(response, 'Daftar model STT gagal dimuat')).models || []
  }
}

import { API_BASE_URL } from '../utils'
import { store } from '../store'

export const authService = {
  async login(email, password) {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    })
    const data = await res.json()
    if (res.ok && data.token) {
      localStorage.setItem('rarayvision-token', data.token)
      store.isLoggedIn = true
      return { success: true }
    }
    return { success: false, error: data.detail || 'Invalid credentials' }
  },

  async register(email, password, name) {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name })
    })
    const data = await res.json()
    if (res.ok && data.status === 'success') return { success: true }
    return { success: false, error: data.detail || 'Registration failed' }
  },

  async loginWithFace(blob) {
    const formData = new FormData()
    formData.append('file', blob, 'face.jpg')
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/login-face`, {
      method: 'POST',
      body: formData
    })
    const data = await res.json()
    if (res.ok && data.status === 'success') {
      localStorage.setItem('rarayvision-token', data.token)
      store.isLoggedIn = true
      return { success: true }
    }
    return { success: false, error: data.detail || 'Face recognition failed' }
  },

  async googleLogin(credential) {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential })
    })
    const data = await res.json()
    if (res.ok && data.token) {
      localStorage.setItem('rarayvision-token', data.token)
      store.isLoggedIn = true
      return { success: true }
    }
    return { success: false, error: data.detail || 'Google login failed' }
  },

  async fetchMe() {
    const token = localStorage.getItem('rarayvision-token')
    if (!token) return { success: false }
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (!res.ok) throw new Error('Failed to fetch user')
      const data = await res.json()
      if (data.status === 'success') {
        store.user = data.user
        return { success: true }
      }
    } catch {
      return { success: false }
    }
  },

  async getRegisteredUsers() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/registered-users`)
      if (!res.ok) throw new Error('Failed to fetch registered users')
      const data = await res.json()
      if (data.status === 'success') {
        return { success: true, users: data.users }
      }
      return { success: false, users: [] }
    } catch {
      return { success: false, users: [] }
    }
  },

  async fetchUsers() {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/users`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        return { success: true, users: data.users }
      }
      return { success: false, error: data.detail || 'Failed to fetch users' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  async createUser(name, email, password) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/users`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ name, email, password })
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        return { success: true, user: data.user }
      }
      return { success: false, error: data.detail || 'Failed to create user' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  async updateUser(userId, name, email) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/users/${userId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ name, email })
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        return { success: true, user: data.user }
      }
      return { success: false, error: data.detail || 'Failed to update user' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  async deleteUser(userId) {
    const token = localStorage.getItem('rarayvision-token')
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        return { success: true }
      }
      return { success: false, error: data.detail || 'Failed to delete user' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  async checkHealth() {
    try {
      store.isChecking = true
      const res = await fetch(`${API_BASE_URL}/health`)
      if (!res.ok) throw new Error('HTTP ' + res.status)
      store.apiStatus = 'Online'
      store.apiStatusDetail = 'Raray Vision API'
    } catch {
      store.apiStatus = 'Offline'
      store.apiStatusDetail = 'Unable to connect to backend'
    } finally {
      store.isChecking = false
    }
  },

  logout() { store.logout() }
}

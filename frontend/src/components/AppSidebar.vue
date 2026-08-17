<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { store } from '../store'
import { authService } from '../services/authService'
import { API_BASE_URL } from '../utils'
import logoImage from '../assets/logo.png'

const emit = defineEmits(['toggle'])
const router = useRouter()
const route = useRoute()

const isCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
const showLogoutModal = ref(false)
const isLoggingOut = ref(false)
const showDocsMenu = ref(false)

// Collapsible state for each menu group (default all expanded)
const collapsedGroups = ref(JSON.parse(localStorage.getItem('sidebar_groups_collapsed') || '{}'))

const toggleSidebar = () => {
  isCollapsed.value = !isCollapsed.value
  localStorage.setItem('sidebar_collapsed', isCollapsed.value)
  emit('toggle', isCollapsed.value)
}

const toggleGroup = (groupKey) => {
  if (isCollapsed.value) return
  collapsedGroups.value[groupKey] = !collapsedGroups.value[groupKey]
  localStorage.setItem('sidebar_groups_collapsed', JSON.stringify(collapsedGroups.value))
}

onMounted(() => {
  emit('toggle', isCollapsed.value)
})

const goTo = (path) => {
  router.push(path)
}

const confirmLogout = () => {
  isLoggingOut.value = true
  setTimeout(() => {
    authService.logout()
    showLogoutModal.value = false
    isLoggingOut.value = false
    router.push('/')
  }, 600)
}

const menuGroups = [
  {
    key: 'main',
    title: 'Main & Live',
    items: [
      {
        name: 'Dashboard',
        path: '/dashboard',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect></svg>`
      },
      {
        name: 'Live Stream',
        path: '/live',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`
      },
      {
        name: 'CCTV Grid',
        path: '/cameras/grid',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`
      }
    ]
  },
  {
    key: 'vision',
    title: 'Computer Vision AI',
    items: [
      {
        name: 'HSE / K3 Safety',
        path: '/hse/playground',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>`
      },
      {
        name: 'Inventory AI',
        path: '/inventory/playground',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>`
      },
      {
        name: 'Tire Counter',
        path: '/tire-counter',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3"></circle><line x1="12" y1="2" x2="12" y2="5"></line><line x1="12" y1="19" x2="12" y2="22"></line><line x1="2" y1="12" x2="5" y2="12"></line><line x1="19" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="4.93" x2="7.05" y2="7.05"></line><line x1="16.95" y1="16.95" x2="19.07" y2="19.07"></line><line x1="4.93" y1="19.07" x2="7.05" y2="16.95"></line><line x1="16.95" y1="7.05" x2="19.07" y2="4.93"></line></svg>`
      },
      {
        name: 'Tire OCR',
        path: '/tires',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="4"></circle><line x1="4.93" y1="4.93" x2="9.17" y2="9.17"></line><line x1="14.83" y1="14.83" x2="19.07" y2="19.07"></line><line x1="14.83" y1="9.17" x2="19.07" y2="4.93"></line><line x1="4.93" y1="19.07" x2="9.17" y2="14.83"></line></svg>`
      }
    ]
  },
  {
    key: 'rag',
    title: 'Knowledge & RAG',
    items: [
      {
        name: 'RAG Knowledge',
        path: '/rag',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>`
      },
      {
        name: 'AnyDoc Converter',
        path: '/anydoc',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`
      },
      {
        name: 'PDF Inspector',
        path: '/pdf-inspector',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>`
      }
    ]
  },
  {
    key: 'lab',
    title: 'Biometrics & Lab',
    items: [
      {
        name: 'Anti-Spoofing',
        path: '/anti-spoof',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="m9 12 2 2 4-4"></path></svg>`
      },
      {
        name: 'Face Tester',
        path: '/tester',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>`
      }
    ]
  },
  {
    key: 'system',
    title: 'Sistem & Pengaturan',
    items: [
      {
        name: 'Users',
        path: '/users',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`
      },
      {
        name: 'Settings',
        path: '/settings',
        icon: `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>`
      }
    ]
  }
]

const isActive = (itemPath) => {
  if (itemPath === '/dashboard') return route.path === '/dashboard'
  return route.path.startsWith(itemPath)
}
</script>

<template>
  <aside :class="['app-sidebar', { collapsed: isCollapsed }]">
    <!-- Sidebar Header & Toggle Button -->
    <div class="sidebar-header">
      <div class="brand-info" @click="goTo('/dashboard')">
        <img :src="logoImage" alt="Chitra Vision logo" class="sidebar-logo" />
        <div v-if="!isCollapsed" class="brand-text">
          <span class="brand-name">Chitra Vision</span>
          <span class="brand-tag">AI Console</span>
        </div>
      </div>

      <button type="button" class="btn-collapse-toggle" @click="toggleSidebar" :title="isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'">
        <svg v-if="isCollapsed" viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
        <svg v-else viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
      </button>
    </div>

    <!-- Navigation Menu Items Grouped -->
    <nav class="sidebar-nav">
      <div v-for="group in menuGroups" :key="group.key" class="nav-group">
        <!-- Group Header (Accordion Toggle) -->
        <div 
          v-if="!isCollapsed" 
          class="nav-group-header" 
          @click="toggleGroup(group.key)"
        >
          <span class="group-title">{{ group.title }}</span>
          <svg 
            :class="['group-chevron', { rotated: collapsedGroups[group.key] }]" 
            viewBox="0 0 24 24" 
            width="12" 
            height="12" 
            stroke="currentColor" 
            stroke-width="2.5" 
            fill="none"
          >
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </div>

        <!-- Collapsed Mini Divider when Sidebar is in Icon Mode -->
        <div v-else class="nav-group-divider" :title="group.title"></div>

        <!-- Group Items List -->
        <div v-show="!collapsedGroups[group.key] || isCollapsed" class="nav-group-items">
          <a 
            v-for="item in group.items" 
            :key="item.path"
            href="#" 
            :class="['sidebar-link', { active: isActive(item.path) }]"
            @click.prevent="goTo(item.path)"
            :title="isCollapsed ? item.name : ''"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span v-if="!isCollapsed" class="nav-label">{{ item.name }}</span>
          </a>
        </div>
      </div>

      <!-- API Docs Link -->
      <div class="sidebar-docs-wrapper">
        <button 
          type="button" 
          :class="['sidebar-link', 'docs-btn', { active: showDocsMenu }]"
          @click="showDocsMenu = !showDocsMenu"
          :title="isCollapsed ? 'API Docs' : ''"
        >
          <span class="nav-icon">
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          </span>
          <span v-if="!isCollapsed" class="nav-label">API Docs</span>
          <span v-if="!isCollapsed" class="chevron-icon">
            <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="6 9 12 15 18 9"/></svg>
          </span>
        </button>

        <div v-if="showDocsMenu" class="sidebar-sub-menu">
          <a :href="`${API_BASE_URL}/redoc`" target="_blank" rel="noopener" class="sub-link">
            <span class="sub-dot"></span> Redoc
          </a>
          <a :href="`${API_BASE_URL}/docs`" target="_blank" rel="noopener" class="sub-link">
            <span class="sub-dot"></span> Swagger UI
          </a>
        </div>
      </div>
    </nav>

    <!-- Sidebar Footer / User Profile & Logout -->
    <div class="sidebar-footer">
      <div v-if="store.isLoggedIn" class="sidebar-user-card" @click="goTo('/settings')" title="User Profile & Settings">
        <div class="user-avatar">
          <img v-if="store.user?.avatar_url" :src="store.user.avatar_url" alt="User Avatar" />
          <span v-else class="avatar-initials">{{ store.user?.name ? store.user.name.charAt(0).toUpperCase() : 'A' }}</span>
        </div>
        <div v-if="!isCollapsed" class="user-info">
          <span class="user-name">{{ store.user?.name || 'System Admin' }}</span>
          <span class="user-role">{{ store.user?.email || 'admin@dfs.co.id' }}</span>
        </div>
      </div>

      <button 
        type="button" 
        class="sidebar-link logout-btn" 
        @click="showLogoutModal = true"
        :title="isCollapsed ? 'Logout' : ''"
      >
        <span class="nav-icon">
          <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
        </span>
        <span v-if="!isCollapsed" class="nav-label">Logout</span>
      </button>
    </div>

    <!-- Logout Modal -->
    <div v-if="showLogoutModal" class="modal-overlay" @click.self="showLogoutModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>Logout Confirmation</h3>
        </div>
        <div class="modal-body">
          <p style="margin: 0; color: #334155;">Are you sure you want to log out?</p>
        </div>
        <div class="modal-footer" style="margin-top: 1rem;">
          <button class="cancel-btn" @click="showLogoutModal = false">Cancel</button>
          <button class="generate-btn danger" style="background: #dc2626; color: white; display:flex; align-items:center; gap:8px;" :disabled="isLoggingOut" @click="confirmLogout">
            <svg v-if="isLoggingOut" class="spinner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
            {{ isLoggingOut ? 'Logging out...' : 'Log Out' }}
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 240px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  z-index: 100;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 2px 0 12px rgba(0,0,0,0.03);
}

.app-sidebar.collapsed {
  width: 68px;
}

.sidebar-header {
  height: 64px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
}

.brand-info {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  overflow: hidden;
}

.sidebar-logo {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  white-space: nowrap;
}

.brand-name {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.brand-tag {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}

.btn-collapse-toggle {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #475569;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.btn-collapse-toggle:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.sidebar-nav {
  flex: 1;
  padding: 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  overflow-x: hidden;
}

/* Nav Groups & Headers */
.nav-group {
  display: flex;
  flex-direction: column;
}

.nav-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  cursor: pointer;
  user-select: none;
  border-radius: 6px;
  transition: background 0.15s;
}

.nav-group-header:hover {
  background: #f8fafc;
}

.group-title {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #94a3b8;
}

.group-chevron {
  color: #94a3b8;
  transition: transform 0.2s ease;
}

.group-chevron.rotated {
  transform: rotate(-90deg);
}

.nav-group-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 6px 4px;
}

.nav-group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  color: #475569;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.15s ease-in-out;
  border: none;
  background: transparent;
  width: 100%;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}

.sidebar-link:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.sidebar-link.active {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 700;
}

.nav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  flex-shrink: 0;
}

.nav-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chevron-icon {
  display: flex;
  align-items: center;
}

.sidebar-docs-wrapper {
  margin-top: 4px;
  border-top: 1px dashed #e2e8f0;
  padding-top: 8px;
}

.sidebar-sub-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 36px;
  margin-top: 4px;
  margin-bottom: 4px;
}

.sub-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  font-size: 12px;
  color: #64748b;
  text-decoration: none;
  border-radius: 6px;
  font-weight: 500;
  transition: all 0.15s;
}

.sub-link:hover {
  color: #2563eb;
  background: #f8fafc;
}

.sub-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #cbd5e1;
}

.sidebar-footer {
  padding: 12px 10px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: background 0.15s;
}

.sidebar-user-card:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  overflow: hidden;
  background: #2563eb;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.user-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  line-height: 1.2;
}

.user-name {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}

.user-role {
  font-size: 10px;
  color: #64748b;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}

.logout-btn {
  color: #ef4444;
}

.logout-btn:hover {
  background: #fef2f2;
  color: #dc2626;
}
</style>

<script setup>
import { ref, onMounted } from 'vue'
import { store } from './store'
import { authService } from './services/authService'
import { apiKeyService } from './services/apiKeyService'
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppFooter from './components/AppFooter.vue'

const isSidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')

const handleSidebarToggle = (collapsed) => {
  isSidebarCollapsed.value = collapsed
}

onMounted(async () => {
  authService.checkHealth()
  if (store.isLoggedIn) {
    await authService.fetchMe()
    await apiKeyService.fetch()
  }
})
</script>

<template>
  <div 
    class="app-shell" 
    :class="{ 
      'has-sidebar': store.isLoggedIn && $route.path !== '/login', 
      'sidebar-collapsed': isSidebarCollapsed && store.isLoggedIn && $route.path !== '/login' 
    }"
  >
    <AppSidebar 
      v-if="store.isLoggedIn && $route.path !== '/login'" 
      @toggle="handleSidebarToggle"
    />
    <div class="main-content-wrapper">
      <AppHeader v-if="!store.isLoggedIn && $route.path !== '/login'" />
      <main class="content">
        <RouterView />
      </main>
      <AppFooter v-if="['/', '/dashboard'].includes($route.path)" />
    </div>
  </div>
</template>

<style>
.app-shell {
  min-height: 100vh;
  display: flex;
  background: #f8fafc;
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
}

.app-shell.has-sidebar .main-content-wrapper {
  margin-left: 230px;
  width: calc(100% - 230px);
  padding: 24px 32px;
  box-sizing: border-box;
  transition: margin-left 0.25s cubic-bezier(0.4, 0, 0.2, 1), width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.app-shell.has-sidebar.sidebar-collapsed .main-content-wrapper {
  margin-left: 68px;
  width: calc(100% - 68px);
}

.main-content-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.content {
  flex: 1;
  width: 100%;
  max-width: 100%;
}
</style>

import { createRouter, createWebHistory } from 'vue-router'
import { store } from './store'
import LoginView from './views/LoginView.vue'
import DashboardView from './views/DashboardView.vue'
import TesterView from './views/TesterView.vue'
import LiveView from './views/LiveView.vue'
import AboutView from './views/AboutView.vue'
import InstallationView from './views/InstallationView.vue'
import TireScannerView from './views/TireScannerView.vue'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: LoginView },
  { path: '/about', component: AboutView },
  { path: '/feedback', redirect: '/about' },
  { path: '/installation', component: InstallationView },
  {
    path: '/dashboard',
    component: DashboardView,
    meta: { requiresAuth: true }
  },
  {
    path: '/tester',
    component: TesterView,
    meta: { requiresAuth: true }
  },
  {
    path: '/live',
    component: LiveView,
    meta: { requiresAuth: true }
  },
  {
    path: '/tires',
    component: TireScannerView,
    meta: { requiresAuth: true }
  },
  {
    path: '/pdf-inspector',
    component: () => import('./views/PdfInspectorView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/anydoc',
    component: () => import('./views/AnyDocConverterView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/document-converter',
    redirect: '/anydoc'
  },
  {
    path: '/rag',
    component: () => import('./views/RagKnowledgeView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/knowledge-base',
    redirect: '/rag'
  },
  {
    path: '/anti-spoof',
    component: () => import('./views/AntiSpoofCompareView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    component: () => import('./views/SettingsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/users',
    component: () => import('./views/UsersView.vue'),
    meta: { requiresAuth: true }
  },
  // Inventory Routes
  { path: '/inventory', redirect: '/inventory/playground' },
  {
    path: '/inventory/playground',
    component: () => import('./views/inventory/InventoryPlaygroundView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/inventory/config',
    component: () => import('./views/inventory/InventoryConfigView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/inventory/history',
    component: () => import('./views/inventory/InventoryHistoryView.vue'),
    meta: { requiresAuth: true }
  },
  // HSE Safety Routes
  { path: '/hse', redirect: '/hse/playground' },
  {
    path: '/hse/playground',
    component: () => import('./views/hse/HSEPlaygroundView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/hse/zone-editor',
    component: () => import('./views/hse/HSEZoneEditorView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/hse/rules',
    component: () => import('./views/hse/HSERulesView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/hse/incidents',
    component: () => import('./views/hse/HSEIncidentLogView.vue'),
    meta: { requiresAuth: true }
  },
  // Camera Routes
  { path: '/cameras', redirect: '/cameras/grid' },
  {
    path: '/cameras/grid',
    component: () => import('./views/cameras/CameraGridView.vue'),
    meta: { requiresAuth: true }
  },
  // Tire Counter (Mining OTR & Warehouse)
  {
    path: '/tire-counter',
    component: () => import('./views/TireCounterView.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, _from, next) => {
  if (to.meta.requiresAuth && !store.isLoggedIn) {
    next('/login')
  } else {
    next()
  }
})

export default router

import { createRouter, createWebHistory } from 'vue-router'
import ChatInterface from '@/components/ChatInterface.vue'
import ChatInterfaceV2 from '@/components/ChatInterfaceV2.vue'
import { useAuth } from '@/composables/useAuth'

// Get auth instance
const auth = useAuth()

// Define routes
const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/components/views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/setup',
    name: 'Setup',
    component: () => import('@/components/views/SetupView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/agentChat',
    name: 'Home',
    component: ChatInterfaceV2,
    meta: { requiresAuth: true }
  },
  {
    path: '/agentChat_v1',
    name: 'ChatV2',
    component: ChatInterface,
    meta: { requiresAuth: true }
  },
  // Catch-all route for 404
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/components/views/NotFoundView.vue'),
    meta: { requiresAuth: false }
  }
]

// Create router
const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guard
router.beforeEach(async (to, from, next) => {
  // If first visit, check setup status
  if (!auth.setupChecked.value) {
    await auth.checkSetupStatus()
  }
  
  // Redirect to setup if needed
  if (auth.needsSetup.value && to.path !== '/setup') {
    next('/setup')
    return
  }
  
  // If page requires auth, check logged in status
  if (to.meta.requiresAuth) {
    // Check auth status if unknown
    if (!auth.initialized.value) {
      await auth.checkAuth()
    }
    
    // Redirect to login if not authenticated
    if (!auth.isAuthenticated.value) {
      next('/login')
      return
    }
  }
  // If going to login/setup while already authenticated, redirect to home
  else if ((to.path === '/login' || to.path === '/setup') && 
           auth.isAuthenticated.value && 
           !auth.needsSetup.value) {
    next('/')
    return
  }
  
  next()
})

export default router
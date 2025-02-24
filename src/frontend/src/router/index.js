import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/pages/index.vue'),
    name: 'home'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    // Always scroll to top when navigating
    return { top: 0 }
  }
})

// Navigation guard for future auth implementation
router.beforeEach((to, from, next) => {
  console.info(`Navigating from ${from.path} to ${to.path}`)
  next()
})

export default router
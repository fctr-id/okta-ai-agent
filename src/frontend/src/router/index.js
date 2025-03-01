import { createRouter, createWebHistory } from 'vue-router'
import ChatInterface from '@/components/ChatInterface.vue'
import ChatInterfaceV2 from '@/components/ChatInterfaceV2.vue'

// Define routes
const routes = [
  {
    path: '/',
    name: 'Home',
    component: ChatInterface
  },
  {
    path: '/v2',
    name: 'ChatV2',
    component: ChatInterfaceV2
  },
  // ...any other existing routes...
]

// Create router
const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
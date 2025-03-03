import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import vuetify from './plugins/vuetify'
import './styles/variables.css'

const app = createApp(App)

// Configure app
app.use(router)
app.use(vuetify)

// Error handling
app.config.errorHandler = (err, vm, info) => {
  console.error('Global error:', err)
  console.error('Error info:', info)
}

// Performance monitoring in development
if (import.meta.env.DEV) {
  app.config.performance = true
}

// Mount app
app.mount('#app')
<template>
  <AppLayout contentClass="auth-content">
    <div class="auth-box">
      <div class="setup-icon">
        <v-icon size="32" color="#4C64E2">mdi-alert-circle-outline</v-icon>
      </div>
      <h1 class="auth-title">Page Not Found</h1>
      <div class="auth-subtitle">The page you're looking for doesn't exist or has been moved</div>

      <v-btn class="auth-button mt-8" color="primary" to="/agentChat">
        <v-icon class="mr-2">mdi-home</v-icon>
        Return to Home
      </v-btn>
    </div>
  </AppLayout>
</template>

<script setup>
import { useRouter } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const router = useRouter()
</script>

<style scoped>
.auth-box {
  background: white;
  border-radius: var(--border-radius);
  box-shadow: var(--shadow-medium);
  padding: 40px;
  width: 100%;
  max-width: 480px;
  text-align: center;
  position: relative;
  z-index: 5;
  animation: cardEntry 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes cardEntry {
  0% {
    opacity: 0;
    transform: translateY(20px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.setup-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 24px;
}

.auth-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.auth-subtitle {
  font-size: 16px;
  color: var(--text-secondary);
  margin-bottom: 32px;
}

.auth-button {
  width: 100%;
  padding: 14px;
  background: var(--primary) !important;
  color: white !important;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease !important;
  text-transform: none !important;
  letter-spacing: normal !important;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-button:hover {
  background: var(--primary-dark) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.15) !important;
}

/* Responsive adjustments */
@media (max-width: 480px) {
  .auth-box {
    padding: 30px 20px;
  }

  .auth-title {
    font-size: 24px;
  }
}
</style>
<template>
  <div class="auth-page">
    <!-- Modern floating header - same as other pages -->
    <header class="floating-header">
      <div class="header-content">
        <div class="brand">
          <img src="@/assets/fctr-logo.png" alt="Okta Logo" height="24" />
          <div class="brand-divider"></div>
          <div class="title-with-badge">
            <span>AI Agent for Okta</span>
            <div class="beta-badge">BETA</div>
          </div>
        </div>
        <button class="logout-btn" aria-label="Logout" @click="handleLogout">
          <v-icon>mdi-logout</v-icon>
        </button>
      </div>
    </header>

    <div class="auth-container">
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
    </div>

    <!-- Modern footer credit - same as other pages -->
    <footer class="page-footer">
      <div class="footer-content">
        <span>Powered by </span>
        <a href="https://fctr.io" target="_blank" class="branded-link">
          Fctr Identity
        </a>
        <span class="disclaimer">• Responses may require verification</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { useAuth } from '@/composables/useAuth'
import { useRouter } from 'vue-router'

const auth = useAuth()
const router = useRouter()

const handleLogout = async () => {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  background: linear-gradient(180deg, #fafbff 0%, #f8f9ff 100%);
  position: relative;
  overflow-y: auto;
}

.auth-page::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 100px;
  background: linear-gradient(to bottom,
      rgba(76, 100, 226, 0.03) 0%,
      rgba(76, 100, 226, 0.01) 70%,
      transparent 100%);
  z-index: 1;
}

.floating-header {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  width: calc(100% - 40px);
  max-width: 1280px;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  backdrop-filter: blur(15px);
  border-radius: 16px;
  padding: 16px 24px;
  box-shadow: 0 2px 20px rgba(76, 100, 226, 0.08),
    0 1px 8px rgba(76, 100, 226, 0.05);
  position: relative;
  border: none;
  z-index: 2;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 500;
  color: #2c3e50;
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-divider {
  height: 20px;
  width: 1px;
  background: #e0e0e0;
}

.beta-badge {
  background: #F0F3FF;
  color: #4C64E2;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  letter-spacing: 0.5px;
}

.logout-btn {
  background: transparent;
  border: none;
  color: #777;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.logout-btn:hover {
  background: #f5f5f5;
  color: #333;
}

.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 40px 20px;
}

.auth-box {
  background: white;
  border-radius: 16px;
  box-shadow: 0 6px 30px rgba(76, 100, 226, 0.08);
  padding: 40px;
  width: 100%;
  max-width: 480px;
  text-align: center;
  position: relative;
  z-index: 5;
}

.setup-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: #F0F3FF;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 24px;
}

.auth-title {
  font-size: 28px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}

.auth-subtitle {
  font-size: 16px;
  color: #666;
  margin-bottom: 32px;
}

.auth-button {
  width: 100%;
  padding: 14px;
  background: #4C64E2 !important;
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
  background: #3b4fd9 !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.15) !important;
}

/* Footer */
.page-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px 0;
  text-align: center;
  font-size: 13px;
  color: #5d6b8a;
  background: white;
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.03);
  z-index: 50;
}

.footer-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.branded-link {
  color: #4C64E2;
  text-decoration: none;
  font-weight: 500;
}

.disclaimer {
  color: #7d8bb2;
  margin-left: 4px;
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
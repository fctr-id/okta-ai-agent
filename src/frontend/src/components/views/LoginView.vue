<template>
  <AppLayout :showLogout="false" contentClass="auth-content">
    <div class="auth-box animate-entry">
      <h1 class="auth-title">Welcome </h1>
      <div class="auth-subtitle">Sign in to Okta AI Agent</div>

      <form @submit.prevent="handleLogin" class="auth-form">
        <transition name="fade-slide">
          <div v-if="auth.error.value" class="error-alert">
            {{ auth.error.value }}
          </div>
        </transition>

        <div class="form-field">
          <label for="username">Username</label>
          <div class="input-wrapper">
            <v-icon class="field-icon">mdi-account</v-icon>
            <input type="text" id="username" v-model="username" placeholder="Enter your username"
              autocomplete="username" required :disabled="auth.loading.value" />
          </div>
        </div>

        <div class="form-field">
          <label for="password">Password</label>
          <div class="input-wrapper">
            <v-icon class="field-icon">mdi-lock</v-icon>
            <input :type="showPassword ? 'text' : 'password'" id="password" v-model="password"
              placeholder="Enter your password" autocomplete="current-password" required
              :disabled="auth.loading.value" />
            <button type="button" class="password-toggle" @click="showPassword = !showPassword"
              tabindex="-1">
              <v-icon>{{ showPassword ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
            </button>
          </div>
        </div>

        <button type="submit" class="auth-button glow-effect" :class="{ 'loading': auth.loading.value }"
          :disabled="auth.loading.value || !username || !password">
          <span v-if="!auth.loading.value">Sign In</span>
          <div v-else class="button-loader"></div>
        </button>
      </form>
    </div>
  </AppLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import AppLayout from '@/components/layout/AppLayout.vue'

const router = useRouter()
const auth = useAuth()

// Form data
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const animationReady = ref(false)

// Animation setup
onMounted(() => {
  animationReady.value = true
})

// Form submission
const handleLogin = async () => {
  if (!username.value || !password.value) return

  const success = await auth.login(username.value, password.value)
  if (success) {
    router.push('/agentChat')
  }
}
</script>

<style scoped>
@import '@/styles/variables.scss';

.auth-box {
  background: white;
  border-radius: 16px;
  box-shadow: 0 6px 30px rgba(76, 100, 226, 0.08);
  padding: 40px;
  width: 100%;
  max-width: 440px;
  text-align: center;
  position: relative;
  z-index: 5;
}

/* Animation for card entry */
.animate-entry {
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

.auth-title {
  font-size: 28px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}

.text-highlight {
  color: #4C64E2;
  position: relative;
  display: inline-block;
}

.text-highlight:after {
  content: '';
  position: absolute;
  bottom: 0px;
  left: -1px;
  right: -1px;
  height: 6px;
  background: rgba(76, 100, 226, 0.1);
  z-index: -1;
  border-radius: 4px;
}

.auth-subtitle {
  font-size: 16px;
  color: #666;
  margin-bottom: 32px;
  background: linear-gradient(90deg, #5d6b8a 0%, #4C64E2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  display: inline-block;
}

.auth-form {
  text-align: left;
}

.form-field {
  margin-bottom: 24px;
  animation: fadeIn 0.5s ease-out;
  animation-fill-mode: both;
}

.form-field:nth-child(2) {
  animation-delay: 0.1s;
}

.form-field:nth-child(3) {
  animation-delay: 0.2s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(5px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.form-field label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #444;
  margin-bottom: 8px;
  transition: color 0.2s;
}

.form-field:focus-within label {
  color: #4C64E2;
}

.input-wrapper {
  position: relative;
  border: 1px solid #ddd;
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
}

.input-wrapper:hover {
  border-color: #bbc4f3;
}

.input-wrapper:focus-within {
  border-color: #4C64E2;
  box-shadow: 0 0 0 3px rgba(76, 100, 226, 0.15);
}

.field-icon {
  color: #999;
  margin: 0 12px;
  font-size: 20px;
  transition: color 0.3s ease;
}

.input-wrapper:focus-within .field-icon {
  color: #4C64E2;
}

.input-wrapper input {
  width: 100%;
  padding: 14px 16px 14px 0;
  border: none;
  outline: none;
  font-size: 15px;
  background: transparent;
}

.password-toggle {
  background: transparent;
  border: none;
  color: #999;
  padding: 0 16px;
  cursor: pointer;
  outline: none;
  transition: color 0.2s ease;
}

.password-toggle:hover {
  color: #4C64E2;
}

/* Error alert with animation */
.error-alert {
  background: rgba(220, 38, 38, 0.05);
  color: #dc2626;
  padding: 12px 16px;
  border-radius: 10px;
  margin-bottom: 24px;
  font-size: 14px;
  border-left: 3px solid #dc2626;
  position: relative;
  overflow: hidden;
}

.error-alert::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(220, 38, 38, 0.1), transparent);
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  0% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(100%);
  }
}

/* Fade-slide transition */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.3s, transform 0.3s;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.auth-button {
  width: 100%;
  padding: 14px;
  background: #4C64E2;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  animation: fadeIn 0.5s ease-out;
  animation-delay: 0.3s;
  animation-fill-mode: both;
}

.auth-button:hover:not(:disabled) {
  background: #3b4fd9;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(76, 100, 226, 0.25);
}

.auth-button:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.15);
}

.glow-effect:not(:disabled)::after {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.2) 0%, transparent 70%);
  opacity: 0;
  transition: opacity 0.5s ease;
}

.glow-effect:not(:disabled):hover::after {
  opacity: 1;
}

.auth-button:disabled {
  background: #cfd7f9;
  cursor: not-allowed;
}

.auth-button.loading {
  background: #cfd7f9;
  cursor: wait;
}

.button-loader {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
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
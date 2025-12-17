<template>
  <AppLayout :showHeader="true" :showLogout="false" contentClass="auth-content">
    <div class="auth-box animate-entry">
      <div class="auth-logo">
        <img src="@/assets/fctr-logo-full.svg" alt="fctr" />
      </div>
      <h1 class="auth-title">
        <span class="title-main">Tako AI</span>
        <span class="title-divider">|</span>
        <span class="title-sub">AI Agent for Okta</span>
      </h1>

      <form @submit.prevent="handleLogin" class="auth-form">
        <transition name="fade-slide">
          <div v-if="auth.error.value || validationError" class="error-alert">
            {{ auth.error.value || validationError }}
          </div>
        </transition>

        <div class="form-field">
          <label for="username">Username</label>
          <div class="input-wrapper">
            <input type="text" id="username" v-model="username" placeholder="Enter your username"
              autocomplete="username" required :disabled="auth.loading.value" @input="sanitizeUsernameInput" />
          </div>
          <transition name="fade">
            <small v-if="usernameModified" class="input-modified-hint">
              Username was adjusted to remove invalid characters
            </small>
          </transition>
        </div>

        <div class="form-field">
          <label for="password">Password</label>
          <div class="input-wrapper">
            <input :type="showPassword ? 'text' : 'password'" id="password" v-model="password"
              placeholder="Enter your password" autocomplete="current-password" required :disabled="auth.loading.value"
              @input="sanitizePasswordInput" />
            <button type="button" class="password-toggle" @click="showPassword = !showPassword" tabindex="-1">
              <v-icon>{{ showPassword ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
            </button>
          </div>
        </div>

        <!-- In the template, inside your button -->
        <button type="submit" class="auth-button glow-effect" :disabled="auth.loading.value || !username || !password">
          <span v-if="!auth.loading.value">Sign In</span>
          <div v-else class="three-dots-loader">
            <div class="dot"></div>
            <div class="dot"></div>
            <div class="dot"></div>
          </div>
        </button>
      </form>
    </div>
  </AppLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useSanitize } from '@/composables/useSanitize'
import AppLayout from '@/components/layout/AppLayout.vue'

const router = useRouter()
const auth = useAuth()
const { username: sanitizeUsername, text: sanitizeText } = useSanitize()

// Form data
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const animationReady = ref(false)
const validationError = ref('')
const usernameModified = ref(false)

// Animation setup
onMounted(() => {
  animationReady.value = true
})

// Input sanitization
const sanitizeUsernameInput = () => {
  const originalValue = username.value;
  username.value = sanitizeUsername(username.value, {
    maxLength: 20,
    allowedPattern: /^[a-zA-Z0-9_-]$/
  });

  // Track if username was modified to provide user feedback
  usernameModified.value = (originalValue !== username.value);

  // Clear the modified flag after 3 seconds
  if (usernameModified.value) {
    setTimeout(() => {
      usernameModified.value = false;
    }, 3000);
  }
};

const sanitizePasswordInput = () => {
  // For password, we primarily want to prevent XSS but keep special characters
  password.value = sanitizeText(password.value, {
    maxLength: 50,
    removeHtml: true,
    trim: false // Don't trim passwords as spaces might be intentional
  });
};

// Form submission
const handleLogin = async () => {
  validationError.value = '';

  if (!username.value || !password.value) {
    validationError.value = "Please enter both username and password";
    return;
  }

  // Apply final sanitization before submission
  const sanitizedUsername = sanitizeUsername(username.value);
  const sanitizedPassword = sanitizeText(password.value, {
    removeHtml: true,
    trim: false
  });

  // Use sanitized credentials for login
  const success = await auth.login(sanitizedUsername, sanitizedPassword);
  if (success) {
    router.push('/agentChat');
  }
}
</script>


<style scoped>
/* 2026 Glassmorphism Auth Box */
.auth-box {
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(24px) saturate(120%);
  -webkit-backdrop-filter: blur(24px) saturate(120%);
  border-radius: 24px;
  padding: 3rem 2.5rem;
  width: 100%;
  max-width: 440px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.8);
  animation: card-appear 0.5s ease-out forwards;
}

.auth-logo {
  display: flex;
  justify-content: center;
  margin-bottom: 1.5rem;
}

.auth-logo img {
  height: 28px;
}

@keyframes card-appear {
  0% {
    opacity: 0;
    transform: translateY(12px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-entry {
  animation: card-appear 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}

.auth-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-bottom: 2rem;
  font-size: 18px;
  font-weight: 500;
}

.title-main {
  color: #1a1a1a;
  font-weight: 600;
}

.title-divider {
  color: #d1d5db;
  font-weight: 300;
}

.title-sub {
  color: #888;
  font-weight: 400;
}

.auth-form {
  text-align: left;
}

.form-field {
  margin-bottom: 24px;
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
  font-size: 13px;
  font-weight: 500;
  color: #666;
  margin-bottom: 8px;
  letter-spacing: 0.01em;
}

.form-field:focus-within label {
  color: #4C64E2;
}

/* Glassmorphism inputs */
.input-wrapper {
  position: relative;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 12px;
  overflow: hidden;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
}

.input-wrapper:hover {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(0, 0, 0, 0.12);
}

.input-wrapper:focus-within {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(76, 100, 226, 0.4);
  box-shadow: 0 0 0 3px rgba(76, 100, 226, 0.08);
}

.input-wrapper input {
  width: 100%;
  padding: 14px 16px;
  border: none;
  outline: none;
  font-size: 15px;
  background: transparent;
  color: #1a1a1a;
}

.input-wrapper input::placeholder {
  color: #999;
}

.password-toggle {
  background: transparent;
  border: none;
  color: #999;
  padding: 0 12px;
  cursor: pointer;
  outline: none;
  transition: color 0.2s ease;
}

.password-toggle:hover {
  color: #4C64E2;
}

/* Error alert - 2026 minimal glassmorphism */
.error-alert {
  background: rgba(254, 202, 202, 0.5);
  color: #991b1b;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
  border: 1px solid rgba(239, 68, 68, 0.2);
  text-align: center;
}

.input-modified-hint {
  color: #b45309;
  font-size: 11px;
  margin-top: 4px;
  display: block;
}

/* Fade transition for hints */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Fade-slide transition */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.3s, transform 0.3s;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* Modern submit button */
.auth-button {
  width: 100%;
  padding: 14px;
  background: #4C64E2;
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.2);
  margin-top: 8px;
}

.auth-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(76, 100, 226, 0.3);
}

.auth-button:active:not(:disabled) {
  transform: translateY(0);
}

.auth-button:disabled {
  background: #a5b4fc;
  cursor: not-allowed;
  box-shadow: none;
}

/* 3-dot loader */
.three-dots-loader {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  height: 18px;
}

.three-dots-loader .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: white;
  animation: bounce 1.4s ease-in-out infinite;
}

.three-dots-loader .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.three-dots-loader .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.6;
  }
  40% {
    transform: scale(1.1);
    opacity: 1;
  }
}

/* Responsive */
@media (max-width: 480px) {
  .auth-box {
    padding: 2rem 1.5rem;
    border-radius: 20px;
  }
}
</style>
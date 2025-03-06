<template>
  <AppLayout :showLogout="false" contentClass="auth-content">
    <div class="auth-box animate-entry">
      <h1 class="auth-title">Welcome </h1>
      <div class="auth-subtitle">Sign in to AI agent for Okta</div>

      <form @submit.prevent="handleLogin" class="auth-form">
        <transition name="fade-slide">
          <div v-if="auth.error.value || validationError" class="error-alert">
            {{ auth.error.value || validationError }}
          </div>
        </transition>

        <div class="form-field">
          <label for="username">Username</label>
          <div class="input-wrapper">
            <v-icon class="field-icon">mdi-account</v-icon>
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
            <v-icon class="field-icon">mdi-lock</v-icon>
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
/* Enhanced background - only needed if you're controlling the page background here */

.auth-box {
  background: white;
  border-radius: 16px;
  padding: 2rem;
  width: 100%;
  max-width: 420px;
  box-shadow:
    0 10px 30px rgba(0, 0, 0, 0.05),
    0 5px 15px rgba(76, 100, 226, 0.04),
    0 2px 5px rgba(0, 0, 0, 0.02);
  transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(76, 100, 226, 0.08);
}

/* Add subtle entry animation */
@keyframes card-appear {
  0% {
    opacity: 0;
    transform: translateY(10px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.auth-box {
  animation: card-appear 0.5s ease-out forwards;
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
  margin-bottom: 8px;
  background: linear-gradient(90deg, var(--primary), #5e72e4);
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
}

.text-highlight {
  color: var(--primary);
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
  background: linear-gradient(90deg, var(--text-muted) 0%, var(--primary) 100%);
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
  color: var(--primary);
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
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(76, 100, 226, 0.15);
}

/* Add side accent bar on focus like ChatInterfaceV2 */
.input-wrapper::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 3px;
  height: 0;
  background: linear-gradient(180deg, var(--primary), #5e72e4);
  transition: height 0.25s cubic-bezier(0.25, 1, 0.5, 1);
  border-top-left-radius: 10px;
  border-bottom-left-radius: 10px;
}

.input-wrapper:focus-within::before {
  height: 100%;
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
  background: linear-gradient(135deg, rgba(244, 67, 54, 0.02), rgba(244, 67, 54, 0.08));
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

.input-modified-hint {
  color: #b45309;
  font-size: 12px;
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
  background: linear-gradient(135deg, var(--primary), #5e72e4);
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
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.15);
}

.auth-button:hover:not(:disabled) {
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

/* Clean, centered 3-dot animation */
.three-dots-loader {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  height: 20px;
}

.three-dots-loader .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: white;
  display: inline-block;
}

.three-dots-loader .dot:nth-child(1) {
  animation: bounce 1.4s ease-in-out 0s infinite;
}

.three-dots-loader .dot:nth-child(2) {
  animation: bounce 1.4s ease-in-out 0.2s infinite;
}

.three-dots-loader .dot:nth-child(3) {
  animation: bounce 1.4s ease-in-out 0.4s infinite;
}

@keyframes bounce {

  0%,
  80%,
  100% {
    transform: scale(0.8);
    opacity: 0.6;
  }

  40% {
    transform: scale(1.2);
    opacity: 1;
    box-shadow: 0 0 6px rgba(255, 255, 255, 0.3);
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
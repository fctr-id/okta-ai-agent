<template>
  <AppLayout :showHeader="true" :showLogout="false" contentClass="auth-content">
    <section class="auth-shell animate-entry">
      <div class="auth-hero">
        <h1 class="auth-title">Login to Tako AI</h1>
        <p class="auth-description">Use your admin credentials to continue into the Tako workspace.</p>
      </div>

      <div class="auth-card">
        <form @submit.prevent="handleLogin" class="auth-form">
          <transition name="fade-slide">
            <div v-if="auth.error.value || validationError" class="status-alert status-alert-error">
              {{ auth.error.value || validationError }}
            </div>
          </transition>

          <div class="form-field">
            <label for="username">Username</label>
            <div class="input-wrapper">
              <input
                id="username"
                v-model="username"
                type="text"
                placeholder="Enter your username"
                autocomplete="username"
                required
                :disabled="auth.loading.value"
                @input="sanitizeUsernameInput"
              />
            </div>
            <transition name="fade">
              <small v-if="usernameModified" class="input-modified-hint">
                Username was adjusted to remove invalid characters.
              </small>
            </transition>
          </div>

          <div class="form-field">
            <label for="password">Password</label>
            <div class="input-wrapper">
              <input
                id="password"
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="Enter your password"
                autocomplete="current-password"
                required
                :disabled="auth.loading.value"
                @input="sanitizePasswordInput"
              />
              <button type="button" class="password-toggle" @click="showPassword = !showPassword" tabindex="-1">
                <v-icon>{{ showPassword ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
              </button>
            </div>
          </div>

          <button type="submit" class="auth-button" :disabled="auth.loading.value || !username || !password">
            <span v-if="!auth.loading.value">Sign In</span>
            <div v-else class="three-dots-loader">
              <div class="dot"></div>
              <div class="dot"></div>
              <div class="dot"></div>
            </div>
          </button>
        </form>
      </div>
    </section>
  </AppLayout>
</template>

<script setup>
import { ref } from 'vue'
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
const validationError = ref('')
const usernameModified = ref(false)

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
.auth-shell {
  width: min(100%, 820px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
  padding: 24px 24px 40px;
}

.animate-entry {
  animation: auth-rise 0.45s cubic-bezier(0.16, 1, 0.3, 1);
}

.auth-hero {
  text-align: center;
  max-width: 640px;
}

.auth-title {
  margin: 0;
  color: var(--text-primary);
  font-size: 42px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.08;
}

.auth-description {
  margin: 10px auto 0;
  max-width: 560px;
  font-size: 15px;
  font-weight: 450;
  line-height: 1.55;
  color: var(--text-secondary);
}

.auth-card {
  width: min(100%, 620px);
  background: #ffffff;
  border: 2px solid rgba(15, 23, 42, 0.28);
  border-radius: 10px;
  padding: 16px;
  box-shadow: none;
}

.auth-form {
  text-align: left;
}

.form-field {
  margin-bottom: 20px;
}

.form-field label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-secondary);
}

.form-field:focus-within label {
  color: var(--text-primary);
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 52px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.16);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.input-wrapper:hover {
  border-color: rgba(15, 23, 42, 0.24);
}

.input-wrapper:focus-within {
  border-color: rgba(var(--primary-rgb), 0.5);
  box-shadow: 0 0 0 4px rgba(var(--primary-rgb), 0.12);
}

.input-wrapper input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  padding: 0 16px;
  font-size: 15px;
  color: var(--text-primary);
}

.input-wrapper input::placeholder {
  color: var(--text-muted);
}

.password-toggle {
  border: none;
  background: transparent;
  color: var(--text-muted);
  padding: 0 14px;
  cursor: pointer;
  transition: color 0.18s ease;
}

.password-toggle:hover {
  color: var(--text-primary);
}

.status-alert {
  margin-bottom: 16px;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.45;
  border: 1px solid transparent;
}

.status-alert-error {
  background: rgba(180, 35, 24, 0.06);
  border-color: rgba(180, 35, 24, 0.14);
  color: #a22c29;
}

.input-modified-hint {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  color: #9a5a00;
}

.auth-button {
  width: 100%;
  min-height: 52px;
  margin-top: 10px;
  border: none;
  border-radius: 10px;
  background: var(--primary);
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.18s ease, transform 0.18s ease;
  box-shadow: none;
}

.auth-button:hover:not(:disabled) {
  background: var(--primary-hover);
  transform: translateY(-1px);
}

.auth-button:disabled {
  background: var(--surface-muted);
  color: var(--text-faint);
  cursor: not-allowed;
  box-shadow: none;
}

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

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
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

@keyframes auth-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 640px) {
  .auth-shell {
    padding: 16px 16px 28px;
    gap: 16px;
  }

  .auth-title {
    font-size: 32px;
  }

  .auth-card {
    padding: 14px;
  }

  .auth-description {
    font-size: 14px;
  }
}
</style>
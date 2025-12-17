<template>
  <AppLayout :showHeader="true" :showLogout="false" contentClass="auth-content">
    <div class="auth-box animate-entry">
      <div class="auth-logo">
        <img src="@/assets/fctr-logo-full.svg" alt="fctr" />
      </div>
      <h1 class="auth-title">
        <span class="title-main">Initial Setup for Tako AI</span>
      </h1>
      <p class="auth-subtitle">Create your admin account to get started</p>

      <form @submit.prevent="handleSetup" class="auth-form">
        <div v-if="auth.error.value" class="error-alert">
          {{ auth.error.value }}
        </div>

        <div v-if="validationError" class="warning-alert">
          {{ validationError }}
        </div>

        <div class="form-field">
          <label for="username">Admin Username</label>
          <div class="input-wrapper">
            <input type="text" id="username" v-model="username" placeholder="Choose an admin username"
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
              placeholder="Create a secure password" autocomplete="new-password" required :disabled="auth.loading.value"
              @input="sanitizePasswordInput" />
            <button type="button" class="password-toggle" @click="showPassword = !showPassword" tabindex="-1">
              <v-icon>{{ showPassword ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
            </button>
          </div>
          <div class="password-requirements">
            <div class="requirement" :class="{ met: passwordLength }">
              <v-icon size="14" :color="passwordLength ? '#10b981' : '#9ca3af'">
                {{ passwordLength ? 'mdi-check-circle' : 'mdi-circle-outline' }}
              </v-icon>
              <span>At least 12 characters</span>
            </div>
            <div class="requirement" :class="{ met: passwordUppercase }">
              <v-icon size="14" :color="passwordUppercase ? '#10b981' : '#9ca3af'">
                {{ passwordUppercase ? 'mdi-check-circle' : 'mdi-circle-outline' }}
              </v-icon>
              <span>One uppercase letter</span>
            </div>
            <div class="requirement" :class="{ met: passwordLowercase }">
              <v-icon size="14" :color="passwordLowercase ? '#10b981' : '#9ca3af'">
                {{ passwordLowercase ? 'mdi-check-circle' : 'mdi-circle-outline' }}
              </v-icon>
              <span>One lowercase letter</span>
            </div>
            <div class="requirement" :class="{ met: passwordNumber }">
              <v-icon size="14" :color="passwordNumber ? '#10b981' : '#9ca3af'">
                {{ passwordNumber ? 'mdi-check-circle' : 'mdi-circle-outline' }}
              </v-icon>
              <span>One number</span>
            </div>
            <div class="requirement" :class="{ met: passwordSpecial }">
              <v-icon size="14" :color="passwordSpecial ? '#10b981' : '#9ca3af'">
                {{ passwordSpecial ? 'mdi-check-circle' : 'mdi-circle-outline' }}
              </v-icon>
              <span>One special character</span>
            </div>
          </div>
        </div>

        <div class="form-field">
          <label for="confirmPassword">Confirm Password</label>
          <div class="input-wrapper">
            <input :type="showPassword ? 'text' : 'password'" id="confirmPassword" v-model="confirmPassword"
              placeholder="Confirm your password" autocomplete="new-password" required :disabled="auth.loading.value"
              @input="sanitizeConfirmPasswordInput" />
          </div>
        </div>

        <button type="submit" class="auth-button"
          :disabled="auth.loading.value || !formIsValid">
          <span v-if="!auth.loading.value">Complete Setup</span>
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
import { ref, computed, watch, } from 'vue'
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
const confirmPassword = ref('')
const showPassword = ref(false)
const validationError = ref('')
const usernameModified = ref(false)

// Sanitization functions
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
  // We only remove control characters and HTML tags
  password.value = sanitizeText(password.value, {
    maxLength: 50,
    removeHtml: true,
    trim: false // Don't trim passwords as spaces might be intentional
  });
};

const sanitizeConfirmPasswordInput = () => {
  // Same sanitization for confirm password field
  confirmPassword.value = sanitizeText(confirmPassword.value, {
    maxLength: 50,
    removeHtml: true,
    trim: false
  });
};

// Password validation
const passwordLength = computed(() => password.value.length >= 12)
const passwordUppercase = computed(() => /[A-Z]/.test(password.value))
const passwordLowercase = computed(() => /[a-z]/.test(password.value))
const passwordNumber = computed(() => /[0-9]/.test(password.value))
const passwordSpecial = computed(() => /[^A-Za-z0-9]/.test(password.value))

const passwordIsValid = computed(() =>
  passwordLength.value &&
  passwordUppercase.value &&
  passwordLowercase.value &&
  passwordNumber.value &&
  passwordSpecial.value
)

const formIsValid = computed(() =>
  username.value.length >= 3 &&
  passwordIsValid.value &&
  password.value === confirmPassword.value
)

// Form submission
const handleSetup = async () => {
  validationError.value = '';

  // Final sanitization before submission
  const finalUsername = sanitizeUsername(username.value);
  const finalPassword = sanitizeText(password.value, {
    removeHtml: true,
    trim: false
  });

  // Validate final sanitized inputs
  if (finalUsername.length < 3) {
    validationError.value = 'Username must be at least 3 characters';
    return;
  }

  if (!passwordIsValid.value) {
    validationError.value = 'Please meet all password requirements';
    return;
  }

  if (finalPassword !== sanitizeText(confirmPassword.value, { removeHtml: true, trim: false })) {
    validationError.value = 'Passwords do not match';
    return;
  }

  // Submit sanitized values
  const success = await auth.setupAdmin(finalUsername, finalPassword);
  if (success) {
    router.push('/agentChat');
  }
};

// Show password match error in real-time once both fields have content
watch([password, confirmPassword], ([newPassword, newConfirmPassword]) => {
  // Only show error if both fields have content and don't match
  if (newPassword && newConfirmPassword && newPassword !== newConfirmPassword) {
    validationError.value = 'Passwords do not match';
  } else {
    // Clear the error if they match or fields are empty
    if (validationError.value === 'Passwords do not match') {
      validationError.value = '';
    }
  }
});
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
  max-width: 480px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.8);
  animation: card-appear 0.5s ease-out forwards;
  margin: auto;
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
  gap: 8px;
  margin-bottom: 0.25rem;
  font-size: 20px;
  font-weight: 600;
}

.title-main {
  color: #1a1a1a;
}

.auth-subtitle {
  font-size: 14px;
  color: #888;
  text-align: center;
  margin-bottom: 2rem;
}

.auth-form {
  text-align: left;
}

.form-field {
  margin-bottom: 22px;
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

/* Password requirements - minimal 2026 */
.password-requirements {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 8px;
  font-size: 11px;
  color: #999;
}

.requirement {
  display: flex;
  align-items: center;
  gap: 4px;
  transition: color 0.2s ease;
}

.requirement.met {
  color: #10b981;
}

/* Error/Warning alerts - glassmorphism */
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

.warning-alert {
  background: rgba(254, 243, 199, 0.5);
  color: #92400e;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
  border: 1px solid rgba(251, 191, 36, 0.2);
  text-align: center;
}

.input-modified-hint {
  color: #b45309;
  font-size: 11px;
  margin-top: 4px;
  display: block;
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
  margin-top: 12px;
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.2);
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
  gap: 6px;
  align-items: center;
  justify-content: center;
  height: 18px;
}

.three-dots-loader .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: white;
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

/* Fade transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Responsive */
@media (max-width: 480px) {
  .auth-box {
    padding: 2rem 1.5rem;
    border-radius: 20px;
  }

  .password-requirements {
    grid-template-columns: 1fr;
  }
}
</style>
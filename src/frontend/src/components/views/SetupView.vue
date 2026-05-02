<template>
  <AppLayout :showHeader="true" :showLogout="false" contentClass="auth-content">
    <section class="auth-shell animate-entry">
      <div class="auth-hero">
        <h1 class="auth-title">Create your admin account</h1>
        <p class="auth-description">Set up the first admin account before entering the Tako workspace.</p>
      </div>

      <div class="auth-card auth-card-wide">
        <form @submit.prevent="handleSetup" class="auth-form">
          <transition name="fade-slide">
            <div v-if="auth.error.value" class="status-alert status-alert-error">
              {{ auth.error.value }}
            </div>
          </transition>

          <transition name="fade-slide">
            <div v-if="validationError" class="status-alert status-alert-warning">
              {{ validationError }}
            </div>
          </transition>

          <div class="form-field">
            <label for="username">Admin Username</label>
            <div class="input-wrapper">
              <input
                id="username"
                v-model="username"
                type="text"
                placeholder="Choose an admin username"
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
                placeholder="Create a secure password"
                autocomplete="new-password"
                required
                :disabled="auth.loading.value"
                @input="sanitizePasswordInput"
              />
              <button type="button" class="password-toggle" @click="showPassword = !showPassword" tabindex="-1">
                <v-icon>{{ showPassword ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
              </button>
            </div>

            <div class="password-requirements">
              <div class="requirement" :class="{ met: passwordLength }">
                <v-icon size="14" :color="passwordLength ? '#0f766e' : '#94a3b8'">
                  {{ passwordLength ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
                <span>At least 12 characters</span>
              </div>
              <div class="requirement" :class="{ met: passwordUppercase }">
                <v-icon size="14" :color="passwordUppercase ? '#0f766e' : '#94a3b8'">
                  {{ passwordUppercase ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
                <span>One uppercase letter</span>
              </div>
              <div class="requirement" :class="{ met: passwordLowercase }">
                <v-icon size="14" :color="passwordLowercase ? '#0f766e' : '#94a3b8'">
                  {{ passwordLowercase ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
                <span>One lowercase letter</span>
              </div>
              <div class="requirement" :class="{ met: passwordNumber }">
                <v-icon size="14" :color="passwordNumber ? '#0f766e' : '#94a3b8'">
                  {{ passwordNumber ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
                <span>One number</span>
              </div>
              <div class="requirement" :class="{ met: passwordSpecial }">
                <v-icon size="14" :color="passwordSpecial ? '#0f766e' : '#94a3b8'">
                  {{ passwordSpecial ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
                <span>One special character</span>
              </div>
            </div>
          </div>

          <div class="form-field">
            <label for="confirmPassword">Confirm Password</label>
            <div class="input-wrapper">
              <input
                id="confirmPassword"
                v-model="confirmPassword"
                :type="showPassword ? 'text' : 'password'"
                placeholder="Confirm your password"
                autocomplete="new-password"
                required
                :disabled="auth.loading.value"
                @input="sanitizeConfirmPasswordInput"
              />
            </div>
          </div>

          <button type="submit" class="auth-button" :disabled="auth.loading.value || !formIsValid">
            <span v-if="!auth.loading.value">Complete Setup</span>
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
.auth-shell {
  width: min(100%, 840px);
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
  max-width: 720px;
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
  max-width: 580px;
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

.auth-card-wide {
  width: min(100%, 680px);
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

.password-requirements {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.requirement {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(15, 23, 42, 0.03);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
}

.requirement.met {
  color: #0f766e;
  border-color: rgba(15, 118, 110, 0.16);
  background: rgba(15, 118, 110, 0.07);
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

.status-alert-warning {
  background: rgba(154, 90, 0, 0.08);
  border-color: rgba(154, 90, 0, 0.16);
  color: #9a5a00;
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

  .password-requirements {
    grid-template-columns: 1fr;
  }
}
</style>
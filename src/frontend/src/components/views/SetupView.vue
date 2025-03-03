<template>
  <AppLayout :showLogout="false" contentClass="auth-content">
    <div class="app-card setup-card">
      <div class="setup-icon">
        <v-icon size="32" color="#4C64E2">mdi-shield-account</v-icon>
      </div>
      <h1 class="auth-title">Initial Setup</h1>
      <div class="auth-subtitle">Create your admin account to get started</div>

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
            <v-icon class="field-icon">mdi-account</v-icon>
            <input type="text" id="username" v-model="username" placeholder="Choose an admin username"
              autocomplete="username" required :disabled="auth.loading.value" @input="sanitizeUsernameInput" />
          </div>
          <small v-if="usernameModified" class="input-modified-hint">
            Username was adjusted to remove invalid characters
          </small>
        </div>

        <div class="form-field">
          <label for="password">Password</label>
          <div class="input-wrapper">
            <v-icon class="field-icon">mdi-lock</v-icon>
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
            <v-icon class="field-icon">mdi-lock-check</v-icon>
            <input :type="showPassword ? 'text' : 'password'" id="confirmPassword" v-model="confirmPassword"
              placeholder="Confirm your password" autocomplete="new-password" required :disabled="auth.loading.value"
              @input="sanitizeConfirmPasswordInput" />
          </div>
        </div>

        <button type="submit" class="auth-button" :class="{ 'loading': auth.loading.value }"
          :disabled="auth.loading.value || !formIsValid">
          <span v-if="!auth.loading.value">Complete Setup</span>
          <div v-else class="button-loader"></div>
        </button>
      </form>
    </div>
  </AppLayout>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
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

<style lang="scss">
@use '@/styles/variables' as v;

// Then update variable references like:
// From: $primary
// To: v.$primary

.setup-card {
  width: 100%;
  max-width: 480px;
}

.setup-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: v.$primary-light;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 24px;
}
</style><style>
/* Consolidated styles using CSS variables */
.setup-card {
  width: 100%;
  max-width: 480px;
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
  text-align: center;
}

.auth-subtitle {
  font-size: 16px;
  color: var(--text-secondary);
  margin-bottom: 32px;
  text-align: center;
}

.auth-form {
  text-align: left;
}

.form-field {
  margin-bottom: 24px;
}

.form-field label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #444;
  margin-bottom: 8px;
}

.input-wrapper {
  position: relative;
  border: 1px solid #ddd;
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
}

.input-wrapper:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(76, 100, 226, 0.1);
}

.field-icon {
  color: #999;
  margin: 0 12px;
  font-size: 20px;
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
  color: var(--primary);
}

.error-alert {
  background: rgba(220, 38, 38, 0.05);
  color: #dc2626;
  padding: 12px 16px;
  border-radius: 10px;
  margin-bottom: 24px;
  font-size: 14px;
  border-left: 3px solid #dc2626;
}

.warning-alert {
  background: rgba(234, 179, 8, 0.05);
  color: #b45309;
  padding: 12px 16px;
  border-radius: 10px;
  margin-bottom: 24px;
  font-size: 14px;
  border-left: 3px solid #eab308;
}

.password-requirements {
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}

.requirement {
  display: flex;
  align-items: center;
  gap: 6px;
  transition: color 0.2s ease;
}

.requirement.met {
  color: #10b981;
}

.auth-button {
  width: 100%;
  padding: 14px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 8px;
}

.auth-button:hover:not(:disabled) {
  background: var(--primary-dark);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(76, 100, 226, 0.15);
}

.auth-button:disabled {
  background: #cfd7f9;
  cursor: not-allowed;
}

.auth-button.loading {
  background: #cfd7f9;
  cursor: wait;
}

.input-modified-hint {
  color: #b45309;
  font-size: 12px;
  margin-top: 4px;
  display: block;
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
  .app-card {
    padding: 30px 20px;
  }

  .auth-title {
    font-size: 24px;
  }

  .password-requirements {
    grid-template-columns: 1fr;
  }
}
</style>
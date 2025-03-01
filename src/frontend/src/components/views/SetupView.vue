<template>
    <div class="auth-page">
        <!-- Modern floating header -->
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
            </div>
        </header>

        <div class="auth-container">
            <div class="auth-box">
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
                                autocomplete="username" required :disabled="auth.loading.value" />
                        </div>
                    </div>

                    <div class="form-field">
                        <label for="password">Password</label>
                        <div class="input-wrapper">
                            <v-icon class="field-icon">mdi-lock</v-icon>
                            <input :type="showPassword ? 'text' : 'password'" id="password" v-model="password"
                                placeholder="Create a secure password" autocomplete="new-password" required
                                :disabled="auth.loading.value" />
                            <button type="button" class="password-toggle" @click="showPassword = !showPassword"
                                tabindex="-1">
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
                            <input :type="showPassword ? 'text' : 'password'" id="confirmPassword"
                                v-model="confirmPassword" placeholder="Confirm your password"
                                autocomplete="new-password" required :disabled="auth.loading.value" />
                        </div>
                    </div>

                    <button type="submit" class="auth-button" :class="{ 'loading': auth.loading.value }"
                        :disabled="auth.loading.value || !formIsValid">
                        <span v-if="!auth.loading.value">Complete Setup</span>
                        <div v-else class="button-loader"></div>
                    </button>
                </form>
            </div>
        </div>

        <!-- Modern footer credit -->
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
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const auth = useAuth()

// Form data
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const validationError = ref('')

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
    validationError.value = ''

    if (username.value.length < 3) {
        validationError.value = 'Username must be at least 3 characters'
        return
    }

    if (!passwordIsValid.value) {
        validationError.value = 'Please meet all password requirements'
        return
    }

    if (password.value !== confirmPassword.value) {
        validationError.value = 'Passwords do not match'
        return
    }

    const success = await auth.setupAdmin(username.value, password.value)
    if (success) {
        router.push('/agentChat')
    }
}

watch([password, confirmPassword], ([newPassword, newConfirmPassword]) => {
  // Only show error if both fields have content and don't match
  if (newPassword && newConfirmPassword && newPassword !== newConfirmPassword) {
    validationError.value = 'Passwords do not match'
  } else {
    // Clear the error if they match or fields are empty
    if (validationError.value === 'Passwords do not match') {
      validationError.value = ''
    }
  }
})
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
    border-color: #4C64E2;
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
    color: #4C64E2;
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
    background: #4C64E2;
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
    background: #3b4fd9;
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

    .password-requirements {
        grid-template-columns: 1fr;
    }
}
</style>
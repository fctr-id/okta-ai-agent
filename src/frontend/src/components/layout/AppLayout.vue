<template>
    <div class="app-page">
        <!-- Header -->
        <header class="floating-header">
            <div class="header-content">
                <div class="brand">
                    <img src="@/assets/fctr-logo.png" alt="Okta Logo" height="24" />
                    <div class="brand-divider"></div>
                    <div class="title-with-badge">
                        <div class="tako-title-container">
                            <span class="tako-name">Tako AI</span>
                            <!--<span class="tako-subtitle">AI Agent for Okta</span>-->
                        </div>
                        <div class="beta-badge">BETA</div>
                    </div>
                </div>

                <div class="header-actions">
                    <!-- Add SyncStatusButton here -->
                    <div class="mode-toggle" v-if="showLogout">
                        <span class="mode-label">Database</span>
                        <v-switch v-model="isRealtimeMode" color="primary" density="compact" hide-details class="mx-2"
                            inset></v-switch>
                        <span class="mode-label" :class="{ 'active': isRealtimeMode }">Realtime</span>
                    </div>

                    <div class="header-spacer"></div>
                    <SyncStatusButton v-if="showLogout && !isRealtimeMode" />
                    <v-tooltip text="Logout" location="bottom">
                        <template v-slot:activator="{ props }">
                            <button v-if="showLogout" v-bind="props" class="logout-btn" aria-label="Logout"
                                @click="handleLogout">
                                <v-icon>mdi-logout</v-icon>
                            </button>
                        </template>
                    </v-tooltip>
                </div>
            </div>
        </header>

        <!-- Main Content -->
        <main class="main-content" :class="contentClass">
            <slot></slot>
        </main>

        <!-- Footer -->
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
import SyncStatusButton from '@/components/sync/SyncStatusButton.vue'
import { isRealtimeMode } from '@/state/chatMode.js';

const props = defineProps({
    showLogout: {
        type: Boolean,
        default: true
    },
    contentClass: {
        type: String,
        default: ''
    }
})

const auth = useAuth()
const router = useRouter()

const handleLogout = async () => {
    await auth.logout()
    router.push('/login')
}
</script>

<style>
.app-page {
    min-height: 100vh;
    background: linear-gradient(180deg, #e5eaf5 0%, #f0f4fb 100%);
    position: relative;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

.app-page::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 200px;
    background: linear-gradient(to bottom,
            rgba(76, 100, 226, 0.05) 0%,
            rgba(76, 100, 226, 0.02) 75%,
            transparent 100%);
    z-index: 1;
}


/* Header */
.floating-header {
    position: relative;
    /* Changed from fixed */
    margin: 20px auto;
    /* Instead of positioning with top/left/transform */
    z-index: 100;
    width: calc(100% - 40px);
    max-width: var(--max-width);
}

.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: white;
    backdrop-filter: blur(15px);
    border-radius: var(--border-radius);
    padding: 16px 24px;
    box-shadow: var(--shadow-light);
    position: relative;
    border: none;
    z-index: 2;
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 500;
    color: var(--text-primary);
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
    background: var(--primary-light);
    color: var(--primary);
    font-size: 10px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 6px;
    letter-spacing: 0.5px;
    margin-top: -5px;
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

/* Main content area */
.main-content {
    width: calc(100% - 40px);
    max-width: var(--max-width);
    margin: 0 auto;
    padding-top: 0;
    padding-bottom: 30px;
    /* Reduced from 80px */
    flex-grow: 1;
    /* Add this to make it expand and fill space */
}


/* For auth pages - centered boxes */
.auth-content {
    display: flex;
    flex-direction: column;
    /* Add this */
    justify-content: center;
    align-items: center;
    flex-grow: 1;
    /* Add this to make it expand */
    padding: 20px 0;
}


/* Full-width footer fixed to bottom */
.page-footer {
    position: relative;
    margin-top: auto;
    /* Add this to push to the bottom */
    padding: 14px 0;
    text-align: center;
    font-size: 13px;
    color: var(--text-muted);
    background: white;
    box-shadow: 0 -1px 0 rgba(76, 100, 226, 0.08);
    z-index: 50;
}

/* Add subtle gradient top border */
.page-footer::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg,
            rgba(76, 100, 226, 0.01),
            rgba(76, 100, 226, 0.1) 40%,
            rgba(76, 100, 226, 0.1) 60%,
            rgba(76, 100, 226, 0.01));
}

.footer-content {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    max-width: var(--max-width);
    margin: 0 auto;
}

.branded-link {
    color: var(--primary);
    text-decoration: none;
    font-weight: 500;
    position: relative;
    transition: all 0.2s ease;
    padding: 0 3px;
}

.branded-link:hover {
    color: var(--primary-dark);
}

/* Add subtle underline animation on hover */
.branded-link::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    width: 0;
    height: 1px;
    background: linear-gradient(90deg, var(--primary), #5e72e4);
    transition: width 0.2s ease;
}

.branded-link:hover::after {
    width: 100%;
}

.disclaimer {
    color: #7d8bb2;
    margin-left: 4px;
}

.v-tooltip .v-overlay__content {
    background-color: var(--primary-dark) !important;
    color: white !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    padding: 5px 10px !important;
    border-radius: 4px !important;
    opacity: 0.95 !important;
}


/* Common card styles */
.app-card {
    background: white;
    border-radius: var(--border-radius);
    box-shadow: var(--shadow-medium);
    padding: 40px;
    animation: cardEntry 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

/* Mode toggle container */
/* Mode toggle container */
.mode-toggle {
    display: flex;
    align-items: center;
    background: rgba(255, 255, 255, 0.9);
    padding: 5px 12px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(76, 100, 226, 0.15);
    margin-right: 12px;
    transition: all 0.25s ease;
    border: 1px solid rgba(76, 100, 226, 0.12);
    position: relative;
    overflow: hidden;
}

/* Add subtle gradient background */
.mode-toggle::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg,
            rgba(76, 100, 226, 0.03) 0%,
            rgba(94, 114, 228, 0.05) 100%);
    z-index: 0;
}

/* Ensure content shows above gradient */
.mode-toggle>* {
    position: relative;
    z-index: 1;
}

.mode-toggle:hover {
    box-shadow: 0 4px 12px rgba(76, 100, 226, 0.25);
    transform: translateY(-2px);
    border-color: rgba(76, 100, 226, 0.2);
}

/* Mode labels with enhanced styling */
.mode-label {
    font-size: 13px;
    font-weight: 500;
    transition: all 0.25s ease;
    padding: 3px 6px;
    border-radius: 6px;
}

.mode-toggle .mode-label:first-child {
    color: #6B63B5;
    margin-right: 8px;
    opacity: 0.7;
}

.mode-toggle .mode-label.active:first-child {
    opacity: 1;
    background: rgba(107, 99, 181, 0.1);
    text-shadow: 0 0 10px rgba(107, 99, 181, 0.2);
}

.mode-toggle .mode-label:last-child {
    color: #4C64E2;
    margin-left: 8px;
    opacity: 0.7;
}

.mode-toggle .mode-label.active {
    font-weight: 600;
    opacity: 1;
    background: rgba(76, 100, 226, 0.1);
    text-shadow: 0 0 10px rgba(76, 100, 226, 0.2);
}

.v-switch__track {
    display: inline-flex;
    align-items: center;
    font-size: 0.5rem;
    padding: 0 5px;
    background-color: #6B63B5 !important;
    border-radius: 9999px;
    height: 14px;
    opacity: 0.6;
    min-width: 36px;
    cursor: pointer;
    transition: 0.2s background-color cubic-bezier(0.4, 0, 0.2, 1);
}

/* Add responsive styling */
@media (max-width: 768px) {
    .mode-label {
        font-size: 12px;
    }
}

.header-spacer {
    flex: 1;
}

/* Animation */
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

/* Responsive adjustments */
@media (max-width: 768px) {
    .floating-header {
        width: calc(100% - 20px);
        top: 10px;
    }

    .header-content {
        padding: 12px 16px;
    }
}

@media (max-width: 480px) {
    .app-card {
        padding: 30px 20px;
    }
}

.title-with-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.tako-title-container {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.tako-name {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary, #4C64E2);
  letter-spacing: -0.5px;
}

.tako-subtitle {
  font-size: 16px;
  font-weight: 400;
  color: #666;
  opacity: 0.7;
}



/* For mobile responsiveness */
@media (max-width: 600px) {
  .tako-title-container {
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  
  .tako-name {
    font-size: 24px;
  }
  
  .tako-subtitle {
    font-size: 14px;
  }
}
</style>
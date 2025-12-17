<template>
    <div class="app-page">
        <!-- Header -->
        <header v-if="showHeader" class="floating-header">
            <div class="header-content">
                <!-- Brand section only shows when logged in -->
                <div v-if="showLogout" class="brand">
                    <img src="@/assets/fctr-icon.svg" alt="fctr" height="28" />
                    <div class="brand-divider"></div>
                    <div class="title-with-badge">
                        <div class="tako-title-container">
                            <span class="tako-name">Tako AI</span>
                        </div>
                        <div class="beta-badge">BETA</div>
                    </div>
                </div>
                <!-- Empty spacer when not logged in -->
                <div v-else></div>

                <div class="header-actions">
                    <!-- Add SyncStatusButton here -->
                    <div class="header-spacer"></div>
                    <SyncStatusButton v-if="showLogout" />
                    <button v-if="showLogout" class="logout-btn" aria-label="Logout"
                        @click="handleLogout">
                        <v-icon size="16">mdi-logout</v-icon>
                        <span>Log out</span>
                    </button>
                </div>
            </div>
        </header>

        <!-- Content Surface (rounded top corners, gradient background) -->
        <div class="content-surface">
            <!-- Main Content -->
            <main class="main-content" :class="contentClass">
                <slot></slot>
            </main>

            <!-- Footer -->
            <footer class="page-footer">
            <div class="footer-content">
                <span>Powered by </span>
                <a href="https://fctr.io" target="_blank" class="branded-link">
                    fctr
                </a>
                <span class="version-tag">{{ appVersion }}</span>
                <span class="disclaimer">• Responses may require verification</span>
            </div>
        </footer>
        </div>
    </div>
</template>

<script setup>
import { useAuth } from '@/composables/useAuth'
import { useRouter } from 'vue-router'
import { computed } from 'vue'
import SyncStatusButton from '@/components/sync/SyncStatusButton.vue'

const props = defineProps({
    showHeader: {
        type: Boolean,
        default: true
    },
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

const appVersion = computed(() => {
    const version = import.meta.env.VITE_APP_VERSION
    return version ? `v${version}` : 'v1.3-beta'
})

const handleLogout = async () => {
    await auth.logout()
    router.push('/login')
}
</script>

<style>
.app-page {
    min-height: 100vh;
    background: #FFFFFF;
    position: relative;
    overflow-y: auto;
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
}

/* Content surface below header with rounded top corners and gradient */
.content-surface {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin: 0 16px 16px 16px;
    border-top-left-radius: 24px;
    border-top-right-radius: 24px;
    border-bottom-left-radius: 24px;
    border-bottom-right-radius: 24px;
    /* Calm Slate - soft blue gradient */
    background: linear-gradient(135deg, rgb(210, 218, 241), rgb(210, 220, 240), rgb(220, 238, 245));
    overflow: hidden;
}




/* Header */
.floating-header {
    position: relative;
    margin: 0;
    z-index: 100;
    width: 100%;
    max-width: 100%;
    min-height: 56px;

    /* Frosted glass effect */
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(12px) saturate(180%);
    -webkit-backdrop-filter: blur(12px) saturate(180%);
    border-bottom: 1px solid rgba(255, 255, 255, 0.3);
    transition: all 0.2s ease;
}

.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    max-width: 100%;
    margin: 0;
    padding: 12px 24px;
    box-shadow: none;
    position: relative;
    z-index: 2;
}

.floating-header:hover {
    background: #ffffff;
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

.tako-name {
    font-family: var(--font-family-display);
    font-weight: 700;
    font-size: 19px;
    letter-spacing: -0.01em;
    color: #1e293b;
}

.title-with-badge {
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand-divider {
    height: 16px;
    width: 1px;
    background: rgba(76, 100, 226, 0.18);
}

.beta-badge {
    background: rgba(76, 100, 226, 0.1);
    color: #4C64E2;
    font-size: 10px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 6px;
    letter-spacing: 0.5px;
    line-height: 1;
}

.logout-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    background: rgba(248, 250, 252, 0.9);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(100, 116, 139, 0.15);
    color: #64748b;
    cursor: pointer;
    padding: 8px 14px;
    border-radius: 20px;
    font-family: var(--font-family-body);
    font-size: 13px;
    font-weight: 500;
    transition: all 0.2s ease;
}

.logout-btn:hover {
    background: #ffffff;
    border-color: rgba(100, 116, 139, 0.25);
    color: #475569;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
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
    justify-content: center;
    align-items: center;
    flex-grow: 1;
    padding: 20px 0;
}


/* Footer inside the content surface */
.page-footer {
    position: relative;
    margin-top: auto;
    padding: 14px 0;
    text-align: center;
    font-size: 13px;
    color: var(--text-muted);
    background: transparent;
    z-index: 50;
}

/* Hide the old pseudo border */
.page-footer::before {
    display: none;
}

.footer-content {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    max-width: var(--max-width);
    margin: 0 auto;
}

.version-tag {
    color: var(--text-muted);
    font-size: 12px;
    opacity: 0.8;
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
        width: 100%;
    }

    .header-content {
        padding: 10px 16px;
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

/* For mobile responsiveness */
@media (max-width: 600px) {
  .tako-name {
    font-size: 18px;
  }
}
</style>
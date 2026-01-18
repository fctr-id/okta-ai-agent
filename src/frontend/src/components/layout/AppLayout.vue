<template>
    <div class="app-page">
        <!-- Header -->
        <header v-if="showHeader" class="floating-header">
            <div class="header-content">
                <!-- Brand section: Wordmark + Tako AI -->
                <div class="brand">
                    <img src="@/assets/fctr-wordmark.svg" alt="fctr" />
                    
                    <div class="brand-divider"></div>
                    <div class="title-with-badge">
                        <div class="tako-title-container">
                            <span class="tako-name">Tako AI</span>
                        </div>
                        <div v-if="showLogout" class="beta-badge">BETA</div>
                    </div>
                </div>

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
    background: #ffffff;
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
    margin: 0;
    border-radius: 0;
    /* Calm Slate - soft blue gradient */
    background: linear-gradient(135deg, rgb(210, 218, 241), rgb(210, 220, 240), rgb(220, 238, 245));
    overflow: hidden;
}




/* Header */
.floating-header {
    position: sticky;
    top: 0;
    left: 0;
    right: 0;
    margin: 0;
    z-index: 100;
    width: 100%;
    min-height: 64px;

    /* High-end frosted glass */
    background: rgba(255, 255, 255, 0.75);
    backdrop-filter: blur(20px) saturate(160%);
    -webkit-backdrop-filter: blur(20px) saturate(160%);
    border-bottom: 1px solid rgba(0, 0, 0, 0.05);
    transition: all 0.3s ease;
}

.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    max-width: 100%;
    margin: 0;
    padding: 0 32px;
    height: 64px;
    position: relative;
    z-index: 2;
}

.floating-header:hover {
    background: rgba(255, 255, 255, 0.9);
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
}

.brand img {
    display: block;
    height: 28px;
    width: auto;
    object-fit: contain;
}

.tako-name {
    font-family: var(--font-family-display);
    font-weight: 800;
    font-size: 17px;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #475569;
    display: flex;
    align-items: center;
}

.title-with-badge {
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand-divider {
    height: 14px;
    width: 2px;
    background: #4C64E2;
    align-self: center;
    border-radius: 4px;
    opacity: 0.2;
}

.beta-badge {
    background: rgba(76, 100, 226, 0.08);
    border: 1px solid rgba(76, 100, 226, 0.2);
    color: #4C64E2;
    font-size: 9px;
    font-weight: 800;
    padding: 2px 6px;
    border-radius: 6px;
    letter-spacing: 0.05em;
    line-height: 1;
}

.logout-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 1px solid rgba(15, 23, 42, 0.1);
    color: #475569;
    cursor: pointer;
    padding: 7px 16px;
    border-radius: 8px;
    font-family: var(--font-family-body);
    font-size: 13px;
    font-weight: 600;
    transition: all 0.2s ease;
}

.logout-btn:hover {
    background: #ffffff;
    border-color: rgba(15, 23, 42, 0.2);
    color: #0f172a;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
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

/* For mobile responsiveness */
@media (max-width: 600px) {
  .tako-name {
    font-size: 18px;
  }
}
</style>
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
        <div class="content-surface" :class="{ 'sidebar-expanded': showLogout && !sidebarCollapsed }">
            <!-- Main Content -->
            <main class="main-content" :class="[contentClass, { 'sidebar-expanded': showLogout && !sidebarCollapsed }]">
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

        <!-- Sidebar (Moved outside content-surface to avoid flex interference) -->
        <HistorySidebar 
            v-if="showLogout" 
            ref="sidebarRef"
            @select="handleSelectHistory"
            @new-session="handleNewSession"
            @collapse-change="handleCollapseChange"
        />
    </div>
</template>

<script setup>
import { useAuth } from '@/composables/useAuth'
import { useRouter } from 'vue-router'
import { computed, ref, provide } from 'vue'
import SyncStatusButton from '@/components/sync/SyncStatusButton.vue'
import HistorySidebar from './HistorySidebar.vue'

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
const sidebarRef = ref(null)
const sidebarCollapsed = ref(false)

// Provide sidebar refresh to children
const refreshHistory = () => sidebarRef.value?.refresh()
provide('refreshHistory', refreshHistory)

// Expose for parent components (like ChatInterfaceV2)
defineExpose({
    refreshHistory
})

const appVersion = computed(() => {
    const version = import.meta.env.VITE_APP_VERSION
    return version ? `v${version}` : 'v2.0.0-beta'
})

const handleLogout = async () => {
    await auth.logout()
    router.push('/login')
}

// Track sidebar collapse state
const handleCollapseChange = (isCollapsed) => {
    sidebarCollapsed.value = isCollapsed
}

// Global event bus for history interactions
const handleSelectHistory = (item) => {
    window.dispatchEvent(new CustomEvent('tako:select-history', { detail: item }))
}

const handleNewSession = () => {
    window.dispatchEvent(new CustomEvent('tako:new-session'))
}
</script>

<style>
.app-page {
    --sidebar-width: 280px;
    --collapsed-sidebar-width: 48px;
    --header-height: 56px;
    min-height: 100vh;
    height: 100dvh;
    background: var(--bg-page);
    position: relative;
    overflow-y: auto;
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
}

/* Header - flat, hairline divider */
.floating-header {
    position: sticky;
    top: 0;
    left: 0;
    right: 0;
    margin: 0;
    z-index: 100;
    width: 100%;
    min-height: var(--header-height);
    background: var(--bg-page);
    border-bottom: 1px solid var(--border-color);
}

.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    max-width: 100%;
    margin: 0;
    padding: 0 24px;
    height: var(--header-height);
    position: relative;
    z-index: 2;
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
}

.brand img {
    display: block;
    height: 27px;
    width: auto;
    object-fit: contain;
}

.tako-name {
    font-family: var(--font-family-display);
    font-weight: 625;
    font-size: 18px;
    line-height: 1;
    letter-spacing: -0.02em;
    color: var(--text-primary);
    display: flex;
    align-items: center;
}

.title-with-badge {
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand-divider {
    height: 18px;
    width: 1px;
    background: var(--border-strong);
    align-self: center;
}

.beta-badge {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 9px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
    letter-spacing: 0.06em;
    line-height: 1;
}

.logout-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    background: #ffffff;
    border: 1px solid var(--border-strong);
    color: var(--text-primary);
    cursor: pointer;
    padding: 6px 12px;
    border-radius: 8px;
    font-family: var(--font-family-body);
    font-size: 13px;
    font-weight: 500;
    box-shadow: none;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.logout-btn:hover {
    background: #ffffff;
    border-color: rgba(var(--primary-rgb), 0.24);
    color: var(--text-primary);
    box-shadow: none;
}

.header-spacer {
    flex: 1;
}

/* Content surface - flat, calm canvas */
.content-surface {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin: 0;
    border-radius: 0;
    background:
        linear-gradient(rgba(15, 23, 42, 0.042) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15, 23, 42, 0.042) 1px, transparent 1px),
        var(--bg-page);
    background-size: 28px 28px;
}

/* Main content area */
.main-content {
    width: 100%;
    max-width: none;
    margin: 0;
    padding-top: 0;
    padding-bottom: 0;
    padding-left: 32px;
    padding-right: 32px;
    /* Reduced from 80px */
    flex-grow: 1;
    /* Add this to make it expand and fill space */
    display: flex;
    flex-direction: column;
    transition: padding-left 0.38s cubic-bezier(0.16, 1, 0.3, 1), padding-right 0.38s cubic-bezier(0.16, 1, 0.3, 1);
}

/* Adjust content positioning when sidebar is expanded */
/* Use padding instead of margin to maintain centering */
.main-content.sidebar-expanded {
    padding-left: calc(var(--sidebar-width) + 32px);
}

.content-surface.sidebar-expanded .page-footer {
    padding-left: var(--sidebar-width);
}


/* For auth pages - centered boxes */
.auth-content {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    flex: 1;
    width: 100%;
    padding: 16px 0 clamp(72px, 10vh, 96px);
}


/* Footer inside the content surface */
.page-footer {
    position: relative;
    margin-top: auto;
    padding: 12px 0;
    text-align: center;
    font-size: 11px;
    color: var(--text-muted);
    background: transparent;
    z-index: 50;
    opacity: 0.85;
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
    background: var(--primary);
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
    box-shadow: none;
    border: 1px solid var(--border-color);
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

    .main-content {
        padding-left: 16px;
        padding-right: 16px;
    }

    .main-content.sidebar-expanded {
        padding-left: calc(var(--collapsed-sidebar-width) + 16px);
    }

    .content-surface.sidebar-expanded .page-footer {
        padding-left: var(--collapsed-sidebar-width);
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
        font-size: 16px;
  }
}
</style>
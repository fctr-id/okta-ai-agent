<template>
    <div class="sync-status-container">
        <v-menu v-model="showDropdown" :close-on-content-click="false" location="bottom end" max-width="320"
            transition="slide-y-transition" :offset="[10, 10]">
            <template v-slot:activator="{ props: menuProps }">
                <v-btn v-bind="menuProps" class="sync-button" :class="{ 'px-2': $vuetify.display.smAndDown }"
                    variant="tonal" color="primary" size="small">
                    <div class="d-flex align-center">
                        <div class="status-indicator me-2" :class="statusColor"></div>
                        <span v-if="!$vuetify.display.smAndDown">{{ statusText }}</span>
                    </div>
                </v-btn>
            </template>

            <!-- Modern dropdown with enhanced aesthetics -->
            <div class="modern-dropdown">
                <div class="modern-content">
                    <!-- Header with gradient background -->
                    <div class="modern-header">
                        <h3>Okta Data Sync</h3>

                        <!-- Enhanced icon button with same styling as ChatInterface -->
                        <v-tooltip text="Start Sync" location="bottom" v-if="!isSyncing">
                            <template v-slot:activator="{ props }">
                                <button v-bind="props" class="action-btn primary" @click="handleStartSync"
                                    :disabled="isStarting">
                                    <v-icon v-if="!isStarting">mdi-sync</v-icon>
                                    <v-progress-circular v-else indeterminate size="20" width="2"
                                        color="primary"></v-progress-circular>
                                </button>
                            </template>
                        </v-tooltip>

                        <!-- Enhanced stop button with same styling -->
                        <v-tooltip text="Cancel Sync" location="bottom" v-else>
                            <template v-slot:activator="{ props }">
                                <button v-bind="props" class="action-btn error" @click="cancelSync">
                                    <v-icon>mdi-stop</v-icon>
                                </button>
                            </template>
                        </v-tooltip>
                    </div>

                    <!-- Enhanced Sync Progress with gradient background -->
                    <div v-if="isSyncing" class="progress-section">
                        <div class="sync-status-text">
                            <div class="pulse-dot"></div>
                            <span>Syncing data from Okta...</span>
                        </div>
                    </div>

                    <!-- Entity Cards with enhanced visual appeal -->
                    <div class="entity-grid">
                        <div class="entity-card entity-1">
                            <div class="entity-icon">
                                <v-icon size="small">mdi-account-multiple</v-icon>
                            </div>
                            <div class="entity-details">
                                <div class="entity-count" :class="{ 'entity-count-large': entityCounts.users > 9999 }">
                                    {{ entityCounts.users }}
                                </div>
                                <div class="entity-label">Users</div>
                            </div>
                        </div>
                        <div class="entity-card entity-2">
                            <div class="entity-icon">
                                <v-icon size="small">mdi-account-group</v-icon>
                            </div>
                            <div class="entity-details">
                                <div class="entity-count" :class="{ 'entity-count-large': entityCounts.groups > 9999 }">
                                    {{ entityCounts.groups }}
                                </div>
                                <div class="entity-label">Groups</div>
                            </div>
                        </div>
                        <div class="entity-card entity-3">
                            <div class="entity-icon">
                                <v-icon size="small">mdi-application</v-icon>
                            </div>
                            <div class="entity-details">
                                <div class="entity-count"
                                    :class="{ 'entity-count-large': entityCounts.applications > 9999 }">
                                    {{ entityCounts.applications }}
                                </div>
                                <div class="entity-label">Applications</div>
                            </div>
                        </div>
                        <!-- Conditional Devices/Policies -->
                        <div class="entity-card entity-4" v-if="entityCounts.devices && entityCounts.devices > 0">
                            <div class="entity-icon">
                                <v-icon size="small">mdi-devices</v-icon>
                            </div>
                            <div class="entity-details">
                                <div class="entity-count"
                                    :class="{ 'entity-count-large': entityCounts.devices > 9999 }">
                                    {{ entityCounts.devices }}
                                </div>
                                <div class="entity-label">Devices</div>
                            </div>
                        </div>
                        
                        <!-- Show Policies only if no devices or devices count is 0 -->
                        <div class="entity-card entity-4" v-else>
                            <div class="entity-icon">
                                <v-icon size="small">mdi-shield-check</v-icon>
                            </div>
                            <div class="entity-details">
                                <div class="entity-count"
                                    :class="{ 'entity-count-large': entityCounts.policies > 9999 }">
                                    {{ entityCounts.policies }}
                                </div>
                                <div class="entity-label">Policies</div>
                            </div>
                        </div>
                    </div>

                    <!-- Last sync time with improved styling -->
                    <div class="last-sync">
                        <div class="last-sync-label">
                            <v-icon size="16" class="me-1">mdi-clock-outline</v-icon>
                            Last updated
                        </div>
                        <span class="last-sync-time">{{ formattedLastSyncTime() }}</span>
                    </div>

                    <!-- Error message with user-friendly text -->
                    <transition name="fade">
                        <div v-if="syncError" class="error-message">
                            <v-icon size="small" class="me-1">mdi-alert-circle</v-icon>
                            <span>{{ friendlyErrorMessage }}</span>
                        </div>
                    </transition>
                </div>
            </div>
        </v-menu>
    </div>
</template>

<style scoped>
.sync-status-container {
    position: relative;
}

.sync-button {
    background: rgba(76, 100, 226, 0.08) !important;
    color: #4C64E2 !important;
    box-shadow: none !important;
    border: 1px solid rgba(76, 100, 226, 0.15) !important;
    border-radius: 20px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
}

.sync-button:hover {
    background: rgba(76, 100, 226, 0.12) !important;
    transform: none !important;
    box-shadow: none !important;
}

.sync-button .status-indicator {
    border: none !important;
}

/* Minimal status indicator - 2026 style */
.status-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    transition: background-color 0.2s ease;
}

.green {
    background: #22c55e;
}

.orange {
    background: #f59e0b;
    animation: pulse-subtle 2s infinite ease-in-out;
}

.red {
    background: #ef4444;
}

.grey {
    background: #9ca3af;
}

.blue {
    background: #4C64E2;
}

@keyframes pulse {
    0% {
        box-shadow: 0 0 0 0 rgba(255, 152, 0, 0.6);
    }

    70% {
        box-shadow: 0 0 0 8px rgba(255, 152, 0, 0);
    }

    100% {
        box-shadow: 0 0 0 0 rgba(255, 152, 0, 0);
    }
}

/* Minimal dropdown - 2026 style */
.modern-dropdown {
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    border: 1px solid #e5e7eb;
    width: 300px;
}

.modern-content {
    border-radius: 12px;
    background: white;
    overflow: hidden;
}

/* Clean header - 2026 style */
.modern-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px;
    border-bottom: 1px solid #f4f4f5;
}

.modern-header h3 {
    font-size: 14px;
    font-weight: 600;
    color: #18181b;
    margin: 0;
    letter-spacing: -0.01em;
}

/* Minimal action buttons - 2026 style */
.action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    transition: background-color 0.15s ease;
}

.action-btn.primary {
    background: #4C64E2;
    color: white;
}

.action-btn.primary:hover:not(:disabled) {
    background: #3b50c4;
}

.action-btn.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.action-btn.error {
    background: #ef4444;
    color: white;
}

.action-btn.error:hover {
    background: #dc2626;
}

/* Minimal progress section */
.progress-section {
    padding: 14px 16px;
    background: #fafafa;
    display: flex;
    align-items: center;
    justify-content: center;
}

.progress-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}

.sync-status-text {
    display: flex;
    align-items: center;
}

.sync-status-text span {
    font-size: 13px;
    font-weight: 500;
    color: #52525b;
}

.pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #f59e0b;
    margin-right: 10px;
    animation: pulse-subtle 1.5s infinite ease-in-out;
}

@keyframes pulse-subtle {
    0%, 100% {
        opacity: 1;
    }
    50% {
        opacity: 0.5;
    }
}

.progress-info span {
    font-size: 13px;
    color: #666;
    letter-spacing: 0.2px;
}

.progress-percentage {
    font-weight: 600;
    font-size: 14px;
    color: var(--primary);
}

/* Beautiful progress bar with gradient and animation */
.progress-bar-container {
    height: 6px;
    width: 100%;
    background: transparent;
    border-radius: 10px;
    overflow: hidden;
    position: relative;
}

.progress-bar-background {
    position: absolute;
    inset: 0;
    background: rgba(76, 100, 226, 0.12);
    border-radius: 10px;
}

.progress-bar-filled {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), #5e72e4, #7d4ce2);
    border-radius: 10px;
    transition: width 0.5s cubic-bezier(0.25, 1, 0.5, 1);
    position: relative;
    overflow: hidden;
}

.progress-bar-filled::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(90deg,
            rgba(255, 255, 255, 0) 0%,
            rgba(255, 255, 255, 0.3) 50%,
            rgba(255, 255, 255, 0) 100%);
    animation: shimmer 2s infinite;
}

@keyframes shimmer {
    0% {
        transform: translateX(-100%);
    }

    100% {
        transform: translateX(100%);
    }
}

/* Minimal entity grid - 2026 style */
.entity-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding: 12px 16px;
}

.entity-card {
    display: flex;
    align-items: center;
    padding: 10px 12px;
    border-radius: 10px;
    background: #fafafa;
    transition: background-color 0.15s ease;
    border: none;
    min-width: 110px;
}

.entity-card:hover {
    background: #f0f0f5;
}

/* Subtle purple/pink tints for entity cards */
.entity-1 {
    background: rgba(99, 102, 241, 0.04);
}
.entity-1:hover {
    background: rgba(99, 102, 241, 0.08);
}

.entity-2 {
    background: rgba(139, 92, 246, 0.04);
}
.entity-2:hover {
    background: rgba(139, 92, 246, 0.08);
}

.entity-3 {
    background: rgba(168, 85, 247, 0.04);
}
.entity-3:hover {
    background: rgba(168, 85, 247, 0.08);
}

.entity-4 {
    background: rgba(192, 132, 252, 0.04);
}
.entity-4:hover {
    background: rgba(192, 132, 252, 0.08);
}

.entity-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    margin-right: 10px;
    background: white;
    border: 1px solid #e5e7eb;
}

.entity-icon :deep(.v-icon) {
    color: #71717a;
    font-size: 18px;
}

.entity-details {
    display: flex;
    flex-direction: column;
    min-width: 0;
    /* Allow flex item to shrink below content size if needed */
    flex: 1;
}

.entity-count {
    font-weight: 600;
    font-size: 15px;
    color: #18181b;
    line-height: 1;
    margin-bottom: 3px;
    white-space: nowrap;
}

.entity-label {
    font-size: 11px;
    color: #71717a;
    font-weight: 500;
}

.entity-count-large {
    font-size: 13px;
    letter-spacing: -0.02em;
}

/* Minimal last sync footer */
.last-sync {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-top: 1px solid #f4f4f5;
    background: white;
}

.last-sync-label {
    font-size: 12px;
    color: #71717a;
    display: flex;
    align-items: center;
}

.last-sync-label :deep(.v-icon) {
    color: #a1a1aa;
}

.last-sync-time {
    font-size: 12px;
    font-weight: 500;
    color: #3f3f46;
}

/* Minimal error message */
.error-message {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    background: #fef2f2;
    border-top: 1px solid #fecaca;
    color: #dc2626;
    font-size: 12px;
}

.error-message :deep(.v-icon) {
    color: #dc2626;
}

/* Matching transitions from ChatInterface */
.fade-enter-active,
.fade-leave-active {
    transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
    opacity: 0;
}

/* Tooltip matching */
:deep(.v-tooltip .v-overlay__content) {
    background-color: var(--primary-dark);
    color: white;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 4px;
    opacity: 0.95;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}
</style>

<script setup>
import { ref, computed, watch } from 'vue';
import { useSync } from '@/composables/useSync';

const {
    isSyncing,
    syncStatus,
    syncProgress,
    entityCounts,
    syncError,
    startSync,
    cancelSync,
    formattedLastSyncTime,
} = useSync();

// UI state
const showDropdown = ref(false);
const isStarting = ref(false);

// Computed properties
const statusColor = computed(() => {
    if (syncStatus.value === 'running') return 'orange';  // In-progress
    if (syncStatus.value === 'completed') return 'green'; // Success
    if (syncStatus.value === 'failed' || syncStatus.value === 'canceled') return 'red'; // Error
    if (syncStatus.value === 'idle') return 'blue'; // Ready but not active
    return 'grey'; // Default for 'none' or unknown
});

const statusText = computed(() => {
    if (syncStatus.value === 'running') return 'Syncing';
    if (syncStatus.value === 'completed') return 'Synced';
    if (syncStatus.value === 'failed') return 'Failed';
    if (syncStatus.value === 'canceled') return 'Canceled';
    if (syncStatus.value === 'idle') return 'Ready'; // Or "Not synced"
    return 'Not synced';
});

// Format error message to be user-friendly
const friendlyErrorMessage = computed(() => {
    if (!syncError.value) return null;
    const error = syncError.value.toLowerCase();
    if (error.includes('401') || error.includes('invalid token')) {
        return 'Invalid API token. Please check your Okta credentials.';
    }
    if (error.includes('403') || error.includes('forbidden')) {
        return 'Access denied. Check API permissions.';
    }
    if (error.includes('timeout')) {
        return 'Sync timed out. Please try again.';
    }
    if (error.includes('network') || error.includes('fetch')) {
        return 'Network error. Check your connection.';
    }
    // For other errors, truncate if too long
    if (syncError.value.length > 60) {
        return 'Sync failed. Check Okta configuration.';
    }
    return syncError.value;
});

// Methods
const handleStartSync = async () => {
    isStarting.value = true;
    await startSync();
    isStarting.value = false;
};

// Watch for status changes to auto-close dropdown when sync completes
watch(syncStatus, (newStatus, oldStatus) => {
    if (
        (oldStatus === 'running' || oldStatus === 'idle') &&
        ['completed', 'failed', 'canceled'].includes(newStatus)
    ) {
        // Auto-close dropdown after sync completes with a delay
        setTimeout(() => {
            showDropdown.value = false;
        }, 2000);
    }
});
</script>
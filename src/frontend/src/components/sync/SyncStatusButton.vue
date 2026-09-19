<template>
    <div class="sync-status-container">
        <v-menu v-model="showDropdown" :close-on-content-click="false" location="bottom end" max-width="340"
            transition="slide-y-transition" :offset="[10, 10]">
            <template v-slot:activator="{ props: menuProps }">
                <v-btn v-bind="menuProps" class="sync-button" :class="[{ 'px-2': $vuetify.display.smAndDown }, `status-${statusColor}`]"
                    variant="text" size="small" :aria-label="`Okta data sync: ${statusText}`">
                    <div class="d-flex align-center">
                        <div class="status-indicator me-2" :class="statusColor"></div>
                        <span v-if="!$vuetify.display.smAndDown">{{ statusText }}</span>
                        <v-icon class="sync-chevron" size="14" aria-hidden="true">mdi-chevron-down</v-icon>
                    </div>
                </v-btn>
            </template>

            <div class="modern-dropdown" role="region" aria-label="Okta data sync">
                <div class="modern-content">
                    <div class="modern-header">
                        <h3>Okta data sync</h3>

                            <v-tooltip text="Start Sync" location="bottom" v-if="!isSyncing">
                            <template v-slot:activator="{ props }">
                                <button v-bind="props" type="button" class="action-btn primary" @click="handleStartSync"
                                    :disabled="isStarting">
                                    <v-icon v-if="!isStarting" size="15" aria-hidden="true">mdi-sync</v-icon>
                                    <v-progress-circular v-else indeterminate size="14" width="2"
                                        color="white" aria-hidden="true"></v-progress-circular>
                                    <span>{{ isStarting ? 'Starting…' : 'Sync now' }}</span>
                                </button>
                            </template>
                        </v-tooltip>

                            <v-tooltip text="Cancel Sync" location="bottom" v-else>
                            <template v-slot:activator="{ props }">
                                <button v-bind="props" type="button" class="action-btn error" @click="cancelSync">
                                    <v-icon size="15" aria-hidden="true">mdi-stop</v-icon>
                                    <span>Stop sync</span>
                                </button>
                            </template>
                        </v-tooltip>
                    </div>

                    <div v-if="isSyncing" class="progress-section" role="status">
                        <div class="sync-status-text">
                            <div class="pulse-dot"></div>
                            <span>Syncing data from Okta...</span>
                        </div>
                    </div>

                    <!-- Counts share one compact grid, without nested cards. -->
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
                                <div class="entity-label">Apps</div>
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
                        <div v-if="syncError" class="error-message" role="alert">
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
    --sync-surface: #f4f7fc;
    --sync-border: #dce3ef;
    --sync-ink: #53617a;
    background: var(--sync-surface) !important;
    color: var(--sync-ink) !important;
    box-shadow: none !important;
    border: 1px solid var(--sync-border) !important;
    border-radius: 9px !important;
    font-weight: 500 !important;
    font-size: 12px !important;
    height: 32px !important;
    min-height: 32px !important;
    padding: 0 10px !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    transition: box-shadow 0.15s ease;
}

.sync-button:hover {
    transform: none !important;
    box-shadow: 0 0 0 2px var(--sync-surface) !important;
}

.sync-button:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 3px;
}

.sync-chevron {
    margin-left: 6px;
    opacity: 0.7;
}

.sync-button.status-green {
    --sync-surface: #eaf7f0;
    --sync-border: #c4e5d4;
    --sync-ink: #237453;
}

.sync-button.status-orange {
    --sync-surface: #fff6e6;
    --sync-border: #f1d8a9;
    --sync-ink: #946314;
}

.sync-button.status-red {
    --sync-surface: #fff0f0;
    --sync-border: #efcdcd;
    --sync-ink: #b34646;
}

.sync-button.status-blue {
    --sync-surface: #edf2ff;
    --sync-border: #d4dfff;
    --sync-ink: #4563bb;
}

.sync-button .status-indicator {
    border: none !important;
}

/* Minimal status indicator - 2026 style */
.status-indicator {
    width: 6px;
    height: 6px;
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
    background: var(--primary);
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

/* Match the white response surfaces and clearly defined section dividers. */
.modern-dropdown { width: min(340px, calc(100vw - 32px)); border: 1px solid #96a5b9; border-radius: 12px; background: #fff; box-shadow: 0 8px 24px rgba(30, 48, 76, .10); overflow: hidden; }
.modern-content { background: #f0f4f9; }
.modern-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--workspace-outline, #b8c2cf); background: #f8fafc; }
.modern-header h3 { margin: 0; color: #253248; font-size: 14px; font-weight: 600; line-height: 1.4; }
.action-btn { display: inline-flex; align-items: center; justify-content: center; gap: 5px; flex-shrink: 0; min-height: 30px; padding: 0 9px; border: 1px solid transparent; border-radius: 7px; font: inherit; font-size: 11px; font-weight: 550; cursor: pointer; transition: background .15s, border-color .15s; }
.action-btn.primary { background: var(--primary); border-color: #375bcc; color: #fff; }
.action-btn.primary:hover:not(:disabled) { background: var(--primary-hover); border-color: #2948a8; }
.action-btn:disabled { opacity: .55; cursor: default; }
.action-btn.error { color: #aa3636; background: #fff0f0; border-color: #e6b8b8; }
.action-btn.error:hover { background: #ffe3e3; border-color: #ce9595; }
.action-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.progress-section { padding: 10px 16px; border-bottom: 1px solid #dbe3ef; background: #edf3ff; }
.sync-status-text { display: flex; align-items: center; gap: 8px; color: #385ea9; font-size: 12px; }
.pulse-dot { width: 6px; height: 6px; flex-shrink: 0; border-radius: 50%; background: currentColor; animation: pulse-subtle 1.5s ease-in-out infinite; }
@keyframes pulse-subtle { 50% { opacity: .4; } }
.entity-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.entity-card { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 16px; background: #f0f4f9; }
.entity-card:nth-child(odd) { border-right: 1px solid #dde3eb; }
.entity-card:nth-child(n+3) { border-top: 1px solid #dde3eb; }
.entity-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 7px; flex-shrink: 0; background: #edf3ff; color: #4568b3; }
.entity-2 .entity-icon { background: #f2ecfa; color: #7754aa; }
.entity-4 .entity-icon { background: #eaf5f5; color: #276e78; }
.entity-icon :deep(.v-icon) { font-size: 16px; }
.entity-details { min-width: 0; }
.entity-count { color: #253248; font-size: 20px; font-weight: 600; line-height: 1.25; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.entity-count-large { font-size: 16px; }
.entity-label { margin-top: 3px; color: #64748b; font-size: 11px; line-height: 1.4; }
.last-sync { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 12px 16px; border-top: 1px solid var(--workspace-outline, #b8c2cf); background: #f8fafc; }
.last-sync-label { display: inline-flex; align-items: center; color: #64748b; font-size: 11px; }
.last-sync-time { color: #46566f; font-size: 11px; font-weight: 500; }
.error-message { display: flex; align-items: flex-start; gap: 5px; padding: 12px 16px; border-top: 1px solid #e6b8b8; background: #fff0f0; color: #a13333; font-size: 12px; overflow-wrap: anywhere; }
.error-message :deep(.v-icon) { flex-shrink: 0; margin-top: 2px; }
.fade-enter-active, .fade-leave-active { transition: opacity .15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .pulse-dot, .orange { animation: none; } .fade-enter-active, .fade-leave-active { transition: none; } }

/* Tooltip matching */
:deep(.v-tooltip .v-overlay__content) {
    background-color: var(--primary-dark);
    color: white;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 4px;
    opacity: 0.95;
    box-shadow: none;
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

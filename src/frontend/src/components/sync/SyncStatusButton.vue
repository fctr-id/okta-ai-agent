<template>
    <div class="sync-status-container">
        <v-menu v-model="showDropdown" :close-on-content-click="false" location="bottom end" max-width="360"
            transition="slide-y-transition" :offset="[10, 10]">
            <template v-slot:activator="{ props: menuProps }">
                <v-btn v-bind="menuProps" class="sync-button" :class="{ 'is-open': showDropdown }"
                    variant="text" size="small" :aria-label="`Okta data sync: ${statusText}`" :title="`Data sync: ${statusText}`">
                    <div class="sync-button-content">
                        <v-icon size="16" aria-hidden="true">mdi-sync</v-icon>
                        <span v-if="!$vuetify.display.smAndDown">Data sync</span>
                        <span class="status-indicator" :class="statusColor" aria-hidden="true"></span>
                        <v-icon class="sync-chevron" size="14" aria-hidden="true">mdi-chevron-down</v-icon>
                    </div>
                </v-btn>
            </template>

            <div class="modern-dropdown" role="region" aria-label="Okta data sync">
                <div class="modern-content">
                    <div class="modern-header">
                        <div class="sync-title-icon"><v-icon size="20" aria-hidden="true">mdi-database-outline</v-icon></div>
                        <div class="sync-title-copy">
                            <h3>Okta data sync</h3>
                            <p>Data available to Tako</p>
                        </div>
                        <button type="button" class="close-sync" aria-label="Close sync panel" @click="showDropdown = false">
                            <v-icon size="18" aria-hidden="true">mdi-close</v-icon>
                        </button>
                    </div>

                    <div class="sync-summary" role="status">
                        <span class="sync-state"><span class="status-indicator" :class="statusColor" aria-hidden="true"></span>{{ statusText }}</span>
                        <span class="sync-summary-description">{{ isSyncing ? 'Updating records from Okta…' : 'Record totals' }}</span>
                    </div>
                    <div v-if="isSyncing" class="sync-progress-track" aria-hidden="true">
                        <span></span>
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

                    <!-- Timestamp and primary action stay together below the counts. -->
                    <div class="last-sync">
                        <div class="last-sync-label">
                            <v-icon size="16" class="me-1">mdi-clock-outline</v-icon>
                            Last updated
                        </div>
                        <span class="last-sync-time">{{ formattedLastSyncTime() }}</span>
                    </div>
                    <div class="sync-actions">
                        <button v-if="!isSyncing" type="button" class="action-btn primary" @click="handleStartSync" :disabled="isStarting">
                            <v-icon v-if="!isStarting" size="15" aria-hidden="true">mdi-sync</v-icon>
                            <v-progress-circular v-else indeterminate size="14" width="2" color="white" aria-hidden="true" />
                            <span>{{ isStarting ? 'Starting…' : 'Sync now' }}</span>
                        </button>
                        <button v-else type="button" class="action-btn error" @click="cancelSync">
                            <v-icon size="15" aria-hidden="true">mdi-stop</v-icon>
                            <span>Stop sync</span>
                        </button>
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
.sync-status-container { position: relative; }
.sync-button {
    background: #fff !important;
    color: #334b72 !important;
    border: 1px solid #cbd7ea !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(23, 36, 58, .05) !important;
    height: 34px !important;
    min-height: 34px !important;
    padding: 0 11px !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    transition: background .15s, border-color .15s;
}
.sync-button:hover, .sync-button.is-open { background: #eef3fc !important; border-color: #aebfe0 !important; }
.sync-button :deep(.v-btn__overlay) { opacity: 0 !important; }
.sync-button:focus-visible, .action-btn:focus-visible, .close-sync:focus-visible { outline: 2px solid var(--primary, #3e63dd); outline-offset: 3px; }
.sync-button-content { display: flex; align-items: center; gap: 7px; }
.sync-chevron { color: #647797; transition: transform .15s; }
.is-open .sync-chevron { transform: rotate(180deg); }
.status-indicator { display: inline-block; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.green { background: #299477; }
.orange { background: #b7791f; }
.red { background: #c44949; }
.grey { background: #8793a4; }
.blue { background: #3e63dd; }
.modern-dropdown { width: min(360px, calc(100vw - 32px)); border: 1px solid #d5deec; border-radius: 14px; background: #fff; box-shadow: 0 16px 40px -12px rgba(23, 36, 58, .22), 0 3px 10px rgba(23, 36, 58, .05); overflow: hidden; }
.modern-content { background: #fff; }
.modern-header { display: flex; align-items: center; gap: 10px; padding: 18px 18px 16px; background: #f7f9fd; border-bottom: 1px solid #e3e9f2; }
.sync-title-icon { display: grid; place-items: center; width: 36px; height: 36px; flex-shrink: 0; border: 1px solid #dbe5f6; border-radius: 10px; background: #eef3fc; color: #4567ad; }
.sync-title-copy { flex: 1; min-width: 0; }
.modern-header h3 { margin: 0; color: #17243a; font-size: 14px; font-weight: 600; line-height: 1.4; }
.sync-title-copy p { margin: 3px 0 0; color: #5d6b7d; font-size: 12px; line-height: 1.4; }
.close-sync { display: grid; place-items: center; flex-shrink: 0; width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent; color: #63738b; cursor: pointer; }
.close-sync:hover { background: #e8eef8; color: #243957; }
.sync-summary { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px 12px; padding: 14px 18px 12px; font-size: 12px; }
.sync-state { display: inline-flex; align-items: center; gap: 7px; color: #334155; font-weight: 500; }
.sync-summary-description { color: #5d6b7d; }
.sync-progress-track { height: 3px; margin: 0 18px 12px; overflow: hidden; border-radius: 2px; background: #e7edf8; }
.sync-progress-track span { display: block; width: 40%; height: 100%; border-radius: inherit; background: #597bd4; animation: sync-progress 1.8s ease-in-out infinite alternate; }
@keyframes sync-progress { from { transform: translateX(0); } to { transform: translateX(150%); } }
.entity-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0 18px 16px; }
.entity-card { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 13px 12px; border: 1px solid #e3e9f2; border-radius: 10px; background: #f7f9fd; }
.entity-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0; background: #eaf0fc; color: #4e6daf; }
.entity-4 .entity-icon { background: #e5f1f0; color: #327d79; }
.entity-icon :deep(.v-icon) { font-size: 16px; }
.entity-details { min-width: 0; }
.entity-count { color: #243957; font-size: 20px; font-weight: 500; line-height: 1.25; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.entity-count-large { font-size: 16px; }
.entity-label { margin-top: 3px; color: #5d6b7d; font-size: 12px; line-height: 1.4; }
.last-sync { display: flex; flex-direction: column; gap: 4px; padding: 13px 18px 0; border-top: 1px solid #e3e9f2; }
.last-sync-label { display: inline-flex; align-items: center; color: #5d6b7d; font-size: 12px; }
.last-sync-time { padding-left: 20px; color: #334b72; font-size: 12px; font-weight: 400; line-height: 1.5; overflow-wrap: anywhere; }
.sync-actions { display: flex; padding: 14px 18px 18px; }
.action-btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; width: 100%; min-height: 34px; padding: 7px 12px; border: 1px solid transparent; border-radius: 8px; font: inherit; font-size: 12px; font-weight: 500; cursor: pointer; transition: background .15s, border-color .15s; }
.action-btn.primary { background: var(--primary, #3e63dd); border-color: #375bcc; color: #fff; box-shadow: 0 1px 2px rgba(23, 36, 58, .08); }
.action-btn.primary:hover:not(:disabled) { background: var(--primary-hover, #3556c3); }
.action-btn:disabled { opacity: .6; cursor: default; }
.action-btn.error { color: #a13333; background: #fff5f5; border-color: #ebcccc; }
.action-btn.error:hover { background: #fce8e8; }
.error-message { display: flex; align-items: flex-start; gap: 6px; margin: 0 18px 18px; padding: 10px 12px; border: 1px solid #f0d5d5; border-radius: 8px; background: #fff7f7; color: #a13333; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.error-message :deep(.v-icon) { flex-shrink: 0; margin-top: 2px; }
.fade-enter-active, .fade-leave-active { transition: opacity .15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .sync-progress-track span { animation: none; width: 100%; opacity: .55; } .sync-chevron, .fade-enter-active, .fade-leave-active { transition: none; } }
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

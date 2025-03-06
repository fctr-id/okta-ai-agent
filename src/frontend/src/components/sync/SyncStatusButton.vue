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
                        <div class="progress-info">
                            <div class="sync-status-text">
                                <div class="pulse-dot"></div>
                                <span>Syncing data from Okta...</span>
                            </div>
                            <span class="progress-percentage">{{ syncProgress }}%</span>
                        </div>
                        <div class="progress-bar-container">
                            <div class="progress-bar-background"></div>
                            <div class="progress-bar-filled" :style="{ width: `${syncProgress}%` }"></div>
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
                        <div class="entity-card entity-4">
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

                    <!-- Enhanced error message with icon and better visibility -->
                    <transition name="fade">
                        <div v-if="syncError" class="error-message">
                            <v-icon size="small" class="me-1">mdi-alert-circle</v-icon>
                            <span>{{ syncError }}</span>
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

/* Enhanced Sync Button with subtle hover effects */
.sync-button {
    transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
    border-radius: 10px;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.04);
}

.sync-button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(76, 100, 226, 0.15);
}

/* Enhanced status indicator with better animations */
.status-indicator {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
}

.green {
    background: linear-gradient(135deg, #4CAF50, #43A047);
    box-shadow: 0 0 10px rgba(76, 175, 80, 0.4);
}

.orange {
    background: linear-gradient(135deg, #FF9800, #F57C00);
    box-shadow: 0 0 10px rgba(255, 152, 0, 0.4);
    animation: pulse 2s infinite cubic-bezier(0.45, 0, 0.55, 1);
}

.red {
    background: linear-gradient(135deg, #F44336, #E53935);
    box-shadow: 0 0 10px rgba(244, 67, 54, 0.4);
}

.grey {
    background: linear-gradient(135deg, #9E9E9E, #757575);
    box-shadow: 0 0 5px rgba(158, 158, 158, 0.3);
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

/* Modern dropdown with refined aesthetics */
.modern-dropdown {
    background: white;
    border-radius: 16px;
    overflow: hidden;
    box-shadow:
        0 10px 30px rgba(0, 0, 0, 0.08),
        0 5px 15px rgba(76, 100, 226, 0.06),
        0 2px 5px rgba(0, 0, 0, 0.03);
    width: 320px;
    transform: translateY(0);
    transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
}

.modern-content {
    border-radius: 16px;
    background: white;
    overflow: hidden;
}

/* Gradient header like in chat interface */
.modern-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px;
    background: linear-gradient(135deg, rgba(76, 100, 226, 0.02), rgba(76, 100, 226, 0.08));
    border-bottom: 1px solid rgba(76, 100, 226, 0.08);
}

.modern-header h3 {
    font-size: 15px;
    font-weight: 500;
    color: var(--primary);
    margin: 0;
    letter-spacing: 0.2px;
    background: linear-gradient(90deg, var(--primary), #5e72e4);
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
}

/* Enhanced action buttons to match chat interface */
.action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    border: none;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
}

.action-btn.primary {
    background: linear-gradient(135deg, var(--primary), #5e72e4);
    color: white;
}

.action-btn.primary:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 4px 10px rgba(76, 100, 226, 0.25);
}

.action-btn.primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}

.action-btn.error {
    background: linear-gradient(135deg, #FF5252, #F44336);
    color: white;
}

.action-btn.error:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 10px rgba(244, 67, 54, 0.25);
}

/* Enhanced progress section with animation */
.progress-section {
    padding: 16px 18px;
    background: linear-gradient(135deg, rgba(76, 100, 226, 0.02), rgba(76, 100, 226, 0.05));
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
    gap: 8px;
}

.pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--primary);
    animation: pulse-small 1.5s infinite cubic-bezier(0.45, 0, 0.55, 1);
}

@keyframes pulse-small {
    0% {
        transform: scale(0.8);
        opacity: 0.8;
    }

    50% {
        transform: scale(1.2);
        opacity: 1;
    }

    100% {
        transform: scale(0.8);
        opacity: 0.8;
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

/* Improved entity grid with cards */
.entity-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    padding: 18px;
}

.entity-card {
    display: flex;
    align-items: center;
    padding: 12px;
    border-radius: 12px;
    background: #f8f9ff;
    transition: all 0.3s cubic-bezier(0.25, 1, 0.5, 1);
    border: 1px solid rgba(76, 100, 226, 0.08);
    min-width: 120px;
    /* Ensure minimum width */
}

.entity-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(76, 100, 226, 0.1);
}

/* Apply soft gradient backgrounds to each card */
.entity-1 {
    background: linear-gradient(135deg, rgba(76, 100, 226, 0.03), rgba(76, 100, 226, 0.08));
}

.entity-2 {
    background: linear-gradient(135deg, rgba(125, 76, 226, 0.03), rgba(125, 76, 226, 0.08));
}

.entity-3 {
    background: linear-gradient(135deg, rgba(76, 175, 226, 0.03), rgba(76, 175, 226, 0.08));
}

.entity-4 {
    background: linear-gradient(135deg, rgba(94, 114, 228, 0.03), rgba(94, 114, 228, 0.08));
}

.entity-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: 10px;
    margin-right: 10px;
    background: white;
    box-shadow: 0 3px 8px rgba(76, 100, 226, 0.1);
}

.entity-icon :deep(.v-icon) {
    background: linear-gradient(135deg, var(--primary), #5e72e4);
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    font-size: 20px;
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
    font-size: 16px;
    color: #333;
    line-height: 1;
    margin-bottom: 4px;
    white-space: nowrap;
    /* Keep on one line */
}

.entity-label {
    font-size: 12px;
    color: #666;
    letter-spacing: 0.2px;
}

.entity-count-large {
    font-size: 14px;
    /* Slightly smaller font for large numbers */
    letter-spacing: -0.3px;
    /* Tighter letter spacing */
}

/* Enhanced last sync footer */
.last-sync {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-top: 1px solid rgba(76, 100, 226, 0.08);
    background: linear-gradient(135deg, rgba(248, 249, 255, 0.5), rgba(248, 249, 255, 0.9));
}

.last-sync-label {
    font-size: 12px;
    color: #666;
    display: flex;
    align-items: center;
}

.last-sync-label :deep(.v-icon) {
    color: var(--primary);
    opacity: 0.7;
}

.last-sync-time {
    font-size: 12px;
    font-weight: 500;
    color: #333;
    letter-spacing: 0.2px;
}

/* Enhanced error message */
.error-message {
    display: flex;
    align-items: center;
    padding: 14px 18px;
    background: linear-gradient(135deg, rgba(244, 67, 54, 0.03), rgba(244, 67, 54, 0.08));
    border-top: 1px solid rgba(244, 67, 54, 0.1);
    color: #F44336;
    font-size: 12px;
    letter-spacing: 0.2px;
}

.error-message :deep(.v-icon) {
    color: #F44336;
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
    if (syncStatus.value === 'running' || syncStatus.value === 'idle') return 'orange';
    if (syncStatus.value === 'completed') return 'green';
    if (syncStatus.value === 'failed' || syncStatus.value === 'canceled') return 'red';
    return 'grey'; // Default for 'none' or unknown
});

const statusText = computed(() => {
    if (syncStatus.value === 'running' || syncStatus.value === 'idle') return 'Syncing';
    if (syncStatus.value === 'completed') return 'Synced';
    if (syncStatus.value === 'failed') return 'Failed';
    if (syncStatus.value === 'canceled') return 'Canceled';
    return 'Not synced';
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
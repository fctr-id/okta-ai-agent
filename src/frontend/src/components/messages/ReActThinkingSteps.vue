<template>
    <v-card class="react-thinking-steps mb-4" elevation="2">
        <v-card-title class="d-flex align-center">
            <v-icon color="primary" class="mr-2">mdi-brain</v-icon>
            <span>Discovery Process</span>
            <v-spacer />
            <v-chip v-if="isRunning" color="primary" size="small">
                <v-progress-circular indeterminate size="16" width="2" class="mr-2" />
                Running
            </v-chip>
            <v-chip v-else color="success" size="small">
                <v-icon size="16" class="mr-1">mdi-check</v-icon>
                Complete
            </v-chip>
        </v-card-title>
        
        <v-card-text>
            <v-timeline density="compact" side="end">
                <v-timeline-item
                    v-for="(step, idx) in steps"
                    :key="idx"
                    :dot-color="getStepColor(step)"
                    size="small"
                >
                    <template v-slot:icon>
                        <v-icon size="16">{{ getStepIcon(step) }}</v-icon>
                    </template>
                    
                    <div class="step-content">
                        <!-- Step Header -->
                        <div class="d-flex align-center mb-2">
                            <strong>{{ step.title }}</strong>
                            <v-spacer />
                            <span v-if="step.timestamp" class="text-caption text-grey">
                                {{ step.timestamp }}
                            </span>
                        </div>
                        
                        <!-- Step Text -->
                        <div class="step-text">
                            {{ step.text }}
                        </div>
                        
                        <!-- Progress bar for step (if available) -->
                        <v-progress-linear
                            v-if="step.progress && step.progress.total > 0"
                            :model-value="(step.progress.current / step.progress.total) * 100"
                            color="primary"
                            height="4"
                            class="mt-2"
                        />
                    </div>
                </v-timeline-item>
            </v-timeline>
        </v-card-text>
    </v-card>
</template>

<script setup>
const props = defineProps({
    steps: {
        type: Array,
        required: true,
        default: () => []
    },
    isRunning: {
        type: Boolean,
        default: false
    }
})

const getStepColor = (step) => {
    if (step.status === 'running') return 'primary'
    if (step.status === 'completed') return 'success'
    if (step.status === 'error') return 'error'
    return 'grey'
}

const getStepIcon = (step) => {
    if (step.status === 'running') return 'mdi-loading'
    if (step.status === 'completed') return 'mdi-check'
    if (step.status === 'error') return 'mdi-alert'
    return 'mdi-circle-small'
}
</script>

<style scoped>
.react-thinking-steps {
    max-width: 100%;
    border-radius: 12px;
    overflow: hidden;
    transition: all 0.3s ease;
    border: 1.5px solid rgba(76, 100, 226, 0.2);
    background: rgba(255, 255, 255, 0.75) !important;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.12);
}

.react-thinking-steps:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.14) !important;
    background: rgba(255, 255, 255, 0.82) !important;
    border-color: rgba(76, 100, 226, 0.3);
}

.step-content {
    padding: 8px 0;
    animation: slide-in-right 0.4s ease-out;
}

@keyframes slide-in-right {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
}

.step-text {
    color: rgba(0, 0, 0, 0.7);
    font-size: 14px;
    line-height: 1.5;
}

/* Animated icon for running status */
:deep(.mdi-loading) {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    0% {
        transform: rotate(0deg);
    }
    100% {
        transform: rotate(360deg);
    }
}

/* Status chip styling */
:deep(.v-chip) {
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Timeline styling */
:deep(.v-timeline) {
    padding-top: 8px;
}

:deep(.v-timeline-item) {
    padding-bottom: 16px;
}

:deep(.v-timeline-item:last-child) {
    padding-bottom: 0;
}

/* Progress linear styling */
:deep(.v-progress-linear) {
    border-radius: 2px;
}

/* Card title styling */
:deep(.v-card-title) {
    background: linear-gradient(135deg, rgba(76, 100, 226, 0.05) 0%, rgba(125, 76, 226, 0.05) 100%);
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
    font-weight: 600;
    padding: 16px 20px;
}

:deep(.v-card-text) {
    padding: 20px;
}

/* Step color transitions */
:deep(.v-timeline-item__dot) {
    transition: all 0.3s ease;
}

/* Running step pulse animation */
:deep(.v-timeline-item__dot[style*="primary"]) {
    animation: pulse 2s ease infinite;
}

@keyframes pulse {
    0%, 100% {
        box-shadow: 0 0 0 0 rgba(76, 100, 226, 0.4);
    }
    50% {
        box-shadow: 0 0 0 8px rgba(76, 100, 226, 0);
    }
}
</style>


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
}

.step-content {
    padding: 8px 0;
}

.step-text {
    color: rgba(0, 0, 0, 0.7);
    font-size: 14px;
    line-height: 1.5;
}
</style>

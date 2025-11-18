<template>
  <div v-if="validationStep || executionStarted || subprocessProgress.length > 0" class="exec-wrapper">
    <div class="exec-card">
      <button class="exec-header" @click="isExpanded = !isExpanded">
        <v-icon size="18" :class="{ rotated: isExpanded }">mdi-chevron-right</v-icon>
        <span class="title">Script validation and execution</span>
        <div class="spacer"></div>
        <span class="status-badge" :class="statusClass">{{ statusText }}</span>
        <span v-if="completedStepsCount > 0 && totalStepsCount > 0" class="progress-info">
          {{ completedStepsCount }}/{{ totalStepsCount }}
        </span>
      </button>

      <transition name="expand">
        <div v-show="isExpanded" class="exec-body">
          <!-- Generated Script (show before validation) -->
          <div v-if="generatedScript" class="generated-script-section">
            <button class="script-toggle" @click="isScriptExpanded = !isScriptExpanded">
              <v-icon size="16" :class="{ rotated: isScriptExpanded }">mdi-chevron-right</v-icon>
              <span class="script-label">Generated Script</span>
              <span class="script-length">({{ scriptLength }} characters)</span>
              <v-icon size="16" class="copy-icon" @click.stop="copyScript">mdi-content-copy</v-icon>
            </button>
            <transition name="expand">
              <div v-show="isScriptExpanded" class="script-content">
                <pre><code>{{ generatedScript }}</code></pre>
              </div>
            </transition>
          </div>

          <div v-if="validationStep || executionStarted" class="unified-steps">
            <div class="steps-list">
              <!-- Validation Step -->
              <div v-if="validationStep" class="unified-step" :class="getValidationStepClass">
                <div class="step-status">
                  <span class="status-icon" :class="getValidationStatusClass">
                    <span v-if="validationStep.status === 'complete'">✓</span>
                    <span v-else-if="validationStep.status === 'failed'">✗</span>
                    <span v-else>●</span>
                  </span>
                </div>
                <div class="step-content">
                  <div class="step-header">
                    <div class="step-info-flow">
                      <span class="step-type">Validation</span>
                    </div>
                  </div>
                  <div class="step-description">
                    <div class="step-context">{{ validationStep.message }}</div>
                  </div>
                </div>
              </div>

              <!-- Separator -->
              <hr v-if="validationStep && executionStarted" class="step-separator">

              <!-- Execution Step -->
              <div v-if="executionStarted" class="unified-step" :class="getExecutionStepClass">
                <div class="step-status">
                  <span class="status-icon" :class="getExecutionStatusClass">
                    <span v-if="isComplete">✓</span>
                    <span v-else-if="executionError">✗</span>
                    <span v-else>●</span>
                  </span>
                </div>
                <div class="step-content">
                  <div class="step-header">
                    <div class="step-info-flow">
                      <span class="step-type">Execution</span>
                    </div>
                    <div class="step-metrics">
                      <!-- Rate limit warning -->
                      <span v-if="rateLimitWarning" class="rate-limit-warning">
                        <v-icon size="12" color="warning">mdi-clock-alert-outline</v-icon>
                        Rate limit: {{ rateLimitWarning }}s
                      </span>
                      <!-- Record count -->
                      <span v-if="isComplete && resultCount > 0" class="record-count">
                        <v-icon size="12" color="grey-darken-1">mdi-database-outline</v-icon>
                        {{ resultCount.toLocaleString() }} records
                      </span>
                    </div>
                  </div>
                  <div class="step-description">
                    <div class="step-context">
                      {{ isComplete ? 'Script executed successfully' : executionError ? 'Script execution failed' : executionMessage }}
                    </div>

                    <!-- Progress Bar -->
                    <div v-if="isExecuting" class="api-progress-container">
                      <v-progress-linear
                        :model-value="progressValue"
                        :indeterminate="progressValue === 0"
                        height="6"
                        color="primary"
                        bg-color="rgba(76, 100, 226, 0.1)"
                        rounded
                        class="api-progress-bar"
                      ></v-progress-linear>
                      <div class="progress-text">
                        {{ progressValue > 0 ? `${progressValue.toFixed(0)}% - ${executionMessage}` : executionMessage }}
                      </div>
                    </div>

                    <!-- Subprocess Progress with tree structure (only for actual subprocess events) -->
                    <div v-if="hasActualSubprocessProgress" class="subprocess-tree">
                      <div v-for="(progress, index) in subprocessProgress" :key="index" class="subprocess-line">
                        <span class="subprocess-branch">└─</span>
                        <v-icon 
                          class="subprocess-icon" 
                          size="11" 
                          :color="progress.success ? '#388E3C' : '#4C64E2'"
                        >
                          {{ progress.success ? 'mdi-check' : 'mdi-loading' }}
                        </v-icon>
                        <span class="subprocess-label">{{ progress.label }}</span>
                        <span v-if="progress.message" class="subprocess-message">: {{ progress.message }}</span>
                      </div>
                    </div>

                    <!-- Error message -->
                    <div v-if="executionError" class="step-error">{{ executionError }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Token Summary -->
          <div v-if="tokenUsage && tokenUsage.total > 0" class="token-summary">
            <span class="token-total">
              {{ tokenUsage.total.toLocaleString() }} tokens ({{ tokenUsage.input.toLocaleString() }} in • {{ tokenUsage.output.toLocaleString() }} out)
            </span>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  validationStep: {
    type: Object,
    default: null
  },
  executionStarted: {
    type: Boolean,
    default: false
  },
  isExecuting: {
    type: Boolean,
    default: false
  },
  isComplete: {
    type: Boolean,
    default: false
  },
  executionError: {
    type: String,
    default: null
  },
  executionMessage: {
    type: String,
    default: 'Executing script...'
  },
  progressValue: {
    type: Number,
    default: 0
  },
  subprocessProgress: {
    type: Array,
    default: () => []
  },
  resultCount: {
    type: Number,
    default: 0
  },
  tokenUsage: {
    type: Object,
    default: null
  },
  rateLimitWarning: {
    type: Number,
    default: 0
  },
  generatedScript: {
    type: String,
    default: null
  }
})

const isExpanded = ref(true)
const isScriptExpanded = ref(false)

const scriptLength = computed(() => {
  return props.generatedScript ? props.generatedScript.length : 0
})

const copyScript = async () => {
  if (!props.generatedScript) return
  try {
    await navigator.clipboard.writeText(props.generatedScript)
    // Could add a toast notification here
  } catch (err) {
    console.error('Failed to copy script:', err)
  }
}

// Filter out empty or non-progress items
const hasActualSubprocessProgress = computed(() => {
  if (!props.subprocessProgress || props.subprocessProgress.length === 0) return false
  // Check if there's at least one item with actual content
  return props.subprocessProgress.some(item => item.label && item.label.trim().length > 0)
})

// Overall status
const statusClass = computed(() => {
  if (props.executionError) return 'error'
  if (props.isComplete) return 'ok'
  if (props.isExecuting || (props.validationStep && props.validationStep.status === 'in-progress')) return 'run'
  return 'idle'
})

const statusText = computed(() => {
  if (props.executionError) return 'Error'
  if (props.isComplete) return 'Complete'
  if (props.isExecuting) return 'Running'
  if (props.validationStep?.status === 'in-progress') return 'Validating'
  if (props.validationStep?.status === 'failed') return 'Failed'
  return 'Ready'
})

// Step counts for progress display
const completedStepsCount = computed(() => {
  let count = 0
  if (props.validationStep?.status === 'complete') count++
  if (props.isComplete) count++
  return count
})

const totalStepsCount = computed(() => {
  let count = 0
  if (props.validationStep) count++
  if (props.executionStarted) count++
  return count
})

// Validation step classes
const getValidationStepClass = computed(() => {
  if (!props.validationStep) return ''
  if (props.validationStep.status === 'failed') return 'step-failed'
  if (props.validationStep.status === 'complete') return 'step-success'
  return 'step-active'
})

const getValidationStatusClass = computed(() => {
  if (!props.validationStep) return ''
  if (props.validationStep.status === 'failed') return 'status-failed'
  if (props.validationStep.status === 'complete') return 'status-success'
  return 'status-active'
})

// Execution step classes
const getExecutionStepClass = computed(() => {
  if (props.executionError) return 'step-failed'
  if (props.isComplete) return 'step-success'
  if (props.isExecuting) return 'step-active'
  return ''
})

const getExecutionStatusClass = computed(() => {
  if (props.executionError) return 'status-failed'
  if (props.isComplete) return 'status-success'
  if (props.isExecuting) return 'status-active'
  return ''
})

</script>

<style scoped>
.exec-wrapper {
  margin: 3rem 0;
}

.exec-card {
  background: white;
  border-radius: 12px;
  border: 1px solid rgba(76, 100, 226, 0.15);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  transition: all 0.3s ease;
}

.exec-card:hover {
  box-shadow: 0 6px 24px rgba(76, 100, 226, 0.12);
  border-color: rgba(76, 100, 226, 0.25);
}

.exec-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 14px 20px;
  background: rgba(76, 100, 226, 0.03);
  border: none;
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.exec-header:hover {
  background: rgba(76, 100, 226, 0.06);
}

.exec-header .v-icon {
  color: #4C64E2;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.exec-header .v-icon.rotated {
  transform: rotate(90deg);
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a1a;
  letter-spacing: -0.01em;
}

.status-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.status-badge.idle { background: #e0e0e0; color: #666; }
.status-badge.run { background: #E3F2FD; color: #1976D2; }
.status-badge.ok { background: #E8F5E9; color: #388E3C; }
.status-badge.error { background: #FFEBEE; color: #C62828; }

.progress-info {
  font-size: 0.7rem;
  font-weight: 500;
  color: #666;
  padding: 0.25rem 0.5rem;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 8px;
}

.spacer {
  flex: 1;
}

.exec-body {
  padding: 16px;
  background: white;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

/* Unified Steps (matching realtime ExecutionDetailsPanel) */
.unified-steps {
  font-size: 14px;
  line-height: 1.6;
  color: #333;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.step-separator {
  border: none;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  margin: 12px 0;
}

.unified-step {
  display: flex;
  gap: 12px;
  padding: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(76, 100, 226, 0.02);
  border-radius: 6px;
  transition: all 0.2s ease;
}

.unified-step:last-child {
  padding-bottom: 10px;
  border-bottom: none;
}

.unified-step.step-active {
  background: rgba(76, 100, 226, 0.06);
}

.unified-step.step-success {
  background: rgba(76, 100, 226, 0.02);
}

.unified-step.step-failed {
  background: rgba(198, 40, 40, 0.03);
  border-color: rgba(198, 40, 40, 0.1);
}

/* Step Status Icon */
.step-status {
  flex-shrink: 0;
  padding-top: 2px;
}

.status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 12px;
  font-weight: bold;
  opacity: 0.8;
}

.status-icon.status-active {
  color: #4C64E2;
  opacity: 1;
}

.status-icon.status-success {
  color: #388E3C;
  opacity: 1;
}

.status-icon.status-failed {
  color: #C62828;
  opacity: 1;
}

/* Step Content */
.step-content {
  flex: 1;
  min-width: 0;
}

.step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.step-info-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.step-type {
  font-size: 14px;
  font-weight: 800;
  color: #4C64E2;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.step-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}

.rate-limit-warning {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #F57C00;
  font-weight: 600;
  padding: 3px 10px;
  background: rgba(255, 152, 0, 0.1);
  border: 1px solid rgba(255, 152, 0, 0.3);
  border-radius: 4px;
  font-size: 11px;
}

.record-count {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #666;
  font-weight: 500;
  padding: 2px 8px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 4px;
}

/* Step Description */
.step-description {
  font-size: 13px;
  color: #555;
  line-height: 1.6;
}

.step-context {
  margin-bottom: 8px;
  font-weight: 500;
  color: #555;
  line-height: 1.6;
}

/* API Progress Container */
.api-progress-container {
  margin-top: 12px;
  padding: 10px;
  background: rgba(76, 100, 226, 0.04);
  border-radius: 6px;
  border: 1px solid rgba(76, 100, 226, 0.1);
}

.api-progress-bar {
  margin-bottom: 6px;
}

.progress-text {
  font-size: 11px;
  color: #4C64E2;
  font-weight: 600;
  text-align: center;
}

/* Subprocess Tree */
.subprocess-tree {
  margin-top: 10px;
  padding-left: 12px;
  border-left: 2px solid rgba(76, 100, 226, 0.15);
}

.subprocess-line {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #666;
  line-height: 1.8;
  padding: 2px 0;
}

.subprocess-branch {
  color: rgba(76, 100, 226, 0.3);
  margin-right: 6px;
  font-family: monospace;
  font-size: 14px;
}

.subprocess-icon {
  margin-right: 6px;
  flex-shrink: 0;
}

.subprocess-label {
  color: #4C64E2;
  font-weight: 600;
}

.subprocess-message {
  color: #666;
  font-style: italic;
  margin-left: 4px;
}

/* Step Error */
.step-error {
  margin-top: 10px;
  padding: 10px 12px;
  background: rgba(198, 40, 40, 0.06);
  border-left: 3px solid #C62828;
  border-radius: 4px;
  font-size: 12px;
  color: #C62828;
  font-weight: 500;
}

/* Generated Script Section */
.generated-script-section {
  margin: 12px 0;
  border: 1px solid rgba(76, 100, 226, 0.15);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(76, 100, 226, 0.02);
}

.script-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background 0.2s;
  color: #333;
}

.script-toggle:hover {
  background: rgba(76, 100, 226, 0.05);
}

.script-label {
  font-size: 13px;
  font-weight: 700;
  color: #4C64E2;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.script-length {
  font-size: 12px;
  color: #666;
  font-weight: 400;
}

.copy-icon {
  margin-left: auto;
  color: #4C64E2;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.copy-icon:hover {
  opacity: 1;
}

.script-content {
  padding: 12px;
  background: #f8f9fa;
  border-top: 1px solid rgba(76, 100, 226, 0.15);
  max-height: 400px;
  overflow-y: auto;
}

.script-content pre {
  margin: 0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.script-content code {
  color: #333;
}

/* Token Summary (matching realtime style) */
.token-summary {
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(76, 100, 226, 0.04);
  border-radius: 8px;
  border: 1px solid rgba(76, 100, 226, 0.1);
  text-align: center;
}

.token-total {
  font-size: 12px;
  font-weight: 600;
  color: #4C64E2;
}

/* Expand transition */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>

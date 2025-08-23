<template>
  <div v-if="expansionPanelData.visible" class="exec-wrapper">
    <div class="exec-card">
      <button class="exec-header" @click="isExpanded = !isExpanded" :aria-expanded="isExpanded.toString()">
        <span class="chevron" :class="{ open: isExpanded }">›</span>
        <span class="title">Execution Details</span>
        <div class="spacer"></div>
        <span class="status-badge" :class="statusClass">{{ statusText }}</span>
        <span v-if="expansionPanelData.planData?.stepCount" class="steps-info">{{ expansionPanelData.planData.stepCount }} steps</span>
        <span v-if="completedStepsCount > 0 && totalStepsCount > 0" class="progress-info">{{ completedStepsCount }}/{{ totalStepsCount }}</span>
      </button>

      <transition name="fade-collapse">
        <div v-show="isExpanded" class="exec-body" style="background-color: #ffffff !important; min-height: 200px;">
          <div v-if="expansionPanelData.planData?.plan" class="unified-steps" style="position: relative; z-index: 1;">
            <div class="steps-list">
              <template v-for="(planStep, index) in getPlanSteps(expansionPanelData.planData.plan)" :key="index">
                <div 
                  class="unified-step"
                  :class="getUnifiedStepClass(index + 1)"
                >
                  <div class="step-status">
                    <span class="status-icon" :class="getStatusIconClass(index + 1)">
                      <span v-if="getStepStatus(index + 1) === 'completed'">✓</span>
                      <span v-else-if="getStepStatus(index + 1) === 'failed'">✗</span>
                      <span v-else-if="getStepStatus(index + 1) === 'active'">●</span>
                      <span v-else>○</span>
                    </span>
                  </div>
                  <div class="step-content">
                    <div class="step-header">
                      <span class="step-type">{{ planStep.toolType }}</span>
                      <span class="step-operation">{{ planStep.operation }}</span>
                      <div class="step-metrics" v-if="getStepDetails(index + 1)">
                        <span v-if="getStepDetails(index + 1).duration" class="duration">
                          <v-icon size="12" color="grey-darken-1">mdi-timer-outline</v-icon>
                          {{ formatDuration(getStepDetails(index + 1).duration) }}
                        </span>
                        <span v-if="getStepDetails(index + 1).recordCount" class="record-count">
                          <v-icon size="12" color="grey-darken-1">mdi-database-outline</v-icon>
                          {{ getStepDetails(index + 1).recordCount.toLocaleString() }} records
                        </span>
                      </div>
                    </div>
                    <div class="step-description">{{ planStep.context }}</div>
                    <div v-if="getStepDetails(index + 1)?.errorMessage" class="step-error">{{ getStepDetails(index + 1).errorMessage }}</div>
                  </div>
                </div>
                <!-- HR separator between steps (not after last step) -->
                <hr v-if="index < getPlanSteps(expansionPanelData.planData.plan).length - 1" class="step-separator">
              </template>
            </div>
          </div>
          <div v-else class="empty">No execution plan available.</div>
          
          <!-- Token Summary at the end of expansion panel -->
          <div v-if="totalTokens > 0" class="token-summary">
            <span class="token-total">{{ totalTokens.toLocaleString() }} tokens ({{ totalInputTokens.toLocaleString() }} in • {{ totalOutputTokens.toLocaleString() }} out)</span>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue';

const props = defineProps({
  expansionPanelData: { type: Object, required: true },
  isProcessing: { type: Boolean, default: false },
  executionStatus: { type: String, default: 'idle' }
});

const isExpanded = ref(false);

// Auto-collapse when execution is completed
watch(() => props.executionStatus, (newStatus) => {
  if (newStatus === 'completed') {
    isExpanded.value = false;
  }
});

// Sort steps numerically
const sortedStepDetails = computed(() => [...props.expansionPanelData.stepDetails].sort((a,b) => a.stepNumber - b.stepNumber));
const completedStepsCount = computed(() => props.expansionPanelData.stepDetails.filter(s => s.success === true).length);
const totalStepsCount = computed(() => {
  // Use static step count from plan data if available, otherwise fall back to step details length
  return props.expansionPanelData.planData?.stepCount || props.expansionPanelData.stepDetails.length;
});

// Token tracking
const totalInputTokens = computed(() => {
  return props.expansionPanelData.stepDetails.reduce((total, step) => total + (step.inputTokens || 0), 0);
});

const totalOutputTokens = computed(() => {
  return props.expansionPanelData.stepDetails.reduce((total, step) => total + (step.outputTokens || 0), 0);
});

const totalTokens = computed(() => totalInputTokens.value + totalOutputTokens.value);

const statusText = computed(() => {
  switch (props.executionStatus) {
    case 'planning': return 'Planning';
    case 'executing': return 'Executing';
    case 'completed': return 'Completed';
    case 'error': return 'Error';
    case 'cancelled': return 'Cancelled';
    default: return 'Idle';
  }
});

const statusClass = computed(() => {
  switch (props.executionStatus) {
    case 'completed': return 'ok';
    case 'error': return 'err';
    case 'executing': return 'run';
    case 'planning': return 'plan';
    case 'cancelled': return 'err';
    default: return 'idle';
  }
});

const isStepActive = (step) => props.expansionPanelData.currentStepExecution?.stepNumber === step.stepNumber;
const metaVisible = (step) => step.recordCount || step.progressPercentage || (step.inputTokens + step.outputTokens) || step.errorMessage;
const rowClass = (step) => ({ active: isStepActive(step) && step.success === null, success: step.success === true, failed: step.success === false });
const rowIconClass = (step) => ({ success: step.success === true, failed: step.success === false, active: isStepActive(step) && step.success === null });

const formatDuration = (seconds) => {
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1);
  return `${m}m ${s}s`;
};

// Convert plan to structured steps for modern display
const getPlanSteps = (plan) => {
  if (!plan || typeof plan !== 'object' || !plan.steps || !Array.isArray(plan.steps)) {
    return [];
  }
  
  return plan.steps.map(step => ({
    toolType: step.tool_name ? step.tool_name.toUpperCase() : 'UNKNOWN',
    operation: step.operation || 'query',
    context: step.query_context || step.reasoning || 'Processing step'
  }));
};

// Helper methods for unified plan/execution view
const getStepDetails = (stepNumber) => {
  return props.expansionPanelData.stepDetails.find(step => step.stepNumber === stepNumber);
};

const getStepStatus = (stepNumber) => {
  const stepDetail = getStepDetails(stepNumber);
  if (!stepDetail) return 'pending';
  if (stepDetail.success === true) return 'completed';
  if (stepDetail.success === false) return 'failed';
  if (props.expansionPanelData.currentStepExecution?.stepNumber === stepNumber) return 'active';
  return 'pending';
};

const getUnifiedStepClass = (stepNumber) => {
  const status = getStepStatus(stepNumber);
  return {
    'unified-step-completed': status === 'completed',
    'unified-step-failed': status === 'failed',
    'unified-step-active': status === 'active',
    'unified-step-pending': status === 'pending'
  };
};

const getStatusIconClass = (stepNumber) => {
  const status = getStepStatus(stepNumber);
  return {
    'status-completed': status === 'completed',
    'status-failed': status === 'failed',
    'status-active': status === 'active',
    'status-pending': status === 'pending'
  };
};

// Auto expand when processing begins
watch([() => props.isProcessing, () => props.expansionPanelData.visible], ([processing, visible]) => {
  if (processing && visible && !isExpanded.value) isExpanded.value = true;
});
</script>

<style scoped>
.exec-wrapper { 
  margin: 12px auto; 
  max-width: 1280px;
  width: calc(100% - 40px);
  min-width: 0;
  position: relative;
  font-family: inherit;
}

.exec-card { 
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(76, 100, 226, 0.12);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(76, 100, 226, 0.08);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  overflow: hidden;
  width: 100%;
}

.exec-header { 
  all: unset;
  display: flex;
  align-items: center;
  width: 100%;
  padding: 18px 20px;
  cursor: pointer;
  background: rgba(0, 0, 0, 0.02);
  font-weight: 600;
  color: #333;
  transition: background-color 0.2s ease;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  gap: 12px;
  box-sizing: border-box;
}

.exec-header:hover { 
  background: rgba(0, 0, 0, 0.04);
}

.spacer {
  flex: 1;
}

.chevron { 
  display: inline-block;
  transition: transform 0.25s ease;
  font-size: 20px;
  color: #4C64E2;
  font-weight: 700;
  flex-shrink: 0;
}

.chevron.open { 
  transform: rotate(90deg);
}

.title { 
  color: #333;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.steps-info, .progress-info { 
  color: #666;
  font-weight: 700;
  font-size: 14px;
  white-space: nowrap;
  flex-shrink: 0;
}

.status-badge { 
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  white-space: nowrap;
  flex-shrink: 0;
  min-width: fit-content;
}

.status-badge.ok { 
  background: rgba(76, 175, 80, 0.12);
  color: #2e7d32;
}

.status-badge.err { 
  background: rgba(244, 67, 54, 0.12);
  color: #c62828;
}

.status-badge.run { 
  background: rgba(142, 84, 233, 0.12);
  color: #8e54e9;
}

.status-badge.plan { 
  background: rgba(255, 152, 0, 0.12);
  color: #ef6c00;
}

.status-badge.idle { 
  background: rgba(158, 158, 158, 0.12);
  color: #616161;
}

.exec-body { 
  padding: 16px;
  background-color: #ffffff !important;
  background: #ffffff !important;
  border-top: 1px solid rgba(76, 100, 226, 0.08);
  border-radius: 0 0 12px 12px;
  position: relative;
  min-height: 100px;
}

/* Ensure background shows by creating a solid layer */
.exec-body::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ffffff;
  border-radius: 0 0 12px 12px;
  z-index: -1;
}

.exec-body * {
  color: inherit;
  position: relative;
  z-index: 1;
}

.plan-block { 
  margin-bottom: 16px;
}

.unified-steps {
  margin-bottom: 16px;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 16px;
}

.unified-step {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  transition: all 0.2s ease;
}

.step-separator {
  width: 80%;
  margin: 10px auto;
  border: none;
  height: 1px;
  background: rgba(76, 100, 226, 0.15);
}

.token-summary {
  margin-top: 20px;
  padding: 12px 16px;
  background: rgba(76, 100, 226, 0.04);
  border: 1px solid rgba(76, 100, 226, 0.08);
  border-radius: 8px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.token-total {
  font-size: 13px;
  font-weight: 600;
  color: #4C64E2;
}

.debug-info {
  font-size: 10px;
  color: #999;
}

.step-status {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.status-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  background: #f5f5f5;
  color: #999;
}

.status-completed {
  background: #4caf50;
  color: #fff;
}

.status-failed {
  background: #f44336;
  color: #fff;
}

.status-active {
  background: #4C64E2;
  color: #fff;
  animation: pulse 1.4s ease-in-out infinite;
}

.step-content {
  flex: 1;
  min-width: 0;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.step-metrics {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.duration, .record-count {
  font-size: 11px;
  font-weight: 500;
  color: #666;
  background: rgba(76, 100, 226, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.step-error {
  margin-top: 6px;
  font-size: 12px;
  color: #f44336;
  font-weight: 500;
  padding: 6px 8px;
  background: rgba(244, 67, 54, 0.06);
  border-radius: 4px;
}

.plan-content {
  margin-top: 8px;
}

.plan-title {
  font-size: 14px;
  font-weight: 600;
  color: #4C64E2;
  margin-bottom: 16px;
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 16px;
}

.plan-step {
  padding: 12px 0;
  border-bottom: 1px solid rgba(76, 100, 226, 0.06);
}

.plan-step:last-child {
  border-bottom: none;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.step-type {
  background: rgba(76, 100, 226, 0.08);
  color: #4C64E2;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.step-operation {
  color: #333;
  font-weight: 500;
  font-size: 13px;
}

.step-description {
  color: #666;
  font-size: 13px;
  line-height: 1.5;
  margin-left: 0;
  margin-top: 6px;
}

.steps { 
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-row { 
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(76, 100, 226, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
  transition: all 0.2s ease;
}

.step-row.active { 
  border-color: #8e54e9;
  background: rgba(142, 84, 233, 0.05);
  box-shadow: 0 2px 8px rgba(142, 84, 233, 0.15);
}

.step-row.success { 
  border-color: rgba(76, 175, 80, 0.3);
  background: rgba(76, 175, 80, 0.05);
}

.step-row.failed { 
  border-color: rgba(244, 67, 54, 0.3);
  background: rgba(244, 67, 54, 0.05);
}

.left { 
  display: flex;
  align-items: flex-start;
  margin-top: 2px;
}

.icon { 
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  border-radius: 50%;
  background: #f5f5f5;
  color: #666;
  font-weight: 600;
}

.icon.success { 
  background: #4caf50;
  color: #fff;
}

.icon.failed { 
  background: #f44336;
  color: #fff;
}

.icon.active { 
  background: #8e54e9;
  color: #fff;
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse { 
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.main { 
  flex: 1;
  min-width: 0;
}

.line1 { 
  display: flex;
  gap: 8px;
  align-items: center;
  font-weight: 500;
  color: #333;
  margin-bottom: 4px;
}

.name { 
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 14px;
}

.duration { 
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.meta { 
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.chip { 
  background: rgba(76, 100, 226, 0.08);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: #666;
}

.chip.error { 
  background: rgba(244, 67, 54, 0.1);
  color: #c62828;
}

.error-line { 
  margin-top: 6px;
  font-size: 12px;
  color: #f44336;
  font-weight: 500;
  line-height: 1.4;
}

.empty { 
  padding: 16px;
  font-size: 13px;
  color: #999;
  font-style: italic;
  text-align: center;
}

.current { 
  margin-top: 12px;
  padding: 8px 12px;
  font-size: 13px;
  color: #8e54e9;
  font-weight: 600;
  background: rgba(142, 84, 233, 0.05);
  border-radius: 8px;
}

.fade-collapse-enter-from, .fade-collapse-leave-to { 
  opacity: 0;
  max-height: 0;
}

.fade-collapse-enter-to, .fade-collapse-leave-from { 
  opacity: 1;
  max-height: 800px;
}

.fade-collapse-enter-active, .fade-collapse-leave-active { 
  transition: all 0.3s ease;
}
</style>

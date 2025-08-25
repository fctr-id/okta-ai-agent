<template>
  <div v-if="expansionPanelData.visible || isProcessing || rtSteps.length > 0" class="exec-wrapper">
    <div class="exec-card">
      <button class="exec-header" @click="isExpanded = !isExpanded" :aria-expanded="isExpanded.toString()">
        <span class="chevron" :class="{ open: isExpanded }">›</span>
        <span class="title">Execution Details</span>
        <div class="spacer"></div>
        <span class="status-badge" :class="statusClass">{{ statusText }}</span>
        <span v-if="completedStepsCount > 0 && totalStepsCount > 0" class="progress-info">{{ completedStepsCount }}/{{ totalStepsCount }}</span>
      </button>

      <transition name="fade-collapse">
        <div v-show="isExpanded" class="exec-body" style="background-color: #ffffff !important;">
          <div v-if="displaySteps.length > 0" class="unified-steps" style="position: relative; z-index: 1;">
            <div class="steps-list">
              <transition-group name="step-slide" tag="div" class="step-container">
                <template v-for="(planStep, index) in displaySteps" :key="`step-${index}-${planStep.toolType}`">
                  <div 
                    class="unified-step"
                    :class="getUnifiedStepClass(index)"
                  >
                    <div class="step-status">
                      <span class="status-icon" :class="getStatusIconClass(index)">
                        <span v-if="getStepStatus(index) === 'completed'">✓</span>
                        <span v-else-if="getStepStatus(index) === 'failed'">✗</span>
                        <span v-else-if="getStepStatus(index) === 'active'">●</span>
                        <span v-else>○</span>
                      </span>
                    </div>
                    <div class="step-content">
                      <div class="step-header">
                        <div class="step-info-flow">
                          <div class="step-type-container">
                            <span class="step-type" :class="`step-badge-${planStep.phase}`">
                              <span v-if="planStep.toolType === 'API' || planStep.toolType === 'SQL'">
                                {{ planStep.toolType }}<span v-if="getEntityFromStep(planStep)"> • {{ getEntityFromStep(planStep) }}</span> • {{ planStep.operation }}
                              </span>
                              <span v-else>
                                {{ planStep.toolType }}
                              </span>
                            </span>
                          </div>
                          <span v-if="planStep.toolType !== 'API' && planStep.toolType !== 'SQL'" class="step-operation-text">{{ planStep.operation }}</span>
                        </div>
                        <div class="step-metrics">
                          <!-- Show duration - prefer execution details, fallback to rtSteps -->
                          <span v-if="getStepDetailsForDisplay(index)?.duration || props.rtSteps?.[planStep.stepIndex]?.duration" class="duration">
                            <v-icon size="12" color="grey-darken-1">mdi-timer-outline</v-icon>
                            {{ formatDuration(getStepDetailsForDisplay(index)?.duration || props.rtSteps[planStep.stepIndex].duration) }}
                          </span>
                          
                          <!-- Show rate limit warning badge if rate limit occurred -->
                          <span v-if="getRateLimitInfo(index)" class="rate-limit-warning-big">
                            <v-icon size="16" color="warning">mdi-clock-alert-outline</v-icon>
                            <strong>Rate limit: {{ getRateLimitInfo(index).waitSeconds }}s</strong>
                          </span>
                          
                          <!-- Show record count ONLY for execution steps (API, SQL, API_SQL) -->
                          <span v-if="(planStep.phase === 'api' || planStep.phase === 'sql' || planStep.phase === 'hybrid') && (getStepDetailsForDisplay(index)?.recordCount || props.rtSteps?.[planStep.stepIndex]?.record_count)" class="record-count">
                            <v-icon size="12" color="grey-darken-1">mdi-database-outline</v-icon>
                            {{ (getStepDetailsForDisplay(index)?.recordCount || props.rtSteps[planStep.stepIndex]?.record_count || 0).toLocaleString() }} records
                          </span>
                        </div>
                      </div>
                      <div class="step-description">
                        <!-- Show execution step query context if available, otherwise show stepper context -->
                        <div v-if="planStep.executionStep && planStep.executionStep.queryContext" class="step-context">
                          {{ planStep.executionStep.queryContext }}
                        </div>
                        <div v-else-if="planStep.context" class="step-context">
                          {{ planStep.context }}
                        </div>
                        
                        <!-- API Progress Bar for active API steps -->
                        <div v-if="planStep.phase === 'api'" class="api-progress-container">
                          <v-progress-linear
                            v-show="isProgressVisible(index)"
                            :model-value="getProgressValue(index)"
                            :indeterminate="isProgressIndeterminate(index)"
                            height="6"
                            color="primary"
                            bg-color="rgba(76, 100, 226, 0.1)"
                            rounded
                            class="api-progress-bar"
                          ></v-progress-linear>
                          <div v-show="isProgressVisible(index)" class="progress-text">
                            <span v-if="isProgressIndeterminate(index)">
                              {{ getProgressMessage(index) }}
                            </span>
                            <span v-else>
                              {{ getProgressValue(index)?.toFixed(1) }}% - {{ getProgressMessage(index) }}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div v-if="getStepDetailsForDisplay(index)?.errorMessage" class="step-error">{{ getStepDetailsForDisplay(index).errorMessage }}</div>
                    </div>
                  </div>
                  <!-- HR separator between steps (not after last step) -->
                  <hr v-if="index < displaySteps.length - 1" :key="`separator-${index}`" class="step-separator">
                </template>
              </transition-group>
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
  expansionPanelData: {
    type: Object,
    required: true
  },
  rtSteps: {
    type: Array,
    default: () => []
  },
  // NEW: execution status prop (passed from parent) – fixes badge stuck on Idle
  executionStatus: {
    type: String,
    default: 'idle'
  },
  // NEW: processing state (ref or boolean)
  isProcessing: {
    type: [Boolean, Object],
    default: false
  }
});

const isExpanded = ref(false);

// Expansion logic: expand when processing, collapse when results are ready
watch([() => props.isProcessing, () => props.executionStatus], 
([processing, status]) => {
  // Expand when processing, collapse when completed (results are ready)
  const shouldExpand = processing && status !== 'completed';
  
  // Only update if state actually changes to prevent unnecessary renders
  if (shouldExpand !== isExpanded.value) {
    isExpanded.value = shouldExpand;
  }
});

// Optimized sorted step details - avoid unnecessary array operations
const sortedStepDetails = computed(() => {
  const details = props.expansionPanelData.stepDetails;
  if (!details || details.length <= 1) return details || [];
  return [...details].sort((a,b) => a.stepNumber - b.stepNumber);
});
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

// Reset function to collapse the panel
const resetPanel = () => {
  isExpanded.value = false;
};

// Expose reset function to parent components
defineExpose({
  resetPanel
});

// Smooth animation handlers for proper height transitions
// const onEnter = (el) => {
//   el.style.height = '0';
//   el.style.opacity = '0';
// };

// const onAfterEnter = (el) => {
//   el.style.height = 'auto';
//   el.style.opacity = '1';
// };

// const onLeave = (el) => {
//   el.style.height = el.scrollHeight + 'px';
//   el.offsetHeight; // Force reflow
//   el.style.height = '0';
//   el.style.opacity = '0';
// };

// const onAfterLeave = (el) => {
//   el.style.height = '';
//   el.style.opacity = '';
// };

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
const isProgressVisible = (stepIndex) => {
  if (props.expansionPanelData.currentStepExecution) {
    const currentStepNumber = props.expansionPanelData.currentStepExecution.stepNumber;
    const displayStepsValue = displaySteps.value;
    const step = displayStepsValue[stepIndex];
    
    if (step?.backend_step_number === currentStepNumber) {
      const currentStep = props.expansionPanelData.currentStepExecution;
      const hasData = !!(currentStep.subprocessProgressPercent !== undefined || currentStep.subprocessProgressDetails);
      
      return hasData;
    }
  }
  return false;
};

const isProgressIndeterminate = (stepIndex) => {
  // If this is the currently active step, check live data
  if (props.expansionPanelData.currentStepExecution) {
    const currentStepNumber = props.expansionPanelData.currentStepExecution.stepNumber;
    const displayStepsValue = displaySteps.value;
    const stepBackendNumber = displayStepsValue[stepIndex]?.backend_step_number;
    
    if (stepBackendNumber === currentStepNumber) {
      const subprocessPercentage = props.expansionPanelData.currentStepExecution.subprocessProgressPercent;
      return subprocessPercentage === undefined || subprocessPercentage === null;
    }
  }
  
  // For other steps, check regular step details
  const stepDetails = getExecutionStepForStepperIndex(stepIndex);
  const subprocessPercentage = stepDetails?.subprocessProgressPercent;
  return subprocessPercentage === undefined || subprocessPercentage === null;
};

const getProgressValue = (stepIndex) => {
  // If this is the currently active step, check live data
  if (props.expansionPanelData.currentStepExecution) {
    const currentStepNumber = props.expansionPanelData.currentStepExecution.stepNumber;
    const displayStepsValue = displaySteps.value;
    const stepBackendNumber = displayStepsValue[stepIndex]?.backend_step_number;
    
    if (stepBackendNumber === currentStepNumber) {
      const subprocessPercentage = props.expansionPanelData.currentStepExecution.subprocessProgressPercent;
      return (subprocessPercentage !== undefined && subprocessPercentage !== null) ? subprocessPercentage : 0;
    }
  }
  
  // For other steps, check regular step details
  const stepDetails = getExecutionStepForStepperIndex(stepIndex);
  const subprocessPercentage = stepDetails?.subprocessProgressPercent;
  return (subprocessPercentage !== undefined && subprocessPercentage !== null) ? subprocessPercentage : 0;
};

const getProgressMessage = (stepIndex) => {
  // If this is the currently active step, check live data
  if (props.expansionPanelData.currentStepExecution) {
    const currentStepNumber = props.expansionPanelData.currentStepExecution.stepNumber;
    const displayStepsValue = displaySteps.value;
    const stepBackendNumber = displayStepsValue[stepIndex]?.backend_step_number;
    
    if (stepBackendNumber === currentStepNumber) {
      const subprocessDetails = props.expansionPanelData.currentStepExecution.subprocessProgressDetails;
      if (subprocessDetails) {
        return subprocessDetails;
      }
    }
  }
  
  // For other steps, check regular step details
  const stepDetails = getExecutionStepForStepperIndex(stepIndex);
  if (stepDetails?.subprocessProgressDetails) {
    return stepDetails.subprocessProgressDetails;
  }
  
  // Otherwise, show generic message based on step status
  return 'Starting API requests...';
};

// Helper function to get rate limit info for the correct step
const getRateLimitInfo = (stepIndex) => {
  // If this is the currently active step, check live data
  if (props.expansionPanelData.currentStepExecution) {
    const currentStepNumber = props.expansionPanelData.currentStepExecution.stepNumber;
    const displayStepsValue = displaySteps.value;
    const stepBackendNumber = displayStepsValue[stepIndex]?.backend_step_number;
    
    if (stepBackendNumber === currentStepNumber) {
      return props.expansionPanelData.currentStepExecution.rateLimitInfo;
    }
  }
  
  // For other steps, check regular step details
  const stepDetails = getExecutionStepForStepperIndex(stepIndex);
  return stepDetails?.rateLimitInfo;
};

// Convert plan to structured steps for modern display - CACHED as computed for performance
const displaySteps = computed(() => {
  // If we have rtSteps from stepper, use those for consistent step display
  if (props.rtSteps && props.rtSteps.length > 0) {
    return props.rtSteps
      .map((step, originalIndex) => {
        // Apply the same step mapping logic as the main stepper
        let badge = '';
        let entity = '';
        let operation = '';
        let phase = '';
        const tool = step.tool_name;

        if (tool === 'thinking') {
          badge = 'CRAFTING';
          entity = 'Strategy';
          operation = '';
          phase = 'crafting';
        } else if (tool === 'generating_steps' || tool === 'generate_plan') {
          badge = 'GENERATING';
          entity = 'Plan';
          operation = '';
          phase = 'generating';
        } else if (tool === 'finalizing_results') {
          badge = 'FINALIZING';
          entity = '';  // Don't show entity for FINALIZING
          operation = 'Results';  // Show meaningful operation
          phase = 'finalizing';
        } else if (tool === 'RELATIONSHIP_ANALYSIS' || tool === 'relationship_analysis') {
          badge = 'ANALYZING';
          entity = 'Relationships';
          operation = '';
          phase = 'analyzing';
        } else if (tool === 'enriching_data') {
          badge = 'ENRICHING';
          entity = 'Data';
          operation = '';
          phase = 'enriching';
        } else if (tool === 'api') {
          badge = 'API';
          entity = step.entity || '';
          operation = step.operation || '';
          phase = 'api';
        } else if (tool === 'sql') {
          badge = 'SQL';
          entity = step.entity || '';
          operation = step.operation || '';
          phase = 'sql';
        } else if (tool === 'API_SQL') {
          badge = 'HYBRID';
          entity = step.entity || '';
          operation = step.operation || '';
          phase = 'hybrid';
        } else {
          badge = (tool || step.name || `step_${originalIndex+1}`).toUpperCase();
          entity = step.entity || '';
          operation = step.operation || '';
          phase = 'other';
        }

        return {
          toolType: badge,
          operation: operation || entity,
          // ENHANCED: Use query_context first, then plan context, then reason, then meaningful fallback
          context: step.query_context || getPlanContextForStep(originalIndex) || step.reason || 
                   (tool === 'finalizing_results' ? 'Compiling and formatting the final results' : `${badge} ${entity}`.trim()),
          stepStatus: step.status || 'pending',
          stepIndex: originalIndex, // Use original index for rtSteps access
          originalIndex: originalIndex, // Keep track of original index
          phase: phase,
          // CRITICAL: Add backend step number mapping for subprocess progress
          backend_step_number: step.backend_step_number,
          // NEW: Add execution step details for enhanced context
          executionStep: getExecutionStepForStepperIndex(originalIndex)
        };
      })
      .filter(step => !props.rtSteps[step.originalIndex]?.hidden); // Filter hidden steps AFTER mapping
  }

  // Fallback to original plan-based logic if no rtSteps available yet
  if (props.expansionPanelData.planData?.plan) {
    return getPlanSteps(props.expansionPanelData.planData.plan);
  }

  return [];
});

const getPlanSteps = (plan) => {
  if (!plan || typeof plan !== 'object' || !plan.steps || !Array.isArray(plan.steps)) {
    return [];
  }
  
  return plan.steps.map(step => ({
    toolType: step.tool_name ? step.tool_name.toUpperCase() : 'UNKNOWN',
    operation: step.operation || 'query',
    context: step.query_context || step.reasoning || 'Processing step',
    stepStatus: 'pending',
    stepIndex: 0,
    phase: 'other'
  }));
};

// NEW: Helper to get detailed plan context for a specific step index
const getPlanContextForStep = (stepIndex) => {
  if (!props.expansionPanelData.planData?.plan?.steps) return null;
  
  // Map rtSteps index to plan steps - plan steps are execution steps only
  // rtSteps: [thinking(0), generating_steps(1), step1(2), step2(3), step3(4), ...]
  // plan.steps: [step1(0), step2(1), step3(2), ...]
  const planStepIndex = stepIndex - 2; // Subtract thinking(0) and generating_steps(1)
  
  if (planStepIndex >= 0 && planStepIndex < props.expansionPanelData.planData.plan.steps.length) {
    const planStep = props.expansionPanelData.planData.plan.steps[planStepIndex];
    return planStep.query_context || planStep.reasoning;
  }
  
  return null;
};

// Helper methods for unified plan/execution view - ENHANCED with stepper status
const getStepDetails = (stepNumber) => {
  return props.expansionPanelData.stepDetails.find(step => step.stepNumber === stepNumber);
};

// NEW: Map stepper step index to actual execution step number
const getExecutionStepForStepperIndex = (stepperIndex) => {
  if (!props.rtSteps || !props.rtSteps[stepperIndex]) return null;
  
  const stepperStep = props.rtSteps[stepperIndex];
  const backendStepNumber = stepperStep.backend_step_number;
  
  // Match by actual backend step number, not tool type
  if (backendStepNumber !== undefined) {
    return props.expansionPanelData.stepDetails.find(execStep => 
      execStep.stepNumber === backendStepNumber
    );
  }
  
  return null; // No backend step number available
};

// ENHANCED: Get step details for display that correctly maps stepper to execution steps
const getStepDetailsForDisplay = (stepperIndex) => {
  // If the current step is the one being displayed, return the live execution data
  const displayStepsValue = displaySteps.value;
  if (displayStepsValue[stepperIndex]?.status === 'active' && props.expansionPanelData.currentStepExecution) {
    // Ensure the active step we're displaying matches the backend's active step
    if (displayStepsValue[stepperIndex].backend_step_number === props.expansionPanelData.currentStepExecution.stepNumber) {
      return props.expansionPanelData.currentStepExecution;
    }
  }
  
  // For non-active steps, find the corresponding execution data
  return getExecutionStepForStepperIndex(stepperIndex);
};

const getStepStatus = (stepIndex) => {
  // First check if we have rtSteps data with status (using 0-based index)
  if (props.rtSteps && props.rtSteps.length > stepIndex) {
    const rtStep = props.rtSteps[stepIndex];
    if (rtStep && rtStep.status) {
      // Map stepper statuses to expansion panel statuses
      if (rtStep.status === 'completed') return 'completed';
      if (rtStep.status === 'error') return 'failed';
      if (rtStep.status === 'active') return 'active';
      return 'pending';
    }
  }

  // Fallback to original stepDetails logic (convert to 1-based for stepDetails)
  const stepDetail = getStepDetails(stepIndex + 1);
  if (!stepDetail) return 'pending';
  if (stepDetail.success === true) return 'completed';
  if (stepDetail.success === false) return 'failed';
  if (props.expansionPanelData.currentStepExecution?.stepNumber === stepIndex + 1) return 'active';
  return 'pending';
};

const getUnifiedStepClass = (stepIndex) => {
  const status = getStepStatus(stepIndex);
  return {
    'unified-step-completed': status === 'completed',
    'unified-step-failed': status === 'failed',
    'unified-step-active': status === 'active',
    'unified-step-pending': status === 'pending'
  };
};

const getStatusIconClass = (stepIndex) => {
  const status = getStepStatus(stepIndex);
  return {
    'status-completed': status === 'completed',
    'status-failed': status === 'failed',
    'status-active': status === 'active',
    'status-pending': status === 'pending'
  };
};

// Helper to extract entity from step for enhanced display
const getEntityFromStep = (planStep) => {
  // Extract entity from rtSteps if available
  if (planStep.stepIndex !== undefined && props.rtSteps && props.rtSteps[planStep.stepIndex]) {
    const rtStep = props.rtSteps[planStep.stepIndex];
    if (rtStep.entity && rtStep.entity.trim()) {
      return rtStep.entity;
    }
  }
  
  // Fallback: try to extract from operation or context
  if (planStep.operation && planStep.operation.includes(' ')) {
    // If operation contains spaces, first word might be entity
    const words = planStep.operation.split(' ');
    const possibleEntity = words[0];
    if (['Users', 'Groups', 'Applications', 'Devices', 'Policies', 'Logs', 'Events'].includes(possibleEntity)) {
      return possibleEntity;
    }
  }
  
  return null;
};
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

.duration, .record-count, .step-number, .rate-limit-warning {
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

.rate-limit-warning {
  background: rgba(255, 193, 7, 0.08);
  color: #f57c00;
  border: 1px solid rgba(255, 193, 7, 0.12);
}

.rate-limit-warning-big {
  font-size: 11px;
  font-weight: 600;
  color: #f57c00;
  background: rgba(255, 193, 7, 0.08);
  padding: 3px 8px;
  border-radius: 4px;
  margin-left: 8px;
  border: 1px solid rgba(255, 193, 7, 0.12);
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.step-type-container {
  display: inline-block;
}

.step-badge-container {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.step-info-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.entity-separator {
  color: #4C64E2;
  font-weight: 600;
  font-size: 14px;
  margin: 0 2px;
}

.step-entity-name {
  color: #2e7d32;
  font-weight: 700;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.step-operation-text {
  color: #333;
  font-weight: 500;
  font-size: 13px;
}

/* Step badge phase colors - integrated from stepper */
.step-badge-crafting { background: #f3e5f5 !important; color: #7b1fa2 !important; }
.step-badge-generating { background: #e9f7ff !important; color: #076489 !important; }
.step-badge-finalizing { background: #e8f5e8 !important; color: #2e7d32 !important; }
.step-badge-enriching { background: #fde7d9 !important; color: #f57c00 !important; }
.step-badge-api { background: #e8f9f6 !important; color: #0f6f62 !important; }
.step-badge-sql { background: #fff4e5 !important; color: #9a5a00 !important; }
.step-badge-hybrid { background: #fce4ec !important; color: #ad1457 !important; }
.step-badge-other { background: #ececec !important; color: #555 !important; }

.step-entity {
  background: rgba(76, 175, 80, 0.08);
  color: #2e7d32;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid rgba(76, 175, 80, 0.2);
}

.step-operation {
  color: #333;
  font-weight: 500;
  font-size: 13px;
  display: flex;
  align-items: center;
}

.step-description {
  color: #666;
  font-size: 13px;
  line-height: 1.5;
  margin-left: 0;
  margin-top: 6px;
}

.step-context {
  color: #666;
}

.api-progress-container {
  margin-top: 8px;
  padding: 8px 0;
}

.api-progress-bar {
  margin-bottom: 4px;
}

.progress-text {
  font-size: 11px;
  color: #4C64E2;
  font-weight: 500;
  text-align: left;
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

/* Smooth expand/collapse animation */
.fade-collapse-enter-active {
  transition: max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
  overflow: hidden;
}

.fade-collapse-leave-active {
  transition: max-height 0.35s cubic-bezier(0.4, 0, 0.6, 1), opacity 0.25s ease;
  overflow: hidden;
}

.fade-collapse-enter-from,
.fade-collapse-leave-to {
  max-height: 0;
  opacity: 0;
}

.fade-collapse-enter-to,
.fade-collapse-leave-from {
  max-height: 800px;
  opacity: 1;
}

/* Step Animation Styles */
.step-container {
  position: relative;
}

.step-slide-enter-active {
  transition: all 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  transform-origin: top;
}

.step-slide-leave-active {
  transition: all 0.4s cubic-bezier(0.55, 0.06, 0.68, 0.19);
  position: absolute;
  width: 100%;
}

.step-slide-enter-from {
  opacity: 0;
  transform: translateY(-20px) scaleY(0.8);
}

.step-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px) scaleY(0.9);
}

.step-slide-move {
  transition: transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

/* Enhanced step animations with subtle glow effect */
.unified-step {
  transition: all 0.3s ease;
  transform-origin: left center;
}

.unified-step.step-active {
  animation: pulse-glow 2s ease-in-out infinite alternate;
}

@keyframes pulse-glow {
  from {
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
  }
  to {
    box-shadow: 0 4px 16px rgba(76, 175, 80, 0.4), 0 0 20px rgba(76, 175, 80, 0.1);
  }
}

.step-separator {
  transition: all 0.3s ease;
  opacity: 0.6;
}

/* New step highlight animation */
@keyframes new-step-highlight {
  0% {
    background-color: rgba(255, 235, 59, 0.3);
    transform: scale(1.02);
  }
  50% {
    background-color: rgba(255, 235, 59, 0.1);
  }
  100% {
    background-color: transparent;
    transform: scale(1);
  }
}
</style>

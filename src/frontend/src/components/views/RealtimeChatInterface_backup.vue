<template>
  <AppLayout contentClass="chat-content">
    <main class="content-area mt-10" :class="{ 'has-results': messages.length > 0 }">
      <!-- Search Container with Animated Position -->
      <div :class="['search-container', messages.length > 0 ? 'moved' : '']">
        <!-- Title with animated gradient underline -->
        <div :class="['title-wrapper', messages.length > 0 ? 'hidden' : '']">
          <h1 class="main-title">Tako Realtime Query Mode</h1>
          <div class="title-underline"></div>
        </div>

        <!-- Modern integrated search -->
        <div class="search-wrapper">
          <div class="integrated-search-bar">
            <!-- Reset button -->
            <transition name="fade" mode="out-in">
              <div v-if="messages.length > 0 && !isProcessing" class="reset-btn-container" key="reset-btn">
                <v-tooltip text="Start over" location="top">
                  <template v-slot:activator="{ props }">
                    <button v-bind="props" class="action-btn reset-btn" @click="resetInterface"
                      aria-label="Reset search">
                      <v-icon>mdi-refresh</v-icon>
                    </button>
                  </template>
                </v-tooltip>
              </div>
              <div v-else-if="!isProcessing" class="empty-btn-container" key="empty-btn-placeholder"></div>
            </transition>

            <!-- Stop button (now part of the search bar, shown when processing) -->
            <transition name="fade">
              <div v-if="isProcessing && canCancelQuery" class="stop-btn-container">
                <v-tooltip text="Stop processing" location="top">
                  <template v-slot:activator="{ props }">
                    <button v-bind="props" @click="handleCancelExecution" class="action-btn stop-btn"
                      aria-label="Stop processing" :disabled="isCancelling">
                      <div class="circular-progress-container">
                        <div class="indeterminate-progress"></div>
                      </div>
                      <v-icon size="large" color="#4C64E2">mdi-stop</v-icon>
                    </button>
                  </template>
                </v-tooltip>
              </div>
            </transition>

            <!-- Search input -->
            <v-text-field v-model="userInput" @keydown="handleKeyDown" @keydown.enter.prevent="handleQuerySubmit"
              placeholder="Ask a question about your Okta tenant..." variant="plain" color="#4C64E2"
              bg-color="transparent" hide-details class="search-input" :clearable="true" :disabled="isProcessing"           
              </v-text-field>
            <v-tooltip text="Send query" location="top">
              <template v-slot:activator="{ props }">
                <button v-bind="props" class="action-btn send-btn" :disabled="!canSubmitQuery" :loading="isSubmitting"
                  @click="handleQuerySubmit" aria-label="Send query">
                  <v-icon>mdi-send</v-icon>
                </button>
              </template>
            </v-tooltip>
          </div>
        </div>



        <!-- Suggestions -->
        <transition name="fade-up">
          <div v-if="messages.length === 0 && !isProcessing" class="suggestions-wrapper">
            <!-- Add note about case-sensitivity -->
            <div class="case-sensitivity-note mt-n8">
              <div class="note-content">
                <v-icon color="info" size="small" class="note-icon">mdi-information</v-icon>
                <span>Note: Application and group names are case-sensitive. Please enter them exactly as they appear in Okta.</span>
              </div>
            </div>
            
            <div class="tools-button-container">
              <v-btn
                color="primary"
                class="tools-action-button"
                prepend-icon="mdi-tools"
                @click="showToolsModal = true"
                elevation="1"
                rounded
              >
                View Available Tools
              </v-btn>
            </div>
          </div>
        </transition>


      </div>

      

      <!-- Display User question -->
      <transition name="fade">
        <div v-if="messages.length > 0 && messages[0]?.role === 'user'" class="question-header-container">
          <div class="question-header">
            <div class="question-icon">
              <v-icon>mdi-account</v-icon>
            </div>
            <div class="question-text">{{ messages[0].content }}</div>
            <div class="question-timestamp">{{ formatTime(messages[0].timestamp) }}</div>
          </div>
        </div>
      </transition>

      
          <!-- Add this after the search container - ERROR -->
        <transition name="fade">
          <div v-if="rtError" class="error-container mt-4">
            <v-alert
              type="error"
              variant="tonal"
              border="start"
              class="mx-auto"
              style="max-width: 800px;"
            >
              {{ rtError }}
            </v-alert>
          </div>
        </transition>

      <!-- Unified Progress Display OR Final Outcome Area -->
      <transition name="fade-up">
        <div v-if="showProgressDisplayArea || showFinalOutcomeArea" ref="messagesContainerRef"
          class="results-container mt-8" @scroll="handleScroll">

          <div class="content-wrapper">
            <!-- Progress Area with Stepper - Show for both processing and errors -->
            <div v-if="showProgressDisplayArea || (rtExecutionStatus === 'error' && rtSteps.length > 0)" class="unified-progress-area">
              <div :class="['stepper-container-wrapper', { 'expanded': hasStepperExpanded }]">
                <v-stepper v-model="currentProgressStepId" class="elevation-0 transparent-stepper" flat hide-actions>
                  <v-stepper-header>
                    <transition-group name="step-fade">
                      <template v-for="(item, index) in progressSteps" :key="item.id">
                        <v-stepper-item :value="item.id" :title="item.title" :complete="item.status === 'completed'"
                          :error="item.status === 'error'" :disabled="item.status === 'pending'">
                          <!-- Use the built-in icon slot for custom indicator -->
                          <template v-slot:icon>
                            <div v-if="item.status === 'active'" class="step-pulse-indicator"></div>
                            <v-icon v-else-if="item.status === 'completed'" color="#38b2ac">mdi-check-circle</v-icon>
                            <v-icon v-else-if="item.status === 'error'" color="error">mdi-alert-circle</v-icon>
                            <div v-else class="step-empty-indicator"></div>
                          </template>
                        </v-stepper-item>
                        <v-divider v-if="index < progressSteps.length - 1" :key="`divider-${index}`"></v-divider>
                      </template>
                    </transition-group>
                  </v-stepper-header>
                </v-stepper>
                
                <!-- Error message under stepper -->
                <div v-if="rtExecutionStatus === 'error' && rtError" 
                     class="error-details mt-3 mx-4 mb-3 pa-3 rounded bg-red-lighten-5">
                  <div class="d-flex align-center text-red-darken-2">
                    <v-icon color="error" class="me-2">mdi-alert-circle-outline</v-icon>
                    <span class="font-weight-medium">Step failed: {{ getFailedStepName() }}</span>
                  </div>
                  <div class="error-message mt-2">{{ rtError }}</div>
                </div>
              </div>
            </div>

            <!-- Final Results/Cancelled Display (only show when not error) -->
            <div v-if="showFinalOutcomeArea && rtExecutionStatus !== 'error'" class="full-width-section">
              <div v-if="rtResults" class="final-results mt-4">
                <!--<h3 class="text-subtitle-1 mb-3 px-4">Results</h3>-->
                <data-display :content="rtResults.content" :type="determineDisplayType(rtResults.display_type)"
                  :metadata="rtResults.metadata || {}" />
              </div>

              <div v-if="rtExecutionStatus === 'cancelled'"
                class="cancelled-container mt-3 pa-3 rounded bg-orange-lighten-5">
                <div class="d-flex align-center text-orange-darken-3">
                  <v-icon color="warning" class="me-2">mdi-cancel</v-icon>
                  <span class="font-weight-medium">Query execution was cancelled.</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </transition>

      <v-dialog v-model="showToolsModal" max-width="800px" scrollable>
        <v-card>
          <v-toolbar color="primary" class="text-white">
            <v-toolbar-title>Available Tools</v-toolbar-title>
            <v-spacer></v-spacer>
            <v-text-field
              v-model="toolSearch"
              prepend-inner-icon="mdi-magnify"
              placeholder="Search tools..."
              hide-details
              density="compact"
              class="mt-2 search-field"
              variant="outlined"
              style="max-width: 250px"
            ></v-text-field>
            <v-btn icon @click="showToolsModal = false" class="ml-2">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </v-toolbar>
          
          <v-card-text class="pa-4">
            <div v-if="isLoadingTools" class="d-flex justify-center my-4">
              <v-progress-circular indeterminate color="primary"></v-progress-circular>
            </div>
            
            <div v-else class="tools-wrapper">
              <!-- Fixed-column grid with vertical overflow -->
              <div class="tools-grid-container">
                <div 
                  v-for="tool in filteredTools" 
                  :key="tool.tool_name" 
                  class="tool-cell"
                  @click="userInput = tool.tool_name; showToolsModal = false;"
                >
                  <div class="tool-content">
                    <!-- Info icon moved to the left -->
                    <v-tooltip location="top">
                      <template v-slot:activator="{ props }">
                        <v-icon v-bind="props" size="small" class="info-icon">mdi-information-outline</v-icon>
                      </template>
                      <span class="tooltip-text">{{ tool.description }}</span>
                    </v-tooltip>
                    <!-- Tool name after the icon -->
                    <div class="tool-name">{{ tool.tool_name }}</div>
                  </div>
                </div>
              </div>
              
              <!-- No results message -->
              <div v-if="filteredTools.length === 0" class="text-center py-8">
                <v-icon size="large" color="grey-lighten-1">mdi-magnify-close</v-icon>
                <div class="text-body-1 mt-2">No matching tools found</div>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-dialog>
    </main>
  </AppLayout>
</template>



<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue';
import AppLayout from '@/components/layout/AppLayout.vue';
import DataDisplay from '@/components/messages/DataDisplay.vue';
import { useRealtimeStream } from '@/composables/useRealtimeStream';
import { MessageType } from '@/components/messages/messageTypes';

const {
  isProcessing,
  error: rtError,
  processId: rtProcessId,
  status: rtExecutionStatus,
  planGenerated: rtPlanGenerated,
  currentStepIndex: rtCurrentStepIndexVal,
  steps: rtSteps,
  results: rtResults,
  startProcess,
  connectToStream,
  cancelProcess,
  cleanup,
} = useRealtimeStream();

const userInput = ref('');
const messages = ref([]);
const messagesContainerRef = ref(null);
const isSubmitting = ref(false);
const isCancelling = ref(false);
const autoScroll = ref(true);
const showToolsModal = ref(false);
const availableTools = ref([]);
const isLoadingTools = ref(false);
const toolSearch = ref('');

// Add message history management
const CONFIG = {
  MAX_HISTORY: 5
};
const messageHistory = ref([]);
const historyIndex = ref(-1);

const exampleQueries = ref([
  'Find user dan@fctr.io and fetch factors',
  'List all users created last month',
  'Show groups for user test.user@example.com',
]);

const canSubmitQuery = computed(() => userInput.value.trim().length > 0 && !isProcessing.value);
const canCancelQuery = computed(() => isProcessing.value && rtProcessId.value && !isCancelling.value && rtExecutionStatus.value !== 'completed' && rtExecutionStatus.value !== 'error' && rtExecutionStatus.value !== 'cancelled');

// Load saved history on component mount
onMounted(() => {
  try {
    const savedHistory = localStorage.getItem('realtimeMessageHistory');
    if (savedHistory) {
      messageHistory.value = JSON.parse(savedHistory);
    }
  } catch (error) {
    console.error('Failed to load realtime message history:', error);
    localStorage.removeItem('realtimeMessageHistory');
  }
});

const formatTime = (timestamp) => {
  if (!timestamp) return '';
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const insertExampleQuery = (query) => {
  userInput.value = query;
  nextTick(() => {
    const inputElement = document.querySelector('.search-input input');
    if (inputElement) inputElement.focus();
  });
};

// Update the message history when sending a query
const updateMessageHistory = (query) => {
  if (!query || !query.trim()) return;
  
  const sanitizedQuery = query.trim();
  const existingIndex = messageHistory.value.indexOf(sanitizedQuery);

  if (existingIndex === -1) {
    // New message - add to front of history
    messageHistory.value = [sanitizedQuery, ...messageHistory.value.slice(0, CONFIG.MAX_HISTORY - 1)];
  } else {
    // Existing message - move to front of history
    messageHistory.value = [
      sanitizedQuery,
      ...messageHistory.value.slice(0, existingIndex),
      ...messageHistory.value.slice(existingIndex + 1)
    ];
  }

  // Save to localStorage and reset index
  localStorage.setItem('realtimeMessageHistory', JSON.stringify(messageHistory.value));
  historyIndex.value = -1;
};

// Add keyboard navigation handler
const handleKeyDown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleQuerySubmit();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (historyIndex.value < messageHistory.value.length - 1) {
      historyIndex.value++;
      userInput.value = messageHistory.value[historyIndex.value];
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (historyIndex.value > -1) {
      historyIndex.value--;
      userInput.value = historyIndex.value === -1 ? '' : messageHistory.value[historyIndex.value];
    }
  }
};

const handleQuerySubmit = async () => {
  if (!canSubmitQuery.value) return;
  const query = userInput.value.trim();
  
  // Update message history with this query
  updateMessageHistory(query);
  
  messages.value = [
    { role: 'user', content: query, timestamp: new Date() },
  ];
  userInput.value = '';
  isSubmitting.value = true;
  try {
    const newProcessId = await startProcess(query);
    if (newProcessId) {
      await connectToStream(newProcessId);
    } else {
      console.error("Failed to start process, no process ID received.");
      rtExecutionStatus.value = 'error';
      rtError.value = "Error! Please check the backend and try again.";
    }
  } catch (error) {
    console.error('Error submitting query:', error);
    rtExecutionStatus.value = 'error';
    rtError.value = error.message || "An unexpected error occurred while submitting the query.";
  } finally {
    isSubmitting.value = false;
  }
};

const getFailedStepName = () => {
  const failedStep = rtSteps.value?.find(step => 
    step.status === 'error' || step.operation_status === 'error'
  );
  
  if (failedStep) {
    return failedStep.tool_name || `Step ${failedStep.step_index + 1}`;
  }
  return 'Unknown step';
};

const hasStepperExpanded = computed(() => {
  // Expand the stepper container when:
  // 1. Plan has been generated AND
  // 2. There are plan steps available
  return rtPlanGenerated.value && rtSteps.value?.length > 0;
});

const resetInterface = async () => {
  if (isProcessing.value && rtProcessId.value) {
    await handleCancelExecution();
  }
  messages.value = [];
  userInput.value = '';
  cleanup();
  isCancelling.value = false;
  autoScroll.value = true;
  // Don't clear history when resetting interface
};

const handleCancelExecution = async () => {
  if (!rtProcessId.value || isCancelling.value) return;
  isCancelling.value = true;
  try {
    await cancelProcess();
  } catch (error) {
    console.error('Error during manual cancellation:', error);
  } finally {
    isCancelling.value = false;
  }
};

const determineDisplayType = (typeFromServer) => {
  if (typeFromServer === 'markdown') return MessageType.MARKDOWN;
  if (typeFromServer === 'table' || typeFromServer === 'vuetify_data_table') return MessageType.TABLE;
  return MessageType.TEXT;
};

const scrollToBottom = () => {
  nextTick(() => {
    if (autoScroll.value && messagesContainerRef.value) {
      messagesContainerRef.value.scrollTop = messagesContainerRef.value.scrollHeight;
    }
  });
};

const handleScroll = () => {
  if (messagesContainerRef.value) {
    const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.value;
    autoScroll.value = scrollHeight - scrollTop - clientHeight < 100;
  }
};

const PREPARE_PLAN_ID = 'prepare_plan';
const GENERATING_CODE_ID = 'generating_code'; // New constant for the code generation step
const FINALIZE_RESULTS_ID = 'finalize_results';

const progressSteps = computed(() => {
  const items = [];

  // First step (Planning)
  items.push({
    id: PREPARE_PLAN_ID,
    title: 'creating_plan',
    status: rtExecutionStatus.value === 'planning' && !rtPlanGenerated.value ? 'active' :
      (rtPlanGenerated.value || !['initial', 'planning'].includes(rtExecutionStatus.value) ? 'completed' : 'pending'),
  });

  // Add the new Generating Code step when plan is generated
  if (rtPlanGenerated.value) {
    const isGeneratingCode = rtExecutionStatus.value === 'generating_code';
    // Check if any step has started or completed - this works even without phase="executing"
    const hasStepsStarted = rtSteps.value?.some(step => 
      step.status === 'active' || 
      step.status === 'in_progress' ||
      step.status === 'running' || 
      step.status === 'completed');
  
    items.push({
      id: GENERATING_CODE_ID,
      title: 'generating_code',
      status: isGeneratingCode && !hasStepsStarted ? 'active' : 'completed',
    });
  }

  // Plan steps
  if (rtPlanGenerated.value && rtSteps.value?.length > 0) {
    rtSteps.value.forEach((step, index) => {
      let itemStatus;

      // Map statuses directly from the backend
      if (step.status === 'completed') {
        itemStatus = 'completed';
      } else if (step.status === 'error') {
        itemStatus = 'error';
      } else if (step.status === 'active' || step.status === 'in_progress' || step.status === 'running') {
        // Accept multiple possible "active" states
        itemStatus = 'active';
      } else {
        itemStatus = 'pending';
      }

      items.push({
        id: `plan_step_${step.id || index}`,
        title: step.tool_name || `Action ${index + 1}`,
        status: itemStatus,
      });
    });
  }

  // Final step
  items.push({
    id: FINALIZE_RESULTS_ID,
    title: 'finalizing_results',
    status: rtExecutionStatus.value === 'processing_final_results' ? 'active' :
      (['completed', 'error', 'cancelled'].includes(rtExecutionStatus.value) ? 'completed' : 'pending'),
  });

  return items;
});

const currentProgressStepId = computed(() => {
  const activeItem = progressSteps.value.find(item => item.status === 'active');
  if (activeItem) return activeItem.id;

  if (rtExecutionStatus.value === 'planning' && !rtPlanGenerated.value) return PREPARE_PLAN_ID;
  if (rtExecutionStatus.value === 'generating_code') return GENERATING_CODE_ID;
  if (rtExecutionStatus.value === 'planning' && rtPlanGenerated.value && rtSteps.value?.length > 0) return `plan_step_${rtSteps.value[0].id || 0}`;
  if (rtExecutionStatus.value === 'executing' && rtSteps.value?.[rtCurrentStepIndexVal.value]) return `plan_step_${rtSteps.value[rtCurrentStepIndexVal.value].id || rtCurrentStepIndexVal.value}`;
  if (rtExecutionStatus.value === 'processing_final_results') return FINALIZE_RESULTS_ID;
  if (rtExecutionStatus.value === 'completed' || rtExecutionStatus.value === 'error' || rtExecutionStatus.value === 'cancelled') {
    for (let i = progressSteps.value.length - 1; i >= 0; i--) {
      if (progressSteps.value[i].status !== 'pending') return progressSteps.value[i].id;
    }
    return FINALIZE_RESULTS_ID;
  }
  return PREPARE_PLAN_ID;
});

const showProgressDisplayArea = computed(() =>
  messages.value.length > 0 &&
  (isProcessing.value || ['planning', 'generating_code', 'executing', 'processing_final_results'].includes(rtExecutionStatus.value)) &&
  !rtResults.value && rtExecutionStatus.value !== 'error' && rtExecutionStatus.value !== 'cancelled'
);

const showFinalOutcomeArea = computed(() =>
  messages.value.length > 0 &&
  (rtResults.value || rtExecutionStatus.value === 'error' || rtExecutionStatus.value === 'cancelled')
);

// Keep this for backwards compatibility but we're not displaying it anymore
const progressAreaTitle = computed(() => {
  if (rtExecutionStatus.value === 'planning' && !rtPlanGenerated.value) return "Understanding Your Query";
  if (rtExecutionStatus.value === 'generating_code') return "Generating Code";
  if (rtPlanGenerated.value && (rtExecutionStatus.value === 'planning' || rtExecutionStatus.value === 'executing')) return "Executing Plan";
  if (rtExecutionStatus.value === 'processing_final_results') return "Preparing Your Results";
  return "";
});

watch([rtExecutionStatus, rtSteps, rtResults, rtError, rtPlanGenerated, rtCurrentStepIndexVal, isProcessing], () => {
  scrollToBottom();
}, { deep: true });

watch(messages, () => {
  scrollToBottom();
}, { deep: true });

// Filter tools based on search
const filteredTools = computed(() => {
  if (!toolSearch.value) return availableTools.value;

  const search = toolSearch.value.toLowerCase();
  return availableTools.value.filter(tool =>
    tool.tool_name.toLowerCase().includes(search) ||
    tool.description.toLowerCase().includes(search)
  );
});

// Function to fetch available tools from backend
const fetchAvailableTools = async () => {
  isLoadingTools.value = true;
  try {
    const response = await fetch('/api/realtime/available-tools');
    const data = await response.json();
    availableTools.value = data.tools;
  } catch (error) {
    console.error('Error fetching tools:', error);
    availableTools.value = [];
  } finally {
    isLoadingTools.value = false;
  }
};

// Watch modal visibility to load tools when opened
watch(showToolsModal, (newVal) => {
  if (newVal && availableTools.value.length === 0) {
    fetchAvailableTools();
  }
});


</script>

<style scoped>
/* Basic layout and structure */
.chat-content {
  background: transparent;
}

.content-area {
  width: calc(100% - 40px);
  max-width: var(--max-width);
  margin: 0 auto;
  padding: 0;
  transition: all 0.3s ease;
}

.content-area.has-results {
  padding-top: 60px;
  padding-bottom: 220px;
}

/* Title and header styles */
.title-wrapper {
  margin-bottom: 28px;
  transition: opacity 0.4s ease;
  text-align: center;
  opacity: 1;
}

.title-wrapper.hidden {
  opacity: 0;
  transform: translateY(-20px);
  pointer-events: none;
}

.main-title {
  font-size: 32px;
  font-weight: 500;
  margin-bottom: 8px;
  background: linear-gradient(135deg, #ff9966, #ff5e62, #845ec2, #2c73d2, #0081cf);
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
}

/* Search container */
.search-container {
  position: fixed;
  left: 50%;
  top: 45%;
  transform: translate(-50%, -50%);
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  padding-bottom: 40px;
  transition: all 0.7s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 50;
  will-change: transform, top;
  backface-visibility: hidden;
}

.search-container.moved {
  top: calc(100vh - 200px);
  transform: translate(-50%, 0);
}

/* Search components */
.search-wrapper {
  width: 100%;
  max-width: 850px;
  margin: 0 auto;
}

.integrated-search-bar {
  display: flex;
  align-items: center;
  background: white;
  border-radius: 12px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.06);
  padding: 6px 8px;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
  border: 1px solid var(--primary);
}

.integrated-search-bar:has(.v-field--focused) {
  box-shadow: 0 8px 28px rgba(76, 100, 226, 0.15);
  transform: translateY(-2px);
  border: 1.5px solid var(--primary);
}

.search-input {
  flex: 1;
}

.search-input :deep(.v-field) {
  box-shadow: none !important;
  border: none;
  min-height: 44px !important;
}

.search-input :deep(.v-field__input) {
  padding: 0 0 0 16px !important;
  font-size: 15px;
  min-height: 42px !important;
  display: flex !important;
  align-items: center !important;
}

.search-input :deep(.v-field__input input) {
  margin-top: 0 !important;
  padding: 0 !important;
}

.search-input :deep(.v-field__clearable) {
  align-self: center !important;
  padding: 0 !important;
}

.search-input :deep(.v-field__clearable .v-icon) {
  display: flex;
  align-items: center;
  justify-content: center;
  transform: translateY(-2px);
  padding: 0;
  margin-right: 4px;
}

/* Button styles */
.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  color: #999;
}

.reset-btn {
  width: 38px !important;
  height: 38px !important;
  margin-right: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.reset-btn:hover {
  color: #666;
  background: #f5f5f5;
}

.send-btn {
  color: white;
  background: var(--primary);
  margin-left: 4px;
}

.send-btn:hover:not(:disabled) {
  background: var(--primary-dark);
  transform: translateY(-1px);
}

.send-btn:disabled {
  background: #e0e0e0;
  color: #999;
  cursor: not-allowed;
}

.stop-btn {
  position: relative;
  width: 38px !important;
  height: 38px !important;
  background-color: white;
  color: #4C64E2;
  border: none;
  border-radius: 50%;
  z-index: 2;
  box-shadow: 0 2px 8px rgba(76, 100, 226, 0.15);
  cursor: pointer;
  margin-right: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.reset-btn-container,
.stop-btn-container,
.empty-btn-container {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  flex-shrink: 0;
}

.circular-progress-container {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 40px;
  height: 40px;
  pointer-events: none;
}

.indeterminate-progress {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border: 1px solid rgba(76, 100, 226, 0.2);
  border-top: 1px solid #4C64E2;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.suggestions-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 64px;
}

/* Suggestion header text */
.suggestion-header {
  font-size: 16px;
  color: #555;
  margin-bottom: 20px;
  font-weight: 500;
}

.suggestions-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  max-width: 850px;
  margin: 0 auto;
}

.suggestion-btn {
  position: relative;
  background: #fff !important;
  border: none !important;
  border-radius: var(--border-radius) !important;
  transition: all 0.2s ease;
  color: var(--text-primary) !important;
  font-weight: 400 !important;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
  padding: 0 12px !important;
  height: 32px !important;
  min-width: 0 !important;
  overflow: hidden !important;
  font-size: 13px !important;
  letter-spacing: 0.2px !important;
  text-transform: none !important;
}

.suggestion-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--border-radius);
  padding: 1.5px;
  background: linear-gradient(90deg, var(--primary), #5e72e4, #8e54e9, #d442f5);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0.85;
  pointer-events: none;
}

.suggestion-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(142, 84, 233, 0.2);
  color: #8e54e9 !important;
  background: #f8f9ff !important;
}

/* Question display */
.question-header-container {
  max-width: var(--max-width);
  width: calc(100% - 40px);
  margin: 24px auto 20px;
  display: flex;
  justify-content: center;
  position: relative;
  z-index: 40;
}

.question-header {
  background-color: var(--primary);
  color: white;
  padding: 12px 20px;
  border-radius: 12px;
  width: fit-content;
  max-width: 90%;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 4px 16px rgba(76, 100, 226, 0.2);
}

.question-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.question-icon :deep(.v-icon) {
  color: white !important;
}

.question-text {
  font-weight: 500;
  color: white;
}

.question-timestamp {
  font-size: 12px;
  opacity: 0.8;
  color: rgba(255, 255, 255, 0.9);
  margin-left: 8px;
  white-space: nowrap;
}

/* Results container */
.results-container {
  max-width: var(--max-width);
  width: calc(100% - 40px);
  margin: 12px auto 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: transparent;
}

.content-wrapper {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.full-width-results {
  border-radius: var(--border-radius);
  box-shadow: var(--shadow-medium);
  background: white;
  overflow: hidden;
  width: 100%;
}

.system-message {
  border-radius: var(--border-radius);
  width: 100%;
}

.error-container,
.cancelled-container {
  border: 0px solid currentColor;
}

/* Stepper styles */
.transparent-stepper {
  background-color: transparent !important;
}

.stepper-container-wrapper {
  width: 380px;
  max-width: 100%;
  margin: 0 auto;
  transition: width 0.8s cubic-bezier(0.22, 1, 0.36, 1);
  background-color: white;
  border-radius: var(--border-radius);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
  padding: 8px 0 0;
  /* Remove bottom padding */
  overflow: hidden;
}


.stepper-bottom-spacer {
  height: 12px;
  background-color: white;
  width: 100%;
}

.stepper-container-wrapper.expanded {
  width: 100%;
  /* Full width when expanded */
}

.full-width-section {
  width: 100%;
}


.final-results {
  background: white;
  border-radius: var(--border-radius);
  box-shadow: var(--shadow-medium);
  overflow: hidden;
  width: 100%;
}


/* Keep the transition container visible during animation */
.unified-progress-area {
  width: 100%;
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 20px;
  overflow: hidden;
  /* Ensure animation is visible */
}

.v-stepper :deep(.v-stepper-header) {
  flex-wrap: nowrap;
  padding: 16px 20px;
  overflow-x: auto;
  justify-content: space-around !important;
  border-radius: 8px;
  background-color: transparent;
}

.v-stepper {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
}

.v-stepper-item {
  flex-basis: auto !important;
  min-width: 120px;
  flex-shrink: 0;
  padding: 0 4px;
}

/* Custom column layout for step item */
.v-stepper :deep(.v-stepper-item) {
  flex-direction: column !important;
  align-items: center !important;
  text-align: center !important;
  min-width: 100px !important;
  max-width: 150px !important;
}

/* Remove any theme colors that might interfere */
.v-stepper :deep(.v-stepper-item__icon) {
  background-color: transparent !important;
  background: none !important;
  box-shadow: none !important;
  border: none !important;
  margin: 0 !important;
  padding: 0 !important;
  width: 24px !important;
  height: 24px !important;
  display: flex;
  align-items: center;
  justify-content: center;
}

.v-stepper :deep(.v-stepper-item__icon) div {
  background-color: transparent !important;
  background: none !important;
  box-shadow: none !important;
  border: none !important;
}

.v-stepper :deep(.v-stepper-item__title) {
  font-size: 0.9rem !important;
  white-space: normal !important;
  line-height: 1.2 !important;
  max-width: 100% !important;
  text-align: center !important;
  color: #555 !important;
  margin-top: 4px;
}

.v-stepper :deep(.v-stepper-item__content) {
  margin: 8px auto 0 !important;
  padding: 0 4px !important;
  text-align: center !important;
}

.v-stepper :deep(.v-stepper-item__subtitle) {
  display: none !important;
}

.v-stepper :deep(.v-divider) {
  align-self: center;
  min-height: 1px;
  max-height: 1px;
  min-width: 20px;
  max-width: none;
}

.v-stepper :deep(.v-icon) {
  margin: 0 !important;
  font-size: 20px !important;
}

.v-stepper :deep(.v-icon.mdi-check-circle) {
  color: #38b2ac !important;
}

.v-stepper-item :deep(.v-ripple__container) {
  display: none !important;
}

/* Step indicators */
.step-pulse-indicator {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4C64E2, #3949AB);
  box-shadow: 0 0 10px rgba(76, 100, 226, 0.4);
  display: inline-block;
  position: relative;
  animation: pulse-animation 2s infinite ease-in-out;
  z-index: 5;
}

.step-empty-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid rgba(0, 0, 0, 0.2);
  display: inline-block;
}

.completed-step-icon {
  color: #38b2ac !important;
  filter: drop-shadow(0 1px 2px rgba(56, 178, 172, 0.3));
}

/* Dynamic stepper container */
.stepper-container {
  width: 380px;
  /* Initial width for just 2-3 steps */
  margin: 0 auto;
  transition: width 0.8s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}

.stepper-container.expanded {
  width: 100%;
  /* Full width when expanded */
}

/* Step fade animation */
.step-fade-enter-active {
  transition: all 0.5s ease;
  position: relative;
  z-index: 1;
}

.step-fade-leave-active {
  transition: all 0.3s ease;
  position: absolute;
}

.step-fade-enter-from,
.step-fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* Add smooth transitions for dividers */
.v-stepper :deep(.v-divider) {
  transition: width 0.5s ease, opacity 0.5s ease;
}


/* Animation for steps */
.step-fade-enter-active {
  transition: all 0.5s ease;
  position: relative;
  z-index: 1;
}

.step-fade-leave-active {
  transition: all 0.3s ease;
  position: absolute;
}

.step-fade-enter-from,
.step-fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* Transitions for dividers */
.v-stepper :deep(.v-divider) {
  transition: width 0.5s ease, opacity 0.5s ease;
}

/* Fixed 3-column grid with vertical flow */
.tools-grid-container {
  display: grid;
  grid-template-columns: repeat(3, 1fr); /* Exactly 3 columns */
  gap: 12px;
  width: 100%;
  padding: 8px 4px;
  box-sizing: border-box;
}

/* Force 3 columns with higher specificity */
.v-dialog .tools-grid-container {
  display: grid !important;
  grid-template-columns: repeat(2, 1fr) !important;
  gap: 12px !important;
  width: 100% !important;
  padding: 8px 4px !important;
  box-sizing: border-box !important;
}

/* No height restriction on wrapper */
.tools-wrapper {
  width: 100%;
}

/* Let the dialog handle vertical scrolling */
.v-dialog {
  overflow-y: auto;
}

/* Tool cell styling */
.tool-cell {
  background-color: #f8f9fa;
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  border: 1px solid #e0e0e0;
  transition: all 0.2s ease;
}

/* Hover effect for tool cell */
.tool-cell:hover {
  background-color: #eef2ff;
  border-color: #4C64E2;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

/* Updated content layout with icon on left */
/* Fix for icon and text alignment on same line */
.tool-content {
  display: flex;
  align-items: center; 
  flex-direction: row; /* Ensure horizontal layout */
  width: 100%;
  min-width: 0; /* Important for flex item sizing */
}

.info-icon {
  flex: 0 0 auto; /* Don't grow, don't shrink, use auto basis */
  margin-right: 12px;
  color: #bbc0d5;
  transition: all 0.25s ease;
}

.tool-name {
  flex: 1 1 auto; /* Allow grow and shrink */
  font-size: 14px;
  font-weight: 500;
  font-family: 'SF Pro Display', system-ui, -apple-system, sans-serif;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #444;
  letter-spacing: 0.2px;
}
/* White search field with proper icon styling */
.search-field {
  background-color: white !important;
  border-radius: 4px;
}

.search-field :deep(.v-field__input) {
  color: #333 !important;
}

.search-field :deep(.v-field__prepend-inner) {
  color: #666 !important;
}

.tools-grid-container {
  display: grid;
  grid-template-columns: repeat(4, 1fr); /* 4 columns by default */
  gap: 12px;
  padding: 16px 8px;
}


/* Animations and keyframes */
@keyframes spin {
  0% {
    transform: rotate(0deg);
  }

  100% {
    transform: rotate(360deg);
  }
}

@keyframes pulse-animation {
  0% {
    transform: scale(0.8);
    box-shadow: 0 0 0 0 rgba(76, 100, 226, 0.7);
  }

  50% {
    transform: scale(1.3);
    box-shadow: 0 0 20px 10px rgba(76, 100, 226, 0.1);
  }

  100% {
    transform: scale(0.8);
    box-shadow: 0 0 0 0 rgba(76, 100, 226, 0);
  }
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease-out, transform 0.2s ease-out;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.fade-up-enter-active,
.fade-up-leave-active {
  transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}

.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(20px);
}


/* Add these styles */
.error-details {
  border-left: 3px solid #ef4444;
  background-color: #fef2f2;
}

.error-message {
  font-size: 14px;
  color: #b91c1c;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Responsive styles */
@media (max-width: 1300px) {
  .content-area {
    max-width: 95% !important;
  }
}

@media (max-width: 992px) {
  .search-container {
    max-width: 85%;
  }
}

@media (max-width: 768px) {
  .content-area {
    padding: 0 16px;
    padding-top: 40px;
    padding-bottom: 160px;
  }

  .search-container.moved {
    top: calc(100vh - 140px);
  }

  .main-title {
    font-size: 28px;
  }
}

@media (max-width: 480px) {
  .content-area {
    padding-top: 30px;
    padding-bottom: 140px;
  }

  .search-container.moved {
    top: calc(100vh - 120px);
  }

  .main-title {
    font-size: 24px;
  }
}

/* Case sensitivity note styles */
.case-sensitivity-note {
  background-color: #e8f4fd;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 24px;
  border-left: 3px solid #42a5f5;
  max-width: 800px;
  width: 100%;
}

.note-content {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: #0277bd;
  line-height: 1.4;
}

.note-icon {
  margin-right: 8px;
  flex-shrink: 0;
}

</style>

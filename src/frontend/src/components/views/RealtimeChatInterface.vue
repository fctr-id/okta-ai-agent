<template>
  <AppLayout contentClass="chat-content">
    <main class="content-area mt-10" :class="{ 'has-results': messages.length > 0 }">
      <!-- Search Container with Animated Position -->
      <div :class="['search-container', messages.length > 0 ? 'moved' : '']">
        <!-- Title with animated gradient underline -->
        <div :class="['title-wrapper', messages.length > 0 ? 'hidden' : '']">
          <h1 class="main-title">I'm Tako. How can I help you?</h1>
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
            <div class="search-input-wrapper">
              <textarea 
                v-model="userInput" 
                @keydown="handleKeyDown" 
                @input="adjustTextareaHeight"
                ref="textareaRef"
                placeholder="Ask a question about your Okta tenant..." 
                class="search-textarea"
                :disabled="isProcessing"
                rows="1"
              ></textarea>
              <button v-if="userInput" @click="clearInput" class="clear-btn" aria-label="Clear input">
                <v-icon size="small">mdi-close</v-icon>
              </button>
            </div>
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
            <!-- Case-sensitivity note (commented out per user request)
            <div class="case-sensitivity-note mt-n8">
              <div class="note-content">
                <v-icon color="info" size="small" class="note-icon">mdi-information</v-icon>
                <span>Note: Application and group names are case-sensitive. Please enter them exactly as they appear in Okta.</span>
              </div>
            </div>
            -->
            
            <!-- Sample query suggestions -->
            <div class="suggestions-grid">
              <v-btn v-for="(suggestion, i) in suggestions" :key="i" class="suggestion-btn"
                variant="outlined" @click="selectSuggestion(suggestion)" size="small">
                {{ suggestion }}
              </v-btn>
            </div>
            
            <!-- Spacer between suggestions and tools button -->
            <div class="suggestions-spacer"></div>
            
            <div class="tools-button-container">
              <v-btn
                color="primary"
                class="tools-action-button"
                prepend-icon="mdi-database"
                @click="showToolsModal = true"
                elevation="1"
                rounded
              >
                View API entities available
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
                        <v-stepper-item :value="item.id" :complete="item.status === 'completed'"
                                         :error="item.status === 'error'" :disabled="item.status === 'pending'"
                                         class="custom-badge-step">
                          <template #icon>
                            <div v-if="item.status === 'active'" class="step-pulse-indicator"></div>
                            <v-icon v-else-if="item.status === 'completed'" color="#38b2ac">mdi-check-circle</v-icon>
                            <v-icon v-else-if="item.status === 'error'" color="error">mdi-alert-circle</v-icon>
                            <div v-else class="step-empty-indicator"></div>
                          </template>
                          <template #title>
                            <div class="step-badge-wrapper">
                              <span class="step-badge" :class="[`badge-${item.phase}`, { 'badge-error': item.status === 'error' } ]">{{ item.badge }}</span>
                              <div class="step-main-text" :class="{'dimmed': item.status === 'pending'}">{{ item.entity }}</div>
                              <div class="step-operation-text" :class="{'dimmed': item.status === 'pending'}">{{ item.operation }}</div>
                            </div>
                          </template>
                        </v-stepper-item>
                        <v-divider v-if="index < progressSteps.length - 1" :key="`divider-${index}`"></v-divider>
                      </template>
                    </transition-group>
                  </v-stepper-header>
                </v-stepper>
              </div>
            </div>

            <!-- Dedicated Error Container (outside stepper) -->
            <div v-if="rtExecutionStatus === 'error' && rtError" class="error-container-standalone mt-4">
              <div class="error-details pa-4 rounded bg-red-lighten-5">
                <div class="d-flex align-center text-red-darken-2">
                  <v-icon color="error" class="me-2">mdi-alert-circle-outline</v-icon>
                  <span class="font-weight-medium">Step failed: {{ getFailedStepName() }}</span>
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

      <v-dialog v-model="showToolsModal" max-width="850px" scrollable>
        <v-card class="entities-modal">
          <v-toolbar class="entities-modal-toolbar">
            <v-toolbar-title class="entities-modal-title">Available Okta API Entities</v-toolbar-title>
            <v-spacer></v-spacer>
            
            <div class="entities-search-wrapper">
              <v-text-field
                v-model="toolSearch"
                prepend-inner-icon="mdi-magnify"
                placeholder="Search entities..."
                hide-details
                density="compact"
                class="entities-search-field"
                variant="outlined"
              ></v-text-field>
            </div>
            
            <v-btn icon @click="showToolsModal = false" class="close-btn">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </v-toolbar>
          
          <v-card-text class="entities-modal-content">
            <div v-if="isLoadingTools" class="loading-container">
              <v-progress-circular indeterminate color="primary" size="28"></v-progress-circular>
              <span class="loading-text">Loading Okta entities...</span>
            </div>
            
            <div v-else class="entities-wrapper">
              <!-- Compact chip layout for entities -->
              <div class="entities-chips-container">
                <div
                  v-for="entity in filteredTools" 
                  :key="entity.entity_name"
                  class="entity-chip-wrapper"
                >
                  <div class="entity-chip-content">
                    {{ entity.display_name }}
                  </div>
                </div>
              </div>
              
              <!-- No results message -->
              <div v-if="filteredTools.length === 0" class="no-results-container">
                <v-icon size="48" class="no-results-icon">mdi-magnify-close</v-icon>
                <div class="no-results-text">No matching entities found</div>
                <div class="no-results-subtitle">Try a different search term</div>
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
  chunkedResults, // Add chunked results for progress indicators
  startProcess,
  connectToStream,
  cancelProcess,
  cleanup,
} = useRealtimeStream();

const userInput = ref('');
const messages = ref([]);
const messagesContainerRef = ref(null);
const textareaRef = ref(null);
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

// Comprehensive query suggestions for users (copied from ChatInterfaceV2.vue)
const suggestions = ref([
  'List all users along with their creation dates',
  'Show users with PUSH factor registered', 
  'Find users with SMS registered with phone number ending with 2364',
  'Show me all users who are in locked status',
  'List all groups and their descriptions',
  'Show applications assigned to user dan@fctr.io',
  'Find users in Engineering group with admin roles',
  'How many users were created last month?'
]);

const canSubmitQuery = computed(() => userInput.value.trim().length > 0 && !isProcessing.value);
const canCancelQuery = computed(() => isProcessing.value && rtProcessId.value && !isCancelling.value && rtExecutionStatus.value !== 'completed' && rtExecutionStatus.value !== 'error' && rtExecutionStatus.value !== 'cancelled');

// Load saved history on component mount
onMounted(() => {
  // Force document to be scrollable (fix for scrolling issues)
  document.documentElement.style.overflow = 'auto'
  document.body.style.overflow = 'auto'
  document.documentElement.style.height = 'auto'
  document.body.style.height = 'auto'

  // Force layout recalculation on smaller screens
  if (window.innerHeight <= 800) {
    document.querySelector('.chat-content')?.classList.add('small-screen')
  }

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
      nextTick(() => adjustTextareaHeight());
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (historyIndex.value > -1) {
      historyIndex.value--;
      userInput.value = historyIndex.value === -1 ? '' : messageHistory.value[historyIndex.value];
      nextTick(() => adjustTextareaHeight());
    }
  }
};

// Dynamic textarea height adjustment
const adjustTextareaHeight = () => {
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto';
    const scrollHeight = textareaRef.value.scrollHeight;
    const maxHeight = 6 * 24; // 6 rows * 24px line height
    textareaRef.value.style.height = Math.min(scrollHeight, maxHeight) + 'px';
  }
};

// Clear input function
const clearInput = () => {
  userInput.value = '';
  adjustTextareaHeight();
  if (textareaRef.value) {
    textareaRef.value.focus();
  }
};

// Handle suggestion selection
const selectSuggestion = (suggestion) => {
  userInput.value = suggestion;
  handleQuerySubmit();
};

// Map backend tool names to user-friendly display names (matching backend implementation)
const getStepDisplayName = (toolName, entity) => {
  if (!entity && toolName) {
    return toolName;
  }
  
  const displayMapping = {
    "api": entity,  // "users", "groups", "system_log", etc.
    "sql": `sql_${entity}`,  // "sql_users", "sql_groups", etc.
  };
  
  return displayMapping[toolName] || toolName;
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
  
  // When there's a general execution error but no specific failed step
  // Provide a cleaner message instead of showing the raw error
  if (rtError.value) {
    // Check if the error is about 0 failed steps (general execution failure)
    if (rtError.value.includes('0 failed steps') || rtError.value.includes('completed with 0')) {
      return 'Execution error occurred';
    }
    // For other errors, show a generic message
    return 'Error occurred during execution';
  }
  
  return 'Error! Please check the backend and try again.';
};

const hasStepperExpanded = computed(() => {
  // Expand the stepper container when:
  // 1. We have received execution steps from step_plan_info (more than the 4 bookend steps including hidden ones)
  // 2. OR we have an error condition
  const visibleStepsCount = rtSteps.value?.filter(step => !step.hidden).length || 0;
  return (visibleStepsCount > 3) || rtExecutionStatus.value === 'error';
});

const resetInterface = async () => {
  if (isProcessing.value && rtProcessId.value) {
    await handleCancelExecution();
  }
  messages.value = [];
  userInput.value = '';
  cleanup();
  
  // Clear the error state from previous runs
  rtError.value = null;
  
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
    // Only enable auto-scroll if user is near the bottom (within 100px)
    // If user scrolls up, disable auto-scroll to allow manual scrolling
    autoScroll.value = scrollHeight - scrollTop - clientHeight < 100;
  }
};

// Stepper management using the managed step flow from useRealtimeStream

const progressSteps = computed(() => {
  return rtSteps.value
    .filter(step => !step.hidden) // Filter out hidden steps
    .map((step, index) => {
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
      entity = 'Results';
      operation = '';
      phase = 'finalizing';
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
      badge = (tool || step.name || `step_${index+1}`).toUpperCase();
      entity = step.entity || '';
      operation = step.operation || '';
      phase = 'other';
    }

    return {
      id: step.id || `step_${index}`,
      badge,
      entity,
      operation,
      phase,
      status: step.status || 'pending'
    };
  });
});

const currentProgressStepId = computed(() => {
  // Find the currently active step from the managed step flow
  const activeStep = rtSteps.value.find(step => step.status === 'active');
  if (activeStep) {
    return activeStep.id || 'active_step';
  }
  
  // If no active step, find the last non-pending step
  for (let i = rtSteps.value.length - 1; i >= 0; i--) {
    const step = rtSteps.value[i];
    if (step.status !== 'pending') {
      return step.id || `step_${i}`;
    }
  }
  
  // Default to first step if all are pending
  return rtSteps.value.length > 0 ? (rtSteps.value[0].id || 'step_0') : 'default_step';
});

const showProgressDisplayArea = computed(() =>
  messages.value.length > 0 &&
  (isProcessing.value || ['planning', 'executing', 'processing_final_results'].includes(rtExecutionStatus.value)) &&
  !rtResults.value && rtExecutionStatus.value !== 'error' && rtExecutionStatus.value !== 'cancelled'
);

const showFinalOutcomeArea = computed(() =>
  messages.value.length > 0 &&
  (rtResults.value || rtExecutionStatus.value === 'error' || rtExecutionStatus.value === 'cancelled')
);

watch([rtExecutionStatus, rtSteps, rtResults, rtError, rtPlanGenerated, rtCurrentStepIndexVal, isProcessing], () => {
  scrollToBottom();
}, { deep: true });

watch(messages, () => {
  scrollToBottom();
}, { deep: true });

// Watch for input changes to adjust textarea height
watch(userInput, () => {
  nextTick(() => adjustTextareaHeight());
});

// Filter Okta entities based on search
const filteredTools = computed(() => {
  if (!toolSearch.value) return availableTools.value;

  const search = toolSearch.value.toLowerCase();
  return availableTools.value.filter(entity =>
    entity.display_name.toLowerCase().includes(search) ||
    entity.entity_name.toLowerCase().includes(search) ||
    entity.description.toLowerCase().includes(search)
  );
});

// Function to fetch Okta entities from backend
const fetchOktaEntities = async () => {
  isLoadingTools.value = true;
  try {
    const response = await fetch('/api/realtime/okta-entities');
    const data = await response.json();
    availableTools.value = data.entities || [];
  } catch (error) {
    console.error('Error fetching Okta entities:', error);
    availableTools.value = [];
  } finally {
    isLoadingTools.value = false;
  }
};

// Watch modal visibility to load entities when opened
watch(showToolsModal, (newVal) => {
  if (newVal && availableTools.value.length === 0) {
    fetchOktaEntities();
  }
});


</script>

<style scoped>
/* CSS Variables */
:root {
  --primary: #8e54e9;
}

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

.search-input-wrapper {
  flex: 1;
  position: relative;
  display: flex;
  align-items: flex-end;
  min-height: 42px;
}

.search-textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  font-family: inherit;
  color: #333;
  padding: 11px 40px 11px 4px; /* Reduced left padding to 4px for more text space */
  margin: 0;
  resize: none;
  line-height: 1.5;
  min-height: 42px;
  max-height: 144px; /* 6 rows * 24px */
  overflow-y: auto;
  transition: height 0.2s ease;
}

.search-textarea::placeholder {
  color: #999;
  font-size: 15px;
}

.search-textarea:disabled {
  color: #999;
  cursor: not-allowed;
}

.clear-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: #e0e0e0;
  border: 1px solid #bbb;
  color: #555;
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}

.clear-btn:hover {
  color: #333;
  background: #d0d0d0;
  border-color: #999;
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

.suggestions-spacer {
  height: 24px;
  width: 100%;
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
  width: 480px;
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
  padding: 16px 32px;
  overflow-x: auto;
  justify-content: space-between !important;
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
  min-width: 140px;
  flex-shrink: 0;
  padding: 0 12px;
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
  /* We now render custom content (badge + main), so neutralize defaults */
  font-size: 0 !important; /* hide native text spacing */
  line-height: 0 !important;
  margin-top: 0 !important;
  color: transparent !important;
  text-align: center !important;
}

.v-stepper :deep(.v-stepper-item__content) {
  margin: 8px auto 0 !important;
  padding: 0 4px !important;
  text-align: center !important;
}

/* Subtitle slot unused now */
.v-stepper :deep(.v-stepper-item__subtitle) { display: none !important; }

/* Custom badge + main layout */
.custom-badge-step .step-badge-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 72px;
}

.step-badge {
  display: inline-block;
  padding: 3px 8px; /* slightly larger badge */
  font-size: 0.66rem; /* tiny bump */
  font-weight: 600;
  letter-spacing: 0.75px; /* tighten a touch */
  border-radius: 10px;
  background: #eef1f5;
  color: #44515e;
  line-height: 1.12;
  position: relative;
  text-transform: uppercase;
  max-width: 100%;
  white-space: nowrap;
}

/* Phase color accents */
.step-badge.badge-crafting { background: #f3e5f5; color: #7b1fa2; }
.step-badge.badge-generating { background: #e9f7ff; color: #076489; }
.step-badge.badge-formatting { background: #f5f6ff; color: #2d3c9c; }
.step-badge.badge-enriching { background: #fde7d9; color: #f57c00; }
.step-badge.badge-finalizing { background: #e8f5e8; color: #2e7d32; }
.step-badge.badge-api { background: #e8f9f6; color: #0f6f62; }
.step-badge.badge-sql { background: #fff4e5; color: #9a5a00; }
.step-badge.badge-hybrid { background: #fce4ec; color: #ad1457; }
.step-badge.badge-other { background: #ececec; color: #555; }
.step-badge.badge-error { 
  /* Softer error styling (Option B) to align with other pastel phase badges */
  background: #fbe9ea !important; /* light, slightly cool red */
  color: #b3261e !important;      /* Material error primary */
  box-shadow: 0 0 0 1px #f2b8b5 inset; /* subtle border for definition */
}

.step-main-text {
  font-size: 0.72rem; /* slightly smaller */
  font-weight: 500;
  line-height: 1.18;
  color: #6b7280; /* Lighter gray for entity (same as operation for balance) */
  text-align: center;
  word-break: break-word;
  max-width: 165px; /* allow longer operation names */
  white-space: normal;
}

.step-main-text.dimmed { opacity: 0.55; }

.step-operation-text {
  font-size: 0.65rem; /* smaller than entity */
  font-weight: 400;
  line-height: 1.15;
  color: #6b7280; /* Lighter gray for operation */
  text-align: center;
  word-break: break-word;
  max-width: 165px;
  white-space: normal;
  margin-top: 2px; /* small gap between entity and operation */
}

.step-operation-text.dimmed { opacity: 0.55; }

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

/* Entities Modal Styling - Match Realtime Interface Theme */
.entities-modal {
  border-radius: 16px !important;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.12) !important;
}

.entities-modal-toolbar {
  background: linear-gradient(135deg, #667eea, #764ba2) !important;
  color: white !important;
  padding: 0 24px !important;
  min-height: 72px !important;
}

.entities-modal-title {
  font-size: 18px !important;
  font-weight: 600 !important;
  color: white !important;
}

.entities-search-wrapper {
  flex: 1;
  max-width: none;
  margin: 0 20px;
}

.entities-search-field {
  background-color: rgba(255, 255, 255, 0.15) !important;
  border-radius: 8px !important;
  backdrop-filter: blur(10px);
}

.entities-search-field :deep(.v-field) {
  background-color: rgba(255, 255, 255, 0.15) !important;
  border-radius: 8px !important;
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
}

.entities-search-field :deep(.v-field__input) {
  color: white !important;
  font-size: 14px !important;
}

.entities-search-field :deep(.v-field__input input::placeholder) {
  color: rgba(255, 255, 255, 0.8) !important;
}

.entities-search-field :deep(.v-field__prepend-inner) {
  color: rgba(255, 255, 255, 0.9) !important;
}

.close-btn {
  color: white !important;
  background-color: rgba(255, 255, 255, 0.1) !important;
  border-radius: 8px !important;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background-color: rgba(255, 255, 255, 0.2) !important;
}

.entities-modal-content {
  padding: 24px !important;
  background: #fafbfc;
}

.loading-container {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  gap: 16px;
}

.loading-text {
  color: #666;
  font-size: 16px;
  font-weight: 500;
}

/* Entities Wrapper and Chips - Match Suggestion Button Style */
.entities-wrapper {
  width: 100%;
}

.entities-chips-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-start;
  align-items: flex-start;
  max-height: 420px;
  overflow-y: auto;
  padding: 8px;
}

.entity-chip-wrapper {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid transparent;
}

.entity-chip-wrapper:nth-child(4n+1) {
  border-color: rgba(102, 126, 234, 0.4);
}

.entity-chip-wrapper:nth-child(4n+2) {
  border-color: rgba(118, 75, 162, 0.4);
}

.entity-chip-wrapper:nth-child(4n+3) {
  border-color: rgba(86, 204, 242, 0.4);
}

.entity-chip-wrapper:nth-child(4n+4) {
  border-color: rgba(47, 128, 237, 0.4);
}

.entity-chip-content {
  background: white;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #444;
  letter-spacing: 0.1px;
  display: flex;
  align-items: center;
  white-space: nowrap;
  position: relative;
  z-index: 1;
  min-height: 28px;
}

/* No Results Styling */
.no-results-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
  text-align: center;
}

.no-results-icon {
  color: #bbb !important;
  margin-bottom: 16px;
}

.no-results-text {
  font-size: 18px;
  font-weight: 500;
  color: #666;
  margin-bottom: 8px;
}

.no-results-subtitle {
  font-size: 14px;
  color: #999;
}

/* Scrollbar styling for chips container */
.entities-chips-container::-webkit-scrollbar {
  width: 6px;
}

.entities-chips-container::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.entities-chips-container::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}

.entities-chips-container::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
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

.error-container-standalone {
  max-width: 800px;
  margin: 0 auto;
}

.error-message {
  font-size: 14px;
  color: #b91c1c;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Chunk progress indicator styles */
.chunk-progress-indicator {
  border-left: 3px solid #3b82f6;
  background-color: #eff6ff;
  animation: pulse-blue 2s ease-in-out infinite alternate;
}

@keyframes pulse-blue {
  0% {
    background-color: #eff6ff;
  }
  100% {
    background-color: #dbeafe;
  }
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
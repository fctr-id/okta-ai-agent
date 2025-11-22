<template>
    <AppLayout contentClass="chat-content">
        <main class="content-area mt-10" :class="{ 'has-results': hasResults }">
            <!-- Search Container with Animated Position -->
            <div :class="['search-container', hasResults ? 'moved' : '']">
                <!-- Title with animated gradient underline -->
                <div :class="['title-wrapper', hasResults ? 'hidden' : '']">
                    <h1 class="main-title">
                        I'm Tako. How can I help you?
                    </h1>
                    <div class="title-underline"></div>
                </div>

                <!-- Modern integrated search -->
                <div class="search-wrapper">
                    <div class="integrated-search-bar">
                        <!-- Reset button (only when results are showing and not loading) -->
                        <transition name="fade" mode="out-in">
                            <div v-if="hasResults && !isLoading && !reactLoading" class="reset-btn-container" key="reset-btn">
                                <v-tooltip text="Start over" location="top">
                                    <template v-slot:activator="{ props }">
                                        <button v-bind="props" class="action-btn reset-btn" @click="resetInterface"
                                            aria-label="Reset search">
                                            <v-icon>mdi-refresh</v-icon>
                                        </button>
                                    </template>
                                </v-tooltip>
                            </div>
                        </transition>

                        <!-- Stop button with progress (when loading) -->
                        <transition name="fade">
                            <div v-if="isLoading || reactLoading" class="stop-btn-container">
                                <v-tooltip text="Stop processing" location="top">
                                    <template v-slot:activator="{ props }">
                                        <button v-bind="props" @click="stopProcessing" class="action-btn stop-btn "
                                            aria-label="Stop processing">
                                            <!-- Progress circle - thinner spinner only -->
                                            <div class="circular-progress-container">
                                                <div v-if="!isStreaming" class="indeterminate-progress"></div>
                                                <svg v-else class="determinate-progress" viewBox="0 0 36 36">
                                                    <circle class="progress-background" cx="18" cy="18" r="16"
                                                        fill="none" />
                                                    <circle class="progress-value" cx="18" cy="18" r="16" fill="none"
                                                        :stroke-dasharray="`${progress * 0.98}, 100`" />
                                                </svg>
                                            </div>
                                            <!-- Larger stop icon -->
                                            <v-icon size="large" color="#4C64E2">mdi-stop</v-icon>
                                        </button>
                                    </template>
                                </v-tooltip>
                            </div>
                        </transition>

                        <!-- Search input with dynamic placeholder -->
                        <v-text-field v-model="userInput" @keydown="handleKeyDown" autofocus refs="searchInput"
                            @update:model-value="handleUserInputChange" :focused="isFocused" @focus="isFocused = true"
                            @blur="isFocused = false" placeholder="Ask anything about your Okta tenant..."
                            variant="plain" color="#4C64E2" bg-color="transparent" hide-details class="search-input"
                            :clearable="true" />

                        <!-- Send button -->
                        <v-tooltip text="Send query" location="top">
                            <template v-slot:activator="{ props }">
                                <button v-bind="props" class="action-btn send-btn"
                                    :disabled="!userInput || !(userInput?.trim?.())" @click="sendQuery"
                                    aria-label="Send query">
                                    <v-icon>mdi-send</v-icon>
                                </button>
                            </template>
                        </v-tooltip>
                    </div>
                </div>

                <!-- Suggestions -->
                <transition name="fade-up">
                    <div v-if="!hasResults" class="suggestions-wrapper">
                        <div class="suggestions-grid">
                            <v-btn v-for="(suggestion, i) in suggestions" :key="i" class="suggestion-btn"
                                variant="outlined" @click="selectSuggestion(suggestion)" size="small">
                                {{ suggestion }}
                            </v-btn>
                        </div>
                    </div>
                </transition>
            </div>

            <!-- Display User question -->
            <transition name="fade">
                <div v-if="hasResults && lastQuestion" class="question-header-container">
                    <div class="question-header">
                        <div class="question-icon">
                            <v-icon color="#4C64E2">mdi-help-circle</v-icon>
                        </div>
                        <div class="question-text">{{ lastQuestion }}</div>
                        <div class="question-timestamp">{{ getCurrentTime() }}</div>
                    </div>
                </div>
            </transition>

            <!-- Error Alert -->
            <transition name="fade-up">
                <div v-if="reactError" class="error-alert-container">
                    <v-alert
                        type="error"
                        variant="outlined"
                        prominent
                        closable
                        @click:close="reactError = null"
                        class="error-alert"
                        color="error"
                    >
                        <template v-slot:prepend>
                            <v-icon size="large">mdi-alert-circle</v-icon>
                        </template>
                        <div class="error-content">
                            <div class="error-title">Error</div>
                            <div class="error-message">Please try again. If it persists, contact the admin.</div>
                        </div>
                    </v-alert>
                </div>
            </transition>

            <!-- ReAct Two-Panel Interface (only in ReAct mode) -->
            <transition name="fade-up">
                <div v-if="isReActMode && (reactLoading || reactSteps.length > 0 || reactExecutionStarted)" class="react-panels mb-4">
                    <!-- Discovery Panel -->
                    <DiscoveryPanel
                        :steps="reactSteps"
                        :isThinking="reactLoading && reactSteps.length === 0"
                        :isComplete="reactDiscoveryComplete"
                        :error="reactError"
                        :executionStarted="reactExecutionStarted"
                    />
                    
                    <!-- Execution Panel (only show after discovery starts AND we have a script or execution started) -->
                    <ExecutionPanel
                        v-if="(reactDiscoveryComplete && reactGeneratedScript) || reactExecutionStarted"
                        :validationStep="reactValidationStep"
                        :executionStarted="reactExecutionStarted"
                        :isExecuting="reactIsExecuting"
                        :isComplete="!reactLoading && !reactProcessing && reactResults !== null"
                        :executionError="reactError"
                        :executionMessage="reactExecutionMessage"
                        :progressValue="reactExecutionProgress"
                        :subprocessProgress="reactSubprocessProgress"
                        :resultCount="reactResults?.metadata?.count || 0"
                        :tokenUsage="reactTokenUsage"
                        :rateLimitWarning="reactRateLimitWarning"
                        :generatedScript="reactGeneratedScript"
                    />
                </div>
            </transition>

            <!-- Results Area with Smooth Transitions -->
            <transition name="fade-up">
                <div v-if="hasResults && ((isReActMode && !reactLoading) || (!isReActMode && !isLoading))"
                    :class="['results-container', getContentClass(isReActMode ? MessageType.TABLE : currentResponse.type)]" class="mt-8">
                    <DataDisplay 
                        v-if="isReActMode && reactResults"
                        :type="reactResults.display_type"
                        :content="reactResults.content"
                        :metadata="reactResults.metadata"
                    />
                    <DataDisplay 
                        v-else-if="!isReActMode"
                        :type="currentResponse.type" 
                        :content="currentResponse.content"
                        :metadata="currentResponse.metadata"
                    />
                </div>
            </transition>
        </main>

        <!-- Loading overlay -->
        <transition name="fade">
            <div v-if="isLoading" class="inline-loading-indicator">
                <div class="loading-pulse"></div>
                <span>{{ isStreaming ? `Processing data (${progress}%)...` : 'Processing your query...' }}</span>
            </div>
        </transition>
    </AppLayout>
</template>

<script setup>
/**
 * Chat Interface Component
 * 
 * Main component for the search and query interface that handles
 * user input, displays results, and manages the overall UI state.
 */

console.log('🚀 ChatInterfaceV2 INITIALIZING')
console.log('📍 Current URL:', window.location.href)

import { ref, watch, nextTick, onMounted } from 'vue'
import { useFetchStream } from '@/composables/useFetchStream'
import { useSanitize } from '@/composables/useSanitize'
import { useReactStream } from '@/composables/useReactStream'
import DataDisplay from '@/components/messages/DataDisplay.vue'
import DiscoveryPanel from '@/components/messages/DiscoveryPanel.vue'
import ExecutionPanel from '@/components/messages/ExecutionPanel.vue'
import { MessageType } from '@/components/messages/messageTypes'
import { useAuth } from '@/composables/useAuth'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

// ---------- STATE MANAGEMENT ----------

/**
 * Core UI state
 */
const userInput = ref('') // Current text in the input field
const isLoading = ref(false) // Loading state for API calls
const isClearable = ref(true) // Whether the text input can be cleared
const lastQuestion = ref('') // Stores the last question that was asked
const isFocused = ref(false) // Tracks if the search input is focused
const hasResults = ref(false) // Whether there are results to display
const auth = useAuth()
const router = useRouter()

// Add new refs to store stream controller and track streaming progress
const streamController = ref(null)
const { postStream, isStreaming, progress } = useFetchStream()

// ReAct mode detection and state
const isReActMode = ref(true) // Default to ReAct mode
const {
    isLoading: reactLoading,
    isProcessing: reactProcessing,
    error: reactError,
    currentStep: reactCurrentStep,
    discoverySteps: reactSteps,
    isDiscoveryComplete: reactDiscoveryComplete,
    validationStep: reactValidationStep,
    executionStarted: reactExecutionStarted,
    isExecuting: reactIsExecuting,
    executionMessage: reactExecutionMessage,
    executionProgress: reactExecutionProgress,
    subprocessProgress: reactSubprocessProgress,
    rateLimitWarning: reactRateLimitWarning,
    generatedScript: reactGeneratedScript,
    results: reactResults,
    tokenUsage: reactTokenUsage,
    startProcess: startReActProcess,
    connectToStream: connectReActStream,
    cancelProcess: cancelReAct
} = useReactStream()

// Watch mode changes and log
watch(isReActMode, (newMode) => {
    console.log('🔥 MODE CHANGED:', newMode ? 'REACT MODE 🚀' : 'TAKO MODE 🤖')
})

// Initialize sanitization utilities
const { query: sanitizeQuery, text: sanitizeText } = useSanitize()

/**
 * Response data state
 */
const currentResponse = ref({
    type: MessageType.METADATA,
    content: [],
    metadata: {
        headers: [],
        total: 0
    }
})

// ---------- UTILITY FUNCTIONS ----------

/**
 * Stops the current query processing and aborts the stream
 */
const stopProcessing = () => {
    if (isReActMode.value) {
        // Cancel ReAct process
        cancelReAct()
        isLoading.value = false
        return
    }
    
    // Tako flow
    if (streamController.value) {
        streamController.value.abort();
        streamController.value = null;
        isLoading.value = false;
    }
}

/**
 * Get the current time formatted as HH:MM
 * @returns {string} Formatted time string
 */
const getCurrentTime = () => {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Ensures userInput is always a string and applies basic sanitization
 * @param {*} val - The new input value
 */
const handleUserInputChange = (val) => {
    // Ensure we always have a string
    const rawInput = val === null ? '' : val

    // Apply lightweight sanitization (not full, as user is still typing)
    userInput.value = sanitizeText(rawInput, {
        maxLength: 2000,
        removeHtml: true,
        trim: false // Don't trim while typing
    })
}

/**
 * Determines the CSS class to apply based on response type
 * @param {string} type - The message type from MessageType enum
 * @returns {string} CSS class name
 */
const getContentClass = (type) => {
    if (type === MessageType.STREAM || type === MessageType.TABLE) {
        return 'full-width-results';
    } else {
        return 'compact-results';
    }
}

/**
 * Handle authentication errors by redirecting to login
 */
const handleAuthError = async (status) => {
    if (status === 401 || status === 403) {
        console.warn(`Authentication error (${status}), redirecting to login`);

        try {
            // Use the proper logout method from auth composable
            await auth.logout();

            // After logout completes, force navigation
            setTimeout(() => {
                window.location.href = '/login';
            }, 100);
        } catch (error) {
            console.error("Error during logout:", error);
            // Force navigation even if logout fails
            window.location.href = '/login';
        }
        return true;
    }
    return false;
}

// ---------- PREDEFINED CONTENT ----------

/**
 * Query suggestions for users
 */
const suggestions = ref([
    'List all  users along with their creation dates',
    'Show users with PUSH factor registered',
    'Find users withs SMS  registered with phone number ending with 2364',
    'How many users were created last month?',
    'List all users assigned to the \'monday\' app',
    'Find all users reporting to \'noah.williams\' and get me their emails only ',
    'List all users along with their registered factors',
    'show me all users who are in locked status'
])

// ---------- API INTERACTION ----------


// ---------- EVENT HANDLERS ----------

/**
 * Handles keyboard input to trigger query submission
 * @param {KeyboardEvent} e - Keyboard event
 */
const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        if (userInput.value.trim()) {
            sendQuery()
        }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (historyIndex.value < messageHistory.value.length - 1) {
            historyIndex.value++
            // Sanitize when retrieving from history
            userInput.value = sanitizeQuery(messageHistory.value[historyIndex.value])
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (historyIndex.value > -1) {
            historyIndex.value--
            // Sanitize when retrieving from history
            userInput.value = historyIndex.value === -1 ? '' :
                sanitizeQuery(messageHistory.value[historyIndex.value])
        }
    }
}

/**
 * Clears the input field
 */
const clearInput = () => {
    userInput.value = ''
}

/**
 * Fills input with predefined query and submits
 * @param {string} query - The query to use
 */
const useQuery = (query) => {
    // Sanitize even predefined queries
    userInput.value = sanitizeQuery(query)
    sendQuery()
}

/**
 * Resets the interface to its initial state
 */
const resetInterface = () => {
    hasResults.value = false
    userInput.value = ''
    currentResponse.value = {
        type: MessageType.TEXT,
        content: '',
        metadata: {}
    }
    
    // Reset ReAct state
    if (isReActMode.value) {
        // Cancel any ongoing ReAct process
        cancelReAct()
        
        // Reset all ReAct-specific state
        reactSteps.value = []
        reactResults.value = null
        reactValidationStep.value = null
        reactExecutionStarted.value = false
        reactIsExecuting.value = false
        reactExecutionMessage.value = ''
        reactExecutionProgress.value = 0
        reactSubprocessProgress.value = []
        reactTokenUsage.value = null
        reactDiscoveryComplete.value = false
        reactError.value = null
    }
}

/**
 * Handles suggestion selection
 * @param {string} suggestion - The selected suggestion
 */
const selectSuggestion = (suggestion) => {
    // Sanitize suggestion before populating field
    userInput.value = sanitizeQuery(suggestion);

    // Focus the input field after populating
    nextTick(() => {
        const inputElement = document.querySelector('.search-input input');
        if (inputElement) {
            inputElement.focus();
        }
    });
}

/**
 * Submits the query to the backend API
 */
const sendQuery = async () => {
    if (!userInput.value.trim() || isLoading.value) return

    // Apply full sanitization before sending query
    const rawQuery = userInput.value.trim()
    const sanitizedQuery = sanitizeQuery(rawQuery, { maxLength: 2000 })

    lastQuestion.value = sanitizedQuery
    isLoading.value = true
    hasResults.value = true
    userInput.value = ''

    // Store sanitized query in history
    updateMessageHistory(sanitizedQuery)

    try {
        // Check if ReAct mode is enabled
        console.log('[ChatInterfaceV2] isReActMode:', isReActMode.value)
        
        if (isReActMode.value) {
            // Use ReAct flow
            console.log('[ChatInterfaceV2] Using ReAct flow for query:', sanitizedQuery)
            const pid = await startReActProcess(sanitizedQuery)
            if (pid) {
                await connectReActStream(pid)
            }
            isLoading.value = false
            return
        }

        // Tako flow (existing)
        console.log('[ChatInterfaceV2] Using Tako flow for query:', sanitizedQuery)
        // First check authentication only (lightweight call) 
        const authCheckResponse = await fetch('/api/query?auth_check=true', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        // Check for auth errors before proceeding
        if (await handleAuthError(authCheckResponse.status)) {
            isLoading.value = false;
            return;
        }
        // Send sanitized query to API
        const streamResponse = await postStream('/api/query', { query: sanitizedQuery })
        streamController.value = streamResponse

        let currentData = []
        let headers = []

        // Set hasResults to true only when we receive the first data
        let receivedFirstData = false

        for await (const data of streamResponse.getStream()) {
            if (!data) continue

            // Set hasResults to true on first valid data
            if (!receivedFirstData) {
                hasResults.value = true
                receivedFirstData = true
            }

            switch (data.type) {
                case 'metadata':
                    // Store headers from metadata
                    headers = data.content?.headers || []
                    currentResponse.value = {
                        type: MessageType.STREAM,
                        content: [],
                        metadata: data.content
                    }
                    break

                case 'batch':
                    if (Array.isArray(data.content)) {
                        // Accumulate batch data
                        currentData = [...currentData, ...data.content]

                        // Update response with correct structure
                        currentResponse.value = {
                            type: MessageType.STREAM,
                            content: currentData,
                            metadata: {
                                ...(currentResponse.value.metadata || {}),
                                headers: headers,
                                total: currentData.length,
                                batchSize: data.content.length,
                                currentBatch: data.metadata?.batch_number || 0
                            }
                        }
                    }
                    break

                case 'complete':
                    isLoading.value = false
                    streamController.value = null
                    break

                case 'error':
                    currentResponse.value = {
                        type: MessageType.ERROR,
                        content: data.content || 'An error occurred',
                        metadata: {}
                    }
                    isLoading.value = false
                    streamController.value = null
                    break
            }
        }
    } catch (error) {
        currentResponse.value = {
            type: MessageType.ERROR,
            content: error.message || 'Unknown error occurred',
            metadata: {}
        }
        isLoading.value = false
        streamController.value = null
    } finally {
        isLoading.value = false
        streamController.value = null
        setTimeout(() => {
            const inputElement = document.querySelector('.search-input input');
            if (inputElement) {
                inputElement.focus();
            }
        }, 100);
    }
}

/* Code to let the user scroll through the last 5 questions */
// Inside script setup, add these constants and refs
const CONFIG = {
    MAX_HISTORY: 5
}

const messageHistory = ref([])
const historyIndex = ref(-1)

// Add this mounted hook to load saved history
onMounted(() => {
    try {
        const savedHistory = localStorage.getItem('messageHistory')
        if (savedHistory) {
            // Sanitize history from localStorage before using
            messageHistory.value = JSON.parse(savedHistory).map(item => sanitizeQuery(item))
        }
        
        // Detect ReAct mode from query param or localStorage
        const urlParams = new URLSearchParams(window.location.search)
        const modeParam = urlParams.get('mode')
        const savedMode = localStorage.getItem('agentMode')
        
        console.log('[ChatInterfaceV2] Mode detection:', { 
            url: window.location.href,
            modeParam, 
            savedMode 
        })
        
        isReActMode.value = modeParam !== 'realtime' && (modeParam === 'react' || savedMode !== 'realtime')
        
        console.log('[ChatInterfaceV2] isReActMode set to:', isReActMode.value)
        
        // Save mode preference
        if (modeParam) {
            localStorage.setItem('agentMode', modeParam)
        }
    } catch (error) {
        console.error('Failed to load message history:', error)
        localStorage.removeItem('messageHistory')
    }
})

/**
 * Updates the message history by adding a new query or moving an existing one to the front
 * @param {string} query - The query to add to history
 */
const updateMessageHistory = (query) => {
    try {
        // Ensure the query is sanitized
        const sanitizedQuery = sanitizeQuery(query)
        const existingIndex = messageHistory.value.indexOf(sanitizedQuery)

        if (existingIndex === -1) {
            // New message - add to front of history
            messageHistory.value = [sanitizedQuery, ...messageHistory.value.slice(0, CONFIG.MAX_HISTORY - 1)]
        } else {
            // Existing message - move to front of history
            messageHistory.value = [
                sanitizedQuery,
                ...messageHistory.value.slice(0, existingIndex),
                ...messageHistory.value.slice(existingIndex + 1)
            ]
        }

        // Save to localStorage and reset index
        localStorage.setItem('messageHistory', JSON.stringify(messageHistory.value))
        historyIndex.value = -1
    } catch (historyError) {
        console.error('History management error:', historyError)
    }
}

onMounted(() => {
    // Force document to be scrollable
    document.documentElement.style.overflow = 'auto'
    document.body.style.overflow = 'auto'
    document.documentElement.style.height = 'auto'
    document.body.style.height = 'auto'

    // Force layout recalculation on smaller screens
    if (window.innerHeight <= 800) {
        document.querySelector('.chat-content')?.classList.add('small-screen')
    }
})
</script>

<style scoped>
/* Search container */
.chat-content {
    background: transparent;
}

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
    backface-visibility: hidden; /* Prevent rendering artifacts */
    -webkit-transform-style: preserve-3d;  /* Prevent rendering artifacts on webkit */
    transform-style: preserve-3d; /* Prevent rendering artifacts */
}

.search-container.moved {
    top: calc(100vh - 200px);
    transform: translate(-50%, 0);
}

/* Title with animated underline */
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
    background: linear-gradient(135deg,
            #ff9966,
            #ff5e62,
            #845ec2,
            #2c73d2,
            #0081cf);
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    position: relative;
}

.title-underline {
    height: 4px;
    width: 100px;
    margin: 0 auto;
    background: linear-gradient(90deg, var(--primary), #6373E5);
    border-radius: 2px;
    display: none;
}

/* Main content area */
.content-area {
    width: calc(100% - 40px);
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 0;
    transition: all 0.3s ease;
}

.content-area.has-results {
    padding-top: 60px;
    padding-bottom: 60px;
}

/* Modern integrated search */
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

/* Add a subtle side accent when focused */
.integrated-search-bar:has(.v-field--focused)::before {
    content: '';
    position: absolute;
    left: 0;
    top: 10px;
    bottom: 10px;
    width: 3px;
    border-radius: 4px;
}

.integrated-search-bar:focus-within {
    box-shadow: 0 8px 30px rgba(76, 100, 226, 0.15);
    transform: translateY(-2px);
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

.search-input :deep(.v-field__clearable:hover .v-icon) {
    color: #666;
}

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

/* Action buttons */
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
    width: 38px !important; /* Match stop button width */
    height: 38px !important; /* Match stop button height */
    margin-right: 0; /* Remove extra margin */
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

/* Stop button styling */
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




/* Container styles for the button containers */
.reset-btn-container,
.stop-btn-container {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    flex-shrink: 0;
}

/* Progress indicators */
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

@keyframes spin {
    0% {
        transform: rotate(0deg);
    }

    100% {
        transform: rotate(360deg);
    }
}

.determinate-progress {
    width: 100%;
    height: 100%;
    transform: rotate(-90deg);
}

.progress-background {
    stroke: rgba(76, 100, 226, 0.2);
    stroke-width: 1.5px;
    /* Thinner stroke: 2px → 1.5px */
}

.progress-value {
    stroke: #4C64E2;
    stroke-linecap: round;
    stroke-width: 1.5px;
    /* Thinner stroke: 2px → 1.5px */
    transition: stroke-dasharray 0.3s ease;
}

/* Update the suggestions CSS */
.suggestions-wrapper {
    margin-top: 1.5rem;
    padding: 0 1rem;
    opacity: 1;
    transition: opacity 0.4s ease;
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

/* Updated gradient border inspired by the title gradient */
.suggestion-btn::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: var(--border-radius);
    padding: 1.5px;
    background: linear-gradient(90deg,
            var(--primary),
            #5e72e4,
            #8e54e9,
            #d442f5);
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

/* Centered question header with blue background */
.question-header-container {
    max-width: var(--max-width);
    width: calc(100% - 40px);
    margin: 24px auto 20px;
    display: flex;
    justify-content: center;
    position: relative;
    z-index: 40; /* Lower than search container but higher than results */
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

@keyframes subtleSlideUp {
    from {
        opacity: 0;
        transform: translateY(12px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Results containers */
.results-container {
    max-width: var(--max-width);
    width: calc(100% - 40px);
    margin-left: auto !important;
    margin-right: auto !important;
    margin-top: 12px;
    margin-bottom: 120px !important;
    display: flex;
    flex-direction: column;
    align-items: center;
    overflow: visible !important;
}

.full-width-results {
    border-radius: var(--border-radius);
    box-shadow: var(--shadow-medium);
    background: white;
    overflow: hidden;
    width: 100%;
}

.compact-results {
    width: fit-content;
    max-width: var(--max-width);
    margin-left: 0;
    margin-right: auto;
    background: transparent;
    box-shadow: none;
}

/* Enhanced loading indicator */
.inline-loading-indicator {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: white;
    border-radius: 18px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15),
        0 6px 12px rgba(76, 100, 226, 0.08);
    padding: 18px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    z-index: 2000; /* Increased z-index to ensure it's above everything */
    min-width: 240px;
    border: 1px solid rgba(76, 100, 226, 0.1);
    will-change: opacity, transform; /* Optimize for animation */
    backface-visibility: hidden; /* Prevent rendering artifacts */
}

.loading-pulse {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--primary);
    position: relative;
    animation: pulse 1.5s ease infinite;
}

.loading-pulse::before,
.loading-pulse::after {
    content: '';
    position: absolute;
    width: 4px;
    height: 4px;
    background: white;
    border-radius: 50%;
}

.loading-pulse::before {
    animation: orbit1 2s linear infinite;
}

.loading-pulse::after {
    animation: orbit2 2.5s linear infinite;
}

.inline-loading-indicator span {
    font-size: 15px;
    font-weight: 400;
}

@keyframes pulse {

    0%,
    100% {
        transform: scale(0.9);
        background-color: var(--primary);
    }

    50% {
        transform: scale(1.1);
        background-color: #7D4CE2;
    }
}

@keyframes orbit1 {
    0% {
        transform: rotate(0deg) translateX(15px);
    }

    100% {
        transform: rotate(360deg) translateX(15px);
    }
}

@keyframes orbit2 {
    0% {
        transform: rotate(0deg) translateX(10px) rotate(0deg);
    }

    100% {
        transform: rotate(-360deg) translateX(10px) rotate(360deg);
    }
}

/* Button container to consistently hold space */
.button-container {
    width: 48px;
    height: 48px;
    position: relative;
    flex-shrink: 0;
}

/* Empty container for when neither button is showing */
.empty-btn-container {
    width: 48px;
    height: 48px;
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

/* Transitions for the main fade - Fix specificity for loading indicator */
.inline-loading-indicator.fade-enter-active,
.inline-loading-indicator.fade-leave-active {
    transition: opacity 0.4s ease-out, transform 0.3s ease-out;
    transform-origin: center center;
}

.inline-loading-indicator.fade-enter-from,
.inline-loading-indicator.fade-leave-to {
    opacity: 0;
    transform: translate(-50%, -50%) scale(0.95);
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
    }

    .search-container {
        max-width: 100%;
    }

    .search-container.moved {
        top: calc(100vh - 140px);
    }

    .main-title {
        font-size: 28px;
    }

    .results-area {
        margin-top: 80px;
    }

    .inline-loading-indicator {
        padding: 16px 20px;
        min-width: 220px;
        gap: 14px;
    }

    .loading-pulse {
        width: 18px;
        height: 18px;
    }

    .inline-loading-indicator span {
        font-size: 14px;
    }
}

@media (max-width: 480px) {
    .search-container.moved {
        top: calc(100vh - 120px);
    }

    .main-title {
        font-size: 24px;
    }

    .inline-loading-indicator {
        padding: 12px 16px;
        min-width: 200px;
        border-radius: 14px;
    }

    .loading-pulse {
        width: 16px;
        height: 16px;
    }

    .inline-loading-indicator span {
        font-size: 13px;
    }
}

/* Error Alert Styling */
.error-alert-container {
    max-width: var(--max-width);
    width: calc(100% - 40px);
    margin: 20px auto;
    position: relative;
    z-index: 35;
}

.error-alert {
    border-radius: 12px !important;
    box-shadow: 0 4px 16px rgba(244, 67, 54, 0.2) !important;
}

.error-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.error-title {
    font-size: 16px;
    font-weight: 600;
    color: #c62828;
}

.error-message {
    font-size: 14px;
    line-height: 1.5;
    color: #424242;
    word-break: break-word;
}

.error-alert {
    background-color: rgba(255, 255, 255, 0.98) !important;
}
</style>
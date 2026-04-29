<template>
    <AppLayout contentClass="chat-content" ref="appLayoutRef">
        <main class="content-area" :class="{ 'has-results': hasResults }">
            <!-- Search Container with Animated Position -->
            <div class="search-container">
                <!-- Hero title -->
                <div class="hero-card" :class="{ hidden: hasResults || isReturningHome }">
                    <div class="title-wrapper">
                        <h1 class="main-title gradient-title">
                            Hey There! I'm Tako 
                        </h1>
                        <p class="main-subtitle">Ask your AI agent anything about your okta tenant.</p>
                    </div>
                </div>

                <!-- Modern integrated search - Plain CSS Card -->
                <div :class="['composer-shell', hasResults ? 'moved' : '']">
                    <div ref="searchWrapperRef" class="search-wrapper">
                        <div class="query-card" :class="{ 'is-focused': isFocused }">
                        
                            <!-- Input row with icons -->
                            <div class="query-input-row">
                                <!-- Left icons (reset/stop) -->
                                <div class="query-icons-left">
                                    <!-- Reset button when has results -->
                                    <button 
                                        v-if="hasResults && !isLoading && !reactLoading" 
                                        class="icon-btn" 
                                        @click="resetInterface"
                                        title="Start over"
                                    >
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M1 4v6h6M23 20v-6h-6"/>
                                            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                                        </svg>
                                    </button>
                                    <!-- Stop button when loading -->
                                    <button 
                                        v-if="isLoading || reactLoading" 
                                        class="icon-btn stop-icon" 
                                        @click="stopProcessing"
                                        title="Stop processing"
                                    >
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                            <rect x="6" y="6" width="12" height="12" rx="2"/>
                                        </svg>
                                    </button>
                                </div>
                                
                                <!-- Native textarea -->
                                <textarea 
                                    ref="searchTextarea"
                                    v-model="userInput"
                                    @keydown="handleKeyDown"
                                    @focus="isFocused = true"
                                    @blur="isFocused = false"
                                    @input="autoResizeTextarea"
                                    placeholder="List all users in ACTIVE status"
                                    class="query-textarea"
                                    rows="1"
                                ></textarea>
                                
                                <!-- Submit button -->
                                <button 
                                    class="send-button"
                                    :disabled="!userInput || !(userInput?.trim?.())"
                                    @click="sendQuery"
                                    title="Send query"
                                    aria-label="Send query"
                                >
                                    <v-icon icon="mdi-arrow-up" size="18" />
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Suggestions -->
                <transition name="fade-up">
                    <div v-if="!hasResults && !isReturningHome" class="suggestions-wrapper">
                        <div class="suggestions-grid">
                            <button 
                                v-for="(suggestion, i) in suggestions" 
                                :key="i" 
                                class="suggestion-btn"
                                @click="selectSuggestion(suggestion.query)"
                            >
                                <span class="suggestion-text">{{ suggestion.query }}</span>
                            </button>
                        </div>
                        
                        <!-- Special Tools Button -->
                        <div class="special-tools-container">
                            <button class="special-tools-btn" @click="showSpecialToolsModal = true">
                                <v-icon icon="mdi-tools" size="18" />
                                <span>Special Tools</span>
                            </button>
                        </div>
                    </div>
                </transition>
            </div>

            <!-- Display User question -->
            <transition name="working-bar">
                <div v-if="hasResults && lastQuestion" class="question-header-container">
                    <div class="question-header">
                        <div class="question-icon">
                            <v-icon style="color: white;">mdi-help-circle</v-icon>
                        </div>
                        <div class="question-text">{{ lastQuestion }}</div>
                        <div class="question-timestamp">{{ getCurrentTime() }}</div>
                    </div>
                </div>
            </transition>

            <!-- Error Alert - 2026 Minimal Style -->
            <transition name="fade-up">
                <div v-if="reactError" class="error-block">
                    <div class="error-icon">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="12" y1="8" x2="12" y2="12"/>
                            <circle cx="12" cy="16" r="0.5" fill="currentColor"/>
                        </svg>
                    </div>
                    <div class="error-content">
                        <span class="error-text">{{ reactError }}</span>
                    </div>
                    <button class="error-dismiss" @click="reactError = null" title="Dismiss">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18"/>
                            <line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
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
                    :class="['results-container', getContentClass(isReActMode ? reactResults?.display_type : currentResponse.type)]" class="mt-8">
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
        
        <!-- Special Tools Modal -->
        <v-dialog v-model="showSpecialToolsModal" max-width="800px">
            <v-card class="special-tools-modal">
                <v-card-title class="modal-header">
                    <div class="modal-title">
                        <v-icon icon="mdi-tools" size="24" class="title-icon" />
                        <span>Special Tools</span>
                    </div>
                    <v-btn icon="mdi-close" variant="text" @click="showSpecialToolsModal = false" />
                </v-card-title>
                
                <v-card-text class="modal-content">
                    <!-- Info Note -->
                    <div class="info-note">
                        <v-icon icon="mdi-information" size="20" style="color: var(--primary)" />
                        <span>These tools will automatically be invoked when your query matches the criteria. You don't need to do anything special.</span>
                    </div>
                    
                    <!-- Loading State -->
                    <div v-if="specialToolsLoading" class="loading-state">
                        <v-progress-circular indeterminate color="primary" />
                        <p>Loading special tools...</p>
                    </div>
                    
                    <!-- Error State -->
                    <div v-else-if="specialToolsError" class="error-state">
                        <v-icon icon="mdi-alert-circle" color="error" size="48" />
                        <p>{{ specialToolsError }}</p>
                    </div>
                    
                    <!-- Tools Grid -->
                    <div v-else-if="specialTools.length > 0" class="tools-grid">
                        <div v-for="(tool, index) in specialTools" 
                             :key="index" 
                             class="tool-card"
                             @click="selectToolExample(tool)">
                            <div class="tool-header">
                                <h3 class="tool-name">{{ tool.name }}</h3>
                            </div>
                            <p class="tool-description">{{ extractSpecialToolText(tool.description) }}</p>
                            <div v-if="tool.examples && tool.examples.length > 0" class="tool-examples">
                                <p class="examples-label">Try asking:</p>
                                <ul class="examples-list">
                                    <li v-for="(example, i) in tool.examples.slice(0, 2)" 
                                        :key="i"
                                        class="example-item">
                                        "{{ example }}"
                                    </li>
                                </ul>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Empty State -->
                    <div v-else class="empty-state">
                        <v-icon icon="mdi-information-outline" size="48" />
                        <p>No special tools available</p>
                    </div>
                </v-card-text>
            </v-card>
        </v-dialog>
    </AppLayout>
</template>

<script setup>
/**
 * Chat Interface Component
 * 
 * Main component for the search and query interface that handles
 * user input, displays results, and manages the overall UI state.
 */

import { ref, watch, nextTick, onMounted, onBeforeUnmount, inject } from 'vue'
import { useFetchStream } from '@/composables/useFetchStream'
import { useSanitize } from '@/composables/useSanitize'
import { useReactStream } from '@/composables/useReactStream'
import { useSpecialTools } from '@/composables/useSpecialTools'
import { useHistory } from '@/composables/useHistory'
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
const searchTextarea = ref(null) // Ref for native textarea
const searchWrapperRef = ref(null) // Ref for the moving composer wrapper
const isLoading = ref(false) // Loading state for API calls
const lastQuestion = ref('') // Stores the last question that was asked
const isFocused = ref(false) // Tracks if the search input is focused
const hasResults = ref(false) // Whether there are results to display
const isReturningHome = ref(false) // Keeps the home shell hidden during reverse motion
const auth = useAuth()
const router = useRouter()

let composerCleanupTimerId = null
let homeRevealTimerId = null

/**
 * Auto-resize textarea to fit content
 */
const autoResizeTextarea = () => {
    const textarea = searchTextarea.value
    if (textarea) {
        textarea.style.height = 'auto'
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'
    }
}

const clearComposerAnimationTimer = () => {
    if (composerCleanupTimerId !== null) {
        window.clearTimeout(composerCleanupTimerId)
        composerCleanupTimerId = null
    }
}

const clearHomeRevealTimer = () => {
    if (homeRevealTimerId !== null) {
        window.clearTimeout(homeRevealTimerId)
        homeRevealTimerId = null
    }
}

const cleanupComposerAnimation = () => {
    const searchWrapper = searchWrapperRef.value
    if (!searchWrapper) {
        return
    }

    searchWrapper.style.removeProperty('transform')
    searchWrapper.style.removeProperty('transition')
    searchWrapper.style.removeProperty('transform-origin')
    searchWrapper.style.removeProperty('will-change')
    searchWrapper.style.removeProperty('opacity')
}

const animateComposerDock = async (beforeRect) => {
    await nextTick()

    const searchWrapper = searchWrapperRef.value
    if (!searchWrapper || !beforeRect) {
        return false
    }

    const afterRect = searchWrapper.getBoundingClientRect()
    const deltaX = beforeRect.left - afterRect.left
    const deltaY = beforeRect.top - afterRect.top
    const scaleX = beforeRect.width / Math.max(afterRect.width, 1)
    const scaleY = beforeRect.height / Math.max(afterRect.height, 1)
    const hasMovement = Math.abs(deltaX) > 1 || Math.abs(deltaY) > 1 || Math.abs(scaleX - 1) > 0.01 || Math.abs(scaleY - 1) > 0.01

    if (!hasMovement) {
        return false
    }

    clearComposerAnimationTimer()

    searchWrapper.style.transformOrigin = 'top left'
    searchWrapper.style.willChange = 'transform, opacity'
    searchWrapper.style.transition = 'none'
    searchWrapper.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(${scaleX}, ${scaleY})`
    searchWrapper.style.opacity = '0.98'
    searchWrapper.getBoundingClientRect()

    requestAnimationFrame(() => {
        searchWrapper.style.transition = 'transform 0.34s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.22s ease'
        searchWrapper.style.transform = 'translate(0, 0) scale(1, 1)'
        searchWrapper.style.opacity = '1'
    })

    composerCleanupTimerId = window.setTimeout(() => {
        cleanupComposerAnimation()
        composerCleanupTimerId = null
    }, 380)

    return true
}

const animateComposerReturnHome = async (beforeRect) => {
    const didAnimate = await animateComposerDock(beforeRect)

    if (!isReturningHome.value) {
        return
    }

    if (!didAnimate) {
        isReturningHome.value = false
        return
    }

    clearHomeRevealTimer()
    homeRevealTimerId = window.setTimeout(() => {
        isReturningHome.value = false
        homeRevealTimerId = null
    }, 360)
}

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
    startScriptExecution,
    connectToStream: connectReActStream,
    cancelProcess: cancelReAct
} = useReactStream()

// Initialize sanitization utilities
const { query: sanitizeQuery, text: sanitizeText } = useSanitize()

// History Management
const { saveToHistory } = useHistory()
const appLayoutRef = ref(null)

// History refresh helper - matches the one provided by AppLayout but accessible here
const refreshHistory = async () => {
    if (appLayoutRef.value?.refreshHistory) {
        await appLayoutRef.value.refreshHistory()
    }
}

// Watch for query completion to refresh history
let lastQuery = null
watch([reactProcessing, reactResults], ([processing, results]) => {
    // Trigger refresh when processing completes AND we have results
    if (!processing && results && lastQuestion.value && lastQuestion.value !== lastQuery) {
        lastQuery = lastQuestion.value
        console.log('[ChatInterface] Query completed, refreshing history for:', lastQuestion.value)
        
        // Retry with exponential backoff to handle variable DB write times
        refreshHistoryWithRetry(lastQuestion.value, 3).catch(err => {
            console.error('Failed to refresh history sidebar after retries:', err)
        })
    }
})

// Special Tools
const { tools: specialTools, loading: specialToolsLoading, error: specialToolsError, fetchTools } = useSpecialTools()
const showSpecialToolsModal = ref(false)

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

onBeforeUnmount(() => {
    clearComposerAnimationTimer()
    clearHomeRevealTimer()
    cleanupComposerAnimation()
})

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
 * Query suggestions - curated valid questions (rearranged for varied lengths)
 */
const suggestions = ref([
    { query: 'Show me all okta admins in the tenant and list their roles', icon: 'mdi-shield-account-outline' },
    { query: 'List all users along with their creation dates', icon: 'mdi-calendar-outline' },
    { query: 'Show me all users in locked status', icon: 'mdi-lock-outline' },
    { query: 'Show users with PUSH factor registered', icon: 'mdi-shield-check-outline' },
    { query: 'Find the SAML certificate expiry date for all the active SAML applications', icon: 'mdi-certificate-outline' },
    { query: 'Show applications assigned to user dan@fctr.io', icon: 'mdi-apps' },
    { query: 'Find all users in Engineering group', icon: 'mdi-account-group-outline' },
    { query: 'Find groups with more than 50 members', icon: 'mdi-account-multiple-outline' },
    { query: 'Can john.smith@company.com access Salesforce?', icon: 'mdi-help-circle-outline' }
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
 * Resets the interface to its initial state
 */
const resetInterface = () => {
    const shouldAnimateHome = hasResults.value
    const composerRect = shouldAnimateHome ? searchWrapperRef.value?.getBoundingClientRect() ?? null : null

    clearHomeRevealTimer()
    if (shouldAnimateHome) {
        isReturningHome.value = true
    }

    clearComposerAnimationTimer()
    cleanupComposerAnimation()
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

    if (shouldAnimateHome) {
        void animateComposerReturnHome(composerRect)
    } else {
        isReturningHome.value = false
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
 * Handles clicking on a special tool card
 * Populates the first example query into the search field
 * @param {Object} tool - The selected tool object
 */
const selectToolExample = (tool) => {
    if (tool.examples && tool.examples.length > 0) {
        // Use the first example
        userInput.value = sanitizeQuery(tool.examples[0])
        showSpecialToolsModal.value = false
        
        // Focus input field
        nextTick(() => {
            if (searchTextarea.value) {
                searchTextarea.value.focus()
            }
        })
    }
}

/**
 * Extracts text after "SPECIAL TOOL:" from description
 * @param {String} description - The full description text
 * @returns {String} Text after SPECIAL TOOL: or original description
 */
const extractSpecialToolText = (description) => {
    const match = description.match(/SPECIAL TOOL:\s*(.+)/s)
    return match ? match[1].trim() : description
}

/**
 * Retry history refresh with exponential backoff until query appears
 * @param {String} queryText - The query to check for
 * @param {Number} maxRetries - Maximum number of retry attempts
 */
const refreshHistoryWithRetry = async (queryText, maxRetries = 3) => {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
        // Exponential backoff: 100ms, 200ms, 400ms
        const delay = 100 * Math.pow(2, attempt)
        await new Promise(resolve => setTimeout(resolve, delay))
        
        console.log(`[History Refresh] Attempt ${attempt + 1}/${maxRetries} after ${delay}ms`)
        
        try {
            await refreshHistory()
            // If refresh succeeds without error, assume history was updated and stop retrying
            console.log(`[History Refresh] ✓ Refresh successful, stopping retries`)
            return
        } catch (err) {
            console.warn(`[History Refresh] Attempt ${attempt + 1} failed:`, err)
            // Only retry if we haven't exhausted all attempts
            if (attempt === maxRetries - 1) {
                console.error(`[History Refresh] All ${maxRetries} attempts failed`)
            }
        }
    }
}

/**
 * Submits the query to the backend API
 */
const sendQuery = async () => {
    if (!userInput.value.trim() || isLoading.value) return

    // Apply full sanitization before sending query
    const rawQuery = userInput.value.trim()
    const sanitizedQuery = sanitizeQuery(rawQuery, { maxLength: 2000 })
    const shouldAnimateDock = !hasResults.value
    const composerRect = shouldAnimateDock ? searchWrapperRef.value?.getBoundingClientRect() ?? null : null

    clearHomeRevealTimer()
    isReturningHome.value = false

    lastQuestion.value = sanitizedQuery
    isLoading.value = true
    hasResults.value = true
    userInput.value = ''

    if (shouldAnimateDock) {
        void animateComposerDock(composerRect)
    }

    // Store sanitized query in history
    updateMessageHistory(sanitizedQuery)

    try {
        if (isReActMode.value) {
            // Use ReAct flow
            const pid = await startReActProcess(sanitizedQuery)
            if (pid) {
                await connectReActStream(pid)
                // History refresh will be triggered by watch on reactLoading
            }
            isLoading.value = false
            return
        }

        // Tako flow (existing)
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
onMounted(async () => {
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
        
        isReActMode.value = modeParam !== 'realtime' && (modeParam === 'react' || savedMode !== 'realtime')
        
        // Save mode preference
        if (modeParam) {
            localStorage.setItem('agentMode', modeParam)
        }
        
        // Fetch special tools on mount
        await fetchTools()

        // History Event Listeners
        window.addEventListener('tako:select-history', (e) => {
            userInput.value = e.detail.query_text
            nextTick(autoResizeTextarea)
        })

        window.addEventListener('tako:execute-history', async (e) => {
            const item = e.detail
            const shouldAnimateDock = !hasResults.value
            const composerRect = shouldAnimateDock ? searchWrapperRef.value?.getBoundingClientRect() ?? null : null

            clearHomeRevealTimer()
            isReturningHome.value = false

            lastQuestion.value = item.query_text
            isLoading.value = true
            hasResults.value = true

            if (shouldAnimateDock) {
                void animateComposerDock(composerRect)
            }
            
            try {
                const pid = await startScriptExecution(item.query_text, item.final_script)
                if (pid) {
                    await connectReActStream(pid)
                    
                    // Retry history refresh with exponential backoff
                    try {
                        await refreshHistoryWithRetry(item.query_text, 3)
                    } catch (err) {
                        console.error('Failed to refresh history sidebar after retries:', err)
                        // Non-critical - don't block user workflow
                    }
                }
            } finally {
                isLoading.value = false
            }
        })
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
    // Force layout recalculation on smaller screens
    if (window.innerHeight <= 800) {
        document.querySelector('.chat-content')?.classList.add('small-screen')
    }

    // Auto-focus the textarea on load
    nextTick(() => {
        if (searchTextarea.value) {
            searchTextarea.value.focus()
        }
    })
})
</script>

<style scoped>
/* Search container */
.chat-content {
    background: transparent;
    display: flex;
    flex-direction: column;
    flex: 1;
}

.content-area {
    width: 100%;
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 0;
    transition: padding 0.3s ease;
    position: relative;
    min-height: 0;
    box-sizing: border-box;
}

/* Initially center the search container vertically and horizontally */
.content-area:not(.has-results) {
    justify-content: center;
    align-items: center;
    padding-bottom: 42px;
    padding-top: 0;
}

.search-container {
    width: 100%;
    max-width: 1080px;
    padding: 0 24px 32px;
    transition: opacity 0.28s ease;
    z-index: 50;
    margin: 0 auto;
}

.composer-shell {
    width: 100%;
}

/* When results appear, fix search bar to bottom with space for footer */
.composer-shell.moved {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    width: 760px;
    max-width: calc(100vw - 360px);
    padding-bottom: 0;
    z-index: 90;
    margin: 0;
}

/* Adjust horizontal position when sidebar is expanded */
.sidebar-expanded .composer-shell.moved {
    left: calc(50% + 140px);
}

/* Hide placeholder when in mini mode */
.composer-shell.moved .query-textarea::placeholder {
    opacity: 0;
}

/* Compact style when moved - Clean white bar */
.composer-shell.moved .query-card {
    padding: 10px 12px;
    border-radius: 10px;
    background: #ffffff;
    box-shadow: none;
}

.composer-shell.moved .query-card::before {
    border-radius: 10px;
}

.composer-shell.moved .query-label {
    display: none;
}

.composer-shell.moved .query-input-row {
    flex-direction: row;
    align-items: center;
    gap: 12px;
}

.composer-shell.moved .query-icons-left {
    display: flex;
    align-items: center;
    flex-shrink: 0;
}

.composer-shell.moved .query-textarea {
    min-height: 32px;
    max-height: 120px;
    font-size: 15px;
    flex: 1;
    background: transparent;
    border-radius: 0;
    padding: 6px 0;
}

.composer-shell.moved .send-button {
    margin-top: 0;
    width: 38px;
    height: 38px;
    padding: 0;
    border-radius: 8px;
    flex-shrink: 0;
    background: var(--primary);
    color: white;
}

.composer-shell.moved .icon-btn {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: #f3f4f6;
}

.composer-shell.moved .icon-btn:hover {
    background: #e5e7eb;
}

.composer-shell.moved .icon-btn.stop-icon {
    background: rgba(239, 68, 68, 0.1);
    color: #ef4444;
    animation: pulse-stop 1.5s ease-in-out infinite;
}

.composer-shell.moved .icon-btn.stop-icon:hover {
    background: rgba(239, 68, 68, 0.15);
}

@keyframes pulse-stop {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

.composer-shell.moved .send-button {
    width: 38px;
    height: 38px;
    padding: 0;
    border-radius: 8px;
}

/* Title with animated underline */

.hero-card {
    max-width: 760px;
    margin: 0 auto 18px;
    max-height: 140px;
    overflow: hidden;
    padding: 0;
    border-radius: 0;
    background: transparent;
    border: none;
    box-shadow: none;
    transition: opacity 0.35s ease, transform 0.35s ease, max-height 0.35s ease, margin 0.35s ease;
}

.hero-card.hidden {
    opacity: 0;
    transform: translateY(-16px);
    max-height: 0;
    margin-bottom: 0;
    pointer-events: none;
}

.title-wrapper {
    margin: 0;
    text-align: center;
}

.main-title {
    font-family: var(--font-family-display);
    font-size: 36px;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--text-primary);
    position: relative;
    letter-spacing: 0;
    line-height: 1.12;
}

.main-title.gradient-title {
    background: none;
    color: var(--text-primary);
}

.main-subtitle {
    font-family: var(--font-family-body);
    font-size: 14px;
    font-weight: 450;
    color: var(--text-secondary);
    margin: 0 auto;
    max-width: 520px;
    line-height: 1.5;
    letter-spacing: 0;
}

.content-area.has-results {
    padding-top: 60px;
    padding-bottom: 60px;
}

/* Modern integrated search - Plain CSS Card */
.search-wrapper {
    width: 100%;
    max-width: 760px;
    margin: 0 auto;
}

.query-card {
    position: relative;
    background: white;
    border-radius: 10px;
    box-shadow: none;
    padding: 14px;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
    border: 2px solid rgba(15, 23, 42, 0.28);
    display: flex;
    flex-direction: column;
}

.query-card:hover {
    border-color: rgba(15, 23, 42, 0.42);
    box-shadow: none;
}

.query-card.is-focused {
    box-shadow: 0 0 0 4px rgba(var(--primary-rgb), 0.14);
    border-color: rgba(var(--primary-rgb), 0.62);
}

.query-label {
    display: none;
}

.query-input-row {
    display: flex;
    align-items: flex-end;
    width: 100%;
    gap: 12px;
}

.query-icons-left {
    display: none;
}

.query-textarea {
    width: 100%;
    border: none;
    outline: none;
    resize: none;
    font-family: inherit;
    font-size: 15px;
    font-weight: 400;
    line-height: 1.5;
    color: var(--text-primary);
    background: transparent;
    min-height: 42px;
    max-height: 150px;
    overflow-y: auto;
    padding: 8px 2px;
    flex: 1;
}

.query-textarea::placeholder {
    color: var(--text-muted);
}

.icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    background: #fafafa;
    border-radius: 10px;
    cursor: pointer;
    color: #9ca3af;
    transition: all 0.15s ease;
}

.icon-btn:hover {
    background: #f3f4f6;
    color: #6b7280;
}

.icon-btn.stop-icon {
    color: var(--primary);
    background: rgba(var(--primary-rgb), 0.08);
}

.icon-btn.stop-icon:hover {
    background: rgba(var(--primary-rgb), 0.12);
}

.send-button {
    align-self: flex-end;
    width: 40px;
    height: 40px;
    padding: 0;
    border: none;
    border-radius: 8px;
    background: var(--primary);
    color: white;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.15s ease;
    flex-shrink: 0;
}

.send-button:hover:not(:disabled) {
    background: var(--primary-hover);
    transform: translateY(-1px);
}

.send-button:disabled {
    background: var(--surface-muted);
    color: var(--text-faint);
    cursor: not-allowed;
}

:deep(.v-tooltip .v-overlay__content) {
    background-color: var(--primary-dark);
    color: white;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 4px;
    opacity: 0.95;
    box-shadow: none;
}

/* Modern 2026 Suggestion Cards - Clean minimal style */
.suggestions-wrapper {
    margin-top: 14px;
    padding: 0;
    width: 100%;
    max-width: 1040px;
    position: relative;
    opacity: 1;
    background: transparent;
    border: none;
    border-radius: 0;
    box-shadow: none;
    transition: opacity 0.4s ease;
}

.suggestions-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
    width: 100%;
    max-width: 1040px;
    margin: 0 auto;
}

.suggestion-btn {
    position: relative;
    padding: 8px 12px;
    width: auto;
    max-width: 100%;
    display: inline-flex;
    margin: 0;
    background: #ffffff;
    border: 1px solid var(--border-color);
    box-shadow: none;
    border-radius: 10px;
    cursor: pointer;
    text-align: left;
    flex-direction: row;
    align-items: center;
    gap: 0;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.suggestion-btn::before {
    display: none;
}

.suggestion-btn:hover {
    background: #ffffff;
    border-color: var(--border-strong);
    box-shadow: none;
    transform: translateY(-1px);
}

.suggestion-btn:hover::before {
    opacity: 0.35;
}

.suggestion-btn:focus-visible {
    outline: 2px solid rgba(var(--primary-rgb), 0.35);
    outline-offset: 2px;
}

.suggestion-text {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    line-height: 1.4;
}

.suggestion-header {
    display: flex;
    align-items: center;
    gap: 6px;
}

.suggestion-icon {
    display: none;
}

.suggestion-icon :deep(.v-icon) {
    display: none;
}

/* Remove glow effect */
.suggestion-btn::after {
    display: none;
}

.suggestion-btn:hover .suggestion-icon {
    display: none;
}

.suggestion-btn:hover .suggestion-icon :deep(.v-icon) {
    display: none;
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
    box-shadow: none;
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
    box-shadow: none;
    background: white;
    border: 1px solid var(--border-color);
    overflow: hidden;
    width: 100%;
}

.compact-results {
    width: 100%;
    max-width: 900px;
    margin-left: auto;
    margin-right: auto;
    background: transparent;
    box-shadow: none;
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

.fade-up-enter-active,
.fade-up-leave-active {
    transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}

.fade-up-enter-from,
.fade-up-leave-to {
    opacity: 0;
    transform: translateY(20px);
}

.working-bar-enter-active,
.working-bar-leave-active {
    transition: opacity 0.24s ease, transform 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

.working-bar-enter-from,
.working-bar-leave-to {
    opacity: 0;
    transform: translateY(10px) scale(0.985);
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

    .composer-shell.moved {
        bottom: 16px;
    }

    .composer-shell.moved .send-button {
        padding: 8px 16px;
    }

    .main-title {
        font-size: 28px;
    }

    .results-area {
        margin-top: 80px;
    }
}

@media (max-width: 480px) {
    .composer-shell.moved {
        bottom: 12px;
    }

    .composer-shell.moved .query-card {
        padding: 10px 12px;
    }

    .composer-shell.moved .send-button {
        padding: 8px 12px;
        font-size: 12px;
    }

    .main-title {
        font-size: 24px;
    }
}

/* Error Block - Warm Solid Style */
.error-block {
    max-width: 900px;
    width: calc(100% - 40px);
    margin: 60px auto 20px;
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 10px;
    position: relative;
    z-index: 35;
}

.error-icon {
    flex-shrink: 0;
    color: #f87171;
    display: flex;
    align-items: center;
    line-height: 0;
    margin-top: -2px;
}

.error-content {
    flex: 1;
    display: flex;
    align-items: center;
}

.error-text {
    font-size: 13px;
    color: #b91c1c;
    font-weight: 450;
    line-height: 1.5;
}

.error-dismiss {
    flex-shrink: 0;
    padding: 5px;
    background: transparent;
    border: none;
    cursor: pointer;
    color: #f87171;
    transition: all 0.15s;
    border-radius: 6px;
}

.error-dismiss:hover {
    background: rgba(248, 113, 113, 0.1);
    color: #dc2626;
}

/* Special Tools Button */
.special-tools-container {
    margin-top: 16px;
    display: flex;
    justify-content: center;
}

.special-tools-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 8px 12px;
    background: #ffffff;
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
    box-shadow: none;
}

.special-tools-btn:hover {
    background: var(--surface-muted);
    border-color: var(--border-strong);
    color: var(--text-primary);
    transform: translateY(-1px);
    box-shadow: none;
}

.special-tools-btn:active {
    transform: translateY(0);
}

.special-tools-btn .sparkle-icon {
    opacity: 0.9;
}

/* Special Tools Modal */
.special-tools-modal {
    border-radius: 16px;
    overflow: hidden;
    box-shadow: none;
    border: 1px solid var(--border-strong);
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
}

.modal-title {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 2#ffffff;
    border-bottom: 1px solid #e5e7eb;
}

.modal-title {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 20px;
    font-weight: 700;
    color: #1a1a1a;
}

.title-icon {
    color: var(--primary);
}

.modal-content {
    padding: 16px;
    max-height: 600px;
    overflow-y: auto;
}

/* Loading/Error/Empty States */
.loading-state, .error-state, .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    min-height: 300px;
    color: #6b7280;
}

.loading-state p, .error-state p, .empty-state p {
    font-size: 14px;
    margin: 0;
}

/* Info Note */
.info-note {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: var(--primary-light);
    border: 1px solid rgba(var(--primary-rgb), 0.18);
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 13px;
    color: var(--primary-dark);
    line-height: 1.5;
}

/* Tools List - Row Layout */
.tools-grid {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.tool-card {
    padding: 20px;
    background: #ffffff;
    border: 2px solid #d1d5db;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s ease;
}

.tool-card:hover {
    border-color: var(--primary);
    background: #f8fbff;
    transform: translateX(4px);
}

.tool-header {
    margin-bottom: 8px;
}

.tool-name {
    font-size: 14px;
    font-weight: 600;
    color: #1a1a1a;
    margin: 0;
}

.tool-description {
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
    margin: 0;
}

.tool-examples {
    display: none;
}

.examples-label {
    display: none;
}

.examples-list {
    display: none;
}

.example-item {
    display: none;
}
</style>
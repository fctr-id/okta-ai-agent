<template>
    <div class="chat-interface">
        <!-- Modern floating header -->
        <header class="floating-header">
            <div class="header-content">
                <div class="brand">
                    <img src="@/assets/fctr-logo.png" alt="Okta Logo" height="24" />
                    <div class="brand-divider"></div>
                    <div class="title-with-badge">
                        <span>AI Agent for Okta</span>
                        <div class="beta-badge">BETA</div>
                    </div>
                </div>
                <button class="logout-btn" aria-label="Logout" @click="handleLogout">
                    <v-icon>mdi-logout</v-icon>
                </button>
            </div>
        </header>

        <main class="content-area mt-10" :class="{ 'has-results': hasResults }">
            <!-- Search Container with Animated Position -->
            <div :class="['search-container', hasResults ? 'moved' : '']">
                <!-- Title with animated gradient underline -->
                <div :class="['title-wrapper', hasResults ? 'hidden' : '']">
                    <h1 class="main-title">How can I help you?</h1>
                    <div class="title-underline"></div>
                </div>

                <!-- Modern integrated search -->
                <div class="search-wrapper">
                    <div class="integrated-search-bar">
                        <!-- Reset button (only when results are showing) -->
                        <transition name="fade">
                            <button v-if="hasResults" class="action-btn reset-btn" @click="resetInterface"
                                aria-label="Reset search">
                                <v-icon>mdi-refresh</v-icon>
                            </button>
                        </transition>

                        <!-- Search input with dynamic placeholder -->
                        <v-text-field v-model="userInput" @keydown="handleKeyDown" autofocus refs="searchInput"
                            @update:model-value="handleUserInputChange" :focused="isFocused" @focus="isFocused = true"
                            @blur="isFocused = false"
                            :placeholder="hasResults ? 'Ask anything about your Okta tenant...' : 'Ask anything about your Okta tenant...'"
                            variant="plain" color="#4C64E2" bg-color="transparent" hide-details class="search-input"
                            :clearable="true" />

                        <!-- Send button -->
                        <button class="action-btn send-btn" :disabled="!userInput || !(userInput?.trim?.())"
                            @click="sendQuery" aria-label="Send query">
                            <v-icon>mdi-send</v-icon>
                        </button>
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
                            <!-- Show more button removed -->
                        </div>
                    </div>
                </transition>
            </div>

            <!-- Display User question-->
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

            <!-- Results Area with Smooth Transitions -->
            <transition name="fade-up">
                <div v-if="hasResults && !isLoading"
                    :class="['results-container', getContentClass(currentResponse.type)]" class="mt-8">
                    <DataDisplay :type="currentResponse.type" :content="currentResponse.content"
                        :metadata="currentResponse.metadata" />
                </div>
            </transition>

            <!-- Modern footer credit -->
            <footer class="page-footer">
                <div class="footer-content">
                    <span>Powered by </span>
                    <a href="https://fctr.io" target="_blank" class="branded-link">
                        Fctr Identity
                    </a>
                    <span class="disclaimer">• Responses may require verification</span>
                </div>
            </footer>
        </main>

        <!-- Loading overlay -->
        <transition name="fade">
            <div v-if="isLoading" class="inline-loading-indicator">
                <div class="loading-pulse"></div>
                <span>Processing your query...</span>
            </div>
        </transition>
    </div>
</template>



<script setup>
/**
 * Chat Interface Component
 * 
 * Main component for the search and query interface that handles
 * user input, displays results, and manages the overall UI state.
 */
import { ref, watch, nextTick, onMounted } from 'vue'
import { useFetchStream } from '@/composables/useFetchStream'
import DataDisplay from '@/components/messages/DataDisplay.vue'
import { MessageType } from '@/components/messages/messageTypes'
import { useAuth } from '@/composables/useAuth'
import { useRouter } from 'vue-router'

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
 * Get the current time formatted as HH:MM
 * @returns {string} Formatted time string
 */
const getCurrentTime = () => {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Ensures userInput is always a string
 * @param {*} val - The new input value
 */
const handleUserInputChange = (val) => {
    userInput.value = val === null ? '' : val
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

/* Code to handle logout */
const handleLogout = async () => {
  await auth.logout()
  router.push('/login')
}
// ---------- PREDEFINED CONTENT ----------

/**
 * Query suggestions for users
 */
const suggestions = ref([
    'List all my users along with their creation dates',
    'Show users with PUSH factor registered',
    'Find users withs SMS  registered with phone number ending with 2364',
    'How many users were created last month?',
    'List all users assigned to the \'monday\' app',
    'Find all users reporting to \'noah.williams\' and get me their emails only ',
    'List all users along with their registered factors',
    'show me all users who are in locked status'
])

// Deprecated - no longer needed with new suggestion implementation
// const showMoreSuggestions = ref(false)

// ---------- API INTERACTION ----------

/**
 * Stream API utilities
 */
const { postStream } = useFetchStream()

// ---------- EVENT HANDLERS ----------

/**
 * Handles keyboard input to trigger query submission
 * @param {KeyboardEvent} e - Keyboard event
 */
// Add this function to handle keyboard navigation
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
            userInput.value = messageHistory.value[historyIndex.value]
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (historyIndex.value > -1) {
            historyIndex.value--
            userInput.value = historyIndex.value === -1 ? '' : messageHistory.value[historyIndex.value]
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
    userInput.value = query
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
    // No longer needed:
    // showMoreSuggestions.value = false
}

/**
 * Handles suggestion selection
 * @param {string} suggestion - The selected suggestion
 */
const selectSuggestion = (suggestion) => {
    userInput.value = suggestion;

    // Focus the input field after populating
    nextTick(() => {
        const inputElement = document.querySelector('.search-input input');
        if (inputElement) {
            inputElement.focus();
        }
    });

    // Don't send query automatically - let user edit if desired
}

/**
 * Submits the query to the backend API
 */
const sendQuery = async () => {
    if (!userInput.value.trim() || isLoading.value) return

    const query = userInput.value.trim()
    lastQuestion.value = query
    isLoading.value = true
    hasResults.value = true
    userInput.value = ''

    updateMessageHistory(query)

    try {
        const streamResponse = await postStream('/api/query', { query })
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
                    //console.log("Metadata received:", data.content); // Add this line
                    //console.log("Last sync value:", data.content?.last_sync); // Add this line
                    currentResponse.value = {
                        type: MessageType.STREAM, // Important: Use STREAM type
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

                case 'error':
                    currentResponse.value = {
                        type: MessageType.ERROR,
                        content: data.content || 'An error occurred',
                        metadata: {}
                    }
                    break
            }
        }
    } catch (error) {
        currentResponse.value = {
            type: MessageType.ERROR,
            content: error.message || 'Unknown error occurred',
            metadata: {}
        }
    } finally {
        isLoading.value = false
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
            messageHistory.value = JSON.parse(savedHistory)
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
        const existingIndex = messageHistory.value.indexOf(query)

        if (existingIndex === -1) {
            // New message - add to front of history
            messageHistory.value = [query, ...messageHistory.value.slice(0, CONFIG.MAX_HISTORY - 1)]
        } else {
            // Existing message - move to front of history
            messageHistory.value = [
                query,
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
    document.querySelector('.chat-interface')?.classList.add('small-screen')
  }
})
</script>

<style scoped>
/* Create an extended background effect */

body, html {
  height: auto !important;
  min-height: 100% !important;
  overflow-y: auto !important;
  position: relative !important;
}

/* Fixed chat interface base layout */
.chat-interface {
  min-height: 100vh;
  /* Remove any height restrictions */
  height: auto !important;
  overflow-y: visible !important;
  overflow-x: hidden;
  display: block !important; /* Important change - use block instead of flex */
  position: relative !important;
  background: linear-gradient(180deg, #fafbff 0%, #f8f9ff 100%);
}

/* Add a full-width header background */
.chat-interface::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 100px;
    /* Adjust based on header height + desired extension */
    background: linear-gradient(to bottom,
            rgba(76, 100, 226, 0.03) 0%,
            rgba(76, 100, 226, 0.01) 70%,
            transparent 100%);
    z-index: 1;
}

/* Cleaner, more modern header design */

/* Update header-content style */
.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: white;
    backdrop-filter: blur(15px);
    border-radius: 16px;
    padding: 16px 24px;
    box-shadow: 0 2px 20px rgba(76, 100, 226, 0.08),
        0 1px 8px rgba(76, 100, 226, 0.05);
    position: relative;
    border: none;
    /* Remove border for cleaner look */
    z-index: 2;
}

/* Create subtle blue spill effect */
.floating-header::after {
    content: '';
    position: absolute;
    bottom: -25px;
    left: 5%;
    right: 5%;
    height: 25px;
    background: radial-gradient(ellipse at center,
            rgba(76, 100, 226, 0.25) 0%,
            rgba(76, 100, 226, 0.1) 50%,
            rgba(76, 100, 226, 0) 85%);
    filter: blur(12px);
    z-index: 1;
    pointer-events: none;
}

/* Floating header positioning */
.floating-header {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 100;
    width: calc(100% - 40px);
    max-width: 1280px;
    position: relative;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 500;
    color: #2c3e50;
}

.title-with-badge {
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand-divider {
    height: 20px;
    width: 1px;
    background: #e0e0e0;
}

.beta-badge {
    background: #F0F3FF;
    color: #4C64E2;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 6px;
    letter-spacing: 0.5px;
}

.logout-btn {
    background: transparent;
    border: none;
    color: #777;
    cursor: pointer;
    padding: 8px;
    border-radius: 8px;
    transition: all 0.2s ease;
}

.logout-btn:hover {
    background: #f5f5f5;
    color: #333;
}

/* Main content area */
.content-area {
    width: calc(100% - 40px) !important;
    /* Match header's width calculation exactly */
    max-width: 1280px !important;
    margin: 0 auto;
    padding: 0;
    /* Remove padding from container */
    transition: all 0.3s ease;
}

.content-area.has-results {
    padding-top: 60px;
    /* Add top padding to clear the header */
    padding-bottom: 60px;
}

/* Search container - moved higher */
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
    background: linear-gradient(90deg, #4C64E2, #6373E5);
    border-radius: 2px;
    display: none;
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
    border: 1px solid #4C64E2;
    /* Always show blue border */
}

.integrated-search-bar:has(.v-field--focused) {
    box-shadow: 0 8px 28px rgba(76, 100, 226, 0.15);
    transform: translateY(-2px);
    border: 1.5px solid #4C64E2;
    /* Make it slightly bolder when focused */
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
    margin-right: 4px;
}

.reset-btn:hover {
    color: #666;
    background: #f5f5f5;
}

.send-btn {
    color: white;
    background: #4C64E2;
    margin-left: 4px;
}

.send-btn:hover:not(:disabled) {
    background: #3b4fd9;
    transform: translateY(-1px);
}

.send-btn:disabled {
    background: #e0e0e0;
    color: #999;
    cursor: not-allowed;
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
    border-radius: 16px !important;
    transition: all 0.2s ease;
    color: #333 !important;
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
    border-radius: 16px;
    padding: 1.5px;
    background: linear-gradient(90deg,
            #4C64E2,
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

.show-more-btn {
    color: #4C64E2 !important;
    font-weight: 500 !important;
    height: 32px !important;
    font-size: 13px !important;
    text-transform: none !important;
}

/* Centered question header with blue background */
.question-header-container {
    max-width: 1280px;
    width: calc(100% - 40px);
    margin: 24px auto 20px;
    display: flex;
    justify-content: center;
    position: relative;
}

.question-header {
    background-color: #4C64E2; /* Blue background from original user message */
    color: white; /* White text for contrast */
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
    box-shadow: 0 4px 16px rgba(76, 100, 226, 0.2); /* Enhanced shadow for blue background */
}

.question-icon {
    display: flex;
    align-items: center;
    justify-content: center;
}

.question-icon :deep(.v-icon) {
    color: white !important; /* Force white icon */
}

.question-text {
    font-weight: 500;
    color: white; /* Ensure text is white */
}

.question-timestamp {
    font-size: 12px;
    opacity: 0.8;
    color: rgba(255, 255, 255, 0.9); /* Semi-transparent white */
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

/* Results area */
.results-area {
    border-radius: 16px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
    background: white;
    overflow: hidden;
    margin-top: 16px;
    width: 100%;
    padding: 0;
}

.results-container {
  max-width: 1280px;
  width: calc(100% - 40px);
  margin-left: auto !important; 
  margin-right: auto !important;
  margin-top: 12px;
  margin-bottom: 180px !important; /* Increased from 80px to 180px */
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow: visible !important;
}


.full-width-results {
    border-radius: 16px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
    background: white;
    overflow: hidden;
    width: 100%;
}

.compact-results {
    width: fit-content;
    max-width: 1280px;
    margin-left: 0;
    margin-right: auto;
    background: transparent;
    box-shadow: none;
}


/* Result sections for multi-part results */
.result-section {
    margin-bottom: 20px;
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 14px rgba(76, 100, 226, 0.05);
}

.section-title {
    font-size: 16px;
    font-weight: 500;
    color: #374151;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #eef1ff;
}

/* Footer */
.page-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px 0;
  text-align: center;
  font-size: 13px;
  color: #5d6b8a;
  background: white;
  box-shadow: 0 -2px 10px rgba(0,0,0,0.03);
  z-index: 50;
}


.footer-content {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
}

.branded-link {
    color: #4C64E2;
    text-decoration: none;
    font-weight: 500;
}

.disclaimer {
    color: #7d8bb2;
    margin-left: 4px;
}

/* Loading redesign */
.loading-overlay {
    position: fixed;
    inset: 0;
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}



/* Enhanced loading indicator */
.inline-loading-indicator {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: white;
    border-radius: 18px;  /* Reduced from 24px */
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15),
                0 6px 12px rgba(76, 100, 226, 0.08);
    padding: 18px 24px;   /* Reduced from 28px 40px */
    display: flex;
    align-items: center;
    gap: 16px;            /* Reduced from 20px */
    z-index: 1000;
    min-width: 240px;     /* Reduced from 320px */
    border: 1px solid rgba(76, 100, 226, 0.1);
}

.loading-pulse {
    width: 20px;          /* Reduced from 28px */
    height: 20px;         /* Reduced from 28px */
    border-radius: 50%;
    background: #4C64E2;
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
    font-size: 15px;      /* Reduced from default */
    font-weight: 400;     /* Lighter weight */
}

@keyframes pulse {

    0%,
    100% {
        transform: scale(0.9);
        background-color: #4C64E2;
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

/* Transitions */
.fade-enter-active,
.fade-leave-active {
    transition: opacity 0.3s ease;
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

/* Responsive styles */
@media (max-width: 1300px) {
    .content-area {
        max-width: 95% !important;
    }

    .floating-header {
        max-width: 95%;
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

    .floating-header {
        width: calc(100% - 20px);
        top: 10px;
    }

    .header-content {
        padding: 10px 16px;
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
        padding: 12px 20px;
    }

    .inline-loading-indicator span {
        font-size: 14px;
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
</style>
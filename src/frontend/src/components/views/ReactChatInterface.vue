<template>
    <AppLayout contentClass="chat-content">
        <main class="content-area mt-10" :class="{ 'has-results': hasResults }">
            <!-- Search Container -->
            <div :class="['search-container', hasResults ? 'moved' : '']">
                <!-- Title -->
                <div :class="['title-wrapper', hasResults ? 'hidden' : '']">
                    <h1 class="main-title">
                        I'm Tako ReAct Agent 🚀
                        <v-chip color="success" size="small" class="ml-2" variant="elevated">
                            REACT MODE
                        </v-chip>
                    </h1>
                    <div class="title-underline"></div>
                </div>

                <!-- Search Bar -->
                <div class="search-wrapper">
                    <div class="integrated-search-bar">
                        <!-- Reset button -->
                        <transition name="fade" mode="out-in">
                            <div v-if="hasResults && !isLoading" class="reset-btn-container" key="reset-btn">
                                <v-tooltip text="Start over" location="top">
                                    <template v-slot:activator="{ props }">
                                        <button v-bind="props" class="action-btn reset-btn" @click="resetInterface">
                                            <v-icon>mdi-refresh</v-icon>
                                        </button>
                                    </template>
                                </v-tooltip>
                            </div>
                        </transition>

                        <!-- Stop button -->
                        <transition name="fade">
                            <div v-if="isLoading" class="stop-btn-container">
                                <v-tooltip text="Stop processing" location="top">
                                    <template v-slot:activator="{ props }">
                                        <button v-bind="props" @click="cancelProcess" class="action-btn stop-btn">
                                            <v-icon size="large" color="#4C64E2">mdi-stop</v-icon>
                                        </button>
                                    </template>
                                </v-tooltip>
                            </div>
                        </transition>

                        <!-- Text Input -->
                        <v-text-field 
                            v-model="userInput" 
                            placeholder="Ask a question about your Okta tenant..."
                            variant="solo" 
                            :disabled="isLoading" 
                            hide-details
                            @keyup.enter="sendQuery"
                            class="search-input"
                        >
                            <template v-slot:append-inner>
                                <v-btn 
                                    icon="mdi-send" 
                                    :disabled="!userInput || !userInput.trim()" 
                                    @click="sendQuery"
                                    color="primary"
                                />
                            </template>
                        </v-text-field>
                    </div>

                    <!-- Suggestions -->
                    <div v-if="!hasResults" class="suggestions-wrapper">
                        <v-btn 
                            v-for="suggestion in suggestions" 
                            :key="suggestion"
                            variant="outlined" 
                            @click="selectSuggestion(suggestion)" 
                            size="small"
                            class="suggestion-btn"
                        >
                            {{ suggestion }}
                        </v-btn>
                    </div>
                </div>

                <!-- Results Area -->
                <transition name="fade">
                    <div v-if="hasResults" class="results-area">
                        <!-- Question Display -->
                        <div class="question-display">
                            <span class="question-text">{{ lastQuestion }}</span>
                            <span class="timestamp">{{ getCurrentTime() }}</span>
                        </div>

                        <!-- ReAct Thinking Steps -->
                        <ReActThinkingSteps 
                            v-if="discoverySteps.length > 0"
                            :steps="discoverySteps"
                            :isRunning="isLoading"
                        />

                        <!-- Error Display -->
                        <div v-if="error" class="error-message">
                            <v-icon color="error">mdi-alert-circle</v-icon>
                            {{ error }}
                        </div>

                        <!-- Results Display -->
                        <DataDisplay 
                            v-if="results"
                            :type="results.display_type || 'table'" 
                            :content="results.content"
                            :metadata="results.metadata || {}"
                        />

                        <!-- Token Usage -->
                        <div v-if="tokenUsage" class="token-usage">
                            <v-icon size="small">mdi-chip</v-icon>
                            Tokens: {{ tokenUsage.total_tokens }} 
                            ({{ tokenUsage.prompt_tokens }} in / {{ tokenUsage.completion_tokens }} out)
                        </div>
                    </div>
                </transition>
            </div>
        </main>

        <!-- Loading overlay -->
        <transition name="fade">
            <div v-if="isLoading" class="inline-loading-indicator">
                <div class="loading-pulse"></div>
                <span>{{ isProcessing ? 'Processing discovery steps...' : 'Starting ReAct agent...' }}</span>
            </div>
        </transition>
    </AppLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useReactStream } from '@/composables/useReactStream'
import DataDisplay from '@/components/messages/DataDisplay.vue'
import ReActThinkingSteps from '@/components/messages/ReActThinkingSteps.vue'
import AppLayout from '@/components/layout/AppLayout.vue'

console.log('🚀 ReactChatInterface LOADED - ReAct Mode Active')

// UI State
const userInput = ref('')
const lastQuestion = ref('')
const hasResults = ref(false)

// ReAct Composable
const {
    isLoading,
    isProcessing,
    error,
    currentStep,
    discoverySteps,
    results,
    tokenUsage,
    startProcess,
    connectToStream,
    cancelProcess: cancelReAct
} = useReactStream()

// Sample suggestions
const suggestions = [
    'List all users along with their creation dates',
    'Show users with PUSH factor registered',
    'Find users with SMS factor',
    'Show applications assigned to user dan@fctr.io'
]

/**
 * Send query to ReAct agent
 */
const sendQuery = async () => {
    if (!userInput.value.trim() || isLoading.value) return

    console.log('🚀 [ReactChat] Sending query:', userInput.value)

    lastQuestion.value = userInput.value.trim()
    hasResults.value = true
    const query = userInput.value
    userInput.value = ''

    try {
        // Start ReAct process
        const pid = await startProcess(query)
        console.log('🚀 [ReactChat] Process started, ID:', pid)
        
        if (pid) {
            // Connect to SSE stream
            await connectToStream(pid)
            console.log('🚀 [ReactChat] Stream connected')
        }
    } catch (err) {
        console.error('🚀 [ReactChat] Error:', err)
    }
}

/**
 * Select a suggestion
 */
const selectSuggestion = (suggestion) => {
    userInput.value = suggestion
    sendQuery()
}

/**
 * Reset interface
 */
const resetInterface = () => {
    userInput.value = ''
    lastQuestion.value = ''
    hasResults.value = false
    error.value = null
    discoverySteps.value = []
    results.value = null
    tokenUsage.value = null
}

/**
 * Cancel current process
 */
const cancelProcess = () => {
    console.log('🚀 [ReactChat] Cancelling process')
    cancelReAct()
}

/**
 * Get current time
 */
const getCurrentTime = () => {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

onMounted(() => {
    console.log('🚀 [ReactChat] Component mounted')
})
</script>

<style scoped>
.chat-content {
    background: transparent;
}

.content-area {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem;
    transition: all 0.3s ease;
}

.search-container {
    width: 100%;
    max-width: 800px;
    transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.search-container.moved {
    margin-top: -10vh;
}

.title-wrapper {
    text-align: center;
    margin-bottom: 2rem;
    transition: opacity 0.3s ease, transform 0.3s ease;
}

.title-wrapper.hidden {
    opacity: 0;
    transform: translateY(-20px);
    pointer-events: none;
}

.main-title {
    font-size: 2.5rem;
    font-weight: 600;
    color: #1a1a1a;
    margin-bottom: 0.5rem;
}

.title-underline {
    height: 4px;
    width: 100px;
    margin: 0 auto;
    background: linear-gradient(90deg, #4C64E2, #00B8D4);
    border-radius: 2px;
}

.search-wrapper {
    width: 100%;
}

.integrated-search-bar {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-bottom: 1.5rem;
}

.action-btn {
    min-width: 48px;
    height: 48px;
    border-radius: 50%;
    border: none;
    background: white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
}

.action-btn:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.search-input {
    flex: 1;
}

.suggestions-wrapper {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
}

.suggestion-btn {
    text-transform: none;
    font-size: 0.875rem;
}

.results-area {
    margin-top: 2rem;
    width: 100%;
}

.question-display {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: #f5f5f5;
    border-radius: 8px;
    margin-bottom: 1.5rem;
}

.question-text {
    font-weight: 500;
    color: #1a1a1a;
}

.timestamp {
    color: #666;
    font-size: 0.875rem;
}

.error-message {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 1rem;
    background: #ffebee;
    border-radius: 8px;
    color: #c62828;
    margin-bottom: 1rem;
}

.token-usage {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 1rem;
    padding: 0.75rem;
    background: #e3f2fd;
    border-radius: 8px;
    font-size: 0.875rem;
    color: #1565c0;
}

.inline-loading-indicator {
    position: fixed;
    bottom: 2rem;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem 2rem;
    background: white;
    border-radius: 50px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
    z-index: 1000;
}

.loading-pulse {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: linear-gradient(90deg, #4C64E2, #00B8D4);
    animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.2); opacity: 0.7; }
}

.fade-enter-active, .fade-leave-active {
    transition: opacity 0.3s ease;
}

.fade-enter-from, .fade-leave-to {
    opacity: 0;
}

.has-results {
    align-items: flex-start;
}
</style>

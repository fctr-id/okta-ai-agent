<template>
    <v-app class="bg-custom">
        <div class="d-flex justify-center">
            <div class="chat-wrapper">
                <!-- Header -->
                <v-toolbar color="white" flat border class="px-4" height="64">
                    <div class="d-flex align-center w-100">
                        <div class="d-flex align-center">
                            <img src="@/assets/fctr-logo.png" alt="Okta Logo" class="toolbar-logo mr-4" height="25" />
                            <span class="text-body-1">AI Agent for Okta</span>
                            <v-chip color="grey-lighten-0" size="small" style="border-radius: 0" class="ml-2">
                                <span class="text-black">BETA</span>
                            </v-chip>
                        </div>
                        <v-spacer />
                        <v-btn variant="text" icon>
                            <v-tooltip activator="parent" location="bottom">
                                <span>Logout</span>
                            </v-tooltip>
                            <v-icon color="#777">mdi-logout</v-icon>
                        </v-btn>
                    </div>
                </v-toolbar>

                <!-- Chat Messages Area -->
                <v-main class="chat-area">
                    <div class="messages-container d-flex flex-column gap-4 py-4 px-4" ref="messagesContainer">
                        <template v-for="(message, index) in messages" :key="index">
                            <!-- User Message -->
                            <div v-if="message.type === 'user'" class="user-message-wrapper">
                                <div class="user-message">
                                    {{ message.content }}
                                </div>
                                <div class="user-info">
                                    <v-icon color="#777" size="large">mdi-account-outline</v-icon>
                                </div>
                            </div>

                            <!-- Bot Response -->
                            <div v-else-if="message.type === 'assistant'" class="bot-message-wrapper">
                                <div class="bot-info">
                                    <v-icon color="#777" size="large">mdi-creation-outline</v-icon>
                                </div>
                                <div class="bot-content">
                                    <div class="bot-message" :class="{ 'error': message.isError }">
                                        <!-- Regular Text Message -->
                                        <div v-if="!message.dataType" class="message-text"
                                            :class="{ 'error-text': message.isError }">
                                            {{ message.content }}
                                        </div>

                                        <!-- Data Display Component for Stream/JSON -->
                                        <DataDisplay v-else :type="message.dataType" :content="message.content"
                                            :metadata="message.metadata" :loading="message.isLoading" />

                                        <!-- Loading Indicator -->
                                        <div v-if="message.isTyping" class="loading-dots">
                                            <span></span>
                                            <span></span>
                                            <span></span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </template>
                    </div>
                </v-main>

                <!-- Input Area -->
                <v-footer color="white" flat class="footer-container">
                    <div class="d-flex flex-column w-100 py-2">
                        <div class="d-flex align-center gap-2">
                            <v-text-field v-model="userInput" placeholder="What do you want to find?" variant="outlined"
                                color="#9DA8F5" hide-details class="chat-input text-grey-darken-2" density="comfortable"
                                @keyup.enter="sendMessage" @keydown="handleKeyDown" />
                            <v-btn icon @click="sendMessage" class="send-button" variant="outlined">
                                <v-icon color="#FFF" size="20">mdi-send-outline</v-icon>
                            </v-btn>
                        </div>

                        <div class="text-caption text-grey-darken-1 mt-2">
                            Powered by
                            <a href="https://fctr.io" target="_blank" class="text-decoration-none"
                                style="color: #4C6EF5">
                                Fctr Identity
                            </a>
                            *(Some reponses may be incorrect. Please verify)
                        </div>
                    </div>
                </v-footer>
            </div>
        </div>
    </v-app>
</template>

<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'
import { useFetchStream } from '@/composables/useFetchStream'
import DataDisplay from './messages/DataDisplay.vue'

// Configuration
const CONFIG = {
    MAX_HISTORY: 5,
    MESSAGE_DELAY: 1000,
}

const userInput = ref('')
const messages = ref([])
const isLoading = ref(false)
const messagesContainer = ref(null)
const messageHistory = ref([])
const historyIndex = ref(-1)

// Input sanitization
const sanitizeInput = (input) => {
    return input.replace(/<[^>]*>/g, '')
}

// Add this utility function for delays
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))

const removeTypingIndicator = () => {
    const index = messages.value.findIndex(m => m.isTyping)
    if (index !== -1) {
        messages.value.splice(index, 1)
    }
}

const addErrorMessage = (error) => {
    removeTypingIndicator()
    messages.value.push({
        type: 'assistant',
        content: error.message || 'Sorry, I encountered an error processing your request.',
        isError: true // Add this flag for styling
    })
}

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

const handleKeyDown = (e) => {
    if (e.key === 'ArrowUp') {
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

const { postStream } = useFetchStream()

const sendMessage = async () => {
    const sanitizedInput = sanitizeInput(userInput.value.trim())

    if (!sanitizedInput || isLoading.value) {
        console.warn('Message sending prevented:', !sanitizedInput ? 'empty input' : 'loading state')
        return
    }

    try {
        userInput.value = ''
        isLoading.value = true

        // Handle message history
        try {
            const isDuplicate = messageHistory.value.includes(sanitizedInput)
            if (!isDuplicate) {
                messageHistory.value = [sanitizedInput, ...messageHistory.value.slice(0, CONFIG.MAX_HISTORY - 1)]
                localStorage.setItem('messageHistory', JSON.stringify(messageHistory.value))
            }
            historyIndex.value = -1
        } catch (historyError) {
            console.error('History management error:', historyError)
        }

        // Add user message
        messages.value.push({
            type: 'user',
            content: sanitizedInput,
        })
        await scrollToBottom()

        // Wait before showing bot response
        await delay(500)

        // Show typing indicator
        messages.value.push({
            type: 'assistant',
            content: '',
            isTyping: true
        })
        await scrollToBottom()

        // Make API call using the composable
        const streamResponse = await postStream('/api/query', { query: sanitizedInput })
        let hasReceivedResponse = false


        try {
            for await (const data of streamResponse.getStream()) {
                if (data.type === 'text') {
                    removeTypingIndicator()
                    messages.value.push({
                        type: 'assistant',
                        dataType: data.type,
                        content: data.content,
                        metadata: data.metadata,
                        isLoading: false
                    })
                    break  // Exit loop for text messages
                } else {
                    // Continue streaming for other types
                    if (!hasReceivedResponse) {
                        removeTypingIndicator()
                        hasReceivedResponse = true
                    }
                    messages.value.push({
                        type: 'assistant',
                        dataType: data.type,
                        content: data.content,
                        metadata: data.metadata,
                        isLoading: false
                    })
                }
                await scrollToBottom()
            }
        } catch (streamError) {
            console.error('Stream processing error:', streamError)
            removeTypingIndicator()
            throw streamError
        }

    } catch (error) {
        console.error('Error:', error)
        removeTypingIndicator()
        await delay(500)
        messages.value.push({
            type: 'assistant',
            dataType: 'error',
            content: {
                message: error.message || 'Sorry, I encountered an error processing your request.',
                timestamp: new Date().toISOString()
            },
            isError: true
        })
        await scrollToBottom()
    } finally {
        isLoading.value = false
    }
}

// Updated scroll function with force option
const scrollToBottom = async (force = false) => {
    await nextTick()
    if (messagesContainer.value) {
        const container = messagesContainer.value
        const scrollOptions = {
            top: container.scrollHeight,
            behavior: force ? 'auto' : 'smooth'
        }
        container.scrollTo(scrollOptions)
    }
}

// Watch for new messages and scroll
watch(() => messages.value.length, () => {
    scrollToBottom()
})
</script>

<style scoped>
/* Layout & Background */
.bg-custom {
    background-color: #f4f4f4 !important;
}

.chat-wrapper {
    max-width: 960px;
    width: 100%;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: white;
}

/* Header Styles */
.toolbar-logo {
    display: flex;
    align-items: center;
}

/* Chat Area Container */
.chat-area {
    flex: 1;
    overflow: hidden;
    position: relative;
    background: #f4f4f4;
}

.messages-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    overflow-y: auto;
    scroll-behavior: smooth;
    -ms-overflow-style: none;
    scrollbar-width: none;
    margin-bottom: 24px;

    &::-webkit-scrollbar {
        display: none;
    }
}

/* Message Styles - User */
.user-message-wrapper {
    position: relative;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding-right: 32px;
}

.user-message {
    background-color: #4C64E2;
    color: white;
    padding: 12px 16px;
    border-radius: 15px;
    border-top-right-radius: 0;
    max-width: 80%;
    white-space: pre-wrap;
    word-break: break-word;
    margin-top: 24px;
    font-size: 14.5px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.user-info {
    position: absolute;
    top: 0;
    right: 0;
    width: 24px;
}

/* Message Styles - Bot */
.bot-message-wrapper {
    position: relative;
    display: flex;
    gap: 8px;
    padding-left: 32px;
    margin-bottom: 16px;
    width: fit-content;
    /* Make wrapper fit content */
    max-width: 80%;
    /* Keep maximum width limit */
}

.bot-message {
    background: white;
    padding: 10px 14px;
    border-radius: 15px;
    border-top-left-radius: 0;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    width: fit-content;
    /* Adapt to content */
    min-width: 100%;
    /* Take at least full width of parent */
    color: #555;
    font-size: 14.5px;
}

.data-display {
    width: 100%;
    min-width: 100%;
}

.bot-info {
    position: absolute;
    top: 0;
    left: 0;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.bot-content {
    flex: 1;
    margin-top: 24px;
    width: 100%;
    /* Take full width of parent */
    min-width: 200px;
    /* Minimum width for readability */
}


.bot-message .message-text {
    font-size: 15px !important;
    line-height: 20px;
    color: #777 !important;
}

/* Error Message Styles */
.bot-message.error {
    background-color: #FEF2F2;
    border: 1px solid #FCA5A5;
    box-shadow: 0 2px 4px rgba(220, 38, 38, 0.1);
}

.bot-message .message-text.error-text {
    color: #DC2626 !important;
    font-weight: 500;
}


/* Code Block Styles */
pre {
    white-space: pre-wrap;
    margin: 0;
}

.message-card {
    min-width: 200px;
}

/* Footer & Input Area */
.footer-container {
    border-top: 1px solid rgba(0, 0, 0, 0.12);
    padding: 60px 25px !important;
    height: auto !important;
    min-height: 84px !important;
    max-height: 84px !important;
    position: sticky;
    bottom: 0;
    width: 100%;
    background: white;
}

.chat-input :deep(.v-field) {
    border-radius: 10px !important;
}

.send-button {
    border-radius: 5px !important;
    width: 52px !important;
    height: 48px !important;
    background: #4C64E2 !important;
    border: 1px solid #666 !important;
    margin-left: 16px !important;
    padding: 12px !important;
    transition: transform 0.2s ease-out;

    &:hover {
        transform: scale(1.1);
    }
}

/* Animations */
@keyframes subtleSlideUp {
    from {
        opacity: 0;
        transform: translateY(8px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Spacing Utilities */
.user-message-wrapper:last-child,
.bot-message-wrapper:last-child {
    margin-bottom: 24px;
}

/* Animation Classes */
.user-info,
.bot-info {
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}


/* Loading Animation */
.loading-dots {
    display: flex;
    gap: 8px;
    padding: 12px 16px;
}

.loading-dots span {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background-color: #4C64E2;
    display: inline-block;
    animation: bounce 1.4s infinite ease-in-out both;
}

.loading-dots span:nth-child(1) {
    animation-delay: -0.32s;
}

.loading-dots span:nth-child(2) {
    animation-delay: -0.16s;
}

@keyframes bounce {

    0%,
    80%,
    100% {
        transform: scale(0);
    }

    40% {
        transform: scale(1.0);
    }
}
</style>

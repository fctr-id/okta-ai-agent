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
                    <div class="messages-container d-flex flex-column gap-4 py-4 px-0" ref="messagesContainer">
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
                console.log('Stream response:', data)
                if (!hasReceivedResponse) {
                    removeTypingIndicator()
                    hasReceivedResponse = true

                    messages.value.push({
                        type: 'assistant',
                        dataType: data.type,
                        content: data.content,
                        metadata: data.metadata,
                        isLoading: false,
                    })
                    await scrollToBottom()
                    break
                }
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
    background-color: #fff !important;
}

.chat-wrapper {
    max-width: 1440px;
    width: 100%;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: white;
    margin: 0 auto;
    border-left: 1px solid #e5e7eb;
    border-right: 1px solid #e5e7eb;
    box-shadow: 0 0 24px rgba(0, 0, 0, 0.08);
}

/* Chat Area Container */
.chat-area {
    flex: 1;
    overflow: hidden;
    position: relative;
    background: #f4f4f4;
    border-top: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
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
    margin: 0 auto 24px auto;
    padding: 0 48px;
    max-width: 1400px;

    &::-webkit-scrollbar {
        display: none;
    }
}

/* Message Styles - User */
.user-message-wrapper {
    position: relative;
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding-right: 32px;
    width: 100%;
    margin: 16px 0;
}

.user-message {
    background-color: #4C64E2;
    color: white;
    padding: 10px 14px;
    border-radius: 16px;
    border-top-right-radius: 4px;
    width: fit-content; /* Changed from max-width: 60% */
    min-width: min-content; /* Changed from fixed 200px */
    max-width: 80%; /* Added max-width constraint */
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 14.5px;
    line-height: 1.5;
    box-shadow: 0 2px 8px rgba(76, 100, 226, 0.2);
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Message Styles - Bot */
.bot-message-wrapper {
    position: relative;
    display: flex;
    gap: 12px;
    padding-left: 32px;
    padding-right: 32px;
    width: 100%;
    margin: 16px 0;
}

.bot-message {
    background: white;
    padding: 6px 14px;
    border-radius: 16px;
    border-top-left-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    width: fit-content; /* Changed from 100% */
    min-width: min-content; /* Added */
    max-width: 100%; /* Added */
    color: #2c3e50;
    font-size: 14.5px;
    line-height: 1.5;
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}


.data-display {
    width: 100%;
    overflow-x: auto;
    margin: 12px 0;
    padding: 0px 0px;
    border: none; /* Added to remove any inner borders */
}

/* Remove any potential inner borders */

.bot-content {
    width: fit-content; /* Changed from 100% */
    min-width: min-content; /* Added */
    max-width: 100%; /* Added */
    display: flex;
    flex-direction: column;
}

/* Error Message Styles */
.bot-message.error {
    background-color: #FEF2F2;
    border: 1px solid #FCA5A5;
    box-shadow: 0 2px 8px rgba(220, 38, 38, 0.1);
}

/* Footer & Input Area */
.footer-container {
    border-top: 1px solid #e5e7eb;
    padding: 60px 25px !important; /* Increased top padding significantly */
    height: auto !important;
    min-height: 120px !important;
    max-height: 120px !important;
    position: sticky;
    bottom: 0;
    width: 100%;
    background: white;
    z-index: 10;
    box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.03);
    display: flex;
    align-items: center;
}

.chat-input :deep(.v-field) {
    border-radius: 12px !important;
    background: #f8f9fa !important;
}

.send-button {
    border-radius: 12px !important;
    width: 52px !important;
    height: 52px !important;
    background: #4C64E2 !important;
    border: none !important;
    margin-left: 16px !important;
    padding: 14px !important;
    transition: all 0.2s ease-out;

    &:hover {
        transform: scale(1.05);
        background: #3b4fd9 !important;
    }
}

/* Animations */
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

/* Loading Animation */
.loading-dots {
    display: flex;
    gap: 8px;
    padding: 16px;
    justify-content: center;
}

.loading-dots span {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: #4C64E2;
    display: inline-block;
    animation: bounce 1.4s infinite ease-in-out both;
    opacity: 0.6;
}

/* Responsive Design */
@media (max-width: 1440px) {
    .chat-wrapper {
        max-width: 100%;
    }
}

@media (max-width: 1024px) {
    .messages-container {
        padding: 0 32px;
    }
    
    .user-message {
        max-width: 70%;
    }
}

@media (max-width: 768px) {
    .messages-container {
        padding: 0 16px;
    }
    
    .footer-container {
        padding: 16px 24px !important;
    }
    
    .user-message {
        max-width: 80%;
    }
    
    .bot-message {
        width: calc(100% - 32px);
    }
}

@media (max-width: 480px) {
    .user-message,
    .bot-message {
        padding: 14px 16px;
        font-size: 14px;
    }
}

@keyframes bounce {
    0%, 80%, 100% {
        transform: scale(0);
    }
    40% {
        transform: scale(1.0);
    }
}
</style>

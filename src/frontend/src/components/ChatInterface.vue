<template>
    <v-app class="bg-custom">
        <div class="d-flex justify-center">
            <div class="chat-wrapper">
                <!-- Header - No changes -->
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

                <!-- Chat Messages Area - No changes to structure -->
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
                                            <span></span><span></span><span></span>
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
                                @keyup.enter="sendMessage" @keydown="handleKeyDown" @input="handleInputChange" />
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
                            *(Some responses may be incorrect. Please verify)
                        </div>
                    </div>
                </v-footer>
            </div>
        </div>
    </v-app>
</template>

<script setup>
import { computed, ref, watch, onMounted, nextTick } from 'vue'
import { useFetchStream } from '@/composables/useFetchStream'
import { useSanitize } from '@/composables/useSanitize'
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

// Initialize sanitization utilities
const { text: sanitizeText, query: sanitizeQuery } = useSanitize()

// Handle input change with sanitization
const handleInputChange = () => {
    // Apply lightweight sanitization during typing (full sanitization at submission)
    if (userInput.value !== null && userInput.value !== undefined) {
        // Basic sanitization while typing for better UX
        userInput.value = sanitizeText(userInput.value, {
            maxLength: 2000,
            removeHtml: true,
            trim: false // Don't trim while typing
        })
    }
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
    removeTypingIndicator();
    messages.value.push({
        type: 'assistant',
        content: typeof error === 'object' ? error.message || 'An error occurred' : error,
        isError: true
    });
};

onMounted(() => {
    try {
        const savedHistory = localStorage.getItem('messageHistory')
        if (savedHistory) {
            // Sanitize history loaded from localStorage
            const parsedHistory = JSON.parse(savedHistory)
            messageHistory.value = parsedHistory.map(item => sanitizeQuery(item))
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

const { postStream } = useFetchStream()

// Update in the script section of ChatInterface.vue
const handleStreamResponse = async (streamResponse) => {
    let currentMessage = null;

    try {
        for await (const data of streamResponse.getStream()) {
            //console.log('Stream data:', data);
            if (!data) continue;

            switch (data.type) {
                case 'text':
                    removeTypingIndicator();
                    messages.value.push({
                        type: 'assistant',
                        // Sanitize response text to prevent reflected XSS
                        content: sanitizeText(data.content),
                        isError: false
                    });
                    await scrollToBottom();
                    break;
                case 'metadata':
                    removeTypingIndicator();
                    currentMessage = {
                        type: 'assistant',
                        dataType: 'stream',
                        content: [], // Will hold the data rows
                        metadata: data.content, // Direct assignment without spreading
                        isLoading: true
                    };
                    messages.value.push(currentMessage);
                    await scrollToBottom();
                    break;

                case 'batch':
                    if (currentMessage && Array.isArray(data.content)) {
                        // Append new content instead of replacing
                        currentMessage.content = [
                            ...currentMessage.content || [],
                            ...data.content
                        ];

                        // Update metadata
                        currentMessage.metadata = {
                            ...currentMessage.metadata,
                            batchInfo: data.metadata
                        };

                        // Force reactivity update
                        messages.value = [...messages.value];
                        await scrollToBottom(true);
                    }
                    break;

                case 'complete':
                    if (currentMessage) {
                        currentMessage.isLoading = false;
                        messages.value = [...messages.value];
                    }
                    break;

                case 'error':
                    removeTypingIndicator();
                    // Sanitize error message to prevent XSS
                    const errorContent = typeof data.content === 'object' ?
                        sanitizeText(data.content.message || 'Error occurred') :
                        sanitizeText(data.content);

                    messages.value.push({
                        type: 'assistant',
                        content: errorContent,
                        isError: true
                    });
                    await scrollToBottom();
                    break;
            }
        }
    } catch (error) {
        console.error('Stream processing error:', error);
        removeTypingIndicator();
        // Sanitize error message
        addErrorMessage(typeof error === 'string' ? sanitizeText(error) : error);
    } finally {
        if (currentMessage) {
            currentMessage.isLoading = false;
        }
        isLoading.value = false;
    }
};


const sendMessage = async () => {
    // Apply full sanitization on submission
    const sanitizedInput = sanitizeQuery(userInput.value.trim(), { maxLength: 2000 })

    if (!sanitizedInput || isLoading.value) {
        console.warn('Message sending prevented:', !sanitizedInput ? 'empty input' : 'loading state')
        return
    }

    try {
        userInput.value = ''
        isLoading.value = true

        // Handle message history with sanitized input
        try {
            const existingIndex = messageHistory.value.indexOf(sanitizedInput)

            if (existingIndex === -1) {
                // New message - add to front of history
                messageHistory.value = [sanitizedInput, ...messageHistory.value.slice(0, CONFIG.MAX_HISTORY - 1)]
            } else {
                // Existing message - move to front of history
                messageHistory.value = [
                    sanitizedInput,
                    ...messageHistory.value.slice(0, existingIndex),
                    ...messageHistory.value.slice(existingIndex + 1)
                ]
            }

            // Save sanitized history to localStorage and reset index
            localStorage.setItem('messageHistory', JSON.stringify(messageHistory.value))
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

        // Make API call and handle stream with sanitized input
        const streamResponse = await postStream('/api/query', { query: sanitizedInput })
        await handleStreamResponse(streamResponse)

    } catch (error) {
        console.error('Error:', error)
        removeTypingIndicator()
        await delay(500)

        // Sanitize error message
        const errorMessage = error.message || 'Sorry, I encountered an error processing your request.'

        messages.value.push({
            type: 'assistant',
            dataType: 'error',
            content: {
                message: sanitizeText(errorMessage),
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
    width: fit-content;
    /* Changed from max-width: 60% */
    min-width: min-content;
    /* Changed from fixed 200px */
    max-width: 80%;
    /* Added max-width constraint */
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
    width: fit-content;
    /* Changed from 100% */
    min-width: min-content;
    /* Added */
    max-width: 100%;
    /* Added */
    color: #2c3e50;
    font-size: 14.5px;
    line-height: 1.5;
    animation: subtleSlideUp 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.bot-message .message-text {
    white-space: pre-wrap;
    word-break: break-word;
    padding: 10px 14px;
}

.data-display {
    width: 100%;
    overflow-x: auto;
    margin: 12px 0;
    padding: 0px 0px;
    border: none;
    /* Added to remove any inner borders */
}

/* Remove any potential inner borders */

.bot-content {
    width: fit-content;
    /* Changed from 100% */
    min-width: min-content;
    /* Added */
    max-width: 100%;
    /* Added */
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
    padding: 60px 25px !important;
    /* Increased top padding significantly */
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
    padding: 0px 14px 12px 14px;
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

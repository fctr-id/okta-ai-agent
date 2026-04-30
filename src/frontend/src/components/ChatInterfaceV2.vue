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
                                <div v-if="isLoading || reactLoading" class="query-icons-left">
                                    <button 
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

            <transition name="fade-up">
                <div v-if="hasResults" class="transcript-shell">
                    <div class="transcript-session-bar">
                        <div class="transcript-session-label">
                            <span class="transcript-session-label-caption">Current session</span>
                            <span class="transcript-session-label-title" :title="activeSessionTitle || 'Untitled conversation'">
                                {{ activeSessionTitle || 'Untitled conversation' }}
                            </span>
                        </div>
                    </div>

                    <div v-if="sessionLoadOverlayVisible" class="session-load-overlay" role="status" aria-live="polite" aria-busy="true">
                        <div class="session-load-dialog">
                            <div class="session-load-header">
                                <div class="session-load-icon">
                                    <v-progress-circular indeterminate color="primary" size="20" width="2" />
                                </div>

                                <div class="session-load-copy">
                                    <span class="session-load-eyebrow">
                                        {{ sessionHydrationTotal > 0 ? 'Loading saved session' : 'Opening session' }}
                                    </span>
                                    <span class="session-load-title" :title="sessionLoadOverlayTitle">
                                        {{ sessionLoadOverlayTitle }}
                                    </span>
                                </div>
                            </div>

                            <div class="session-load-progress-block">
                                <div class="session-load-progress-copy">
                                    <span>{{ sessionHydrationLabel }}</span>
                                    <span v-if="sessionHydrationTotal > 0" class="session-load-progress-muted">
                                        {{ sessionHydrationProgress }}%
                                    </span>
                                </div>

                                <v-progress-linear
                                    color="primary"
                                    rounded
                                    height="8"
                                    :indeterminate="sessionHydrationTotal === 0"
                                    :model-value="sessionHydrationProgress"
                                />
                            </div>
                        </div>
                    </div>

                    <div v-if="sessionViewError && conversationTurns.length === 0 && !legacyTurnVisible" class="transcript-state-card transcript-state-card-error">
                        {{ sessionViewError }}
                    </div>

                    <div v-else-if="!sessionViewLoading && conversationTurns.length === 0 && !legacyTurnVisible" class="transcript-state-card">
                        Ask a question to start this conversation.
                    </div>

                    <div v-if="legacyTurnVisible" class="transcript-list">
                        <article class="transcript-turn is-active">
                            <div class="question-header-container transcript-question-header">
                                <div class="question-header">
                                    <div class="question-copy">
                                        <div class="question-text">{{ lastQuestion }}</div>
                                    </div>
                                    <div class="question-timestamp">Now</div>
                                </div>
                            </div>

                            <div
                                v-if="legacyResponseHasContent"
                                :class="['results-container', 'transcript-results', getContentClass(currentResponse.type)]"
                            >
                                <DataDisplay
                                    :type="currentResponse.type"
                                    :content="currentResponse.content"
                                    :metadata="currentResponse.metadata"
                                />
                            </div>

                            <div v-else class="turn-loading-card">
                                <div class="turn-summary-meta">
                                    <span class="turn-status-pill turn-status-pill-active">
                                        Running
                                    </span>
                                </div>
                                <v-progress-linear indeterminate color="primary" rounded height="6" />
                            </div>
                        </article>
                    </div>

                    <div v-if="conversationTurns.length > 0" class="transcript-list">
                        <article
                            v-for="turn in conversationTurns"
                            :key="turn.key"
                            :ref="(element) => setTranscriptTurnElement(turn.key, element)"
                            class="transcript-turn"
                            :class="{ 'is-active': turn.isActive }"
                        >
                            <div class="question-header-container transcript-question-header">
                                <div class="question-header">
                                    <div class="question-copy">
                                        <div class="question-text">{{ turn.queryText }}</div>
                                    </div>
                                    <div class="question-timestamp">{{ formatTurnTimestamp(turn) }}</div>
                                </div>
                            </div>

                            <div v-if="showLivePanelsForTurn(turn)" class="react-panels mb-4 transcript-react-panels">
                                <DiscoveryPanel
                                    :steps="reactSteps"
                                    :isThinking="reactLoading && reactSteps.length === 0"
                                    :isComplete="reactDiscoveryComplete"
                                    :error="reactError"
                                    :executionStarted="reactExecutionStarted"
                                />

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

                            <div
                                v-if="turn.results"
                                :class="['results-container', 'transcript-results', getContentClass(turn.results.display_type)]"
                            >
                                <DataDisplay
                                    :type="turn.results.display_type"
                                    :content="turn.results.content"
                                    :metadata="turn.results.metadata"
                                    :showTableAction="shouldShowTurnResultsAction(turn) || turn.isLoadingFullResults"
                                    :tableActionLabel="getTurnResultsActionLabel(turn)"
                                    :tableActionLoading="turn.isLoadingFullResults"
                                    @table-action="loadFullTurnResults(turn)"
                                />
                            </div>

                            <div v-else-if="turn.isHydratingResults" class="turn-loading-card">
                                <div class="turn-summary-meta">
                                    <span class="turn-status-pill turn-status-pill-muted">
                                        Loading saved result
                                    </span>
                                    <span
                                        v-if="turn.resultCount !== null && turn.resultCount !== undefined"
                                        class="turn-status-pill turn-status-pill-muted"
                                    >
                                        {{ formatResultCount(turn.resultCount, turn.isPartialResult) }}
                                    </span>
                                </div>
                                <v-progress-linear indeterminate color="primary" rounded height="6" />
                            </div>

                            <div v-else-if="!turn.results" class="turn-summary-card">
                                <div class="turn-summary-meta">
                                    <span class="turn-status-pill" :class="turnStatusClass(turn)">
                                        {{ formatTurnStatus(turn) }}
                                    </span>
                                    <span
                                        v-if="turn.resultCount !== null && turn.resultCount !== undefined"
                                        class="turn-status-pill turn-status-pill-muted"
                                    >
                                        {{ formatResultCount(turn.resultCount, turn.isPartialResult) }}
                                    </span>
                                </div>

                                <p class="turn-summary-text">{{ getTurnSummary(turn) }}</p>
                                <p v-if="turn.resultsError || turn.error" class="turn-error-text">{{ turn.resultsError || turn.error }}</p>
                            </div>
                        </article>
                    </div>
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

import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount, inject } from 'vue'
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
    currentSessionId: reactSessionId,
    currentRunId: reactRunId,
    currentTurnNumber: reactTurnNumber,
    startProcess: startReActProcess,
    connectToStream: connectReActStream,
    cancelProcess: cancelReAct
} = useReactStream()

// Initialize sanitization utilities
const { query: sanitizeQuery, text: sanitizeText } = useSanitize()

// History Management
const { fetchSessionDetail, fetchTurnResultPreview, fetchTurnResultFull } = useHistory()
const appLayoutRef = ref(null)
const activeSessionId = ref(null)
const activeSessionTitle = ref('')
const pendingSessionTitle = ref('')
const conversationTurns = ref([])
const sessionViewLoading = ref(false)
const sessionViewError = ref(null)
const activeTurnKey = ref(null)
const sessionHydrationLoaded = ref(0)
const sessionHydrationTotal = ref(0)
let sessionLoadRequestId = 0
const transcriptTurnElements = new Map()
let activeTurnScrollFrameId = null

const setTranscriptTurnElement = (turnKey, element) => {
    if (!turnKey) {
        return
    }

    if (element instanceof HTMLElement) {
        transcriptTurnElements.set(turnKey, element)
        return
    }

    transcriptTurnElements.delete(turnKey)
}

const scrollToTurn = (turnKey, behavior = 'smooth') => {
    if (!turnKey) {
        return
    }

    void nextTick(() => {
        if (activeTurnScrollFrameId !== null) {
            window.cancelAnimationFrame(activeTurnScrollFrameId)
        }

        activeTurnScrollFrameId = window.requestAnimationFrame(() => {
            activeTurnScrollFrameId = null
            const turnElement = transcriptTurnElements.get(turnKey)
            if (!turnElement) {
                return
            }

            turnElement.scrollIntoView({
                behavior,
                block: 'end',
                inline: 'nearest'
            })
        })
    })
}

const sessionHydrationProgress = computed(() => {
    if (sessionHydrationTotal.value <= 0) {
        return 0
    }

    return Math.min(100, Math.round((sessionHydrationLoaded.value / sessionHydrationTotal.value) * 100))
})

const sessionHydrationLabel = computed(() => {
    if (sessionHydrationTotal.value > 0) {
        const loaded = Math.min(sessionHydrationLoaded.value, sessionHydrationTotal.value)
        return `Loading saved results ${loaded}/${sessionHydrationTotal.value}`
    }

    return 'Loading conversation...'
})

const sessionLoadOverlayVisible = computed(() => sessionViewLoading.value)

const sessionLoadOverlayTitle = computed(() => {
    return pendingSessionTitle.value || activeSessionTitle.value || 'Selected conversation'
})

const buildTurnKey = ({ sessionId, runId, turnNumber }) => `${sessionId || 'session'}:${turnNumber || 'turn'}:${runId || 'run'}`

const deriveSessionTitle = (query, maxLength = 120) => {
    const cleaned = String(query || '').replace(/\s+/g, ' ').trim()
    if (!cleaned) return 'New conversation'
    return cleaned.length <= maxLength ? cleaned : `${cleaned.slice(0, maxLength - 3).trimEnd()}...`
}

const cleanSummaryText = (value) => {
    if (!value) return ''

    return String(value)
        .replace(/^#+\s*/gm, '')
        .replace(/[`*_]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
}

const normalizeConversationResult = (resultLike) => {
    if (!resultLike) {
        return null
    }

    const rawDisplayType = resultLike.display_type || resultLike.displayType || MessageType.TABLE
    const normalizedDisplayType = rawDisplayType === MessageType.STREAM || rawDisplayType === MessageType.BATCH
        ? MessageType.TABLE
        : rawDisplayType

    return {
        display_type: normalizedDisplayType,
        content: resultLike.content ?? resultLike.results ?? [],
        metadata: resultLike.metadata || {}
    }
}

const shouldHydrateSavedTurn = (turn) => Boolean(
    turn.displayType ||
    turn.artifactFile ||
    turn.finalResponseSummary ||
    turn.resultCount !== null ||
    turn.status === 'completed'
)

const normalizeConversationTurn = (turnLike) => {
    const sessionId = turnLike.sessionId || turnLike.session_id || activeSessionId.value || null
    const runId = turnLike.runId || turnLike.run_id || null
    const turnNumber = turnLike.turnNumber || turnLike.turn_number || null

    return {
        key: turnLike.key || buildTurnKey({ sessionId, runId, turnNumber }),
        sessionId,
        runId,
        turnNumber,
        queryText: turnLike.queryText ?? turnLike.query_text ?? '',
        source: turnLike.source ?? 'user',
        status: turnLike.status ?? 'created',
        completionMode: turnLike.completionMode ?? turnLike.completion_mode ?? null,
        displayType: turnLike.displayType ?? turnLike.display_type ?? null,
        finalResponseSummary: turnLike.finalResponseSummary ?? turnLike.final_response_summary ?? null,
        resultCount: turnLike.resultCount ?? turnLike.result_count ?? null,
        isPartialResult: Boolean(turnLike.isPartialResult ?? turnLike.is_partial_result ?? false),
        artifactFile: turnLike.artifactFile ?? turnLike.artifact_file ?? null,
        startedAt: turnLike.startedAt ?? turnLike.started_at ?? null,
        completedAt: turnLike.completedAt ?? turnLike.completed_at ?? null,
        updatedAt: turnLike.updatedAt ?? turnLike.updated_at ?? null,
        isActive: Boolean(turnLike.isActive),
        isHydratingResults: Boolean(turnLike.isHydratingResults),
        isLoadingFullResults: Boolean(turnLike.isLoadingFullResults),
        resultsHydrated: Boolean(turnLike.resultsHydrated ?? turnLike.results_hydrated ?? turnLike.results),
        results: normalizeConversationResult(turnLike.results),
        resultsError: turnLike.resultsError ?? null,
        error: turnLike.error ?? null,
        steps: turnLike.steps || [],
        validationStep: turnLike.validationStep || null,
        executionStarted: Boolean(turnLike.executionStarted),
        isExecuting: Boolean(turnLike.isExecuting),
        executionMessage: turnLike.executionMessage ?? '',
        executionProgress: turnLike.executionProgress || 0,
        subprocessProgress: turnLike.subprocessProgress || [],
        generatedScript: turnLike.generatedScript || null,
        tokenUsage: turnLike.tokenUsage || null,
        rateLimitWarning: turnLike.rateLimitWarning || 0,
        discoveryComplete: Boolean(turnLike.discoveryComplete)
    }
}

const sortConversationTurns = () => {
    conversationTurns.value = [...conversationTurns.value].sort((left, right) => {
        const leftOrder = left.turnNumber ?? Number.MAX_SAFE_INTEGER
        const rightOrder = right.turnNumber ?? Number.MAX_SAFE_INTEGER
        if (leftOrder !== rightOrder) {
            return leftOrder - rightOrder
        }
        return String(left.runId || left.key).localeCompare(String(right.runId || right.key))
    })
}

const findConversationTurnByIdentity = ({ sessionId, runId, turnNumber, key = null }) => {
    return conversationTurns.value.find((item) => {
        if (key && item.key === key) {
            return true
        }

        if (runId && item.runId === runId) {
            return true
        }

        return Boolean(sessionId && turnNumber && item.sessionId === sessionId && item.turnNumber === turnNumber)
    }) || null
}

const resolveActiveTurnKey = ({ sessionId, runId, turnNumber }) => {
    const matchedTurn = findConversationTurnByIdentity({
        sessionId,
        runId,
        turnNumber,
        key: activeTurnKey.value
    })

    return matchedTurn?.key || buildTurnKey({ sessionId, runId, turnNumber })
}

const upsertConversationTurn = (turnLike) => {
    const normalized = normalizeConversationTurn(turnLike)
    const index = conversationTurns.value.findIndex((item) =>
        item.key === normalized.key ||
        (normalized.runId && item.runId === normalized.runId) ||
        (normalized.sessionId && normalized.turnNumber && item.sessionId === normalized.sessionId && item.turnNumber === normalized.turnNumber)
    )

    if (index >= 0) {
        conversationTurns.value[index] = normalizeConversationTurn({
            ...conversationTurns.value[index],
            ...turnLike
        })
    } else {
        conversationTurns.value.push(normalized)
    }

    sortConversationTurns()
    return conversationTurns.value.find((item) => item.key === normalized.key) || normalized
}

const deriveActiveTurnStatus = () => {
    if (reactError.value) return 'failed'
    if (reactResults.value && !reactLoading.value && !reactProcessing.value) return 'completed'
    if (reactExecutionStarted.value || reactLoading.value || reactProcessing.value) return 'running'
    return 'created'
}

const deriveTurnCompletionMode = () => {
    if (reactError.value) return 'fail'
    if (!reactResults.value) return null
    if (reactResults.value.display_type === 'markdown') return 'direct_answer'

    const resultCount = reactResults.value?.metadata?.count
    if (resultCount === 0) return 'empty'
    return 'script'
}

const registerActiveTurn = (queryText, source = 'user') => {
    const sessionId = reactSessionId.value || activeSessionId.value
    const runId = reactRunId.value
    const turnNumber = reactTurnNumber.value

    if (!sessionId || !runId || !turnNumber) {
        return null
    }

    activeSessionId.value = sessionId
    if (!activeSessionTitle.value) {
        activeSessionTitle.value = deriveSessionTitle(queryText)
    }

    const turn = upsertConversationTurn({
        sessionId,
        runId,
        turnNumber,
        queryText,
        source,
        status: 'created',
        startedAt: new Date().toISOString(),
        isActive: true
    })

    activeTurnKey.value = turn.key
    hasResults.value = true
    scrollToTurn(turn.key, 'smooth')
    return turn
}

const syncActiveTurnFromStream = () => {
    if (!isReActMode.value) {
        return
    }

    const sessionId = reactSessionId.value || activeSessionId.value
    const runId = reactRunId.value
    const turnNumber = reactTurnNumber.value

    if (!sessionId || !runId || !turnNumber || !lastQuestion.value) {
        return
    }

    activeSessionId.value = sessionId
    if (!activeSessionTitle.value) {
        activeSessionTitle.value = deriveSessionTitle(lastQuestion.value)
    }

    const resultCount = reactResults.value?.metadata?.count ?? (Array.isArray(reactResults.value?.content) ? reactResults.value.content.length : null)
    const existing = findConversationTurnByIdentity({ sessionId, runId, turnNumber })

    const updatedTurn = upsertConversationTurn({
        ...existing,
        key: resolveActiveTurnKey({ sessionId, runId, turnNumber }),
        sessionId,
        runId,
        turnNumber,
        queryText: existing?.queryText || lastQuestion.value,
        source: existing?.source || 'user',
        status: deriveActiveTurnStatus(),
        completionMode: deriveTurnCompletionMode(),
        displayType: reactResults.value?.display_type || existing?.displayType || null,
        finalResponseSummary: existing?.finalResponseSummary,
        resultCount,
        isPartialResult: Boolean(reactResults.value?.metadata?.is_partial_result || existing?.isPartialResult),
        startedAt: existing?.startedAt || new Date().toISOString(),
        completedAt: !reactLoading.value && !reactProcessing.value ? (existing?.completedAt || new Date().toISOString()) : existing?.completedAt,
        isActive: reactLoading.value || reactProcessing.value,
        results: reactResults.value || existing?.results || null,
        error: reactError.value || null,
        steps: reactSteps.value,
        validationStep: reactValidationStep.value,
        executionStarted: reactExecutionStarted.value,
        isExecuting: reactIsExecuting.value,
        executionMessage: reactExecutionMessage.value,
        executionProgress: reactExecutionProgress.value,
        subprocessProgress: reactSubprocessProgress.value,
        generatedScript: reactGeneratedScript.value,
        tokenUsage: reactTokenUsage.value,
        rateLimitWarning: reactRateLimitWarning.value,
        discoveryComplete: reactDiscoveryComplete.value
    })

    activeTurnKey.value = updatedTurn.key
    hasResults.value = true
    scrollToTurn(updatedTurn.key, updatedTurn.isActive ? 'auto' : 'smooth')
}

const prepareSessionTurnsForHydration = (turns) => turns.map((turnLike) => {
    const normalizedTurn = normalizeConversationTurn(turnLike)
    const needsHydration = shouldHydrateSavedTurn(normalizedTurn) && !normalizedTurn.results

    return normalizeConversationTurn({
        ...normalizedTurn,
        isHydratingResults: needsHydration,
        resultsHydrated: !needsHydration,
        resultsError: null
    })
})

const hydrateSessionTurnResults = async (sessionId, turns, requestId) => {
    const turnsToHydrate = turns.filter((turn) => turn.isHydratingResults)
    sessionHydrationLoaded.value = 0
    sessionHydrationTotal.value = turnsToHydrate.length

    for (const turn of turnsToHydrate) {
        if (requestId !== sessionLoadRequestId) {
            return
        }

        try {
            const preview = await fetchTurnResultPreview(sessionId, turn.turnNumber)
            if (requestId !== sessionLoadRequestId) {
                return
            }

            upsertConversationTurn({
                key: turn.key,
                sessionId: turn.sessionId,
                runId: turn.runId,
                turnNumber: turn.turnNumber,
                results: preview?.available ? preview : null,
                isHydratingResults: false,
                resultsHydrated: true,
                resultsError: null
            })
        } catch (err) {
            if (requestId !== sessionLoadRequestId) {
                return
            }

            upsertConversationTurn({
                key: turn.key,
                sessionId: turn.sessionId,
                runId: turn.runId,
                turnNumber: turn.turnNumber,
                isHydratingResults: false,
                resultsHydrated: true,
                resultsError: err.message || 'Failed to load saved result preview'
            })
        } finally {
            if (requestId === sessionLoadRequestId) {
                sessionHydrationLoaded.value += 1
            }
        }
    }
}

const shouldShowLoadFullResults = (turn) => {
    const resultMetadata = turn.results?.metadata || {}
    if (!turn.results || turn.results.display_type === 'markdown') {
        return false
    }

    return Boolean(resultMetadata.isPreview)
}

const shouldShowTurnResultsAction = (turn) => shouldShowLoadFullResults(turn)

const getTurnResultsActionLabel = (turn) => {
    if (turn.isLoadingFullResults) {
        return 'Fetching all records...'
    }

    return 'Fetch all records'
}

const loadFullTurnResults = async (turn) => {
    if (!turn?.sessionId || !turn?.turnNumber || turn.isLoadingFullResults) {
        return
    }

    upsertConversationTurn({
        key: turn.key,
        sessionId: turn.sessionId,
        runId: turn.runId,
        turnNumber: turn.turnNumber,
        isLoadingFullResults: true,
        resultsError: null,
    })

    try {
        const fullResult = await fetchTurnResultFull(turn.sessionId, turn.turnNumber)
        upsertConversationTurn({
            key: turn.key,
            sessionId: turn.sessionId,
            runId: turn.runId,
            turnNumber: turn.turnNumber,
            results: fullResult?.available ? fullResult : turn.results,
            isLoadingFullResults: false,
            resultsError: fullResult?.available ? null : 'Saved full result is not available for this turn',
        })
    } catch (err) {
        upsertConversationTurn({
            key: turn.key,
            sessionId: turn.sessionId,
            runId: turn.runId,
            turnNumber: turn.turnNumber,
            isLoadingFullResults: false,
            resultsError: err.message || 'Failed to load saved full result',
        })
    }
}

const prepareComposerForSessionLoad = async () => {
    clearHomeRevealTimer()
    clearComposerAnimationTimer()
    cleanupComposerAnimation()
    isReturningHome.value = false
    hasResults.value = true

    await nextTick()
    autoResizeTextarea()
}

const loadConversationSession = async (sessionId, options = {}) => {
    const requestId = ++sessionLoadRequestId
    pendingSessionTitle.value = String(options?.title || '').trim()
    await prepareComposerForSessionLoad()
    sessionViewLoading.value = true
    sessionViewError.value = null
    sessionHydrationLoaded.value = 0
    sessionHydrationTotal.value = 0

    let sessionDetail = null

    try {
        sessionDetail = await fetchSessionDetail(sessionId)
        if (requestId !== sessionLoadRequestId) {
            return null
        }

        activeSessionId.value = sessionDetail.session_id
        activeSessionTitle.value = sessionDetail.title || 'Untitled conversation'
        conversationTurns.value = prepareSessionTurnsForHydration(sessionDetail.turns || [])
        sortConversationTurns()
        activeTurnKey.value = null

        await hydrateSessionTurnResults(sessionDetail.session_id, conversationTurns.value, requestId)
        if (requestId !== sessionLoadRequestId) {
            return null
        }
    } catch (err) {
        if (requestId !== sessionLoadRequestId) {
            return null
        }

        sessionViewError.value = err.message || 'Failed to load conversation'
        conversationTurns.value = []
        sessionHydrationLoaded.value = 0
        sessionHydrationTotal.value = 0
        window.dispatchEvent(new CustomEvent('tako:session-load-failed', {
            detail: {
                sessionId
            }
        }))
        throw err
    } finally {
        if (requestId === sessionLoadRequestId) {
            sessionViewLoading.value = false
            pendingSessionTitle.value = ''
        }
    }

    if (requestId === sessionLoadRequestId && sessionDetail) {
        window.dispatchEvent(new CustomEvent('tako:session-loaded', {
            detail: {
                sessionId: sessionDetail.session_id
            }
        }))
    }

    return sessionDetail
}

// History refresh helper - matches the one provided by AppLayout but accessible here
const refreshHistory = async () => {
    if (appLayoutRef.value?.refreshHistory) {
        await appLayoutRef.value.refreshHistory()
    }
}

watch([
    reactLoading,
    reactProcessing,
    reactResults,
    reactError,
    reactSteps,
    reactValidationStep,
    reactExecutionStarted,
    reactIsExecuting,
    reactExecutionMessage,
    reactExecutionProgress,
    reactSubprocessProgress,
    reactGeneratedScript,
    reactTokenUsage,
    reactRateLimitWarning,
    reactDiscoveryComplete,
    reactSessionId,
    reactRunId,
    reactTurnNumber
], () => {
    syncActiveTurnFromStream()
}, { deep: true })

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

const legacyResponseHasContent = computed(() => {
    const response = currentResponse.value
    if (!response) return false
    if (response.type === MessageType.ERROR) return Boolean(response.content)
    if (Array.isArray(response.content)) return response.content.length > 0
    return Boolean(response.content)
})

const legacyTurnVisible = computed(() => {
    return !isReActMode.value && hasResults.value && (Boolean(lastQuestion.value) || legacyResponseHasContent.value || isLoading.value)
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
    if (activeTurnScrollFrameId !== null) {
        window.cancelAnimationFrame(activeTurnScrollFrameId)
        activeTurnScrollFrameId = null
    }
    transcriptTurnElements.clear()
    window.removeEventListener('tako:select-history', handleSidebarSelectEvent)
    window.removeEventListener('tako:new-session', handleNewSessionEvent)
})

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

const parseApiTimestamp = (rawTimestamp) => {
    if (!rawTimestamp) return null

    const timestamp = String(rawTimestamp).trim()
    if (!timestamp) return null

    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp)
    const normalizedTimestamp = hasTimezone ? timestamp : `${timestamp}Z`
    const parsedDate = new Date(normalizedTimestamp)

    return Number.isNaN(parsedDate.getTime()) ? null : parsedDate
}

const formatTurnTimestamp = (turn) => {
    const rawTimestamp = turn.completedAt || turn.updatedAt || turn.startedAt
    if (!rawTimestamp) return 'Now'

    const timestamp = parseApiTimestamp(rawTimestamp)
    if (!timestamp) return 'Now'

    const now = new Date()
    if (timestamp.toDateString() === now.toDateString()) {
        return timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    return timestamp.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const formatTurnStatus = (turn) => {
    const statusValue = turn.completionMode || turn.status || 'active'
    return String(statusValue)
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase())
}

const formatResultCount = (count, isPartial = false) => {
    const label = `${count} result${count === 1 ? '' : 's'}`
    return isPartial ? `${label} partial` : label
}

const getTurnSummary = (turn) => {
    if (turn.finalResponseSummary) {
        return cleanSummaryText(turn.finalResponseSummary)
    }

    if (turn.results) {
        if (turn.results.display_type === 'markdown' && typeof turn.results.content === 'string') {
            const summary = cleanSummaryText(turn.results.content)
            return summary ? summary.slice(0, 240) : 'Generated a direct answer.'
        }

        if (turn.resultCount === 0) {
            return 'No matching results found.'
        }

        if (turn.resultCount !== null && turn.resultCount !== undefined) {
            return `Returned ${formatResultCount(turn.resultCount, turn.isPartialResult)}.`
        }

        return 'Completed with structured results.'
    }

    if (turn.error) {
        return 'This turn failed before producing a final result.'
    }

    if (turn.isActive) {
        return turn.executionMessage || 'Working through this request.'
    }

    if (turn.status === 'created') {
        return 'Preparing this turn.'
    }

    return 'No summary available yet.'
}

const showLivePanelsForTurn = (turn) => {
    return turn.isActive && isReActMode.value && (reactLoading.value || reactSteps.value.length > 0 || reactExecutionStarted.value)
}

const turnStatusClass = (turn) => {
    if (turn.error || turn.status === 'failed') {
        return 'turn-status-pill-error'
    }

    if (turn.status === 'completed') {
        return 'turn-status-pill-success'
    }

    if (turn.isActive || turn.status === 'running' || turn.status === 'created') {
        return 'turn-status-pill-active'
    }

    return 'turn-status-pill-muted'
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

const ensureAuthenticatedSession = async () => {
    try {
        const authCheckResponse = await fetch('/api/auth/check', {
            method: 'GET',
            credentials: 'include'
        })

        if (await handleAuthError(authCheckResponse.status)) {
            return false
        }

        if (!authCheckResponse.ok) {
            throw new Error(`Authentication check failed with status ${authCheckResponse.status}`)
        }

        return true
    } catch (error) {
        console.error('Failed to validate authentication before query submission:', error)
        throw error
    }
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
    sessionLoadRequestId += 1
    userInput.value = ''
    lastQuestion.value = ''
    activeSessionId.value = null
    activeSessionTitle.value = ''
    pendingSessionTitle.value = ''
    conversationTurns.value = []
    sessionViewLoading.value = false
    sessionViewError.value = null
    sessionHydrationLoaded.value = 0
    sessionHydrationTotal.value = 0
    activeTurnKey.value = null
    window.dispatchEvent(new CustomEvent('tako:conversation-reset'))
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

    try {
        const isSessionValid = await ensureAuthenticatedSession()
        if (!isSessionValid) {
            return
        }
    } catch (error) {
        reactError.value = error.message || 'Failed to validate session'
        return
    }

    // Apply full sanitization before sending query
    const rawQuery = userInput.value.trim()
    const sanitizedQuery = sanitizeQuery(rawQuery, { maxLength: 2000 })
    const shouldAnimateDock = !hasResults.value
    const composerRect = shouldAnimateDock ? searchWrapperRef.value?.getBoundingClientRect() ?? null : null

    clearHomeRevealTimer()
    isReturningHome.value = false
    activeTurnKey.value = null

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
            const pid = await startReActProcess(sanitizedQuery, activeSessionId.value)
            if (pid) {
                registerActiveTurn(sanitizedQuery, 'user')
                await connectReActStream(pid)
                // History refresh will be triggered by watch on reactLoading
            }
            isLoading.value = false
            return
        }

        // Tako flow (existing)
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

const handleSidebarSelectEvent = async (event) => {
    const item = event.detail

    if (item?.kind === 'session' && item.session_id) {
        if (reactLoading.value || reactProcessing.value) {
            cancelReAct()
            isLoading.value = false
        }

        try {
            await loadConversationSession(item.session_id, {
                title: item.title || ''
            })
        } catch (error) {
            console.error('Failed to load selected conversation:', error)
        }
        return
    }

    if (item?.query_text) {
        userInput.value = sanitizeQuery(item.query_text)
        nextTick(() => {
            autoResizeTextarea()
            if (searchTextarea.value) {
                searchTextarea.value.focus()
            }
        })
    }
}

const handleNewSessionEvent = () => {
    resetInterface()
}

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
        window.addEventListener('tako:select-history', handleSidebarSelectEvent)
        window.addEventListener('tako:new-session', handleNewSessionEvent)
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
    bottom: 72px;
    left: 32px;
    right: 32px;
    width: auto;
    max-width: 760px;
    padding-bottom: 0;
    z-index: 90;
    margin-left: auto;
    margin-right: auto;
}

/* Adjust horizontal position when sidebar is expanded */
.sidebar-expanded .composer-shell.moved {
    left: calc(var(--sidebar-width) + 32px);
    right: 32px;
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
    width: min(var(--turn-content-max-width), 100%);
    margin: 24px auto 20px;
    display: flex;
    justify-content: flex-end;
    position: relative;
    z-index: 40; /* Lower than search container but higher than results */
}

.transcript-shell {
    --turn-content-max-width: 900px;
    max-width: var(--max-width);
    width: calc(100% - 40px);
    margin: 0 auto 176px;
    position: relative;
    isolation: isolate;
    min-height: 280px;
    display: flex;
    flex-direction: column;
    gap: 18px;
}

.session-load-overlay {
    position: absolute;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 72px 20px 24px;
    border-radius: 24px;
    background: rgba(247, 250, 252, 0.58);
    backdrop-filter: blur(12px);
}

.session-load-dialog {
    width: min(100%, 440px);
    padding: 18px;
    border-radius: 18px;
    border: 1px solid rgba(15, 23, 42, 0.08);
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.session-load-header {
    display: flex;
    align-items: center;
    gap: 14px;
}

.session-load-icon {
    width: 40px;
    height: 40px;
    flex-shrink: 0;
    border-radius: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: rgba(var(--primary-rgb), 0.08);
    border: 1px solid rgba(var(--primary-rgb), 0.1);
}

.session-load-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.session-load-eyebrow {
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
}

.session-load-title {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-primary);
    font-size: 16px;
    font-weight: 600;
    line-height: 1.3;
}

.session-load-progress-block {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.session-load-progress-copy {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 500;
}

.session-load-progress-muted {
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 700;
}

.transcript-session-bar {
    width: calc(100% - 40px);
    max-width: 100%;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

.transcript-session-label {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.transcript-session-label-caption {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
}

.transcript-session-label-title {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
}

.transcript-state-card {
    width: 100%;
    padding: 20px 22px;
    border-radius: 16px;
    border: 1px solid var(--border-color);
    background: rgba(255, 255, 255, 0.92);
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.5;
}

.transcript-state-card-error {
    color: #b42318;
    border-color: rgba(180, 35, 24, 0.18);
    background: rgba(180, 35, 24, 0.05);
}

.transcript-list {
    display: flex;
    flex-direction: column;
    gap: 24px;
}

.transcript-turn {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.transcript-turn.is-active {
    scroll-margin-top: 96px;
}

.transcript-question-header {
    margin: 0 auto;
    width: calc(100% - 40px);
    max-width: 100%;
}

.transcript-question-header .question-header {
    width: fit-content;
    max-width: 100%;
    justify-content: flex-start;
    align-items: center;
    margin-left: auto;
}

.question-copy {
    display: flex;
    flex-direction: column;
    gap: 0;
    min-width: 0;
    flex: 1;
}

.transcript-react-panels {
    margin-bottom: 0;
}

.transcript-results {
    margin-top: 0;
    margin-bottom: 0 !important;
}

.turn-summary-card {
    width: 100%;
    max-width: var(--turn-content-max-width);
    margin: 0 auto;
    padding: 18px 20px;
    border-radius: 16px;
    border: 1px solid var(--border-color);
    background: rgba(255, 255, 255, 0.9);
    box-shadow: none;
}

.turn-loading-card {
    width: 100%;
    max-width: var(--turn-content-max-width);
    margin: 0 auto;
    padding: 18px 20px;
    border-radius: 16px;
    border: 1px solid var(--border-color);
    background: rgba(255, 255, 255, 0.84);
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.turn-summary-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
}

@media (max-width: 640px) {
    .session-load-overlay {
        padding: 64px 12px 18px;
    }

    .session-load-dialog {
        padding: 16px;
        border-radius: 16px;
    }

    .transcript-session-bar {
        align-items: flex-start;
        flex-direction: column;
    }
}

.turn-status-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid rgba(15, 23, 42, 0.12);
    background: rgba(15, 23, 42, 0.04);
    color: var(--text-secondary);
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
}

.turn-status-pill-active {
    color: #0f766e;
    border-color: rgba(15, 118, 110, 0.16);
    background: rgba(15, 118, 110, 0.08);
}

.turn-status-pill-success {
    color: #1d4ed8;
    border-color: rgba(29, 78, 216, 0.16);
    background: rgba(29, 78, 216, 0.08);
}

.turn-status-pill-error {
    color: #b42318;
    border-color: rgba(180, 35, 24, 0.16);
    background: rgba(180, 35, 24, 0.08);
}

.turn-status-pill-muted {
    color: var(--text-muted);
    border-color: rgba(15, 23, 42, 0.1);
    background: rgba(15, 23, 42, 0.03);
}

.turn-summary-text {
    margin: 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.6;
}

.turn-error-text {
    margin: 10px 0 0;
    color: #b42318;
    font-size: 13px;
    line-height: 1.5;
}

.question-header {
    background-color: var(--primary);
    color: white;
    padding: 10px 16px;
    border-radius: 10px;
    width: fit-content;
    max-width: 88%;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 14px;
    line-height: 1.4;
    display: flex;
    align-items: center;
    gap: 10px;
    box-shadow: none;
}

.question-text {
    font-weight: 500;
    color: white;
}

.question-timestamp {
    font-size: 11px;
    opacity: 0.78;
    color: rgba(255, 255, 255, 0.9);
    margin-left: 6px;
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
        bottom: 20px;
        left: 16px;
        right: 16px;
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
        bottom: 16px;
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
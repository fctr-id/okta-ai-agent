/**
 * useReactStream.js - Composable for ReAct Agent SSE Streaming
 * 
 * Simplified SSE handler for One-ReAct agent execution.
 * Handles discovery steps, token usage, and final results.
 */

import { ref, watch } from 'vue'
import { useAuth } from './useAuth'

// Use relative URL to go through Vite proxy
const API_BASE_URL = ''

export function useReactStream() {
    const auth = useAuth()
    
    // Centralized auth error handler - follows pattern from useSync.js
    const handleAuthError = async (status) => {
        if (status === 401 || status === 403) {
            console.warn(`[useReactStream] Authentication error (${status}), logging out and redirecting`)
            
            try {
                // Clean up auth state
                await auth.logout()
                
                // Force navigation after logout completes
                setTimeout(() => {
                    window.location.href = '/login'
                }, 100)
            } catch (err) {
                console.error('[useReactStream] Error during logout:', err)
                // Force navigation even if logout fails
                window.location.href = '/login'
            }
            return true
        }
        return false
    }
    
    // State
    const isLoading = ref(false)
    const isProcessing = ref(false)
    const error = ref(null)
    const currentProcessId = ref(null)
    
    // Discovery state
    const currentStep = ref('')
    const discoverySteps = ref([])
    const isDiscoveryComplete = ref(false)
    
    // Execution state
    const validationStep = ref(null)
    const executionStarted = ref(false)
    const isExecuting = ref(false)
    const executionMessage = ref('')
    const executionProgress = ref(0)
    const subprocessProgress = ref([])
    const rateLimitWarning = ref(0) // Countdown in seconds
    const generatedScript = ref(null) // Generated script code
    
    // Results
    const results = ref(null)
    const tokenUsage = ref(null)
    
    // SSE connection
    let eventSource = null
    
    /**
     * Start ReAct process
     */
    const startProcess = async (query) => {
        console.log('[useReactStream] startProcess called with query:', query)
        
        // CRITICAL: Close any existing EventSource before starting new query
        if (eventSource) {
            console.log('[useReactStream] Closing previous EventSource before new query')
            closeStream()
        }
        
        isLoading.value = true
        error.value = null
        discoverySteps.value = []
        isDiscoveryComplete.value = false
        validationStep.value = null
        executionStarted.value = false
        isExecuting.value = false
        executionMessage.value = ''
        executionProgress.value = 0
        subprocessProgress.value = []
        rateLimitWarning.value = 0
        generatedScript.value = null
        results.value = null
        tokenUsage.value = null
        
        try {
            console.log('[useReactStream] Sending POST to:', `${API_BASE_URL}/api/react/start-react-process`)
            
            const response = await fetch(`${API_BASE_URL}/api/react/start-react-process`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ query })
            })
            
            // Handle session timeout (401/403)
            if (await handleAuthError(response.status)) {
                return null
            }
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`)
            }
            
            const data = await response.json()
            console.log('[useReactStream] Received process_id:', data.process_id)
            currentProcessId.value = data.process_id
            return data.process_id
            
        } catch (err) {
            console.error('[useReactStream] Failed to start ReAct process:', err)
            error.value = err.message
            isLoading.value = false
            return null
        }
    }
    
    /**
     * Start execution from saved script
     */
    const startScriptExecution = async (query, scriptCode) => {
        console.log('[useReactStream] startScriptExecution called')
        
        isLoading.value = true
        error.value = null
        discoverySteps.value = []
        isDiscoveryComplete.value = true // Skip discovery
        validationStep.value = null
        executionStarted.value = false
        isExecuting.value = false
        executionMessage.value = ''
        executionProgress.value = 0
        subprocessProgress.value = []
        rateLimitWarning.value = 0
        generatedScript.value = scriptCode
        results.value = null
        tokenUsage.value = null
        
        try {
            const response = await fetch(`${API_BASE_URL}/api/react/execute-script`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ query, script_code: scriptCode })
            })
            
            if (await handleAuthError(response.status)) {
                return null
            }
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`)
            }
            
            const data = await response.json()
            currentProcessId.value = data.process_id
            return data.process_id
            
        } catch (err) {
            console.error('[useReactStream] Failed to start script execution:', err)
            error.value = err.message
            isLoading.value = false
            return null
        }
    }
    
    /**
     * Connect to SSE stream
     */
    const connectToStream = async (processId) => {
        console.log('[useReactStream] connectToStream called with processId:', processId)
        
        if (!processId) {
            error.value = 'No process ID provided'
            return
        }
        
        // PRE-FLIGHT AUTH CHECK: Verify session before establishing SSE connection
        // EventSource doesn't expose HTTP status codes, so we check proactively
        try {
            const authCheck = await fetch(`${API_BASE_URL}/api/react/stream-react-updates?process_id=${processId}`, {
                method: 'HEAD',
                credentials: 'include'
            })
            
            if (await handleAuthError(authCheck.status)) {
                return
            }
        } catch (err) {
            // If HEAD fails, try to proceed with SSE anyway (might be unsupported)
            console.warn('[useReactStream] Pre-flight check failed, proceeding with SSE:', err)
        }
        
        isProcessing.value = true
        
        const url = `${API_BASE_URL}/api/react/stream-react-updates?process_id=${processId}`
        
        eventSource = new EventSource(url, {
            withCredentials: true
        })
        
        // Handle explicit close event from server
        eventSource.addEventListener('close', () => {
            console.log('[useReactStream] Server requested connection close')
            closeStream()
        })
        
        // Handle all messages with unified JSON format {type: "...", ...data}
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)
                
                // Route messages based on the 'type' field in the data
                switch (data.type) {
                    case 'STEP-START':
                        handleStepStart(data)
                        break
                    case 'STEP-END':
                        handleStepEnd(data)
                        break
                    case 'TOOL-CALL':
                        handleToolCall(data)
                        break
                    case 'STEP-PROGRESS':
                        handleStepProgress(data)
                        break
                    case 'STEP-TOKENS':
                        handleStepTokens(data)
                        break
                    case 'SCRIPT-GENERATED':
                        handleScriptGenerated(data)
                        break
                    case 'RESULT-METADATA':
                        handleResultMetadata(data)
                        break
                    case 'RESULT-BATCH':
                        handleResultBatch(data)
                        break
                    case 'COMPLETE':
                        handleComplete(data)
                        break
                    case 'DONE':
                        console.log('[useReactStream] Received DONE signal - closing stream')
                        isLoading.value = false
                        isProcessing.value = false
                        currentStep.value = ''
                        closeStream()
                        break
                    case 'ERROR':
                        handleError(data)
                        break
                }
            } catch (err) {
                console.error('[useReactStream] Error parsing SSE message:', err, event.data)
            }
        }
        
        // Single unified error handler
        eventSource.onerror = (err) => {
            console.error('[useReactStream] SSE error:', err)
            console.log('[useReactStream] ReadyState:', eventSource?.readyState)
            console.log('[useReactStream] Processing:', isProcessing.value, 'Results:', !!results.value)
            
            // Always close the stream on error
            closeStream()
            
            // Only treat as error if we haven't completed successfully
            if (isProcessing.value && !results.value) {
                error.value = 'Stream connection lost'
                isLoading.value = false
                isProcessing.value = false
            }
        }
    }
    
    /**
     * Handle STEP-START event
     */
    const handleStepStart = (data) => {
        console.log('[useReactStream] handleStepStart called')
        console.log('[useReactStream] STEP-START data:', data)
        
        currentStep.value = data.title
        
        // Mark previous step as complete when a new step starts
        if (discoverySteps.value.length > 0) {
            const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
            if (lastStep.status === 'in-progress') {
                lastStep.status = 'complete'
                console.log('[useReactStream] Auto-completed previous step:', lastStep.title)
            }
        }
        
        // Check if this is a synthesis/execution phase
        if (data.step === 'synthesis' || (typeof data.step === 'number' && (data.title.includes('Synthesize') || data.title.includes('Prepare final')))) {
            isDiscoveryComplete.value = true
        }
        
        // Track validation phase - STRICT CHECK
        if (data.step === 'validation') {
            validationStep.value = {
                status: 'in-progress',
                message: data.title,
                details: data.text
            }
        }
        
        // Track execution phase - STRICT CHECK
        if (data.step === 'execution') {
            executionStarted.value = true
            isExecuting.value = true
            executionMessage.value = data.title
        }
        
        // Add step to discovery list (Everything except validation and final execution)
        // We explicitly want to include "Executing test query" (which has numeric step)
        const isFinalPhase = data.step === 'validation' || data.step === 'execution';
        
        if (!isFinalPhase) {
            // Clean up the text - remove emojis and "STARTING:" prefix
            let cleanText = data.text || data.title
            if (cleanText) {
                // Strip all emojis first
                cleanText = cleanText.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '')
                // Remove "STARTING:" prefix
                cleanText = cleanText.replace(/^STARTING:\s*/i, '')
                // Also handle "STEP 1:", "STEP 2:", etc. for backward compatibility
                cleanText = cleanText.replace(/^STEP\s+\d+:\s*/i, '')
                cleanText = cleanText.replace(/^STEP\s+\d+\s*[-–—]\s*/i, '')
                // Trim any extra whitespace
                cleanText = cleanText.trim()
            }
            
            discoverySteps.value.push({
                id: `step-${discoverySteps.value.length + 1}`,
                step: data.step || discoverySteps.value.length + 1,
                title: cleanText || data.title, // Use cleaned text as title
                reasoning: cleanText || data.reasoning || null, // Use cleaned text as reasoning
                tool: data.tool || null, // Add tool info if available
                text: cleanText, // Store cleaned text
                status: 'in-progress',
                timestamp: new Date(data.timestamp * 1000).toLocaleTimeString(),
                tools: [] // Initialize empty tools array for future tool tracking
            })
        }
    }
    
    /**
     * Handle STEP-END event
     */
    const handleStepEnd = (data) => {
        // Check if this is a validation failure
        const isFailure = data.title && (data.title.toLowerCase().includes('failed') || data.title.toLowerCase().includes('error'))
        
        // Update validation if complete or failed
        if (validationStep.value && validationStep.value.status === 'in-progress') {
            validationStep.value.status = isFailure ? 'failed' : 'complete'
            if (isFailure) {
                validationStep.value.message = data.text || 'Validation failed'
            }
        }
        
        // Update last discovery step status
        const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
        if (lastStep && lastStep.status === 'in-progress') {
            lastStep.status = isFailure ? 'failed' : 'complete'
            // Append completion text to the step text or reasoning
            if (data.result) {
                lastStep.text = (lastStep.text ? lastStep.text + '\n\n' : '') + '✅ ' + data.result
            } else if (data.text) {
                lastStep.text = (lastStep.text ? lastStep.text + '\n\n' : '') + '✅ ' + data.text
            }
        }
        
        currentStep.value = ''
    }
    
    /**
     * Handle TOOL-CALL event
     */
    const handleToolCall = (data) => {
        // Add tool call to the most recent step's tools array
        const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
        if (lastStep && lastStep.tools) {
            lastStep.tools.push({
                name: data.tool_name || 'unknown',
                description: data.description || '',
                timestamp: new Date((data.timestamp || Date.now()) * 1000).toLocaleTimeString()
            })
        }
    }
    
    /**
     * Handle STEP-PROGRESS event (subprocess execution)
     */
    const handleStepProgress = (data) => {
        // Check if this is a rate limit event
        if (data.progress_type === 'rate_limit' && data.wait_seconds) {
            rateLimitWarning.value = data.wait_seconds
            executionMessage.value = data.message || `Rate limit - waiting ${data.wait_seconds}s`
            
            // Start countdown (client-side only, no backend load)
            const countdown = setInterval(() => {
                rateLimitWarning.value--
                if (rateLimitWarning.value <= 0) {
                    clearInterval(countdown)
                    rateLimitWarning.value = 0
                }
            }, 1000)
            
            return
        }
        
        // Ignore rate_limit_wait spam events - we already have the countdown running
        if (data.progress_type === 'rate_limit_wait') {
            return
        }
        
        // Regular progress event
        currentStep.value = `${data.entity}: ${data.current}/${data.total}`
        executionMessage.value = `Processing ${data.entity}...`
        
        // Calculate progress percentage
        if (data.total > 0) {
            executionProgress.value = Math.round((data.current / data.total) * 100)
        }
        
        // Track subprocess progress
        const existing = subprocessProgress.value.find(p => p.label === data.entity)
        if (existing) {
            existing.current = data.current
            existing.total = data.total
            existing.percent = data.total > 0 ? Math.round((data.current / data.total) * 100) : null
            existing.message = data.message || null
            existing.success = data.status === 'completed_max_reached' || data.status === 'completed'
        } else {
            subprocessProgress.value.push({
                label: data.entity,
                current: data.current,
                total: data.total,
                percent: data.total > 0 ? Math.round((data.current / data.total) * 100) : null,
                message: data.message || null,
                success: false
            })
        }
    }
    
    /**
     * Handle STEP-TOKENS event
     */
    const handleStepTokens = (data) => {
        tokenUsage.value = {
            input: data.input_tokens,
            output: data.output_tokens,
            total: data.total_tokens,
            requests: data.requests
        }
    }
    
    /**
     * Handle SCRIPT-GENERATED event
     */
    const handleScriptGenerated = (data) => {
        // Handle both direct and wrapped data structures
        const scriptCode = data.script_code || data.content?.script_code
        
        if (scriptCode) {
            generatedScript.value = scriptCode
        } else {
            console.warn('[useReactStream] No script_code found in SCRIPT-GENERATED event')
        }
    }
    
    /**
     * Handle RESULT-METADATA event (chunked streaming)
     */
    const handleResultMetadata = (data) => {
        // Initialize results with streaming structure
        results.value = {
            display_type: data.display_type || 'table',
            content: [],
            metadata: {
                isStreaming: true,
                streamingProgress: {
                    current: 0,
                    total: data.total_records,
                    chunksReceived: 0,
                    totalChunks: data.total_batches
                },
                execution_plan: data.execution_plan
            }
        }
        
        // Set headers if provided
        if (data.headers) {
            results.value.headers = data.headers
        }
    }
    
    /**
     * Handle RESULT-BATCH event (chunked streaming)
     */
    const handleResultBatch = (data) => {
        if (!results.value || !results.value.content) {
            results.value = {
                display_type: 'table',
                content: [],
                metadata: {
                    isStreaming: true,
                    streamingProgress: {
                        current: 0,
                        total: 0,
                        chunksReceived: 0,
                        totalChunks: data.total_batches
                    }
                }
            }
        }
        
        // Append batch data to content
        if (data.results && Array.isArray(data.results)) {
            results.value.content = [...results.value.content, ...data.results]
            
            // Update progress
            if (results.value.metadata?.streamingProgress) {
                results.value.metadata.streamingProgress = {
                    ...results.value.metadata.streamingProgress,
                    current: results.value.content.length,
                    chunksReceived: data.batch_number
                }
            }
        }
        
        // If final batch, mark streaming complete
        if (data.is_final) {
            if (results.value.metadata) {
                results.value.metadata.isStreaming = false
            }
            isExecuting.value = false
        }
    }
    
    /**
     * Handle COMPLETE event
     */
    const handleComplete = (data) => {
        console.log('[useReactStream] handleComplete called with:', data)
        console.log('[useReactStream] - display_type:', data.display_type)
        console.log('[useReactStream] - content type:', typeof data.content)
        console.log('[useReactStream] - content length:', data.content?.length || 'N/A')
        console.log('[useReactStream] - is_special_tool:', data.is_special_tool)
        
        // Mark discovery as complete
        isDiscoveryComplete.value = true
        
        // Mark execution as complete
        isExecuting.value = false
        
        // Mark last step as completed
        if (discoverySteps.value.length > 0) {
            const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
            if (lastStep.status === 'in-progress') {
                lastStep.status = 'complete'
            }
        }
        
        // Handle Markdown/Text content
        if (data.display_type === 'markdown') {
            console.log('[useReactStream] Setting markdown results with content:', data.content?.substring(0, 100))
            results.value = {
                display_type: 'markdown',
                content: data.content,
                metadata: {
                    isStreaming: false,
                    execution_plan: data.execution_plan,
                    ...data.metadata  // Merge backend metadata
                }
            }
            console.log('[useReactStream] Results set to:', results.value)
        }
        // Check if this is a chunked response (no results) or non-chunked (has results)
        else if (data.results && Array.isArray(data.results) && data.results.length > 0) {
            // Non-chunked response - small dataset, all data in COMPLETE event
            results.value = {
                display_type: data.display_type || 'table',
                content: data.results,
                metadata: {
                    isStreaming: false,
                    execution_plan: data.execution_plan,
                    count: data.count,
                    ...data.metadata  // Merge backend metadata (data_source_type, last_sync)
                }
            }
            
            // Add headers if provided
            if (data.headers) {
                results.value.headers = data.headers
            }
        } else {
            // Chunked response - just a completion signal, data already loaded via RESULT-BATCH events
            console.log('[useReactStream] Chunked response complete signal')
            if (results.value && results.value.metadata) {
                results.value.metadata.isStreaming = false
            }
        }
        
        // Don't close stream yet - wait for DONE event which comes after history save
        // isLoading.value = false
        // isProcessing.value = false
        // currentStep.value = ''
        // closeStream()
    }
    
    /**
     * Handle ERROR event
     */
    const handleError = (data) => {
        console.log('[useReactStream] ========== ERROR EVENT ==========')
        console.log('[useReactStream] Full data object:', JSON.stringify(data, null, 2))
        console.log('[useReactStream] data.error value:', data.error)
        console.log('[useReactStream] data.error type:', typeof data.error)
        
        // Set error from the event data
        error.value = data.error || 'An unexpected error occurred. Please try again.'
        
        console.log('[useReactStream] error.value set to:', error.value)
        console.log('[useReactStream] =====================================')
        
        isLoading.value = false
        isProcessing.value = false
        currentStep.value = ''
        
        // Mark validation step as failed if it exists
        if (validationStep.value && validationStep.value.status === 'in-progress') {
            validationStep.value.status = 'failed'
            validationStep.value.message = data.error
        }
        
        // Mark the last step as failed
        if (discoverySteps.value.length > 0) {
            const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
            if (lastStep.status === 'in-progress') {
                lastStep.status = 'failed'
            }
        }
        
        closeStream()
    }
    
    /**
     * Cancel process
     */
    const cancelProcess = async () => {
        if (!currentProcessId.value) return
        
        try {
            const response = await fetch(`${API_BASE_URL}/api/react/cancel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    process_id: currentProcessId.value
                })
            })
            
            // Handle session timeout (401/403)
            if (await handleAuthError(response.status)) {
                return
            }
            
            closeStream()
            isLoading.value = false
            isProcessing.value = false
            
        } catch (err) {
            console.error('Failed to cancel process:', err)
        }
    }
    
    /**
     * Close SSE connection
     */
    const closeStream = () => {
        if (eventSource) {
            console.log('[useReactStream] Closing EventSource (readyState:', eventSource.readyState, ')')
            eventSource.close()
            eventSource = null
            console.log('[useReactStream] EventSource closed and nulled')
        }
    }
    
    return {
        // State
        isLoading,
        isProcessing,
        error,
        currentStep,
        
        // Discovery state
        discoverySteps,
        isDiscoveryComplete,
        
        // Execution state
        validationStep,
        executionStarted,
        isExecuting,
        executionMessage,
        executionProgress,
        subprocessProgress,
        rateLimitWarning,
        generatedScript,
        
        // Results
        results,
        tokenUsage,
        
        // Methods
        startProcess,
        startScriptExecution,
        connectToStream,
        cancelProcess
    }
}

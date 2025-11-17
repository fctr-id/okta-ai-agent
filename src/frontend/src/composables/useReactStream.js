/**
 * useReactStream.js - Composable for ReAct Agent SSE Streaming
 * 
 * Simplified SSE handler for One-ReAct agent execution.
 * Handles discovery steps, token usage, and final results.
 */

import { ref } from 'vue'

// Use relative URL to go through Vite proxy
const API_BASE_URL = ''

export function useReactStream() {
    
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
     * Connect to SSE stream
     */
    const connectToStream = async (processId) => {
        console.log('[useReactStream] connectToStream called with processId:', processId)
        
        if (!processId) {
            error.value = 'No process ID provided'
            return
        }
        
        isProcessing.value = true
        
        const url = `${API_BASE_URL}/api/react/stream-react-updates?process_id=${processId}`
        console.log('[useReactStream] Connecting to SSE stream:', url)
        
        eventSource = new EventSource(url, {
            withCredentials: true
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
                        console.log('[useReactStream] STEP-PROGRESS event:', data)
                        handleStepProgress(data)
                        break
                    case 'STEP-TOKENS':
                        handleStepTokens(data)
                        break
                    case 'COMPLETE':
                        handleComplete(data)
                        break
                    case 'ERROR':
                        console.log('[useReactStream] ERROR event received:', data)
                        handleError(data)
                        break
                    default:
                        console.log('[useReactStream] Unknown message type:', data.type)
                        break
                }
            } catch (err) {
                console.error('[useReactStream] Error parsing SSE message:', err, event.data)
            }
        }
        
        eventSource.onerror = (err) => {
            console.error('[useReactStream] SSE error:', err)
            
            // Only treat as error if we haven't completed successfully
            if (isProcessing.value && !results.value) {
                error.value = 'Stream connection lost'
                isLoading.value = false
                isProcessing.value = false
            }
            
            // Close the stream (this is called when server closes connection normally too)
            closeStream()
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
        if (data.step === 'synthesis' || data.title.includes('Synthesize') || data.title.includes('Prepare final')) {
            isDiscoveryComplete.value = true
        }
        
        // Track validation phase
        if (data.step === 'validation' || data.title.includes('Validat')) {
            validationStep.value = {
                status: 'in-progress',
                message: data.title,
                details: data.text
            }
        }
        
        // Track execution phase
        if (data.step === 'execution' || data.title.includes('Execut')) {
            executionStarted.value = true
            isExecuting.value = true
            executionMessage.value = data.title
        }
        
        // Add step to discovery list (only if not execution/validation)
        // Check title content instead of step field which may not exist
        const isValidationOrExecution = 
            data.title?.toLowerCase().includes('validat') || 
            data.title?.toLowerCase().includes('execut') ||
            data.title?.toLowerCase().includes('prepare final') ||
            data.title?.toLowerCase().includes('synthesize')
        
        if (!isValidationOrExecution) {
            // Clean up the title - remove "STEP X:" prefix to show just the action
            let cleanTitle = data.title
            if (cleanTitle) {
                // Remove "STEP 1:", "STEP 2:", etc. from the beginning
                cleanTitle = cleanTitle.replace(/^STEP\s+\d+:\s*/i, '')
                // Also handle variations like "Step 1 -", "STEP 1 -", etc.
                cleanTitle = cleanTitle.replace(/^STEP\s+\d+\s*[-–—]\s*/i, '')
            }
            
            discoverySteps.value.push({
                id: `step-${discoverySteps.value.length + 1}`,
                step: data.step || discoverySteps.value.length + 1,
                title: cleanTitle || data.title, // Use cleaned title
                reasoning: data.text || data.reasoning || null, // Reasoning is in data.text field
                tool: data.tool || null, // Add tool info if available
                text: data.text,
                status: 'in-progress',
                timestamp: new Date(data.timestamp * 1000).toLocaleTimeString(),
                tools: [] // Initialize empty tools array for future tool tracking
            })
        }
        
        console.log('[useReactStream] discoverySteps updated:', discoverySteps.value)
    }
    
    /**
     * Handle STEP-END event
     */
    const handleStepEnd = (data) => {
        console.log('[useReactStream] handleStepEnd called')
        console.log('[useReactStream] STEP-END data:', data)
        
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
            lastStep.text = data.text // Update with completion text
            if (data.result) {
                lastStep.result = data.result
            }
        }
        
        currentStep.value = ''
    }
    
    /**
     * Handle TOOL-CALL event
     */
    const handleToolCall = (data) => {
        console.log('[useReactStream] handleToolCall called')
        console.log('[useReactStream] TOOL-CALL data:', data)
        
        // Add tool call to the most recent step's tools array
        const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
        if (lastStep && lastStep.tools) {
            lastStep.tools.push({
                name: data.tool_name || 'unknown',
                description: data.description || '',
                timestamp: new Date((data.timestamp || Date.now()) * 1000).toLocaleTimeString()
            })
            console.log('[useReactStream] Added tool to last step:', lastStep.title, 'Tool:', data.tool_name)
        } else {
            console.warn('[useReactStream] No active step to attach tool call to')
        }
    }
    
    /**
     * Handle STEP-PROGRESS event (subprocess execution)
     */
    const handleStepProgress = (data) => {
        console.log('[useReactStream] handleStepProgress called with data:', data)
        
        // Check if this is a rate limit event
        if (data.progress_type === 'rate_limit' && data.wait_seconds) {
            console.log('[useReactStream] Rate limit detected:', data.wait_seconds, 'seconds')
            rateLimitWarning.value = data.wait_seconds
            executionMessage.value = data.message || `Rate limit - waiting ${data.wait_seconds}s`
            
            // Start countdown
            const countdown = setInterval(() => {
                rateLimitWarning.value--
                console.log('[useReactStream] Rate limit countdown:', rateLimitWarning.value)
                if (rateLimitWarning.value <= 0) {
                    clearInterval(countdown)
                    rateLimitWarning.value = 0
                    console.log('[useReactStream] Rate limit countdown complete')
                }
            }, 1000)
            
            return
        }
        
        // Regular progress event
        console.log('[useReactStream] Regular progress event - entity:', data.entity)
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
        console.log('[useReactStream] handleStepTokens called')
        console.log('[useReactStream] STEP-TOKENS data:', data)
        
        tokenUsage.value = {
            input: data.input_tokens,
            output: data.output_tokens,
            total: data.total_tokens,
            requests: data.requests
        }
    }
    
    /**
     * Handle COMPLETE event
     */
    const handleComplete = (data) => {
        console.log('[useReactStream] handleComplete called')
        console.log('[useReactStream] COMPLETE data:', data)
        console.log('[useReactStream] data.results:', data.results)
        console.log('[useReactStream] data.results is array:', Array.isArray(data.results))
        console.log('[useReactStream] data.results length:', data.results?.length)
        console.log('[useReactStream] data.headers:', data.headers)
        
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
        
        // Store results with headers if provided
        if (data.results) {
            results.value = {
                display_type: 'table',
                content: data.results, // This is the array of results
                metadata: {
                    isStreaming: false,
                    execution_plan: data.execution_plan,
                    count: data.count
                }
            }
            
            // Include headers if provided by backend
            if (data.headers && Array.isArray(data.headers) && data.headers.length > 0) {
                results.value.metadata.headers = data.headers
                console.log('[useReactStream] Headers received from backend:', data.headers.length, 'columns')
            }
            
            console.log('[useReactStream] Results stored:')
            console.log('  - display_type:', results.value.display_type)
            console.log('  - content:', results.value.content)
            console.log('  - content is array:', Array.isArray(results.value.content))
            console.log('  - content length:', results.value.content?.length)
            console.log('  - metadata:', results.value.metadata)
        }
        
        isLoading.value = false
        isProcessing.value = false
        currentStep.value = ''
        
        closeStream()
    }
    
    /**
     * Handle ERROR event
     */
    const handleError = (data) => {
        console.log('[useReactStream] handleError called with:', data)
        error.value = data.error
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
            await fetch(`${API_BASE_URL}/api/react/cancel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    process_id: currentProcessId.value
                })
            })
            
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
            eventSource.close()
            eventSource = null
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
        
        // Results
        results,
        tokenUsage,
        
        // Methods
        startProcess,
        connectToStream,
        cancelProcess
    }
}

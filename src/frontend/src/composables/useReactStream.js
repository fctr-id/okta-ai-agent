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
                    case 'STEP-PROGRESS':
                        handleStepProgress(data)
                        break
                    case 'STEP-TOKENS':
                        handleStepTokens(data)
                        break
                    case 'COMPLETE':
                        handleComplete(data)
                        break
                    case 'ERROR':
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
        
        // Add step to list
        discoverySteps.value.push({
            step: data.step || discoverySteps.value.length + 1,
            title: data.title,
            text: data.text,
            status: 'running',
            timestamp: new Date(data.timestamp * 1000).toLocaleTimeString()
        })
        console.log('[useReactStream] discoverySteps updated:', discoverySteps.value)
    }
    
    /**
     * Handle STEP-END event
     */
    const handleStepEnd = (data) => {
        console.log('[useReactStream] handleStepEnd called')
        console.log('[useReactStream] STEP-END data:', data)
        
        // Update last step status
        const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
        if (lastStep) {
            lastStep.status = 'completed'
            lastStep.text = data.text // Update with completion text
        }
        
        currentStep.value = ''
    }
    
    /**
     * Handle STEP-PROGRESS event (subprocess execution)
     */
    const handleStepProgress = (data) => {
        // Update current step with progress
        currentStep.value = `${data.entity}: ${data.current}/${data.total}`
        
        // Update or add progress step
        const progressStep = discoverySteps.value.find(s => s.title === 'Executing Code')
        if (progressStep) {
            progressStep.text = `Processing ${data.entity}: ${data.current}/${data.total}`
            progressStep.progress = {
                current: data.current,
                total: data.total
            }
        }
    }
    
    /**
     * Handle STEP-TOKENS event
     */
    const handleStepTokens = (data) => {
        console.log('[useReactStream] handleStepTokens called')
        console.log('[useReactStream] STEP-TOKENS data:', data)
        
        tokenUsage.value = {
            inputTokens: data.input_tokens,
            outputTokens: data.output_tokens,
            totalTokens: data.total_tokens,
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
        
        // Mark last step as completed
        if (discoverySteps.value.length > 0) {
            const lastStep = discoverySteps.value[discoverySteps.value.length - 1]
            if (lastStep.status === 'running') {
                lastStep.status = 'completed'
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
        error.value = data.error
        isLoading.value = false
        isProcessing.value = false
        currentStep.value = ''
        
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
        discoverySteps,
        results,
        tokenUsage,
        
        // Methods
        startProcess,
        connectToStream,
        cancelProcess
    }
}

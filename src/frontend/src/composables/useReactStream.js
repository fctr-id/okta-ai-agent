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
        
        // Handle different event types
        eventSource.addEventListener('STEP-START', handleStepStart)
        eventSource.addEventListener('STEP-END', handleStepEnd)
        eventSource.addEventListener('STEP-PROGRESS', handleStepProgress)
        eventSource.addEventListener('STEP-TOKENS', handleStepTokens)
        eventSource.addEventListener('COMPLETE', handleComplete)
        eventSource.addEventListener('ERROR', handleError)
        
        // Generic message handler
        eventSource.onmessage = (event) => {
            console.log('SSE message:', event.data)
        }
        
        eventSource.onerror = (err) => {
            console.error('SSE error:', err)
            error.value = 'Stream connection lost'
            closeStream()
        }
    }
    
    /**
     * Handle STEP-START event
     */
    const handleStepStart = (event) => {
        const data = JSON.parse(event.data)
        
        currentStep.value = data.title
        
        // Add step to list
        discoverySteps.value.push({
            step: data.step || discoverySteps.value.length + 1,
            title: data.title,
            text: data.text,
            status: 'running',
            timestamp: new Date(data.timestamp * 1000).toLocaleTimeString()
        })
    }
    
    /**
     * Handle STEP-END event
     */
    const handleStepEnd = (event) => {
        const data = JSON.parse(event.data)
        
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
    const handleStepProgress = (event) => {
        const data = JSON.parse(event.data)
        
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
    const handleStepTokens = (event) => {
        const data = JSON.parse(event.data)
        
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
    const handleComplete = (event) => {
        const data = JSON.parse(event.data)
        
        // Store results
        if (data.results) {
            results.value = {
                display_type: 'table', // or 'markdown', 'json'
                content: data.results.results || [],
                metadata: {
                    headers: [], // Would be extracted from results
                    isStreaming: false,
                    execution_plan: data.results.execution_plan,
                    steps_taken: data.results.steps_taken
                }
            }
        }
        
        isLoading.value = false
        isProcessing.value = false
        currentStep.value = ''
        
        closeStream()
    }
    
    /**
     * Handle ERROR event
     */
    const handleError = (event) => {
        const data = JSON.parse(event.data)
        
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

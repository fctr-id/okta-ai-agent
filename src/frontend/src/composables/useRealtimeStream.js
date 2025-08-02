import { ref, reactive, toRefs, watch } from "vue";
import { useAuth } from "./useAuth";

/**
 * Composable for handling realtime Server-Sent Events (SSE) streaming
 * Used to connect to the backend realtime API endpoints and process streaming updates
 * @returns {Object} Methods and reactive state for SSE connection management
 */
export function useRealtimeStream() {
    // Authentication service
    const auth = useAuth();

    // Chunked result state for large responses
    const chunkedResults = ref({
        chunks: [],
        expectedChunks: 0,
        receivedChunks: 0,
        totalRecords: 0,
        isReceivingChunks: false
    });

    // Connection state
    const isLoading = ref(false);
    const isProcessing = ref(false);
    const isStreaming = ref(false);
    const error = ref(null);
    const activeEventSource = ref(null);
    const processId = ref(null);

    // Execution state tracking
    const execution = reactive({
        status: "idle", // idle, planning, executing, completed, error, cancelled
        planGenerated: false,
        currentStepIndex: -1,
        steps: [],
        results: null,
    });

    /**
     * Start a new query process
     * @param {string} query - The natural language query to process
     * @returns {Promise<string|null>} - The process ID or null if failed
     */
    const startProcess = async (query) => {
        if (!query?.trim()) return null;

        // Reset state
        isLoading.value = true;
        isProcessing.value = true;
        isStreaming.value = false;
        error.value = null;
        execution.status = "planning";
        execution.planGenerated = false;
        execution.currentStepIndex = -1;
        execution.results = null;

        // Reset chunked results state
        chunkedResults.value = {
            chunks: [],
            expectedChunks: 0,
            receivedChunks: 0,
            totalRecords: 0,
            isReceivingChunks: false
        };

        // Initialize with only the two bookend steps
        execution.steps = [
            {
                id: 'generate_plan',
                tool_name: 'generate_plan',
                reason: 'Analyzing query and generating execution plan',
                status: 'active', // Start with planning step active
            },
            {
                id: 'finalizing_results',
                tool_name: 'finalizing_results', 
                reason: 'Processing and formatting final results',
                status: 'pending',
            }
        ];

        try {
            const response = await fetch("/api/realtime/start-process", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                credentials: "include", // Include cookies for authentication
                body: JSON.stringify({ query: query.trim() }),
            });

            // Handle non-OK responses more explicitly
            if (!response.ok) {
                const errorText = await response.text();

                // Add explicit handling for 401 status
                if (response.status === 401) {
                    // console.log("Authentication expired, redirecting to login");
                    auth.logout(); // Update auth state
                    window.location = "/login"; // Force navigation to login
                    return null;
                }

                // Try to parse as JSON, fall back to text if that fails
                let errorMessage;
                try {
                    const errorData = JSON.parse(errorText);
                    errorMessage = errorData.detail || `Failed to start process: ${response.statusText}`;
                } catch (e) {
                    // If parsing fails, use the text directly
                    errorMessage = `Failed to start process: ${response.status} - ${errorText || response.statusText}`;
                }
                throw new Error(errorMessage);
            }

            // Parse successful response
            const data = await response.json();
            processId.value = data.process_id;

            if (data.plan) {
                // Don't override our bookend steps here - let step_plan_info handle the insertion
                execution.planGenerated = true;
            }

            return data.process_id;
        } catch (err) {
            console.error("Error in startProcess:", err);
            error.value = err.message || "Failed to start process";
            execution.status = "error";
            isProcessing.value = false;
            return null;
        } finally {
            isLoading.value = false;
        }
    };

    /**
     * Connect to the SSE stream for realtime updates
     * @param {string} id - The process ID to connect to
     * @returns {EventSource|null} - The EventSource instance or null if connection fails
     */
    const connectToStream = async (id) => {
        if (!id) {
            console.error("No process ID provided for stream connection");
            return null;
        }

        try {
            // Close any existing connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }

            // Create new EventSource connection
            const eventSourceUrl = `/api/realtime/stream-updates/${id}`;

            // Create EventSource - cookies will be sent automatically
            const eventSource = new EventSource(eventSourceUrl, {
                withCredentials: true, // This ensures cookies are sent with the request
            });
            activeEventSource.value = eventSource;
            isStreaming.value = true;

            // Handle connection open event
            eventSource.onopen = () => {
                execution.status = execution.planGenerated ? "executing" : "planning";
            };

            // Set up event handlers for different event types
            eventSource.addEventListener("plan_status", (event) => {
                // console.log("[EventSource] Received plan_status event:", event.data);
                handlePlanStatusEvent(event);
            });

            eventSource.addEventListener("phase_update", (event) => {
                // console.log("[EventSource] Received phase_update event:", event.data);
                handlePhaseUpdateEvent(event);
            });

            eventSource.addEventListener("step_status_update", (event) => {
                // console.log("[EventSource] Received step_status_update event:", event.data);
                handleStepStatusEvent(event);
            });

            eventSource.addEventListener("step_plan_info", (event) => {
                // console.log("[EventSource] Received step_plan_info event:", event.data);
                handleStepPlanInfoEvent(event);
            });

            eventSource.addEventListener("final_result", (event) => {
                handleFinalResultEvent(event);
            });

            eventSource.addEventListener("final_result_chunk", (event) => {
                console.log("[EventSource] Received final_result_chunk event:", event.data);
                handleFinalResultChunkEvent(event);
            });

            eventSource.addEventListener("plan_error", (event) => {
                // console.log("[EventSource] Received plan_error event:", event.data);
                handleErrorEvent(event);
            });

            eventSource.addEventListener("plan_cancelled", (event) => {
                // console.log("[EventSource] Received plan_cancelled event:", event.data);
                handleCancelledEvent(event);
            });

            // Handle general messages (some backends send untyped messages)
            eventSource.onmessage = (event) => {
                // console.log("[EventSource] Received generic onmessage event:", event.data);
                try {
                    const data = JSON.parse(event.data);
                    // Handle based on message content structure
                    if (data.plan)
                        handlePlanStatusEvent({ data: JSON.stringify({ status: "generated", plan: data.plan }) });
                    else if (data.phase) handlePhaseUpdateEvent({ data: JSON.stringify({ phase: data.phase }) });
                    else if (data.result) handleFinalResultEvent({ data: JSON.stringify({ result: data.result }) });
                    // else console.log("[EventSource] Unhandled generic message type:", data);
                } catch (err) {
                    console.error("[EventSource] Error handling generic message:", err);
                }
            };

            // Handle connection errors
            eventSource.onerror = (e) => {
                console.error("EventSource error:", e);
                handleConnectionError(e, eventSource);
            };

            return eventSource;
        } catch (err) {
            console.error("Error connecting to event stream:", err);
            error.value = err.message || "Failed to connect to event stream. Please try again.";
            execution.status = "error";
            isStreaming.value = false;
            isProcessing.value = false;
            return null;
        }
    };

    /**
     * Handle plan status events
     */

    const handlePlanStatusEvent = (event) => {
        try {
            const data = JSON.parse(event.data);

            // Handle rich plan details when available
            if (data.plan_details) {
                execution.planGenerated = true;
                const steps = data.plan_details.steps_summary || [];
                execution.steps = steps.map((step) => ({
                    id: step.step_index,
                    tool_name: step.tool_name,
                    reason: step.reason,
                    status: "pending",
                }));
                execution.status = "executing";
                return;
            }

            // Handle simpler plan status updates
            if (
                data.status === "generated" ||
                data.status === "starting_execution" ||
                data.status === "running_execution"
            ) {
                execution.planGenerated = true;
                execution.status = "executing";
            }
        } catch (err) {
            console.error("Error processing plan status event:", err);
        }
    };

    /**
     * Handle step status update events
     */
    const handleStepStatusEvent = (event) => {
        try {
            const data = JSON.parse(event.data);

            // Handle Modern Execution Manager format (new)
            if (data.step_number !== undefined && data.step_name && data.status) {
                // Map step numbers to our inserted steps (accounting for generate_plan at index 0)
                // Backend step 1 -> frontend index 1 (after generate_plan)
                const stepIndex = data.step_number; // Keep 1-based since generate_plan is at index 0
                
                if (stepIndex >= 1 && stepIndex < execution.steps.length - 1) { // Exclude finalizing_results (last step)
                    // Map backend status to frontend status
                    const statusMap = {
                        'running': 'active',
                        'completed': 'completed', 
                        'error': 'error'
                    };
                    
                    const frontendStatus = statusMap[data.status] || data.status;
                    execution.steps[stepIndex].status = frontendStatus;
                    
                    // Handle ERROR status - immediately stop execution and show error
                    if (data.status === 'error') {
                        console.error('Step failed:', data);
                        execution.status = "error";
                        execution.currentStepIndex = stepIndex;
                        
                        // Set error message for user display
                        const stepName = execution.steps[stepIndex].tool_name || `Step ${stepIndex}`;
                        error.value = `Execution failed at ${stepName}. The system encountered an error and cannot continue.`;
                        
                        // Mark remaining steps as disabled
                        for (let i = stepIndex + 1; i < execution.steps.length; i++) {
                            if (execution.steps[i].status === "pending" || execution.steps[i].status === "active") {
                                execution.steps[i].status = "pending";
                                execution.steps[i].disabled = true;
                            }
                        }
                        
                        // Stop processing
                        isProcessing.value = false;
                        isStreaming.value = false;
                        
                        return;
                    }
                    
                    // Update current step index if step is running
                    if (data.status === 'running') {
                        execution.currentStepIndex = stepIndex;
                        execution.status = "executing";
                    }
                    
                    // Check if all execution steps are completed (excluding bookends)
                    if (data.status === 'completed') {
                        const executionSteps = execution.steps.slice(1, -1); // Exclude generate_plan and finalizing_results
                        const allExecutionStepsCompleted = executionSteps.every(step => step.status === 'completed');
                        
                        if (allExecutionStepsCompleted) {
                            // All execution steps are done, activate finalizing_results
                            const finalizingStepIndex = execution.steps.length - 1;
                            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                                execution.steps[finalizingStepIndex].status = 'active';
                                execution.currentStepIndex = finalizingStepIndex;
                            }
                        }
                    }
                }
                return;
            }

            // Handle legacy format (existing)
            const stepIndex = data.step_index;

            // First check if this is an error status update
            if (data.operation_status === "error") {
                // Mark the step as error immediately
                if (stepIndex >= 0 && stepIndex < execution.steps.length) {
                    console.error('Legacy operation failed:', data);
                    execution.steps[stepIndex].status = "error";
                    execution.steps[stepIndex].error = true; // Explicitly set error flag for v-stepper-item
                    execution.steps[stepIndex].error_message = data.error_message;

                    // Also update execution status to prevent finalizing steps from going green
                    execution.status = "error";
                    execution.currentStepIndex = stepIndex;
                    
                    // Set error message for user display
                    const stepName = execution.steps[stepIndex].tool_name || `Step ${stepIndex}`;
                    error.value = `Execution failed at ${stepName}. The system encountered an error and cannot continue.`;

                    // Mark any remaining future steps as cancelled/disabled
                    for (let i = stepIndex + 1; i < execution.steps.length; i++) {
                        if (execution.steps[i].status === "pending" || execution.steps[i].status === "active") {
                            execution.steps[i].status = "pending";
                            execution.steps[i].disabled = true;
                        }
                    }
                    
                    // Stop processing
                    isProcessing.value = false;
                    isStreaming.value = false;
                }
                return;
            }

            // Handle normal status updates for valid steps
            if (stepIndex >= 0 && stepIndex < execution.steps.length) {
                // Map statuses correctly
                if (data.status === "running") {
                    execution.steps[stepIndex].status = "active";
                    execution.currentStepIndex = stepIndex;
                } else if (data.status === "completed") {
                    // Handle completion status outside the 'running' condition
                    setTimeout(() => {
                        execution.steps[stepIndex].status = "completed";
                        if (data.result_summary) {
                            execution.steps[stepIndex].result_summary = data.result_summary;
                        }
                    }, 0);
                } else {
                    // For other statuses, map correctly
                    const statusMap = {
                        running: "active",
                        completed: "completed",
                        error: "error",
                    };
                    execution.steps[stepIndex].status = statusMap[data.status] || data.status;
                }
            }
        } catch (err) {
            console.error("Error processing step status event:", err);
        }
    };

    /**
     * Handle step plan info events - INSERT steps between generate_plan and finalizing_results
     */
    const handleStepPlanInfoEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            // DEBUG: Log the received step plan info
            // console.log("[handleStepPlanInfoEvent] Received step_plan_info event:", data);
            // console.log("[handleStepPlanInfoEvent] Current execution.steps before:", execution.steps);

            if (data.steps && Array.isArray(data.steps)) {
                // console.log(`[handleStepPlanInfoEvent] Processing ${data.steps.length} steps from plan`);
                execution.planGenerated = true;
                
                // Complete the generate_plan step
                if (execution.steps[0] && execution.steps[0].id === 'generate_plan') {
                    execution.steps[0].status = 'completed';
                    // console.log("[handleStepPlanInfoEvent] Completed generate_plan step");
                }

                // Create the new execution steps from the plan
                const newExecutionSteps = data.steps.map((step, index) => {
                    const newStep = {
                        id: `step_${index + 1}`,
                        tool_name: step.tool_name,
                        operation: step.operation,
                        entity: step.entity,
                        reason: step.query_context || 'Processing data',
                        status: "pending",
                        critical: step.critical
                    };
                    // console.log(`[handleStepPlanInfoEvent] Created step ${index + 1}:`, newStep);
                    return newStep;
                });

                // Insert the new steps between generate_plan (index 0) and finalizing_results (last)
                // Keep generate_plan, insert new steps, keep finalizing_results
                const generatePlanStep = execution.steps[0];
                const finalizingResultsStep = execution.steps[execution.steps.length - 1];
                
                execution.steps = [
                    generatePlanStep,
                    ...newExecutionSteps,
                    finalizingResultsStep
                ];

                // console.log("[handleStepPlanInfoEvent] Updated execution.steps:", execution.steps);
                execution.status = "executing";
                // console.log("[handleStepPlanInfoEvent] Set execution status to 'executing'");
            } else {
                console.warn("[handleStepPlanInfoEvent] No valid steps array found in data:", data);
            }
        } catch (err) {
            console.error("[handleStepPlanInfoEvent] Error processing step plan info event:", err);
            console.error("[handleStepPlanInfoEvent] Event data:", event.data);
        }
    };

    /**
     * Handle chunked final result events - Stream table updates progressively
     */
    const handleFinalResultChunkEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const chunkInfo = data.chunk_info;
            
            // console.log(`[handleFinalResultChunkEvent] Received chunk ${chunkInfo.chunk_number}/${chunkInfo.total_chunks} (${chunkInfo.chunk_size} records)`);
            
            // First chunk - initialize chunked result state and show initial table
            if (chunkInfo.chunk_number === 1) {
                chunkedResults.value = {
                    chunks: [],
                    expectedChunks: chunkInfo.total_chunks,
                    receivedChunks: 0,
                    totalRecords: chunkInfo.total_size,
                    isReceivingChunks: true,
                    baseData: data // Store non-content data for final assembly
                };
                
                // Activate the finalizing_results step
                const finalizingStepIndex = execution.steps.length - 1;
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'active';
                    execution.currentStepIndex = finalizingStepIndex;
                }
                
                // console.log(`[handleFinalResultChunkEvent] Starting chunked reception: expecting ${chunkInfo.total_chunks} chunks with ${chunkInfo.total_size} total records`);
                
                // NEW: Show initial empty table with streaming indicator
                const formattedResponse = data.formatted_response || {};
                execution.results = {
                    content: [], // Start with empty array
                    display_type: formattedResponse.display_type || data.display_type || "table",
                    headers: formattedResponse.headers || [], // Include headers for chunked streaming
                    metadata: {
                        ...formattedResponse.metadata,
                        isStreaming: true,
                        streamingProgress: {
                            current: 0,
                            total: chunkInfo.total_size,
                            chunksReceived: 0,
                            totalChunks: chunkInfo.total_chunks
                        }
                    }
                };
            }
            
            // NEW: Add chunk data to existing results and update progressively
            if (data.formatted_response?.content) {
                chunkedResults.value.chunks.push(...data.formatted_response.content);
                chunkedResults.value.receivedChunks++;
                
                // Update the table content in real-time
                execution.results.content = [...chunkedResults.value.chunks]; // Spread to trigger reactivity
                
                // Update streaming progress
                execution.results.metadata.streamingProgress = {
                    current: chunkedResults.value.chunks.length,
                    total: chunkedResults.value.totalRecords,
                    chunksReceived: chunkedResults.value.receivedChunks,
                    totalChunks: chunkedResults.value.expectedChunks
                };
                
                // console.log(`[handleFinalResultChunkEvent] Updated table: ${chunkedResults.value.chunks.length}/${chunkedResults.value.totalRecords} records`);
            }
            
            // If this is the final chunk or we've received all chunks
            if (chunkInfo.is_final_chunk || chunkedResults.value.receivedChunks >= chunkedResults.value.expectedChunks) {
                // console.log(`[handleFinalResultChunkEvent] All chunks received, finalizing streaming table`);
                
                // Mark streaming as complete
                execution.results.metadata.isStreaming = false;
                delete execution.results.metadata.streamingProgress; // Remove progress indicator
                
                // Complete the finalizing_results step
                setTimeout(() => {
                    const finalizingStepIndex = execution.steps.length - 1;
                    if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                        execution.steps[finalizingStepIndex].status = 'completed';
                    }
                    
                    execution.status = "completed";
                    isProcessing.value = false;
                    isStreaming.value = false;
                    
                    // Close EventSource after completion
                    if (activeEventSource.value) {
                        activeEventSource.value.close();
                        activeEventSource.value = null;
                    }
                }, 300); // Brief delay to show completion
                
                // Reset chunk state
                chunkedResults.value.isReceivingChunks = false;
            }
            
        } catch (err) {
            console.error("[handleFinalResultChunkEvent] Error processing final result chunk:", err);
            console.error("[handleFinalResultChunkEvent] Event data:", event.data);
            
            // Reset chunk state on error
            chunkedResults.value.isReceivingChunks = false;
            execution.status = "error";
            error.value = "Failed to process chunked response";
        }
    };

    /**
     * Handle final result events - Activate finalizing_results step and then complete
     */
    const handleFinalResultEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            // If we're receiving chunks, this might be the final completion signal
            if (chunkedResults.value.isReceivingChunks) {
                console.log("[handleFinalResultEvent] Received final_result during chunked streaming - completing");

                // Force completion of chunked streaming
                execution.results.metadata.isStreaming = false;
                delete execution.results.metadata.streamingProgress;
                
                // Complete the finalizing step
                const finalizingStepIndex = execution.steps.length - 1;
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'completed';
                }
                
                execution.status = "completed";
                isProcessing.value = false;
                isStreaming.value = false;
                chunkedResults.value.isReceivingChunks = false;
                
                // Close EventSource
                if (activeEventSource.value) {
                    activeEventSource.value.close();
                    activeEventSource.value = null;
                }
                return;
            }
            
            // Close EventSource for regular (non-chunked) results
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
            
            // Activate the finalizing_results step (last step)
            const finalizingStepIndex = execution.steps.length - 1;
            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                execution.steps[finalizingStepIndex].status = 'active';
                execution.currentStepIndex = finalizingStepIndex;
            }
            
            // Small delay to show the finalizing step as active, then complete it
            setTimeout(() => {
                // Complete the finalizing_results step
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'completed';
                }
                
                // The Results Formatter output is in data.formatted_response
                const formattedResponse = data.formatted_response || {};
                const agentDisplayMetadata = formattedResponse.metadata || data.metadata || data.display_hints || {};

                // Format the result to the expected shape for the frontend
                execution.results = {
                    content: formattedResponse.content || data.content || data.result_content || "", // Try formatted_response first
                    display_type: formattedResponse.display_type || data.display_type || "markdown",
                    headers: formattedResponse.headers || [], // Include headers for Vuetify table display
                    metadata: agentDisplayMetadata, // This will now correctly pass headers, totalItems, etc.
                };

                execution.status = data.status || "completed"; // Use status from data if available
                isProcessing.value = false;
                isStreaming.value = false; // Ensure streaming is also marked as false
                
            }, 500); // Show finalizing step as active for 500ms
            
        } catch (err) {
            console.error("Error processing final result event:", err);
            // Optionally, set an error state in the execution object
            execution.error = "Failed to process final result.";
            execution.status = "error";
            isProcessing.value = false;
            isStreaming.value = false;
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        }
    };

    /**
     * Handle phase update events - Detect results formatter phase
     */
    const handlePhaseUpdateEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            const newPhase = data.phase || execution.status;
            
            // Check if this indicates the start of results formatting
            if (newPhase.toLowerCase().includes('results') || 
                newPhase.toLowerCase().includes('formatting') ||
                newPhase.toLowerCase().includes('finalizing')) {
                
                // Activate the finalizing_results step
                const finalizingStepIndex = execution.steps.length - 1;
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'active';
                    execution.currentStepIndex = finalizingStepIndex;
                }
            }
            
            execution.status = newPhase;
        } catch (err) {
            console.error("Error processing phase update event:", err);
        }
    };

    /**
     * Handle error events
     */
    const handleErrorEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            error.value = data.error || data.message || "An error occurred during execution";
            execution.status = "error";
            isProcessing.value = false;
            isStreaming.value = false;

            // Close the connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        } catch (err) {
            console.error("Error processing error event:", err);
        }
    };

    /**
     * Handle cancelled events
     */
    const handleCancelledEvent = (event) => {
        execution.status = "cancelled";
        isProcessing.value = false;
        isStreaming.value = false;

        // Close the connection
        if (activeEventSource.value) {
            activeEventSource.value.close();
            activeEventSource.value = null;
        }
    };

    /**
     * Handle connection errors
     */
    const handleConnectionError = (e, eventSource) => {
        console.error("Connection error in EventSource:", e);

        // If we're already completed, cancelled, or have an error, this is expected connection closure
        // Also check if we have results (final processing phase) or finalizing_results step is active
        const finalizingStepIndex = execution.steps.length - 1;
        const isFinalizingActive = execution.steps[finalizingStepIndex]?.status === 'active' && 
                                   execution.steps[finalizingStepIndex]?.id === 'finalizing_results';
        
        // Special handling for chunked streaming completion
        if (chunkedResults.value.isReceivingChunks && chunkedResults.value.chunks.length > 0) {
            // console.log("[handleConnectionError] Connection closed during chunked streaming - attempting graceful completion");
            
            // Force completion of chunked streaming
            execution.results.metadata.isStreaming = false;
            delete execution.results.metadata.streamingProgress;
            
            // Complete the finalizing step
            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                execution.steps[finalizingStepIndex].status = 'completed';
            }
            
            execution.status = "completed";
            isProcessing.value = false;
            isStreaming.value = false;
            chunkedResults.value.isReceivingChunks = false;
            
            if (eventSource && activeEventSource.value) {
                eventSource.close();
                activeEventSource.value = null;
            }
            return;
        }
        
        if (execution.status === "completed" || 
            execution.status === "cancelled" || 
            execution.status === "error" ||
            execution.results !== null ||
            isFinalizingActive ||
            activeEventSource.value === null) { // Already closed by us
            if (eventSource && activeEventSource.value) {
                eventSource.close();
                activeEventSource.value = null;
            }
            return;
        }

        // Only treat as error if we're still processing
        error.value = "Connection to server lost. Please try your query again.";
        execution.status = "error";
        isProcessing.value = false;
        isStreaming.value = false;

        // Close the connection
        if (eventSource) {
            eventSource.close();
        }
        activeEventSource.value = null;
    };

    /**
     * Cancel an in-progress query
     * @returns {Promise<void>}
     */
    const cancelProcess = async () => {
        if (!processId.value) {
            console.warn("No process ID available to cancel");
            return;
        }

        try {

            const response = await fetch(`/api/realtime/cancel/${processId.value}`, {
                method: "POST",
                credentials: "include", // Include cookies for authentication
            });

            if (!response.ok) {
                // Silent fail for cancel requests
            }

            execution.status = "cancelled";
            isProcessing.value = false;
            isStreaming.value = false;

            // Close the connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        } catch (err) {
            // Silent fail for cancel errors
        }
    };

    /**
     * Clean up resources when component unmounts
     */
    const cleanup = () => {
        if (activeEventSource.value) {
            activeEventSource.value.close();
            activeEventSource.value = null;
        }
        isStreaming.value = false;
    };

    // Automatically clean up EventSource when process ID changes to null
    watch(
        () => processId.value,
        (newVal) => {
            if (!newVal && activeEventSource.value) {
                cleanup();
            }
        }
    );

    return {
        // State
        isLoading,
        isProcessing,
        isStreaming,
        error,
        processId,
        chunkedResults, // Expose chunked results state for progress tracking
        ...toRefs(execution), // Expose reactive execution state

        // Methods
        startProcess,
        connectToStream,
        cancelProcess,
        cleanup,
    };
}
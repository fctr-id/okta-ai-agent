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
                    console.log("Authentication expired, redirecting to login");
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
                console.log("Closing existing EventSource connection");
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
                handlePlanStatusEvent(event);
            });

            eventSource.addEventListener("phase_update", (event) => {
                handlePhaseUpdateEvent(event);
            });

            eventSource.addEventListener("step_status_update", (event) => {
                handleStepStatusEvent(event);
            });

            eventSource.addEventListener("step_plan_info", (event) => {
                handleStepPlanInfoEvent(event);
            });

            eventSource.addEventListener("final_result", (event) => {
                handleFinalResultEvent(event);
            });

            eventSource.addEventListener("plan_error", (event) => {
                handleErrorEvent(event);
            });

            eventSource.addEventListener("plan_cancelled", (event) => {
                handleCancelledEvent(event);
            });

            // Handle general messages (some backends send untyped messages)
            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // Handle based on message content structure
                    if (data.plan)
                        handlePlanStatusEvent({ data: JSON.stringify({ status: "generated", plan: data.plan }) });
                    else if (data.phase) handlePhaseUpdateEvent({ data: JSON.stringify({ phase: data.phase }) });
                    else if (data.result) handleFinalResultEvent({ data: JSON.stringify({ result: data.result }) });
                } catch (err) {
                    console.error("Error handling generic message:", err);
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
                    execution.steps[stepIndex].status = "error";
                    execution.steps[stepIndex].error = true; // Explicitly set error flag for v-stepper-item
                    execution.steps[stepIndex].error_message = data.error_message;

                    // Also update execution status to prevent finalizing steps from going green
                    execution.status = "error";

                    // Mark any remaining future steps as cancelled/disabled
                    for (let i = stepIndex + 1; i < execution.steps.length; i++) {
                        if (execution.steps[i].status === "pending" || execution.steps[i].status === "active") {
                            execution.steps[i].status = "pending";
                            execution.steps[i].disabled = true;
                        }
                    }
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
            console.log('🟣 RECEIVED step_plan_info event:', data);

            if (data.steps && Array.isArray(data.steps)) {
                console.log('🟣 Processing steps from backend:', data.steps);
                
                execution.planGenerated = true;
                
                // Complete the generate_plan step
                if (execution.steps[0] && execution.steps[0].id === 'generate_plan') {
                    execution.steps[0].status = 'completed';
                }

                // Create the new execution steps from the plan
                const newExecutionSteps = data.steps.map((step, index) => {
                    console.log(`🟣 Creating step ${index + 1}:`, {
                        tool_name: step.tool_name,
                        operation: step.operation,
                        entity: step.entity,
                        query_context: step.query_context
                    });
                    
                    return {
                        id: `step_${index + 1}`,
                        tool_name: step.tool_name,
                        operation: step.operation,
                        entity: step.entity,
                        reason: step.query_context || 'Processing data',
                        status: "pending",
                        critical: step.critical
                    };
                });

                console.log('🟣 Created execution steps:', newExecutionSteps);

                // Insert the new steps between generate_plan (index 0) and finalizing_results (last)
                // Keep generate_plan, insert new steps, keep finalizing_results
                const generatePlanStep = execution.steps[0];
                const finalizingResultsStep = execution.steps[execution.steps.length - 1];
                
                execution.steps = [
                    generatePlanStep,
                    ...newExecutionSteps,
                    finalizingResultsStep
                ];

                console.log('🟣 Final steps array:', execution.steps);
                execution.status = "executing";
            } else {
                console.warn('🟣 No steps array found in step_plan_info data:', data);
            }
        } catch (err) {
            console.error("Error processing step plan info event:", err);
        }
    };

    /**
     * Handle final result events - Activate finalizing_results step and then complete
     */
    const handleFinalResultEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            // Immediately close the EventSource to prevent server-side closure error
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
            
            // First, activate the finalizing_results step (last step)
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
            error.value = data.error || "An error occurred during execution";
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
        
        if (execution.status === "completed" || 
            execution.status === "cancelled" || 
            execution.status === "error" ||
            execution.results !== null ||
            isFinalizingActive ||
            activeEventSource.value === null) { // Already closed by us
            console.log("Connection closed after process completion - this is expected");
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
     * Mock implementation for testing UI when backend is not available
     * @param {string} query - The natural language query to process
     * @returns {Promise<string>} - A mock process ID
     */
    const mockProcess = async (query) => {
        isLoading.value = true;
        isProcessing.value = true;
        error.value = null;
        execution.status = "planning";

        try {
            // Simulate API delay
            await new Promise((resolve) => setTimeout(resolve, 1000));

            // Generate mock process ID
            const mockId = "mock-" + Math.random().toString(36).substring(2, 10);
            processId.value = mockId;

            // Simulate plan generation
            execution.planGenerated = true;
            execution.status = "executing";
            execution.steps = [
                { id: 0, tool_name: "Search users", status: "pending", reason: "Find user information" },
                { id: 1, tool_name: "Get group memberships", status: "pending", reason: "Check group associations" },
                { id: 2, tool_name: "Analyze permissions", status: "pending", reason: "Review access rights" },
            ];

            // Simulate step execution
            setTimeout(() => {
                execution.steps[0].status = "in_progress";
                execution.currentStepIndex = 0;
            }, 1000);

            setTimeout(() => {
                execution.steps[0].status = "completed";
                execution.steps[0].result_summary = "Found 5 matching users";
            }, 3000);

            setTimeout(() => {
                execution.steps[1].status = "in_progress";
                execution.currentStepIndex = 1;
            }, 3500);

            setTimeout(() => {
                execution.steps[1].status = "completed";
                execution.steps[1].result_summary = "Retrieved group memberships";
            }, 5500);

            setTimeout(() => {
                execution.steps[2].status = "in_progress";
                execution.currentStepIndex = 2;
            }, 6000);

            setTimeout(() => {
                execution.steps[2].status = "completed";
                execution.steps[2].result_summary = "Analysis complete";

                // Simulate final result
                execution.results = {
                    content: `# Results for "${query}"\n\n* Found 5 users matching criteria\n* Users belong to 3 groups\n* Admin permissions: 2 users`,
                    display_type: "markdown",
                    metadata: { total_users: 5 },
                };
                execution.status = "completed";
                isProcessing.value = false;
            }, 8000);

            return mockId;
        } catch (err) {
            error.value = err.message || "Failed to start mock process";
            execution.status = "error";
            isProcessing.value = false;
            return null;
        } finally {
            isLoading.value = false;
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
        ...toRefs(execution), // Expose reactive execution state

        // Methods
        startProcess,
        connectToStream,
        cancelProcess,
        mockProcess,
        cleanup,
    };
}

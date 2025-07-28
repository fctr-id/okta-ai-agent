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
        execution.steps = [];
        execution.currentStepIndex = -1;
        execution.results = null;

        //console.log('Starting realtime process with query:', query)

        try {
            //console.log('Sending request to /api/realtime/start-process')
            const response = await fetch("/api/realtime/start-process", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                credentials: "include", // Include cookies for authentication
                body: JSON.stringify({ query: query.trim() }),
            });

            //console.log('Response status:', response.status)

            // Handle non-OK responses more explicitly
            if (!response.ok) {
                const errorText = await response.text();
                //console.error('Error response body:', errorText)

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
            //console.log('Process started successfully:', data)
            processId.value = data.process_id;

            if (data.plan) {
                //console.log('Plan received with initial response')
                // Initialize execution state with the plan
                execution.planGenerated = true;
                execution.steps = data.plan.steps.map((step, index) => ({
                    ...step,
                    id: index,
                    status: "pending",
                }));
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
            //console.log('Connecting to EventSource:', eventSourceUrl)

            // Create EventSource - cookies will be sent automatically
            const eventSource = new EventSource(eventSourceUrl, {
                withCredentials: true, // This ensures cookies are sent with the request
            });
            activeEventSource.value = eventSource;
            isStreaming.value = true;

            //console.log('EventSource connection created')

            // Handle connection open event
            eventSource.onopen = () => {
                //console.log('EventSource connection opened')
                execution.status = execution.planGenerated ? "executing" : "planning";
            };

            // Set up event handlers for different event types
            eventSource.addEventListener("plan_status", (event) => {
                //console.log('Received plan_status event:', event.data)
                handlePlanStatusEvent(event);
            });

            eventSource.addEventListener("phase_update", (event) => {
                //console.log('Received phase_update event:', event.data)
                handlePhaseUpdateEvent(event);
            });

            eventSource.addEventListener("step_status_update", (event) => {
                //console.log('Received step_status_update event:', event.data)
                handleStepStatusEvent(event);
            });

            eventSource.addEventListener("step_plan_info", (event) => {
                //console.log('Received step_plan_info event:', event.data)
                handleStepPlanInfoEvent(event);
            });

            eventSource.addEventListener("final_result", (event) => {
                //console.log('Received final_result event:', event.data)
                handleFinalResultEvent(event);
            });

            eventSource.addEventListener("plan_error", (event) => {
                //console.log('Received plan_error event:', event.data)
                handleErrorEvent(event);
            });

            eventSource.addEventListener("plan_cancelled", (event) => {
                //console.log('Received plan_cancelled event:', event.data)
                handleCancelledEvent(event);
            });

            // Handle general messages (some backends send untyped messages)
            eventSource.onmessage = (event) => {
                //console.log('Received generic message event:', event.data)
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

            //console.log('Processing plan status event:', data)

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
            //console.log('Processing step status update:', data);

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
                        //console.log(`Completing step ${stepIndex} after delay`);
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
     * Handle step plan info events
     */
    const handleStepPlanInfoEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log('Processing step plan info event:', data);

            if (data.steps && Array.isArray(data.steps)) {
                execution.planGenerated = true;
                execution.steps = data.steps.map((step) => ({
                    id: step.id,
                    tool_name: step.tool_name,
                    reason: step.query_context || 'Processing data',
                    status: step.status || "pending",
                    critical: step.critical
                }));
                execution.status = "executing";
                console.log('Updated execution steps:', execution.steps);
            }
        } catch (err) {
            console.error("Error processing step plan info event:", err);
        }
    };

    /**
     * Handle final result events
     */
    const handleFinalResultEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            
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

            // Close the connection
            if (activeEventSource.value) {
                //console.log('Closing EventSource after receiving final result');
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
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
     * Handle phase update events
     */
    const handlePhaseUpdateEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            execution.status = data.phase || execution.status;
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
                //console.log('Closing EventSource after error event')
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
            //console.log('Closing EventSource after cancellation')
            activeEventSource.value.close();
            activeEventSource.value = null;
        }
    };

    /**
     * Handle connection errors
     */
    const handleConnectionError = (e, eventSource) => {
        console.error("Connection error in EventSource:", e);

        if (execution.status !== "completed" && execution.status !== "error") {
            error.value = "Connection to server lost. Please try your query again.";
            execution.status = "error";
            isProcessing.value = false;
            isStreaming.value = false;
        }

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
            //console.log('Cancelling process:', processId.value)

            const response = await fetch(`/api/realtime/cancel/${processId.value}`, {
                method: "POST",
                credentials: "include", // Include cookies for authentication
            });

            if (!response.ok) {
                //console.error('Failed to cancel process:', response.statusText)
            } else {
                //console.log('Process cancelled successfully')
            }

            execution.status = "cancelled";
            isProcessing.value = false;
            isStreaming.value = false;

            // Close the connection
            if (activeEventSource.value) {
                //console.log('Closing EventSource after cancellation')
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        } catch (err) {
            //console.error('Error cancelling process:', err)
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
            //console.log('Cleaning up EventSource connection')
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
                //console.log('Process ID reset, cleaning up EventSource')
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

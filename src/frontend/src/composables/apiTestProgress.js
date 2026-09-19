// Request status is evidence from the client, independent of step/tool ordering.
const statuses = new Set(['running', 'success', 'empty', 'failed', 'cancelled', 'unknown'])

export function applyApiTestProgress(steps, event) {
    if (event?.kind !== 'api_test_request') return false
    if (!event.test_id || !event.request_id || !statuses.has(event.status)) return true
    const tool = steps.flatMap(step => step.tools || []).find(tool => tool.testId === event.test_id)
    if (!tool) return true
    tool.requests ||= []
    const request = tool.requests.find(request => request.id === event.request_id)
    if (request) {
        // Ignore duplicate/stale starts; never undo a terminal status.
        if (request.status === 'running') request.status = event.status
    } else {
        tool.requests.push({ id: event.request_id, operation: event.operation, status: event.status })
    }
    return true
}

export function interruptApiTests(steps) {
    for (const step of steps) {
        for (const tool of step.tools || []) {
            for (const request of tool.requests || []) {
                // Stream closure does not establish API success or failure.
                if (request.status === 'running') request.status = 'unknown'
            }
        }
    }
}

export const requestStatusLabels = {
    running: 'Testing', success: 'Returned data', empty: 'No data',
    failed: 'Failed', cancelled: 'Cancelled', unknown: 'Unconfirmed',
}

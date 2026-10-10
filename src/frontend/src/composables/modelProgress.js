// Provider events describe retry state only; never display raw provider prose.
const active = new Set(['retry_wait', 'retrying'])
const states = new Set([...active, 'success', 'failed', 'cancelled', 'timed_out'])

export function applyModelProgress(steps, event, now = Date.now()) {
    if (event?.kind !== 'model_request') return false
    if (!/^[a-f0-9]{32}$/.test(event.request_id || '') || !states.has(event.status)) return true
    let step = steps.find(item => item.modelRequests?.some(request => request.id === event.request_id)) || steps.at(-1)
    if (!step) {
        step = { id: `provider-${event.request_id}`, tools: [], modelRequests: [] }
        steps.push(step)
    }
    step.modelRequests ||= []
    let request = step.modelRequests.find(item => item.id === event.request_id)
    if (request && !active.has(request.status)) return true
    if (!request) {
        request = { id: event.request_id }
        step.modelRequests.push(request)
    }
    request.status = event.status
    request.retryUntil = event.status === 'retry_wait' && Number.isFinite(event.retry_after_seconds)
        && event.retry_after_seconds >= 0 && event.retry_after_seconds <= 86400
        ? now + event.retry_after_seconds * 1000 : null
    return true
}

export function interruptModelProgress(steps) {
    for (const step of steps) {
        for (const request of step.modelRequests || []) {
            if (active.has(request.status)) {
                request.status = 'unknown'
                request.retryUntil = null
            }
        }
    }
}

export function modelProgressLabel(request, now = Date.now()) {
    if (request.status === 'retry_wait') {
        return request.retryUntil > now
            ? `AI provider rate limited · requested wait: ${Math.ceil((request.retryUntil - now) / 1000)}s remaining`
            : 'AI provider rate limited · waiting for retry'
    }
    return { retrying: 'Retrying AI provider request', success: 'AI provider responded',
        failed: 'AI provider request failed', cancelled: 'AI provider request cancelled',
        timed_out: 'AI provider request timed out', unknown: 'AI provider request status unconfirmed',
    }[request.status] || 'AI provider request status unconfirmed'
}

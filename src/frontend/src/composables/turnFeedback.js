export const isClarification = (value) => Boolean(value && (
    value.outcome === 'clarify' || value.result_mode === 'needs_clarification' ||
    value.completionMode === 'clarify' || value.completion_mode === 'clarify' ||
    value.status === 'needs_clarification'
))

export const isClarificationTurn = (turn) => isClarification(turn) || isClarification(turn.results?.metadata)

export const clarificationResult = (event) => ({
    display_type: 'text',
    content: event.user_message || event.content || event.error || 'Please clarify your request.',
    metadata: { isStreaming: false, outcome: 'clarify', result_mode: 'needs_clarification' },
})

export const hasUnassignedError = (error, activeTurnKey, turns) => Boolean(error && !turns.some(
    turn => turn.key === activeTurnKey && turn.error === error,
))

export const turnStatusPresentation = (turn) => {
    if (isClarificationTurn(turn)) return { label: 'Needs clarification', tone: 'muted' }
    if (turn.error || turn.resultsError || ['failed', 'error'].includes(turn.status)) {
        return { label: 'Failed', tone: 'error' }
    }
    if (turn.isHydratingResults) return { label: 'Loading results', tone: 'active' }
    if (turn.status === 'completed') {
        return turn.isPartialResult
            ? { label: 'Partial results', tone: 'muted' }
            : { label: 'Completed', tone: 'success' }
    }
    if (turn.status === 'cancelled') return { label: 'Cancelled', tone: 'muted' }
    if (turn.isActive) return { label: 'Working', tone: 'active' }
    // Older saved turns may have stale or missing status. Omit the badge
    // rather than imply that the query is running or failed to finish.
    return { label: '', tone: 'muted' }
}

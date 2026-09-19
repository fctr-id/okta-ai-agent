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

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyModelProgress, interruptModelProgress, modelProgressLabel } from '../src/composables/modelProgress.js'

const id = 'a'.repeat(32)
const event = (status, fields = {}) => ({ kind: 'model_request', request_id: id, status, ...fields })

test('provider retry stays with its original phase and uses only explicit delay hints', () => {
    const steps = [{ phase: 'planning' }]
    applyModelProgress(steps, event('retry_wait'), 1000)
    const request = steps[0].modelRequests[0]
    assert.equal(request.retryUntil, null)
    assert.equal(modelProgressLabel(request, 1000), 'AI provider rate limited · waiting for retry')
    applyModelProgress(steps, event('retry_wait', { retry_after_seconds: 3, message: 'PRIVATE' }), 1000)
    assert.match(modelProgressLabel(request, 2000), /2s remaining/)
    assert.match(modelProgressLabel(request, 5000), /waiting for retry/)
    steps.push({ phase: 'synthesis' })
    applyModelProgress(steps, event('retrying'), 5000)
    assert.equal(request.retryUntil, null)
    applyModelProgress(steps, event('success'))
    applyModelProgress(steps, event('retry_wait')) // late status must not undo completion
    assert.equal(request.status, 'success')
    assert.equal(steps[1].modelRequests, undefined)
    assert.doesNotMatch(JSON.stringify(steps), /PRIVATE/)
})

test('stream closure clears waiting without claiming success; malformed events are ignored', () => {
    const steps = []
    applyModelProgress(steps, event('retry_wait', { retry_after_seconds: 30 }), 0)
    interruptModelProgress(steps)
    assert.equal(steps[0].modelRequests[0].status, 'unknown')
    assert.equal(steps[0].modelRequests[0].retryUntil, null)
    assert.equal(applyModelProgress(steps, undefined), false)
    applyModelProgress(steps, event('PRIVATE'))
    applyModelProgress(steps, event('retry_wait', { request_id: '' }))
    assert.equal(steps[0].modelRequests.length, 1)
})

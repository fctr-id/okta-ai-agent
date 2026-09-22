import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyApiTestProgress, interruptApiTests } from '../src/composables/apiTestProgress.js'

test('out-of-order concurrent results attach to their test even after a new step', () => {
    const steps = [{ tools: [{ testId: 'a', requests: [] }] }, { tools: [{ testId: 'b', requests: [] }] }]
    const emit = (test, id, status) => applyApiTestProgress(steps, {
        kind: 'api_test_request', test_id: test, request_id: id, operation: 'user.list',
        label: 'List directory users', status,
    })
    emit('a', '1', 'running')
    emit('a', '2', 'running')
    emit('b', '3', 'running')
    emit('a', '2', 'empty')
    emit('b', '3', 'success')
    emit('a', '1', 'failed')
    emit('a', '1', 'running') // stale event cannot overwrite failure
    assert.deepEqual(steps[0].tools[0].requests.map(r => r.status), ['failed', 'empty'])
    assert.equal(steps[1].tools[0].requests[0].status, 'success')
    const saved = JSON.parse(JSON.stringify(steps))
    assert.equal(saved[0].tools[0].requests[0].label, 'List directory users')
    assert.equal(saved[0].tools[0].requests[0].operation, 'user.list')
})

test('stream closure marks only unresolved calls unconfirmed', () => {
    const steps = [{ tools: [{ requests: [{ status: 'running' }, { status: 'failed' }, { status: 'success' }] }] }]
    interruptApiTests(steps)
    assert.deepEqual(steps[0].tools[0].requests.map(r => r.status), ['unknown', 'failed', 'success'])
})

test('unrelated progress remains available to existing execution handler', () => {
    assert.equal(applyApiTestProgress([], undefined), false)
    assert.equal(applyApiTestProgress([], 'legacy message'), false)
    assert.equal(applyApiTestProgress([], { kind: 'api_test_request', test_id: 'missing' }), true)
})

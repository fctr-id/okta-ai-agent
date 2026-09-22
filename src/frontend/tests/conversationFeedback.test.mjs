import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ref, nextTick, effectScope, createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { useConversationCollapse } from '../src/composables/useConversationCollapse.js'
import { isClarification, isClarificationTurn, clarificationResult, hasUnassignedError, turnStatusPresentation } from '../src/composables/turnFeedback.js'

test('saved in-progress status is not a live execution or proof of completion', () => {
    for (const status of ['executing', 'running', 'created', 'active']) {
        assert.deepEqual(turnStatusPresentation({ status }), { label: '', tone: 'muted' })
        assert.deepEqual(turnStatusPresentation({ status, results: { metadata: { count: 3 } } }),
            { label: '', tone: 'muted' })
        assert.deepEqual(turnStatusPresentation({ status, isActive: true }), { label: 'Working', tone: 'active' })
    }
    assert.equal(turnStatusPresentation({}).label, '')
    assert.equal(turnStatusPresentation({ status: 'unknown' }).label, '')
    assert.deepEqual(turnStatusPresentation({ status: 'completed' }), { label: 'Completed', tone: 'success' })
    assert.equal(turnStatusPresentation({ status: 'completed', isPartialResult: true }).label, 'Partial results')
    assert.equal(turnStatusPresentation({ status: 'error' }).label, 'Failed')
    assert.equal(turnStatusPresentation({ status: 'cancelled' }).label, 'Cancelled')
    assert.equal(turnStatusPresentation({ status: 'completed', completionMode: 'clarify' }).label, 'Needs clarification')
})

test('follow-up collapses every existing turn and resets sections, while the new turn stays open', async () => {
    const scope = effectScope()
    const turns = ref([{ key: 'first' }, { key: 'second' }])
    const state = scope.run(() => useConversationCollapse(turns))
    try {
        state.collapseForFollowUp()
        assert.deepEqual([...state.collapsedTurnKeys.value], ['first', 'second'])
        assert.deepEqual(state.sectionCollapseRevisions.value, { first: 1, second: 1 })
        turns.value.push({ key: 'third' })
        await nextTick()
        assert.equal(state.collapsedTurnKeys.value.has('third'), false)
        state.setTurnCollapsed('first', false)
        state.collapseForFollowUp()
        assert.equal(state.collapsedTurnKeys.value.has('first'), true)
        assert.equal(state.sectionCollapseRevisions.value.first, 2)
        turns.value = [{ key: 'new-session' }]
        await nextTick()
        assert.equal(state.collapsedTurnKeys.value.size, 0)
        assert.deepEqual(state.sectionCollapseRevisions.value, {})
    } finally { scope.stop() }
})

test('manual collapse previous preserves the current turn and its sections', () => {
    const scope = effectScope()
    try {
        const state = scope.run(() => useConversationCollapse(ref([{ key: 'past' }, { key: 'current' }])))
        state.collapsePreviousTurns()
        assert.deepEqual([...state.collapsedTurnKeys.value], ['past'])
        assert.deepEqual(state.sectionCollapseRevisions.value, { past: 1 })
    } finally { scope.stop() }
})

test('clarification requires an explicit outcome; genuine failures are not reclassified from prose', () => {
    const message = 'Which timezone should I use?'
    assert.equal(isClarification({ error: message }), false)
    const event = { outcome: 'clarify', error: message }
    assert.equal(isClarification(event), true)
    const result = clarificationResult(event)
    assert.equal(result.content, message)
    assert.equal(isClarificationTurn({ results: result }), true)
    assert.equal(isClarificationTurn({ completionMode: 'clarify', error: message }), true)
})

test('only errors assigned to the current answer suppress the page-level fallback', () => {
    const turns = [{ key: 'previous', error: 'Same error' }, { key: 'current', error: 'Current error' }]
    assert.equal(hasUnassignedError('Current error', 'current', turns), false)
    assert.equal(hasUnassignedError('Same error', 'current', turns), true)
    assert.equal(hasUnassignedError('Cannot start query', null, turns), true)
})

test('activity and execution retain failure status without repeating the parent error', async () => {
    const server = await createServer({
        configFile: false, envFile: false, plugins: [vue()],
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false },
    })
    try {
        const { default: Activity } = await server.ssrLoadModule('/src/components/messages/DiscoveryPanel.vue')
        const { default: Execution } = await server.ssrLoadModule('/src/components/messages/ExecutionPanel.vue')
        const error = 'UNIQUE_ERROR_MESSAGE'
        const html = await renderToString(createSSRApp({ render: () => h('div', [
            h(Activity, { error, showError: false }),
            h(Execution, { executionError: error, showError: false, executionStarted: true, validationStep: { status: 'failed', message: error } }),
            h('div', { role: 'alert' }, error),
        ]) }))
        assert.equal(html.split(error).length - 1, 1)
        assert.match(html, /Stopped/)
        assert.match(html, /Execution failed/)
        assert.match(html, /Validation failed/)
    } finally { await server.close() }
})

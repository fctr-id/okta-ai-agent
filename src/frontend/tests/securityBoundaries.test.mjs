import { test } from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { marked } from 'marked'
import { createSSRApp } from 'vue'
import { routerKey } from 'vue-router'
import { useAuth } from '../src/composables/useAuth.js'

test('Markdown keeps formatting while removing unsupported elements and attributes', async () => {
    const dom = new JSDOM('') // No script execution or external resource loading.
    globalThis.window = dom.window
    try {
        const { sanitizeMarkdownHtml } = await import('../src/components/messages/safeMarkdown.js')
        const formatted = sanitizeMarkdownHtml(marked.parse('# Heading\n\n**Bold** and `code`\n\n- item\n\n[Docs](https://example.test/docs)\n\n| A | B |\n| - | - |\n| 1 | 2 |'))
        for (const tag of ['h1', 'strong', 'code', 'ul', 'table', 'a']) {
            assert.ok(formatted.includes(`<${tag}`), tag)
        }
        const clean = sanitizeMarkdownHtml('<p style="color:red" data-note="fixture">Text</p><form><input value="fixture"></form><svg><circle /></svg><a href="custom:fixture">Link</a>')
        const document = new JSDOM(clean).window.document
        assert.equal(document.querySelector('form,input,svg,[style],[data-note]'), null)
        assert.equal(document.querySelector('a').hasAttribute('href'), false)
        assert.match(document.body.textContent, /Text/)
    } finally {
        delete globalThis.window
        dom.window.close()
    }
})

test('logout uses POST and clears local authentication only after server success', async (t) => {
    const app = createSSRApp({})
    app.provide(routerKey, { push() { throw new Error('Unexpected redirect') } })
    const auth = app.runWithContext(() => useAuth())
    t.mock.method(console, 'error', () => {})
    const fetchMock = t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ username: 'fixture' })))
    await auth.checkAuth()
    assert.equal(auth.isAuthenticated.value, true)
    for (const implementation of [async () => new Response('', { status: 500 }), async () => { throw new Error('offline') }]) {
        fetchMock.mock.mockImplementation(implementation)
        assert.equal(await auth.logout(), false)
        assert.equal(auth.isAuthenticated.value, true)
        assert.equal(auth.user.value.username, 'fixture')
        assert.match(auth.error.value, /try again/)
    }
    fetchMock.mock.mockImplementation(async (url, options) => {
        assert.equal(url, '/api/auth/logout')
        assert.equal(options.method, 'POST')
        assert.equal(options.credentials, 'same-origin')
        return new Response(JSON.stringify({ success: true }))
    })
    assert.equal(await auth.logout(), true)
    assert.equal(auth.isAuthenticated.value, false)
    assert.equal(auth.user.value, null)
    assert.equal(auth.error.value, null)
})

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resultColumnKeys, resultRowsCsv, resultValueText } from '../src/components/messages/resultTable.js'

test('CSV preserves quotes, multiline values, lists, objects, and fields missing from the first row', () => {
    const rows = [
        { name: 'A "quoted", name', notes: 'first\nsecond', groups: ['one', 'two', 'three', 'four', 'five', 'six'], details: { enabled: false }, count: 0 },
        { name: 'Zoë', late_field: 'present', empty: null },
    ]
    const headers = resultColumnKeys(rows).map(key => ({ key, title: key }))
    assert.equal(resultRowsCsv(rows, headers),
        '"name","notes","groups","details","count","late_field","empty"\r\n' +
        '"A ""quoted"", name","first\nsecond","[""one"",""two"",""three"",""four"",""five"",""six""]","{""enabled"":false}","0","",""\r\n' +
        '"Zoë","","","","","present",""')
})

test('CSV includes every loaded row and approved column without changing the source', () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({ email: `user${i}@example.test`, extra: ['a', 'b', 'c', 'd', 'e', 'f'], internal: 'omit' }))
    const before = structuredClone(rows)
    const headers = [{ key: 'email', title: 'Email' }, { key: 'extra', title: 'Additional values' }]
    const csv = resultRowsCsv(rows, headers)
    assert.equal(csv.split('\r\n').length, 26)
    assert.ok(csv.includes('user24@example.test'))
    assert.ok(csv.includes('""f""'))
    assert.ok(!csv.includes('internal'))
    assert.ok(!csv.includes('omit'))
    assert.deepEqual(rows, before)
})

test('spreadsheet formulas stay text while negative numbers remain numeric', () => {
    const values = ['=1+1', ' @SUM(A1)', '+1+1', '-1+1', -5, false, null]
    const csv = resultRowsCsv(values.map(value => ({ value })), [{ key: 'value', title: 'Value' }])
    assert.equal(csv, '"Value"\r\n"\'=1+1"\r\n"\' @SUM(A1)"\r\n"\'+1+1"\r\n"\'-1+1"\r\n"-5"\r\n"false"\r\n""')
    assert.equal(resultValueText({ list: [1, 2] }), '{"list":[1,2]}')
})

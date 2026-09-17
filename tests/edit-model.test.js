const test = require('node:test')
const assert = require('node:assert/strict')
const M = require('../qml/Model.js')
const agenda = { calendars: [{ id: 'demo', name: 'Demo', readOnly: false }] }
const event = { calendar: 'demo', file: '/demo.ics', attendees: [] }
test('editing requires a writable, non-recurring event without guests and a file', () => {
  assert.equal(M.eventEditable(agenda, event), true)
  for (const e of [null, {...event, file: ''}, {...event, recurring: true}, {...event, attendees: ['you@example.com']}, {...event, calendar: 'missing'}]) {
    assert.equal(M.eventEditable(agenda, e), false)
    assert.notEqual(M.editReason(agenda, e), '')
  }
  assert.equal(M.eventEditable({calendars: [{...agenda.calendars[0], readOnly: true}]}, event), false)
  assert.equal(M.editReason(agenda, {...event, attendees: ['you@example.com']}), "Events with guests can't be edited from Omagenda yet; edit it in Demo's own app")
})
test('edit hints omit calendar cycling and save-and-add-another', () => {
  assert.equal(M.quickAddHints(agenda, 'demo', true), 'ENTER SAVE · ESC CANCEL')
  assert.match(M.quickAddHints(agenda, 'demo', false), /SHIFT\+ENTER/)
})
test('save progress makes a sync-lock wait visible', () => {
  assert.equal(M.saveProgressText(false, false), '')
  assert.equal(M.saveProgressText(true, false), 'Saving…')
  assert.equal(M.saveProgressText(true, true), 'Saving… waiting for sync to finish')
})

const fs = require('node:fs')
const vm = require('node:vm')
const source = fs.readFileSync(require.resolve('../qml/QuickAdd.qml'), 'utf8')
function overlay() {
  const root = { text: '', prefillDate: '', editFile: '', targetCalendar: '', parsed: null,
    agenda, service: {defaultCalendar: 'demo'}, binPath: '/demo/bin/omagenda' }
  Object.defineProperty(root, 'editing', {get: () => root.editFile !== ''})
  const context = vm.createContext({root, Model: M, Qt: {callLater: f => f()},
    field: {get text() { return root.text }, forceActiveFocus() {}}, parseDebounce: {restart() {}},
    addProc: {running: false}, cycleNoteTimer: {restart() {}}, saveWaitTimer: {restart() {}}})
  for (const match of source.matchAll(/^  function \w+\([^]*?^  }/gm)) vm.runInContext(match[0], context)
  for (const name of ['open', 'openEdit', 'close', 'sentence', 'setText', 'submit', 'cycleCalendar']) root[name] = context[name]
  return context
}
test('Quick Add edit mode omits prefill and rejects cycling and Shift+Enter', () => {
  const c = overlay()
  c.root.openEdit('/demo.ics', 'Dentist on Sep 17 at 3pm', 'demo')
  assert.equal(c.root.editing, true)
  assert.equal(c.field.cursorPosition, c.root.text.length)
  assert.equal(c.root.targetCalendar, 'demo')
  c.root.prefillDate = '2026-09-20'
  assert.equal(c.root.sentence(), 'Dentist on Sep 17 at 3pm')
  c.root.cycleCalendar()
  assert.equal(c.root.targetCalendar, 'demo')
  c.root.submit(true)
  assert.equal(c.addProc.running, false)
  c.root.submit(false)
  assert.deepEqual(Array.from(c.addProc.command), ['/demo/bin/omagenda', 'edit', '/demo.ics', 'Dentist on Sep 17 at 3pm', '--json'])
})
test('cancel makes no write and the next normal Quick Add resets to add mode', () => {
  const c = overlay()
  c.root.openEdit('/demo.ics', 'Dentist on Sep 17 at 3pm', 'demo')
  c.root.close()
  assert.equal(c.addProc.running, false)
  c.root.open('2026-09-20')
  assert.equal(c.root.editing, false)
  assert.equal(c.root.text, '')
  assert.equal(c.root.targetCalendar, '')
  c.root.setText('Checkup 3pm')
  c.root.submit(false)
  assert.deepEqual(Array.from(c.addProc.command), ['/demo/bin/omagenda', 'add', 'Checkup 3pm 2026-09-20', '--json'])
})

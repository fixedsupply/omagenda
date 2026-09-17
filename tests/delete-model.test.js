const test = require("node:test")
const assert = require("node:assert/strict")
const M = require("../qml/Model.js")
const agenda = { calendars: [{ id: "personal", name: "Personal", readOnly: false }, { id: "ro", name: "Subscribed", readOnly: true }] }
const event = { file: "/demo.ics", calendar: "personal", title: "Disposable event", recurring: false }
const empty = { pending: "", message: "", confirm: "" }
const step = (state, action, selected = event, picker = false) => M.deleteTransition(state, action, agenda, selected, picker)

test("delete eligibility and exact refusal reasons", () => {
  assert.equal(M.deleteReason(agenda, event), "")
  assert.equal(M.deleteReason(agenda, { ...event, calendar: "ro" }), "'Subscribed' is read-only, so its events can't be deleted here")
  assert.equal(M.deleteReason(agenda, { ...event, recurring: true }), "Recurring events can't be deleted from Omagenda yet; delete it in Personal's own app")
  for (const e of [null, { ...event, file: "" }, { ...event, calendar: "missing" }]) assert.notEqual(M.deleteReason(agenda, e), "")
})
test("arm and confirm only the same event; picker does nothing", () => {
  const armed = step(empty, "delete")
  assert.equal(armed.pending, event.file)
  assert.equal(armed.confirm, "")
  assert.equal(step(armed, "delete").confirm, event.file)
  assert.equal(step(armed, "delete", { ...event, file: "/other.ics" }).confirm, "")
  assert.deepEqual(step(empty, "delete", event, true), empty)
  for (const e of [{ ...event, recurring: true }, { ...event, calendar: "ro" }]) {
    const refused = step(armed, "delete", e)
    assert.equal(refused.pending, "")
    assert.equal(refused.confirm, "")
    assert.equal(refused.message, M.deleteReason(agenda, e))
  }
})
for (const action of ["escape", "move", "day", "c", "t", "n", "close", "selection", "timeout"]) {
  test(`pending delete cancels on ${action}`, () => assert.deepEqual(step(step(empty, "delete"), action), empty))
}
test("delete hints include confirmation and cancellation with an elided long title", () => {
  const armed = step(empty, "delete")
  assert.equal(M.deleteHint(armed, event), "DELETE 'DISPOSABLE EVENT'? X TO CONFIRM · ESC TO CANCEL")
  assert.match(M.deleteHint(armed, { ...event, title: "a".repeat(100) }), /…'\? X TO CONFIRM · ESC TO CANCEL$/)
  assert.equal(M.deleteHint({ ...empty, message: "Reason" }, event), "Reason")
  assert.equal(M.deleteHint(empty, event), "")
})
test("delete progress identifies a queued delete and its sync wait", () => {
  assert.equal(M.deleteProgressHint("Disposable event", false), "DELETING 'Disposable event'…")
  assert.equal(M.deleteProgressHint("Disposable event", true), "DELETING 'Disposable event'… WAITING FOR SYNC TO FINISH")
  assert.match(M.deleteProgressHint("a".repeat(100), false), /^DELETING 'a{35}…'…$/)
})
test("footer advertises only available actions, in order", () => {
  assert.equal(M.eventActionHints(agenda, event), "E EDIT · X DELETE")
  assert.equal(M.eventActionHints(agenda, { ...event, url: "https://example.com" }), "E EDIT · X DELETE · O OPEN")
  assert.equal(M.eventActionHints(agenda, { ...event, recurring: true }), "")
  assert.equal(M.eventActionHints(agenda, { ...event, calendar: "ro" }), "")
  assert.equal(M.eventActionHints(agenda, { ...event, calendar: "ro", location: "https://example.com" }), "O OPEN")
  assert.equal(M.eventActionHints(agenda, null), "")
  assert.equal(M.eventOpenTarget({ conference: { url: "meeting" }, url: "other" }), "meeting")
  assert.equal(M.eventOpenTarget({ location: "Cafe" }), "")
})

// Reloading can replace the selected event without any navigation signal.
test("a pending delete cannot prompt or confirm a different event after reload", () => {
  const armed = step(empty, "delete")
  const replacement = { ...event, file: "/replacement.ics" }
  assert.equal(M.deleteHint(armed, replacement), "")
  const next = step(armed, "delete", replacement)
  assert.equal(next.confirm, "")
  assert.equal(next.pending, replacement.file)
})

test("a pending delete cannot prompt or confirm an event removed by reload", () => {
  const armed = step(empty, "delete")
  assert.equal(M.deleteHint(armed, null), "")
  const next = step(armed, "delete", null)
  assert.equal(next.confirm, "")
  assert.equal(next.pending, "")
})

test("an unchanged delete state is recognised, so cancelling nothing writes nothing", () => {
  const empty = { pending: "", message: "", confirm: "" }
  assert.equal(M.sameDeleteState(empty, { pending: "", message: "", confirm: "" }), true)
  assert.equal(M.sameDeleteState(empty, {}), true)
  assert.equal(M.sameDeleteState(empty, { pending: "/x.ics", message: "", confirm: "" }), false)
  assert.equal(M.sameDeleteState({ message: "a" }, { message: "b" }), false)
  const cancelled = M.deleteTransition(empty, "day", {}, null, false)
  assert.equal(M.sameDeleteState(cancelled, empty), true)
})

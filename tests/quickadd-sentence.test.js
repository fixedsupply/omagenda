const test = require("node:test")
const assert = require("node:assert/strict")
const M = require("../qml/Model.js")

const withDate = { spans: [{ kind: "date", start: 15, end: 23 }, { kind: "time", start: 24, end: 30 }] }
const timeOnly = { spans: [{ kind: "time", start: 14, end: 20 }] }

test("a sentence that names its own day keeps the panel's date out", () => {
  assert.equal(
    M.quickAddSentence("lunch with Sam tomorrow at 1pm at Cafe Torino", "2026-09-18", false, withDate),
    "lunch with Sam tomorrow at 1pm at Cafe Torino")
})

test("a sentence with no day takes the day selected in the panel", () => {
  assert.equal(
    M.quickAddSentence("lunch with Sam at 1pm", "2026-09-18", false, timeOnly),
    "lunch with Sam at 1pm 2026-09-18")
})

// The bug this guards: the decision used to be made against a parse of the
// sentence that already carried the appended date. That parse always contains
// a date span, so the answer flipped every other keystroke, and the date could
// be appended to a sentence that ended in a location -- saving the event with
// "Cafe Torino 2026-09-18" as its location.
test("the decision ignores a parse of the already-appended sentence", () => {
  const appendedParse = { spans: [{ kind: "date", start: 22, end: 32 }] }
  const typed = "lunch with Sam at 1pm"
  const first = M.quickAddSentence(typed, "2026-09-18", false, timeOnly)
  assert.equal(first, "lunch with Sam at 1pm 2026-09-18")
  // Feeding the appended sentence's own parse back in must not be how the
  // next decision is made; with the typed parse it stays stable.
  assert.equal(M.quickAddSentence(typed, "2026-09-18", false, timeOnly), first)
  assert.notEqual(M.quickAddSentence(typed, "2026-09-18", false, appendedParse), first)
})

test("editing never appends, whatever the panel has selected", () => {
  assert.equal(M.quickAddSentence("lunch with Sam at 1pm", "2026-09-18", true, timeOnly), "lunch with Sam at 1pm")
})

test("no selected day means nothing to append", () => {
  assert.equal(M.quickAddSentence("lunch with Sam at 1pm", "", false, timeOnly), "lunch with Sam at 1pm")
})

test("an empty sentence stays empty rather than becoming a bare date", () => {
  assert.equal(M.quickAddSentence("   ", "2026-09-18", false, null), "")
})

test("a missing or spanless parse counts as naming no day", () => {
  assert.equal(M.parsedHasDate(null), false)
  assert.equal(M.parsedHasDate({}), false)
  assert.equal(M.parsedHasDate({ spans: [] }), false)
  assert.equal(M.parsedHasDate(withDate), true)
})

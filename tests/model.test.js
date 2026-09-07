const test = require("node:test")
const assert = require("node:assert/strict")

const Model = require("../qml/Model.js")

// Placeholder until Phase 2 implements Model.js's real functions (countdown
// text, pill visibility, ticker layout, agenda grouping). Keeps `node --test`
// green through Phase 0/1 so a broken require is caught immediately.
test("Model.js loads and exports something", () => {
  assert.equal(typeof Model, "object")
  assert.equal(typeof Model.placeholder, "function")
  assert.equal(Model.placeholder(), true)
})

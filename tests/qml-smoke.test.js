const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const { spawnSync } = require("node:child_process")

// Pattern: ~/.config/omarchy/plugins/mohamedmansour.finance/tests/qml-smoke.test.js
const qmlDir = path.resolve(__dirname, "..", "qml")
const qmlFiles = fs.readdirSync(qmlDir).filter(f => f.endsWith(".qml"))

test("every QML file parses with qmlformat", () => {
  assert.ok(qmlFiles.length > 0, "expected at least one .qml file under qml/")
  for (const file of qmlFiles) {
    const result = spawnSync("/usr/lib/qt6/bin/qmlformat", [path.join(qmlDir, file)], {
      encoding: "utf8"
    })
    assert.equal(result.status, 0, `${file}: ${result.stderr || result.stdout}`)
  }
})

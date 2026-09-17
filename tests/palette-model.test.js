const test = require("node:test")
const assert = require("node:assert/strict")
const M = require("../qml/Model.js")

test("near-duplicate PM greens receive distinct theme colours", () => {
  const palette = {
    blue: "#509475", green: "#549e6a", magenta: "#c040c0", yellow: "#459451",
    cyan: "#20bccc", red: "#dc4850", orange: "#e88c28", brown: "#75421e"
  }
  const resolved = M.resolvedPalette(palette)
  assert.equal(resolved.blue, "#509475")
  assert.equal(resolved.green, "#75421e")
  assert.equal(resolved.yellow, "#20bccc")
  assert.equal(new Set([resolved.blue, resolved.green, resolved.yellow]).size, 3)
})

test("a palette with distinct named colours remains unchanged", () => {
  const palette = {
    blue: "#205ea6", green: "#879a39", magenta: "#ce5d97", yellow: "#d0a215",
    cyan: "#3aa99f", red: "#d14d41", orange: "#d0772b", brown: "#683b15"
  }
  assert.deepEqual(M.resolvedPalette(palette), {
    blue: palette.blue, green: palette.green, magenta: palette.magenta, yellow: palette.yellow,
    cyan: palette.cyan, red: palette.red, orange: palette.orange
  })
})

test("an all-similar palette keeps its original values when no substitute exists", () => {
  const palette = {}
  for (const name of ["blue", "green", "magenta", "yellow", "cyan", "red", "orange", "brown", "bright_blue", "bright_green", "bright_magenta", "bright_yellow", "bright_cyan", "bright_red"]) palette[name] = "#808080"
  const resolved = M.resolvedPalette(palette)
  for (const name of ["blue", "green", "magenta", "yellow", "cyan", "red", "orange"]) assert.equal(resolved[name], "#808080")
})

test("missing names retain paletteColor's foreground fallback", () => {
  const resolved = M.resolvedPalette({ blue: "#123456" })
  assert.equal(M.paletteColor(resolved, "blue", "#ffffff"), "#123456")
  assert.equal(M.paletteColor(resolved, "green", "#ffffff"), "#ffffff")
})

test("palette resolution is deterministic", () => {
  const palette = { blue: "#509475", green: "#549e6a", yellow: "#459451", brown: "#75421e" }
  assert.deepEqual(M.resolvedPalette(palette), M.resolvedPalette(palette))
})

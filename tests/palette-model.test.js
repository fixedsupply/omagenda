const test = require("node:test")
const assert = require("node:assert/strict")
const M = require("../qml/Model.js")

// The PM's panel showed 33 orange events beside 14 green ones in Tokyo Night,
// and every one of them looked the same colour: orange was separated from red
// (36 apart in RGB) into bright_green, which sits beside green.
test("Tokyo Night keeps orange and green apart", () => {
  const palette = {
    background: "#1a1b26", red: "#f7768e", yellow: "#e0af68", orange: "#eb927b",
    green: "#9ece6a", cyan: "#449dab", blue: "#7aa2f7", magenta: "#ad8ee6", brown: "#75493d",
    bright_red: "#ff7a93", bright_yellow: "#ff9e64", bright_green: "#b9f27c",
    bright_cyan: "#0db9d7", bright_blue: "#7da6ff", bright_magenta: "#bb9af7"
  }
  const resolved = M.resolvedPalette(palette)
  assert.equal(resolved.orange, "#eb927b", "orange and red are already tellable apart")
  assert.equal(resolved.green, "#9ece6a")
  assert.ok(M.colorDistance(resolved.orange, resolved.green) >= 20)
})

test("colour distance follows the eye, not the RGB cube", () => {
  // Same green to look at, far apart in RGB.
  assert.ok(M.colorDistance("#9ece6a", "#b9f27c") < 20)
  // Tellable apart at a glance, closer together in RGB than that pair.
  assert.ok(M.colorDistance("#eb927b", "#f7768e") >= 20)
})

test("near-duplicate greens receive a distinct theme colour", () => {
  const palette = {
    blue: "#509475", green: "#549e6a", magenta: "#c040c0", yellow: "#459451",
    cyan: "#20bccc", red: "#dc4850", orange: "#e88c28", brown: "#75421e"
  }
  const resolved = M.resolvedPalette(palette)
  assert.equal(resolved.blue, "#509475")
  assert.equal(resolved.green, "#75421e")
  // Nothing is left for yellow: taking cyan's colour would only make the cyan
  // calendars the indistinguishable pair instead.
  assert.equal(resolved.yellow, "#459451")
  assert.equal(resolved.cyan, "#20bccc")
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

test("substitutes stay readable on the theme background (the PM's Osaka Jade theme)", () => {
  const palette = {
    background: "#111c18", blue: "#509475", green: "#549e6a", yellow: "#459451", magenta: "#D2689C",
    cyan: "#2DD5B7", red: "#FF5345", orange: "#a2734b", brown: "#513925",
    bright_blue: "#ACD4CF", bright_green: "#63b07a", bright_magenta: "#75bbb3",
    bright_yellow: "#E5C736", bright_cyan: "#8CD3CB", bright_red: "#db9f9c"
  }
  const resolved = M.resolvedPalette(palette)
  assert.equal(resolved.blue, "#509475")
  assert.notEqual(resolved.green, "#513925", "dark brown would vanish on this background")
  assert.equal(new Set([resolved.blue, resolved.green, resolved.yellow]).size, 3)
  for (const name of ["green", "yellow"]) assert.ok(M.readableOn(resolved[name], palette.background), name)
  const names = Object.keys(resolved)
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      assert.ok(M.colorDistance(resolved[names[i]], resolved[names[j]]) >= 20, names[i] + "/" + names[j])
    }
  }
})

test("a dark substitute is rejected on a dark background, accepted on a light one", () => {
  assert.equal(M.readableOn("#513925", "#111c18"), false)
  assert.equal(M.readableOn("#513925", "#fafafa"), true)
  assert.equal(M.readableOn("#ACD4CF", "#111c18"), true)
  assert.equal(M.readableOn("#513925", undefined), true)
})

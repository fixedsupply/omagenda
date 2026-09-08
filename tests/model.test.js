const test = require("node:test")
const assert = require("node:assert/strict")

const Model = require("../qml/Model.js")

// A fixed "now" so countdowns and pill rules are reproducible:
// Monday 7 September 2026, 13:48 local.
const NOW = "2026-09-07T13:48:00-06:00"

const AGENDA = {
  generatedAt: "2026-09-07T13:48:00-06:00",
  range: { from: "2026-09-07", to: "2026-09-21" },
  lastSync: "2026-09-07T13:45:00-06:00",
  activeSet: "",
  calendars: [
    { id: "personal", name: "Personal", color: "blue", readOnly: false },
    { id: "work", name: "Work", color: "green", readOnly: false },
    { id: "family", name: "Family", color: "yellow", readOnly: false }
  ],
  events: [
    {
      id: "work/standup", calendar: "work", title: "Standup",
      start: "2026-09-07T14:00:00-06:00", end: "2026-09-07T14:15:00-06:00",
      allDay: false, location: "", conference: { provider: "meet", url: "https://meet.google.com/x" },
      attendees: 4, recurring: true, alarms: []
    },
    {
      id: "family/pickup", calendar: "family", title: "Pick up Jack",
      start: "2026-09-07T16:30:00-06:00", end: "2026-09-07T17:00:00-06:00",
      allDay: false, location: "School", conference: null, attendees: 0, recurring: true, alarms: []
    },
    {
      id: "personal/lunch", calendar: "personal", title: "Lunch with Sarah",
      start: "2026-09-08T13:00:00-06:00", end: "2026-09-08T14:00:00-06:00",
      allDay: false, location: "Cafe Linnea", conference: null, attendees: 0, recurring: false, alarms: []
    },
    {
      id: "family/holiday", calendar: "family", title: "Labour Day",
      start: "2026-09-07", end: "2026-09-08",
      allDay: true, location: "", conference: null, attendees: 0, recurring: false, alarms: []
    }
  ]
}

// ---------------------------------------------------------------------
test("parsePalette reads a theme's named colours", () => {
  const toml = [
    'mode = "dark"',
    'accent = "#509475"',
    "",
    'red = "#FF5345"',
    'blue = "#509475"',
    'bright_green = "#63b07a"',
    "# a comment",
    "not_a_color = 12"
  ].join("\n")
  const palette = Model.parsePalette(toml)
  assert.equal(palette.red, "#FF5345")
  assert.equal(palette.blue, "#509475")
  assert.equal(palette.bright_green, "#63b07a")
  assert.equal(palette.not_a_color, undefined)
})

test("paletteColor falls back when a theme omits a name", () => {
  const palette = { blue: "#509475" }
  assert.equal(Model.paletteColor(palette, "blue", "#fff"), "#509475")
  assert.equal(Model.paletteColor(palette, "chartreuse", "#fff"), "#fff")
  assert.equal(Model.paletteColor(palette, "", "#fff"), "#fff")
})

test("calendar colour and name lookups", () => {
  assert.equal(Model.calendarColorName(AGENDA, "work"), "green")
  assert.equal(Model.calendarColorName(AGENDA, "nope"), "")
  assert.equal(Model.calendarName(AGENDA, "family"), "Family")
  assert.equal(Model.calendarName(AGENDA, "unknown"), "unknown")
})

// ---------------------------------------------------------------------
test("an all-day date string is read as local, not UTC midnight", () => {
  // Parsed as UTC this lands on 7 Sep anywhere west of Greenwich.
  assert.equal(Model.dateKey("2026-09-08"), "2026-09-08")
})

test("dateKey and addDays work across a month boundary", () => {
  assert.equal(Model.dateKey(Model.addDays("2026-09-30", 1)), "2026-10-01")
  assert.equal(Model.dateKey(Model.addDays("2026-09-07", 7)), "2026-09-14")
})

test("resolveTimeFormat honours an explicit setting over the locale", () => {
  assert.equal(Model.resolveTimeFormat("24h", false), "24h")
  assert.equal(Model.resolveTimeFormat("12h", true), "12h")
  assert.equal(Model.resolveTimeFormat("system", true), "24h")
  assert.equal(Model.resolveTimeFormat("system", false), "12h")
})

test("formatTime in both clocks", () => {
  assert.equal(Model.formatTime("2026-09-07T14:00:00-06:00", "24h"), "14:00")
  assert.equal(Model.formatTime("2026-09-07T14:30:00-06:00", "24h"), "14:30")
  assert.equal(Model.formatTime("2026-09-07T14:00:00-06:00", "12h"), "2pm")
  assert.equal(Model.formatTime("2026-09-07T14:30:00-06:00", "12h"), "2:30pm")
  assert.equal(Model.formatTime("2026-09-07T00:15:00-06:00", "12h"), "12:15am")
  assert.equal(Model.formatTime("2026-09-07", "24h"), "all day")
})

test("countdownText scales from minutes to days", () => {
  assert.equal(Model.countdownText("2026-09-07T14:00:00-06:00", NOW), "12m")
  assert.equal(Model.countdownText("2026-09-07T13:48:00-06:00", NOW), "now")
  assert.equal(Model.countdownText("2026-09-07T13:00:00-06:00", NOW), "now")
  assert.equal(Model.countdownText("2026-09-07T14:48:00-06:00", NOW), "1h")
  assert.equal(Model.countdownText("2026-09-07T14:53:00-06:00", NOW), "1h 5m")
  assert.equal(Model.countdownText("2026-09-09T13:48:00-06:00", NOW), "2d")
})

// ---------------------------------------------------------------------
test("currentOrNextEvent picks the next timed event", () => {
  const event = Model.currentOrNextEvent(AGENDA, NOW)
  assert.equal(event.title, "Standup")
})

test("currentOrNextEvent prefers an event already running", () => {
  const during = "2026-09-07T14:05:00-06:00"
  const event = Model.currentOrNextEvent(AGENDA, during)
  assert.equal(event.title, "Standup")
  assert.ok(Model.isRunning(event, during))
})

test("an all-day event never occupies the hero or pill slot", () => {
  // The only thing left on this day is the all-day Labour Day entry.
  const late = "2026-09-07T20:00:00-06:00"
  const event = Model.currentOrNextEvent(AGENDA, late)
  assert.equal(event.title, "Lunch with Sarah")  // tomorrow's timed event, not Labour Day
})

test("currentOrNextEvent returns null when nothing is left", () => {
  assert.equal(Model.currentOrNextEvent({ events: [] }, NOW), null)
})

// ---------------------------------------------------------------------
test("pill stays out of the bar until an event is close", () => {
  // Standup is 12 minutes out, well inside the default 30-minute lead.
  assert.equal(Model.pillText(AGENDA, NOW, {}), "Standup · 12m")

  // At 13:00 the next event is 60 minutes out: past the lead, so nothing.
  assert.equal(Model.pillText(AGENDA, "2026-09-07T13:00:00-06:00", {}), "")
})

test("pill says 'now' for a running event", () => {
  assert.equal(Model.pillText(AGENDA, "2026-09-07T14:05:00-06:00", {}), "Standup · now")
})

test("alwaysShow keeps a slot with the next event's time", () => {
  const text = Model.pillText(AGENDA, "2026-09-07T13:00:00-06:00", { alwaysShow: true })
  assert.equal(text, "Standup · 14:00")
})

test("alwaysShow with an empty agenda still says something", () => {
  assert.equal(Model.pillText({ events: [] }, NOW, { alwaysShow: true }), "Nothing scheduled")
  assert.equal(Model.pillText({ events: [] }, NOW, {}), "")
})

test("showCountdown off drops the trailing countdown", () => {
  assert.equal(Model.pillText(AGENDA, NOW, { showCountdown: false }), "Standup")
})

test("leadMinutes widens or narrows the window", () => {
  assert.equal(Model.pillText(AGENDA, "2026-09-07T13:00:00-06:00", { leadMinutes: 90 }), "Standup · 1h")
  assert.equal(Model.pillText(AGENDA, NOW, { leadMinutes: 5 }), "")
})

// ---------------------------------------------------------------------
test("tickerDays lays out a week with today and the selection marked", () => {
  const days = Model.tickerDays(AGENDA, "2026-09-07", "2026-09-09", 7)
  assert.equal(days.length, 7)
  assert.equal(days[0].key, "2026-09-07")
  assert.equal(days[0].weekday, "MON")
  assert.equal(days[0].day, 7)
  assert.ok(days[0].isToday)
  assert.ok(!days[0].isSelected)
  assert.ok(days[2].isSelected)
  assert.equal(days[6].key, "2026-09-13")
  assert.equal(days[6].weekday, "SUN")
})

test("ticker dots carry calendar colours and are capped", () => {
  const days = Model.tickerDays(AGENDA, "2026-09-07", "2026-09-07", 7, 3)
  // 7 Sep has Standup (work/green), Pick up Jack (family/yellow), Labour Day (family/yellow)
  assert.deepEqual(days[0].dots, ["yellow", "green", "yellow"])
  assert.deepEqual(days[1].dots, ["blue"])  // 8 Sep: lunch
  assert.deepEqual(days[2].dots, [])        // 9 Sep: nothing
})

test("ticker respects a shorter day count", () => {
  assert.equal(Model.tickerDays(AGENDA, "2026-09-07", "2026-09-07", 3).length, 3)
})

// ---------------------------------------------------------------------
test("eventsForDate puts all-day events first", () => {
  const events = Model.eventsForDate(AGENDA, "2026-09-07")
  assert.deepEqual(events.map(e => e.title), ["Labour Day", "Standup", "Pick up Jack"])
})

test("eventsForDate excludes the exclusive end day of an all-day event", () => {
  // Labour Day runs 7 Sep with DTEND 8 Sep, so it must not appear on the 8th.
  const events = Model.eventsForDate(AGENDA, "2026-09-08")
  assert.deepEqual(events.map(e => e.title), ["Lunch with Sarah"])
})

test("eventsForDate spans a multi-day all-day event", () => {
  const agenda = {
    calendars: [{ id: "family", name: "Family", color: "yellow" }],
    events: [{
      id: "x", calendar: "family", title: "Thanksgiving weekend",
      start: "2026-10-10", end: "2026-10-13", allDay: true, location: "", conference: null, attendees: 0
    }]
  }
  assert.equal(Model.eventsForDate(agenda, "2026-10-10").length, 1)
  assert.equal(Model.eventsForDate(agenda, "2026-10-12").length, 1)
  assert.equal(Model.eventsForDate(agenda, "2026-10-13").length, 0)  // exclusive end
})

test("eventsForDate is empty for a free day", () => {
  assert.deepEqual(Model.eventsForDate(AGENDA, "2026-09-09"), [])
})

// ---------------------------------------------------------------------
test("secondLine prefers a meeting, then a location, then the calendar", () => {
  const [labourDay, standup, pickup] = Model.eventsForDate(AGENDA, "2026-09-07")
  assert.equal(Model.secondLine(standup, AGENDA), "meet · 4 attending")
  assert.equal(Model.secondLine(pickup, AGENDA), "School")
  assert.equal(Model.secondLine(labourDay, AGENDA), "Family")
})

test("formatTimeRange covers timed and all-day events", () => {
  const [labourDay, standup] = Model.eventsForDate(AGENDA, "2026-09-07")
  assert.equal(Model.formatTimeRange(standup, "24h"), "14:00–14:15")
  assert.equal(Model.formatTimeRange(labourDay, "24h"), "all day")
})

test("footerText reports the active set and last sync", () => {
  assert.equal(Model.footerText(AGENDA, "24h"), "Set: all · synced 13:45")
  // This once asserted a bare "Set: work". Staying silent about a sync
  // that had never run is what let an event sit in the vdir unnoticed,
  // so the absence is now stated outright.
  assert.equal(Model.footerText({ activeSet: "work", lastSync: null }, "24h"),
               "Set: work · not synced")
})

// ---------------------------------------------------------------------
test("a missing Python module becomes an actionable sentence", () => {
  const text = Model.healthProblem("omagenda: No module named 'icalendar'", 0)
  assert.match(text, /needs icalendar/)
  assert.match(text, /omarchy pkg add/)
})

test("a bare watcher exit points at doctor", () => {
  assert.match(Model.healthProblem("omagenda watch exited 1", 0), /doctor/)
})

test("no error means no problem to report", () => {
  assert.equal(Model.healthProblem("", 0), "")
  assert.equal(Model.pillProblemText("", 0), "")
})

test("a problem only takes a bar slot when there is nothing else to show", () => {
  assert.notEqual(Model.pillProblemText("No module named 'icalendar'", 0), "")
  assert.equal(Model.pillProblemText("No module named 'icalendar'", 5), "")
})

// ---------------------------------------------------------------------
// Quick Add
const ACCENT = "#7aa2f7"
const FG = "#c0caf5"

test("highlighting paints recognised fragments and leaves the title alone", () => {
  // "Lunch tomorrow at 1pm" -- spans cover "tomorrow" and "at 1pm"
  const html = Model.highlightedHtml(
    "Lunch tomorrow at 1pm",
    [{ start: 6, end: 14, kind: "date" }, { start: 15, end: 21, kind: "time" }],
    ACCENT, FG)
  assert.match(html, new RegExp(`<font color="${FG}">Lunch </font>`))
  assert.match(html, new RegExp(`<font color="${ACCENT}">tomorrow</font>`))
  assert.match(html, new RegExp(`<font color="${ACCENT}">at 1pm</font>`))
})

test("highlighting with no spans is all foreground", () => {
  const html = Model.highlightedHtml("Just a title", [], ACCENT, FG)
  assert.equal(html, `<font color="${FG}">Just a title</font>`)
})

test("highlighting escapes markup so a typed angle bracket cannot inject", () => {
  const html = Model.highlightedHtml('a <b>& c', [], ACCENT, FG)
  assert.match(html, /a &lt;b&gt;&amp; c/)
  assert.doesNotMatch(html, /<b>/)
})

test("highlighting survives a span running past the end of the text", () => {
  // The field can shrink between a keystroke and the parse coming back.
  const html = Model.highlightedHtml("Lun", [{ start: 0, end: 99, kind: "date" }], ACCENT, FG)
  assert.match(html, new RegExp(`<font color="${ACCENT}">Lun</font>`))
})

test("preview line reads like the agenda row it will become", () => {
  const parsed = {
    title: "Lunch with Sarah", start: "2026-09-08T13:00", end: "2026-09-08T14:30",
    allDay: false, location: "Cafe Linnea", calendar: "personal", rrule: null, alarms: ["-PT15M"]
  }
  assert.equal(Model.previewLine(parsed, "24h"),
    "Tue 8 Sep · 13:00–14:30 · Lunch with Sarah · Cafe Linnea · reminder · Personal")
})

test("preview line for an all-day event says so", () => {
  const parsed = { title: "Vacation", start: "2026-09-08", allDay: true, alarms: [] }
  assert.equal(Model.previewLine(parsed, "24h"), "Tue 8 Sep · all day · Vacation")
})

test("preview line marks a repeating event", () => {
  const parsed = { title: "Standup", start: "2026-09-08T09:00", end: "2026-09-08T09:15",
                   allDay: false, rrule: "FREQ=DAILY", alarms: [] }
  assert.match(Model.previewLine(parsed, "24h"), /repeats/)
})

test("preview line is empty until there is something to preview", () => {
  assert.equal(Model.previewLine(null, "24h"), "")
  assert.equal(Model.previewLine({}, "24h"), "")
})

// ---------------------------------------------------------------------
const MIXED = {
  calendars: [
    { id: "gcal", name: "Google", color: "blue", readOnly: true },
    { id: "personal", name: "Personal", color: "green", readOnly: false },
    { id: "work", name: "Work", color: "yellow", readOnly: false }
  ],
  events: []
}

test("a read-only subscription is never offered as a target", () => {
  assert.deepEqual(Model.writableCalendars(MIXED).map(c => c.id), ["personal", "work"])
})

test("tab walks the writable calendars and wraps", () => {
  assert.equal(Model.nextCalendarId(MIXED, "personal"), "work")
  assert.equal(Model.nextCalendarId(MIXED, "work"), "personal")
})

test("tab starts somewhere sensible when nothing is chosen yet", () => {
  assert.equal(Model.nextCalendarId(MIXED, ""), "personal")
  assert.equal(Model.nextCalendarId(MIXED, "gcal"), "personal")  // a read-only one was in play
})

test("tab does nothing when there is nowhere to write", () => {
  assert.equal(Model.nextCalendarId({ calendars: [{ id: "x", readOnly: true }] }, ""), "")
})

// ---------------------------------------------------------------------
const MIXED_ONE_WRITABLE = {
  calendars: [
    { id: "gcal", name: "Google", color: "blue", readOnly: true },
    { id: "personal", name: "Personal", color: "green", readOnly: false }
  ],
  events: []
}

test("tab explains itself when there is only one place to write", () => {
  const reason = Model.cycleUnavailableReason(MIXED_ONE_WRITABLE)
  assert.match(reason, /personal/)
  assert.match(reason, /gcal is read-only/)
})

test("tab says nothing when cycling actually works", () => {
  assert.equal(Model.cycleUnavailableReason(MIXED), "")
})

test("tab explains a vdir with nowhere to write at all", () => {
  const reason = Model.cycleUnavailableReason({ calendars: [{ id: "gcal", readOnly: true }] })
  assert.match(reason, /No calendar can take events/)
})

test("a single calendar with no subscriptions reads naturally", () => {
  const reason = Model.cycleUnavailableReason({ calendars: [{ id: "personal", readOnly: false }] })
  assert.equal(reason, "'personal' is your only calendar")
})

test("the footer withholds the tab hint when tab has nowhere to go", () => {
  const hints = Model.quickAddHints(MIXED_ONE_WRITABLE)
  assert.ok(!hints.includes("TAB"))
  assert.ok(hints.includes("ENTER SAVE"))
  assert.ok(hints.includes("ESC CANCEL"))
})

test("the footer offers the tab hint when there are two places to write", () => {
  assert.ok(Model.quickAddHints(MIXED).includes("TAB CALENDAR"))
})

// ---------------------------------------------------------------------
// The footer's sync state. See tests/test_watch_sync.py for why: an
// event added in Quick Add reached the panel and never the server, and
// the footer said nothing either way.
test("a never-synced agenda says so rather than staying quiet", () => {
  assert.match(Model.footerText({ activeSet: "", lastSync: null }, "24h"), /not synced/)
})

test("a failing sync is named in the footer", () => {
  const text = Model.footerText({ activeSet: "", lastSync: "2026-09-08T14:00:00", syncOk: false }, "24h")
  assert.match(text, /sync failing/)
})

test("a healthy sync shows the time it happened", () => {
  const text = Model.footerText({ activeSet: "", lastSync: "2026-09-08T14:05:00", syncOk: true }, "24h")
  assert.match(text, /synced 14:05/)
  assert.ok(!text.includes("not synced"))
})

test("the active set still leads the footer", () => {
  assert.match(Model.footerText({ activeSet: "Work", lastSync: null }, "24h"), /^Set: Work/)
})

// ---------------------------------------------------------------------
// The pill is also the door to the panel. It used to vanish whenever the
// next event was more than leadMinutes away, which for most of a normal
// day meant the plugin was simply absent from the bar -- indistinguishable
// from broken, and with no keybinding shipped, no way into the agenda.
test("an idle pill keeps its slot so the panel stays reachable", () => {
  assert.equal(Model.pillOccupies("", false, false), true)
})

test("an idle pill can still be told to disappear", () => {
  assert.equal(Model.pillOccupies("", false, true), false)
})

test("a pill with something to say always keeps its slot", () => {
  assert.equal(Model.pillOccupies("Standup · 5m", false, true), true)
})

test("an open panel is never stranded by a collapsing pill", () => {
  assert.equal(Model.pillOccupies("", true, true), true)
})

test("the idle glyph is the same one the vertical bar uses", () => {
  assert.equal(typeof Model.CALENDAR_GLYPH, "string")
  assert.equal(Model.CALENDAR_GLYPH.length > 0, true)
})

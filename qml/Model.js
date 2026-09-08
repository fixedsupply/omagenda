// Pure functions for the bar pill and agenda panel: countdown text, pill
// visibility rules, ticker day layout, agenda grouping, time formatting,
// and the theme's named-colour palette.
//
// Everything here takes `now` explicitly rather than reading the clock, so
// tests/model.test.js can pin it. See ARCHITECTURE.md §8.

// ---------------------------------------------------------------------
// Theme palette
// ---------------------------------------------------------------------
// agenda.json gives each calendar a theme colour *name* ("blue", "green"),
// never a hex value, so a theme switch repaints every calendar without
// Omagenda storing anything. The shell's own Color singleton only exposes
// foreground/background/accent/urgent/muted, though -- the named palette
// lives in the theme's colors.toml and nothing surfaces it -- so the
// plugin parses that file itself. Same file Color.qml reads, same values.
function parsePalette(tomlText) {
  var palette = {}
  var lines = String(tomlText || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var match = lines[i].match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(#[0-9a-fA-F]{3,8})"/)
    if (match) palette[match[1]] = match[2]
  }
  return palette
}

// Resolve a calendar's colour name against the theme, falling back to the
// foreground colour when a theme simply doesn't define that name.
function paletteColor(palette, name, fallback) {
  if (!name) return fallback
  var value = palette ? palette[String(name).toLowerCase()] : null
  return value || fallback
}

function calendarColorName(agenda, calendarId) {
  var calendars = (agenda && agenda.calendars) || []
  for (var i = 0; i < calendars.length; i++) {
    if (calendars[i].id === calendarId) return calendars[i].color
  }
  return ""
}

function calendarName(agenda, calendarId) {
  var calendars = (agenda && agenda.calendars) || []
  for (var i = 0; i < calendars.length; i++) {
    if (calendars[i].id === calendarId) return calendars[i].name || calendars[i].id
  }
  return calendarId || ""
}

// ---------------------------------------------------------------------
// Dates and times
// ---------------------------------------------------------------------
function toDate(value) {
  if (value instanceof Date) return value
  var text = String(value || "")
  // An all-day date ("2026-09-08") parses as UTC midnight in JS, which
  // lands on the previous day west of Greenwich. Build it as local noon
  // instead so every comparison and label stays on the intended day.
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    var parts = text.split("-")
    return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12, 0, 0)
  }
  return new Date(text)
}

function dateKey(value) {
  var d = toDate(value)
  var month = String(d.getMonth() + 1)
  var day = String(d.getDate())
  return d.getFullYear() + "-" + (month.length < 2 ? "0" + month : month) + "-" + (day.length < 2 ? "0" + day : day)
}

function addDays(value, count) {
  var d = toDate(value)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + count, 12, 0, 0)
}

function isAllDayString(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))
}

// "system" defers to the locale; callers pass what Qt.locale() reports so
// this stays pure.
function resolveTimeFormat(setting, localeUses24h) {
  if (setting === "24h" || setting === "12h") return setting
  return localeUses24h ? "24h" : "12h"
}

function formatTime(value, timeFormat) {
  if (isAllDayString(value)) return "all day"
  var d = toDate(value)
  var hours = d.getHours()
  var minutes = d.getMinutes()
  var mm = minutes < 10 ? "0" + minutes : String(minutes)
  if (timeFormat === "12h") {
    var suffix = hours < 12 ? "am" : "pm"
    var h12 = hours % 12
    if (h12 === 0) h12 = 12
    return minutes === 0 ? h12 + suffix : h12 + ":" + mm + suffix
  }
  var hh = hours < 10 ? "0" + hours : String(hours)
  return hh + ":" + mm
}

function formatTimeRange(event, timeFormat) {
  if (event.allDay) return "all day"
  var start = formatTime(event.start, timeFormat)
  var end = formatTime(event.end, timeFormat)
  return start + "–" + end
}

// Compact enough for a bar pill: "12m", "1h 5m", "2h", "3d".
function countdownText(target, now) {
  var deltaMs = toDate(target).getTime() - toDate(now).getTime()
  var minutes = Math.round(deltaMs / 60000)
  if (minutes <= 0) return "now"
  if (minutes < 60) return minutes + "m"
  var hours = Math.floor(minutes / 60)
  var remainder = minutes % 60
  if (hours < 24) return remainder ? hours + "h " + remainder + "m" : hours + "h"
  return Math.round(hours / 24) + "d"
}

// ---------------------------------------------------------------------
// Event selection
// ---------------------------------------------------------------------
function sortedEvents(agenda) {
  var events = ((agenda && agenda.events) || []).slice()
  events.sort(function(a, b) {
    var aKey = dateKey(a.start) + (a.allDay ? " 0" : " 1") + (a.allDay ? "" : String(a.start).slice(11, 19))
    var bKey = dateKey(b.start) + (b.allDay ? " 0" : " 1") + (b.allDay ? "" : String(b.start).slice(11, 19))
    return aKey < bKey ? -1 : (aKey > bKey ? 1 : 0)
  })
  return events
}

// The event the hero and the pill both describe: whatever is running now,
// else the next one to start. All-day events never take the slot -- a
// pill that says "Thanksgiving · now" for sixteen hours is noise, and the
// hero has the same problem.
function currentOrNextEvent(agenda, now) {
  var nowMs = toDate(now).getTime()
  var events = sortedEvents(agenda)
  var next = null
  for (var i = 0; i < events.length; i++) {
    var event = events[i]
    if (event.allDay) continue
    var startMs = toDate(event.start).getTime()
    var endMs = toDate(event.end).getTime()
    if (startMs <= nowMs && nowMs < endMs) return event
    if (startMs > nowMs && (next === null || startMs < toDate(next.start).getTime())) next = event
  }
  return next
}

function isRunning(event, now) {
  if (!event || event.allDay) return false
  var nowMs = toDate(now).getTime()
  return toDate(event.start).getTime() <= nowMs && nowMs < toDate(event.end).getTime()
}

// ---------------------------------------------------------------------
// Bar pill
// ---------------------------------------------------------------------
// Returns "" when the pill should not be in the bar at all. The bar's
// centre shifts the moment a widget appears, so the default is to stay out
// of the way until an event is actually close (`leadMinutes`), unless the
// user asked for a permanent slot (`alwaysShow`).
function pillText(agenda, now, options) {
  options = options || {}
  var leadMinutes = options.leadMinutes === undefined ? 30 : options.leadMinutes
  var alwaysShow = !!options.alwaysShow
  var showCountdown = options.showCountdown === undefined ? true : !!options.showCountdown
  var timeFormat = options.timeFormat || "24h"

  var event = currentOrNextEvent(agenda, now)
  if (!event) return alwaysShow ? "Nothing scheduled" : ""

  if (isRunning(event, now)) {
    return showCountdown ? event.title + " · now" : event.title
  }

  var minutesAway = Math.round((toDate(event.start).getTime() - toDate(now).getTime()) / 60000)
  if (minutesAway > leadMinutes) {
    if (!alwaysShow) return ""
    return event.title + " · " + formatTime(event.start, timeFormat)
  }
  return showCountdown ? event.title + " · " + countdownText(event.start, now) : event.title
}

// A plugin that is enabled but broken must not look like a plugin with
// nothing to report. When the watcher can't run -- overwhelmingly because
// the calendar libraries aren't installed -- both surfaces say so instead
// of rendering an empty, indistinguishable "nothing scheduled".
function healthProblem(serviceError, eventCount) {
  var error = String(serviceError || "")
  if (!error) return ""
  // An error while events are already on screen is worth reporting in the
  // panel but not worth hijacking the bar, so callers decide what to do
  // with it; this only names the problem.
  if (/No module named/.test(error)) {
    var match = error.match(/No module named '([^']+)'/)
    var missing = match ? match[1] : "a Python module"
    return "Omagenda needs " + missing + ": omarchy pkg add python-icalendar python-dateutil python-recurring-ical-events"
  }
  if (/watch exited/.test(error)) return "The Omagenda watcher stopped: run 'omagenda doctor' to see why"
  return error
}

function pillProblemText(serviceError, eventCount) {
  // Only take a bar slot for a problem when there is nothing else to show;
  // a stale-but-populated agenda is still more useful than a warning.
  if (eventCount > 0) return ""
  return healthProblem(serviceError, eventCount) ? "󰃭 !" : ""
}

// ---------------------------------------------------------------------
// Ticker strip
// ---------------------------------------------------------------------
var WEEKDAY_LABELS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]

function tickerDays(agenda, startDate, selectedDate, dayCount, maxDots) {
  var days = []
  var count = dayCount || 7
  var dotCap = maxDots || 3
  var todayKey = dateKey(startDate)
  var selectedKey = dateKey(selectedDate || startDate)
  var events = sortedEvents(agenda)

  for (var i = 0; i < count; i++) {
    var date = addDays(startDate, i)
    var key = dateKey(date)
    var dots = []
    for (var j = 0; j < events.length && dots.length < dotCap; j++) {
      if (dateKey(events[j].start) === key) {
        var color = calendarColorName(agenda, events[j].calendar)
        if (color) dots.push(color)
      }
    }
    days.push({
      key: key,
      weekday: WEEKDAY_LABELS[date.getDay()],
      day: date.getDate(),
      isToday: key === todayKey,
      isSelected: key === selectedKey,
      dots: dots
    })
  }
  return days
}

// ---------------------------------------------------------------------
// Agenda list
// ---------------------------------------------------------------------
function eventsForDate(agenda, dateValue) {
  var key = dateKey(dateValue)
  var events = sortedEvents(agenda)
  var result = []
  for (var i = 0; i < events.length; i++) {
    var event = events[i]
    if (event.allDay) {
      // An all-day event's DTEND is exclusive, so a single-day event ends
      // the next morning; it belongs to every day from start to end-1.
      var startKey = dateKey(event.start)
      var endKey = dateKey(event.end)
      if (key >= startKey && key < endKey) result.push(event)
      else if (startKey === endKey && key === startKey) result.push(event)
    } else if (dateKey(event.start) === key) {
      result.push(event)
    }
  }
  return result
}

function secondLine(event, agenda) {
  if (event.conference && event.conference.url) {
    var provider = event.conference.provider || "meeting"
    var attendees = event.attendees ? " · " + event.attendees + " attending" : ""
    return provider + attendees
  }
  if (event.location) return event.location
  return calendarName(agenda, event.calendar)
}

function footerText(agenda, timeFormat) {
  var set = (agenda && agenda.activeSet) || ""
  var synced = agenda && agenda.lastSync ? formatTime(agenda.lastSync, timeFormat) : ""
  var left = "Set: " + (set || "all")
  return synced ? left + " · synced " + synced : left
}

// ---------------------------------------------------------------------
// Exports for node:test. QML loads this file with `import "Model.js"`,
// which ignores module.exports entirely.
// ---------------------------------------------------------------------
if (typeof module !== "undefined") {
  module.exports = {
    parsePalette: parsePalette,
    paletteColor: paletteColor,
    calendarColorName: calendarColorName,
    calendarName: calendarName,
    toDate: toDate,
    dateKey: dateKey,
    addDays: addDays,
    isAllDayString: isAllDayString,
    resolveTimeFormat: resolveTimeFormat,
    formatTime: formatTime,
    formatTimeRange: formatTimeRange,
    countdownText: countdownText,
    sortedEvents: sortedEvents,
    currentOrNextEvent: currentOrNextEvent,
    isRunning: isRunning,
    pillText: pillText,
    healthProblem: healthProblem,
    pillProblemText: pillProblemText,
    tickerDays: tickerDays,
    eventsForDate: eventsForDate,
    secondLine: secondLine,
    footerText: footerText
  }
}

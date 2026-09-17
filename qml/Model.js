// Pure functions for the bar pill and agenda panel: countdown text, pill
// visibility rules, ticker day layout, agenda grouping, time formatting,
// and the theme's named-colour palette.
//
// Everything here takes `now` explicitly rather than reading the clock, so
// tests/model.test.js can pin it. See ARCHITECTURE.md §8.

// ---------------------------------------------------------------------
// Theme palette
// ---------------------------------------------------------------------
var THEME_COLOR_ORDER = ["blue", "green", "magenta", "yellow", "cyan", "red", "orange"]
// RGB distance below 40 is indistinguishable at a calendar-dot size; it
// separates the named colours in the stock themes while grouping close greens.
var NEAR_DUPLICATE_RGB_DISTANCE = 40
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

function rgbColor(value) {
  var match = String(value || "").match(/^#([0-9a-f]{6})/i)
  if (!match) return null
  return [parseInt(match[1].slice(0, 2), 16), parseInt(match[1].slice(2, 4), 16), parseInt(match[1].slice(4, 6), 16)]
}

function nearDuplicateColor(left, right) {
  var a = rgbColor(left)
  var b = rgbColor(right)
  if (!a || !b) return false
  var red = a[0] - b[0]
  var green = a[1] - b[1]
  var blue = a[2] - b[2]
  return Math.sqrt(red * red + green * green + blue * blue) < NEAR_DUPLICATE_RGB_DISTANCE
}

function isDistinctFromChosen(value, chosen) {
  if (!rgbColor(value)) return false
  for (var i = 0; i < chosen.length; i++) {
    if (nearDuplicateColor(value, chosen[i])) return false
  }
  return true
}

// Calendar colour names are stable in agenda.json. Resolve only collisions
// from this theme to another colour already provided by that same theme.
// A substitute colour must stay visible on the theme background. WCAG's
// minimum contrast for user-interface components is 3:1. With no background
// defined, any substitute is allowed.
var SUBSTITUTE_MIN_CONTRAST = 3

function relativeLuminance(hex) {
  var rgb = rgbColor(hex)
  if (!rgb) return null
  var channel = function(value) {
    var c = value / 255
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])
}

function readableOn(color, background) {
  var fg = relativeLuminance(color)
  if (fg === null) return false
  var bg = relativeLuminance(background)
  if (bg === null) return true
  var lighter = Math.max(fg, bg), darker = Math.min(fg, bg)
  return (lighter + 0.05) / (darker + 0.05) >= SUBSTITUTE_MIN_CONTRAST
}

function resolvedPalette(palette) {
  palette = palette || {}
  var resolved = {}
  var chosen = []
  for (var i = 0; i < THEME_COLOR_ORDER.length; i++) {
    var name = THEME_COLOR_ORDER[i]
    var own = palette[name]
    if (!own) continue
    var value = own
    if (!isDistinctFromChosen(own, chosen)) {
      // Bright variants first: in most themes `brown` is dark, and on a dark
      // background a "separated" calendar would become the hardest to see.
      var substitutes = []
      for (var bright = 0; bright < 6; bright++) substitutes.push("bright_" + THEME_COLOR_ORDER[bright])
      substitutes.push("brown")
      for (var other = 0; other < THEME_COLOR_ORDER.length; other++) {
        if (THEME_COLOR_ORDER[other] !== name) substitutes.push(THEME_COLOR_ORDER[other])
      }
      for (var candidate = 0; candidate < substitutes.length; candidate++) {
        var substitute = palette[substitutes[candidate]]
        if (isDistinctFromChosen(substitute, chosen) && readableOn(substitute, palette.background)) {
          value = substitute
          break
        }
      }
    }
    resolved[name] = value
    if (rgbColor(value)) chosen.push(value)
  }
  return resolved
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

function eventCalendar(agenda, event) {
  return ((agenda && agenda.calendars) || []).find(function(c) { return event && c.id === event.calendar }) || null
}

function calendarProviderLabel(calendar) {
  var labels = { google: "Google", icloud: "iCloud", caldav: "CalDAV", ics: "Subscription", local: "Local" }
  return labels[(calendar && calendar.provider) || "local"] || "Local"
}

function calendarLine(agenda, event) {
  var calendar = eventCalendar(agenda, event)
  return calendar ? (calendar.name + " · " + calendarProviderLabel(calendar)) : ""
}

function calendarWebTarget(agenda, event) {
  if (event && event.webUrl) return event.webUrl
  var calendar = eventCalendar(agenda, event)
  return calendar && calendar.webUrl ? calendar.webUrl : ""
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

// The pill is also the only way into the panel, so a pill that vanishes
// takes the panel with it -- and with no keybinding shipped yet, that
// left the plugin unreachable for most of the day and looking broken
// besides. Idle now keeps the calendar glyph: a square slot, still
// clickable, without a permanent sentence in the bar's centre. Anyone who
// preferred the disappearing act sets collapseWhenIdle.
var CALENDAR_GLYPH = "󰃭"

function pillOccupies(label, opened, collapseWhenIdle) {
  if (opened) return true          // never strand an open panel
  if (label !== "") return true
  return !collapseWhenIdle
}

// An expired sign-in is the one sync failure the user has to act on, and
// the only one that never resolves itself, so it outranks everything else
// the panel might report. A Google OAuth client left in Testing mode
// expires its refresh tokens weekly, which makes this routine rather than
// exotic -- and its raw form, "HTTP Error 400: Bad Request", tells nobody
// what to do.
function syncProblem(agenda) {
  if (!agenda) return ""
  var accounts = agenda.needsReauth || []
  if (accounts.length === 0) return ""
  var who = accounts.length === 1
    ? "Omagenda's sign-in for '" + accounts[0] + "' has expired"
    : "Omagenda's sign-in has expired for " + accounts.join(", ")
  return agenda.syncRemedy ? who + ". " + agenda.syncRemedy : who
}

function needsReauth(agenda) {
  return !!(agenda && agenda.needsReauth && agenda.needsReauth.length > 0)
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

function clampSelectedDay(selectedKey, todayKey, range) {
  var first = todayKey
  var last = range && range.to ? dateKey(addDays(range.to, -1)) : todayKey
  if (last < first) last = first
  if (selectedKey < first) return first
  if (selectedKey > last) return last
  return selectedKey
}

function stripStartFor(currentStart, selectedKey, todayKey, dayCount) {
  var start = dateKey(currentStart || todayKey)
  var selected = dateKey(selectedKey)
  var today = dateKey(todayKey)
  var count = Math.max(1, Number(dayCount) || 7)
  if (start < today) start = today
  if (selected < today) return today
  var offset = Math.floor((toDate(selected).getTime() - toDate(today).getTime()) / 86400000)
  return dateKey(addDays(today, Math.floor(offset / count) * count))
}

function relativeDayHint(selectedKey, todayKey) {
  var days = Math.round((toDate(selectedKey).getTime() - toDate(todayKey).getTime()) / 86400000)
  return days > 1 ? "in " + days + " days" : ""
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
  agenda = agenda || {}
  var left = agenda.visibleCalendarCount < agenda.calendarCount
    ? agenda.visibleCalendarCount + " of " + agenda.calendarCount + " calendars · " : ""
  // A sync that has never run once read the same as one that had just
  // succeeded, because nothing ever wrote lastSync. Both states are now
  // named, since "my event never reached my phone" is only diagnosable
  // if the panel admits which one it is.
  if (agenda.syncPausedUntil)
    return left + "sync paused until " + formatTime(agenda.syncPausedUntil, timeFormat)
  if (agenda.syncOk === false) return left + "sync failing"
  if (!agenda.lastSync) return left + "not synced"
  return left + "synced " + formatTime(agenda.lastSync, timeFormat)
}

// ---------------------------------------------------------------------
// Quick Add
// ---------------------------------------------------------------------
function escapeHtml(text) {
  return String(text === undefined || text === null ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

// The typed sentence with every fragment the parser recognised painted in
// the accent colour, as Text.StyledText markup. The field is a plain Text
// driven by key events rather than a TextInput (the reminders overlay does
// the same), so there is no real caret fighting the markup -- the caret is
// drawn as a character at the end.
//
// Spans arrive sorted and non-overlapping from parse.py; anything between
// them is title text and stays in the foreground colour.
function highlightedHtml(text, spans, accentColor, foregroundColor) {
  var source = String(text || "")
  var ordered = (spans || []).slice().sort(function(a, b) { return a.start - b.start })
  var out = ""
  var cursor = 0
  for (var i = 0; i < ordered.length; i++) {
    var span = ordered[i]
    if (span.start < cursor || span.start > source.length) continue
    out += '<font color="' + foregroundColor + '">' + escapeHtml(source.slice(cursor, span.start)) + "</font>"
    out += '<font color="' + accentColor + '">' + escapeHtml(source.slice(span.start, span.end)) + "</font>"
    cursor = Math.min(span.end, source.length)
  }
  out += '<font color="' + foregroundColor + '">' + escapeHtml(source.slice(cursor)) + "</font>"
  return out
}

// The line under the field: what will actually be written, in the same
// shape the agenda renders it, so the preview and the result agree.
function previewLine(parsed, timeFormat) {
  if (!parsed || !parsed.start) return ""
  var bits = []
  var startsAllDay = parsed.allDay === true

  var d = toDate(parsed.start)
  bits.push(WEEKDAY_LABELS[d.getDay()].charAt(0) + WEEKDAY_LABELS[d.getDay()].slice(1).toLowerCase()
    + " " + d.getDate() + " " + MONTH_LABELS[d.getMonth()])

  if (startsAllDay) bits.push("all day")
  else bits.push(formatTime(parsed.start, timeFormat) + (parsed.end ? "–" + formatTime(parsed.end, timeFormat) : ""))

  bits.push(parsed.title || "Untitled")
  if (parsed.location) bits.push(parsed.location)
  if (parsed.rrule) bits.push("repeats")
  if (parsed.alarms && parsed.alarms.length) bits.push("reminder")
  if (parsed.calendar) bits.push(parsed.calendar.charAt(0).toUpperCase() + parsed.calendar.slice(1))
  return bits.join(" · ")
}

var MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

// Calendars an event can actually be written to. A read-only subscription
// is in the agenda but can never be a target, so it is never offered.
function writableCalendars(agenda) {
  var calendars = (agenda && agenda.calendars) || []
  var out = []
  for (var i = 0; i < calendars.length; i++) {
    if (!calendars[i].readOnly && !calendars[i].hidden) out.push(calendars[i])
  }
  return out
}

// Why Tab did nothing, in the user's terms. Silence is the wrong answer:
// with a single writable calendar the key appears broken, when in fact
// there is simply nowhere else an event could go.
function cycleUnavailableReason(agenda, currentId) {
  var writable = writableCalendars(agenda)
  if (writable.length > 1 || (writable.length === 1 && currentId && writable[0].id !== currentId)) return ""
  if (((agenda && agenda.calendars) || []).some(function(c) { return c.hidden }))
    return writable.length ? "Only one visible calendar can take events" : "No visible calendar can take events"
  var readOnly = ((agenda && agenda.calendars) || []).filter(function(c) { return c.readOnly })
  if (writable.length === 1) {
    if (readOnly.length === 0) return "'" + writable[0].id + "' is your only calendar"
    var names = readOnly.map(function(c) { return c.id }).join(", ")
    return "'" + writable[0].id + "' is the only calendar that can take events ("
      + names + (readOnly.length === 1 ? " is" : " are") + " read-only)"
  }
  return "No calendar can take events; every one found is read-only"
}

function eventCalendar(agenda, event) {
  return event && ((agenda && agenda.calendars) || []).filter(function(c) { return c.id === event.calendar })[0]
}

function eventOpenTarget(event) {
  if (!event) return ""
  return (event.conference && event.conference.url) || event.url
    || (event.location && /^https?:\/\//.test(event.location) ? event.location : "")
}

function editReason(agenda, event) {
  var calendar = eventCalendar(agenda, event)
  if (!event || !event.file || !calendar) return "No event file selected"
  if (calendar.readOnly) return "'" + calendar.name + "' is read-only, so its events can't be edited here"
  if (event.recurring) return "Recurring events can't be edited from Omagenda yet; edit it in " + calendar.name + "'s own app"
  if (event.attendees && event.attendees.length) return "Events with guests can't be edited from Omagenda yet; edit it in " + calendar.name + "'s own app"
  return ""
}

function eventEditable(agenda, event) {
  return editReason(agenda, event) === ""
}

function deleteReason(agenda, event) {
  var calendar = eventCalendar(agenda, event)
  if (!event || !event.file || !calendar) return "No event file selected"
  if (calendar.readOnly) return "'" + calendar.name + "' is read-only, so its events can't be deleted here"
  if (event.recurring) return "Recurring events can't be deleted from Omagenda yet; delete it in " + calendar.name + "'s own app"
  return ""
}

function eventActionHints(agenda, event) {
  var hints = []
  if (eventEditable(agenda, event)) hints.push("E EDIT")
  if (deleteReason(agenda, event) === "") hints.push("X DELETE")
  if (eventOpenTarget(event)) hints.push("O OPEN")
  var web = calendarWebTarget(agenda, event)
  if (web) hints.push(eventCalendar(agenda, event).provider === "icloud" ? "W OPEN ICLOUD CALENDAR" : "W OPEN IN GOOGLE")
  return hints.join(" · ")
}

function deleteTransition(state, action, agenda, event, choosingCalendars) {
  if (action !== "delete") {
    if (["escape", "move", "day", "c", "t", "n", "close", "selection", "timeout"].indexOf(action) !== -1)
      return { pending: "", message: "", confirm: "" }
    return state
  }
  if (choosingCalendars) return state
  var reason = deleteReason(agenda, event)
  if (reason) return { pending: "", message: reason, confirm: "" }
  if (state.pending === event.file) return { pending: "", message: "", confirm: event.file }
  return { pending: event.file, message: "", confirm: "" }
}

// Assigning a new but identical state still notifies every binding that
// reads it. Panel.cancelDelete runs from property-change handlers, some
// of them during the first evaluation of `deleteHint` itself, and that
// no-op write was the "Binding loop detected for property deleteHint".
function sameDeleteState(a, b) {
  a = a || {}; b = b || {}
  return (a.pending || "") === (b.pending || "") && (a.message || "") === (b.message || "")
    && (a.confirm || "") === (b.confirm || "")
}

function deleteHint(state, event) {
  if (state.pending && event && state.pending === event.file) {
    var title = (event.title || "Untitled").toUpperCase()
    if (title.length > 36) title = title.slice(0, 35) + "…"
    return "DELETE '" + title + "'? X TO CONFIRM · ESC TO CANCEL"
  }
  return state.message || ""
}

// A delete/edit holds the same lock as sync. Name that wait explicitly so a
// second key press is not mistaken for a failed first request.
function saveProgressText(running, waiting) {
  if (!running) return ""
  return waiting ? "Saving… waiting for sync to finish" : "Saving…"
}

function deleteProgressHint(title, waiting) {
  var label = String(title || "Untitled").toUpperCase()
  if (label.length > 36) label = label.slice(0, 35) + "…"
  var hint = "DELETING '" + label + "'…"
  return waiting ? hint + " WAITING FOR SYNC TO FINISH" : hint
}

// The footer only advertises keys that do something. Offering "TAB
// CALENDAR" when there is one writable calendar teaches the user the
// feature is broken; withdrawing it teaches them nothing false.
function quickAddHints(agenda, currentId, editing) {
  if (editing) return "ENTER SAVE · ESC CANCEL"
  var base = ["ENTER SAVE", "SHIFT+ENTER SAVE AND ADD ANOTHER"]
  if (cycleUnavailableReason(agenda, currentId) === "") base.push("TAB CALENDAR")
  base.push("ESC CANCEL")
  return base.join(" \u00b7 ")
}

// Tab walks the writable calendars, starting from whichever is in play.
function nextCalendarId(agenda, currentId) {
  var writable = writableCalendars(agenda)
  if (writable.length === 0) return ""
  for (var i = 0; i < writable.length; i++) {
    if (writable[i].id === currentId) return writable[(i + 1) % writable.length].id
  }
  return writable[0].id
}

// Each queued operation records an absolute value, including repeated clicks
// on the same row. Completing one operation never discards later intent.
function visibilityQueue(queue, action) {
  if (action.type === "complete") return queue.slice(1)
  if (action.type === "toggle")
    return queue.concat([{ id: action.id, hidden: !action.hidden }])
  return queue.slice()
}

// A successful agenda load acknowledges recovery only after every write finishes.
function visibilityFailureAfterLoad(failure, running, queue) {
  return running || queue.length > 0 ? failure : ""
}

function calendarRows(agenda, queue) {
  var groups = []
  var rows = []
  ;((agenda && agenda.calendars) || []).forEach(function(calendar) {
    var group = calendar.id.indexOf("/") < 0 ? "LOCAL" : calendar.id.split("/")[0].toUpperCase()
    var row = Object.assign({}, calendar, { group: group })
    ;(queue || []).forEach(function(op) { if (op.id === row.id) row.hidden = op.hidden })
    if (groups.indexOf(group) < 0) groups.push(group)
    rows.push(row)
  })
  return groups.reduce(function(out, group) {
    return out.concat(rows.filter(function(row) { return row.group === group }))
  }, [])
}

function destinationText(agenda, id) {
  var calendar = ((agenda && agenda.calendars) || []).find(function(c) { return c.id === id })
  return "→ " + (calendar ? calendar.name : id) + (calendar && calendar.hidden ? " (hidden)" : "")
}

// ---------------------------------------------------------------------
// Exports for node:test. QML loads this file with `import "Model.js"`,
// which ignores module.exports entirely.
// ---------------------------------------------------------------------
if (typeof module !== "undefined") {
  module.exports = {
    parsePalette: parsePalette,
    resolvedPalette: resolvedPalette,
    readableOn: readableOn,
    paletteColor: paletteColor,
    calendarColorName: calendarColorName,
    calendarName: calendarName,
    eventCalendar: eventCalendar,
    calendarProviderLabel: calendarProviderLabel,
    calendarLine: calendarLine,
    calendarWebTarget: calendarWebTarget,
    toDate: toDate,
    eventOpenTarget: eventOpenTarget,
    eventEditable: eventEditable,
    editReason: editReason,
    deleteReason: deleteReason,
    eventActionHints: eventActionHints,
    deleteTransition: deleteTransition,
    deleteHint: deleteHint,
    saveProgressText: saveProgressText,
    deleteProgressHint: deleteProgressHint,
    sameDeleteState: sameDeleteState,
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
    pillOccupies: pillOccupies,
    syncProblem: syncProblem,
    needsReauth: needsReauth,
    CALENDAR_GLYPH: CALENDAR_GLYPH,
    tickerDays: tickerDays,
    clampSelectedDay: clampSelectedDay,
    stripStartFor: stripStartFor,
    relativeDayHint: relativeDayHint,
    eventsForDate: eventsForDate,
    secondLine: secondLine,
    footerText: footerText,
    visibilityQueue: visibilityQueue,
    visibilityFailureAfterLoad: visibilityFailureAfterLoad,
    calendarRows: calendarRows,
    destinationText: destinationText,
    escapeHtml: escapeHtml,
    highlightedHtml: highlightedHtml,
    previewLine: previewLine,
    writableCalendars: writableCalendars,
    nextCalendarId: nextCalendarId,
    cycleUnavailableReason: cycleUnavailableReason,
    quickAddHints: quickAddHints
  }
}

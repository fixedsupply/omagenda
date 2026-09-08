# Omagenda — architecture and contracts

Technical companion to `PLAN.md`. This is the contract an implementing agent builds against. Paths under `/usr/share/omarchy/shell` refer to the Omarchy 4.0.x shell installed on the target machine; read them there, they are the source of truth for the plugin API.

## 1. Repository layout

```
omagenda/
  manifest.json            # Omarchy plugin manifest (see §2)
  README.md                # user docs: install, keybindings, sync setup, screenshots
  LICENSE                  # MIT
  preview.png              # 16:9 screenshot used by plugin directories
  qml/
    BarWidget.qml          # Up Next pill; hosts Panel via Loader (pattern: panels/weather/BarWidget.qml)
    Panel.qml              # agenda panel (pattern: panels/weather/Panel.qml, panels/clock/Panel.qml)
    QuickAdd.qml           # overlay (pattern: plugins/reminders/ReminderFlow.qml)
    Service.qml            # headless: starts `omagenda watch`, owns the index FileView, exposes IPC
    Model.js               # pure functions: formatting, countdown, ticker layout, token highlighting
  bin/
    omagenda               # Python 3 CLI, executable, no extension (pattern: njpatel.omapager/bin/*)
  omagenda/                # Python package imported by bin/omagenda (sys.path insert)
    __init__.py
    vdir.py                # discover calendars, read/write .ics, displayname/color files
    index.py               # expand occurrences into agenda.json
    parse.py               # natural-language parser (deterministic)
    nl_grammar.md          # the grammar, kept next to the code
    conference.py          # Join-link detection
    sync.py                # orchestrates bridges, pimsync/vdirsyncer, omacal merge, ICS subscriptions
    accounts.py            # `omagenda account add|list|remove`; writes pimsync config; keyring via secret-tool
    bridges/
      __init__.py          # Bridge interface (§11)
      google.py            # Google Calendar API v3
      microsoft.py         # Microsoft Graph (Phase 5)
      ics.py               # read-only ICS subscriptions
    alarms.py              # VALARM scheduling for `watch`
    doctor.py
  tests/
    test_parse.py          # the 150-sentence corpus, table driven
    test_index.py          # recurrence, EXDATE, RECURRENCE-ID, DST, floating, all-day
    test_vdir.py
    model.test.js          # node:test for Model.js (pattern: mohamedmansour.finance/tests)
    qml-smoke.test.js      # qmlformat parses every QML file
  skill/
    SKILL.md               # Claude Code skill describing the CLI
  docs/
    omarchy-menu.jsonc     # menu snippet users paste into ~/.config/omarchy/extensions/
    bindings.lua           # keybinding snippet
    sync-setup.md          # pimsync / vdirsyncer recipes for Fastmail, iCloud, Nextcloud, Google
```

No build step. Installation is `omarchy plugin add <git-url>` plus `omarchy pkg add python-icalendar python-dateutil python-recurring-ical-events pimsync libsecret inotify-tools` (vdirsyncer is honored if already installed). `inotify-tools` is optional -- `omagenda watch` falls back to a 15s poll without it, at the cost of latency and a little battery. `omagenda doctor` verifies all of it.

## 2. Manifest

```json
{
  "schemaVersion": 1,
  "id": "fixedsupply.omagenda",
  "name": "Omagenda",
  "version": "0.1.0",
  "author": "Calvin Symes",
  "license": "MIT",
  "description": "Type a sentence, get an event. What's next, always in the bar.",
  "kinds": ["bar-widget", "overlay", "service"],
  "keepLoaded": true,
  "entryPoints": {
    "barWidget": "qml/BarWidget.qml",
    "overlay": "qml/QuickAdd.qml",
    "service": "qml/Service.qml"
  },
  "barWidget": {
    "displayName": "Omagenda",
    "description": "Next event with countdown; click for the agenda",
    "category": "Time",
    "allowMultiple": false,
    "defaultSection": "center",
    "defaults": {
      "leadMinutes": 30,
      "alwaysShow": false,
      "showCountdown": true,
      "days": 7,
      "activeSet": "",
      "defaultCalendar": "",
      "timeFormat": "system",
      "sets": {}
    },
    "schema": [
      { "key": "leadMinutes", "type": "integer", "label": "Show the pill this many minutes before an event", "min": 0, "max": 240, "step": 5, "defaultValue": 30 },
      { "key": "alwaysShow", "type": "boolean", "label": "Always show the pill", "defaultValue": false },
      { "key": "showCountdown", "type": "boolean", "label": "Countdown in the pill", "defaultValue": true },
      { "key": "days", "type": "integer", "label": "Days in the ticker", "min": 3, "max": 14, "step": 1, "defaultValue": 7 },
      { "key": "defaultCalendar", "type": "string", "label": "Calendar Quick Add writes to" },
      { "key": "timeFormat", "type": "enum", "label": "Clock", "options": ["system", "24h", "12h"], "defaultValue": "system" }
    ]
  }
}
```

Validate with `omarchy plugin validate .` before every commit. The full schema is in `/usr/share/omarchy/shell/services/PluginRegistry.qml`; check whether `sets` (an object) is accepted as a default, otherwise store sets in the Python config file (§5) and drop it from the manifest.

## 3. Data flow

```
vdir on disk  ──(inotify via `omagenda watch`)──▶  agenda.json  ──(FileView watchChanges)──▶  Service.qml ──▶ BarWidget / Panel
                                                          ▲
QuickAdd.qml ──Process──▶ omagenda parse --json (live)      │
QuickAdd.qml ──Process──▶ omagenda add "<sentence>" ────────┘ (writes .ics, reindexes)
Panel `s`     ──Process──▶ omagenda sync
Service.qml   ──Process──▶ omagenda watch (long-running; fires alarms; exits with the shell)
```

Rules:

- QML never parses `.ics`. It reads `~/.local/state/omagenda/agenda.json` through a `FileView { watchChanges: true }` exactly as the weather panel reads its location file.
- Every Python invocation from QML uses `Quickshell.Io.Process` with an argv array, never a shell string, and reads stdout as JSON.
- `omagenda watch` is started by `Service.qml` on load and restarted with backoff if it exits. Only one instance runs; it takes a lock file.
- The countdown ticks in QML from the timestamps in the index (a 1 s `Timer` while the panel is open, 30 s for the pill); the index is not rewritten every minute.

## 4. `agenda.json`

Written atomically (temp file + rename). Times are RFC 3339 with offset; all-day events carry `date` fields only.

```json
{
  "generatedAt": "2026-09-07T14:10:00-06:00",
  "range": { "from": "2026-09-07", "to": "2026-09-21" },
  "lastSync": "2026-09-07T14:05:12-06:00",
  "activeSet": "work",
  "calendars": [
    { "id": "personal", "name": "Personal", "path": "/home/crs/.local/share/calendars/personal", "color": "blue", "readOnly": false, "source": "vdir" }
  ],
  "events": [
    {
      "id": "personal/8f1c…@omagenda",
      "calendar": "personal",
      "title": "Lunch with Sarah",
      "start": "2026-09-10T13:00:00-06:00",
      "end": "2026-09-10T14:00:00-06:00",
      "allDay": false,
      "sourceTz": "America/Edmonton",
      "location": "Cafe Linnea",
      "description": "",
      "url": "",
      "conference": { "provider": "meet", "url": "https://meet.google.com/abc-defg-hij" },
      "attendees": 2,
      "recurring": true,
      "alarms": ["-PT10M"],
      "file": "/home/crs/.local/share/calendars/personal/8f1c….ics"
    }
  ]
}
```

`color` is a theme color name (`red`, `yellow`, `green`, `cyan`, `blue`, `magenta`, `orange`), never hex. The vdir `color` file, if present, is mapped to the nearest theme name by hue at index time; otherwise colors are assigned round-robin in a stable order by calendar id. QML resolves the name through the `Color` singleton so a theme change repaints everything.

## 5. Configuration

Two homes, by ownership:

- **Widget settings** live inline on the bar entry in `~/.config/omarchy/shell.json` (the shell's rule: settings are inline on the entry). The manifest `defaults` and `schema` above describe them; the panel's Settings form is generated by the shell.
- **Calendar-side config** the CLI needs without the shell running lives in `~/.config/omagenda/config.toml` (read with `tomllib`). Accounts are written by `omagenda account add`; the user rarely edits this by hand.

```toml
vdir = "~/.local/share/calendars"
default_calendar = "google-calvin/primary"   # set by `omagenda calendars --set-default`

[[accounts]]
id = "google-calvin"
type = "google"            # google | microsoft | icloud | caldav | ics
email = "calvin@example.com"
calendars = ["primary", "family@group.calendar.google.com"]   # empty = all writable calendars
sync_minutes = 5

[[accounts]]
id = "icloud-family"
type = "icloud"
username = "calvin@icloud.com"   # app-specific password lives in the keyring under omagenda/icloud-family
sync = "pimsync"                 # Omagenda writes ~/.config/pimsync/omagenda-icloud-family.scfg

[[accounts]]
id = "holidays"
type = "ics"
url = "https://…/canada-holidays.ics"
color = "yellow"

[sets]
work = ["google-calvin/primary"]
home = ["google-calvin/family@group.calendar.google.com", "icloud-family/family"]

[alarms]
default_lead = "PT10M"      # used when an event has no VALARM
```

`omagenda calendars` prints the merged view so QML has one place to ask.

## 6. Natural-language parser

Deterministic, single pass over tokens, no network. Output is a parsed event plus a `spans` list so the overlay can color the input.

```
omagenda parse "Lunch with Sarah tomorrow at 1pm for 90 min at Cafe Linnea /personal alert 15m" --json
{
  "ok": true,
  "title": "Lunch with Sarah",
  "start": "2026-09-08T13:00:00-06:00",
  "end":   "2026-09-08T14:30:00-06:00",
  "allDay": false,
  "calendar": "personal",
  "location": "Cafe Linnea",
  "rrule": null,
  "alarms": ["-PT15M"],
  "spans": [
    { "start": 17, "end": 25, "kind": "date" },
    { "start": 26, "end": 32, "kind": "time" },
    { "start": 33, "end": 43, "kind": "duration" },
    { "start": 44, "end": 58, "kind": "location" },
    { "start": 59, "end": 68, "kind": "calendar" },
    { "start": 69, "end": 78, "kind": "alarm" }
  ],
  "warnings": []
}
```

Grammar (document fully in `omagenda/nl_grammar.md`; the corpus in `tests/test_parse.py` is the spec):

- **Dates**: `today`, `tomorrow`, `tmrw`, weekday names and abbreviations, `next <weekday>` (the one after the coming one, Fantastical's rule), `this <weekday>`, `on the 14th`, `Sep 14`, `14 Sep`, `14/9` (locale order from `LC_TIME`, documented), `2026-09-14`, `in 3 days`, `in 2 weeks`, `end of month`.
- **Times**: `1pm`, `1 pm`, `13:00`, `1.30pm`, `noon`, `midnight`, `morning` (09:00), `afternoon` (14:00), `evening` (19:00), `tonight` (20:00), ranges `1-2pm`, `1pm to 2pm`, `from 9 to 10:30`, `at 3` (a time if followed by nothing that looks like a place; a bare `at 3` is a time).
- **Duration**: `for 45 min`, `for 2h`, `for 1.5 hours`; default 60 min, all-day when no time is given.
- **All-day**: no time, or the words `all day`.
- **Recurrence**: `every day`, `daily`, `every weekday`, `every monday`, `every mon and wed`, `weekly`, `every 2 weeks`, `monthly on the 1st`, `every month`, `yearly`, `until <date>`, `for 6 weeks` after a recurrence means COUNT.
- **Location**: `at <words>` when the words are not a time, `in <words>` when not a duration/date, `@ <words>`. Everything after the location keyword up to the next recognized token.
- **Calendar**: `/name` prefix-matched against calendar ids and display names, case-insensitive.
- **Alert**: `alert 15m`, `alert 1h`, `alert 1 day before`, `remind me 10 min before`.
- **Time zone**: `3pm EST`, `15:00 CET`, `at 9am Europe/Berlin`, abbreviations from a small table, IANA names verbatim.
- **Title**: whatever remains, whitespace-collapsed, first letter capitalized. `with <name>` stays in the title (Fantastical does not turn it into an invite without an email address).
- **Ambiguity**: return `warnings` rather than guessing silently. The overlay renders warnings in the dim color under the preview.

Spans never overlap; the earliest longest match wins.

## 7. Writing `.ics`

- One `VCALENDAR` with one `VEVENT` per file, `UID` = `uuid4()@omagenda`, filename `<uid>.ics`, `PRODID:-//Omagenda//EN`, `DTSTAMP`, `CREATED`, `SEQUENCE:0`.
- Timed events: `DTSTART;TZID=<local IANA>` and `DTEND` likewise. All-day: `DTSTART;VALUE=DATE` and exclusive `DTEND`.
- Alarms as `VALARM` with `ACTION:DISPLAY`.
- Write to a temp file in the same directory, `fsync`, rename. Then reindex synchronously and print the new event as JSON so the overlay can confirm.
- Never touch an existing file except through the explicit edit path (v1: open in `$EDITOR`).

## 8. QML surfaces: what to imitate, exactly

Read these files first and match them line for line in structure, naming, and comments. They are short enough to read whole.

| Surface | Imitate | Why |
|---|---|---|
| `BarWidget.qml` | `plugins/panels/weather/BarWidget.qml` | Loader-hosted panel, `injectPanel`, open/close/opened contract, `BarIconButton`, visibility bound to a label |
| Pill visibility rules | `~/.config/omarchy/plugins/njpatel.omapager/Widget.qml` | appears only when there is something to say; the `alwaysShow` setting |
| `Panel.qml` frame and keyboard | `plugins/panels/weather/Panel.qml` | hero-over-detail, `openFromHotkey`, `switchPanel`, `Keys.onPressed` handling, `setCenterHoverRevealSuppressed` |
| Month/ticker grid math | `plugins/panels/clock/Model.js` and `Panel.qml` | week start, day labels, today marking, scroll and arrow stepping |
| Hero | `Ui/PanelHero.qml` | title/meta/detail with a trailing control (the Join button) |
| Section headers, separators, buttons | `Ui/PanelSectionHeader.qml`, `Ui/PanelSeparator.qml`, `Ui/PanelActionButton.qml`, `Ui/Button.qml` | never draw your own |
| Overlay frame and text entry | `plugins/reminders/ReminderFlow.qml` + `ReminderFlowModel.js` | centered card, scrim, key catcher, submit/dismiss semantics, `Style.font.menuFamily` |
| Filterable list (templates) | `plugins/emojis/` | list + filter in the menu style |
| Colors and spacing | `Commons/Color.qml`, `Commons/Style.qml` | use tokens only: `Style.space()`, `Style.spacing.*`, `Style.font.*`, `Color.popups.*`, `Color.menu.*` |
| Helper processes | `~/.config/omarchy/plugins/njpatel.omapager/Service.qml` | resolving `bin/` next to the QML with `Qt.resolvedUrl`, long-running `Process` |
| Tests | `~/.config/omarchy/plugins/mohamedmansour.finance/tests/` | `node:test` for `Model.js`, `qmlformat` smoke test |

Live-highlighting in Quick Add: use a `TextInput` with a transparent text color layered over a `Text` that renders the same string with `textFormat: Text.RichText` and `<font color>` spans from the parser, or `TextEdit` with `TextDocument` formats. Both work; pick the one that keeps the caret and selection correct, and prove it with a manual test before building on it.

IPC: `Service.qml` registers `IpcHandler { target: "omagenda" }` with `toggle`, `quickAdd`, `sync`, `next` so `omarchy-shell omagenda quickAdd` and `omarchy-shell shell toggle fixedsupply.omagenda` both work from keybindings.

## 9. Testing and debugging

```
python -m unittest discover -s tests -v          # Python
node --test 'tests/**/*.test.js'                  # Model.js + qmlformat smoke (a bare directory throws MODULE_NOT_FOUND on Node 26)
omarchy plugin validate .                        # manifest
omarchy-shell shell rescanPlugins                # hot reload after edits under ~/.config/omarchy/plugins/
journalctl --user -f _COMM=quickshell            # QML errors and console.log
omarchy-shell shell toggle fixedsupply.omagenda  # open the panel by IPC
```

Develop by symlinking the repo to `~/.config/omarchy/plugins/fixedsupply.omagenda` and enabling it with `omarchy plugin enable fixedsupply.omagenda`. Saving any file under that path hot-reloads plugin code.

Sample data for development lives in `tests/fixtures/vdir/` (three calendars, recurring events with exceptions, an all-day span, a DST-crossing event, a floating-time event, a Meet link, a Zoom link). `OMAGENDA_VDIR=tests/fixtures/vdir omagenda index` points the CLI at it.

## 10. Performance and safety budgets

- `omagenda index` for a two-week window over 2,000 events: under 300 ms
  once warm. A real Google subscription is a single .ics of years of
  history (6,915 events / 5 MB on the PM's account), and parsing that file
  costs ~4.7 s while expanding a fortnight out of it costs ~0.5 s -- so
  index.py keeps a cache keyed by each file's path, mtime, size, and the
  requested window. Cold, or on the first index after the date rolls over,
  that file is reparsed; warm, the whole index is ~2 ms. `watch` reindexes
  on every vdir change, so warm is the case that matters.
- `omagenda parse`: under 50 ms including interpreter start; the overlay debounces at 60 ms and cancels the previous process if still running.
- Panel open to first paint: under 100 ms; the index is already in memory in `Service.qml`.
- The plugin never runs `sudo`, never writes outside `~/.local/share/calendars`, `~/.local/state/omagenda`, and `~/.config/omagenda`, and never phones home. Subscriptions fetch only the URLs the user wrote in their config.

## 11. Cloud bridges

A bridge mirrors one remote account into vdir folders and pushes local changes back. Google is the reference implementation; Microsoft follows the same interface in Phase 5.

```python
class Bridge(Protocol):
    type: str                                   # "google" | "microsoft"
    def authorize(self, account: Account) -> None       # interactive; stores tokens via keyring
    def list_calendars(self, account) -> list[RemoteCalendar]
    def pull(self, account, cal, state) -> PullResult   # incremental using state.sync_token / delta_link
    def push_create(self, account, cal, vevent) -> RemoteRef
    def push_update(self, account, cal, vevent, ref) -> RemoteRef
    def push_delete(self, account, cal, ref) -> None
```

Sync state per calendar lives in `~/.local/state/omagenda/sync/<account>/<calendar>.json`: remote sync token or delta link, and a map of `UID -> {remoteId, etag, localHash}`. The algorithm, in order, every cycle:

1. **Pull** incrementally; for each changed remote item write or rewrite `<uid>.ics` and update the map; for each deleted remote item remove the file. On a `410 Gone` (Google) or an invalid delta link (Microsoft) do a full pull.
2. **Detect local changes** by comparing each file's hash with `localHash`: new files (no map entry) are creates, changed hashes are updates, missing files with a map entry are deletes.
3. **Push** with conditional requests (`If-Match: etag`). A `412` means the remote changed since the last pull: keep the remote version, save the local one as `<uid>.conflict.ics`, and notify.
4. **Record** the new tokens and hashes atomically.

Mapping rules, Google: `summary`↔`SUMMARY`, `start/end` with `dateTime`+`timeZone` or `date`↔`DTSTART`/`DTEND`, `recurrence[]`↔`RRULE`/`EXDATE` lines verbatim, `location`, `description`, `hangoutLink` and `conferenceData.entryPoints[].uri`→`CONFERENCE`/`X-GOOGLE-CONFERENCE`, `reminders.overrides`↔`VALARM`, `attendees` read-only, `status: cancelled`→delete, instances of recurring events with `recurringEventId`→`RECURRENCE-ID`. Time zones: Google gives IANA names; keep them as `TZID`.

Mapping rules, Microsoft: `subject`, `start/end` with `dateTime`+`timeZone` (Windows zone names, map through a small table to IANA), `recurrence.pattern/range`→`RRULE` (weekly/daily/absoluteMonthly/relativeMonthly/absoluteYearly/relativeYearly; anything else is imported read-only and flagged), `onlineMeeting.joinUrl`→`CONFERENCE`, `isAllDay`, `isCancelled`, `seriesMasterId`, delta via `/me/calendars/{id}/calendarView/delta`.

OAuth, both: loopback redirect to `http://127.0.0.1:<random port>/` served by `http.server` for one request, PKCE, browser opened with `omarchy launch browser <url>` or `xdg-open`. Refresh tokens stored with `secret-tool store --label "Omagenda <account>" omagenda account <id>`. Google scope `https://www.googleapis.com/auth/calendar`; Microsoft scopes `Calendars.ReadWrite offline_access`.

Network calls use `urllib.request` with a 15 s timeout and exponential backoff on 429/5xx. The bridge never runs on the QML side; `omagenda watch` schedules it by `sync_minutes` and on demand from the panel's `s`.

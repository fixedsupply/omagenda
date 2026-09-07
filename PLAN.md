# Omagenda — product plan

*Working title. Fantastical's two best ideas, the mini window and the magic sentence, rebuilt as an Omarchy shell plugin.*

Status: planning, 2026-09-07. Product manager: Calvin Symes. Design and taste: Claude (Fable 5.1). Implementation: any capable coding agent following `AGENTS.md`.

---

## 1. The thesis in three sentences

Fantastical earned its reputation before it was a full calendar app: version 1 was a menu-bar mini window and a text field that turned "Lunch with Sarah tomorrow at 1pm" into an event. Omarchy 4 now has exactly the place where that belongs, a single long-running shell with bar widgets, popup panels, and hotkey-summoned overlays, and nobody has built it. Omagenda is the calendar *layer* of the Omarchy desktop, not another calendar *window*: an Up Next pill in the bar, a keyboard-driven DayTicker panel, and a global-hotkey Quick Add that parses natural language and writes real `.ics` files.

## 2. Why not another calendar app

The Omarchy calendar space already has good full-window apps. Building a third would waste the budget and split the community.

| Project | What it is | Writes events | Lives in the shell | Natural language | Backends |
|---|---|---|---|---|---|
| renCal (t4t5) | Tauri window app, vim keys, local `.ics` | yes | no | yes, inside its window | Google, iCloud, Outlook, CalDAV |
| OmaCal (Extreme Labs) | Tauri window app + CLI + `omacal.upcoming` widget | yes | widget only | no | Google, iCloud, CalDAV |
| omarchy-calendar (tmn73) | Clock replacement, Up Next countdown, month grid, Join button | no, read-only | yes | no | Google via own OAuth, or any JSON you generate |
| omarchy-gcal (felipecpaiva) | Clock replacement with agenda | no, read-only | yes | no | Google via GNOME Online Accounts |
| calendarchy | Rust TUI, macOS-centric | no | no | no | Google, iCloud |

The gap is precise: **nothing in the shell can create an event, and nothing anywhere on Omarchy offers a global, instant, natural-language capture.** Everything in the bar today is a read-only Google viewer. Omagenda fills the gap and deliberately plays well with the existing apps: renCal and OmaCal users keep their app for the big grid; Omagenda gives them the bar, the hotkey, and the sentence.

## 3. Positioning

**Omagenda is to Omarchy what Fantastical 1 was to the Mac.** It is what you touch fifty times a day: what's next, what's today, add this thing. The month grid, drag-and-drop, invitations, and account setup wizards stay in the apps that already do them well.

One-line pitch for the README: *"Type a sentence, get an event. What's next, always in the bar. Themed like the rest of your desktop, stored as plain `.ics` files you own."*

## 4. Design principles (the taste bar)

These are the tiebreakers for any decision the implementer faces.

1. **The file is the truth.** Events are plain `.ics` files in a vdir on disk. Sync is somebody else's excellent job (pimsync, vdirsyncer). No database, no account, no server of ours. If Omagenda disappears, your calendar is still there and `khal` still reads it.
2. **Keyboard first, mouse welcome.** Every action has a key, and the keys are the ones an Omarchy user already knows: `j`/`k`, `h`/`l`, `Enter`, `Escape`, `/`. Mouse works everywhere but never gates anything.
3. **Borrow the theme, never bring colors.** All color comes from the shell's `Color` and `Style` singletons. Calendars are assigned one of the theme's named colors (blue, green, yellow, magenta, cyan, red), not arbitrary hex, so every theme looks designed on purpose.
4. **Imitate the first-party panels exactly.** Same hero-over-detail composition as the weather and clock panels, same spacing scale, same small-caps section headers, same corner radius, same border spec. A user should not be able to tell Omagenda was not shipped with Omarchy.
5. **Instant.** The bar pill and the panel read a pre-computed JSON index; they never parse `.ics` on the UI thread. Quick Add parses locally and deterministically, no network, no LLM, with a live preview under 16 ms.
6. **Quiet.** The bar does not shift or flash. The pill shows the next event only when it is close, and hides otherwise unless the user says "always show". Notifications are Omarchy notifications with a Join action, nothing more.
7. **Agent-friendly.** Omarchy 4 calls itself an agentic desktop. Every capability is available as a CLI with `--json`, plus a `SKILL.md` so Claude Code and friends can read and write the calendar the same way the panel does.
8. **Readable in one sitting.** The whole plugin should be small enough that a cautious user can review it before enabling it (plugins run unsandboxed inside the shell). Python for logic, QML for surfaces, no build step, no npm.

## 5. Fantastical concepts → Omagenda

| Fantastical | Verdict | Omagenda translation |
|---|---|---|
| Menu bar mini window | **Keep, this is the product** | Up Next pill in the bar + DayTicker panel anchored to it, also summoned by hotkey (`omarchy-shell shell toggle <id>`) |
| Natural language event entry with live highlighting | **Keep, this is the product** | Quick Add overlay (like the Reminders and Emoji overlays), global hotkey, tokens light up in the accent color as you type, preview card shows the parsed event |
| DayTicker (horizontal day strip + list below) | Keep | Seven-day strip of date pills with event dots, agenda for the selected day beneath it |
| Up Next with countdown | Keep | Pill text: `Standup · 12m`; header of the panel: hero with title, time, and Join |
| Calendar Sets | Keep, simplified | Named sets in `shell.json`; switch with number keys in the panel or `omagenda set work`; optional per-set default calendar for Quick Add |
| Conference call detection and Join | Keep | Regex over location, description, `CONFERENCE`, and `X-GOOGLE-CONFERENCE` for Meet, Zoom, Teams, Webex, Jitsi, Whereby; Join opens the browser and appears on the notification |
| Time zone support | Keep, small | Store `TZID`, display local, show the source zone when it differs; parser accepts `3pm EST` and `at 15:00 Europe/Berlin` |
| Templates | Adapt | Saved sentences: `omagenda add --template standup` and a `/` picker in Quick Add; a template is just a sentence with blanks |
| Weather in the calendar | Drop | The weather widget already sits next to the clock; do not duplicate it |
| Openings, proposals, RSVP, invitations | Drop for v1 | Needs email and a server; belongs in renCal and OmaCal. Show attendees read-only |
| Tasks, Todoist | Drop for v1 | omarchy-todoist exists; revisit as a `VTODO` view later |
| Interesting calendars | Adapt | Read-only ICS subscriptions (holidays, sports) as a URL in the config, refreshed by the sync step |
| Focus filters | Later | Bind a calendar set to Hyprland workspaces or a Do Not Disturb state; cheap once sets exist |
| Attachments, email forwarding, widgets, Vision Pro | Drop | Not the desktop |

## 6. The surfaces

### 6.1 Up Next pill (bar widget)

- Text: the next event's title and a countdown, compact, in the bar font. `Standup · 12m`, then `Standup · now` from start to end.
- Default visibility: appears `leadMinutes` before an event (default 30) and while one is running. `alwaysShow: true` keeps a glyph plus the next event's time all day.
- Left click: open the panel. Right click: Quick Add. Middle click: sync now. Scroll: nothing, on purpose.
- Sits to the left or right of the clock in whichever section the user prefers; never replaces the clock, so it composes with the stock clock, tmn73's, or a clone.

### 6.2 DayTicker panel

Composition, top to bottom, following `panels/weather/Panel.qml` and `panels/clock/Panel.qml`:

1. **Hero**: the next (or current) event. Title, `14:00–14:30 · in 12m`, calendar color hairline, and a trailing Join button when a conference link exists. When nothing is left today: `Nothing else today`, with tomorrow's first event as the meta line.
2. **Ticker strip**: seven date pills starting today, weekday initial over day number, up to three event dots in calendar colors under each. Today is marked the way the clock panel marks it. `h`/`l` move the selection, `H`/`L` move a week, `t` returns to today.
3. **Agenda list** for the selected day: time column, title, location or attendee count as a dim second line. All-day events first. `j`/`k` move, `Enter` expands a row inline (description, location link, attendees, calendar), `o` opens the location or conference URL, `e` opens the `.ics` in `$EDITOR` in a floating terminal (Omarchy's honest "edit" for v1).
4. **Footer** (small-caps): active calendar set name, last sync time, and hints: `n new · s sync · 1–9 sets · ? help`.

Keys: `n` Quick Add prefilled with the selected date, `s` sync, `1`…`9` switch set, `Escape` close, left/right arrows hand off to neighboring panels like other first-party panels.

### 6.3 Quick Add overlay

A centered card in the menu style (see `plugins/reminders/ReminderFlow.qml` for the frame and `plugins/emojis` for the filterable list feel).

- One text field. As you type, recognized fragments get the accent color: dates, times, durations, recurrence, calendar, location, alert. Unrecognized text stays the foreground color and becomes the title.
- Beneath it, a preview row exactly as the agenda will render it: `Thu 10 Sep · 13:00–14:00 · Lunch with Sarah · Personal`. If the sentence is ambiguous the preview says so in the dim color rather than guessing silently.
- `Enter` writes the event and closes with a brief confirmation notification. `Shift+Enter` writes and keeps the overlay open for the next one. `Tab` cycles the target calendar. `Escape` cancels.
- Prefix `/` opens a template picker; the chosen sentence fills the field with the cursor at the first blank.
- Empty field plus `Enter` closes, matching the reminders flow.

### 6.4 CLI: `omagenda`

Python 3, standard library plus the Arch packages `python-icalendar`, `python-dateutil`, and `python-recurring-ical-events`. Same binary the QML calls. Every command has `--json`.

```
omagenda agenda [--days N] [--from DATE] [--set NAME]   # what the panel shows
omagenda next                                          # what the pill shows
omagenda parse "<sentence>"                            # parsed event, no write
omagenda add "<sentence>" [--calendar NAME] [--dry-run]
omagenda calendars                                     # vdir discovery, colors, sets
omagenda sync                                          # runs pimsync or vdirsyncer if configured, then reindex
omagenda index                                         # rebuild ~/.local/state/omagenda/agenda.json
omagenda watch                                         # long-running: reindex on vdir changes, fire alarms
omagenda doctor                                        # dependencies, vdir, sync tool, keybinding, plugin enabled
```

### 6.5 Notifications

`omagenda watch` fires `omarchy-notification-send` at each `VALARM` (or a per-calendar default lead) with the title, time, and `--exec` to Join when a conference URL exists. One notification per occurrence, deduplicated across restarts through a small state file.

### 6.6 Menu and keybindings

- Ship `docs/omarchy-menu.jsonc` snippet: `trigger.calendar` with Quick Add, Open agenda, Sync now.
- README documents two bindings for `~/.config/hypr/bindings.lua`: `SUPER + CTRL + N` Quick Add, `SUPER + CTRL + ALT + N` panel. (`SUPER + CTRL + ALT + D` is already the stock clock's calendar; do not take it.)

### 6.7 Agent skill

`skill/SKILL.md` describing the CLI so a Claude Code session can answer "what's on Thursday" and "add lunch with Sarah tomorrow at 1" through `omagenda --json`. Installable by copying into `~/.claude/skills/omagenda`.

## 7. Data and sync

- **Store**: vdir layout, `~/.local/share/calendars/<calendar>/<uid>.ics`, with the conventional `displayname` and `color` files. This is what vdirsyncer, pimsync, and khal use. Omagenda writes new events there and reads everything there.
- **Sync**: delegated. `omagenda sync` runs `pimsync sync` or `vdirsyncer sync` when either is configured, otherwise it only reindexes. `omagenda doctor` explains how to set one up and links to a short guide for Fastmail, iCloud, Nextcloud, and generic CalDAV (all work today with app passwords).
- **ICS subscriptions**: read-only URLs listed in the config, fetched during sync into their own vdir folder marked read-only.
- **OmaCal bridge** (optional adapter): when `omacal` is on `PATH`, `agenda` can merge `omacal events list --json`, and `add` can route through `omacal events create`, so OmaCal users get Quick Add without setting up a second sync. Read-only merge is cheap; write routing is a stretch goal.
- **Google**: the honest position. pimsync's native OAuth is still on its roadmap, and vdirsyncer needs the user to create their own OAuth client. v1 therefore supports Google through either the OmaCal bridge or vdirsyncer with the user's own client, documented step by step. A first-party Google path is a v2 decision, see §10.

## 8. Scope

**v1 must**: vdir reader with recurrence expansion; agenda index; Up Next pill; DayTicker panel with keyboard navigation; Quick Add with live highlighting and deterministic parser; write `.ics`; `omagenda` CLI with `--json`; sync delegation; alarms via notifications; Join detection; theme-native colors; `doctor`; README with screenshots; `omarchy plugin validate` clean.

**v1 should**: calendar sets; templates; OmaCal read-only merge; ICS subscriptions; `SKILL.md`.

**Later**: editing in place (title, time) from the panel; Focus filters tied to workspaces; `VTODO` view; Google OAuth in-house; a `bar` kind that replaces the clock for users who want one pill.

## 9. Delivery plan and budget

Prices are Anthropic API rates at 2026-09-07 (Claude Code usage credits bill at these rates): Fable 5.1 $10/$50 per million input/output tokens, Opus 5 $5/$25, Sonnet 5 $2/$10. The budget is CAD 116, roughly USD 85, minus what this planning session cost. Treat the figures below as an envelope, not a quote; check the console after each phase.

| Phase | Deliverable | Model | Envelope (USD) |
|---|---|---|---|
| 0 | Repo scaffold, manifest, parser grammar doc, 150-sentence test corpus | Sonnet 5 (or Grok) | 3–6 |
| 1 | Python core: vdir reader, recurrence, index, CLI, parser with tests green | Sonnet 5; escalate the parser to Opus 5 only if it stalls | 10–20 |
| 2 | QML: Up Next pill + DayTicker panel, keyboard nav, theme-native | Opus 5 (QML/Quickshell is niche, it must read and imitate first-party code) | 15–30 |
| 3 | QML: Quick Add overlay with live highlighting, templates | Opus 5 | 10–20 |
| 4 | `watch` alarms, Join, sets, doctor, README, screenshots, publish | Sonnet 5 | 5–10 |

Cut order if money runs short: templates, OmaCal bridge, ICS subscriptions, calendar sets, then alarms. The pill, the panel, and Quick Add are the product.

Cost hygiene is spelled out in `AGENTS.md`: one phase per session, a fixed read list instead of exploring, logic in Python and `Model.js` where tests are cheap, QML kept thin.

## 10. Decisions for the product manager

1. **Name.** "Omagenda" follows the community's Oma- convention (Omapager, Omafinance, OmaCal) and says what it is. No collisions found. Alternatives if you dislike it: "Upnext", "Ticker". Plugin id would be `fixedsupply.omagenda` unless you want a different namespace.
2. **Repo.** Public from day one under github.com/fixedsupply, MIT license (matching every plugin in the ecosystem)? Or private until v1 works?
3. **Google.** Accept the v1 position (OmaCal bridge or bring-your-own OAuth client) or make first-party Google a v1 requirement? The latter roughly doubles Phase 1 and adds a Google Cloud project to every user's setup.
4. **Your own calendar.** Which backend do you actually use day to day (Google, iCloud, Fastmail, Nextcloud)? v1 will be tested against it first.
5. **Clock relationship.** Keep Omagenda as a separate pill beside the stock clock (my recommendation, composes with everything), or also ship a clock-replacement variant like tmn73's?
6. **Model routing.** Agree to the phase-to-model table above, or run everything on one model?

## 11. Risks

- **Quickshell API drift.** Omarchy 4.0.x moves fast; the implementer must read the installed `/usr/share/omarchy/shell` on the target machine, not remembered APIs. Pin the tested Omarchy version in the README.
- **Recurrence edge cases.** Exceptions (`EXDATE`, `RECURRENCE-ID`), floating times, and DST transitions are where calendar software dies. `python-recurring-ical-events` handles most of it; the test corpus must include the ugly cases.
- **Parser ambiguity.** "at 3" (time or place?), "next Friday" (this week or next?), "in 2 weeks". Resolve with Fantastical's conventions, document them, and show the interpretation in the preview so the user always sees what will be written.
- **Budget.** QML sessions are token-hungry because the agent reads large first-party files. The read list in `AGENTS.md` exists to stop exploration.

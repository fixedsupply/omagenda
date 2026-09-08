# Omagenda — product plan

*Working title. Fantastical's two best ideas, the mini window and the magic sentence, rebuilt as an Omarchy shell plugin.*

Status: planning, 2026-09-07. Product manager: Calvin Symes. Design and taste: Claude (Fable 5.1). Implementation: any capable coding agent following `AGENTS.md`.

---

## 1. The thesis in three sentences

Fantastical earned its reputation before it was a full calendar app: version 1 was a menu-bar mini window and a text field that turned "Lunch with Sarah tomorrow at 1pm" into an event. Omarchy 4 now has exactly the place where that belongs, a single long-running shell with bar widgets, popup panels, and hotkey-summoned overlays, and nobody has built it. Omagenda is the calendar *layer* of the Omarchy desktop, not another calendar *window*: an Up Next pill in the bar, a keyboard-driven agenda panel, and a global-hotkey Quick Add that parses natural language and writes real `.ics` files.

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

## 3a. Naming and Fantastical

"Fantastical" and "DayTicker" are Flexibits' names. Omagenda uses the former once, descriptively, in the README ("inspired by Fantastical's original menu-bar app") with a note that Omagenda is not affiliated with or endorsed by Flexibits, and never in the product name, plugin id, tagline, or keywords. Our surfaces are the *pill*, the *agenda panel* with its *ticker strip*, and *Quick Add*. No Flexibits icons, screenshots, marketing copy, or code are reused anywhere.

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
| Menu bar mini window | **Keep, this is the product** | Up Next pill in the bar + agenda panel anchored to it, also summoned by hotkey (`omarchy-shell shell toggle <id>`) |
| Natural language event entry with live highlighting | **Keep, this is the product** | Quick Add overlay (like the Reminders and Emoji overlays), global hotkey, tokens light up in the accent color as you type, preview card shows the parsed event |
| DayTicker (horizontal day strip + list below) | Keep, renamed | Seven-day "ticker" strip of date pills with event dots, agenda for the selected day beneath it |
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

### 6.2 agenda panel

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

## 7. Data, accounts, and sync

Decided 2026-09-07: Google, Apple, and Microsoft compatibility are all in scope, in that priority order. The design keeps one principle fixed and lets the account types vary around it.

**The vdir is still the truth.** Every account, whatever its origin, is mirrored into `~/.local/share/calendars/<account>/<calendar>/` as one `.ics` file per event, with the conventional `displayname` and `color` files. The pill, the panel, Quick Add, the CLI, and khal all read and write that directory and nothing else. Sync is the job of *bridges*, one per account type, run by `omagenda sync` and by `omagenda watch` on a timer.

| Account type | How it syncs | Who does the work | Setup |
|---|---|---|---|
| **Google Calendar** | Google Calendar API v3, OAuth 2.0 loopback flow, incremental `syncToken`, ETag-conditional writes | Omagenda's own bridge (`omagenda/bridges/google.py`) | `omagenda account add google` opens the browser once; tokens go to the keyring |
| **Apple iCloud** (incl. shared family calendars) | CalDAV at `caldav.icloud.com` with an app-specific password | pimsync (or vdirsyncer if already installed), configured for the user by Omagenda | `omagenda account add icloud` asks for Apple ID and app password, writes the pimsync config, stores the password in the keyring |
| **Microsoft 365 / Outlook.com** | Microsoft Graph, OAuth 2.0 device-code or loopback flow, delta queries | Omagenda bridge (`omagenda/bridges/microsoft.py`), same interface as Google | `omagenda account add microsoft` |
| **Fastmail, Nextcloud, Radicale, any CalDAV** | CalDAV | pimsync, configured by Omagenda | `omagenda account add caldav <url>` |
| **ICS subscriptions** (holidays, sports, school) | HTTP fetch into a read-only calendar | Omagenda | `omagenda account add ics <url>` |
| **OmaCal** (optional) | Merge `omacal events list --json` read-only | Omagenda | automatic when `omacal` is on `PATH` |

Why this split: Apple and every self-hosted service speak CalDAV, and pimsync already does careful two-way CalDAV sync with conflict handling, so Omagenda should configure it rather than reimplement it. Google and Microsoft do not speak CalDAV usably (Google's CalDAV endpoint still needs OAuth and is second-class; Microsoft has none), so those two get purpose-built bridges that translate between the vendor JSON and `VEVENT`. Both bridges implement the same small interface (`ARCHITECTURE.md` §11) so a third one is a contribution-sized task.

**Google accounts on Advanced Protection.** Discovered 2026-09-08 on the
PM's own account. Google's Advanced Protection Program blocks *unverified*
third-party apps from sensitive scopes outright: the consent screen never
appears, and the OAuth flow ends in `Error 400: policy_enforced`. Advanced
Protection also disables app passwords entirely, so the CalDAV fallback is
closed on those accounts too. What still works is the per-calendar secret
iCal URL, which carries its own token, needs no OAuth, and is read-only.

So an Advanced Protection user's Google calendars are read-only in
Omagenda until the app completes Google verification, and possibly after
(verified apps are permitted under Advanced Protection, but that is
Google's call, not something the plan can assume). This is not an edge
case to note and forget -- it is the PM's own primary calendar, and it
means Quick Add writes to a local or iCloud calendar rather than to
Google. It also moves Google verification from "nice, removes a warning"
to "the only route to writing to Google for these users".

**What other people will hit, which is not what the maintainer hit.**
The Google bridge is built and works; the secret-iCal fallback was needed
for one specific reason that most users won't share. Three different
situations, worth keeping straight:

| Who | What happens today | Fix |
|---|---|---|
| Ordinary Google account | OAuth works, after clicking past an "unverified app" warning that looks alarming | verification removes the warning |
| Anyone, once 100 people have connected | The 101st user is refused outright | verification lifts the cap |
| Account on Advanced Protection | Hard-blocked, no click-through | verification, and even then it is Google's call |

The middle row is the one that decides whether this can be published.
Google caps an unverified project at 100 users *in total*, so a plugin
listed on omarchyplugins.com would work for its first hundred adopters
and then start failing for everyone after, with an error none of them can
do anything about. That is not a warning to document; it is a release
blocker.

Verification for this scope is paperwork, not a paid audit: `calendar` is
a *sensitive* scope, not a *restricted* one, so it needs a homepage on a
domain the project controls, a privacy policy on that domain, a demo video
of the consent flow, and Google's review. Days to weeks, no fee. The
alternative for the privacy-minded is documented bring-your-own-client,
where a user makes their own Google Cloud project and is the only user of
it -- no cap, at the cost of a twenty-step setup most people won't do.

So the release sequence is: verification submitted before the plugin is
listed anywhere public, bring-your-own-client documented as the escape
hatch, and the secret-iCal subscription kept as the always-works,
read-only path for Advanced Protection users and anyone who would rather
not grant write access at all.

**Credentials.** OAuth tokens and app passwords go into the desktop keyring through `secret-tool` (libsecret), which Omarchy ships. If no keyring is available, `omagenda doctor` says so and the bridge falls back to a mode-0600 file under `~/.local/state/omagenda/`, clearly labeled.

**Google client id.** The repo ships an OAuth client owned by the project (Google does not treat the installed-app client secret as confidential, and the calendar scope is what makes the app useful). Until the project passes Google's app verification, Google shows an "unverified app" interstitial and caps the app at 100 users. Two consequences for the PM: create the Google Cloud project and OAuth client before Phase 1b, and plan to submit for verification once the README, a privacy page, and a short demo video exist. A bring-your-own-client path stays documented for people who prefer it.

**Microsoft app registration.** Free in Entra ID; a personal Microsoft account can register a multi-tenant public client with no secret. Work and school tenants may require an admin to consent, which the setup wizard explains rather than hides.

## 8. Scope

**v1 must**: vdir reader with recurrence expansion; agenda index; Up Next pill; agenda panel with keyboard navigation; Quick Add with live highlighting and deterministic parser; write `.ics`; `omagenda` CLI with `--json`; Google bridge with two-way sync; iCloud and generic CalDAV through a pimsync config written by `omagenda account add`; alarms via notifications; Join detection; theme-native colors; `doctor`; README with screenshots; `omarchy plugin validate` clean.

**v1 should**: Microsoft bridge; calendar sets; templates; ICS subscriptions; OmaCal read-only merge; `SKILL.md`.

**Later**: editing in place (title, time) from the panel; Focus filters tied to workspaces; `VTODO` view; a `bar` kind that replaces the clock for users who want one pill.

## 9. Delivery plan and budget

Prices are Anthropic API rates at 2026-09-07 (Claude Code usage credits bill at these rates): Fable 5.1 $10/$50 per million input/output tokens, Opus 5 $5/$25, Sonnet 5 $2/$10. The budget is CAD 116, roughly USD 85, minus planning. Treat the figures as an envelope, not a quote; check the console after each phase.

| Phase | Deliverable | Model | Envelope (USD) |
|---|---|---|---|
| 0 | Repo scaffold, manifest, parser grammar doc, 150-sentence test corpus, fixtures | Sonnet 5 (or Grok) | 3–6 |
| 1 | Python core: vdir, recurrence, index, CLI, parser green, pimsync configuration for iCloud/CalDAV | Sonnet 5; escalate the parser to Opus 5 only if it stalls | 10–20 |
| 1b | Google bridge: OAuth, incremental two-way sync, JSON↔VEVENT, keyring | Sonnet 5 for the mapping, Opus 5 for the sync state machine if it stalls | 10–18 |
| 2 | QML: Up Next pill + agenda panel, keyboard nav, theme-native | Opus 5 | 15–30 |
| 3 | QML: Quick Add overlay with live highlighting, templates | Opus 5 | 10–20 |
| 4 | `watch` alarms, Join, sets, doctor, README, screenshots, publish | Sonnet 5 | 5–10 |
| 5 | Microsoft bridge on the Phase 1b interface | Sonnet 5 | 8–15 |

Totals: USD 53–104 without Microsoft, 61–119 with it. **The honest reading is that Microsoft does not fit inside the current credits alongside everything else.** It is therefore Phase 5, built last on an interface the Google bridge has already proven, and it is the first thing to defer if the console says so. Because the PM's own calendars are Google and Apple, this order also means v1 is testable end to end on a real setup before any money goes to Microsoft.

Cut order if money runs short: Microsoft bridge, templates, OmaCal merge, ICS subscriptions, calendar sets, then alarms. The pill, the panel, Quick Add, and Google plus iCloud sync are the product.

Cost hygiene is spelled out in `AGENTS.md`: one phase per session, a fixed read list instead of exploring, logic in Python and `Model.js` where tests are cheap, QML kept thin.

## 10. Decisions log

Resolved 2026-09-07 by the product manager:

1. **Name**: Omagenda. Plugin id `fixedsupply.omagenda`.
2. **Repo and license**: public at github.com/fixedsupply/omagenda from day one, MIT (Omarchy itself and every plugin surveyed are MIT).
3. **Accounts**: Google first-party, Apple through iCloud CalDAV, Microsoft through a Graph bridge; see §7 and the budget note in §9.
4. **Reference setup for testing**: Google (personal) plus iCloud (shared family calendars). v1 is verified against both before release.
5. **Clock relationship**: separate pill beside the stock clock; no clock-replacement variant.
6. **Model routing**: the phase table in §9.

Done: the Google Cloud project and OAuth client (2026-09-07), stored in `.env.local` for Phase 1b.

Decided 2026-09-07: wait on the Microsoft Entra app registration until Phase 5 is actually reached, rather than doing it now.

**Decided 2026-09-08: ship to trusted reviewers under the 100-user cap,
register a domain and verify only if the plugin proves viable.** Google
requires the homepage and privacy policy to live on a domain the project
owns -- GitHub Pages, Vercel and similar are rejected by reviewers who
have tried -- so verification has a real if small floor of about a domain
a year. That is not worth paying before anyone has used the thing. Until
then: the README says plainly that Google sign-in is capped and shows an
unverified-app warning, the read-only iCal subscription stays the path
that always works for everyone, and nothing in the code assumes which way
this goes -- `OMAGENDA_GOOGLE_CLIENT_ID`/`_SECRET` already let a user
point at their own project, and verification later changes no code at all,
only the state of the Cloud project.

**Blocking wider release (raised 2026-09-08): submit the Google Cloud
project for verification.** An unverified project is capped at 100 users
in total, so a plugin listed on omarchyplugins.com would work for its
first hundred adopters and then refuse everyone after, with an error none
of them can act on. Verification also removes the "unverified app" warning
every user currently clicks past, and is the only route by which an
Advanced Protection account (the maintainer's own) can ever connect. It is
paperwork rather than a paid audit for this scope: a homepage on a domain
the project controls, a privacy policy on it, a demo video of the consent
flow, and Google's review. See §7.

## 11. Risks

- **Quickshell API drift.** Omarchy 4.0.x moves fast; the implementer must read the installed `/usr/share/omarchy/shell` on the target machine, not remembered APIs. Pin the tested Omarchy version in the README.
- **Recurrence edge cases.** Exceptions (`EXDATE`, `RECURRENCE-ID`), floating times, and DST transitions are where calendar software dies. `python-recurring-ical-events` handles most of it; the test corpus must include the ugly cases.
- **Two-way sync conflicts.** A Google event edited on the phone and in Quick Add between syncs. Rule: the server wins, the local copy is preserved as `<uid>.conflict.ics`, and a notification says so. Never silently drop either side.
- **Google verification and the 100-user cap.** Real, dated, and on the PM's plate (see §7). Until then the README says so plainly.
- **Parser ambiguity.** "at 3" (time or place?), "next Friday" (this week or next?), "in 2 weeks". Resolve with Fantastical's conventions, document them, and show the interpretation in the preview so the user always sees what will be written.
- **Budget.** QML sessions are token-hungry because the agent reads large first-party files. The read list in `AGENTS.md` exists to stop exploration.

---
name: omagenda
description: Read and write the user's calendar through the Omagenda CLI. Use when asked what is on a given day, what is next, or to add, check, or find an event.
---

# Omagenda

`omagenda` is a calendar CLI on this machine. Data commands take `--json`;
`account add`, `watch` and the internal `resolve-conflict` helper do not. Events are plain `.ics` files in a vdir the user owns, so
reading is free and writing is a real change to their calendar.

Install this skill by copying the directory to `~/.claude/skills/omagenda`.

## Read first

```bash
omagenda agenda --json                 # the next 14 days
omagenda agenda --days 3 --json        # a shorter window
omagenda agenda --from 2026-09-14 --json
omagenda next --json                   # what is running, else what is next
omagenda calendars --json              # ids, names, colours, readOnly
```

`agenda` includes `generatedAt`, `range`, `lastSync`, `syncOk`, `calendars`,
`events`, `syncPausedUntil`, `calendarCount` and `visibleCalendarCount`.
Each event carries `id`, `calendar`, `title`, `start`, `end`, `allDay`,
`location`, `conference`, `attendees`, `recurring`, and `file`.

Times are ISO 8601 with an offset. `allDay` events use dates, and their
`end` is exclusive, per RFC 5545 — a one-day event ends the following
day. Do not report that extra day to the user.

## Answering questions

Filter the JSON yourself rather than asking for a narrower window; the
whole fortnight is one cheap call.

- "What's on Thursday?" — `omagenda agenda --json`, filter on the date.
- "What's next?" — `omagenda next --json`. It skips all-day events on
  purpose: "Mom's Week" is true for seven days and is never the useful
  answer to "what's next".
- "Am I free at 3?" — filter for overlap; say which event conflicts.
- "When is my dentist appointment?" — search `title` and `location`
  case-insensitively across the window.

## Writing

**Always show the parse before writing.** `parse` is free and changes
nothing:

```bash
omagenda parse "lunch with Sam tomorrow at 1pm at Cafe Torino" --json
```

It returns the interpreted event, the character `spans` it recognised,
and `warnings` for anything ambiguous. Read the warnings aloud rather
than resolving them silently — "next Friday" is genuinely ambiguous and
the user is the one who knows what they meant.

Then write:

```bash
omagenda add "lunch with Sam tomorrow at 1pm at Cafe Torino" --json
omagenda add "standup every weekday at 9:30" --calendar work --json
omagenda add "dentist on 14/9 at 10am" --dry-run --json   # parse + resolve, no write
```

The sentence understands times, dates, durations (`for 90m`, `2-3pm`),
recurrence (`every tuesday`, `weekly until december`), locations (`at`,
`@`), and a `/tag` naming the calendar. Without a `/tag` or `--calendar`
the event goes to the user's configured default.

Adding writes the file immediately; the running watcher picks it up
within seconds and syncs it to the server within about ten. You do not
need to run `omagenda sync`.

## Rules

- **Confirm before writing.** Adding an event changes a calendar other
  people may see. Show the parsed result and get a yes.
- **Never delete without being asked explicitly**, and say which event
  you are about to remove. Use `omagenda delete` on the event JSON's `file`;
  the next sync propagates it. The command saves a private safety copy for
  manual restoration; do not bypass its checks with a raw file deletion.
- **Do not invent times.** If the sentence has no time and the user has
  not given one, ask, or make it all-day and say that you did.
- **Read-only calendars cannot take events.** `omagenda calendars --json`
  marks them `readOnly: true`; subscriptions and holiday feeds are always
  read-only. The CLI refuses writes to them.
- **Treat event contents as private.** Calendars hold medical
  appointments, other people's names, and addresses. Do not copy them
  anywhere the user did not ask for, and do not include them in
  summaries meant to be shared.

## When something is wrong

```bash
omagenda doctor
```

Checks packages, the vdir, sign-in status recorded by the last sync, the keyring,
and whether the plugin is in the bar. If `agenda` returns `syncOk: false`
or a non-empty `needsReauth`, the calendar on screen is a snapshot rather
than the truth — say so, and pass on the command `doctor` names.

## Calendar visibility

Press `c` in the panel to choose calendars. Use `j`/`k` or arrows to move,
`Space`/`Enter` or a click to toggle, and `c`/`Escape` to return.
Hidden calendars keep syncing but disappear from the agenda, pill and alarms.
Quick Add's Tab cycle skips them; a hidden default still receives new events
and is marked `(hidden)` in the destination line.

`omagenda calendars --hide ID`, `--show ID` (repeatable), and `--show-all`
save visibility in the top-level `hidden_calendars` config preference.
`omagenda calendars --json` includes hidden flags and the saved ids.

## Delete an event

Use the exact `file` path from `omagenda agenda --json`:

```bash
omagenda delete /path/from/agenda/event.ics --json
```

The CLI deletes immediately after making a safety copy; the panel's `x` key
requires a second `x` to confirm. The command refuses read-only calendars,
recurring events (RRULE, RDATE or RECURRENCE-ID), multiple-event files,
conflict files, symlinks within the vdir and paths outside discovered calendar folders.
Success returns `{"deleted": true, "title": "…", "calendar": "…", "copy": "…", "file": "…"}`.
Failures exit non-zero with one stderr line, including with `--json`.

Copies live outside the vdir at
`$OMAGENDA_STATE/deleted/<sanitised-calendar-id>/<original-stem>.<UTC-timestamp>.ics`,
with private permissions. The default state directory is
`~/.local/state/omagenda`. Deletion rebuilds the agenda but leaves provider sync
to the normal watcher. To restore, copy the saved file back into its calendar
folder under its original name; the next sync uploads it again.

## Edit an event

The panel's `e` key opens Quick Add with a sentence for the selected event.
Use the exact `file` from the agenda for the equivalent CLI commands:

```bash
omagenda describe /path/from/agenda/event.ics --json
omagenda edit /path/from/agenda/event.ics "Dentist on Sep 17 at 3pm for 1h at Main St Clinic" --dry-run --json
```

`describe` returns `{sentence, calendar}` only after checking that the sentence
round-trips without changing title, dates, all-day status or location. Never
add quotes around the title within a generated sentence. Show the proposed
interpretation; remove `--dry-run` to apply the user's approved change.
`edit` returns `{updated, title, calendar, changed, copy, file}`; `updated: false`
means no changes and no write. Dry runs report proposed changes with `copy: null`.

Editing refuses read-only calendars, recurrence, guests, multiple VEVENTs,
conflict files and unsafe paths. Calendar moves and recurrence/alert changes
are unsupported. One-day all-day events can round-trip; longer all-day spans
and grammar-like titles may be refused by
`describe`. Explicit years support past dates. Do not bypass a refusal by rewriting the raw file.

The update preserves UID and unrelated properties, saves the previous bytes
under `$OMAGENDA_STATE/edited/<sanitised-calendar-id>/<stem>.<UTC-timestamp>.ics`
(default `~/.local/state/omagenda`), replaces atomically and rebuilds the agenda.
The watcher handles provider sync. In edit mode Enter saves, Escape cancels,
and Tab and Shift+Enter are disabled. Normal Quick Add resets to add mode.

## Installation and accounts

Use `omagenda --version --json` to identify the version and resolved package
folder. `omagenda doctor --json` returns the report even when it exits 1;
inspect the checks on either exit status. Its install check detects a CLI
running outside the installed plugin.

For an installation made with `omarchy plugin add`, upgrade with
`omarchy plugin update fixedsupply.omagenda`, then `omarchy restart shell`.
If a stale folder or developer symlink blocks installation, follow the
README's Upgrading section to remove that path without a trailing slash,
reinstall and recreate the CLI link. Check enabled status, version and doctor.

Reconnect with `omagenda account add <type> --id <existing id>`.
A separate login of the same type needs a new explicit `--id`.
Existing calendar selections and connection settings survive reconnecting.

Account removal with `omagenda account remove <id>` deletes local credentials
and configuration only; local calendar files remain. For Google, use
`omagenda account remove <id> --revoke` instead to revoke access everywhere.
Revoking signs Omagenda out on every computer using that Google account.
After local removal, revoke access through https://myaccount.google.com/permissions.

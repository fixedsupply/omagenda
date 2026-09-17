# Changelog

## v0.3.0 — 2026-09-17

### Added

- Browse the agenda strip forward through eight weeks with keyboard movement,
  `‹`/`›`, or the scroll wheel.
- Expanded events identify their calendar and provider, with Google event and
  iCloud calendar web links available on the row and with `w`.

### Changed

- Calendar dots, bars and labels now choose distinct existing theme colours when
  a theme's assigned calendar colours are nearly identical.
- Delete and edit saves now say when they are waiting for an in-progress sync.
- Narrower Google permissions: event access and read-only calendar discovery.
  Existing sign-ins still work. Reconnecting gives a token limited to the
  narrower permissions; to also remove the old full-access entry from your
  Google account, remove Omagenda at Google account permissions first, then
  reconnect (this signs out other computers using that account).
- Google acceptance uses a separate, in-memory, short-lived permission for its
  disposable calendar. It is not revoked afterwards, because revoking could also
  sign the normal Omagenda grant out; it expires on its own within an hour.

## v0.2.1

- Account removal is local by default; Google revocation requires `--revoke`
  and warns that it signs out every computer. Local calendars remain.
- Reconnect accounts in place with an existing explicit ID, preserving saved
  settings. Refuse implicit duplicate logins before sign-in for every type.
- Doctor finds orphan refresh tokens from keyring attributes on stderr as
  well as stdout, without exposing secrets.
- Doctor checks the installed plugin version and CLI path, detects stale
  successful syncs, and exits 1 on failed checks in JSON mode too.
- `omagenda --version` reports the manifest version and resolved install
  folder, with optional JSON output.
- Document upgrades, stale folder/symlink recovery and install verification
  following the Dell fresh-install test on Omarchy 4.0.3-1.

## v0.2.0 — 2026-09-16

### Added

- Calendar pick list on `c`, with persistent visibility choices. Hidden calendars
  keep syncing but leave the agenda, pill and alarms. Quick Add skips them when
  cycling destinations and labels a hidden default.
- Delete a selected event with `x`, then `x` again to confirm, or use
  `omagenda delete`. A private safety copy is saved before removal. Recurring,
  read-only, multiple-event and unsafe files are refused.
- Edit with `e` through a pre-filled Quick Add sentence, or use `describe` and
  `edit` in the CLI. Previous versions are saved privately; unchanged saves
  write nothing. Editing refuses recurrence, guests, read-only calendars,
  unsafe files and sentences that cannot preserve the original event.
- Expiring watcher sync pauses: `omagenda sync --pause 30m` and `--resume`.
  Manual sync remains available during a pause.
- Disposable-calendar acceptance scripts for Google and iCloud, with recorded
  successful runs and cleanup in the reviewer checklist.

### Changed

- Quick Add uses native text editing for cursor movement, selection, undo and
  paste. Failed saves retain the text and interpretation preview.
- Google account removal attempts to revoke sign-in and removes stored refresh
  tokens. Local calendars remain; doctor checks for leftover tokens.
- iCloud/CalDAV conflicts keep the server version and save the local version
  outside the calendar. A command resolver works around pimsync 0.5.7's broken
  `keep b` behavior; existing generated config lines migrate on the next sync.
  Calendar-property conflicts keep the server value with bounded resolution.
- Reminder-only collections are excluded from calendar discovery and Quick Add;
  they continue syncing. Empty calendars remain available.

### Fixed

- Times without “at”, such as `Coffee 10am tomorrow`, now parse as timed events.
  Explicit years work in named dates, including descriptions of past events.
- Google's echo of a newly created event no longer overwrites a pending local
  edit or produces a false conflict. Pending edits and deletes follow provider
  filename changes through short-lived aliases.
- Switching a Google event between all-day and timed clears the previous time
  form, avoiding an invalid-start-time error.
- Google timestamps retain their instant when an offset differs from the named
  timezone. Conditional updates preserve unrelated remote metadata; real
  conflicts retain the local version. Recurrence exceptions and remote removals
  survive snapshot reconciliation, and read-only calendars are not uploaded.
- Event files are replaced atomically so pimsync detects same-second changes.
- Clicking a day in the week strip completes navigation even when the clicked
  item is replaced. Delete confirmation no longer causes a binding loop.
- Panel closing supports both older and newer shell hover APIs. Calendar
  visibility failures recover, and failed watcher syncs respect the retry interval.

### Known limitations

- Moving events between calendars, editing events with guests, and editing or
  deleting individual recurring occurrences are deferred. The panel/CLI refuse
  recurring edits and deletes; Google writes of series with exception components
  are also refused. Recurrence changes may require a full calendar download.
- Templates, Microsoft support and inline syntax highlighting are deferred.
  Native editing and the interpretation preview are available. Multi-day all-day
  events and other sentences that cannot round-trip are refused by `describe`.
- Google remains a reviewer preview requiring approved test users; Testing-mode
  sign-in expires after seven days. Expired-auth UX and guest-metadata acceptance
  remain unverified. Generated CalDAV configs require a working `secret-tool`
  keyring even when account setup used the private-file credential fallback.
- A fresh-machine install, reboot, source update, the full overlay, iOS property
  conflicts, multi-calendar iCloud discovery through the real pair, installed
  config migration and the normal five-minute watcher interval remain unverified.
  Today's panel checks do not establish every step of the longer acceptance lists.
- Alarm notifications require an explicit alarm on a timed event; all-day
  alarms and configurable default lead times are not implemented.
- Evidence and remaining checks are in [STATUS.md](STATUS.md) and the
  [reviewer checks](docs/reviewer-checklist.md).

## v0.1.0

Initial preview: [v0.1.0 tag](https://github.com/fixedsupply/omagenda/tree/v0.1.0).

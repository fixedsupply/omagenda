# Omagenda reliability pass — 2026-09-14

Implementation and automated verification are complete for this pass.
Live-provider and fresh-desktop release acceptance remain pending.

## Changes

- Preserve local edits when remote updates or deletions conflict, including
  edits made while downloads are running. Keep distinct conflict copies and
  exclude them from the normal agenda.
- Retain Google ETags and require conditional updates/deletes. Updates use
  PATCH so unmapped metadata remains untouched. Missing versions fail closed
  and trigger refresh rather than authorising an unchecked write.
- Rebuild recurring changes from a complete snapshot, preserving exceptions
  and recurrence date parameters. Full snapshots reconcile remote removals.
  Refuse local writes containing exception components until supported.
- Never push to read-only calendars; restore their permissions on errors.
- Preserve sync settings when saving account/default-calendar configuration.
- Use native text editing in Quick Add. Keep failed saves open, discard stale
  parser responses, and return valid CLI JSON even when there are warnings.
- Isolate Python test defaults and watcher invalidation tests from the live
  plugin, configuration, credentials and calendar directories.
- Update setup, publishing and planning documents to identify preview limits.

## Verification

- 198 Python tests passed via `python tools/test-isolated.py`.
- 64 Node tests passed, including QML syntax checks.
- Offscreen Qt tests passed for insertion at the cursor, selection replacement,
  undo/clipboard, and submit/calendar shortcuts (six Qt results including setup
  and cleanup). The tests use Qt's offscreen platform, not the desktop clipboard.
- Plugin manifest validation, Lua binding syntax and `git diff --check` passed.
- Host reports Omarchy 4.0.3 and Qt 6.11.2 in the test runtime.

All provider regression responses and appointments were invented. No live
provider mutation or fresh-profile installation was performed for this pass.
The offscreen input tests do not exercise the complete running shell overlay.

## Remaining acceptance

Follow `docs/reviewer-checklist.md` with disposable Google/iCloud calendars,
then check the full overlay, reboot and source-update behaviour on the candidate.
Do not claim fresh-install or iCloud round-trip success until recorded.

Inline coloured highlighting is deferred; native editing and the live
interpretation preview remain. Calendar sets, templates and Microsoft stay
deferred. Refresh the historical Quick Add screenshot before publication.
The existing v0.1.0 tag was not moved and does not include this pass.

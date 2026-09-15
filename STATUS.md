# v0.2 candidate — 2026-09-15

Candidate `d57be3d` merges calendar visibility with the iCloud acceptance
and pimsync conflict fixes. It passed `tools/icloud-acceptance.py
--run-live` against a disposable iCloud calendar: all 16 checks, calendar
deleted, real watcher sync paused and resumed, no copy in the real vdir.
Suites on the candidate: 274 isolated Python tests (including real-pimsync
conflict tests run offline) and 70 Model.js tests plus QML parsing; plugin
validation and whitespace checks are clean.

Getting there took five failed live runs. Each found a real problem, and
each cleaned up fully. Details are in `docs/reviewer-checklist.md`.

- The script's own content check misread iCloud's reply.
- pimsync misses in-place edits made within a second of a sync, which also
  affected two Omagenda write paths.
- pimsync 0.5.7's `conflict_resolution keep b` wedges on a real conflict.
- Its `resolve-conflicts` loops forever on an unanswered property prompt.

Still unverified: live panel acceptance of calendar visibility, the
installed watcher migrating the real `family` pair's conflict setting, a
fresh install, reboot and source update. The two pimsync bugs have not yet
been reported upstream; a draft report exists outside the repository.

## Calendar visibility — 2026-09-15

Persistent per-calendar visibility replaces the previous selection layer.
The panel pick list supports queued toggles, and hidden events leave the
agenda, pill and alarms while calendars keep syncing. Quick Add preserves
a hidden default and labels it. Live panel acceptance remains pending;
see `docs/reviewer-checklist.md`. Verification: 252 isolated Python tests and 68 Model.js tests plus QML syntax
validation passed; plugin validation and whitespace checks are clean.
All development used isolated state.

## Previous reliability pass — 2026-09-14

Implementation and automated verification are complete for this pass.
Google's disposable-calendar acceptance script passed on candidate `8f8a026`
on 2026-09-14, including all ten checks and calendar cleanup. Remaining
provider and fresh-desktop acceptance checks are recorded in
`docs/reviewer-checklist.md`. iCloud setup is absent on this machine:
no configured iCloud account and no installed pimsync executable.

## Google timezone integration review

- Reviewed and integrated the timestamp-offset fix from `71df807`, retaining
  the later panel-close fix on main. Named-zone conversion now uses the
  timestamp's instant rather than copying its wall-clock digits.
- Added ICS round-trip coverage for winter offsets and a previous-day
  conversion, plus coverage for named-zone timestamps without an offset.
- All 201 isolated Python tests, both Node test files, six offscreen Qt
  results, plugin validation and whitespace checks passed.
- Reviewed the opt-in disposable Google calendar acceptance helper and
  checked its help command. Its subsequent live run passed as recorded above.

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

All provider regression responses and appointments were invented. The initial
reliability pass did not perform live provider mutations; the subsequent
Google acceptance run used only its own disposable calendar. No fresh-profile
installation has been performed.
The offscreen input tests do not exercise the complete running shell overlay.

## Remaining acceptance

Follow `docs/reviewer-checklist.md` with disposable Google/iCloud calendars,
then check the full overlay, reboot and source-update behaviour on the candidate.
Do not claim fresh-install or iCloud round-trip success until recorded.

Inline coloured highlighting is deferred; native editing and the live
interpretation preview remain. Templates and Microsoft stay deferred.
Refresh the historical Quick Add screenshot before publication.
The existing v0.1.0 tag was not moved and does not include this pass.

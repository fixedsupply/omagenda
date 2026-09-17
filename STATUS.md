# v0.2.1 candidate — 2026-09-16

## v0.3.0 candidate — 2026-09-17

Narrower Google permissions verified live. The maintainer reconnected on
`823229c`, and Google's tokeninfo reported exactly
`https://www.googleapis.com/auth/calendar.events` and
`https://www.googleapis.com/auth/calendar.calendarlist.readonly`.
calendarList (12 calendars) and event reads succeeded with that token.
`tools/google-acceptance.py --run-live` then passed all 10 checks on
`823229c` with the narrow everyday token and a one-off `calendar.app.created`
permission for the disposable calendar, which was deleted. The one-off
token is never revoked. Afterwards the everyday token still worked and no
acceptance calendar remained.

The two panel features (browsing ahead up to eight weeks, and the calendar
line with its web link) are covered by Python, Node and offscreen QML
tests. Live panel acceptance of both is still pending.

## v0.2.1 upgrade acceptance — 2026-09-16

On the maintainer's Dell 7573 (Omarchy 4.0.3-1), a genuine git install of
v0.2.0 was upgraded with `omarchy plugin update fixedsupply.omagenda` and
`omarchy restart shell`. `omagenda --version` reported 0.2.1 from the
plugin folder, and `omagenda doctor` passed its install check, which is
not a symlink there. Its leftover-token check found a real stale keyring
token (`google-2-refresh-token`, left by an accidental duplicate account)
that v0.2.0's check could never see.

The `omagenda` command link in `~/.local/bin` had to be recreated. It had
been deleted during that machine's earlier reinstall, and neither
`omarchy plugin add` nor `omarchy plugin update` creates it. The README's
install and upgrade steps already include the `ln -sf` step.

Based on public v0.2.0 (`ecb279c`), on branch `v0.2.1`.
The PM's Dell fresh-install test on Omarchy 4.0.3-1 initially appeared to
succeed, but a stale developer symlink blocked `plugin add` and an old CLI
on PATH hid the failed installation. After removing the symlink, install,
enabling Omagenda in the centre section, the watcher and sync all worked,
and doctor was clean. This is the PM's reported v0.2.0 test, not a live
acceptance run of this candidate.

The [v0.2.1 changelog](CHANGELOG.md#v021--unreleased) records the fixes:
local-only account removal, explicit reconnect/duplicate handling, keyring
orphan detection, install integrity, stale-sync diagnostics and `--version`.
See [Upgrading](README.md#upgrading) for recovery and verification.

Offline verification: 338 isolated Python tests and 90 Node checks pass
(the requested Node command reports four passing files). Plugin validation
and whitespace checks pass. No QML or screenshot changes. No live provider
run, tag or push in this session. The PM must still verify the
[v0.2.1 upgrade path](docs/reviewer-checklist.md#before-sharing-a-release);
reboot, source-update and full overlay acceptance remain outstanding.

Implementation choices: revocation warnings go to stderr, preserving JSON.
Without a stored token, explicit revocation retains the existing null result;
after local removal, use Google's permissions page to revoke access.
Reconnect reuses saved iCloud/CalDAV connection fields and sync backend;
ICS reconnect prompts for its credential URL. Missing/invalid manifests
fail the install check; invalid sync timestamps request manual sync.
Staleness uses the existing 300-second default and the 30-minute floor
even when the configured interval is zero, with age shown in whole minutes
or hours. An active pause takes precedence in the sign-in check.
Version/location describe the running package, including resolved developer
symlinks. Empty installs must connect a calendar before doctor is clean.

The sections below record earlier candidates and their limitations at the time.

## Historical v0.2.0 release candidate — 2026-09-16

Repository release prep is based on `2fd4a01`; see [CHANGELOG.md](CHANGELOG.md).
Recorded provider evidence: Google candidate `8f8a026` passed all 10 checks
on 2026-09-14, and again on `e7d1e7e` (the Google echo fix) on 2026-09-16;
iCloud candidate `d57be3d` passed all 16 on 2026-09-15. All disposable
calendars were deleted. The all-day/timed switch fix (`2fd4a01`) was
verified live by the watcher's next sync of the PM's affected event.
These runs predate later fixes;
[the reviewer checklist](docs/reviewer-checklist.md) records their scope.
The PM reports live checks today of delete, sentence edit, the calendar pick
list, clicking days and times without “at” on the code leading to `2fd4a01`.
No broader provider or overlay acceptance is inferred from that report.

Local verification: 313 isolated Python tests and 90 Node tests (89 model
checks and one QML parsing check) pass; plugin validation and whitespace
checks pass. Node's default isolated report counts four passing files;
`--test-isolation=none` exposes the 90 individual checks.

Still unverified: fresh-machine install, reboot, source update, full overlay,
iOS property conflicts, multi-calendar iCloud discovery through the real pair,
installed config migration, normal five-minute watcher sync, expired-auth UX
and guest-metadata acceptance. Detailed panel acceptance steps remain where
not covered by the PM's report. The screenshots were regenerated from demo
data and the privacy page update is prepared locally on gh-pages; the final
review and annotated tag follow, and the PM decides the push.
Offline clone of `release-0.2.0` at `9b3e3e1` passed on 2026-09-16:
plugin validation, `python3 -m py_compile` for all 46 `.py` files plus the CLI,
313 isolated Python tests, all four Node files (90 individual checks), CLI
help and whitespace checks. No packages were installed and no network was
used; this reused the host tools and external Python venv.

With empty temporary config/state/vdir and the isolated runner's keyring,
notification and shell-config guards, `doctor --json` exited 0: packages
present, no calendars, no prior sync, no CalDAV tool required, not paused,
none hidden, keyring lookup skipped, and plugin not enabled (no shell.json).
The keyring binary-presence check sees the test stub, not a working keyring.
Messages are accurate; README now explains the empty-install next step.
At that candidate, doctor's per-check failures did not make its JSON exit status nonzero; v0.2.1 fixes this.

The dated sections below are historical evidence, not the current test count.

## Historical candidate — 2026-09-15

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

At that date, still unverified: live panel acceptance of calendar visibility, the
installed watcher migrating the real `family` pair's conflict setting, a
fresh install, reboot and source update. The two pimsync bugs have not yet
been reported upstream; a draft report exists outside the repository.

## Calendar visibility — 2026-09-15

Persistent per-calendar visibility replaces the previous selection layer.
The panel pick list supports queued toggles, and hidden events leave the
agenda, pill and alarms while calendars keep syncing. Quick Add preserves
a hidden default and labels it. Live panel acceptance was pending at that date;
see `docs/reviewer-checklist.md`. Verification: 252 isolated Python tests and 68 Model.js tests plus QML syntax
validation passed; plugin validation and whitespace checks are clean.
All development used isolated state.

## Previous reliability pass — 2026-09-14

Implementation and automated verification are complete for this pass.
Google's disposable-calendar acceptance script passed on candidate `8f8a026`
on 2026-09-14, including all ten checks and calendar cleanup. Remaining
provider and fresh-desktop acceptance checks are recorded in
`docs/reviewer-checklist.md`. At that date iCloud setup was absent; this
was superseded by the configured account, installed pimsync and passing
2026-09-15 acceptance run above.

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
Fresh-install success remains unrecorded; the iCloud script round trip was
subsequently recorded on 2026-09-15.

Inline coloured highlighting is deferred; native editing and the live
interpretation preview remain. Templates and Microsoft stay deferred.
Refresh the historical Quick Add screenshot before publication.
The existing v0.1.0 tag was not moved and does not include this pass.

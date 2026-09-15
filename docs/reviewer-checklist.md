# Reviewer acceptance

This is a preview, not a claim that every provider has passed live testing.
Use invented appointments in disposable calendars. Keep tokens, subscription
URLs, account addresses and screenshots of personal appointments out of
issues, logs and commits.

## Before sharing a release

- Run `python tools/test-isolated.py`, the Node tests, the Qt text-field tests
  and `omarchy plugin validate .` from the candidate checkout.
- Install the candidate on a fresh Omarchy profile, following only the README.
  Confirm the pill appears, both shortcuts work, and Quick Add shows its
  preview. Correct text in the middle, select, paste, undo and save.
- Approve the reviewer as a Google test user before sign-in. Check that
  expired sign-in produces a useful reconnect message.
- Connect only a disposable Google calendar. Create an event in Omagenda;
  let the watcher sync it. Move it on Google; let the watcher import it.
  Change its local title, then verify that time, guests and other metadata
  remain intact remotely. Delete the disposable event and check both sides.
- Move and cancel individual occurrences of an invented recurring series
  on Google. Verify the local agenda. Attempt a local edit to a series with
  exceptions and verify a visible sync error rather than a partial update.
- Edit one disposable event on both sides before sync. Confirm the remote
  version wins and the local edit survives in a conflict copy.
- Repeat create, remote edit and delete against a disposable iCloud calendar
  using an app-specific password and pimsync. This requires a reviewer with
  iCloud access; generated configuration alone is not acceptance evidence.
- Reboot and confirm the plugin starts and continues syncing. Update plugin
  source and confirm the watcher restarts without duplicate watchers.

Record the candidate commit, Omarchy version, providers checked and outcomes.
Do not use the existing v0.1.0 tag as evidence for later reliability changes;
it still identifies the earlier candidate. Publish a new candidate tag only
after its checks are complete.

## Current limits

### Recorded Google script run — 2026-09-14

Candidate `8f8a026` passed `python tools/google-acceptance.py --run-live`
on the maintainer's Omarchy 4.0.3 machine. All ten script checks passed:
disposable calendar creation, CLI upload exactly once, remote time import,
local update with remote metadata retained, conflicting local edit recovery,
moved and cancelled recurrence import, local deletion, and watcher-driven
creation, remote edit import and deletion. The disposable calendar was
successfully deleted; the command exited zero.

The initial sandbox attempt could not access the saved refresh credential
and stopped before sending the calendar creation request. The successful
run used desktop keyring and network access. No personal events were used.

This establishes the script's Google scenarios only. Expired-auth UX,
guest metadata, visible refusal of local series edits with exceptions,
full shell interaction, fresh installation, reboot/source update and iCloud
acceptance remain unverified. The watcher used an accelerated two-second
sync interval.

### Recorded iCloud script run — 2026-09-15

Candidate `d57be3d` passed `python tools/icloud-acceptance.py --run-live`
on the maintainer's Omarchy 4.0.3-1 machine with pimsync 0.5.7-1. All 16
checks passed:

- real watcher sync paused, then resumed;
- disposable calendar created, then deleted;
- CLI upload exactly once, with the remote time change imported;
- local title edit uploaded;
- simultaneous edit ending with the remote title on both sides, and the
  local version saved outside the calendar;
- moved and cancelled recurrence imported as one file;
- local and remote deletion;
- watcher-driven creation, remote edit import and deletion;
- no disposable calendar copied into the real vdir.

The command exited zero. The same checks had passed on `0b8bf1f`, the tip of
the fix branch, before the merge. Runs were started from a Claude Code
session with desktop keyring and network access. No personal events were
read.

Five earlier runs failed. Each deleted its calendar, resumed real sync and
left no orphan.

1. `fc30ec1`, stage "CLI upload exactly once". The event had uploaded, but
   iCloud's `calendar-query` REPORT without a time-range lists the
   collection itself, and the script rejected that entry. Fixed in
   `1710a17`.
2. `1710a17`, stage "local title edit". pimsync's vdir etag is whole-second
   mtime plus inode, so an in-place rewrite in the same second as a sync is
   never uploaded. The script, plus two in-place writers in `omagenda/sync.py`,
   now replace files atomically (`2d8cfdc`).
3. `2d8cfdc`, stage "simultaneous edits". With `conflict_resolution keep b`,
   pimsync 0.5.7 fails every sync with "etag mismatch when updating item"
   and `resolve-conflicts` finds nothing. Generated configs now use an
   `omagenda resolve-conflict` command, and existing configs migrate on
   their next sync (`054e39a`).
4. and 5. `054e39a`, the second time with the diagnostic logging later
   committed in `0b8bf1f`, stage "simultaneous edits". `pimsync
   resolve-conflicts` repeated an unanswered calendar-property prompt until
   the 120-second timeout. It is now given explicit answers and a bounded
   timeout (`0b8bf1f`).

This establishes the script's single-collection iCloud scenarios only. It
does not establish:

- multi-calendar discovery through the real `collections from b` pair;
- the installed watcher migrating an existing `keep b` config;
- property conflicts caused by edits on iOS;
- sync at the normal five-minute interval (the watcher used two seconds);
- the full shell overlay, a fresh installation, reboot or source update.

Unlike the Google script, the conflict step shows a real desktop
notification.

Calendar visibility is implemented; live panel acceptance remains pending below.
Templates, inline syntax highlighting and Microsoft support are deferred.
Local editing of recurring series with exceptions is refused.
A recurrence delta currently requires a full calendar download. A passed
mocked sync suite cannot substitute for the provider checks above.

## Calendar visibility acceptance — pending

Automated verification on 2026-09-15 passed 252 isolated Python tests,
68 Model.js tests and QML syntax validation, plus plugin validation and
whitespace checks. Coverage exercises filtering, CLI rewrites and queued toggles. Live panel latency, scrolling, focus and keyboard handling
remain unverified. After merging, restart the shell and open the panel.
Press C, move with J/K or arrows, toggle with Space/Enter or a click, and
return with C/Escape. Rapidly toggle different rows and the same row twice.
Confirm the footer count, persistence after restart, hidden default label,
and all-hidden message. Confirm doctor remains clean. Record the candidate
and outcome without calendar contents or live screenshots.

## Opt-in Google acceptance script

`python tools/google-acceptance.py --run-live` uses the existing Google
authorization to create a uniquely named disposable secondary calendar.
It requires exactly one configured Google account with an explicit calendar
selection, so the normal watcher will not adopt the test calendar.

The script uses a temporary config, vdir and state directory. It checks CLI
creation, remote time changes, metadata preservation, conflicts, recurring
exceptions and deletion. It also starts a separate watcher with a two-second
sync interval to check automatic round trips without manual sync commands.
That accelerated check is not a measurement of the normal five-minute interval.
No invitations are sent. Conflict notifications are suppressed for the direct
sync scenarios; the calendar API and sync code are real.

The script deletes only the calendar it created, including on test failure.
If cleanup fails or calendar creation has an uncertain outcome, it prints the
path to a private recovery receipt. Resolve that before rerunning. Do not
publish the receipt or captured watcher logs. This script does not validate
the full shell overlay, a fresh installation, reboot, or iCloud.

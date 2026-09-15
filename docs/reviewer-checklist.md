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

Calendar sets, templates, inline syntax highlighting and Microsoft support
are deferred. Local editing of recurring series with exceptions is refused.
A recurrence delta currently requires a full calendar download. A passed
mocked sync suite cannot substitute for the provider checks above.

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

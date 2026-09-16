# Connecting your calendars

Omagenda keeps every calendar as plain `.ics` files in a
[vdir](https://vdirsyncer.pimutils.org/en/stable/vdir.html) at
`~/.local/share/calendars`. The pill, the panel, Quick Add, the CLI, and
tools like `khal` share that event directory; config and state live separately.
Sync is a separate job, done by a *bridge* per account type.

`omagenda watch` syncs every five minutes, and within about ten seconds
of any change you make locally. You never need to run `omagenda sync` by
hand; it exists for when you are impatient.

## Google

Google requires OAuth. There is no password or app-password route: their
CalDAV endpoint needs OAuth too, so a Google account cannot be connected
with a username and password by any client, including this one.

```
omagenda account add google
```

Your browser opens for consent. Tokens use the system keyring, with an
owner-only local file fallback if the keyring is unavailable; neither
belongs in this repository.

The project is currently a **reviewer preview in Google Testing mode**.
The maintainer must add your Google account to the project's test-user list
before you can connect. That list is limited to 100 users. Calendar
permission grants and refresh tokens expire after seven days in this mode;
reconnect when Omagenda reports that sign-in has expired.
See [Google's audience documentation](https://support.google.com/cloud/answer/15549945?hl=en).

You may see an unverified-app warning during consent. Review the requested
calendar access before proceeding. Being a test user does not override
Advanced Protection or a workplace administrator's restrictions.

The Testing limit is separate from Google's cumulative cap for unverified
apps requesting sensitive scopes. Moving to Production is not verification
and does not by itself remove that cap. See
[Google's unverified-app documentation](https://support.google.com/googleapi/answer/7454865?hl=en).

By default every calendar you can write to is synced. To choose
explicitly, list them in `~/.config/omagenda/config.toml`:

```toml
[[accounts]]
id = "google"
type = "google"
calendars = [
  "you@example.com",  # replace with your remote calendar id
]
```

`omagenda calendars` prints the ids, names, colours, and which are
read-only.

## Apple iCloud

**Validation status:** the disposable single-calendar acceptance run passed
all 16 checks on `d57be3d` (2026-09-15), including cleanup. A fresh install
and multi-calendar discovery through the real pair remain unverified;
see [the recorded run](reviewer-checklist.md).

iCloud speaks CalDAV and takes an app-specific password, so it needs no
OAuth and no browser.

1. Sign in at [appleid.apple.com](https://appleid.apple.com), go to
   **Sign-In and Security**, and generate an **app-specific password**.
2. Run:

```
omagenda account add icloud --id family --username you@example.com
```

It prompts for that password with the input hidden and stores it in your
keyring (private-file fallback if unavailable). The generated pimsync config
uses `secret-tool`, so iCloud/CalDAV sync requires an unlocked keyring even
if account setup fell back to a file. It then writes a [pimsync](https://pimsync.whynothugo.nl/)
config for you.

```
omarchy pkg add pimsync libsecret
omagenda sync
```

Events you add reach any iPhone or iPad signed into the same Apple ID.

## Any other CalDAV server

Fastmail, Nextcloud, Radicale, Zoho, a self-hosted Baikal:

```
omagenda account add caldav --id work \
  --url https://caldav.example.com/dav/ --username you@example.com
```

Same prompt, same keyring, same pimsync config.

## A read-only subscription (ICS URL)

Anything that publishes a `.ics` feed: a sports schedule, a holiday
calendar, a shared calendar someone sent you a link to.

```
omagenda account add ics --id holidays --color yellow
```

It prompts for the URL with the input hidden, because a subscription URL
usually carries its own access token and should be treated as a password.
`omagenda account list` masks it back down to its host for the same
reason.

Subscription calendars are marked read-only on disk, and Quick Add will
not offer them as a destination, because the server would refuse the
write.

## Where new events go

```
omagenda calendars --set-default work
```

Quick Add writes there unless the sentence names another calendar with a
`/tag`. Tab cycles between visible calendars that can accept an event; a hidden default remains usable.

## Checking on it

```
omagenda doctor
```

Reports missing packages, the vdir, sign-in status from the last sync,
the keyring, and whether the plugin is in your bar.

## Editing limits in this preview

Google updates use conditional partial writes, preserving fields such as
attendees that Omagenda does not edit. A conflicting local edit is saved
beside the event as `.conflict.ics`; the remote version wins. Existing
conflict copies are retained. Review them manually rather than copying
an entire series back onto the server.

Series containing exception components cannot currently be edited locally;
sync reports an error instead of discarding those components. Edit those
series in Google Calendar. Changes to recurring events trigger a complete
calendar download to rebuild the series correctly, so they can take longer
than an ordinary incremental sync.

## Conflicts and local state

iCloud/CalDAV use a command resolver because pimsync 0.5.7's `keep b`
can leave an event conflict failing indefinitely. On the next sync,
Omagenda replaces the existing generated config's `conflict_resolution`
line with its `resolve-conflict --account ID` command. Other lines stay
unchanged. Event conflicts keep the server version, save yours and notify;
calendar-property conflicts keep the server value. Resolution has a bounded
timeout. Reminder-only collections keep syncing but are excluded from
calendar discovery and Quick Add.

Under `$OMAGENDA_STATE` (default `~/.local/state/omagenda`):

| Path | Purpose |
| --- | --- |
| `deleted/<calendar>/` | Private copies saved before CLI/panel deletion. |
| `edited/<calendar>/` | Private previous versions saved before sentence edits. |
| `conflicts/<account>/` | iCloud/CalDAV losing local versions; kept outside the vdir to avoid uploading duplicates. |
| `adopted.json` | Event-path aliases valid for 24 hours after a provider assigns its own identity; pending edits/deletes can follow them. |
| `sync-paused-until` | Expiry timestamp for the watcher sync pause. |

Google conflict copies remain beside their event as `.conflict.ics`, excluded
from the agenda and uploads. Never replace event contents in place: use an
atomic file replacement so pimsync notices edits made within the same second.

## Pause or disconnect

```bash
omagenda sync --pause 30m --json
omagenda sync --resume --json
omagenda account list --json
omagenda account remove google --json
```

Replace `google` with the id printed by `account list`. Pause durations use
positive integers with `s`, `m` or `h`, up to 24 hours. They expire automatically;
manual `omagenda sync` still runs during a pause. Neither pause nor resume
performs a sync.

Removing a Google account attempts to revoke its sign-in and deletes stored
refresh tokens from the keyring and private-file fallback. If revocation
fails, follow the reported Google permissions link. Local calendars are
retained. `doctor` checks for leftover Google refresh tokens from removed
accounts; a locked or unavailable keyring is reported as skipped.

Project [homepage](https://fixedsupply.dev/omagenda/),
[privacy](https://fixedsupply.dev/omagenda/privacy/) and
[terms](https://fixedsupply.dev/omagenda/terms/).

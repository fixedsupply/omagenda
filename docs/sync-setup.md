# Connecting your calendars

Omagenda keeps every calendar as plain `.ics` files in a
[vdir](https://vdirsyncer.pimutils.org/en/stable/vdir.html) at
`~/.local/share/calendars`. The pill, the panel, Quick Add, the CLI, and
tools like `khal` all read and write that directory and nothing else.
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
  "you@gmail.com",
  "family1234567890@group.calendar.google.com",
]
```

`omagenda calendars` prints the ids, names, colours, and which are
read-only.

## Apple iCloud

**Validation status:** configuration generation has automated coverage; a
fresh-install round trip against a disposable iCloud calendar remains a
release acceptance check.

iCloud speaks CalDAV and takes an app-specific password, so it needs no
OAuth and no browser.

1. Sign in at [appleid.apple.com](https://appleid.apple.com), go to
   **Sign-In and Security**, and generate an **app-specific password**.
2. Run:

```
omagenda account add icloud --id family --username you@icloud.com
```

It prompts for that password with the input hidden and stores it in your
keyring. It then writes a [pimsync](https://pimsync.whynothugo.nl/)
config for you.

```
omarchy pkg add pimsync
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
`/tag`. Tab cycles between calendars that can actually accept an event.

## Checking on it

```
omagenda doctor
```

Reports missing packages, the vdir, whether your sign-ins are still good,
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

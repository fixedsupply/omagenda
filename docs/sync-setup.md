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

Your browser opens, you approve, and the token is stored in your system
keyring rather than in any file in this repository.

> **You will see "Google hasn't verified this app".** Click **Advanced**,
> then **Go to Omagenda (unsafe)**. Omagenda's OAuth client has not been
> through Google's verification review, which is a review of the
> publisher, not of the code. The code is in this repository and the
> scope requested is `calendar` and nothing else.

> **Sign-ins currently expire about weekly.** Until the OAuth client is
> published to production, Google expires its refresh tokens every seven
> days. When that happens the panel says so and names the command to run.
> See [docs/google-cloud-setup.md](google-cloud-setup.md) for the detail,
> including what to do if your account is on Advanced Protection.

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

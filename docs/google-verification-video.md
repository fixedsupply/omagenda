# The Google verification demo video

Google's OAuth verification asks for one video that shows the consent screen,
the exact scopes, and how each scope is used. This is the shot list, the
narration, and who does which part.

## What Google requires

From [Demo video](https://support.google.com/cloud/answer/13804565) and
[Verification requirements](https://support.google.com/cloud/answer/13464321):

- The complete OAuth consent screen, showing the same exact scopes being
  requested at submission.
- The language toggle at the bottom-left of the consent screen set to English.
- How each requested scope is used for the app's functionality, and the app's
  overall purpose.
- The same app, name and branding as the console entry.
- Hosted on YouTube, Google Drive or another accessible file. One link only.
- Narration is recommended so a reviewer can hear where each criterion is met.

Reviewers also routinely ask to see the OAuth client ID in the address bar
during the grant. It costs nothing, so the shot list includes it.

Omagenda requests two scopes, and each gets its own beat in the video:

| Scope | Shown by |
|---|---|
| `calendar.calendarlist.readonly` | the calendar pick list on `c`, naming the account's calendars |
| `calendar.events` | the agenda reading events, then Quick Add, edit and delete writing them back |

## What the demo data has to be

The local demo vdir (`tools/demo-vdir.py`) cannot be used here. Those events
exist only on disk, and it is run with `--no-sync` on purpose — Google has never
heard of them, so they cannot show `calendar.events` being used. The video has
to show an event appearing, changing and disappearing in Google Calendar on the
web, which means real API traffic against a real account.

The staging that satisfies both that and privacy: a dedicated **Omagenda demo**
calendar inside the maintainer's own Google account, holding invented events,
with every other calendar hidden in Omagenda.

The finished video is an unlisted link, which is not the same as private: it
needs no login, and anyone it is forwarded to can watch it. What remains visible
with this approach is the signed-in address on the consent screen — which Google
already has — and the real calendar names in the pick-list shot, which are
blurred in post.

## Before recording

1. **Create a calendar called `Omagenda demo`** in Google Calendar and put four
   or five invented events in it (`Team standup`, `Dentist`, `Farmers market`,
   `Project review`, `Lunch with Sam`). They can be written with Omagenda
   itself: `omagenda add 'Team standup tomorrow 10am' --calendar <demo id>`.
2. **Pin it for sync.** A Google account with an explicit `calendars` list in
   `config.toml` ignores calendars that are not in it, so a newly created
   calendar never appears until its ID is added there.
3. **Hide every other calendar** (`hidden_calendars`, or `c` in the panel) so
   the agenda, the pill and the alarms can only show invented events. Keep the
   original list: it has to be restored afterwards.
4. **In Google Calendar on the web**, untick every calendar but the demo one, so
   the web shots are invented events too.
5. Quiet the desktop: close other windows, silence notifications, and set the
   browser to a clean window with no other tabs, no bookmarks bar, no extensions
   visible, and no other profile signed in.
6. Sign out of Omagenda's Google account (`omagenda account remove google`,
   which is local-only) so that shot 4 can show the sign-in from the start. Do
   this last, immediately before recording.
5. Confirm the console entry matches what the video will show: app name
   **Omagenda**, homepage `https://fixedsupply.dev/omagenda/`, privacy
   `.../privacy/`, terms `.../terms/`.
6. The OAuth app is already published to production, which is the state Google
   expects to see.

## Shot list

Target four to five minutes. Each shot has its narration line; read them as
written or let them be burned-in captions.

1. **Title card, 5s.** "Omagenda, a calendar plugin for the Omarchy Linux
   desktop. Client ID ending <last six characters>."
2. **The homepage**, `https://fixedsupply.dev/omagenda/`, scrolling to the
   privacy and terms links. "This is the app's homepage, privacy policy and
   terms, at the domain registered in the console."
3. **The desktop**, bar pill visible, agenda panel opened and closed. "Omagenda
   runs entirely on the user's own computer. It shows the next event in the top
   bar and a seven-day agenda."
4. **Terminal**: `omagenda account add google --id google`. "Adding a Google
   account starts the OAuth flow in the browser."
5. **The consent screen, held still for ten seconds.** Show the address bar with
   `client_id=` legible, the language toggle at the bottom-left reading English,
   the app name, and both scopes expanded. "This is the consent screen for the
   app being verified. It requests exactly two scopes: see and edit events on
   the user's calendars, and view the list of calendars. The client ID is
   visible in the address bar." Then grant.
6. **Terminal**: the success line and the first sync. "Sign-in succeeded. The
   refresh token is stored in the desktop keyring, on this computer only."
7. **Panel, press `c`.** "The calendar list scope is used for exactly this: the
   names of the account's calendars, so the user can choose which to show and
   which calendar a new event goes to. Omagenda never writes to the calendar
   list." This is the shot whose calendar names get blurred in post; hold it
   still so the blur box does not have to track anything.
8. **Panel, the agenda.** "The events scope reads the user's events to draw the
   agenda and the bar. Events are stored as plain .ics files in a folder on this
   computer."
9. **Quick Add**: type `Coffee with Alex tomorrow 10am`, save. Then switch to
   Google Calendar on the web and show the new event. "The same scope creates an
   event when the user asks. Here it is in Google Calendar."
10. **Edit**: select the event, `e`, change the time to 11am, save. Show the
    change on the web. "Editing rewrites the event through the same scope."
11. **Delete**: select the event, `x`, `x` to confirm. Show it gone on the web.
    "And deleting removes it."
12. **Terminal**: `omagenda account remove google`, then
    `https://myaccount.google.com/permissions` showing the app and the Remove
    access button. "Removing the account deletes the stored sign-in from this
    computer. Access can also be revoked from the Google account page at any
    time."
13. **End card, 5s.** "Omagenda sends no data anywhere except back to Google.
    There is no Omagenda server, no telemetry and no analytics. Contact:
    support@fixedsupply.dev."

Shots 9, 10 and 11 are the ones reviewers watch for: a scope requested is a
scope visibly used.

## Recording

`gpu-screen-recorder` ships with Omarchy and ffmpeg is installed.

```bash
omarchy screenrecord --fullscreen
```

Run it again to stop; the file lands in `~/Videos`. Add
`--with-microphone-audio` for live narration.

Two ways to narrate, in order of preference:

1. **Burned-in captions.** Record silently, then caption from an `.srt`. No
   retakes for a stumbled line, and the wording stays reviewable and editable.
2. **Live narration.** One take, no post-production, but any fluff means
   recording the whole flow again.

Trimming, blurring the calendar names, and captioning:

```bash
ffmpeg -i in.mkv -ss 00:00:03 -to 00:04:30 -c copy trimmed.mkv
ffmpeg -i trimmed.mkv -vf "boxblur=12:enable='between(t,95,110)':x=..." blurred.mkv
ffmpeg -i blurred.mkv -vf subtitles=narration.srt -c:a copy final.mp4
```

The blur region and its time window are read off the recording, so that middle
command gets its real numbers once the take exists.

## Upload

Upload to YouTube as **Unlisted** and submit that one link with the
verification. Keep the source file; a rejection usually asks for one more beat
rather than a new video.

## Afterwards

Undo the staging: restore the hidden-calendar list to what it was, and decide
whether the demo calendar stays (harmless, it syncs like any other) or goes,
along with its events and its entry in the account's pinned `calendars`.

## The recorded video, 2026-09-17

Recorded and submitted: <https://youtu.be/5AZxfH_7RV0> (unlisted), 3:36, kept
locally at `~/Videos/omagenda-oauth-demo.mp4`.

What it shows, in order: title card, homepage, privacy policy (with both narrow
permissions), terms, `omagenda account add google --id demo`, Google's
unverified-app warning, **the consent screen listing both permissions**, first
sync, agenda, calendar pick list, Quick Add creating an event, that event in
Google Calendar on the web, delete with `x` `x`, the empty day in Google
Calendar, `omagenda account remove demo`, end card. Captions are burned in; the
video is silent.

Things learned the hard way, for the next recording:

- **The consent screen only lists the scopes for an account that has not
  already granted them.** A re-grant shows a summary screen saying "Omagenda
  already has some access", which does not satisfy the requirement. Revoke at
  <https://myaccount.google.com/permissions> first, and remember that revoking
  also signs out the maintainer's everyday account, which then needs
  reconnecting.
- **`omagenda account add` prints every calendar it can see**, which on a real
  account means real calendar names in the frame. Clear the terminal as soon as
  the token lands, and cut the take before that output appears.
- The bar carries other plugins' data: a finance widget showed a portfolio
  total in every frame of the first attempt. Disable other bar widgets before
  recording.
- The screen recorder keeps running for a second or so after a workspace
  switch, so takes end with frames of whatever workspace came next. Shave the
  tail of every clip and verify afterwards, frame by frame.
- The Google account permissions page lists every third-party app connected to
  the account. Do not film it; the CLI's removal message names the page anyway.

## Who does what

- **Claude**: this script, staging the demo calendar's data and the panel state,
  starting and stopping the recording, trimming, captions, and checking the
  finished file against the requirements above before it is submitted.
- **The PM**: signing in to Google and clicking through the consent screen (his
  account, his credentials), and uploading to YouTube.
- **Not Codex**: it works in the same terminal, with no browser and no session
  of its own. Nothing here needs it.
- **Not Grok Bot**: it must never sign in to the owner's Google account, which
  is the whole middle of this video.
- **Not TypeSafe**: it is for building AI decisions into software, unrelated to
  recording or verification.

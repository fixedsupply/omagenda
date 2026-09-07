# Google Cloud project setup (one-time, for the project owner)

Omagenda's Google bridge needs an OAuth client so users can sign in with their existing Google account. This client identifies *Omagenda* to Google, not any one user — every user still logs in with their own account and grants or revokes access from their own Google settings at any time. This page is for whoever owns that client (the PM), done once, before Phase 1b.

Cost: free. The Calendar scope Omagenda needs is classified "sensitive," not "restricted" — it never requires Google's paid security assessment (that only applies to scopes like full Gmail or Drive access). The only thing "verification" costs later is writing a privacy page and recording a short screen capture.

## 1. Create the project

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and sign in.
2. Top bar → project picker → **New Project**.
3. Name it `omagenda` (or similar). No organization/billing account is required for this.

## 2. Enable the Calendar API

1. Left menu → **APIs & Services** → **Library**.
2. Search "Google Calendar API" → **Enable**.

## 3. Configure the OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**.
2. User type: **External** (anyone with a Google account, not just your Workspace).
3. Fill in: app name `Omagenda`, user support email, developer contact email. Skip logo and links for now.
4. **Scopes** → **Add or remove scopes** → find or manually enter `https://www.googleapis.com/auth/calendar` → save.
5. **Test users** → add your own Google account (and any early testers, up to 100). Leave publishing status as **Testing** for now.
6. Save. Do **not** click "Publish app" yet — that comes right before the README ships (see §5).

## 4. Create the OAuth client

1. **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**.
2. Application type: **Desktop app**. (This is the type built for exactly Omagenda's flow — a loopback redirect on `127.0.0.1` with PKCE, no server, no redirect URI to register. Do not pick "Web application".)
3. Name it `omagenda-cli` or similar → **Create**.
4. Copy the **Client ID** and **Client secret** shown.

Google does not treat a desktop/installed-app client secret as confidential (it can't be, since it ships in an open-source binary everyone can read); it only identifies the app. This is why OmaCal, gcalcli, rclone, and most open-source Google integrations commit their client id in the repo. Omagenda does the same in `omagenda/bridges/google.py`, per `ARCHITECTURE.md` §11.

## 5. Hand off to the implementer

For Phase 1b, set these two environment variables in the dev session (do not commit them to a file until the PM confirms them for the shipped default):

```
OMAGENDA_GOOGLE_CLIENT_ID=...
OMAGENDA_GOOGLE_CLIENT_SECRET=...
```

## 6. What "Testing" mode means until then

- Up to 100 test users, each added by email on the consent screen.
- Anyone signing in sees an "unverified app" warning; a test user clicks through it, no cap on how many times.
- A signed-in test user's refresh token expires after 7 days and has to sign in again. This is fine for development; fix it before wider release (next section).

## 7. Before public release: publish, then verify

Two separate steps, do them in order:

1. **Publish to production** (OAuth consent screen → **Publish app**). This removes the 7-day token expiry. The 100-user cap and the unverified warning both remain until verification completes — so this step alone is enough for an initial small release to friends or a beta group.
2. **Submit for verification** once the README, a privacy policy page, and a short screen recording of the OAuth flow exist (Google asks for exactly this for a sensitive-scope app). Typical turnaround is days to a couple of weeks. Once approved, the 100-user cap and the warning both go away for everyone.

`omagenda doctor` should report the client's current publishing status by calling `tokeninfo` against a stored token, so contributors don't have to guess why sign-in behaves differently on their machine.

Sources checked 2026-09-07: [Google Cloud Console Help — Manage App Audience](https://support.google.com/cloud/answer/15549945), [Unverified apps](https://support.google.com/cloud/answer/7454865), [When verification is not needed](https://support.google.com/cloud/answer/13464323), [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification), [OAuth 2.0 for Desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app).

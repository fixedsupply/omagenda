<!-- Draft only — the maintainer submits this. Paste from “### Repository URL” below. -->

### Repository URL

https://github.com/fixedsupply/omagenda

### Category

Productivity

### Tags

bar, quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

Needs Omarchy 4.0.x and the Python packages in the README's install line (python-icalendar, python-dateutil, python-recurring-ical-events, libsecret; inotify-tools recommended). iCloud/CalDAV accounts also need pimsync.

Network and permissions: the plugin talks only to the calendar servers the user connects (Google Calendar API, iCloud/CalDAV). There is no Omagenda server and no telemetry. Credentials go in the system keyring via secret-tool. Google uses a desktop OAuth client (loopback redirect) with calendar.events + calendar.calendarlist.readonly. Google's data-access verification was submitted on 2026-09-22 and is under review, so until it is approved Google users see the "unverified app" screen once at sign-in.

The CLI is linked into ~/.local/bin by hand (README step 2). Omagenda writes only its own files: ~/.config/omagenda, ~/.local/state/omagenda, ~/.local/share/calendars, and one ~/.config/pimsync/omagenda-<account>.scfg per iCloud/CalDAV account. Keybinding and menu snippets are opt-in and documented; they are not installed automatically.

### Submission checklist

- [x] The repository is public and contains installation and removal instructions.
- [x] I have documented the plugin license and any external dependencies.
- [x] I confirm that I own or have permission to submit this plugin and its preview assets.
- [x] The plugin does not overwrite user configuration without explicit consent.
- [x] I understand that approval is for listing and is not a security review.

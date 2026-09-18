# Publishing checklist

Drafts for the two listings. Both are submitted by the maintainer; this
file is here so the wording does not have to be reinvented each time.

Do not submit until the [reviewer acceptance checks](reviewer-checklist.md)
are recorded for the candidate commit.

## Before submitting

- [x] `omarchy plugin validate .` is clean
- [x] Both suites pass (`python tools/test-isolated.py`,
      `node --test 'tests/**/*.test.js'`)
- [ ] `preview.png` and every screenshot contain invented data only,
      regenerated from `tools/demo-vdir.py`
- [x] Repository version and changelog prepared for v0.2.1
- [x] Offline clone checks passed on `9b3e3e1` (see STATUS.md)
- [x] Screenshots regenerated for v0.2.0 (Claude): `preview.png`,
      `docs/screenshots/panel.png` and `docs/screenshots/quick-add.png` from
      `tools/demo-vdir.py`; the outdated Tokyo Night image was removed
- [x] Hosted privacy page update prepared on gh-pages (Claude, local commit
      `8cfcac9`); publish it together with the release push
- [ ] Final go/no-go review for v0.2.1 (PM); no tag or push in this session
- [ ] The version in `manifest.json` matches the git tag
- [x] Fresh-machine install on the PM's Dell, Omarchy 4.0.3-1 (2026-09-16):
      the stale developer symlink first blocked installation and an old CLI
      hid the failure. After removing it, install, centre-section enablement,
      watcher and sync worked; doctor was clean. See [STATUS.md](../STATUS.md).
      This v0.2.0 result does not establish v0.2.1 upgrade acceptance.

## Marketplace submission

The marketplace is at `plugins.omarchy.org`. Do not use the old form process.
The maintainer submits a GitHub issue after review:

```bash
gh issue create \
  --repo omacom/omarchy-plugin-marketplace \
  --title "[Plugin]: Omagenda" \
  --body-file docs/marketplace-submission.md
```

`docs/marketplace-submission.md` is ready to pass directly as the body file.
Its first line is an HTML draft marker and does not appear in the issue; the
issue body starts at `### Repository URL`. The headings must remain in this
exact order: Repository URL, Category, Tags, Suggest a missing tag, Maintainer
notes, Submission checklist. Review every statement with the maintainer before
submitting; all five checklist items must be true and checked.

The category is `Productivity`. It is a case-sensitive marketplace value;
`Time / Productivity` is not valid. The tags are `bar` and `quickshell`.
The marketplace allows one to three tags from its fixed list.

The marketplace checks that the repository is public, has a root
`manifest.json`, has a root README with installation and removal steps, has a
root license, uses a unique plugin ID outside `omarchy.*`, and optionally has
a root `preview.png`. This repository satisfies those with `manifest.json`,
this README, `LICENSE`, `fixedsupply.omagenda`, and `preview.png`.

After submission, the bot posts validation and an Automated Security Baseline
result on the issue. A maintainer must apply `approved-and-verified` before
the listing appears. Listing is not a security review.

## Listing copy

**Name:** Omagenda

**Tagline:** Type a sentence, get an event. What's next, always in the bar.

**Category:** Productivity

**Tags:** bar, quickshell

**Description:**

> Omagenda puts your next event in the Omarchy bar and your whole agenda
> one click behind it, and lets you add events by typing them the way you
> would say them — "lunch with Sam tomorrow at 1pm at Cafe Torino".
>
> It takes the two ideas worth taking from Fantastical's original
> menu-bar app: a small agenda you can summon, and natural-language entry
> with a live interpretation preview and a native text field.
>
> Events are plain .ics files in a vdir you own, so khal and anything
> else that speaks vdir sees the same data. Google syncs through a
> built-in bridge; iCloud and any other CalDAV server sync through
> pimsync, configured for you. Credentials use the system keyring, with a private-file fallback.
> Colours come from your theme rather than from us.
>
> It is not a calendar window and does not want to be one — if you use
> renCal or OmaCal for the month grid, keep them.

**Screenshots:** `preview.png`,
`docs/screenshots/panel.png`, `docs/screenshots/quick-add.png`

## awesome-omarchy

This is blocked for now. The target is
[`aorumbayev/awesome-omarchy`](https://github.com/aorumbayev/awesome-omarchy),
whose CI runs `scripts/check-min-stars.py` and requires five or more GitHub
stars for new listings. `fixedsupply/omagenda` currently has 0, so a pull
request would fail today. Do not open one until the threshold is met.

When eligible, add this in the `## Plugins` section, alphabetically by
listing name. The required format uses one hyphen between the link and a
description ending with a full stop:

```markdown
- [Omagenda](https://github.com/fixedsupply/omagenda) - Bar pill, agenda panel, and natural-language Quick Add for calendars you own.
```

The list already has [Calendar](https://github.com/tmn73/omarchy-calendar),
described as “Next Google Calendar event in the Omarchy bar with one-click
meeting join.” Keep Omagenda's wording distinct: it adds a full agenda panel,
natural-language entry, and local vdir ownership rather than echoing that
next-event description.

## Not affiliated with Flexibits

Fantastical is a Flexibits product. Both drafts above mention it once,
descriptively, to say where the idea came from. Do not use it in the
name, the tagline, the plugin id, or the keywords, and do not reuse any
Flexibits icon, screenshot, or copy.


The PM decides when to push and submits both listings. Repository preparation
must not create the tag or publish the branch. The offline clone check is
not the fresh-machine install check above.

Canonical links: [homepage](https://fixedsupply.dev/omagenda/),
[privacy](https://fixedsupply.dev/omagenda/privacy/),
[terms](https://fixedsupply.dev/omagenda/terms/). The hosted privacy page update
belongs to Claude's separate gh-pages handoff.

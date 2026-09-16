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
- [x] Repository version and changelog prepared for v0.2.0
- [x] Offline clone checks passed on `9b3e3e1` (see STATUS.md)
- [x] Screenshots regenerated for v0.2.0 (Claude): `preview.png`,
      `docs/screenshots/panel.png` and `docs/screenshots/quick-add.png` from
      `tools/demo-vdir.py`; the outdated Tokyo Night image was removed
- [x] Hosted privacy page update prepared on gh-pages (Claude, local commit
      `8cfcac9`); publish it together with the release push
- [ ] Final go/no-go review and annotated v0.2.0 tag (Claude)
- [ ] The version in `manifest.json` matches the git tag
- [ ] A fresh-machine run of the README's install block actually works

## omarchyplugins.com

**Name:** Omagenda

**Tagline:** Type a sentence, get an event. What's next, always in the bar.

**Category:** Time / Productivity

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

A single list entry, in the repository's existing format:

```markdown
- [Omagenda](https://github.com/fixedsupply/omagenda) — Bar pill with your next event, an agenda panel, and natural-language Quick Add. Writes plain .ics to a vdir; syncs Google, iCloud, and CalDAV.
```

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

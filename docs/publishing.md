# Publishing checklist

Drafts for the two listings. Both are submitted by the maintainer; this
file is here so the wording does not have to be reinvented each time.

## Before submitting

- [ ] `omarchy plugin validate .` is clean
- [ ] Both suites pass (`python -m unittest discover -s tests`,
      `node --test 'tests/**/*.test.js'`)
- [ ] `preview.png` and every screenshot contain invented data only,
      regenerated from `tools/demo-vdir.py`
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
> that shows you what it understood before you commit. Recognised
> fragments light up as you type, and anything genuinely ambiguous is
> flagged rather than guessed at.
>
> Events are plain .ics files in a vdir you own, so khal and anything
> else that speaks vdir sees the same data. Google syncs through a
> built-in bridge; iCloud and any other CalDAV server sync through
> pimsync, configured for you. Credentials live in your system keyring.
> Colours come from your theme rather than from us.
>
> It is not a calendar window and does not want to be one — if you use
> renCal or OmaCal for the month grid, keep them.

**Screenshots:** `preview.png`, `docs/screenshots/quick-add.png`,
`docs/screenshots/panel-tokyo-night.png`

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

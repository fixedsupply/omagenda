# Working agreement for implementing agents

You are implementing Omagenda, an Omarchy shell plugin specified in `PLAN.md` (product, design, scope) and `ARCHITECTURE.md` (contracts). The product manager is Calvin Symes; design decisions already made in those two files are settled. Raise a question only when the documents are silent or contradictory, and batch questions at the end of a phase.

## Budget rules (non-negotiable)

The whole project has roughly USD 75 of model credit, and the plan already exceeds it if every phase runs to the top of its envelope (`PLAN.md` §9). Sessions cost input tokens every turn, so:

1. **One phase per session.** Finish a phase, commit, stop. Do not start the next phase in the same context.
2. **Read only the read list for your phase** (below). Do not explore `/usr/share/omarchy/shell` beyond it. Do not `cat` files larger than 300 lines whole; read the ranges you need.
3. **Logic goes where tests are cheap**: Python and `Model.js`. QML files stay thin and declarative.
4. **Run tests, not the shell, to iterate.** Launch the shell path (`rescanPlugins`, screenshot) only at checkpoints, not after every edit.
5. **No new dependencies** beyond the Arch packages named in `ARCHITECTURE.md`. No npm packages. No build step.
6. **Commit small and often** with messages that say what changed and why. Never rewrite history.
7. If a phase is running over its envelope, stop, commit what works, and write `STATUS.md` with what remains. Half a working phase committed beats a finished phase nobody can afford.

## The maintainer's own calendar is not test data

This repo is public and is meant for other people to install. The
maintainer's machine has a real calendar on it with real appointments,
including medical ones.

- Never commit a screenshot of the live panel, the bar, or a full desktop.
  Screenshots in `docs/screenshots/` are generated from invented demo
  events, cropped to the plugin's own bounds, and nothing else may be in
  frame.
- Never paste real event titles, locations, attendees, or calendar URLs
  into commit messages, docs, tests, or fixtures.
- Never put a real email address in the repo. Tests use
  `you@example.com`.
- A secret iCal URL is a credential: it is prompted for, never passed as
  an argument, and `account list` masks it.
- To check behaviour against a large real calendar, measure it and report
  the numbers -- do not copy its contents anywhere.

## Style rules

- Match the first-party shell code in structure, naming, and comment voice. Comments explain *why*, in full sentences, like `plugins/panels/clock/Panel.qml`.
- No colors, sizes, or fonts that are not `Color.*` or `Style.*` tokens.
- English UI text, sentence case, no exclamation marks, no emoji in the UI.
- Python: standard library first, type hints, no classes where a function will do, `pathlib` for paths, `zoneinfo` for zones.
- Every CLI command supports `--json` and exits non-zero with a one-line error on failure.

## Development environment

The target machine installs `python-icalendar`, `python-dateutil`, and
`python-recurring-ical-events` as Arch packages (per `ARCHITECTURE.md` §1),
which needs root. A development session without sudo access can instead run:

```
python3 -m venv ~/.venvs/omagenda
source ~/.venvs/omagenda/bin/activate
pip install icalendar python-dateutil recurring-ical-events
```

**Create the venv outside the repo**, not as `.venv/` inside it, even
though that would be gitignored: this repo doubles as the actual plugin
folder (it gets symlinked into `~/.config/omarchy/plugins/`), and
`omarchy plugin validate` rejects the whole plugin if it finds *any*
symlink anywhere underneath it -- which a venv always has (`lib64 -> lib`).
Activate the external venv before running `python -m unittest` or the CLI
directly; nothing about the shipped code depends on a venv existing.

## Reliability development and tests

Work in an isolated checkout when the normal checkout is the running plugin.
Run `python tools/test-isolated.py` for Python tests; it redirects config,
calendar, state and credential defaults into temporary directories. Never
change the installed source to test watcher invalidation. The watcher test
uses a temporary module.

Native text-field interaction tests run with:

```
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=basic QT_QUICK_BACKEND=software /usr/lib/qt6/bin/qmltestrunner -input tests/qml
```

Mocked provider tests do not establish live-provider acceptance. Record
remaining checks in `docs/reviewer-checklist.md`. Multi-component series
writes and inline syntax highlighting are currently deferred; keep native
text editing and the interpretation preview functional.

## Phase 0 — scaffold and corpus

Read list: `PLAN.md`, `ARCHITECTURE.md`, `/usr/share/omarchy/shell/README.md` (manifest section only), `/usr/share/omarchy/shell/plugins/README.md`.

Deliver:
- Repo layout from `ARCHITECTURE.md` §1 with empty modules and a passing (trivial) test run.
- `manifest.json` that passes `omarchy plugin validate .`.
- `omagenda/nl_grammar.md` written out from `ARCHITECTURE.md` §6 with one example per rule.
- `tests/test_parse.py` with a 150-sentence table: sentence, reference date, expected fields. Include the ambiguous cases with their intended resolution and expected warnings. Tests may be skipped (`@unittest.expectedFailure`) until Phase 1.
- `tests/fixtures/vdir/` sample calendars as described in `ARCHITECTURE.md` §9.

Done when: `omarchy plugin validate .` is clean, `python -m unittest` runs, `node --test 'tests/**/*.test.js'` runs (a bare directory throws MODULE_NOT_FOUND on this machine's Node 26), and the corpus reviewer (the PM) has skimmed the sentences.

## Phase 1 — Python core

Read list: `ARCHITECTURE.md` §3–§7 and §9, `omagenda/nl_grammar.md`, `tests/test_parse.py`, the `python-icalendar` and `recurring_ical_events` docs via `python -c "help(...)"` or `pydoc`, not the web.

Deliver, in this order, committing after each:
1. `vdir.py`: discover calendars, read `displayname`/`color`, map colors to theme names, write an event file atomically.
2. `index.py` + `omagenda index` / `agenda` / `next`: recurrence expansion with exceptions, all-day handling, `sourceTz`, conference detection, atomic `agenda.json`.
3. `parse.py` + `omagenda parse`: make the corpus green. Fix the grammar doc when the corpus wins an argument.
4. `omagenda add` with `--dry-run`, and `calendars`, `doctor`.
5. `sync.py`: pimsync / vdirsyncer delegation, ICS subscriptions, optional `omacal events list --json` merge.
6. `omagenda watch`: inotify (via `inotifywait` from `inotify-tools`, or polling every 15 s if the package is missing), reindex on change, alarms through `omarchy-notification-send` with `--exec` Join.

Done when: all Python tests green; `OMAGENDA_VDIR=tests/fixtures/vdir omagenda agenda --json` matches the schema; index of the fixture set runs under 300 ms; `omagenda doctor` on the PM's machine reports correctly.

## Phase 1b — Google bridge and accounts

Read list: `ARCHITECTURE.md` §5, §7, §11; `omagenda/vdir.py` and `omagenda/index.py` as written; Google Calendar API reference pages for `events.list` (sync tokens), `events.insert/patch/delete`, and `calendarList.list` (fetch only those pages, once). The PM supplies the OAuth client id and secret as `OMAGENDA_GOOGLE_CLIENT_ID` / `_SECRET` for development; they are committed into `omagenda/bridges/google.py` once the PM confirms the project's client.

Deliver, committing after each:
1. `accounts.py`: `omagenda account add|list|remove`, keyring via `secret-tool` with the file fallback, pimsync config generation for `icloud` and `caldav` types (verify against the pimsync man page installed locally: `man pimsync.conf`).
2. `bridges/__init__.py` interface and the sync state store.
3. `bridges/google.py`: authorize, list calendars, incremental pull, push with `If-Match`, conflict files.
4. `sync.py` orchestration and `omagenda sync --json` reporting counts per calendar.
5. Tests with recorded JSON fixtures (no network in tests): pull mapping both directions, recurring instances, cancelled events, a 412 conflict, a 410 full-resync.

Done when: `omagenda account add google` on the PM's machine round-trips: an event created by Quick Add appears in Google within one sync, an edit on the phone appears in the panel within one sync, and the conflict path produces a `.conflict.ics` plus a notification. `omagenda account add icloud` produces a pimsync config that syncs the PM's family calendar.

## Phase 2 — Up Next pill and agenda panel

Read list: `ARCHITECTURE.md` §3, §4, §8, §9; then, whole: `/usr/share/omarchy/shell/plugins/panels/weather/BarWidget.qml`, `/usr/share/omarchy/shell/Ui/BarWidget.qml`, `/usr/share/omarchy/shell/Ui/PanelHero.qml`, `/usr/share/omarchy/shell/Ui/PanelSectionHeader.qml`; in ranges as needed: `/usr/share/omarchy/shell/plugins/panels/weather/Panel.qml` (open/close/keys/FileView/Process sections), `/usr/share/omarchy/shell/plugins/panels/clock/Panel.qml` (grid and today marking), `/usr/share/omarchy/shell/plugins/panels/clock/Model.js`, `/usr/share/omarchy/shell/Commons/Style.qml` (property list only), `/usr/share/omarchy/shell/Ui/Panel.qml`, `/usr/share/omarchy/shell/Ui/PopupCard.qml` (header only), `~/.config/omarchy/plugins/njpatel.omapager/Widget.qml` (visibility logic only).

Deliver:
1. `Service.qml`: FileView on `agenda.json`, parsed model exposed as properties, starts `omagenda watch`, IPC target `omagenda`.
2. `Model.js` with tests: countdown text, pill text rules (`leadMinutes`, `alwaysShow`), ticker day layout, agenda grouping, time formatting per `timeFormat`.
3. `BarWidget.qml`: pill, click behaviors, Loader-hosted panel.
4. `Panel.qml`: hero, ticker strip, agenda list, footer, full keyboard map from `PLAN.md` §6.2, `s` triggers sync, `n` summons Quick Add (IPC) with the selected date.
5. A screenshot at each checkpoint via `omarchy capture screenshot` into `docs/screenshots/` for the PM to review.

Done when: the panel opens by click and by `omarchy-shell shell toggle fixedsupply.omagenda`, reflects a change to a fixture `.ics` within two seconds without restart, survives `omarchy theme set` with correct colors, and `journalctl --user _COMM=quickshell` shows no warnings from the plugin.

## Phase 3 — Quick Add overlay

Read list: `ARCHITECTURE.md` §6, §8 (overlay rows); whole: `/usr/share/omarchy/shell/plugins/reminders/ReminderFlow.qml`, `ReminderFlowModel.js`, `manifest.json`; ranges: `/usr/share/omarchy/shell/plugins/emojis/Emojis.qml` (list and filter), `/usr/share/omarchy/shell/Ui/TextField.qml`.

Deliver:
1. `QuickAdd.qml`: card, field, live spans colored from `omagenda parse --json` (debounced), preview row, warnings line, `Enter` / `Shift+Enter` / `Tab` / `Escape` semantics, prefill from payload (`{"date": "2026-09-10", "text": ""}`).
2. Template picker on `/`, templates from `~/.config/omagenda/templates.toml`.
3. Confirmation notification after a write, with the rendered event line.

Done when: typing the ten showcase sentences in `docs/showcase.md` produces the expected files in the fixture vdir, the preview never lags visibly, and the caret behaves correctly with highlighting on.

## Phase 4 — finish and publish

Read list: `PLAN.md` §6.5–§6.7, §8; `README.md` of `~/.config/omarchy/plugins/mohamedmansour.finance` as a model for tone and structure.

Deliver: calendar sets (`1`–`9`, `omagenda set`), `docs/sync-setup.md`, `docs/omarchy-menu.jsonc`, `docs/bindings.lua`, `skill/SKILL.md`, `preview.png`, README with install, screenshots, keybindings, sync recipes, and a "works alongside renCal and OmaCal" section. Tag `v0.1.0`. Draft the listing text for omarchyplugins.com and a PR line for awesome-omarchy; the PM submits both.

## Phase 4b — close out v0.2.0 (three separate sessions)

Written 2026-09-15 after the reliability pass and the recorded Google
acceptance run. Each task below is one session: finish, commit, stop.
Work on a branch cut from `main` in a checkout that is *not*
`~/Projects/omagenda` (that folder is the running plugin). The PM merges
after review. Do not push. Do not rewrite history. Commit messages go
through a file (`git commit -F`), never an inline double-quoted string.

Live provider scripts cannot run inside the Codex sandbox (no network, no
keyring). Print the exact command for the PM to run in a normal terminal,
then read the output they paste back. Never run a syncing watcher against
the real vdir, and never point anything at the real `family` pimsync pair.

### 4b-1 — calendar sets

Read list: `PLAN.md` §6 (the Calendar Sets row and the footer/keys
paragraphs), `ARCHITECTURE.md` (agenda.json `activeSet`, config.toml),
`omagenda/accounts.py` lines 55–80 (config writer already emits a `[sets]`
table), `omagenda/index.py` around `active_set` (line ~172 and ~282),
`bin/omagenda` (`cmd_agenda`, its `--set` flag, `cmd_watch`, the `calendars`
command as a model), `qml/Panel.qml` around line 183 (the `s` key handler),
`qml/Service.qml` (how the panel invokes the CLI), `qml/Model.js`
`footerText`.

Decided design (do not re-open):

- Sets are defined in `config.toml`, not in shell settings, so the CLI works
  without the shell: `[sets]` maps a set name to a list of calendar ids as
  they appear in `omagenda calendars --json` (for example `work = ["google/x@group.calendar.google.com", "personal"]`).
  `ARCHITECTURE.md` currently shows `"sets": {}` under the shell defaults;
  remove that entry and document the config.toml table instead.
- The active set is runtime state, not config: one file,
  `$OMAGENDA_STATE/active-set` (plain text, the set name, absent means all).
  `omagenda set <name>` writes it, `omagenda set --clear` removes it,
  `omagenda set` with no argument prints the active set and the defined
  ones; `--json` on all three. A name that is not defined exits non-zero
  with a one-line error.
- After writing the file, `omagenda set` rebuilds agenda.json immediately
  (reuse the indexer the watcher calls) so the panel updates through its
  existing agenda.json watch. The watcher must also pick up the file on its
  next tick; do not add a second inotify watch for it.
- agenda.json: `activeSet` carries the name; `events` and `calendars` are
  filtered to the set's calendars. An empty or unknown set means all,
  and an unknown one is also reported in `doctor` as a warning.
- Panel: `1`–`9` switch to the Nth defined set in `[sets]` order, `0`
  clears, wired next to the existing `s` handler and going through the CLI
  like `sync` does. The footer already renders `Set: <name>`; leave the
  hint text as specified in `PLAN.md`.
- The per-set Quick Add default calendar from `PLAN.md` is deferred to a
  later task; do not build it.
- Tests: Python for the state file, filtering, the unknown-name error and
  the `--json` shapes; `Model.js` if `footerText` changes. Run
  `python tools/test-isolated.py` and the Node suite.

Also in this session, local housekeeping only: `git worktree remove` the
`omagenda-reliability` worktree and delete the local `reliability-review`
and `integrate-google-timezone` branches (both fully merged). Remote branch
deletion is the PM's command, not yours.

Done when: `omagenda set work` changes the panel within a second on the
PM's machine, `omagenda set --clear` restores everything, and `doctor` is
clean.

### 4b-2 — iCloud acceptance script

Read list: `tools/google-acceptance.py` whole (232 lines; it is the
template), `omagenda/sync.py` lines 55–110 (the pimsync path),
`omagenda/accounts.py` `generate_pimsync_config` and
`pimsync_config_path`, `docs/reviewer-checklist.md`, and `man 5 pimsync.conf`
plus `man 1 pimsync` on this machine (pimsync is installed at
`/usr/bin/pimsync`; the PM's real config at
`~/.config/pimsync/omagenda-family.scfg` is a working example — read it,
never modify it, never sync it).

Deliver `tools/icloud-acceptance.py --run-live`, mirroring the Google
script's shape and safeguards:

- Requires exactly one configured `icloud` account. Read its password the
  way `sync.py` does (`secret-tool lookup service omagenda account <id>`);
  never print it, never write it to disk, pass it to pimsync through the
  `cmd` form the real config already uses.
- Discover the calendar home over CalDAV (`PROPFIND` for
  `current-user-principal`, then `calendar-home-set`) and create one
  disposable calendar with `MKCALENDAR` under a uuid path named
  `Omagenda acceptance <hex>`. Do not retry the create. Write the recovery
  receipt before and after, as the Google script does.
- Everything else isolated: temporary `OMAGENDA_CONFIG`, `OMAGENDA_VDIR`,
  `OMAGENDA_STATE`, and a temporary pimsync `.scfg` whose pair is
  restricted to the disposable collection only and whose `status_path`
  is inside the temp folder. Verify the collection-restriction syntax
  against `pimsync.conf(5)` before relying on it.
- Scenarios, each a `check(...)`: CLI `add` reaches iCloud exactly once
  (verify with a CalDAV `GET` or calendar-query `REPORT`, not by trusting
  pimsync's exit code); a remote time change downloads; a local title
  edit uploads; a remote recurring series with one moved and one cancelled
  occurrence downloads as one file with `EXDATE` and a `RECURRENCE-ID`
  component; local deletion reaches iCloud; remote deletion removes the
  local file; and the watcher round trip with a two-second interval, as in
  the Google script. Conflicts are pimsync's business under
  `conflict_resolution keep b`; check only that a simultaneous edit ends
  with the remote title on both sides and no error.
- `DELETE` the disposable calendar in `finally`; keep the temp folder and
  print the receipt path if that fails.

Then hand the PM the command, read the pasted output, and record the
result in `docs/reviewer-checklist.md` and `STATUS.md` exactly as the
Google run was recorded: candidate commit, date, which checks passed, and
what the run does not establish. If it fails, record the failure and the
stage; do not patch the script until it passes and call that a pass.

Done when: the recorded run lists every check passing and the calendar
deleted, on a commit that is on the PM's branch.

### 4b-3 — release prep for v0.2.0

Read list: `docs/publishing.md`, `STATUS.md`, `manifest.json`, `README.md`
(install and screenshot sections only), `tools/demo-vdir.py` docstring,
and the commit message of `93b5fcf` (`git show -s 93b5fcf`), which records
the screenshot recipe that works.

Deliver, only after 4b-1 and 4b-2 are merged:

- `manifest.json` version `0.2.0`, and any version string the README or
  docs repeat.
- Regenerate `docs/screenshots/quick-add.png` from demo data: it still
  shows the previous simulated text field (`docs/publishing.md` says so).
  Run `omagenda calendars --set-default personal` on the demo vdir first so
  no real calendar id appears in the destination line. Crop to the
  plugin's own bounds. Nothing real may be in frame; compare against the
  rule in "The maintainer's own calendar is not test data".
- `STATUS.md`: rewrite the summary for the candidate. The line saying
  iCloud setup is absent on this machine is stale (an `icloud` account
  and pimsync have been set up since); replace it with what the 4b-2 run
  recorded. List what is still unverified: fresh-machine install, full
  overlay, reboot and source-update behaviour. The PM does the
  fresh-install run on a second machine and submits the listings.
- Tick the items in `docs/publishing.md` that are now true; leave the
  fresh-machine item for the PM.
- Create an annotated tag `v0.2.0` on the final commit. Do not push it.

Done when: `omarchy plugin validate .` is clean, both suites pass, the
new screenshot contains invented data only, and `git tag -n1 v0.2.0`
shows the tag on the reviewed commit.

## Phase 5 — Microsoft bridge

Read list: `ARCHITECTURE.md` §11, `omagenda/bridges/google.py` and its tests, Microsoft Graph reference for `calendarView/delta`, `events` create/update/delete, and the recurrence object (fetch once). The PM supplies the Entra app (client) id.

Deliver: `bridges/microsoft.py` on the same interface, Windows-to-IANA zone table, recurrence mapping with read-only fallback for unsupported patterns, recorded-fixture tests mirroring the Google suite, `omagenda account add microsoft`.

Done when: the Google acceptance test passes against an Outlook.com account. This phase is the first to defer if credits run short.

## Definition of done for the whole project

`omarchy plugin add <url> --enable --yes` on a fresh Omarchy 4.0.x machine, followed by `omarchy pkg add` of the named packages and the README's sync recipe, yields a working pill, panel, and Quick Add within ten minutes, with no file edited outside the user's own config.

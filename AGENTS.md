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

## Style rules

- Match the first-party shell code in structure, naming, and comment voice. Comments explain *why*, in full sentences, like `plugins/panels/clock/Panel.qml`.
- No colors, sizes, or fonts that are not `Color.*` or `Style.*` tokens.
- English UI text, sentence case, no exclamation marks, no emoji in the UI.
- Python: standard library first, type hints, no classes where a function will do, `pathlib` for paths, `zoneinfo` for zones.
- Every CLI command supports `--json` and exits non-zero with a one-line error on failure.

## Phase 0 — scaffold and corpus

Read list: `PLAN.md`, `ARCHITECTURE.md`, `/usr/share/omarchy/shell/README.md` (manifest section only), `/usr/share/omarchy/shell/plugins/README.md`.

Deliver:
- Repo layout from `ARCHITECTURE.md` §1 with empty modules and a passing (trivial) test run.
- `manifest.json` that passes `omarchy plugin validate .`.
- `omagenda/nl_grammar.md` written out from `ARCHITECTURE.md` §6 with one example per rule.
- `tests/test_parse.py` with a 150-sentence table: sentence, reference date, expected fields. Include the ambiguous cases with their intended resolution and expected warnings. Tests may be skipped (`@unittest.expectedFailure`) until Phase 1.
- `tests/fixtures/vdir/` sample calendars as described in `ARCHITECTURE.md` §9.

Done when: `omarchy plugin validate .` is clean, `python -m unittest` runs, `node --test tests/` runs, and the corpus reviewer (the PM) has skimmed the sentences.

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

## Phase 2 — Up Next pill and DayTicker panel

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

## Phase 5 — Microsoft bridge

Read list: `ARCHITECTURE.md` §11, `omagenda/bridges/google.py` and its tests, Microsoft Graph reference for `calendarView/delta`, `events` create/update/delete, and the recurrence object (fetch once). The PM supplies the Entra app (client) id.

Deliver: `bridges/microsoft.py` on the same interface, Windows-to-IANA zone table, recurrence mapping with read-only fallback for unsupported patterns, recorded-fixture tests mirroring the Google suite, `omagenda account add microsoft`.

Done when: the Google acceptance test passes against an Outlook.com account. This phase is the first to defer if credits run short.

## Definition of done for the whole project

`omarchy plugin add <url> --enable --yes` on a fresh Omarchy 4.0.x machine, followed by `omarchy pkg add` of the named packages and the README's sync recipe, yields a working pill, panel, and Quick Add within ten minutes, with no file edited outside the user's own config.

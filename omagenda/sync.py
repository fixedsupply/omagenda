"""Sync local vdir calendars with Google, CalDAV and ICS subscriptions."""
from __future__ import annotations

import hashlib
import concurrent.futures
import contextlib
import json
import os
import re
import shutil
import time
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from omagenda.bridges import AuthExpiredError
from omagenda.doctor import read_config
from omagenda.vdir import resolve_vdir_root

BRIDGE_MODULES = {"google": "omagenda.bridges.google"}


def _sync_ics(account: dict, vdir_root: Path) -> dict:
    url = account.get("url")
    if not url:
        return {"ok": False, "detail": "no url configured"}
    folder = vdir_root / account["id"]
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "detail": f"fetch failed: {exc}"}

    # The folder is left read-only so discover_calendars reports the
    # subscription as such, which means every later refresh has to open
    # the write bit again first. Atomic replacement needs to create a
    # temporary file in the same directory, even for an existing event.
    folder.chmod(0o755)
    try:
        (folder / "displayname").write_text(account.get("id", url))
        if account.get("color"):
            (folder / "color").write_text(account["color"])
        _overwrite_ics(folder / "subscription.ics", data)
    except OSError as exc:
        return {"ok": False, "detail": f"couldn't write into {folder}: {exc}"}
    finally:
        folder.chmod(0o555)  # readOnly, per vdir.discover_calendars' os.access check
    return {"ok": True, "detail": f"fetched {len(data)} bytes into {folder}"}


def _sync_caldav(account: dict) -> dict:
    from omagenda.accounts import ensure_conflict_resolver, pimsync_config_path

    tool = account.get("sync", "pimsync")
    binary = shutil.which(tool)
    if not binary:
        return {"ok": False, "detail": f"{tool} not found on PATH (omarchy pkg add {tool})"}

    config_path = pimsync_config_path(account["id"])
    if not config_path.exists():
        return {"ok": False, "detail": f"no pimsync config at {config_path}; run 'omagenda account add' again"}

    ensure_conflict_resolver(account["id"])
    try:
        # Verbatim against pimsync.conf(5) and pimsync(1): `pimsync -c
        # <configfile> sync [pair...]`. accounts.generate_pimsync_config
        # names the pair after the account id (sanitized), which is also
        # the only pair this config file defines.
        from omagenda.accounts import _safe_pair_name

        def pimsync(command: str, **extra) -> subprocess.CompletedProcess:
            return subprocess.run(
                [binary, "-c", str(config_path), command, _safe_pair_name(account["id"])],
                capture_output=True, text=True, timeout=120, **extra,
            )

        result = pimsync("sync")
        items, properties = pimsync_conflicts(result.stdout)
        if items or properties:
            # `sync` never applies conflict_resolution itself; it only runs
            # under `resolve-conflicts`, which prompts for every conflict.
            # Its output is discarded because a prompt that is never
            # answered repeats without end.
            subprocess.run(
                [binary, "-c", str(config_path), "resolve-conflicts", _safe_pair_name(account["id"])],
                input=pimsync_resolve_answers(items, properties), text=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            )
            result = pimsync("sync")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"{tool} failed to run: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "detail": f"{tool} exited {result.returncode}: {result.stderr.strip()[:200]}"}
    if items or properties:
        kept = []
        if items:
            kept.append(f"{items} conflicting event{'s' if items != 1 else ''} (yours saved)")
        if properties:
            kept.append(f"{properties} calendar setting{'s' if properties != 1 else ''}")
        return {"ok": True, "conflicts": items, "propertyConflicts": properties,
                "detail": f"{tool} sync ok; kept the server version of " + " and ".join(kept)}
    return {"ok": True, "detail": f"{tool} sync ok"}


def _overwrite_ics(path: Path, content: bytes) -> None:
    """Unlike vdir.write_event_ics (create-only, for locally-authored
    events), a sync pull legitimately replaces a file's whole content."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".sync-", suffix=".ics.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _notify_conflict(uid: str, calendar_name: str, saved_as: str | None = None) -> None:
    binary = shutil.which("omarchy-notification-send") or "/usr/share/omarchy/bin/omarchy-notification-send"
    subprocess.run([binary, "-g", "󰢌", "Sync conflict",
                    f"An edit to an event in {calendar_name} conflicted with a server change; "
                    f"your version was saved as {saved_as or uid + '.conflict.ics'}"], check=False)


_FOLD = re.compile(rb"\r?\n[ \t]")
_UID_VALUE = re.compile(rb"^UID:(.*?)\r?$", re.MULTILINE)


def preserve_pimsync_conflict(account_id: str, local: Path, remote: Path, state_dir=None) -> Path:
    """pimsync's conflict resolver (accounts.conflict_resolution_directive).

    `local` and `remote` are pimsync's temporary copies of the two versions,
    not files in the vdir. The server version wins, as for Google: the local
    version is saved first, then `local` is made identical to `remote`,
    which is what tells pimsync the conflict is resolved. The copy is kept in
    the state folder rather than beside the calendar, because pimsync would
    upload any .ics file placed in the vdir as a duplicate event."""
    from omagenda.index import resolve_state_dir

    content = local.read_bytes()
    match = _UID_VALUE.search(_FOLD.sub(b"", content))
    uid = match.group(1).decode("utf-8", "replace").strip() if match else ""
    safe_uid = re.sub(r"[^A-Za-z0-9@._-]", "_", uid)[:200] or "event"
    safe_account = re.sub(r"[^A-Za-z0-9@._-]", "_", account_id) or "account"
    base = Path(state_dir) if state_dir is not None else resolve_state_dir()
    folder = base / "conflicts" / safe_account
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    # Do not replace a previous unresolved conflict with a newer one.
    path = folder / f"{safe_uid}.conflict.ics"
    if path.exists() and path.read_bytes() != content:
        path = folder / f"{safe_uid}.{hashlib.sha256(content).hexdigest()[:12]}.conflict.ics"
    _overwrite_ics(path, content)
    local.write_bytes(remote.read_bytes())
    try:
        _notify_conflict(uid or safe_uid, account_id, saved_as=str(path))
    except OSError:
        pass  # Notification availability must not undo preservation.
    return path


_PIMSYNC_ITEM_CONFLICT = re.compile(r"^-> Item .*: conflict\b", re.MULTILINE)
_PIMSYNC_PROPERTY_CONFLICT = re.compile(r"^-> Property .*: conflict\b", re.MULTILINE)


def pimsync_conflicts(stdout: str) -> tuple[int, int]:
    """(event conflicts, collection property conflicts) listed by `pimsync sync`.

    Its "N conflicts detected" total mixes the two, and a property conflict
    alone (a calendar renamed or recoloured on both sides) still exits 0."""
    text = stdout or ""
    return len(_PIMSYNC_ITEM_CONFLICT.findall(text)), len(_PIMSYNC_PROPERTY_CONFLICT.findall(text))


def pimsync_resolve_answers(items: int, properties: int) -> str:
    """Answers for `pimsync resolve-conflicts`, which asks per conflict.

    Items: "Resolve it manually? (Y)es, (N)o, or (Q)uit" -> y runs the `cmd`
    resolver. Properties: "Keep (A), (B), (E)dit, (S)kip, or (Q)uit" -> b,
    the server, which is Omagenda's policy. Neither prompt accepts the other's
    answer and each simply asks again, so alternating y and b answers every
    prompt in any order. The supply is finite on purpose: at end of input a
    property prompt repeats forever, so it must never run out early, and the
    caller's timeout is the backstop."""
    return "y\nb\n" * (2 * (items + properties) + 4)


_UID_LINE = re.compile(rb"^UID:.*(?:\r?\n[ \t].*)*\r?\n", re.MULTILINE)


def _rewrite_uid(content: bytes, new_uid: str) -> bytes:
    """Replace every UID line, folded continuations included. A series and
    its overrides all share one UID, so replacing them all is what keeps
    the file coherent; a file with no UID at all is left alone rather
    than guessed at."""
    replaced, count = _UID_LINE.subn(f"UID:{new_uid}\r\n".encode(), content)
    return replaced if count else content


def _adopt_remote_uid(file_path: Path, content: bytes, remote_id: str, state_dir: Path | None = None):
    """Take on the id the remote just assigned.

    Google gives an event it has not seen before its own id, and every
    later pull keys that event by that id -- not by the UID Omagenda
    invented and sent. Leaving the local file under the invented UID
    therefore means the next sync writes the server's copy alongside it,
    and the appointment shows up twice, forever, with no way for the user
    to tell which one is real.

    So the moment a create succeeds, the local file takes the remote's
    identity: renamed to the remote id and rewritten to carry it as the
    UID. The next pull then atomically replaces that same file.
    """
    if not remote_id or remote_id == file_path.stem:
        return file_path.stem, file_path, content
    new_path = file_path.with_name(f"{remote_id}.ics")
    new_content = _rewrite_uid(content, remote_id)
    _overwrite_ics(new_path, new_content)
    if new_path != file_path:
        from omagenda.adopted import record

        record(file_path, new_path, state_dir)
        file_path.unlink(missing_ok=True)
    return remote_id, new_path, new_content


def _write_vdir_metadata(calendar_path: Path, calendar) -> None:
    """The vdir sidecar files. Without these a bridge calendar shows up in
    the panel under its raw remote id -- readable for a local folder, but
    "en.usa#holiday@group.v.calendar.google.com" for a Google one --
    and every calendar looks writable, so Quick Add offers destinations
    the remote will refuse."""
    (calendar_path / "displayname").write_text(calendar.name, encoding="utf-8")
    color = getattr(calendar, "color", None)
    if color:
        (calendar_path / "color").write_text(color, encoding="utf-8")


def _sync_one_calendar(bridge, account: dict, calendar, calendar_path: Path, state_dir=None) -> dict:
    try:
        return _sync_calendar_contents(bridge, account, calendar, calendar_path, state_dir)
    finally:
        if not calendar.writable and calendar_path.exists():
            calendar_path.chmod(0o555)


def _sync_calendar_contents(bridge, account: dict, calendar, calendar_path: Path, state_dir=None) -> dict:
    """The shared pull -> detect-local-changes -> push -> record algorithm
    (ARCHITECTURE.md §11), driven through the Bridge protocol so it works
    the same way for any bridge, not just Google."""
    from omagenda.bridges import ConflictError, RemoteRef, SyncState, state_path_for

    calendar_path.mkdir(parents=True, exist_ok=True)
    # A calendar the remote won't accept writes to is left mode 0555, the
    # same marker _sync_ics uses and the one discover_calendars tests for
    # -- so the write bit has to be reopened before every sync, or the
    # second sync of a read-only calendar fails on its own marker.
    calendar_path.chmod(0o755)
    _write_vdir_metadata(calendar_path, calendar)
    state_path = state_path_for(account["id"], calendar.id, state_dir)
    state = SyncState.load(state_path)
    counts = {"pulled": 0, "createdRemote": 0, "createdLocal": 0, "updated": 0, "deletedRemote": 0,
              "deletedLocal": 0, "conflicts": 0}

    # Download first, then snapshot local files before applying the response.
    # An edit made while a slow network request is running must be included.
    pull_result = bridge.pull(account, calendar, state.cursor)

    # Both captured before the pull writes anything, because the pull is
    # what destroys the evidence. A delete made shortly after creating an
    # event used to vanish: the create was pushed, Google reported it back
    # as changed on the next pull, the pull rewrote the file the user had
    # just deleted, and the deletion -- now invisible on disk -- was never
    # sent. The event came back from the dead with no error anywhere.
    refs_before = {uid: dict(entry) for uid, entry in state.items.items()}
    known_before = set(state.items)
    on_disk_before = {f.stem for f in calendar_path.glob("*.ics")
                      if not f.name.endswith(".conflict.ics")}

    local_edits = {}
    for uid in known_before & on_disk_before:
        content = (calendar_path / f"{uid}.ics").read_bytes()
        if hashlib.sha256(content).hexdigest() != state.items[uid]["localHash"]:
            local_edits[uid] = content

    def preserve(uid, content):
        # Do not replace a previous unresolved conflict with a newer one.
        suffix = hashlib.sha256(content).hexdigest()[:12]
        path = calendar_path / f"{uid}.conflict.ics"
        if path.exists() and path.read_bytes() != content:
            path = calendar_path / f"{uid}.{suffix}.conflict.ics"
        _overwrite_ics(path, content)
        counts["conflicts"] += 1
        try:
            _notify_conflict(uid, calendar.name)
        except OSError:
            pass  # Notification availability must not undo preservation.

    # 1. Apply the downloaded changes.
    for change in pull_result.changed:
        digest = hashlib.sha256(change.ics_bytes).hexdigest()
        entry = state.items.get(change.uid)
        # An echo, not a change: the server handing back the very version we
        # last pushed or pulled (same etag), in its own formatting. After a
        # create, Google's next pull always includes the new event, and its
        # bytes never match the file Omagenda wrote. Treating that as a remote
        # change turned a quick edit of a new event into a "conflict", reverted
        # it and filed the edit as a conflict copy. A real remote change always
        # carries a new etag, so it still reaches the conflict handling below.
        # The rule applies only when there is a local edit to protect; without
        # one the file is refreshed to the server's copy exactly as before, and
        # a file deleted since the last sync is never in local_edits, so the
        # snapshot-based deletion further down still sees it. Step 2 below then
        # pushes the edit with the etag this echo just confirmed.
        if (change.uid in local_edits and entry is not None and change.ref.etag
                and entry.get("etag") == change.ref.etag):
            counts["unchanged"] = counts.get("unchanged", 0) + 1
            continue
        if change.uid in local_edits and entry is not None and entry["localHash"] != digest:
            preserve(change.uid, local_edits.pop(change.uid))
        # A "changed" event whose bytes are what we already hold is not a
        # change, and rewriting it costs more than the write: every touched
        # file wakes the watcher, invalidates that file's index-cache entry,
        # and buys a re-parse of a file that did not move.
        #
        # This is not a rare case. Google answers 410 Gone for some
        # subscribed calendars' sync tokens every time -- its US holidays
        # calendar does -- handing back a token it will reject again on the
        # next call, so every sync is a full resync of a few hundred events
        # that have not changed since the calendar was published. Left
        # alone that rewrote 317 identical files every five minutes.
        if entry is not None and entry.get("localHash") == digest \
                and (calendar_path / f"{change.uid}.ics").exists():
            counts["unchanged"] = counts.get("unchanged", 0) + 1
        else:
            _overwrite_ics(calendar_path / f"{change.uid}.ics", change.ics_bytes)
            counts["pulled"] += 1
        state.items[change.uid] = {
            "remoteId": change.ref.remote_id,
            "etag": change.ref.etag,
            "localHash": digest,
        }
    deleted = set(pull_result.deleted_uids)
    if pull_result.full_resync:
        deleted.update(known_before - {change.uid for change in pull_result.changed})
    for uid in deleted:
        if uid in local_edits:
            preserve(uid, local_edits.pop(uid))
        (calendar_path / f"{uid}.ics").unlink(missing_ok=True)
        state.items.pop(uid, None)
        counts["deletedRemote"] += 1
    state.cursor = pull_result.next_cursor
    if not calendar.writable:
        state.save(state_path)
        counts["ok"] = True
        return counts

    # 2. Detect local changes: compare every file on disk against the
    # hash recorded the last time this uid was pulled or pushed. A file
    # just written by the pull above already has a matching hash, so it
    # correctly falls through as "unchanged" here.
    on_disk = {f.stem: f for f in calendar_path.glob("*.ics") if not f.name.endswith(".conflict.ics")}

    # Renames from _adopt_remote_uid land here rather than in on_disk,
    # which is being iterated; they are merged in before step 3, so a
    # just-adopted uid is not mistaken for a local deletion.
    adopted: dict[str, Path] = {}

    for uid, file_path in list(on_disk.items()):
        content = file_path.read_bytes()
        local_hash = hashlib.sha256(content).hexdigest()
        entry = state.items.get(uid)

        if entry is None:
            try:
                ref = bridge.push_create(account, calendar, content)
            except Exception as exc:  # noqa: BLE001 -- one bad event must not stop the others
                counts.setdefault("errors", []).append(f"create {uid}: {exc}")
                if isinstance(exc, AuthExpiredError):
                    counts.update(needsReauth=True, detail=exc.remedy)
                continue
            uid, file_path, content = _adopt_remote_uid(file_path, content, ref.remote_id, state_dir)
            local_hash = hashlib.sha256(content).hexdigest()
            adopted[uid] = file_path
            state.items[uid] = {"remoteId": ref.remote_id, "etag": ref.etag, "localHash": local_hash}
            counts["createdRemote"] += 1

        elif entry["localHash"] != local_hash:
            try:
                ref = bridge.push_update(account, calendar, content, RemoteRef(remote_id=entry["remoteId"], etag=entry.get("etag")))
                state.items[uid] = {"remoteId": ref.remote_id, "etag": ref.etag, "localHash": local_hash}
                counts["updated"] += 1
            except ConflictError:
                # Keep the remote version: leave the tracked state (and
                # therefore the file, on the next pull) pointing at what
                # the server actually has, save this edit separately, and
                # say so. The next pull cycle -- not this push -- is what
                # brings <uid>.ics back in line with the server, since the
                # Bridge protocol has no "fetch one item" method and
                # doesn't need one just for this rare path.
                preserve(uid, content)
                state.cursor = None  # Fetch the winning remote version on the next sync.
            except Exception as exc:  # noqa: BLE001
                counts.setdefault("errors", []).append(f"update {uid}: {exc}")
                if isinstance(exc, AuthExpiredError):
                    counts.update(needsReauth=True, detail=exc.remedy)

    on_disk.update(adopted)
    # A uid this sync already knew about, whose file the user removed
    # before the pull ran. Judged on the pre-pull snapshot rather than on
    # what is on disk now, so an event the pull happened to rewrite is
    # still recognised as deleted. Events the pull itself removed were on
    # disk beforehand, so they are correctly not in this set, and events
    # the pull newly added were not known beforehand.
    for uid in sorted(known_before - on_disk_before):
        entry = state.items.get(uid)
        if entry is None:
            continue
        try:
            bridge.push_delete(account, calendar, RemoteRef(remote_id=refs_before[uid]["remoteId"], etag=refs_before[uid].get("etag")))
        except ConflictError as exc:
            state.cursor = None
            counts.setdefault("errors", []).append(f"delete {uid}: {exc}; remote event retained")
            continue
        except Exception as exc:  # noqa: BLE001
            counts.setdefault("errors", []).append(f"delete {uid}: {exc}")
            if isinstance(exc, AuthExpiredError):
                counts.update(needsReauth=True, detail=exc.remedy)
            continue
        # If the pull resurrected the file, take it back out; the user's
        # deletion is the newer intent.
        (calendar_path / f"{uid}.ics").unlink(missing_ok=True)
        del state.items[uid]
        counts["deletedLocal"] += 1

    # 4. Record.
    state.save(state_path)
    counts["ok"] = "errors" not in counts
    return counts


def _select_calendars(bridge, account: dict) -> list:
    all_calendars = bridge.list_calendars(account)
    wanted_ids = account.get("calendars") or []
    if wanted_ids:
        by_id = {c.id: c for c in all_calendars}
        return [by_id[cid] for cid in wanted_ids if cid in by_id]
    return [c for c in all_calendars if c.writable]


def _sync_bridge(account: dict, vdir_root: Path, state_dir=None) -> dict:
    module_path = BRIDGE_MODULES.get(account["type"])
    if module_path is None:
        return {"ok": False, "detail": f"'{account['type']}' bridge not yet implemented"}

    import importlib

    bridge = importlib.import_module(module_path)
    try:
        calendars = _select_calendars(bridge, account)
    except AuthExpiredError as exc:
        # Kept whole rather than folded into the generic message. Every
        # other failure here is worth a retry; this one waits for the
        # user, so it has to say so and say what to run.
        return {"ok": False, "needsReauth": True, "detail": f"{exc.remedy}",
                "summary": f"Omagenda's sign-in for '{account['id']}' has expired"}
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole sync run
        return {"ok": False, "detail": f"couldn't list calendars: {exc}"}

    if not calendars:
        return {"ok": False, "detail": "no calendars selected (configure 'calendars' or grant write access to at least one)"}

    def one(calendar):
        calendar_path = vdir_root / account["id"] / calendar.id
        try:
            return _sync_one_calendar(bridge, account, calendar, calendar_path, state_dir=state_dir)
        except AuthExpiredError as exc:
            return {"ok": False, "needsReauth": True, "detail": exc.remedy}
        except Exception as exc:  # noqa: BLE001 -- one broken calendar must not sink the others
            return {"ok": False, "detail": str(exc)}

    # Nearly all of a sync is spent waiting on the server: an incremental
    # pull of a large calendar that returns *no changes at all* still
    # takes Google the better part of ten seconds. Done one after
    # another, twelve calendars took two and a half minutes, which meant
    # a Quick Add could sit that long before reaching the phone in your
    # pocket. Each calendar owns its own folder and its own state file,
    # so they overlap safely; the cap is a courtesy to the server rather
    # than a limit of ours.
    per_calendar = {}
    if len(calendars) == 1:
        per_calendar[calendars[0].id] = one(calendars[0])
    else:
        workers = min(_sync_workers(), len(calendars))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(one, c): c for c in calendars}
            for future in concurrent.futures.as_completed(futures):
                per_calendar[futures[future].id] = future.result()

    ordered = {c.id: per_calendar[c.id] for c in calendars if c.id in per_calendar}
    result = {"ok": all(c.get("ok", False) for c in ordered.values()), "calendars": ordered}
    # One expired sign-in fails every calendar on the account, so report
    # it once at the account rather than twelve times underneath it.
    reauth = [c for c in ordered.values() if c.get("needsReauth")]
    if reauth:
        result["needsReauth"] = True
        result["summary"] = f"Omagenda's sign-in for '{account['id']}' has expired"
        result["detail"] = reauth[0]["detail"]
    return result


def _merge_omacal(vdir_root: Path) -> dict | None:
    binary = shutil.which("omacal")
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "events", "list", "--json"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"omacal failed to run: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "detail": f"omacal exited {result.returncode}"}
    return {"ok": True, "detail": "omacal merge not yet wired into the vdir (read-only, Phase 4)"}


# How many calendars to sync at once. Six took 46s on a twelve-calendar
# account and twelve took 38s, so the returns past this point are small
# and the politeness cost is not: someone with fifty calendars should
# not open fifty simultaneous connections. Raise it with `sync_workers`
# in config.toml if your server doesn't mind.
DEFAULT_SYNC_WORKERS = 8


def _sync_workers() -> int:
    try:
        return max(1, int(read_config().get("sync_workers", DEFAULT_SYNC_WORKERS)))
    except Exception:  # noqa: BLE001 -- a bad config value must not stop a sync
        return DEFAULT_SYNC_WORKERS


def record_path(state_dir=None) -> Path:
    from omagenda.index import resolve_state_dir

    base = Path(state_dir).expanduser() if state_dir else resolve_state_dir()
    return base / "last-sync.json"


def read_last_sync(state_dir=None) -> dict:
    """When sync last ran and whether it worked. Absent until the first
    run, which is itself the answer to "why has nothing reached the
    server yet"."""
    try:
        return json.loads(record_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _record_sync(results: dict, state_dir=None) -> None:
    problems = sorted(k for k, v in results.items() if not v.get("ok", False))
    # An expired sign-in outlives the sync that discovered it and is the
    # one failure the user must act on, so it is recorded by name and the
    # panel can keep saying so until they do.
    reauth = sorted(k for k, v in results.items() if v.get("needsReauth"))
    path = record_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "ok": not problems, "problems": problems}
    if reauth:
        payload["needsReauth"] = reauth
        payload["remedy"] = next(v["detail"] for k, v in sorted(results.items())
                                 if v.get("needsReauth"))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def _sync_lock(state_dir=None, timeout: float = 240.0):
    """Serialise syncs across processes.

    `omagenda watch` syncs on its own now, so a hand-run `omagenda sync`
    is a second writer into the same folders -- and the two collided
    exactly as you would expect: one chmodded a read-only calendar back
    to 0555 while the other was still writing into it, and that calendar
    failed with a permission error on its own temp file. Waiting is the
    right answer rather than refusing, because a manual sync is almost
    always someone wanting it to happen *now*, and the wait is bounded by
    how long a sync takes.
    """
    import fcntl

    from omagenda.index import resolve_state_dir

    base = Path(state_dir).expanduser() if state_dir else resolve_state_dir()
    base.mkdir(parents=True, exist_ok=True)
    handle = open(base / "sync.lock", "w")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "another sync has been running for over "
                        f"{int(timeout)}s; check 'omagenda doctor'") from None
                time.sleep(0.25)
        yield
    finally:
        handle.close()  # closing releases the flock


def sync_all(config: dict | None = None, state_dir=None, respect_pause: bool = False) -> dict:
    from omagenda.pause import read_pause

    with _sync_lock(state_dir):
        paused_until = read_pause(state_dir) if respect_pause else None
        if paused_until:
            return {"_pause": {"ok": True, "skipped": True, "pausedUntil": paused_until}}
        return _sync_all_locked(config, state_dir)


def _sync_all_locked(config: dict | None, state_dir) -> dict:
    config = config if config is not None else read_config()
    vdir_root = resolve_vdir_root()
    results = {}
    for account in config.get("accounts", []):
        account_type = account.get("type")
        # A broken account reports itself and the run carries on; the
        # bridge path already did this, and the others have exactly the
        # same reason to (a read-only folder, an unreadable config).
        try:
            if account_type == "ics":
                results[account["id"]] = _sync_ics(account, vdir_root)
            elif account_type in ("icloud", "caldav"):
                results[account["id"]] = _sync_caldav(account)
            elif account_type in ("google", "microsoft"):
                results[account["id"]] = _sync_bridge(account, vdir_root, state_dir=state_dir)
            else:
                results[account.get("id", "?")] = {"ok": False, "detail": f"unknown account type '{account_type}'"}
        except Exception as exc:  # noqa: BLE001 -- see comment above
            results[account.get("id", "?")] = {"ok": False, "detail": str(exc)}

    omacal_result = _merge_omacal(vdir_root)
    if omacal_result is not None:
        results["omacal"] = omacal_result

    _record_sync(results, state_dir)
    return results

"""Sync orchestration.

Reads config.toml's accounts and dispatches each one by type. This phase
has no accounts.py yet (that's Phase 1b), so nothing writes a real account
into config.toml -- sync_all() runs safely against an empty account list
today, and the dispatch below is what Phase 1b's `omagenda account add`
starts populating.

- `ics`: fully implemented and testable now -- a plain HTTP fetch into a
  read-only vdir folder, no external tool required.
- `icloud` / `caldav`: delegates to the configured sync tool (pimsync,
  falling back to vdirsyncer). The exact CLI invocation is a placeholder
  pending Phase 1b, when `accounts.py` writes real pimsync configs and
  this can be verified against `man pimsync` on a machine that has it
  installed (this one doesn't -- no sudo in this session, see AGENTS.md).
- `google` / `microsoft`: not implemented until their bridges land
  (Phase 1b, Phase 5) -- reported clearly rather than attempted.

See ARCHITECTURE.md §7 and §11.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

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

    (folder / "displayname").write_text(account.get("id", url))
    if account.get("color"):
        (folder / "color").write_text(account["color"])
    (folder / "subscription.ics").write_bytes(data)
    folder.chmod(0o555)  # readOnly, per vdir.discover_calendars' os.access check
    return {"ok": True, "detail": f"fetched {len(data)} bytes into {folder}"}


def _sync_caldav(account: dict) -> dict:
    from omagenda.accounts import pimsync_config_path

    tool = account.get("sync", "pimsync")
    binary = shutil.which(tool)
    if not binary:
        return {"ok": False, "detail": f"{tool} not found on PATH (omarchy pkg add {tool})"}

    config_path = pimsync_config_path(account["id"])
    if not config_path.exists():
        return {"ok": False, "detail": f"no pimsync config at {config_path}; run 'omagenda account add' again"}

    try:
        # Verbatim against pimsync.conf(5) and pimsync(1): `pimsync -c
        # <configfile> sync [pair...]`. accounts.generate_pimsync_config
        # names the pair after the account id (sanitized), which is also
        # the only pair this config file defines.
        from omagenda.accounts import _safe_pair_name

        result = subprocess.run(
            [binary, "-c", str(config_path), "sync", _safe_pair_name(account["id"])],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"{tool} failed to run: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "detail": f"{tool} exited {result.returncode}: {result.stderr.strip()[:200]}"}
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


def _notify_conflict(uid: str, calendar_name: str) -> None:
    binary = shutil.which("omarchy-notification-send") or "/usr/share/omarchy/bin/omarchy-notification-send"
    subprocess.run([binary, "-g", "󰢌", "Sync conflict",
                    f"An edit to an event in {calendar_name} conflicted with a server change; "
                    f"your version was saved as {uid}.conflict.ics"], check=False)


def _sync_one_calendar(bridge, account: dict, calendar, calendar_path: Path, state_dir=None) -> dict:
    """The shared pull -> detect-local-changes -> push -> record algorithm
    (ARCHITECTURE.md §11), driven through the Bridge protocol so it works
    the same way for any bridge, not just Google."""
    from omagenda.bridges import ConflictError, RemoteRef, SyncState, state_path_for

    calendar_path.mkdir(parents=True, exist_ok=True)
    state_path = state_path_for(account["id"], calendar.id, state_dir)
    state = SyncState.load(state_path)
    counts = {"pulled": 0, "createdRemote": 0, "createdLocal": 0, "updated": 0, "deletedRemote": 0,
              "deletedLocal": 0, "conflicts": 0}

    # 1. Pull.
    pull_result = bridge.pull(account, calendar, state.cursor)
    for change in pull_result.changed:
        _overwrite_ics(calendar_path / f"{change.uid}.ics", change.ics_bytes)
        state.items[change.uid] = {
            "remoteId": change.ref.remote_id,
            "etag": change.ref.etag,
            "localHash": hashlib.sha256(change.ics_bytes).hexdigest(),
        }
        counts["pulled"] += 1
    for uid in pull_result.deleted_uids:
        (calendar_path / f"{uid}.ics").unlink(missing_ok=True)
        state.items.pop(uid, None)
        counts["deletedRemote"] += 1
    state.cursor = pull_result.next_cursor

    # 2. Detect local changes: compare every file on disk against the
    # hash recorded the last time this uid was pulled or pushed. A file
    # just written by the pull above already has a matching hash, so it
    # correctly falls through as "unchanged" here.
    on_disk = {f.stem: f for f in calendar_path.glob("*.ics") if not f.name.endswith(".conflict.ics")}

    for uid, file_path in on_disk.items():
        content = file_path.read_bytes()
        local_hash = hashlib.sha256(content).hexdigest()
        entry = state.items.get(uid)

        if entry is None:
            try:
                ref = bridge.push_create(account, calendar, content)
            except Exception as exc:  # noqa: BLE001 -- one bad event must not stop the others
                counts.setdefault("errors", []).append(f"create {uid}: {exc}")
                continue
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
                conflict_path = calendar_path / f"{uid}.conflict.ics"
                conflict_path.write_bytes(content)
                _notify_conflict(uid, calendar.name)
                counts["conflicts"] += 1
            except Exception as exc:  # noqa: BLE001
                counts.setdefault("errors", []).append(f"update {uid}: {exc}")

    deleted_by_pull = {c.uid for c in pull_result.changed} | set(pull_result.deleted_uids)
    for uid in [u for u in state.items if u not in on_disk and u not in deleted_by_pull]:
        entry = state.items[uid]
        try:
            bridge.push_delete(account, calendar, RemoteRef(remote_id=entry["remoteId"], etag=entry.get("etag")))
        except Exception as exc:  # noqa: BLE001
            counts.setdefault("errors", []).append(f"delete {uid}: {exc}")
            continue
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
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole sync run
        return {"ok": False, "detail": f"couldn't list calendars: {exc}"}

    if not calendars:
        return {"ok": False, "detail": "no calendars selected (configure 'calendars' or grant write access to at least one)"}

    per_calendar = {}
    for calendar in calendars:
        calendar_path = vdir_root / account["id"] / calendar.id
        try:
            per_calendar[calendar.id] = _sync_one_calendar(bridge, account, calendar, calendar_path, state_dir=state_dir)
        except Exception as exc:  # noqa: BLE001 -- one broken calendar must not sink the others
            per_calendar[calendar.id] = {"ok": False, "detail": str(exc)}

    return {"ok": all(c.get("ok", False) for c in per_calendar.values()), "calendars": per_calendar}


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


def sync_all(config: dict | None = None, state_dir=None) -> dict:
    config = config if config is not None else read_config()
    vdir_root = resolve_vdir_root()
    results = {}
    for account in config.get("accounts", []):
        account_type = account.get("type")
        if account_type == "ics":
            results[account["id"]] = _sync_ics(account, vdir_root)
        elif account_type in ("icloud", "caldav"):
            results[account["id"]] = _sync_caldav(account)
        elif account_type in ("google", "microsoft"):
            results[account["id"]] = _sync_bridge(account, vdir_root, state_dir=state_dir)
        else:
            results[account.get("id", "?")] = {"ok": False, "detail": f"unknown account type '{account_type}'"}

    omacal_result = _merge_omacal(vdir_root)
    if omacal_result is not None:
        results["omacal"] = omacal_result

    return results

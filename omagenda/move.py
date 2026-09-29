"""Move one safe event by creating its independent copy before deleting it."""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from omagenda import index, vdir
from omagenda.doctor import read_config
from omagenda.edit import atomic_bytes, replace_properties
from omagenda.event_file import validate_event_file


def _without_omagenda_properties(content: bytes) -> bytes:
    """Drop direct VEVENT X-OMAGENDA and ORGANIZER fields without reserializing other bytes."""
    chunks: list[bytes] = []
    for line in content.splitlines(keepends=True):
        if line.startswith((b" ", b"\t")) and chunks:
            chunks[-1] += line
        else:
            chunks.append(line)
    output: list[bytes] = []
    stack: list[bytes] = []
    for chunk in chunks:
        head = chunk.splitlines()[0].upper()
        key = re.split(b"[;:]", head, maxsplit=1)[0]
        if stack and stack[-1] == b"VEVENT" and (key.startswith(b"X-OMAGENDA-") or key == b"ORGANIZER"):
            # X-OMAGENDA-* describes the old provider copy (its web link). An
            # ORGANIZER can only be left over here -- events with ATTENDEEs are
            # refused -- and on a CalDAV server it would mark a brand-new event
            # as a scheduling object that server never issued.
            continue
        output.append(chunk)
        if head.startswith(b"BEGIN:"):
            stack.append(head[6:])
        elif head.startswith(b"END:") and stack:
            stack.pop()
    return b"".join(output)


def _write_new(path: Path, content: bytes) -> None:
    """Atomically create a target file and persist its directory entry."""
    if path.exists():
        raise FileExistsError(f"an event already exists at {path}")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".move-", suffix=".ics.tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Link rather than replace: a UUID collision is exceptionally unlikely,
        # but must never turn a move into an overwrite if it does occur.
        os.link(temporary, path)
        Path(temporary).unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _save_source(path: Path, calendar_id: str, content: bytes) -> Path:
    """Make the durable, private source copy required before its unlink."""
    root = vdir.resolve_vdir_root().expanduser().resolve()
    safe_calendar = re.sub(r"[^A-Za-z0-9_-]", "_", calendar_id) or "calendar"
    moved = index.resolve_state_dir() / "moved"
    folder = moved / safe_calendar
    if folder.resolve().is_relative_to(root):
        raise ValueError("Move copies must be stored outside the vdir")
    for directory in (moved, folder):
        if directory.is_symlink():
            raise ValueError("Move copy folders must not be symlinks")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    saved = folder / f"{path.stem}.{stamp}.ics"
    try:
        _write_new(saved, content)
    except Exception:
        saved.unlink(missing_ok=True)
        raise
    return saved


def _target_calendar(calendar_id: str) -> dict:
    calendars = vdir.discover_calendars()
    target = next((calendar for calendar in calendars if calendar["id"] == calendar_id), None)
    if target is None:
        available = ", ".join(calendar["id"] for calendar in calendars) or "none"
        raise ValueError(f"no calendar named '{calendar_id}' (have: {available})")
    if target["readOnly"]:
        raise ValueError(f"'{target['name']}' is read-only, so events can't be moved there")
    # The CLI process imports doctor after its environment is ready. Direct
    # callers can import us earlier, so honour their explicit config override
    # here too without changing doctor.CONFIG_PATH's testable contract.
    config_path = os.environ.get("OMAGENDA_CONFIG")
    if config_path:
        try:
            import tomllib

            with Path(config_path).open("rb") as stream:
                config = tomllib.load(stream)
        except (OSError, ValueError):
            config = {}
    else:
        config = read_config()
    target["hidden"] = target["id"] in config.get("hidden_calendars", [])
    return target


def move_event(event_file: str, calendar_id: str, dry_run: bool = False,
               properties: dict | None = None, title: str | None = None) -> dict:
    """Move `event_file` to a calendar, never deleting the source first.

    `properties` is the sentence edit already calculated by edit.py.  It is
    applied only to the fresh target copy, so a failed move leaves the source
    byte-for-byte untouched.
    """
    from omagenda.sync import _sync_lock

    with _sync_lock():
        return _move_event(event_file, calendar_id, dry_run, properties, title)


def _move_event(event_file: str, calendar_id: str, dry_run: bool = False,
                properties: dict | None = None, title: str | None = None) -> dict:
    """Locked implementation shared with sentence editing."""
    path, source, content, event = validate_event_file(event_file, "move")
    target = _target_calendar(calendar_id)
    if dry_run:
        if target["id"] == source["id"]:
            return {"moved": False, "noOp": True, "title": title or str(event.get("SUMMARY", "Untitled")),
                    "calendar": source["id"], "file": str(path), "name": source["name"]}
        return {"moved": True, "dryRun": True, "title": title or str(event.get("SUMMARY", "Untitled")),
                "calendar": target["id"], "sourceCalendar": source["id"], "file": str(Path(target["path"]) / "<new UID>.ics"),
                "sourceFile": str(path), "copy": None, "hidden": target["hidden"],
                "name": target["name"], "sourceName": source["name"]}
    if target["id"] == source["id"]:
        return {"moved": False, "noOp": True, "title": title or str(event.get("SUMMARY", "Untitled")),
                "calendar": source["id"], "file": str(path), "name": source["name"]}

    now = datetime.now(timezone.utc)
    new_uid = f"{uuid.uuid4()}@omagenda"
    replacements = dict(properties or {})
    replacements.update(UID=new_uid, SEQUENCE=0, DTSTAMP=now, **{"LAST-MODIFIED": now})
    copied = _without_omagenda_properties(replace_properties(content, replacements))
    target_path = Path(target["path"]) / f"{new_uid}.ics"
    source_copy: Path | None = None
    try:
        _write_new(target_path, copied)
        if not target_path.is_file() or target_path.read_bytes() != copied:
            raise OSError(f"could not confirm moved copy at {target_path}")
        source_copy = _save_source(path, source["id"], content)
    except Exception:
        # Before the source unlink, failure must leave exactly the old
        # state. A target copy is only a staging copy until that point.
        target_path.unlink(missing_ok=True)
        raise

    try:
        path.unlink()
    except Exception as exc:
        raise RuntimeError("The event now exists in both calendars: "
                           f"source {path}; target {target_path}. Source removal failed: {exc}") from exc
    try:
        source_dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(source_dir_fd)
        finally:
            os.close(source_dir_fd)
    except Exception as exc:
        raise RuntimeError(f"Event moved to {target_path}; source copy is at {source_copy}, "
                           f"but source directory confirmation failed: {exc}") from exc

    try:
        index.index()
    except Exception as exc:
        raise RuntimeError(f"Event moved to {target_path}; source copy is at {source_copy}, "
                           f"but agenda rebuild failed: {exc}") from exc
    return {"moved": True, "title": title or str(event.get("SUMMARY", "Untitled")),
            "calendar": target["id"], "sourceCalendar": source["id"], "file": str(target_path),
            "sourceFile": str(path), "copy": str(source_copy), "hidden": target["hidden"],
            "name": target["name"], "sourceName": source["name"], "uid": new_uid}

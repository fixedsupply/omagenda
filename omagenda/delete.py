"""Delete a single non-recurring event, preserving its original bytes first."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import icalendar

from omagenda import index, vdir


def delete_event(event_file: str) -> dict:
    # Serialize with provider sync so a pull cannot replace the selected file
    # between validation and unlink, or temporarily reopen a read-only folder.
    from omagenda.sync import _sync_lock

    with _sync_lock():
        return _delete_event(event_file)


def _delete_event(event_file: str) -> dict:
    root_given = vdir.resolve_vdir_root().expanduser().absolute()
    root = root_given.resolve()
    given = Path(event_file).expanduser().absolute()
    # A symlink inside the vdir could alias another calendar's file, so those
    # are refused. Symlinks above it (a symlinked home, or a vdir folder that
    # is itself a link) are ordinary setups and must not block deletion.
    inside_vdir = [p for p in (given, *given.parents)
                   if p not in (root_given, root) and (p.is_relative_to(root_given) or p.is_relative_to(root))]
    if ".." in given.parts or any(p.is_symlink() for p in inside_vdir):
        raise ValueError("Event file must not use '..' or symlinks inside the calendar folder")
    path = given.resolve(strict=True)
    if (not path.is_relative_to(root) or not path.is_file()
            or path.suffix != ".ics" or path.name.endswith(".conflict.ics")):
        raise ValueError("Event file must be a regular .ics file inside a discovered calendar")
    calendar = next((c for c in vdir.discover_calendars()
                     if Path(c["path"]).resolve() == path.parent), None)
    if calendar is None:
        raise ValueError("Event file must be inside a discovered calendar folder")
    name = " ".join(calendar["name"].split())
    if calendar["readOnly"]:
        raise ValueError(f"'{name}' is read-only, so its events can't be deleted here")
    content = path.read_bytes()
    parsed = icalendar.Calendar.from_ical(content)
    if any(key in component for component in parsed.walk()
           for key in ("RRULE", "RDATE", "RECURRENCE-ID")):
        raise ValueError(f"Recurring events can't be deleted from Omagenda yet; delete it in {name}'s own app")
    events = parsed.walk("VEVENT")
    if len(events) != 1:
        raise ValueError("Event file must contain exactly one VEVENT to be deleted")
    title = " ".join(str(events[0].get("SUMMARY", "Untitled")).split())
    calendar_id = re.sub(r"[^A-Za-z0-9_-]", "_", calendar["id"]) or "calendar"
    deleted = index.resolve_state_dir() / "deleted"
    folder = deleted / calendar_id
    if folder.resolve().is_relative_to(root):
        raise ValueError("Deletion copies must be stored outside the vdir")
    for directory in (deleted, folder):
        if directory.is_symlink():
            raise ValueError("Deletion copy folders must not be symlinks")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    saved = folder / f"{path.stem}.{stamp}.ics"
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".delete-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, saved)
        # Persist the directory entry before removing the only other copy.
        directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    path.unlink()
    try:
        index.index()
    except Exception as exc:
        raise RuntimeError(f"Event deleted; copy is at {saved}, but agenda rebuild failed: {exc}") from exc
    return {"deleted": True, "title": title, "calendar": calendar["id"], "copy": str(saved), "name": name}

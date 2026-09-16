"""Delete a single non-recurring event, preserving its original bytes first."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from omagenda import index, vdir


def delete_event(event_file: str) -> dict:
    # Serialize with provider sync so a pull cannot replace the selected file
    # between validation and unlink, or temporarily reopen a read-only folder.
    from omagenda.sync import _sync_lock

    with _sync_lock():
        return _delete_event(event_file)


def _delete_event(event_file: str) -> dict:
    from omagenda.event_file import validate_event_file

    path, calendar, content, event = validate_event_file(event_file)
    root = vdir.resolve_vdir_root().expanduser().resolve()
    name = " ".join(calendar["name"].split())
    title = " ".join(str(event.get("SUMMARY", "Untitled")).split())
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

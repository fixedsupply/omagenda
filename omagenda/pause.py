"""A bounded watcher sync pause, shared by the CLI, indexer and sync lock."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def state_path(state_dir: Path | None = None) -> Path:
    from omagenda.index import resolve_state_dir

    return (Path(state_dir) if state_dir is not None else resolve_state_dir()) / "sync-paused-until"


def parse_duration(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([smh])", value)
    if match and len(match[1].lstrip("0")) <= 5:
        seconds = int(match[1].lstrip("0") or "0") * {"s": 1, "m": 60, "h": 3600}[match[2]]
        if 0 < seconds <= 86400:
            return seconds
    raise ValueError("pause duration must be a positive integer with s, m or h, at most 24h")


def read_pause(state_dir: Path | None = None, now: datetime | None = None) -> str | None:
    try:
        value = state_path(state_dir).read_text(encoding="utf-8").strip()
        until = datetime.fromisoformat(value)
        if until.utcoffset() is not None and until > (now or datetime.now(timezone.utc)):
            return value
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def pause_sync(duration: str, state_dir: Path | None = None) -> str:
    from omagenda.storage import atomic_write_text
    from omagenda.sync import _sync_lock

    until = (datetime.now(timezone.utc) + timedelta(seconds=parse_duration(duration))).isoformat()
    atomic_write_text(state_path(state_dir), until + "\n")
    # The pause must be visible before waiting for any current sync to finish.
    with _sync_lock(state_dir):
        pass
    return until


def resume_sync(state_dir: Path | None = None) -> None:
    state_path(state_dir).unlink(missing_ok=True)

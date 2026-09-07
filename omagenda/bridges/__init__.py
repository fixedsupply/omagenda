"""Bridge interface for cloud calendar accounts.

Every bridge (Google, Microsoft) implements the same `Bridge` protocol; the
actual pull -> detect-local-changes -> push -> record algorithm is shared
and lives in sync.py, not here, since it's the same four steps regardless
of which REST API a bridge talks to (ARCHITECTURE.md §11). This module is
just the contract both sides agree on: the protocol itself, the plain data
it passes back and forth, and the on-disk sync-state store.

Sync state is per calendar, at
`~/.local/state/omagenda/sync/<account_id>/<calendar_id>.json`: the
server's incremental cursor (a Google syncToken or a Microsoft delta
link -- opaque to everything except the bridge that produced it) and a
map of local UID -> {remoteId, etag, localHash}, used to detect local
creates/updates/deletes between sync runs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from omagenda.index import resolve_state_dir


@dataclass
class RemoteCalendar:
    id: str
    name: str
    writable: bool = True


@dataclass
class RemoteRef:
    remote_id: str
    etag: str | None = None


@dataclass
class PullChange:
    """One created-or-updated remote item, ready to write to a vdir file."""
    uid: str
    ics_bytes: bytes
    ref: RemoteRef


@dataclass
class PullResult:
    changed: list[PullChange] = field(default_factory=list)
    deleted_uids: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    full_resync: bool = False


class Bridge(Protocol):
    type: str

    def authorize(self, account: dict) -> None:
        """Interactive; stores tokens via the keyring (accounts.py)."""
        ...

    def list_calendars(self, account: dict) -> list[RemoteCalendar]:
        ...

    def pull(self, account: dict, calendar: RemoteCalendar, cursor: str | None) -> PullResult:
        """Incremental using `cursor` (a syncToken or delta link); pass
        None for a full pull. A bridge that gets a 410/invalid-cursor
        response from the server does the full pull itself and returns
        `full_resync=True` -- the caller doesn't need to notice and retry."""
        ...

    def push_create(self, account: dict, calendar: RemoteCalendar, ics_bytes: bytes) -> RemoteRef:
        ...

    def push_update(self, account: dict, calendar: RemoteCalendar, ics_bytes: bytes, ref: RemoteRef) -> RemoteRef:
        """Raises `ConflictError` on a 412 (remote changed since `ref.etag` was read)."""
        ...

    def push_delete(self, account: dict, calendar: RemoteCalendar, ref: RemoteRef) -> None:
        ...


class ConflictError(Exception):
    """Raised by push_update when the remote's current etag no longer
    matches the one the caller pushed against."""


# ---------------------------------------------------------------------
# Sync state store
# ---------------------------------------------------------------------
@dataclass
class SyncState:
    cursor: str | None = None
    items: dict[str, dict] = field(default_factory=dict)  # uid -> {remoteId, etag, localHash}

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(cursor=data.get("cursor"), items=data.get("items", {}))

    def save(self, path: Path) -> None:
        import os
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"cursor": self.cursor, "items": self.items}, indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".sync-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]", "_", name)


def state_path_for(account_id: str, calendar_id: str, state_dir: Path | None = None) -> Path:
    state_dir = state_dir or resolve_state_dir()
    return state_dir / "sync" / _sanitize(account_id) / f"{_sanitize(calendar_id)}.json"

"""Calendar sets from config, with the active choice kept in runtime state."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def state_path(state_dir: Path | None = None) -> Path:
    from omagenda.index import resolve_state_dir

    return (Path(state_dir) if state_dir is not None else resolve_state_dir()) / "active-set"


def read_active(state_dir: Path | None = None) -> str:
    try:
        return state_path(state_dir).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def defined_sets() -> dict[str, list[str]]:
    from omagenda.doctor import read_config

    return read_config().get("sets", {})


def write_active(name: str, state_dir: Path | None = None) -> None:
    path = state_path(state_dir)
    if not name:
        path.unlink(missing_ok=True)
        return
    atomic_write_text(path, name + "\n")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A watcher must see either the old name or the complete new name.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + "-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

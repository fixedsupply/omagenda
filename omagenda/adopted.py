"""Short-lived aliases for event paths replaced by provider identities."""
import json
import time
from pathlib import Path

from omagenda import index, vdir

TTL = 24 * 60 * 60


def _read(state_dir: Path | None = None) -> dict:
    try:
        entries = json.loads(((state_dir or index.resolve_state_dir()) / "adopted.json").read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(entries, dict):
        return {}
    now = time.time()
    return {old: entry for old, entry in entries.items()
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            and isinstance(entry.get("time"), (int, float))
            and now - TTL <= entry["time"] <= now}


def _inside(path: Path) -> bool:
    return (path.is_absolute() and ".." not in path.parts
            and path.resolve().is_relative_to(vdir.resolve_vdir_root().expanduser().resolve()))


def record(old: Path, new: Path, state_dir: Path | None = None) -> None:
    from omagenda.edit import atomic_bytes

    old, new = old.absolute(), new.absolute()
    if not _inside(old) or not _inside(new):
        return
    entries = {key: entry for key, entry in _read(state_dir).items()
               if _inside(Path(key)) and _inside(Path(entry["path"]))}
    entries[str(old)] = {"path": str(new), "time": time.time()}
    folder = state_dir or index.resolve_state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    atomic_bytes(folder / "adopted.json", json.dumps(entries).encode())


def resolve(given: Path) -> Path:
    entries = _read()
    current = given
    seen = set()
    while _inside(current) and str(current) not in seen:
        seen.add(str(current))
        entry = entries.get(str(current))
        if entry is None:
            break
        current = Path(entry["path"])
        if not _inside(current):
            break
        if current.exists():
            return current
    return given

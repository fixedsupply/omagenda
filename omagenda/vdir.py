"""Vdir discovery and event I/O.

A vdir calendar is any directory that directly holds a `displayname` file
or at least one `*.ics` file. To support both a flat layout (today's
fixtures, and a calendar the user set up by hand) and the per-account
layout a bridge writes later (`<account>/<calendar>/`, ARCHITECTURE.md
§7/§11), `discover_calendars` looks one level deeper into any child
directory that isn't itself a calendar, and ids the result by its path
relative to the vdir root (`"personal"` or `"google-calvin/primary"`).

See ARCHITECTURE.md §1, §4 (the `color` field is always a theme name,
never hex) and §7 (how a new event file is written).
"""
from __future__ import annotations

import colorsys
import os
import re
import tempfile
import uuid
from pathlib import Path

import icalendar

DEFAULT_VDIR = Path.home() / ".local" / "share" / "calendars"

# Order is the round-robin assignment sequence for calendars with no color
# file of their own -- picked for visual variety, not any deeper meaning.
THEME_COLOR_ORDER = ["blue", "green", "magenta", "yellow", "cyan", "red", "orange"]

# Hue anchors (degrees) for mapping an arbitrary hex color to the nearest
# theme name. Matches the seven names a theme's colors.toml defines
# (Commons/Color.qml), never the theme's actual hex -- a theme swap must
# repaint every calendar without Omagenda's own state changing.
_THEME_HUES = {
    "red": 0, "orange": 30, "yellow": 55, "green": 120,
    "cyan": 185, "blue": 225, "magenta": 300,
}


def resolve_vdir_root() -> Path:
    override = os.environ.get("OMAGENDA_VDIR")
    return Path(override).expanduser() if override else DEFAULT_VDIR


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None


def _hue_of_hex(hex_color: str) -> float | None:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    if not match:
        return None
    r, g, b = (int(match.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.08:  # too desaturated (near white/grey/black) to have a real hue
        return None
    return h * 360


def map_color_to_theme(value: str | None) -> str | None:
    """Map a vdir color file's contents to a theme color name.

    Accepts a hex color (mapped to the nearest of the seven theme names by
    hue) or an already-valid theme name (passed through case-insensitively).
    Returns None when the value is missing, unparsable, or too desaturated
    to have a meaningful hue -- the caller then assigns one round-robin.
    """
    if not value:
        return None
    lowered = value.strip().lower()
    if lowered in _THEME_HUES:
        return lowered
    hue = _hue_of_hex(value)
    if hue is None:
        return None
    return min(_THEME_HUES, key=lambda name: min(abs(hue - _THEME_HUES[name]), 360 - abs(hue - _THEME_HUES[name])))


def _is_calendar_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "displayname").is_file():
        return True
    return any(path.glob("*.ics"))


def discover_calendars(vdir_root: Path | str | None = None) -> list[dict]:
    """Discover every calendar under the vdir root.

    Returns a list of {id, name, path, color, readOnly, source} dicts,
    sorted by id. `color` is always one of THEME_COLOR_ORDER's names.
    """
    root = Path(vdir_root).expanduser() if vdir_root else resolve_vdir_root()
    if not root.is_dir():
        return []

    found: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if _is_calendar_dir(child):
            found.append((child.name, child))
            continue
        for grandchild in sorted(child.iterdir()):
            if _is_calendar_dir(grandchild):
                found.append((f"{child.name}/{grandchild.name}", grandchild))

    found.sort(key=lambda item: item[0])

    calendars = []
    for index, (cal_id, path) in enumerate(found):
        name = _read_text_file(path / "displayname") or cal_id
        explicit_color = map_color_to_theme(_read_text_file(path / "color"))
        color = explicit_color or THEME_COLOR_ORDER[index % len(THEME_COLOR_ORDER)]
        calendars.append({
            "id": cal_id,
            "name": name,
            "path": str(path),
            "color": color,
            "readOnly": not os.access(path, os.W_OK),
            "source": "vdir",
        })
    return calendars


def list_ics_files(calendar_path: Path | str) -> list[Path]:
    return sorted(Path(calendar_path).glob("*.ics"))


def read_ics_file(path: Path | str) -> icalendar.Calendar:
    return icalendar.Calendar.from_ical(Path(path).read_bytes())


def write_event_ics(calendar_path: Path | str, cal: icalendar.Calendar, uid: str | None = None) -> Path:
    """Write a new event file atomically: temp file in the same directory,
    fsync, then rename. Never overwrites an existing file (v1 has no
    in-place edit path other than $EDITOR -- ARCHITECTURE.md §7).
    """
    calendar_path = Path(calendar_path)
    uid = uid or f"{uuid.uuid4()}@omagenda"
    final_path = calendar_path / f"{uid}.ics"
    if final_path.exists():
        raise FileExistsError(f"an event with UID {uid} already exists at {final_path}")

    fd, tmp_name = tempfile.mkstemp(dir=calendar_path, prefix=".omagenda-", suffix=".ics.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(cal.to_ical())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, final_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return final_path

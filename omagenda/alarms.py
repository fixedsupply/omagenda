"""Alarm scheduling for `omagenda watch`.

Fires a desktop notification at each event's VALARM trigger time (or a
per-calendar default lead -- not yet configurable, Phase 4), with --exec
opening the conference link when one exists. Deduplicated across restarts
through a small on-disk state file, since `watch` is killed and restarted
constantly (theme changes, shell restarts, logouts) and must never
re-notify for an alarm it already fired. See PLAN.md §6.5.

All-day events have no wall-clock instant to compute a trigger against and
are skipped -- a documented v1 gap, not an oversight (nothing in the
corpus or fixtures needs an all-day reminder yet).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from omagenda.index import resolve_state_dir

FIRED_STATE_FILENAME = "fired-alarms.json"
GRACE_MINUTES = 5  # how far in the past a missed alarm is still worth firing late


def parse_trigger(text: str) -> timedelta:
    """Inverse of index.py's _timedelta_to_iso8601: "-PT15M" -> timedelta(minutes=-15)."""
    match = re.fullmatch(r"(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text)
    if not match:
        raise ValueError(f"not an ISO 8601 duration: {text}")
    sign = -1 if match.group(1) else 1
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups()[1:])
    return sign * timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _load_fired(state_dir: Path) -> set[str]:
    path = state_dir / FIRED_STATE_FILENAME
    try:
        return set(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_fired(state_dir: Path, fired: set[str]) -> None:
    path = state_dir / FIRED_STATE_FILENAME
    # A little pruning so this file doesn't grow forever: keep at most the
    # most recent 2000 keys is unnecessary complexity for v1's event
    # volumes, so it's intentionally left unbounded for now.
    path.write_text(json.dumps(sorted(fired)))


def _default_notify(title: str, message: str, conference_url: str | None) -> None:
    binary = shutil.which("omarchy-notification-send") or "/usr/share/omarchy/bin/omarchy-notification-send"
    command = [binary, "-g", "󰢌", title, message]
    if conference_url:
        command += ["--exec", "xdg-open", conference_url]
    subprocess.run(command, check=False)


def check_and_fire(agenda: dict, state_dir: Path | None = None, now: datetime | None = None,
                    notify=None) -> list[str]:
    """Fire a notification for every alarm whose trigger time has arrived
    (within the grace window) and hasn't already fired. Returns the list
    of newly-fired keys, mainly for tests."""
    state_dir = state_dir or resolve_state_dir()
    now = now or datetime.now().astimezone()
    notify = notify or _default_notify
    fired = _load_fired(state_dir)
    newly_fired = []

    for event in agenda.get("events", []):
        if event["allDay"] or not event.get("alarms"):
            continue
        start = datetime.fromisoformat(event["start"])
        for trigger in event["alarms"]:
            key = f"{event['id']}|{trigger}"
            if key in fired:
                continue
            fire_at = start + parse_trigger(trigger)
            if fire_at > now or fire_at < now - timedelta(minutes=GRACE_MINUTES):
                continue
            conference_url = (event.get("conference") or {}).get("url")
            notify(event["title"], start.strftime("%-I:%M %p"), conference_url)
            fired.add(key)
            newly_fired.append(key)

    if newly_fired:
        _save_fired(state_dir, fired)
    return newly_fired

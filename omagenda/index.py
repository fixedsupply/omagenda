"""Agenda indexing: expand vdir events into agenda.json.

Reads every calendar's .ics files, expands recurrence (including EXDATE and
RECURRENCE-ID exceptions) into concrete occurrences over a date range,
resolves conference links, and writes agenda.json atomically. Backs
`omagenda index`, `agenda`, and `next`. See ARCHITECTURE.md §3-4 and §9.

A note on "recurring": `recurring_ical_events` (with
`keep_recurrence_attributes=True`) stamps a RECURRENCE-ID on *every*
occurrence it returns, including a plain one-off event with no RRULE at
all -- it's the library's way of naming which instant an occurrence
represents, not a signal that the source event recurs. So whether a file's
events are "recurring" is decided once, from the *raw*, unexpanded VEVENT
components (RRULE or RECURRENCE-ID present on any of them means the file
holds a series, master or override), and that one boolean is stamped onto
every occurrence produced from that file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import icalendar
import recurring_ical_events

from omagenda import conference, vdir

DEFAULT_DAYS = 14


def resolve_state_dir() -> Path:
    override = os.environ.get("OMAGENDA_STATE")
    return Path(override).expanduser() if override else Path.home() / ".local" / "state" / "omagenda"


def _timedelta_to_iso8601(td: timedelta) -> str:
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    body = (f"{days}D" if days else "")
    time_body = "".join([
        f"{hours}H" if hours else "",
        f"{minutes}M" if minutes else "",
        f"{seconds}S" if seconds else "",
    ])
    if time_body:
        body += "T" + time_body
    return f"{sign}P{body}" if body else "PT0S"


def _is_recurring_file(raw_components) -> bool:
    return any("RRULE" in c or "RECURRENCE-ID" in c for c in raw_components)


def _source_tz(value) -> str | None:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return getattr(value.tzinfo, "key", str(value.tzinfo))
    return None


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value.isoformat()  # date


def _attendee_count(event) -> int:
    attendees = event.get("ATTENDEE")
    if attendees is None:
        return 0
    return len(attendees) if isinstance(attendees, list) else 1


def _alarms(event) -> list[str]:
    out = []
    for valarm in event.walk("VALARM"):
        trigger = valarm.get("TRIGGER")
        if trigger is not None and isinstance(trigger.dt, timedelta):
            out.append(_timedelta_to_iso8601(trigger.dt))
    return out


def _sort_key(item: dict):
    start = item["start"]
    date_part = start[:10]
    is_timed = 1 if "T" in start else 0
    time_part = start[11:19] if is_timed else "00:00:00"
    return (date_part, is_timed, time_part)


def build_agenda(vdir_root=None, days: int = DEFAULT_DAYS, start: date | None = None,
                  active_set: str = "", last_sync: str | None = None) -> dict:
    start = start or date.today()
    end_span = timedelta(days=days)
    calendars = vdir.discover_calendars(vdir_root)

    events: list[dict] = []
    for cal in calendars:
        for ics_path in vdir.list_ics_files(cal["path"]):
            raw_calendar = vdir.read_ics_file(ics_path)
            raw_components = list(raw_calendar.walk("VEVENT"))
            if not raw_components:
                continue
            recurring = _is_recurring_file(raw_components)
            base_uid = str(raw_components[0].get("UID", ics_path.stem))

            occurrences = recurring_ical_events.of(
                raw_calendar, keep_recurrence_attributes=True
            ).between(start, end_span)

            for occ in occurrences:
                dtstart = occ["DTSTART"].dt
                dtend = occ["DTEND"].dt if occ.get("DTEND") else dtstart
                all_day = not isinstance(dtstart, datetime)
                occ_id = f"{cal['id']}/{base_uid}"
                if recurring:
                    occ_id += f"/{_iso(dtstart)}"
                events.append({
                    "id": occ_id,
                    "calendar": cal["id"],
                    "title": str(occ.get("SUMMARY", "")),
                    "start": _iso(dtstart),
                    "end": _iso(dtend),
                    "allDay": all_day,
                    "sourceTz": _source_tz(dtstart),
                    "location": str(occ.get("LOCATION", "")) or "",
                    "description": str(occ.get("DESCRIPTION", "")) or "",
                    "url": str(occ.get("URL", "")) or "",
                    "conference": conference.detect(occ),
                    "attendees": _attendee_count(occ),
                    "recurring": recurring,
                    "alarms": _alarms(occ),
                    "file": str(ics_path),
                })

    events.sort(key=_sort_key)

    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "range": {"from": start.isoformat(), "to": (start + end_span).isoformat()},
        "lastSync": last_sync,
        "activeSet": active_set,
        "calendars": [{k: v for k, v in c.items()} for c in calendars],
        "events": events,
    }


def write_agenda(agenda: dict, state_dir=None) -> Path:
    state_dir = Path(state_dir).expanduser() if state_dir else resolve_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    final_path = state_dir / "agenda.json"
    fd, tmp_name = tempfile.mkstemp(dir=state_dir, prefix=".agenda-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(agenda, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, final_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return final_path


def index(vdir_root=None, state_dir=None, days: int = DEFAULT_DAYS) -> Path:
    agenda = build_agenda(vdir_root, days=days)
    return write_agenda(agenda, state_dir)

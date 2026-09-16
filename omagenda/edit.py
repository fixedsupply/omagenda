"""Sentence editing that preserves every unrelated iCalendar property byte."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar

from omagenda import index, vdir
from omagenda.event_file import validate_event_file
from omagenda.parse import parse_event


def event_values(event: icalendar.Event, reference: datetime) -> dict:
    start = event.decoded("DTSTART")
    all_day = not isinstance(start, datetime)
    end = event.decoded("DTEND", None)
    if end is None:
        end = start + event.decoded("DURATION", timedelta(days=1) if all_day else timedelta())
    if not all_day:
        start = start.replace(tzinfo=start.tzinfo or reference.tzinfo).astimezone(reference.tzinfo)
        end = end.replace(tzinfo=end.tzinfo or reference.tzinfo).astimezone(reference.tzinfo)
    return {"title": str(event.get("SUMMARY", "")), "start": start, "end": end,
            "allDay": all_day, "location": str(event.get("LOCATION", ""))}


def parsed_values(parsed: dict, reference: datetime) -> dict:
    if parsed["allDay"]:
        start = date.fromisoformat(parsed["start"])
        end = start + timedelta(days=1)
    else:
        zone = ZoneInfo(parsed["tz"]) if parsed["tz"] else reference.tzinfo
        start = datetime.fromisoformat(parsed["start"]).replace(tzinfo=zone).astimezone(reference.tzinfo)
        end = datetime.fromisoformat(parsed["end"]).replace(tzinfo=zone).astimezone(reference.tzinfo)
    return {"title": parsed["title"], "start": start, "end": end,
            "allDay": parsed["allDay"], "location": parsed["location"] or ""}


def same_value(left: object, right: object) -> bool:
    # UTC comparison also distinguishes the two occurrences of a folded hour.
    if isinstance(left, datetime) and isinstance(right, datetime):
        return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)
    return left == right


def parse_sentence(sentence: str, reference: datetime) -> dict:
    return parse_event(sentence, reference=reference,
                       known_calendars=[c["id"] for c in vdir.discover_calendars()])


def describe_event(event_file: str, reference: datetime) -> dict:
    # Read-only, so no sync lock: sync writes by atomic replace, and waiting
    # behind a background sync made `e` look unresponsive for up to a minute.
    # `edit_event` re-validates under the lock before writing anything.
    _, calendar, _, event = validate_event_file(event_file, "edit")
    values = event_values(event, reference)
    start = values["start"]
    month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[start.month - 1]
    # A bare "Sep 10" means the next Sep 10, so a past date must name its year.
    start_date = start if values["allDay"] else start.date()
    needs_year = start.year != reference.year or start_date < reference.date()
    day = f"{month} {start.day}" + (f" {start.year}" if needs_year else "")
    sentence = f"{values['title']} on {day}"
    if values["allDay"]:
        sentence += " all day"
    else:
        minutes = int((values["end"] - start).total_seconds() / 60)
        duration = f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"
        clock = str(start.hour % 12 or 12) + (f":{start.minute:02}" if start.minute else "")
        sentence += f" at {clock}{'pm' if start.hour >= 12 else 'am'} for {duration}"
    if values["location"]:
        sentence += f" at {values['location']}"
    try:
        parsed = parse_sentence(sentence, reference)
        actual = parsed_values(parsed, reference)
        matches = all(same_value(values[key], actual[key]) for key in values)
    except (ValueError, OverflowError):
        matches = False
    if not matches:
        raise ValueError("This event can't be described as a sentence yet")
    return {"sentence": sentence, "calendar": calendar["id"]}


def replace_properties(content: bytes, properties: dict) -> bytes:
    # Work on logical lines, retaining their original folding and line endings.
    # Only direct VEVENT properties are touched; VALARM and VTIMEZONE stay intact.
    chunks: list[bytes] = []
    for line in content.splitlines(keepends=True):
        if line.startswith((b" ", b"\t")) and chunks:
            chunks[-1] += line
        else:
            chunks.append(line)
    newline = b"\r\n" if b"\r\n" in content else b"\n"
    replacement = {}
    for key, value in properties.items():
        component = icalendar.Event()
        if value is not None:
            component.add(key, value)
        replacement[key] = component.to_ical().split(b"\r\n", 1)[1].rsplit(b"END:VEVENT", 1)[0].replace(b"\r\n", newline)
    stack: list[bytes] = []
    output = []
    for chunk in chunks:
        head = chunk.splitlines()[0]
        key = re.split(b"[;:]", head, maxsplit=1)[0].decode("ascii").upper()
        if head.upper() == b"END:VEVENT":
            output.extend(replacement.values())
            replacement.clear()
        if stack and stack[-1] == b"VEVENT" and key in properties:
            if key in replacement:
                output.append(replacement.pop(key))
            continue
        output.append(chunk)
        if head.upper().startswith(b"BEGIN:"):
            stack.append(head[6:].upper())
        elif head.upper().startswith(b"END:"):
            stack.pop()
    return b"".join(output)


def atomic_bytes(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".edit-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_previous(path: Path, calendar_id: str, content: bytes) -> Path:
    parent = index.resolve_state_dir() / "edited"
    folder = parent / (re.sub(r"[^A-Za-z0-9_-]", "_", calendar_id) or "calendar")
    if folder.resolve().is_relative_to(vdir.resolve_vdir_root().expanduser().resolve()):
        raise ValueError("Edit copies must be stored outside the vdir")
    for directory in (parent, folder):
        if directory.is_symlink():
            raise ValueError("Edit copy folders must not be symlinks")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    saved = folder / f"{path.stem}.{stamp}.ics"
    atomic_bytes(saved, content)
    return saved


def edit_event(event_file: str, sentence: str, reference: datetime, dry_run: bool = False) -> dict:
    from omagenda.sync import _sync_lock

    with _sync_lock():
        path, calendar, content, event = validate_event_file(event_file, "edit")
        parsed = parse_sentence(sentence, reference)
        if parsed["calendar"] and parsed["calendar"] != calendar["id"]:
            raise ValueError("Moving events between calendars isn't supported yet")
        if parsed["rrule"] or parsed["alarms"]:
            raise ValueError("Changing recurrence or alerts through sentence editing isn't supported yet")
        before, after = event_values(event, reference), parsed_values(parsed, reference)
        properties = {}
        for field, key in (("title", "SUMMARY"), ("start", "DTSTART"), ("location", "LOCATION")):
            if not same_value(before[field], after[field]):
                properties[key] = after[field] if field != "location" else after[field] or None
        if "DURATION" in event:
            duration = after["end"] - after["start"]
            times_changed = any(not same_value(before[key], after[key]) for key in ("start", "end"))
            if times_changed and duration != event.decoded("DURATION"):
                properties["DURATION"] = duration
        elif not same_value(before["end"], after["end"]):
            properties["DTEND"] = after["end"]
        result = {"updated": bool(properties), "title": after["title"], "calendar": calendar["id"],
                  "file": str(path), "changed": list(properties), "copy": None, "name": calendar["name"]}
        if not properties or dry_run:
            return result
        now = datetime.now(timezone.utc)
        properties.update(SEQUENCE=int(event.get("SEQUENCE", 0)) + 1, DTSTAMP=now, **{"LAST-MODIFIED": now})
        updated = replace_properties(content, properties)
        saved = save_previous(path, calendar["id"], content)
        atomic_bytes(path, updated)
        result["copy"] = str(saved)
        try:
            index.index()
        except Exception as exc:
            raise RuntimeError(f"Event updated; copy is at {saved}, but agenda rebuild failed: {exc}") from exc
        return result

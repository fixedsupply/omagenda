"""Shared file and calendar safeguards for event mutations."""
from pathlib import Path

import icalendar

from omagenda import vdir


def validate_event_file(event_file: str, action: str = "delete") -> tuple:
    participle = "deleted" if action == "delete" else "edited"
    root_given = vdir.resolve_vdir_root().expanduser().absolute()
    root = root_given.resolve()
    given = Path(event_file).expanduser().absolute()
    # A symlink inside the vdir could alias another calendar's file, so those
    # are refused. Symlinks above it (a symlinked home, or a vdir folder that
    # is itself a link) are ordinary setups and must not block editing or deletion.
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
        raise ValueError(f"'{name}' is read-only, so its events can't be {participle} here")
    content = path.read_bytes()
    parsed = icalendar.Calendar.from_ical(content)
    if any(key in component for component in parsed.walk()
           for key in ("RRULE", "RDATE", "RECURRENCE-ID")):
        raise ValueError(f"Recurring events can't be {participle} from Omagenda yet; {action} it in {name}'s own app")
    events = parsed.walk("VEVENT")
    if len(events) != 1:
        raise ValueError(f"Event file must contain exactly one VEVENT to be {participle}")
    if action == "edit" and "ATTENDEE" in events[0]:
        raise ValueError(f"Events with guests can't be edited from Omagenda yet; edit it in {name}'s own app")
    return path, calendar, content, events[0]

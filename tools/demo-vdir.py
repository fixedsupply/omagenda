#!/usr/bin/env python3
"""Build a synthetic vdir for screenshots and demos.

The maintainer's own calendar is not test data (AGENTS.md), and a
screenshot is the easiest way to leak it: a panel holds a week of real
appointments, and a repo keeps them forever. An earlier screenshot went
out with a real child's first name in it, which is exactly the failure
this script exists to make unnecessary.

Everything below is invented. Names are deliberately generic-fictional,
the week is anchored to a fixed weekday pattern so the ticker always
looks the same, and there are no VALARMs so a watcher pointed at this
never fires a notification.

    python3 tools/demo-vdir.py /tmp/omagenda-demo
    OMAGENDA_VDIR=/tmp/omagenda-demo omagenda watch --no-sync

Pointing a *syncing* watcher at this would read every real event as
deleted and push those deletions to the server. Always use --no-sync.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

CALENDARS = [
    ("work", "Work", "blue"),
    ("personal", "Personal", "green"),
    ("family", "Family", "magenta"),
]

# (calendar, days from today, start hour:minute, minutes, title, location,
#  conference url or "")
#
# Anchored to today rather than to a weekday, so day 0 is always a full,
# representative day whenever the screenshots are retaken.
EVENTS = [
    ("family", 0, None, 0, "School PD day", "", ""),
    ("work", 0, (9, 30), 15, "Standup", "", "https://meet.google.com/xxx-yyyy-zzz"),
    ("work", 0, (11, 30), 30, "1:1 with Priya", "Room 204", ""),
    ("personal", 0, (15, 30), 30, "Pick up the kids", "", ""),
    ("personal", 0, (18, 30), 90, "Climbing", "The Wall", ""),
    ("work", 1, (9, 30), 15, "Standup", "", "https://meet.google.com/xxx-yyyy-zzz"),
    ("work", 1, (14, 0), 60, "Design review", "Room 204", ""),
    ("work", 2, (9, 30), 15, "Standup", "", "https://meet.google.com/xxx-yyyy-zzz"),
    ("family", 2, (17, 0), 60, "Swimming lessons", "Aquatic Centre", ""),
    ("work", 3, (9, 30), 15, "Standup", "", "https://meet.google.com/xxx-yyyy-zzz"),
    ("work", 3, (13, 0), 45, "Retro", "", "https://meet.google.com/xxx-yyyy-zzz"),
    ("personal", 4, (12, 30), 60, "Lunch with Sam", "Cafe Torino", ""),
    ("family", 5, None, 0, "A birthday", "", ""),
    ("personal", 6, (10, 0), 120, "Long run", "River path", ""),
]


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S")


def build(root: Path, week_of: date | None = None) -> None:
    start_day = week_of or date.today()

    for cal_id, display, colour in CALENDARS:
        folder = root / cal_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "displayname").write_text(display, encoding="utf-8")
        (folder / "color").write_text(colour, encoding="utf-8")

    for index, (cal_id, offset, start, minutes, title, location, url) in enumerate(EVENTS):
        day = start_day + timedelta(days=offset)
        uid = f"demo-{index}@omagenda.example"
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Omagenda//demo//EN",
                 "BEGIN:VEVENT", f"UID:{uid}",
                 f"DTSTAMP:{_stamp(datetime(2026, 1, 1, 12, 0))}Z"]
        if start is None:
            lines += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}"]
        else:
            begins = datetime.combine(day, datetime.min.time()).replace(hour=start[0], minute=start[1])
            lines += [f"DTSTART:{_stamp(begins)}", f"DTEND:{_stamp(begins + timedelta(minutes=minutes))}"]
        lines.append(f"SUMMARY:{title}")
        if location:
            lines.append(f"LOCATION:{location}")
        if url:
            lines.append(f"DESCRIPTION:Join: {url}")
        lines += ["END:VEVENT", "END:VCALENDAR"]
        (root / cal_id / f"{uid}.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    print(f"{len(EVENTS)} demo events in {len(CALENDARS)} calendars at {root}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <directory>")
    build(Path(sys.argv[1]).expanduser())

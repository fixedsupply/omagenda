"""Conference-link detection (Join).

Recognizes Meet, Zoom, Teams, Webex, Jitsi, and Whereby links from an
event's conference property, location, and description. See PLAN.md §6.2
and ARCHITECTURE.md §4.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("meet", re.compile(r"https?://meet\.google\.com/[a-z0-9-]+", re.I)),
    ("zoom", re.compile(r"https?://[\w.-]*zoom\.us/(?:j|my)/[\w?=&./-]+", re.I)),
    ("teams", re.compile(r"https?://teams\.microsoft\.com/l/meetup-join/\S+", re.I)),
    ("webex", re.compile(r"https?://[\w.-]*webex\.com/\S+", re.I)),
    ("jitsi", re.compile(r"https?://meet\.jit\.si/\S+", re.I)),
    ("whereby", re.compile(r"https?://whereby\.com/\S+", re.I)),
]

_SOURCE_PROPERTIES = ("X-GOOGLE-CONFERENCE", "CONFERENCE", "LOCATION", "DESCRIPTION", "URL")


def detect(event) -> dict | None:
    """Return {"provider": ..., "url": ...} for the first recognized
    conference link found on the event, or None."""
    for prop in _SOURCE_PROPERTIES:
        value = event.get(prop)
        if not value:
            continue
        text = str(value)
        for provider, pattern in _PATTERNS:
            match = pattern.search(text)
            if match:
                return {"provider": provider, "url": match.group(0).rstrip(".,)")}
    return None

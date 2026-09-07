"""Deterministic natural-language event parser.

Single pass over tokens, no network, no LLM, no silent guessing: an
ambiguous construct resolves to the documented default and records a
warning rather than picking silently. The grammar this module implements
is documented rule-by-rule in nl_grammar.md; the corpus in
tests/test_parse.py is the executable specification -- when the two
disagree, one of them is wrong.

Extraction runs as a fixed sequence of passes over the sentence: calendar
tag, alert, recurrence (including its own trailing "until"/"for N weeks"),
date, time, duration, time zone, location, and finally whatever is left
becomes the title. Each pass only claims characters no earlier pass has
already claimed, via the Cursor below -- this is what lets "at 1pm" (time)
and "at Cafe Linnea" (location) coexist in one sentence without the
location pass mis-claiming the first "at".
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_ABBR = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
]
MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

TZ_ABBREVIATIONS = {
    "est": "America/New_York",
    "cet": "Europe/Berlin",
    "pst": "America/Los_Angeles",
    "jst": "Asia/Tokyo",
    "gmt": "Europe/London",
}


class Cursor:
    """Tracks which characters of the sentence a pass has already claimed."""

    def __init__(self, text: str):
        self.text = text
        self.claimed = [False] * len(text)
        self.spans: list[dict] = []

    def free(self, start: int, end: int) -> bool:
        return not any(self.claimed[start:end])

    def claim(self, start: int, end: int, kind: str) -> None:
        for i in range(start, end):
            self.claimed[i] = True
        self.spans.append({"start": start, "end": end, "kind": kind})

    def next_claim_after(self, index: int) -> int:
        """The index of the next already-claimed character at or after
        `index`, or len(text) if nothing further is claimed. Used by the
        location pass to know where its span has to stop."""
        for i in range(index, len(self.text)):
            if self.claimed[i]:
                return i
        return len(self.text)

    def title(self) -> str:
        chars = [c if not claimed else " " for c, claimed in zip(self.text, self.claimed)]
        collapsed = re.sub(r"\s+", " ", "".join(chars)).strip()
        return re.sub(r"\s+(?:by|on|at|in|for)$", "", collapsed, flags=re.I)


def _day_index(name: str) -> int:
    name = name.lower()
    if name in DAY_NAMES:
        return DAY_NAMES.index(name)
    return DAY_ABBR.index(name[:3])


def _month_index(name: str) -> int:
    name = name.lower()
    if name in MONTH_NAMES:
        return MONTH_NAMES.index(name) + 1
    return MONTH_ABBR.index(name[:3]) + 1


def _ordinal_pattern() -> str:
    return r"(\d{1,2})(?:st|nd|rd|th)?"


# ---------------------------------------------------------------------
# Calendar tag: /name
# ---------------------------------------------------------------------
_CALENDAR_RE = re.compile(r"(?<!\S)/(\w[\w-]*)")


def _extract_calendar(cursor: Cursor, known_calendars: list[str] | None) -> tuple[str | None, list[str]]:
    warnings = []
    match = _CALENDAR_RE.search(cursor.text)
    if not match or not cursor.free(match.start(), match.end()):
        return None, warnings
    cursor.claim(match.start(), match.end(), "calendar")
    name = match.group(1).lower()
    if not known_calendars:
        return name, warnings
    matches = [c for c in known_calendars if c.lower().startswith(name)]
    if matches:
        return matches[0].lower(), warnings
    warnings.append(f"no calendar matches '/{name}'; using the default calendar")
    return None, warnings


# ---------------------------------------------------------------------
# Alerts: "alert 15m", "alert 1 day before", "remind me 10 min before"
# ---------------------------------------------------------------------
_ALERT_RES = [
    (re.compile(r"\b(?:alert|remind me)\s+(\d+)\s*(?:m|min|mins|minutes?)\b(?:\s+before)?", re.I), "M"),
    (re.compile(r"\b(?:alert|remind me)\s+(\d+)\s*(?:h|hours?)\b(?:\s+before)?", re.I), "H"),
    (re.compile(r"\b(?:alert|remind me)\s+(1)\s+days?\s+before\b", re.I), "D"),  # only "1 day before" is defined
]
_ALERT_UNSUPPORTED_RE = re.compile(r"\balert\s+\d+\s+days?\s+before\b", re.I)


def _extract_alerts(cursor: Cursor) -> tuple[list[str], list[str]]:
    warnings = []
    alarms = []
    for pattern, unit in _ALERT_RES:
        for match in pattern.finditer(cursor.text):
            if not cursor.free(match.start(), match.end()):
                continue
            cursor.claim(match.start(), match.end(), "alarm")
            alarms.append(f"-PT{match.group(1)}{unit}" if unit != "D" else f"-P{match.group(1)}D")
    return alarms, warnings


def _warn_unsupported_alerts(cursor: Cursor) -> list[str]:
    # "alert N days before" isn't documented (only minutes, hours, and the
    # single fixed phrase "N day before" are) -- flag it without consuming
    # it, so it stays visible in the title rather than vanishing silently.
    warnings = []
    for match in re.finditer(r"\balert\s+(\d+)\s+days?\s+before\b", cursor.text, re.I):
        if int(match.group(1)) != 1 and cursor.free(match.start(), match.end()):
            warnings.append(f"'{match.group(0)}' isn't a supported reminder phrasing; no reminder was set")
    return warnings


# ---------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------
def _resolve_trailing_until_or_count(cursor: Cursor, after: int, reference: datetime) -> tuple[str, list[str]]:
    """Look for "until <phrase>" or "for N weeks" anywhere later in the
    sentence (not necessarily right after the recurrence phrase -- "every
    weekday at 9am until Dec 25" has a time expression in between).
    Claims only the found phrase's own span, leaving the text between it
    and the recurrence phrase free for other passes (the "at 9am" in that
    example). Returns (suffix_to_append_to_rrule, warnings)."""
    warnings = []
    remainder = cursor.text[after:]

    until_match = re.search(r"\buntil\s+([a-z0-9 ]+?)(?=[.,;/]|$)", remainder, re.I)
    if until_match:
        start, end = after + until_match.start(), after + until_match.end()
        if cursor.free(start, end):
            phrase = until_match.group(1).strip()
            resolved, _, _ = _parse_date_phrase(phrase, reference)
            cursor.claim(start, end, "recurrence")
            if resolved:
                return f";UNTIL={resolved.strftime('%Y%m%d')}", warnings
            warnings.append(f"'until {phrase}' isn't a date Omagenda can resolve; the recurrence has no end date")
            return "", warnings

    count_match = re.search(r"\bfor\s+(\d+)\s+weeks?\b", remainder, re.I)
    if count_match:
        start, end = after + count_match.start(), after + count_match.end()
        if cursor.free(start, end):
            cursor.claim(start, end, "recurrence")
            return f";COUNT={count_match.group(1)}", warnings

    return "", warnings


_RECURRENCE_PATTERNS = [
    (re.compile(r"\bevery\s+weekday\b", re.I), lambda m: "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"),
    (re.compile(r"\bevery\s+(\d+)\s+days?\b", re.I), lambda m: f"FREQ=DAILY;INTERVAL={m.group(1)}"),
    (re.compile(r"\b(?:every\s+day|daily)\b", re.I), lambda m: "FREQ=DAILY"),
    (re.compile(r"\bevery\s+(\d+)\s+weeks?\b", re.I), lambda m: f"FREQ=WEEKLY;INTERVAL={m.group(1)}"),
    (
        re.compile(rf"\bevery\s+({'|'.join(DAY_NAMES + DAY_ABBR)})\s+and\s+({'|'.join(DAY_NAMES + DAY_ABBR)})\b", re.I),
        lambda m: f"FREQ=WEEKLY;BYDAY={DAY_CODES[_day_index(m.group(1))]},{DAY_CODES[_day_index(m.group(2))]}",
    ),
    (
        re.compile(rf"\bevery\s+({'|'.join(DAY_NAMES + DAY_ABBR)})\b", re.I),
        lambda m: f"FREQ=WEEKLY;BYDAY={DAY_CODES[_day_index(m.group(1))]}",
    ),
    (
        re.compile(rf"\bweekly\s+on\s+({'|'.join(DAY_NAMES + DAY_ABBR)})\b", re.I),
        lambda m: f"FREQ=WEEKLY;BYDAY={DAY_CODES[_day_index(m.group(1))]}",
    ),
    (
        re.compile(rf"\b(?:monthly|every\s+month)\s+on\s+the\s+{_ordinal_pattern()}\b", re.I),
        lambda m: f"FREQ=MONTHLY;BYMONTHDAY={int(m.group(1))}",
    ),
    (re.compile(r"\byearly\b", re.I), lambda m: "FREQ=YEARLY"),
    (re.compile(r"\bweekly\b", re.I), lambda m: "FREQ=WEEKLY"),
]


def _extract_recurrence(cursor: Cursor, reference: datetime) -> tuple[str | None, list[str]]:
    warnings = []
    best = None
    # Patterns are ordered most- to least-specific (a weekday list before a
    # single weekday, a single weekday before bare "weekly"). The first
    # pattern in that order with any free match wins the sentence, rather
    # than whichever pattern's match happens to start earliest in the
    # string -- otherwise a title like "Weekly 1:1 with my manager every
    # tuesday..." would let the generic "weekly" at word 1 pre-empt the
    # far more specific "every tuesday" that appears right after it.
    for pattern, build in _RECURRENCE_PATTERNS:
        for match in pattern.finditer(cursor.text):
            if cursor.free(match.start(), match.end()):
                best = (match, build)
                break
        if best:
            break
    if best is None:
        return None, warnings
    match, build = best
    rrule = build(match)
    cursor.claim(match.start(), match.end(), "recurrence")
    suffix, extra_warnings = _resolve_trailing_until_or_count(cursor, match.end(), reference)
    warnings.extend(extra_warnings)
    return rrule + suffix, warnings


# ---------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------
def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _next_weekday(ref_date: date, target: int, skip_one_more: bool) -> date:
    delta = (target - ref_date.weekday()) % 7
    result = ref_date + timedelta(days=delta)
    if skip_one_more:
        result += timedelta(days=7)
    return result


def _month_day_this_or_next_year(ref_date: date, month: int, day: int) -> date:
    candidate = date(ref_date.year, month, day)
    if candidate < ref_date:
        candidate = date(ref_date.year + 1, month, day)
    return candidate


def _ordinal_this_or_next_month(ref_date: date, day: int) -> date:
    year, month = ref_date.year, ref_date.month
    candidate = date(year, month, day)
    if candidate < ref_date:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        candidate = date(year, month, day)
    return candidate


_DATE_PATTERNS_SIMPLE = [
    (re.compile(r"\btoday\b", re.I), lambda m, rd: rd),
    (re.compile(r"\b(?:tomorrow|tmrw)\b", re.I), lambda m, rd: rd + timedelta(days=1)),
    (re.compile(r"\bend of month\b", re.I), lambda m, rd: date(rd.year, rd.month, _last_day_of_month(rd.year, rd.month))),
]


def _parse_date_phrase(phrase: str, reference: datetime) -> tuple[date | None, str | None, list[str]]:
    """Try to resolve a standalone date phrase (used for recurrence UNTIL
    clauses). Returns (date_or_None, matched_kind, warnings). Does not
    touch a Cursor -- callers decide what to claim."""
    rd = reference.date()
    for pattern, resolver in _DATE_PATTERNS_SIMPLE:
        m = pattern.fullmatch(phrase.strip())
        if m:
            return resolver(m, rd), "date", []
    m = re.fullmatch(rf"({'|'.join(MONTH_NAMES + MONTH_ABBR)})\s+(\d{{1,2}})", phrase.strip(), re.I)
    if m:
        return _month_day_this_or_next_year(rd, _month_index(m.group(1)), int(m.group(2))), "date", []
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", phrase.strip())
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "date", []
    return None, None, []


_ALL_DAY_RE = re.compile(r"\ball day\b", re.I)


def _extract_date(cursor: Cursor, reference: datetime) -> tuple[date | None, list[str]]:
    warnings = []
    rd = reference.date()
    text = cursor.text

    m = _ALL_DAY_RE.search(text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "duration")

    for pattern, resolver in _DATE_PATTERNS_SIMPLE:
        m = pattern.search(text)
        if m and cursor.free(m.start(), m.end()):
            cursor.claim(m.start(), m.end(), "date")
            return resolver(m, rd), warnings

    m = re.search(r"\bin\s+(\d+)\s+days?\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return rd + timedelta(days=int(m.group(1))), warnings

    m = re.search(r"\bin\s+(\d+)\s+weeks?\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return rd + timedelta(days=int(m.group(1)) * 7), warnings

    m = re.search(r"\bnext\s+(" + "|".join(DAY_NAMES + DAY_ABBR) + r")\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _next_weekday(rd, _day_index(m.group(1)), skip_one_more=True), warnings

    m = re.search(r"\bthis\s+(" + "|".join(DAY_NAMES + DAY_ABBR) + r")\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _next_weekday(rd, _day_index(m.group(1)), skip_one_more=False), warnings

    m = re.search(r"\b(" + "|".join(DAY_NAMES + DAY_ABBR) + r")\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _next_weekday(rd, _day_index(m.group(1)), skip_one_more=False), warnings

    m = re.search(r"\b(?:on\s+the\s+|the\s+)" + _ordinal_pattern() + r"\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _ordinal_this_or_next_month(rd, int(m.group(1))), warnings

    m = re.search(rf"\b({'|'.join(MONTH_NAMES + MONTH_ABBR)})\s+(\d{{1,2}})\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _month_day_this_or_next_year(rd, _month_index(m.group(1)), int(m.group(2))), warnings

    m = re.search(rf"\b(\d{{1,2}})\s+({'|'.join(MONTH_NAMES + MONTH_ABBR)})\b", text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return _month_day_this_or_next_year(rd, _month_index(m.group(2)), int(m.group(1))), warnings

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "date")
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), warnings

    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if m and cursor.free(m.start(), m.end()):
        a, b = int(m.group(1)), int(m.group(2))

        def _valid_month_day(month, day):
            return 1 <= month <= 12 and 1 <= day <= _last_day_of_month(rd.year, month)

        day_first_valid = _valid_month_day(b, a)      # a=day, b=month
        month_first_valid = _valid_month_day(a, b)    # a=month, b=day
        resolved = None
        if day_first_valid and month_first_valid and (a, b) != (b, a):
            resolved = _month_day_this_or_next_year(rd, b, a)
            other = _month_day_this_or_next_year(rd, a, b)
            if resolved != other:
                warnings.append(
                    f"'{m.group(0)}' could be day-first ({resolved:%b %d}) or month-first ({other:%b %d}); assuming day-first"
                )
        elif day_first_valid:
            resolved = _month_day_this_or_next_year(rd, b, a)
        elif month_first_valid:
            resolved = _month_day_this_or_next_year(rd, a, b)
        else:
            warnings.append(f"'{m.group(0)}' isn't a valid date in either day-first or month-first order")
            return None, warnings
        cursor.claim(m.start(), m.end(), "date")
        return resolved, warnings

    return None, warnings


# ---------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------
_NAMED_TIMES = {
    "noon": (12, 0), "midnight": (0, 0), "morning": (9, 0),
    "afternoon": (14, 0), "evening": (19, 0), "tonight": (20, 0),
}


def _clock_to_24h(hour: int, ampm: str | None, business_default: bool = False) -> tuple[int, list[str]]:
    warnings = []
    if ampm:
        if ampm.lower() == "pm" and hour != 12:
            hour += 12
        if ampm.lower() == "am" and hour == 12:
            hour = 0
        return hour, warnings
    if business_default:
        if hour == 12:
            pass  # noon
        elif 7 <= hour <= 11:
            pass  # already a sensible morning hour
        elif 1 <= hour <= 6:
            hour += 12
        return hour, warnings
    return hour, warnings


def _extract_time_range(cursor: Cursor) -> tuple[tuple[int, int] | None, tuple[int, int] | None, list[str]]:
    warnings = []
    m = re.search(r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+to\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", cursor.text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "time")
        ampm1 = m.group(3) or m.group(6)
        ampm2 = m.group(6) or m.group(3)
        h1, _ = _clock_to_24h(int(m.group(1)), ampm1)
        h2, _ = _clock_to_24h(int(m.group(4)), ampm2)
        return (h1, int(m.group(2) or 0)), (h2, int(m.group(5) or 0)), warnings

    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+to\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", cursor.text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "time")
        h1, _ = _clock_to_24h(int(m.group(1)), m.group(3))
        h2, _ = _clock_to_24h(int(m.group(4)), m.group(6))
        return (h1, int(m.group(2) or 0)), (h2, int(m.group(5) or 0)), warnings

    m = re.search(r"\b(\d{1,2})-(\d{1,2})\s*(am|pm)\b", cursor.text, re.I)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "time")
        h1, _ = _clock_to_24h(int(m.group(1)), m.group(3))
        h2, _ = _clock_to_24h(int(m.group(2)), m.group(3))
        return (h1, 0), (h2, 0), warnings

    return None, None, warnings


_CLOCK_WITH_MINUTES_RE = re.compile(r"\bat\s+(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", re.I)
_CLOCK_BARE_RE = re.compile(r"\bat\s+(\d{1,2})\s*(am|pm)?\b", re.I)
_CLOCK_STANDALONE_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b")


def _extract_time(cursor: Cursor) -> tuple[tuple[int, int] | None, list[str]]:
    warnings = []

    for name, (h, mnt) in _NAMED_TIMES.items():
        m = re.search(rf"\b{name}\b", cursor.text, re.I)
        if m and cursor.free(m.start(), m.end()):
            cursor.claim(m.start(), m.end(), "time")
            return (h, mnt), warnings

    # An explicit minute component (":00", ".30") is never ambiguous --
    # nobody says "13:00pm" -- so this path never warns or applies the
    # business-hour default, even when the hour alone would be <= 12.
    m = _CLOCK_WITH_MINUTES_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        hour = int(m.group(1))
        h, _ = _clock_to_24h(hour, m.group(3))
        cursor.claim(m.start(), m.end(), "time")
        return (h, int(m.group(2))), warnings

    # A bare hour with no minutes and no am/pm is where the real ambiguity
    # lives: "at 3" could be 3am or 3pm, so this is the one path that
    # applies the business-hour default and always warns about it.
    m = _CLOCK_BARE_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        hour = int(m.group(1))
        ampm = m.group(2)
        if ampm:
            h, _ = _clock_to_24h(hour, ampm)
        else:
            h, _ = _clock_to_24h(hour, None, business_default=True)
            warnings.append(
                f"'at {hour}' has no am/pm, so it's read as {h if h <= 12 else h - 12}"
                f"{'am' if h < 12 else 'pm'} -- say '{hour}am' or '{hour}pm' to be exact"
            )
        cursor.claim(m.start(), m.end(), "time")
        return (h, 0), warnings

    m = _CLOCK_STANDALONE_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        hour = int(m.group(1))
        h, _ = _clock_to_24h(hour, m.group(3))
        cursor.claim(m.start(), m.end(), "time")
        return (h, int(m.group(2))), warnings

    return None, warnings


# ---------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------
_DURATION_RE = re.compile(r"\bfor\s+(\d+(?:\.\d+)?)\s*(min|mins|minutes?|m|h|hours?|hr)\b", re.I)
_DURATION_UNSUPPORTED_RE = re.compile(r"\bfor\s+(\d+(?:\.\d+)?)\s*(weeks?|days?)\b", re.I)


def _extract_duration(cursor: Cursor) -> tuple[int | None, list[str]]:
    warnings = []
    m = _DURATION_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "duration")
        value = float(m.group(1))
        unit = m.group(2).lower()
        minutes = value * 60 if unit.startswith("h") else value
        return int(round(minutes)), warnings

    m = _DURATION_UNSUPPORTED_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "duration")
        warnings.append(f"'{m.group(0)}' isn't a supported duration (only minutes and hours are)")
        return None, warnings

    return None, warnings


# ---------------------------------------------------------------------
# Time zone
# ---------------------------------------------------------------------
_TZ_ABBR_RE = re.compile(r"\b(" + "|".join(TZ_ABBREVIATIONS) + r")\b", re.I)
_TZ_IANA_RE = re.compile(r"\b([A-Za-z]+/[A-Za-z_]+)\b")


def _extract_timezone(cursor: Cursor, local_tz: str | None) -> tuple[str | None, list[str]]:
    warnings = []
    m = _TZ_IANA_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "tz")
        return m.group(1), warnings
    m = _TZ_ABBR_RE.search(cursor.text)
    if m and cursor.free(m.start(), m.end()):
        cursor.claim(m.start(), m.end(), "tz")
        return TZ_ABBREVIATIONS[m.group(1).lower()], warnings
    return local_tz, warnings


# ---------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------
_LOCATION_KEYWORD_RE = re.compile(r"\b(?:at|in)\s+|@\s+", re.I)


def _extract_location(cursor: Cursor) -> tuple[str | None, list[str]]:
    warnings = []
    for m in _LOCATION_KEYWORD_RE.finditer(cursor.text):
        if not cursor.free(m.start(), m.end()):
            continue
        stop = cursor.next_claim_after(m.end())
        value = cursor.text[m.end():stop].strip().rstrip(".,;")
        if not value:
            continue
        cursor.claim(m.start(), m.end() + len(cursor.text[m.end():stop]) - len(cursor.text[m.end():stop].lstrip()) + len(value), "location")
        return value, warnings
    return None, warnings


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------
def parse_event(sentence: str, reference: datetime, known_calendars: list[str] | None = None) -> dict:
    cursor = Cursor(sentence)
    warnings: list[str] = []

    calendar, w = _extract_calendar(cursor, known_calendars)
    warnings += w

    alarms, w = _extract_alerts(cursor)
    warnings += w
    warnings += _warn_unsupported_alerts(cursor)

    rrule, w = _extract_recurrence(cursor, reference)
    warnings += w

    resolved_date, w = _extract_date(cursor, reference)
    warnings += w
    if resolved_date:
        event_date = resolved_date
    else:
        # No separate date token was found. If the recurrence phrase named
        # exactly one weekday ("every tuesday", "weekly on wednesday"),
        # that weekday IS the implied date for the event's own anchor --
        # its keyword was consumed whole by the recurrence pass, so the
        # date pass never got a chance to see it on its own.
        single_day = re.fullmatch(r"FREQ=\w+;BYDAY=([A-Z]{2})(?:;.*)?", rrule or "")
        if single_day:
            event_date = _next_weekday(reference.date(), DAY_CODES.index(single_day.group(1)), skip_one_more=False)
        else:
            event_date = reference.date()

    range_start, range_end, w = _extract_time_range(cursor)
    warnings += w
    if range_start:
        start_h, start_m = range_start
        end_h, end_m = range_end
    else:
        single, w = _extract_time(cursor)
        warnings += w
        if single:
            start_h, start_m = single
        else:
            start_h = start_m = None
        end_h = end_m = None

    duration_minutes, w = _extract_duration(cursor)
    warnings += w

    local_tz = getattr(reference.tzinfo, "key", None)
    tz, w = _extract_timezone(cursor, local_tz)
    warnings += w

    location, w = _extract_location(cursor)
    warnings += w

    all_day = start_h is None
    result: dict = {
        "title": cursor.title() or sentence.strip(),
        "allDay": all_day,
        "calendar": calendar,
        "location": location,
        "rrule": rrule,
        "alarms": alarms,
        "tz": tz,
        "warnings": warnings,
        "spans": sorted(cursor.spans, key=lambda s: s["start"]),
    }

    if all_day:
        result["start"] = event_date.isoformat()
    else:
        result["start"] = datetime(event_date.year, event_date.month, event_date.day, start_h, start_m).isoformat(timespec="minutes")
        if end_h is not None:
            end_dt = datetime(event_date.year, event_date.month, event_date.day, end_h, end_m)
        elif duration_minutes is not None:
            end_dt = datetime(event_date.year, event_date.month, event_date.day, start_h, start_m) + timedelta(minutes=duration_minutes)
        else:
            end_dt = datetime(event_date.year, event_date.month, event_date.day, start_h, start_m) + timedelta(minutes=60)
        result["end"] = end_dt.isoformat(timespec="minutes")

    return result

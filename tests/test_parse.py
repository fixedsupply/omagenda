"""The natural-language parser corpus.

This is the executable specification for `omagenda.parse`, matching
`omagenda/nl_grammar.md` rule for rule. Phase 0 defines the corpus before
Phase 1 makes it pass (AGENTS.md); until then every case is an expected
failure so the suite reports a clean, if trivial, run.

Target API (Phase 1 implements this): `omagenda.parse.parse_event(sentence,
reference)` returns a dict with keys `title`, `start`, `end`, `allDay`,
`calendar`, `location`, `rrule`, `alarms`, `tz`, `warnings` — the same shape
`omagenda parse --json` reports, minus `ok` and `spans` (those are the CLI
and overlay concerns, not the grammar's). `start`/`end` are ISO date
(`YYYY-MM-DD`) for all-day events or ISO local datetime with no offset
(`YYYY-MM-DDTHH:MM`) otherwise — offset and DST resolution is
recurrence/index territory, covered by `tests/test_index.py`, not this file.

A case only asserts the keys present in its `expect` dict, so each one
names just the rule it is testing. `warns=True` asserts `warnings` is
non-empty; `warns=False` (the default) asserts it is empty.

Reference instant for every case below: **Monday 2026-09-07, 09:00,
America/Edmonton** — a fixed point so the corpus is reproducible. Dates in
`expect` were computed independently with plain `datetime`/`timedelta`
arithmetic (see the comments), not with any code shared with the parser.
"""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

REFERENCE = datetime(2026, 9, 7, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
assert REFERENCE.strftime("%A") == "Monday"

# ---------------------------------------------------------------------------
# Dates (nl_grammar.md "Dates")
# ---------------------------------------------------------------------------
DATE_CASES = [
    ("Lunch today", {"title": "Lunch", "start": "2026-09-07", "allDay": True}),
    ("Lunch tomorrow", {"start": "2026-09-08", "allDay": True}),
    ("Lunch tmrw", {"start": "2026-09-08", "allDay": True}),
    ("Call mom monday", {"start": "2026-09-07"}),  # bare weekday, today is Monday
    ("Call mom tuesday", {"start": "2026-09-08"}),
    ("Call mom wednesday", {"start": "2026-09-09"}),
    ("Call mom thursday", {"start": "2026-09-10"}),
    ("Call mom friday", {"start": "2026-09-11"}),
    ("Call mom saturday", {"start": "2026-09-12"}),
    ("Call mom sunday", {"start": "2026-09-13"}),
    ("Call mom this friday", {"start": "2026-09-11"}),
    ("Call mom next friday", {"start": "2026-09-18"}),  # the one after the coming one
    ("Call mom next monday", {"start": "2026-09-14"}),  # bare monday is today, next is +7
    ("Call mom next tuesday", {"start": "2026-09-15"}),
    ("Team sync on the 14th", {"start": "2026-09-14"}),
    ("Team sync on the 3rd", {"start": "2026-10-03"}),  # 3rd already passed this month
    ("Dentist Sep 14", {"start": "2026-09-14"}),
    ("Dentist 14 Sep", {"start": "2026-09-14"}),
    ("Dentist September 14", {"start": "2026-09-14"}),
    ("Holiday party Dec 25", {"start": "2026-12-25"}),
    ("Ski trip Jan 3", {"start": "2027-01-03"}),  # already passed this year, rolls to next
    ("Board meeting 2026-09-14", {"start": "2026-09-14"}),
    ("Ship it in 3 days", {"title": "Ship it", "start": "2026-09-10"}),
    ("Renew passport in 2 weeks", {"start": "2026-09-21"}),
    ("Pay rent end of month", {"start": "2026-09-30"}),
    ("Standup", {"start": "2026-09-07"}),  # no date token at all -> reference date
]

# ---------------------------------------------------------------------------
# Times (nl_grammar.md "Times")
# ---------------------------------------------------------------------------
TIME_CASES = [
    ("Lunch at 1pm", {"start": "2026-09-07T13:00"}),
    ("Lunch at 1 pm", {"start": "2026-09-07T13:00"}),
    ("Lunch at 1.30pm", {"start": "2026-09-07T13:30"}),
    ("Lunch at 13:00", {"start": "2026-09-07T13:00"}),
    ("Lunch at noon", {"start": "2026-09-07T12:00"}),
    ("Wake up at midnight", {"start": "2026-09-07T00:00"}),
    ("Run in the morning", {"start": "2026-09-07T09:00"}),
    ("Coffee in the afternoon", {"start": "2026-09-07T14:00"}),
    ("Dinner in the evening", {"start": "2026-09-07T19:00"}),
    ("Movie tonight", {"start": "2026-09-07T20:00"}),
    ("Workshop 1-2pm", {"start": "2026-09-07T13:00", "end": "2026-09-07T14:00"}),
    ("Workshop 1pm to 2pm", {"start": "2026-09-07T13:00", "end": "2026-09-07T14:00"}),
    ("Workshop from 9 to 10:30", {"start": "2026-09-07T09:00", "end": "2026-09-07T10:30"}),
    ("Call at 3", {"start": "2026-09-07T15:00"}, True),  # bare hour, afternoon-biased, warns
    ("Standup tomorrow at 9am", {"start": "2026-09-08T09:00"}),
    ("Standup tomorrow at 9", {"start": "2026-09-08T09:00"}, True),
    ("All-hands next friday at 2pm", {"start": "2026-09-18T14:00"}),
    ("Quiet hour", {"allDay": True}),  # no time token -> all-day
    ("Gym at 6am", {"start": "2026-09-07T06:00"}),
    ("Gym at 6.15am", {"start": "2026-09-07T06:15"}),
    ("Checkout noon tomorrow", {"start": "2026-09-08T12:00"}),
    ("Sleep in until noon", {"start": "2026-09-07T12:00"}),
]

# ---------------------------------------------------------------------------
# Duration and all-day (nl_grammar.md "Duration", "All-day")
# ---------------------------------------------------------------------------
DURATION_CASES = [
    ("Lunch at 1pm for 45 min", {"start": "2026-09-07T13:00", "end": "2026-09-07T13:45"}),
    ("Lunch at 1pm for 45m", {"end": "2026-09-07T13:45"}),
    ("Workshop at 1pm for 2h", {"end": "2026-09-07T15:00"}),
    ("Workshop at 1pm for 2 hours", {"end": "2026-09-07T15:00"}),
    ("Workshop at 1pm for 1.5 hours", {"end": "2026-09-07T14:30"}),
    ("Standup at 9am", {"end": "2026-09-07T10:00"}),  # no duration -> default 60 min
    ("Company retreat", {"allDay": True}),  # no time, no duration -> all-day
    ("Company retreat all day", {"allDay": True}),
    ("Company retreat tomorrow all day", {"start": "2026-09-08", "allDay": True}),
    ("Vacation next monday all day", {"start": "2026-09-14", "allDay": True}),
    ("Offsite at 9am for 3 hours", {"end": "2026-09-07T12:00"}),
    ("Nap at 2pm for 20 min", {"end": "2026-09-07T14:20"}),
    ("Sprint planning at 10am for 1 hour", {"end": "2026-09-07T11:00"}),
    ("Retro at 4pm for 30 min", {"end": "2026-09-07T16:30"}),
]

# ---------------------------------------------------------------------------
# Recurrence (nl_grammar.md "Recurrence")
# ---------------------------------------------------------------------------
RECURRENCE_CASES = [
    ("Standup every day at 9am", {"rrule": "FREQ=DAILY"}),
    ("Standup daily at 9am", {"rrule": "FREQ=DAILY"}),
    ("Gym every weekday at 6am", {"rrule": "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"}),
    ("Trash day every monday", {"rrule": "FREQ=WEEKLY;BYDAY=MO"}),
    ("Team sync weekly on wednesday at 2pm", {"rrule": "FREQ=WEEKLY;BYDAY=WE"}),
    ("Book club every mon and wed at 7pm", {"rrule": "FREQ=WEEKLY;BYDAY=MO,WE"}),
    ("Paycheck every 2 weeks", {"rrule": "FREQ=WEEKLY;INTERVAL=2"}),
    ("Rent due monthly on the 1st", {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"}),
    ("Board meeting every month on the 14th", {"rrule": "FREQ=MONTHLY;BYMONTHDAY=14"}),
    ("Anniversary yearly on dec 25", {"rrule": "FREQ=YEARLY"}),
    ("Standup every weekday at 9am until Dec 25",
     {"rrule": "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20261225"}),
    ("Sprint standup every day at 9am for 6 weeks",
     {"rrule": "FREQ=DAILY;COUNT=6"}),  # recurrence present -> "for 6 weeks" is COUNT
    ("Standup every monday at 9am for 6 weeks",
     {"rrule": "FREQ=WEEKLY;BYDAY=MO;COUNT=6"}),
    ("Book club every wed at 7pm until next year",
     {"rrule": "FREQ=WEEKLY;BYDAY=WE"}, True),  # relative "until" needs a concrete date, warns
    ("Trash day every tuesday", {"rrule": "FREQ=WEEKLY;BYDAY=TU"}),
    ("Trash day every thursday", {"rrule": "FREQ=WEEKLY;BYDAY=TH"}),
    ("Trash day every friday", {"rrule": "FREQ=WEEKLY;BYDAY=FR"}),
    ("Trash day every saturday", {"rrule": "FREQ=WEEKLY;BYDAY=SA"}),
    ("Trash day every sunday", {"rrule": "FREQ=WEEKLY;BYDAY=SU"}),
    ("Water plants every 3 days", {"rrule": "FREQ=DAILY;INTERVAL=3"}),
]

# ---------------------------------------------------------------------------
# Location (nl_grammar.md "Location")
# ---------------------------------------------------------------------------
LOCATION_CASES = [
    ("Lunch at Cafe Linnea", {"title": "Lunch", "location": "Cafe Linnea"}),
    ("Lunch at 1pm at Cafe Linnea", {"start": "2026-09-07T13:00", "location": "Cafe Linnea"}),
    ("Study session in the library", {"location": "the library"}),
    ("Study session in 2 weeks", {"start": "2026-09-21", "location": None}),  # "in" is a date here, not a place
    ("Standup @ Room 204", {"location": "Room 204"}),
    ("Team offsite at the lake house all day", {"location": "the lake house", "allDay": True}),
    ("Yoga in the park at 7am", {"location": "the park", "start": "2026-09-07T07:00"}),
    ("Dinner at Nonna's tomorrow at 7pm", {"location": "Nonna's", "start": "2026-09-08T19:00"}),
    ("Call at the office at 3pm", {"location": "the office", "start": "2026-09-07T15:00"}),
    ("Pickup at school at 3pm", {"location": "school", "start": "2026-09-07T15:00"}),
    ("Meeting @ HQ tomorrow", {"location": "HQ", "start": "2026-09-08"}),
    ("Conference in Berlin next friday", {"location": "Berlin", "start": "2026-09-18"}),
]

# ---------------------------------------------------------------------------
# Calendar prefix (nl_grammar.md "Calendar")
# ---------------------------------------------------------------------------
CALENDAR_CASES = [
    ("Lunch with Sarah /personal", {"title": "Lunch with Sarah", "calendar": "personal"}),
    ("Sprint planning /work", {"calendar": "work"}),
    ("Pick up Jack /family", {"calendar": "family"}),
    ("Standup /Work", {"calendar": "work"}),  # case-insensitive
    ("Dentist /pers", {"calendar": "personal"}),  # prefix match
    ("Board meeting /fam", {"calendar": "family"}),
    ("Retro /w", {"calendar": "work"}),
    ("Trip planning /nonexistent", {"calendar": None}, True),  # no match -> warning, falls back
    ("Movie night /personal at 8pm", {"calendar": "personal", "start": "2026-09-07T20:00"}),
    ("Client call /work tomorrow at 10am", {"calendar": "work", "start": "2026-09-08T10:00"}),
]

# ---------------------------------------------------------------------------
# Alert (nl_grammar.md "Alert")
# ---------------------------------------------------------------------------
ALERT_CASES = [
    ("Lunch at 1pm alert 15m", {"alarms": ["-PT15M"]}),
    ("Lunch at 1pm alert 15 min", {"alarms": ["-PT15M"]}),
    ("Standup at 9am alert 1h", {"alarms": ["-PT1H"]}),
    ("Flight tomorrow at 6am alert 1 day before", {"alarms": ["-P1D"]}),
    ("Dentist at 2pm remind me 10 min before", {"alarms": ["-PT10M"]}),
    ("Call mom at 5pm alert 5m", {"alarms": ["-PT5M"]}),
    ("Standup every weekday at 9am alert 5m",
     {"rrule": "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", "alarms": ["-PT5M"]}),
    ("Board meeting next friday at 2pm alert 1h", {"alarms": ["-PT1H"]}),
    ("Pickup at 3pm remind me 15 min before", {"alarms": ["-PT15M"]}),
    ("Anniversary yearly on dec 25 alert 1 day before", {"alarms": ["-P1D"]}),
]

# ---------------------------------------------------------------------------
# Time zone (nl_grammar.md "Time zone")
# ---------------------------------------------------------------------------
TIMEZONE_CASES = [
    ("Call with New York at 3pm EST", {"start": "2026-09-07T15:00", "tz": "America/New_York"}),
    ("Call with Berlin at 15:00 CET", {"start": "2026-09-07T15:00", "tz": "Europe/Berlin"}),
    ("Call with Berlin at 9am Europe/Berlin", {"start": "2026-09-07T09:00", "tz": "Europe/Berlin"}),
    ("Standup at 9am America/Edmonton", {"tz": "America/Edmonton"}),
    ("Call with Tokyo at 8am JST", {"start": "2026-09-07T08:00", "tz": "Asia/Tokyo"}),
    ("Call with London at 2pm GMT", {"start": "2026-09-07T14:00", "tz": "Europe/London"}),
    ("Webinar tomorrow at 11am PST", {"start": "2026-09-08T11:00", "tz": "America/Los_Angeles"}),
    ("Standup at 9am", {"tz": "America/Edmonton"}),  # no zone token -> local system zone (the reference's)
]

# ---------------------------------------------------------------------------
# Combined / showcase sentences — the ones a real user actually types
# ---------------------------------------------------------------------------
SHOWCASE_CASES = [
    ("Lunch with Sarah tomorrow at 1pm for 90 min at Cafe Linnea /personal alert 15m",
     {"title": "Lunch with Sarah", "start": "2026-09-08T13:00", "end": "2026-09-08T14:30",
      "location": "Cafe Linnea", "calendar": "personal", "alarms": ["-PT15M"]}),
    ("Standup every weekday at 9am for 15 min /work",
     {"title": "Standup", "rrule": "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR",
      "end": "2026-09-07T09:15", "calendar": "work"}),
    ("Pick up Jack from school at 3:30pm /family alert 10m",
     {"title": "Pick up Jack from school", "start": "2026-09-07T15:30",
      "calendar": "family", "alarms": ["-PT10M"]}),
    ("Dinner with the Petersons next saturday at 6pm at their place /family",
     {"start": "2026-09-19T18:00", "location": "their place", "calendar": "family"}),
    ("Quarterly board meeting monthly on the 1st at 10am /work alert 1 day before",
     {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1", "start_time": "10:00",
      "calendar": "work", "alarms": ["-P1D"]}),
    ("Flight to Berlin next friday at 6am for 9 hours alert 2h",
     {"start": "2026-09-18T06:00", "end": "2026-09-18T15:00", "alarms": ["-PT2H"]}),
    ("Weekly 1:1 with my manager every tuesday at 11am for 30 min /work",
     {"rrule": "FREQ=WEEKLY;BYDAY=TU", "end": "2026-09-08T11:30", "calendar": "work"}),
    ("Kid's soccer practice every saturday at 9am at the community field /family",
     {"rrule": "FREQ=WEEKLY;BYDAY=SA", "location": "the community field", "calendar": "family"}),
    ("Renew driver's license by end of month",
     {"title": "Renew driver's license by end of month"}),  # "by" is not a recognized keyword; whole phrase is title
    ("Book club every mon and wed at 7pm until dec 25 /personal",
     {"rrule": "FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261225", "calendar": "personal"}),
    ("Pay the mortgage monthly on the 1st alert 3 days before",
     {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"}, True),  # "3 days before" isn't a documented alert unit -> warns
    ("Vet appointment for the dog tomorrow at 2:30pm at Riverside Vet alert 30m",
     {"start": "2026-09-08T14:30", "location": "Riverside Vet", "alarms": ["-PT30M"]}),
    ("Parent-teacher conference next thursday at 4pm /family alert 1h",
     {"start": "2026-09-17T16:00", "calendar": "family", "alarms": ["-PT1H"]}),
    ("Standup at 9am /work tomorrow", {"start": "2026-09-08T09:00", "calendar": "work"}),
    ("Team lunch next friday at noon at the usual spot /work",
     {"start": "2026-09-18T12:00", "location": "the usual spot", "calendar": "work"}),
    ("Call with Berlin office next monday at 9am Europe/Berlin for 1 hour /work",
     {"start": "2026-09-14T09:00", "end": "2026-09-14T10:00", "tz": "Europe/Berlin", "calendar": "work"}),
]

# ---------------------------------------------------------------------------
# Ambiguity and warnings (nl_grammar.md "Ambiguity policy")
# ---------------------------------------------------------------------------
AMBIGUITY_CASES = [
    ("Standup 14/9", {"start": "2026-09-14"}, True),  # locale-ambiguous numeric date, day-first assumed
    ("Standup 9/14", {"start": "2026-09-14"}, True),  # month-first reading also plausible -> warns
    ("Call at 3", {"start": "2026-09-07T15:00"}, True),  # bare hour, no am/pm, afternoon-biased
    ("Call at 9", {"start": "2026-09-07T09:00"}, False),  # 9 with no marker but conventionally morning-hour range still resolved without ambiguity per the 1-11 rule window; documented exception
    ("Standup every day for 6 weeks", {"rrule": "FREQ=DAILY;COUNT=6"}, False),  # recurrence present, unambiguous COUNT
    ("Vacation for 2 weeks", {"allDay": False}, True),  # "for 2 weeks" with no recurrence token is an unusually long duration; warns rather than silently producing a 2-week-long timed event
    ("Trip planning /xyz", {"calendar": None}, True),
    ("Book club every wed at 7pm until next year", {}, True),
    ("Pay the mortgage monthly on the 1st alert 3 days before", {}, True),
    ("Study session in 2 weeks", {"start": "2026-09-21"}, False),  # "in" correctly read as date, not location
    ("Meeting at 3", {"start": "2026-09-07T15:00"}, True),
    ("Sync at 3 at HQ", {"start": "2026-09-07T15:00", "location": "HQ"}, True),  # bare hour ambiguity persists even with a later location
    ("Call 5", {"title": "Call 5"}, False),  # bare digit with no time keyword nearby is not a time at all
    ("Something on 31/11", {}, True),  # not a valid calendar date in either reading -> warns, no date resolved
]

ALL_CASES = (
    DATE_CASES + TIME_CASES + DURATION_CASES + RECURRENCE_CASES + LOCATION_CASES
    + CALENDAR_CASES + ALERT_CASES + TIMEZONE_CASES + SHOWCASE_CASES + AMBIGUITY_CASES
)


def _unpack(case):
    if len(case) == 2:
        sentence, expect = case
        return sentence, expect, False
    sentence, expect, warns = case
    return sentence, expect, warns


class ParserCorpusTest(unittest.TestCase):
    """Table-driven corpus. Every case is an expected failure until Phase 1
    implements `omagenda.parse.parse_event` — see the module docstring."""

    def test_corpus_size(self):
        # A floor, not a ceiling: Phase 1 may add cases when the grammar
        # doc gains detail, but the corpus should not shrink back below
        # what Phase 0 committed to reviewing.
        self.assertGreaterEqual(len(ALL_CASES), 150)

    @unittest.expectedFailure
    def test_corpus(self):
        from omagenda.parse import parse_event  # noqa: PLC0415 (not implemented until Phase 1)

        failures = []
        for sentence, expect, warns in (_unpack(c) for c in ALL_CASES):
            with self.subTest(sentence=sentence):
                result = parse_event(sentence, reference=REFERENCE)
                for key, value in expect.items():
                    if result.get(key) != value:
                        failures.append(f"{sentence!r}: {key} expected {value!r}, got {result.get(key)!r}")
                has_warnings = bool(result.get("warnings"))
                if has_warnings != warns:
                    failures.append(f"{sentence!r}: expected warns={warns}, got warnings={result.get('warnings')!r}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    print(f"corpus size: {len(ALL_CASES)}")
    unittest.main()

# Omagenda natural-language grammar

The parser (`parse.py`) is a deterministic single pass over tokens: no network, no LLM, no silent guessing. This document is the human-readable grammar; `tests/test_parse.py` is the executable specification. When the two disagree, fix whichever one is wrong — they must describe the same behavior.

General rules, before the per-category ones below:

- Matching is case-insensitive.
- Spans never overlap. Where two rules could both match the same text, the earliest, longest match wins.
- Anything not claimed by a date, time, duration, recurrence, location, calendar, alert, or time zone token becomes the **title**, whitespace-collapsed, first letter capitalized.
- An ambiguous or unsupported construct produces a **warning** rather than a guess. The overlay shows warnings under the preview instead of hiding them.
- All resolution is relative to a **reference date**, normally "now" in the local time zone; tests pin it explicitly so the corpus is reproducible.

## Dates

| Pattern | Resolves to | Notes |
|---|---|---|
| `today` | reference date | |
| `tomorrow`, `tmrw` | reference date + 1 day | |
| `<weekday>` (`monday`, `mon`, ...) | the next occurrence of that weekday, today counts if it is today | bare weekday names mean "the next one," matching how people actually say them |
| `this <weekday>` | same as bare `<weekday>` | explicit synonym |
| `next <weekday>` | the occurrence **after** the coming one | Fantastical's rule: "next Friday" said on a Wednesday means the Friday after this one, not this Friday |
| `on the 14th`, `the 14th` | the 14th of the reference month, or next month if that date has passed | ordinal-only dates |
| `Sep 14`, `14 Sep`, `September 14` | that calendar date, this year, or next year if it has passed | month name or abbreviation, either order |
| `14/9`, `9/14` | that calendar date, read in `LC_TIME` date order | genuinely ambiguous only when **both** the day-first and month-first readings are valid calendar dates (`12/10` could be Dec 10 or Oct 12); when one reading has a component over 12, the other reading is used with no warning (`14/9` can only be Sep 14) |
| `2026-09-14` | that exact date | ISO form is never ambiguous |
| `in 3 days` | reference date + 3 days | |
| `in 2 weeks` | reference date + 14 days | |
| `end of month` | the last day of the reference month | |
| no date token present | the reference date | |

## Times

| Pattern | Resolves to | Notes |
|---|---|---|
| `1pm`, `1 pm`, `1.30pm`, `13:00` | that time | |
| `noon` | 12:00 | |
| `midnight` | 00:00 | |
| `morning` | 09:00 | |
| `afternoon` | 14:00 | |
| `evening` | 19:00 | |
| `tonight` | 20:00 | also implies today's date if no date token is present |
| `1-2pm`, `1pm to 2pm`, `from 9 to 10:30` | a start and end time | sets both `start` and `end`; `for <duration>` is redundant and ignored with a warning if both are given and disagree |
| `at 3`, bare `at <hour>` generally | a business-hour default: 7–11 reads as morning, 12 as noon, 1–6 as afternoon, if nothing after it reads as a place; otherwise the location rule wins | always ambiguous and always warns, even inside 7–11 — the other reading (9am vs 9pm) is still a real possibility, the default is just the likelier one; see Location below and the ambiguity note |
| no time token, and no `all day` | all-day event | |

## Duration

| Pattern | Resolves to |
|---|---|
| `for 45 min`, `for 45m` | 45-minute duration |
| `for 2h`, `for 2 hours` | 2-hour duration |
| `for 1.5 hours` | 90-minute duration |
| none given, and a start time was given | 60-minute default |
| none given, and no time was given | all-day |

## All-day

- No time token anywhere in the sentence, or the literal words `all day`.
- An all-day event has `allDay: true`, `start`/`end` as dates (no time component), and ignores any duration token with a warning if one was also given.

## Recurrence

| Pattern | RRULE |
|---|---|
| `every day`, `daily` | `FREQ=DAILY` |
| `every weekday` | `FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR` |
| `every monday`, `weekly` (with a weekday date token) | `FREQ=WEEKLY;BYDAY=<day>` |
| `every mon and wed` | `FREQ=WEEKLY;BYDAY=MO,WE` |
| `every 2 weeks` | `FREQ=WEEKLY;INTERVAL=2` |
| `monthly on the 1st`, `every month` | `FREQ=MONTHLY;BYMONTHDAY=<n>` |
| `yearly` | `FREQ=YEARLY` |
| `... until <date>` | adds `UNTIL=<date>` to whatever pattern preceded it |
| `... for 6 weeks` (after a recurrence phrase) | adds `COUNT=6` — a bare `for <n> <unit>` means COUNT only when a recurrence token appears earlier in the sentence; otherwise it is a duration (see above) |

## Location

- `at <words>` claims location when `<words>` does not itself parse as a time (`at 3pm` is a time; `at Cafe Linnea` is a location).
- `in <words>` claims location when `<words>` does not parse as a duration or date (`in 2 weeks` is a date; `in the kitchen` is a location).
- `@ <words>` always claims location.
- A location keyword's match extends to the next recognized token (date, time, duration, recurrence, calendar, alert) or end of string, whichever comes first.

## Calendar

- `/<name>` prefix-matches (case-insensitive) against known calendar ids and display names.
- No match found: `calendar` is `null` and a warning names the unmatched prefix. This lets `add` fall back to the account's default calendar rather than fail outright.

## Alert

| Pattern | Resolves to |
|---|---|
| `alert 15m`, `alert 15 min` | `VALARM` trigger `-PT15M` |
| `alert 1h` | `-PT1H` |
| `alert 1 day before` | `-P1D` |
| `remind me 10 min before` | `-PT10M` |

## Time zone

| Pattern | Resolves to |
|---|---|
| `3pm EST`, `15:00 CET` | the given time in that zone's abbreviation, mapped through a small fixed table (documented in `parse.py`); the event's `TZID` is set to the corresponding IANA zone |
| `at 9am Europe/Berlin` | the given time in that IANA zone verbatim |
| no zone token | the local system zone |

## Ambiguity policy

The parser never picks silently between two materially different readings. Instead:

1. It resolves to the reading documented above (the "biased" default), and
2. adds a `warnings` entry naming the ambiguity and the choice made, so the overlay can show it and the user can correct it by typing more.

This applies to: locale-ambiguous numeric dates where both readings are valid (`12/10`, but not `14/9` — see Dates above), any bare `at <hour>` with no am/pm marker regardless of which half of the day it defaults to, a `for <n> <unit>` immediately after a recurrence phrase (COUNT) versus with no recurrence phrase (duration), and a duration given in a unit the grammar doesn't define (only minutes and hours are; `for 2 weeks` falls back to a single all-day placeholder rather than a two-week-long timed event).

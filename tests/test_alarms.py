"""Alarm-firing tests. See PLAN.md §6.5 and ARCHITECTURE.md §3."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from omagenda.alarms import check_and_fire, parse_trigger


def _event(**overrides):
    base = {
        "id": "work/abc@omagenda",
        "title": "Standup",
        "start": "2026-09-07T09:00:00-06:00",
        "end": "2026-09-07T09:15:00-06:00",
        "allDay": False,
        "alarms": ["-PT15M"],
        "conference": None,
    }
    base.update(overrides)
    return base


class ParseTriggerTest(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(parse_trigger("-PT15M").total_seconds(), -900)

    def test_hours(self):
        self.assertEqual(parse_trigger("-PT1H").total_seconds(), -3600)

    def test_days(self):
        self.assertEqual(parse_trigger("-P1D").total_seconds(), -86400)


class CheckAndFireTest(unittest.TestCase):
    def test_fires_when_trigger_time_has_arrived(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event()]}
            now = datetime.fromisoformat("2026-09-07T08:45:00-06:00")  # exactly at -15m
            fired_calls = []
            newly_fired = check_and_fire(
                agenda, state_dir=Path(tmp), now=now,
                notify=lambda title, when, url: fired_calls.append((title, when, url)),
            )
            self.assertEqual(len(newly_fired), 1)
            self.assertEqual(fired_calls, [("Standup", "9:00 AM", None)])

    def test_does_not_fire_before_trigger_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event()]}
            now = datetime.fromisoformat("2026-09-07T08:00:00-06:00")  # 45m early
            fired_calls = []
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: fired_calls.append(a))
            self.assertEqual(fired_calls, [])

    def test_does_not_refire_within_the_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event()]}
            now = datetime.fromisoformat("2026-09-07T08:45:00-06:00")
            calls = []
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: calls.append(a))
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: calls.append(a))
            self.assertEqual(len(calls), 1)  # second call sees it in the persisted fired-state

    def test_does_not_fire_alarm_missed_beyond_the_grace_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event()]}
            now = datetime.fromisoformat("2026-09-07T12:00:00-06:00")  # hours late
            calls = []
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: calls.append(a))
            self.assertEqual(calls, [])

    def test_all_day_events_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event(allDay=True, start="2026-09-07", end="2026-09-08")]}
            now = datetime.fromisoformat("2026-09-07T08:45:00-06:00")
            calls = []
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: calls.append(a))
            self.assertEqual(calls, [])

    def test_conference_url_passed_through_for_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = {"events": [_event(conference={"provider": "meet", "url": "https://meet.google.com/abc"})]}
            now = datetime.fromisoformat("2026-09-07T08:45:00-06:00")
            calls = []
            check_and_fire(agenda, state_dir=Path(tmp), now=now, notify=lambda *a: calls.append(a))
            self.assertEqual(calls[0][2], "https://meet.google.com/abc")


if __name__ == "__main__":
    unittest.main()

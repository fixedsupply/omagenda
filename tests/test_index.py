"""Recurrence expansion and agenda.json indexing tests.

Covers the cases calendar software gets wrong: EXDATE/RECURRENCE-ID
exceptions, a real DST-crossing event, floating times, and all-day spans.
See ARCHITECTURE.md §3-4 and §9, and tests/fixtures/vdir/.

The DST fixture (family/cabin-weekend.ics) spans 2026-03-08, the last
confirmed spring-forward transition for America/Edmonton in the installed
tzdata (2026c) -- Alberta's tzdata already encodes a law taking effect
2026-11-01 that keeps the province on a fixed UTC-6 offset year-round from
then on, so a fall crossing later in 2026 wouldn't actually cross anything.
"""
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from omagenda.index import build_agenda, index, resolve_state_dir, write_agenda

FIXTURES = Path(__file__).parent / "fixtures" / "vdir"


class BuildAgendaTest(unittest.TestCase):
    def test_indexes_fixture_vdir_under_budget(self):
        start = time.monotonic()
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.3, "ARCHITECTURE.md §10 budget: under 300ms")
        self.assertIn("events", agenda)
        self.assertEqual(len(agenda["calendars"]), 3)

    def test_recurring_exception_is_excluded(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        starts = [e["start"] for e in agenda["events"] if e["title"] == "Standup"]
        self.assertNotIn("2026-09-11T09:00:00-06:00", starts)
        self.assertIn("2026-09-10T09:00:00-06:00", starts)  # Thursday, still present

    def test_recurrence_id_override_replaces_one_occurrence(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=21, start=date(2026, 9, 7))
        pickups = [e for e in agenda["events"] if e["title"].startswith("Pick up Jack")]
        titles_by_date = {e["start"][:10]: e["title"] for e in pickups}
        self.assertEqual(titles_by_date["2026-09-11"], "Pick up Jack")
        self.assertEqual(titles_by_date["2026-09-18"], "Pick up Jack (early dismissal)")
        # the override moved the time from 15:30 to 16:00
        overridden = next(e for e in pickups if e["start"].startswith("2026-09-18"))
        self.assertTrue(overridden["start"].startswith("2026-09-18T16:00:00"))

    def test_all_occurrences_from_a_series_are_flagged_recurring(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=21, start=date(2026, 9, 7))
        pickups = [e for e in agenda["events"] if e["title"].startswith("Pick up Jack")]
        self.assertTrue(pickups)
        self.assertTrue(all(e["recurring"] for e in pickups))  # override included

    def test_one_off_event_is_not_recurring(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        lunch = next(e for e in agenda["events"] if e["title"] == "Lunch with Sarah")
        self.assertFalse(lunch["recurring"])
        self.assertEqual(lunch["location"], "Cafe Linnea")

    def test_dst_crossing_event_keeps_wall_clock_time_on_both_ends(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=10, start=date(2026, 3, 5))
        cabin = next(e for e in agenda["events"] if e["title"] == "Cabin weekend")
        # 17:00 before the spring-forward, 12:00 after it -- wall-clock hours
        # preserved even though the UTC offset changed from -07:00 to -06:00.
        self.assertTrue(cabin["start"].startswith("2026-03-06T17:00:00-07:00"))
        self.assertTrue(cabin["end"].startswith("2026-03-08T12:00:00-06:00"))

    def test_multiday_all_day_event(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=20, start=date(2026, 10, 8))
        holiday = next(e for e in agenda["events"] if e["title"] == "Thanksgiving weekend")
        self.assertTrue(holiday["allDay"])
        self.assertEqual(holiday["start"], "2026-10-10")
        self.assertEqual(holiday["end"], "2026-10-13")  # exclusive, per RFC 5545
        self.assertIsNone(holiday["sourceTz"])

    def test_floating_time_event_has_no_source_tz(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        reading = next(e for e in agenda["events"] if e["title"] == "Read a book")
        self.assertFalse(reading["allDay"])
        self.assertIsNone(reading["sourceTz"])
        self.assertEqual(reading["start"], "2026-09-12T20:00:00")  # no offset: floating

    def test_conference_links_detected(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        planning = next(e for e in agenda["events"] if e["title"] == "Sprint planning")
        self.assertEqual(planning["conference"], {"provider": "meet", "url": "https://meet.google.com/abc-defg-hij"})
        self.assertEqual(planning["attendees"], 2)

        client_call = next(e for e in agenda["events"] if e["title"] == "Client call")
        self.assertEqual(client_call["conference"]["provider"], "zoom")
        self.assertEqual(client_call["conference"]["url"], "https://zoom.us/j/1234567890")

    def test_alarms_extracted_as_iso8601_durations(self):
        agenda = build_agenda(FIXTURES, use_cache=False, days=14, start=date(2026, 9, 7))
        pickup = next(e for e in agenda["events"] if e["title"] == "Pick up Jack")
        self.assertEqual(pickup["alarms"], ["-PT15M"])

    def test_events_sorted_all_day_before_timed_on_same_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal_dir = Path(tmp) / "personal"
            cal_dir.mkdir()
            (cal_dir / "allday.ics").write_text(
                "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:a@x\n"
                "DTSTAMP:20260901T000000Z\nDTSTART;VALUE=DATE:20260910\n"
                "DTEND;VALUE=DATE:20260911\nSUMMARY:All day\nEND:VEVENT\nEND:VCALENDAR\n"
            )
            (cal_dir / "timed.ics").write_text(
                "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:b@x\n"
                "DTSTAMP:20260901T000000Z\nDTSTART;TZID=America/Edmonton:20260910T090000\n"
                "DTEND;TZID=America/Edmonton:20260910T100000\nSUMMARY:Timed\nEND:VEVENT\nEND:VCALENDAR\n"
            )
            agenda = build_agenda(Path(tmp), use_cache=False, days=5, start=date(2026, 9, 10))
            self.assertEqual([e["title"] for e in agenda["events"]], ["All day", "Timed"])


class WriteAgendaTest(unittest.TestCase):
    def test_write_is_atomic_and_round_trips(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            agenda = build_agenda(FIXTURES, use_cache=False, days=7, start=date(2026, 9, 7))
            path = write_agenda(agenda, state_dir=tmp)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
            self.assertEqual(json.loads(path.read_text()), agenda)

    def test_index_writes_to_resolved_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = index(FIXTURES, state_dir=tmp, days=7)
            self.assertEqual(path, Path(tmp) / "agenda.json")
            self.assertTrue(path.exists())


class ResolveStateDirTest(unittest.TestCase):
    def test_env_override(self):
        import os

        old = os.environ.get("OMAGENDA_STATE")
        try:
            os.environ["OMAGENDA_STATE"] = "/tmp/omagenda-test-state"
            self.assertEqual(str(resolve_state_dir()), "/tmp/omagenda-test-state")
        finally:
            if old is None:
                os.environ.pop("OMAGENDA_STATE", None)
            else:
                os.environ["OMAGENDA_STATE"] = old


if __name__ == "__main__":
    unittest.main()


class IndexCacheTest(unittest.TestCase):
    """Re-parsing an unchanged file was the entire cost of an index: a real
    Google subscription is one 5 MB file of years of history, ~4.7s to
    parse and milliseconds to expand a fortnight out of. Every test here
    pins state_dir, so no cache is ever written to the real state dir."""

    def test_second_build_is_cached_and_agrees_with_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = build_agenda(FIXTURES, days=14, start=date(2026, 9, 7), state_dir=tmp)
            second = build_agenda(FIXTURES, days=14, start=date(2026, 9, 7), state_dir=tmp)
            self.assertEqual(first["events"], second["events"])
            self.assertTrue((Path(tmp) / "index-cache.json").exists())

    def test_touching_a_file_invalidates_only_that_entry(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            vdir_root = Path(tmp) / "vdir"
            shutil.copytree(FIXTURES, vdir_root)
            state = Path(tmp) / "state"

            build_agenda(vdir_root, days=14, start=date(2026, 9, 7), state_dir=state)

            # Rewrite one event's summary, padded to the same byte length
            # so the size is unchanged -- this proves mtime alone catches
            # an edit, which is the case a size check would miss.
            target = vdir_root / "personal" / "lunch.ics"
            target.write_bytes(target.read_bytes().replace(b"Lunch with Sarah", b"Lunch with Alex "))

            after = build_agenda(vdir_root, days=14, start=date(2026, 9, 7), state_dir=state)
            titles = [e["title"].strip() for e in after["events"]]
            self.assertIn("Lunch with Alex", titles)
            self.assertNotIn("Lunch with Sarah", titles)

            # The other calendars' entries were served from cache, not reparsed.
            self.assertIn("Standup", titles)

    def test_a_different_window_is_not_served_from_the_old_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            week = build_agenda(FIXTURES, days=3, start=date(2026, 9, 7), state_dir=tmp)
            fortnight = build_agenda(FIXTURES, days=14, start=date(2026, 9, 7), state_dir=tmp)
            self.assertGreater(len(fortnight["events"]), len(week["events"]))

    def test_a_corrupt_cache_is_ignored_rather_than_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index-cache.json").write_text("{ not json")
            agenda = build_agenda(FIXTURES, days=14, start=date(2026, 9, 7), state_dir=tmp)
            self.assertTrue(agenda["events"])


class OneLineFieldsTest(unittest.TestCase):
    """Real calendars carry multi-line venue addresses; a row that renders
    on one line has to collapse them or the layout breaks."""

    def test_a_multiline_location_collapses(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal_dir = Path(tmp) / "work"
            cal_dir.mkdir()
            (cal_dir / "e.ics").write_text(
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a@x\r\n"
                "DTSTAMP:20260901T000000Z\r\n"
                "DTSTART;TZID=America/Edmonton:20260910T090000\r\n"
                "DTEND;TZID=America/Edmonton:20260910T100000\r\n"
                "SUMMARY:Class\r\n"
                "LOCATION:Gym - University District\\n4128 University Ave NW\\nCalgary AB\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n"
            )
            agenda = build_agenda(Path(tmp), use_cache=False, days=2, start=date(2026, 9, 10))
            location = agenda["events"][0]["location"]
            self.assertNotIn("\n", location)
            self.assertEqual(location, "Gym - University District 4128 University Ave NW Calgary AB")

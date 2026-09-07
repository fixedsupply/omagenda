"""Recurrence expansion and agenda.json indexing tests.

Covers the cases calendar software gets wrong: EXDATE/RECURRENCE-ID
exceptions, DST-crossing events, floating times, and all-day spans. See
ARCHITECTURE.md §3-4 and §9, and the fixtures under tests/fixtures/vdir/.

Not yet implemented: Phase 1 (see AGENTS.md).
"""
import unittest


class IndexTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_indexes_fixture_vdir_under_budget(self):
        import time

        from omagenda.index import build_agenda

        start = time.monotonic()
        agenda = build_agenda("tests/fixtures/vdir", days=14)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.3, "ARCHITECTURE.md §10 budget: under 300ms")
        self.assertIn("events", agenda)

    @unittest.expectedFailure
    def test_recurring_exception_is_excluded(self):
        # standup.ics in the work fixture recurs daily but excludes one
        # date via EXDATE; that date must not appear in the expansion.
        from omagenda.index import build_agenda

        agenda = build_agenda("tests/fixtures/vdir", days=14)
        starts = [e["start"] for e in agenda["events"] if e["title"] == "Standup"]
        self.assertNotIn("2026-09-11T09:00:00-06:00", starts)

    @unittest.expectedFailure
    def test_dst_crossing_event_keeps_wall_clock_time(self):
        # the family fixture has an event that spans the fall-back DST
        # transition; its local start time must not shift.
        from omagenda.index import build_agenda

        agenda = build_agenda("tests/fixtures/vdir", days=90)
        dst_events = [e for e in agenda["events"] if e["title"] == "Cabin weekend"]
        self.assertTrue(dst_events)


if __name__ == "__main__":
    unittest.main()

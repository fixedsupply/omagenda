"""Vdir discovery and atomic write tests. See ARCHITECTURE.md §7 and §9."""
import shutil
import tempfile
import unittest
from pathlib import Path

from omagenda.vdir import discover_calendars, map_color_to_theme, write_event_ics

FIXTURES = Path(__file__).parent / "fixtures" / "vdir"


class DiscoverCalendarsTest(unittest.TestCase):
    def test_discovers_fixture_calendars(self):
        cals = {c["id"]: c for c in discover_calendars(FIXTURES)}
        self.assertEqual(sorted(cals), ["family", "personal", "work"])

    def test_reads_displayname_and_color(self):
        cals = {c["id"]: c for c in discover_calendars(FIXTURES)}
        self.assertEqual(cals["personal"]["name"], "Personal")
        self.assertEqual(cals["personal"]["color"], "blue")
        self.assertEqual(cals["work"]["name"], "Work")
        self.assertEqual(cals["work"]["color"], "green")
        self.assertEqual(cals["family"]["color"], "yellow")

    def test_calendar_with_no_color_file_gets_round_robin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "untagged").mkdir()
            (root / "untagged" / "displayname").write_text("Untagged")
            cals = discover_calendars(root)
            self.assertEqual(len(cals), 1)
            self.assertIn(cals[0]["color"], [
                "blue", "green", "magenta", "yellow", "cyan", "red", "orange",
            ])

    def test_discovers_nested_account_calendars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "google-calvin" / "primary"
            nested.mkdir(parents=True)
            (nested / "displayname").write_text("Primary")
            cals = discover_calendars(root)
            self.assertEqual(cals[0]["id"], "google-calvin/primary")

    def test_missing_vdir_root_returns_empty(self):
        self.assertEqual(discover_calendars("/nonexistent/path/for/sure"), [])

    def _collection(self, root, name, *components, color=None):
        path = root / "family" / name
        path.mkdir(parents=True)
        (path / "displayname").write_text(name.title())
        if color:
            (path / "color").write_text(color)
        for index, component in enumerate(components):
            (path / f"item{index}.ics").write_text(
                f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:{component}\r\nUID:{name}-{index}\r\n"
                f"SUMMARY:x\r\nEND:{component}\r\nEND:VCALENDAR\r\n")
        return path

    def test_reminder_only_collections_are_not_calendars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._collection(root, "events", "VEVENT", "VEVENT")
            self._collection(root, "reminders", "VTODO", "VTODO")
            self._collection(root, "mixed", "VTODO", "VEVENT")
            self._collection(root, "empty")
            ids = [c["id"] for c in discover_calendars(root)]
            self.assertEqual(ids, ["family/empty", "family/events", "family/mixed"])
            everything = discover_calendars(root, include_reminder_lists=True)
            self.assertEqual({c["id"]: c["reminderList"] for c in everything},
                             {"family/empty": False, "family/events": False,
                              "family/mixed": False, "family/reminders": True})
            self.assertNotIn("reminderList", discover_calendars(root)[0])

    def test_doctor_names_skipped_reminder_lists(self):
        from unittest import mock
        from omagenda import doctor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._collection(root, "events", "VEVENT")
            self._collection(root, "reminders", "VTODO")
            with mock.patch("omagenda.vdir.resolve_vdir_root", return_value=root):
                result = doctor._check_vdir()
            self.assertTrue(result["ok"])
            self.assertIn("1 calendar(s)", result["detail"])
            self.assertIn("skipped reminder list(s) with no events: family/reminders", result["detail"])

    def test_skipping_a_reminder_list_keeps_other_colours(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._collection(root, "a-reminders", "VTODO")
            self._collection(root, "b-events", "VEVENT")
            self._collection(root, "c-events", "VEVENT")
            with_lists = {c["id"]: c["color"] for c in discover_calendars(root, include_reminder_lists=True)}
            without = {c["id"]: c["color"] for c in discover_calendars(root)}
            self.assertEqual(without, {k: v for k, v in with_lists.items() if k != "family/a-reminders"})


class ColorMappingTest(unittest.TestCase):
    def test_named_color_passes_through(self):
        self.assertEqual(map_color_to_theme("Blue"), "blue")

    def test_hex_maps_to_nearest_hue(self):
        self.assertEqual(map_color_to_theme("#ff0000"), "red")
        self.assertEqual(map_color_to_theme("#00ff00"), "green")
        self.assertEqual(map_color_to_theme("#0000ff"), "blue")

    def test_missing_or_unparsable_returns_none(self):
        self.assertIsNone(map_color_to_theme(None))
        self.assertIsNone(map_color_to_theme(""))
        self.assertIsNone(map_color_to_theme("not a color"))


class WriteEventIcsTest(unittest.TestCase):
    def test_write_is_atomic_and_readable_back(self):
        import icalendar

        with tempfile.TemporaryDirectory() as tmp:
            cal_dir = Path(tmp)
            cal = icalendar.Calendar()
            cal.add("prodid", "-//Omagenda//Test//EN")
            cal.add("version", "2.0")
            event = icalendar.Event()
            event.add("uid", "test-uid@omagenda")
            event.add("summary", "Test event")
            cal.add_component(event)

            path = write_event_ics(cal_dir, cal, uid="test-uid@omagenda")
            self.assertTrue(path.exists())
            self.assertEqual(list(cal_dir.glob("*.tmp")), [])  # no leftover temp file

            written = icalendar.Calendar.from_ical(path.read_bytes())
            summaries = [c["summary"] for c in written.walk("VEVENT")]
            self.assertEqual(summaries, ["Test event"])

    def test_refuses_to_overwrite_existing_uid(self):
        import icalendar

        with tempfile.TemporaryDirectory() as tmp:
            cal_dir = Path(tmp)
            cal = icalendar.Calendar()
            event = icalendar.Event()
            event.add("uid", "dup@omagenda")
            cal.add_component(event)
            write_event_ics(cal_dir, cal, uid="dup@omagenda")
            with self.assertRaises(FileExistsError):
                write_event_ics(cal_dir, cal, uid="dup@omagenda")


if __name__ == "__main__":
    unittest.main()

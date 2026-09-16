"""Sentence edits use disposable calendars and recorded provider responses."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import icalendar

from omagenda.edit import describe_event, edit_event, event_values, parse_sentence, parsed_values
from omagenda.vdir import discover_calendars

REFERENCE = datetime(2026, 9, 16, 9, tzinfo=ZoneInfo("America/Edmonton"))
CLI = Path(__file__).resolve().parents[1] / "bin" / "omagenda"


class EditTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.folder = self.base / "vdir" / "personal"
        self.folder.mkdir(parents=True)
        (self.folder / "displayname").write_text("Personal")
        self.state = self.base / "state"
        env = patch.dict(os.environ, OMAGENDA_VDIR=str(self.folder.parent),
                         OMAGENDA_STATE=str(self.state), OMAGENDA_CONFIG=str(self.base / "config.toml"))
        env.start()
        self.addCleanup(env.stop)
        self.file = self.folder / "demo.ics"
        self.write_event()

    def write_event(self, title="Dentist", start=None, minutes=60, location="Main St Clinic", extra=b"", duration=False):
        start = start or REFERENCE.replace(day=17, hour=15)
        cal = icalendar.Calendar()
        cal.add("version", "2.0")
        event = icalendar.Event()
        event.add("uid", "disposable@omagenda")
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("duration" if duration else "dtend", timedelta(minutes=minutes) if duration else start + timedelta(minutes=minutes))
        if location:
            event.add("location", location)
        cal.add_component(event)
        self.file.write_bytes(cal.to_ical().replace(b"END:VEVENT", extra + b"END:VEVENT"))

    def event(self):
        return icalendar.Calendar.from_ical(self.file.read_bytes()).walk("VEVENT")[0]

    def describe(self):
        return describe_event(str(self.file), REFERENCE)["sentence"]

    def edit(self, sentence, dry_run=False):
        return edit_event(str(self.file), sentence, REFERENCE, dry_run)

    def test_describe_corpus_and_unchanged_save(self):
        for title in ("Dentist", "Review 2pm slides", "Plan for success", "Walk on sunshine", "Meet at cafe"):
            for minutes, minute, location, year, zone in ((30, 0, "", 2026, "America/Edmonton"),
                    (90, 15, "Main St Clinic", 2026, "America/Edmonton"),
                    (120, 45, "", 2027, "Europe/Berlin"), (75, 5, "Room 4", 2026, "America/Edmonton")):
                with self.subTest(title=title, minutes=minutes, year=year):
                    self.write_event(title, REFERENCE.replace(year=year, day=17, hour=15, minute=minute, tzinfo=ZoneInfo(zone)), minutes, location)
                    original = self.file.read_bytes()
                    try:
                        sentence = self.describe()
                    except ValueError as exc:
                        # Grammar-like titles must fail safely, never lose words.
                        self.assertEqual(str(exc), "This event can't be described as a sentence yet")
                        self.assertIn(title, ("Meet at cafe", "Plan for success"))
                        continue
                    self.assertEqual(event_values(self.event(), REFERENCE), parsed_values(parse_sentence(sentence, REFERENCE), REFERENCE))
                    self.assertFalse(self.edit(sentence)["updated"])
                    self.assertEqual(self.file.read_bytes(), original)
                    if year != REFERENCE.year:
                        self.assertIn("2027", sentence)

    def test_all_day_one_day_and_multiday_refusal(self):
        self.write_event(start=REFERENCE.date(), minutes=1440, location="")
        self.assertIn("all day", self.describe())
        self.assertFalse(self.edit(self.describe())["updated"])
        self.write_event(start=REFERENCE.date(), minutes=2880, location="")
        with self.assertRaisesRegex(ValueError, "can't be described as a sentence yet"):
            self.describe()

    def test_seconds_and_ambiguous_titles_refuse(self):
        for title, start in (("Dentist", REFERENCE.replace(day=17, second=12)),
                             ("Meeting tomorrow", REFERENCE.replace(day=18)), ("Meet at cafe", REFERENCE.replace(day=17))):
            self.write_event(title=title, start=start)
            with self.assertRaisesRegex(ValueError, "can't be described as a sentence yet"):
                self.describe()

    def test_past_events_name_their_year_and_can_be_edited(self):
        for start in (REFERENCE.replace(month=8), REFERENCE.replace(day=10), REFERENCE.replace(year=2025, month=12)):
            with self.subTest(start=start):
                self.write_event(title="Dentist", start=start.replace(hour=15))
                sentence = self.describe()
                self.assertIn(f" {start.year} at 3pm", sentence)
                self.assertFalse(self.edit(sentence)["updated"])
                result = self.edit(sentence.replace("Dentist", "Dentist follow-up"))
                self.assertEqual(result["changed"], ["SUMMARY"])
                self.assertEqual(str(self.event()["SUMMARY"]), "Dentist follow-up")

    def test_parser_year_needs_a_plausible_real_date(self):
        from datetime import date
        today = date.today()
        next_sep_14 = date(today.year if (today.month, today.day) <= (9, 14) else today.year + 1, 9, 14).isoformat()
        cases = {
            "Dinner on Sep 14 2027 at 7pm": ("Dinner", "2027-09-14T19:00"),
            "Dinner Sep 14 1900": ("Dinner 1900", next_sep_14),
            "Call Sep 14 0000": ("Call 0000", next_sep_14),
            "Party on Feb 30 2027": None,
        }
        for sentence, expected in cases.items():
            with self.subTest(sentence=sentence):
                result = subprocess.run([sys.executable, str(CLI), "parse", sentence, "--json"],
                                        capture_output=True, text=True, env=dict(os.environ, TZ="America/Edmonton"))
                if expected is None:
                    # Invalid with a year behaves exactly as the same date without one.
                    bare = subprocess.run([sys.executable, str(CLI), "parse", sentence.replace(" 2027", ""), "--json"],
                                          capture_output=True, text=True)
                    self.assertEqual(result.returncode, bare.returncode)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout)
                parsed = parsed.get("event", parsed)
                self.assertEqual((parsed["title"], parsed["start"]), expected)

    def test_individual_changes_and_location_removal(self):
        for sentence, changed in (
            ("Checkup on Sep 17 at 3pm for 1h at Main St Clinic", ["SUMMARY"]),
            ("Dentist on Sep 17 at 2pm for 2h at Main St Clinic", ["DTSTART"]),
            ("Dentist on Sep 17 at 3pm for 2h at Main St Clinic", ["DTEND"]),
            ("Dentist on Sep 17 at 3pm for 1h at Other Clinic", ["LOCATION"]),
            ("Dentist on Sep 17 at 3pm for 1h", ["LOCATION"]),
            ("Dentist on Sep 18 all day at Main St Clinic", ["DTSTART", "DTEND"])):
            with self.subTest(sentence=sentence):
                self.write_event()
                result = self.edit(sentence)
                self.assertEqual(result["changed"], changed)
                self.assertEqual(int(self.event()["SEQUENCE"]), 1)
                if sentence.endswith("for 1h"):
                    self.assertNotIn("LOCATION", self.event())
        self.edit("Dentist on Sep 19 all day at Main St Clinic")
        self.assertEqual(int(self.event()["SEQUENCE"]), 2)

    def test_duration_property_and_foreign_start_preserved(self):
        self.write_event(start=REFERENCE.replace(day=17, hour=23, tzinfo=ZoneInfo("Europe/Berlin")), duration=True)
        original_start = next(line for line in self.file.read_bytes().splitlines() if line.startswith(b"DTSTART"))
        result = self.edit(self.describe().replace("for 1h", "for 90m"))
        self.assertEqual(result["changed"], ["DURATION"])
        self.assertNotIn("DTEND", self.event())
        self.assertIn(original_start, self.file.read_bytes().splitlines())
        self.edit(self.describe().replace("at 3pm", "at 4pm"))
        self.assertEqual(self.event()["DTSTART"].params["TZID"], "America/Edmonton")

    def test_unrelated_lines_are_byte_identical_including_nested_components(self):
        extra = (b"DESCRIPTION:Keep this deliberately\r\n folded text\r\nX-FOO;X-PARAM=hello:opaque\r\n"
                 b"URL:https://example.com\r\nCONFERENCE:https://example.com/meeting\r\n"
                 b"CREATED:20260101T000000Z\r\nORGANIZER:mailto:you@example.com\r\n"
                 b"BEGIN:VALARM\r\nACTION:DISPLAY\r\nSUMMARY:Alarm\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n")
        self.write_event(extra=extra)
        original = self.file.read_bytes()
        self.edit(self.describe().replace("Dentist", "Checkup"))
        expected = original.replace(b"SUMMARY:Dentist", b"SUMMARY:Checkup")
        actual = b"".join(line for line in self.file.read_bytes().splitlines(keepends=True)
                          if not line.startswith((b"SEQUENCE:", b"DTSTAMP:", b"LAST-MODIFIED:")))
        self.assertEqual(actual, expected)

    def test_copy_precedes_replacement_new_inode_and_permissions(self):
        original, inode = self.file.read_bytes(), self.file.stat().st_ino
        replace = os.replace
        def checked_replace(source, target):
            if target == self.file:
                saved = list((self.state / "edited" / "personal").glob("*.ics"))
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].read_bytes(), original)
            replace(source, target)
        with patch("omagenda.edit.os.replace", side_effect=checked_replace):
            result = self.edit(self.describe().replace("Dentist", "Checkup"))
        self.assertNotEqual(self.file.stat().st_ino, inode)
        saved = Path(result["copy"])
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
        self.assertTrue((self.state / "agenda.json").exists())

    def test_failed_copy_no_changes_and_dry_run_do_not_replace(self):
        original, inode = self.file.read_bytes(), self.file.stat().st_ino
        sentence = self.describe()
        self.assertFalse(self.edit(sentence)["updated"])
        self.assertTrue(self.edit(sentence.replace("Dentist", "Checkup"), True)["updated"])
        with patch("omagenda.edit.save_previous", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self.edit(sentence.replace("Dentist", "Checkup"))
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(self.file.stat().st_ino, inode)
        self.assertFalse((self.state / "edited").exists())

    def test_refusals_shared_with_describe(self):
        for prop in (b"RRULE:FREQ=DAILY", b"RDATE:20260920T190000Z", b"RECURRENCE-ID:20260917T190000Z",
                     b"ATTENDEE:mailto:you@example.com", b"END:VEVENT\r\nBEGIN:VEVENT\r\nUID:second"):
            self.write_event(extra=prop + b"\r\n")
            for operation in (self.describe, lambda: self.edit("Checkup tomorrow 3pm")):
                with self.assertRaises(ValueError):
                    operation()
        self.write_event()
        calendars = discover_calendars()
        calendars[0]["readOnly"] = True
        with patch("omagenda.vdir.discover_calendars", return_value=calendars):
            for operation in (self.describe, lambda: self.edit("Checkup tomorrow 3pm")):
                with self.assertRaisesRegex(ValueError, "read-only"):
                    operation()
        other = self.folder.parent / "other"
        other.mkdir()
        (other / "displayname").write_text("Other")
        with self.assertRaisesRegex(ValueError, "Moving events between calendars isn't supported yet"):
            self.edit("Checkup tomorrow 3pm /other")

    def test_cli_json_dry_run_and_no_changes(self):
        # CLI uses today's real local reference, so use an unambiguous future year.
        self.write_event(start=REFERENCE.replace(year=datetime.now().year + 1))
        def cli(*args):
            return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
        description = cli("describe", str(self.file), "--json")
        self.assertEqual(description.returncode, 0, description.stderr)
        sentence = json.loads(description.stdout)["sentence"]
        unchanged = cli("edit", str(self.file), sentence)
        self.assertEqual(unchanged.stdout.strip(), "No changes")
        result = cli("edit", str(self.file), sentence.replace("Dentist", "Checkup"), "--dry-run", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"updated": True, "title": "Checkup", "calendar": "personal", "changed": ["SUMMARY"], "copy": None})

    def test_google_sync_updates_same_remote_event(self):
        from omagenda.bridges import RemoteCalendar, google
        from omagenda.sync import _sync_one_calendar
        from tests.test_bridge_google import STANDALONE_EVENT, _FakeResponse
        self.file.unlink()
        account = {"id": "google-demo", "type": "google"}
        calendar = RemoteCalendar(id="primary", name="Demo", writable=True)
        remote = dict(STANDALONE_EVENT, attendees=[], etag="recorded-etag")
        with patch.object(google, "_get_access_token", return_value="fake-token"), \
             patch("urllib.request.urlopen", return_value=_FakeResponse({"items": [remote], "nextSyncToken": "token1"})):
            _sync_one_calendar(google, account, calendar, self.folder, self.state)
        self.file = next(self.folder.glob("*.ics"))
        uid = str(self.event()["UID"])
        self.edit("Checkup on Sep 8 2026 at 1pm for 1h at Cafe Linnea")
        requests = []
        def respond(request, **kwargs):
            requests.append(request)
            if request.method == "PATCH":
                return _FakeResponse(dict(remote, summary="Checkup", etag="updated-etag"))
            return _FakeResponse({"items": [], "nextSyncToken": "token2"})
        with patch.object(google, "_get_access_token", return_value="fake-token"), \
             patch("urllib.request.urlopen", side_effect=respond):
            counts = _sync_one_calendar(google, account, calendar, self.folder, self.state)
            again = _sync_one_calendar(google, account, calendar, self.folder, self.state)
        self.assertTrue(counts["ok"], counts)
        self.assertTrue(again["ok"], again)
        writes = [r for r in requests if r.method != "GET"]
        self.assertEqual([r.method for r in writes], ["PATCH"])
        self.assertTrue(writes[0].full_url.endswith("/events/abc123"))
        self.assertEqual(writes[0].get_header("If-match"), "recorded-etag")
        self.assertEqual(json.loads(writes[0].data)["summary"], "Checkup")
        self.assertEqual(str(self.event()["UID"]), uid)

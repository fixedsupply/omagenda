"""Moves make a fresh, provider-independent target before touching source."""
import os
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import icalendar

from omagenda.bridges import PullChange, PullResult, RemoteCalendar, RemoteRef, SyncState, state_path_for
from omagenda.edit import edit_event
from omagenda.move import move_event
from omagenda.sync import _sync_one_calendar


REFERENCE = datetime(2026, 9, 16, 9, tzinfo=ZoneInfo("America/Edmonton"))
CLI = Path(__file__).resolve().parents[1] / "bin" / "omagenda"


class MoveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "vdir"
        self.personal = self.root / "personal"
        self.work = self.root / "work"
        for folder, name in ((self.personal, "Personal"), (self.work, "Work")):
            folder.mkdir(parents=True)
            (folder / "displayname").write_text(name)
        self.state = self.base / "state"
        env = patch.dict(os.environ, OMAGENDA_VDIR=str(self.root), OMAGENDA_STATE=str(self.state),
                         OMAGENDA_CONFIG=str(self.base / "config.toml"))
        env.start()
        self.addCleanup(env.stop)
        self.source = self.personal / "source.ics"
        self.write_source()

    def write_source(self, extra=b""):
        event = icalendar.Event()
        event.add("uid", "source@omagenda")
        event.add("summary", "Dental checkup")
        event.add("dtstart", REFERENCE.replace(day=17, hour=15))
        event.add("dtend", REFERENCE.replace(day=17, hour=16))
        event.add("sequence", 7)
        event.add("dtstamp", REFERENCE)
        calendar = icalendar.Calendar()
        calendar.add("version", "2.0")
        calendar.add_component(event)
        self.original = calendar.to_ical().replace(b"END:VEVENT", extra + b"END:VEVENT")
        self.source.write_bytes(self.original)

    def target(self):
        files = list(self.work.glob("*.ics"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_success_is_fresh_and_strips_provider_state(self):
        self.write_source(b"X-OMAGENDA-WEB-URL:https://old.example/event\r\nX-FOO:keep\r\n")
        result = move_event(str(self.source), "work")
        target = self.target()
        event = icalendar.Calendar.from_ical(target.read_bytes()).walk("VEVENT")[0]
        self.assertTrue(result["moved"])
        self.assertNotEqual(str(event["UID"]), "source@omagenda")
        self.assertEqual(target.stem, str(event["UID"]))
        self.assertEqual(int(event["SEQUENCE"]), 0)
        self.assertNotIn(b"X-OMAGENDA-", target.read_bytes())
        self.assertIn(b"X-FOO:keep", target.read_bytes())
        self.assertFalse(self.source.exists())
        saved = Path(result["copy"])
        self.assertEqual(saved.read_bytes(), self.original)
        self.assertEqual(saved.parent, self.state / "moved" / "personal")
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)

    def test_target_write_failure_rolls_back_before_source_changes(self):
        with patch("omagenda.move._write_new", side_effect=OSError("target full")):
            with self.assertRaisesRegex(OSError, "target full"):
                move_event(str(self.source), "work")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.work.glob("*.ics")), [])

    def test_source_removal_failure_reports_both_files(self):
        original_unlink = Path.unlink

        def fail_source(path, *args, **kwargs):
            if path == self.source:
                raise OSError("source busy")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_source):
            with self.assertRaisesRegex(RuntimeError, r"exists in both calendars: source .*source\.ics; target .*\.ics"):
                move_event(str(self.source), "work")
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target().exists())
        self.assertTrue(list((self.state / "moved" / "personal").glob("*.ics")))

    def test_refusals_and_no_op(self):
        cases = (
            (b"RRULE:FREQ=DAILY\r\n", "Recurring events"),
            (b"RDATE:20260920T190000Z\r\n", "Recurring events"),
            (b"RECURRENCE-ID:20260917T190000Z\r\n", "Recurring events"),
            (b"ATTENDEE:mailto:you@example.com\r\n", "guests"),
            (b"END:VEVENT\r\nBEGIN:VEVENT\r\nUID:second\r\n", "exactly one VEVENT"),
        )
        for extra, message in cases:
            with self.subTest(extra=extra):
                self.write_source(extra)
                with self.assertRaisesRegex(ValueError, message):
                    move_event(str(self.source), "work")
                self.assertTrue(self.source.exists())
        self.write_source()
        result = move_event(str(self.source), "personal")
        self.assertTrue(result["noOp"])
        self.assertTrue(self.source.exists())
        with self.assertRaisesRegex(ValueError, "no calendar named 'missing'"):
            move_event(str(self.source), "missing")
        calendars = __import__("omagenda.vdir", fromlist=["discover_calendars"]).discover_calendars()
        calendars[1]["readOnly"] = True
        with patch("omagenda.vdir.discover_calendars", return_value=calendars):
            with self.assertRaisesRegex(ValueError, "read-only"):
                move_event(str(self.source), "work")

    def test_hidden_target_and_dry_run(self):
        Path(os.environ["OMAGENDA_CONFIG"]).write_text('hidden_calendars = ["work"]\n')
        dry = move_event(str(self.source), "work", dry_run=True)
        self.assertTrue(dry["moved"])
        self.assertTrue(dry["hidden"])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.work.glob("*.ics")), [])
        result = move_event(str(self.source), "work")
        self.assertTrue(result["hidden"])

    def test_cli_move_dry_run_and_edit_calendar(self):
        dry = subprocess.run([sys.executable, str(CLI), "move", str(self.source), "work", "--dry-run", "--json"],
                             capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertTrue(json.loads(dry.stdout)["moved"])
        self.assertTrue(self.source.exists())
        edited = subprocess.run([sys.executable, str(CLI), "edit", str(self.source),
                                 "Orthodontist on Sep 17 at 3pm for 1h", "--calendar", "work", "--json"],
                                capture_output=True, text=True)
        self.assertEqual(edited.returncode, 0, edited.stderr)
        self.assertTrue(json.loads(edited.stdout)["moved"])
        self.assertFalse(self.source.exists())

    def test_sentence_edit_is_applied_to_the_moved_copy(self):
        result = edit_event(str(self.source), "Orthodontist on Sep 17 at 3pm for 1h", REFERENCE,
                            calendar_id="work")
        event = icalendar.Calendar.from_ical(self.target().read_bytes()).walk("VEVENT")[0]
        self.assertTrue(result["moved"])
        self.assertEqual(str(event["SUMMARY"]), "Orthodontist")
        self.assertFalse(self.source.exists())

    def test_provider_move_is_target_create_then_source_delete(self):
        """Google's UID adoption and a pull echo still carry both halves."""
        from tests.test_sync_bridge_orchestration import FakeBridge

        source = self.personal / "old.ics"
        self.source.rename(source)
        source.write_bytes(self.original.replace(b"UID:source@omagenda", b"UID:old"))
        old_content = source.read_bytes()
        state = SyncState(items={"old": {"remoteId": "remote-old", "etag": "old-etag",
                                           "localHash": __import__("hashlib").sha256(old_content).hexdigest()}})
        state_dir = self.state / "provider"
        state.save(state_path_for("google", "personal", state_dir))
        result = move_event(str(source), "work")

        target_bridge = FakeBridge()
        target_counts = _sync_one_calendar(target_bridge, {"id": "google", "type": "google"},
                                           RemoteCalendar(id="work", name="Work"), self.work, state_dir)
        source_bridge = FakeBridge(pull_results=[PullResult(changed=[
            PullChange(uid="old", ics_bytes=old_content, ref=RemoteRef("remote-old", "old-etag"))
        ])])
        source_counts = _sync_one_calendar(source_bridge, {"id": "google", "type": "google"},
                                           RemoteCalendar(id="personal", name="Personal"), self.personal, state_dir)
        self.assertTrue(result["moved"])
        self.assertEqual(target_counts["createdRemote"], 1)
        self.assertEqual(len(target_bridge.push_create_calls), 1)
        self.assertEqual(source_counts["deletedLocal"], 1)
        self.assertEqual([ref.remote_id for ref in source_bridge.push_delete_calls], ["remote-old"])
        self.assertFalse((self.personal / "old.ics").exists(), "a pull echo must not resurrect the source")

    def test_organizer_without_guests_moves_and_is_dropped_from_the_copy(self):
        """Apple writes ORGANIZER on events with no invitees; those have no guests.

        The copy is a new event, so a leftover ORGANIZER would make a CalDAV
        server treat it as a scheduling object it never issued.
        """
        self.write_source(b"ORGANIZER:mailto:you@example.com\r\n")
        result = move_event(str(self.source), "work")
        moved = Path(result["file"]).read_bytes()
        self.assertTrue(result["moved"])
        self.assertNotIn(b"ORGANIZER", moved)
        self.assertIn(b"SUMMARY:", moved)

    def test_pimsync_and_local_moves_are_plain_vdir_create_and_delete(self):
        """pimsync sees the same target file and missing source as any local vdir."""
        result = move_event(str(self.source), "work")
        self.assertTrue(result["moved"])
        self.assertFalse(self.source.exists())
        self.assertTrue(Path(result["file"]).exists())

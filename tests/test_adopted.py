"""Provider adoption preserves pending editor and delete paths."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from omagenda import adopted
from omagenda.delete import delete_event
from omagenda.edit import describe_event, edit_event
from omagenda.event_file import validate_event_file
from omagenda.sync import _sync_one_calendar
from tests.test_sync_bridge_orchestration import ACCOUNT, CALENDAR, FakeBridge, _ics


class AdoptedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "vdir"
        self.folder = self.root / "personal"
        self.folder.mkdir(parents=True)
        self.state = self.base / "state"
        env = patch.dict(os.environ, OMAGENDA_VDIR=str(self.root), OMAGENDA_STATE=str(self.state),
                         OMAGENDA_CONFIG=str(self.base / "config.toml"))
        env.start()
        self.addCleanup(env.stop)
        self.old = self.folder / "local@omagenda.ics"
        self.new = self.folder / "new-remote-id.ics"

    def test_create_adoption_describe_edit_delete(self):
        self.old.write_bytes(_ics(self.old.stem))
        counts = _sync_one_calendar(FakeBridge(), ACCOUNT, CALENDAR, self.folder, self.state)
        self.assertEqual(counts["createdRemote"], 1)
        entry = json.loads((self.state / "adopted.json").read_text())[str(self.old)]
        self.assertEqual(entry["path"], str(self.new))
        self.assertIsInstance(entry["time"], float)
        reference = datetime(2026, 9, 8, 9, tzinfo=ZoneInfo("America/Edmonton"))
        sentence = describe_event(str(self.old), reference)["sentence"]
        with patch("omagenda.index.index"):
            result = edit_event(str(self.old), sentence.replace("Event", "Edited event"), reference)
            self.assertEqual(result["file"], str(self.new))
            self.assertIn(b"SUMMARY:Edited event", self.new.read_bytes())
            result = delete_event(str(self.old))
        self.assertEqual(result["file"], str(self.new))
        self.assertFalse(self.new.exists())

    def test_pruning_and_chains(self):
        final = self.folder / "final.ics"
        final.write_bytes(_ics("final"))
        with patch("omagenda.adopted.time.time", return_value=100000):
            adopted.record(self.old, self.new)
        with patch("omagenda.adopted.time.time", return_value=100001):
            adopted.record(self.new, final)
            self.assertEqual(adopted.resolve(self.old), final)
        with patch("omagenda.adopted.time.time", return_value=186401):
            self.assertEqual(adopted.resolve(self.old), self.old)
            adopted.record(self.new, final)
        entries = json.loads((self.state / "adopted.json").read_text())
        self.assertNotIn(str(self.old), entries)

    def test_missing_without_alias(self):
        with self.assertRaises(FileNotFoundError):
            validate_event_file(str(self.old))

    def test_outside_alias_ignored_and_never_recorded(self):
        outside = self.base / "outside.ics"
        outside.write_bytes(_ics("outside"))
        adopted.record(self.old, outside)
        self.assertFalse((self.state / "adopted.json").exists())
        self.state.mkdir()
        import time
        (self.state / "adopted.json").write_text(json.dumps({str(self.old): {
            "path": str(outside), "time": time.time()}}))
        with self.assertRaises(FileNotFoundError):
            validate_event_file(str(self.old))

    def test_target_still_subject_to_validation(self):
        self.new.write_bytes(_ics("new").replace(b"END:VEVENT", b"RRULE:FREQ=DAILY\r\nEND:VEVENT"))
        adopted.record(self.old, self.new)
        with self.assertRaisesRegex(ValueError, "Recurring"):
            validate_event_file(str(self.old))

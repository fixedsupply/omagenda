"""Sync recording and freshness.

An event added in Quick Add reached the panel instantly and the server
never: `omagenda watch` only reindexed, and nothing ran a sync. The panel
could not have shown the problem either, because agenda.json's `lastSync`
field had no writer at all -- a sync that had never run looked exactly
like one that had just succeeded. These tests cover the record itself;
the watcher's scheduling of it lives in test_watch_sync.py.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from omagenda.index import build_agenda
from omagenda.sync import read_last_sync, record_path, _record_sync
from tests.test_sync import WithVdir


class RecordTest(unittest.TestCase):
    def test_absent_until_the_first_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_last_sync(Path(tmp)), {})

    def test_a_clean_run_records_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            _record_sync({"google": {"ok": True}}, Path(tmp))
            record = read_last_sync(Path(tmp))
        self.assertTrue(record["ok"])
        self.assertEqual(record["problems"], [])
        self.assertIn("T", record["at"])

    def test_a_failed_account_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            _record_sync({"google": {"ok": False, "detail": "network down"},
                          "personal": {"ok": True}}, Path(tmp))
            record = read_last_sync(Path(tmp))
        self.assertFalse(record["ok"])
        self.assertEqual(record["problems"], ["google"])

    def test_a_corrupt_record_reads_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = record_path(Path(tmp))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(read_last_sync(Path(tmp)), {})


class AgendaCarriesTheRecordTest(unittest.TestCase):
    def _agenda(self, state: Path):
        with WithVdir() as vdir_root:
            return build_agenda(vdir_root, days=1, start=date(2026, 9, 9),
                                state_dir=state, use_cache=False)

    def test_never_synced_is_reported_as_never(self):
        with tempfile.TemporaryDirectory() as tmp:
            agenda = self._agenda(Path(tmp))
        self.assertIsNone(agenda["lastSync"])

    def test_a_recorded_sync_reaches_the_agenda(self):
        with tempfile.TemporaryDirectory() as tmp:
            _record_sync({"google": {"ok": True}}, Path(tmp))
            agenda = self._agenda(Path(tmp))
        self.assertIsNotNone(agenda["lastSync"])
        self.assertTrue(agenda["syncOk"])

    def test_a_failed_sync_reaches_the_agenda(self):
        with tempfile.TemporaryDirectory() as tmp:
            _record_sync({"google": {"ok": False, "detail": "nope"}}, Path(tmp))
            agenda = self._agenda(Path(tmp))
        self.assertFalse(agenda["syncOk"])

    def test_sync_all_records_itself(self):
        with tempfile.TemporaryDirectory() as tmp, WithVdir():
            from omagenda.sync import sync_all

            sync_all({"accounts": []}, state_dir=Path(tmp))
            self.assertIn("at", read_last_sync(Path(tmp)))


if __name__ == "__main__":
    unittest.main()

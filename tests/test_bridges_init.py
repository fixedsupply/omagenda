"""Tests for the bridge interface's shared pieces: SyncState persistence
and the sync-state file path convention. See ARCHITECTURE.md §11."""
import tempfile
import unittest
from pathlib import Path

from omagenda.bridges import PullChange, PullResult, RemoteCalendar, RemoteRef, SyncState, state_path_for


class SyncStateTest(unittest.TestCase):
    def test_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sync" / "google-calvin" / "primary.json"
            state = SyncState(cursor="abc123", items={"uid1@omagenda": {"remoteId": "r1", "etag": "e1", "localHash": "h1"}})
            state.save(path)
            reloaded = SyncState.load(path)
            self.assertEqual(reloaded.cursor, "abc123")
            self.assertEqual(reloaded.items["uid1@omagenda"]["remoteId"], "r1")

    def test_missing_file_is_a_fresh_empty_state(self):
        state = SyncState.load(Path("/nonexistent/path/state.json"))
        self.assertIsNone(state.cursor)
        self.assertEqual(state.items, {})

    def test_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            SyncState(cursor="x").save(path)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


class StatePathForTest(unittest.TestCase):
    def test_sanitizes_calendar_id_with_at_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = state_path_for("google-calvin", "family@group.calendar.google.com", state_dir=Path(tmp))
            self.assertTrue(str(path).endswith("sync/google-calvin/family@group.calendar.google.com.json"))

    def test_sanitizes_a_path_separator_in_either_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = state_path_for("acc/ount", "cal/endar", state_dir=Path(tmp))
            self.assertNotIn("acc/ount", str(path.relative_to(Path(tmp) / "sync")))
            self.assertIn("_", path.parent.name)


class DataclassesTest(unittest.TestCase):
    def test_pull_result_defaults(self):
        result = PullResult()
        self.assertEqual(result.changed, [])
        self.assertEqual(result.deleted_uids, [])
        self.assertFalse(result.full_resync)

    def test_pull_change_and_remote_calendar_are_plain_data(self):
        cal = RemoteCalendar(id="primary", name="Calvin", writable=True)
        change = PullChange(uid="u@omagenda", ics_bytes=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", ref=RemoteRef(remote_id="r1", etag="e1"))
        self.assertEqual(cal.id, "primary")
        self.assertEqual(change.ref.etag, "e1")


if __name__ == "__main__":
    unittest.main()

"""Regression scenarios use invented events, temporary files and fake bridges."""
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from omagenda.accounts import write_config
from omagenda.bridges import ConflictError, PullChange, PullResult, RemoteCalendar, RemoteRef
from omagenda.bridges import google
from omagenda.sync import _sync_one_calendar
from tests.test_sync_bridge_orchestration import FakeBridge, _ics

ACCOUNT = {"id": "demo", "type": "google"}
CALENDAR = RemoteCalendar("demo-calendar", "Demo")


def change(title, etag="v1"):
    return PullChange("demo", _ics("demo", title), RemoteRef("demo", etag))


class SyncReliabilityTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cal = self.root / "calendar"
        self.state = self.root / "state"
        notification = patch("omagenda.sync._notify_conflict")
        self.notify = notification.start()
        self.addCleanup(notification.stop)
        self.sync(FakeBridge([PullResult(changed=[change("Original")], next_cursor="cursor")]))

    def sync(self, bridge, calendar=CALENDAR):
        return _sync_one_calendar(bridge, ACCOUNT, calendar, self.cal, self.state)

    def test_simultaneous_edits_preserve_local_and_show_remote(self):
        (self.cal / "demo.ics").write_bytes(_ics("demo", "Local edit"))
        bridge = FakeBridge([PullResult(changed=[change("Phone edit", "v2")])])
        result = self.sync(bridge)
        self.assertEqual(result["conflicts"], 1)
        self.assertIn(b"Local edit", (self.cal / "demo.conflict.ics").read_bytes())
        self.assertIn(b"Phone edit", (self.cal / "demo.ics").read_bytes())
        self.assertEqual(bridge.push_update_calls, [])

    def test_conflict_copies_do_not_appear_as_duplicate_appointments(self):
        from datetime import date
        from omagenda.index import build_agenda
        (self.cal / "demo.conflict.ics").write_bytes(_ics("demo", "Unresolved edit"))
        agenda = build_agenda(self.root, start=date(2026, 9, 8), days=1,
                              state_dir=self.state, use_cache=False)
        self.assertEqual([event["title"] for event in agenda["events"]], ["Original"])

    def test_add_json_with_warning_is_still_a_single_json_document(self):
        import json
        import os
        import subprocess
        import sys
        env = {**os.environ, "OMAGENDA_VDIR": str(self.root),
               "OMAGENDA_STATE": str(self.state), "OMAGENDA_CONFIG": str(self.root / "config.toml")}
        cli = Path(__file__).resolve().parent.parent / "bin" / "omagenda"
        result = subprocess.run([sys.executable, str(cli), "add", "Review at 3", "--json"],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["event"]["warnings"])

    def test_delete_conflict_retains_remote_and_requests_refresh(self):
        from omagenda.bridges import SyncState, state_path_for
        (self.cal / "demo.ics").unlink()
        bridge = FakeBridge([PullResult(changed=[change("Phone edit", "v2")])])
        with patch.object(bridge, "push_delete", side_effect=ConflictError("changed")):
            result = self.sync(bridge)
        self.assertFalse(result["ok"])
        self.assertIn(b"Phone edit", (self.cal / "demo.ics").read_bytes())
        state = SyncState.load(state_path_for(ACCOUNT["id"], CALENDAR.id, self.state))
        self.assertIsNone(state.cursor)

    def test_edit_during_network_request_is_preserved(self):
        bridge = FakeBridge()
        def delayed_pull(*args):
            (self.cal / "demo.ics").write_bytes(_ics("demo", "Edited during download"))
            return PullResult(changed=[change("Phone edit", "v2")])
        with patch.object(bridge, "pull", side_effect=delayed_pull):
            self.sync(bridge)
        self.assertIn(b"Edited during download", (self.cal / "demo.conflict.ics").read_bytes())

    def test_unchanged_remote_does_not_overwrite_local_edit(self):
        (self.cal / "demo.ics").write_bytes(_ics("demo", "Local edit"))
        bridge = FakeBridge([PullResult(changed=[change("Original")])])
        self.sync(bridge)
        self.assertIn(b"Local edit", bridge.push_update_calls[0][0])

    def test_remote_deletion_preserves_unsynced_edit(self):
        (self.cal / "demo.ics").write_bytes(_ics("demo", "Local edit"))
        self.sync(FakeBridge([PullResult(deleted_uids=["demo"])]))
        self.assertFalse((self.cal / "demo.ics").exists())
        self.assertIn(b"Local edit", (self.cal / "demo.conflict.ics").read_bytes())

    def test_full_resync_removes_absent_remote_without_pushing_delete(self):
        bridge = FakeBridge([PullResult(full_resync=True)])
        self.sync(bridge)
        self.assertFalse((self.cal / "demo.ics").exists())
        self.assertEqual(bridge.push_delete_calls, [])

    def test_delete_uses_version_from_before_pull(self):
        (self.cal / "demo.ics").unlink()
        bridge = FakeBridge([PullResult(changed=[change("Phone edit", "v2")])])
        self.sync(bridge)
        self.assertEqual(bridge.push_delete_calls[0].etag, "v1")

    def test_readonly_calendar_never_pushes(self):
        (self.cal / "new.ics").write_bytes(_ics("new"))
        bridge = FakeBridge()
        self.sync(bridge, RemoteCalendar(CALENDAR.id, "Read only", writable=False))
        self.assertEqual(bridge.push_create_calls, [])
        self.assertEqual(self.cal.stat().st_mode & 0o777, 0o555)
        self.cal.chmod(0o755)

    def test_readonly_permissions_restored_after_pull_failure(self):
        bridge = FakeBridge()
        with patch.object(bridge, "pull", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.sync(bridge, RemoteCalendar(CALENDAR.id, "Read only", writable=False))
        self.assertEqual(self.cal.stat().st_mode & 0o777, 0o555)
        self.cal.chmod(0o755)

    def test_conflict_copy_is_not_overwritten(self):
        (self.cal / "demo.conflict.ics").write_bytes(_ics("demo", "Older conflict"))
        (self.cal / "demo.ics").write_bytes(_ics("demo", "Local edit"))
        self.sync(FakeBridge([PullResult(changed=[change("Phone edit", "v2")])]))
        copies = [p.read_bytes() for p in self.cal.glob("*.conflict.ics")]
        self.assertEqual(len(copies), 2)
        self.assertTrue(any(b"Older conflict" in data for data in copies))
        self.assertTrue(any(b"Local edit" in data for data in copies))


class GoogleReliabilityTest(unittest.TestCase):
    EVENT = {"id": "demo", "etag": "v1", "summary": "Demo",
             "start": {"date": "2026-09-15"}, "end": {"date": "2026-09-16"}}

    def test_pull_retains_etag(self):
        with patch.object(google, "_authed_request", return_value=(200, {"items": [self.EVENT]}, {})):
            result = google.pull(ACCOUNT, CALENDAR, "cursor")
        self.assertEqual(result.changed[0].ref.etag, "v1")

    def test_instance_only_delta_rebuilds_complete_series(self):
        master = {**self.EVENT, "recurrence": ["RRULE:FREQ=DAILY;COUNT=3"]}
        exception = {"id": "demo-instance", "recurringEventId": "demo", "status": "cancelled",
                     "originalStartTime": {"date": "2026-09-16"}}
        responses = [(200, {"items": [exception], "nextSyncToken": "delta"}, {}),
                     (200, {"items": [master, exception], "nextSyncToken": "full"}, {})]
        with patch.object(google, "_authed_request", side_effect=responses) as request:
            result = google.pull(ACCOUNT, CALENDAR, "cursor")
        self.assertEqual(request.call_count, 2)
        self.assertTrue(result.full_resync)
        self.assertEqual(result.next_cursor, "full")
        self.assertIn(b"EXDATE;VALUE=DATE:20260916", result.changed[0].ics_bytes)

    def test_update_patches_only_supported_fields_and_checks_version(self):
        with patch.object(google, "_authed_request", return_value=(200, self.EVENT, {})) as request:
            google.push_update(ACCOUNT, CALENDAR, _ics("demo", "Edited"), RemoteRef("demo", "v1"))
        self.assertEqual(request.call_args.args[1], "PATCH")
        body = request.call_args.kwargs["body"]
        self.assertNotIn("attendees", body)
        self.assertNotIn("conferenceData", body)
        self.assertEqual(body["location"], "")
        self.assertEqual(request.call_args.kwargs["extra_headers"], {"If-Match": "v1"})

    def test_recurrence_date_parameters_survive_push(self):
        import icalendar
        content = _ics("demo").replace(b"END:VEVENT", b"RDATE;VALUE=DATE:20260920\r\nEXDATE;TZID=America/Edmonton:20260921T130000\r\nEND:VEVENT")
        event = icalendar.Calendar.from_ical(content).walk("VEVENT")[0]
        body = google._local_event_to_google_body(event)
        self.assertIn("RDATE;VALUE=DATE:20260920", body["recurrence"])
        self.assertIn("EXDATE;TZID=America/Edmonton:20260921T130000", body["recurrence"])

    def test_missing_version_cannot_update_or_delete(self):
        with patch.object(google, "_authed_request") as request:
            with self.assertRaises(ConflictError):
                google.push_update(ACCOUNT, CALENDAR, _ics("demo"), RemoteRef("demo"))
            with self.assertRaises(ConflictError):
                google.push_delete(ACCOUNT, CALENDAR, RemoteRef("demo"))
        request.assert_not_called()

    def test_delete_checks_version(self):
        with patch.object(google, "_authed_request", return_value=(204, None, {})) as request:
            google.push_delete(ACCOUNT, CALENDAR, RemoteRef("demo", "v1"))
        self.assertEqual(request.call_args.kwargs["extra_headers"], {"If-Match": "v1"})

    def test_multi_component_edit_is_not_silently_truncated(self):
        content = _ics("demo").replace(b"END:VCALENDAR", b"BEGIN:VEVENT\r\nUID:demo\r\nEND:VEVENT\r\nEND:VCALENDAR")
        with patch.object(google, "_authed_request") as request:
            with self.assertRaises(ValueError):
                google.push_update(ACCOUNT, CALENDAR, content, RemoteRef("demo", "v1"))
        request.assert_not_called()


class ConfigReliabilityTest(unittest.TestCase):
    def test_saving_default_keeps_sync_configuration(self):
        config = {"default_calendar": "demo", "sync_interval": 90, "sync_workers": 2}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            write_config(config, path)
            self.assertEqual(tomllib.loads(path.read_text()), config)

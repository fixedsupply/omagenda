"""Tests for sync.py's shared pull/detect/push/record algorithm
(ARCHITECTURE.md §11), driven against a fake Bridge -- no real network,
no real Google account needed to verify the orchestration itself."""
import tempfile
import unittest
from pathlib import Path

from omagenda.bridges import ConflictError, PullChange, PullResult, RemoteCalendar, RemoteRef
from omagenda.sync import _select_calendars, _sync_one_calendar

ACCOUNT = {"id": "google-calvin", "type": "google"}
CALENDAR = RemoteCalendar(id="primary", name="Calvin", writable=True)


def _ics(uid: str, summary: str = "Event") -> bytes:
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n"
        "DTSTART;TZID=America/Edmonton:20260908T130000\r\nDTEND;TZID=America/Edmonton:20260908T140000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


class FakeBridge:
    def __init__(self, pull_results=None, list_calendars_result=None, conflict_uids=None):
        self._pull_results = list(pull_results or [])
        self.list_calendars_result = list_calendars_result or []
        self._conflict_uids = set(conflict_uids or [])
        self.push_create_calls = []
        self.push_update_calls = []
        self.push_delete_calls = []

    def list_calendars(self, account):
        return self.list_calendars_result

    def pull(self, account, calendar, cursor):
        return self._pull_results.pop(0) if self._pull_results else PullResult()

    def push_create(self, account, calendar, ics_bytes):
        self.push_create_calls.append(ics_bytes)
        return RemoteRef(remote_id="new-remote-id", etag="etag-1")

    def push_update(self, account, calendar, ics_bytes, ref):
        self.push_update_calls.append((ics_bytes, ref))
        if ref.remote_id in self._conflict_uids:
            raise ConflictError("stale etag")
        return RemoteRef(remote_id=ref.remote_id, etag="etag-updated")

    def push_delete(self, account, calendar, ref):
        self.push_delete_calls.append(ref)


class SyncOneCalendarTest(unittest.TestCase):
    def test_pull_writes_files_and_records_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "calendars" / "google-calvin" / "primary"
            state_dir = Path(tmp) / "state"
            bridge = FakeBridge(pull_results=[PullResult(
                changed=[PullChange(uid="a@g", ics_bytes=_ics("a@g"), ref=RemoteRef(remote_id="a@g", etag="e1"))],
                next_cursor="tok-1",
            )])

            counts = _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)

            self.assertTrue(counts["ok"])
            self.assertEqual(counts["pulled"], 1)
            self.assertTrue((calendar_path / "a@g.ics").exists())

            from omagenda.bridges import SyncState, state_path_for

            state = SyncState.load(state_path_for("google-calvin", "primary", state_dir))
            self.assertEqual(state.cursor, "tok-1")
            self.assertEqual(state.items["a@g"]["etag"], "e1")

    def test_pulled_file_is_not_immediately_pushed_back(self):
        # a file this same cycle just wrote from a pull must not look like
        # a local change and bounce straight back to the server
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            bridge = FakeBridge(pull_results=[PullResult(
                changed=[PullChange(uid="a@g", ics_bytes=_ics("a@g"), ref=RemoteRef(remote_id="a@g", etag="e1"))],
            )])
            _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=Path(tmp) / "state")
            self.assertEqual(bridge.push_create_calls, [])
            self.assertEqual(bridge.push_update_calls, [])

    def test_new_local_file_is_pushed_as_a_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            calendar_path.mkdir(parents=True)
            (calendar_path / "local1@omagenda.ics").write_bytes(_ics("local1@omagenda", "New event"))
            bridge = FakeBridge()

            counts = _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=Path(tmp) / "state")

            self.assertEqual(counts["createdRemote"], 1)
            self.assertEqual(len(bridge.push_create_calls), 1)

    def test_modified_local_file_is_pushed_as_an_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            state_dir = Path(tmp) / "state"
            calendar_path.mkdir(parents=True)
            # first sync: pull one event, establishing state
            bridge = FakeBridge(pull_results=[PullResult(
                changed=[PullChange(uid="a@g", ics_bytes=_ics("a@g", "Original"), ref=RemoteRef(remote_id="a@g", etag="e1"))],
            )])
            _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)

            # user hand-edits the file locally between syncs
            (calendar_path / "a@g.ics").write_bytes(_ics("a@g", "Edited locally"))
            counts = _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)

            self.assertEqual(counts["updated"], 1)
            self.assertEqual(len(bridge.push_update_calls), 1)
            pushed_ref = bridge.push_update_calls[0][1]
            self.assertEqual(pushed_ref.etag, "e1")  # pushed with the etag from the original pull

    def test_locally_deleted_file_is_pushed_as_a_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            state_dir = Path(tmp) / "state"
            bridge = FakeBridge(pull_results=[
                PullResult(changed=[PullChange(uid="a@g", ics_bytes=_ics("a@g"), ref=RemoteRef(remote_id="a@g", etag="e1"))]),
                PullResult(),  # second sync pulls nothing new
            ])
            _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)
            (calendar_path / "a@g.ics").unlink()

            counts = _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)

            self.assertEqual(counts["deletedLocal"], 1)
            self.assertEqual(len(bridge.push_delete_calls), 1)
            self.assertEqual(bridge.push_delete_calls[0].remote_id, "a@g")

    def test_conflict_saves_a_conflict_copy_and_notifies_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            state_dir = Path(tmp) / "state"
            bridge = FakeBridge(
                pull_results=[PullResult(changed=[PullChange(uid="a@g", ics_bytes=_ics("a@g", "v1"), ref=RemoteRef(remote_id="a@g", etag="e1"))])],
                conflict_uids={"a@g"},
            )
            _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)
            (calendar_path / "a@g.ics").write_bytes(_ics("a@g", "edited locally, will conflict"))

            from unittest import mock
            with mock.patch("omagenda.sync._notify_conflict") as notify:
                counts = _sync_one_calendar(bridge, ACCOUNT, CALENDAR, calendar_path, state_dir=state_dir)

            self.assertEqual(counts["conflicts"], 1)
            self.assertTrue((calendar_path / "a@g.conflict.ics").exists())
            notify.assert_called_once()

    def test_a_broken_push_reports_an_error_but_does_not_stop_other_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendar_path = Path(tmp) / "cal"
            calendar_path.mkdir(parents=True)
            (calendar_path / "ok@omagenda.ics").write_bytes(_ics("ok@omagenda", "Fine"))

            class BrokenBridge(FakeBridge):
                def push_create(self, account, calendar, ics_bytes):
                    raise RuntimeError("network exploded")

            counts = _sync_one_calendar(BrokenBridge(), ACCOUNT, CALENDAR, calendar_path, state_dir=Path(tmp) / "state")
            self.assertFalse(counts["ok"])
            self.assertEqual(counts["createdRemote"], 0)
            self.assertIn("errors", counts)


class SelectCalendarsTest(unittest.TestCase):
    def test_empty_config_selects_only_writable_calendars(self):
        bridge = FakeBridge(list_calendars_result=[
            RemoteCalendar(id="primary", name="Calvin", writable=True),
            RemoteCalendar(id="readonly-holidays", name="Holidays", writable=False),
        ])
        selected = _select_calendars(bridge, {"id": "g", "type": "google"})
        self.assertEqual([c.id for c in selected], ["primary"])

    def test_explicit_calendars_list_overrides_writable_filter(self):
        bridge = FakeBridge(list_calendars_result=[
            RemoteCalendar(id="primary", name="Calvin", writable=True),
            RemoteCalendar(id="readonly-holidays", name="Holidays", writable=False),
        ])
        selected = _select_calendars(bridge, {"id": "g", "type": "google", "calendars": ["readonly-holidays"]})
        self.assertEqual([c.id for c in selected], ["readonly-holidays"])

    def test_unknown_configured_calendar_is_silently_skipped(self):
        bridge = FakeBridge(list_calendars_result=[RemoteCalendar(id="primary", name="Calvin", writable=True)])
        selected = _select_calendars(bridge, {"id": "g", "type": "google", "calendars": ["typo-id"]})
        self.assertEqual(selected, [])


class SyncAllIntegrationTest(unittest.TestCase):
    """Drives the whole path through the public sync_all() entry point,
    with a fake bridge module registered in sys.modules -- catches
    mismatches between _sync_bridge's return shape and what sync_all/the
    CLI expect that a lower-level unit test wouldn't."""

    def test_sync_all_dispatches_a_google_account_through_the_real_pipeline(self):
        import sys
        import types

        from omagenda.sync import sync_all

        fake_module = types.ModuleType("omagenda.bridges.fake_google")
        bridge = FakeBridge(
            list_calendars_result=[RemoteCalendar(id="primary", name="Calvin", writable=True)],
            pull_results=[PullResult(changed=[
                PullChange(uid="a@g", ics_bytes=_ics("a@g"), ref=RemoteRef(remote_id="a@g", etag="e1")),
            ])],
        )
        fake_module.list_calendars = bridge.list_calendars
        fake_module.pull = bridge.pull
        fake_module.push_create = bridge.push_create
        fake_module.push_update = bridge.push_update
        fake_module.push_delete = bridge.push_delete
        sys.modules["omagenda.bridges.fake_google"] = fake_module

        with tempfile.TemporaryDirectory() as tmp:
            from unittest import mock

            with mock.patch("omagenda.sync.BRIDGE_MODULES", {"google": "omagenda.bridges.fake_google"}),                  mock.patch("omagenda.sync.resolve_vdir_root", return_value=Path(tmp)):
                results = sync_all({"accounts": [{"id": "google-calvin", "type": "google"}]})

        del sys.modules["omagenda.bridges.fake_google"]

        self.assertTrue(results["google-calvin"]["ok"])
        self.assertEqual(results["google-calvin"]["calendars"]["primary"]["pulled"], 1)


if __name__ == "__main__":
    unittest.main()

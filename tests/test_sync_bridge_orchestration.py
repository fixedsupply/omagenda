"""Tests for sync.py's shared pull/detect/push/record algorithm
(ARCHITECTURE.md §11), driven against a fake Bridge -- no real network,
no real Google account needed to verify the orchestration itself."""
import os
import tempfile
import unittest
from pathlib import Path

import icalendar

from omagenda.bridges import ConflictError, PullChange, PullResult, RemoteCalendar, RemoteRef
from omagenda.sync import _rewrite_uid, _select_calendars, _sync_one_calendar
from omagenda.vdir import discover_calendars

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



def _sync_bridge_for_test(bridge, root, calendars):
    """Drive _sync_bridge with a stub bridge, without importlib."""
    import importlib
    import unittest.mock

    import omagenda.sync as sync_module

    # _sync_bridge imports its bridge module by name at call time.
    with unittest.mock.patch.object(importlib, "import_module", return_value=bridge), \
            unittest.mock.patch.dict(sync_module.BRIDGE_MODULES, {"stub": "stub.module"}):
        return sync_module._sync_bridge({"id": "acct", "type": "stub"}, root, state_dir=root / "state")


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
                # state_dir has to be pinned too. Without it this wrote real
                # sync state into ~/.local/state/omagenda -- it did exactly
                # that once, because _sync_bridge accepted a state_dir and
                # then never forwarded it to _sync_one_calendar.
                results = sync_all({"accounts": [{"id": "google-calvin", "type": "google"}]},
                                   state_dir=Path(tmp) / "state")

            self.assertTrue((Path(tmp) / "state" / "sync" / "google-calvin" / "primary.json").exists())

        del sys.modules["omagenda.bridges.fake_google"]

        self.assertTrue(results["google-calvin"]["ok"])
        self.assertEqual(results["google-calvin"]["calendars"]["primary"]["pulled"], 1)


if __name__ == "__main__":
    unittest.main()


class VdirMetadataTest(unittest.TestCase):
    """A bridge calendar has a name and a colour on the remote and an
    access role that says whether it takes writes. None of that reached
    the vdir before, so a real Google account showed up in the panel as a
    column of raw ids, all of them apparently writable -- which meant
    Quick Add offered holiday feeds as destinations.
    """

    def _run(self, writable=True, color="green"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        calendar = RemoteCalendar(id="cal-1", name="Holidays in Canada",
                                  writable=writable, color=color)
        bridge = FakeBridge()
        path = root / "acct" / calendar.id
        _sync_one_calendar(bridge, {"id": "acct"}, calendar, path,
                           state_dir=root / "state")
        return path

    def test_display_name_and_colour_are_written(self):
        path = self._run()
        self.assertEqual((path / "displayname").read_text(), "Holidays in Canada")
        self.assertEqual((path / "color").read_text(), "green")

    def test_a_read_only_calendar_is_marked_read_only(self):
        path = self._run(writable=False)
        self.assertFalse(os.access(path, os.W_OK))

    def test_a_writable_calendar_stays_writable(self):
        self.assertTrue(os.access(self._run(writable=True), os.W_OK))

    def test_no_colour_writes_no_colour_file(self):
        self.assertFalse((self._run(color=None) / "color").exists())

    def test_a_read_only_calendar_can_be_synced_twice(self):
        # The 0555 marker is written by the first sync and would block the
        # second one from writing into its own folder.
        path = self._run(writable=False)
        calendar = RemoteCalendar(id="cal-1", name="Holidays in Canada", writable=False)
        _sync_one_calendar(FakeBridge(), {"id": "acct"},
                           calendar, path, state_dir=path.parent.parent / "state")
        self.assertFalse(os.access(path, os.W_OK))

    def test_discovery_sees_the_name_and_the_read_only_flag(self):
        self._run(writable=False)
        path = self._run(writable=False)
        found = {c["id"]: c for c in discover_calendars(path.parent.parent)}
        entry = next(iter(found.values()))
        self.assertEqual(entry["name"], "Holidays in Canada")
        self.assertTrue(entry["readOnly"])


class AdoptRemoteUidTest(unittest.TestCase):
    """An event created in Omagenda used to come back from the next pull
    as a second, separate event.

    Omagenda invents a UID when it writes the .ics; Google ignores it on
    insert and assigns its own event id, and every later pull keys the
    event by that id. So the pull wrote the server's copy next to the
    local one and the appointment appeared twice, permanently. The fix is
    to take on the remote's id the moment the create succeeds.
    """

    LOCAL = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
             b"UID:invented-1@omagenda\r\nDTSTART:20260909T160000Z\r\n"
             b"DTEND:20260909T170000Z\r\nSUMMARY:Coffee\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def _calendar_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_create_renames_the_file_to_the_remote_id(self):
        root = self._calendar_dir()
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        (path / "invented-1@omagenda.ics").write_bytes(self.LOCAL)

        calendar = RemoteCalendar(id="cal-1", name="Primary")
        bridge = FakeBridge()
        counts = _sync_one_calendar(bridge, {"id": "acct"}, calendar, path,
                                    state_dir=root / "state")

        self.assertEqual(counts["createdRemote"], 1)
        self.assertFalse((path / "invented-1@omagenda.ics").exists())
        self.assertTrue((path / "new-remote-id.ics").exists())

    def test_the_uid_inside_the_file_is_rewritten_too(self):
        root = self._calendar_dir()
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        (path / "invented-1@omagenda.ics").write_bytes(self.LOCAL)

        _sync_one_calendar(FakeBridge(), {"id": "acct"},
                           RemoteCalendar(id="cal-1", name="Primary"), path,
                           state_dir=root / "state")

        event = next(iter(icalendar.Calendar.from_ical(
            (path / "new-remote-id.ics").read_bytes()).walk("VEVENT")))
        self.assertEqual(str(event["UID"]), "new-remote-id")

    def test_a_pull_of_the_same_event_does_not_make_a_second_copy(self):
        root = self._calendar_dir()
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        (path / "invented-1@omagenda.ics").write_bytes(self.LOCAL)
        calendar = RemoteCalendar(id="cal-1", name="Primary")

        _sync_one_calendar(FakeBridge(), {"id": "acct"}, calendar, path,
                           state_dir=root / "state")

        # The server now hands the same event back under its own id.
        served = self.LOCAL.replace(b"invented-1@omagenda", b"new-remote-id")
        bridge = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="new-remote-id", ics_bytes=served,
            ref=RemoteRef(remote_id="new-remote-id", etag="etag-2"))])])
        _sync_one_calendar(bridge, {"id": "acct"}, calendar, path,
                           state_dir=root / "state")

        self.assertEqual(sorted(p.name for p in path.glob("*.ics")),
                         ["new-remote-id.ics"])

    def test_the_adopted_event_is_not_mistaken_for_a_local_deletion(self):
        root = self._calendar_dir()
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        (path / "invented-1@omagenda.ics").write_bytes(self.LOCAL)

        bridge = FakeBridge()
        _sync_one_calendar(bridge, {"id": "acct"},
                           RemoteCalendar(id="cal-1", name="Primary"), path,
                           state_dir=root / "state")

        self.assertEqual(bridge.push_delete_calls, [])

    def test_a_folded_uid_line_is_replaced_whole(self):
        folded = (b"BEGIN:VEVENT\r\nUID:a-very-long-uid-that-the-server\r\n"
                  b" -wrapped-across-lines\r\nSUMMARY:x\r\nEND:VEVENT\r\n")
        self.assertEqual(
            _rewrite_uid(folded, "short"),
            b"BEGIN:VEVENT\r\nUID:short\r\nSUMMARY:x\r\nEND:VEVENT\r\n")

    def test_a_file_with_no_uid_is_left_alone(self):
        raw = b"BEGIN:VEVENT\r\nSUMMARY:x\r\nEND:VEVENT\r\n"
        self.assertEqual(_rewrite_uid(raw, "short"), raw)


class ConcurrencyTest(unittest.TestCase):
    """Calendars are synced concurrently because a sync is almost all
    waiting: an incremental pull that returns nothing still costs Google
    the better part of ten seconds, so twelve calendars done in series
    took two and a half minutes. Correctness must not depend on the
    order they finish in.
    """

    def _calendars(self, n):
        return [RemoteCalendar(id=f"cal-{i}", name=f"Calendar {i}") for i in range(n)]

    def test_every_calendar_is_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendars = self._calendars(5)
            bridge = FakeBridge(list_calendars_result=calendars)
            result = _sync_bridge_for_test(bridge, Path(tmp), calendars)
        self.assertEqual(sorted(result["calendars"]), sorted(c.id for c in calendars))
        self.assertTrue(result["ok"])

    def test_results_are_reported_in_the_listed_order(self):
        # as_completed hands them back in whatever order they finish, so
        # the report is re-ordered deliberately; a shuffled list of
        # calendars in the CLI output would be its own small bug.
        with tempfile.TemporaryDirectory() as tmp:
            calendars = self._calendars(6)
            bridge = FakeBridge(list_calendars_result=calendars)
            result = _sync_bridge_for_test(bridge, Path(tmp), calendars)
        self.assertEqual(list(result["calendars"]), [c.id for c in calendars])

    def test_one_failing_calendar_does_not_sink_the_others(self):
        class OneBadBridge(FakeBridge):
            def pull(self, account, calendar, cursor):
                if calendar.id == "cal-2":
                    raise RuntimeError("that calendar is on fire")
                return PullResult()

        with tempfile.TemporaryDirectory() as tmp:
            calendars = self._calendars(5)
            result = _sync_bridge_for_test(OneBadBridge(list_calendars_result=calendars),
                                           Path(tmp), calendars)
        self.assertFalse(result["ok"])
        self.assertFalse(result["calendars"]["cal-2"]["ok"])
        self.assertTrue(all(result["calendars"][c.id]["ok"] for c in calendars if c.id != "cal-2"))

    def test_a_single_calendar_skips_the_pool_entirely(self):
        with tempfile.TemporaryDirectory() as tmp:
            calendars = self._calendars(1)
            result = _sync_bridge_for_test(FakeBridge(list_calendars_result=calendars),
                                           Path(tmp), calendars)
        self.assertTrue(result["ok"])


class MappingVersionResyncTest(unittest.TestCase):
    """A bridge that starts mapping a new remote field (Google's htmlLink in
    v0.3.0) forces one full pull per calendar, then goes back to incremental."""

    EVENT = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:r1\r\nSUMMARY:Lunch\r\n"
             b"DTSTART:20260917T190000Z\r\nDTEND:20260917T200000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_old_state_pulls_in_full_once_and_keeps_a_pending_edit(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        calendar = RemoteCalendar(id="cal-1", name="Primary")
        seed = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="r1", ics_bytes=self.EVENT, ref=RemoteRef(remote_id="r1", etag="e1"))], next_cursor="old-token")])
        _sync_one_calendar(seed, {"id": "acct"}, calendar, path, state_dir=root / "state")

        edited = self.EVENT.replace(b"SUMMARY:Lunch", b"SUMMARY:Lunch moved")
        (path / "r1.ics").write_bytes(edited)

        class VersionedBridge(FakeBridge):
            MAPPING_VERSION = 2

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.cursors = []

            def pull(self, account, calendar, cursor):
                self.cursors.append(cursor)
                return super().pull(account, calendar, cursor)

        remapped = self.EVENT.replace(b"END:VEVENT", b"X-OMAGENDA-WEB-URL:https://calendar.google.com/x\r\nEND:VEVENT")
        bridge = VersionedBridge(pull_results=[
            PullResult(changed=[PullChange(uid="r1", ics_bytes=remapped, ref=RemoteRef(remote_id="r1", etag="e1"))],
                       next_cursor="new-token", full_resync=True),
            PullResult(next_cursor="newer-token")])
        counts = _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")
        self.assertEqual(bridge.cursors, [None], "an older mapping must pull in full")
        self.assertEqual(counts["conflicts"], 0)
        self.assertEqual(counts["deletedRemote"], 0)
        self.assertEqual([body for body, _ in bridge.push_update_calls], [edited])
        self.assertEqual((path / "r1.ics").read_bytes(), edited)

        _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")
        self.assertEqual(bridge.cursors, [None, "new-token"], "the resync happens only once")


class EditVersusEchoTest(unittest.TestCase):
    """Editing an event you had only just created used to be reverted.

    Reported 2026-09-16: Quick Add created a Google event, the sync pushed
    it and adopted Google's id, and the user edited it before the next
    pull. That pull carried Google's echo of the new event, in Google's
    own formatting, so its bytes differed from the file Omagenda wrote.
    It was judged a remote change, the local edit became a conflict copy,
    and the event went back to its original time.
    """

    LOCAL = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Omagenda//EN\r\nBEGIN:VEVENT\r\n"
             b"UID:draft@omagenda\r\nSUMMARY:Lunch\r\nSEQUENCE:0\r\n"
             b"DTSTART;TZID=America/Edmonton:20260917T130000\r\nDTEND;TZID=America/Edmonton:20260917T140000\r\n"
             b"END:VEVENT\r\nEND:VCALENDAR\r\n")
    GOOGLE_ECHO = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:new-remote-id\r\n"
                   b"SUMMARY:Lunch\r\nDTSTART;TZID=America/Edmonton:20260917T130000\r\n"
                   b"DTEND;TZID=America/Edmonton:20260917T140000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def _created(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        (path / "draft@omagenda.ics").write_bytes(self.LOCAL)
        calendar = RemoteCalendar(id="cal-1", name="Primary")
        creating = FakeBridge()
        _sync_one_calendar(creating, {"id": "acct"}, calendar, path, state_dir=root / "state")
        self.assertEqual(len(creating.push_create_calls), 1)
        self.assertTrue((path / "new-remote-id.ics").exists())
        return root, path, calendar

    def _edit(self, path):
        edited = (path / "new-remote-id.ics").read_bytes().replace(b"T140000", b"T150000")
        temporary = path / "edit.tmp"
        temporary.write_bytes(edited)
        os.replace(temporary, path / "new-remote-id.ics")
        return edited

    def test_an_edit_survives_the_server_echoing_the_new_event_back(self):
        root, path, calendar = self._created()
        edited = self._edit(path)
        echo = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="new-remote-id", ics_bytes=self.GOOGLE_ECHO,
            ref=RemoteRef(remote_id="new-remote-id", etag="etag-1"))])])
        counts = _sync_one_calendar(echo, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(counts["conflicts"], 0)
        self.assertEqual(list(path.glob("*.conflict.ics")), [])
        self.assertEqual([body for body, _ in echo.push_update_calls], [edited])
        self.assertEqual(echo.push_update_calls[0][1].etag, "etag-1")
        self.assertEqual((path / "new-remote-id.ics").read_bytes(), edited)

    def test_a_real_remote_change_still_conflicts_with_a_local_edit(self):
        root, path, calendar = self._created()
        edited = self._edit(path)
        remote = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="new-remote-id", ics_bytes=self.GOOGLE_ECHO.replace(b"SUMMARY:Lunch", b"SUMMARY:Lunch moved"),
            ref=RemoteRef(remote_id="new-remote-id", etag="etag-2"))])])
        counts = _sync_one_calendar(remote, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(counts["conflicts"], 1)
        self.assertEqual([p.read_bytes() for p in path.glob("*.conflict.ics")], [edited])
        self.assertIn(b"SUMMARY:Lunch moved", (path / "new-remote-id.ics").read_bytes())

    def test_an_unedited_echo_still_refreshes_to_the_server_copy(self):
        root, path, calendar = self._created()
        echo = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="new-remote-id", ics_bytes=self.GOOGLE_ECHO,
            ref=RemoteRef(remote_id="new-remote-id", etag="etag-1"))])])
        counts = _sync_one_calendar(echo, {"id": "acct"}, calendar, path, state_dir=root / "state")
        self.assertEqual((counts["conflicts"], counts["pulled"]), (0, 1))
        self.assertEqual(echo.push_update_calls, [])
        self.assertEqual((path / "new-remote-id.ics").read_bytes(), self.GOOGLE_ECHO)


class DeleteVersusEchoTest(unittest.TestCase):
    """Deleting an event you had only just created used to bring it back.

    The create was pushed, Google reported that same event back as
    changed on the next pull, the pull rewrote the file the user had
    since deleted, and the deletion -- no longer visible on disk -- was
    never sent anywhere. No error was raised; the event simply returned.
    Local deletions are now judged on a snapshot taken before the pull.
    """

    EVENT = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:remote-1\r\n"
             b"DTSTART:20260909T160000Z\r\nDTEND:20260909T170000Z\r\n"
             b"SUMMARY:Coffee\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def _seeded(self):
        """A calendar with one event both sides already agree on."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        calendar = RemoteCalendar(id="cal-1", name="Primary")
        seeding = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="remote-1", ics_bytes=self.EVENT,
            ref=RemoteRef(remote_id="remote-1", etag="etag-1"))])])
        _sync_one_calendar(seeding, {"id": "acct"}, calendar, path, state_dir=root / "state")
        return root, path, calendar

    def test_a_delete_survives_the_server_echoing_the_event_back(self):
        root, path, calendar = self._seeded()
        (path / "remote-1.ics").unlink()

        # The very next pull hands the same event back, exactly as Google
        # does with an event it has just been told about.
        echo = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="remote-1", ics_bytes=self.EVENT,
            ref=RemoteRef(remote_id="remote-1", etag="etag-1"))])])
        counts = _sync_one_calendar(echo, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(counts["deletedLocal"], 1)
        self.assertEqual([r.remote_id for r in echo.push_delete_calls], ["remote-1"])
        self.assertFalse((path / "remote-1.ics").exists(), "the event must not come back")

    def test_a_plain_delete_still_works(self):
        root, path, calendar = self._seeded()
        (path / "remote-1.ics").unlink()

        bridge = FakeBridge()
        counts = _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(counts["deletedLocal"], 1)
        self.assertEqual(len(bridge.push_delete_calls), 1)

    def test_an_event_deleted_on_the_server_is_not_pushed_back_as_a_delete(self):
        root, path, calendar = self._seeded()

        bridge = FakeBridge(pull_results=[PullResult(deleted_uids=["remote-1"])])
        counts = _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(counts["deletedRemote"], 1)
        self.assertEqual(bridge.push_delete_calls, [], "the server already knows")
        self.assertFalse((path / "remote-1.ics").exists())

    def test_a_new_event_from_the_server_is_not_mistaken_for_a_deletion(self):
        root, path, calendar = self._seeded()

        fresh = self.EVENT.replace(b"remote-1", b"remote-2")
        bridge = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="remote-2", ics_bytes=fresh,
            ref=RemoteRef(remote_id="remote-2", etag="etag-9"))])])
        _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")

        self.assertEqual(bridge.push_delete_calls, [])
        self.assertTrue((path / "remote-2.ics").exists())

    def test_an_untouched_calendar_pushes_nothing(self):
        root, path, calendar = self._seeded()
        bridge = FakeBridge()
        counts = _sync_one_calendar(bridge, {"id": "acct"}, calendar, path, state_dir=root / "state")
        self.assertEqual(counts["deletedLocal"], 0)
        self.assertEqual(bridge.push_delete_calls, [])
        self.assertTrue((path / "remote-1.ics").exists())


class UnchangedPullTest(unittest.TestCase):
    """A pulled event whose bytes match what is already on disk is not
    rewritten.

    Google answers 410 Gone for some subscribed calendars' sync tokens
    every single time -- its US holidays calendar does, handing back a
    token it rejects again on the next call -- so every sync is a full
    resync of a few hundred unchanged events. Rewriting them wakes the
    watcher and throws away that file's index-cache entry, buying a
    re-parse of a file that never moved.
    """

    EVENT = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:holiday-1\r\n"
             b"DTSTART;VALUE=DATE:20261225\r\nSUMMARY:Christmas\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def _pull(self, path, root, ics=None):
        bridge = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="holiday-1", ics_bytes=ics or self.EVENT,
            ref=RemoteRef(remote_id="holiday-1", etag="etag-1"))])])
        return _sync_one_calendar(bridge, {"id": "acct"},
                                  RemoteCalendar(id="cal-1", name="Holidays"),
                                  path, state_dir=root / "state")

    def _fresh(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / "acct" / "cal-1"
        path.mkdir(parents=True)
        return root, path

    def test_the_first_pull_writes(self):
        root, path = self._fresh()
        counts = self._pull(path, root)
        self.assertEqual(counts["pulled"], 1)
        self.assertTrue((path / "holiday-1.ics").exists())

    def test_an_identical_second_pull_does_not_rewrite(self):
        root, path = self._fresh()
        self._pull(path, root)
        before = (path / "holiday-1.ics").stat().st_mtime_ns

        counts = self._pull(path, root)

        self.assertEqual(counts["pulled"], 0)
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual((path / "holiday-1.ics").stat().st_mtime_ns, before,
                         "the file must not be touched at all")

    def test_a_genuinely_changed_event_is_still_written(self):
        root, path = self._fresh()
        self._pull(path, root)
        changed = self.EVENT.replace(b"Christmas", b"Christmas Day")

        counts = self._pull(path, root, ics=changed)

        self.assertEqual(counts["pulled"], 1)
        self.assertIn(b"Christmas Day", (path / "holiday-1.ics").read_bytes())

    def test_the_skip_checks_the_file_and_not_only_the_hash(self):
        # The hash alone would say "already have it" for a file that is no
        # longer there, so the check tests both. Here the pull does write
        # it -- and then the deletion the user made wins, per
        # DeleteVersusEchoTest, which is why this asserts the push rather
        # than a file on disk. The two rules meet exactly here.
        root, path = self._fresh()
        self._pull(path, root)
        (path / "holiday-1.ics").unlink()

        bridge = FakeBridge(pull_results=[PullResult(changed=[PullChange(
            uid="holiday-1", ics_bytes=self.EVENT,
            ref=RemoteRef(remote_id="holiday-1", etag="etag-1"))])])
        counts = _sync_one_calendar(bridge, {"id": "acct"},
                                    RemoteCalendar(id="cal-1", name="Holidays"),
                                    path, state_dir=root / "state")

        self.assertEqual(counts["pulled"], 1, "the hash matched but the file was gone")
        self.assertEqual(counts["deletedLocal"], 1)
        self.assertEqual([r.remote_id for r in bridge.push_delete_calls], ["holiday-1"])
        self.assertFalse((path / "holiday-1.ics").exists())

"""Sync orchestration tests.

Every test here sets OMAGENDA_VDIR explicitly and restores it afterward --
sync_all() writes files, and a test that forgets this override writes into
the real ~/.local/share/calendars instead of a temp directory. (This
happened once during development: two ad-hoc debug commands in a row
forgot the override and left a stray "holidays" calendar, chmod'd
read-only by _sync_ics itself, sitting in the real vdir path. Cleaned up
by hand; this test file exists so it can't happen silently again.)
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

from omagenda.sync import sync_all

FIXTURE_ICS = Path(__file__).parent / "fixtures" / "vdir" / "family" / "holiday.ics"


class WithVdir:
    """Context manager: point OMAGENDA_VDIR *and* OMAGENDA_STATE at fresh
    temp dirs for the duration of the block, always restoring both.

    The state override was added after this guard failed to prevent the
    very thing it exists for. sync_all() records when it last ran, and
    that record defaults to the real ~/.local/state/omagenda -- so a test
    syncing a fixture account named "broken" wrote {"ok": false,
    "problems": ["broken"]} into the maintainer's live state, and the
    running panel duly reported that syncing was failing. Redirecting the
    vdir alone was never enough: anything sync_all writes has to land in
    the temp dir, not just the calendars.
    """

    _VARS = ("OMAGENDA_VDIR", "OMAGENDA_STATE")

    def __enter__(self):
        self._old = {v: os.environ.get(v) for v in self._VARS}
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        os.environ["OMAGENDA_VDIR"] = str(root / "calendars")
        os.environ["OMAGENDA_STATE"] = str(root / "state")
        (root / "calendars").mkdir()
        return root / "calendars"

    def __exit__(self, *exc):
        for var, previous in self._old.items():
            if previous is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = previous
        self._tmp.cleanup()


class SyncIcsTest(unittest.TestCase):
    def test_fetches_ics_subscription_into_readonly_calendar(self):
        with WithVdir() as vdir_root:
            config = {"accounts": [
                {"id": "holidays", "type": "ics", "url": f"file://{FIXTURE_ICS.resolve()}", "color": "yellow"},
            ]}
            results = sync_all(config)
            self.assertTrue(results["holidays"]["ok"], results["holidays"])

            calendar_dir = vdir_root / "holidays"
            self.assertTrue((calendar_dir / "subscription.ics").exists())
            self.assertEqual((calendar_dir / "displayname").read_text(), "holidays")
            self.assertFalse(os.access(calendar_dir, os.W_OK), "subscription calendar must be read-only")

            # discover_calendars must see it and mark it read-only.
            from omagenda.vdir import discover_calendars

            cals = {c["id"]: c for c in discover_calendars(vdir_root)}
            self.assertIn("holidays", cals)
            self.assertTrue(cals["holidays"]["readOnly"])
            self.assertEqual(cals["holidays"]["color"], "yellow")

    def test_missing_url_reports_without_raising(self):
        with WithVdir():
            results = sync_all({"accounts": [{"id": "broken", "type": "ics"}]})
            self.assertFalse(results["broken"]["ok"])

    def test_unreachable_url_reports_without_raising(self):
        with WithVdir():
            results = sync_all({"accounts": [
                {"id": "broken", "type": "ics", "url": "file:///no/such/file.ics"},
            ]})
            self.assertFalse(results["broken"]["ok"])


class SyncCaldavAndUnknownTest(unittest.TestCase):
    def test_missing_sync_tool_reports_without_raising(self):
        with WithVdir():
            results = sync_all({"accounts": [
                {"id": "family-icloud", "type": "icloud", "sync": "a-tool-that-does-not-exist"},
            ]})
            self.assertFalse(results["family-icloud"]["ok"])
            self.assertIn("not found on PATH", results["family-icloud"]["detail"])

    def test_unimplemented_bridge_reports_without_raising(self):
        with WithVdir():
            results = sync_all({"accounts": [{"id": "g", "type": "google"}]})
            self.assertFalse(results["g"]["ok"])

    def test_unknown_account_type_reports_without_raising(self):
        with WithVdir():
            results = sync_all({"accounts": [{"id": "x", "type": "bogus"}]})
            self.assertFalse(results["x"]["ok"])

    def test_no_accounts_is_a_no_op(self):
        with WithVdir():
            self.assertEqual({k: v for k, v in sync_all({}).items() if k != "omacal"}, {})


class IcsResyncTest(unittest.TestCase):
    """A subscription folder is left read-only on purpose, so refreshing it
    has to reopen the write bit -- otherwise one missing file wedges the
    subscription permanently."""

    def _config(self):
        return {"accounts": [
            {"id": "gcal", "type": "ics", "url": f"file://{FIXTURE_ICS.resolve()}", "color": "blue"},
        ]}

    def test_repeated_sync_succeeds(self):
        with WithVdir():
            self.assertTrue(sync_all(self._config())["gcal"]["ok"])
            self.assertTrue(sync_all(self._config())["gcal"]["ok"])

    def test_sync_recovers_when_the_fetched_file_was_deleted(self):
        with WithVdir() as vdir_root:
            sync_all(self._config())
            folder = vdir_root / "gcal"
            folder.chmod(0o755)
            (folder / "subscription.ics").unlink()
            folder.chmod(0o555)

            self.assertTrue(sync_all(self._config())["gcal"]["ok"])
            self.assertTrue((folder / "subscription.ics").exists())
            self.assertFalse(os.access(folder, os.W_OK))  # still marked read-only

    def test_one_broken_account_does_not_sink_the_others(self):
        with WithVdir():
            config = {"accounts": [
                {"id": "broken"},  # no type at all -- would raise on ["type"]
                {"id": "gcal", "type": "ics", "url": f"file://{FIXTURE_ICS.resolve()}"},
            ]}
            results = sync_all(config)
            self.assertFalse(results["broken"]["ok"])
            self.assertTrue(results["gcal"]["ok"])


if __name__ == "__main__":
    unittest.main()


class GuardTest(unittest.TestCase):
    """The guard itself. It failed once by covering only half of what
    sync_all writes, and the failure was invisible until the maintainer's
    own panel started reporting a sync failure for an account named
    "broken" that existed only in this file."""

    def test_the_state_dir_is_redirected_too(self):
        real = os.environ.get("OMAGENDA_STATE")
        with WithVdir():
            self.assertNotEqual(os.environ["OMAGENDA_STATE"], real)
            from omagenda.index import resolve_state_dir

            self.assertTrue(str(resolve_state_dir()).startswith(tempfile.gettempdir()))

    def test_a_sync_records_inside_the_temp_state_dir(self):
        from omagenda.index import resolve_state_dir
        from omagenda.sync import read_last_sync, record_path

        with WithVdir():
            sync_all({"accounts": [{"id": "broken", "type": "ics"}]})
            self.assertTrue(record_path().exists())
            self.assertEqual(read_last_sync()["problems"], ["broken"])
            temp_state = resolve_state_dir()

        self.assertFalse(temp_state.exists(), "the temp state dir must be cleaned up")

    def test_both_variables_are_restored(self):
        before = (os.environ.get("OMAGENDA_VDIR"), os.environ.get("OMAGENDA_STATE"))
        with WithVdir():
            pass
        self.assertEqual((os.environ.get("OMAGENDA_VDIR"), os.environ.get("OMAGENDA_STATE")), before)


class SyncLockTest(unittest.TestCase):
    """Two syncs must not run over each other.

    `omagenda watch` syncs on its own now, so a hand-run `omagenda sync`
    is a second writer into the same folders. The two collided in
    practice: one chmodded a read-only calendar back to 0555 while the
    other was still writing into it, and that calendar failed with a
    permission error on its own temp file.
    """

    def test_a_second_sync_waits_rather_than_racing(self):
        import threading

        from omagenda.sync import _sync_lock

        with WithVdir():
            order = []
            released = threading.Event()

            def holder():
                with _sync_lock():
                    order.append("first-in")
                    released.wait(2)
                    order.append("first-out")

            thread = threading.Thread(target=holder)
            thread.start()
            while "first-in" not in order:
                time.sleep(0.01)
            released.set()
            with _sync_lock(timeout=5):
                order.append("second-in")
            thread.join()

        self.assertEqual(order, ["first-in", "first-out", "second-in"],
                         "the second sync must not start until the first finishes")

    def test_waiting_gives_up_eventually(self):
        import threading

        from omagenda.sync import _sync_lock

        with WithVdir():
            holding = threading.Event()
            release = threading.Event()

            def holder():
                with _sync_lock():
                    holding.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            holding.wait(2)
            try:
                with self.assertRaises(TimeoutError):
                    with _sync_lock(timeout=0.3):
                        pass
            finally:
                release.set()
                thread.join()

    def test_a_normal_sync_takes_and_releases_the_lock(self):
        from omagenda.sync import _sync_lock

        with WithVdir():
            sync_all({"accounts": []})
            # If the lock leaked, this would block until the timeout.
            with _sync_lock(timeout=1):
                pass

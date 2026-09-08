"""When the watcher decides to sync.

`omagenda watch` reindexed on every vdir change and never once synced, so
an event created in Quick Add appeared in the panel immediately and never
left the machine. PLAN.md had always said sync runs "by `omagenda sync`
and by `omagenda watch` on a timer"; only the reindex half was built.
"""
import importlib.machinery
import importlib.util
import os
import unittest
import unittest.mock
from pathlib import Path

_spec = importlib.util.spec_from_loader(
    "omagenda_cli",
    importlib.machinery.SourceFileLoader(
        "omagenda_cli", str(Path(__file__).resolve().parent.parent / "bin" / "omagenda")))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class SyncDueTest(unittest.TestCase):
    INTERVAL = 300
    SETTLE = 10

    def due(self, now, last_sync, pending):
        return cli._sync_due(now, last_sync, pending, self.INTERVAL, self.SETTLE)

    def test_a_quiet_watcher_syncs_on_the_interval(self):
        self.assertFalse(self.due(now=299, last_sync=0, pending=False))
        self.assertTrue(self.due(now=300, last_sync=0, pending=False))

    def test_a_local_change_syncs_without_waiting_for_the_interval(self):
        self.assertTrue(self.due(now=11, last_sync=0, pending=True))

    def test_a_local_change_still_waits_out_the_settle_window(self):
        # The sync that just ran wrote into the vdir being watched, so
        # this "change" is very likely its own.
        self.assertFalse(self.due(now=3, last_sync=0, pending=True))

    def test_the_first_pass_syncs_immediately(self):
        # last_sync starts at 0 and monotonic time is well past it, so a
        # freshly started watcher pulls at once rather than after five
        # minutes of showing stale data.
        self.assertTrue(self.due(now=10_000, last_sync=0, pending=False))

    def test_no_reason_means_no_sync(self):
        self.assertFalse(self.due(now=5, last_sync=0, pending=False))


class SyncConfigurationTest(unittest.TestCase):
    def test_the_default_interval_is_five_minutes(self):
        self.assertEqual(cli.DEFAULT_SYNC_INTERVAL, 300)

    def test_the_settle_window_is_shorter_than_the_interval(self):
        # Otherwise a local change would never get its early push.
        self.assertLess(cli.SYNC_SETTLE, cli.DEFAULT_SYNC_INTERVAL)


class SyncOnceTest(unittest.TestCase):
    """The watcher outlives any single sync failure, but says so."""

    def test_a_raising_sync_does_not_escape(self):
        with unittest.mock.patch("omagenda.sync.sync_all", side_effect=OSError("network down")):
            cli._sync_once()  # must not raise

    def test_a_failing_account_is_named_on_stderr(self):
        import io
        import contextlib

        stderr = io.StringIO()
        with unittest.mock.patch("omagenda.sync.sync_all",
                                 return_value={"google": {"ok": False, "detail": "token expired"}}), \
                contextlib.redirect_stderr(stderr):
            cli._sync_once()
        self.assertIn("google", stderr.getvalue())
        self.assertIn("token expired", stderr.getvalue())

    def test_a_clean_sync_says_nothing(self):
        import io
        import contextlib

        stderr = io.StringIO()
        with unittest.mock.patch("omagenda.sync.sync_all", return_value={"google": {"ok": True}}), \
                contextlib.redirect_stderr(stderr):
            cli._sync_once()
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()


class SourceFingerprintTest(unittest.TestCase):
    """The watcher stands down when its own code changes.

    Quickshell adopts long-running Process objects across a config
    reload, on purpose, so that reloading a shell does not kill the
    commands it is running. For a plugin that means `omarchy restart
    shell` leaves the OLD watcher running the OLD code indefinitely, with
    nothing to indicate it. This cost three false negatives in one
    afternoon: a sync fix was verified as "not working" three times
    against a watcher that had never loaded it.
    """

    def test_the_script_and_the_package_are_both_covered(self):
        paths = cli._source_paths()
        names = {p.name for p in paths}
        self.assertIn("omagenda", names | {p.name for p in paths})
        self.assertIn("sync.py", names)
        self.assertIn("index.py", names)
        self.assertTrue(any(p.name == "omagenda" for p in paths),
                        "the CLI script itself must be watched too")

    def test_the_fingerprint_is_stable_when_nothing_changes(self):
        self.assertEqual(cli._source_fingerprint(), cli._source_fingerprint())

    def test_a_touched_source_file_changes_the_fingerprint(self):
        before = cli._source_fingerprint()
        target = next(p for p in cli._source_paths() if p.name == "sync.py")
        original = target.stat()
        try:
            os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
            self.assertNotEqual(cli._source_fingerprint(), before)
        finally:
            os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(cli._source_fingerprint(), before)

    def test_a_missing_file_counts_as_changed(self):
        # A plugin update caught mid-write: better to restart than to run
        # on half a tree.
        before = cli._source_fingerprint()
        with unittest.mock.patch.object(
                cli, "_source_paths",
                return_value=cli._source_paths() + [Path("/nonexistent/module.py")]):
            self.assertNotEqual(cli._source_fingerprint(), before)

    def test_the_fingerprint_records_size_as_well_as_time(self):
        # An edit that lands inside the same mtime granularity still has
        # to be caught.
        entry = cli._source_fingerprint()[0]
        self.assertEqual(len(entry), 3)
        self.assertIsInstance(entry[2], int)

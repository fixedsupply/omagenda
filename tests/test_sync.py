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
import unittest
from pathlib import Path

from omagenda.sync import sync_all

FIXTURE_ICS = Path(__file__).parent / "fixtures" / "vdir" / "family" / "holiday.ics"


class WithVdir:
    """Context manager: point OMAGENDA_VDIR at a fresh temp dir for the
    duration of the block, and always restore the previous value."""

    def __enter__(self):
        self._old = os.environ.get("OMAGENDA_VDIR")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["OMAGENDA_VDIR"] = self._tmp.name
        return Path(self._tmp.name)

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("OMAGENDA_VDIR", None)
        else:
            os.environ["OMAGENDA_VDIR"] = self._old
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

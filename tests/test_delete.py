"""Deletion checks use disposable calendars and recorded Google responses."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from omagenda.delete import delete_event
from tests.test_sync_bridge_orchestration import _ics

CLI = Path(__file__).resolve().parents[1] / "bin" / "omagenda"


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "vdir"
        self.folder = self.root / "personal"
        self.folder.mkdir(parents=True)
        (self.folder / "displayname").write_text("Personal")
        self.state = self.base / "state"
        env = patch.dict(os.environ, OMAGENDA_VDIR=str(self.root),
                         OMAGENDA_STATE=str(self.state), OMAGENDA_CONFIG=str(self.base / "config.toml"))
        env.start()
        self.addCleanup(env.stop)
        self.file = self.folder / "demo.ics"
        self.content = _ics("demo", "Disposable event").replace(b"20260908", date.today().strftime("%Y%m%d").encode())
        self.file.write_bytes(self.content)

    def cli(self, path=None, *args):
        return subprocess.run([sys.executable, str(CLI), "delete", str(path or self.file), *args],
                              capture_output=True, text=True)

    def test_cli_copy_permissions_json_and_immediate_index(self):
        from omagenda.index import index
        index()
        self.assertEqual(len(json.loads((self.state / "agenda.json").read_text())["events"]), 1)
        result = self.cli(None, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data), {"deleted", "title", "calendar", "copy"})
        self.assertTrue(data["deleted"])
        self.assertEqual(data["title"], "Disposable event")
        self.assertEqual(data["calendar"], "personal")
        saved = Path(data["copy"])
        self.assertEqual(saved.read_bytes(), self.content)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
        self.assertRegex(saved.name, r"^demo\.\d{8}T\d{12}Z\.ics$")
        self.assertFalse(self.file.exists())
        self.assertEqual(json.loads((self.state / "agenda.json").read_text())["events"], [])

    def test_text_output(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("Deleted 'Disposable event' from Personal. A copy is at "))

    def test_rejects_unsafe_paths_and_non_events(self):
        outside = self.base / "outside.ics"
        outside.write_bytes(self.content)
        link = self.folder / "link.ics"
        link.symlink_to(outside)
        internal_link = self.folder / "internal.ics"
        internal_link.symlink_to(self.file)
        conflict = self.folder / "demo.conflict.ics"
        conflict.write_bytes(self.content)
        wrong = self.folder / "demo.txt"
        wrong.write_bytes(self.content)
        direct = self.root / "direct.ics"
        direct.write_bytes(self.content)
        symlink_folder = self.root / "alias"
        symlink_folder.symlink_to(self.folder, target_is_directory=True)
        for path in (outside, link, internal_link, conflict, wrong, direct, self.folder,
                     self.folder / ".." / "personal" / "demo.ics", symlink_folder / "demo.ics",
                     self.folder / "missing.ics"):
            with self.subTest(path=path):
                result = self.cli(path, "--json")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(self.file.exists())
        self.assertEqual(outside.read_bytes(), self.content)

    def test_refuses_read_only(self):
        from omagenda.vdir import discover_calendars
        calendars = discover_calendars()
        calendars[0]["readOnly"] = True
        with patch("omagenda.vdir.discover_calendars", return_value=calendars):
            with self.assertRaisesRegex(ValueError, "'Personal' is read-only, so its events can't be deleted here"):
                delete_event(str(self.file))
        self.assertTrue(self.file.exists())

    def test_refuses_each_recurrence_property(self):
        for prop in (b"RRULE:FREQ=DAILY", b"RDATE:20260910T190000Z", b"RECURRENCE-ID:20260908T190000Z"):
            with self.subTest(prop=prop):
                self.file.write_bytes(self.content.replace(b"END:VEVENT", prop + b"\r\nEND:VEVENT"))
                result = self.cli(None, "--json")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Recurring events can't be deleted from Omagenda yet; delete it in Personal's own app", result.stderr)
                self.assertTrue(self.file.exists())

    def test_rdate_is_recurring_in_agenda_even_with_an_old_cache(self):
        from omagenda.index import build_agenda
        self.file.write_bytes(self.content.replace(b"END:VEVENT", b"RDATE:20260920T190000Z\r\nEND:VEVENT"))
        stat = self.file.stat()
        old_key = f"{self.file}|{stat.st_mtime_ns}|{stat.st_size}|{date.today().isoformat()}|14"
        self.state.mkdir()
        (self.state / "index-cache.json").write_text(json.dumps({old_key: [{"recurring": False}]}))
        events = build_agenda()["events"]
        self.assertTrue(events)
        self.assertTrue(all(event["recurring"] for event in events))

    def test_refuses_multiple_empty_and_malformed(self):
        event = self.content.split(b"BEGIN:VEVENT")[1].split(b"END:VEVENT")[0]
        for content in (self.content.replace(b"END:VCALENDAR", b"BEGIN:VEVENT" + event + b"END:VEVENT\r\nEND:VCALENDAR"),
                        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n", b"invalid"):
            self.file.write_bytes(content)
            result = self.cli(None, "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertTrue(self.file.exists())

    def test_copy_failure_keeps_original(self):
        with patch("omagenda.delete.os.replace", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                delete_event(str(self.file))
        self.assertEqual(self.file.read_bytes(), self.content)
        self.assertEqual(list((self.state / "deleted" / "personal").iterdir()), [])

    def test_unlink_failure_keeps_copy(self):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == self.file:
                raise OSError("unlink failed")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink):
            with self.assertRaisesRegex(OSError, "unlink failed"):
                delete_event(str(self.file))
        self.assertEqual(self.file.read_bytes(), self.content)
        self.assertEqual(next((self.state / "deleted" / "personal").glob("*.ics")).read_bytes(), self.content)

    def test_refuses_copy_inside_vdir(self):
        with patch.dict(os.environ, OMAGENDA_STATE=str(self.root / "state")):
            with self.assertRaisesRegex(ValueError, "outside the vdir"):
                delete_event(str(self.file))
        self.assertTrue(self.file.exists())

    def test_google_sync_deletes_cli_removed_file_remotely_once(self):
        from omagenda.bridges import RemoteCalendar
        from omagenda.bridges import google
        from omagenda.sync import _sync_one_calendar
        from tests.test_bridge_google import STANDALONE_EVENT, _FakeResponse

        self.file.unlink()
        account = {"id": "google-demo", "type": "google"}
        calendar = RemoteCalendar(id="primary", name="Demo", writable=True)
        with patch.object(google, "_get_access_token", return_value="fake-token"), \
             patch("urllib.request.urlopen", return_value=_FakeResponse({"items": [dict(STANDALONE_EVENT, etag="recorded-etag")], "nextSyncToken": "token1"})):
            _sync_one_calendar(google, account, calendar, self.folder, self.state)
        event_file = next(self.folder.glob("*.ics"))
        result = self.cli(event_file, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        requests = []
        def respond(request, **kwargs):
            requests.append(request)
            if request.method == "DELETE":
                return _FakeResponse(None, 204)
            # A provider echo must not resurrect the file deleted by the CLI.
            items = [dict(STANDALONE_EVENT, etag="recorded-etag")] if len(requests) == 1 else []
            return _FakeResponse({"items": items, "nextSyncToken": "token2"})
        with patch.object(google, "_get_access_token", return_value="fake-token"), \
             patch("urllib.request.urlopen", side_effect=respond):
            counts = _sync_one_calendar(google, account, calendar, self.folder, self.state)
            again = _sync_one_calendar(google, account, calendar, self.folder, self.state)
        self.assertTrue(counts["ok"], counts)
        self.assertEqual(counts["deletedLocal"], 1)
        self.assertEqual(again["deletedLocal"], 0)
        deletes = [r for r in requests if r.method == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0].get_header("If-match"), "recorded-etag")
        self.assertTrue(deletes[0].full_url.endswith("/events/abc123"))
        self.assertTrue(Path(json.loads(result.stdout)["copy"]).exists())
        self.assertFalse(event_file.exists())

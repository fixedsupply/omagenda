"""pimsync conflicts end with the server version on both sides and the local one saved.

The integration test drives the real pimsync binary against two local vdir
storages, so it needs no network and no account, and it reproduces the
pimsync 0.5.7 behaviour that made `conflict_resolution keep b` unusable.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omagenda import accounts, sync


def event(summary: str, uid: str = "conflict-1@omagenda") -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Omagenda test//EN\r\n"
            f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260915T000000Z\r\n"
            "DTSTART:20260916T150000Z\r\nDTEND:20260916T153000Z\r\n"
            f"SUMMARY:{summary}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def replace(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


class ConflictDirectiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        patcher = mock.patch.object(accounts, "PIMSYNC_CONFIG_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_directive_names_the_plugin_resolver_for_the_account(self):
        directive = accounts.conflict_resolution_directive("family")
        self.assertTrue(directive.startswith("conflict_resolution cmd "))
        self.assertIn(f'"{accounts.CONFLICT_RESOLVER}"', directive)
        self.assertTrue(directive.endswith('resolve-conflict --account "family"'))
        self.assertTrue(accounts.CONFLICT_RESOLVER.name == "omagenda")

    def test_existing_keep_b_config_is_migrated_once_and_otherwise_untouched(self):
        path = accounts.pimsync_config_path("family")
        original = ('status_path "/x/"\n\npair family {\n\tstorage_a family_local\n'
                    '\tcollections from b\n\tconflict_resolution keep b\n}\n'
                    'storage family_remote {\n\tpassword {\n\t\tcmd secret-tool lookup x\n\t}\n}\n')
        path.write_text(original)
        path.chmod(0o600)
        self.assertTrue(accounts.ensure_conflict_resolver("family"))
        migrated = path.read_text()
        self.assertNotIn("keep b", migrated)
        self.assertIn("\t" + accounts.conflict_resolution_directive("family") + "\n", migrated)
        self.assertEqual(migrated.replace("\t" + accounts.conflict_resolution_directive("family"),
                                          "\tconflict_resolution keep b"), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(accounts.ensure_conflict_resolver("family"))
        self.assertFalse(accounts.ensure_conflict_resolver("absent"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["omagenda-family.scfg"])


class PreserveConflictTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "state"

    def pair(self, local_summary, remote_summary, uid="conflict-1@omagenda"):
        local, remote = self.base / "a.tmp", self.base / "b.tmp"
        local.write_bytes(event(local_summary, uid))
        remote.write_bytes(event(remote_summary, uid))
        return local, remote

    def test_server_wins_and_local_version_is_saved_outside_the_vdir(self):
        local, remote = self.pair("Mine", "Theirs")
        with mock.patch.object(sync, "_notify_conflict") as notify:
            saved = sync.preserve_pimsync_conflict("family", local, remote, state_dir=self.state)
        self.assertEqual(saved, self.state / "conflicts" / "family" / "conflict-1@omagenda.conflict.ics")
        self.assertEqual(saved.read_bytes(), event("Mine"))
        self.assertEqual(local.read_bytes(), remote.read_bytes())
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
        notify.assert_called_once_with("conflict-1@omagenda", "family", saved_as=str(saved))

    def test_a_second_different_conflict_does_not_replace_the_first(self):
        with mock.patch.object(sync, "_notify_conflict"):
            first = sync.preserve_pimsync_conflict("family", *self.pair("Mine 1", "Theirs"), state_dir=self.state)
            second = sync.preserve_pimsync_conflict("family", *self.pair("Mine 2", "Theirs"), state_dir=self.state)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), event("Mine 1"))
        self.assertEqual(second.read_bytes(), event("Mine 2"))

    def test_unsafe_uid_and_notification_failure_are_contained(self):
        local, remote = self.pair("Mine", "Theirs", uid="../../evil/uid")
        with mock.patch.object(sync, "_notify_conflict", side_effect=OSError):
            saved = sync.preserve_pimsync_conflict("fam/ily", local, remote, state_dir=self.state)
        self.assertEqual(saved.parent, self.state / "conflicts" / "fam_ily")
        self.assertNotIn("/", saved.name.replace(".conflict.ics", ""))
        self.assertEqual(local.read_bytes(), remote.read_bytes())


@unittest.skipUnless(shutil.which("pimsync"), "pimsync is not installed")
class RealPimsyncConflictTest(unittest.TestCase):
    """End to end through the real pimsync binary and the real CLI resolver."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.a, self.b = base / "a" / "cal", base / "b" / "cal"
        self.a.mkdir(parents=True)
        self.b.mkdir(parents=True)
        self.state = base / "state"
        # pimsync runs the resolver as a separate process, beyond any mock, so
        # a fake notifier on PATH keeps a test run off the real desktop.
        fake_bin = base / "bin"
        fake_bin.mkdir()
        notifier = fake_bin / "omarchy-notification-send"
        notifier.write_text("#!/bin/sh\nexit 0\n")
        notifier.chmod(0o700)
        patches = [mock.patch.object(accounts, "PIMSYNC_CONFIG_DIR", base / "pimsync"),
                   mock.patch.dict(os.environ, {"OMAGENDA_STATE": str(self.state),
                                                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"})]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        (base / "pimsync").mkdir()
        # Written with the old policy on purpose: the sync must migrate it.
        accounts.pimsync_config_path("conflicttest").write_text(
            f'status_path "{base}/status/"\n'
            "pair conflicttest {\n\tstorage_a local\n\tstorage_b remote\n"
            "\tcollections from b\n\tconflict_resolution keep b\n}\n"
            f'storage local {{\n\ttype vdir/icalendar\n\tpath "{base}/a/"\n\tfileext ics\n}}\n'
            f'storage remote {{\n\ttype vdir/icalendar\n\tpath "{base}/b/"\n\tfileext ics\n}}\n')
        self.account = {"id": "conflicttest", "type": "icloud", "sync": "pimsync"}

    def test_both_sides_edited_resolves_to_server_version_and_saves_local(self):
        (self.b / "e.ics").write_bytes(event("Original"))
        first = sync._sync_caldav(self.account)
        self.assertTrue(first["ok"], first)
        self.assertEqual((self.a / "e.ics").read_bytes(), event("Original"))

        (self.b / "displayname").write_text("Remote name")
        self.assertTrue(sync._sync_caldav(self.account)["ok"])

        replace(self.a / "e.ics", event("Local conflict copy"))
        replace(self.b / "e.ics", event("Remote conflict winner"))
        # A calendar renamed on both sides too: resolve-conflicts prompts for
        # properties and, unanswered, repeats that prompt forever.
        (self.a / "displayname").write_text("Local rename")
        (self.b / "displayname").write_text("Remote rename")
        result = sync._sync_caldav(self.account)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result.get("conflicts"), 1)
        self.assertEqual(result.get("propertyConflicts"), 1)
        self.assertEqual((self.a / "displayname").read_text(), "Remote rename")
        self.assertEqual((self.a / "e.ics").read_bytes(), event("Remote conflict winner"))
        self.assertEqual((self.b / "e.ics").read_bytes(), event("Remote conflict winner"))
        saved = list((self.state / "conflicts" / "conflicttest").glob("*.conflict.ics"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), event("Local conflict copy"))
        self.assertEqual(sorted(p.name for p in self.a.glob("*.ics")), ["e.ics"])
        self.assertEqual(sorted(p.name for p in self.b.glob("*.ics")), ["e.ics"])
        self.assertNotIn("keep b", accounts.pimsync_config_path("conflicttest").read_text())

        again = sync._sync_caldav(self.account)
        self.assertTrue(again["ok"], again)
        self.assertNotIn("conflicts", again)

    def test_property_conflict_alone_is_resolved_to_the_server_value(self):
        (self.b / "e.ics").write_bytes(event("Original"))
        (self.b / "displayname").write_text("Remote name")
        self.assertTrue(sync._sync_caldav(self.account)["ok"])
        (self.a / "displayname").write_text("Local rename")
        (self.b / "displayname").write_text("Remote rename")
        result = sync._sync_caldav(self.account)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result.get("conflicts"), result.get("propertyConflicts")), (0, 1))
        self.assertEqual((self.a / "displayname").read_text(), "Remote rename")
        self.assertFalse((self.state / "conflicts").exists())
        self.assertNotIn("propertyConflicts", sync._sync_caldav(self.account))


class ConflictParsingTest(unittest.TestCase):
    def test_counts_items_and_properties_separately(self):
        stdout = ("Plan:\n-> Item x1: conflict\n-> Item x2: conflict\n"
                  '-> Property display name: conflict (a: "A", b: "B")\n3 conflicts detected\n')
        self.assertEqual(sync.pimsync_conflicts(stdout), (2, 1))
        self.assertEqual(sync.pimsync_conflicts("0 conflicts detected\n"), (0, 0))
        self.assertEqual(sync.pimsync_conflicts(None), (0, 0))

    def test_answers_cover_every_prompt_in_any_order(self):
        answers = sync.pimsync_resolve_answers(2, 1).split()
        self.assertGreaterEqual(answers.count("y"), 2 * 2)
        self.assertGreaterEqual(answers.count("b"), 2 * 1)
        self.assertEqual(set(answers), {"y", "b"})

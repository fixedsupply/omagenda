"""Account management tests: config.toml round-trip, keyring fallback,
and pimsync config generation. See ARCHITECTURE.md §5 and §11."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omagenda.accounts import (
    add_account,
    generate_pimsync_config,
    get_secret,
    list_accounts,
    remove_account,
    store_secret,
    write_config,
)


class ConfigRoundTripTest(unittest.TestCase):
    def test_write_then_read_preserves_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = {
                "vdir": "~/.local/share/calendars",
                "default_calendar": "personal",
                "accounts": [
                    {"id": "family-icloud", "type": "icloud", "username": "calvin@icloud.com", "sync": "pimsync"},
                    {"id": "holidays", "type": "ics", "url": "https://example.com/h.ics", "color": "yellow"},
                ],
                "sets": {"work": ["work"], "home": ["personal", "family-icloud/family"]},
                "alarms": {"default_lead": "PT10M"},
            }
            write_config(config, path)
            # read_config() always reads CONFIG_PATH; read this file back directly instead.
            import tomllib

            with path.open("rb") as f:
                reloaded = tomllib.load(f)
            self.assertEqual(reloaded, config)

    def test_special_characters_are_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = {"accounts": [{"id": "x", "type": "ics", "url": 'https://example.com/a"b\\c.ics'}]}
            write_config(config, path)
            import tomllib

            with path.open("rb") as f:
                reloaded = tomllib.load(f)
            self.assertEqual(reloaded, config)


class AddRemoveAccountTest(unittest.TestCase):
    def test_add_writes_and_reads_back_via_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            with mock.patch("omagenda.doctor.CONFIG_PATH", path):
                add_account({"id": "g", "type": "google", "email": "calvin@example.com"}, path)
                accounts = list_accounts()
                self.assertEqual([a["id"] for a in accounts], ["g"])

                with self.assertRaises(ValueError):
                    add_account({"id": "g", "type": "google"}, path)

                self.assertTrue(remove_account("g", path))
                self.assertEqual(list_accounts(), [])
                self.assertFalse(remove_account("g", path))  # already gone

    def test_add_requires_id_and_type(self):
        with self.assertRaises(ValueError):
            add_account({"type": "google"})
        with self.assertRaises(ValueError):
            add_account({"id": "x"})


class SecretFallbackTest(unittest.TestCase):
    """Forces the no-keyring path (secret-tool "not found") so these tests
    never touch the real keyring or leave real secrets behind."""

    def test_file_fallback_round_trips_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets_dir = Path(tmp) / "secrets"
            with mock.patch("omagenda.accounts.SECRETS_DIR", secrets_dir), \
                 mock.patch("shutil.which", return_value=None):
                used_keyring = store_secret("test-account", "hunter2")
                self.assertFalse(used_keyring)
                self.assertEqual(get_secret("test-account"), "hunter2")
                mode = (secrets_dir / "test-account").stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

    def test_missing_secret_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets_dir = Path(tmp) / "secrets"
            with mock.patch("omagenda.accounts.SECRETS_DIR", secrets_dir), \
                 mock.patch("shutil.which", return_value=None):
                self.assertIsNone(get_secret("never-stored"))


class PimsyncConfigTest(unittest.TestCase):
    def test_generated_scfg_has_the_documented_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            vdir_root = Path(tmp) / "calendars"
            config_dir = Path(tmp) / "pimsync"
            status_dir = Path(tmp) / "pimsync-status"
            with mock.patch("omagenda.accounts.PIMSYNC_CONFIG_DIR", config_dir), \
                 mock.patch("omagenda.accounts.PIMSYNC_STATUS_DIR", status_dir):
                account = {"id": "family-icloud", "type": "icloud", "username": "calvin@icloud.com"}
                path = generate_pimsync_config(account, vdir_root=vdir_root)

                self.assertTrue(path.exists())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                text = path.read_text()

                # Verbatim directive names from pimsync.conf(5) -- not
                # invented ones. See the module docstring.
                self.assertIn("pair family_icloud {", text)
                self.assertIn("storage_a family_icloud_local", text)
                self.assertIn("storage_b family_icloud_remote", text)
                self.assertIn("collections from b", text)
                self.assertIn("conflict_resolution keep b", text)
                self.assertIn("type vdir/icalendar", text)
                self.assertIn(f"path {vdir_root / 'family-icloud'}/", text)
                self.assertIn("type caldav", text)
                self.assertIn("url https://caldav.icloud.com/", text)
                self.assertIn("username calvin@icloud.com", text)
                self.assertIn("password {", text)
                self.assertIn("cmd secret-tool lookup service omagenda account family-icloud", text)

                self.assertTrue((vdir_root / "family-icloud").is_dir())

    def test_caldav_uses_the_given_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            vdir_root = Path(tmp) / "calendars"
            with mock.patch("omagenda.accounts.PIMSYNC_CONFIG_DIR", Path(tmp) / "pimsync"), \
                 mock.patch("omagenda.accounts.PIMSYNC_STATUS_DIR", Path(tmp) / "status"):
                account = {"id": "nextcloud", "type": "caldav", "url": "https://cloud.example.com/remote.php/dav/",
                           "username": "calvin"}
                path = generate_pimsync_config(account, vdir_root=vdir_root)
                self.assertIn("url https://cloud.example.com/remote.php/dav/", path.read_text())

    def test_unsupported_type_raises(self):
        with self.assertRaises(ValueError):
            generate_pimsync_config({"id": "x", "type": "google"}, vdir_root=Path("/tmp"))


class DerivedAccountIdTest(unittest.TestCase):
    """`--id` is optional now, so the derived label is real behaviour.

    bin/omagenda is a script, not an importable module, so it is exec'd
    here -- which means giving it the `__file__` it reads at import time
    to locate the package beside itself."""

    def _load_cli(self):
        import importlib.util

        source_path = Path(__file__).parent.parent / "bin" / "omagenda"
        spec = importlib.util.spec_from_loader("omagenda_cli", loader=None)
        module = importlib.util.module_from_spec(spec)
        module.__dict__["__file__"] = str(source_path)
        exec(compile(source_path.read_text(), str(source_path), "exec"), module.__dict__)  # noqa: S102
        return module

    def _derive(self, account_type, email=None, username=None, existing=()):
        module = self._load_cli()
        with mock.patch("omagenda.accounts.list_accounts", return_value=[{"id": i} for i in existing]):
            return module._default_account_id(account_type, email, username)

    def test_email_local_part_names_the_account(self):
        self.assertEqual(self._derive("google", email="you@example.com"), "google-you")

    def test_username_is_used_when_there_is_no_email(self):
        self.assertEqual(self._derive("icloud", username="calvin@icloud.com"), "icloud-calvin")

    def test_type_alone_when_there_is_no_address(self):
        self.assertEqual(self._derive("caldav"), "caldav")

    def test_a_taken_name_gets_a_suffix_rather_than_colliding(self):
        self.assertEqual(
            self._derive("google", email="you@example.com", existing=("google-you",)),
            "google-you-2")

    def test_an_odd_address_still_yields_a_safe_label(self):
        self.assertEqual(self._derive("google", email="first.last+tag@gmail.com"), "google-first-last-tag")


if __name__ == "__main__":
    unittest.main()


class WritableTargetTest(unittest.TestCase):
    """`add` fell back to calendars[0], which on a real setup was a
    read-only Google subscription sorting before the local calendar, so
    every Quick Add failed with a calendar sitting right there that could
    have taken the event."""

    def _run_add(self, sentence, vdir_root):
        import subprocess
        import sys
        from pathlib import Path as P

        env = {**os.environ, "OMAGENDA_VDIR": str(vdir_root),
               "OMAGENDA_STATE": str(vdir_root.parent / "state")}
        cli = P(__file__).parent.parent / "bin" / "omagenda"
        return subprocess.run([sys.executable, str(cli), "add", sentence, "--json"],
                              capture_output=True, text=True, env=env)

    def test_a_read_only_calendar_is_never_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            vdir_root = Path(tmp) / "calendars"
            # "aaa-readonly" sorts first, exactly like a real "gcal" did.
            for name, writable in (("aaa-readonly", False), ("personal", True)):
                d = vdir_root / name
                d.mkdir(parents=True)
                (d / "displayname").write_text(name)
                if not writable:
                    d.chmod(0o555)

            result = self._run_add("Coffee today at 3pm", vdir_root)
            try:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('"calendar": "personal"', result.stdout)
            finally:
                (vdir_root / "aaa-readonly").chmod(0o755)

    def test_all_read_only_says_so_plainly(self):
        with tempfile.TemporaryDirectory() as tmp:
            vdir_root = Path(tmp) / "calendars"
            d = vdir_root / "sub"
            d.mkdir(parents=True)
            (d / "displayname").write_text("sub")
            d.chmod(0o555)
            try:
                result = self._run_add("Coffee today at 3pm", vdir_root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("read-only", result.stderr)
            finally:
                d.chmod(0o755)

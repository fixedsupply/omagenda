"""Account selection happens before sign-in, with credentials mocked."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omagenda import accounts, doctor
from tests.test_watch_sync import cli


class ReconnectTest(unittest.TestCase):
    def setUp(self):
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(doctor, 'CONFIG_PATH', base / 'config.toml'))
        self.enterContext(patch.object(accounts, 'CONFIG_PATH', base / 'config.toml'))
        self.authorize = self.enterContext(patch('omagenda.bridges.google.authorize'))
        self.calendars = self.enterContext(patch('omagenda.bridges.google.list_calendars', return_value=[]))
        self.prompt = self.enterContext(patch('getpass.getpass', return_value='https://example.com/demo.ics'))
        self.enterContext(patch.object(accounts, 'store_secret'))
        self.enterContext(patch.object(accounts, 'generate_pimsync_config', return_value=base / 'test.scfg'))

    def run_add(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            result = cli.main(['account', 'add', *args])
        return result, out.getvalue()

    def test_reconnect_preserves_settings_and_refreshes_email(self):
        accounts.write_config({'accounts': [{'id': 'demo', 'type': 'google',
            'calendars': ['selected'], 'email': 'old@example.com'}]})
        result, out = self.run_add('google', '--id', 'demo', '--email', 'you@example.com')
        self.assertEqual(result, 0, out)
        self.assertIn("Reconnected 'demo'.", out)
        self.authorize.assert_called_once()
        self.assertEqual(accounts.list_accounts(), [{'id': 'demo', 'type': 'google',
            'calendars': ['selected'], 'email': 'you@example.com'}])

    def test_type_mismatch_precedes_sign_in(self):
        accounts.write_config({'accounts': [{'id': 'demo', 'type': 'ics'}]})
        result, out = self.run_add('google', '--id', 'demo')
        self.assertEqual(result, 1)
        self.assertIn('has type ics, not google', out)
        self.authorize.assert_not_called()

    def test_no_id_refuses_every_type_before_sign_in(self):
        for kind in ('google', 'icloud', 'caldav', 'ics'):
            with self.subTest(kind=kind):
                accounts.write_config({'accounts': [{'id': 'first', 'type': kind},
                                                     {'id': 'second', 'type': kind}]})
                result, out = self.run_add(kind)
                self.assertEqual(result, 1)
                for account_id in ('first', 'second'):
                    self.assertIn(f'omagenda account add {kind} --id {account_id}', out)
                self.assertIn('new explicit --id', out)
        self.authorize.assert_not_called()
        self.calendars.assert_not_called()
        self.prompt.assert_not_called()

    def test_explicit_new_id_allows_separate_login(self):
        accounts.write_config({'accounts': [{'id': 'first', 'type': 'google'}]})
        result, out = self.run_add('google', '--id', 'second')
        self.assertEqual(result, 0, out)
        self.authorize.assert_called_once()
        self.assertEqual([a['id'] for a in accounts.list_accounts()], ['first', 'second'])

    def test_other_types_reconnect_with_existing_connection_settings(self):
        for kind in ('icloud', 'caldav', 'ics'):
            with self.subTest(kind=kind):
                original = {'id': 'demo', 'type': kind, 'username': 'you@example.com',
                            'url': 'https://example.com/demo.ics', 'sync': 'vdirsyncer'}
                accounts.write_config({'accounts': [original]})
                result, out = self.run_add(kind, '--id', 'demo')
                self.assertEqual(result, 0, out)
                self.assertIn("Reconnected 'demo'.", out)
                self.assertEqual(accounts.list_accounts(), [original])

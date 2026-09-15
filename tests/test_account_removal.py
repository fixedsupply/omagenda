"""Removal and orphan diagnostics never expose a credential."""
import contextlib
import io
import json
import os
import subprocess
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

from omagenda import accounts, doctor
from tests.test_sync import WithVdir
from tests.test_watch_sync import cli


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.vdir = self.enterContext(WithVdir())
        self.base = self.vdir.parent
        self.config = self.base / 'config.toml'
        self.secrets = self.base / 'secrets'
        self.enterContext(patch.object(doctor, 'CONFIG_PATH', self.config))
        self.enterContext(patch.object(accounts, 'CONFIG_PATH', self.config))
        self.enterContext(patch.object(accounts, 'SECRETS_DIR', self.secrets))
        self.enterContext(patch.object(accounts, 'PIMSYNC_CONFIG_DIR', self.base / 'pimsync'))
        self.enterContext(patch('shutil.which', return_value='secret-tool'))
        self.secret_run = self.enterContext(patch('omagenda.accounts.subprocess.run',
            return_value=subprocess.CompletedProcess([], 1, '', '')))
        self.network = self.enterContext(patch('omagenda.accounts.urllib.request.urlopen'))
        self.network.return_value.__enter__.return_value.status = 200
        self.secrets.mkdir()
        (self.secrets / 'demo-refresh-token').write_text('fake-private-token')
        (self.secrets / 'demo').write_text('fake-base-secret')
        (self.vdir / 'demo').mkdir()
        (self.vdir / 'demo/event.ics').write_text('retained')
        self.configure('google')

    def configure(self, kind):
        accounts.write_config({'accounts': [{'id': 'demo', 'type': kind}]})

    def remove(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(['account', 'remove', 'demo', *extra])
        self.assertEqual(status, 0, err.getvalue())
        self.assertNotIn('fake-private-token', out.getvalue() + err.getvalue())
        self.assertEqual(accounts.list_accounts(), [])
        self.assertFalse((self.secrets / 'demo').exists())
        self.assertTrue((self.vdir / 'demo/event.ics').exists())
        return out.getvalue(), err.getvalue()

    def test_success_and_json(self):
        out, err = self.remove('--json')
        self.assertEqual(json.loads(out), {'removed': True, 'revoked': True,
                                         'calendarFolder': str(self.vdir / 'demo')})
        self.assertFalse((self.secrets / 'demo-refresh-token').exists())
        calls = [c.args[0] for c in self.secret_run.call_args_list]
        self.assertIn(['secret-tool', 'clear', 'service', 'omagenda', 'account', 'demo-refresh-token'], calls)
        self.assertIn(['secret-tool', 'clear', 'service', 'omagenda', 'account', 'demo'], calls)
        request = self.network.call_args.args[0]
        self.assertEqual(request.full_url, 'https://oauth2.googleapis.com/revoke')
        self.assertEqual(request.data, b'token=fake-private-token')
        self.assertEqual(self.network.call_args.kwargs['timeout'], 10)

    def test_already_invalid(self):
        self.network.side_effect = urllib.error.HTTPError('unused', 400, 'bad', {},
            io.BytesIO(b'{"error":"invalid_token"}'))
        out, _ = self.remove('--json')
        self.assertTrue(json.loads(out)['revoked'])

    def test_offline_removes_and_warns_without_exception_contents(self):
        self.network.side_effect = OSError('fake-private-token')
        out, err = self.remove('--json')
        self.assertFalse(json.loads(out)['revoked'])
        self.assertIn('https://myaccount.google.com/permissions', err)
        self.assertEqual(sum(line.startswith('Warning:') for line in err.splitlines()), 1)
        self.assertFalse((self.secrets / 'demo-refresh-token').exists())

    def test_other_response_is_failure(self):
        self.network.return_value.__enter__.return_value.status = 503
        out, _ = self.remove('--json')
        self.assertFalse(json.loads(out)['revoked'])

    def test_no_token(self):
        (self.secrets / 'demo-refresh-token').unlink()
        out, _ = self.remove('--json')
        self.assertIsNone(json.loads(out)['revoked'])
        self.network.assert_not_called()

    def test_non_google(self):
        self.configure('icloud')
        out, _ = self.remove('--json')
        self.assertIsNone(json.loads(out)['revoked'])
        self.network.assert_not_called()

    def test_doctor_search_discards_secret_values(self):
        self.secret_run.return_value = subprocess.CompletedProcess([], 0,
            '[item]\nsecret = fake-private-token\nattribute.account = old-refresh-token\n'
            'attribute.account = demo-refresh-token\n', '')
        report = doctor._check_leftover_tokens(doctor.read_config())
        self.assertFalse(report['ok'])
        self.assertNotIn('fake-private-token', json.dumps(report))
        self.assertIn('secret-tool clear service omagenda account old-refresh-token', report['detail'])
        self.assertIn(f'rm -f {self.secrets}/old-refresh-token', report['detail'])
        self.assertNotIn('demo', report['detail'])

    def test_fallback_orphan_and_skipped_keyring(self):
        (self.secrets / 'old-refresh-token').write_text('fake-private-token')
        report = doctor._check_leftover_tokens(doctor.read_config())
        self.assertFalse(report['ok'])
        self.assertTrue(report['skipped'])
        self.assertIn('old:', report['detail'])
        self.assertNotIn('fake-private-token', json.dumps(report))

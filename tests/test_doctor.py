"""Offline diagnostics distinguish an installed CLI from a stale checkout."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import omagenda
from omagenda import doctor
from tests.test_watch_sync import cli


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.plugin = self.base / 'plugin'
        self.plugin.mkdir()
        (self.plugin / 'manifest.json').write_text('{"version": "0.2.1"}')
        self.enterContext(patch.object(doctor, 'PLUGIN_PATH', self.plugin))
        self.enterContext(patch.object(omagenda, '__file__', str(self.plugin / 'omagenda/__init__.py')))

    def test_matching_install(self):
        check = doctor._check_install()
        self.assertTrue(check['ok'])
        self.assertIn('installed version 0.2.1', check['detail'])
        self.assertIn('not a symlink', check['detail'])
        self.assertIn(str(Path(omagenda.__file__).resolve()), check['detail'])

    def test_developer_symlink(self):
        link = self.base / 'link'
        link.symlink_to(self.plugin, target_is_directory=True)
        with patch.object(doctor, 'PLUGIN_PATH', link):
            check = doctor._check_install()
        self.assertTrue(check['ok'])
        self.assertIn(f'developer install (symlink to {self.plugin})', check['detail'])

    def test_wrong_cli(self):
        outside = self.base / 'plugin-old/omagenda/__init__.py'
        with patch.object(omagenda, '__file__', str(outside)):
            check = doctor._check_install()
        self.assertFalse(check['ok'])
        for value in (str(outside), str(self.plugin), 'ln -sf ~/.config/omarchy/plugins/'):
            self.assertIn(value, check['detail'])

    def test_missing_plugin(self):
        with patch.object(doctor, 'PLUGIN_PATH', self.base / 'missing'):
            check = doctor._check_install()
        self.assertFalse(check['ok'])
        self.assertIn('plugin folder missing', check['detail'])

    def test_invalid_manifest(self):
        (self.plugin / 'manifest.json').write_text('broken')
        self.assertFalse(doctor._check_install()['ok'])

    def test_enable_remedy_depends_on_install(self):
        shell = self.base / 'shell.json'
        shell.write_text('{}')
        with patch.object(doctor, 'SHELL_JSON_PATH', shell):
            self.assertIn('omarchy plugin enable', doctor._check_plugin_enabled(True)['detail'])
            self.assertNotIn('omarchy plugin enable', doctor._check_plugin_enabled(False)['detail'])

    def test_run_passes_install_failure_to_enabled_check(self):
        with patch.object(doctor, '_check_install', return_value={'ok': False}),              patch.object(doctor, '_check_plugin_enabled', return_value={'ok': False}) as enabled,              patch.object(doctor, '_check_leftover_tokens', return_value={'ok': True}):
            self.assertFalse(doctor.run()['install']['ok'])
        enabled.assert_called_once_with(False)


class SignInTest(unittest.TestCase):
    def check(self, age, interval=300, paused=None):
        record = {'ok': True, 'at': (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()}
        with patch('omagenda.sync.read_last_sync', return_value=record),              patch('omagenda.pause.read_pause', return_value=paused),              patch.object(doctor, 'read_config', return_value={'sync_interval': interval}):
            return doctor._check_sign_in()

    def test_recent_success(self):
        self.assertTrue(self.check(600)['ok'])

    def test_thirty_minute_floor(self):
        self.assertTrue(self.check(1790)['ok'])
        result = self.check(1810)
        self.assertFalse(result['ok'])
        self.assertIn('last successful sync was 30 minutes ago; is the watcher running? try: omagenda sync',
                      result['detail'])

    def test_configured_interval(self):
        self.assertTrue(self.check(3500, interval=1200)['ok'])
        self.assertFalse(self.check(3700, interval=1200)['ok'])

    def test_paused_stays_ok(self):
        result = self.check(86400, paused='2026-09-17T00:00:00+00:00')
        self.assertTrue(result['ok'])
        self.assertIn('sync paused until', result['detail'])

    def test_invalid_timestamp(self):
        with patch('omagenda.sync.read_last_sync', return_value={'ok': True, 'at': 'bad'}),              patch('omagenda.pause.read_pause', return_value=None):
            self.assertFalse(doctor._check_sign_in()['ok'])


class DoctorExitTest(unittest.TestCase):
    def test_json_and_text_agree(self):
        for ok in (True, False):
            for args in (['doctor'], ['doctor', '--json']):
                with self.subTest(ok=ok, args=args):
                    report = {'install': {'ok': True, 'detail': 'installed'},
                              'signIn': {'ok': ok, 'detail': 'status'}}
                    out = io.StringIO()
                    with patch.object(doctor, 'run', return_value=report), contextlib.redirect_stdout(out):
                        self.assertEqual(cli.main(args), 0 if ok else 1)
                    if '--json' in args:
                        self.assertEqual(json.loads(out.getvalue()), report)

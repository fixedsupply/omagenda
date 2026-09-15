"""Offline safeguards for the opt-in iCloud script; no provider acceptance."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('icloud_acceptance', ROOT / 'tools/icloud-acceptance.py')
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class ICloudAcceptanceTests(unittest.TestCase):
    def test_requires_explicit_live_flag(self):
        with patch.object(acceptance.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                acceptance.main([])
        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_json_does_not_enable_live_run(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            acceptance.main(['--json'])

    def test_unknown_argument_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            acceptance.main(['--run-live', '--account', 'family'])

    def test_selects_only_icloud(self):
        account = {'type': 'icloud', 'id': 'test', 'username': 'you@example.com'}
        self.assertEqual(acceptance.select_account({'accounts': [{'type': 'google'}, account]}), account)

    def test_refuses_zero_or_multiple_accounts_before_keyring(self):
        for accounts in ([], [{'type': 'icloud'}, {'type': 'icloud'}]):
            with self.subTest(accounts=accounts), patch('omagenda.doctor.read_config', return_value={'accounts': accounts}), \
                    patch.object(acceptance.subprocess, 'run') as run, \
                    patch.object(acceptance.tempfile, 'mkdtemp') as mkdir, \
                    contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(acceptance.main(['--run-live', '--json']), 1)
                self.assertFalse(json.loads(output.getvalue())['success'])
                run.assert_not_called()
                mkdir.assert_not_called()

    def test_refuses_incomplete_account(self):
        for account in ({'type': 'icloud'}, {'type': 'icloud', 'id': 'test'}):
            with self.subTest(account=account), self.assertRaises(ValueError):
                acceptance.select_account({'accounts': [account]})

    def test_receipt_is_private_and_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.json'
            url = 'https://caldav.icloud.com/home/disposable/'
            acceptance.write_receipt(path, 'Omagenda acceptance invented', url, 'creation pending')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['phase'], 'creation pending')
            acceptance.write_receipt(path, 'Omagenda acceptance invented', url, 'created')
            self.assertEqual(json.loads(path.read_text()), {'calendar_name': 'Omagenda acceptance invented',
                                                         'calendar_url': url, 'phase': 'created'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_scfg_restricts_one_collection_and_uses_keyring_command(self):
        folder = Path('/tmp/acceptance example')
        account = {'id': 'test-account', 'username': 'you@example.com'}
        config = acceptance.generate_scfg(folder, account, 'https://p01-caldav.icloud.com/123/calendars/abc/')
        self.assertEqual(config.count('    collection {'), 1)
        self.assertIn('        id_a disposable\n', config)
        self.assertIn('        href_b "/123/calendars/abc/"\n', config)
        self.assertNotIn('collections ', config)
        self.assertIn('conflict_resolution keep b', config)
        self.assertIn('cmd secret-tool lookup service omagenda account "test-account"', config)
        self.assertIn('status_path "/tmp/acceptance example/pimsync-state/"', config)
        self.assertIn('path "/tmp/acceptance example/calendars/acceptance/"', config)
        self.assertNotIn('pair family', config)
        self.assertNotIn(str(Path.home()), config)

    def test_scfg_quotes_untrusted_values(self):
        config = acceptance.generate_scfg(Path('/tmp/test'),
            {'id': 'test"\ncollections all', 'username': 'you@example.com'}, 'https://caldav.icloud.com/disposable/')
        self.assertIn('account "test\\"\\ncollections all"', config)
        self.assertNotIn('\ncollections all', config)

    def test_rejects_credential_redirects_outside_icloud(self):
        for url in ('http://caldav.icloud.com/', 'https://icloud.com.evil.example/',
                    'https://you@example.com/', 'https://caldav.icloud.com:444/',
                    'https://caldav.icloud.com/?secret=value'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                acceptance.trusted_url(url)
        self.assertEqual(acceptance.trusted_url('https://p01-caldav.icloud.com/home/'),
                         'https://p01-caldav.icloud.com/home/')

    def test_child_cli_uses_isolated_pimsync_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            # Inspect the bootstrap in a child without executing any CLI command.
            command = acceptance.cli_command(folder, 'watch', '--sync-interval', '2')
            command[2] = command[2].replace('runpy.run_path(script,run_name="__main__")',
                'print(a.pimsync_config_path("acceptance")); print(a.SECRETS_DIR); print(sys.argv[1:])')
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines()[0], str(folder / 'pimsync/omagenda-acceptance.scfg'))
            self.assertEqual(result.stdout.splitlines()[1], str(folder / 'secrets'))
            self.assertEqual(result.stdout.splitlines()[2], "['watch', '--sync-interval', '2']")

    def test_missing_keyring_password_stops_before_discovery(self):
        account = {'id': 'test', 'type': 'icloud', 'username': 'you@example.com'}
        with patch('omagenda.doctor.read_config', return_value={'accounts': [account]}), \
                patch.object(acceptance.shutil, 'which', return_value='/usr/bin/pimsync'), \
                patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'')) as run, \
                patch.object(acceptance.urllib.request, 'build_opener') as opener, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(acceptance.main(['--run-live']), 1)
            self.assertEqual(run.call_args.args[0], ['secret-tool', 'lookup', 'service', 'omagenda', 'account', 'test'])
            opener.assert_not_called()

    def test_uncertain_creation_is_not_retried_and_cleanup_is_scoped(self):
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / 'receipt-folder'
                folder.mkdir(mode=0o700)
                calls = []
                account = {'id': 'test', 'type': 'icloud', 'username': 'you@example.com'}

                def response(req, timeout):
                    calls.append((req.method, req.full_url))
                    if req.method == 'PROPFIND':
                        tag, href = ('current-user-principal', '/principal/') if len(calls) == 1 else ('calendar-home-set', '/home/')
                        prefix = 'd' if len(calls) == 1 else 'c'
                        body = (f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                f'<d:response><d:propstat><d:prop><{prefix}:{tag}><d:href>{href}</d:href>'
                                f'</{prefix}:{tag}></d:prop><d:status>HTTP/1.1 200 OK</d:status>'
                                '</d:propstat></d:response></d:multistatus>').encode()
                        return io.BytesIO(body)
                    if req.method == 'MKCALENDAR':
                        receipt = json.loads((folder / 'recovery.json').read_text())
                        self.assertEqual(receipt['phase'], 'creation pending')
                        self.assertEqual(receipt['calendar_url'], req.full_url)
                        raise TimeoutError('uncertain response')
                    self.assertEqual(req.method, 'DELETE')
                    self.assertEqual(req.full_url, calls[-2][1])
                    if cleanup_fails:
                        raise TimeoutError('cleanup failed')
                    return io.BytesIO(b'')

                with patch('omagenda.doctor.read_config', return_value={'accounts': [account]}), \
                        patch.object(acceptance.shutil, 'which', return_value='/usr/bin/pimsync'), \
                        patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'invented-password', b'')), \
                        patch.object(acceptance.tempfile, 'mkdtemp', return_value=str(folder)), \
                        patch.object(acceptance.urllib.request, 'build_opener') as opener, \
                        contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                    opener.return_value.open.side_effect = response
                    self.assertEqual(acceptance.main(['--run-live', '--json']), 1)
                self.assertEqual([method for method, url in calls], ['PROPFIND', 'PROPFIND', 'MKCALENDAR', 'DELETE'])
                report = json.loads(output.getvalue())
                self.assertEqual(report['failed_stage'], 'create disposable calendar')
                self.assertEqual(report['calendar_cleaned_up'], not cleanup_fails)
                self.assertEqual(folder.exists(), cleanup_fails)
                self.assertNotIn('invented-password', output.getvalue() + errors.getvalue())
                if cleanup_fails:
                    self.assertEqual(report['recovery_receipt'], str(folder / 'recovery.json'))
                    self.assertIn(str(folder / 'recovery.json'), errors.getvalue())

    def test_bootstrap_disables_personal_omacal_probe(self):
        command = acceptance.cli_command(Path('/tmp/isolated'), 'sync')
        self.assertIn('s._merge_omacal=lambda root: None', command[2])

    @unittest.skipUnless(acceptance.shutil.which('pimsync'), 'pimsync is not installed')
    def test_native_pimsync_mapping_excludes_other_collections_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            local = folder / 'calendars/acceptance/disposable'
            remote = folder / 'remote/disposable'
            unrelated = folder / 'remote/unrelated'
            for directory in (local, remote, unrelated, folder / 'pimsync-state'):
                directory.mkdir(parents=True)
            event = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Acceptance//EN\r\n'
                     'BEGIN:VEVENT\r\nUID:invented\r\nDTSTAMP:20260915T120000Z\r\n'
                     'DTSTART:20260916T120000Z\r\nSUMMARY:Invented appointment\r\n'
                     'END:VEVENT\r\nEND:VCALENDAR\r\n')
            (remote / 'invented.ics').write_text(event)
            (unrelated / 'other.ics').write_text(event.replace('UID:invented', 'UID:unrelated'))
            config = acceptance.generate_scfg(folder, {'id': 'test', 'username': 'you@example.com'},
                                               'https://caldav.icloud.com/disposable/')
            # Keep the actual pair block; substitute a local backend for DAV.
            # Vdir hrefs are relative to the storage root; DAV hrefs use URL paths.
            config = config.split('storage acceptance_remote {')[0]
            config = config.replace('href_b "/disposable/"', 'href_b "disposable/"')
            config += 'storage acceptance_remote {\n    type vdir/icalendar\n    path ' + json.dumps(str(folder / 'remote')) + '\n}\n'
            path = folder / 'test.scfg'
            path.write_text(config)
            result = subprocess.run(['pimsync', '-v', 'debug', '-c', str(path), 'sync', 'acceptance'],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(local.glob('*.ics'))), 1)
            self.assertIn('UID:invented', next(local.glob('*.ics')).read_text())
            self.assertFalse((local.parent / 'unrelated').exists())
            self.assertTrue((unrelated / 'other.ics').exists())

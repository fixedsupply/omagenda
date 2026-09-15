"""Offline safeguards for the opt-in iCloud script; no provider acceptance."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import fcntl
import os
from tests.test_sync import WithVdir
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('icloud_acceptance', ROOT / 'tools/icloud-acceptance.py')
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class ICloudAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.vdir = self.enterContext(WithVdir())

    def test_local_event_replace_changes_content_and_inode(self):
        path = self.vdir / 'invented.ics'
        path.write_bytes(b'original')
        original_inode = path.stat().st_ino
        acceptance.replace_local_event(path, b'edited')
        self.assertEqual(path.read_bytes(), b'edited')
        self.assertNotEqual(path.stat().st_ino, original_inode)
        self.assertEqual(list(self.vdir.iterdir()), [path])

    def test_local_edit_steps_use_atomic_helper(self):
        tree = ast.parse((ROOT / 'tools/icloud-acceptance.py').read_text())
        edits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, 'write_bytes')
                if node.func.attr == 'write_text':
                    # Only setup metadata and the isolated sync config use text writes.
                    self.assertIsInstance(node.func.value, ast.BinOp)
                    self.assertIn(node.func.value.right.value,
                                  ('displayname', 'omagenda-acceptance.scfg'))
            if isinstance(node.func, ast.Name) and node.func.id == 'replace_local_event':
                self.assertEqual(node.args[0].id, 'path')
                edits.append(node.args[1].keywords[0].value.value)
        self.assertCountEqual(edits, ['Locally edited appointment', 'Local conflict copy'])

    def test_report_skips_collection_and_preserves_item_with_explicit_port(self):
        calendar_url = 'https://p01-caldav.icloud.com:443/home/disposable/'
        for trailing_slash in ('', '/'):
            with self.subTest(trailing_slash=trailing_slash):
                body = f'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
                  <d:response><d:href>/home/disposable{trailing_slash}</d:href>
                    <d:propstat><d:prop><d:getetag>"collection"</d:getetag></d:prop>
                      <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
                  <d:response><d:href>/home/disposable/invented.ics</d:href>
                    <d:propstat><d:prop><c:calendar-data>BEGIN:VCALENDAR
END:VCALENDAR</c:calendar-data></d:prop>
                      <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
                </d:multistatus>'''.encode()
                self.assertEqual(acceptance.parse_events_report(body, calendar_url),
                                 {calendar_url + 'invented.ics': b'BEGIN:VCALENDAR\nEND:VCALENDAR'})

    def test_report_rejects_other_collection(self):
        body = b'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
          <d:response><d:href>/home/disposable-other/invented.ics</d:href>
            <d:propstat><d:prop><c:calendar-data>invented</c:calendar-data></d:prop>
              <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
        </d:multistatus>'''
        with self.assertRaisesRegex(RuntimeError, 'outside the disposable calendar'):
            acceptance.parse_events_report(body, 'https://p01-caldav.icloud.com:443/home/disposable/')

    def test_report_rejects_item_without_calendar_data(self):
        body = b'''<d:multistatus xmlns:d="DAV:">
          <d:response><d:href>/home/disposable/invented.ics</d:href>
            <d:propstat><d:prop><d:getetag>"item"</d:getetag></d:prop>
              <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
        </d:multistatus>'''
        with self.assertRaisesRegex(RuntimeError, 'REPORT omitted calendar data'):
            acceptance.parse_events_report(body, 'https://p01-caldav.icloud.com:443/home/disposable/')

    def test_failure_line_includes_script_exception_messages(self):
        for exception in (RuntimeError, AssertionError, TimeoutError, ValueError):
            with self.subTest(exception=exception):
                self.assertEqual(acceptance.failure_line('offline check', exception('Fixed script message')),
                                 f'FAIL: offline check ({exception.__name__}: Fixed script message)')

    def test_failure_line_hides_library_exception_messages(self):
        private_url = 'https://p01-caldav.icloud.com/123/calendars/invented/'
        for exc in (OSError(private_url), json.JSONDecodeError(private_url, '', 0)):
            with self.subTest(exception=type(exc)):
                self.assertEqual(acceptance.failure_line('offline check', exc),
                                 f'FAIL: offline check ({type(exc).__name__})')

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
        self.assertIn('conflict_resolution cmd ', config)
        self.assertIn('resolve-conflict --account "acceptance"', config)
        self.assertNotIn('keep b', config)
        self.assertIn('cmd secret-tool lookup service omagenda account "test-account"', config)
        self.assertIn('status_path "/tmp/acceptance example/pimsync-state/"', config)
        self.assertIn('path "/tmp/acceptance example/calendars/acceptance/"', config)
        self.assertNotIn('pair family', config)
        # The conflict resolver is the plugin's own CLI; no other real path may appear.
        from omagenda.accounts import CONFLICT_RESOLVER
        self.assertNotIn(str(Path.home()), config.replace(str(CONFLICT_RESOLVER), ''))

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

    @patch.object(acceptance, 'require_pause_support')
    def test_missing_keyring_password_stops_before_discovery(self, support):
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
        for cleanup_fails, has_orphan in ((False, False), (True, False), (False, True)):
            with self.subTest(cleanup_fails=cleanup_fails, has_orphan=has_orphan), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / 'receipt-folder'
                folder.mkdir(mode=0o700)
                calls = []
                account = {'id': 'test', 'type': 'icloud', 'username': 'you@example.com'}

                def response(req, timeout):
                    calls.append((req.method, req.full_url))
                    if req.method == 'PROPFIND':
                        tag, href = ('current-user-principal', '/principal/') if len(calls) == 2 else ('calendar-home-set', '/home/')
                        prefix = 'd' if len(calls) == 2 else 'c'
                        body = (f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                f'<d:response><d:propstat><d:prop><{prefix}:{tag}><d:href>{href}</d:href>'
                                f'</{prefix}:{tag}></d:prop><d:status>HTTP/1.1 200 OK</d:status>'
                                '</d:propstat></d:response></d:multistatus>').encode()
                        return io.BytesIO(body)
                    if req.method == 'MKCALENDAR':
                        receipt = json.loads((folder / 'recovery.json').read_text())
                        self.assertEqual(receipt['phase'], 'creation pending')
                        self.assertEqual(receipt['calendar_url'], req.full_url)
                        if has_orphan:
                            collection = req.full_url.rstrip('/').split('/')[-1]
                            (self.vdir / account['id'] / collection).mkdir(parents=True)
                        raise TimeoutError('uncertain response')
                    self.assertEqual(req.method, 'DELETE')
                    self.assertEqual(req.full_url, calls[-2][1])
                    if cleanup_fails:
                        raise TimeoutError('cleanup failed')
                    return io.BytesIO(b'')

                def installed(*args):
                    calls.append(('PAUSE' if args[0] == '--pause' else 'RESUME', 'installed'))
                    return {'pausedUntil': '2099-01-01T00:00:00+00:00' if args[0] == '--pause' else None}

                original_orphans = acceptance.real_vdir_orphans
                def orphans(*args):
                    calls.append(('ORPHAN CHECK', 'local'))
                    return original_orphans(*args)

                with patch.object(acceptance, 'require_pause_support'), \
                        patch.object(acceptance, 'real_vdir_orphans', side_effect=orphans), \
                        patch.object(acceptance, 'installed_sync', side_effect=installed), \
                        patch.object(acceptance, 'confirm_watcher_pause'), \
                        patch('omagenda.doctor.read_config', return_value={'accounts': [account]}), \
                        patch.object(acceptance.shutil, 'which', return_value='/usr/bin/pimsync'), \
                        patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'invented-password', b'')), \
                        patch.object(acceptance.tempfile, 'mkdtemp', return_value=str(folder)), \
                        patch.object(acceptance.urllib.request, 'build_opener') as opener, \
                        contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                    opener.return_value.open.side_effect = response
                    self.assertEqual(acceptance.main(['--run-live', '--json']), 1)
                self.assertEqual([method for method, url in calls], ['PAUSE', 'PROPFIND', 'PROPFIND', 'MKCALENDAR', 'DELETE', 'ORPHAN CHECK', 'RESUME'])
                report = json.loads(output.getvalue())
                self.assertEqual(report['failed_stage'], 'create disposable calendar')
                self.assertEqual(report['calendar_cleaned_up'], not cleanup_fails)
                self.assertTrue(folder.exists())
                self.assertEqual(report['temporary_folder'], str(folder))
                self.assertIn(str(folder), errors.getvalue())
                self.assertTrue(report['real_sync_paused'])
                self.assertTrue(report['real_sync_resumed'])
                if has_orphan:
                    orphan = Path(report['real_vdir_orphan'])
                    self.assertTrue(orphan.is_dir())
                    self.assertIn(f'rm -rf -- {orphan}', errors.getvalue())
                    self.assertEqual(report['cleanup_failed_stage'], 'real vdir orphan check')
                else:
                    self.assertIsNone(report['real_vdir_orphan'])
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


class RealPauseSafeguardsTest(unittest.TestCase):
    def setUp(self):
        self.vdir = self.enterContext(WithVdir())
        self.state = Path(os.environ['OMAGENDA_STATE'])
        self.account = {'id': 'test', 'type': 'icloud', 'username': 'you@example.com'}
        self.enterContext(patch('omagenda.doctor.read_config', return_value={'accounts': [self.account]}))
        self.run = self.enterContext(patch.object(acceptance.subprocess, 'run'))
        self.opener = self.enterContext(patch.object(acceptance.urllib.request, 'build_opener'))
        self.mkdir = self.enterContext(patch.object(acceptance.tempfile, 'mkdtemp'))

    def main(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = acceptance.main(['--run-live', '--json'])
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_missing_support_stops_before_any_write(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, 'sync --json', '')
        code, report, err = self.main()
        self.assertEqual(code, 1)
        self.assertEqual(report['failed_stage'], 'installed pause support preflight')
        self.assertIn('merged and installed first', err)
        self.assertFalse(report['real_sync_paused'])
        self.assertFalse(report['real_sync_resumed'])
        self.assertEqual(self.run.call_args.args[0], [str(acceptance.installed_cli()), 'sync', '--help'])
        self.assertEqual(self.run.call_count, 1)
        self.opener.assert_not_called()
        self.mkdir.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_missing_installed_cli_has_same_preflight_message(self):
        self.run.side_effect = FileNotFoundError
        self.assertIn('merged and installed first', self.main()[2])
        self.mkdir.assert_not_called()

    def test_confirmation_timeout_resumes_before_any_icloud_write(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if command[0] == 'secret-tool':
                return subprocess.CompletedProcess([], 0, b'fake-password', b'')
            self.assertNotIn('env', kwargs)
            if '--help' in command:
                output = 'sync --pause DURATION --resume'
            else:
                output = json.dumps({'pausedUntil': '2099-01-01T00:00:00+00:00' if '--pause' in command else None})
            return subprocess.CompletedProcess([], 0, output, '')
        self.run.side_effect = run
        with patch.object(acceptance.shutil, 'which', return_value='pimsync'), \
             patch.object(acceptance, 'watcher_running', return_value=True), \
             patch.object(acceptance.time, 'monotonic', side_effect=[0, 0, 91]), \
             patch.object(acceptance.time, 'sleep'):
            code, report, err = self.main()
        self.assertEqual(code, 1)
        self.assertEqual(report['failed_stage'], 'watcher pause confirmation')
        self.assertTrue(report['real_sync_paused'])
        self.assertTrue(report['real_sync_resumed'])
        self.assertEqual(commands[-1], [str(acceptance.installed_cli()), 'sync', '--resume', '--json'])
        self.assertIn('90 seconds', err)
        self.opener.return_value.open.assert_not_called()
        self.mkdir.assert_not_called()

    def test_pause_failure_still_attempts_resume(self):
        with patch.object(acceptance, 'require_pause_support'), \
             patch.object(acceptance.shutil, 'which', return_value='pimsync'), \
             patch.object(acceptance, 'installed_sync', side_effect=[TimeoutError, {'pausedUntil': None}]) as installed:
            self.run.return_value = subprocess.CompletedProcess([], 0, b'fake-password', b'')
            _, report, _ = self.main()
        self.assertFalse(report['real_sync_paused'])
        self.assertTrue(report['real_sync_resumed'])
        self.assertEqual(installed.call_args.args, ('--resume',))
        self.opener.return_value.open.assert_not_called()

    def test_failed_resume_prints_exact_command(self):
        with patch.object(acceptance, 'require_pause_support'), \
             patch.object(acceptance.shutil, 'which', return_value='pimsync'), \
             patch.object(acceptance, 'installed_sync', side_effect=[{'pausedUntil': '2099-01-01T00:00:00+00:00'}, OSError]), \
             patch.object(acceptance, 'confirm_watcher_pause', side_effect=TimeoutError):
            self.run.return_value = subprocess.CompletedProcess([], 0, b'fake-password', b'')
            _, report, err = self.main()
        self.assertFalse(report['real_sync_resumed'])
        self.assertIn(str(acceptance.installed_cli()) + ' sync --resume', err)

    def test_watch_lock_probe_never_creates_file_and_releases_lock(self):
        self.assertFalse(acceptance.watcher_running(self.state))
        self.assertFalse(self.state.exists())
        self.state.mkdir()
        lock = self.state / 'watch.lock'
        lock.write_text('invented pid')
        with lock.open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(acceptance.watcher_running(self.state))
        self.assertFalse(acceptance.watcher_running(self.state))
        with lock.open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(lock.read_text(), 'invented pid')

    def test_confirmation_requires_exact_timestamp(self):
        self.state.mkdir()
        agenda = self.state / 'agenda.json'
        agenda.write_text('{"syncPausedUntil":"different"}')
        until = '2099-01-01T00:00:00+00:00'
        def tick(seconds):
            agenda.write_text(json.dumps({'syncPausedUntil': until}))
        with patch.object(acceptance, 'watcher_running', return_value=True), \
             patch.object(acceptance.time, 'sleep', side_effect=tick) as sleep:
            acceptance.confirm_watcher_pause(self.state, until)
        sleep.assert_called_once_with(1)

    def test_no_watcher_needs_no_confirmation(self):
        with patch.object(acceptance.time, 'sleep') as sleep:
            acceptance.confirm_watcher_pause(self.state, 'future')
        sleep.assert_not_called()

    def test_orphan_detection_is_read_only_and_account_scoped(self):
        config = {'accounts': [self.account, {'id': 'dav', 'type': 'caldav'}, {'id': 'google', 'type': 'google'}]}
        for name in ('test', 'dav', 'google', 'unconfigured'):
            (self.vdir / name / 'uuid').mkdir(parents=True)
        found = acceptance.real_vdir_orphans(config, self.vdir, 'uuid')
        self.assertEqual(found, [self.vdir / 'test/uuid', self.vdir / 'dav/uuid'])
        self.assertTrue(all(p.exists() for p in found))
        self.assertEqual(acceptance.real_vdir_orphans(config, self.vdir, 'absent'), [])

    def test_stop_watcher_stops_process_group_and_waits(self):
        from unittest.mock import Mock
        watcher = Mock(pid=123456)
        order = []
        watcher.wait.side_effect = lambda **kwargs: order.append('wait')
        with patch.object(acceptance.os, 'killpg', side_effect=lambda pid, sig: order.append(sig)):
            acceptance.stop_watcher(watcher)
        self.assertEqual(order, [acceptance.signal.SIGTERM, 'wait', acceptance.signal.SIGKILL, 'wait'])

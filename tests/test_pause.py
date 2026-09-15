"""Pause state and all sync attempts stay in disposable directories."""
import contextlib
import io
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from omagenda import pause, sync, doctor
from omagenda.index import build_agenda
from tests.test_sync import WithVdir
from tests.test_watch_sync import cli


class PauseTest(unittest.TestCase):
    def setUp(self):
        self.vdir = self.enterContext(WithVdir())
        self.config = self.vdir.parent / 'config.toml'
        self.config.write_text('')
        self.enterContext(patch.object(doctor, 'CONFIG_PATH', self.config))
        self.provider = self.enterContext(patch.object(sync, '_sync_all_locked', return_value={}))

    def command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(['sync', *args])
        return status, out.getvalue(), err.getvalue()

    def test_duration_limits(self):
        for value, seconds in [('90s', 90), ('20m', 1200), ('2h', 7200),
                               ('24h', 86400), ('1440m', 86400), ('86400s', 86400)]:
            self.assertEqual(pause.parse_duration(value), seconds)
        for value in ['', '0s', '-1m', '1.5h', '25h', '86401s', '1441m', '20', ' 2h', '2H', '9'*5000+'s']:
            with self.assertRaises(ValueError):
                pause.parse_duration(value)
        self.assertEqual(self.command('--pause', '')[0], 1)
        status, out, err = self.command('--pause', '25h')
        self.assertEqual(status, 1)
        self.assertEqual(out, '')
        self.assertEqual(len(err.splitlines()), 1)
        self.assertFalse(pause.state_path().exists())

    def test_cli_round_trip_resume_and_json(self):
        status, out, _ = self.command('--pause', '30m', '--json')
        self.assertEqual(status, 0)
        until = json.loads(out)['pausedUntil']
        self.assertEqual(json.loads(out), {'pausedUntil': until})
        self.assertEqual(pause.read_pause(), until)
        self.assertEqual(pause.state_path().read_text(), until + '\n')
        self.assertIsNotNone(datetime.fromisoformat(until).utcoffset())
        self.assertEqual(build_agenda()['syncPausedUntil'], until)
        with patch.object(doctor, '_check_leftover_tokens', return_value={}):
            self.assertEqual(doctor.run()['syncPause'], {'ok': True, 'detail': f'paused until {until}'})
        self.assertEqual(self.command('--resume', '--json')[:2], (0, '{"pausedUntil": null}\n'))
        self.assertFalse(pause.state_path().exists())
        self.assertIsNone(build_agenda()['syncPausedUntil'])
        self.provider.assert_not_called()

    def test_expired_invalid_unreadable_files_are_ignored_without_deletion(self):
        pause.pause_sync('1s')
        for value in ['invalid', '2026-01-01T00:00:00',
                      (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()]:
            pause.state_path().write_text(value)
            self.assertIsNone(pause.read_pause())
            self.assertIsNone(build_agenda()['syncPausedUntil'])
            self.assertEqual(pause.state_path().read_text(), value)
        with patch('pathlib.Path.read_text', side_effect=PermissionError):
            self.assertIsNone(pause.read_pause())

    def test_skip_is_checked_after_lock_and_manual_sync_runs(self):
        order = []
        @contextlib.contextmanager
        def lock(*args):
            order.append('locked')
            yield
            order.append('released')
        def read(*args):
            self.assertEqual(order, ['locked'])
            return 'future'
        with patch.object(sync, '_sync_lock', lock), patch.object(pause, 'read_pause', side_effect=read):
            result = sync.sync_all(respect_pause=True)
        self.assertEqual(result, {'_pause': {'ok': True, 'skipped': True, 'pausedUntil': 'future'}})
        self.provider.assert_not_called()
        until = pause.pause_sync('1h')
        status, _, err = self.command('--json')
        self.assertEqual(status, 0)
        self.assertIn(until, err)
        self.provider.assert_called_once()

    def test_pause_waits_for_current_sync_after_writing_state(self):
        holding, release, completed = threading.Event(), threading.Event(), threading.Event()
        def holder():
            with sync._sync_lock():
                holding.set()
                release.wait(5)
        def pauser():
            pause.pause_sync('1h')
            completed.set()
        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(holding.wait(2))
        waiter = threading.Thread(target=pauser)
        waiter.start()
        try:
            self.assertFalse(completed.wait(0.1))
            self.assertIsNotNone(pause.read_pause())
        finally:
            release.set()
            thread.join(5)
            waiter.join(5)
        self.assertTrue(completed.is_set())

    def test_sync_once_requests_pause_and_reports_skip(self):
        with patch.object(sync, 'sync_all', return_value={'_pause': {'ok': True, 'skipped': True}}) as attempt:
            self.assertFalse(cli._sync_once())
        attempt.assert_called_once_with(respect_pause=True)

    def test_pending_push_survives_skipped_tick(self):
        self.config.write_text('[[accounts]]\nid="demo"\ntype="icloud"\n')
        pending = []
        def due(now, last, push, interval):
            pending.append(push)
            return True
        args = cli.build_parser().parse_args(['watch'])
        with patch.object(cli, '_sync_due', side_effect=due), \
             patch.object(cli, '_sync_once', side_effect=[True, False, True, True]), \
             patch.object(cli, '_wait_for_vdir_change', side_effect=[True, False, False, KeyboardInterrupt]), \
             patch('omagenda.alarms.check_and_fire'):
            self.assertEqual(cli.cmd_watch(args), 0)
        self.assertEqual(pending, [False, True, True, False])

    def test_flags_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['sync', '--pause', '1h', '--resume'])

    def test_failed_sync_waits_for_interval_before_retrying(self):
        self.config.write_text('[[accounts]]\nid="demo"\ntype="icloud"\n')
        now = [1000.0]
        calls_per_tick = []
        def tick(*args, **kwargs):
            calls_per_tick.append(attempt.call_count)
            if len(calls_per_tick) == 3:
                raise KeyboardInterrupt
            now[0] = 1001.0 if len(calls_per_tick) == 1 else 1300.0
            return False
        with patch.object(sync, 'sync_all', side_effect=OSError('network down')) as attempt, \
             patch('time.monotonic', side_effect=lambda: now[0]), \
             patch.object(cli, '_wait_for_vdir_change', side_effect=tick), \
             patch('omagenda.alarms.check_and_fire'), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_watch(cli.build_parser().parse_args(['watch'])), 0)
        self.assertEqual(calls_per_tick, [1, 1, 2])

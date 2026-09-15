"""Visibility is durable, leaves sync alone, and never uses personal data."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch, Mock

from omagenda import accounts, alarms, doctor, sync
from omagenda.index import build_agenda
from tests.test_watch_sync import cli

ROOT = Path(__file__).resolve().parent.parent


class VisibilityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = self.base / 'config.toml'
        self.state = self.base / 'state'
        self.vdir = self.base / 'vdir'
        shutil.copytree(ROOT / 'tests/fixtures/vdir', self.vdir)
        self.env = dict(os.environ, OMAGENDA_CONFIG=str(self.config),
                        OMAGENDA_STATE=str(self.state), OMAGENDA_VDIR=str(self.vdir))
        for guard in (patch.dict(os.environ, self.env),
                      patch.object(doctor, 'CONFIG_PATH', self.config),
                      patch.object(accounts, 'CONFIG_PATH', self.config)):
            guard.start()
            self.addCleanup(guard.stop)
        self.save([])

    def save(self, hidden):
        accounts.write_config({'hidden_calendars': hidden})

    def command(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/omagenda'), *args],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def agenda(self):
        return build_agenda(start=date(2026, 9, 7))

    def test_filter_counts_and_cache_restore(self):
        original = self.agenda()
        self.save(['work', 'missing'])
        filtered = self.agenda()
        self.assertEqual(filtered['events'], [e for e in original['events'] if e['calendar'] != 'work'])
        self.assertEqual(len(filtered['calendars']), len(original['calendars']))
        self.assertEqual(filtered['visibleCalendarCount'], filtered['calendarCount'] - 1)
        self.assertTrue(next(c for c in filtered['calendars'] if c['id'] == 'work')['hidden'])
        self.save([])
        self.assertEqual(self.agenda()['events'], original['events'])

    def test_legacy_preferences_are_ignored(self):
        original = self.agenda()
        self.config.write_text('[sets]\nold = ["work"]\n')
        (self.state / 'active-set').write_text('old\n')
        self.assertEqual(self.agenda()['events'], original['events'])

    def test_cli_shapes_and_immediate_reindex(self):
        self.save(['missing'])
        result = json.loads(self.command('calendars', '--hide', 'work', '--hide', 'personal', '--json'))
        self.assertEqual(result['hiddenCalendars'], ['missing', 'work', 'personal'])
        self.assertTrue(all(isinstance(c['hidden'], bool) for c in result['calendars']))
        indexed = json.loads((self.state / 'agenda.json').read_text())
        self.assertEqual(indexed['visibleCalendarCount'], indexed['calendarCount'] - 2)
        self.assertIn('[hidden]', self.command('calendars'))
        result = json.loads(self.command('calendars', '--show', 'work', '--json'))
        self.assertEqual(result['hiddenCalendars'], ['missing', 'personal'])
        result = json.loads(self.command('calendars', '--show-all', '--json'))
        self.assertEqual(result['hiddenCalendars'], [])

    def test_unknown_id_has_one_safe_error_and_no_write(self):
        original = self.config.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'bin/omagenda'), 'calendars', '--hide', 'not-known'],
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.splitlines(), ['omagenda: unknown calendar id'])
        self.assertEqual(self.config.read_bytes(), original)

    def test_every_config_rewrite_preserves_visibility(self):
        self.save(['work', 'missing'])
        for arguments in [('calendars', '--set-default', 'personal'), ('calendars', '--clear-default'),
                          ('account', 'add', 'ics', '--id', 'demo', '--url', 'https://example.com/demo.ics'),
                          ('account', 'remove', 'demo'), ('calendars', '--hide', 'personal'),
                          ('calendars', '--show', 'personal')]:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                args = cli.build_parser().parse_args(list(arguments))
                self.assertEqual(args.func(args), 0)
            self.assertEqual(doctor.read_config()['hidden_calendars'][:2], ['work', 'missing'])

    def test_next_and_alarms_exclude_hidden_events(self):
        original = self.agenda()
        event = next(e for e in original['events'] if e['alarms'] and not e['allDay'])
        now = datetime.fromisoformat(event['start']) + alarms.parse_trigger(event['alarms'][0])
        notify = Mock()
        (self.base / "alarm-before").mkdir()
        alarms.check_and_fire(original, self.base / 'alarm-before', now, notify)
        self.assertTrue(notify.called)
        self.save([c['id'] for c in original['calendars']])
        hidden = self.agenda()
        self.assertEqual(hidden['events'], [])
        notify.reset_mock()
        self.assertEqual(alarms.check_and_fire(hidden, self.base / 'alarm-after', now, notify), [])
        notify.assert_not_called()
        output = io.StringIO()
        with patch('omagenda.index.date') as day, contextlib.redirect_stdout(output):
            day.today.return_value = date(2026, 9, 7)
            cli.cmd_next(cli.build_parser().parse_args(['next', '--json']))
        self.assertIsNone(json.loads(output.getvalue()))

    def test_sync_keeps_all_account_selections(self):
        google = {'id': 'google', 'type': 'google', 'calendars': ['primary', 'holidays']}
        cloud = {'id': 'cloud', 'type': 'icloud', 'sync': 'pimsync'}
        config = {'hidden_calendars': ['google/primary', 'cloud/work'], 'accounts': [google, cloud]}
        with patch.object(sync, '_sync_bridge', return_value={'ok': True}) as bridge, \
             patch.object(sync, '_sync_caldav', return_value={'ok': True}) as caldav, \
             patch.object(sync, '_merge_omacal', return_value=None):
            sync.sync_all(config, self.state)
        self.assertEqual(bridge.call_args.args[0], google)
        caldav.assert_called_once_with(cloud)

    def test_doctor_reports_stale_ids_without_failure(self):
        self.save(['work', 'missing'])
        with patch.object(doctor, '_check_leftover_tokens', return_value={}), \
             patch.object(doctor, '_check_keyring', return_value={}):
            result = doctor.run()['hiddenCalendars']
        self.assertTrue(result['ok'])
        self.assertIn('2 hidden', result['detail'])
        self.assertIn('missing', result['detail'])

    def test_hidden_default_still_receives_new_events(self):
        accounts.write_config({'hidden_calendars': ['personal'], 'default_calendar': 'personal'})
        result = json.loads(self.command('add', 'lunch tomorrow 1pm', '--dry-run', '--json'))
        self.assertEqual(result['calendar'], 'personal')

    def test_watcher_reads_visibility_on_next_tick_without_sync(self):
        snapshots = []
        def tick(*args, **kwargs):
            if len(snapshots) == 1:
                self.save(['work'])
                return False
            raise KeyboardInterrupt
        with patch.object(cli, '_wait_for_vdir_change', side_effect=tick), \
             patch.object(cli, '_sync_once') as attempt, \
             patch('omagenda.alarms.check_and_fire', side_effect=lambda agenda: snapshots.append(agenda)):
            self.assertEqual(cli.cmd_watch(cli.build_parser().parse_args(['watch', '--no-sync'])), 0)
        attempt.assert_not_called()
        self.assertFalse(next(c for c in snapshots[0]['calendars'] if c['id'] == 'work')['hidden'])
        self.assertTrue(next(c for c in snapshots[1]['calendars'] if c['id'] == 'work')['hidden'])

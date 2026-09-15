"""Calendar selection stays isolated from config and survives watcher ticks."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from omagenda import doctor
from omagenda.index import build_agenda
from omagenda.sets import read_active, write_active
from tests.test_watch_sync import cli

ROOT = Path(__file__).resolve().parent.parent


class CalendarSetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / 'config.toml'
        self.config.write_text('[sets]\nwork = ["work"]\nhome = ["personal", "family"]\nempty = []\nmissing = ["absent"]\n')
        self.state = self.base / 'state'
        self.env = dict(os.environ, OMAGENDA_CONFIG=str(self.config),
                        OMAGENDA_STATE=str(self.state),
                        OMAGENDA_VDIR=str(ROOT / 'tests/fixtures/vdir'))
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.env).start()
        patch.object(doctor, 'CONFIG_PATH', self.config).start()

    def command(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'bin/omagenda'), *args],
                              env=self.env, text=True, capture_output=True)

    def agenda(self, **kwargs):
        return build_agenda(start=date(2026, 9, 7), **kwargs)

    def test_state_round_trip_and_clear(self):
        self.assertEqual(read_active(), '')
        write_active('work')
        self.assertEqual((self.state / 'active-set').read_text(), 'work\n')
        self.assertEqual(read_active(), 'work')
        write_active('home')
        self.assertEqual(read_active(), 'home')
        write_active('')
        write_active('')
        self.assertFalse((self.state / 'active-set').exists())

    def test_filter_and_restore_with_cache(self):
        all_events = self.agenda()['events']
        write_active('work')
        agenda = self.agenda()
        self.assertEqual(agenda['activeSet'], 'work')
        self.assertEqual([c['id'] for c in agenda['calendars']], ['work'])
        self.assertEqual(agenda['events'], [e for e in all_events if e['calendar'] == 'work'])
        write_active('home')
        self.assertEqual(self.agenda()['events'], [e for e in all_events if e['calendar'] != 'work'])
        write_active('')
        self.assertEqual(self.agenda()['events'], all_events)

    def test_empty_and_unknown_mean_all(self):
        expected = self.agenda()['events']
        for name in ('empty', 'unknown'):
            write_active(name)
            agenda = self.agenda()
            self.assertEqual(agenda['activeSet'], name)
            self.assertEqual(agenda['events'], expected)
            self.assertEqual(len(agenda['calendars']), 3)

    def test_defined_set_with_no_matching_calendars_is_empty(self):
        write_active('missing')
        self.assertEqual(self.agenda()['calendars'], [])
        self.assertEqual(self.agenda()['events'], [])

    def test_json_list_select_clear_and_immediate_index(self):
        original = self.config.read_bytes()
        for arguments, expected in (((), ''), (('work',), 'work'), (('--clear',), '')):
            result = self.command('set', *arguments, '--json')
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload), {'activeSet', 'sets'})
            self.assertEqual(payload['activeSet'], expected)
            self.assertEqual(list(payload['sets']), ['work', 'home', 'empty', 'missing'])
            if arguments:
                agenda = json.loads((self.state / 'agenda.json').read_text())
                self.assertEqual(agenda['activeSet'], expected)
                self.assertEqual(len(agenda['calendars']), 1 if expected else 3)
        self.assertEqual(self.config.read_bytes(), original)

    def test_unknown_name_fails_without_changing_state(self):
        write_active('work')
        for name in ('unknown', 'bad\nname', ''):
            result = self.command('set', name, '--json')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertEqual(result.stdout, '')
            self.assertEqual(read_active(), 'work')

    def test_number_uses_config_order(self):
        result = self.command('set', '--number', '2', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['activeSet'], 'home')
        for number in ('0', '5', '10'):
            self.assertNotEqual(self.command('set', '--number', number).returncode, 0)
        self.assertEqual(read_active(), 'home')

    def test_agenda_override_does_not_change_state(self):
        write_active('home')
        result = self.command('agenda', '--set', 'work', '--from', '2026-09-07', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        agenda = json.loads(result.stdout)
        self.assertEqual(agenda['activeSet'], 'work')
        self.assertTrue(agenda['events'])
        self.assertTrue(all(e['calendar'] == 'work' for e in agenda['events']))
        self.assertEqual(read_active(), 'home')

    def test_doctor_warns_for_unknown_state(self):
        for name, expected in (('', True), ('work', True), ('unknown', False)):
            write_active(name)
            report = doctor.run()['activeSet']
            self.assertEqual(report['ok'], expected)
            if not expected:
                self.assertIn('warning:', report['detail'])
                self.assertIn('showing all calendars', report['detail'])

    def test_watcher_reads_state_on_next_tick_without_sync(self):
        snapshots = []

        def tick(*args, **kwargs):
            snapshots.append(json.loads((self.state / 'agenda.json').read_text()))
            if len(snapshots) == 1:
                write_active('work')
                return False
            raise KeyboardInterrupt

        args = cli.build_parser().parse_args(['watch', '--no-sync'])
        with patch.object(cli, '_wait_for_vdir_change', side_effect=tick), \
             patch.object(cli, '_sync_once') as sync, \
             patch('omagenda.alarms.check_and_fire'):
            self.assertEqual(cli.cmd_watch(args), 0)
        sync.assert_not_called()
        self.assertEqual([s['activeSet'] for s in snapshots], ['', 'work'])
        self.assertEqual([c['id'] for c in snapshots[1]['calendars']], ['work'])

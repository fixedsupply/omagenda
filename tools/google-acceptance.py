#!/usr/bin/env python3
"""Opt-in live Google acceptance, confined to a newly created calendar.

Uses the stored account for events and one-off consent for calendar creation.
No invitees, personal event reads, or production configuration changes. Deletes its own calendar in finally.
A private recovery receipt remains if cleanup fails. Not part of unit discovery.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import urllib.request
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


APP_CREATED_SCOPES = ("https://www.googleapis.com/auth/calendar.app.created",)


@contextmanager
def calendar_authorization(account):
    """Keep the disposable-calendar token in memory only, and never revoke it.

    It is requested without offline access, so no refresh token exists and
    the access token expires by itself within an hour. Revoking it is
    deliberately avoided: Google may treat a revocation as withdrawing the
    whole grant for this OAuth client and Google account, which would also
    sign the maintainer's everyday Omagenda out (the same concern that made
    `omagenda account remove` local by default in v0.2.1)."""
    from omagenda.bridges import google

    tokens = google.exchange_authorization(account, scopes=APP_CREATED_SCOPES, offline=False)
    if not set(APP_CREATED_SCOPES) <= set(tokens.get("scope", "").split()):
        raise RuntimeError("Disposable-calendar permission was not granted")
    yield tokens["access_token"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='create and delete a disposable Google calendar')
    options = parser.parse_args()
    if not options.run_live:
        parser.error('This writes to Google; explicitly supply --run-live')

    from omagenda.doctor import read_config
    from omagenda.accounts import write_config
    from omagenda.bridges import google, RemoteCalendar
    from omagenda.sync import _sync_one_calendar
    import icalendar

    accounts = [a for a in read_config().get('accounts', []) if a.get('type') == 'google']
    if len(accounts) != 1 or not accounts[0].get('calendars'):
        raise RuntimeError('Requires exactly one Google account with explicit calendar selection')
    account = accounts[0]
    calendar_id = None
    watcher = None
    folder = Path(tempfile.mkdtemp(prefix='omagenda-google-acceptance-'))
    receipt = folder / 'recovery.json'
    passed = []
    stage = 'one-off calendar authorization'
    authorization = ExitStack()

    def check(label, condition=True):
        if not condition:
            raise AssertionError(label)
        passed.append(label)
        print('PASS: ' + label, flush=True)

    def api(method, suffix='', body=None):
        if not calendar_id:
            raise RuntimeError('No disposable calendar has been created')
        url = google.API_BASE + '/calendars/' + quote(calendar_id, safe='') + suffix
        return google._authed_request(account, method, url, body=body)[1]

    def until(label, predicate, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if watcher is not None and watcher.poll() is not None:
                raise RuntimeError('Isolated watcher exited')
            if predicate():
                check(label)
                return
            time.sleep(2)
        raise TimeoutError(label)

    success = False
    cleaned = False
    try:
        calendar_token = authorization.enter_context(calendar_authorization(account))
        stage = 'create disposable calendar'
        # Do not retry this POST: an uncertain response must not create a
        # second calendar. The unique name helps manual recovery if needed.
        name = 'Omagenda acceptance ' + uuid.uuid4().hex[:12]
        receipt.write_text(json.dumps({'calendar_name': name}))
        receipt.chmod(0o600)
        request = urllib.request.Request(google.API_BASE + '/calendars', method='POST',
            headers={'Authorization': 'Bearer ' + calendar_token,
                     'Content-Type': 'application/json'},
            data=json.dumps({'summary': name, 'timeZone': 'UTC'}).encode())
        with urllib.request.urlopen(request, timeout=20) as response:
            created = json.load(response)
        calendar_id = created['id']
        receipt.write_text(json.dumps({'calendar_name': name, 'calendar_id': calendar_id}))
        check('created disposable Google calendar')
        vdir = folder / 'calendars'
        state = folder / 'state'
        local = vdir / account['id'] / calendar_id
        remote = RemoteCalendar(calendar_id, 'Acceptance calendar')
        isolated_account = {'id': account['id'], 'type': 'google', 'calendars': [calendar_id]}
        config_path = folder / 'config.toml'
        write_config({'accounts': [isolated_account], 'default_calendar': account['id'] + '/' + calendar_id}, config_path)
        env = {**os.environ, 'OMAGENDA_CONFIG': str(config_path), 'OMAGENDA_VDIR': str(vdir),
               'OMAGENDA_STATE': str(state), 'PYTHONDONTWRITEBYTECODE': '1'}

        def sync():
            # Avoid test-only conflict notifications on the user's desktop.
            with patch('omagenda.sync._notify_conflict'):
                result = _sync_one_calendar(google, isolated_account, remote, local, state)
            if not result.get('ok'):
                raise RuntimeError('Test-calendar sync failed')
            return result

        def add(title):
            result = subprocess.run([sys.executable, str(ROOT / 'bin/omagenda'), 'add',
                                     title + ' tomorrow at 1pm for 30m', '--json'],
                                    env=env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError('Test CLI add failed')
            return Path(json.loads(result.stdout)['file'])

        def edit(path, title):
            cal = icalendar.Calendar.from_ical(path.read_bytes())
            cal.walk('VEVENT')[0]['SUMMARY'] = title
            path.write_bytes(cal.to_ical())

        sync()
        stage = 'CLI create and Google upload'
        add('Acceptance appointment')
        sync()
        events = api('GET', '/events')['items']
        check('CLI event uploaded exactly once', len(events) == 1 and events[0]['summary'] == 'Acceptance appointment')
        event_id = events[0]['id']
        path = local / (event_id + '.ics')
        event_url = '/events/' + quote(event_id, safe='')

        stage = 'remote time change and metadata preservation'
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
        api('PATCH', event_url, {'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': (start + timedelta(minutes=30)).isoformat()},
            'transparency': 'transparent', 'visibility': 'private',
            'extendedProperties': {'private': {'acceptance': 'preserve-me'}}})
        sync()
        event = icalendar.Calendar.from_ical(path.read_bytes()).walk('VEVENT')[0]
        check('Google time change downloaded', event['dtstart'].dt == start)
        edit(path, 'Locally edited appointment')
        sync()
        saved = api('GET', event_url)
        check('Local edit uploaded with metadata retained',
              saved['summary'] == 'Locally edited appointment' and saved['transparency'] == 'transparent'
              and saved['visibility'] == 'private' and saved['extendedProperties']['private']['acceptance'] == 'preserve-me')

        stage = 'simultaneous edits'
        edit(path, 'Local conflict copy')
        api('PATCH', event_url, {'summary': 'Remote conflict winner'})
        result = sync()
        check('Conflicting local edit preserved', result['conflicts'] == 1
              and b'Local conflict copy' in (local / (event_id + '.conflict.ics')).read_bytes()
              and b'Remote conflict winner' in path.read_bytes())

        stage = 'recurring exceptions'
        series = api('POST', '/events', {'summary': 'Acceptance series',
            'start': {'dateTime': start.isoformat(), 'timeZone': 'UTC'},
            'end': {'dateTime': (start + timedelta(minutes=30)).isoformat(), 'timeZone': 'UTC'},
            'recurrence': ['RRULE:FREQ=DAILY;COUNT=3'], 'reminders': {'useDefault': False, 'overrides': []}})
        sync()
        series_url = '/events/' + quote(series['id'], safe='')
        instances = api('GET', series_url + '/instances')['items']
        moved = instances[1]
        moved_start = start + timedelta(days=1, hours=1)
        api('PATCH', '/events/' + quote(moved['id'], safe=''),
            {'start': {'dateTime': moved_start.isoformat(), 'timeZone': 'UTC'},
             'end': {'dateTime': (moved_start + timedelta(minutes=30)).isoformat(), 'timeZone': 'UTC'}})
        api('DELETE', '/events/' + quote(instances[2]['id'], safe=''))
        sync()
        series_file = local / (series['id'] + '.ics')
        components = icalendar.Calendar.from_ical(series_file.read_bytes()).walk('VEVENT')
        check('Moved and cancelled occurrences downloaded', len(components) == 2
              and bool(components[0].get('EXDATE')) and components[1]['dtstart'].dt == moved_start)

        stage = 'local deletion'
        path.unlink()
        sync()
        remaining = api('GET', '/events').get('items', [])
        check('Local deletion reached Google', not any(item['id'] == event_id for item in remaining))

        stage = 'automatic watcher round trip'
        with (folder / 'watcher.log').open('w') as log:
            watcher = subprocess.Popen([sys.executable, str(ROOT / 'bin/omagenda'), 'watch',
                '--sync-interval', '2', '--poll-seconds', '1'], env=env, stdout=log, stderr=log)
            add('Watcher acceptance appointment')
            found = {}
            def uploaded():
                for item in api('GET', '/events').get('items', []):
                    if item.get('summary') == 'Watcher acceptance appointment':
                        found.update(item)
                        return True
                return False
            until('Watcher uploaded a CLI event without manual sync', uploaded)
            watch_url = '/events/' + quote(found['id'], safe='')
            watch_path = local / (found['id'] + '.ics')
            api('PATCH', watch_url, {'summary': 'Watcher remote change'})
            until('Watcher downloaded a Google edit without manual sync',
                  lambda: watch_path.exists() and b'Watcher remote change' in watch_path.read_bytes())
            watch_path.unlink()
            until('Watcher uploaded a deletion without manual sync',
                  lambda: not any(item['id'] == found['id'] for item in api('GET', '/events').get('items', [])))
        success = True
    except Exception as exc:
        print('FAIL: ' + stage + ' (' + type(exc).__name__ + ')', flush=True)
    finally:
        try:
            try:
                if watcher is not None:
                    watcher.terminate()
                    try:
                        watcher.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        watcher.kill()
                        watcher.wait(timeout=10)
            finally:
                if calendar_id:
                    try:
                        google._api_request('DELETE', google.API_BASE + '/calendars/'
                                            + quote(calendar_id, safe=''), calendar_token)
                        cleaned = True
                        print('PASS: deleted disposable Google calendar', flush=True)
                    except Exception as exc:
                        print('CLEANUP NEEDED: ' + str(receipt) + ' (' + type(exc).__name__ + ')', flush=True)
                else:
                    print('Creation outcome needs review; recovery receipt: ' + str(receipt), flush=True)
        finally:
            authorization.close()
    if success and cleaned:
        import shutil
        shutil.rmtree(folder)
    else:
        print('Recovery folder: ' + str(folder), flush=True)
    print(json.dumps({'passed_checks': len(passed), 'success': success, 'calendar_cleaned_up': cleaned}), flush=True)
    return 0 if success and cleaned else 1


if __name__ == '__main__':
    sys.exit(main())

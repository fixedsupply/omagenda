#!/usr/bin/env python3
"""Opt-in iCloud acceptance using one disposable calendar and isolated storage.

Run in a normal terminal with --run-live. Requires one configured iCloud
account and its desktop keyring password. Never reads personal events or syncs
an installed pair. Private recovery receipts and logs must not be published.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PAIR = 'acceptance'
NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}


def select_account(config: dict) -> dict:
    accounts = [a for a in config.get('accounts', []) if a.get('type') == 'icloud']
    if len(accounts) != 1:
        raise ValueError('Requires exactly one configured icloud account')
    if not accounts[0].get('id') or not accounts[0].get('username'):
        raise ValueError('The icloud account requires an id and username')
    return accounts[0]


def write_receipt(path: Path, name: str, url: str, phase: str) -> None:
    temporary = path.with_suffix('.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        json.dump({'calendar_name': name, 'calendar_url': url, 'phase': phase}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def trusted_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not (parsed.hostname == 'icloud.com' or parsed.hostname.endswith('.icloud.com'))
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError('Expected an HTTPS iCloud DAV URL')
    return url


def generate_scfg(folder: Path, account: dict, calendar_url: str) -> str:
    trusted_url(calendar_url)
    # pimsync.conf(5), COLLECTION SECTIONS: id_a selects the local directory;
    # href_b selects exactly this remote path. No discovery-wide selector is used.
    q = json.dumps
    return f'''status_path {q(str(folder / 'pimsync-state') + '/')}
pair acceptance {{
    storage_a acceptance_local
    storage_b acceptance_remote
    collection {{
        alias disposable
        id_a disposable
        href_b {q(urlsplit(calendar_url).path)}
    }}
    conflict_resolution keep b
}}
storage acceptance_local {{
    type vdir/icalendar
    path {q(str(folder / 'calendars' / PAIR) + '/')}
    fileext ics
}}
storage acceptance_remote {{
    type caldav
    url {q(calendar_url)}
    username {q(account['username'])}
    password {{
        cmd secret-tool lookup service omagenda account {q(account['id'])}
    }}
}}
'''


def cli_command(folder: Path, *args: str) -> list[str]:
    # The production path is a module constant, so redirect it only in this
    # child interpreter before loading the real CLI, including for watch.
    # Disable the unrelated OmaCal probe so it cannot read personal events.
    bootstrap = (
        'import sys,runpy; from pathlib import Path; '
        'sys.path.insert(0,sys.argv.pop(1)); import omagenda.accounts as a; '
        'a.PIMSYNC_CONFIG_DIR=Path(sys.argv.pop(1)); '
        'a.PIMSYNC_STATUS_DIR=Path(sys.argv.pop(1)); '
        'a.SECRETS_DIR=Path(sys.argv.pop(1)); '
        'import omagenda.sync as s; s._merge_omacal=lambda root: None; '
        'script=sys.argv.pop(1); sys.argv[0]=script; runpy.run_path(script,run_name="__main__")'
    )
    return [sys.executable, '-c', bootstrap, str(ROOT), str(folder / 'pimsync'),
            str(folder / 'pimsync-state'), str(folder / 'secrets'), str(ROOT / 'bin/omagenda'), *args]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    parser.add_argument('--json', action='store_true', help='emit only the final JSON report')
    options = parser.parse_args(argv)
    if not options.run_live:
        parser.error('This writes to iCloud; explicitly supply --run-live')

    from omagenda.doctor import read_config
    from omagenda.accounts import write_config
    import icalendar

    folder = None
    watcher = None
    calendar_url = None
    attempted = False
    cleaned = False
    success = False
    passed: list[str] = []
    stage = 'account and keyring preflight'

    def check(label: str, condition: bool = True) -> None:
        if not condition:
            raise AssertionError(label)
        passed.append(label)
        if not options.json:
            print('PASS: ' + label, flush=True)

    try:
        account = select_account(read_config())
        if not shutil.which('pimsync'):
            raise RuntimeError('pimsync is required')
        credential = subprocess.run(['secret-tool', 'lookup', 'service', 'omagenda',
                                     'account', account['id']], capture_output=True, timeout=20)
        if credential.returncode or not credential.stdout.strip():
            raise RuntimeError('Keyring password unavailable')
        password = credential.stdout.rstrip(b'\r\n')
        auth = 'Basic ' + base64.b64encode(account['username'].encode() + b':' + password).decode()

        # Validate each redirect before forwarding the Basic credential.
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                trusted_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(Redirect())

        def request(method: str, url: str, body: bytes | None = None,
                    headers: dict | None = None) -> bytes:
            req = urllib.request.Request(trusted_url(url), method=method, data=body,
                headers={'Authorization': auth, **(headers or {})})
            with opener.open(req, timeout=30) as response:
                return response.read()

        def prop(url: str, tag: str) -> str:
            prefix = 'c' if tag == 'calendar-home-set' else 'd'
            body = (f'<d:propfind xmlns:d="DAV:" xmlns:c="{NS["c"]}"><d:prop>'
                    f'<{prefix}:{tag}/></d:prop></d:propfind>').encode()
            root = ET.fromstring(request('PROPFIND', url, body,
                                         {'Depth': '0', 'Content-Type': 'application/xml'}))
            for props in root.findall('.//d:propstat', NS):
                if ' 200 ' in props.findtext('d:status', '', NS):
                    href = props.findtext(f'd:prop/{prefix}:{tag}/d:href', None, NS)
                    if href:
                        return trusted_url(urljoin(url, href))
            raise RuntimeError('DAV discovery property missing')

        stage = 'CalDAV home discovery'
        principal = prop(account.get('url', 'https://caldav.icloud.com/'), 'current-user-principal')
        home = prop(principal, 'calendar-home-set')
        token = uuid.uuid4().hex
        name = 'Omagenda acceptance ' + token
        calendar_url = trusted_url(home.rstrip('/') + '/' + token + '/')
        folder = Path(tempfile.mkdtemp(prefix='omagenda-icloud-acceptance-'))
        receipt = folder / 'recovery.json'
        stage = 'create disposable calendar'
        write_receipt(receipt, name, calendar_url, 'creation pending')
        attempted = True
        # Never retry MKCALENDAR. The receipt identifies even an uncertain write.
        request('MKCALENDAR', calendar_url,
                (f'<c:mkcalendar xmlns:c="{NS["c"]}" xmlns:d="DAV:"><d:set><d:prop>'
                 f'<d:displayname>{escape(name)}</d:displayname>'
                 '<c:supported-calendar-component-set><c:comp name="VEVENT"/>'
                 '</c:supported-calendar-component-set></d:prop></d:set></c:mkcalendar>').encode(),
                {'Content-Type': 'application/xml'})
        write_receipt(receipt, name, calendar_url, 'created')
        check('created disposable iCloud calendar')
        local = folder / 'calendars' / PAIR / 'disposable'
        local.mkdir(parents=True)
        (local / 'displayname').write_text('Acceptance calendar')
        (folder / 'pimsync').mkdir()
        (folder / 'pimsync-state').mkdir()
        (folder / 'pimsync' / 'omagenda-acceptance.scfg').write_text(generate_scfg(folder, account, calendar_url))
        config = folder / 'config.toml'
        write_config({'accounts': [{'id': PAIR, 'type': 'icloud', 'sync': 'pimsync'}],
                      'default_calendar': PAIR + '/disposable'}, config)
        env = {**os.environ, 'OMAGENDA_CONFIG': str(config),
               'OMAGENDA_VDIR': str(folder / 'calendars'), 'OMAGENDA_STATE': str(folder / 'state'),
               'PYTHONDONTWRITEBYTECODE': '1'}

        def cli(*args: str) -> dict:
            result = subprocess.run(cli_command(folder, *args, '--json'), env=env,
                                    capture_output=True, text=True, timeout=150)
            if result.returncode:
                raise RuntimeError('Isolated CLI command failed')
            return json.loads(result.stdout)

        def sync() -> None:
            result = cli('sync')
            if not result.get(PAIR, {}).get('ok'):
                raise RuntimeError('Disposable pimsync pair failed')

        def events() -> dict[str, bytes]:
            body = (f'<c:calendar-query xmlns:c="{NS["c"]}" xmlns:d="DAV:">'
                    '<d:prop><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
                    '<c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>').encode()
            root = ET.fromstring(request('REPORT', calendar_url, body,
                                {'Depth': '1', 'Content-Type': 'application/xml'}))
            found = {}
            for response in root.findall('d:response', NS):
                href = trusted_url(urljoin(calendar_url, response.findtext('d:href', '', NS)))
                if not href.startswith(calendar_url) or href == calendar_url:
                    raise RuntimeError('REPORT returned a resource outside the disposable calendar')
                data = response.findtext('.//c:calendar-data', None, NS)
                if data is None:
                    raise RuntimeError('REPORT omitted calendar data')
                found[href] = data.encode()
            return found

        def components(data: bytes) -> list:
            return icalendar.Calendar.from_ical(data).walk('VEVENT')

        def local_uid(uid: str) -> list[Path]:
            return [p for p in local.glob('*.ics') if str(components(p.read_bytes())[0]['UID']) == uid]

        def changed(data: bytes, **fields) -> bytes:
            cal = icalendar.Calendar.from_ical(data)
            event = cal.walk('VEVENT')[0]
            for key, value in fields.items():
                event.pop(key, None)
                event.add(key, value)
            return cal.to_ical()

        def put(url: str, data: bytes) -> None:
            if not url.startswith(calendar_url) or url == calendar_url:
                raise RuntimeError('Refusing write outside disposable calendar')
            request('PUT', url, data, {'Content-Type': 'text/calendar'})

        def add(title: str) -> Path:
            return Path(cli('add', title + ' tomorrow at 1pm for 30m')['file'])

        sync()
        stage = 'CLI upload exactly once'
        path = add('Acceptance appointment')
        uid = str(components(path.read_bytes())[0]['UID'])
        sync()
        remote = events()
        check('CLI event uploaded exactly once', len(remote) == 1 and
              str(components(next(iter(remote.values())))[0]['UID']) == uid and
              str(components(next(iter(remote.values())))[0]['SUMMARY']) == 'Acceptance appointment')
        event_url = next(iter(remote))
        path = local_uid(uid)[0]
        stage = 'remote time change'
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
        put(event_url, changed(request('GET', event_url), dtstart=start, dtend=start + timedelta(minutes=30)))
        sync()
        check('iCloud time change downloaded', components(path.read_bytes())[0]['DTSTART'].dt == start)
        stage = 'local title edit'
        path.write_bytes(changed(path.read_bytes(), summary='Locally edited appointment'))
        sync()
        check('Local title edit uploaded', str(components(request('GET', event_url))[0]['SUMMARY']) == 'Locally edited appointment')
        stage = 'simultaneous edits'
        path.write_bytes(changed(path.read_bytes(), summary='Local conflict copy'))
        put(event_url, changed(request('GET', event_url), summary='Remote conflict winner'))
        sync()
        check('Simultaneous edit keeps remote title on both sides',
              str(components(path.read_bytes())[0]['SUMMARY']) == 'Remote conflict winner' and
              str(components(request('GET', event_url))[0]['SUMMARY']) == 'Remote conflict winner')
        stage = 'recurring exceptions'
        series_uid = uuid.uuid4().hex
        cal = icalendar.Calendar()
        cal.add('version', '2.0')
        cal.add('prodid', '-//Omagenda acceptance//EN')
        master = icalendar.Event()
        for key, value in {'uid': series_uid, 'summary': 'Acceptance series', 'dtstamp': datetime.now(timezone.utc),
                           'dtstart': start, 'dtend': start + timedelta(minutes=30),
                           'rrule': {'freq': 'daily', 'count': 3}, 'exdate': start + timedelta(days=2)}.items():
            master.add(key, value)
        cal.add_component(master)
        moved = icalendar.Event()
        moved_start = start + timedelta(days=1, hours=1)
        for key, value in {'uid': series_uid, 'summary': 'Acceptance series', 'dtstamp': datetime.now(timezone.utc),
                           'recurrence-id': start + timedelta(days=1), 'dtstart': moved_start,
                           'dtend': moved_start + timedelta(minutes=30)}.items():
            moved.add(key, value)
        cal.add_component(moved)
        series_url = calendar_url + series_uid + '.ics'
        put(series_url, cal.to_ical())
        sync()
        files = local_uid(series_uid)
        parts = components(files[0].read_bytes()) if len(files) == 1 else []
        masters = [p for p in parts if 'RECURRENCE-ID' not in p]
        overrides = [p for p in parts if 'RECURRENCE-ID' in p]
        check('Moved and cancelled occurrences downloaded in one file', len(parts) == 2 and
              len(masters) == 1 and len(overrides) == 1 and
              masters[0].get('EXDATE') is not None and
              [date.dt for date in masters[0]['EXDATE'].dts] == [start + timedelta(days=2)] and
              overrides[0]['RECURRENCE-ID'].dt == start + timedelta(days=1) and
              overrides[0]['DTSTART'].dt == moved_start)
        stage = 'local deletion'
        path.unlink()
        sync()
        check('Local deletion reached iCloud', event_url not in events())
        # Keep the series while testing deletion, avoiding pimsync's empty-side guard.
        stage = 'remote deletion'
        delete_path = add('Remote deletion appointment')
        delete_uid = str(components(delete_path.read_bytes())[0]['UID'])
        sync()
        delete_url = next(url for url, data in events().items() if str(components(data)[0]['UID']) == delete_uid)
        request('DELETE', delete_url)
        sync()
        check('Remote deletion removed local file', not local_uid(delete_uid))
        stage = 'automatic watcher round trip'

        def until(label: str, predicate) -> None:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if watcher.poll() is not None:
                    raise RuntimeError('Isolated watcher exited')
                if predicate():
                    check(label)
                    return
                time.sleep(2)
            raise TimeoutError(label)

        with (folder / 'watcher.log').open('w') as log:
            watcher = subprocess.Popen(cli_command(folder, 'watch', '--sync-interval', '2', '--poll-seconds', '1'),
                env=env, stdout=log, stderr=log, start_new_session=True)
            watch_path = add('Watcher acceptance appointment')
            watch_uid = str(components(watch_path.read_bytes())[0]['UID'])
            found = {}

            def uploaded() -> bool:
                found.clear()
                found.update({url: data for url, data in events().items()
                              if str(components(data)[0]['UID']) == watch_uid})
                return len(found) == 1

            until('Watcher uploaded a CLI event without manual sync', uploaded)
            watch_url = next(iter(found))
            put(watch_url, changed(request('GET', watch_url), summary='Watcher remote change'))
            until('Watcher downloaded an iCloud edit without manual sync',
                  lambda: len(local_uid(watch_uid)) == 1 and
                  str(components(local_uid(watch_uid)[0].read_bytes())[0]['SUMMARY']) == 'Watcher remote change')
            local_uid(watch_uid)[0].unlink()
            until('Watcher uploaded a deletion without manual sync', lambda: watch_url not in events())
        if 'sync failed' in (folder / 'watcher.log').read_text():
            raise RuntimeError('Isolated watcher reported a sync error')
        success = True
    except Exception as exc:
        print('FAIL: ' + stage + ' (' + type(exc).__name__ + ')', file=sys.stderr, flush=True)
    finally:
        if watcher is not None:
            # Stop the process group, including any in-flight pimsync child,
            # before deleting the collection so no sync can recreate it.
            try:
                os.killpg(watcher.pid, signal.SIGTERM)
                watcher.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                os.killpg(watcher.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            watcher.wait(timeout=10)
        if attempted:
            try:
                request('DELETE', calendar_url)
                cleaned = True
                check('deleted disposable iCloud calendar')
            except Exception as exc:
                print('CLEANUP NEEDED: ' + str(receipt) + ' (' + type(exc).__name__ + ')', file=sys.stderr, flush=True)
        if cleaned:
            shutil.rmtree(folder)
    print(json.dumps({'passed_checks': len(passed), 'checks': passed, 'success': success and cleaned,
                      'failed_stage': ('calendar cleanup' if success and not cleaned else
                                       None if success else stage), 'calendar_cleaned_up': cleaned,
                      'recovery_receipt': str(receipt) if attempted and not cleaned else None}), flush=True)
    return 0 if success and cleaned else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Opt-in iCloud acceptance using one disposable calendar and isolated storage.

Run in a normal terminal with --run-live. Requires one configured iCloud
account and its desktop keyring password. Never reads personal events or syncs
an installed pair. Pauses real watcher sync only through the installed CLI.
Private recovery receipts and logs must not be published.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import shlex
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


def replace_local_event(path: Path, content: bytes) -> None:
    """Replace the inode so pimsync detects edits made within the same second."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.acceptance-', suffix='.ics.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def trusted_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not (parsed.hostname == 'icloud.com' or parsed.hostname.endswith('.icloud.com'))
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError('Expected an HTTPS iCloud DAV URL')
    return url


def parse_events_report(body: bytes, calendar_url: str) -> dict[str, bytes]:
    root = ET.fromstring(body)
    found = {}
    for response in root.findall('d:response', NS):
        href = trusted_url(urljoin(calendar_url, response.findtext('d:href', '', NS)))
        # iCloud includes the collection itself without calendar data in this REPORT.
        if href.rstrip('/') == calendar_url.rstrip('/'):
            continue
        if not href.startswith(calendar_url.rstrip('/') + '/'):
            raise RuntimeError('REPORT returned a resource outside the disposable calendar')
        data = response.findtext('.//c:calendar-data', None, NS)
        if data is None:
            raise RuntimeError('REPORT omitted calendar data')
        found[href] = data.encode()
    return found


def failure_line(stage: str, exc: Exception) -> str:
    detail = type(exc).__name__
    # Library exception subclasses can include private URLs in their messages.
    if type(exc) in (RuntimeError, AssertionError, TimeoutError, ValueError):
        detail += ': ' + str(exc)
    return 'FAIL: ' + stage + ' (' + detail + ')'


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


def installed_cli() -> Path:
    return Path.home() / '.config/omarchy/plugins/fixedsupply.omagenda/bin/omagenda'


def installed_sync(*args: str) -> dict:
    # Inherit the PM's environment, never the disposable provider environment.
    result = subprocess.run([str(installed_cli()), 'sync', *args, '--json'],
                            capture_output=True, text=True, timeout=260)
    if result.returncode:
        raise RuntimeError('Installed sync command failed')
    return json.loads(result.stdout)


def require_pause_support() -> None:
    try:
        result = subprocess.run([str(installed_cli()), 'sync', '--help'],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 0 and '--pause' in result.stdout:
            return
    except (OSError, subprocess.TimeoutExpired):
        pass
    print('This branch must be merged and installed first: the installed CLI must support sync --pause.',
          file=sys.stderr)
    raise RuntimeError('Installed pause support missing')


def watcher_running(state: Path) -> bool:
    # Opening read-only avoids creating or changing any real state file.
    try:
        handle = (state / 'watch.lock').open('r')
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def confirm_watcher_pause(state: Path, until: str) -> None:
    if not watcher_running(state):
        return
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if json.loads((state / 'agenda.json').read_text()).get('syncPausedUntil') == until:
                return
        except (OSError, ValueError, UnicodeError, AttributeError):
            pass
        time.sleep(1)
    print('Running watcher did not confirm the pause within 90 seconds; update the watcher before retrying.',
          file=sys.stderr)
    raise TimeoutError('Watcher pause confirmation')


def real_vdir_orphans(config: dict, vdir: Path, collection_id: str) -> list[Path]:
    return [vdir / account['id'] / collection_id for account in config.get('accounts', [])
            if account.get('type') in ('icloud', 'caldav')
            and (vdir / account['id'] / collection_id).is_dir()]


def stop_watcher(watcher) -> None:
    # Stop the whole group so a surviving pimsync child cannot recreate the calendar.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    parser.add_argument('--json', action='store_true', help='emit only the final JSON report')
    options = parser.parse_args(argv)
    if not options.run_live:
        parser.error('This writes to iCloud; explicitly supply --run-live')

    from omagenda.doctor import read_config
    from omagenda.accounts import write_config
    from omagenda.index import resolve_state_dir
    from omagenda.vdir import resolve_vdir_root
    import icalendar

    folder = None
    watcher = None
    calendar_url = None
    attempted = False
    cleaned = False
    success = False
    passed: list[str] = []
    stage = 'account and keyring preflight'
    pause_attempted = False
    real_sync_paused = False
    real_sync_resumed = False
    orphan = None
    cleanup_failed = None
    failed_stage = None

    def check(label: str, condition: bool = True) -> None:
        if not condition:
            raise AssertionError(label)
        passed.append(label)
        if not options.json:
            print('PASS: ' + label, flush=True)

    try:
        real_config = read_config()
        account = select_account(real_config)
        real_state = resolve_state_dir()
        real_vdir = resolve_vdir_root()
        stage = 'installed pause support preflight'
        require_pause_support()
        stage = 'account and keyring preflight'
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

        stage = 'pause real watcher sync'
        pause_attempted = True
        until = installed_sync('--pause', '30m').get('pausedUntil')
        if not isinstance(until, str) or datetime.fromisoformat(until).utcoffset() is None:
            raise RuntimeError('Installed CLI did not return a pause timestamp')
        real_sync_paused = True
        stage = 'watcher pause confirmation'
        confirm_watcher_pause(real_state, until)
        check('real watcher sync paused')

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
            return parse_events_report(request('REPORT', calendar_url, body,
                                       {'Depth': '1', 'Content-Type': 'application/xml'}), calendar_url)

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
        replace_local_event(path, changed(path.read_bytes(), summary='Locally edited appointment'))
        sync()
        check('Local title edit uploaded', str(components(request('GET', event_url))[0]['SUMMARY']) == 'Locally edited appointment')
        stage = 'simultaneous edits'
        replace_local_event(path, changed(path.read_bytes(), summary='Local conflict copy'))
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
        failed_stage = stage
        print(failure_line(stage, exc), file=sys.stderr, flush=True)
    finally:
        try:
            if watcher is not None:
                try:
                    stop_watcher(watcher)
                except Exception:
                    cleanup_failed = 'isolated watcher cleanup'
                    print('FAIL: isolated watcher cleanup', file=sys.stderr)
            if attempted:
                try:
                    request('DELETE', calendar_url)
                    cleaned = True
                    check('deleted disposable iCloud calendar')
                except Exception as exc:
                    cleanup_failed = cleanup_failed or 'calendar cleanup'
                    print('CLEANUP NEEDED: ' + str(receipt) + ' (' + type(exc).__name__ + ')',
                          file=sys.stderr, flush=True)
                try:
                    orphans = real_vdir_orphans(real_config, real_vdir, token)
                    orphan = str(orphans[0]) if orphans else None
                    for path in orphans:
                        print(f'ORPHAN: {path}; remove with: rm -rf -- {shlex.quote(str(path))}',
                              file=sys.stderr, flush=True)
                    check('no disposable calendar in real vdir', not orphans)
                except Exception:
                    cleanup_failed = cleanup_failed or 'real vdir orphan check'
        finally:
            if pause_attempted:
                try:
                    result = installed_sync('--resume')
                    if result != {'pausedUntil': None}:
                        raise RuntimeError('Installed CLI did not confirm resume')
                    real_sync_resumed = True
                    check('real watcher sync resumed')
                except Exception:
                    cleanup_failed = cleanup_failed or 'real sync resume'
                    print('RESUME NEEDED: ' + shlex.quote(str(installed_cli())) + ' sync --resume',
                          file=sys.stderr, flush=True)
        success = success and cleaned and not cleanup_failed and real_sync_resumed
        if folder is not None:
            if success:
                try:
                    shutil.rmtree(folder)
                except OSError:
                    success = False
                    cleanup_failed = 'temporary folder cleanup'
            if not success:
                print('Temporary folder retained: ' + str(folder), file=sys.stderr, flush=True)
    print(json.dumps({'passed_checks': len(passed), 'checks': passed, 'success': success,
                      'failed_stage': None if success else failed_stage or cleanup_failed,
                      'cleanup_failed_stage': cleanup_failed,
                      'calendar_cleaned_up': cleaned,
                      'real_sync_paused': real_sync_paused, 'real_sync_resumed': real_sync_resumed,
                      'real_vdir_orphan': orphan,
                      'temporary_folder': str(folder) if folder is not None and not success else None,
                      'recovery_receipt': str(receipt) if attempted and not success else None}), flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

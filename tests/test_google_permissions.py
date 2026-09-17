"""Google consent and acceptance cleanup, with every external call mocked."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from omagenda.bridges import google, PullChange, PullResult, RemoteRef
from omagenda import sync

ACCOUNT = {'id': 'demo', 'type': 'google', 'email': 'you@example.com', 'calendars': ['demo']}


class PermissionTest(unittest.TestCase):
    def test_product_url_scopes(self):
        params = parse_qs(urlparse(google.build_auth_url('http://127.0.0.1:1234/', 'challenge')).query)
        self.assertEqual(params['scope'][0].split(), [
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.calendarlist.readonly'])

    def test_partial_or_absent_grants_store_nothing(self):
        for granted in (*google.SCOPES, ''):
            with self.subTest(granted=granted), patch.object(google, 'exchange_authorization',
                    return_value={'scope': granted, 'refresh_token': 'secret'}), \
                    patch.object(google, 'store_secret') as store:
                with self.assertRaises(RuntimeError) as error:
                    google.authorize(ACCOUNT)
                for missing in set(google.SCOPES) - {granted}:
                    self.assertIn(missing, str(error.exception))
                self.assertIn('omagenda account add google --id demo', str(error.exception))
                self.assertIn('both boxes ticked', str(error.exception))
                store.assert_not_called()

    def test_complete_and_legacy_grants(self):
        for scope in (' '.join(google.SCOPES), 'https://www.googleapis.com/auth/calendar'):
            with self.subTest(scope=scope), patch.object(google, 'exchange_authorization',
                    return_value={'scope': scope, 'refresh_token': 'secret'}), \
                    patch.object(google, 'store_secret') as store:
                google.authorize(ACCOUNT)
                store.assert_called_once_with('demo-refresh-token', 'secret')

    def test_scope_errors_record_account_and_remedy(self):
        for body in ({'error': {'errors': [{'reason': 'insufficientPermissions'}]}},
                     {'error': {'details': [{'reason': 'ACCESS_TOKEN_SCOPE_INSUFFICIENT'}]}}):
            for refreshed in (False, True):
                errors = ([google.ApiError(401, '')] if refreshed else []) + [google.ApiError(403, json.dumps(body))]
                with self.subTest(body=body, refreshed=refreshed), tempfile.TemporaryDirectory() as tmp, \
                        patch.object(google, '_get_access_token', return_value='normal-token'), \
                        patch.object(google, '_api_request', side_effect=errors):
                    result = sync._sync_bridge(ACCOUNT, Path(tmp), state_dir=Path(tmp))
                    sync._record_sync({'demo': result}, Path(tmp))
                    record = sync.read_last_sync(Path(tmp))
                    self.assertEqual(record['needsReauth'], ['demo'])
                    self.assertEqual(record['remedy'], 'Reconnect with: omagenda account add google --id demo')

    def test_event_write_scope_errors_survive_per_event_error_handling(self):
        from tests.test_sync_bridge_orchestration import FakeBridge, CALENDAR, _ics
        for operation in ('create', 'update', 'delete'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                local = root / 'acct' / CALENDAR.id
                bridge = FakeBridge(pull_results=[PullResult(changed=[
                    PullChange(uid='demo', ics_bytes=_ics('demo'), ref=RemoteRef(remote_id='demo', etag='1'))])])
                sync._sync_one_calendar(bridge, ACCOUNT, CALENDAR, local, root / 'state')
                if operation == 'create':
                    (local / 'new.ics').write_bytes(_ics('new'))
                elif operation == 'update':
                    (local / 'demo.ics').write_bytes(_ics('demo', 'Changed'))
                else:
                    (local / 'demo.ics').unlink()
                def refused(*args):
                    return google._authed_request(ACCOUNT, 'POST', google.API_BASE + '/calendars/demo/events')
                with patch.object(bridge, 'push_' + operation, side_effect=refused), \
                        patch.object(google, '_get_access_token', return_value='normal-token'), \
                        patch.object(google, '_api_request', side_effect=google.ApiError(403,
                            '{"error":{"errors":[{"reason":"insufficientPermissions"}]}}')):
                    result = sync._sync_one_calendar(bridge, ACCOUNT, CALENDAR, local, root / 'state')
                sync._record_sync({'demo': result}, root / 'state')
                record = sync.read_last_sync(root / 'state')
                self.assertEqual(record['needsReauth'], ['demo'])
                self.assertIn('omagenda account add google --id demo', record['remedy'])

    def test_other_403_is_not_reauth(self):
        with patch.object(google, '_get_access_token', return_value='normal-token'), \
                patch.object(google, '_api_request', side_effect=google.ApiError(403, '{"error":{"reason":"forbidden"}}')):
            with self.assertRaises(google.ApiError):
                google.list_calendars(ACCOUNT)


class AcceptancePermissionTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('google_acceptance',
            Path(__file__).resolve().parents[1] / 'tools/google-acceptance.py')
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)

    def test_one_off_flow_never_stores_and_always_revokes(self):
        for failure in (None, RuntimeError, KeyboardInterrupt):
            with self.subTest(failure=failure), patch.object(google.http.server, 'HTTPServer') as server, \
                    patch.object(google, '_open_browser') as browser, \
                    patch.object(google.urllib.request, 'urlopen') as urlopen, \
                    patch.object(google, 'store_secret') as store, \
                    patch('omagenda.accounts.write_config') as config:
                server.return_value.server_address = ('127.0.0.1', 1234)
                def callback():
                    server.return_value.oauth_code = 'code'
                server.return_value.handle_request.side_effect = callback
                urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({
                    'access_token': 'one-off-secret', 'scope': self.script.APP_CREATED_SCOPES[0]}).encode()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    try:
                        with self.script.calendar_authorization(ACCOUNT) as token:
                            self.assertEqual(token, 'one-off-secret')
                            if failure:
                                raise failure()
                    except (RuntimeError, KeyboardInterrupt):
                        if failure is None:
                            raise
                params = parse_qs(urlparse(browser.call_args.args[0]).query)
                self.assertEqual(params['scope'], ['https://www.googleapis.com/auth/calendar.app.created'])
                self.assertEqual(params['access_type'], ['online'])
                self.assertEqual(urlopen.call_count, 2)
                revoke = urlopen.call_args.args[0]
                self.assertEqual(revoke.full_url, 'https://oauth2.googleapis.com/revoke')
                self.assertEqual(parse_qs(revoke.data.decode()), {'token': ['one-off-secret']})
                self.assertNotIn('one-off-secret', output.getvalue())
                store.assert_not_called()
                config.assert_not_called()
                server.return_value.server_close.assert_called_once()

    def test_refused_one_off_scope_is_revoked(self):
        with patch.object(google, 'exchange_authorization', return_value={
                'access_token': 'one-off-secret', 'scope': ''}), \
                patch.object(google.urllib.request, 'urlopen') as revoke:
            with self.assertRaisesRegex(RuntimeError, 'permission was not granted'):
                with self.script.calendar_authorization(ACCOUNT):
                    self.fail('Partial consent must not start acceptance')
            self.assertEqual(revoke.call_args.args[0].full_url, 'https://oauth2.googleapis.com/revoke')

    def test_main_failure_and_interruption_revoke_after_calendar_delete(self):
        for failure in (RuntimeError, KeyboardInterrupt):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch('sys.argv', ['google-acceptance.py', '--run-live']), \
                    patch('omagenda.doctor.read_config', return_value={'accounts': [ACCOUNT]}), \
                    patch.object(self.script.tempfile, 'mkdtemp', return_value=tmp), \
                    patch.object(google, 'exchange_authorization', return_value={
                        'access_token': 'one-off-secret', 'scope': self.script.APP_CREATED_SCOPES[0]}), \
                    patch.object(google.urllib.request, 'urlopen') as urlopen, \
                    patch.object(google, '_api_request') as delete, \
                    patch('omagenda.sync._sync_one_calendar', side_effect=failure), \
                    patch.object(google, 'store_secret') as store:
                urlopen.return_value.__enter__.return_value.read.return_value = b'{"id":"disposable"}'
                order = []
                delete.side_effect = lambda *a, **kw: order.append('delete')
                def opened(request, **kwargs):
                    if request.full_url.endswith('/revoke'):
                        order.append('revoke')
                    return MagicMock(__enter__=MagicMock(return_value=io.BytesIO(b'{"id":"disposable"}')))
                urlopen.side_effect = opened
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    try:
                        self.assertEqual(self.script.main(), 1)
                    except KeyboardInterrupt:
                        self.assertIs(failure, KeyboardInterrupt)
                self.assertEqual(order, ['delete', 'revoke'])
                self.assertEqual(delete.call_args.args[2], 'one-off-secret')
                for path in Path(tmp).rglob('*'):
                    if path.is_file():
                        self.assertNotIn(b'one-off-secret', path.read_bytes())
                self.assertNotIn('one-off-secret', output.getvalue())
                store.assert_not_called()

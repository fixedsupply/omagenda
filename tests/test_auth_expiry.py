"""An expired Google sign-in, from the token endpoint to the panel.

A Google OAuth client left in Testing mode expires its refresh tokens
every seven days, so this is a routine event rather than an exotic one.
Its raw form is "couldn't list calendars: HTTP Error 400: Bad Request",
which tells nobody what happened or what to do -- and because sync failed
silently in the background, the first sign would have been events quietly
not reaching the phone in the user's pocket.
"""
import io
import json
import tempfile
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

from omagenda.bridges import AuthExpiredError, google
from omagenda.doctor import _check_sign_in
from omagenda.sync import read_last_sync, sync_all
from tests.test_sync import WithVdir

ACCOUNT = {"id": "google", "type": "google"}


def _token_response(code: int, error: str, description: str = ""):
    body = json.dumps({"error": error, "error_description": description}).encode()
    return urllib.error.HTTPError("https://oauth2.googleapis.com/token", code,
                                  "Bad Request", {}, io.BytesIO(body))


class TokenClassificationTest(unittest.TestCase):
    def setUp(self):
        google.forget_access_token("google")
        self.addCleanup(google.forget_access_token, "google")

    def test_invalid_grant_is_an_expired_sign_in(self):
        with unittest.mock.patch.object(google.urllib.request, "urlopen",
                                        side_effect=_token_response(400, "invalid_grant", "Token expired")), \
                unittest.mock.patch.object(google, "get_secret", return_value="stored"):
            with self.assertRaises(AuthExpiredError) as caught:
                google._get_access_token(ACCOUNT)
        self.assertIn("omagenda account add google", caught.exception.remedy)
        self.assertEqual(caught.exception.account_id, "google")

    def test_a_server_error_is_not_mistaken_for_an_expired_sign_in(self):
        with unittest.mock.patch.object(google.urllib.request, "urlopen",
                                        side_effect=_token_response(500, "backend_error")), \
                unittest.mock.patch.object(google, "get_secret", return_value="stored"):
            with self.assertRaises(Exception) as caught:
                google._get_access_token(ACCOUNT)
        self.assertNotIsInstance(caught.exception, AuthExpiredError)

    def test_missing_credentials_still_says_to_add_the_account(self):
        with unittest.mock.patch.object(google, "get_secret", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                google._get_access_token(ACCOUNT)
        self.assertIn("account add google", str(caught.exception))


class SyncReportsItTest(unittest.TestCase):
    def setUp(self):
        google.forget_access_token("google")
        self.addCleanup(google.forget_access_token, "google")

    def _sync(self, state):
        with unittest.mock.patch.object(google.urllib.request, "urlopen",
                                        side_effect=_token_response(400, "invalid_grant", "Token expired")), \
                unittest.mock.patch.object(google, "get_secret", return_value="stored"), \
                WithVdir():
            return sync_all({"accounts": [ACCOUNT]}, state_dir=state)

    def test_the_account_result_carries_the_remedy(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._sync(Path(tmp))["google"]
        self.assertFalse(result["ok"])
        self.assertTrue(result["needsReauth"])
        self.assertIn("expired", result["summary"])
        self.assertIn("omagenda account add google --id google", result["detail"])
        self.assertNotIn("HTTP Error", result["detail"])

    def test_the_record_outlives_the_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._sync(Path(tmp))
            record = read_last_sync(Path(tmp))
        self.assertEqual(record["needsReauth"], ["google"])
        self.assertIn("account add google", record["remedy"])

    def test_doctor_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._sync(Path(tmp))
            import os

            old = os.environ.get("OMAGENDA_STATE")
            os.environ["OMAGENDA_STATE"] = tmp
            try:
                check = _check_sign_in()
            finally:
                if old is None:
                    os.environ.pop("OMAGENDA_STATE", None)
                else:
                    os.environ["OMAGENDA_STATE"] = old
        self.assertFalse(check["ok"])
        self.assertIn("sign-in expired", check["detail"])
        self.assertIn("account add google", check["detail"])


class RetryOnStaleTokenTest(unittest.TestCase):
    """The token is cached, so a grant revoked mid-sync arrives as a 401
    on a request rather than as a failure to fetch a token."""

    def setUp(self):
        google.forget_access_token("google")
        self.addCleanup(google.forget_access_token, "google")

    def test_a_401_is_retried_once_with_a_fresh_token(self):
        calls = []

        def api(method, url, token, body=None, extra_headers=None):
            calls.append(token)
            if len(calls) == 1:
                raise google.ApiError(401, "stale")
            return 200, {"items": []}, {}

        with unittest.mock.patch.object(google, "_api_request", side_effect=api), \
                unittest.mock.patch.object(google, "_fetch_access_token",
                                           side_effect=[("first", 3600), ("second", 3600)]):
            status, payload, _ = google._authed_request(ACCOUNT, "GET", "https://example/api")

        self.assertEqual(status, 200)
        self.assertEqual(calls, ["first", "second"], "the retry must use a new token")

    def test_a_non_401_error_is_not_retried(self):
        calls = []

        def api(method, url, token, body=None, extra_headers=None):
            calls.append(token)
            raise google.ApiError(500, "server on fire")

        with unittest.mock.patch.object(google, "_api_request", side_effect=api), \
                unittest.mock.patch.object(google, "_fetch_access_token", return_value=("t", 3600)):
            with self.assertRaises(google.ApiError):
                google._authed_request(ACCOUNT, "GET", "https://example/api")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

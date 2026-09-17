"""Google bridge tests against recorded JSON shapes -- no real network.
See AGENTS.md's Phase 1b brief: pull mapping both directions, recurring
instances, cancelled events, a 412 conflict, a 410 full-resync."""
import datetime
import json
import unittest
import urllib.error
from unittest import mock

import icalendar

from omagenda.bridges import ConflictError, RemoteCalendar, RemoteRef
from omagenda.bridges import google
from omagenda.bridges.google import (
    ApiError,
    _local_event_to_google_body,
    _map_events_page,
    push_create,
    push_delete,
    push_update,
    pull,
)


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.headers = {}

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _HTTPErrorWithBody(urllib.error.HTTPError):
    def __init__(self, status, payload):
        import io
        super().__init__("https://example", status, "err", {}, io.BytesIO(payload))

    def read(self):
        return self.fp.read()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------
# Mapping: Google JSON -> VEVENT (pull direction)
# ---------------------------------------------------------------------
STANDALONE_EVENT = {
    "id": "abc123",
    "status": "confirmed",
    "summary": "Lunch with Sarah",
    "start": {"dateTime": "2026-09-08T13:00:00-06:00", "timeZone": "America/Edmonton"},
    "end": {"dateTime": "2026-09-08T14:00:00-06:00", "timeZone": "America/Edmonton"},
    "location": "Cafe Linnea",
    "hangoutLink": "https://meet.google.com/abc-defg-hij",
    "attendees": [{"email": "sarah@example.com"}],
    "htmlLink": "https://calendar.google.com/event?eid=abc",
}

ALL_DAY_EVENT = {
    "id": "holiday1",
    "status": "confirmed",
    "summary": "Thanksgiving",
    "start": {"date": "2026-10-12"},
    "end": {"date": "2026-10-13"},
}

RECURRING_MASTER = {
    "id": "standup-master",
    "status": "confirmed",
    "summary": "Standup",
    "start": {"dateTime": "2026-09-07T09:00:00-06:00", "timeZone": "America/Edmonton"},
    "end": {"dateTime": "2026-09-07T09:15:00-06:00", "timeZone": "America/Edmonton"},
    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"],
}

MODIFIED_INSTANCE = {
    "id": "standup-master_20260909T150000Z",
    "status": "confirmed",
    "summary": "Standup (moved)",
    "recurringEventId": "standup-master",
    "originalStartTime": {"dateTime": "2026-09-09T09:00:00-06:00", "timeZone": "America/Edmonton"},
    "start": {"dateTime": "2026-09-09T10:00:00-06:00", "timeZone": "America/Edmonton"},
    "end": {"dateTime": "2026-09-09T10:15:00-06:00", "timeZone": "America/Edmonton"},
}

CANCELLED_INSTANCE = {
    "id": "standup-master_20260910T150000Z",
    "status": "cancelled",
    "recurringEventId": "standup-master",
    "originalStartTime": {"dateTime": "2026-09-10T09:00:00-06:00", "timeZone": "America/Edmonton"},
}

CANCELLED_STANDALONE = {"id": "gone123", "status": "cancelled"}


class MapEventsPageTest(unittest.TestCase):
    def test_standalone_event_maps_summary_time_location_conference_attendees(self):
        files, deleted = _map_events_page([STANDALONE_EVENT])
        self.assertEqual(deleted, [])
        text = "\r\n".join(files["abc123"])
        self.assertIn("UID:abc123", text)
        self.assertIn("SUMMARY:Lunch with Sarah", text)
        self.assertIn("DTSTART;TZID=America/Edmonton:20260908T130000", text)
        self.assertIn("DTEND;TZID=America/Edmonton:20260908T140000", text)
        self.assertIn("LOCATION:Cafe Linnea", text)
        self.assertIn("X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij", text)
        self.assertIn("X-OMAGENDA-WEB-URL:https://calendar.google.com/event?eid=abc", text)
        self.assertIn("ATTENDEE:mailto:sarah@example.com", text)

    def test_all_day_event_uses_value_date(self):
        files, _ = _map_events_page([ALL_DAY_EVENT])
        text = "\r\n".join(files["holiday1"])
        self.assertIn("DTSTART;VALUE=DATE:20261012", text)
        self.assertIn("DTEND;VALUE=DATE:20261013", text)

    def test_cancelled_standalone_event_is_deleted_not_a_file(self):
        files, deleted = _map_events_page([CANCELLED_STANDALONE])
        self.assertEqual(files, {})
        self.assertEqual(deleted, ["gone123"])

    def test_recurring_master_carries_its_own_rrule(self):
        files, _ = _map_events_page([RECURRING_MASTER])
        text = "\r\n".join(files["standup-master"])
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", text)
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_modified_instance_becomes_a_recurrence_id_override_in_the_same_file(self):
        files, deleted = _map_events_page([RECURRING_MASTER, MODIFIED_INSTANCE])
        self.assertEqual(deleted, [])
        self.assertIn("standup-master", files)
        self.assertNotIn(MODIFIED_INSTANCE["id"], files)  # folded into the master's file, not its own
        text = "\r\n".join(files["standup-master"])
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)  # master + one override
        self.assertEqual(text.count("UID:standup-master"), 2)  # override shares the master's UID
        self.assertIn("RECURRENCE-ID;TZID=America/Edmonton:20260909T090000", text)
        self.assertIn("SUMMARY:Standup (moved)", text)
        self.assertIn("DTSTART;TZID=America/Edmonton:20260909T100000", text)

    def test_cancelled_instance_becomes_an_exdate_on_the_master_not_a_deletion(self):
        files, deleted = _map_events_page([RECURRING_MASTER, CANCELLED_INSTANCE])
        self.assertEqual(deleted, [])  # the series continues; only one occurrence is gone
        text = "\r\n".join(files["standup-master"])
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)  # no separate file for a cancelled instance
        self.assertIn("EXDATE;TZID=America/Edmonton:20260910T090000", text)

    def test_master_with_both_a_modified_and_a_cancelled_instance(self):
        files, deleted = _map_events_page([RECURRING_MASTER, MODIFIED_INSTANCE, CANCELLED_INSTANCE])
        self.assertEqual(deleted, [])
        text = "\r\n".join(files["standup-master"])
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)
        self.assertIn("EXDATE;TZID=America/Edmonton:20260910T090000", text)
        self.assertIn("RECURRENCE-ID;TZID=America/Edmonton:20260909T090000", text)

    def test_produced_file_parses_as_valid_icalendar(self):
        from omagenda.bridges.google import _wrap_calendar

        files, _ = _map_events_page([RECURRING_MASTER, MODIFIED_INSTANCE, CANCELLED_INSTANCE])
        cal = icalendar.Calendar.from_ical(_wrap_calendar(files["standup-master"]))
        self.assertEqual(len(list(cal.walk("VEVENT"))), 2)


# ---------------------------------------------------------------------
# Mapping: VEVENT -> Google JSON (push direction)
# ---------------------------------------------------------------------
class LocalEventToGoogleBodyTest(unittest.TestCase):
    def _event(self, ics_body: str):
        text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + ics_body + "\r\nEND:VCALENDAR\r\n"
        return next(iter(icalendar.Calendar.from_ical(text).walk("VEVENT")))

    def test_timed_event_with_location_and_alarm(self):
        event = self._event(
            "BEGIN:VEVENT\r\nUID:x@omagenda\r\nSUMMARY:Lunch\r\n"
            "DTSTART;TZID=America/Edmonton:20260908T130000\r\n"
            "DTEND;TZID=America/Edmonton:20260908T140000\r\n"
            "LOCATION:Cafe Linnea\r\n"
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Lunch\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n"
            "END:VEVENT"
        )
        body = _local_event_to_google_body(event)
        self.assertEqual(body["summary"], "Lunch")
        self.assertEqual(body["start"], {"dateTime": "2026-09-08T13:00:00-06:00", "timeZone": "America/Edmonton"})
        self.assertEqual(body["end"], {"dateTime": "2026-09-08T14:00:00-06:00", "timeZone": "America/Edmonton"})
        self.assertEqual(body["location"], "Cafe Linnea")
        self.assertEqual(body["reminders"], {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]})

    def test_all_day_event(self):
        event = self._event(
            "BEGIN:VEVENT\r\nUID:x@omagenda\r\nSUMMARY:Holiday\r\n"
            "DTSTART;VALUE=DATE:20261012\r\nDTEND;VALUE=DATE:20261013\r\nEND:VEVENT"
        )
        body = _local_event_to_google_body(event)
        self.assertEqual(body["start"], {"date": "2026-10-12"})
        self.assertEqual(body["end"], {"date": "2026-10-13"})

    def test_recurring_event_round_trips_rrule_verbatim(self):
        event = self._event(
            "BEGIN:VEVENT\r\nUID:x@omagenda\r\nSUMMARY:Standup\r\n"
            "DTSTART;TZID=America/Edmonton:20260907T090000\r\nDTEND;TZID=America/Edmonton:20260907T091500\r\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\nEND:VEVENT"
        )
        body = _local_event_to_google_body(event)
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"])

    def test_web_url_is_pull_only(self):
        event = self._event("BEGIN:VEVENT\r\nUID:x@omagenda\r\nSUMMARY:Lunch\r\nDTSTART:20260908T130000\r\nDTEND:20260908T140000\r\nX-OMAGENDA-WEB-URL:https://example.com/event\r\nEND:VEVENT")
        self.assertNotIn("htmlLink", _local_event_to_google_body(event))


# ---------------------------------------------------------------------
# pull(): syncToken propagation and the 410 -> full resync path
# ---------------------------------------------------------------------
class PullTest(unittest.TestCase):
    def setUp(self):
        self.account = {"id": "google-calvin", "type": "google"}
        self.calendar = RemoteCalendar(id="primary", name="Calvin")
        patcher = mock.patch("omagenda.bridges.google._get_access_token", return_value="fake-token")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_incremental_pull_records_the_next_sync_token(self):
        response = _FakeResponse({"items": [STANDALONE_EVENT], "nextSyncToken": "tok-2"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = pull(self.account, self.calendar, cursor="tok-1")
        self.assertFalse(result.full_resync)
        self.assertEqual(result.next_cursor, "tok-2")
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].uid, "abc123")

    def test_410_triggers_a_full_pull_and_reports_full_resync(self):
        calls = []

        def fake_urlopen(request, timeout=15):
            calls.append(request.full_url)
            if "syncToken=tok-stale" in request.full_url:
                raise _HTTPErrorWithBody(410, json.dumps({"error": "gone"}).encode())
            return _FakeResponse({"items": [ALL_DAY_EVENT], "nextSyncToken": "tok-fresh"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = pull(self.account, self.calendar, cursor="tok-stale")

        self.assertTrue(result.full_resync)
        self.assertEqual(result.next_cursor, "tok-fresh")
        self.assertEqual(len(result.changed), 1)
        self.assertTrue(any("syncToken=tok-stale" in c for c in calls))
        self.assertTrue(any("syncToken" not in c for c in calls))  # the retried, full-pull request

    def test_non_410_http_error_propagates(self):
        # 500 retries with backoff before giving up -- mock the sleep so
        # this test doesn't actually take ~7 seconds.
        with mock.patch("urllib.request.urlopen", side_effect=_HTTPErrorWithBody(500, b"{}")), \
             mock.patch("time.sleep"):
            with self.assertRaises(ApiError):
                pull(self.account, self.calendar, cursor=None)


# ---------------------------------------------------------------------
# push_update(): 412 -> ConflictError
# ---------------------------------------------------------------------
class PushTest(unittest.TestCase):
    def setUp(self):
        self.account = {"id": "google-calvin", "type": "google"}
        self.calendar = RemoteCalendar(id="primary", name="Calvin")
        patcher = mock.patch("omagenda.bridges.google._get_access_token", return_value="fake-token")
        self.addCleanup(patcher.stop)
        patcher.start()

    def _ics(self, uid="x@omagenda"):
        return (
            f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:Lunch\r\n"
            "DTSTART;TZID=America/Edmonton:20260908T130000\r\nDTEND;TZID=America/Edmonton:20260908T140000\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()

    def test_push_create_returns_remote_ref(self):
        response = _FakeResponse({"id": "new-remote-id", "etag": '"etag-1"'})
        with mock.patch("urllib.request.urlopen", return_value=response):
            ref = push_create(self.account, self.calendar, self._ics())
        self.assertEqual(ref.remote_id, "new-remote-id")
        self.assertEqual(ref.etag, '"etag-1"')

    def test_push_update_conflict_raises_conflict_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=_HTTPErrorWithBody(412, b"{}")):
            with self.assertRaises(ConflictError):
                push_update(self.account, self.calendar, self._ics(), RemoteRef(remote_id="r1", etag='"stale"'))

    def test_push_update_sends_if_match_header(self):
        captured = {}

        def fake_urlopen(request, timeout=15):
            captured["if_match"] = request.get_header("If-match")
            return _FakeResponse({"id": "r1", "etag": '"etag-2"'})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            push_update(self.account, self.calendar, self._ics(), RemoteRef(remote_id="r1", etag='"etag-1"'))
        self.assertEqual(captured["if_match"], '"etag-1"')

    def _patched_body(self, ics_bytes):
        import json as _json
        captured = {}

        def fake_urlopen(request, timeout=15):
            captured["body"] = _json.loads(request.data.decode())
            return _FakeResponse({"id": "r1", "etag": '"etag-2"'})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            push_update(self.account, self.calendar, ics_bytes, RemoteRef(remote_id="r1", etag='"etag-1"'))
        return captured["body"]

    def test_push_update_to_a_timed_event_clears_any_all_day_date(self):
        timed = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:r1\r\nSUMMARY:Now timed\r\n"
                 b"DTSTART;TZID=America/Edmonton:20260916T100000\r\nDTEND;TZID=America/Edmonton:20260916T110000\r\n"
                 b"END:VEVENT\r\nEND:VCALENDAR\r\n")
        body = self._patched_body(timed)
        for key in ("start", "end"):
            self.assertIn("dateTime", body[key])
            self.assertIn("date", body[key])
            self.assertIsNone(body[key]["date"])

    def test_push_update_to_an_all_day_event_clears_any_time(self):
        all_day = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:r1\r\nSUMMARY:Now all day\r\n"
                   b"DTSTART;VALUE=DATE:20260916\r\nDTEND;VALUE=DATE:20260917\r\n"
                   b"END:VEVENT\r\nEND:VCALENDAR\r\n")
        body = self._patched_body(all_day)
        for key in ("start", "end"):
            self.assertEqual(body[key]["date"], "2026-09-1" + ("6" if key == "start" else "7"))
            self.assertIsNone(body[key]["dateTime"])
            self.assertIsNone(body[key]["timeZone"])

    def test_push_delete_ignores_already_gone(self):
        with mock.patch("urllib.request.urlopen", side_effect=_HTTPErrorWithBody(404, b"{}")):
            push_delete(self.account, self.calendar, RemoteRef(remote_id="r1", etag="v1"))  # must not raise

    def test_push_delete_propagates_other_errors(self):
        with mock.patch("urllib.request.urlopen", side_effect=_HTTPErrorWithBody(500, b"{}")), \
             mock.patch("time.sleep"):
            with self.assertRaises(ApiError):
                push_delete(self.account, self.calendar, RemoteRef(remote_id="r1", etag="v1"))


if __name__ == "__main__":
    unittest.main()


class AuthUrlTest(unittest.TestCase):
    def test_login_hint_is_included_when_an_email_is_known(self):
        from omagenda.bridges.google import build_auth_url

        url = build_auth_url("http://127.0.0.1:1234/", "chal", "you@example.com")
        self.assertIn("login_hint=you%40example.com", url)
        self.assertIn("code_challenge=chal", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("access_type=offline", url)

    def test_no_login_hint_without_an_email(self):
        from omagenda.bridges.google import build_auth_url

        url = build_auth_url("http://127.0.0.1:1234/", "chal", None)
        self.assertNotIn("login_hint", url)


class TimeZoneTest(unittest.TestCase):
    """Google's `timeZone` is usually an IANA name, but a calendar that
    arrived by import carries whatever its source used. "GMT-05:00" was
    the one seen in the wild, and writing it straight into a TZID
    parameter corrupted the property: the colons terminate the parameter
    early, so every later parse of that file read the value as
    "00:20180112T090000" and raised.
    """

    def test_iana_zone_is_kept_as_a_tzid(self):
        value, tzid, all_day = google._google_time_to_ics(
            {"dateTime": "2026-09-09T09:00:00-06:00", "timeZone": "America/Edmonton"})
        self.assertEqual((value, tzid, all_day), ("20260909T090000", "America/Edmonton", False))
        self.assertEqual(google._dt_property_line("DTSTART", value, tzid, all_day),
                         "DTSTART;TZID=America/Edmonton:20260909T090000")

    def test_named_zone_conversion_preserves_instant_after_ics_round_trip(self):
        for raw in ("2026-01-16T15:00:00Z", "2026-09-16T02:00:00+02:00"):
            with self.subTest(raw=raw):
                value, tzid, all_day = google._google_time_to_ics(
                    {"dateTime": raw, "timeZone": "America/Edmonton"})
                line = google._dt_property_line("DTSTART", value, tzid, all_day)
                calendar = icalendar.Calendar.from_ical(
                    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:demo\r\n"
                    + line + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
                self.assertEqual(calendar.walk("VEVENT")[0]["DTSTART"].dt,
                                 datetime.datetime.fromisoformat(raw))

    def test_named_zone_without_offset_keeps_local_time(self):
        self.assertEqual(google._google_time_to_ics(
            {"dateTime": "2026-09-16T09:00:00", "timeZone": "America/Edmonton"}),
            ("20260916T090000", "America/Edmonton", False))

    def test_unusable_zone_falls_back_to_utc(self):
        value, tzid, all_day = google._google_time_to_ics(
            {"dateTime": "2018-01-12T09:00:00-05:00", "timeZone": "GMT-05:00"})
        self.assertIsNone(tzid)
        self.assertEqual(value, "20180112T140000Z")
        self.assertEqual(google._dt_property_line("DTSTART", value, tzid, all_day),
                         "DTSTART:20180112T140000Z")

    def test_missing_zone_falls_back_to_utc(self):
        value, tzid, _ = google._google_time_to_ics({"dateTime": "2026-09-09T09:00:00-06:00"})
        self.assertIsNone(tzid)
        self.assertEqual(value, "20260909T150000Z")

    def test_all_day_is_untouched(self):
        self.assertEqual(google._google_time_to_ics({"date": "2026-09-09"}),
                         ("20260909", None, True))

    def test_a_zone_needing_quotes_gets_them(self):
        # No IANA name contains these, but the framing must be correct
        # regardless of what reaches it.
        self.assertEqual(google._dt_property_line("DTSTART", "20260909T090000", "A:B", False),
                         'DTSTART;TZID="A:B":20260909T090000')

    def test_the_emitted_line_survives_a_round_trip(self):
        value, tzid, all_day = google._google_time_to_ics(
            {"dateTime": "2018-01-12T09:00:00-05:00", "timeZone": "GMT-05:00"})
        raw = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\n"
               + google._dt_property_line("DTSTART", value, tzid, all_day)
               + "\r\nSUMMARY:Imported\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        parsed = icalendar.Calendar.from_ical(raw)
        event = next(iter(parsed.walk("VEVENT")))
        self.assertEqual(event["DTSTART"].dt,
                         datetime.datetime(2018, 1, 12, 14, 0, tzinfo=datetime.timezone.utc))

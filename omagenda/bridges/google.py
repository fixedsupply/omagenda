"""Google Calendar bridge.

OAuth 2.0 loopback + PKCE against the project's own desktop-app client
(docs/google-cloud-setup.md), incremental sync via syncToken, conditional
writes via ETag, JSON<->VEVENT mapping per ARCHITECTURE.md §11.

The client id/secret are the project's own -- committed here per that
same section ("Google does not treat a desktop-app client secret as
confidential"), confirmed by the PM 2026-09-07. Either can still be
overridden with OMAGENDA_GOOGLE_CLIENT_ID/_SECRET for a bring-your-own
client (PLAN.md §7).

Every network call goes through `_api_request`, the one place that knows
about retries, backoff, and how a 410 (invalid syncToken) or 412 (stale
etag) gets surfaced to the caller -- pull() and push_update() are the only
callers that give those two codes any special meaning.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json as json_module
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from omagenda.accounts import get_secret, store_secret
from omagenda.bridges import ConflictError, PullChange, PullResult, RemoteCalendar, RemoteRef

TYPE = "google"

DEFAULT_CLIENT_ID = os.environ.get(
    "OMAGENDA_GOOGLE_CLIENT_ID",
    "37688166711-tv86un1nt39aqu7r21nf71s6iuou7vq8.apps.googleusercontent.com",
)
DEFAULT_CLIENT_SECRET = os.environ.get("OMAGENDA_GOOGLE_CLIENT_SECRET", "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")

SCOPE = "https://www.googleapis.com/auth/calendar"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"

_TOKEN_SECRET_SUFFIX = "-refresh-token"


# ---------------------------------------------------------------------
# HTTP plumbing: one place that knows about retries, backoff, and how
# 410/412 get reported back to the two callers that care about them.
# ---------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Google API error {status}: {body[:300]}")
        self.status = status
        self.body = body


def _api_request(method: str, url: str, access_token: str, body: dict | None = None,
                  extra_headers: dict | None = None) -> tuple[int, dict | None, dict]:
    headers = {"Authorization": f"Bearer {access_token}"}
    headers.update(extra_headers or {})
    data = None
    if body is not None:
        data = json_module.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    delay = 1.0
    last_error: ApiError | None = None
    for _attempt in range(4):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                payload = json_module.loads(raw) if raw else None
                return response.status, payload, dict(response.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code in (410, 412, 404):
                raise ApiError(exc.code, raw) from None
            if exc.code == 429 or exc.code >= 500:
                last_error = ApiError(exc.code, raw)
                time.sleep(delay)
                delay *= 2
                continue
            raise ApiError(exc.code, raw) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = ApiError(0, str(exc))
            time.sleep(delay)
            delay *= 2
    raise last_error or ApiError(0, "request failed with no response")


# ---------------------------------------------------------------------
# OAuth: PKCE + loopback redirect (ARCHITECTURE.md §11)
# ---------------------------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _OneShotAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_code = params.get("code", [None])[0]
        self.server.oauth_error = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        message = "You can close this tab." if self.server.oauth_code else "Authorization failed; you can close this tab."
        self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

    def log_message(self, *args):  # silence BaseHTTPRequestHandler's default stderr logging
        pass


def _open_browser(url: str) -> None:
    if shutil.which("omarchy"):
        subprocess.run(["omarchy", "launch", "browser", url], check=False)
        return
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.run([opener, url], check=False)
        return
    print(f"Open this URL to continue: {url}")


def build_auth_url(redirect_uri: str, challenge: str, email: str | None = None) -> str:
    """The consent URL. `login_hint` is what makes an account's own address
    actually matter: without it Google shows a generic account chooser, so
    on a machine signed into several accounts you have to know which one
    this is supposed to be. With it, Google preselects that address."""
    params = {
        "client_id": DEFAULT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    if email:
        params["login_hint"] = email
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def authorize(account: dict) -> None:
    """Interactive: opens a browser for consent, waits for the loopback
    redirect, exchanges the code, and stores the refresh token."""
    verifier, challenge = _pkce_pair()
    server = http.server.HTTPServer(("127.0.0.1", 0), _OneShotAuthHandler)
    server.oauth_code = None
    server.oauth_error = None
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"

    auth_url = build_auth_url(redirect_uri, challenge, account.get("email"))
    _open_browser(auth_url)
    server.handle_request()
    server.server_close()

    if server.oauth_error or not server.oauth_code:
        raise RuntimeError(f"Google authorization failed: {server.oauth_error or 'no code returned'}")

    token_body = urllib.parse.urlencode({
        "client_id": DEFAULT_CLIENT_ID,
        "client_secret": DEFAULT_CLIENT_SECRET,
        "code": server.oauth_code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=token_body, method="POST",
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=15) as response:
        tokens = json_module.loads(response.read())

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google returned no refresh token -- if you've authorized this account before, "
            "revoke it at https://myaccount.google.com/permissions and try again"
        )
    store_secret(account["id"] + _TOKEN_SECRET_SUFFIX, refresh_token)


def _get_access_token(account: dict) -> str:
    refresh_token = get_secret(account["id"] + _TOKEN_SECRET_SUFFIX)
    if not refresh_token:
        raise RuntimeError(f"no stored Google credentials for '{account['id']}'; run 'omagenda account add google' first")
    body = urllib.parse.urlencode({
        "client_id": DEFAULT_CLIENT_ID,
        "client_secret": DEFAULT_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json_module.loads(response.read())["access_token"]


# ---------------------------------------------------------------------
# list_calendars
# ---------------------------------------------------------------------
def list_calendars(account: dict) -> list[RemoteCalendar]:
    token = _get_access_token(account)
    calendars: list[RemoteCalendar] = []
    page_token = None
    while True:
        url = f"{API_BASE}/users/me/calendarList"
        if page_token:
            url += f"?pageToken={urllib.parse.quote(page_token)}"
        _, payload, _ = _api_request("GET", url, token)
        for item in payload.get("items", []):
            calendars.append(RemoteCalendar(
                id=item["id"],
                name=item.get("summary", item["id"]),
                writable=item.get("accessRole") in ("owner", "writer"),
            ))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return calendars


# ---------------------------------------------------------------------
# JSON -> VEVENT mapping
# ---------------------------------------------------------------------
def _escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _google_time_to_ics(t: dict) -> tuple[str, str | None, bool]:
    """Returns (value, tzid, all_day). Google gives an IANA `timeZone`
    name directly (ARCHITECTURE.md §11: "keep them as TZID") -- the
    dateTime's own embedded offset is redundant with it, so only the
    naive wall-clock component is used."""
    if "date" in t:
        return t["date"].replace("-", ""), None, True
    match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", t["dateTime"])
    value = match.group(1).replace("-", "") + "T" + match.group(2).replace(":", "")
    return value, t.get("timeZone"), False


def _dt_property_line(name: str, value: str, tzid: str | None, all_day: bool) -> str:
    if all_day:
        return f"{name};VALUE=DATE:{value}"
    if tzid:
        return f"{name};TZID={tzid}:{value}"
    return f"{name}:{value}Z"


def _conference_url(item: dict) -> str | None:
    if item.get("hangoutLink"):
        return item["hangoutLink"]
    for entry_point in (item.get("conferenceData") or {}).get("entryPoints") or []:
        if entry_point.get("entryPointType") == "video" and entry_point.get("uri"):
            return entry_point["uri"]
    return None


def _vevent_block(uid: str, item: dict, recurrence_id: tuple[str, str | None, bool] | None = None) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}"]
    if recurrence_id:
        lines.append(_dt_property_line("RECURRENCE-ID", *recurrence_id))
    lines.append(f"SUMMARY:{_escape_text(item.get('summary', ''))}")

    start_value, start_tzid, all_day = _google_time_to_ics(item["start"])
    end_value, end_tzid, _ = _google_time_to_ics(item["end"])
    lines.append(_dt_property_line("DTSTART", start_value, start_tzid, all_day))
    lines.append(_dt_property_line("DTEND", end_value, end_tzid, all_day))

    if item.get("location"):
        lines.append(f"LOCATION:{_escape_text(item['location'])}")
    if item.get("description"):
        lines.append(f"DESCRIPTION:{_escape_text(item['description'])}")

    conference_url = _conference_url(item)
    if conference_url:
        lines.append(f"X-GOOGLE-CONFERENCE:{conference_url}")

    for line in item.get("recurrence", []) or []:
        lines.append(line)  # verbatim, per ARCHITECTURE.md §11

    reminders = item.get("reminders") or {}
    if not reminders.get("useDefault") and reminders.get("overrides"):
        for override in reminders["overrides"]:
            minutes = override.get("minutes", 0)
            lines += [
                "BEGIN:VALARM", "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_text(item.get('summary', ''))}",
                f"TRIGGER:-PT{minutes}M", "END:VALARM",
            ]

    for attendee in item.get("attendees") or []:
        if attendee.get("email"):
            lines.append(f"ATTENDEE:mailto:{attendee['email']}")

    lines.append("END:VEVENT")
    return lines


def _map_events_page(items: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """Groups a page of the events.list response into one VEVENT-block
    list per local UID (a recurring master's file includes its own
    overrides and EXDATEs already folded in) plus a list of deleted UIDs.
    """
    standalone: dict[str, dict] = {}
    masters: dict[str, dict] = {}
    instances: dict[str, list[dict]] = {}
    deleted: list[str] = []

    for item in items:
        recurring_event_id = item.get("recurringEventId")
        if recurring_event_id:
            instances.setdefault(recurring_event_id, []).append(item)
        elif item.get("status") == "cancelled":
            deleted.append(item["id"])
        elif item.get("recurrence"):
            masters[item["id"]] = item
        else:
            standalone[item["id"]] = item

    files: dict[str, list[str]] = {uid: _vevent_block(uid, item) for uid, item in standalone.items()}

    for uid, item in masters.items():
        lines = _vevent_block(uid, item)
        exdate_lines = []
        override_blocks: list[str] = []
        for instance in instances.get(uid, []):
            original_start = instance.get("originalStartTime")
            if instance.get("status") == "cancelled":
                if original_start:
                    value, tzid, all_day = _google_time_to_ics(original_start)
                    exdate_lines.append(_dt_property_line("EXDATE", value, tzid, all_day))
            else:
                recurrence_id = _google_time_to_ics(original_start) if original_start else None
                # A full, complete VEVENT block -- a RECURRENCE-ID override
                # is a sibling component sharing the master's UID, not a
                # continuation of the master's own property list.
                override_blocks += _vevent_block(uid, instance, recurrence_id=recurrence_id)
        if exdate_lines:
            lines = lines[:-1] + exdate_lines + [lines[-1]]  # before the master's own END:VEVENT
        lines += override_blocks
        files[uid] = lines

    return files, deleted


def _wrap_calendar(vevent_lines: list[str]) -> bytes:
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Omagenda//EN", *vevent_lines, "END:VCALENDAR", ""])
    return text.encode("utf-8")


# ---------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------
def pull(account: dict, calendar: RemoteCalendar, cursor: str | None) -> PullResult:
    token = _get_access_token(account)
    full_resync = False
    items: list[dict] = []
    next_cursor = cursor

    def fetch(sync_token: str | None) -> str | None:
        nonlocal items
        page_token = None
        latest_sync_token = None
        while True:
            params = {"singleEvents": "false", "showDeleted": "true", "maxResults": "250"}
            if sync_token:
                params["syncToken"] = sync_token
            if page_token:
                params["pageToken"] = page_token
            url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events?{urllib.parse.urlencode(params)}"
            _, payload, _ = _api_request("GET", url, token)
            items.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if payload.get("nextSyncToken"):
                latest_sync_token = payload["nextSyncToken"]
            if not page_token:
                return latest_sync_token

    try:
        next_cursor = fetch(cursor)
    except ApiError as exc:
        if exc.status == 410 and cursor is not None:
            items = []
            full_resync = True
            next_cursor = fetch(None)
        else:
            raise

    files, deleted_uids = _map_events_page(items)
    changed = [PullChange(uid=uid, ics_bytes=_wrap_calendar(lines), ref=RemoteRef(remote_id=uid))
               for uid, lines in files.items()]
    return PullResult(changed=changed, deleted_uids=deleted_uids, next_cursor=next_cursor, full_resync=full_resync)


# ---------------------------------------------------------------------
# VEVENT -> JSON mapping, for push
# ---------------------------------------------------------------------
def _local_event_to_google_body(event) -> dict:
    body: dict = {"summary": str(event.get("summary", ""))}

    dtstart = event["dtstart"].dt
    dtend = event["dtend"].dt if event.get("dtend") else dtstart
    if isinstance(dtstart, datetime):
        body["start"] = {"dateTime": dtstart.isoformat()}
        body["end"] = {"dateTime": dtend.isoformat()}
        if dtstart.tzinfo is not None:
            zone_name = getattr(dtstart.tzinfo, "key", None)
            if zone_name:
                body["start"]["timeZone"] = zone_name
                body["end"]["timeZone"] = zone_name
    else:
        body["start"] = {"date": dtstart.isoformat()}
        body["end"] = {"date": dtend.isoformat()}

    if event.get("location"):
        body["location"] = str(event["location"])
    if event.get("description"):
        body["description"] = str(event["description"])

    rrule = event.get("rrule")
    if rrule:
        body["recurrence"] = [f"RRULE:{rrule.to_ical().decode()}"]
        exdates = event.get("exdate")
        exdates = exdates if isinstance(exdates, list) else ([exdates] if exdates else [])
        for exdate_prop in exdates:
            body["recurrence"].append(f"EXDATE:{exdate_prop.to_ical().decode()}")

    overrides = []
    for valarm in event.walk("VALARM"):
        trigger = valarm.get("TRIGGER")
        if trigger is not None and isinstance(trigger.dt, timedelta):
            overrides.append({"method": "popup", "minutes": int(abs(trigger.dt.total_seconds()) // 60)})
    if overrides:
        body["reminders"] = {"useDefault": False, "overrides": overrides}

    return body


def push_create(account: dict, calendar: RemoteCalendar, ics_bytes: bytes) -> RemoteRef:
    import icalendar

    event = next(iter(icalendar.Calendar.from_ical(ics_bytes).walk("VEVENT")))
    token = _get_access_token(account)
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events"
    _, payload, headers = _api_request("POST", url, token, body=_local_event_to_google_body(event))
    return RemoteRef(remote_id=payload["id"], etag=payload.get("etag"))


def push_update(account: dict, calendar: RemoteCalendar, ics_bytes: bytes, ref: RemoteRef) -> RemoteRef:
    import icalendar

    event = next(iter(icalendar.Calendar.from_ical(ics_bytes).walk("VEVENT")))
    token = _get_access_token(account)
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events/{urllib.parse.quote(ref.remote_id)}"
    headers = {"If-Match": ref.etag} if ref.etag else {}
    try:
        _, payload, _ = _api_request("PUT", url, token, body=_local_event_to_google_body(event), extra_headers=headers)
    except ApiError as exc:
        if exc.status == 412:
            raise ConflictError(f"'{ref.remote_id}' changed on the server since it was last read") from exc
        raise
    return RemoteRef(remote_id=payload["id"], etag=payload.get("etag"))


def push_delete(account: dict, calendar: RemoteCalendar, ref: RemoteRef) -> None:
    token = _get_access_token(account)
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events/{urllib.parse.quote(ref.remote_id)}"
    try:
        _api_request("DELETE", url, token)
    except ApiError as exc:
        if exc.status != 404:  # already gone is not an error
            raise

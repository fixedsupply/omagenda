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
import threading
import functools
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo
from datetime import datetime, timedelta, timezone

from omagenda import vdir
from omagenda.accounts import get_secret, store_secret
from omagenda.bridges import (AuthExpiredError, ConflictError, PullChange, PullResult,
                              RemoteCalendar, RemoteRef)

TYPE = "google"

DEFAULT_CLIENT_ID = os.environ.get(
    "OMAGENDA_GOOGLE_CLIENT_ID",
    "37688166711-tv86un1nt39aqu7r21nf71s6iuou7vq8.apps.googleusercontent.com",
)
DEFAULT_CLIENT_SECRET = os.environ.get("OMAGENDA_GOOGLE_CLIENT_SECRET", "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")

SCOPES = ("https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.calendarlist.readonly")
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
def _authed_request(account: dict, method: str, url: str, body: dict | None = None,
                    extra_headers: dict | None = None):
    """One request carrying the account's access token, retried once with
    a fresh token if the server says the one used is no longer good.

    The token is cached for its lifetime, so the moment a grant is
    revoked -- or a cached token outlives its welcome -- surfaces here as
    a 401 rather than at the point the token was fetched. Retrying with a
    fresh token either succeeds or fails at the refresh, which is where
    an expired sign-in gets named properly.
    """
    for attempt in range(2):
        try:
            return _api_request(method, url, _get_access_token(account), body, extra_headers)
        except ApiError as exc:
            if exc.status == 403 and _insufficient_scope(exc.body):
                raise AuthExpiredError(
                    account["id"],
                    remedy=f"Reconnect with: omagenda account add google --id {account['id']}",
                    detail="Required Google Calendar permission was not granted") from None
            if exc.status != 401 or attempt:
                raise
            forget_access_token(account["id"])


def _insufficient_scope(body: str) -> bool:
    """Google uses both legacy error reasons and structured ErrorInfo."""
    try:
        payload = json_module.loads(body)
    except ValueError:
        return False

    def contains_reason(value):
        if isinstance(value, dict):
            return (value.get("reason") in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT")
                    or any(contains_reason(item) for item in value.values()))
        return isinstance(value, list) and any(contains_reason(item) for item in value)

    return contains_reason(payload)


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


def build_auth_url(redirect_uri: str, challenge: str, email: str | None = None, *,
                   scopes: tuple[str, ...] = SCOPES, offline: bool = True) -> str:
    """The consent URL. `login_hint` is what makes an account's own address
    actually matter: without it Google shows a generic account chooser, so
    on a machine signed into several accounts you have to know which one
    this is supposed to be. With it, Google preselects that address."""
    params = {
        "client_id": DEFAULT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline" if offline else "online",
        "prompt": "consent",
    }
    if email:
        params["login_hint"] = email
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_authorization(account: dict, *, scopes: tuple[str, ...] = SCOPES,
                           offline: bool = True) -> dict:
    """Exchange browser consent using loopback PKCE without storing credentials."""
    verifier, challenge = _pkce_pair()
    server = http.server.HTTPServer(("127.0.0.1", 0), _OneShotAuthHandler)
    server.oauth_code = None
    server.oauth_error = None
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"

    try:
        auth_url = build_auth_url(redirect_uri, challenge, account.get("email"),
                                  scopes=scopes, offline=offline)
        _open_browser(auth_url)
        server.handle_request()
    finally:
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

    return tokens


def authorize(account: dict) -> None:
    """Store a refresh token only after both required permissions are granted."""
    tokens = exchange_authorization(account)
    granted = set(tokens.get("scope", "").split())
    missing = set(SCOPES) - granted
    if missing and "https://www.googleapis.com/auth/calendar" not in granted:
        raise RuntimeError(
            f"Google permission not granted: {', '.join(sorted(missing))}; "
            f"run omagenda account add google --id {account['id']} again with both boxes ticked")
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google returned no refresh token -- if you've authorized this account before, "
            "revoke it at https://myaccount.google.com/permissions and try again"
        )
    store_secret(account["id"] + _TOKEN_SECRET_SUFFIX, refresh_token)


# An access token is good for an hour, and every call that needed one
# used to spend a full round trip to Google's token endpoint getting a
# fresh one -- thirteen of them in a single sync of twelve calendars,
# about seventeen seconds of pure waiting, and needless load on an
# endpoint that is rate limited. Cached per process, which matters most
# in `omagenda watch`, the process that syncs over and over.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()
_TOKEN_EARLY_EXPIRY = 300  # refresh early rather than race the expiry


def _get_access_token(account: dict) -> str:
    key = account["id"]
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached and cached[1] > time.time():
            return cached[0]
    token, lifetime = _fetch_access_token(account)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, time.time() + max(60, lifetime - _TOKEN_EARLY_EXPIRY))
    return token


def forget_access_token(account_id: str) -> None:
    """Drop a cached token, so the next call gets a fresh one."""
    with _TOKEN_LOCK:
        _TOKEN_CACHE.pop(account_id, None)


def _fetch_access_token(account: dict) -> tuple[str, float]:
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
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json_module.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise _token_error(account, exc) from None
    return payload["access_token"], float(payload.get("expires_in", 3600))


# Google's own names for "these credentials are finished". invalid_grant
# is overwhelmingly the one that will be seen: it covers an expired
# Testing-mode refresh token, a revoked grant, and a changed password.
_DEAD_CREDENTIAL_ERRORS = {"invalid_grant", "unauthorized_client", "invalid_client"}


def _token_error(account: dict, exc: urllib.error.HTTPError) -> Exception:
    try:
        body = json_module.loads(exc.read())
    except Exception:  # noqa: BLE001 -- a non-JSON body is just no extra detail
        body = {}
    finally:
        exc.close()  # an HTTPError holds an open response until told otherwise
    code = body.get("error", "")
    if exc.code in (400, 401) and code in _DEAD_CREDENTIAL_ERRORS:
        return AuthExpiredError(
            account["id"],
            remedy=f"Reconnect with: omagenda account add google --id {account['id']}",
            detail=body.get("error_description", code))
    return RuntimeError(f"Google refused the token request ({exc.code} {code or exc.reason})")


# ---------------------------------------------------------------------
# list_calendars
# ---------------------------------------------------------------------
def list_calendars(account: dict) -> list[RemoteCalendar]:
    calendars: list[RemoteCalendar] = []
    page_token = None
    while True:
        url = f"{API_BASE}/users/me/calendarList"
        if page_token:
            url += f"?pageToken={urllib.parse.quote(page_token)}"
        _, payload, _ = _authed_request(account, "GET", url)
        for item in payload.get("items", []):
            calendars.append(RemoteCalendar(
                id=item["id"],
                name=item.get("summary", item["id"]),
                writable=item.get("accessRole") in ("owner", "writer"),
                color=vdir.map_color_to_theme(item.get("backgroundColor")),
            ))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return calendars


# ---------------------------------------------------------------------
# JSON -> VEVENT mapping
# ---------------------------------------------------------------------
def _escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@functools.lru_cache(maxsize=None)
def _is_iana_zone(name: str) -> bool:
    """Google's `timeZone` is *usually* an IANA name, but calendars that
    arrived by import carry whatever their source used -- "GMT-05:00" is
    the one seen in the wild. That is not a zone any tzdata lookup
    resolves, and worse, its colons break the ICS property it would be
    written into, so it has to be recognised as unusable before it is
    ever emitted."""
    try:
        zoneinfo.ZoneInfo(name)
    except Exception:  # noqa: BLE001 -- any failure means "not usable as a TZID"
        return False
    return True


def _google_time_to_ics(t: dict) -> tuple[str, str | None, bool]:
    """Keep the instant from dateTime, expressed in the named zone if valid.

    Calendar responses can express dateTime in a different offset from the
    event's timeZone. Dropping that offset shifts the appointment.
    """
    if "date" in t:
        return t["date"].replace("-", ""), None, True

    raw = t["dateTime"]
    tzid = t.get("timeZone")
    if tzid and _is_iana_zone(tzid):
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is not None:
            moment = moment.astimezone(zoneinfo.ZoneInfo(tzid))
        return moment.strftime("%Y%m%dT%H%M%S"), tzid, False

    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        # Floating: no offset and no zone, so RFC 5545 local time. Left
        # floating rather than guessed at.
        return moment.strftime("%Y%m%dT%H%M%S"), None, False
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), None, False


def _param_value(value: str) -> str:
    """RFC 5545 3.1: a parameter value containing ':', ';' or ',' must be
    quoted, or it terminates the parameter early and corrupts every
    property that follows on the line."""
    return f'"{value}"' if any(c in value for c in ':;,') else value


def _dt_property_line(name: str, value: str, tzid: str | None, all_day: bool) -> str:
    """The value arrives fully formed -- _google_time_to_ics decides
    between a wall clock carrying a TZID, a UTC instant carrying its own
    trailing Z, and a floating local time carrying neither -- so this
    only frames it."""
    if all_day:
        return f"{name};VALUE=DATE:{value}"
    if tzid:
        return f"{name};TZID={_param_value(tzid)}:{value}"
    return f"{name}:{value}"


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
    full_resync = cursor is None
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
            _, payload, _ = _authed_request(account, "GET", url)
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

    # A delta may contain only an exception, or only a changed master.
    # Rebuild from a complete snapshot so neither drops existing exceptions.
    if cursor is not None and not full_resync and any(
            item.get("recurringEventId") or item.get("recurrence") for item in items):
        items = []
        next_cursor = fetch(None)
        full_resync = True
    files, deleted_uids = _map_events_page(items)
    versions = {item["id"]: item.get("etag") for item in items}
    changed = [PullChange(uid=uid, ics_bytes=_wrap_calendar(lines), ref=RemoteRef(remote_id=uid, etag=versions.get(uid)))
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

    recurrence = []
    for name in ("rrule", "rdate", "exrule", "exdate"):
        properties = event.get(name)
        properties = properties if isinstance(properties, list) else ([properties] if properties else [])
        for prop in properties:
            params = ";" + prop.params.to_ical().decode() if prop.params else ""
            recurrence.append(name.upper() + params + ":" + prop.to_ical().decode())
    if recurrence:
        body["recurrence"] = recurrence

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

    events = icalendar.Calendar.from_ical(ics_bytes).walk("VEVENT")
    if len(events) != 1 or events[0].get("recurrence-id"):
        raise ValueError("Creating a series with exceptions is not supported yet; use Google Calendar")
    event = events[0]
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events"
    _, payload, headers = _authed_request(account, "POST", url, body=_local_event_to_google_body(event))
    return RemoteRef(remote_id=payload["id"], etag=payload.get("etag"))


def push_update(account: dict, calendar: RemoteCalendar, ics_bytes: bytes, ref: RemoteRef) -> RemoteRef:
    import icalendar

    events = icalendar.Calendar.from_ical(ics_bytes).walk("VEVENT")
    if len(events) != 1 or events[0].get("recurrence-id"):
        raise ValueError("Editing a series with exceptions is not supported yet; edit it in Google Calendar")
    event = events[0]
    if not ref.etag:
        raise ConflictError("Missing event version; sync again before updating")
    body = _local_event_to_google_body(event)
    for field in ("location", "description"):
        body.setdefault(field, "")
    body.setdefault("recurrence", [])
    # PATCH merges into the stored event. Turning an all-day event into a
    # timed one would leave its old `date` beside the new `dateTime`, which
    # Google rejects with 400 "Invalid start time" (seen live 2026-09-16 when
    # an event was edited from all day to 10am); the reverse leaves a stale
    # dateTime. An explicit null clears whichever form is not being sent.
    for key in ("start", "end"):
        when = body.get(key)
        if isinstance(when, dict) and "dateTime" in when:
            when.setdefault("date", None)
        elif isinstance(when, dict) and "date" in when:
            when.setdefault("dateTime", None)
            when.setdefault("timeZone", None)
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events/{urllib.parse.quote(ref.remote_id)}"
    headers = {"If-Match": ref.etag} if ref.etag else {}
    try:
        _, payload, _ = _authed_request(account, "PATCH", url, body=body, extra_headers=headers)
    except ApiError as exc:
        if exc.status == 412:
            raise ConflictError(f"'{ref.remote_id}' changed on the server since it was last read") from exc
        raise
    return RemoteRef(remote_id=payload["id"], etag=payload.get("etag"))


def push_delete(account: dict, calendar: RemoteCalendar, ref: RemoteRef) -> None:
    if not ref.etag:
        raise ConflictError("Missing event version; sync again before deleting")
    url = f"{API_BASE}/calendars/{urllib.parse.quote(calendar.id)}/events/{urllib.parse.quote(ref.remote_id)}"
    try:
        _authed_request(account, "DELETE", url, extra_headers={"If-Match": ref.etag})
    except ApiError as exc:
        if exc.status == 412:
            raise ConflictError("Event changed before deletion") from exc
        if exc.status not in (404, 410):  # already gone is not an error
            raise

"""Environment diagnostics.

Checks the things a fresh install commonly gets wrong: the calendar
libraries are importable, the vdir has calendars in it, a sync tool is on
PATH if the config asks for one, a keyring is available for account
credentials, and whether the plugin is enabled in shell.json. Backs
`omagenda doctor`. See ARCHITECTURE.md §9.

Account-level checks (OAuth token health) land in Phase 1b once accounts
exist at all.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import subprocess
import shlex
import re
from pathlib import Path
from datetime import datetime, timezone

import omagenda

CONFIG_PATH = Path(os.environ.get("OMAGENDA_CONFIG", Path.home() / ".config" / "omagenda" / "config.toml"))
SHELL_JSON_PATH = Path.home() / ".config" / "omarchy" / "shell.json"
PLUGIN_ID = "fixedsupply.omagenda"
PLUGIN_PATH = Path.home() / ".config" / "omarchy" / "plugins" / PLUGIN_ID
REQUIRED_PACKAGES = ["icalendar", "dateutil", "recurring_ical_events"]


def read_config() -> dict:
    """The handful of top-level config.toml keys Phase 1 needs
    (`vdir`, `default_calendar`); accounts.py (Phase 1b) owns the rest."""
    if not CONFIG_PATH.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover -- this repo targets a current Python
        import tomli as tomllib  # type: ignore[no-redef]
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def _check_packages() -> dict:
    missing = [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]
    return {
        "ok": not missing,
        "detail": "all present" if not missing else f"missing: {', '.join(missing)} "
        "(omarchy pkg add python-icalendar python-dateutil python-recurring-ical-events)",
    }


def _check_vdir() -> dict:
    from omagenda.vdir import resolve_vdir_root, discover_calendars

    root = resolve_vdir_root()
    if not root.is_dir():
        return {"ok": False, "detail": f"{root} doesn't exist yet"}
    everything = discover_calendars(root, include_reminder_lists=True)
    calendars = [c for c in everything if not c["reminderList"]]
    skipped = [c for c in everything if c["reminderList"]]
    note = ("; skipped reminder list(s) with no events: " + ", ".join(c["id"] for c in skipped)
            if skipped else "")
    if not calendars:
        return {"ok": False, "detail": f"{root} exists but has no calendars in it{note}"}
    names = ", ".join(c["id"] for c in calendars)
    return {"ok": True, "detail": f"{len(calendars)} calendar(s) at {root}: {names}{note}"}


def _check_sync_tool(config: dict) -> dict:
    wanted = None
    for account in config.get("accounts", []):
        if account.get("type") in ("icloud", "caldav"):
            wanted = account.get("sync", "pimsync")
            break
    if wanted is None:
        return {"ok": True, "detail": "no CalDAV/iCloud account configured yet, nothing required"}
    found = shutil.which(wanted)
    if found:
        return {"ok": True, "detail": f"{wanted} found at {found}"}
    return {"ok": False, "detail": f"{wanted} not found on PATH (omarchy pkg add {wanted})"}


def _check_keyring() -> dict:
    found = shutil.which("secret-tool")
    if found:
        return {"ok": True, "detail": f"secret-tool found at {found}"}
    return {"ok": False, "detail": "secret-tool not found; account credentials would fall back to a plain file (omarchy pkg add libsecret)"}


def _check_install() -> dict:
    package = Path(omagenda.__file__).resolve()
    target = PLUGIN_PATH.resolve()
    symlink = PLUGIN_PATH.is_symlink()
    detail = f"plugin folder {PLUGIN_PATH}"
    detail += f"; developer install (symlink to {target})" if symlink else "; not a symlink"
    detail += f"; CLI package {package}"
    if not PLUGIN_PATH.is_dir():
        return {"ok": False, "detail": detail + "; plugin folder missing; reinstall Omagenda"}
    try:
        version = json.loads((target / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "detail": detail + "; installed manifest missing or invalid; reinstall Omagenda"}
    detail += f"; installed version {version}"
    if not package.is_relative_to(target):
        return {"ok": False, "detail": detail + f"; CLI is outside installed plugin {target}; try: "
                "ln -sf ~/.config/omarchy/plugins/fixedsupply.omagenda/bin/omagenda ~/.local/bin/omagenda"}
    return {"ok": True, "detail": detail}


def _check_plugin_enabled(install_ok: bool = True) -> dict:
    if not SHELL_JSON_PATH.exists():
        return {"ok": False, "detail": "no shell.json yet; Omarchy is using its defaults, which don't include Omagenda"}
    try:
        shell_config = json.loads(SHELL_JSON_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": f"couldn't read {SHELL_JSON_PATH}: {exc}"}

    layout = shell_config.get("bar", {}).get("layout", {})
    for section in layout.values():
        for entry in section:
            if entry.get("id") == PLUGIN_ID:
                return {"ok": True, "detail": f"in the bar's {_section_name(layout, entry)} section"}
    plugins = shell_config.get("plugins", [])
    if any(p.get("id") == PLUGIN_ID for p in plugins):
        return {"ok": True, "detail": "enabled (non-widget)"}
    remedy = ("omarchy plugin enable fixedsupply.omagenda" if install_ok
              else "fix the install check first")
    return {"ok": False, "detail": f"not enabled yet ({remedy})"}


def _section_name(layout: dict, target_entry: dict) -> str:
    for name, entries in layout.items():
        if target_entry in entries:
            return name
    return "?"


def _check_sign_in() -> dict:
    """Whether the last sync found the stored credentials still good.

    Read from what sync recorded rather than by calling the server, so
    `doctor` stays offline and instant. A Google OAuth client left in
    Testing mode expires its refresh tokens every seven days, which makes
    an expired sign-in the single most likely thing to be wrong here.
    """
    from omagenda.sync import read_last_sync
    from omagenda.pause import read_pause

    paused = read_pause()
    if paused:
        return {"ok": True, "detail": f"sync paused until {paused}"}
    record = read_last_sync()
    if not record:
        return {"ok": True, "detail": "no sync has run yet"}
    expired = record.get("needsReauth") or []
    if expired:
        return {"ok": False,
                "detail": f"sign-in expired for {', '.join(expired)}. {record.get('remedy', '')}"}
    if not record.get("ok", True):
        return {"ok": False,
                "detail": f"last sync at {record.get('at', '?')} reported problems with "
                          f"{', '.join(record.get('problems', [])) or 'an account'}"}
    try:
        at = datetime.fromisoformat(record.get("at", ""))
        age = (datetime.now(timezone.utc) - at).total_seconds()
    except (ValueError, TypeError):
        return {"ok": False, "detail": "last sync timestamp invalid; try: omagenda sync"}
    threshold = max(1800, 3 * int(read_config().get("sync_interval", 300)))
    if age > threshold:
        minutes = int(age // 60)
        age_text = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} hours"
        return {"ok": False, "detail": f"last successful sync was {age_text} ago; "
                "is the watcher running? try: omagenda sync"}
    return {"ok": True, "detail": f"last synced {record.get('at', '?')}"}


def _check_leftover_tokens(config: dict) -> dict:
    from omagenda.accounts import SECRETS_DIR

    suffix = "-refresh-token"
    names = {p.name for p in SECRETS_DIR.glob("*" + suffix) if p.is_file()}
    skipped = False
    binary = shutil.which("secret-tool")
    try:
        if not binary:
            skipped = True
        else:
            result = subprocess.run([binary, "search", "--all", "service", "omagenda"],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                skipped = True
            else:
                # Search prints secrets too. Only account attributes leave this scope.
                for stream in (result.stderr, result.stdout):
                    names.update(re.findall(r"^attribute\.account = (.+)$", stream, re.MULTILINE))
                del stream
            del result
    except (OSError, subprocess.TimeoutExpired):
        skipped = True
    configured = {a["id"] for a in config.get("accounts", [])}
    leftovers = sorted(name for name in names if name.endswith(suffix) and name[:-len(suffix)] not in configured)
    details = []
    for name in leftovers:
        details.append(f"{name[:-len(suffix)]}: secret-tool clear service omagenda account {shlex.quote(name)}; "
                       f"rm -f {shlex.quote(str(SECRETS_DIR / name))}")
    if skipped:
        details.append("keyring check skipped (unavailable or locked)")
    return {"ok": not leftovers, "skipped": skipped,
            "detail": "; ".join(details) or "no leftover tokens"}


def run() -> dict:
    from omagenda.pause import read_pause

    config = read_config()
    install = _check_install()
    paused = read_pause()
    from omagenda.vdir import discover_calendars
    hidden = config.get("hidden_calendars", [])
    discovered = {c["id"] for c in discover_calendars()}
    missing = [c for c in hidden if c not in discovered]
    detail = f"{len(hidden)} hidden" if hidden else "none hidden"
    if missing:
        detail += "; no longer discovered: " + ", ".join(missing)
    return {
        "install": install,
        "hiddenCalendars": {"ok": True, "detail": detail},
        "syncPause": {"ok": True, "detail": f"paused until {paused}" if paused else "not paused"},
        "leftoverTokens": _check_leftover_tokens(config),
        "packages": _check_packages(),
        "vdir": _check_vdir(),
        "signIn": _check_sign_in(),
        "syncTool": _check_sync_tool(config),
        "keyring": _check_keyring(),
        "pluginEnabled": _check_plugin_enabled(install["ok"]),
    }

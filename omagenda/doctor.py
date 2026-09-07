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
import shutil
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "omagenda" / "config.toml"
SHELL_JSON_PATH = Path.home() / ".config" / "omarchy" / "shell.json"
PLUGIN_ID = "fixedsupply.omagenda"
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
    calendars = discover_calendars(root)
    if not calendars:
        return {"ok": False, "detail": f"{root} exists but has no calendars in it"}
    names = ", ".join(c["id"] for c in calendars)
    return {"ok": True, "detail": f"{len(calendars)} calendar(s) at {root}: {names}"}


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


def _check_plugin_enabled() -> dict:
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
    return {"ok": False, "detail": "not enabled yet (omarchy plugin enable fixedsupply.omagenda)"}


def _section_name(layout: dict, target_entry: dict) -> str:
    for name, entries in layout.items():
        if target_entry in entries:
            return name
    return "?"


def run() -> dict:
    config = read_config()
    return {
        "packages": _check_packages(),
        "vdir": _check_vdir(),
        "syncTool": _check_sync_tool(config),
        "keyring": _check_keyring(),
        "pluginEnabled": _check_plugin_enabled(),
    }

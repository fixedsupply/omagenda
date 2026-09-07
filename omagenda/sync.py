"""Sync orchestration.

Reads config.toml's accounts and dispatches each one by type. This phase
has no accounts.py yet (that's Phase 1b), so nothing writes a real account
into config.toml -- sync_all() runs safely against an empty account list
today, and the dispatch below is what Phase 1b's `omagenda account add`
starts populating.

- `ics`: fully implemented and testable now -- a plain HTTP fetch into a
  read-only vdir folder, no external tool required.
- `icloud` / `caldav`: delegates to the configured sync tool (pimsync,
  falling back to vdirsyncer). The exact CLI invocation is a placeholder
  pending Phase 1b, when `accounts.py` writes real pimsync configs and
  this can be verified against `man pimsync` on a machine that has it
  installed (this one doesn't -- no sudo in this session, see AGENTS.md).
- `google` / `microsoft`: not implemented until their bridges land
  (Phase 1b, Phase 5) -- reported clearly rather than attempted.

See ARCHITECTURE.md §7 and §11.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from omagenda.doctor import read_config
from omagenda.vdir import resolve_vdir_root


def _sync_ics(account: dict, vdir_root: Path) -> dict:
    url = account.get("url")
    if not url:
        return {"ok": False, "detail": "no url configured"}
    folder = vdir_root / account["id"]
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "detail": f"fetch failed: {exc}"}

    (folder / "displayname").write_text(account.get("id", url))
    if account.get("color"):
        (folder / "color").write_text(account["color"])
    (folder / "subscription.ics").write_bytes(data)
    folder.chmod(0o555)  # readOnly, per vdir.discover_calendars' os.access check
    return {"ok": True, "detail": f"fetched {len(data)} bytes into {folder}"}


def _sync_caldav(account: dict) -> dict:
    from omagenda.accounts import pimsync_config_path

    tool = account.get("sync", "pimsync")
    binary = shutil.which(tool)
    if not binary:
        return {"ok": False, "detail": f"{tool} not found on PATH (omarchy pkg add {tool})"}

    config_path = pimsync_config_path(account["id"])
    if not config_path.exists():
        return {"ok": False, "detail": f"no pimsync config at {config_path}; run 'omagenda account add' again"}

    try:
        # Verbatim against pimsync.conf(5) and pimsync(1): `pimsync -c
        # <configfile> sync [pair...]`. accounts.generate_pimsync_config
        # names the pair after the account id (sanitized), which is also
        # the only pair this config file defines.
        from omagenda.accounts import _safe_pair_name

        result = subprocess.run(
            [binary, "-c", str(config_path), "sync", _safe_pair_name(account["id"])],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"{tool} failed to run: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "detail": f"{tool} exited {result.returncode}: {result.stderr.strip()[:200]}"}
    return {"ok": True, "detail": f"{tool} sync ok"}


def _sync_bridge(account: dict) -> dict:
    return {"ok": False, "detail": f"'{account['type']}' bridge not yet implemented"}


def _merge_omacal(vdir_root: Path) -> dict | None:
    binary = shutil.which("omacal")
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "events", "list", "--json"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"omacal failed to run: {exc}"}
    if result.returncode != 0:
        return {"ok": False, "detail": f"omacal exited {result.returncode}"}
    return {"ok": True, "detail": "omacal merge not yet wired into the vdir (read-only, Phase 4)"}


def sync_all(config: dict | None = None) -> dict:
    config = config if config is not None else read_config()
    vdir_root = resolve_vdir_root()
    results = {}
    for account in config.get("accounts", []):
        account_type = account.get("type")
        if account_type == "ics":
            results[account["id"]] = _sync_ics(account, vdir_root)
        elif account_type in ("icloud", "caldav"):
            results[account["id"]] = _sync_caldav(account)
        elif account_type in ("google", "microsoft"):
            results[account["id"]] = _sync_bridge(account)
        else:
            results[account.get("id", "?")] = {"ok": False, "detail": f"unknown account type '{account_type}'"}

    omacal_result = _merge_omacal(vdir_root)
    if omacal_result is not None:
        results["omacal"] = omacal_result

    return results

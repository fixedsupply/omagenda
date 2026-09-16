"""Account management.

`omagenda account add|list|remove`: writes ~/.config/omagenda/config.toml
entries, stores credentials via the keyring (secret-tool), falling back to
a mode-0600 file when no keyring is available, and generates a pimsync
config for icloud/caldav accounts. See ARCHITECTURE.md §5 and §11.

Python's stdlib only reads TOML (`tomllib`), never writes it, so this
module owns a small writer scoped to exactly the shapes config.toml uses
(top-level scalars, a repeated [[accounts]] array-of-tables, and the
[alarms] tables) -- not a general-purpose TOML serializer.

pimsync config syntax (scfg) verified against pimsync.conf(5), section by
section, since this machine has no sudo path to install pimsync and check
it directly (see AGENTS.md's Phase 1b note): the `password { cmd ... }`
block form, `storage <name> { type vdir/icalendar | caldav; ... }`, the
`pair` block's `storage_a`/`storage_b`/`collections`/`conflict_resolution`
directives, and the `conflict_resolution cmd` form all come from its own
worked examples, not guessed. (`keep a|keep b` also exist, but pimsync
0.5.7 never resolves a conflict with them; see
`conflict_resolution_directive`.)
"""
from __future__ import annotations

import re
import os
import json
import urllib.error
import urllib.parse
import urllib.request
import shutil
import subprocess
from pathlib import Path

from omagenda.doctor import CONFIG_PATH, read_config

SERVICE = "omagenda"
SECRETS_DIR = Path(os.environ.get("OMAGENDA_STATE", Path.home() / ".local/state/omagenda")) / "secrets"
PIMSYNC_CONFIG_DIR = Path.home() / ".config" / "pimsync"
PIMSYNC_STATUS_DIR = Path.home() / ".local" / "share" / "pimsync" / "status"


# ---------------------------------------------------------------------
# config.toml (read via doctor.read_config; write is owned here)
# ---------------------------------------------------------------------
def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value for config.toml: {type(value)}")


def write_config(config: dict, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    lines: list[str] = []

    for key in ("vdir", "default_calendar", "sync_interval", "sync_workers", "hidden_calendars"):
        if key in config:
            lines.append(f"{key} = {_toml_value(config[key])}")
    if lines:
        lines.append("")

    for account in config.get("accounts", []):
        lines.append("[[accounts]]")
        for key, value in account.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    if config.get("alarms"):
        lines.append("[alarms]")
        for key, value in config["alarms"].items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def add_account(account: dict, path: Path | None = None) -> None:
    if not account.get("id") or not account.get("type"):
        raise ValueError("an account needs at least 'id' and 'type'")
    config = read_config()
    accounts = config.setdefault("accounts", [])
    if any(a["id"] == account["id"] for a in accounts):
        raise ValueError(f"an account named '{account['id']}' already exists")
    accounts.append(account)
    write_config(config, path)


def _revoke_google_token(token: str) -> bool:
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/revoke",
        data=urllib.parse.urlencode({"token": token}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        try:
            return exc.code == 400 and json.loads(exc.read()).get("error") == "invalid_token"
        except Exception:
            return False
        finally:
            exc.close()
    except Exception:
        # Transport exceptions can contain the credential; never relay them.
        return False


def remove_account(account_id: str, path: Path | None = None, *, revoke: bool = False) -> dict | None:
    config = read_config()
    accounts = config.get("accounts", [])
    remaining = [a for a in accounts if a["id"] != account_id]
    if len(remaining) == len(accounts):
        return None
    account = next(a for a in accounts if a["id"] == account_id)
    revoked = None
    if account.get("type") == "google":
        from omagenda.bridges.google import _TOKEN_SECRET_SUFFIX

        token = get_secret(account_id + _TOKEN_SECRET_SUFFIX) if revoke else None
        if token:
            revoked = _revoke_google_token(token)
        delete_secret(account_id + _TOKEN_SECRET_SUFFIX)
    delete_secret(account_id)
    config["accounts"] = remaining
    write_config(config, path)
    pimsync_config_path(account_id).unlink(missing_ok=True)
    from omagenda.vdir import resolve_vdir_root

    return {"removed": True, "revoked": revoked,
            "calendarFolder": str(resolve_vdir_root() / account_id)}


def list_accounts() -> list[dict]:
    return read_config().get("accounts", [])


# ---------------------------------------------------------------------
# Credentials: keyring first, a private file as the documented fallback
# ---------------------------------------------------------------------
def _secret_file_path(account_id: str) -> Path:
    return SECRETS_DIR / account_id


def store_secret(account_id: str, secret: str) -> bool:
    """Stores a credential for `account_id`. Returns True if it went into
    the real keyring, False if it fell back to a file (doctor.py's keyring
    check is what tells the user which one is in play)."""
    binary = shutil.which("secret-tool")
    if binary:
        result = subprocess.run(
            [binary, "store", "--label", f"Omagenda {account_id}", "service", SERVICE, "account", account_id],
            input=secret, text=True, capture_output=True,
        )
        if result.returncode == 0:
            return True
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(0o700)
    path = _secret_file_path(account_id)
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)
    return False


def get_secret(account_id: str) -> str | None:
    binary = shutil.which("secret-tool")
    if binary:
        try:
            result = subprocess.run(
                [binary, "lookup", "service", SERVICE, "account", account_id],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        return _secret_file_path(account_id).read_text(encoding="utf-8")
    except OSError:
        return None


def delete_secret(account_id: str) -> None:
    binary = shutil.which("secret-tool")
    if binary:
        try:
            subprocess.run([binary, "clear", "service", SERVICE, "account", account_id],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    _secret_file_path(account_id).unlink(missing_ok=True)


# ---------------------------------------------------------------------
# pimsync config generation (icloud, caldav)
# ---------------------------------------------------------------------
def pimsync_config_path(account_id: str) -> Path:
    return PIMSYNC_CONFIG_DIR / f"omagenda-{account_id}.scfg"


def _safe_pair_name(account_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", account_id)


CONFLICT_RESOLVER = Path(__file__).resolve().parent.parent / "bin" / "omagenda"
_CONFLICT_LINE = re.compile(r"^([ \t]*)conflict_resolution\b.*$", re.MULTILINE)


def _scfg_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def conflict_resolution_directive(account_id: str) -> str:
    """The pair's conflict policy: the server version wins, and the local
    version is kept and announced, exactly as the Google bridge does.

    It cannot be `conflict_resolution keep b`. In pimsync 0.5.7 an item
    changed on both sides then makes `sync` report "0 conflicts detected"
    and fail with "etag mismatch when updating item", on that sync and every
    later one, while `resolve-conflicts` finds nothing to resolve, so one
    genuine conflict wedges the account for good. With a `cmd` resolver,
    `sync` reports the conflict and `pimsync resolve-conflicts` runs the
    command; `sync._sync_caldav` does that automatically."""
    return (f"conflict_resolution cmd {_scfg_quote(str(CONFLICT_RESOLVER))} "
            f"resolve-conflict --account {_scfg_quote(account_id)}")


def ensure_conflict_resolver(account_id: str) -> bool:
    """Bring an existing config's conflict_resolution line up to date, so
    configs written with `keep b` before the fix above stop wedging.
    Everything else in the file is left exactly as it was."""
    path = pimsync_config_path(account_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    wanted = conflict_resolution_directive(account_id)
    updated = _CONFLICT_LINE.sub(lambda match: match.group(1) + wanted, text)
    if updated == text:
        return False
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + "-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def generate_pimsync_config(account: dict, vdir_root: Path | None = None) -> Path:
    """Writes a self-contained pimsync config for one account: a local
    vdir/icalendar storage and a remote caldav storage, paired with
    `collections from b` so pimsync discovers every calendar the server
    offers and creates one subdirectory per calendar under the local
    path -- exactly the layout vdir.discover_calendars expects for a
    multi-calendar account (ARCHITECTURE.md §1).

    The conflict policy matches Omagenda's everywhere else (ARCHITECTURE.md
    §11): the remote wins and the local version is kept; see
    `conflict_resolution_directive` for why that is a `cmd` resolver.
    """
    from omagenda.vdir import resolve_vdir_root

    vdir_root = vdir_root or resolve_vdir_root()
    account_id = account["id"]
    account_type = account.get("type")
    if account_type == "icloud":
        url = account.get("url", "https://caldav.icloud.com/")
        username = account.get("username", "")
    elif account_type == "caldav":
        url = account["url"]
        username = account.get("username", "")
    else:
        raise ValueError(f"generate_pimsync_config: unsupported account type '{account_type}'")

    pair_name = _safe_pair_name(account_id)
    local_path = vdir_root / account_id
    local_path.mkdir(parents=True, exist_ok=True)
    PIMSYNC_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    lookup_cmd = f"secret-tool lookup service {SERVICE} account {account_id}"

    scfg = (
        f'status_path "{PIMSYNC_STATUS_DIR}/"\n'
        "\n"
        f"pair {pair_name} {{\n"
        f"\tstorage_a {pair_name}_local\n"
        f"\tstorage_b {pair_name}_remote\n"
        "\tcollections from b\n"
        f"\t{conflict_resolution_directive(account_id)}\n"
        "}\n"
        "\n"
        f"storage {pair_name}_local {{\n"
        "\ttype vdir/icalendar\n"
        f"\tpath {local_path}/\n"
        "\tfileext ics\n"
        "}\n"
        "\n"
        f"storage {pair_name}_remote {{\n"
        "\ttype caldav\n"
        f"\turl {url}\n"
        f"\tusername {username}\n"
        "\tpassword {\n"
        f"\t\tcmd {lookup_cmd}\n"
        "\t}\n"
        "}\n"
    )

    path = pimsync_config_path(account_id)
    PIMSYNC_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(scfg, encoding="utf-8")
    path.chmod(0o600)
    return path

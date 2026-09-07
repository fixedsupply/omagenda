"""Account management.

`omagenda account add|list|remove`: writes ~/.config/omagenda/config.toml
entries, stores credentials via the keyring (secret-tool), falling back to
a mode-0600 file when no keyring is available, and generates a pimsync
config for icloud/caldav accounts. See ARCHITECTURE.md §5 and §11.

Python's stdlib only reads TOML (`tomllib`), never writes it, so this
module owns a small writer scoped to exactly the shapes config.toml uses
(top-level scalars, a repeated [[accounts]] array-of-tables, and the
[sets]/[alarms] tables) -- not a general-purpose TOML serializer.

pimsync config syntax (scfg) verified against pimsync.conf(5), section by
section, since this machine has no sudo path to install pimsync and check
it directly (see AGENTS.md's Phase 1b note): the `password { cmd ... }`
block form, `storage <name> { type vdir/icalendar | caldav; ... }`, the
`pair` block's `storage_a`/`storage_b`/`collections`/`conflict_resolution`
directives, and the literal `conflict_resolution keep a|keep b` keywords
(not a made-up "remote_wins" or similar) all come from its own worked
examples, not guessed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from omagenda.doctor import CONFIG_PATH, read_config

SERVICE = "omagenda"
SECRETS_DIR = Path.home() / ".local" / "state" / "omagenda" / "secrets"
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

    for key in ("vdir", "default_calendar"):
        if key in config:
            lines.append(f"{key} = {_toml_value(config[key])}")
    if lines:
        lines.append("")

    for account in config.get("accounts", []):
        lines.append("[[accounts]]")
        for key, value in account.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    if config.get("sets"):
        lines.append("[sets]")
        for key, value in config["sets"].items():
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


def remove_account(account_id: str, path: Path | None = None) -> bool:
    config = read_config()
    accounts = config.get("accounts", [])
    remaining = [a for a in accounts if a["id"] != account_id]
    if len(remaining) == len(accounts):
        return False
    config["accounts"] = remaining
    write_config(config, path)
    delete_secret(account_id)
    pimsync_config_path(account_id).unlink(missing_ok=True)
    return True


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
        result = subprocess.run(
            [binary, "lookup", "service", SERVICE, "account", account_id],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    try:
        return _secret_file_path(account_id).read_text(encoding="utf-8")
    except OSError:
        return None


def delete_secret(account_id: str) -> None:
    binary = shutil.which("secret-tool")
    if binary:
        subprocess.run([binary, "clear", "service", SERVICE, "account", account_id], capture_output=True)
    _secret_file_path(account_id).unlink(missing_ok=True)


# ---------------------------------------------------------------------
# pimsync config generation (icloud, caldav)
# ---------------------------------------------------------------------
def pimsync_config_path(account_id: str) -> Path:
    return PIMSYNC_CONFIG_DIR / f"omagenda-{account_id}.scfg"


def _safe_pair_name(account_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", account_id)


def generate_pimsync_config(account: dict, vdir_root: Path | None = None) -> Path:
    """Writes a self-contained pimsync config for one account: a local
    vdir/icalendar storage and a remote caldav storage, paired with
    `collections from b` so pimsync discovers every calendar the server
    offers and creates one subdirectory per calendar under the local
    path -- exactly the layout vdir.discover_calendars expects for a
    multi-calendar account (ARCHITECTURE.md §1).

    `conflict_resolution keep b` matches Omagenda's stated policy
    everywhere else (ARCHITECTURE.md §11): the remote wins.
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
        "\tconflict_resolution keep b\n"
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

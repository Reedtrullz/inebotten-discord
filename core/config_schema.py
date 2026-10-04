"""Validated, private updates for the application's dotenv settings."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


_SUPPORTED_SETTINGS = {
    "DISCORD_USER_TOKEN",
    "DISCORD_EMAIL",
    "DISCORD_PASSWORD",
    "AI_PROVIDER",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "HERMES_API_URL",
    "GCAL_ENABLED",
    "GOOGLE_CALENDAR_ID",
}
_KEY_LINE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=)(.*)$")


def validate_settings(values: dict[str, str]) -> list[dict[str, str]]:
    """Return safe field/reason errors; never include submitted values."""
    errors: list[dict[str, str]] = []
    for field, value in values.items():
        if not isinstance(field, str) or field not in _SUPPORTED_SETTINGS:
            errors.append({"field": str(field), "reason": "unsupported setting"})
            continue
        if not isinstance(value, str):
            errors.append({"field": field, "reason": "must be text"})
            continue
        if "\n" in value or "\r" in value or "\x00" in value:
            errors.append({"field": field, "reason": "must be a single line"})
            continue
        if field in {"DISCORD_EMAIL", "DISCORD_PASSWORD"}:
            errors.append({"field": field, "reason": "email/password authentication is unsupported; use DISCORD_USER_TOKEN"})
        elif field == "DISCORD_USER_TOKEN" and not value:
            errors.append({"field": field, "reason": "must not be empty"})
        elif field == "OPENROUTER_API_KEY" and not value:
            errors.append({"field": field, "reason": "must not be empty"})
        elif field == "AI_PROVIDER" and value not in {"lm_studio", "openrouter"}:
            errors.append({"field": field, "reason": "unsupported value"})
        elif field == 'OPENROUTER_MODEL' and not value.strip():
            errors.append({'field': field, 'reason': 'must not be empty'})
        elif field == 'HERMES_API_URL':
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
                _ = parsed.port  # Reject malformed/out-of-range ports without echoing the URL.
            except ValueError:
                valid = False
            if not valid:
                errors.append({'field': field, 'reason': 'must be an HTTP(S) URL without embedded credentials'})
        elif field == "GCAL_ENABLED" and value.strip().lower() not in {"true", "false"}:
            errors.append({"field": field, "reason": "must be true or false"})
    return errors


def settings_path(project_root: Path | None = None) -> Path:
    """Return the active settings path, honoring explicit HERMES_HOME exclusively."""
    if "HERMES_HOME" in os.environ:
        configured_home = os.environ["HERMES_HOME"]
        if not configured_home.strip():
            raise ValueError("HERMES_HOME must name a configuration directory")
        return Path(configured_home).expanduser() / "discord" / ".env"
    return (project_root or Path.cwd()) / ".env"


def hermes_settings_path() -> Path:
    """Return the canonical desktop/console Hermes settings path."""
    from utils.json_storage import hermes_home_path

    if "HERMES_HOME" in os.environ and not os.environ["HERMES_HOME"].strip():
        raise ValueError("HERMES_HOME must name a configuration directory")
    return hermes_home_path() / "discord" / ".env"


def update_settings(path: Path, changes: dict[str, str]) -> None:
    """Atomically update selected dotenv keys while retaining all other text."""
    errors = validate_settings(changes)
    if errors:
        summary = "; ".join(f"{error['field']}: {error['reason']}" for error in errors)
        raise ValueError(summary)

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise ValueError("settings path must not be a symbolic link")
    if target.exists():
        if not target.is_file():
            raise ValueError("settings path must be a regular file")
        os.chmod(target, 0o600)
        with target.open('r', encoding='utf-8', newline='') as handle:
            existing = handle.read()
    else:
        existing = ""

    pending = dict(changes)
    output: list[str] = []
    for line in existing.splitlines(keepends=True):
        match = _KEY_LINE.match(line.rstrip("\r\n"))
        if match and match.group(2) in changes:
            key = match.group(2)
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            _value, comment = _split_inline_comment(match.group(4))
            output.append(f"{match.group(1)}{key}{match.group(3)}{_format_value(changes[key])}{comment}{newline}")
            pending.pop(key, None)
        else:
            output.append(line)
    for key, value in pending.items():
        if output and not output[-1].endswith(("\n", "\r")):
            output.append("\n")
        output.append(f"{key}={_format_value(value)}\n")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _format_value(value: str) -> str:
    if value and re.search(r"[\s#'\"\\$]", value):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return value


def _split_inline_comment(value: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif quote and character == quote:
            quote = None
        elif not quote and character in {"'", '"'}:
            quote = character
        elif not quote and character == "#" and (index == 0 or value[index - 1].isspace()):
            stripped_value = value[:index].rstrip()
            return stripped_value, value[len(stripped_value):]
    return value, ""

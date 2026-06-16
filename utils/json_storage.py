#!/usr/bin/env python3
"""Small JSON persistence helpers shared by local file-backed managers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def hermes_home_path() -> Path:
    """Return the configured Hermes home, defaulting to ~/.hermes."""
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def hermes_discord_data_dir() -> Path:
    """Return the canonical Hermes Discord data directory."""
    data_dir = hermes_home_path() / "discord" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def read_json(path: str | Path, default: Any) -> Any:
    """Read JSON from path, returning default if the file is missing or invalid."""
    json_path = Path(path)
    if not json_path.exists():
        return default
    try:
        with json_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def write_json_atomic(path: str | Path, data: Any, *, indent: int | None = 2) -> None:
    """Write JSON via temp file + atomic replace to avoid partial files."""
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{json_path.name}.",
        suffix=".tmp",
        dir=str(json_path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=indent)
        mode = json_path.stat().st_mode & 0o777 if json_path.exists() else 0o600
        os.chmod(temp_path, mode)
        os.replace(temp_path, json_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def hermes_discord_data_path(filename: str, *, legacy_filename: str | None = None) -> Path:
    """Return canonical Hermes Discord data path, migrating a legacy file if needed."""
    hermes_home = hermes_home_path()
    data_dir = hermes_discord_data_dir()

    target = data_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = hermes_home / "discord" / (legacy_filename or filename)

    if legacy != target and legacy.exists() and not target.exists():
        try:
            os.replace(legacy, target)
        except OSError:
            return legacy

    return target

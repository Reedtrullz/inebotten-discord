#!/usr/bin/env python3
"""Small JSON persistence helpers shared by local file-backed managers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
    temp_path = json_path.with_name(f".{json_path.name}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=indent)
        os.replace(temp_path, json_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def hermes_discord_data_path(filename: str, *, legacy_filename: str | None = None) -> Path:
    """Return canonical ~/.hermes/discord/data path, migrating a legacy file if needed."""
    data_dir = Path.home() / ".hermes" / "discord" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    target = data_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = Path.home() / ".hermes" / "discord" / (legacy_filename or filename)

    if legacy != target and legacy.exists() and not target.exists():
        try:
            os.replace(legacy, target)
        except OSError:
            return legacy

    return target

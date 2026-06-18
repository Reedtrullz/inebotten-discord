#!/usr/bin/env python3
"""User-facing memory control regressions."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from memory.user_memory import UserMemory


def _run(coro):
    return asyncio.run(coro)


def test_format_user_memory_for_user_shows_stored_fields():
    with TemporaryDirectory() as tmp:
        memory = UserMemory(storage_path=Path(tmp) / "memory.json")
        _run(memory.setup())
        _run(memory.set_location("u1", "Trondheim"))
        _run(memory.add_interest("u1", "RBK"))

        text = _run(memory.format_user_memory_for_user("u1", "Reidar"))

    assert "Dette husker jeg om deg" in text
    assert "Trondheim" in text
    assert "RBK" in text
    assert "slett minnet mitt bekreft" in text


def test_export_user_memory_does_not_create_missing_user():
    with TemporaryDirectory() as tmp:
        memory = UserMemory(storage_path=Path(tmp) / "memory.json")
        _run(memory.setup())

        exported = _run(memory.export_user_memory("missing"))

    assert exported == {}
    assert "missing" not in memory.memory


def test_delete_user_memory_persists_and_does_not_touch_other_users():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "memory.json"
        memory = UserMemory(storage_path=path)
        _run(memory.setup())
        _run(memory.set_location("u1", "Trondheim"))
        _run(memory.set_location("u2", "Oslo"))

        deleted = _run(memory.delete_user_memory("u1"))

        stored = json.loads(path.read_text(encoding="utf-8"))

    assert deleted is True
    assert "u1" not in stored
    assert stored["u2"]["location"] == "Oslo"

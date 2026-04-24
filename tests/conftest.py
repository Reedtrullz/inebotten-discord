"""Shared test stubs for optional Discord dependency."""

import inspect
import os
import sys
from types import SimpleNamespace

import pytest


os.environ.setdefault("DISCORD_USER_TOKEN", "test_token_1234567890.abc.defghijklmnopqrstuvwxyz")

try:
    import discord  # noqa: F401
except ModuleNotFoundError:
    class _FakeDiscordClient:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeDiscordError(Exception):
        def __init__(self, *args, status=None, **kwargs):
            super().__init__(*args)
            self.status = status

    class _FakeActivity:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    sys.modules["discord"] = SimpleNamespace(
        Client=_FakeDiscordClient,
        DMChannel=type("DMChannel", (), {}),
        GroupChannel=type("GroupChannel", (), {}),
        TextChannel=type("TextChannel", (), {}),
        Message=type("Message", (), {}),
        Status=SimpleNamespace(
            online="online",
            idle="idle",
            dnd="dnd",
            invisible="invisible",
            offline="offline",
        ),
        ActivityType=SimpleNamespace(
            playing="playing",
            watching="watching",
            listening="listening",
            competing="competing",
        ),
        Activity=_FakeActivity,
        errors=SimpleNamespace(
            Forbidden=type("Forbidden", (_FakeDiscordError,), {}),
            HTTPException=type("HTTPException", (_FakeDiscordError,), {}),
        ),
    )


def pytest_collection_modifyitems(items):
    for item in items:
        if item.name == "test_remaining" and item.module.__name__.endswith("test_advanced_dialect"):
            item.add_marker(pytest.mark.skip(reason="external LM Studio dialect smoke test"))
            continue
        obj = getattr(item, "obj", None)
        if obj is not None and inspect.iscoroutinefunction(obj):
            item.add_marker(pytest.mark.asyncio)

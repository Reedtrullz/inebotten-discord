"""Shared test stubs for optional Discord dependency."""

import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


_TEST_HOME = Path(tempfile.mkdtemp(prefix="inebotten-tests-"))
os.environ["HOME"] = str(_TEST_HOME)
os.environ.setdefault("HERMES_HOME", str(_TEST_HOME / ".hermes"))
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


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_HOME, ignore_errors=True)

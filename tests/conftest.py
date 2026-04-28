"""Shared test stubs for optional Discord dependency."""

from collections.abc import AsyncGenerator
from importlib import import_module
import os
import shutil
import sys
import tempfile
import threading
import time
import asyncio
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Generator

import pytest
import pytest_asyncio

from web_console.server import ConsoleServer


_REAL_HOME = Path.home()
_TEST_HOME = Path(tempfile.mkdtemp(prefix="inebotten-tests-"))
os.environ["HOME"] = str(_TEST_HOME)
_ = os.environ.setdefault("HERMES_HOME", str(_TEST_HOME / ".hermes"))
_ = os.environ.setdefault("DISCORD_USER_TOKEN", "test_token_1234567890.abc.defghijklmnopqrstuvwxyz")
# Point Playwright to real browser cache (tests override HOME)
# macOS: ~/Library/Caches/ms-playwright, Linux: ~/.cache/ms-playwright
_pw_cache_mac = _REAL_HOME / "Library" / "Caches" / "ms-playwright"
_pw_cache_linux = _REAL_HOME / ".cache" / "ms-playwright"
_pw_cache = _pw_cache_mac if _pw_cache_mac.exists() else _pw_cache_linux
if _pw_cache.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_pw_cache))

HOST = "127.0.0.1"
PORT = 18081
API_KEY = "test-key-frontend"

try:
    import discord  # pyright: ignore[reportMissingImports]  # noqa: F401
except ModuleNotFoundError:
    class _FakeDiscordClient:
        def __init__(self, *args: object, **kwargs: object):
            pass

    class _FakeDiscordError(Exception):
        def __init__(self, *args: object, status: object | None = None, **kwargs: object):
            super().__init__(*args)
            self.status = status

    class _FakeActivity:
        def __init__(self, *args: object, **kwargs: object):
            self.args = args
            self.kwargs = kwargs

    discord_stub = ModuleType("discord")
    setattr(discord_stub, "Client", _FakeDiscordClient)
    setattr(discord_stub, "DMChannel", type("DMChannel", (), {}))
    setattr(discord_stub, "GroupChannel", type("GroupChannel", (), {}))
    setattr(discord_stub, "TextChannel", type("TextChannel", (), {}))
    setattr(discord_stub, "Message", type("Message", (), {}))
    setattr(
        discord_stub,
        "Status",
        SimpleNamespace(
            online="online",
            idle="idle",
            dnd="dnd",
            invisible="invisible",
            offline="offline",
        ),
    )
    setattr(
        discord_stub,
        "ActivityType",
        SimpleNamespace(
            playing="playing",
            watching="watching",
            listening="listening",
            competing="competing",
        ),
    )
    setattr(discord_stub, "Activity", _FakeActivity)
    setattr(
        discord_stub,
        "errors",
        SimpleNamespace(
            Forbidden=type("Forbidden", (_FakeDiscordError,), {}),
            HTTPException=type("HTTPException", (_FakeDiscordError,), {}),
        ),
    )
    sys.modules["discord"] = discord_stub


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        module_name = getattr(getattr(item, "module", None), "__name__", "")
        if item.name == "test_remaining" and module_name.endswith("test_advanced_dialect"):
            item.add_marker(pytest.mark.skip(reason="external LM Studio dialect smoke test"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    shutil.rmtree(_TEST_HOME, ignore_errors=True)


@pytest.fixture
def console_server() -> Generator[ConsoleServer, None, None]:
    """Start ConsoleServer on an ephemeral port to avoid conflicts."""
    server = ConsoleServer(host=HOST, port=0, api_key=API_KEY)
    loop_container: list[asyncio.AbstractEventLoop] = []

    def run_loop() -> None:
        loop = asyncio.new_event_loop()
        loop_container.append(loop)
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()

    while not loop_container:
        time.sleep(0.01)
    loop = loop_container[0]

    future = asyncio.run_coroutine_threadsafe(server.start(), loop)
    future.result(timeout=5)
    time.sleep(0.1)

    try:
        yield server
    finally:
        future = asyncio.run_coroutine_threadsafe(server.stop(), loop)
        future.result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


@pytest.fixture
def api_key() -> str:
    return API_KEY


@pytest.fixture
def frontend_base_url() -> str:
    return f"http://{HOST}:{PORT}"


@pytest_asyncio.fixture
async def auth_page(console_server: ConsoleServer) -> AsyncGenerator[object, None]:
    """Authenticated Playwright page for future frontend tests."""
    async_playwright = import_module("playwright.async_api").async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(f"http://{HOST}:{PORT}/login")
        await page.fill('input[name="api_key"]', API_KEY)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"http://{HOST}:{PORT}/")
        try:
            yield page
        finally:
            await context.close()
            await browser.close()

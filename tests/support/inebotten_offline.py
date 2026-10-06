"""Early bootstrap, not an OS sandbox. PYTEST_DONT_REWRITE"""

import atexit
import errno
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import tempfile


_BOOTSTRAPPED = False
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _loopback(host):
    if host in ("localhost", b"localhost"):
        return True
    try:
        return ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host).is_loopback
    except (ValueError, TypeError):
        return False


def _check_address(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
        raise OSError(errno.ENETUNREACH, "external network disabled in offline tests")


def _connect(sock, address):
    _check_address(sock, address)
    return _ORIGINAL_CONNECT(sock, address)


def _connect_ex(sock, address):
    _check_address(sock, address)
    return _ORIGINAL_CONNECT_EX(sock, address)


def _getaddrinfo(host, *args, **kwargs):
    if host is not None and not _loopback(host):
        raise OSError(errno.ENETUNREACH, "external DNS disabled in offline tests")
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def bootstrap():
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    if os.environ.get("INEBOTTEN_OFFLINE_TESTS") != "1":
        base = Path(__file__).resolve().parents[2] / ".superpowers" / "test-runs"
        base.mkdir(parents=True, exist_ok=True)
        runtime = Path(tempfile.mkdtemp(prefix="direct-", dir=base))
        atexit.register(shutil.rmtree, runtime, ignore_errors=True)
        # Direct pytest is safe too; only this test process gets new paths.
        for name in tuple(os.environ):
            if name.startswith(("DISCORD_", "OPENROUTER_", "HERMES_", "GOOGLE_", "GCAL_", "CONSOLE_", "LM_STUDIO_", "TAVILY_", "BROWSERBASE_")):
                os.environ.pop(name, None)
        os.environ.update(HOME=str(runtime / "home"), HERMES_HOME=str(runtime / "hermes"))
        Path(os.environ["HOME"]).mkdir()
    if os.environ.get("INEBOTTEN_LIVE_ACCOUNT") != "1":
        os.environ.setdefault(
            "DISCORD_USER_TOKEN", "test_token_1234567890.abc.defghijklmnopqrstuvwxyz"
        )
    if os.environ.get("INEBOTTEN_LIVE_PROVIDER") != "1" and os.environ.get("INEBOTTEN_LIVE_ACCOUNT") != "1":
        socket.socket.connect = _connect
        socket.socket.connect_ex = _connect_ex
        socket.getaddrinfo = _getaddrinfo


def pytest_collection_modifyitems(config, items):
    import pytest
    for marker, flag in (
        ("live_provider", "INEBOTTEN_LIVE_PROVIDER"),
        ("live_account", "INEBOTTEN_LIVE_ACCOUNT"),
    ):
        if os.environ.get(flag) != "1":
            for item in items:
                if item.get_closest_marker(marker):
                    item.add_marker(pytest.mark.skip(reason=f"{marker} requires explicit opt-in"))


bootstrap()

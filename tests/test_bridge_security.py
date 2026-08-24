"""Focused protocol and boundary tests for the local Hermes bridge."""

from __future__ import annotations

import asyncio
import json

import pytest

from ai import hermes_bridge_server as bridge


async def _request(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


@pytest.fixture
async def bridge_server(monkeypatch):
    server_obj = bridge.HermesBridgeServer()

    async def no_lm_studio():
        return False

    server_obj._check_lm_studio = no_lm_studio
    server = await asyncio.start_server(server_obj.handle_request, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()
        await server_obj.cleanup()


@pytest.mark.asyncio
async def test_root_does_not_disclose_upstream_url(bridge_server):
    response = await _request(
        bridge_server,
        b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
    )

    body = json.loads(response.split(b"\r\n\r\n", 1)[1])
    assert body["service"] == "Hermes Bridge Server"
    assert "lm_studio" not in body
    assert bridge.LM_STUDIO_URL.encode() not in response

def test_chat_schema_keeps_connector_fields_but_rejects_unknown_data():
    payload = {
        "message": "hei",
        "author_name": "selfbot",
        "channel_type": "DM",
        "timestamp": "2026-08-18T12:00:00",
        "is_mention": True,
        "temperature": 0.7,
        "max_tokens": 200,
    }
    assert bridge.HermesBridgeServer._validate_chat_payload(payload) == payload

    with pytest.raises(ValueError, match="Unsupported payload field"):
        bridge.HermesBridgeServer._validate_chat_payload({**payload, "debug": True})

    with pytest.raises(ValueError, match="message is too long"):
        bridge.HermesBridgeServer._validate_chat_payload(
            {"message": "x" * (bridge.MAX_MESSAGE_CHARS + 1)}
        )


def test_api_key_auth_uses_constant_time_compare(monkeypatch):
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "test-secret")

    assert bridge.HermesBridgeServer._authorized({"x-api-key": "test-secret"})
    assert bridge.HermesBridgeServer._authorized(
        {"authorization": "Bearer test-secret"}
    )
    assert not bridge.HermesBridgeServer._authorized({"x-api-key": "wrong"})
    assert not bridge.HermesBridgeServer._authorized({})


def test_non_loopback_bind_requires_key(monkeypatch):
    monkeypatch.setattr(bridge, "HOST", "0.0.0.0")
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "")

    with pytest.raises(RuntimeError, match="HERMES_BRIDGE_API_KEY"):
        bridge.validate_runtime_config()


@pytest.mark.asyncio
async def test_unauthorized_request_does_not_consume_rate_quota(monkeypatch):
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "test-secret")
    server_obj = bridge.HermesBridgeServer()
    called = 0

    async def allow(_writer):
        nonlocal called
        called += 1
        return True

    server_obj._allow_request = allow
    server = await asyncio.start_server(server_obj.handle_request, "127.0.0.1", 0)
    try:
        response = await _request(
            server.sockets[0].getsockname()[1],
            b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
    finally:
        server.close()
        await server.wait_closed()
        await server_obj.cleanup()

    assert b"401 Unauthorized" in response
    assert called == 0


@pytest.mark.asyncio
async def test_rate_limit_peer_map_has_hard_cap(monkeypatch):
    monkeypatch.setattr(bridge, "MAX_RATE_LIMIT_PEERS", 2)
    server_obj = bridge.HermesBridgeServer()

    class Writer:
        def __init__(self, peer):
            self.peer = peer

        def get_extra_info(self, name):
            return (self.peer, 1234) if name == "peername" else None

    assert await server_obj._allow_request(Writer("one"))
    assert await server_obj._allow_request(Writer("two"))
    assert not await server_obj._allow_request(Writer("three"))
    assert len(server_obj._rate_history) == 2


@pytest.mark.asyncio
async def test_header_read_timeout_returns_generic_error(monkeypatch):
    monkeypatch.setattr(bridge, "HEADER_READ_TIMEOUT", 0.05)
    server_obj = bridge.HermesBridgeServer()
    server = await asyncio.start_server(server_obj.handle_request, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        response = await asyncio.wait_for(reader.read(), timeout=1)
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        await server_obj.cleanup()

    assert b"408 Request Timeout" in response
    assert b"Traceback" not in response
    assert bridge.LM_STUDIO_URL.encode() not in response

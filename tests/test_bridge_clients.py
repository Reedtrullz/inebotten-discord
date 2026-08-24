"""Offline credential propagation tests for built-in bridge clients."""

from ai.hermes_connector import HermesConnector


def test_connector_session_includes_configured_bridge_key(monkeypatch):
    captured = {}

    class Session:
        closed = False

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("ai.hermes_connector.aiohttp.ClientSession", Session)
    connector = HermesConnector(api_key="test-bridge-key")
    session = __import__("asyncio").run(connector._get_session())
    assert session is not None
    assert captured["headers"]["X-API-Key"] == "test-bridge-key"


def test_combined_runner_health_headers_follow_environment(monkeypatch):
    monkeypatch.setenv("HERMES_BRIDGE_API_KEY", "runner-key")
    import importlib
    from scripts import run_both

    reloaded = importlib.reload(run_both)
    assert reloaded.BRIDGE_REQUEST_HEADERS == {"X-API-Key": "runner-key"}

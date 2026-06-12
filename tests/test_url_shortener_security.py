from __future__ import annotations

import http.client

from features.url_shortener import URLShortener


class FakeResponse:
    status = 200

    def read(self):
        return b"https://tinyurl.com/example"


class FakeHTTPSConnection:
    instances = []

    def __init__(self, host, timeout=10):
        self.host = host
        self.timeout = timeout
        self.method = None
        self.path = None
        self.headers = None
        self.closed = False
        self.instances.append(self)

    def request(self, method, path, headers=None):
        self.method = method
        self.path = path
        self.headers = headers or {}

    def getresponse(self):
        return FakeResponse()

    def close(self):
        self.closed = True


def test_tinyurl_api_uses_https(monkeypatch):
    FakeHTTPSConnection.instances = []
    monkeypatch.setattr(http.client, "HTTPSConnection", FakeHTTPSConnection)

    result = URLShortener().shorten_url("https://example.com/private?token=secret")

    assert result["short"] == "https://tinyurl.com/example"
    assert FakeHTTPSConnection.instances
    connection = FakeHTTPSConnection.instances[0]
    assert connection.host == "tinyurl.com"
    assert connection.method == "GET"
    assert connection.path.startswith("/api-create.php?")
    assert connection.closed is True

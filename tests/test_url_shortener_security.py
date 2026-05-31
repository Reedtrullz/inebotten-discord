from __future__ import annotations

import urllib.request

from features.url_shortener import URLShortener


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"https://tinyurl.com/example"


def test_tinyurl_api_uses_https(monkeypatch):
    requested_urls = []

    def fake_urlopen(url, timeout=10):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = URLShortener().shorten_url("https://example.com/private?token=secret")

    assert result["short"] == "https://tinyurl.com/example"
    assert requested_urls
    assert requested_urls[0].startswith("https://tinyurl.com/api-create.php?")

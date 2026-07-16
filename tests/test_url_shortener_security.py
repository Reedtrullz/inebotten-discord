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


def test_parser_preserves_path_query_fragment_and_action_words():
    url = "https://example.com/path/then/delete?q=fish%20and%20chips#result"

    result = URLShortener().parse_shorten_command(f"shorten {url}")

    assert result == {"url": url}


def test_parser_accepts_bounded_natural_link_shortening_frames():
    manager = URLShortener()
    url = "https://example.com/a/b"

    for text in (
        f"make this URL shorter: {url}",
        f"could you shorten this link for me? {url}",
        f"kan du korte ned denne lenken {url}",
    ):
        assert manager.parse_shorten_command(text) == {"url": url}

    for text in (
        "make this URL shorter",
        "could you not shorten this link for me? https://example.com/a/b",
        "Ola said make this URL shorter: https://example.com/a/b",
    ):
        assert manager.parse_shorten_command(text) is None


def test_parser_preserves_ambiguous_trailing_url_punctuation_losslessly():
    manager = URLShortener()

    assert manager.parse_shorten_command(
        "Kan du forkorte https://example.com/a_(b)?"
    ) == {"url": "https://example.com/a_(b)?"}
    assert manager.parse_shorten_command(
        "Forkort https://example.com/a_(b))."
    ) == {"url": "https://example.com/a_(b))."}


def test_parser_removes_only_leading_invocation_not_url_data():
    url = "https://example.com/@inebotten?q=@inebotten!"

    result = URLShortener().parse_shorten_command(
        f"@inebotten, forkort {url}"
    )

    assert result == {"url": url}


def test_parser_accepts_conditional_courtesy_without_comma_dependency():
    url = "https://example.com/a"
    manager = URLShortener()

    for text in (
        f"kan du hvis du har tid forkorte {url}",
        f"could you if you have time shorten {url}",
        f"if you have time could you shorten {url}",
    ):
        assert manager.parse_shorten_command(text) == {"url": url}

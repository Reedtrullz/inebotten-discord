#!/usr/bin/env python3
"""Search result provenance regressions."""

import logging
import sys
from types import ModuleType

import pytest

from features.browser_manager import BrowserManager
from features.search_manager import SearchManager, detect_search_intent


def test_normalize_result_adds_source_metadata():
    manager = SearchManager()

    result = manager._normalize_result(
        {
            "title": "Kilde",
            "url": "https://example.com",
            "content": "Kort tekst",
            "published_at": "2026-06-17",
        },
        "tavily",
    )

    assert result["title"] == "Kilde"
    assert result["url"] == "https://example.com"
    assert result["href"] == "https://example.com"
    assert result["provider"] == "tavily"
    assert result["published_at"] == "2026-06-17"
    assert result["freshness"] == "published"
    assert result["fetched_at"]


def test_format_results_for_ai_requires_citations_and_marks_missing_published_date():
    manager = SearchManager()
    result = manager._normalize_result(
        {"title": "Kilde uten dato", "url": "https://example.com", "body": "Fakta"},
        "duckduckgo",
    )

    formatted = manager.format_results_for_ai([result])

    assert "Oppgi kilde" in formatted
    assert "Publisert: ikke tilgjengelig" in formatted
    assert "Kilde: https://example.com" in formatted
    assert "Friskhet: fetched_only" in formatted


def test_no_results_copy_does_not_pretend_live_verification():
    formatted = SearchManager().format_results_for_ai([])

    assert "fant ingen ferske kilder" in formatted
    assert "ikke-verifisert" in formatted


@pytest.mark.asyncio
async def test_search_failover_logs_neither_query_nor_exception_body(
    monkeypatch,
    capsys,
):
    query_canary = "RAW_QUERY_SECRET_CANARY"
    exception_canary = "PROVIDER_EXCEPTION_SECRET_CANARY"

    tavily = ModuleType("tavily")

    class FailingTavily:
        def __init__(self, **_kwargs):
            raise RuntimeError(exception_canary)

    tavily.TavilyClient = FailingTavily
    google = ModuleType("googlesearch")

    def failing_google(*_args, **_kwargs):
        raise RuntimeError(exception_canary)

    google.search = failing_google
    duck = ModuleType("duckduckgo_search")

    class FailingDuck:
        def __init__(self):
            raise RuntimeError(exception_canary)

    duck.DDGS = FailingDuck
    monkeypatch.setitem(sys.modules, "tavily", tavily)
    monkeypatch.setitem(sys.modules, "googlesearch", google)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", duck)

    manager = SearchManager()
    manager.tavily_api_key = "configured"
    assert await manager.search(query_canary) == []

    output = capsys.readouterr().out
    assert query_canary not in output
    assert exception_canary not in output


@pytest.mark.asyncio
async def test_browser_status_log_never_contains_url(capsys):
    url_canary = "https://example.invalid/?state=URL_SECRET_CANARY"
    manager = BrowserManager()
    manager.api_key = "configured"
    manager.project_id = "configured"

    assert await manager.fetch_page_content(url_canary) is None

    output = capsys.readouterr().out
    assert url_canary not in output
    assert "URL_SECRET_CANARY" not in output


def test_search_intent_debug_logs_never_contain_raw_content(caplog):
    canary = "SEARCH_INTENT_RAW_SECRET_CANARY"
    with caplog.at_level(logging.DEBUG):
        assert detect_search_intent(f"Hva synes du om {canary}?") is None

    assert canary not in caplog.text

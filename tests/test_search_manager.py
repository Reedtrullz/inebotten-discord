#!/usr/bin/env python3
"""Search result provenance regressions."""

from features.search_manager import SearchManager


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

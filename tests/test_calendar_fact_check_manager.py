import json
import logging

import pytest

from ai.calendar_fact_check_extractor import CalendarFactCheckExtraction
from core.calendar_fact_check_evidence import (
    CalendarEvidenceStatus,
    parse_source_findings,
)
from core.calendar_fact_check_store import CalendarFactCheckTarget
from features.calendar_fact_check_manager import CalendarFactCheckManager
from features.search_manager import SearchAttempt


TARGET = CalendarFactCheckTarget(
    "calendar-1", "revision", "Rosenborg - Fredrikstad", "26.07.2026", "09:00"
)


class Search:
    def __init__(self, attempt):
        self.attempt = attempt
        self.calls = []

    async def search_with_status(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.attempt


class Browser:
    def __init__(self, content=None, error=False):
        self.content = content
        self.error = error
        self.calls = []

    async def fetch_page_content(self, url):
        self.calls.append(url)
        if self.error:
            raise RuntimeError("FETCH_EXCEPTION_CANARY")
        return self.content


class Extractor:
    def __init__(self, status="ok", candidate=("27.07.2026", "19:00")):
        self.status = status
        self.candidate = candidate
        self.evidence = None

    async def extract(self, evidence):
        self.evidence = evidence
        if self.status == "unavailable":
            return CalendarFactCheckExtraction("unavailable")
        date, time = self.candidate
        row = evidence[0]
        raw = json.dumps({"findings": [{
            "source": 1,
            "date": date,
            "time": time,
            "excerpt": row.body,
            "explanation": "Kampstart.",
        }]})
        return CalendarFactCheckExtraction(
            "ok", parse_source_findings(raw, evidence)
        )


def result(url="https://fotball.no/kamp", body="Kamp 27.07.2026 kl. 19:00"):
    return {
        "title": "Kamp",
        "url": url,
        "body": body,
        "provider": "google",
        "fetched_at": "2026-07-16T18:00:00Z",
        "published_at": None,
    }


@pytest.mark.asyncio
async def test_manager_bounds_search_fetch_and_supports_trusted_change():
    rows = tuple(result(f"https://fotball.no/kamp/{i}") for i in range(4))
    search = Search(SearchAttempt("ok", rows, "google"))
    browser = Browser("x" * 7_000)
    extractor = Extractor()
    decision = await CalendarFactCheckManager(
        search_manager=search, browser_manager=browser, extractor=extractor
    ).investigate(TARGET)
    assert decision.status is CalendarEvidenceStatus.SUPPORTED
    assert search.calls[0][1] == {"max_results": 3, "region": "no-no"}
    assert len(browser.calls) == 3
    assert len(extractor.evidence) == 3
    assert all(len(row.page_content) == 6_000 for row in extractor.evidence)
    query = search.calls[0][0]
    assert TARGET.title in query and "2026" in query and TARGET.date in query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempt", "status"),
    (
        (SearchAttempt("unavailable", (), None), CalendarEvidenceStatus.UNAVAILABLE),
        (SearchAttempt("empty", (), "google"), CalendarEvidenceStatus.INSUFFICIENT),
        (SearchAttempt("ok", (result("http://127.0.0.1/private"),), "google"), CalendarEvidenceStatus.INSUFFICIENT),
    ),
)
async def test_manager_fail_closed_search_outcomes(attempt, status):
    decision = await CalendarFactCheckManager(
        search_manager=Search(attempt), browser_manager=Browser(), extractor=Extractor()
    ).investigate(TARGET)
    assert decision.status is status


@pytest.mark.asyncio
async def test_fetch_failure_uses_snippet_and_extractor_failure_is_unavailable():
    attempt = SearchAttempt("ok", (result(),), "google")
    supported = await CalendarFactCheckManager(
        search_manager=Search(attempt), browser_manager=Browser(error=True), extractor=Extractor()
    ).investigate(TARGET)
    unavailable = await CalendarFactCheckManager(
        search_manager=Search(attempt), browser_manager=Browser(), extractor=Extractor("unavailable")
    ).investigate(TARGET)
    assert supported.status is CalendarEvidenceStatus.SUPPORTED
    assert unavailable.status is CalendarEvidenceStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_manager_logs_only_bounded_provider_outcome_and_site_label(caplog):
    canaries = "TITLE_CANARY QUERY_CANARY URL_CANARY PAGE_CANARY EXCERPT_CANARY"
    target = CalendarFactCheckTarget("id", "rev", canaries, "26.07.2026", "09:00")
    attempt = SearchAttempt("ok", (result("https://untrusted.example/path"),), "google")
    with caplog.at_level(logging.INFO):
        await CalendarFactCheckManager(
            search_manager=Search(attempt), browser_manager=Browser("PAGE_CANARY"), extractor=Extractor()
        ).investigate(target)
    for canary in canaries.split():
        assert canary not in caplog.text
    assert "FETCH_EXCEPTION_CANARY" not in caplog.text

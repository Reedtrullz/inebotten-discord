"""Bounded public investigation for one frozen calendar target."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlsplit

from ai.calendar_fact_check_extractor import CalendarFactCheckExtractor
from core.calendar_fact_check_evidence import (
    CalendarEvidenceDecision,
    CalendarEvidenceStatus,
    CalendarSearchEvidence,
    CalendarSourcePolicy,
    reduce_source_findings,
)
from core.calendar_fact_check_store import CalendarFactCheckTarget
from features.browser_manager import BrowserManager
from features.search_manager import SearchManager
from utils.sanitizer import sanitize_url


logger = logging.getLogger(__name__)


def build_calendar_fact_check_query(target: CalendarFactCheckTarget) -> str:
    year = target.date.rsplit(".", 1)[-1]
    return f'"{target.title}" tidspunkt {year} {target.date}'


class CalendarFactCheckManager:
    def __init__(
        self,
        *,
        search_manager: SearchManager,
        browser_manager: BrowserManager,
        extractor: CalendarFactCheckExtractor,
        source_policy: CalendarSourcePolicy | None = None,
    ) -> None:
        self.search_manager = search_manager
        self.browser_manager = browser_manager
        self.extractor = extractor
        self.source_policy = source_policy or CalendarSourcePolicy()

    async def investigate(
        self,
        target: CalendarFactCheckTarget,
    ) -> CalendarEvidenceDecision:
        attempt = await self.search_manager.search_with_status(
            build_calendar_fact_check_query(target),
            max_results=3,
            region="no-no",
        )
        provider = attempt.provider if attempt.provider in {
            "tavily", "google", "duckduckgo"
        } else "other"
        if attempt.status == "unavailable":
            logger.info(
                "calendar_fact_check_investigation outcome=unavailable provider=%s count=0",
                provider,
            )
            return CalendarEvidenceDecision(CalendarEvidenceStatus.UNAVAILABLE)
        evidence = await self._collect_public_evidence(attempt.results[:3])
        if not evidence:
            logger.info(
                "calendar_fact_check_investigation outcome=insufficient provider=%s count=0",
                provider,
            )
            return CalendarEvidenceDecision(CalendarEvidenceStatus.INSUFFICIENT)
        extraction = await self.extractor.extract(evidence)
        if extraction.status == "unavailable":
            logger.info(
                "calendar_fact_check_investigation outcome=unavailable provider=%s count=%d",
                provider,
                len(evidence),
            )
            return CalendarEvidenceDecision(CalendarEvidenceStatus.UNAVAILABLE)
        decision = reduce_source_findings(
            extraction.findings,
            self.source_policy,
            current=(target.date, target.time),
        )
        labels = ",".join(
            sorted({self._safe_site_label(row.url) for row in extraction.findings})
        ) or "none"
        logger.info(
            "calendar_fact_check_investigation outcome=%s provider=%s count=%d sites=%s",
            decision.status.value,
            provider,
            len(evidence),
            labels,
        )
        return decision

    async def _collect_public_evidence(
        self,
        results: tuple[dict, ...],
    ) -> tuple[CalendarSearchEvidence, ...]:
        evidence: list[CalendarSearchEvidence] = []
        total_page_chars = 0
        for result in results[:3]:
            if not isinstance(result, dict):
                continue
            safe_url = sanitize_url(str(result.get("url") or result.get("href") or ""))
            if not safe_url:
                continue
            page_content = None
            if total_page_chars < 18_000:
                try:
                    fetched = await self.browser_manager.fetch_page_content(safe_url)
                except Exception:
                    fetched = None
                if isinstance(fetched, str) and fetched.strip():
                    page_content = " ".join(fetched.split())[:6_000]
                    total_page_chars += len(page_content)
            provider = str(result.get("provider") or "other").casefold()
            if provider not in {"tavily", "google", "duckduckgo"}:
                provider = "other"
            evidence.append(CalendarSearchEvidence(
                index=len(evidence) + 1,
                title=" ".join(str(result.get("title") or "Søkeresultat").split())[:500],
                url=safe_url,
                body=" ".join(str(result.get("body") or "").split())[:6_000],
                provider=provider,
                fetched_at=str(result.get("fetched_at") or ""),
                published_at=(
                    str(result["published_at"])
                    if result.get("published_at") is not None
                    else None
                ),
                page_content=page_content,
            ))
        return tuple(evidence)

    def _safe_site_label(self, url: str) -> str:
        host = (urlsplit(url).hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        trusted = next((
            domain
            for domain in self.source_policy.trusted_domains
            if host == domain or host.endswith("." + domain)
        ), None)
        return trusted or hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]

"""Strict public-evidence contracts for calendar schedule fact checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import re
from urllib.parse import urlsplit


class CalendarEvidenceStatus(str, Enum):
    SUPPORTED = "supported"
    CURRENT = "current"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CalendarSearchEvidence:
    index: int
    title: str
    url: str
    body: str
    provider: str
    fetched_at: str
    published_at: str | None
    page_content: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarSourceFinding:
    source: int
    site_key: str
    trusted_domain: str | None
    date: str
    time: str
    excerpt: str
    explanation: str
    url: str


@dataclass(frozen=True, slots=True)
class CalendarEvidenceDecision:
    status: CalendarEvidenceStatus
    date: str | None = None
    time: str | None = None
    supporting: tuple[CalendarSourceFinding, ...] = ()
    conflicting: tuple[CalendarSourceFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarSourcePolicy:
    trusted_domains: frozenset[str] = frozenset({
        "fotball.no",
        "eliteserien.no",
        "rbk.no",
        "fredrikstadfk.no",
    })


_FINDING_KEYS = frozenset({"source", "date", "time", "excerpt", "explanation"})
_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_TIME = re.compile(r"\d{2}:\d{2}")
_MONTHS = (
    ("januar", "january"),
    ("februar", "february"),
    ("mars", "march"),
    ("april", "april"),
    ("mai", "may"),
    ("juni", "june"),
    ("juli", "july"),
    ("august", "august"),
    ("september", "september"),
    ("oktober", "october"),
    ("november", "november"),
    ("desember", "december"),
)


def _reject_constant(_value: str) -> None:
    raise ValueError("non_finite_json")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _canonical_date(value: object) -> tuple[str, datetime]:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise ValueError("invalid_date")
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y")
    except ValueError as exc:
        raise ValueError("invalid_date") from exc
    if parsed.strftime("%d.%m.%Y") != value:
        raise ValueError("invalid_date")
    return value, parsed


def _canonical_time(value: object) -> str:
    if not isinstance(value, str) or _TIME.fullmatch(value) is None:
        raise ValueError("invalid_time")
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("invalid_time") from exc
    if parsed.strftime("%H:%M") != value:
        raise ValueError("invalid_time")
    return value


def _date_aliases(value: str, parsed: datetime) -> frozenset[str]:
    day = parsed.day
    month = parsed.month
    year = parsed.year
    norwegian, english = _MONTHS[month - 1]
    aliases = {
        value,
        value.replace(".", "/"),
        f"{year:04d}-{month:02d}-{day:02d}",
        f"{day}. {norwegian} {year}",
        f"{day} {norwegian} {year}",
        f"{day} {english} {year}",
        f"{english} {day}, {year}",
        f"{english} {day} {year}",
    }
    return frozenset(alias.casefold() for alias in aliases)


def _time_aliases(value: str) -> frozenset[str]:
    dotted = value.replace(":", ".")
    return frozenset({
        value,
        dotted,
        f"kl {value}",
        f"kl. {value}",
        f"kl {dotted}",
        f"kl. {dotted}",
    })


def _trusted_domain(host: str, policy: CalendarSourcePolicy) -> str | None:
    return next(
        (
            trusted
            for trusted in sorted(policy.trusted_domains)
            if host == trusted or host.endswith("." + trusted)
        ),
        None,
    )


def _independent_site(host: str) -> str:
    parts = tuple(part for part in host.split(".") if part)
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def parse_source_findings(
    raw: str,
    evidence: tuple[CalendarSearchEvidence, ...],
    policy: CalendarSourcePolicy | None = None,
) -> tuple[CalendarSourceFinding, ...]:
    """Parse one complete JSON envelope and bind every finding to evidence."""

    if not isinstance(raw, str):
        raise ValueError("invalid_json")
    try:
        value = json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict) or set(value) != {"findings"}:
        raise ValueError("invalid_envelope")
    rows = value["findings"]
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError("invalid_findings")
    indexed = {item.index: item for item in evidence}
    if len(indexed) != len(evidence):
        raise ValueError("duplicate_evidence_index")
    source_policy = policy or CalendarSourcePolicy()
    findings: list[CalendarSourceFinding] = []
    for item in rows:
        if not isinstance(item, dict) or set(item) != _FINDING_KEYS:
            raise ValueError("invalid_finding")
        source = item["source"]
        if isinstance(source, bool) or not isinstance(source, int) or source not in indexed:
            raise ValueError("invalid_source")
        date_value, parsed_date = _canonical_date(item["date"])
        time_value = _canonical_time(item["time"])
        excerpt = item["excerpt"]
        explanation = item["explanation"]
        if not isinstance(excerpt, str) or not 0 < len(excerpt) <= 160:
            raise ValueError("invalid_excerpt")
        if not isinstance(explanation, str) or not 0 < len(explanation) <= 240:
            raise ValueError("invalid_explanation")
        source_row = indexed[source]
        combined = _normalized(" ".join(filter(None, (
            source_row.title,
            source_row.body,
            source_row.page_content,
        ))))
        normalized_excerpt = _normalized(excerpt)
        if normalized_excerpt not in combined:
            raise ValueError("excerpt_not_bound")
        folded = combined.casefold()
        if not any(alias in folded for alias in _date_aliases(date_value, parsed_date)):
            raise ValueError("date_not_bound")
        if not any(alias in folded for alias in _time_aliases(time_value)):
            raise ValueError("time_not_bound")
        host = (urlsplit(source_row.url).hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            raise ValueError("invalid_source_url")
        trusted = _trusted_domain(host, source_policy)
        findings.append(CalendarSourceFinding(
            source=source,
            site_key=trusted or _independent_site(host),
            trusted_domain=trusted,
            date=date_value,
            time=time_value,
            excerpt=normalized_excerpt,
            explanation=_normalized(explanation),
            url=source_row.url,
        ))
    return tuple(findings)


def reduce_source_findings(
    findings: tuple[CalendarSourceFinding, ...],
    policy: CalendarSourcePolicy,
    current: tuple[str, str | None],
) -> CalendarEvidenceDecision:
    """Apply the immutable trusted-source and independent-agreement policy."""

    del policy
    unique: dict[tuple[str, str, str], CalendarSourceFinding] = {}
    for finding in findings:
        unique.setdefault(
            (finding.site_key, finding.date, finding.time),
            finding,
        )
    bounded = tuple(unique.values())
    trusted_candidates = {
        (finding.date, finding.time)
        for finding in bounded
        if finding.trusted_domain is not None
    }
    if len(trusted_candidates) > 1:
        return CalendarEvidenceDecision(
            CalendarEvidenceStatus.CONFLICTING,
            conflicting=bounded,
        )
    if trusted_candidates:
        candidate = next(iter(trusted_candidates))
        supporting = tuple(
            finding
            for finding in bounded
            if (finding.date, finding.time) == candidate
        )
        conflicting = tuple(
            finding
            for finding in bounded
            if (finding.date, finding.time) != candidate
        )
        status = (
            CalendarEvidenceStatus.CURRENT
            if candidate == current
            else CalendarEvidenceStatus.SUPPORTED
        )
        return CalendarEvidenceDecision(
            status,
            date=candidate[0],
            time=candidate[1],
            supporting=supporting,
            conflicting=conflicting,
        )

    by_candidate: dict[tuple[str, str], set[str]] = {}
    for finding in bounded:
        by_candidate.setdefault((finding.date, finding.time), set()).add(
            finding.site_key
        )
    if len(by_candidate) > 1:
        return CalendarEvidenceDecision(
            CalendarEvidenceStatus.CONFLICTING,
            conflicting=bounded,
        )
    if by_candidate:
        candidate, sites = next(iter(by_candidate.items()))
        if len(sites) >= 2:
            status = (
                CalendarEvidenceStatus.CURRENT
                if candidate == current
                else CalendarEvidenceStatus.SUPPORTED
            )
            return CalendarEvidenceDecision(
                status,
                date=candidate[0],
                time=candidate[1],
                supporting=bounded,
            )
    return CalendarEvidenceDecision(CalendarEvidenceStatus.INSUFFICIENT)

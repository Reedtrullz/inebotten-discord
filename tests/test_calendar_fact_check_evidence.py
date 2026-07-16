import json

import pytest

from core.calendar_fact_check_evidence import (
    CalendarEvidenceStatus,
    CalendarSearchEvidence,
    CalendarSourcePolicy,
    parse_source_findings,
    reduce_source_findings,
)


def row(index=1, url="https://www.fotball.no/kamp", body=None):
    return CalendarSearchEvidence(
        index=index,
        title="Kampinfo",
        url=url,
        body=body or "Rosenborg - Fredrikstad 27. juli 2026 kl. 19:00",
        provider="google",
        fetched_at="2026-07-16T18:00:00+00:00",
        published_at=None,
    )


def raw_finding(source=1, date="27.07.2026", time="19:00", **extra):
    finding = {
        "source": source,
        "date": date,
        "time": time,
        "excerpt": "Rosenborg - Fredrikstad 27. juli 2026 kl. 19:00",
        "explanation": "NFF viser kampstart.",
    }
    finding.update(extra)
    return json.dumps({"findings": [finding]})


def test_valid_trusted_evidence_is_bound_and_supported():
    findings = parse_source_findings(raw_finding(), (row(),))
    decision = reduce_source_findings(
        findings,
        CalendarSourcePolicy(),
        current=("26.07.2026", "09:00"),
    )
    assert findings[0].trusted_domain == "fotball.no"
    assert decision.status is CalendarEvidenceStatus.SUPPORTED
    assert (decision.date, decision.time) == ("27.07.2026", "19:00")


@pytest.mark.parametrize(
    "raw",
    (
        '{"findings":[],"findings":[]}',
        '{"findings":[{"source":1,"date":"27.07.2026","time":"19:00",'
        '"excerpt":"x","explanation":"x","extra":true}]}',
        '{"findings":NaN}',
        json.dumps({"findings": [{"source": 9, "date": "27.07.2026", "time": "19:00", "excerpt": "x", "explanation": "x"}]}),
        raw_finding(date="31.02.2026"),
        raw_finding(time="25:00"),
        raw_finding(excerpt="x" * 161),
        raw_finding(explanation="x" * 241),
        raw_finding(excerpt="invented excerpt"),
    ),
)
def test_parser_rejects_unbound_or_noncanonical_output(raw):
    with pytest.raises(ValueError):
        parse_source_findings(raw, (row(),))


def test_parser_requires_date_and_time_aliases_in_source():
    with pytest.raises(ValueError):
        parse_source_findings(
            raw_finding(),
            (row(body="Rosenborg - Fredrikstad uten publisert tidspunkt"),),
        )


def test_parser_accepts_documented_english_aliases():
    evidence = (
        row(body="Rosenborg - Fredrikstad July 27, 2026 at 19.00"),
    )
    raw = json.dumps({
        "findings": [{
            "source": 1,
            "date": "27.07.2026",
            "time": "19:00",
            "excerpt": "Rosenborg - Fredrikstad July 27, 2026 at 19.00",
            "explanation": "Published kickoff.",
        }]
    })
    assert len(parse_source_findings(raw, evidence)) == 1


def parsed(url, *, date="27.07.2026", time="19:00", index=1):
    body = f"Kamp {date} kl. {time}"
    raw = json.dumps({
        "findings": [{
            "source": index,
            "date": date,
            "time": time,
            "excerpt": body,
            "explanation": "Kampstart.",
        }]
    })
    return parse_source_findings(raw, (row(index=index, url=url, body=body),))[0]


def test_duplicate_same_site_does_not_create_untrusted_agreement():
    findings = (
        parsed("https://a.example.com/one", index=1),
        parsed("https://b.example.com/two", index=2),
    )
    decision = reduce_source_findings(
        findings, CalendarSourcePolicy(), current=("26.07.2026", "09:00")
    )
    assert decision.status is CalendarEvidenceStatus.INSUFFICIENT


def test_two_independent_untrusted_sites_can_support():
    findings = (
        parsed("https://example.com/one", index=1),
        parsed("https://other.no/two", index=2),
    )
    decision = reduce_source_findings(
        findings, CalendarSourcePolicy(), current=("26.07.2026", "09:00")
    )
    assert decision.status is CalendarEvidenceStatus.SUPPORTED


def test_one_untrusted_source_is_insufficient():
    decision = reduce_source_findings(
        (parsed("https://example.com/one"),),
        CalendarSourcePolicy(),
        current=("26.07.2026", "09:00"),
    )
    assert decision.status is CalendarEvidenceStatus.INSUFFICIENT


def test_untrusted_disagreement_is_conflicting():
    findings = (
        parsed("https://example.com/one", index=1),
        parsed("https://other.no/two", date="28.07.2026", index=2),
    )
    assert reduce_source_findings(
        findings, CalendarSourcePolicy(), current=("26.07.2026", "09:00")
    ).status is CalendarEvidenceStatus.CONFLICTING


def test_trusted_conflict_blocks_but_untrusted_conflict_does_not_override():
    trusted = (
        parsed("https://fotball.no/one", index=1),
        parsed("https://rbk.no/two", date="28.07.2026", index=2),
    )
    assert reduce_source_findings(
        trusted, CalendarSourcePolicy(), current=("26.07.2026", "09:00")
    ).status is CalendarEvidenceStatus.CONFLICTING

    mixed = (
        parsed("https://fotball.no/one", index=1),
        parsed("https://example.com/two", date="28.07.2026", index=2),
    )
    decision = reduce_source_findings(
        mixed, CalendarSourcePolicy(), current=("26.07.2026", "09:00")
    )
    assert decision.status is CalendarEvidenceStatus.SUPPORTED
    assert len(decision.conflicting) == 1


def test_evidence_matching_current_is_read_only_current():
    decision = reduce_source_findings(
        (parsed("https://fotball.no/one"),),
        CalendarSourcePolicy(),
        current=("27.07.2026", "19:00"),
    )
    assert decision.status is CalendarEvidenceStatus.CURRENT

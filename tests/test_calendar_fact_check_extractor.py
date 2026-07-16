import json
import logging

import pytest

from ai.calendar_fact_check_extractor import CalendarFactCheckExtractor
from core.calendar_fact_check_evidence import CalendarSearchEvidence


class Connector:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def evidence_row():
    return CalendarSearchEvidence(
        1,
        "Kamp",
        "https://fotball.no/kamp",
        "Rosenborg 27. juli 2026 kl. 19:00",
        "google",
        "2026-07-16T18:00:00Z",
        None,
    )


@pytest.mark.asyncio
async def test_extractor_is_history_free_and_strict(evidence_row):
    response = json.dumps({"findings": [{
        "source": 1,
        "date": "27.07.2026",
        "time": "19:00",
        "excerpt": "Rosenborg 27. juli 2026 kl. 19:00",
        "explanation": "NFF viser kampstart.",
    }]})
    connector = Connector((True, response))
    result = await CalendarFactCheckExtractor(connector).extract((evidence_row,))
    call = connector.calls[0]
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 800
    assert call["history"] == ()
    assert call["is_mention"] is False
    assert "DISCORD_ID_CANARY" not in json.dumps(call)
    assert result.status == "ok"
    assert result.findings[0].date == "27.07.2026"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        (False, "MODEL_OUTPUT_CANARY"),
        (True, ""),
        (True, "not json"),
        (True, '```json\n{"findings":[]}\n```'),
        (True, '{"findings":[{"source":2,"date":"27.07.2026","time":"19:00","excerpt":"x","explanation":"x"}]}'),
        RuntimeError("EXCEPTION_BODY_CANARY"),
    ),
)
async def test_extractor_failures_are_unavailable_without_raw_logs(
    evidence_row, response, caplog
):
    with caplog.at_level(logging.INFO):
        result = await CalendarFactCheckExtractor(Connector(response)).extract(
            (evidence_row,)
        )
    assert result.status == "unavailable"
    assert result.findings == ()
    assert "MODEL_OUTPUT_CANARY" not in caplog.text
    assert "EXCEPTION_BODY_CANARY" not in caplog.text


@pytest.mark.asyncio
async def test_empty_valid_findings_remain_distinguishable(evidence_row):
    result = await CalendarFactCheckExtractor(
        Connector((True, '{"findings":[]}'))
    ).extract((evidence_row,))
    assert result.status == "ok"
    assert result.findings == ()

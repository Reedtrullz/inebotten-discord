"""History-free AI extraction for bounded calendar schedule evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Literal

from core.calendar_fact_check_evidence import (
    CalendarSearchEvidence,
    CalendarSourceFinding,
    parse_source_findings,
)


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Extract only explicit calendar date and time findings from the supplied public evidence. Return exactly one JSON object with this schema and no code fences or prose: {"findings":[{"source":1,"date":"DD.MM.YYYY","time":"HH:MM","excerpt":"exact source excerpt","explanation":"bounded explanation"}]}. Use only source indexes, dates, times, and exact excerpts present in the evidence. Return {"findings":[]} when unsupported."""


@dataclass(frozen=True, slots=True)
class CalendarFactCheckExtraction:
    status: Literal["ok", "unavailable"]
    findings: tuple[CalendarSourceFinding, ...] = ()


class CalendarFactCheckExtractor:
    def __init__(self, connector) -> None:
        self.connector = connector

    async def extract(
        self,
        evidence: tuple[CalendarSearchEvidence, ...],
    ) -> CalendarFactCheckExtraction:
        context = json.dumps(
            {
                "evidence": [
                    {
                        "source": row.index,
                        "title": row.title,
                        "body": row.body,
                        "page_content": row.page_content,
                        "published_at": row.published_at,
                    }
                    for row in evidence
                ]
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            success, response = await self.connector.generate_response(
                message_content="Extract calendar schedule evidence.",
                author_name="calendar-fact-check",
                channel_type="INTERNAL_TOOL",
                is_mention=False,
                system_prompt=_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=800,
                context_prompt=context,
                history=(),
            )
            if success is not True or not isinstance(response, str) or not response:
                raise ValueError("connector_unavailable")
            findings = parse_source_findings(response, evidence)
        except Exception:
            logger.info("calendar_fact_check_extraction outcome=unavailable count=0")
            return CalendarFactCheckExtraction("unavailable")
        logger.info(
            "calendar_fact_check_extraction outcome=ok count=%d",
            len(findings),
        )
        return CalendarFactCheckExtraction("ok", findings)

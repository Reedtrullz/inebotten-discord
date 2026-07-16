"""Deterministic Discord-facing calendar fact-check conversation flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from core.calendar_fact_check_evidence import CalendarEvidenceStatus
from core.calendar_fact_check_store import CalendarFactCheckPhase
from core.intent_models import BotIntent, IntentResult, IntentRisk
from core.message_context import RoutingContext
from core.pending_actions import neutralize_discord_text
from core.pending_targets import PendingTargetError
from features.calendar_fact_check_manager import CalendarFactCheckManager
from utils.sanitizer import sanitize_url


@dataclass(frozen=True, slots=True)
class CalendarFactCheckFlow:
    text: str
    proposed_route: IntentResult | None = None
    clear_after_staged: bool = False


class CalendarFactCheckHandler:
    def __init__(self, monitor, manager: CalendarFactCheckManager) -> None:
        self.monitor = monitor
        self.manager = manager

    async def handle(
        self,
        payload: Mapping[str, object],
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> CalendarFactCheckFlow:
        action = payload["action"]
        handlers = {
            "start": self._start,
            "select": self._select,
            "search": self._search,
            "cancel": self._cancel,
        }
        try:
            handler = handlers[action]
        except (KeyError, TypeError) as exc:
            raise ValueError("wrong_action") from exc
        return await handler(payload, routing, reference_time=reference_time)

    def _ready_copy(self, target) -> str:
        title = neutralize_discord_text(target.title)
        schedule = target.date
        if target.time is not None:
            schedule += f" kl. {target.time}"
        missing = (
            " Oppføringen har ikke et spesifikt klokkeslett."
            if target.time is None
            else ""
        )
        return (
            f"Jeg fant **{title}**. Kalenderen har {schedule}.{missing} "
            "Vil du at jeg skal sjekke riktig tidspunkt, eller vil du oppgi "
            "riktig dato eller klokkeslett?"
        )

    async def _start(self, payload, routing, *, reference_time):
        targets = self.monitor.pending_targets.snapshot_calendar_fact_check_targets(
            str(payload["target"]), reference_time=reference_time, limit=6
        )
        if not targets:
            return CalendarFactCheckFlow(
                "Jeg fant ingen kalenderoppføring som passer. Oppgi en mer presis tittel."
            )
        if len(targets) > 5:
            return CalendarFactCheckFlow(
                "Jeg fant for mange kalenderoppføringer. Oppgi en mer presis tittel."
            )
        inquiry = self.monitor.calendar_fact_checks.begin(routing.key, targets)
        if inquiry.phase is CalendarFactCheckPhase.READY:
            return CalendarFactCheckFlow(self._ready_copy(inquiry.targets[0]))
        lines = ["Jeg fant flere kalenderoppføringer. Velg ett nummer:"]
        lines.extend(
            f"{index}. {neutralize_discord_text(target.title)} — {target.date}"
            + (f" kl. {target.time}" if target.time else "")
            for index, target in enumerate(inquiry.targets, start=1)
        )
        return CalendarFactCheckFlow("\n".join(lines))

    async def _select(self, payload, routing, *, reference_time):
        del reference_time
        try:
            inquiry = self.monitor.calendar_fact_checks.select(
                routing.key, int(payload["number"])
            )
        except (ValueError, TypeError):
            return CalendarFactCheckFlow(
                "Det nummeret finnes ikke i valgene. Velg et nummer fra listen."
            )
        return CalendarFactCheckFlow(self._ready_copy(inquiry.targets[0]))

    async def _search(self, payload, routing, *, reference_time):
        lookup = self.monitor.calendar_fact_checks.lookup(routing.key)
        inquiry = lookup.inquiry
        if (
            inquiry is None
            or inquiry.phase is not CalendarFactCheckPhase.READY
            or inquiry.targets[0].stable_id != payload["target"]
        ):
            return CalendarFactCheckFlow(
                "Denne faktasjekken er ikke lenger aktiv. Start på nytt."
            )
        target = inquiry.targets[0]
        try:
            target = self.monitor.pending_targets.revalidate_calendar_fact_check_target(
                target, reference_time=reference_time
            )
        except PendingTargetError:
            self.monitor.calendar_fact_checks.cancel(routing.key)
            return CalendarFactCheckFlow(
                "Kalenderoppføringen har endret seg; start på nytt."
            )
        decision = await self.manager.investigate(target)
        try:
            target = self.monitor.pending_targets.revalidate_calendar_fact_check_target(
                target, reference_time=reference_time
            )
        except PendingTargetError:
            self.monitor.calendar_fact_checks.cancel(routing.key)
            return CalendarFactCheckFlow(
                "Kalenderoppføringen har endret seg; start på nytt."
            )
        sources = self._source_copy((*decision.supporting, *decision.conflicting))
        if decision.status is CalendarEvidenceStatus.CURRENT:
            return CalendarFactCheckFlow(
                "Kildene jeg fant stemmer med tidspunktet som allerede står i kalenderen."
                + sources
            )
        if decision.status is CalendarEvidenceStatus.CONFLICTING:
            return CalendarFactCheckFlow(
                "Kildene oppgir ulike tidspunkter, så jeg foreslår ingen endring."
                + sources
            )
        if decision.status is CalendarEvidenceStatus.INSUFFICIENT:
            return CalendarFactCheckFlow(
                "Jeg fant ikke nok uavhengig støtte til å foreslå en endring."
                + sources
            )
        if decision.status is CalendarEvidenceStatus.UNAVAILABLE:
            return CalendarFactCheckFlow(
                "Jeg kunne ikke gjennomføre kildesjekken nå. Ingen endring er foreslått."
            )
        if decision.date is None or decision.time is None:
            return CalendarFactCheckFlow(
                "Jeg fant ikke et komplett, støttet tidspunkt. Ingen endring er foreslått."
            )
        changes = {}
        if decision.date != target.date:
            changes["date"] = decision.date
        if decision.time != target.time:
            changes["time"] = decision.time
        if not changes:
            return CalendarFactCheckFlow(
                "Kildene jeg fant stemmer med tidspunktet som allerede står i kalenderen."
                + sources
            )
        route = IntentResult(
            BotIntent.CALENDAR_EDIT,
            1.0,
            {"calendar_edit": {"target": target.stable_id, "changes": changes}},
            "calendar_fact_check_supported_edit",
            risk=IntentRisk.MUTATING,
            requires_confirmation=True,
        )
        return CalendarFactCheckFlow(
            "Kildene støtter et annet tidspunkt." + sources,
            proposed_route=route,
            clear_after_staged=True,
        )

    async def _cancel(self, payload, routing, *, reference_time):
        del payload, reference_time
        self.monitor.calendar_fact_checks.cancel(routing.key)
        return CalendarFactCheckFlow("Faktasjekken er avbrutt.")

    @staticmethod
    def _source_copy(findings) -> str:
        links = []
        for finding in findings:
            safe = sanitize_url(finding.url)
            if safe:
                inert = quote(safe, safe=":/?#[]!$&'()*+,;=%-._~")
                links.append(f"<{inert}>")
        unique = tuple(dict.fromkeys(links))
        return (" Kilder: " + " ".join(unique)) if unique else ""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.calendar_fact_check_evidence import (
    CalendarEvidenceDecision,
    CalendarEvidenceStatus,
)
from core.calendar_fact_check_store import (
    CalendarFactCheckStore,
    CalendarFactCheckTarget,
)
from core.intent_models import BotIntent
from core.message_context import ConversationKey, ResolvedMention, RoutingContext
from core.pending_targets import PendingTargetError
from features.calendar_fact_check_handler import CalendarFactCheckHandler


NOW = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
KEY = ConversationKey(1, 2, 3)
ROUTING = RoutingContext(KEY, ResolvedMention(3, "Reidar"))
TARGET = CalendarFactCheckTarget(
    "calendar-1", "revision-1", "Rosenborg - Fredrikstad", "26.07.2026", "09:00"
)


class Targets:
    def __init__(self, targets=(TARGET,)):
        self.targets = targets
        self.stale = False

    def snapshot_calendar_fact_check_targets(self, *_args, **_kwargs):
        return self.targets

    def revalidate_calendar_fact_check_target(self, target, **_kwargs):
        if self.stale:
            raise PendingTargetError("target_changed")
        return target


class Manager:
    def __init__(self, decision=None):
        self.decision = decision or CalendarEvidenceDecision(
            CalendarEvidenceStatus.INSUFFICIENT
        )

    async def investigate(self, _target):
        return self.decision


def make_handler(targets=(TARGET,), decision=None):
    target_resolver = Targets(targets)
    monitor = SimpleNamespace(
        pending_targets=target_resolver,
        calendar_fact_checks=CalendarFactCheckStore(now_provider=lambda: NOW),
    )
    return CalendarFactCheckHandler(monitor, Manager(decision)), monitor, target_resolver


@pytest.mark.asyncio
async def test_start_one_target_is_deterministic_and_stored():
    handler, monitor, _ = make_handler()
    flow = await handler.handle(
        {"action": "start", "field": "schedule", "target": TARGET.title},
        ROUTING,
        reference_time=NOW,
    )
    assert flow.proposed_route is None
    assert TARGET.title in flow.text
    assert "26.07.2026 kl. 09:00" in flow.text
    assert "sjekke riktig tidspunkt" in flow.text
    assert monitor.calendar_fact_checks.lookup(KEY).inquiry is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("targets", "copy"),
    (((), "ingen"), (tuple(TARGET for _ in range(6)), "for mange")),
)
async def test_start_zero_or_overflow_does_not_create_state(targets, copy):
    handler, monitor, _ = make_handler(targets)
    flow = await handler.handle(
        {"action": "start", "field": "schedule", "target": "kamp"},
        ROUTING,
        reference_time=NOW,
    )
    assert copy in flow.text
    assert monitor.calendar_fact_checks.lookup(KEY).inquiry is None


@pytest.mark.asyncio
async def test_selection_and_cancellation_are_scoped():
    second = CalendarFactCheckTarget("calendar-2", "revision-2", "Kamp 2", "27.07.2026", None)
    handler, monitor, _ = make_handler((TARGET, second))
    start = await handler.handle(
        {"action": "start", "field": "schedule", "target": "kamp"}, ROUTING, reference_time=NOW
    )
    assert "1." in start.text and "2." in start.text
    invalid = await handler.handle({"action": "select", "number": 9}, ROUTING, reference_time=NOW)
    assert "finnes ikke" in invalid.text
    selected = await handler.handle({"action": "select", "number": 2}, ROUTING, reference_time=NOW)
    assert "ikke et spesifikt klokkeslett" in selected.text
    cancelled = await handler.handle({"action": "cancel"}, ROUTING, reference_time=NOW)
    assert "avbrutt" in cancelled.text
    assert monitor.calendar_fact_checks.lookup(KEY).inquiry is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (CalendarEvidenceStatus.CURRENT, "allerede"),
        (CalendarEvidenceStatus.CONFLICTING, "ulike"),
        (CalendarEvidenceStatus.INSUFFICIENT, "ikke nok"),
        (CalendarEvidenceStatus.UNAVAILABLE, "kunne ikke"),
    ),
)
async def test_read_only_investigation_outcomes_never_propose(status, expected):
    handler, _monitor, _ = make_handler(
        decision=CalendarEvidenceDecision(status)
    )
    await handler.handle(
        {"action": "start", "field": "schedule", "target": TARGET.title}, ROUTING, reference_time=NOW
    )
    flow = await handler.handle(
        {"action": "search", "field": "schedule", "target": TARGET.stable_id}, ROUTING, reference_time=NOW
    )
    assert expected in flow.text
    assert flow.proposed_route is None


@pytest.mark.asyncio
async def test_supported_change_constructs_confirmation_gated_edit_only():
    decision = CalendarEvidenceDecision(
        CalendarEvidenceStatus.SUPPORTED, date="27.07.2026", time="19:00"
    )
    handler, _monitor, _ = make_handler(decision=decision)
    await handler.handle(
        {"action": "start", "field": "schedule", "target": TARGET.title}, ROUTING, reference_time=NOW
    )
    flow = await handler.handle(
        {"action": "search", "field": "schedule", "target": TARGET.stable_id}, ROUTING, reference_time=NOW
    )
    assert flow.proposed_route.intent is BotIntent.CALENDAR_EDIT
    assert flow.proposed_route.requires_confirmation is True
    assert flow.proposed_route.payload == {
        "calendar_edit": {
            "target": TARGET.stable_id,
            "changes": {"date": "27.07.2026", "time": "19:00"},
        }
    }
    assert flow.clear_after_staged is True


@pytest.mark.asyncio
async def test_stale_target_before_search_fails_closed_and_clears_inquiry():
    handler, monitor, resolver = make_handler()
    await handler.handle(
        {"action": "start", "field": "schedule", "target": TARGET.title}, ROUTING, reference_time=NOW
    )
    resolver.stale = True
    flow = await handler.handle(
        {"action": "search", "field": "schedule", "target": TARGET.stable_id}, ROUTING, reference_time=NOW
    )
    assert "endret seg" in flow.text
    assert flow.proposed_route is None
    assert monitor.calendar_fact_checks.lookup(KEY).inquiry is None

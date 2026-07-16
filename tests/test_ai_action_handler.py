"""Offline tests for send-free model and pending action orchestration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from cal_system.temporal_resolver import TemporalResolver
from core.action_bridge import ActionBridge
from core.dispatch_result import DeliveryState, DispatchOutcome, MessageSendResult
from core.intent_models import BotIntent, IntentResult, IntentRisk, IntentSource
from core.intent_payloads import PayloadValidationError, validate_intent_payload
from core.message_context import conversation_key_from_message
from core.nlu_metrics import NLUMetrics
from core.pending_actions import (
    PendingActionStore,
    PendingStatus,
    PendingTargetFamily,
    PendingTargetGuard,
)
from core.utterance import normalize_utterance
from features.ai_action_handler import (
    AIActionHandler,
    ConfirmationPreviewTooLarge,
    ModelDisposition,
    UnsupportedConfirmationSummary,
    format_choice_label,
    format_confirmation_card_details,
    format_confirmation_card_heading,
    format_confirmation_card_messages,
    format_confirmation_details,
    format_confirmation_messages,
    neutralize_confirmation_value,
)
from tests.nlu_test_support import FIXED_NOW, ready_choices, ready_confirmation


def action_line(
    action: str,
    confidence: float,
    slots: dict[str, object],
    *,
    reply: str = "",
    clarification: str | None = None,
) -> str:
    return json.dumps(
        {
            "action": action,
            "confidence": confidence,
            "slots": slots,
            "reply": reply,
            "clarification": clarification,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def semantic_reminder_route() -> IntentResult:
    return IntentResult(
        BotIntent.REMINDER_CREATE,
        0.91,
        {
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_date": "15.07.2026",
                "time": "09:00",
                "timezone": "Europe/Oslo",
            }
        },
        "semantic_action",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )


def guard(
    family: PendingTargetFamily,
    label: str,
    detail: str | None = None,
    *,
    display_fields: tuple[tuple[str, str], ...] = (),
) -> PendingTargetGuard:
    return PendingTargetGuard(
        family=family,
        stable_id=f"{family.value}-a",
        original_position=1,
        fingerprint=None,
        revision="revision-a",
        label=label,
        display_detail=detail or label,
        display_fields=display_fields,
    )


def destructive_calendar_route() -> IntentResult:
    return IntentResult(
        BotIntent.CALENDAR_DELETE,
        0.99,
        {"calendar_target": {"target": "Møte med Ola"}},
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.DESTRUCTIVE,
        requires_confirmation=True,
    )


def destructive_calendar_guard() -> PendingTargetGuard:
    return guard(
        PendingTargetFamily.CALENDAR,
        "Møte med Ola",
        "tittel: Møte med Ola; dato: 15.07.2026; tid: 14:00; "
        "type: event; status: ikke fullført",
        display_fields=(
            ("tittel", "Møte med Ola"),
            ("dato", "15.07.2026"),
            ("tid", "14:00"),
            ("type", "event"),
            ("status", "ikke fullført"),
        ),
    )


@pytest.mark.asyncio
async def test_model_response_returns_route_without_send_or_dispatch(
    action_handler,
    message,
    routing_context,
):
    raw = "Klart.\n" + action_line(
        "REMINDER_CREATE",
        0.91,
        {"text": "ringe legen"},
    )
    outcome = await action_handler.handle_model_response(
        raw=raw,
        utterance=normalize_utterance("kan du huske legetelefonen?"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.visible_text == (
        "Jeg har forberedt handlingen, men ikke utført den."
    )
    assert outcome.route is not None
    assert outcome.route.intent is BotIntent.REMINDER_CREATE
    assert action_handler.metrics.snapshot()["actions"] == {"accepted": 1}
    action_handler.dispatch_claimed.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_typed_payload_validation_failure_is_inert_and_bounded(
    action_handler,
    routing_context,
):
    action_handler.bridge.to_result = Mock(
        side_effect=PayloadValidationError("missing_payload")
    )
    outcome = await action_handler.handle_model_response(
        raw=action_line(
            "CALENDAR_CREATE",
            0.95,
            {"title": "Møte", "date": "15.07.2026"},
        ),
        utterance=normalize_utterance("planlegg møte 15. juli"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.route is None
    assert "utførte ingen handling" in outcome.visible_text
    assert outcome.parser_errors == ("missing_slot",)
    assert action_handler.metrics.snapshot()["actions"] == {
        "missing_slot": 1
    }


@pytest.mark.asyncio
async def test_invalid_protocol_returns_natural_copy_without_machine_json(
    action_handler,
    routing_context,
):
    outcome = await action_handler.handle_model_response(
        raw=action_line(
            "CALENDAR_CREATE",
            0.99,
            {"title": "Møte"},
        ),
        utterance=normalize_utterance("kan du ordne et møte?"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.visible_text == (
        "Jeg utførte ingen handling fordi forslaget ikke kunne valideres. "
        "Formuler ønsket på nytt."
    )
    assert '{"action"' not in outcome.visible_text
    assert outcome.route is None
    assert outcome.parser_errors == ("missing_slot",)
    assert outcome.disposition is ModelDisposition.INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "utterance"),
    [
        (
            "Klart, jeg slettet den.\n"
            + action_line("CALENDAR_DELETE", 0.99, {"target": "1"}),
            "ikke slett kalenderen",
        ),
        (
            "Ferdig.\n"
            + action_line("REMINDER_DELETE", 0.99, {"number": 1}),
            "kan du slette nummer 1?",
        ),
        ("Slettet.\n{\"action\":", "slett kalenderen"),
    ],
)
async def test_rejected_write_never_repeats_model_completion_claim(
    action_handler,
    routing_context,
    raw,
    utterance,
):
    outcome = await action_handler.handle_model_response(
        raw=raw,
        utterance=normalize_utterance(utterance),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.route is None
    assert outcome.disposition in {
        ModelDisposition.BLOCKED,
        ModelDisposition.INVALID,
    }
    assert "utførte ingen handling" in outcome.visible_text
    assert not any(
        claim in outcome.visible_text.casefold()
        for claim in ("klart", "ferdig", "slettet")
    )
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
async def test_nested_reply_protocol_is_stripped_and_never_executed(
    action_handler,
    routing_context,
):
    nested = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    raw = action_line("HELP", 0.99, {}, reply=f"@everyone\n{nested}")
    outcome = await action_handler.handle_model_response(
        raw=raw,
        utterance=normalize_utterance("hjelp meg"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert nested not in outcome.visible_text
    assert outcome.visible_text == "@everyone"
    assert outcome.route is not None
    assert outcome.route.intent is BotIntent.HELP
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
async def test_nested_clarification_protocol_is_inert(
    action_handler,
    routing_context,
):
    nested = action_line("QUOTE_DELETE", 1.0, {"index": 1})
    raw = action_line(
        "CLARIFY",
        0.99,
        {},
        clarification=nested,
    )
    outcome = await action_handler.handle_model_response(
        raw=raw,
        utterance=normalize_utterance("kan du hjelpe?"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.route is not None
    assert outcome.route.intent is BotIntent.CLARIFY
    assert nested not in outcome.route.payload["clarification"]


@pytest.mark.asyncio
async def test_none_proposal_is_ordinary_prose_and_not_an_accepted_action(
    action_handler,
    routing_context,
):
    outcome = await action_handler.handle_model_response(
        raw="Hyggelig svar.\n" + action_line("NONE", 1.0, {}),
        utterance=normalize_utterance("hvordan går det?"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.visible_text == "Hyggelig svar."
    assert outcome.route is None
    assert outcome.disposition is ModelDisposition.ORDINARY
    assert action_handler.metrics.snapshot().get("actions", {}) == {}


@pytest.mark.asyncio
async def test_legacy_safe_proposal_records_only_legacy_result(
    action_handler,
    routing_context,
):
    outcome = await action_handler.handle_model_response(
        raw="Viser oversikten.\n[SHOW_DASHBOARD]",
        utterance=normalize_utterance("vis dashboard"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    assert outcome.route is not None
    assert outcome.route.intent is BotIntent.DASHBOARD
    assert action_handler.metrics.snapshot()["actions"] == {"legacy": 1}


@pytest.mark.asyncio
async def test_bridge_rejection_never_records_accepted_action(
    action_handler,
    routing_context,
):
    outcome = await action_handler.handle_model_response(
        raw=action_line("CALENDAR_DELETE", 0.99, {"target": "Møte"}),
        utterance=normalize_utterance("ikke slett møtet i kalenderen"),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )
    snapshot = action_handler.metrics.snapshot()
    assert outcome.disposition is ModelDisposition.BLOCKED
    assert snapshot.get("actions", {}) == {}
    assert snapshot["rejections"]


@pytest.mark.asyncio
async def test_confirm_claims_and_dispatches_once(action_handler, message):
    pending = ready_confirmation(
        action_handler.store,
        conversation_key_from_message(message),
        semantic_reminder_route(),
        "Ringe legen",
    )
    first = await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    second = await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    assert first.dispatch is not None and first.dispatch.ok is True
    assert second.dispatch is None
    action_handler.dispatch_claimed.assert_awaited_once()


@pytest.mark.asyncio
async def test_committed_send_failure_is_terminal(action_handler, message):
    action_handler.dispatch_claimed.return_value = DispatchOutcome.failure(
        "send_failed",
        mutated=True,
        retryable=False,
    ).with_delivery(MessageSendResult(DeliveryState.UNKNOWN, "transport"))
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        semantic_reminder_route(),
        "Ringe legen",
    )
    await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    assert action_handler.store.peek(key).status is PendingStatus.FAILED
    await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    action_handler.dispatch_claimed.assert_awaited_once()


@pytest.mark.asyncio
async def test_retryable_prewrite_failure_returns_to_ready(
    action_handler,
    message,
):
    action_handler.dispatch_claimed.return_value = DispatchOutcome.failure(
        "not_found",
        mutated=False,
        retryable=True,
    ).with_delivery(MessageSendResult(DeliveryState.DELIVERED))
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        semantic_reminder_route(),
        "Ringe legen",
    )
    await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    assert action_handler.store.peek(key).status is PendingStatus.READY


@pytest.mark.asyncio
async def test_invalid_dispatch_return_is_terminal_commit_unknown(
    action_handler,
    message,
):
    action_handler.dispatch_claimed.return_value = object()
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        semantic_reminder_route(),
        "Ringe legen",
    )
    outcome = await action_handler.confirm(
        message,
        pending.action_id,
        reference_time=FIXED_NOW,
    )
    assert outcome.dispatch is not None
    assert outcome.dispatch.commit_unknown is True
    assert action_handler.store.peek(key).status is PendingStatus.FAILED


@pytest.mark.asyncio
async def test_temporal_correction_restages_new_validated_route(
    action_handler,
    message,
):
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        semantic_reminder_route(),
        "Ringe legen",
    )
    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance("i morgen kl 14"),
        reference_time=FIXED_NOW,
    )
    unchanged = action_handler.store.peek(key)
    assert unchanged.action_id == pending.action_id
    assert outcome.presentation is not None
    assert outcome.presentation.correction_action_id == pending.action_id
    reminder = outcome.presentation.routes[0].payload["reminder"]
    assert reminder["due_date"] == "15.07.2026"
    assert reminder["time"] == "14:00"
    assert outcome.dispatch is None
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_correction_recomputes_canonical_due_at(
    action_handler,
    message,
):
    key = conversation_key_from_message(message)
    route = replace(
        semantic_reminder_route(),
        payload={
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_at": "2026-07-20T10:00:00+02:00",
            }
        },
    )
    pending = ready_confirmation(action_handler.store, key, route, "Ringe")
    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance("i morgen kl 14"),
        reference_time=FIXED_NOW,
    )
    assert outcome.presentation is not None
    corrected = outcome.presentation.routes[0].payload["reminder"]
    assert corrected["due_date"] == "15.07.2026"
    assert corrected["time"] == "14:00"
    assert corrected["due_at"] == "2026-07-15T14:00:00+02:00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("correction", "expected_date", "expected_time", "expected_due_at"),
    [
        (
            "kl 15",
            "20.07.2026",
            "15:00",
            "2026-07-20T15:00:00+02:00",
        ),
        (
            "i morgen",
            "15.07.2026",
            "10:00",
            "2026-07-15T10:00:00+02:00",
        ),
        (
            "i kveld",
            "14.07.2026",
            "19:00",
            "2026-07-14T19:00:00+02:00",
        ),
        (
            "this evening",
            "14.07.2026",
            "19:00",
            "2026-07-14T19:00:00+02:00",
        ),
        (
            "tonight",
            "14.07.2026",
            "19:00",
            "2026-07-14T19:00:00+02:00",
        ),
        (
            "på kvelden",
            "20.07.2026",
            "19:00",
            "2026-07-20T19:00:00+02:00",
        ),
    ],
)
async def test_reminder_partial_temporal_correction_merges_frozen_fields(
    action_handler,
    message,
    correction,
    expected_date,
    expected_time,
    expected_due_at,
):
    key = conversation_key_from_message(message)
    original_route = replace(
        semantic_reminder_route(),
        payload={
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_date": "20.07.2026",
                "time": "10:00",
                "timezone": "Europe/Oslo",
            }
        },
    )
    pending = ready_confirmation(
        action_handler.store,
        key,
        original_route,
        "Ringe",
    )

    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance(correction),
        reference_time=FIXED_NOW,
    )

    assert outcome.presentation is not None
    corrected = outcome.presentation.routes[0].payload["reminder"]
    assert corrected == {
        "action": "add",
        "text": "Ringe legen",
        "due_at": expected_due_at,
        "due_date": expected_date,
        "time": expected_time,
        "timezone": "Europe/Oslo",
    }
    unchanged = action_handler.store.peek(key)
    assert unchanged is not None
    assert unchanged.action_id == pending.action_id
    assert unchanged.routes[0].payload == original_route.payload
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("correction", "expected_date", "expected_time"),
    [
        ("kl 15", "20.07.2026", "15:00"),
        ("i morgen", "15.07.2026", "10:00"),
    ],
)
async def test_calendar_partial_temporal_correction_merges_frozen_fields(
    action_handler,
    message,
    correction,
    expected_date,
    expected_time,
):
    key = conversation_key_from_message(message)
    original_route = IntentResult(
        BotIntent.CALENDAR_ITEM,
        0.99,
        {
            "calendar_item": {
                "title": "Møte med Ola",
                "date": "20.07.2026",
                "time": "10:00",
                "type": "event",
            }
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    pending = ready_confirmation(
        action_handler.store,
        key,
        original_route,
        "Møte",
    )

    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance(correction),
        reference_time=FIXED_NOW,
    )

    assert outcome.presentation is not None
    corrected = outcome.presentation.routes[0].payload["calendar_item"]
    assert corrected == {
        "title": "Møte med Ola",
        "date": expected_date,
        "time": expected_time,
        "type": "event",
    }
    unchanged = action_handler.store.peek(key)
    assert unchanged is not None
    assert unchanged.action_id == pending.action_id
    assert unchanged.routes[0].payload == original_route.payload
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
async def test_named_title_correction_does_not_leak_temporal_defaults(
    action_handler,
    message,
):
    key = conversation_key_from_message(message)
    original_route = IntentResult(
        BotIntent.CALENDAR_ITEM,
        0.99,
        {
            "calendar_item": {
                "title": "Foreløpig",
                "date": "20.07.2026",
                "time": "10:00",
                "type": "event",
            }
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    pending = ready_confirmation(
        action_handler.store,
        key,
        original_route,
        "Møte",
    )

    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance("tittel: Møte i morgen kl 15"),
        reference_time=FIXED_NOW,
    )

    assert outcome.presentation is not None
    assert outcome.presentation.routes[0].payload["calendar_item"] == {
        "title": "Møte i morgen kl 15",
        "date": "20.07.2026",
        "time": "10:00",
        "type": "event",
    }
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
async def test_correction_uses_turn_reference_across_oslo_midnight(
    action_handler,
    message,
):
    turn_reference = FIXED_NOW.replace(hour=23, minute=59)
    wall_clock = turn_reference + timedelta(minutes=2)
    wall_reads = []

    def read_wall_clock():
        wall_reads.append(wall_clock)
        return wall_clock

    action_handler.temporal_resolver = TemporalResolver(
        now_provider=read_wall_clock
    )
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        semantic_reminder_route(),
        "Ringe legen",
    )
    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance("i morgen kl 01"),
        reference_time=turn_reference,
    )
    assert outcome.presentation is not None
    corrected = outcome.presentation.routes[0].payload["reminder"]
    assert corrected["due_date"] == "15.07.2026"
    assert corrected["time"] == "01:00"
    assert wall_reads == []


@pytest.mark.asyncio
async def test_invalid_correction_is_bounded_and_store_unchanged(
    action_handler,
    message,
):
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        IntentResult(
            BotIntent.POLL_CREATE,
            0.99,
            {"poll": {"question": "Mat?", "options": ["Pizza", "Taco"]}},
            source=IntentSource.SEMANTIC,
            risk=IntentRisk.ADDITIVE,
            requires_confirmation=True,
        ),
        "Avstemning",
    )
    before = action_handler.store.peek(key)
    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance("alternativer: bare ett"),
        reference_time=FIXED_NOW,
    )
    assert "forstod ikke rettelsen" in outcome.text
    assert outcome.presentation is None
    assert action_handler.store.peek(key) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correction",
    ["spørsmål: Nytt spørsmål?", "question: New question?"],
)
async def test_poll_create_accepts_natural_question_correction_labels(
    action_handler,
    message,
    correction,
):
    key = conversation_key_from_message(message)
    pending = ready_confirmation(
        action_handler.store,
        key,
        IntentResult(
            BotIntent.POLL_CREATE,
            0.99,
            {"poll": {"question": "Mat?", "options": ["Pizza", "Taco"]}},
            source=IntentSource.SEMANTIC,
            risk=IntentRisk.ADDITIVE,
            requires_confirmation=True,
        ),
        "Avstemning",
    )

    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance(correction),
        reference_time=FIXED_NOW,
    )

    assert outcome.presentation is not None
    expected = "New question?" if correction.startswith("question") else "Nytt spørsmål?"
    assert outcome.presentation.routes[0].payload["poll"]["question"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correction",
    [
        "tittel: Nytt spørsmål?",
        "spørsmål: Nytt spørsmål?",
        "question: Nytt spørsmål?",
    ],
)
async def test_poll_edit_question_correction_keeps_frozen_target(
    action_handler,
    message,
    correction,
):
    key = conversation_key_from_message(message)
    poll_guard = guard(
        PendingTargetFamily.POLL,
        "Mat?",
        "spørsmål: Mat?; alternativer: Pizza, Taco",
    )
    pending = ready_confirmation(
        action_handler.store,
        key,
        IntentResult(
            BotIntent.POLL_EDIT,
            0.99,
            {"poll_edit": {"poll_id": "poll-a", "question": "Mat?"}},
            source=IntentSource.SEMANTIC,
            risk=IntentRisk.MUTATING,
            requires_confirmation=True,
        ),
        "Endre avstemning",
        poll_guard,
    )
    outcome = await action_handler.correct(
        message,
        pending.action_id,
        normalize_utterance(correction),
        reference_time=FIXED_NOW,
    )
    assert outcome.presentation is not None
    assert outcome.presentation.target_guards == (poll_guard,)
    assert (
        outcome.presentation.routes[0].payload["poll_edit"]["question"]
        == "Nytt spørsmål?"
    )


@pytest.mark.asyncio
async def test_selected_destructive_route_is_restaged_not_dispatched(
    action_handler,
    message,
):
    key = conversation_key_from_message(message)
    routes = (
        IntentResult(BotIntent.CALENDAR_LIST, 1.0),
        destructive_calendar_route(),
    )
    calendar_guard = destructive_calendar_guard()
    pending = ready_choices(
        action_handler.store,
        key,
        routes,
        "Velg",
        (None, calendar_guard),
    )
    outcome = await action_handler.select(message, pending.action_id, 1)
    assert outcome.route is not None
    assert outcome.target_guard == calendar_guard
    assert outcome.route.requires_confirmation is True
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_auth_two_stage_confirmation_hides_code_and_dispatches_once(
    action_handler,
    message,
    caplog,
    capsys,
):
    exchange_code_result = AsyncMock(return_value=True)

    async def dispatch_auth(_message, pending, _reference_time):
        route = pending.routes[0]
        if route.payload.get("action") == "exchange":
            await exchange_code_result(route.payload["code"])
        return DispatchOutcome.success(mutated=True)

    action_handler.dispatch_claimed.side_effect = dispatch_auth
    key = conversation_key_from_message(message)
    initiation = IntentResult(
        BotIntent.CALENDAR_AUTH,
        1.0,
        {"action": "start"},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    initiation_flow = action_handler.prepare_confirmation(message, initiation)
    assert initiation_flow.presentation is not None
    assert "koble til Google Kalender" in "\n".join(
        initiation_flow.presentation.messages
    )
    assert action_handler.store.peek(key) is None
    first = ready_confirmation(
        action_handler.store,
        key,
        initiation,
        initiation_flow.presentation.summary,
    )
    await action_handler.confirm(
        message,
        first.action_id,
        reference_time=FIXED_NOW,
    )

    canary = "SECRET_AUTH_CODE_123"
    exchange = replace(
        initiation,
        payload={
            "action": "exchange",
            "code": canary,
            "state": "SECRET_STATE_456",
        },
    )
    exchange_flow = action_handler.prepare_confirmation(message, exchange)
    assert exchange_flow.presentation is not None
    preview = "\n".join(exchange_flow.presentation.messages)
    assert "kalenderkoden" in preview
    assert "Selve koden vises ikke" in preview
    assert canary not in preview
    assert "SECRET_STATE_456" not in preview
    assert canary not in repr(action_handler.metrics.snapshot())
    second = ready_confirmation(
        action_handler.store,
        key,
        exchange,
        exchange_flow.presentation.summary,
    )
    await action_handler.confirm(
        message,
        second.action_id,
        reference_time=FIXED_NOW,
    )
    replay = await action_handler.confirm(
        message,
        second.action_id,
        reference_time=FIXED_NOW,
    )
    assert replay.dispatch is None
    assert action_handler.dispatch_claimed.await_count == 2
    exchange_code_result.assert_awaited_once_with(canary)
    captured = capsys.readouterr()
    assert canary not in captured.out
    assert canary not in captured.err
    assert canary not in caplog.text
    message.reply.assert_not_awaited()


@pytest.mark.parametrize(
    "bridge",
    (ActionBridge(), ActionBridge(metrics=NLUMetrics())),
)
def test_handler_rejects_split_or_missing_bridge_metric_ownership(bridge):
    store_metrics = NLUMetrics()
    store = PendingActionStore(
        now_provider=lambda: FIXED_NOW,
        metrics=store_metrics,
    )
    with pytest.raises(ValueError, match="bridge_metrics_identity_mismatch"):
        AIActionHandler(
            store=store,
            dispatch_claimed=Mock(),
            metrics=store_metrics,
            temporal_resolver=TemporalResolver(
                now_provider=lambda: FIXED_NOW
            ),
            bridge=bridge,
        )


def confirmation_case(
    intent: BotIntent,
    payload: dict[str, object],
    *expected: str,
    target_guard: PendingTargetGuard | None = None,
):
    return pytest.param(
        IntentResult(
            intent,
            0.99,
            payload,
            risk=IntentRisk.MUTATING,
            requires_confirmation=True,
        ),
        target_guard,
        expected,
        id=f"{intent.value}-{len(expected)}-{expected[0]}",
    )


_CALENDAR_GUARD = destructive_calendar_guard()
_REMINDER_GUARD = guard(
    PendingTargetFamily.REMINDER,
    "Ringe legen",
    display_fields=(
        ("tekst", "Ringe legen"),
        ("dato", "15.07.2026"),
        ("tid", "09:00"),
        ("status", "ikke fullført"),
    ),
)
_POLL_GUARD = guard(
    PendingTargetFamily.POLL,
    "Mat?",
    "Mat? — Taco",
    display_fields=(
        ("spørsmål", "Mat?"),
        ("alternativer", "1. Pizza; 2. Taco"),
    ),
)
_POLL_VOTE_GUARD = guard(
    PendingTargetFamily.POLL,
    "Mat?",
    "Mat? — Taco",
    display_fields=(("spørsmål", "Mat?"), ("valg", "Taco")),
)
_WATCH_GUARD = guard(
    PendingTargetFamily.WATCHLIST,
    "The Bear",
    display_fields=(
        ("tittel", "The Bear"),
        ("type", "series"),
        ("sjanger", "drama"),
    ),
)
_QUOTE_GUARD = guard(
    PendingTargetFamily.QUOTE,
    "Et sitat",
    display_fields=(("tekst", "Et sitat"), ("forfatter", "Ola")),
)
_BIRTHDAY_GUARD = guard(
    PendingTargetFamily.BIRTHDAY,
    "Ola Nordmann",
    display_fields=(
        ("person", "Ola Nordmann"),
        ("dato", "02.03.1991"),
    ),
)


CONFIRMATION_CASES = (
    confirmation_case(
        BotIntent.CALENDAR_ITEM,
        {
            "calendar_item": {
                "title": "Legetime",
                "date": "15.07.2026",
                "time": "09:00",
                "recurrence": "weekly",
            }
        },
        "opprette kalenderoppføringen",
        "Legetime",
        "15.07.2026",
        "09:00",
        "weekly",
    ),
    confirmation_case(
        BotIntent.CALENDAR_EDIT,
        {
            "calendar_edit": {
                "target": "Legetime",
                "changes": {"title": "Tannlege", "time": "10:00"},
            }
        },
        "endre kalenderoppføringen",
        "Møte med Ola",
        "15.07.2026",
        "14:00",
        "Tannlege",
        "10:00",
        target_guard=_CALENDAR_GUARD,
    ),
    confirmation_case(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": "Legetime"}},
        "slette kalenderoppføringen",
        "Møte med Ola",
        target_guard=_CALENDAR_GUARD,
    ),
    confirmation_case(
        BotIntent.CALENDAR_COMPLETE,
        {"calendar_target": {"target": "Legetime"}},
        "fullføre kalenderoppføringen",
        "Møte med Ola",
        target_guard=_CALENDAR_GUARD,
    ),
    confirmation_case(
        BotIntent.CALENDAR_CLEAR,
        {"calendar_target": {"all": True}},
        "tømme hele kalenderen",
        "Møte med Ola",
        target_guard=_CALENDAR_GUARD,
    ),
    confirmation_case(
        BotIntent.CALENDAR_SYNC,
        {},
        "synkronisere kalenderen",
    ),
    confirmation_case(
        BotIntent.CALENDAR_AUTH,
        {"action": "start"},
        "koble til Google Kalender",
    ),
    confirmation_case(
        BotIntent.REMINDER_CREATE,
        {
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_date": "15.07.2026",
                "time": "09:00",
                "recurrence": "weekly",
            }
        },
        "opprette påminnelsen",
        "Ringe legen",
        "15.07.2026",
        "09:00",
        "weekly",
    ),
    confirmation_case(
        BotIntent.REMINDER_EDIT,
        {
            "reminder": {
                "action": "edit",
                "number": 1,
                "changes": {"text": "Ringe tannlegen", "time": "10:00"},
            }
        },
        "endre påminnelsen",
        "Ringe legen",
        "Ringe tannlegen",
        "10:00",
        target_guard=_REMINDER_GUARD,
    ),
    confirmation_case(
        BotIntent.REMINDER_DELETE,
        {"reminder": {"action": "delete", "number": 1}},
        "slette påminnelsen",
        "Ringe legen",
        target_guard=_REMINDER_GUARD,
    ),
    confirmation_case(
        BotIntent.REMINDER_COMPLETE,
        {"reminder": {"action": "complete", "number": 1}},
        "fullføre påminnelsen",
        "Ringe legen",
        target_guard=_REMINDER_GUARD,
    ),
    confirmation_case(
        BotIntent.POLL_CREATE,
        {"poll": {"question": "Mat?", "options": ["Pizza", "Taco"]}},
        "opprette avstemningen",
        "Mat?",
        "1. Pizza",
        "2. Taco",
    ),
    confirmation_case(
        BotIntent.POLL_VOTE,
        {"vote": {"poll_id": "poll-a", "option": 2}},
        "stemme i avstemningen",
        "Taco",
        target_guard=_POLL_VOTE_GUARD,
    ),
    confirmation_case(
        BotIntent.POLL_EDIT,
        {"poll_edit": {"poll_id": "poll-a", "question": "Ny mat?"}},
        "endre avstemningen",
        "Taco",
        "Ny mat?",
        target_guard=_POLL_GUARD,
    ),
    confirmation_case(
        BotIntent.POLL_DELETE,
        {"poll_delete": {"poll_id": "poll-a"}},
        "slette avstemningen",
        "Taco",
        target_guard=_POLL_GUARD,
    ),
    confirmation_case(
        BotIntent.POLL_CLOSE,
        {"poll_close": {"poll_id": "poll-a"}},
        "lukke avstemningen",
        "Taco",
        target_guard=_POLL_GUARD,
    ),
    confirmation_case(
        BotIntent.WATCHLIST,
        {
            "watchlist": {
                "action": "add",
                "title": "The Bear",
                "type": "series",
                "genre": "drama",
            }
        },
        "legge til i se-listen",
        "The Bear",
        "series",
        "drama",
    ),
    confirmation_case(
        BotIntent.WATCHLIST,
        {
            "watchlist": {
                "action": "edit",
                "index": 1,
                "title": "The Bear 2",
                "comment": "Se snart",
            }
        },
        "endre elementet i se-listen",
        "The Bear",
        "The Bear 2",
        "Se snart",
        target_guard=_WATCH_GUARD,
    ),
    confirmation_case(
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "remove", "index": 1}},
        "fjerne elementet fra se-listen",
        "The Bear",
        target_guard=_WATCH_GUARD,
    ),
    confirmation_case(
        BotIntent.QUOTE,
        {"quote": {"action": "save", "text": "Et sitat", "author": "Ola"}},
        "lagre sitatet",
        "Et sitat",
        "Ola",
    ),
    confirmation_case(
        BotIntent.QUOTE_EDIT,
        {"quote": {"action": "edit", "index": 1, "text": "Nytt sitat"}},
        "endre sitatet",
        "Et sitat",
        "Nytt sitat",
        target_guard=_QUOTE_GUARD,
    ),
    confirmation_case(
        BotIntent.QUOTE_DELETE,
        {"quote": {"action": "delete", "index": 1}},
        "slette sitatet",
        "Et sitat",
        target_guard=_QUOTE_GUARD,
    ),
    confirmation_case(
        BotIntent.BIRTHDAY_CREATE,
        {
            "birthday": {
                "action": "add",
                "user_id": 7,
                "display_name": "Ola Nordmann",
                "day": 2,
                "month": 3,
                "year": 1991,
            }
        },
        "lagre bursdagen",
        "Ola Nordmann",
        "2",
        "3",
        "1991",
    ),
    confirmation_case(
        BotIntent.BIRTHDAY_EDIT,
        {
            "birthday": {
                "action": "edit",
                "user_id": 7,
                "day": 3,
                "month": 4,
                "year": 1992,
            }
        },
        "endre bursdagen",
        "Ola Nordmann",
        "3",
        "4",
        "1992",
        target_guard=_BIRTHDAY_GUARD,
    ),
    confirmation_case(
        BotIntent.MEMORY_DELETE,
        {"memory": {"content": "HEMMELIG_INNHOLD", "confirmed": True}},
        "slette det jeg husker om deg",
    ),
    confirmation_case(
        BotIntent.SET_LOCATION,
        {"city": "Tromsø"},
        "lagre bostedet",
        "Tromsø",
    ),
    confirmation_case(
        BotIntent.PROFILE,
        {"profile": {"action": "status", "value": "dnd"}},
        "endre statusen min",
        "dnd",
    ),
)


@pytest.mark.asyncio
async def test_model_profile_paraphrase_is_staged_with_exact_typed_preview(
    action_handler,
    message,
    routing_context,
):
    outcome = await action_handler.handle_model_response(
        raw=action_line(
            "PROFILE_PLAYING",
            0.98,
            {"value": "Life is Strange"},
        ),
        utterance=normalize_utterance(
            "could you show that you are playing Life is Strange?"
        ),
        routing=routing_context,
        reference_time=FIXED_NOW,
        deterministic_route=None,
        active_poll_count=0,
        active_poll_id=None,
        semantic_action_allowed=True,
    )

    assert outcome.route is not None
    assert outcome.route.payload == {
        "profile": {"action": "playing", "value": "Life is Strange"}
    }
    assert outcome.route.requires_confirmation is True
    staged = action_handler.prepare_confirmation(message, outcome.route)
    assert staged.presentation is not None
    assert staged.presentation.routes == (outcome.route,)
    assert "Life is Strange" in staged.presentation.summary
    action_handler.dispatch_claimed.assert_not_awaited()


@pytest.mark.parametrize("route,target_guard,expected", CONFIRMATION_CASES)
def test_confirmation_details_cover_every_supported_write_proposition(
    route,
    target_guard,
    expected,
):
    details = format_confirmation_details(route, target_guard)
    for value in expected:
        assert value in details
    if route.intent is BotIntent.MEMORY_DELETE:
        assert "HEMMELIG_INNHOLD" not in details


@pytest.mark.parametrize("route,target_guard,expected", CONFIRMATION_CASES)
def test_confirmation_cards_cover_every_supported_write_proposition(
    route,
    target_guard,
    expected,
):
    card = "\n".join(
        (
            format_confirmation_card_heading(route),
            format_confirmation_card_details(route, target_guard),
        )
    )
    aliases = {
        "weekly": "Hver uke",
        "series": "Serie",
        "dnd": "Ikke forstyrr",
    }
    for value in expected:
        assert aliases.get(value, value) in card
    if route.intent is BotIntent.MEMORY_DELETE:
        assert "HEMMELIG_INNHOLD" not in card


def test_calendar_delete_confirmation_is_a_clean_action_card():
    route = destructive_calendar_route()
    target = destructive_calendar_guard()
    details = format_confirmation_card_details(route, target)
    messages = format_confirmation_card_messages(
        heading="🗑️ **Skal jeg slette kalenderoppføringen?**",
        details=details,
        instruction=(
            "Svar `@inebotten ja` for å bekrefte, eller "
            "`@inebotten nei` for å avbryte."
        ),
        optional_prefix="",
        max_messages=5,
        max_message_length=2000,
    )

    assert messages == (
        "🗑️ **Skal jeg slette kalenderoppføringen?**\n\n"
        "**Møte med Ola**\n"
        "📅 15.07.2026 kl. 14:00\n"
        "**Type:** Avtale\n"
        "**Status:** Ikke fullført\n\n"
        "Svar `@inebotten ja` for å bekrefte, eller "
        "`@inebotten nei` for å avbryte.",
    )
    assert "Bekreftelsesdetaljer" not in messages[0]
    assert "1/1" not in messages[0]
    assert "mål:" not in messages[0]


def test_default_model_staging_copy_is_not_repeated_before_action_card(
    action_handler,
    message,
):
    flow = action_handler.prepare_confirmation(
        message,
        semantic_reminder_route(),
        prefix="Jeg har forberedt handlingen, men ikke utført den.",
    )

    assert flow.presentation is not None
    preview = "\n".join(flow.presentation.messages)
    assert "Jeg har forberedt handlingen" not in preview
    assert "Skal jeg opprette påminnelsen?" in preview


@pytest.mark.parametrize(
    ("intent", "payload", "expected"),
    (
        (
            BotIntent.CALENDAR_ITEM,
            {"calendar_item": {"title": "Møte", "date": "17.07.2026"}},
            "📅 **Skal jeg opprette kalenderoppføringen?**",
        ),
        (
            BotIntent.REMINDER_CREATE,
            {"reminder": {"action": "add", "text": "Ring legen"}},
            "🔔 **Skal jeg opprette påminnelsen?**",
        ),
        (
            BotIntent.POLL_CREATE,
            {"poll": {"question": "Mat?", "options": ["Pizza", "Taco"]}},
            "🗳️ **Skal jeg opprette avstemningen?**",
        ),
        (
            BotIntent.WATCHLIST,
            {"watchlist": {"action": "add", "title": "The Bear"}},
            "🎬 **Skal jeg legge til i se-listen?**",
        ),
        (
            BotIntent.QUOTE,
            {"quote": {"action": "save", "text": "Et sitat"}},
            "📝 **Skal jeg lagre sitatet?**",
        ),
        (
            BotIntent.BIRTHDAY_CREATE,
            {
                "birthday": {
                    "action": "add",
                    "user_id": 7,
                    "display_name": "Ola",
                    "day": 2,
                    "month": 3,
                }
            },
            "🎂 **Skal jeg lagre bursdagen?**",
        ),
        (
            BotIntent.SET_LOCATION,
            {"city": "Tromsø"},
            "📍 **Skal jeg lagre bostedet?**",
        ),
        (
            BotIntent.PROFILE,
            {"profile": {"action": "status", "value": "dnd"}},
            "👤 **Skal jeg endre statusen min?**",
        ),
        (
            BotIntent.CALENDAR_AUTH,
            {"action": "start"},
            "🔐 **Skal jeg koble til Google Kalender?**",
        ),
        (
            BotIntent.MEMORY_DELETE,
            {"memory": {"action": "delete"}},
            "⚠️ **Skal jeg slette det jeg husker om deg?**",
        ),
    ),
)
def test_confirmation_headings_use_friendly_copy_and_domain_icons(
    intent,
    payload,
    expected,
):
    route = IntentResult(
        intent,
        0.99,
        payload,
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )

    assert format_confirmation_card_heading(route) == expected


def test_confirmation_card_numbers_only_multipart_previews():
    instruction = "Svar `@inebotten ja` eller `@inebotten nei`."
    messages = format_confirmation_card_messages(
        heading="📝 **Skal jeg lagre sitatet?**",
        details="x" * 120,
        instruction=instruction,
        optional_prefix="",
        max_messages=5,
        max_message_length=140,
    )

    assert len(messages) > 1
    assert all(
        f"_(del {index} av {len(messages)})_" in message
        for index, message in enumerate(messages, start=1)
    )
    assert all(instruction not in message for message in messages[:-1])
    assert messages[-1].endswith(instruction)


@pytest.mark.parametrize("control", (">>> quote", "> quote", "# heading", "- list"))
def test_confirmation_card_marks_continuations_before_midline_markdown(control):
    heading = "📝 **Skal jeg lagre sitatet?**"
    instruction = "Svar `@inebotten ja` eller `@inebotten nei`."
    marker = "↪ "
    reserved = len(
        f"{heading} _(del 5 av 5)_\n\n\n\n{instruction}"
    ) + len(marker)
    first_piece_size = 2000 - reserved

    messages = format_confirmation_card_messages(
        heading=heading,
        details=("x" * first_piece_size) + control,
        instruction=instruction,
        optional_prefix="",
        max_messages=5,
        max_message_length=2000,
    )

    assert len(messages) == 2
    continuation = messages[1].split("\n\n", 1)[1]
    assert continuation.startswith(f"{marker}{control}")


def test_watchlist_edit_confirmation_shows_nullable_fields_are_removed():
    route = IntentResult(
        BotIntent.WATCHLIST,
        0.99,
        {
            "watchlist": {
                "action": "edit",
                "index": 1,
                "genre": None,
                "comment": None,
            }
        },
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    target = guard(
        PendingTargetFamily.WATCHLIST,
        "The Bear",
        display_fields=(
            ("tittel", "The Bear"),
            ("type", "series"),
            ("sjanger", "drama"),
            ("kommentar", "Se snart"),
        ),
    )

    details = format_confirmation_card_details(route, target)

    assert "**Endringer**" in details
    assert "**Sjanger:** Fjern" in details
    assert "**Kommentar:** Fjern" in details


def test_poll_vote_confirmation_uses_selected_text_without_internal_number():
    route = IntentResult(
        BotIntent.POLL_VOTE,
        0.99,
        {"vote": {"poll_id": "poll-a", "option": 2}},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    target = guard(
        PendingTargetFamily.POLL,
        "Mat?",
        display_fields=(("spørsmål", "Mat?"), ("valg", "Taco")),
    )

    details = format_confirmation_card_details(route, target)

    assert details == "**Mat?**\n**Valg:** Taco"
    assert "**Valg:** 2" not in details


def test_birthday_cards_render_one_date_instead_of_repeating_date_parts():
    target = guard(
        PendingTargetFamily.BIRTHDAY,
        "Ola Nordmann",
        display_fields=(
            ("person", "Ola Nordmann"),
            ("dato", "02.03.1991"),
        ),
    )
    create = IntentResult(
        BotIntent.BIRTHDAY_CREATE,
        0.99,
        {
            "birthday": {
                "action": "add",
                "user_id": 7,
                "display_name": "Ola Nordmann",
                "day": 2,
                "month": 3,
                "year": 1991,
            }
        },
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    edit = replace(
        create,
        intent=BotIntent.BIRTHDAY_EDIT,
        payload={
            "birthday": {
                "action": "edit",
                "user_id": 7,
                "day": 3,
                "month": 4,
                "year": 1992,
            }
        },
        risk=IntentRisk.MUTATING,
    )

    assert format_confirmation_card_details(create, target) == (
        "**Ola Nordmann**\n📅 02.03.1991"
    )
    assert format_confirmation_card_details(edit, target) == (
        "**Ola Nordmann**\n"
        "📅 02.03.1991\n\n"
        "**Endringer**\n"
        "**Ny dato:** 03.04.1992"
    )


def test_reminder_cards_hide_canonical_time_transport_fields():
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.99,
        {
            "reminder": {
                "action": "add",
                "text": "Ring legen",
                "due_at": "2026-07-20T13:00:00+00:00",
                "due_date": "20.07.2026",
                "time": "15:00",
                "timezone": "Europe/Oslo",
            }
        },
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    due_at_only = replace(
        route,
        payload={
            "reminder": {
                "action": "add",
                "text": "Ring legen",
                "due_at": "2026-07-20T13:00:00+00:00",
                "timezone": "Europe/Oslo",
            }
        },
    )

    for candidate in (route, due_at_only):
        details = format_confirmation_card_details(candidate, None)
        assert "📅 20.07.2026 kl. 15:00" in details
        assert "2026-07-20T13:00:00+00:00" not in details
        assert "Europe/Oslo" not in details
        assert "Tidspunkt" not in details
        assert "Tidssone" not in details


@pytest.mark.parametrize(
    ("day", "rrule_day", "expected_day", "date", "days_offset"),
    (
        ("fredag", "FR", "Fredag", "17.07.2026", 1),
        ("måndag", "MO", "Måndag", "20.07.2026", 4),
        ("tysdag", "TU", "Tysdag", "21.07.2026", 5),
        ("laurdag", "SA", "Laurdag", "18.07.2026", 2),
        ("sundag", "SU", "Sundag", "19.07.2026", 3),
    ),
)
def test_calendar_card_hides_redundant_offset_and_recurrence_alias(
    day,
    rrule_day,
    expected_day,
    date,
    days_offset,
):
    payload = validate_intent_payload(
        BotIntent.CALENDAR_ITEM,
        {
            "title": "Ukentlig møte",
            "date": date,
            "days_offset": days_offset,
            "recurrence": "weekly",
            "recurrence_day": day,
            "rrule_day": rrule_day,
        },
    )
    route = IntentResult(
        BotIntent.CALENDAR_ITEM,
        0.99,
        {"calendar_item": payload},
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )

    details = format_confirmation_card_details(route, None)

    assert f"📅 {date}" in details
    assert "Dager fra nå" not in details
    assert details.count(f"**Gjentakelsesdag:** {expected_day}") == 1
    assert rrule_day not in details


def test_conflicting_recurrence_days_fail_closed_before_confirmation():
    route = IntentResult(
        BotIntent.CALENDAR_ITEM,
        0.99,
        {
            "calendar_item": {
                "title": "Ukentlig møte",
                "date": "17.07.2026",
                "recurrence": "weekly",
                "recurrence_day": "monday",
                "rrule_day": "FR",
            }
        },
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )

    with pytest.raises(
        UnsupportedConfirmationSummary,
        match="conflicting_confirmation_fields",
    ):
        format_confirmation_card_details(route, None)


def test_reminder_edit_renders_removed_date_and_time_as_fields_not_icons():
    route = IntentResult(
        BotIntent.REMINDER_EDIT,
        0.99,
        {
            "reminder": {
                "action": "edit",
                "reminder_id": "reminder-a",
                "changes": {"due_date": None, "time": None},
            }
        },
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )

    details = format_confirmation_card_details(route, _REMINDER_GUARD)

    assert "**Dato:** Fjern" in details
    assert "**Tid:** Fjern" in details
    assert "📅 fjern" not in details
    assert "kl. fjern" not in details


def test_long_poll_question_is_rendered_once_without_truncated_headline():
    question = "Q" * 300
    route = IntentResult(
        BotIntent.POLL_DELETE,
        0.99,
        {"poll_delete": {"poll_id": "poll-a"}},
        risk=IntentRisk.DESTRUCTIVE,
        requires_confirmation=True,
    )
    target = guard(
        PendingTargetFamily.POLL,
        question,
        display_fields=(("spørsmål", question),),
    )

    details = format_confirmation_card_details(route, target)

    assert details == f"**Spørsmål:** {question}"
    assert details.count("Q" * 200) == 1


def test_memory_delete_and_singular_calendar_clear_use_clean_copy():
    memory_route = IntentResult(
        BotIntent.MEMORY_DELETE,
        0.99,
        {"memory": {"action": "delete"}},
        risk=IntentRisk.DESTRUCTIVE,
        requires_confirmation=True,
    )
    memory_guard = guard(PendingTargetFamily.MEMORY, "lagret brukerminne")
    clear_route = IntentResult(
        BotIntent.CALENDAR_CLEAR,
        0.99,
        {"calendar_target": {"all": True}},
        risk=IntentRisk.DESTRUCTIVE,
        requires_confirmation=True,
    )
    clear_guard = guard(
        PendingTargetFamily.CALENDAR,
        "hele kalenderen",
        display_fields=(
            ("omfang", "hele kalenderen"),
            ("oppføringer", "1"),
        ),
    )

    assert format_confirmation_card_details(memory_route, memory_guard) == ""
    assert format_confirmation_card_details(clear_route, clear_guard) == (
        "Hele **1 oppføring** blir slettet."
    )


@pytest.mark.parametrize(
    ("action", "value", "expected"),
    (
        ("status", "online", "**Status:** Pålogget"),
        ("status", "offline", "**Status:** Frakoblet"),
        ("status", "idle", "**Status:** Borte"),
        ("status", "dnd", "**Status:** Ikke forstyrr"),
        ("status", "invisible", "**Status:** Usynlig"),
        ("playing", "Baldur's Gate 3", "**Aktivitet:** Baldur's Gate 3"),
        ("watching", "The Bear", "**Aktivitet:** The Bear"),
    ),
)
def test_profile_confirmation_uses_user_facing_field_labels(
    action,
    value,
    expected,
):
    route = IntentResult(
        BotIntent.PROFILE,
        0.99,
        {"profile": {"action": action, "value": value}},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )

    details = format_confirmation_card_details(route, None)

    assert details == expected
    assert "**Verdi:**" not in details


@pytest.mark.parametrize(
    ("route", "expected", "raw"),
    (
        (
            IntentResult(
                BotIntent.CALENDAR_ITEM,
                0.99,
                {
                    "calendar_item": {
                        "title": "Legetime",
                        "date": "15.07.2026",
                        "recurrence": "weekly",
                    }
                },
                risk=IntentRisk.ADDITIVE,
                requires_confirmation=True,
            ),
            "**Gjentakelse:** Hver uke",
            "weekly",
        ),
        (
            IntentResult(
                BotIntent.WATCHLIST,
                0.99,
                {
                    "watchlist": {
                        "action": "add",
                        "title": "The Bear",
                        "type": "series",
                    }
                },
                risk=IntentRisk.ADDITIVE,
                requires_confirmation=True,
            ),
            "**Type:** Serie",
            "series",
        ),
        (
            IntentResult(
                BotIntent.PROFILE,
                0.99,
                {"profile": {"action": "status", "value": "dnd"}},
                risk=IntentRisk.MUTATING,
                requires_confirmation=True,
            ),
            "**Status:** Ikke forstyrr",
            "dnd",
        ),
    ),
)
def test_confirmation_cards_humanize_internal_enum_values(route, expected, raw):
    details = format_confirmation_card_details(route, None)

    assert expected in details
    assert raw not in details


def test_confirmation_neutralizes_discord_controls_urls_and_bidi_losslessly():
    canary = (
        "@everyone <@123> <#456> <t:123:R> </foo:123> <:x:123> "
        "<a:x:123> >>> https://example.test/a_b\u202e\nslutt"
    )
    route = replace(
        semantic_reminder_route(),
        payload={"reminder": {"action": "add", "text": canary}},
    )
    details = format_confirmation_details(route, None)
    assert "@everyone" not in details
    assert "<@123>" not in details
    assert "<#456>" not in details
    assert "https://" not in details
    assert "<t:" not in details
    assert "</foo:" not in details
    assert "<:x:" not in details
    assert "<a:x:" not in details
    assert ">>>" not in details
    assert "‹t:123:R›" in details
    assert "https：//example.test/a\\_b" in details
    assert "\u202e" not in details
    assert "a\\_b slutt" in details
    assert neutralize_confirmation_value("Pay\nPal\tlater") == "Pay Pal later"


def test_card_preview_accepts_schema_maximum_backslashes_and_balances_markdown():
    instruction = "Svar `@inebotten ja` eller `@inebotten nei`."
    for text in ("\\" * 2000, "*" * 2000):
        route = IntentResult(
            BotIntent.QUOTE,
            0.99,
            {"quote": {"action": "save", "text": text}},
            risk=IntentRisk.ADDITIVE,
            requires_confirmation=True,
        )
        details = format_confirmation_card_details(route, None)
        messages = format_confirmation_card_messages(
            heading=format_confirmation_card_heading(route),
            details=details,
            instruction=instruction,
            optional_prefix="",
            max_messages=5,
            max_message_length=2000,
        )

        assert details.startswith("**Tekst:** ")
        assert len(messages) <= 5
        assert all(len(message) <= 2000 for message in messages)
        assert all(message.count("**") % 2 == 0 for message in messages)
        assert sum(message.count("\\") for message in messages) == details.count(
            "\\"
        )


def test_schema_maximum_quote_edit_fits_in_five_card_messages():
    route = IntentResult(
        BotIntent.QUOTE_EDIT,
        0.99,
        {
            "quote": {
                "action": "edit",
                "index": 1,
                "text": "*" * 2000,
                "author": "*" * 200,
            }
        },
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    target = guard(
        PendingTargetFamily.QUOTE,
        "Langt sitat",
        display_fields=(
            ("tekst", "*" * 1700),
            ("forfatter", "*" * 200),
        ),
    )
    details = format_confirmation_card_details(route, target)

    messages = format_confirmation_card_messages(
        heading=format_confirmation_card_heading(route),
        details=details,
        instruction="Svar `@inebotten ja` eller `@inebotten nei`.",
        optional_prefix="",
        max_messages=5,
        max_message_length=2000,
    )

    assert len(messages) <= 5
    assert all(len(message) <= 2000 for message in messages)
    assert sum(message.count(r"\*") for message in messages) == 4_100


def test_schema_maximum_calendar_edit_fits_without_echoing_old_description():
    route = IntentResult(
        BotIntent.CALENDAR_EDIT,
        0.99,
        {
            "calendar_edit": {
                "target": "calendar-a",
                "changes": {
                    "title": "*" * 200,
                    "description": "*" * 2000,
                },
            }
        },
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    target = guard(
        PendingTargetFamily.CALENDAR,
        "*" * 200,
        display_fields=(
            ("tittel", "*" * 200),
            ("dato", "24.07.2026"),
            ("tid", "09:00"),
            ("type", "event"),
            ("status", "ikke fullført"),
        ),
    )
    details = format_confirmation_card_details(route, target)

    messages = format_confirmation_card_messages(
        heading=format_confirmation_card_heading(route),
        details=details,
        instruction="Svar `@inebotten ja` eller `@inebotten nei`.",
        optional_prefix="",
        max_messages=5,
        max_message_length=2000,
    )

    assert len(messages) <= 5
    assert all(len(message) <= 2000 for message in messages)
    assert sum(message.count(r"\*") for message in messages) == 2_400


def _details_from_messages(messages: tuple[str, ...], instruction: str) -> str:
    pieces = []
    for index, message in enumerate(messages):
        piece = message.split(":\n", 1)[1]
        if index == len(messages) - 1:
            piece = piece.removesuffix(f"\n{instruction}")
        pieces.append(piece)
    return "".join(pieces)


def test_maximum_material_values_are_complete_and_prefix_is_sacrificed_first():
    text = "*" * 2000
    options = []
    for index in range(1, 11):
        prefix = f"valg-{index}-"
        options.append(prefix + (str(index % 10) * (100 - len(prefix))))
    route = IntentResult(
        BotIntent.POLL_CREATE,
        0.99,
        {"poll": {"question": "Q" * 300, "options": options}},
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    details = format_confirmation_details(route, None)
    instruction = "Svar @inebotten ja eller nei."
    messages = format_confirmation_messages(
        details=details,
        instruction=instruction,
        optional_prefix="P" * 10_000,
        max_messages=5,
        max_message_length=2000,
    )
    assert len(messages) <= 5
    assert all(len(message) <= 2000 for message in messages)
    assert _details_from_messages(messages, instruction) == details
    assert neutralize_confirmation_value(options[-1]) in details

    long_quote = IntentResult(
        BotIntent.QUOTE,
        0.99,
        {"quote": {"action": "save", "text": text}},
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    quote_details = format_confirmation_details(long_quote, None)
    quote_messages = format_confirmation_messages(
        details=quote_details,
        instruction=instruction,
        optional_prefix="P" * 10_000,
        max_messages=5,
        max_message_length=2000,
    )
    assert _details_from_messages(quote_messages, instruction) == quote_details

    for route in (
        IntentResult(
            BotIntent.CALENDAR_ITEM,
            0.99,
            {
                "calendar_item": {
                    "title": "Møte",
                    "date": "15.07.2026",
                    "description": "D" * 2000,
                }
            },
            risk=IntentRisk.ADDITIVE,
            requires_confirmation=True,
        ),
        IntentResult(
            BotIntent.WATCHLIST,
            0.99,
            {
                "watchlist": {
                    "action": "add",
                    "title": "The Bear",
                    "comment": "C" * 2000,
                }
            },
            risk=IntentRisk.ADDITIVE,
            requires_confirmation=True,
        ),
    ):
        material_details = format_confirmation_details(route, None)
        material_messages = format_confirmation_messages(
            details=material_details,
            instruction=instruction,
            optional_prefix="",
            max_messages=5,
            max_message_length=2000,
        )
        assert (
            _details_from_messages(material_messages, instruction)
            == material_details
        )


def test_confirmation_previews_distinguish_late_text_and_tenth_option():
    first_text = "A" * 180 + "x"
    second_text = "A" * 180 + "y"
    first = replace(
        semantic_reminder_route(),
        payload={"reminder": {"action": "add", "text": first_text}},
    )
    second = replace(
        semantic_reminder_route(),
        payload={"reminder": {"action": "add", "text": second_text}},
    )
    assert format_confirmation_details(first, None) != format_confirmation_details(
        second,
        None,
    )

    options_a = [f"valg {index}" for index in range(1, 11)]
    options_b = [*options_a[:-1], "helt annet tiende valg"]
    poll_a = IntentResult(
        BotIntent.POLL_CREATE,
        0.99,
        {"poll": {"question": "Mat?", "options": options_a}},
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    poll_b = replace(
        poll_a,
        payload={"poll": {"question": "Mat?", "options": options_b}},
    )
    assert format_confirmation_details(poll_a, None) != format_confirmation_details(
        poll_b,
        None,
    )


def test_calendar_auth_code_never_appears_in_confirmation_or_choice_label():
    canary = "SECRET_AUTH_CODE_123"
    route = IntentResult(
        BotIntent.CALENDAR_AUTH,
        1.0,
        {"action": "exchange", "code": canary, "state": "state-canary"},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    details = format_confirmation_details(route, None)
    label = format_choice_label(route, None)
    assert "sende inn den oppgitte kalenderkoden" in details
    assert canary not in details
    assert "state-canary" not in details
    assert canary not in label


def test_unsupported_write_summary_fails_closed():
    route = IntentResult(
        BotIntent.DAILY_DIGEST,
        1.0,
        {"unexpected": "value"},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    with pytest.raises(UnsupportedConfirmationSummary):
        format_confirmation_details(route, None)


def test_preview_refuses_to_drop_authoritative_details():
    with pytest.raises(ConfirmationPreviewTooLarge):
        format_confirmation_messages(
            details="x" * 20_000,
            instruction="bekreft",
            optional_prefix="",
            max_messages=5,
            max_message_length=2000,
        )

"""End-to-end natural-language action orchestration without live services."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    MessageSendResult,
)
from core.intent_models import BotIntent, IntentResult, IntentRisk, IntentSource
from core.message_context import (
    conversation_key_from_message,
    routing_context_from_message,
)
from core.message_monitor import bounded_discord_text_chunks
from core.mutation_coordinator import CALENDAR_SHARED_SCOPE
from core.pending_actions import PendingStatus
from core.rate_limiter import RateLimiter
from core.send_receipt import DiscordSendCoordinator
from core.utterance import normalize_utterance
from features.base_handler import BaseHandler
from features.memory_handler import MemoryHandler
from memory.localization import Localization
from tests.test_ai_action_handler import action_line
from tests.test_message_monitor_routing import (
    MessageMonitorRoutingTests,
    RecordingMessage,
)


@pytest.fixture
def monitor():
    return MessageMonitorRoutingTests().make_monitor()


def _calendar_row():
    return {
        "id": "calendar-1",
        "title": "Legetime",
        "date": "16.07.2026",
        "time": "12:00",
        "type": "event",
        "description": "Kontroll",
        "completed": False,
        "recurrence": None,
        "recurrence_sequence": 0,
    }


@pytest.mark.asyncio
async def test_deterministic_destructive_route_stages_then_confirms_once(monitor):
    row = _calendar_row()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (dict(row),)
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    monitor.calendar.get_upcoming = (
        lambda guild_id, days=365, reference_time=None: [dict(row)]
    )
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = handler

    first = RecordingMessage("@inebotten slett kalenderoppføring 1")
    await monitor.handle_message(first)

    handler.assert_not_awaited()
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(first)
    )
    assert pending is not None
    assert pending.status is PendingStatus.READY
    assert pending.routes[0].payload["calendar_target"]["target"] == "calendar-1"
    assert "Bekreftelsesdetaljer" in first.replies[0]

    await monitor.handle_message(RecordingMessage("@inebotten ja"))
    await monitor.handle_message(RecordingMessage("@inebotten ja"))

    handler.assert_awaited_once()
    assert monitor.pending_actions.counts()["completed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("utterance", "method_name", "return_value", "visible_text"),
    [
        (
            "vis minnet mitt",
            "format_user_memory_for_user",
            "Jeg husker favorittfargen din.",
            "Jeg husker favorittfargen din.",
        ),
        (
            "eksporter minnet mitt",
            "export_user_memory",
            {"facts": ["favorittfarge: blå"]},
            "favorittfarge",
        ),
    ],
)
async def test_memory_read_intents_cross_the_typed_monitor_boundary(
    monitor,
    utterance,
    method_name,
    return_value,
    visible_text,
):
    method = AsyncMock(return_value=return_value)
    setattr(monitor.user_memory, method_name, method)
    monitor.handlers["memory"] = MemoryHandler(monitor)
    message = RecordingMessage(f"@inebotten {utterance}")

    outcome = await monitor.handle_message(message)

    assert outcome.ok
    method.assert_awaited_once()
    assert len(message.replies) == 1
    assert visible_text in message.replies[0]


@pytest.mark.asyncio
async def test_memory_delete_requires_preview_and_executes_only_once(monitor):
    monitor.user_memory.snapshot_pending_user = lambda user_id: {
        "user_id": user_id,
        "facts": ["favorittfarge: blå"],
    }
    delete = AsyncMock(return_value=True)
    monitor.user_memory.delete_user_memory_result = delete
    monitor.handlers["memory"] = MemoryHandler(monitor)

    preview = RecordingMessage("@inebotten slett minnet mitt bekreft")
    await monitor.handle_message(preview)

    delete.assert_not_awaited()
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(preview)
    )
    assert pending is not None and pending.status is PendingStatus.READY
    assert pending.routes[0].payload == {"memory": {"action": "delete"}}
    assert len(preview.replies) == 1

    confirmation = RecordingMessage("@inebotten ja")
    await monitor.handle_message(confirmation)
    provider = AsyncMock(
        return_value=(
            True,
            action_line("SHOW_DASHBOARD", 1.0, {}),
        )
    )
    monitor.hermes = type(
        "Hermes",
        (),
        {"generate_response": provider},
    )()
    dashboard = AsyncMock(return_value="Uventet oversikt")
    monitor._generate_dashboard = dashboard
    duplicate = RecordingMessage("@inebotten ja")
    await monitor.handle_message(duplicate)

    delete.assert_awaited_once_with(7)
    assert monitor.pending_actions.counts()["completed"] == 1
    assert confirmation.replies == [
        "✅ Ferdig. Jeg har slettet brukerminnet ditt."
    ]
    provider.assert_not_awaited()
    dashboard.assert_not_awaited()
    assert duplicate.replies == [
        "Det finnes ingen aktiv bekreftelse å utføre."
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected_payload", "preview_text", "hidden_text"),
    [
        (
            "kalender auth",
            {},
            "starte kalenderautorisering",
            None,
        ),
        (
            "kalender auth AbC_12",
            {"auth_code": "AbC_12"},
            "kalenderkoden",
            "AbC_12",
        ),
    ],
)
async def test_calendar_auth_stages_before_start_or_code_exchange(
    monitor,
    command,
    expected_payload,
    preview_text,
    hidden_text,
):
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_auth = handler
    preview = RecordingMessage(f"@inebotten {command}")

    await monitor.handle_message(preview)

    handler.assert_not_awaited()
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(preview)
    )
    assert pending is not None and pending.status is PendingStatus.READY
    assert pending.routes[0].intent is BotIntent.CALENDAR_AUTH
    assert pending.routes[0].payload == expected_payload
    assert preview_text in preview.replies[0]
    if hidden_text is not None:
        assert hidden_text not in preview.replies[0]

    await monitor.handle_message(RecordingMessage("@inebotten ja"))

    handler.assert_awaited_once()
    assert handler.await_args.args[1] == expected_payload


@pytest.mark.asyncio
async def test_semantic_natural_language_reminder_is_staged_not_executed(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "REMINDER_CREATE",
                        0.99,
                        {
                            "text": "ringe legen",
                            "due_date": "16.07.2026",
                        },
                        reply="Det kan jeg ordne.",
                    ),
                )
            )
        },
    )()
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["reminders"].handle_reminder_create = handler
    message = RecordingMessage(
        "@inebotten sørg for at jeg ringer legen i morgen"
    )

    await monitor.handle_message(message)

    handler.assert_not_awaited()
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None
    assert pending.status is PendingStatus.READY
    assert pending.routes[0].intent is BotIntent.REMINDER_CREATE
    assert "ringe legen" in message.replies[0]
    decisions = monitor.nlu_metrics.snapshot()["decisions"]
    assert decisions == {
        "intent=reminder_create|source=semantic|outcome=staged": 1
    }

    await monitor.handle_message(RecordingMessage("@inebotten ja"))
    handler.assert_awaited_once()
    decisions = monitor.nlu_metrics.snapshot()["decisions"]
    assert decisions[
        "intent=reminder_create|source=semantic|outcome=executed"
    ] == 1


@pytest.mark.asyncio
async def test_semantic_profile_paraphrase_stages_then_dispatches_typed_payload(
    monitor,
):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "PROFILE_PLAYING",
                        0.99,
                        {"value": "Life is Strange"},
                    ),
                )
            )
        },
    )()
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["profile"] = SimpleNamespace(
        handle_profile_command=handler
    )
    preview = RecordingMessage(
        "@inebotten could you show that you are playing Life is Strange?"
    )

    await monitor.handle_message(preview)

    handler.assert_not_awaited()
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(preview)
    )
    assert pending is not None and pending.status is PendingStatus.READY
    assert pending.routes[0].intent is BotIntent.PROFILE
    assert pending.routes[0].payload == {
        "profile": {"action": "playing", "value": "Life is Strange"}
    }
    assert pending.routes[0].requires_confirmation is True
    assert "Life is Strange" in preview.replies[0]

    await monitor.handle_message(RecordingMessage("@inebotten ja"))

    handler.assert_awaited_once()
    assert handler.await_args.args[1] == {
        "action": "playing",
        "value": "Life is Strange",
    }
    assert monitor.pending_actions.counts()["completed"] == 1


@pytest.mark.asyncio
async def test_handler_value_error_after_write_is_commit_unknown(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "REMINDER_CREATE",
                        0.99,
                        {
                            "text": "ringe legen",
                            "due_date": "16.07.2026",
                        },
                    ),
                )
            )
        },
    )()
    writes = []

    async def mutate_then_raise(*args, **kwargs):
        writes.append((args, kwargs))
        raise ValueError("post_commit_failure")

    monitor.handlers["reminders"].handle_reminder_create = mutate_then_raise
    preview = RecordingMessage(
        "@inebotten sørg for at jeg ringer legen i morgen"
    )
    await monitor.handle_message(preview)

    confirmation = RecordingMessage("@inebotten ja")
    outcome = await monitor.handle_message(confirmation)

    assert len(writes) == 1
    assert not outcome.ok
    assert outcome.commit_unknown
    assert outcome.error_code == "commit_state_unknown"
    assert monitor.pending_actions.counts()["failed"] == 1
    assert "Ikke prøv denne bekreftelsen på nytt" in confirmation.replies[0]


@pytest.mark.asyncio
async def test_same_conversation_confirmation_waits_for_preview_delivery(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "REMINDER_CREATE",
                        0.99,
                        {
                            "text": "ringe legen",
                            "due_date": "16.07.2026",
                        },
                    ),
                )
            )
        },
    )()
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["reminders"].handle_reminder_create = handler
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_preview(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = blocked_preview
    preview_task = asyncio.create_task(
        monitor.handle_message(
            RecordingMessage(
                "@inebotten sørg for at jeg ringer legen i morgen"
            )
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    confirmation_task = asyncio.create_task(
        monitor.handle_message(RecordingMessage("@inebotten ja"))
    )

    await asyncio.sleep(0)
    assert not confirmation_task.done()
    handler.assert_not_awaited()

    release.set()
    await preview_task
    await confirmation_task
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_different_conversations_keep_task_local_language(monitor):
    monitor.loc = Localization(default_lang="no")
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    class BlockingHelp:
        async def handle_help(self, message):
            if message.author.id == 7:
                entered.set()
                await release.wait()
            seen.append((message.author.id, monitor.loc.current_lang))
            return DispatchOutcome.success()

    monitor.handlers["help"] = BlockingHelp()
    english = RecordingMessage("@inebotten what can you do?")
    norwegian = RecordingMessage("@inebotten hjelp")
    norwegian.author = type(
        "Author",
        (),
        {"id": 8, "name": "Norsk bruker"},
    )()
    norwegian.channel = type("Channel", (), {"id": 101})()

    english_task = asyncio.create_task(monitor.handle_message(english))
    await asyncio.wait_for(entered.wait(), timeout=1)
    norwegian_task = asyncio.create_task(monitor.handle_message(norwegian))
    await norwegian_task
    release.set()
    await english_task

    assert sorted(seen) == [(7, "en"), (8, "no")]


@pytest.mark.asyncio
async def test_cancelled_preview_records_the_delivered_semantic_stage(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "REMINDER_CREATE",
                        0.99,
                        {
                            "text": "ringe legen",
                            "due_date": "16.07.2026",
                        },
                    ),
                )
            )
        },
    )()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_preview(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = blocked_preview
    message = RecordingMessage(
        "@inebotten sørg for at jeg ringer legen i morgen"
    )
    task = asyncio.create_task(monitor.handle_message(message))
    await asyncio.wait_for(entered.wait(), timeout=1)

    task.cancel()
    release.set()
    with pytest.raises(DispatchCancelled):
        await task

    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None and pending.status is PendingStatus.READY
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=reminder_create|source=semantic|outcome=staged": 1
    }


@pytest.mark.asyncio
async def test_cancelled_result_copy_send_keeps_confirmed_decision(monitor):
    row = _calendar_row()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (
        dict(row),
    )
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    monitor.calendar.get_upcoming = (
        lambda guild_id, days=365, reference_time=None: [dict(row)]
    )
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = handler
    preview = RecordingMessage("@inebotten slett kalenderoppføring 1")
    await monitor.handle_message(preview)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_result_copy(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor.discord_sender.send_result = blocked_result_copy
    task = asyncio.create_task(
        monitor.handle_message(RecordingMessage("@inebotten ja"))
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled):
        await task

    handler.assert_awaited_once()
    assert monitor.pending_actions.counts()["completed"] == 1
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_delete|source=deterministic|outcome=staged": 1,
        "intent=calendar_delete|source=deterministic|outcome=executed": 1,
    }


@pytest.mark.asyncio
async def test_model_dashboard_has_one_send_owner(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line("SHOW_DASHBOARD", 0.99, {}),
                )
            )
        },
    )()
    dashboard = AsyncMock(return_value="Samlet oversikt")
    monitor._generate_dashboard = dashboard
    message = RecordingMessage("@inebotten kan jeg få alt samlet på ett sted?")

    await monitor.handle_message(message)

    dashboard.assert_awaited_once()
    assert message.replies == ["Samlet oversikt"]


@pytest.mark.asyncio
async def test_model_dashboard_over_discord_limit_is_bounded(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line("SHOW_DASHBOARD", 0.99, {}),
                )
            )
        },
    )()
    monitor._generate_dashboard = AsyncMock(return_value="x" * 2_001)
    message = RecordingMessage("@inebotten gi meg en samlet oversikt")

    await monitor.handle_message(message)

    assert [len(reply) for reply in message.replies] == [2_000, 1]


@pytest.mark.asyncio
async def test_cancelled_semantic_dashboard_keeps_delivered_decision(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line("SHOW_DASHBOARD", 0.99, {}),
                )
            )
        },
    )()
    monitor._generate_dashboard = AsyncMock(return_value="Samlet oversikt")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor.discord_sender.send_result = blocked_send
    task = asyncio.create_task(
        monitor.handle_message(
            RecordingMessage("@inebotten gi meg en samlet oversikt")
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert cancelled.value.outcome.ok
    assert cancelled.value.outcome.response_sent
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=dashboard|source=semantic|outcome=executed": 1
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "send_result",
    [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
async def test_cancelled_monitor_fallback_preserves_mutation_truth(
    monitor,
    send_result,
):
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_sync = handler
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(message, text):
        del message, text
        entered.set()
        await release.wait()
        return send_result

    monitor.discord_sender.send_result = blocked_send
    task = asyncio.create_task(
        monitor.handle_message(
            RecordingMessage("@inebotten kalender synkroniser")
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert cancelled.value.outcome.ok
    assert cancelled.value.outcome.mutated
    assert cancelled.value.outcome.delivery_result == send_result
    handler.assert_awaited_once()
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_sync|source=deterministic|outcome=executed": 1
    }


@pytest.mark.asyncio
async def test_two_model_proposals_are_inert(monitor):
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    "\n".join(
                        [
                            action_line(
                                "CALENDAR_DELETE",
                                1.0,
                                {"target": "1"},
                            ),
                            action_line(
                                "REMINDER_DELETE",
                                1.0,
                                {"number": 1},
                            ),
                        ]
                    ),
                )
            )
        },
    )()
    calendar = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    reminder = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = calendar
    monitor.handlers["reminders"].handle_reminder_delete = reminder

    await monitor.handle_message(RecordingMessage("@inebotten kan du rydde opp?"))

    calendar.assert_not_awaited()
    reminder.assert_not_awaited()
    assert monitor.pending_actions.counts()["ready"] == 0


@pytest.mark.asyncio
async def test_compatibility_model_parser_never_executes_or_sends(monitor):
    calendar = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = calendar
    message = RecordingMessage("@inebotten slett den")

    visible = await monitor._parse_and_execute_actions(
        action_line("CALENDAR_DELETE", 1.0, {"target": "1"}),
        message,
    )

    calendar.assert_not_awaited()
    assert message.replies == []
    assert monitor.pending_actions.counts()["ready"] == 0
    assert isinstance(visible, str) and visible


def test_monitor_owns_one_metrics_resolver_and_clock_graph(monitor):
    assert monitor.intent_router.metrics is monitor.nlu_metrics
    assert monitor.pending_actions.metrics is monitor.nlu_metrics
    assert monitor.ai_action_handler.metrics is monitor.nlu_metrics
    assert monitor.ai_action_handler.bridge.metrics is monitor.nlu_metrics
    assert monitor.intent_router.temporal_resolver is monitor.temporal_resolver
    assert monitor.ai_action_handler.temporal_resolver is monitor.temporal_resolver
    assert monitor.intent_router.now_provider is monitor._reference_time_now
    assert monitor.pending_actions.now_provider is monitor._reference_time_now
    assert monitor.pending_targets.coordinator is monitor.mutation_coordinator


@pytest.mark.asyncio
async def test_rate_rejected_turn_never_routes_or_dispatches(monitor):
    monitor.rate_limiter.can_send = lambda: (
        False,
        "daily_quota_exceeded",
    )
    monitor.rate_limiter.record_dropped = Mock()
    router = Mock()
    monitor.intent_router.route_utterance = router
    provider = AsyncMock(return_value=(True, "should not run"))
    monitor.hermes = type(
        "Hermes",
        (),
        {"generate_response": provider},
    )()
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["watchlist"].handle_watchlist = handler

    outcome = await monitor.handle_message(
        RecordingMessage("@inebotten legg Dune til watchlist")
    )

    assert outcome is None
    router.assert_not_called()
    provider.assert_not_awaited()
    handler.assert_not_awaited()
    monitor.rate_limiter.record_dropped.assert_called_once()
    assert monitor.nlu_metrics.snapshot().get("decisions", {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["clock", "normalize", "router"])
async def test_authorized_turn_boundary_contains_pre_dispatch_faults(
    monitor,
    monkeypatch,
    fault,
):
    if fault == "clock":
        monitor._reference_time_now = lambda: (_ for _ in ()).throw(
            RuntimeError("clock_failed")
        )
    elif fault == "normalize":
        import core.message_monitor as monitor_module

        monkeypatch.setattr(
            monitor_module,
            "normalize_utterance",
            lambda text: (_ for _ in ()).throw(
                RuntimeError("normalize_failed")
            ),
        )
    else:
        class MalformedRouter:
            def route_utterance(self, *args, **kwargs):
                del args, kwargs
                return object()

        monitor.intent_router = MalformedRouter()

    message = RecordingMessage("@inebotten hjelp")
    outcome = await monitor.handle_message(message)

    assert not outcome.ok
    assert outcome.error_code == "turn_exception"
    assert outcome.response_sent
    assert monitor.error_count == 1
    assert len(message.replies) == 1
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=ai_chat|source=deterministic|outcome=failed": 1
    }


@pytest.mark.asyncio
async def test_cancelled_failure_copy_retains_unknown_write_truth(monitor):
    route = IntentResult(
        BotIntent.WATCHLIST,
        0.99,
        {"watchlist": {"action": "add", "title": "Dune"}},
        risk=IntentRisk.ADDITIVE,
    )
    monitor.intent_router.route_utterance = Mock(return_value=route)
    monitor._process_route = AsyncMock(
        side_effect=RuntimeError("post_dispatch_fault")
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor.discord_sender.send_result = blocked_send
    task = asyncio.create_task(
        monitor.handle_message(
            RecordingMessage("@inebotten legg Dune til watchlist")
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert cancelled.value.outcome.commit_unknown
    assert cancelled.value.outcome.response_sent
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=watchlist|source=deterministic|outcome=failed": 1
    }


@pytest.mark.asyncio
async def test_cancelled_confirmation_freeze_error_keeps_semantic_route(
    monitor,
):
    monitor.intent_router.route_utterance = Mock(
        return_value=IntentResult(BotIntent.AI_CHAT, 1.0)
    )
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "CALENDAR_DELETE",
                        0.99,
                        {"target": "1"},
                    ),
                )
            )
        },
    )()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: ()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor.discord_sender.send_result = blocked_send
    task = asyncio.create_task(
        monitor.handle_message(
            RecordingMessage("@inebotten slett kalenderoppføring 1")
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert not cancelled.value.outcome.ok
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_delete|source=semantic|outcome=failed": 1
    }


@pytest.mark.asyncio
async def test_cancelled_choice_freeze_error_keeps_clarify_route(monitor):
    clarify = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(
                    BotIntent.CALENDAR_DELETE,
                    0.9,
                    {"calendar_target": {"target": 1}},
                    source=IntentSource.SEMANTIC,
                    risk=IntentRisk.DESTRUCTIVE,
                    requires_confirmation=True,
                ),
            ),
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.READ_ONLY,
    )
    monitor.intent_router.route_utterance = Mock(return_value=clarify)
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: ()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(message, text):
        del message, text
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor.discord_sender.send_result = blocked_send
    task = asyncio.create_task(
        monitor.handle_message(RecordingMessage("@inebotten hjelp eller slett"))
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert not cancelled.value.outcome.ok
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=clarify|source=semantic|outcome=failed": 1
    }


@pytest.mark.parametrize(
    ("length", "count", "last_suffix"),
    [
        (2_000, 1, ""),
        (2_001, 2, ""),
        (10_000, 5, ""),
        (65_536, 5, "[svaret er forkortet]"),
    ],
)
def test_normal_model_text_is_bounded_to_five_discord_chunks(
    length,
    count,
    last_suffix,
):
    chunks = bounded_discord_text_chunks("x" * length)
    assert len(chunks) == count
    assert all(len(chunk) <= 2_000 for chunk in chunks)
    if last_suffix:
        assert chunks[-1].endswith(last_suffix)


@pytest.mark.asyncio
async def test_partial_text_sequence_is_terminal_unknown_without_replay(monitor):
    monitor._send_response_result = AsyncMock(
        side_effect=(
            MessageSendResult(DeliveryState.DELIVERED),
            MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        )
    )

    result = await monitor._send_text_sequence_result(
        RecordingMessage("@inebotten hei"),
        "x" * 2_001,
    )

    assert result == MessageSendResult(DeliveryState.UNKNOWN, "partial_send")
    assert monitor._send_response_result.await_count == 2


@pytest.mark.asyncio
async def test_failed_confirmation_preview_never_becomes_ready(monitor):
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.99,
        {"reminder": {"action": "add", "text": "Ringe legen"}},
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    flow = monitor.ai_action_handler.prepare_confirmation(message, route)
    monitor._send_response_result = AsyncMock(
        return_value=MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "forbidden",
        )
    )

    outcome = await monitor._send_flow_outcome(
        message,
        flow,
        fallback_route=route,
    )

    assert not outcome.dispatch.ok
    assert outcome.dispatch.error_code == "confirmation_send_failed"
    assert monitor.pending_actions.peek(
        conversation_key_from_message(message)
    ) is None


@pytest.mark.asyncio
async def test_choice_presentation_keeps_clarify_decision_identity(monitor):
    message = RecordingMessage("@inebotten hjelp eller status")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(BotIntent.STATUS, 0.9),
            ),
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.READ_ONLY,
    )

    outcome = await monitor._process_route(
        message,
        utterance=normalize_utterance("hjelp eller status"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )

    assert outcome.dispatch.ok
    assert outcome.decision_route.intent is BotIntent.CLARIFY
    assert outcome.decision_route.source is IntentSource.SEMANTIC
    assert outcome.decision_outcome == "clarified"
    pending = monitor.pending_actions.peek(routing.key)
    assert pending is not None and pending.status is PendingStatus.READY


@pytest.mark.asyncio
async def test_failed_choice_presentation_keeps_clarify_decision_identity(
    monitor,
):
    message = RecordingMessage("@inebotten hjelp eller status")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(BotIntent.STATUS, 0.9),
            ),
        },
        risk=IntentRisk.READ_ONLY,
    )
    monitor._send_response_result = AsyncMock(
        return_value=MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "forbidden",
        )
    )

    outcome = await monitor._process_route(
        message,
        utterance=normalize_utterance("hjelp eller status"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )

    assert not outcome.dispatch.ok
    assert outcome.decision_route.intent is BotIntent.CLARIFY
    assert outcome.decision_outcome == "failed"


@pytest.mark.asyncio
async def test_selected_mutation_reuses_guard_then_confirms(monitor):
    row = _calendar_row()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (
        dict(row),
    )
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = handler
    message = RecordingMessage("@inebotten hjelp eller slett første")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(
                    BotIntent.CALENDAR_DELETE,
                    0.9,
                    {"calendar_target": {"target": 1}},
                    risk=IntentRisk.DESTRUCTIVE,
                    requires_confirmation=False,
                ),
            ),
        },
        risk=IntentRisk.READ_ONLY,
    )

    await monitor._process_route(
        message,
        utterance=normalize_utterance("hjelp eller slett første"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )
    await monitor.handle_message(
        RecordingMessage("@inebotten jeg mener den andre")
    )

    staged = monitor.pending_actions.peek(routing.key)
    assert staged is not None and staged.status is PendingStatus.READY
    assert staged.routes[0].intent is BotIntent.CALENDAR_DELETE
    handler.assert_not_awaited()

    await monitor.handle_message(RecordingMessage("@inebotten det kan du"))
    handler.assert_awaited_once()
    assert monitor.pending_actions.counts()["completed"] == 1


@pytest.mark.asyncio
async def test_selected_read_cancellation_keeps_selected_route(monitor):
    message = RecordingMessage("@inebotten hjelp eller kalender")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(
                    BotIntent.CALENDAR_LIST,
                    0.9,
                    source=IntentSource.SEMANTIC,
                ),
            ),
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.READ_ONLY,
    )
    await monitor._process_route(
        message,
        utterance=normalize_utterance("hjelp eller kalender"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )

    async def cancelled_list(*args, **kwargs):
        del args, kwargs
        raise DispatchCancelled(
            DispatchOutcome.success().with_delivery(
                MessageSendResult(DeliveryState.DELIVERED)
            )
        )

    monitor.handlers["calendar"].handle_list = cancelled_list

    with pytest.raises(DispatchCancelled):
        await monitor.handle_message(RecordingMessage("@inebotten 2"))

    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_list|source=semantic|outcome=executed": 1
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
async def test_selected_read_failure_never_replays_after_send(
    monitor,
    terminal,
):
    message = RecordingMessage("@inebotten hjelp eller kalender")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Hva mener du?",
            "choices": (
                IntentResult(BotIntent.HELP, 0.9),
                IntentResult(
                    BotIntent.CALENDAR_LIST,
                    0.9,
                    source=IntentSource.SEMANTIC,
                ),
            ),
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.READ_ONLY,
    )
    await monitor._process_route(
        message,
        utterance=normalize_utterance("hjelp eller kalender"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )
    monitor.discord_sender.send_result = AsyncMock(return_value=terminal)

    async def send_then_fail(selected_message, *, reference_time):
        del reference_time
        await monitor._send_response_result(
            selected_message,
            "Kalenderresultat",
        )
        raise ValueError("post_send_failure")

    monitor.handlers["calendar"].handle_list = send_then_fail

    outcome = await monitor.handle_message(RecordingMessage("@inebotten 2"))

    assert not outcome.ok
    assert outcome.error_code == "turn_exception"
    assert outcome.delivery_result == terminal
    monitor.discord_sender.send_result.assert_awaited_once()
    assert monitor.intent_stats[BotIntent.CALENDAR_LIST.value]["errors"] == 1
    assert monitor.intent_stats[BotIntent.ACTION_SELECT.value]["errors"] == 0
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_list|source=semantic|outcome=failed": 1
    }


@pytest.mark.asyncio
async def test_semantic_action_cancelled_while_waiting_for_target_lock(
    monitor,
):
    row = _calendar_row()
    monitor.intent_router.route_utterance = Mock(
        return_value=IntentResult(BotIntent.AI_CHAT, 1.0)
    )
    monitor.hermes = type(
        "Hermes",
        (),
        {
            "generate_response": AsyncMock(
                return_value=(
                    True,
                    action_line(
                        "CALENDAR_DELETE",
                        0.99,
                        {"target": "1"},
                    ),
                )
            )
        },
    )()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (
        dict(row),
    )
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = handler
    message = RecordingMessage("@inebotten slett kalenderoppføring 1")
    lock = monitor.mutation_coordinator._lock_for(CALENDAR_SHARED_SCOPE)

    async with monitor.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
        task = asyncio.create_task(monitor.handle_message(message))
        for _ in range(100):
            if lock._waiters:
                break
            await asyncio.sleep(0)
        assert lock._waiters
        task.cancel()
        with pytest.raises(DispatchCancelled) as cancelled:
            await task

    assert cancelled.value.outcome.error_code == "cancelled"
    assert not cancelled.value.outcome.commit_unknown
    assert cancelled.value.decision_route.intent is BotIntent.CALENDAR_DELETE
    assert cancelled.value.decision_route.source is IntentSource.SEMANTIC
    handler.assert_not_awaited()
    assert monitor.pending_actions.counts()["ready"] == 0
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_delete|source=semantic|outcome=failed": 1
    }


@pytest.mark.asyncio
async def test_confirmed_action_cancelled_while_waiting_for_domain_lock(
    monitor,
):
    row = _calendar_row()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (
        dict(row),
    )
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    monitor.calendar.get_upcoming = (
        lambda guild_id, days=365, reference_time=None: [dict(row)]
    )
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_delete = handler
    preview = RecordingMessage("@inebotten slett kalenderoppføring 1")
    await monitor.handle_message(preview)
    key = conversation_key_from_message(preview)
    lock = monitor.mutation_coordinator._lock_for(CALENDAR_SHARED_SCOPE)

    async with monitor.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
        task = asyncio.create_task(
            monitor.handle_message(RecordingMessage("@inebotten ja"))
        )
        for _ in range(100):
            pending = monitor.pending_actions.peek(key)
            if (
                pending is not None
                and pending.status is PendingStatus.EXECUTING
                and lock._waiters
            ):
                break
            await asyncio.sleep(0)
        assert pending is not None
        assert pending.status is PendingStatus.EXECUTING
        assert lock._waiters
        task.cancel()
        with pytest.raises(DispatchCancelled) as cancelled:
            await task

    assert cancelled.value.outcome.error_code == "cancelled"
    assert cancelled.value.outcome.commit_unknown
    assert cancelled.value.decision_route.intent is BotIntent.CALENDAR_DELETE
    handler.assert_not_awaited()
    assert monitor.pending_actions.counts()["failed"] == 1
    assert monitor.nlu_metrics.snapshot()["decisions"] == {
        "intent=calendar_delete|source=deterministic|outcome=staged": 1,
        "intent=calendar_delete|source=deterministic|outcome=failed": 1,
    }


def _multi_message_confirmation(monitor, message, count=3):
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.99,
        {"reminder": {"action": "add", "text": "Ringe legen"}},
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    flow = monitor.ai_action_handler.prepare_confirmation(message, route)
    assert flow.presentation is not None
    flow = replace(
        flow,
        presentation=replace(
            flow.presentation,
            messages=tuple(f"Bekreftelse {index}" for index in range(count)),
        ),
    )
    return route, flow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "results",
        "expected_code",
        "expected_delivery",
        "restores_previous",
    ),
    [
        (
            (MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),),
            "confirmation_send_failed",
            MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
            True,
        ),
        (
            (MessageSendResult(DeliveryState.UNKNOWN, "timeout"),),
            "confirmation_delivery_unknown",
            MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
            False,
        ),
        (
            (
                MessageSendResult(DeliveryState.DELIVERED),
                MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
            ),
            "partial_confirmation_preview",
            MessageSendResult(DeliveryState.UNKNOWN, "partial_send"),
            False,
        ),
        (
            (
                MessageSendResult(DeliveryState.DELIVERED),
                MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
            ),
            "confirmation_delivery_unknown",
            MessageSendResult(DeliveryState.UNKNOWN, "partial_send"),
            False,
        ),
    ],
)
async def test_presentation_failure_matrix_settles_before_transition(
    monitor,
    results,
    expected_code,
    expected_delivery,
    restores_previous,
):
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    route, flow = _multi_message_confirmation(monitor, message)
    key = conversation_key_from_message(message)
    previous_draft = monitor.pending_actions.begin_confirmation(
        key,
        route,
        "Tidligere bekreftelse",
    )
    previous = monitor.pending_actions.activate_presentation(previous_draft)
    assert previous is not None and previous.status is PendingStatus.READY
    owned_tasks = []
    result_iter = iter(results)

    async def send_result(sent_message, text):
        del sent_message, text
        owned_tasks.append(asyncio.current_task())
        return next(result_iter)

    monitor._send_response_result = send_result
    transition_checks = []
    original_abort = monitor.pending_actions.abort_presentation

    def checked_abort(*args, **kwargs):
        transition_checks.append(
            bool(owned_tasks) and all(task.done() for task in owned_tasks)
        )
        return original_abort(*args, **kwargs)

    monitor.pending_actions.abort_presentation = checked_abort

    outcome = await monitor._send_flow_outcome(
        message,
        flow,
        fallback_route=route,
    )

    assert not outcome.dispatch.ok
    assert outcome.dispatch.error_code == expected_code
    assert outcome.dispatch.delivery_result == expected_delivery
    assert len(owned_tasks) == len(results)
    assert transition_checks == [True]
    settled = monitor.pending_actions.peek(key)
    assert settled is not None
    if restores_previous:
        assert settled.action_id == previous.action_id
        assert settled.status is PendingStatus.READY
    else:
        assert settled.action_id != previous.action_id
        assert settled.status is PendingStatus.FAILED


@pytest.mark.asyncio
async def test_repeated_preview_cancellation_settles_then_activates(monitor):
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    route, flow = _multi_message_confirmation(monitor, message, count=1)
    entered = asyncio.Event()
    release = asyncio.Event()
    owned_tasks = []

    async def blocked_send(sent_message, text):
        del sent_message, text
        owned_tasks.append(asyncio.current_task())
        entered.set()
        await release.wait()
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = blocked_send
    transition_checks = []
    original_activate = monitor.pending_actions.activate_presentation

    def checked_activate(*args, **kwargs):
        transition_checks.append(
            bool(owned_tasks) and all(task.done() for task in owned_tasks)
        )
        return original_activate(*args, **kwargs)

    monitor.pending_actions.activate_presentation = checked_activate
    task = asyncio.create_task(
        monitor._send_flow_outcome(
            message,
            flow,
            fallback_route=route,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    for _ in range(2):
        task.cancel()
        for _ in range(100):
            await asyncio.sleep(0)
            if task.cancelling() == 0:
                break
        assert not task.done()
        assert task.cancelling() == 0
    release.set()

    with pytest.raises(DispatchCancelled) as cancelled:
        await task

    assert cancelled.value.outcome.ok
    assert cancelled.value.outcome.delivery_result == MessageSendResult(
        DeliveryState.DELIVERED
    )
    assert transition_checks == [True]
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None and pending.status is PendingStatus.READY


@pytest.mark.asyncio
@pytest.mark.parametrize("message_count", [1, 3])
async def test_final_delivered_chunk_cancellation_activates_once(
    monitor,
    message_count,
):
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    route, flow = _multi_message_confirmation(
        monitor,
        message,
        count=message_count,
    )
    owned_tasks = []
    sends = 0
    outer = None

    async def cancel_after_final_delivery(sent_message, text):
        nonlocal sends
        del sent_message, text
        owned_tasks.append(asyncio.current_task())
        sends += 1
        if sends == message_count:
            asyncio.get_running_loop().call_soon(outer.cancel)
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = cancel_after_final_delivery
    transition_checks = []
    original_activate = monitor.pending_actions.activate_presentation

    def checked_activate(*args, **kwargs):
        transition_checks.append(
            bool(owned_tasks) and all(task.done() for task in owned_tasks)
        )
        return original_activate(*args, **kwargs)

    monitor.pending_actions.activate_presentation = checked_activate
    outer = asyncio.create_task(
        monitor._send_flow_outcome(
            message,
            flow,
            fallback_route=route,
        )
    )

    with pytest.raises(DispatchCancelled) as cancelled:
        await outer

    assert sends == message_count
    assert cancelled.value.outcome.ok
    assert cancelled.value.outcome.delivery_result == MessageSendResult(
        DeliveryState.DELIVERED
    )
    assert transition_checks == [True]
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None and pending.status is PendingStatus.READY


@pytest.mark.asyncio
async def test_nonfinal_delivered_chunk_cancellation_invalidates_preview(
    monitor,
):
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    route, flow = _multi_message_confirmation(monitor, message, count=3)
    owned_tasks = []
    sends = 0
    outer = None

    async def cancel_after_first_delivery(sent_message, text):
        nonlocal sends
        del sent_message, text
        owned_tasks.append(asyncio.current_task())
        sends += 1
        if sends == 1:
            asyncio.get_running_loop().call_soon(outer.cancel)
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = cancel_after_first_delivery
    transition_checks = []
    original_abort = monitor.pending_actions.abort_presentation

    def checked_abort(*args, **kwargs):
        transition_checks.append(
            bool(owned_tasks) and all(task.done() for task in owned_tasks)
        )
        return original_abort(*args, **kwargs)

    monitor.pending_actions.abort_presentation = checked_abort
    outer = asyncio.create_task(
        monitor._send_flow_outcome(
            message,
            flow,
            fallback_route=route,
        )
    )

    with pytest.raises(DispatchCancelled) as cancelled:
        await outer

    assert sends == 1
    assert not cancelled.value.outcome.ok
    assert cancelled.value.outcome.error_code == "presentation_cancelled"
    assert cancelled.value.outcome.delivery_result == MessageSendResult(
        DeliveryState.UNKNOWN,
        "partial_send",
    )
    assert transition_checks == [True]
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None and pending.status is PendingStatus.FAILED


@pytest.mark.asyncio
async def test_schema_maximum_confirmation_crosses_presentation_losslessly(
    monitor,
):
    message = RecordingMessage("@inebotten lagre et langt sitat")
    route = IntentResult(
        BotIntent.QUOTE,
        0.99,
        {"quote": {"action": "save", "text": "*" * 2_000}},
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    flow = monitor.ai_action_handler.prepare_confirmation(message, route)
    assert flow.presentation is not None
    assert len(flow.presentation.messages) > 1
    sent = []

    async def record_send(sent_message, text):
        del sent_message
        sent.append(text)
        return MessageSendResult(DeliveryState.DELIVERED)

    monitor._send_response_result = record_send

    outcome = await monitor._send_flow_outcome(
        message,
        flow,
        fallback_route=route,
    )

    assert outcome.dispatch.ok
    assert tuple(sent) == flow.presentation.messages
    assert "".join(sent).count("*") == 2_000
    pending = monitor.pending_actions.peek(
        conversation_key_from_message(message)
    )
    assert pending is not None and pending.status is PendingStatus.READY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
@pytest.mark.parametrize(
    "dispatch",
    [
        DispatchOutcome.success(),
        DispatchOutcome.failure("handler_failed"),
        DispatchOutcome.failure("partial_failure", mutated=True),
        DispatchOutcome.failure("commit_state_unknown", commit_unknown=True),
    ],
)
async def test_handler_owned_delivery_never_gets_monitor_fallback(
    monitor,
    terminal,
    dispatch,
):
    route = IntentResult(BotIntent.CALENDAR_LIST, 1.0)
    monitor.handlers["calendar"].handle_list = AsyncMock(
        return_value=dispatch.with_delivery(terminal)
    )
    monitor._send_text_sequence_result = AsyncMock(
        return_value=MessageSendResult(DeliveryState.DELIVERED)
    )
    message = RecordingMessage("@inebotten vis kalenderen")

    outcome = await monitor._process_route(
        message,
        utterance=normalize_utterance("vis kalenderen"),
        routing_context=routing_context_from_message(message, bot_user_id=42),
        route=route,
        reference_time=monitor._reference_time_now(),
    )

    assert outcome.dispatch == dispatch.with_delivery(terminal)
    monitor._send_text_sequence_result.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dispatch",
    [
        DispatchOutcome.success(),
        DispatchOutcome.failure("handler_failed"),
        DispatchOutcome.failure("partial_failure", mutated=True),
        DispatchOutcome.failure("commit_state_unknown", commit_unknown=True),
    ],
)
@pytest.mark.parametrize(
    "terminal",
    [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
async def test_truly_silent_handler_gets_one_bounded_fallback(
    monitor,
    dispatch,
    terminal,
):
    route = IntentResult(BotIntent.CALENDAR_LIST, 1.0)
    monitor.handlers["calendar"].handle_list = AsyncMock(
        return_value=dispatch
    )
    monitor._send_text_sequence_result = AsyncMock(return_value=terminal)
    message = RecordingMessage("@inebotten vis kalenderen")

    outcome = await monitor._process_route(
        message,
        utterance=normalize_utterance("vis kalenderen"),
        routing_context=routing_context_from_message(message, bot_user_id=42),
        route=route,
        reference_time=monitor._reference_time_now(),
    )

    assert outcome.dispatch == dispatch.with_delivery(terminal)
    monitor._send_text_sequence_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_six_cross_conversation_sends_share_rate_admission(monitor):
    limiter = RateLimiter(max_per_second=5, daily_quota=10)
    monitor.rate_limiter = limiter
    monitor.discord_sender = DiscordSendCoordinator(limiter)
    handler = BaseHandler(monitor)
    starts = []
    attempts = []

    class ProbeMessage:
        def __init__(self, channel_id, *, uncertain=False):
            self.channel = type("Channel", (), {"id": channel_id})()
            self.author = type(
                "Author",
                (),
                {"id": channel_id, "name": f"Bruker {channel_id}"},
            )()
            self.uncertain = uncertain

        async def reply(self, content, **kwargs):
            starts.append(asyncio.get_running_loop().time())
            attempts.append((content, kwargs))
            if self.uncertain:
                raise RuntimeError("transport ended after attempt")

    messages = [
        ProbeMessage(101),
        ProbeMessage(102, uncertain=True),
        ProbeMessage(103),
        ProbeMessage(104),
        ProbeMessage(105),
        ProbeMessage(106),
    ]
    tasks = [
        monitor._send_text_sequence_result(messages[0], "x" * 10_000),
        handler.send_response_result(
            messages[1],
            "@everyone <@123> <@&123> <#123> https://example.invalid",
        ),
        *(
            monitor._send_response_result(message, f"Svar {index}")
            for index, message in enumerate(messages[2:], start=3)
        ),
    ]

    preview_result, handler_result, *single_results = await asyncio.gather(
        *tasks
    )

    assert preview_result == MessageSendResult(DeliveryState.DELIVERED)
    assert handler_result == MessageSendResult(
        DeliveryState.UNKNOWN,
        "transport",
    )
    assert single_results == [
        MessageSendResult(DeliveryState.DELIVERED)
    ] * 4
    assert len(starts) == 10
    assert all(
        sum(start <= candidate < start + 1.0 for candidate in starts) <= 5
        for start in starts
    )
    assert limiter.daily_count == 10
    assert limiter.total_sent == 10
    assert limiter.total_dropped == 0
    for _, kwargs in attempts:
        allowed = kwargs["allowed_mentions"]
        assert allowed.everyone is False
        assert allowed.roles is False
        assert allowed.users is False
        assert allowed.replied_user is False
        assert kwargs["suppress_embeds"] is True
        assert kwargs["mention_author"] is False

    rejected = ProbeMessage(107)
    rejected_result = await monitor._send_response_result(
        rejected,
        "Skal avvises før forsøk",
    )
    assert rejected_result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "daily_quota",
    )
    assert len(attempts) == 10
    assert limiter.daily_count == 10
    assert limiter.total_dropped == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("direct_dm", [False, True], ids=["guild", "dm"])
@pytest.mark.parametrize(
    "output_path",
    ["model", "handler", "confirmation", "nested_reply"],
)
async def test_hostile_output_paths_disable_mentions_and_embeds(
    monitor,
    monkeypatch,
    direct_dm,
    output_path,
):
    hostile = (
        "@everyone <@123> <@&123> <#123> "
        "https://example.invalid <https://example.invalid/path>"
    )

    class FakeDMChannel:
        def __init__(self):
            self.id = 701
            self.send = AsyncMock()

    class FakeGroupChannel:
        pass

    monkeypatch.setattr(discord, "DMChannel", FakeDMChannel)
    monkeypatch.setattr(discord, "GroupChannel", FakeGroupChannel)
    message = RecordingMessage("@inebotten håndter dette trygt")
    message.reply = AsyncMock()
    if direct_dm:
        message.guild = None
        message.channel = FakeDMChannel()
        adapter = message.channel.send
    else:
        message.guild = type("Guild", (), {"id": 700})()
        message.channel = type("Channel", (), {"id": 701})()
        adapter = message.reply

    if output_path == "model":
        monitor.intent_router.route_utterance = Mock(
            return_value=IntentResult(BotIntent.AI_CHAT, 1.0)
        )
        monitor.hermes = type(
            "Hermes",
            (),
            {"generate_response": AsyncMock(return_value=(True, hostile))},
        )()
    elif output_path == "handler":
        monitor.intent_router.route_utterance = Mock(
            return_value=IntentResult(BotIntent.CALENDAR_LIST, 1.0)
        )

        async def handler_copy(selected_message, *, reference_time):
            del reference_time
            delivery = await monitor._send_response_result(
                selected_message,
                hostile,
            )
            return DispatchOutcome.success().with_delivery(delivery)

        monitor.handlers["calendar"].handle_list = handler_copy
    elif output_path == "confirmation":
        monitor.intent_router.route_utterance = Mock(
            return_value=IntentResult(
                BotIntent.REMINDER_CREATE,
                0.99,
                {"reminder": {"action": "add", "text": hostile}},
                risk=IntentRisk.ADDITIVE,
                requires_confirmation=True,
            )
        )
    else:
        nested = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
        monitor.intent_router.route_utterance = Mock(
            return_value=IntentResult(BotIntent.AI_CHAT, 1.0)
        )
        monitor.hermes = type(
            "Hermes",
            (),
            {
                "generate_response": AsyncMock(
                    return_value=(
                        True,
                        action_line(
                            "REMINDER_CREATE",
                            0.99,
                            {"text": "Ringe legen"},
                            reply=f"{hostile}\n{nested}",
                        ),
                    )
                )
            },
        )()

    await monitor.handle_message(message)

    assert adapter.await_count >= 1
    for call in adapter.await_args_list:
        kwargs = call.kwargs
        allowed = kwargs["allowed_mentions"]
        assert allowed.everyone is False
        assert allowed.roles is False
        assert allowed.users is False
        assert allowed.replied_user is False
        assert kwargs["suppress_embeds"] is True
        if not direct_dm:
            assert kwargs["mention_author"] is False


@pytest.mark.asyncio
async def test_guarded_calendar_correction_rebinds_then_confirms(monitor):
    row = _calendar_row()
    monitor.calendar.snapshot_pending_items = lambda *, reference_time: (
        dict(row),
    )
    monitor.calendar.snapshot_all_item_ids = lambda: ("calendar-1",)
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["calendar"].handle_edit = handler
    message = RecordingMessage("@inebotten endre første avtale")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.CALENDAR_EDIT,
        0.99,
        {
            "calendar_edit": {
                "target": 1,
                "changes": {"title": "Foreløpig"},
            }
        },
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )

    await monitor._process_route(
        message,
        utterance=normalize_utterance("endre første avtale"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )
    original = monitor.pending_actions.peek(routing.key)
    assert original is not None
    old_hash = original.target_guards[0].proposition_hash

    await monitor.handle_message(
        RecordingMessage("@inebotten tittel: Endelig navn")
    )
    corrected = monitor.pending_actions.peek(routing.key)
    assert corrected is not None and corrected.status is PendingStatus.READY
    assert corrected.action_id != original.action_id
    assert corrected.target_guards[0].proposition_hash != old_hash
    assert corrected.routes[0].payload["calendar_edit"]["changes"] == {
        "title": "Endelig navn"
    }

    await monitor.handle_message(RecordingMessage("@inebotten ja"))
    handler.assert_awaited_once()
    dispatched = handler.await_args.args[1]
    assert dispatched["target"] == "calendar-1"
    assert dispatched["changes"] == {"title": "Endelig navn"}


@pytest.mark.asyncio
async def test_reminder_partial_correction_repreviews_then_executes_once(
    monitor,
):
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["reminders"].handle_reminder_create = handler
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.99,
        {
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_date": "20.07.2026",
                "time": "10:00",
                "timezone": "Europe/Oslo",
            }
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )

    await monitor._process_route(
        message,
        utterance=normalize_utterance("minn meg på å ringe legen"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )
    original = monitor.pending_actions.peek(routing.key)
    assert original is not None and original.status is PendingStatus.READY

    correction = RecordingMessage("@inebotten kl 15")
    await monitor.handle_message(correction)

    handler.assert_not_awaited()
    corrected = monitor.pending_actions.peek(routing.key)
    assert corrected is not None and corrected.status is PendingStatus.READY
    assert corrected.action_id != original.action_id
    assert corrected.routes[0].payload["reminder"] == {
        "action": "add",
        "text": "Ringe legen",
        "due_at": "2026-07-20T15:00:00+02:00",
        "due_date": "20.07.2026",
        "time": "15:00",
        "timezone": "Europe/Oslo",
    }
    assert "Bekreftelsesdetaljer" in correction.replies[0]

    await monitor.handle_message(RecordingMessage("@inebotten ja takk"))
    await monitor.handle_message(RecordingMessage("@inebotten ja takk"))

    handler.assert_awaited_once()
    dispatched = handler.await_args.args[1]
    assert dispatched == corrected.routes[0].payload["reminder"]
    assert monitor.pending_actions.counts()["completed"] == 1


@pytest.mark.asyncio
async def test_cancel_wrapper_disarms_pending_action_without_dispatch(monitor):
    handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
    monitor.handlers["reminders"].handle_reminder_create = handler
    message = RecordingMessage("@inebotten minn meg på å ringe legen")
    routing = routing_context_from_message(message, bot_user_id=42)
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.99,
        {
            "reminder": {
                "action": "add",
                "text": "Ringe legen",
                "due_date": "20.07.2026",
            }
        },
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    await monitor._process_route(
        message,
        utterance=normalize_utterance("minn meg på å ringe legen"),
        routing_context=routing,
        route=route,
        reference_time=monitor._reference_time_now(),
    )
    assert monitor.pending_actions.peek(routing.key) is not None

    cancellation = RecordingMessage("@inebotten nei, avbryt")
    await monitor.handle_message(cancellation)

    handler.assert_not_awaited()
    assert monitor.pending_actions.peek(routing.key) is None
    assert cancellation.replies == ["Avbrutt."]


@pytest.mark.asyncio
async def test_authorized_turn_normalizes_once_and_keeps_later_bot_mention(
    monitor,
    monkeypatch,
):
    import core.message_monitor as monitor_module

    calls = []
    original = monitor_module.normalize_utterance

    def recording_normalize(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(monitor_module, "normalize_utterance", recording_normalize)
    message = RecordingMessage("<@42> hjelp\nbehold <@42> senere")

    await monitor.handle_message(message)

    assert calls == ["hjelp\nbehold <@42> senere"]

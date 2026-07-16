"""Offline integration proof for scoped, policy-safe conversation history."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import tests.test_message_monitor_routing as routing_tests

from ai.chat_contract import ChatTurn, REDACTED_AUTH_TURN
from core.dispatch_result import (
    DeliveryState,
    DispatchOutcome,
    MessageSendResult,
)
from core.intent_models import BotIntent, IntentResult, IntentRisk, IntentSource
from core.message_context import conversation_key_from_message
from features.base_handler import BaseHandler
from features.memory_handler import MemoryHandler
from memory.conversation_context import ConversationContext
from tests.nlu_test_support import FIXED_NOW
from tests.test_message_monitor_routing import RecordingMessage


@pytest.fixture
def monitor():
    instance = routing_tests.MessageMonitorRoutingTests().make_monitor()
    instance.conversation = ConversationContext(
        max_history=20,
        now_provider=instance._reference_time_now,
    )
    return instance


def _ai_route() -> IntentResult:
    return IntentResult(
        BotIntent.AI_CHAT,
        1.0,
        source=IntentSource.DETERMINISTIC,
        risk=IntentRisk.READ_ONLY,
    )


def _provider(response="svar"):
    generate = AsyncMock(return_value=(True, response))
    return type("Hermes", (), {"generate_response": generate})(), generate


def _calendar_list_action() -> str:
    return json.dumps(
        {
            "action": "CALENDAR_LIST",
            "confidence": 0.99,
            "slots": {},
            "reply": "Her er kalenderen.",
            "clarification": None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _clarify_action(question: str = "Hvilken dag?") -> str:
    return json.dumps(
        {
            "action": "CLARIFY",
            "confidence": 0.99,
            "slots": {},
            "reply": "",
            "clarification": question,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _install_private_calendar_list(monitor, private_copy: str) -> None:
    async def handle_list(message, *, reference_time):
        del reference_time
        delivery = await monitor._send_response_result(
            message,
            private_copy,
        )
        return DispatchOutcome.success().with_delivery(delivery)

    monitor.handlers["calendar"].handle_list = handle_list


@pytest.mark.asyncio
async def test_current_message_appears_once_in_provider_arguments(monitor):
    message = RecordingMessage("@inebotten UNIK-AKTUELL-MELDING")
    message.id = 99
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider()

    await monitor.handle_message(message)

    call = generate.await_args.kwargs
    serialized = (
        "\n".join(turn.content for turn in call["history"])
        + "\n"
        + call["message_content"]
    )
    assert serialized.count("UNIK-AKTUELL-MELDING") == 1
    key = conversation_key_from_message(message)
    assert [
        (turn.role, turn.content)
        for turn in monitor.conversation.get_prompt_history(key)
    ] == [
        ("user", "UNIK-AKTUELL-MELDING"),
        ("assistant", "svar"),
    ]


@pytest.mark.asyncio
async def test_prior_assistant_and_user_turns_reach_provider_in_order(monitor):
    message = RecordingMessage("@inebotten ny melding")
    key = conversation_key_from_message(message)
    monitor.conversation.add_turn(key, ChatTurn("user", "forrige spørsmål", 1))
    monitor.conversation.add_turn(key, ChatTurn("assistant", "forrige svar"))
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider()

    await monitor.handle_message(message)

    assert [
        (turn.role, turn.content)
        for turn in generate.await_args.kwargs["history"]
    ] == [
        ("user", "forrige spørsmål"),
        ("assistant", "forrige svar"),
    ]


@pytest.mark.asyncio
async def test_model_calendar_read_reclassifies_entire_turn_before_followup(
    monitor,
):
    # Keep the canary itself bridge-valid: this test isolates history-policy
    # reclassification, while ActionBridge independently requires that a
    # CALENDAR_LIST proposal is supported by the current utterance.
    inbound_canary = "SHOW MY CALENDAR?!?!!"
    output_canary = "PRIVATE-CALENDAR-ROW-CANARY"
    monitor.conversation = ConversationContext(
        max_history=3,
        now_provider=monitor._reference_time_now,
    )
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider(_calendar_list_action())
    _install_private_calendar_list(monitor, output_canary)
    first = RecordingMessage(f"@inebotten {inbound_canary}")
    key = conversation_key_from_message(first)
    prior = (
        ChatTurn("user", "eldste historikk", 900_001),
        ChatTurn("assistant", "midterste historikk"),
        ChatTurn("user", "nyeste historikk", 900_002),
    )
    for turn in prior:
        monitor.conversation.add_turn(key, turn)

    await monitor.handle_message(first)

    assert output_canary in first.replies[0]
    assert monitor.conversation.get_prompt_history(key) == prior

    generate.reset_mock()
    generate.return_value = (True, "Vanlig oppfølging.")
    followup = RecordingMessage("@inebotten hvordan går det?")
    await monitor.handle_message(followup)

    history = generate.await_args.kwargs["history"]
    assert history == prior
    serialized = "\n".join(turn.content for turn in history)
    assert inbound_canary not in serialized
    assert output_canary not in serialized


@pytest.mark.asyncio
async def test_semantic_clarification_keeps_bounded_context_for_slot_reply(
    monitor,
):
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider(_clarify_action())
    first = RecordingMessage("@inebotten planlegg noe med Ola")

    await monitor.handle_message(first)

    assert first.replies == ["Hvilken dag?"]
    generate.reset_mock()
    generate.return_value = (True, "Da tar vi det i morgen.")
    second = RecordingMessage("@inebotten i morgen")
    await monitor.handle_message(second)

    history = generate.await_args.kwargs["history"]
    assert [(turn.role, turn.content) for turn in history] == [
        ("user", "planlegg noe med Ola"),
        ("assistant", "Hvilken dag?"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_mode",
    [
        "missing",
        "stage_rejecting",
        "stage_raising",
        "reclass_rejecting",
        "reclass_raising",
    ],
)
async def test_semantic_history_transition_fails_closed_for_adapters(
    monitor,
    adapter_mode,
):
    # The semantic action bridge is intentionally evidence-bound.  Use a
    # distinctive exact calendar-read phrase so this adapter test reaches the
    # history transition it is meant to exercise.
    inbound_canary = "SHOW MY CALENDAR?!?!!"
    output_canary = f"ADAPTER-{adapter_mode}-OUTPUT-CANARY"
    turns = []
    history_reads = []

    def add_turn(key, turn):
        turns.append((key, turn))

    def get_prompt_history(
        key,
        *,
        limit=10,
        exclude_source_message_id=None,
    ):
        history_reads.append(key)
        return tuple(
            turn
            for turn_key, turn in turns[-limit:]
            if turn_key == key
            and (
                exclude_source_message_id is None
                or turn.source_message_id != exclude_source_message_id
            )
        )

    adapter = SimpleNamespace(
        add_turn=add_turn,
        get_prompt_history=get_prompt_history,
    )

    def successful_stage(key, turn):
        add_turn(key, turn)
        return True

    def partial_stage_rejection(key, turn):
        add_turn(key, turn)
        return False

    def partial_stage_failure(key, turn):
        add_turn(key, turn)
        raise RuntimeError("adapter staging failed")

    def accept_reclassification(key, source_message_id, policy):
        del key, source_message_id, policy
        return True

    if adapter_mode == "stage_rejecting":
        adapter.stage_source_turn = partial_stage_rejection
        adapter.reclassify_source_turn = accept_reclassification
    elif adapter_mode == "stage_raising":
        adapter.stage_source_turn = partial_stage_failure
        adapter.reclassify_source_turn = accept_reclassification
    elif adapter_mode == "reclass_rejecting":
        adapter.stage_source_turn = successful_stage

        def reject_reclassification(key, source_message_id, policy):
            del key, source_message_id, policy
            return False

        adapter.reclassify_source_turn = reject_reclassification
    elif adapter_mode == "reclass_raising":
        adapter.stage_source_turn = successful_stage

        def fail_reclassification(key, source_message_id, policy):
            del key, source_message_id, policy
            raise RuntimeError("adapter rollback failed")

        adapter.reclassify_source_turn = fail_reclassification
    monitor.conversation = adapter
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider(_calendar_list_action())
    _install_private_calendar_list(monitor, output_canary)
    first = RecordingMessage(f"@inebotten {inbound_canary}")

    await monitor.handle_message(first)

    assert output_canary in first.replies[0]
    if adapter_mode == "missing":
        assert turns == []
    else:
        assert [turn.content for _, turn in turns] == [inbound_canary]
    assert monitor._provider_history_quarantined

    generate.reset_mock()
    generate.return_value = (True, "Vanlig oppfølging.")
    await monitor.handle_message(
        RecordingMessage("@inebotten hvordan går det?")
    )

    history = generate.await_args.kwargs["history"]
    assert history == ()
    serialized = "\n".join(turn.content for turn in history)
    assert inbound_canary not in serialized
    assert output_canary not in serialized
    assert len(history_reads) == (
        0 if adapter_mode.startswith("stage_") else 1
    )


@pytest.mark.asyncio
async def test_untagged_and_rate_rejected_messages_are_not_recorded(monitor):
    untagged = RecordingMessage("hemmelig")
    key = conversation_key_from_message(untagged)

    await monitor.handle_message(untagged)
    assert monitor.conversation.get_prompt_history(key) == ()

    monitor.rate_limiter.can_send = lambda: (False, "daily_quota_exceeded")
    rejected = RecordingMessage("@inebotten fortsatt hemmelig")
    await monitor.handle_message(rejected)
    assert monitor.conversation.get_prompt_history(key) == ()


@pytest.mark.asyncio
async def test_non_delivery_records_inbound_but_not_assistant(monitor):
    message = RecordingMessage("@inebotten svar meg")
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, _ = _provider("utgående svar")
    monitor.discord_sender.send_result = AsyncMock(
        return_value=MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "forbidden",
        )
    )

    outcome = await monitor.handle_message(message)

    assert not outcome.response_sent
    assert [
        (turn.role, turn.content)
        for turn in monitor.conversation.get_prompt_history(
            conversation_key_from_message(message)
        )
    ] == [("user", "svar meg")]


@pytest.mark.asyncio
async def test_memory_and_search_data_use_only_bounded_allowlisted_context(monitor):
    memory_canary = "MEMORY-INTEREST-CANARY"
    search_canary = "SEARCH-CANARY"
    stable_user_id = 987_654_321
    forbidden_canaries = (
        "LEGACY-NOTE-CANARY",
        "API-KEY-CANARY",
        "TOKEN-CANARY",
        "PRIVATE-NOTE-CANARY",
        "BIRTHDAY-CANARY",
    )
    route = IntentResult(
        BotIntent.SEARCH,
        1.0,
        {"search": {"query": "kanari", "type": "web"}},
    )
    monitor.intent_router.route_utterance = Mock(return_value=route)
    monitor.user_memory.snapshot_user = Mock(
        return_value={
            "interests": [memory_canary],
            "location": "Trondheim",
            "last_topics": ["ski"],
            "preferences": {
                "humor_style": "friendly",
                "use_dialect": True,
                "api_key": forbidden_canaries[1],
            },
            "note": forbidden_canaries[0],
            "token": forbidden_canaries[2],
            "private_note": forbidden_canaries[3],
            "birthday": forbidden_canaries[4],
        }
    )
    monitor.search_manager = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "title": search_canary,
                    "href": "https://example.invalid",
                    "body": "trygt søkeresultat",
                }
            ]
        ),
        get_news=AsyncMock(),
        format_results_for_ai=Mock(
            side_effect=AssertionError("legacy trusted interpolation")
        ),
    )
    monitor.hermes, generate = _provider()
    message = RecordingMessage("@inebotten søk etter kanari")
    message.author.id = stable_user_id

    await monitor.handle_message(message)

    call = generate.await_args.kwargs
    context = json.loads(call["context_prompt"])
    serialized_context = json.dumps(context, ensure_ascii=False)
    assert memory_canary in serialized_context
    assert search_canary in serialized_context
    assert str(stable_user_id) not in serialized_context
    assert all(canary not in serialized_context for canary in forbidden_canaries)
    assert set(context["author"]) == {"display_name"}
    assert context["user_memory"] == {
        "interests": [memory_canary],
        "last_topics": ["ski"],
        "location": "Trondheim",
        "preferences": {
            "humor_style": "friendly",
            "use_dialect": True,
        },
    }
    assert len(call["context_prompt"]) <= 4_000
    assert memory_canary not in call["system_prompt"]
    assert search_canary not in call["system_prompt"]


@pytest.mark.asyncio
async def test_memory_export_never_reenters_future_provider_history(monitor):
    private_export = "PRIVATE-MEMORY-EXPORT-CANARY"
    export_route = IntentResult(
        BotIntent.MEMORY_EXPORT,
        1.0,
        {"memory": {"action": "export"}},
    )
    monitor.handlers["memory"] = MemoryHandler(monitor)
    monitor.user_memory.export_user_memory = AsyncMock(
        return_value={"private_note": private_export}
    )
    monitor.intent_router.route_utterance = Mock(return_value=export_route)
    first = RecordingMessage("@inebotten eksporter minnet mitt")

    await monitor.handle_message(first)

    assert private_export in first.replies[0]
    assert monitor.conversation.get_prompt_history(
        conversation_key_from_message(first)
    ) == ()

    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider()
    followup = RecordingMessage("@inebotten hvordan går det?")

    await monitor.handle_message(followup)

    serialized_history = "\n".join(
        turn.content for turn in generate.await_args.kwargs["history"]
    )
    assert private_export not in serialized_history
    assert generate.await_args.kwargs["history"] == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("send_owner", ["monitor", "base_handler"])
async def test_calendar_auth_code_and_oauth_reply_never_reach_history_or_logs(
    monitor,
    capsys,
    send_owner,
):
    secret_code = "AbC_12_SECRET"
    oauth_url = (
        "https://accounts.google.com/o/oauth2/auth?state=SECRETSTATE"
    )
    base = BaseHandler(monitor)

    async def auth_reply(message, payload, *, reference_time):
        del payload, reference_time
        if send_owner == "monitor":
            delivery = await monitor._send_response_result(message, oauth_url)
        else:
            delivery = await base.send_response_result(message, oauth_url)
        return DispatchOutcome.success(mutated=True).with_delivery(delivery)

    monitor.handlers["calendar"].handle_auth = auth_reply
    original_route = monitor.intent_router.route_utterance

    def route(utterance, *args, **kwargs):
        if utterance.text == "hvordan går det?":
            return _ai_route()
        return original_route(utterance, *args, **kwargs)

    monitor.intent_router.route_utterance = route
    first = RecordingMessage(f"@inebotten kalender auth {secret_code}")
    await monitor.handle_message(first)
    await monitor.handle_message(RecordingMessage("@inebotten ja"))
    monitor.hermes, generate = _provider()
    followup = RecordingMessage("@inebotten hvordan går det?")

    await monitor.handle_message(followup)

    history = generate.await_args.kwargs["history"]
    serialized = "\n".join(turn.content for turn in history)
    assert secret_code not in serialized
    assert oauth_url not in serialized
    assert "SECRETSTATE" not in serialized
    assert serialized.count(REDACTED_AUTH_TURN) >= 2
    captured = capsys.readouterr().out
    assert secret_code not in captured
    assert oauth_url not in captured
    assert "SECRETSTATE" not in captured


@pytest.mark.asyncio
async def test_sensitive_choice_redacts_menu_and_safe_selection(monitor):
    auth = IntentResult(
        BotIntent.CALENDAR_AUTH,
        1.0,
        {"auth_code": "CHOICE_SECRET"},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    clarify = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "clarification": "Velg",
            "choices": (
                IntentResult(BotIntent.HELP, 1.0),
                auth,
            ),
        },
        source=IntentSource.SEMANTIC,
    )
    original_route = monitor.intent_router.route_utterance
    calls = 0

    def route(utterance, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return clarify
        return original_route(utterance, *args, **kwargs)

    monitor.intent_router.route_utterance = route
    monitor.handlers["help"].handle_help = AsyncMock(
        return_value=DispatchOutcome.success()
    )
    first = RecordingMessage("@inebotten hjelp eller kalenderkode")
    await monitor.handle_message(first)
    await monitor.handle_message(RecordingMessage("@inebotten 1"))

    history = monitor.conversation.get_prompt_history(
        conversation_key_from_message(first)
    )
    serialized = "\n".join(turn.content for turn in history)
    assert "CHOICE_SECRET" not in serialized
    assert serialized.count(REDACTED_AUTH_TURN) >= 2


@pytest.mark.asyncio
async def test_expired_sensitive_pending_followup_redacts_fail_closed(monitor):
    secret = "EXPIRED_SECRET"
    route = IntentResult(
        BotIntent.CALENDAR_AUTH,
        1.0,
        {"auth_code": secret},
        risk=IntentRisk.MUTATING,
        requires_confirmation=True,
    )
    original_route = monitor.intent_router.route_utterance
    monitor.intent_router.route_utterance = Mock(return_value=route)
    first = RecordingMessage("@inebotten kalenderkode")
    await monitor.handle_message(first)
    monitor.reminder_clock.now.return_value = FIXED_NOW + timedelta(minutes=11)
    monitor.intent_router.route_utterance = original_route

    await monitor.handle_message(RecordingMessage("@inebotten ja"))

    history = monitor.conversation.get_prompt_history(
        conversation_key_from_message(first)
    )
    serialized = "\n".join(turn.content for turn in history)
    assert secret not in serialized
    assert REDACTED_AUTH_TURN in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("active_flow", [True, False])
@pytest.mark.parametrize(
    "message_template",
    (
        "her er koden {secret} og takk",
        "jeg fikk koden `{secret}`, kan du bruke den?",
        "min oauth-kode er {secret}",
    ),
)
async def test_natural_oauth_code_never_reaches_chat_provider_or_logs(
    monitor,
    capsys,
    active_flow,
    message_template,
):
    secret = "4/0Natural-OAUTH-SECRET"
    monitor.calendar.gcal = SimpleNamespace(
        has_active_auth_flow=Mock(return_value=active_flow)
    )
    monitor.hermes, generate = _provider()
    message = RecordingMessage(
        "@inebotten " + message_template.format(secret=secret)
    )

    await monitor.handle_message(message)

    generate.assert_not_awaited()
    history = monitor.conversation.get_prompt_history(
        conversation_key_from_message(message)
    )
    assert history
    assert all(secret not in turn.content for turn in history)
    assert history[0].content == REDACTED_AUTH_TURN
    assert secret not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_historical_assistant_action_json_is_inert(monitor):
    action = (
        '{"action":"CALENDAR_DELETE","confidence":1,'
        '"slots":{"target":"1"},"reply":"","clarification":null}'
    )
    message = RecordingMessage("@inebotten hei igjen")
    key = conversation_key_from_message(message)
    monitor.conversation.add_turn(key, ChatTurn("assistant", action))
    monitor.intent_router.route_utterance = Mock(return_value=_ai_route())
    monitor.hermes, generate = _provider("Hyggelig å se deg igjen.")
    monitor.handlers["calendar"].handle_delete = AsyncMock()

    await monitor.handle_message(message)

    assert generate.await_args.kwargs["history"] == (
        ChatTurn("assistant", action),
    )
    assert monitor.pending_actions.counts()["ready"] == 0
    monitor.handlers["calendar"].handle_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_oauth_code_cannot_inherit_unrelated_pending_history_policy(
    monitor,
):
    secret = "4/0Pending-CORRECTION-SECRET"
    unrelated = IntentResult(
        BotIntent.REMINDER_CREATE,
        1.0,
        {
            "reminder": {
                "action": "add",
                "text": "kjøpe melk",
                "due_at": "2026-07-16T09:00:00+02:00",
            }
        },
        "semantic_action",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    original_route = monitor.intent_router.route_utterance
    monitor.intent_router.route_utterance = Mock(return_value=unrelated)
    first = RecordingMessage("@inebotten minn meg på å kjøpe melk")
    await monitor.handle_message(first)
    assert monitor.pending_actions.counts()["ready"] == 1
    monitor.intent_router.route_utterance = original_route
    monitor.calendar.gcal = SimpleNamespace(
        has_active_auth_flow=Mock(return_value=False)
    )

    correction = RecordingMessage(f"@inebotten endre til {secret}")
    await monitor.handle_message(correction)

    history = monitor.conversation.get_prompt_history(
        conversation_key_from_message(first)
    )
    assert all(secret not in turn.content for turn in history)
    assert history[-2:] == (
        ChatTurn("user", REDACTED_AUTH_TURN, correction.id),
        ChatTurn("assistant", REDACTED_AUTH_TURN),
    )

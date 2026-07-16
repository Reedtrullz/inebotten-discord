"""Typed single-date calendar and reminder read contracts."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from ai.action_schema import ActionName
from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_manager import ReminderManager
from core.action_bridge import ActionBridge
from core.dispatch_result import (
    DeliveryState,
    DispatchOutcome,
    MessageSendResult,
)
from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent, IntentResult, IntentSource
from core.intent_payloads import PayloadValidationError, validate_intent_payload
from core.utterance import normalize_utterance
from features.calendar_handler import CalendarHandler
from tests.nlu_harness import build_production_router
from tests.nlu_test_support import bridge_context, proposal_for
from tests.test_message_monitor_routing import (
    MessageMonitorRoutingTests,
    NOW,
    RecordingMessage,
)
from tests.test_reminder_typed_handler import TypedMessage, make_handler


REFERENCE = datetime(2026, 7, 14, 12, tzinfo=ZoneInfo("Europe/Oslo"))

UNSUPPORTED_P2_LIST_READS = (
    ("What do I have planned next week?", ActionName.CALENDAR_LIST),
    ("Do I have anything planned next week?", ActionName.CALENDAR_LIST),
    ("Hva har jeg planlagt neste uke?", ActionName.CALENDAR_LIST),
    ("Kva har eg planlagt neste veke?", ActionName.CALENDAR_LIST),
    ("What are my plans next week?", ActionName.CALENDAR_LIST),
    ("What have I got planned next week?", ActionName.CALENDAR_LIST),
    ("Har jeg planer neste uke?", ActionName.CALENDAR_LIST),
    ("Kva er planane mine neste veke?", ActionName.CALENDAR_LIST),
    ("What do I have tomorrow with Kari?", ActionName.CALENDAR_LIST),
    ("What do I have tomorrow for work?", ActionName.CALENDAR_LIST),
    (
        "What do I have tomorrow and next week?",
        ActionName.CALENDAR_LIST,
    ),
    ("What do I have Friday with Kari?", ActionName.CALENDAR_LIST),
    (
        "Do I need to remember anything next week?",
        ActionName.REMINDER_LIST,
    ),
    (
        "Is there anything I should remember next week?",
        ActionName.REMINDER_LIST,
    ),
    ("Er det noe jeg må huske neste uke?", ActionName.REMINDER_LIST),
    ("Er det noko eg må hugse neste veke?", ActionName.REMINDER_LIST),
    (
        "Check my calendar tomorrow and next week",
        ActionName.CALENDAR_LIST,
    ),
    (
        "Do I have anything on my calendar tomorrow and next week?",
        ActionName.CALENDAR_LIST,
    ),
    (
        "Check only work events on my calendar tomorrow",
        ActionName.CALENDAR_LIST,
    ),
    ("Check calendar tasks tomorrow", ActionName.CALENDAR_LIST),
    (
        "Sjekk bare jobbarrangementer i kalenderen i morgen",
        ActionName.CALENDAR_LIST,
    ),
    ("Sjekk kalenderoppgaver i morgen", ActionName.CALENDAR_LIST),
    (
        "Er det noe i kalenderen min om jobb i morgen?",
        ActionName.CALENDAR_LIST,
    ),
    (
        "Sjekk berre jobbarrangement i kalenderen i morgon",
        ActionName.CALENDAR_LIST,
    ),
    (
        "Er det noko i kalenderen min om jobb i morgon?",
        ActionName.CALENDAR_LIST,
    ),
    (
        "Check my reminders tomorrow and next week",
        ActionName.REMINDER_LIST,
    ),
    ("Check reminders about mom tomorrow", ActionName.REMINDER_LIST),
    ("Check completed reminders", ActionName.REMINDER_LIST),
    (
        "Are there any completed reminders tomorrow?",
        ActionName.REMINDER_LIST,
    ),
    (
        "Sjekk påminnelser om mamma i morgen",
        ActionName.REMINDER_LIST,
    ),
    ("Sjekk fullførte påminnelser", ActionName.REMINDER_LIST),
    (
        "Er det noen fullførte påminnelser i morgen?",
        ActionName.REMINDER_LIST,
    ),
    (
        "Sjekk påminningar om mamma i morgon",
        ActionName.REMINDER_LIST,
    ),
    (
        "Er det nokon fullførte påminningar i morgon?",
        ActionName.REMINDER_LIST,
    ),
)


@pytest.mark.parametrize(
    ("text", "intent", "payload"),
    (
        (
            "What's on my calendar today?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "14.07.2026"}},
        ),
        (
            "Har jeg noe planlagt i morgen?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "15.07.2026"}},
        ),
        (
            "Kva står på planen komande laurdag?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "18.07.2026"}},
        ),
        (
            "Show me my calendar 20.07.2026",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "20.07.2026"}},
        ),
        (
            "What's coming up on my calendar day after tomorrow?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "16.07.2026"}},
        ),
        (
            "What's my schedule tomorrow?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "15.07.2026"}},
        ),
        (
            "Kan eg sjå kalenderen min i morgon?",
            BotIntent.CALENDAR_LIST,
            {"calendar_list": {"date": "15.07.2026"}},
        ),
        (
            "Any reminders for tomorrow?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "15.07.2026"}},
        ),
        (
            "Har jeg påminnelser fredag?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "17.07.2026"}},
        ),
        (
            "Kva må eg hugse i morgon?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "15.07.2026"}},
        ),
        (
            "Show reminders for 20/07/2026",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "20.07.2026"}},
        ),
        (
            "Do I have any reminders tomorrow?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "15.07.2026"}},
        ),
        (
            "Could I see my reminders day after tomorrow?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "16.07.2026"}},
        ),
        (
            "Kan jeg se påminnelsene mine i morgen?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list", "due_date": "15.07.2026"}},
        ),
    ),
)
def test_exact_en_nb_nn_single_date_reads_use_the_frozen_reference(
    text, intent, payload
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)
    action = (
        ActionName.CALENDAR_LIST
        if intent is BotIntent.CALENDAR_LIST
        else ActionName.REMINDER_LIST
    )
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result.intent is intent
    assert result.payload == payload
    assert semantic is not None
    assert semantic.intent is intent
    assert semantic.payload == payload


@pytest.mark.parametrize(
    ("text", "action"),
    (
        ("show my calendar for the week", ActionName.CALENDAR_LIST),
        ("what is on my calendar all week", ActionName.CALENDAR_LIST),
        ("show my calendar for the rest of this week", ActionName.CALENDAR_LIST),
        ("show my calendar over the next few days", ActionName.CALENDAR_LIST),
        ("show my calendar in July", ActionName.CALENDAR_LIST),
        ("show my calendar this quarter", ActionName.CALENDAR_LIST),
        ("show reminders next week", ActionName.REMINDER_LIST),
        ("vis påminningane mine neste veke", ActionName.REMINDER_LIST),
        ("show reminders in the next 3 days", ActionName.REMINDER_LIST),
        ("What's on my calendar tomorrow and next week?", ActionName.CALENDAR_LIST),
        ("Show my calendar tomorrow through next week", ActionName.CALENDAR_LIST),
        ("What reminders do I have tomorrow and next week?", ActionName.REMINDER_LIST),
        ("Show only work events on my calendar tomorrow", ActionName.CALENDAR_LIST),
        ("Show calendar tasks tomorrow", ActionName.CALENDAR_LIST),
        ("Show reminders about mom tomorrow", ActionName.REMINDER_LIST),
        ("Which completed reminders do I have tomorrow?", ActionName.REMINDER_LIST),
        ("Show only work events on my calendar", ActionName.CALENDAR_LIST),
        ("Show completed reminders", ActionName.REMINDER_LIST),
    ),
)
def test_unrepresentable_ranges_never_become_unfiltered_semantic_lists(
    text, action
):
    result = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is None


@pytest.mark.parametrize(
    "text",
    (
        "show my calendar next week",
        "show reminders this weekend",
        "vis kalenderen neste uke",
        "vis påminningane mine dei neste 3 dagane",
    ),
)
def test_unrepresentable_ranges_never_route_as_unfiltered_deterministic_lists(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent not in {BotIntent.CALENDAR_LIST, BotIntent.REMINDER_LIST}


@pytest.mark.parametrize(("text", "action"), UNSUPPORTED_P2_LIST_READS)
def test_p2_read_aliases_do_not_discard_unsupported_ranges_or_qualifiers(
    text,
    action,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent not in {
        BotIntent.CALENDAR_LIST,
        BotIntent.REMINDER_LIST,
    }
    assert semantic is None


@pytest.mark.parametrize("direction", ("write_first", "read_first"))
@pytest.mark.parametrize(
    "read_request",
    tuple(text for text, _ in UNSUPPORTED_P2_LIST_READS),
)
def test_unsupported_p2_reads_block_partial_execution_in_both_directions(
    read_request,
    direction,
):
    write = "add Inception to my watchlist"
    text = (
        f"{write} and {read_request}"
        if direction == "write_first"
        else f"{read_request} and {write}"
    )
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "multiple_actions_require_split"
    assert semantic is None


def test_semantic_list_date_must_match_the_shared_resolver():
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.CALENDAR_LIST,
            {"date": "16.07.2026"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance("What's on my calendar tomorrow?")
        ),
    )

    assert result is None


@pytest.mark.parametrize(
    ("text", "action"),
    (
        (
            "What's on my calendar tomorrow and delete event 1",
            ActionName.CALENDAR_LIST,
        ),
        (
            "Kva må eg hugse i morgon og slett påminning 1",
            ActionName.REMINDER_LIST,
        ),
    ),
)
def test_filtered_list_sequences_never_execute_only_the_first_clause(text, action):
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "multiple_actions_require_split"
    assert semantic is None


@pytest.mark.parametrize(
    "second",
    (
        "Har jeg noe planlagt i morgen?",
        "Any reminders for tomorrow?",
        "Har jeg påminnelser fredag?",
        "What's my schedule tomorrow?",
        "Kan eg sjå påminningane mine i morgon?",
        "Show only work events on my calendar tomorrow",
    ),
)
def test_write_first_then_filtered_or_unsupported_read_never_partially_executes(
    second,
):
    text = f"add Inception to my watchlist and {second}"
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "multiple_actions_require_split"
    assert semantic is None


@pytest.mark.parametrize(
    ("text", "expected_text"),
    (
        (
            "Legg inn en påminnelse om å ringe mamma i morgen",
            "ringe mamma",
        ),
        (
            "Kan du legge inn en påminnelse om å ringe mamma i morgen?",
            "ringe mamma",
        ),
        (
            "Planlegg en påminnelse om å ringe mamma i morgen",
            "ringe mamma",
        ),
        (
            "Legg til et gjøremål om å kjøpe melk i morgen",
            "kjøpe melk",
        ),
        (
            "Sette opp en reminder to call mom tomorrow",
            "call mom",
        ),
    ),
)
def test_explicit_reminder_nouns_never_fall_into_calendar(text, expected_text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.REMINDER_CREATE
    assert result.payload["reminder"]["text"] == expected_text
    assert result.payload["reminder"]["due_date"] == "15.07.2026"


def test_birthday_shorthand_routes_to_birthday_and_unresolved_name_clarifies():
    router = build_production_router(EvalFixture.EMPTY)

    own = router.route_help_example("Legg inn bursdagen min 15. mai")
    named = router.route_help_example("Legg inn en bursdag for Ola 15. mai")

    assert own.intent is BotIntent.BIRTHDAY_CREATE
    assert own.payload["birthday"] == {
        "action": "add",
        "user_id": 7,
        "display_name": "Kari",
        "day": 15,
        "month": 5,
    }
    assert named.intent is BotIntent.CLARIFY
    assert named.reason == "birthday_identity_required"


@pytest.mark.parametrize(
    "text",
    (
        "Legg inn Dune på watchlisten i morgen",
        "Planlegg en avstemning om lunsj i morgen",
        "Planlegg ein avstemming i morgon",
        "Planlegg et sitat i morgen",
        "Legg inn profilen min i morgen",
    ),
)
def test_foreign_feature_nouns_without_calendar_domain_never_write_calendar(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is not BotIntent.CALENDAR_ITEM


def test_explicit_calendar_domain_overrides_foreign_noun_guard():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "Planlegg et sitat i kalenderen i morgen"
    )

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == "Sitat"


@pytest.mark.parametrize(
    "second",
    (
        "Legg inn en påminnelse om å ringe mamma i morgen",
        "Legg inn bursdagen min 15. mai",
        "Planlegg ein avstemming i morgon",
    ),
)
def test_cross_domain_second_actions_always_require_split(second):
    text = f"add Inception to my watchlist and {second}"
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "multiple_actions_require_split"
    assert semantic is None


@pytest.mark.parametrize(
    ("intent", "raw", "expected"),
    (
        (
            BotIntent.CALENDAR_LIST,
            {"date": "20/07/2026"},
            {"date": "20.07.2026"},
        ),
        (
            BotIntent.REMINDER_LIST,
            {"action": "list", "due_date": "20/07/2026"},
            {"action": "list", "due_date": "20.07.2026"},
        ),
    ),
)
def test_typed_list_filters_are_canonicalized(intent, raw, expected):
    assert validate_intent_payload(intent, raw) == expected


@pytest.mark.parametrize(
    ("intent", "raw"),
    (
        (BotIntent.CALENDAR_LIST, {"date": "tomorrow"}),
        (BotIntent.CALENDAR_LIST, {"date": "20.07.2026", "range": 3}),
        (BotIntent.REMINDER_LIST, {"action": "list", "due_date": "Friday"}),
        (
            BotIntent.REMINDER_SEARCH,
            {"action": "search", "query": "lege", "due_date": "20.07.2026"},
        ),
    ),
)
def test_typed_list_filters_reject_aliases_ranges_and_wrong_actions(intent, raw):
    with pytest.raises(PayloadValidationError):
        validate_intent_payload(intent, raw)


def test_filtered_calendar_output_preserves_complete_snapshot_indices():
    rows = (
        {"id": "one", "title": "I dag", "date": "14.07.2026"},
        {"id": "two", "title": "I morgen", "date": "15.07.2026"},
        {"id": "three", "title": "Senere", "date": "16.07.2026"},
    )
    handler = object.__new__(CalendarHandler)
    handler.calendar = SimpleNamespace(
        snapshot_pending_items=Mock(return_value=rows)
    )

    text = handler._format_list(REFERENCE, date_filter="15.07.2026")

    assert "**2.** I morgen" in text
    assert "**1.** I morgen" not in text
    assert "I dag" not in text
    assert (
        handler._format_list(REFERENCE, date_filter="20.07.2026")
        == "📭 **Ingen kalenderoppføringer 20.07.2026.**"
    )


def test_explicit_calendar_date_bypasses_unfiltered_one_year_horizon_safely():
    manager = object.__new__(CalendarManager)
    manager.items = {
        manager.SHARED_KEY: [
            {
                "id": "near",
                "title": "Nær",
                "date": "15.07.2026",
                "completed": False,
                "delete_pending": False,
            },
            {
                "id": "far",
                "title": "Langt fram",
                "date": "01.08.2027",
                "completed": False,
                "delete_pending": False,
            },
        ]
    }
    handler = object.__new__(CalendarHandler)
    handler.calendar = manager

    unfiltered = handler._format_list(REFERENCE)
    filtered = handler._format_list(
        REFERENCE, date_filter="01.08.2027"
    )
    status, matches = handler._resolve_target(
        {"number": 2}, reference_time=REFERENCE
    )

    assert "Nær" in unfiltered
    assert "Langt fram" not in unfiltered
    assert "**2.** Langt fram" in filtered
    assert status == "found"
    assert matches[0]["id"] == "far"


@pytest.mark.asyncio
async def test_explicit_past_calendar_date_is_rejected_as_unsupported_history():
    manager = object.__new__(CalendarManager)
    manager.items = {
        manager.SHARED_KEY: [
            {
                "id": "past",
                "title": "I går",
                "date": "13.07.2026",
                "completed": False,
                "delete_pending": False,
            },
            {
                "id": "future",
                "title": "I morgen",
                "date": "15.07.2026",
                "completed": False,
                "delete_pending": False,
            },
        ]
    }
    handler = object.__new__(CalendarHandler)
    handler.calendar = manager

    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example("Show me my calendar 13.07.2026")
    semantic = ActionBridge().to_result(
        proposal_for(ActionName.CALENDAR_LIST, {}, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(
                "Show me my calendar 13.07.2026"
            )
        ),
    )
    handler._now_provider = lambda: REFERENCE
    handler.send_response_result = AsyncMock(
        return_value=MessageSendResult(DeliveryState.DELIVERED)
    )
    outcome = await handler.handle_list(
        RecordingMessage("must remain unread"),
        {"date": "13.07.2026"},
        reference_time=REFERENCE,
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "calendar_history_not_supported"
    assert semantic is None
    assert not outcome.ok
    assert outcome.error_code == "invalid_payload"
    assert "i dag og fremover" in handler.send_response_result.await_args.args[1]
    assert [row["id"] for row in manager.snapshot_target_items(
        reference_time=REFERENCE
    )] == ["future"]


@pytest.mark.parametrize(
    "text",
    (
        "Check my calendar 13.07.2026",
        "Do I have anything on my calendar 13.07.2026?",
        "Sjekk kalenderen min 13.07.2026",
        "Er det noko i kalenderen min 13.07.2026?",
    ),
)
def test_p2_past_calendar_aliases_keep_the_history_clarification(text):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(ActionName.CALENDAR_LIST, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "calendar_history_not_supported"
    assert semantic is None


@pytest.mark.asyncio
async def test_calendar_handler_rejects_malformed_direct_typed_filter():
    handler = object.__new__(CalendarHandler)
    handler._now_provider = lambda: REFERENCE
    handler.calendar = SimpleNamespace(snapshot_pending_items=Mock())
    handler.send_response_result = AsyncMock(
        return_value=MessageSendResult(DeliveryState.DELIVERED)
    )

    outcome = await handler.handle_list(
        RecordingMessage("must remain unread"),
        {"date": "tomorrow"},
        reference_time=REFERENCE,
    )

    assert not outcome.ok
    assert outcome.error_code == "invalid_payload"
    handler.calendar.snapshot_pending_items.assert_not_called()


def test_filtered_reminder_output_preserves_complete_active_indices():
    manager = object.__new__(ReminderManager)
    manager.reminders = {
        "123": [
            {
                "id": "one",
                "text": "I dag",
                "due_date": "14.07.2026",
                "completed": False,
                "created_at": "2026-07-01T10:00:00+02:00",
            },
            {
                "id": "two",
                "text": "I morgen",
                "due_date": "15.07.2026",
                "completed": False,
                "created_at": "2026-07-02T10:00:00+02:00",
            },
        ]
    }

    text = manager.format_reminders_list(
        123,
        show_completed=True,
        reference_time=REFERENCE,
        due_date="15.07.2026",
    )

    assert text is not None
    assert "**2.** I morgen" in text
    assert "**1.** I morgen" not in text
    assert "I dag" not in text
    assert (
        manager.format_reminders_list(
            123,
            show_completed=True,
            reference_time=REFERENCE,
            due_date="20.07.2026",
        )
        is None
    )


@pytest.mark.asyncio
async def test_dispatch_passes_validated_calendar_filter_without_raw_reparse():
    monitor = MessageMonitorRoutingTests().make_monitor()
    expected = DispatchOutcome.success(mutated=False)
    handler = AsyncMock(return_value=expected)
    monitor.handlers["calendar"].handle_list = handler
    message = RecordingMessage("CONTRADICTORY RAW CONTENT")
    route = IntentResult(
        BotIntent.CALENDAR_LIST,
        1.0,
        {"calendar_list": {"date": "15/07/2026"}},
        source=IntentSource.DETERMINISTIC,
    )

    actual = await monitor._handle_intent(message, route, reference_time=NOW)

    assert actual is expected
    handler.assert_awaited_once_with(
        message,
        {"date": "15.07.2026"},
        reference_time=NOW,
    )


@pytest.mark.asyncio
async def test_reminder_handler_forwards_filter_and_names_empty_date():
    handler, reminders, _ = make_handler()
    reminders.format_reminders_list.return_value = None

    outcome = await handler.handle_reminder_list(
        TypedMessage(),
        {"action": "list", "due_date": "15.07.2026"},
        reference_time=NOW,
    )

    assert outcome.ok
    reminders.format_reminders_list.assert_called_once_with(
        123,
        show_completed=True,
        reference_time=NOW,
        due_date="15.07.2026",
    )
    sent = handler.send_response_result.await_args.args[1]
    assert "15.07.2026" in sent

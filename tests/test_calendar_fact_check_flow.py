from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.calendar_fact_check_store import CalendarFactCheckStore, CalendarFactCheckTarget
from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from core.message_context import ConversationKey
from tests.nlu_harness import build_production_router


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)
KEY = ConversationKey(9001, 9002, 9003)
TARGET = CalendarFactCheckTarget(
    "calendar-1", "revision-1", "Møte med Ola", "26.07.2026", "09:00"
)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


@pytest.fixture
def adapter():
    value = build_production_router(EvalFixture.CALENDAR_TITLE_MEETING)
    clock = Clock()
    store = CalendarFactCheckStore(now_provider=clock)
    value._router.calendar_fact_checks = store
    value._router.monitor.pending_targets = SimpleNamespace(
        revalidate_calendar_fact_check_target=lambda target, **_kwargs: target
    )
    value._routing_context = value._routing_context.__class__(
        KEY, value._routing_context.author, value._routing_context.mentions
    )
    value._clock = clock
    return value


def begin(adapter, targets=(TARGET,)):
    adapter._router.calendar_fact_checks.begin(KEY, targets)


@pytest.mark.parametrize("text", ("sjekk", "ja, finn ut av det", "kan du undersøke?", "look it up"))
def test_ready_search_continuations_are_scoped_read_only(adapter, text):
    begin(adapter)
    result = adapter.route_help_example(text)
    assert result.intent is BotIntent.CALENDAR_FACT_CHECK
    assert result.payload == {
        "calendar_fact_check": {
            "action": "search",
            "field": "schedule",
            "target": TARGET.stable_id,
        }
    }
    assert result.requires_confirmation is False


def test_choice_selection_and_invalid_choice_are_bounded(adapter):
    second = CalendarFactCheckTarget("calendar-2", "revision-2", "Møte 2", "27.07.2026", "10:00")
    begin(adapter, (TARGET, second))
    invalid = adapter.route_help_example("9")
    assert invalid.intent is BotIntent.CLARIFY
    selected = adapter.route_help_example("andre")
    assert selected.intent is BotIntent.CALENDAR_FACT_CHECK
    assert selected.payload["calendar_fact_check"] == {"action": "select", "number": 2}


@pytest.mark.parametrize(
    ("text", "changes"),
    (
        ("klokka 18", {"time": "18:00"}),
        ("27.07.2026", {"date": "27.07.2026"}),
        ("27.07.2026 klokka 18", {"date": "27.07.2026", "time": "18:00"}),
    ),
)
def test_direct_temporal_reply_only_stages_requested_fields(adapter, text, changes):
    begin(adapter)
    result = adapter.route_help_example(text)
    assert result.intent is BotIntent.CALENDAR_EDIT
    assert result.reason == "calendar_fact_check_direct_edit"
    assert result.requires_confirmation is True
    assert result.payload == {
        "calendar_edit": {"target": TARGET.stable_id, "changes": changes}
    }


@pytest.mark.parametrize("text", ("6", "at 6", "klokka 25"))
def test_ambiguous_or_invalid_direct_time_clarifies(adapter, text):
    begin(adapter)
    result = adapter.route_help_example(text)
    assert result.intent is BotIntent.CLARIFY
    assert result.requires_confirmation is False


def test_cancel_and_unrelated_turn_do_not_cross_state_boundaries(adapter):
    begin(adapter)
    unrelated = adapter.route_help_example("hvordan går det?")
    assert unrelated.intent is BotIntent.AI_CHAT
    assert adapter._router.calendar_fact_checks.lookup(KEY).inquiry is not None
    cancelled = adapter.route_help_example("avbryt")
    assert cancelled.intent is BotIntent.CALENDAR_FACT_CHECK
    assert cancelled.payload["calendar_fact_check"] == {"action": "cancel"}


def test_expired_recognized_continuation_gets_targeted_copy(adapter):
    begin(adapter)
    adapter._clock.value += timedelta(minutes=10)
    result = adapter.route_help_example("sjekk")
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "calendar_fact_check_expired"


def test_other_conversation_cannot_observe_inquiry(adapter):
    begin(adapter)
    other = adapter._router.route(
        "sjekk",
        guild_id=KEY.guild_id,
        channel_id=KEY.channel_id,
        user_id=KEY.user_id + 1,
        reference_time=NOW,
    )
    assert other.intent is not BotIntent.CALENDAR_FACT_CHECK

#!/usr/bin/env python3
"""Regression tests for central intent routing."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from cal_system.natural_language_parser import NaturalLanguageParser, NaturalParseResult
from cal_system.temporal_resolver import DATE_ALIASES, OSLO, TemporalResolver
from core.eval_fixtures import EvalFixture
from core.intent_models import (
    IntentCandidate,
    IntentResult,
    IntentRisk,
    IntentSource,
    RejectionCode,
)
from core.intent_payloads import ENVELOPE_KEYS, validate_intent_payload
from core.intent_router import (
    BotIntent,
    COLLECTOR_ORDER,
    CollectorContext,
    CollectorOutput,
    IntentRouter,
)
from core.message_context import (
    ConversationKey,
    ResolvedMention,
    RoutingContext,
    conversation_key_from_message,
    domain_scope_id,
    routing_context_from_message,
)
from core.nlu_metrics import NLUMetrics
from core.pending_actions import PendingActionStore
from core.utterance import normalize_utterance
from core.utterance_semantics import REJECTIONS, analyze_utterance
from features.crypto_manager import parse_price_command
from features.quote_manager import parse_quote_command
from features.search_manager import detect_search_intent
from features.watchlist_manager import parse_watchlist_command
from tests.nlu_harness import build_production_router


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)


@pytest.fixture
def production_router_adapter():
    return build_production_router(EvalFixture.MIXED_STATE)


@pytest.fixture
def active_poll_router_adapter():
    return build_production_router(EvalFixture.ACTIVE_POLL)


def _nested_payload_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _nested_payload_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _nested_payload_keys(nested)


@pytest.mark.parametrize(
    "read_request",
    (
        "show all my reminders",
        "show my calendar",
        "show active polls",
        "show my watchlist",
        "list quotes",
        "show upcoming birthdays",
        "show word of the day",
        "show aurora",
        "show school holidays in Oslo",
        "show weather",
        "show what you remember about me",
        "show me what you remember about me",
        "export my memory",
        "show bot status",
        "show profile",
        "show birthday",
        "show me a quote",
    ),
)
def test_calendar_create_plus_every_reviewed_read_requires_split(
    production_router_adapter,
    read_request,
):
    create = production_router_adapter.route_help_example(
        "create a meeting tomorrow"
    )
    combined = production_router_adapter.route_help_example(
        f"create a meeting tomorrow and {read_request}"
    )

    assert create.intent is BotIntent.CALENDAR_ITEM
    assert combined.intent is BotIntent.CLARIFY
    assert combined.reason == "multiple_actions_require_split"
    assert "calendar_item" not in combined.payload


@pytest.mark.parametrize(
    ("text", "expected_intent", "payload_path", "expected_value"),
    (
        (
            "search for cats and dogs",
            BotIntent.SEARCH,
            ("search", "query"),
            "cats and dogs",
        ),
        (
            "remind me to buy milk and bread tomorrow",
            BotIntent.REMINDER_CREATE,
            ("reminder", "text"),
            "buy milk and bread",
        ),
        (
            "add Fish and Chips to my watchlist",
            BotIntent.WATCHLIST,
            ("watchlist", "title"),
            "Fish and Chips",
        ),
        (
            "create a meeting with Research and Development tomorrow",
            BotIntent.CALENDAR_ITEM,
            ("calendar_item", "title"),
            "Meeting with Research and Development",
        ),
    ),
)
def test_sequence_guard_preserves_supported_payload_conjunctions(
    production_router_adapter,
    text,
    expected_intent,
    payload_path,
    expected_value,
):
    result = production_router_adapter.route_help_example(text)
    value = result.payload
    for key in payload_path:
        value = value[key]

    assert result.intent is expected_intent
    assert result.reason != "multiple_actions_require_split"
    assert value == expected_value


@pytest.mark.parametrize(
    "text",
    (
        "møte med Ola i morgen kl. 14",
        "legg inn møte i morgen kl. 14",
    ),
)
def test_sequence_probe_does_not_treat_clock_abbreviation_as_clause_boundary(
    production_router_adapter,
    text,
):
    result = production_router_adapter.route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.reason != "multiple_actions_require_split"


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        (
            "shorten https://example.com/a,and/delete?next=remove",
            BotIntent.SHORTEN_URL,
        ),
        (
            'remind me about "and show weather" tomorrow',
            BotIntent.REMINDER_CREATE,
        ),
    ),
)
def test_sequence_probe_preserves_urls_and_quoted_payloads(
    production_router_adapter,
    text,
    expected_intent,
):
    result = production_router_adapter.route_help_example(text)

    assert result.intent is expected_intent
    assert result.reason != "multiple_actions_require_split"


def test_contextual_bare_poll_vote_after_write_requires_split_only_with_poll():
    with_poll = build_production_router(EvalFixture.ACTIVE_POLL)
    empty = build_production_router(EvalFixture.EMPTY)
    text = "create a meeting tomorrow and 1"

    guarded = with_poll.route_help_example(text)
    unguarded = empty.route_help_example(text)

    assert guarded.intent is BotIntent.CLARIFY
    assert guarded.reason == "multiple_actions_require_split"
    assert unguarded.intent is BotIntent.CALENDAR_ITEM


def test_sequence_probe_budget_overflow_after_write_fails_closed():
    adapter = build_production_router(EvalFixture.ACTIVE_POLL)
    payload = " and ".join(["filler"] * 25 + ["1"])

    result = adapter.route_help_example(
        f"create a meeting tomorrow and {payload}"
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"


@pytest.mark.parametrize(
    ("fixture", "expected_intent"),
    (
        (EvalFixture.ACTIVE_REMINDER, BotIntent.REMINDER_COMPLETE),
        (EvalFixture.CALENDAR_TITLE_MEETING, BotIntent.CALENDAR_COMPLETE),
    ),
)
def test_bare_completion_uses_the_only_live_target_domain(
    fixture,
    expected_intent,
):
    result = build_production_router(fixture).route_help_example("ferdig 1")

    assert result.intent is expected_intent


def test_bare_completion_clarifies_when_calendar_and_reminder_indices_overlap():
    result = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example("ferdig 1")

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "ambiguous_completion_domain"
    assert "kalenderoppføring 1" in result.payload["clarification"]
    assert "påminnelse 1" in result.payload["clarification"]


@pytest.mark.parametrize(
    "text",
    (
        "mark 1 done",
        "mark 1 complete",
        "marker 1 ferdig",
        "marker 1 som ferdig",
        "Can you mark 1 done?",
    ),
)
def test_unqualified_mark_done_clarifies_when_target_stores_overlap(text):
    result = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "ambiguous_completion_domain"


@pytest.mark.parametrize(
    "text",
    ("mark 1 done", "mark 1 complete", "marker 1 ferdig"),
)
def test_unqualified_mark_done_uses_only_live_reminder_store(text):
    result = build_production_router(
        EvalFixture.ACTIVE_REMINDER
    ).route_help_example(text)

    assert result.intent is BotIntent.REMINDER_COMPLETE


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        ("kalender ferdig 1", BotIntent.CALENDAR_COMPLETE),
        ("ferdig påminnelse 1", BotIntent.REMINDER_COMPLETE),
    ),
)
def test_explicit_completion_domain_is_deterministic_in_mixed_state(
    text,
    expected_intent,
):
    result = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)

    assert result.intent is expected_intent


def test_bare_number_clarifies_when_poll_and_reminder_are_both_live():
    result = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example("1")

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "ambiguous_numeric_domain"


class DummyMonitor:
    def __init__(self, active_polls=False, calendar_titles=None, active_reminders=False):
        self.nlp_parser = NaturalLanguageParser()
        self.calendar = SimpleNamespace(
            get_upcoming=lambda guild_id, days=365, reference_time=None: [
                {"title": title, "date": "29.06.2026", "time": "12:00"}
                for title in (calendar_titles or [])
            ]
        )
        self.countdown = SimpleNamespace(parse_countdown_query=self._parse_countdown)
        self.poll = SimpleNamespace(
            get_active_polls=lambda guild_id, reference_time=None: (
                [{"id": "poll1"}] if active_polls else []
            )
        )
        self.reminders = SimpleNamespace(
            get_active_reminders=lambda guild_id: [{"id": "rem1"}] if active_reminders else []
        )
        self.conversation = SimpleNamespace(
            should_show_dashboard=self._should_show_dashboard,
            threads={},
        )
        self.detect_search_intent = self._detect_search_intent

        self.parse_poll_command = self._parse_poll
        self.parse_vote = self._parse_vote
        self.parse_watchlist_command = parse_watchlist_command
        self.parse_quote_command = parse_quote_command
        self.parse_price_command = self._parse_price
        self.parse_horoscope_command = self._parse_horoscope
        self.parse_compliment_command = self._parse_compliment
        self.parse_calculator_command = self._parse_calculator
        self.parse_shorten_command = self._parse_shorten

    def _parse_countdown(self, content, *, reference_time=None):
        return {"event": "jul"} if "hvor lenge til jul" in content.lower() else None

    def _parse_poll(self, content):
        return {"question": "pizza?", "options": ["Ja", "Nei"]} if "avstemning" in content.lower() else None

    def _parse_vote(self, content):
        return int(content) if content.strip().isdigit() else None

    def _parse_watchlist(self, content, **_kwargs):
        lower = content.lower()
        if "fjern watchlist" in lower or "slett watchlist" in lower or "fjern fra watchlist" in lower:
            return {"action": "remove"}
        if "endre watchlist" in lower or "rediger watchlist" in lower:
            return {"action": "edit"}
        return {"action": "suggest"} if "hva skal vi se" in lower else None

    def _parse_quote(self, content):
        return {"action": "get"} if "sitat" in content.lower() else None

    def _parse_price(self, content):
        return {"type": "crypto", "asset": "bitcoin"} if "bitcoin" in content.lower() and "koster" in content.lower() else None

    def _parse_horoscope(self, content):
        return {"sign": "væren"} if "horoskop" in content.lower() else None

    def _parse_compliment(self, content):
        return {"action": "compliment"} if "kompliment" in content.lower() else None

    def _parse_calculator(self, content):
        return {"type": "math", "expression": "2+2"} if "2+2" in content else None

    def _parse_shorten(self, content):
        return {"url": "https://example.com"} if "forkort" in content.lower() else None

    def _detect_search_intent(self, content):
        lower = content.lower()
        if "hva skjer i trondheim" in lower:
            return {"query": "Trondheim i helga", "type": "web"}
        if lower.strip() in {"hva skjer?", "hva skjer"}:
            return {"query": "hva skjer", "type": "web"}
        return None

    def _should_show_dashboard(self, content, guild_id):
        if "vis dashboard" in content.lower():
            return True, "explicit_request"
        return False, "default"


def _semantic_reminder_route() -> IntentResult:
    return IntentResult(
        BotIntent.REMINDER_CREATE,
        0.91,
        {
            "reminder": {
                "action": "add",
                "text": "ringe legen",
                "due_at": "2026-07-15T09:00:00+02:00",
            }
        },
        "semantic_action",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )


def _present_confirmation(store, key, route=None):
    draft = store.begin_confirmation(
        key,
        route or _semantic_reminder_route(),
        "Ringe legen",
    )
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


def _present_choices(store, key):
    draft = store.begin_choices(
        key,
        (
            IntentResult(BotIntent.CALENDAR_LIST, 1.0),
            IntentResult(BotIntent.REMINDER_LIST, 1.0),
        ),
        "Velg",
        target_guards=(None, None),
    )
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


@pytest.fixture
def pending_store():
    return PendingActionStore(now_provider=lambda: NOW)


@pytest.fixture
def pending_router(pending_store):
    return IntentRouter(
        DummyMonitor(),
        pending_actions=pending_store,
        now_provider=lambda: NOW,
    )


def test_matching_confirmation_routes_before_collectors(
    pending_router,
    pending_store,
):
    pending = _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    route = pending_router.route(
        "ja",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert route.intent is BotIntent.ACTION_CONFIRM
    assert route.payload == {
        "pending": {"action_id": pending.action_id}
    }
    assert route.risk is IntentRisk.READ_ONLY


def test_expired_pending_prunes_without_swallowing_fresh_calendar_read():
    current = [NOW]
    store = PendingActionStore(
        now_provider=lambda: current[0],
        ttl=timedelta(minutes=10),
    )
    router = IntentRouter(
        DummyMonitor(),
        pending_actions=store,
        now_provider=lambda: current[0],
    )
    _present_confirmation(store, ConversationKey(1, 10, 7))
    current[0] += timedelta(minutes=10)

    route = router.route(
        "kan du vise meg kalenderen?",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )

    assert route.intent is BotIntent.CALENDAR_LIST
    assert route.reason != "pending_expired"
    assert store.peek(ConversationKey(1, 10, 7)) is None


def test_ambiguous_norwegian_half_clock_clarifies_without_staging_reminder():
    route = IntentRouter(
        DummyMonitor(),
        now_provider=lambda: NOW,
    ).route(
        "kan du minne meg på å ringe legen i morgen klokka halv tre?",
        guild_id=123,
    )

    assert route.intent is BotIntent.CLARIFY
    assert route.reason == "reminder_half_clock_ambiguous"
    assert route.requires_confirmation is False
    assert "morgenen" in route.payload["clarification"]
    assert "ettermiddagen" in route.payload["clarification"]


def test_invalid_half_clock_does_not_receive_a_false_ambiguity_prompt():
    route = IntentRouter(
        DummyMonitor(),
        now_provider=lambda: NOW,
    ).route(
        "kan du minne meg på å ringe legen i morgen klokka halv 25?",
        guild_id=123,
    )

    assert route.intent is not BotIntent.REMINDER_CREATE
    assert route.reason != "reminder_half_clock_ambiguous"


def test_polite_infinitive_url_shorten_preserves_full_url_payload():
    url = "https://example.com/a/delete/calendar?x=1&next=remove#fragment"
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        f"Kan du forkorte {url}"
    )

    assert result.intent is BotIntent.SHORTEN_URL
    assert result.payload == {"shorten": {"url": url}}


@pytest.mark.parametrize(
    ("text", "expected_time"),
    (
        ("møte i morgen kl 14.30", "14:30"),
        ("møte i morgen klokka 14:30", "14:30"),
        (
            "møte i morgen klokka halv tre på ettermiddagen",
            "14:30",
        ),
        (
            "møte i morgen kvart over to på ettermiddagen",
            "14:15",
        ),
        (
            "møte i morgen klokka kvart over to på ettermiddagen",
            "14:15",
        ),
    ),
)
def test_calendar_route_keeps_minimal_title_after_natural_time_cleanup(
    text,
    expected_time,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == "Møte"
    assert result.payload["calendar_item"]["time"] == expected_time


def test_pending_cancel_correction_and_selection_payloads_are_inert_ids(
    pending_router,
    pending_store,
):
    key_value = ConversationKey(1, 10, 7)
    confirmation = _present_confirmation(pending_store, key_value)
    canceled = pending_router.route(
        "nei", guild_id=1, channel_id=10, user_id=7
    )
    assert canceled.intent is BotIntent.ACTION_CANCEL
    assert canceled.payload == {
        "pending": {"action_id": confirmation.action_id}
    }

    corrected = pending_router.route(
        "i morgen kl 14",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert corrected.intent is BotIntent.ACTION_CORRECT
    assert corrected.payload == {
        "pending": {
            "action_id": confirmation.action_id,
            "correction_text": "i morgen kl 14",
        }
    }

    choices = _present_choices(pending_store, key_value)
    selected = pending_router.route(
        "den andre",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert selected.intent is BotIntent.ACTION_SELECT
    assert selected.payload == {
        "pending": {
            "action_id": choices.action_id,
            "choice_index": 1,
        }
    }
    assert "route" not in selected.payload["pending"]


@pytest.mark.parametrize(
    "text",
    [
        "nei takk",
        "ikke likevel",
        "glem det",
        "la oss droppe det",
    ],
)
def test_natural_pending_cancellations_route_before_collectors(
    pending_router,
    pending_store,
    text,
):
    pending = _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    route = pending_router.route(
        text,
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert route.intent is BotIntent.ACTION_CANCEL
    assert route.payload == {
        "pending": {"action_id": pending.action_id}
    }


@pytest.mark.parametrize(
    "text",
    ["kjør på", "det stemmer", "go ahead", "sure", "yep"],
)
def test_natural_pending_confirmations_route_before_collectors(
    pending_router,
    pending_store,
    text,
):
    pending = _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    route = pending_router.route(
        text,
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert route.intent is BotIntent.ACTION_CONFIRM
    assert route.payload == {
        "pending": {"action_id": pending.action_id}
    }


@pytest.mark.parametrize(
    "text",
    [
        "lukk avstemning 1, men ved nærmere ettertanke ikke",
        "close poll 1, but on second thought do not",
        "edit poll 1 question: Ny?, but on second thought do not",
        "lukk avstemning 1, nei takk",
    ],
)
def test_poll_retractions_block_deterministic_mutations(
    active_poll_router_adapter,
    text,
):
    result, _ = active_poll_router_adapter.evaluate(text, guild_id=123)
    assert result.intent is BotIntent.AI_CHAT
    assert result.reason == "unsafe_mutation_blocked"


@pytest.mark.parametrize(
    "text",
    [
        "opprett møte i morgen, og så slett kalenderen",
        "opprett møte i morgen, deretter slett kalenderen",
        "opprett møte i morgen, så slett kalenderen",
        "opprett møte i morgen, slett kalenderen",
        "opprett møte i morgen; slett kalenderen",
        "create a meeting tomorrow, then delete the calendar",
        "create a meeting tomorrow; after that delete the calendar",
        "påminn meg om å ringe legen i morgen og slett kalenderen",
        "lag en avstemning: Mat? Pizza eller taco, så påminn meg om å handle",
        "lagre sitat Tenk stort. Slett kalenderen",
        "kalender auth AbC_12, deretter slett kalenderen",
        "kan du lage en avstemning: Mat? Pizza eller taco, deretter slett kalenderen",
        "jeg stemmer på alternativ to, deretter slett kalenderen",
    ],
)
def test_production_router_never_selects_or_stages_one_partial_action(
    production_router_adapter,
    text,
):
    result, parser_names = production_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "tail",
    (
        "forkort https://example.com/a",
        "søk etter katter",
        "vis prisen på BTC",
        "regn ut 2+2",
        "vis horoskopet for løven",
        "vis status",
        "gi meg et kompliment",
        "konverter 100 USD til NOK",
        "sett status idle",
        "start nedtelling til jul",
        "compute 42",
        "omgjør 10 km til meter",
        "hvor mange dager er det til jul",
        "how much is Solana",
        "could you if you have time search for cats",
        "if you have time could you shorten https://example.com/a",
        "kan du huske at jeg vil se Inception",
        "teach me a word",
        "can I see aurora tonight",
    ),
)
def test_calendar_create_then_read_action_never_commits_a_partial_title(
    production_router_adapter,
    tail,
):
    result, parser_names = production_router_adapter.evaluate(
        f"lag et møte i morgen og {tail}",
        guild_id=123,
    )

    assert parser_names == ()
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"


@pytest.mark.parametrize(
    "head",
    (
        "forkort https://example.com/a",
        "søk etter katter",
        "vis prisen på BTC",
        "regn ut 2+2",
        "vis horoskopet for løven",
        "vis status",
        "gi meg et kompliment",
        "konverter 100 USD til NOK",
    ),
)
def test_read_action_then_calendar_create_also_requires_one_action_per_turn(
    production_router_adapter,
    head,
):
    result, parser_names = production_router_adapter.evaluate(
        f"{head} og lag et møte i morgen",
        guild_id=123,
    )

    assert parser_names == ()
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"


@pytest.mark.parametrize("retraction", sorted(REJECTIONS))
def test_production_router_never_writes_or_stages_after_terminal_retraction(
    production_router_adapter,
    retraction,
):
    result, parser_names = production_router_adapter.evaluate(
        f"påminn meg om å ringe legen i morgen, {retraction}",
        guild_id=123,
    )

    assert parser_names == ()
    assert result.intent is BotIntent.AI_CHAT
    assert result.reason == "unsafe_mutation_blocked"
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    [
        "slett poll 1 og 2",
        "slett poll 1 og poll 2",
        "slett poll 1, 2",
        "lukk poll siste og 1",
    ],
)
def test_production_router_never_executes_only_one_of_multiple_poll_targets(
    active_poll_router_adapter,
    text,
):
    result, parser_names = active_poll_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    [
        "lukk poll etter 15 minutter",
        "slett poll kanskje",
        "lukk poll når alle har stemt",
        'slett poll "nummer 1 og 2"',
    ],
)
def test_production_router_never_discards_unsupported_poll_mutation_suffix(
    active_poll_router_adapter,
    text,
):
    result, parser_names = active_poll_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "unsupported_poll_mutation_modifier"
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    [
        "src/foo/bar",
        "./src/foo/bar.py",
        "docs/setup/getting-started.md",
        "kan du se på src/foo/bar?",
        "which file is docs/setup/getting-started.md?",
    ],
)
def test_production_router_never_turns_relative_path_into_implicit_poll(
    production_router_adapter,
    text,
):
    result, parser_names = production_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.AI_CHAT
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("text", "expected_title"),
    [
        ("husk å se Glem det aldri", "Glem det aldri"),
        ("husk å se Love and Thunder", "Love and Thunder"),
    ],
)
def test_production_router_preserves_action_shaped_media_titles(
    production_router_adapter,
    text,
    expected_title,
):
    result, parser_names = production_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.WATCHLIST
    assert result.payload["watchlist"]["action"] == "add"
    assert result.payload["watchlist"]["title"] == expected_title


def test_other_scope_confirmation_is_ordinary_chat(
    pending_router,
    pending_store,
):
    _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    for route in (
        pending_router.route(
            "ja", guild_id=1, channel_id=10, user_id=8
        ),
        pending_router.route(
            "ja", guild_id=1, channel_id=11, user_id=7
        ),
        pending_router.route(
            "ja", guild_id=2, channel_id=10, user_id=7
        ),
    ):
        assert route.intent is BotIntent.AI_CHAT


def test_quoted_and_meta_confirmation_words_do_not_consume_pending(
    pending_router,
    pending_store,
):
    _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    for text in ('"ja"', "jeg sa ja", "ordet «ja»"):
        route = pending_router.route(
            text,
            guild_id=1,
            channel_id=10,
            user_id=7,
        )
        assert route.intent is BotIntent.AI_CHAT

    confirmed = pending_router.route(
        "ja",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert confirmed.intent is BotIntent.ACTION_CONFIRM


def test_dm_confirmation_requires_exact_channel_and_user(
    pending_router,
    pending_store,
):
    pending = _present_confirmation(
        pending_store,
        ConversationKey(None, 300, 7),
    )
    assert pending_router.route(
        "ja", guild_id=None, channel_id=301, user_id=7
    ).intent is BotIntent.AI_CHAT
    assert pending_router.route(
        "ja", guild_id=None, channel_id=300, user_id=8
    ).intent is BotIntent.AI_CHAT

    matched = pending_router.route(
        "ja", guild_id=None, channel_id=300, user_id=7
    )
    assert matched.intent is BotIntent.ACTION_CONFIRM
    assert matched.payload == {
        "pending": {"action_id": pending.action_id}
    }


def test_unrelated_pending_message_continues_normal_routing(
    pending_router,
    pending_store,
):
    _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    route = pending_router.route(
        "hjelp",
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert route.intent is BotIntent.HELP


def test_incomplete_legacy_route_call_skips_pending_lookup(
    pending_router,
):
    assert pending_router.route("ja", guild_id=1).intent is BotIntent.AI_CHAT


def test_routing_context_mismatch_never_resolves_pending(
    pending_router,
    pending_store,
):
    key_value = ConversationKey(1, 10, 7)
    _present_confirmation(pending_store, key_value)
    context = RoutingContext(
        key=key_value,
        author=ResolvedMention(7, "Ola"),
    )

    mismatched = pending_router.route(
        "ja",
        guild_id=2,
        routing_context=context,
    )
    assert mismatched.intent is BotIntent.AI_CHAT
    assert mismatched.reason == "invalid_context"
    matched = pending_router.route("ja", routing_context=context)
    assert matched.intent is BotIntent.ACTION_CONFIRM


def test_evaluate_utterance_resolves_pending_exactly_once(
    pending_router,
    pending_store,
):
    _present_confirmation(
        pending_store,
        ConversationKey(1, 10, 7),
    )
    pending_store.resolve = Mock(wraps=pending_store.resolve)

    routed = pending_router.evaluate_utterance(
        normalize_utterance("ja"),
        guild_id=1,
        channel_id=10,
        user_id=7,
    )
    assert routed.result.intent is BotIntent.ACTION_CONFIRM
    pending_store.resolve.assert_called_once()


def test_expired_pending_action_becomes_fixed_clarification():
    current = [NOW]
    store = PendingActionStore(
        now_provider=lambda: current[0],
        ttl=timedelta(minutes=1),
    )
    router = IntentRouter(
        DummyMonitor(),
        pending_actions=store,
        now_provider=lambda: current[0],
    )
    _present_confirmation(store, ConversationKey(1, 10, 7))
    current[0] += timedelta(minutes=1)

    route = router.route(
        "ja", guild_id=1, channel_id=10, user_id=7
    )
    assert route.intent is BotIntent.CLARIFY
    assert route.reason == "pending_expired"
    assert route.payload == {
        "clarification": (
            "Den forrige bekreftelsen er utløpt. "
            "Be meg om handlingen på nytt."
        )
    }


def test_pending_router_preserves_injected_metrics_identity(pending_store):
    metrics = NLUMetrics()
    router = IntentRouter(
        DummyMonitor(),
        metrics=metrics,
        pending_actions=pending_store,
        now_provider=lambda: NOW,
    )
    assert router.metrics is metrics
    assert router.pending_actions is pending_store


class IntentRouterTests(unittest.TestCase):
    def route(
        self,
        text,
        active_polls=False,
        monitor=None,
        calendar_titles=None,
        active_reminders=False,
        *,
        channel_id=None,
        user_id=None,
    ):
        monitor = monitor or DummyMonitor(
            active_polls=active_polls,
            calendar_titles=calendar_titles,
            active_reminders=active_reminders,
        )
        return IntentRouter(
            monitor, now_provider=lambda: NOW
        ).route(
            text,
            guild_id=123,
            channel_id=channel_id,
            user_id=user_id,
        )

    def test_conversational_future_prompt_stays_ai_chat(self):
        result = self.route("jeg skal bare høre hva du synes om RBK i morgen")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_calendar_task_prompt_routes_to_calendar_item(self):
        result = self.route("husk å kjøpe melk på mandag")
        self.assertEqual(result.intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(result.payload["reminder"]["action"], "add")
        self.assertEqual(result.payload["reminder"]["text"], "kjøpe melk")

    def test_calendar_event_prompt_routes_with_time(self):
        result = self.route("møte med Ola i morgen kl 14")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["time"], "14:00")

    def test_english_pm_time_routes_with_time(self):
        result = self.route("meeting tomorrow at 3pm")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["time"], "15:00")
        self.assertEqual(result.payload["calendar_item"]["title"], "Meeting")

    def test_vague_reminder_followup_never_scrapes_recent_bot_prose(self):
        monitor = DummyMonitor()
        monitor.conversation.threads[456] = [
            {
                "channel_id": 456,
                "user_id": 7,
                "username": "Inebotten",
                "content": "Skal jeg hjelpe deg med å legge inn en påminnelse om å bestille billettene, eller kanskje du vil planlegge turen?",
                "is_bot": True,
                "timestamp": datetime.now(),
            }
        ]

        result = self.route(
            "minn meg på det imorgen kveld",
            monitor=monitor,
            channel_id=456,
            user_id=7,
        )

        self.assertEqual(result.intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(result.payload["reminder"]["text"], "det")
        self.assertEqual(result.payload["reminder"]["time"], "19:00")

    def test_vague_reminder_followup_is_not_filled_from_any_scope(self):
        monitor = DummyMonitor()
        monitor.conversation.threads[456] = [
            {
                "channel_id": 456,
                "user_id": 8,
                "content": "Skal jeg legge inn en påminnelse om å kjøpe is?",
                "is_bot": True,
                "timestamp": NOW,
            },
            {
                "channel_id": 456,
                "user_id": 7,
                "content": "Skal jeg legge inn en påminnelse om å bestille billetter?",
                "is_bot": True,
                "timestamp": NOW - timedelta(minutes=1),
            },
        ]
        monitor.conversation.threads[999] = [
            {
                "channel_id": 999,
                "user_id": 7,
                "content": "Skal jeg legge inn en påminnelse om å hente pakken?",
                "is_bot": True,
                "timestamp": NOW + timedelta(minutes=1),
            }
        ]

        matching = self.route(
            "minn meg på det i morgen",
            monitor=monitor,
            channel_id=456,
            user_id=7,
        )
        other_user = self.route(
            "minn meg på det i morgen",
            monitor=monitor,
            channel_id=456,
            user_id=9,
        )

        self.assertEqual(matching.payload["reminder"]["text"], "det")
        self.assertEqual(other_user.payload["reminder"]["text"], "det")

    def test_vague_hva_skjer_stays_ai_chat(self):
        result = self.route("hva skjer?")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_contextual_hva_skjer_routes_to_search(self):
        result = self.route("hva skjer i Trondheim i helga?")
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_travel_cost_question_routes_to_search_not_crypto(self):
        monitor = DummyMonitor()
        monitor.parse_price_command = cast(Any, parse_price_command)
        monitor.detect_search_intent = detect_search_intent

        result = self.route(
            "hva koster det å fly fra trondheim til panama?",
            monitor=monitor,
        )

        self.assertIsNone(parse_price_command("hva koster det å fly fra trondheim til panama?"))
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_active_poll_gates_numeric_vote(self):
        self.assertEqual(self.route("1", active_polls=False).intent, BotIntent.AI_CHAT)
        self.assertEqual(self.route("1", active_polls=True).intent, BotIntent.POLL_VOTE)

    def test_poll_list_routes_when_active_polls_exist(self):
        result = self.route("polls", active_polls=True)
        self.assertEqual(result.intent, BotIntent.POLL_LIST)
        self.assertEqual(result.confidence, 0.95)

    def test_poll_list_routes_even_when_no_active_polls(self):
        result = self.route("polls", active_polls=False)
        self.assertEqual(result.intent, BotIntent.POLL_LIST)

    def test_prompt_priority_examples(self):
        examples = {
            "status": BotIntent.STATUS,
            "hjelp": BotIntent.HELP,
            "bot status": BotIntent.STATUS,
            "status dnd": BotIntent.PROFILE,
            "status online": BotIntent.PROFILE,
            "kalender": BotIntent.CALENDAR_LIST,
            "hvor lenge til jul": BotIntent.COUNTDOWN,
            "hva skal vi se": BotIntent.WATCHLIST,
            "sitat": BotIntent.QUOTE,
            "hvor mye koster bitcoin": BotIntent.PRICE,
            "hva er 2+2": BotIntent.CALCULATOR,
            "vis dashboard": BotIntent.DASHBOARD,
        }
        for prompt, expected in examples.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(self.route(prompt).intent, expected)

    def test_status_command_priority_keeps_health_over_profile(self):
        self.assertEqual(self.route("status").intent, BotIntent.STATUS)
        self.assertEqual(self.route("bot status").intent, BotIntent.STATUS)

    def test_status_alone_does_not_trigger_profile(self):
        result = self.route("status")
        self.assertEqual(result.intent, BotIntent.STATUS)
        self.assertNotEqual(result.intent, BotIntent.PROFILE)

    def test_presence_status_requires_discord_status_word(self):
        self.assertEqual(self.route("status dnd").intent, BotIntent.PROFILE)
        self.assertEqual(self.route("status invisible").intent, BotIntent.PROFILE)
        self.assertEqual(self.route("status").intent, BotIntent.STATUS)

    def test_profile_activity_preserves_titles_with_copular_words(self):
        for text in (
            "playing Life is Strange",
            "watching This Is Us",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.PROFILE)
        self.assertEqual(
            self.route("playing football is fun").intent,
            BotIntent.AI_CHAT,
        )

    def test_incomplete_calendar_oppdater_falls_back(self):
        result = self.route("kalender oppdater")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)
        self.assertEqual(result.payload, {})

    def test_calendar_oppdater_fra_google_routes_to_sync(self):
        result = self.route("kalender oppdater fra google")
        self.assertEqual(result.intent, BotIntent.CALENDAR_SYNC)
        self.assertEqual(result.reason, "calendar_sync_keyword")

    def test_calendar_synkroniser_routes_to_sync(self):
        result = self.route("kalender synkroniser")
        self.assertEqual(result.intent, BotIntent.CALENDAR_SYNC)
        self.assertEqual(result.reason, "calendar_sync_keyword")

    def test_calendar_clear_phrases_win_over_delete(self):
        self.assertEqual(self.route("kalender slett alt").intent, BotIntent.CALENDAR_CLEAR)
        self.assertEqual(self.route("kalender fjern alt").intent, BotIntent.CALENDAR_CLEAR)

    def test_calendar_clear_accepts_bounded_possessive_natural_phrases(self):
        for text in (
            "Kan du tømme kalenderen min?",
            "Kan du tømme heile kalenderen min?",
            "Could you clear my calendar?",
        ):
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.CALENDAR_CLEAR)
                self.assertEqual(
                    result.payload,
                    {"calendar_target": {"all": True}},
                )
                self.assertTrue(result.requires_confirmation)

    def test_calendar_clear_possessive_forms_keep_destructive_gate_bounded(self):
        for text in (
            "Kan du vise kalenderen min?",
            "Kan du forklare hvordan jeg tømmer kalenderen min?",
            "Ikke tøm kalenderen min",
            "Could you clear my calendar filters?",
            "Kalenderen min er tom",
        ):
            with self.subTest(text=text):
                self.assertIsNot(
                    self.route(text).intent,
                    BotIntent.CALENDAR_CLEAR,
                )

    def test_calendar_delete_still_handles_item_deletion(self):
        self.assertEqual(self.route("kalender slett 2").intent, BotIntent.CALENDAR_DELETE)
        self.assertEqual(self.route("kalender slette 2").intent, BotIntent.CALENDAR_DELETE)
        self.assertEqual(self.route("kalender fjerne 2").intent, BotIntent.CALENDAR_DELETE)

    def test_calendar_delete_handles_leading_calendar_context_and_title(self):
        result = self.route("kalender fjern meldekort")
        self.assertEqual(result.intent, BotIntent.CALENDAR_DELETE)

    def test_calendar_delete_handles_bare_title_when_calendar_item_matches(self):
        result = self.route(
            "slett meldekort",
            calendar_titles=["Send inn meldekort (Uke 25 - 26)"],
        )
        self.assertEqual(result.intent, BotIntent.CALENDAR_DELETE)
        self.assertEqual(result.reason, "calendar_delete_title_match")

    def test_bare_delete_without_calendar_match_stays_ai_chat(self):
        result = self.route("slett prosjektet", calendar_titles=["Send inn meldekort"])
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_calendar_delete_understands_definite_calendar_form(self):
        prompts = [
            'Slett alle "Send inn meldekort" i kalenderen',
            "kalenderen slett meldekort",
            "fjern meldekort fra kalenderen",
            "vennligst slett meldekort fra kalenderen",
            "kan du slette meldekort fra kalenderen",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(self.route(prompt).intent, BotIntent.CALENDAR_DELETE)

    def test_calendar_edit_variants_and_aliases_route(self):
        self.assertEqual(self.route("kalender rediger 1 tittel: Ny").intent, BotIntent.CALENDAR_EDIT)
        self.assertEqual(self.route("kalender oppdatere 1 tittel: Ny").intent, BotIntent.CALENDAR_EDIT)
        self.assertEqual(self.route("arrangementer").intent, BotIntent.CALENDAR_LIST)
        self.assertEqual(self.route("events").intent, BotIntent.CALENDAR_LIST)

    def test_bare_numeric_delete_routes_to_calendar_delete(self):
        self.assertEqual(self.route("slett 2").intent, BotIntent.CALENDAR_DELETE)

    def test_reserved_delete_targets_keep_their_own_domains(self):
        self.assertEqual(self.route("slett poll 2", active_polls=True).intent, BotIntent.POLL_DELETE)
        self.assertEqual(self.route("slett sitat 1").intent, BotIntent.QUOTE_DELETE)

    def test_incomplete_reminder_edit_falls_back(self):
        result = self.route("endre påminnelse")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)
        self.assertEqual(result.payload, {})

    def test_bare_search_routes_to_web_search(self):
        result = self.route("søk møte")
        self.assertEqual(result.intent, BotIntent.SEARCH)
        self.assertEqual(result.payload["search"]["query"], "møte")

    def test_explicit_calendar_search_routes_to_local_calendar_search(self):
        result = self.route("søk kalender møte")
        self.assertEqual(result.intent, BotIntent.CALENDAR_SEARCH)
        self.assertEqual(result.payload["query"], "møte")

    def test_reminder_search_routes_to_local_reminder_search(self):
        result = self.route("søk påminnelse lege")
        self.assertEqual(result.intent, BotIntent.REMINDER_SEARCH)
        self.assertEqual(
            result.payload,
            {"reminder": {"action": "search", "query": "lege"}},
        )

    def test_reminder_create_list_and_complete_route_to_reminders(self):
        self.assertEqual(self.route("påminnelse Ring lege om 2 timer").intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(self.route("påminnelser").intent, BotIntent.REMINDER_LIST)
        self.assertEqual(self.route("reminders").intent, BotIntent.REMINDER_LIST)
        self.assertEqual(self.route("ferdig 1", active_reminders=True).intent, BotIntent.REMINDER_COMPLETE)

    def test_bare_calendar_complete_title_is_not_stolen_by_reminders(self):
        result = self.route(
            "ferdig meldekort uke 25",
            calendar_titles=["Send inn meldekort uke 25"],
            active_reminders=True,
        )

        self.assertEqual(result.intent, BotIntent.CALENDAR_COMPLETE)

    def test_quoted_reminder_complete_does_not_route(self):
        result = self.route('hva skjer hvis jeg skriver "ferdig påminnelse 1"?', active_reminders=True)

        self.assertNotEqual(result.intent, BotIntent.REMINDER_COMPLETE)

    def test_generic_calendar_context_words_do_not_hijack_phrases(self):
        self.assertNotEqual(self.route("kommende filmer").intent, BotIntent.CALENDAR_LIST)
        self.assertNotEqual(self.route("planlagt vedlikehold").intent, BotIntent.CALENDAR_LIST)
        self.assertNotEqual(self.route("events in Trondheim").intent, BotIntent.CALENDAR_LIST)

    def test_web_search_phrase_does_not_route_to_calendar_search(self):
        result = self.route("søk på nett Trondheim konserter")
        self.assertEqual(result.intent, BotIntent.SEARCH)
        self.assertEqual(result.payload["search"]["query"], "Trondheim konserter")

    def test_memory_view_routes_strictly(self):
        result = self.route("vis minnet mitt")
        self.assertEqual(result.intent, BotIntent.MEMORY_VIEW)
        self.assertEqual(result.payload["memory"]["action"], "view")

    def test_natural_local_state_questions_use_local_read_intents(self):
        cases = {
            "Hva vet du om meg?": BotIntent.MEMORY_VIEW,
            "Kva veit du om meg?": BotIntent.MEMORY_VIEW,
            "Hva vet du om kalenderen min?": BotIntent.CALENDAR_LIST,
            "Fortell meg om påminnelsene mine": BotIntent.REMINDER_LIST,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, expected)

    def test_memory_export_routes_strictly(self):
        result = self.route("eksporter minnet mitt")
        self.assertEqual(result.intent, BotIntent.MEMORY_EXPORT)
        self.assertEqual(result.payload["memory"]["action"], "export")

    def test_memory_delete_prose_confirmation_never_becomes_authorization(self):
        result = self.route("slett minnet mitt bekreft")
        self.assertEqual(result.intent, BotIntent.MEMORY_DELETE)
        self.assertEqual(result.payload, {"memory": {"action": "delete"}})
        self.assertTrue(result.requires_confirmation)

    def test_quoted_memory_delete_confirmation_does_not_route(self):
        result = self.route('hva skjer hvis jeg skriver "slett minnet mitt bekreft"?')
        self.assertNotEqual(result.intent, BotIntent.MEMORY_DELETE)

    def test_quote_list_routes_to_quote_list(self):
        result = self.route("liste sitater")
        self.assertEqual(result.intent, BotIntent.QUOTE_LIST)

    def test_birthday_edit_requires_resolved_identity_before_execution(self):
        result = self.route("endre bursdag")
        self.assertEqual(result.intent, BotIntent.CLARIFY)
        self.assertEqual(result.payload, {})
        self.assertEqual(result.reason, "birthday_identity_required")

    def test_natural_birthday_list_is_a_typed_local_read(self):
        for text in ("vis bursdager", "bursdagar", "show birthdays"):
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.BIRTHDAY_LIST)
                self.assertEqual(
                    result.payload,
                    {"birthday": {"action": "list", "scope": "all"}},
                )

    def test_birthday_edit_is_anchored_to_a_direct_frame(self):
        for text in (
            "Kan du endre bursdag?",
            "Please edit birthday",
            "endre bursdag Ola Nordmann 02.03.1991",
            "Kan du endre bursdag Ola Nordmann 02.03.1991?",
            "Please edit birthday Ola Nordmann 02.03.1991",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(text).intent,
                    BotIntent.CLARIFY,
                )
        for text in (
            "jeg lurer på hvordan man kan endre bursdag",
            "ordene endre bursdag står i teksten",
            "ordene endre bursdag Ola Nordmann 02.03.1991 står i teksten",
            "editing a birthday is complicated",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_birthday_edit_candidate_specificity_tracks_target(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)

        def collect(text):
            utterance = normalize_utterance(text)
            context = CollectorContext(
                utterance,
                analyze_utterance(utterance),
                None,
                123,
                None,
                None,
                NOW,
            )
            return [
                candidate
                for candidate in router._collect_calendar_reminder_candidates(
                    context
                ).candidates
                if candidate.reason == "birthday_identity_required"
            ]

        targetless = collect("endre bursdag")
        targetful = collect("endre bursdag Ola Nordmann 02.03.1991")

        self.assertEqual(len(targetless), 1)
        self.assertEqual(targetless[0].specificity, 2)
        self.assertEqual(len(targetful), 1)
        self.assertEqual(targetful[0].specificity, 3)

    def test_incomplete_watchlist_remove_falls_back(self):
        result = self.route("fjern watchlist")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)
        self.assertEqual(result.payload, {})

    def test_complete_calendar_edit_alias_keeps_canonical_payload(self):
        result = self.route("kalender oppdatere 1 tittel: Ny")
        self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
        self.assertEqual(
            result.payload,
            {
                "calendar_edit": {
                    "target": "1",
                    "changes": {"title": "Ny"},
                }
            },
        )

    def test_bare_display_number_is_bounded_calendar_target_evidence(self):
        result = self.route("slett 2")
        self.assertEqual(result.intent, BotIntent.CALENDAR_DELETE)
        self.assertEqual(
            result.payload, {"calendar_target": {"number": 2}}
        )
        self.assertIs(result.risk, IntentRisk.DESTRUCTIVE)
        self.assertTrue(result.requires_confirmation)

    def test_natural_calendar_edit_payload_is_complete(self):
        result = self.route(
            "Kan du endre møte med Ola til fredag kl 10?",
            calendar_titles=["Møte med Ola"],
        )
        self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
        self.assertEqual(
            result.payload,
            {
                "calendar_edit": {
                    "target": "møte med Ola",
                    "changes": {
                        "date": "17.07.2026",
                        "time": "10:00",
                    },
                }
            },
        )

    def test_natural_calendar_edit_rejects_partial_or_hedged_time_text(self):
        for text in (
            "Flytt møtet med Ola til fredag etter lunsj",
            "Flytt møtet med Ola til fredag en gang på dagen",
            "Flytt møtet med Ola til kanskje fredag",
            "Flytt møtet med Ola til fredag hvis det passer",
            "Move the meeting with Ola to Friday after lunch",
            "Move the meeting with Ola to maybe Friday",
        ):
            with self.subTest(text=text):
                result = self.route(
                    text,
                    calendar_titles=["Møte med Ola"],
                )
                self.assertNotEqual(result.intent, BotIntent.CALENDAR_EDIT)
                self.assertEqual(result.payload, {})

    def test_natural_calendar_edit_can_explicitly_preserve_time(self):
        cases = (
            "Flytt møtet med Ola til fredag, men ikke endre tidspunktet",
            "Flytt møtet med Ola til fredag, men ikkje endre tidspunktet",
            "Move the meeting with Ola to Friday but do not change the time",
        )
        for text in cases:
            with self.subTest(text=text):
                result = self.route(
                    text,
                    calendar_titles=["Møte med Ola"],
                )
                self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
                self.assertEqual(
                    result.payload["calendar_edit"]["changes"],
                    {"date": "17.07.2026"},
                )

    def test_natural_calendar_edit_uses_rightmost_unquoted_temporal_split(self):
        cases = (
            (
                "Kan du endre møte Fra Oslo til Bergen til fredag kl 10?",
                "møte Fra Oslo til Bergen",
            ),
            (
                'Kan du endre møte "Fra Oslo til Bergen" til fredag kl 10?',
                'møte "Fra Oslo til Bergen"',
            ),
            (
                "Would you change meeting From Here to Eternity to Friday at 10?",
                "meeting From Here to Eternity",
            ),
        )
        for text, expected_target in cases:
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
                self.assertEqual(
                    result.payload["calendar_edit"]["target"],
                    expected_target,
                )
                self.assertEqual(
                    result.payload["calendar_edit"]["changes"],
                    {"date": "17.07.2026", "time": "10:00"},
                )

    def test_natural_reminder_payload_is_complete(self):
        result = self.route("Påminn meg om å ringe legen i morgen")
        self.assertEqual(result.intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(
            result.payload,
            {
                "reminder": {
                    "action": "add",
                    "text": "ringe legen",
                    "due_date": "15.07.2026",
                    "time": "09:00",
                    "due_at": "2026-07-15T09:00:00+02:00",
                    "timezone": "Europe/Oslo",
                }
            },
        )

    def test_pure_route_wrapper_matches_normalized_entry(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        self.assertEqual(
            router.route("hjelp", 123),
            router.route_utterance(
                normalize_utterance("hjelp"), guild_id=123
            ),
        )

    def test_routing_context_scalar_mismatches_fail_bounded(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        routing = RoutingContext(
            ConversationKey(123, 456, 7),
            ResolvedMention(7, "Kari"),
        )
        for kwargs in (
            {"guild_id": 999},
            {"channel_id": 999},
            {"user_id": 999},
        ):
            with self.subTest(kwargs=kwargs):
                routed = router.evaluate_utterance(
                    normalize_utterance("hjelp"),
                    routing_context=routing,
                    **kwargs,
                )
                self.assertEqual(routed.result.intent, BotIntent.AI_CHAT)
                self.assertEqual(routed.result.reason, "invalid_context")
                self.assertEqual(
                    routed.diagnostics.rejection_counts,
                    {RejectionCode.INVALID_CONTEXT: 1},
                )

    def test_message_context_extracts_dm_identity_and_target_mentions(self):
        bot = SimpleNamespace(
            id=99,
            display_name="Inebotten",
            name="inebotten",
        )
        target = SimpleNamespace(
            id=8,
            display_name="Ola",
            name="ola",
        )
        author = SimpleNamespace(
            id=7,
            display_name="Kari",
            name="kari",
        )
        message = SimpleNamespace(
            guild=None,
            channel=SimpleNamespace(id=456),
            author=author,
            mentions=(bot, target, target),
        )

        key = conversation_key_from_message(message)
        routing = routing_context_from_message(
            message,
            bot_user_id=99,
        )

        self.assertEqual(key, ConversationKey(None, 456, 7))
        self.assertEqual(domain_scope_id(key), 456)
        self.assertEqual(routing.key, key)
        self.assertEqual(routing.author, ResolvedMention(7, "Kari"))
        self.assertEqual(
            routing.mentions,
            (ResolvedMention(8, "Ola"),),
        )

    def test_message_context_uses_guild_scope_without_losing_channel(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, display_name=None, name="Kari"),
            mentions=(),
        )

        routing = routing_context_from_message(message)

        self.assertEqual(
            routing.key,
            ConversationKey(123, 456, 7),
        )
        self.assertEqual(domain_scope_id(routing.key), 123)
        self.assertEqual(routing.author, ResolvedMention(7, "Kari"))

    def test_dm_routing_keeps_identity_none_and_domain_scope_channel(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        seen = []

        def capture(context):
            seen.append(
                (
                    context.guild_id,
                    context.channel_id,
                    context.domain_scope_id,
                )
            )
            return CollectorOutput()

        for name in COLLECTOR_ORDER:
            setattr(router, name, capture)
        routing = RoutingContext(
            ConversationKey(None, 456, 7),
            ResolvedMention(7, "Kari"),
        )

        router.evaluate_utterance(
            normalize_utterance("hei"),
            routing_context=routing,
        )

        self.assertEqual(
            seen,
            [(None, 456, 456)] * len(COLLECTOR_ORDER),
        )

    def test_dm_domain_state_reads_use_bare_channel_scope(self):
        monitor = DummyMonitor()
        reminder_scopes = []
        poll_scopes = []
        calendar_scopes = []
        monitor.reminders.get_active_reminders = lambda scope_id: (
            reminder_scopes.append(scope_id) or [{"id": "rem1"}]
        )
        monitor.poll.get_active_polls = (
            lambda scope_id, reference_time=None: (
                poll_scopes.append(scope_id) or [{"id": "poll1"}]
            )
        )
        monitor.calendar.get_upcoming = (
            lambda scope_id, days=365, reference_time=None: (
                calendar_scopes.append(scope_id)
                or [{"title": "Styremøte"}]
            )
        )
        router = IntentRouter(monitor, now_provider=lambda: NOW)
        routing = RoutingContext(
            ConversationKey(None, 456, 7),
            ResolvedMention(7, "Kari"),
        )

        active_poll_reader = monitor.poll.get_active_polls
        monitor.poll.get_active_polls = (
            lambda scope_id, reference_time=None: (
                poll_scopes.append(scope_id) or []
            )
        )
        reminder = router.route("1", routing_context=routing)
        monitor.poll.get_active_polls = active_poll_reader
        poll = router.route("vis poll", routing_context=routing)
        calendar = router.route(
            "slett Styremøte",
            routing_context=routing,
        )

        self.assertEqual(reminder.intent, BotIntent.REMINDER_COMPLETE)
        self.assertEqual(poll.intent, BotIntent.POLL_LIST)
        self.assertEqual(calendar.intent, BotIntent.CALENDAR_DELETE)
        self.assertTrue(reminder_scopes)
        self.assertTrue(poll_scopes)
        self.assertTrue(calendar_scopes)
        self.assertEqual(set(reminder_scopes), {456})
        self.assertEqual(set(poll_scopes), {456})
        self.assertEqual(set(calendar_scopes), {456})

    def test_invalid_dm_scalar_context_does_not_read_domain_state(self):
        monitor = DummyMonitor()
        monitor.reminders.get_active_reminders = Mock(
            side_effect=AssertionError("must not read")
        )
        monitor.poll.get_active_polls = Mock(
            side_effect=AssertionError("must not read")
        )
        monitor.calendar.get_upcoming = Mock(
            side_effect=AssertionError("must not read")
        )
        routing = RoutingContext(
            ConversationKey(None, 456, 7),
            ResolvedMention(7, "Kari"),
        )

        routed = IntentRouter(
            monitor,
            now_provider=lambda: NOW,
        ).evaluate_utterance(
            normalize_utterance("ferdig 1"),
            guild_id=999,
            routing_context=routing,
        )

        self.assertEqual(routed.result.intent, BotIntent.AI_CHAT)
        self.assertEqual(routed.result.reason, "invalid_context")
        monitor.reminders.get_active_reminders.assert_not_called()
        monitor.poll.get_active_polls.assert_not_called()
        monitor.calendar.get_upcoming.assert_not_called()

    def test_supplied_scalar_identity_survives_only_on_collector_context(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        seen = []

        def capture(context):
            seen.append(
                (context.guild_id, context.channel_id, context.user_id)
            )
            return CollectorOutput()

        for name in COLLECTOR_ORDER:
            setattr(router, name, capture)
        routed = router.evaluate_utterance(
            normalize_utterance("hei"),
            guild_id=123,
            channel_id=456,
            user_id=7,
        )
        self.assertEqual(seen, [(123, 456, 7)] * len(COLLECTOR_ORDER))
        self.assertNotIn("123", repr(routed))
        self.assertNotIn("456", repr(routed))

    def test_routing_context_derives_all_three_scalar_ids(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        seen = []

        def capture(context):
            seen.append(
                (context.guild_id, context.channel_id, context.user_id)
            )
            return CollectorOutput()

        for name in COLLECTOR_ORDER:
            setattr(router, name, capture)
        routing = RoutingContext(
            ConversationKey(123, 456, 7),
            ResolvedMention(7, "Kari"),
        )
        router.evaluate_utterance(
            normalize_utterance("hei"), routing_context=routing
        )
        self.assertEqual(seen, [(123, 456, 7)] * len(COLLECTOR_ORDER))

    def test_route_captures_injected_clock_exactly_once(self):
        calls = []
        before_midnight = datetime(
            2026, 7, 14, 23, 59, tzinfo=OSLO
        )
        after_midnight = datetime(
            2026, 7, 15, 0, 1, tzinfo=OSLO
        )

        def clock():
            value = before_midnight if not calls else after_midnight
            calls.append(value)
            return value

        result = IntentRouter(DummyMonitor(), now_provider=clock).route(
            "påminn meg om å ringe legen i morgen", guild_id=123
        )
        self.assertEqual(result.intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(calls, [before_midnight])
        self.assertEqual(
            result.payload["reminder"]["due_at"],
            "2026-07-15T09:00:00+02:00",
        )

    def test_supplied_reference_time_never_reads_now_provider(self):
        def unexpected_clock_read():
            raise AssertionError("now_provider_was_read")

        result = IntentRouter(
            DummyMonitor(), now_provider=unexpected_clock_read
        ).route(
            "påminn meg om å ringe legen i morgen",
            guild_id=123,
            reference_time=NOW,
        )
        self.assertEqual(result.intent, BotIntent.REMINDER_CREATE)
        self.assertEqual(
            result.payload["reminder"]["due_at"],
            "2026-07-15T09:00:00+02:00",
        )

    def test_reminder_parser_exception_is_bounded_one_for_one(self):
        monitor = DummyMonitor()

        def explode(_text, **_kwargs):
            raise RuntimeError("SECRET_REMINDER_TOKEN")

        monitor.parse_reminder_command = explode
        metrics = NLUMetrics()
        router = IntentRouter(
            monitor, metrics=metrics, now_provider=lambda: NOW
        )
        routed = router.evaluate_utterance(
            normalize_utterance(
                "påminn meg om å ringe legen i morgen"
            ),
            guild_id=123,
        )
        self.assertEqual(
            routed.diagnostics.parser_errors,
            ("parse_reminder_command",),
        )
        self.assertEqual(
            routed.diagnostics.rejection_counts,
            {RejectionCode.PARSER_ERROR: 1},
        )
        self.assertEqual(
            metrics.snapshot()["parser_errors"],
            {"parser=reminder|code=exception": 1},
        )
        self.assertNotIn("SECRET_REMINDER_TOKEN", repr(routed))
        self.assertNotIn("RuntimeError", repr(routed))

    def test_invalid_calendar_temporal_is_diagnostic_only(self):
        metrics = NLUMetrics()
        routed = IntentRouter(
            DummyMonitor(), metrics=metrics, now_provider=lambda: NOW
        ).evaluate_utterance(
            normalize_utterance("møte 31.02.2026 kl 14"),
            guild_id=123,
        )
        self.assertEqual(routed.result.intent, BotIntent.AI_CHAT)
        self.assertEqual(routed.result.payload, {})
        self.assertEqual(
            routed.diagnostics.rejection_counts,
            {RejectionCode.INVALID_TEMPORAL: 1},
        )
        self.assertEqual(
            metrics.snapshot()["parser_errors"],
            {"parser=calendar|code=invalid_temporal": 1},
        )

    def test_quote_parser_exception_is_bounded_one_for_one(self):
        monitor = DummyMonitor()

        def explode(_text):
            raise RuntimeError("SECRET_TOKEN")

        monitor.parse_quote_command = explode
        metrics = NLUMetrics()
        router = IntentRouter(
            monitor, metrics=metrics, now_provider=lambda: NOW
        )
        utterance = normalize_utterance("sitat")
        routed = router.evaluate_utterance(utterance, guild_id=123)
        self.assertEqual(
            routed.diagnostics.parser_errors,
            ("parse_quote_command",),
        )
        self.assertEqual(
            routed.diagnostics.rejection_counts,
            {RejectionCode.PARSER_ERROR: 1},
        )
        self.assertEqual(
            metrics.snapshot()["parser_errors"],
            {"parser=quote|code=exception": 1},
        )
        context = CollectorContext(
            utterance,
            analyze_utterance(utterance),
            None,
            123,
            None,
            None,
            NOW,
        )
        output = router._collect_poll_watchlist_quote_candidates(context)
        diagnostics = [
            rejection
            for rejection in output.rejections
            if rejection.code is RejectionCode.PARSER_ERROR
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].candidate.payload, {})
        self.assertEqual(
            diagnostics[0].candidate.reason,
            "parser_error_diagnostic",
        )
        self.assertFalse(
            any(
                candidate.reason == "parser_error_diagnostic"
                for candidate in output.candidates
            )
        )
        self.assertNotIn("SECRET_TOKEN", repr(routed))
        self.assertNotIn("RuntimeError", repr(routed))

    def test_safe_parse_rejects_metric_family_mismatch(self):
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        with self.assertRaisesRegex(
            ValueError, "invalid_parser_metric_family"
        ):
            router._safe_parse(
                [], [], "parse_quote_command", "calendar", lambda: None
            )

    def test_read_command_examples_are_inert_in_all_masking_forms(self):
        for inner in (
            "vis watchlist",
            "sitat",
            "hvor lenge til jul",
            "dagens ord",
            "nordlys",
            "skoleferie",
        ):
            for text in (
                f'"{inner}"',
                f"`{inner}`",
                f"```text\n{inner}\n```",
            ):
                with self.subTest(text=text):
                    self.assertEqual(
                        self.route(text).intent, BotIntent.AI_CHAT
                    )
        for text in ('"polls"', "`polls`", "```text\npolls\n```"):
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(text, active_polls=True).intent,
                    BotIntent.AI_CHAT,
                )

    def test_write_examples_are_inert_when_quoted_or_code_only(self):
        for text in (
            '`møte i morgen kl 14`',
            "```text\nslett kalenderen\n```",
            '"sett bosted Oslo"',
        ):
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.AI_CHAT)
                self.assertEqual(result.payload, {})

    def test_live_quote_save_keeps_quoted_target_case(self):
        result = self.route('lagre sitat "Carpe Diem"')
        self.assertEqual(result.intent, BotIntent.QUOTE)
        self.assertEqual(result.payload["quote"]["action"], "save")
        self.assertEqual(result.payload["quote"]["text"], "Carpe Diem")

    def test_quote_save_removes_only_the_leading_live_frame(self):
        cases = {
            'lagre sitat "Lagre dette, ikke slett sitatet"': (
                "Lagre dette, ikke slett sitatet",
                "no",
            ),
            "save this: Please save this quote for later": (
                "Please save this quote for later",
                "en",
            ),
            "husk dette: husk dette øyeblikket": (
                "husk dette øyeblikket",
                "no",
            ),
        }
        for text, (expected_payload, expected_lang) in cases.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.QUOTE)
                self.assertEqual(
                    result.payload["quote"]["text"], expected_payload
                )
                self.assertEqual(
                    result.payload["quote"]["lang"], expected_lang
                )

    def test_resolved_quoted_calendar_target_is_safe_data(self):
        result = self.route(
            'slett møte "Møte med Ola"',
            calendar_titles=["Møte med Ola"],
        )
        self.assertEqual(result.intent, BotIntent.CALENDAR_DELETE)
        self.assertEqual(
            result.payload,
            {"calendar_target": {"target": "Møte med Ola"}},
        )
        self.assertTrue(result.requires_confirmation)
        for text in (
            'jeg skrev "slett møte Møte med Ola"',
            'hva betyr "slett møte Møte med Ola"?',
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(
                        text, calendar_titles=["Møte med Ola"]
                    ).intent,
                    BotIntent.AI_CHAT,
                )

    def test_complete_watchlist_routes_and_generic_frames(self):
        positives = {
            "husk å se Arrival": ("add", "Arrival"),
            "hugs å sjå Arrival": ("add", "Arrival"),
            "remember to watch The Bear": ("add", "The Bear"),
            "add The Bear to watchlist": ("add", "The Bear"),
            "fjern film 2": ("remove", None),
            "remove show 2": ("remove", None),
        }
        for text, (action, title) in positives.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.WATCHLIST)
                self.assertEqual(result.payload["watchlist"]["action"], action)
                if title:
                    self.assertEqual(
                        result.payload["watchlist"]["title"], title
                    )
        for text in (
            "fjern på watchlist",
            "endre i watchlist",
            "remove 2",
            "edit 2 to The Matrix",
            '"husk å se Arrival"',
            "ikke husk å se Arrival",
            "jeg husket å se Arrival i går",
            "jeg fjernet film 2 i går",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_norwegian_definite_watchlist_types_preserve_title_and_type(self):
        cases = {
            "legg til filmen Operation Cancel": ("Operation Cancel", "movie"),
            "legg til serien This Is Us": ("This Is Us", "series"),
        }
        for text, (title, item_type) in cases.items():
            with self.subTest(text=text):
                parsed = parse_watchlist_command(text)
                self.assertEqual(parsed["title"], title)
                self.assertEqual(parsed["type"], item_type)
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.WATCHLIST)
                self.assertEqual(result.payload["watchlist"]["title"], title)
                self.assertEqual(
                    result.payload["watchlist"]["type"], item_type
                )

    def test_reminder_ids_require_manager_shape_or_explicit_id_prefix(self):
        positives = {
            "slett påminnelse rem_123_abcdef": BotIntent.REMINDER_DELETE,
            "slett påminnelse id custom_1": BotIntent.REMINDER_DELETE,
            "endre påminnelse rem_123_abcdef tekst: Ring": BotIntent.REMINDER_EDIT,
            "endre påminnelse id custom_1 tekst: Ring": BotIntent.REMINDER_EDIT,
        }
        for text, intent in positives.items():
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, intent)
        for text in (
            "slett påminnelse tomorrow",
            "slett påminnelse fredag",
            "endre påminnelse tomorrow tekst: Ring",
            "endre påminnelse fredag tekst: Ring",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_dashboard_conversation_scope_prefers_exact_channel_id(self):
        monitor = DummyMonitor()
        seen = []

        def should_show_dashboard(content, conversation_id):
            seen.append(conversation_id)
            return True, "explicit_request"

        monitor.conversation.should_show_dashboard = should_show_dashboard
        router = IntentRouter(monitor, now_provider=lambda: NOW)

        channel_result = router.route(
            "vis dashboard",
            guild_id=123,
            channel_id=456,
        )
        legacy_result = router.route("vis dashboard", guild_id=123)

        self.assertEqual(channel_result.intent, BotIntent.DASHBOARD)
        self.assertEqual(legacy_result.intent, BotIntent.DASHBOARD)
        self.assertEqual(seen, [456, 123])

    def test_numeric_calendar_delete_boundaries_fail_closed(self):
        for text in (
            '"slett 2"',
            "ikke slett 2",
            "slett 0",
            "slett -1",
            "slett 2x",
        ):
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.AI_CHAT)
                self.assertEqual(result.payload, {})

    def test_collectors_never_call_mutation_methods(self):
        monitor = DummyMonitor(
            active_polls=True,
            calendar_titles=["Møte med Ola"],
            active_reminders=True,
        )

        def mutation_called(*_args, **_kwargs):
            raise AssertionError("collector_mutated_state")

        monitor.calendar.add_item = mutation_called
        monitor.calendar.edit_item = mutation_called
        monitor.calendar.delete_item = mutation_called
        monitor.reminders.add_reminder = mutation_called
        monitor.reminders.edit_reminder = mutation_called
        monitor.poll.create_poll = mutation_called
        monitor.poll.delete_poll = mutation_called
        router = IntentRouter(monitor, now_provider=lambda: NOW)
        for text in (
            "hjelp",
            "påminn meg om å ringe legen i morgen",
            "slett møte Møte med Ola",
            "avstemning Pizza? Ja eller Nei",
            "hugs å sjå Arrival",
            "forkort https://example.com/a/b",
        ):
            with self.subTest(text=text):
                router.evaluate_utterance(
                    normalize_utterance(text), guild_id=123
                )

    def test_exact_memory_forget_frame_is_preserved_but_requires_capability(self):
        for text in ("glem meg", "glem meg bekreft"):
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.MEMORY_DELETE)
                self.assertEqual(
                    result.payload,
                    {"memory": {"action": "delete"}},
                )
                self.assertTrue(result.requires_confirmation)
        for text in (
            '"glem meg"',
            "ikke glem meg",
            "jeg skrev glem meg",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_router_resolver_compatibility_smoke(self):
        raw = self.route("møte 20.07.2026 13:30")
        noon = self.route("møte 20.07.2026 noon")
        self.assertEqual(raw.payload["calendar_item"]["time"], "13:30")
        self.assertEqual(noon.payload["calendar_item"]["time"], "12:00")
        for alias, offset in DATE_ALIASES.items():
            with self.subTest(alias=alias):
                result = self.route(f"møte {alias} kl 14")
                self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
                self.assertEqual(
                    result.payload["calendar_item"]["date"],
                    (NOW.date() + timedelta(days=offset)).strftime(
                        "%d.%m.%Y"
                    ),
                )

    def test_labeled_watchlist_edit_keeps_complete_typed_fields(self):
        result = self.route(
            "endre watchlist 2 tittel: The Matrix type: film "
            "sjanger: sci-fi kommentar: klassiker"
        )
        self.assertEqual(result.intent, BotIntent.WATCHLIST)
        self.assertEqual(
            result.payload["watchlist"],
            {
                "action": "edit",
                "index": 2,
                "title": "The Matrix",
                "type": "movie",
                "genre": "sci-fi",
                "comment": "klassiker",
                "lang": "no",
            },
        )

    def test_calendar_clear_never_absorbs_masked_target_data(self):
        titles = ["Møte med Ola"]
        positives = (
            'slett kalender "Møte med Ola"',
            "slett kalender «Møte med Ola»",
            'kalender slett "Møte med Ola"',
            'slett møte "Møte med Ola"',
            'slett avtale "Møte med Ola"',
            'slett påminnelse "Møte med Ola"',
            'slett reminder "Møte med Ola"',
            'slett event "Møte med Ola"',
            "fullfør event «Møte med Ola»",
        )
        for text in positives:
            with self.subTest(text=text):
                result = self.route(text, calendar_titles=titles)
                expected = (
                    BotIntent.CALENDAR_COMPLETE
                    if text.startswith("fullfør")
                    else BotIntent.CALENDAR_DELETE
                )
                self.assertEqual(result.intent, expected)
                self.assertEqual(
                    result.payload,
                    {"calendar_target": {"target": "Møte med Ola"}},
                )
                self.assertNotEqual(result.intent, BotIntent.CALENDAR_CLEAR)

        for text, available in (
            ('slett kalender "Møte med Ola"', titles * 2),
            ("slett kalender `Møte med Ola`", titles),
            ("slett kalender ```text\nMøte med Ola\n```", titles),
            ('slett kalender "Ukjent møte"', titles),
            ('slett arrangement "Møte med Ola"', titles),
            ('slett meeting "Møte med Ola"', titles),
        ):
            with self.subTest(text=text):
                result = self.route(text, calendar_titles=available)
                self.assertEqual(result.intent, BotIntent.AI_CHAT)
                self.assertNotEqual(result.intent, BotIntent.CALENDAR_CLEAR)

        self.assertEqual(
            self.route("slett kalender").intent,
            BotIntent.CALENDAR_CLEAR,
        )

    def test_calendar_title_match_evidence_distinguishes_data_from_control(self):
        monitor = DummyMonitor(calendar_titles=["Møte med Ola"])
        router = IntentRouter(monitor, now_provider=lambda: NOW)

        def collect(text):
            utterance = normalize_utterance(text)
            context = CollectorContext(
                utterance,
                analyze_utterance(utterance),
                None,
                123,
                None,
                None,
                NOW,
            )
            return [
                candidate
                for candidate in router._collect_calendar_reminder_candidates(
                    context
                ).candidates
                if candidate.reason == "calendar_delete_title_match"
            ]

        unquoted = collect("slett Møte med Ola")
        quoted = collect('slett møte "Møte med Ola"')
        self.assertEqual(unquoted[0].domain_terms, ("Møte med Ola",))
        self.assertEqual(quoted[0].domain_terms, ("møte",))

    def test_action_specific_parser_gates_ignore_inert_write_examples(self):
        poll_examples = (
            'vis poll "avstemning Pizza? Ja eller Nei"',
            "vis poll `avstemning Pizza? Ja eller Nei`",
            "vis poll ```text\navstemning Pizza? Ja eller Nei\n```",
            "vis poll ```\navstemning Pizza? Ja eller Nei\n```",
        )
        for text in poll_examples:
            with self.subTest(text=text):
                result = self.route(text, active_polls=True)
                self.assertNotEqual(result.intent, BotIntent.POLL_CREATE)

        quote_examples = (
            'vis sitat "lagre dette"',
            "vis sitat `lagre dette`",
            "vis sitat ```text\nlagre dette\n```",
            "vis sitat ```\nlagre dette\n```",
        )
        for text in quote_examples:
            with self.subTest(text=text):
                result = self.route(text)
                self.assertFalse(
                    result.intent is BotIntent.QUOTE
                    and result.payload.get("quote", {}).get("action")
                    == "save"
                )

    def test_poll_list_aliases_never_become_create_from_slash_data(self):
        cases = (
            'vis poll "Question / A / B"',
            "poll list `Question / A / B`",
            "avstemning liste ```text\nQuestion / A / B\n```",
        )
        for active_polls in (False, True):
            for text in cases:
                with self.subTest(active_polls=active_polls, text=text):
                    monitor = DummyMonitor(active_polls=active_polls)
                    monitor.parse_poll_command = lambda _text: {
                        "question": "Question",
                        "options": ["A", "B"],
                    }
                    result = self.route(text, monitor=monitor)
                    self.assertNotEqual(result.intent, BotIntent.POLL_CREATE)
                    self.assertEqual(result.intent, BotIntent.POLL_LIST)

    def test_anchored_control_frames_preserve_direct_commands(self):
        cases = {
            "spiller Elden Ring": BotIntent.PROFILE,
            "watching The Bear": BotIntent.PROFILE,
            "kalender synkroniser": BotIntent.CALENDAR_SYNC,
            "kalender auth AbC_12": BotIntent.CALENDAR_AUTH,
            "kalenderkode AbC_12": BotIntent.CALENDAR_AUTH,
            "sett min lokasjon til Oslo": BotIntent.SET_LOCATION,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, expected)
        auth = self.route("kalender auth AbC_12")
        self.assertEqual(auth.payload["auth_code"], "AbC_12")
        self.assertTrue(auth.requires_confirmation)
        compact_auth = self.route("kalenderkode AbC_12")
        self.assertEqual(compact_auth.payload["auth_code"], "AbC_12")
        self.assertTrue(compact_auth.requires_confirmation)
        auth_start = self.route("kalender auth")
        self.assertEqual(auth_start.payload, {})
        self.assertTrue(auth_start.requires_confirmation)

    def test_calendar_auth_rejects_cancellation_vocabulary_as_codes(self):
        for text in (
            "kalender auth cancel",
            "kalender code nei",
            "kalenderkode avbryt",
            "gcal login stopp",
            "gcal auth no",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(
                    self.route(text).intent,
                    BotIntent.CALENDAR_AUTH,
                )

    def test_natural_calendar_auth_followups_require_exact_active_scope(self):
        monitor = DummyMonitor()
        checker = Mock(return_value=True)
        monitor.calendar.gcal = SimpleNamespace(
            has_active_auth_flow=checker
        )
        cases = {
            "her er koden 4/0AbC_12-SECRET": "4/0AbC_12-SECRET",
            (
                "her er koden 4/0AbC_12-SECRET og takk"
            ): "4/0AbC_12-SECRET",
            "koden er AbC_12_SECRET": "AbC_12_SECRET",
            (
                "koden er AbC_12_SECRET håper den virker"
            ): "AbC_12_SECRET",
            (
                "jeg fikk koden `4/0AbC_12-SECRET`, kan du bruke den?"
            ): "4/0AbC_12-SECRET",
            (
                "min oauth-kode er 4/0AbC_12-SECRET"
            ): "4/0AbC_12-SECRET",
            "4/0Bare-CODE": "4/0Bare-CODE",
            (
                "http://localhost:8080/?code=4%2F0Redirect-CODE&scope=x"
            ): "4/0Redirect-CODE",
        }
        for text, code in cases.items():
            with self.subTest(text=text):
                result = self.route(
                    text,
                    monitor=monitor,
                    channel_id=10,
                    user_id=7,
                )
                self.assertEqual(result.intent, BotIntent.CALENDAR_AUTH)
                self.assertEqual(result.payload, {"auth_code": code})
                self.assertEqual(
                    result.reason,
                    "calendar_auth_scoped_followup",
                )
                self.assertTrue(result.requires_confirmation)
        checker.assert_called_with(7, 10, reference_time=NOW)

    def test_explicit_calendar_auth_accepts_oauth_safe_code_characters(self):
        cases = {
            "kalender auth 4/0AbC.DEF": "4/0AbC.DEF",
            "kalender auth 4/0AbC+DEF": "4/0AbC+DEF",
            "kalenderkode 4%2F0AbC-DEF": "4/0AbC-DEF",
            "gcal code 4/0AbC=DEF": "4/0AbC=DEF",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.CALENDAR_AUTH)
                self.assertEqual(result.payload, {"auth_code": expected})
                self.assertTrue(result.requires_confirmation)

    def test_credential_shaped_followup_without_matching_flow_stays_local(self):
        monitor = DummyMonitor()
        monitor.calendar.gcal = SimpleNamespace(
            has_active_auth_flow=Mock(return_value=False)
        )
        for text in (
            "her er koden 4/0AbC_12-SECRET",
            "her er koden 4/0AbC_12-SECRET og takk",
            "koden er 4/0AbC_12-SECRET håper den virker",
            "jeg fikk koden `4/0AbC_12-SECRET`, kan du bruke den?",
            "min oauth-kode er 4/0AbC_12-SECRET",
            "4/0Bare-CODE",
        ):
            with self.subTest(text=text):
                result = self.route(
                    text,
                    monitor=monitor,
                    channel_id=10,
                    user_id=7,
                )
                self.assertEqual(result.intent, BotIntent.CLARIFY)
                self.assertEqual(
                    result.reason,
                    "credential_shaped_input_blocked",
                )
                self.assertNotIn("SECRET", repr(result.payload))
                self.assertNotIn("Bare-CODE", repr(result.payload))

        ordinary = self.route(
            "kan du forklare hva denne koden gjør?",
            monitor=monitor,
            channel_id=10,
            user_id=7,
        )
        self.assertEqual(ordinary.intent, BotIntent.AI_CHAT)
        for text in (
            "koden er skrevet i Python",
            "resultatet var 4/2026 i tabellen",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(
                        text,
                        monitor=monitor,
                        channel_id=10,
                        user_id=7,
                    ).intent,
                    BotIntent.AI_CHAT,
                )

    def test_watchlist_suggestion_compatibility_is_typed_and_scoped(self):
        cases = {
            "anbefaling film": "movie",
            "anbefaling komedie film": "movie",
            "recommend movie": "movie",
            "Can you recommend a movie": "movie",
            "recommend me a movie": "movie",
            "filmforslag": "movie",
            "serieforslag": "series",
        }
        for text, expected_type in cases.items():
            with self.subTest(text=text):
                direct = parse_watchlist_command(text)
                self.assertEqual(direct["action"], "suggest")
                self.assertEqual(direct["type"], expected_type)
                routed = self.route(text)
                self.assertEqual(routed.intent, BotIntent.WATCHLIST)
                self.assertEqual(
                    routed.payload["watchlist"]["type"], expected_type
                )
        for text in (
            "anbefaling",
            "recommend",
            "I recommend a movie",
            "recommend this",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_watchlist_command(text))
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_watchlist_temporal_ownership_uses_shared_resolver_and_clock(self):
        resolver = TemporalResolver()
        seen = []
        monitor = DummyMonitor()

        def recording_parser(content, **kwargs):
            seen.append(kwargs)
            return parse_watchlist_command(content, **kwargs)

        monitor.parse_watchlist_command = recording_parser
        router = IntentRouter(
            monitor,
            temporal_resolver=resolver,
            now_provider=lambda: NOW,
        )
        cases = tuple(DATE_ALIASES) + ("i kveld", "20.07.2026")
        for temporal in cases:
            text = f"husk å se Arrival {temporal}"
            with self.subTest(temporal=temporal):
                direct = parse_watchlist_command(
                    text,
                    reference_time=NOW,
                    temporal_resolver=resolver,
                )
                routed = router.route(text, guild_id=123)
                if temporal in {"i dag", "idag", "today"}:
                    self.assertEqual(direct["title"], "Arrival")
                    self.assertEqual(routed.intent, BotIntent.WATCHLIST)
                    self.assertEqual(
                        routed.payload["watchlist"]["title"], "Arrival"
                    )
                else:
                    self.assertIsNone(direct)
                    self.assertEqual(
                        routed.intent,
                        BotIntent.REMINDER_CREATE,
                    )
        self.assertTrue(seen)
        self.assertTrue(
            all(item["reference_time"] is NOW for item in seen)
        )
        self.assertTrue(
            all(item["temporal_resolver"] is resolver for item in seen)
        )

    def test_unsupported_multi_action_forms_never_route_one_partial_write(self):
        cases = (
            "legg til møte i morgen og påminn meg om å ringe legen",
            "påminn meg om å ringe legen i morgen og slett kalenderen",
            "påminn meg om å ringe legen og minn meg om å kjøpe melk",
            "flytt møtet med Ola til fredag og endre tittelen til Nytt møte",
            "lag en avstemning: Mat? Pizza eller taco og påminn meg om å handle",
        )
        router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
        for text in cases:
            with self.subTest(text=text):
                result = router.route(text, guild_id=123)
                self.assertIn(result.intent, {BotIntent.AI_CHAT, BotIntent.CLARIFY})
                self.assertFalse(result.requires_confirmation)

    def test_polite_watchlist_add_preserves_title(self):
        cases = (
            ("Kan du legge Arrival på watchlist?", "Arrival"),
            ("Kan du legge til Arrival på watchlist?", "Arrival"),
            ("Could you add Arrival to watchlist?", "Arrival"),
            ("Please add Arrival to the watchlist", "Arrival"),
            ("Kan du legge Inception til watchlisten min?", "Inception"),
            ("Kan du legge til Inception på watchlisten min?", "Inception"),
            ("Kan du huske at jeg vil se Inception?", "Inception"),
            ("Kan du huske at jeg skal se Inception?", "Inception"),
        )
        for text, title in cases:
            with self.subTest(text=text):
                direct = parse_watchlist_command(text)
                self.assertEqual(direct["title"], title)
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.WATCHLIST)
                self.assertEqual(
                    result.payload["watchlist"]["title"], title
                )

    def test_polite_norwegian_definite_watchlist_add_is_scoped(self):
        text = "Kan du legge Inception på watchlista?"

        direct = parse_watchlist_command(text)
        self.assertEqual(direct["title"], "Inception")
        result = self.route(text)
        self.assertEqual(result.intent, BotIntent.WATCHLIST)
        self.assertEqual(
            result.payload["watchlist"],
            {
                "action": "add",
                "title": "Inception",
                "type": None,
                "lang": "no",
            },
        )

    def test_watchlist_descriptions_and_non_media_tasks_are_not_adds(self):
        descriptions = (
            "jeg la Arrival på watchlist",
            "Arrival er på watchlist",
            "la være å legge Arrival på watchlist",
            "I added Arrival to watchlist",
            "ikke legg Arrival på watchlist",
            "do not add Arrival to watchlist",
            "legg til i watchlist",
            "Kan du huske at jeg vil se hvordan dette virker?",
            "Jeg vil se Inception",
            "Ola sa at jeg vil se Inception",
        )
        for text in descriptions:
            with self.subTest(text=text):
                self.assertIsNone(parse_watchlist_command(text))
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

        indirect_non_media = "Kan du huske at jeg skal se legen i morgen?"
        self.assertIsNone(parse_watchlist_command(indirect_non_media))
        self.assertNotEqual(
            self.route(indirect_non_media).intent,
            BotIntent.WATCHLIST,
        )

        reminder_tasks = (
            "husk å se på saken i morgen",
            "husk å se om døra er låst",
            "husk å se til barna",
            "remember to watch the kids tomorrow",
            "husk å se Arrival i morgen",
        )
        for text in reminder_tasks:
            with self.subTest(text=text):
                self.assertIsNone(parse_watchlist_command(text))
                self.assertEqual(
                    self.route(text).intent,
                    BotIntent.REMINDER_CREATE,
                )

    def test_inflected_calendar_edits_and_numeric_targets_route(self):
        edit_cases = (
            "Kan du endre møtet med Ola til fredag kl 10?",
            "Kan du flytte møtet med Ola til fredag kl 10?",
            "Endre avtalen med Ola til fredag kl 10",
            "flytt eventet med Ola til fredag kl 10",
            "Would you change meeting with Ola to Friday at 10?",
        )
        for text in edit_cases:
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
                self.assertTrue(result.payload["calendar_edit"]["changes"])

        targets = {
            "slett møte 1": BotIntent.CALENDAR_DELETE,
            "fullfør møte 1": BotIntent.CALENDAR_COMPLETE,
            "delete event 1": BotIntent.CALENDAR_DELETE,
            "complete meeting 1": BotIntent.CALENDAR_COMPLETE,
        }
        for text, expected in targets.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, expected)
                self.assertEqual(
                    result.payload["calendar_target"], {"number": 1}
                )

    def test_polite_and_inflected_reminder_frames_route(self):
        creates = (
            "Kan du påminne meg om å ringe legen i morgen?",
            "Kunne du minne meg om å ringe legen i morgen?",
            "Vil du minne meg om å ringe legen i morgen?",
            "Please remind me to call the doctor tomorrow",
            "Could you remind me to call the doctor tomorrow?",
            "Would you remind me to call the doctor tomorrow?",
            "Kan du påminn meg om å ringe legen i morgen?",
        )
        for text in creates:
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(text).intent,
                    BotIntent.REMINDER_CREATE,
                )

        targets = {
            "slett påminnelsen 1": BotIntent.REMINDER_DELETE,
            "delete the reminder 1": BotIntent.REMINDER_DELETE,
            "complete reminder number 1": BotIntent.REMINDER_COMPLETE,
            "delete reminder #1": BotIntent.REMINDER_DELETE,
        }
        for text, expected in targets.items():
            with self.subTest(text=text):
                result = self.route(text)
                self.assertEqual(result.intent, expected)
                self.assertEqual(result.payload["reminder"]["number"], 1)

    def test_positive_forget_reminder_frames_are_bounded_and_negation_safe(self):
        creates = (
            "ikke glem å kjøpe melk i morgen",
            "ikkje gløym å kjøpe mjølk i morgon",
            "don't forget to buy milk tomorrow",
        )
        for text in creates:
            with self.subTest(text=text):
                self.assertEqual(
                    self.route(text).intent,
                    BotIntent.REMINDER_CREATE,
                )
        for text in (
            "ikke glem å ikke kjøpe melk i morgen",
            "don't forget not to buy milk tomorrow",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text).intent, BotIntent.AI_CHAT)

    def test_reference_time_is_threaded_to_every_active_state_read(self):
        poll_references = []
        calendar_references = []
        monitor = DummyMonitor()

        def active_polls(_guild_id, *, reference_time):
            poll_references.append(reference_time)
            return [{"id": "poll1"}]

        def upcoming(_guild_id, days=365, *, reference_time):
            calendar_references.append(reference_time)
            return [{"title": "Møte med Ola"}]

        monitor.poll.get_active_polls = active_polls
        monitor.calendar.get_upcoming = upcoming
        router = IntentRouter(monitor, now_provider=lambda: NOW)

        self.assertEqual(
            router.route(
                "vis poll", guild_id=123, reference_time=NOW
            ).intent,
            BotIntent.POLL_LIST,
        )
        self.assertEqual(
            router.route(
                "slett Møte med Ola",
                guild_id=123,
                reference_time=NOW,
            ).intent,
            BotIntent.CALENDAR_DELETE,
        )
        self.assertTrue(poll_references)
        self.assertTrue(calendar_references)
        self.assertTrue(
            all(reference is NOW for reference in poll_references)
        )
        self.assertTrue(
            all(reference is NOW for reference in calendar_references)
        )

    def test_capability_help_is_exact_not_generic_creation_help(self):
        self.assertEqual(self.route("Kva kan du gjere?").intent, BotIntent.HELP)
        for text in (
            "ka kan du lage avstemning",
            "hva kan du slette",
            "what can you create tomorrow",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(self.route(text).intent, BotIntent.HELP)


@pytest.mark.parametrize(
    ("text", "intent", "envelope", "expected"),
    [
        (
            "jeg må levere rapport 20.07.2030",
            BotIntent.CALENDAR_ITEM,
            "calendar_item",
            {"title": "levere rapport", "date": "20.07.2030", "type": "task"},
        ),
        (
            "kalender endre 1 type: task",
            BotIntent.CALENDAR_EDIT,
            "calendar_edit",
            {"target": "1", "changes": {"type": "task"}},
        ),
        (
            "slett møte med Ola",
            BotIntent.CALENDAR_DELETE,
            "calendar_target",
            {"target": "møte med Ola"},
        ),
        (
            "kalender slett alt",
            BotIntent.CALENDAR_CLEAR,
            "calendar_target",
            {"all": True},
        ),
        (
            "påminn meg om å ringe legen 20.07.2030 kl 14",
            BotIntent.REMINDER_CREATE,
            "reminder",
            {
                "action": "add",
                "text": "ringe legen",
                "due_at": "2030-07-20T14:00:00+02:00",
                "due_date": "20.07.2030",
                "time": "14:00",
                "timezone": "Europe/Oslo",
            },
        ),
        (
            "påminnelser",
            BotIntent.REMINDER_LIST,
            "reminder",
            {"action": "list"},
        ),
        (
            "søk påminnelse lege",
            BotIntent.REMINDER_SEARCH,
            "reminder",
            {"action": "search", "query": "lege"},
        ),
        (
            "endre påminnelse 1 tekst: Ring tannlegen",
            BotIntent.REMINDER_EDIT,
            "reminder",
            {"action": "edit", "number": 1, "changes": {"text": "Ring tannlegen"}},
        ),
        (
            "slett påminnelse 1",
            BotIntent.REMINDER_DELETE,
            "reminder",
            {"action": "delete", "number": 1},
        ),
        (
            "avstemning Pizza? / Ja / Nei",
            BotIntent.POLL_CREATE,
            "poll",
            {"question": "Pizza?", "options": ["Ja", "Nei"], "lang": "no"},
        ),
        (
            "rediger avstemning 1 alternativer: Pizza / Taco / Salat",
            BotIntent.POLL_EDIT,
            "poll_edit",
            {"target": 1, "options": ["Pizza", "Taco", "Salat"]},
        ),
        (
            "slett poll 1",
            BotIntent.POLL_DELETE,
            "poll_delete",
            {"target": 1},
        ),
        (
            "lukk poll 1",
            BotIntent.POLL_CLOSE,
            "poll_close",
            {"target": 1},
        ),
        (
            "endre watchlist 1 tittel: The Matrix",
            BotIntent.WATCHLIST,
            "watchlist",
            {"action": "edit", "index": 1, "title": "The Matrix", "lang": "no"},
        ),
        (
            "hva skal vi se?",
            BotIntent.WATCHLIST,
            "watchlist",
            {"action": "suggest", "type": None, "genre": None, "lang": "no"},
        ),
        (
            "liste sitater",
            BotIntent.QUOTE_LIST,
            "quote",
            {"action": "list", "lang": "no"},
        ),
        (
            "endre sitat 1 tekst: Ny tekst forfatter: Kari",
            BotIntent.QUOTE_EDIT,
            "quote",
            {
                "action": "edit",
                "index": 1,
                "text": "Ny tekst",
                "author": "Kari",
                "lang": "no",
            },
        ),
        (
            "slett sitat 1",
            BotIntent.QUOTE_DELETE,
            "quote",
            {"action": "delete", "index": 1, "lang": "no"},
        ),
        (
            "vis minnet mitt",
            BotIntent.MEMORY_VIEW,
            "memory",
            {"action": "view"},
        ),
        (
            "eksporter minnet mitt",
            BotIntent.MEMORY_EXPORT,
            "memory",
            {"action": "export"},
        ),
        (
            "slett minnet mitt bekreft",
            BotIntent.MEMORY_DELETE,
            "memory",
            {"action": "delete"},
        ),
    ],
)
def test_production_action_routes_emit_complete_validated_envelopes(
    production_router_adapter, text, intent, envelope, expected
):
    result, parser_names = production_router_adapter.evaluate(text, guild_id=123)

    assert parser_names == ()
    assert result.intent is intent
    assert ENVELOPE_KEYS[intent] == envelope
    assert result.payload == {envelope: expected}
    assert validate_intent_payload(intent, result.payload[envelope]) == expected
    assert {"content", "original_text", "raw_text"}.isdisjoint(
        _nested_payload_keys(result.payload)
    )


def test_poll_vote_freezes_the_single_active_poll_id(active_poll_router_adapter):
    result, parser_names = active_poll_router_adapter.evaluate("1", guild_id=123)

    assert parser_names == ()
    assert result.intent is BotIntent.POLL_VOTE
    assert result.payload == {"vote": {"option": 1, "poll_id": "poll-1"}}


@pytest.mark.parametrize(
    ("text", "option"),
    [
        ("stem på alternativ to", 2),
        ("jeg stemmer på alternativ to", 2),
        ("I vote for option two", 2),
    ],
)
def test_natural_vote_freezes_the_single_active_poll_id(
    active_poll_router_adapter,
    text,
    option,
):
    result, parser_names = active_poll_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.POLL_VOTE
    assert result.payload == {
        "vote": {"option": option, "poll_id": "poll-1"}
    }
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    [
        "Ola stemmer på alternativ to",
        "jeg stemte på alternativ to",
        "jeg stemmer på alternativ to, men glem det",
    ],
)
def test_natural_vote_reports_and_retractions_never_write(
    active_poll_router_adapter,
    text,
):
    result, parser_names = active_poll_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is not BotIntent.POLL_VOTE
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("text", "question", "options"),
    [
        (
            "kan du lage en avstemning: Hva spiser vi? Pizza eller taco",
            "Hva spiser vi?",
            ["Pizza", "taco"],
        ),
        (
            "can you make a poll: Food? Pizza or tacos",
            "Food?",
            ["Pizza", "tacos"],
        ),
    ],
)
def test_production_router_accepts_bounded_polite_poll_creation(
    production_router_adapter,
    text,
    question,
    options,
):
    result, parser_names = production_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.POLL_CREATE
    assert result.payload["poll"]["question"] == question
    assert result.payload["poll"]["options"] == options
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    [
        "jeg lagde en avstemning: Mat? Pizza eller taco",
        "we discussed a poll: Food? Pizza or tacos",
    ],
)
def test_production_router_keeps_descriptive_poll_mentions_in_chat(
    production_router_adapter,
    text,
):
    result, parser_names = production_router_adapter.evaluate(
        text, guild_id=123
    )

    assert parser_names == ()
    assert result.intent is BotIntent.AI_CHAT
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("text", "intent", "envelope", "expected"),
    [
        (
            "slett poll",
            BotIntent.POLL_DELETE,
            "poll_delete",
            {"poll_id": "poll-1"},
        ),
        (
            "lukk poll",
            BotIntent.POLL_CLOSE,
            "poll_close",
            {"poll_id": "poll-1"},
        ),
        (
            "endre poll spørsmål: Middag?",
            BotIntent.POLL_EDIT,
            "poll_edit",
            {"poll_id": "poll-1", "question": "Middag?"},
        ),
        (
            "endre poll spørsmål: Middag: pizza eller taco?",
            BotIntent.POLL_EDIT,
            "poll_edit",
            {
                "poll_id": "poll-1",
                "question": "Middag: pizza eller taco?",
            },
        ),
    ],
)
def test_targetless_poll_actions_freeze_the_single_active_poll(
    active_poll_router_adapter, text, intent, envelope, expected
):
    result, parser_names = active_poll_router_adapter.evaluate(text, guild_id=123)

    assert parser_names == ()
    assert result.intent is intent
    assert result.payload == {envelope: expected}


@pytest.mark.parametrize("text", ["1", "slett poll", "lukk poll", "endre poll spørsmål: Ny?"])
def test_implicit_poll_actions_fail_closed_without_one_stable_poll_id(text):
    monitor = DummyMonitor(active_polls=True)
    monitor.poll.get_active_polls = lambda *_args, **_kwargs: [
        {"id": "poll-1"},
        {"id": "poll-2"},
    ]

    result = IntentRouter(monitor, now_provider=lambda: NOW).route(text, guild_id=123)

    assert result.intent is BotIntent.AI_CHAT
    assert result.payload == {}


def test_calendar_create_projects_parser_only_fields_and_none_values():
    monitor = DummyMonitor()
    monitor.nlp_parser.parse_task_with_recurrence_result = lambda *_args, **_kwargs: {
        "title": "Styremøte",
        "date": "22.07.2030",
        "time": None,
        "type": "event",
        "recurrence": "weekly",
        "recurrence_day": "mandag",
        "rrule_day": "MO",
        "days_offset": 5,
        "description": "Saksliste",
        "due_at": "2030-07-22T09:00:00+02:00",
    }
    result = IntentRouter(monitor, now_provider=lambda: NOW).route(
        "møte Styremøte 22.07.2030", guild_id=123
    )

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload == {
        "calendar_item": {
            "title": "Styremøte",
            "date": "22.07.2030",
            "type": "event",
            "recurrence": "weekly",
            "recurrence_day": "mandag",
            "rrule_day": "MO",
            "days_offset": 5,
            "description": "Saksliste",
        }
    }


@pytest.mark.parametrize("stage", ["task", "event"])
@pytest.mark.parametrize(
    "invalid",
    [[], 1, "SECRET_CALENDAR_VALUE", NaturalParseResult([])],  # type: ignore[arg-type]
)
def test_non_mapping_calendar_parser_output_is_a_bounded_diagnostic(
    stage, invalid
):
    monitor = DummyMonitor()
    if stage == "task":
        monitor.nlp_parser.parse_task_with_recurrence_result = (
            lambda *_args, **_kwargs: invalid
        )
    else:
        monitor.nlp_parser.parse_task_with_recurrence_result = (
            lambda *_args, **_kwargs: NaturalParseResult(None)
        )
        monitor.nlp_parser.parse_event_result = lambda *_args, **_kwargs: invalid
    metrics = NLUMetrics()

    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(
        normalize_utterance("møte styremøte 20.07.2030"),
        guild_id=123,
    )

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.result.payload == {}
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        "parser=calendar|code=invalid_payload": 1
    }
    assert "SECRET_CALENDAR_VALUE" not in repr(routed)


def test_invalid_parser_payload_is_bounded_and_never_arbitrated():
    monitor = DummyMonitor()
    monitor.parse_quote_command = lambda _text: {
        "action": "get",
        "raw_text": "SECRET_RAW_TEXT",
    }
    metrics = NLUMetrics()
    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(normalize_utterance("sitat"), guild_id=123)

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.result.payload == {}
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        "parser=quote|code=invalid_payload": 1
    }
    assert "SECRET_RAW_TEXT" not in repr(routed)


@pytest.mark.parametrize("family", ["calendar", "poll", "watchlist"])
def test_one_invalid_parser_object_records_one_diagnostic_across_candidate_tiers(
    family,
):
    monitor = DummyMonitor()
    if family == "calendar":
        monitor.nlp_parser.parse_task_with_recurrence_result = (
            lambda *_args, **_kwargs: {
                "title": "Møte",
                "date": "20.07.2030",
                "type": "bad",
            }
        )
        text = "møte Møte 20.07.2030"
    elif family == "poll":
        monitor.parse_poll_command = lambda _text: {
            "question": "Hva?",
            "options": ["Ja", "Nei"],
            "lang": "xx",
        }
        text = "lag poll Hva? / Ja / Nei"
    else:
        monitor.parse_watchlist_command = lambda *_args, **_kwargs: {
            "action": "add",
            "title": "Matrix",
            "type": "bad",
        }
        text = "legg Matrix på watchlist"
    metrics = NLUMetrics()

    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(normalize_utterance(text), guild_id=123)

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.result.payload == {}
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        f"parser={family}|code=invalid_payload": 1
    }


@pytest.mark.parametrize(
    ("family", "text", "invalid_action"),
    [
        ("reminder", "påminnelse Ring lege", ["add"]),
        ("reminder", "påminnelse Ring lege", {"add": True}),
        ("watchlist", "vis watchlist", ["status"]),
        ("watchlist", "vis watchlist", {"status": True}),
        ("quote", "sitat", ["get"]),
        ("quote", "sitat", {"get": True}),
    ],
)
def test_json_shaped_parser_actions_fail_closed_with_bounded_diagnostic(
    family, text, invalid_action
):
    monitor = DummyMonitor()
    if family == "reminder":
        monitor.parse_reminder_command = lambda *_args, **_kwargs: {
            "action": invalid_action
        }
    elif family == "watchlist":
        monitor.parse_watchlist_command = lambda *_args, **_kwargs: {
            "action": invalid_action
        }
    else:
        monitor.parse_quote_command = lambda *_args, **_kwargs: {
            "action": invalid_action
        }
    metrics = NLUMetrics()

    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(normalize_utterance(text), guild_id=123)

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.result.payload == {}
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        f"parser={family}|code=invalid_payload": 1
    }
    assert repr(invalid_action) not in repr(routed)


@pytest.mark.parametrize("family", ["reminder", "watchlist", "quote"])
def test_non_mapping_parser_output_is_a_bounded_invalid_payload(family):
    monitor = DummyMonitor()
    text = {
        "reminder": "påminnelse Ring lege",
        "watchlist": "vis watchlist",
        "quote": "sitat",
    }[family]
    if family == "reminder":
        monitor.parse_reminder_command = lambda *_args, **_kwargs: []
    elif family == "watchlist":
        monitor.parse_watchlist_command = lambda *_args, **_kwargs: []
    else:
        monitor.parse_quote_command = lambda *_args, **_kwargs: []
    metrics = NLUMetrics()

    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(normalize_utterance(text), guild_id=123)

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        f"parser={family}|code=invalid_payload": 1
    }


@pytest.mark.parametrize(
    ("parser", "invalid"),
    [
        ("create", []),
        ("create", 7),
        ("vote", []),
        ("vote", "1"),
        ("vote", True),
    ],
)
def test_non_mapping_poll_parser_output_is_a_bounded_invalid_payload(
    parser, invalid
):
    monitor = DummyMonitor(active_polls=parser == "vote")
    if parser == "create":
        monitor.parse_poll_command = lambda _text: invalid
        text = "lag poll Hva? / Ja / Nei"
    else:
        monitor.parse_vote = lambda _text: invalid
        text = "1"
    metrics = NLUMetrics()

    routed = IntentRouter(
        monitor, metrics=metrics, now_provider=lambda: NOW
    ).evaluate_utterance(normalize_utterance(text), guild_id=123)

    assert routed.result.intent is BotIntent.AI_CHAT
    assert routed.result.payload == {}
    assert routed.diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}
    assert metrics.snapshot()["parser_errors"] == {
        "parser=poll|code=invalid_payload": 1
    }


def test_quote_author_lookup_routes_in_norwegian_and_english(
    production_router_adapter,
):
    for text, author, lang in (
        ("hva sa Kari?", "Kari", "no"),
        ("what did Kari say?", "Kari", "en"),
    ):
        result, parser_names = production_router_adapter.evaluate(text, guild_id=123)
        assert parser_names == ()
        assert result.intent is BotIntent.QUOTE
        assert result.payload == {
            "quote": {"action": "get", "author": author, "lang": lang}
        }


def test_semantic_action_candidate_is_validated_before_arbitration():
    router = IntentRouter(DummyMonitor(), now_provider=lambda: NOW)
    candidate = IntentCandidate(
        BotIntent.QUOTE,
        0.9,
        50,
        payload={"quote": {"action": "get", "raw_text": "SECRET"}},
        source=IntentSource.SEMANTIC,
    )

    valid, rejected = router._validate_action_candidates([candidate])

    assert valid == []
    assert len(rejected) == 1
    assert rejected[0].code is RejectionCode.PARSER_ERROR
    assert router.metrics.snapshot()["parser_errors"] == {
        "parser=quote|code=invalid_payload": 1
    }


def test_action_routes_never_expose_raw_text_compatibility_fields(
    production_router_adapter,
):
    forbidden = {"content", "original_text", "raw_text"}

    for text in (
        "jeg må levere rapport 20.07.2030",
        "endre påminnelse 1 tekst: Ring tannlegen",
        "rediger avstemning 1 alternativer: Pizza / Taco / Salat",
        "endre watchlist 1 tittel: The Matrix",
        "endre sitat 1 tekst: Ny tekst forfatter: Kari",
    ):
        result, _ = production_router_adapter.evaluate(text, guild_id=123)
        assert forbidden.isdisjoint(_nested_payload_keys(result.payload))


if __name__ == "__main__":
    unittest.main()

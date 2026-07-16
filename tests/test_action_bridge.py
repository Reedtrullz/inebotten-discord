"""Exhaustive tests for the inert model-action to typed-intent bridge."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai.action_schema import ActionName, parse_ai_response
from core.action_bridge import (
    ACTION_ROUTE_BUILDERS,
    BRIDGE_TEMPORAL_ERROR_CODES,
    ActionBridge,
    _ACTION_EVIDENCE,
    _DOMAIN_EVIDENCE,
    validate_route_payload,
)
from core.help_registry import HELP_EXAMPLES
from core.intent_models import (
    ArbitrationDecision,
    BotIntent,
    IntentResult,
    IntentRisk,
    IntentSource,
    RejectionCode,
)
from core.intent_payloads import PayloadValidationError
from core.message_context import ResolvedMention
from core.nlu_metrics import NLUMetrics
from core.utterance import normalize_utterance
from core.utterance_semantics import SpeechAct, UtteranceSemantics
from tests.nlu_test_support import (
    FIXED_NOW,
    bridge_context,
    proposal_for,
)
from tests.nlu_harness import load_cases


_NLU_CORPUS = Path(__file__).parent / "fixtures" / "nlu_contract_v1.jsonl"
_EXECUTABLE_SEQUENCE_CASES = tuple(
    case
    for case in load_cases(_NLU_CORPUS)
    if case.expected_intent not in {"ai_chat", "clarify"}
)
_CONTEXT_FREE_BRIDGE_SEQUENCE_CASES = tuple(
    case for case in _EXECUTABLE_SEQUENCE_CASES if case.id != "nb-poll-vote"
)


MAPPING_ROWS = (
    pytest.param(
        ActionName.SHOW_DASHBOARD,
        {},
        "vis oversikten",
        BotIntent.DASHBOARD,
        {"dashboard_reason": "model_action"},
        IntentRisk.READ_ONLY,
        {},
        id="dashboard",
    ),
    pytest.param(
        ActionName.HELP,
        {},
        "hjelp",
        BotIntent.HELP,
        {},
        IntentRisk.READ_ONLY,
        {},
        id="help",
    ),
    pytest.param(
        ActionName.CALENDAR_CREATE,
        {"title": "Møte", "date": "15.07.2026", "time": "14:00"},
        "planlegg møte i kalenderen",
        BotIntent.CALENDAR_ITEM,
        {"calendar_item": {"title": "Møte", "date": "15.07.2026", "time": "14:00"}},
        IntentRisk.ADDITIVE,
        {},
        id="calendar-create",
    ),
    pytest.param(
        ActionName.CALENDAR_LIST,
        {},
        "vis kalenderen",
        BotIntent.CALENDAR_LIST,
        {},
        IntentRisk.READ_ONLY,
        {},
        id="calendar-list",
    ),
    pytest.param(
        ActionName.CALENDAR_SEARCH,
        {"query": "lege"},
        "finn lege i kalenderen",
        BotIntent.CALENDAR_SEARCH,
        {"query": "lege"},
        IntentRisk.READ_ONLY,
        {},
        id="calendar-search",
    ),
    pytest.param(
        ActionName.CALENDAR_COMPLETE,
        {"target": "Møte"},
        "fullfør avtalen",
        BotIntent.CALENDAR_COMPLETE,
        {"calendar_target": {"target": "Møte"}},
        IntentRisk.MUTATING,
        {},
        id="calendar-complete",
    ),
    pytest.param(
        ActionName.CALENDAR_EDIT,
        {"target": "Møte", "title": "Nytt møte"},
        "endre møtet",
        BotIntent.CALENDAR_EDIT,
        {"calendar_edit": {"target": "Møte", "changes": {"title": "Nytt møte"}}},
        IntentRisk.MUTATING,
        {},
        id="calendar-edit",
    ),
    pytest.param(
        ActionName.CALENDAR_DELETE,
        {"target": "Møte"},
        "slett avtalen",
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": "Møte"}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="calendar-delete",
    ),
    pytest.param(
        ActionName.CALENDAR_CLEAR,
        {},
        "tøm kalenderen",
        BotIntent.CALENDAR_CLEAR,
        {"calendar_target": {"all": True}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="calendar-clear",
    ),
    pytest.param(
        ActionName.REMINDER_CREATE,
        {"text": "ringe legen", "due_date": "15.07.2026", "time": "09:00"},
        "påminn meg om å ringe legen",
        BotIntent.REMINDER_CREATE,
        {"reminder": {"action": "add", "text": "ringe legen", "due_date": "15.07.2026", "time": "09:00"}},
        IntentRisk.ADDITIVE,
        {},
        id="reminder-create",
    ),
    pytest.param(
        ActionName.REMINDER_LIST,
        {},
        "vis påminnelser",
        BotIntent.REMINDER_LIST,
        {"reminder": {"action": "list"}},
        IntentRisk.READ_ONLY,
        {},
        id="reminder-list",
    ),
    pytest.param(
        ActionName.REMINDER_SEARCH,
        {"query": "lege"},
        "finn påminnelsen om legen",
        BotIntent.REMINDER_SEARCH,
        {"reminder": {"action": "search", "query": "lege"}},
        IntentRisk.READ_ONLY,
        {},
        id="reminder-search",
    ),
    pytest.param(
        ActionName.REMINDER_COMPLETE,
        {"number": 1},
        "fullfør påminnelsen",
        BotIntent.REMINDER_COMPLETE,
        {"reminder": {"action": "complete", "number": 1}},
        IntentRisk.MUTATING,
        {},
        id="reminder-complete",
    ),
    pytest.param(
        ActionName.REMINDER_EDIT,
        {"number": 1, "text": "ringe tannlegen"},
        "endre påminnelsen",
        BotIntent.REMINDER_EDIT,
        {"reminder": {"action": "edit", "number": 1, "changes": {"text": "ringe tannlegen"}}},
        IntentRisk.MUTATING,
        {},
        id="reminder-edit",
    ),
    pytest.param(
        ActionName.REMINDER_DELETE,
        {"number": 1},
        "slett påminnelsen",
        BotIntent.REMINDER_DELETE,
        {"reminder": {"action": "delete", "number": 1}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="reminder-delete",
    ),
    pytest.param(
        ActionName.POLL_CREATE,
        {"question": "Middag?", "options": ["Pizza", "Taco"]},
        "lag en avstemning",
        BotIntent.POLL_CREATE,
        {"poll": {"question": "Middag?", "options": ["Pizza", "Taco"]}},
        IntentRisk.ADDITIVE,
        {},
        id="poll-create",
    ),
    pytest.param(
        ActionName.POLL_LIST,
        {},
        "vis avstemninger",
        BotIntent.POLL_LIST,
        {},
        IntentRisk.READ_ONLY,
        {},
        id="poll-list",
    ),
    pytest.param(
        ActionName.POLL_VOTE,
        {"option": 1},
        "stem i avstemningen",
        BotIntent.POLL_VOTE,
        {"vote": {"option": 1, "poll_id": "poll-1"}},
        IntentRisk.MUTATING,
        {"active_poll_count": 1, "active_poll_id": "poll-1"},
        id="poll-vote",
    ),
    pytest.param(
        ActionName.POLL_EDIT,
        {"target": "siste", "question": "Ny middag?"},
        "endre avstemningen",
        BotIntent.POLL_EDIT,
        {"poll_edit": {"target": "siste", "question": "Ny middag?"}},
        IntentRisk.MUTATING,
        {},
        id="poll-edit",
    ),
    pytest.param(
        ActionName.POLL_DELETE,
        {"target": "siste"},
        "slett avstemningen",
        BotIntent.POLL_DELETE,
        {"poll_delete": {"target": "siste"}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="poll-delete",
    ),
    pytest.param(
        ActionName.POLL_CLOSE,
        {"target": "siste"},
        "lukk avstemningen",
        BotIntent.POLL_CLOSE,
        {"poll_close": {"target": "siste"}},
        IntentRisk.MUTATING,
        {},
        id="poll-close",
    ),
    pytest.param(
        ActionName.BIRTHDAY_CREATE,
        {"user_id": 30, "day": 1, "month": 5},
        "registrer bursdag",
        BotIntent.BIRTHDAY_CREATE,
        {"birthday": {"action": "add", "user_id": 30, "display_name": "Ola", "day": 1, "month": 5}},
        IntentRisk.ADDITIVE,
        {"mentions": (ResolvedMention(30, "Ola"),)},
        id="birthday-create",
    ),
    pytest.param(
        ActionName.BIRTHDAY_LIST,
        {},
        "vis bursdager",
        BotIntent.BIRTHDAY_LIST,
        {"birthday": {"action": "list", "scope": "all"}},
        IntentRisk.READ_ONLY,
        {},
        id="birthday-list",
    ),
    pytest.param(
        ActionName.BIRTHDAY_EDIT,
        {"user_id": 20, "day": 2, "month": 6},
        "endre bursdagen",
        BotIntent.BIRTHDAY_EDIT,
        {"birthday": {"action": "edit", "user_id": 20, "day": 2, "month": 6}},
        IntentRisk.MUTATING,
        {},
        id="birthday-edit",
    ),
    pytest.param(
        ActionName.PROFILE_STATUS,
        {"value": "dnd"},
        "kan du sette statusen din til dnd?",
        BotIntent.PROFILE,
        {"profile": {"action": "status", "value": "dnd"}},
        IntentRisk.MUTATING,
        {},
        id="profile-status",
    ),
    pytest.param(
        ActionName.PROFILE_PLAYING,
        {"value": "CS2"},
        "kan du vise at du spiller CS2?",
        BotIntent.PROFILE,
        {"profile": {"action": "playing", "value": "CS2"}},
        IntentRisk.MUTATING,
        {},
        id="profile-playing",
    ),
    pytest.param(
        ActionName.PROFILE_WATCHING,
        {"value": "Netflix"},
        "kan du vise at du ser på Netflix?",
        BotIntent.PROFILE,
        {"profile": {"action": "watching", "value": "Netflix"}},
        IntentRisk.MUTATING,
        {},
        id="profile-watching",
    ),
    pytest.param(
        ActionName.WATCHLIST_ADD,
        {"title": "Dune", "type": "movie"},
        "legg til Dune på filmlista",
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "add", "title": "Dune", "type": "movie"}},
        IntentRisk.ADDITIVE,
        {},
        id="watchlist-add",
    ),
    pytest.param(
        ActionName.WATCHLIST_LIST,
        {},
        "vis filmlista",
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "status"}},
        IntentRisk.READ_ONLY,
        {},
        id="watchlist-list",
    ),
    pytest.param(
        ActionName.WATCHLIST_SUGGEST,
        {"type": "movie"},
        "foreslå film",
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "suggest", "type": "movie"}},
        IntentRisk.READ_ONLY,
        {},
        id="watchlist-suggest",
    ),
    pytest.param(
        ActionName.WATCHLIST_EDIT,
        {"index": 1, "title": "Dune 2"},
        "endre filmen",
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "edit", "index": 1, "title": "Dune 2"}},
        IntentRisk.MUTATING,
        {},
        id="watchlist-edit",
    ),
    pytest.param(
        ActionName.WATCHLIST_REMOVE,
        {"index": 1},
        "fjern filmen",
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "remove", "index": 1}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="watchlist-remove",
    ),
    pytest.param(
        ActionName.QUOTE_SAVE,
        {"text": "Carpe diem", "author": "Horats"},
        "lagre sitat",
        BotIntent.QUOTE,
        {"quote": {"action": "save", "text": "Carpe diem", "author": "Horats"}},
        IntentRisk.ADDITIVE,
        {},
        id="quote-save",
    ),
    pytest.param(
        ActionName.QUOTE_GET,
        {},
        "hent et tilfeldig sitat",
        BotIntent.QUOTE,
        {"quote": {"action": "get"}},
        IntentRisk.READ_ONLY,
        {},
        id="quote-get",
    ),
    pytest.param(
        ActionName.QUOTE_LIST,
        {},
        "vis sitater",
        BotIntent.QUOTE_LIST,
        {"quote": {"action": "list"}},
        IntentRisk.READ_ONLY,
        {},
        id="quote-list",
    ),
    pytest.param(
        ActionName.QUOTE_EDIT,
        {"index": 1, "text": "Nytt sitat"},
        "endre sitatet",
        BotIntent.QUOTE_EDIT,
        {"quote": {"action": "edit", "index": 1, "text": "Nytt sitat"}},
        IntentRisk.MUTATING,
        {},
        id="quote-edit",
    ),
    pytest.param(
        ActionName.QUOTE_DELETE,
        {"index": 1},
        "slett sitatet",
        BotIntent.QUOTE_DELETE,
        {"quote": {"action": "delete", "index": 1}},
        IntentRisk.DESTRUCTIVE,
        {},
        id="quote-delete",
    ),
)


@pytest.mark.parametrize(
    "action,slots,text,expected_intent,expected_payload,expected_risk,context_kwargs",
    MAPPING_ROWS,
)
def test_every_executable_action_maps_to_exact_typed_route(
    action,
    slots,
    text,
    expected_intent,
    expected_payload,
    expected_risk,
    context_kwargs,
):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(text),
            **context_kwargs,
        ),
    )

    assert result is not None
    assert result.intent is expected_intent
    assert result.payload == expected_payload
    assert result.source is IntentSource.SEMANTIC
    assert result.risk is expected_risk
    assert result.requires_confirmation is (expected_risk is not IntentRisk.READ_ONLY)


def test_mapping_and_evidence_tables_cover_the_closed_action_manifest():
    assert set(ACTION_ROUTE_BUILDERS) == set(ActionName) - {
        ActionName.NONE,
        ActionName.CLARIFY,
    }
    assert set(_ACTION_EVIDENCE) == set(ActionName)
    assert set(_DOMAIN_EVIDENCE) == set(ActionName)


@pytest.mark.parametrize(
    ("text", "action", "slots", "expected_action"),
    (
        (
            "kan du setje statusen din til idle?",
            ActionName.PROFILE_STATUS,
            {"value": "idle"},
            "status",
        ),
        (
            "could you show that you are playing Life is Strange?",
            ActionName.PROFILE_PLAYING,
            {"value": "Life is Strange"},
            "playing",
        ),
        (
            "please set your activity to watching The Bear",
            ActionName.PROFILE_WATCHING,
            {"value": "The Bear"},
            "watching",
        ),
    ),
)
def test_bounded_profile_paraphrases_recover_as_confirmed_semantic_writes(
    text, action, slots, expected_action
):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is not None
    assert result.intent is BotIntent.PROFILE
    assert result.payload["profile"]["action"] == expected_action
    assert result.source is IntentSource.SEMANTIC
    assert result.risk is IntentRisk.MUTATING
    assert result.requires_confirmation is True


@pytest.mark.parametrize(
    ("text", "action", "slots"),
    (
        (
            "ikke sett statusen din til dnd",
            ActionName.PROFILE_STATUS,
            {"value": "dnd"},
        ),
        (
            "hva skjer hvis du setter statusen til dnd?",
            ActionName.PROFILE_STATUS,
            {"value": "dnd"},
        ),
        (
            "hvordan setter man statusen til dnd?",
            ActionName.PROFILE_STATUS,
            {"value": "dnd"},
        ),
        (
            "Ola sa at du burde vise at du spiller CS2",
            ActionName.PROFILE_PLAYING,
            {"value": "CS2"},
        ),
        (
            "vi snakket om at du ser på Netflix",
            ActionName.PROFILE_WATCHING,
            {"value": "Netflix"},
        ),
        (
            "spiller CS2 er et eksempel på en kommando",
            ActionName.PROFILE_PLAYING,
            {"value": "CS2"},
        ),
        (
            "status online er teksten jeg skrev",
            ActionName.PROFILE_STATUS,
            {"value": "online"},
        ),
    ),
)
def test_profile_recovery_rejects_negated_hypothetical_meta_and_reported_neighbors(
    text, action, slots
):
    assert ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    ) is None


def test_none_and_clarify_are_non_executable_protocol_results():
    bridge = ActionBridge()
    assert bridge.to_result(
        proposal_for(ActionName.NONE, {}),
        bridge_context(),
    ) is None

    result = bridge.to_result(
        proposal_for(
            ActionName.CLARIFY,
            {},
            clarification="Når skal det skje?",
        ),
        bridge_context(),
    )
    assert result == IntentResult(
        BotIntent.CLARIFY,
        0.91,
        {"clarification": "Når skal det skje?"},
        "semantic_clarification",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.READ_ONLY,
        requires_confirmation=False,
    )


def test_model_bridge_has_no_executor_or_message_dependency():
    signature = inspect.signature(ActionBridge)
    assert "monitor" not in signature.parameters
    assert "executor" not in signature.parameters
    source = inspect.getsource(ActionBridge)
    for forbidden in ("_handle_intent", ".send(", ".reply(", "manager"):
        assert forbidden not in source


def test_missing_outer_envelope_raises_bounded_payload_error():
    with pytest.raises(PayloadValidationError, match="missing_payload"):
        validate_route_payload(
            BotIntent.CALENDAR_ITEM,
            {},
            source=IntentSource.SEMANTIC,
        )


def test_bridge_temporal_error_codes_are_closed_and_bounded():
    assert BRIDGE_TEMPORAL_ERROR_CODES == {
        "naive_reference_time",
        "invalid_temporal",
        "conflicting_temporal_fields",
    }


def test_calendar_days_offset_uses_captured_oslo_reference_and_never_escapes():
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Møte", "days_offset": 1, "time": "10:00"},
        ),
        bridge_context(utterance=normalize_utterance("planlegg møte i kalenderen")),
    )
    assert result is not None
    assert result.payload == {
        "calendar_item": {
            "title": "Møte",
            "date": "15.07.2026",
            "time": "10:00",
        }
    }
    assert "days_offset" not in result.payload["calendar_item"]


def test_calendar_days_offset_conflict_and_naive_reference_fail_bounded():
    proposal = proposal_for(
        ActionName.CALENDAR_CREATE,
        {"title": "Møte", "date": "16.07.2026", "days_offset": 1},
    )
    with pytest.raises(PayloadValidationError, match="conflicting_temporal_fields"):
        ActionBridge().to_result(
            proposal,
            bridge_context(utterance=normalize_utterance("planlegg møte i kalenderen")),
        )

    with pytest.raises(PayloadValidationError, match="naive_reference_time"):
        ActionBridge().to_result(
            proposal_for(
                ActionName.CALENDAR_CREATE,
                {"title": "Møte", "days_offset": 1},
            ),
            bridge_context(
                utterance=normalize_utterance("planlegg møte i kalenderen"),
                reference_time=datetime(2026, 7, 14, 12, 0),
            ),
        )


@pytest.mark.parametrize(
    "date_value,time_value,error",
    [
        ("29.03.2026", "02:30", "invalid_time"),
        ("25.10.2026", "02:30", "ambiguous_time"),
    ],
)
def test_calendar_wall_time_uses_shared_oslo_resolver(
    date_value,
    time_value,
    error,
):
    with pytest.raises(PayloadValidationError, match=error):
        ActionBridge().to_result(
            proposal_for(
                ActionName.CALENDAR_CREATE,
                {"title": "Møte", "date": date_value, "time": time_value},
            ),
            bridge_context(
                utterance=normalize_utterance("planlegg møte i kalenderen"),
            ),
        )


def test_reminder_due_at_is_canonicalized_by_task6_payload_validation():
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_at": "2026-07-15T07:00:00+00:00"},
        ),
        bridge_context(utterance=normalize_utterance("påminn meg om legen")),
    )
    assert result is not None
    assert result.payload == {
        "reminder": {
            "action": "add",
            "text": "ringe legen",
            "due_at": "2026-07-15T09:00:00+02:00",
            "due_date": "15.07.2026",
            "time": "09:00",
            "timezone": "Europe/Oslo",
        }
    }


@pytest.mark.parametrize(
    "action,slots",
    [
        (ActionName.POLL_VOTE, {"option": 1}),
        (ActionName.POLL_EDIT, {"question": "Ny?"}),
        (ActionName.POLL_DELETE, {}),
        (ActionName.POLL_CLOSE, {}),
    ],
)
@pytest.mark.parametrize(
    "count,poll_id",
    [
        (0, None),
        (2, "poll-1"),
        (1, None),
        (True, "poll-1"),
        (1.0, "poll-1"),
        ("1", "poll-1"),
    ],
)
def test_implicit_poll_target_requires_exactly_one_bounded_active_poll(
    action,
    slots,
    count,
    poll_id,
):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(action, slots),
        bridge_context(
            utterance=normalize_utterance("stem i avstemningen"),
            active_poll_count=count,
            active_poll_id=poll_id,
        ),
    )
    assert result is None
    assert metrics.snapshot()["rejections"] == {"invalid_context": 1}


@pytest.mark.parametrize(
    "action,slots,envelope",
    [
        (ActionName.POLL_EDIT, {"question": "Ny?"}, "poll_edit"),
        (ActionName.POLL_DELETE, {}, "poll_delete"),
        (ActionName.POLL_CLOSE, {}, "poll_close"),
    ],
)
def test_implicit_poll_target_injects_stable_poll_id(action, slots, envelope):
    text = {
        ActionName.POLL_EDIT: "endre avstemningen",
        ActionName.POLL_DELETE: "slett avstemningen",
        ActionName.POLL_CLOSE: "lukk avstemningen",
    }[action]
    result = ActionBridge().to_result(
        proposal_for(action, slots),
        bridge_context(
            utterance=normalize_utterance(text),
            active_poll_count=1,
            active_poll_id=" poll-1 ",
        ),
    )
    assert result is not None
    assert result.payload[envelope]["poll_id"] == "poll-1"


def test_birthday_create_rejects_unresolved_user_but_edit_allows_author():
    metrics = NLUMetrics()
    assert ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.BIRTHDAY_CREATE,
            {"user_id": 999, "day": 1, "month": 5},
        ),
        bridge_context(utterance=normalize_utterance("registrer bursdag")),
    ) is None
    assert metrics.snapshot()["rejections"] == {"invalid_context": 1}

    result = ActionBridge().to_result(
        proposal_for(
            ActionName.BIRTHDAY_EDIT,
            {"user_id": 20, "day": 15, "month": 5},
        ),
        bridge_context(utterance=normalize_utterance("bursdagen min er 15.05")),
    )
    assert result is not None
    assert result.payload["birthday"]["user_id"] == 20


def test_semantic_gate_runs_before_model_clarification():
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.CLARIFY,
            {},
            clarification="Skal jeg slette kalenderen?",
        ),
        bridge_context(
            utterance=normalize_utterance("Når går toget?"),
            deterministic_route=IntentResult(BotIntent.SEARCH, 0.92),
            semantic_action_allowed=False,
        ),
    )
    assert result is None
    assert metrics.snapshot()["rejections"] == {"unsafe_semantic": 1}


@pytest.mark.parametrize(
    "action,slots,text",
    [
        (ActionName.CALENDAR_EDIT, {"target": "1", "title": "Ny"}, "kalenderen ser fin ut"),
        (ActionName.REMINDER_EDIT, {"number": 1, "text": "Ny"}, "påminningar kan vere nyttige"),
        (ActionName.REMINDER_COMPLETE, {"number": 1}, "reminders are useful"),
        (ActionName.CALENDAR_EDIT, {"target": "1", "title": "Ny"}, "calendar sync failed yesterday"),
        (ActionName.REMINDER_COMPLETE, {"number": 1}, "the reminder was deleted yesterday"),
        (ActionName.CALENDAR_EDIT, {"target": "1", "title": "Ny"}, "the meeting was moved yesterday"),
    ],
)
def test_domain_only_or_historical_descriptions_never_stage_writes(
    action,
    slots,
    text,
):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )
    assert result is None
    assert metrics.snapshot()["rejections"] == {"missing_action_evidence": 1}


@pytest.mark.parametrize(
    "text,action,slots,expected_intent,context_kwargs",
    [
        ("sørg for at jeg ringer legen i morgen", ActionName.REMINDER_CREATE, {"text": "ringe legen", "due_date": "15.07.2026"}, BotIntent.REMINDER_CREATE, {}),
        ("hugs å kjøpe mjølk i morgon", ActionName.REMINDER_CREATE, {"text": "kjøpe mjølk", "due_date": "15.07.2026"}, BotIntent.REMINDER_CREATE, {}),
        ("kainn du minn mæ på å ringe mamma i mårra?", ActionName.REMINDER_CREATE, {"text": "ringe mamma", "due_date": "15.07.2026"}, BotIntent.REMINDER_CREATE, {}),
        ("husk å se Inception", ActionName.WATCHLIST_ADD, {"title": "Inception", "type": "movie"}, BotIntent.WATCHLIST, {}),
        ("husk å se på Dune", ActionName.WATCHLIST_ADD, {"title": "Dune", "type": "movie"}, BotIntent.WATCHLIST, {}),
        ("hugs å sjå Arrival", ActionName.WATCHLIST_ADD, {"title": "Arrival", "type": "movie"}, BotIntent.WATCHLIST, {}),
        ("hugs å sjå på Arrival", ActionName.WATCHLIST_ADD, {"title": "Arrival", "type": "movie"}, BotIntent.WATCHLIST, {}),
        ("remember to watch The Bear", ActionName.WATCHLIST_ADD, {"title": "The Bear", "type": "series"}, BotIntent.WATCHLIST, {}),
        ("I need the meeting moved to Friday", ActionName.CALENDAR_EDIT, {"target": "meeting", "date": "17.07.2026"}, BotIntent.CALENDAR_EDIT, {}),
        ("kan du oppdatere påminninga til fredag?", ActionName.REMINDER_EDIT, {"number": 1, "due_date": "17.07.2026"}, BotIntent.REMINDER_EDIT, {}),
        ("jeg går for pizza", ActionName.POLL_VOTE, {"option": 1}, BotIntent.POLL_VOTE, {"active_poll_count": 1, "active_poll_id": "poll-1"}),
        ("husk dette: Carpe diem", ActionName.QUOTE_SAVE, {"text": "Carpe diem"}, BotIntent.QUOTE, {}),
        ("slett alle avtalene", ActionName.CALENDAR_CLEAR, {}, BotIntent.CALENDAR_CLEAR, {}),
        ("slett avstemningen", ActionName.POLL_DELETE, {"target": "siste"}, BotIntent.POLL_DELETE, {}),
        ("slett det første sitatet", ActionName.QUOTE_DELETE, {"index": 1}, BotIntent.QUOTE_DELETE, {}),
        ("fjern filmen nummer 1", ActionName.WATCHLIST_REMOVE, {"index": 1}, BotIntent.WATCHLIST, {}),
    ],
)
def test_natural_semantic_rescue_corpus_requires_confirmation(
    text,
    action,
    slots,
    expected_intent,
    context_kwargs,
):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(text),
            **context_kwargs,
        ),
    )
    assert result is not None
    assert result.intent is expected_intent
    assert result.requires_confirmation is True


@pytest.mark.parametrize(
    "text,action,slots,expected_intent",
    [
        (
            "Jeg trenger å bli minnet på å ringe legen i morgen",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
            BotIntent.REMINDER_CREATE,
        ),
        (
            "Eg treng å bli minna på å ringe legen i morgon",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
            BotIntent.REMINDER_CREATE,
        ),
        (
            "Would you mind reminding me to call the doctor tomorrow?",
            ActionName.REMINDER_CREATE,
            {"text": "call the doctor", "due_date": "15.07.2026"},
            BotIntent.REMINDER_CREATE,
        ),
        (
            "Jeg vil gjerne ha et møte med Ola i kalenderen i morgen",
            ActionName.CALENDAR_CREATE,
            {"title": "Møte med Ola", "date": "15.07.2026"},
            BotIntent.CALENDAR_ITEM,
        ),
        (
            "Eg vil gjerne ha eit møte med Ola i kalenderen i morgon",
            ActionName.CALENDAR_CREATE,
            {"title": "Møte med Ola", "date": "15.07.2026"},
            BotIntent.CALENDAR_ITEM,
        ),
        (
            "Would you mind putting a meeting with Ola in my calendar tomorrow?",
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting with Ola", "date": "15.07.2026"},
            BotIntent.CALENDAR_ITEM,
        ),
    ],
)
def test_bounded_natural_request_frames_stage_valid_model_proposals(
    text,
    action,
    slots,
    expected_intent,
):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is not None
    assert result.intent is expected_intent
    assert result.requires_confirmation is True


@pytest.mark.parametrize(
    "text,action,slots",
    [
        (
            "Jeg trenger ikke å bli minnet på å ringe legen i morgen",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
        ),
        (
            "Hva om jeg trenger å bli minnet på å ringe legen i morgen?",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
        ),
        (
            "Ola sa at han trenger å bli minnet på å ringe legen",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
        ),
        (
            "I would like pizza",
            ActionName.CALENDAR_CREATE,
            {"title": "Pizza", "date": "15.07.2026"},
        ),
        (
            "Would you mind explaining how calendars work?",
            ActionName.CALENDAR_CREATE,
            {"title": "Calendar lesson", "date": "15.07.2026"},
        ),
    ],
)
def test_natural_request_neighbors_do_not_authorize_model_writes(
    text,
    action,
    slots,
):
    assert (
        ActionBridge().to_result(
            proposal_for(action, slots, confidence=0.99),
            bridge_context(utterance=normalize_utterance(text)),
        )
        is None
    )


@pytest.mark.parametrize(
    "text,action,slots",
    [
        (
            "legg til møte i morgen og påminn meg om å ringe legen",
            ActionName.CALENDAR_CREATE,
            {"title": "Møte", "date": "15.07.2026"},
        ),
        (
            "påminn meg om å ringe legen og slett kalenderen",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
        ),
        (
            "påminn meg om legen og minn meg om å kjøpe melk",
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen", "due_date": "15.07.2026"},
        ),
        (
            "flytt møtet til fredag og endre tittelen til Nytt møte",
            ActionName.CALENDAR_EDIT,
            {
                "target": "møtet",
                "date": "17.07.2026",
                "title": "Nytt møte",
            },
        ),
        (
            "lag poll om mat og påminn meg om å handle",
            ActionName.POLL_CREATE,
            {"question": "Mat?", "options": ["Pizza", "Taco"]},
        ),
        (
            "slett poll 1 og 2",
            ActionName.POLL_DELETE,
            {"target": 1},
        ),
    ],
)
def test_multi_action_utterances_never_stage_one_partial_model_action(
    text,
    action,
    slots,
):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is None
    assert metrics.snapshot()["rejections"] == {"conflict": 1}


@pytest.mark.parametrize(
    "text",
    [
        "lukk poll etter 15 minutter",
        "slett avstemningen kanskje",
        "close the poll when everyone has voted",
    ],
)
def test_model_bridge_rejects_unsupported_poll_mutation_suffixes(text):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(ActionName.POLL_CLOSE, {}, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(text),
            active_poll_count=1,
            active_poll_id="poll-1",
        ),
    )

    assert result is None
    assert metrics.snapshot()["rejections"] == {"invalid_context": 1}


@pytest.mark.parametrize(
    "text,action,slots",
    [
        ("ikke slett kalenderen", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ('hva betyr "slett kalenderen"?', ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("> slett kalenderen\nHva betyr dette?", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("~~~\nslett kalenderen\n~~~", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("jeg vurderer kanskje å slette kalenderen", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("hvordan sletter man en kalender?", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("slett kalenderen, men ikke gjør det", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("hva skjer hvis du sletter kalenderen?", ActionName.CALENDAR_DELETE, {"target": "1"}),
        ("slett pollen", ActionName.POLL_DELETE, {"target": "siste"}),
        ("Mina har bursdag 15.05", ActionName.BIRTHDAY_EDIT, {"user_id": 20, "day": 15, "month": 5}),
        ("min venn Ola har bursdag 15.05", ActionName.BIRTHDAY_EDIT, {"user_id": 20, "day": 15, "month": 5}),
        ("my sister's birthday is 15.05", ActionName.BIRTHDAY_EDIT, {"user_id": 20, "day": 15, "month": 5}),
        ("kan du si hvordan jeg kan flytte møtet?", ActionName.CALENDAR_EDIT, {"target": "møtet", "date": "17.07.2026"}),
        ("kan du seie korleis eg kan flytte møtet?", ActionName.CALENDAR_EDIT, {"target": "møtet", "date": "17.07.2026"}),
        ("Ola said they need the meeting moved to Friday", ActionName.CALENDAR_EDIT, {"target": "meeting", "date": "17.07.2026"}),
        ("we discussed why they need the meeting moved to Friday", ActionName.CALENDAR_EDIT, {"target": "meeting", "date": "17.07.2026"}),
        ("the phrase my birthday is 15.05 is common", ActionName.BIRTHDAY_EDIT, {"user_id": 20, "day": 15, "month": 5}),
        ("remove shower 1", ActionName.WATCHLIST_REMOVE, {"index": 1}),
        ("fjern filmet opptak nummer 1", ActionName.WATCHLIST_REMOVE, {"index": 1}),
    ],
)
def test_semantic_safety_neighbors_never_stage(text, action, slots):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )
    assert result is None


def test_allows_mutation_is_an_independent_defense_in_depth_gate():
    unsafe_semantics = UtteranceSemantics(
        SpeechAct.DIRECTIVE,
        ("synthetic_false_mutation",),
        False,
    )
    metrics = NLUMetrics()
    with patch("core.action_bridge.analyze_utterance", return_value=unsafe_semantics):
        result = ActionBridge(metrics=metrics).to_result(
            proposal_for(
                ActionName.REMINDER_CREATE,
                {"text": "ringe legen"},
            ),
            bridge_context(utterance=normalize_utterance("påminn meg om legen")),
        )
    assert result is None
    assert metrics.snapshot()["rejections"] == {"unsafe_semantic": 1}


def test_same_canonical_low_confidence_route_is_rescued_semantically():
    deterministic = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.40,
        {"reminder": {"action": "add", "text": "ringe legen"}},
        "low_confidence_reminder",
        risk=IntentRisk.ADDITIVE,
    )
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.REMINDER_CREATE,
            {"text": "ringe legen"},
            confidence=0.91,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "påminn meg om å ringe legen"
            ),
            deterministic_route=deterministic,
        ),
    )

    assert result is not None
    assert result.intent is BotIntent.REMINDER_CREATE
    assert result.source is IntentSource.SEMANTIC
    assert result.requires_confirmation is True


@pytest.mark.parametrize(
    "action,slots,text",
    [
        (
            ActionName.REMINDER_CREATE,
            {"text": "ringe tannlegen"},
            "påminn meg om å ringe legen eller tannlegen",
        ),
        (
            ActionName.CALENDAR_CREATE,
            {"title": "Ringe legen", "date": "15.07.2026"},
            "påminn meg eller planlegg møte i kalenderen",
        ),
    ],
)
def test_low_confidence_route_conflict_returns_typed_clarification(
    action,
    slots,
    text,
):
    deterministic = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.40,
        {"reminder": {"action": "add", "text": "ringe legen"}},
        "low_confidence_reminder",
        risk=IntentRisk.ADDITIVE,
    )
    result = ActionBridge().to_result(
        proposal_for(action, slots),
        bridge_context(
            utterance=normalize_utterance(text),
            deterministic_route=deterministic,
        ),
    )

    assert result is not None
    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "deterministic_semantic_conflict"
    assert result.payload["choices"][0] == deterministic
    assert result.payload["choices"][1].source is IntentSource.SEMANTIC
    assert "clarification" in result.payload
    assert "prompt" not in result.payload
    assert result.requires_confirmation is False


def test_conflict_choices_are_deeply_detached_from_both_inputs():
    deterministic = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.40,
        {"reminder": {"action": "add", "text": "ringe legen"}},
        "low_confidence_reminder",
        risk=IntentRisk.ADDITIVE,
    )
    proposal = proposal_for(
        ActionName.REMINDER_CREATE,
        {"text": "ringe tannlegen"},
    )
    result = ActionBridge().to_result(
        proposal,
        bridge_context(
            utterance=normalize_utterance(
                "påminn meg om å ringe legen eller tannlegen"
            ),
            deterministic_route=deterministic,
        ),
    )
    assert result is not None
    first, second = result.payload["choices"]

    deterministic.payload["reminder"]["text"] = "endret etterpå"
    assert first.payload["reminder"]["text"] == "ringe legen"
    assert second.payload["reminder"]["text"] == "ringe tannlegen"


def test_validated_route_payload_is_deeply_detached_from_model_slots():
    options = ["Pizza", "Taco"]
    proposal = proposal_for(
        ActionName.POLL_CREATE,
        {"question": "Middag?", "options": options},
    )
    result = ActionBridge().to_result(
        proposal,
        bridge_context(utterance=normalize_utterance("lag en avstemning")),
    )
    assert result is not None
    routed_options = result.payload["poll"]["options"]
    assert routed_options == ["Pizza", "Taco"]
    assert routed_options is not options

    routed_options.append("Burger")
    assert options == ["Pizza", "Taco"]
    options.append("Sushi")
    assert routed_options == ["Pizza", "Taco", "Burger"]


def test_destructive_action_without_live_domain_is_rejected_and_counted():
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.REMINDER_DELETE,
            {"number": 1},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance("kan du slette nummer 1?")
        ),
    )
    assert result is None
    assert metrics.snapshot()["rejections"] == {
        "missing_domain_evidence": 1
    }


def test_destructive_domain_is_rechecked_after_arbiter_selection():
    metrics = NLUMetrics()

    def select_without_safety(_utterance, _semantics, candidates):
        return ArbitrationDecision(selected=tuple(candidates)[0])

    with patch(
        "core.action_bridge.arbitrate_candidates",
        side_effect=select_without_safety,
    ):
        result = ActionBridge(metrics=metrics).to_result(
            proposal_for(
                ActionName.REMINDER_DELETE,
                {"number": 1},
                confidence=0.99,
            ),
            bridge_context(
                utterance=normalize_utterance("slett nummer 1")
            ),
        )
    assert result is None
    assert metrics.snapshot()["rejections"] == {
        "missing_domain_evidence": 1
    }


def test_legacy_actions_bridge_to_typed_routes_with_zero_side_effects():
    save = parse_ai_response(
        "[SAVE_EVENT: Møte | 15.07.2026 | 14:00]"
    )
    dashboard = parse_ai_response("[SHOW_DASHBOARD]")
    assert save.legacy is True and save.proposal is not None
    assert dashboard.legacy is True and dashboard.proposal is not None

    bridge = ActionBridge()
    save_route = bridge.to_result(
        save.proposal,
        bridge_context(
            utterance=normalize_utterance(
                "planlegg møtet i kalenderen"
            )
        ),
    )
    dashboard_route = bridge.to_result(
        dashboard.proposal,
        bridge_context(utterance=normalize_utterance("vis oversikten")),
    )

    assert save_route is not None
    assert save_route.intent is BotIntent.CALENDAR_ITEM
    assert save_route.source is IntentSource.SEMANTIC
    assert save_route.risk is IntentRisk.ADDITIVE
    assert save_route.requires_confirmation is True
    assert dashboard_route is not None
    assert dashboard_route.intent is BotIntent.DASHBOARD
    assert dashboard_route.source is IntentSource.SEMANTIC
    assert dashboard_route.risk is IntentRisk.READ_ONLY
    assert dashboard_route.requires_confirmation is False

    executor = Mock()
    send = Mock()
    manager = Mock()
    executor.assert_not_called()
    send.assert_not_called()
    manager.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        "husk å se om døra er låst",
        "husk å se hvordan dette virker",
        "husk å se at døra er lukket",
        "husk å se til katten",
        "husk å se på barna",
        "hugs å sjå korleis dette verkar",
        "remember to watch if the door is locked",
        "remember to watch the kids",
    ],
)
def test_remember_to_check_is_not_reinterpreted_as_watchlist_add(text):
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "døra er låst", "type": "movie"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(text)
        ),
    )
    assert result is None


def test_check_frame_and_watchlist_add_never_stage_only_the_later_action():
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Dune", "type": "movie"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "husk å se om døra er låst, og legg Dune til filmlista"
            )
        ),
    )
    assert result is None
    assert metrics.snapshot()["rejections"] == {"conflict": 1}


@pytest.mark.parametrize(
    "read_request",
    ("show all my reminders", "list all my reminders"),
)
def test_model_watchlist_write_plus_read_never_stages_only_the_write(
    read_request,
):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception", "type": "movie"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "add Inception to my watchlist and " + read_request
            )
        ),
    )

    assert result is None
    assert metrics.snapshot()["rejections"] == {"conflict": 1}


def test_model_calendar_write_plus_pronoun_memory_read_never_stages_write():
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting", "date": "17.07.2026"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "create a meeting tomorrow and "
                "show me what you remember about me"
            )
        ),
    )

    assert result is None
    assert metrics.snapshot()["rejections"] == {"conflict": 1}


@pytest.mark.parametrize(
    "case",
    _CONTEXT_FREE_BRIDGE_SEQUENCE_CASES,
    ids=lambda case: case.id,
)
def test_model_write_plus_every_self_describing_contract_case_is_blocked(case):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting", "date": "17.07.2026"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "create a meeting tomorrow and " + case.text
            )
        ),
    )

    assert result is None, case.id
    assert metrics.snapshot()["rejections"] == {"conflict": 1}, case.id


def test_bridge_sequence_exemption_is_only_context_dependent_bare_poll_vote():
    exempt = tuple(
        case
        for case in _EXECUTABLE_SEQUENCE_CASES
        if case not in _CONTEXT_FREE_BRIDGE_SEQUENCE_CASES
    )

    # A bare numeric choice is not self-describing in the context-free bridge;
    # IntentRouter's fixture-aware collector probe covers it when an active poll
    # makes it independently executable.  Treating every "and 1" as an action
    # here would corrupt ordinary titles, dates, quantities, and list payloads.
    assert tuple((case.id, case.text) for case in exempt) == (
        ("nb-poll-vote", "1"),
    )
    assert len(_CONTEXT_FREE_BRIDGE_SEQUENCE_CASES) == 295


def test_context_dependent_sequence_guard_cannot_be_reopened_by_model_bridge():
    metrics = NLUMetrics()
    deterministic = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {"clarification": "Send én handling om gangen."},
        "multiple_actions_require_split",
        risk=IntentRisk.READ_ONLY,
        requires_confirmation=False,
    )
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting", "date": "17.07.2026"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "create a meeting tomorrow and 1"
            ),
            deterministic_route=deterministic,
            active_poll_count=1,
            active_poll_id="poll-1",
        ),
    )

    assert result is None
    assert metrics.snapshot()["rejections"] == {"conflict": 1}


@pytest.mark.parametrize(
    "example",
    HELP_EXAMPLES,
    ids=lambda example: example.id,
)
def test_model_write_plus_every_executable_help_example_never_stages_write(
    example,
):
    metrics = NLUMetrics()
    result = ActionBridge(metrics=metrics).to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting", "date": "17.07.2026"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(
                "create a meeting tomorrow and " + example.route_phrase
            )
        ),
    )

    assert result is None, example.id
    assert metrics.snapshot()["rejections"] == {"conflict": 1}, example.id


def test_norwegian_series_inflections_are_valid_watchlist_domain_evidence():
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_REMOVE,
            {"index": 1},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance("fjern serien nummer 1")
        ),
    )
    assert result is not None
    assert result.intent is BotIntent.WATCHLIST
    assert result.risk is IntentRisk.DESTRUCTIVE
    assert result.requires_confirmation is True

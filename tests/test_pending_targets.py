from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.intent_models import BotIntent, IntentResult, IntentRisk
from core.message_context import ConversationKey, ResolvedMention, RoutingContext
from core.mutation_coordinator import (
    CALENDAR_SHARED_SCOPE,
    MEMORY_STORE_SCOPE,
    REMINDER_STORE_SCOPE,
    MutationCoordinator,
)
from core.pending_actions import PendingTargetFamily
from core.pending_actions import PendingTargetGuard
from core.pending_targets import (
    PendingTargetError,
    PendingTargetResolver,
    conversation_turn_scope,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Europe/Oslo"))
KEY = ConversationKey(guild_id=10, channel_id=20, user_id=30)
ROUTING = RoutingContext(KEY, ResolvedMention(30, "Reidar"))


def _calendar_row(item_id: str, title: str) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "date": "16.07.2026",
        "time": "12:00",
        "type": "event",
        "description": "",
        "completed": False,
        "recurrence": None,
        "recurrence_sequence": 0,
    }


def _reminder_row(reminder_id: str, text: str) -> dict[str, object]:
    return {
        "reminder_id": reminder_id,
        "text": text,
        "due_at": "2026-07-16T12:00:00+02:00",
        "due_date": "16.07.2026",
        "time": "12:00",
        "timezone": "Europe/Oslo",
        "recurrence": None,
        "recurrence_sequence": 0,
        "completed": False,
    }


def _poll_row(poll_id: str, question: str = "Kaffe?") -> dict[str, object]:
    return {
        "poll_id": poll_id,
        "question": question,
        "options": [
            {"text": "Ja", "votes": []},
            {"text": "Nei", "votes": []},
        ],
        "status": "active",
    }


@pytest.fixture
def state():
    values = SimpleNamespace(
        calendar=[_calendar_row("cal-a", "Lege"), _calendar_row("cal-b", "Møte")],
        reminder=[_reminder_row("rem-a", "Ring lege"), _reminder_row("rem-b", "Kjøp melk")],
        polls=[_poll_row("poll-a")],
        watchlist=[
            {"title": "Dune", "type": "movie", "genre": "sci-fi", "comment": ""},
            {"title": "Arrival", "type": "movie", "genre": "sci-fi", "comment": ""},
        ],
        quotes=[
            {"text": "Vær snill", "author": "A"},
            {"text": "Vær modig", "author": "B"},
        ],
        birthdays={},
        memories={30: {"facts": ["liker kaffe"], "preferences": {"tone": "kort"}}},
    )
    return values


@pytest.fixture
def resolver(state):
    calendar = SimpleNamespace(
        snapshot_pending_items=Mock(
            side_effect=lambda *, reference_time: tuple(deepcopy(state.calendar))
        ),
        snapshot_all_item_ids=Mock(
            side_effect=lambda: tuple(sorted(str(row["id"]) for row in state.calendar))
        ),
    )
    monitor = SimpleNamespace(
        calendar=calendar,
        reminders=SimpleNamespace(
            snapshot_pending_items=Mock(
                side_effect=lambda scope_id: tuple(deepcopy(state.reminder))
            )
        ),
        poll=SimpleNamespace(
            snapshot_pending_items=Mock(
                side_effect=lambda scope_id, *, reference_time: tuple(
                    deepcopy(state.polls)
                )
            )
        ),
        watchlist=SimpleNamespace(
            snapshot_pending_items=Mock(
                side_effect=lambda scope_id: tuple(deepcopy(state.watchlist))
            )
        ),
        quote=SimpleNamespace(
            snapshot_pending_items=Mock(
                side_effect=lambda scope_id: tuple(deepcopy(state.quotes))
            )
        ),
        birthdays=SimpleNamespace(
            snapshot_pending_user=Mock(
                side_effect=lambda scope_id, user_id: deepcopy(
                    state.birthdays.get((scope_id, user_id))
                )
            )
        ),
        user_memory=SimpleNamespace(
            snapshot_pending_user=Mock(
                side_effect=lambda user_id: deepcopy(state.memories.get(user_id))
            )
        ),
    )
    return PendingTargetResolver(monitor, coordinator=MutationCoordinator())


def _route(
    intent: BotIntent,
    payload: dict[str, object],
    *,
    risk: IntentRisk = IntentRisk.DESTRUCTIVE,
) -> IntentResult:
    return IntentResult(
        intent,
        0.99,
        payload,
        risk=risk,
        requires_confirmation=True,
    )


@pytest.mark.parametrize(
    ("intent", "key"),
    [
        (BotIntent.CALENDAR_DELETE, "calendar_target"),
        (BotIntent.CALENDAR_COMPLETE, "calendar_target"),
        (BotIntent.CALENDAR_EDIT, "calendar_edit"),
    ],
)
def test_calendar_position_freezes_to_id_and_follows_reorder(
    resolver,
    state,
    intent,
    key,
):
    frozen = resolver.freeze(
        _route(intent, {key: {"target": "1"}}),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.route.payload[key]["target"] == "cal-a"
    assert frozen.guard.family is PendingTargetFamily.CALENDAR
    assert "tittel: Lege" in frozen.guard.display_detail
    assert "status: ikke fullført" in frozen.guard.display_detail
    assert "title:" not in frozen.guard.display_detail
    assert "completed:" not in frozen.guard.display_detail
    assert frozen.guard.display_fields[:3] == (
        ("tittel", "Lege"),
        ("dato", "16.07.2026"),
        ("tid", "12:00"),
    )
    assert ("status", "ikke fullført") in frozen.guard.display_fields
    assert ("type", "event") in frozen.guard.display_fields
    assert not any(
        label == "forekomst" for label, _ in frozen.guard.display_fields
    )
    state.calendar.reverse()

    claimed = resolver.revalidate(
        frozen.route,
        frozen.guard,
        ROUTING,
        reference_time=NOW,
    )
    assert claimed.payload[key]["target"] == "cal-a"


def test_calendar_target_preview_does_not_echo_stored_description(resolver, state):
    state.calendar[0]["description"] = "Privat møtekode 1234"

    frozen = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert "beskrivelse" not in dict(frozen.guard.display_fields)
    assert all(
        "Privat møtekode" not in value
        for _, value in frozen.guard.display_fields
    )


def test_calendar_target_preview_adds_number_only_when_public_fields_collide(
    resolver,
    state,
):
    state.calendar[1] = deepcopy(state.calendar[0])
    state.calendar[1]["id"] = "cal-b"
    state.calendar[1]["description"] = "Annen privat beskrivelse"

    frozen = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 2}},
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert ("nummer", "2") in frozen.guard.display_fields
    assert "beskrivelse" not in dict(frozen.guard.display_fields)


def test_calendar_collision_detection_uses_sanitized_public_fields(
    resolver,
    state,
):
    state.calendar[0]["title"] = "Pay\u202ePal"
    state.calendar[1] = deepcopy(state.calendar[0])
    state.calendar[1]["id"] = "cal-b"
    state.calendar[1]["title"] = "PayPal"
    state.calendar[1]["description"] = "Annen privat beskrivelse"

    frozen = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert ("tittel", "PayPal") in frozen.guard.display_fields
    assert ("nummer", "1") in frozen.guard.display_fields


def test_stored_recurrence_aliases_dedupe_only_when_semantically_equal(
    resolver,
    state,
):
    state.calendar[0].update(
        recurrence="weekly",
        recurrence_day="måndag",
        rrule_day="MO",
    )
    equivalent = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    assert equivalent.guard is not None
    assert [
        value
        for label, value in equivalent.guard.display_fields
        if label == "gjentakelsesdag"
    ] == ["måndag"]

    state.calendar[0].update(recurrence_day="monday", rrule_day="FR")
    conflicting = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    assert conflicting.guard is not None
    assert [
        value
        for label, value in conflicting.guard.display_fields
        if label == "gjentakelsesdag"
    ] == ["monday", "FR"]


def test_calendar_same_id_revision_change_fails_closed(resolver, state):
    route = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": 1}},
    )
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)
    state.calendar[0]["title"] = "Annet møte"

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


def test_unique_title_fragment_freezes_but_ambiguous_fragment_does_not(
    resolver,
    state,
):
    route = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": "lege"}},
    )
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)
    assert frozen.route.payload["calendar_target"]["target"] == "cal-a"

    state.calendar[1]["title"] = "Legetime nummer to"
    ambiguous = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": "leg"}},
    )
    with pytest.raises(PendingTargetError, match="ambiguous_target"):
        resolver.freeze(ambiguous, ROUTING, reference_time=NOW)


def test_duplicate_stable_id_is_rejected_before_staging(resolver, state):
    state.calendar[1]["id"] = "cal-a"
    route = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": 1}},
    )

    with pytest.raises(PendingTargetError, match="ambiguous_target"):
        resolver.freeze(route, ROUTING, reference_time=NOW)


def test_calendar_clear_guards_complete_id_set(resolver, state):
    frozen = resolver.freeze(
        _route(BotIntent.CALENDAR_CLEAR, {"calendar_clear": {}}),
        ROUTING,
        reference_time=NOW,
    )
    state.calendar.append(_calendar_row("cal-c", "Ny"))

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


@pytest.mark.parametrize(
    "intent",
    [
        BotIntent.REMINDER_EDIT,
        BotIntent.REMINDER_DELETE,
        BotIntent.REMINDER_COMPLETE,
    ],
)
def test_reminder_number_freezes_to_stable_id(resolver, state, intent):
    frozen = resolver.freeze(
        _route(intent, {"reminder": {"number": 2}}),
        ROUTING,
        reference_time=NOW,
    )
    assert frozen.route.payload["reminder"] == {"reminder_id": "rem-b"}
    assert frozen.guard.display_fields == (
        ("tekst", "Kjøp melk"),
        ("dato", "16.07.2026"),
        ("tid", "12:00"),
        ("status", "ikke fullført"),
    )
    state.reminder.reverse()

    claimed = resolver.revalidate(
        frozen.route,
        frozen.guard,
        ROUTING,
        reference_time=NOW,
    )
    assert claimed.payload["reminder"] == {"reminder_id": "rem-b"}


def test_recurring_reminder_occurrence_change_invalidates_guard(resolver, state):
    state.reminder[0]["recurrence"] = "weekly"
    frozen = resolver.freeze(
        _route(BotIntent.REMINDER_COMPLETE, {"reminder": {"number": 1}}),
        ROUTING,
        reference_time=NOW,
    )
    state.reminder[0]["recurrence_sequence"] = 1

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


def test_recurrence_day_aliases_render_once_without_raw_rrule(resolver, state):
    state.calendar[0].update(
        recurrence="weekly",
        recurrence_day="friday",
        rrule_day="FR",
    )
    frozen = resolver.freeze(
        _route(BotIntent.CALENDAR_DELETE, {"calendar_target": {"target": 1}}),
        ROUTING,
        reference_time=NOW,
    )

    recurrence_days = [
        value
        for label, value in frozen.guard.display_fields
        if label == "gjentakelsesdag"
    ]
    assert recurrence_days == ["friday"]
    assert "FR" not in dict(frozen.guard.display_fields).values()


@pytest.mark.parametrize(
    ("intent", "key"),
    [
        (BotIntent.POLL_VOTE, "vote"),
        (BotIntent.POLL_EDIT, "poll_edit"),
        (BotIntent.POLL_DELETE, "poll_delete"),
        (BotIntent.POLL_CLOSE, "poll_close"),
    ],
)
def test_poll_operations_freeze_id_and_full_proposition(
    resolver,
    state,
    intent,
    key,
):
    inner = {"poll_id": "poll-a"}
    if intent is BotIntent.POLL_VOTE:
        inner["option"] = 2
    frozen = resolver.freeze(
        _route(intent, {key: inner}),
        ROUTING,
        reference_time=NOW,
    )
    assert frozen.route.payload[key]["poll_id"] == "poll-a"
    if intent is BotIntent.POLL_VOTE:
        assert "Nei" in frozen.guard.display_detail
        assert frozen.guard.display_fields == (
            ("spørsmål", "Kaffe?"),
            ("valg", "Nei"),
        )
    else:
        assert frozen.guard.display_fields == (
            ("spørsmål", "Kaffe?"),
            ("alternativer", "1. Ja; 2. Nei"),
        )
    state.polls[0]["options"][1]["text"] = "Kanskje"

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


@pytest.mark.parametrize(
    ("intent", "payload_key", "state_name"),
    [
        (BotIntent.WATCHLIST, "watchlist", "watchlist"),
        (BotIntent.QUOTE_DELETE, "quote", "quotes"),
    ],
)
def test_fingerprint_target_follows_unique_reorder(
    resolver,
    state,
    intent,
    payload_key,
    state_name,
):
    inner = {"index": 1}
    if intent is BotIntent.WATCHLIST:
        inner["action"] = "remove"
    frozen = resolver.freeze(
        _route(intent, {payload_key: inner}),
        ROUTING,
        reference_time=NOW,
    )
    getattr(state, state_name).reverse()

    claimed = resolver.revalidate(
        frozen.route,
        frozen.guard,
        ROUTING,
        reference_time=NOW,
    )
    assert claimed.payload[payload_key]["index"] == 2


def test_schema_maximum_quote_can_still_be_frozen_for_deletion(resolver, state):
    state.quotes[0] = {"text": "*" * 2000, "author": "*" * 200}
    frozen = resolver.freeze(
        _route(BotIntent.QUOTE_DELETE, {"quote": {"action": "delete", "index": 1}}),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert dict(frozen.guard.display_fields)["tekst"].count(r"\*") == 2000


def test_watchlist_edit_guard_keeps_only_identity_fields_in_preview(resolver):
    frozen = resolver.freeze(
        _route(
            BotIntent.WATCHLIST,
            {
                "watchlist": {
                    "action": "edit",
                    "index": 1,
                    "title": "Dune: Part Two",
                    "comment": "Ny kommentar",
                }
            },
            risk=IntentRisk.MUTATING,
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert frozen.guard.display_fields == (
        ("tittel", "Dune"),
        ("type", "movie"),
    )


def test_watchlist_edit_guard_adds_number_when_public_fields_collide(
    resolver,
    state,
):
    state.watchlist[0]["title"] = "Dune Part"
    state.watchlist[1] = {
        "title": "Dune\nPart",
        "type": "movie",
        "genre": "drama",
        "comment": "Annen privat kommentar",
    }

    frozen = resolver.freeze(
        _route(
            BotIntent.WATCHLIST,
            {
                "watchlist": {
                    "action": "edit",
                    "index": 2,
                    "title": "Dune: Part Two",
                }
            },
            risk=IntentRisk.MUTATING,
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert frozen.guard.display_fields == (
        ("tittel", "Dune Part"),
        ("type", "movie"),
        ("nummer", "2"),
    )


def test_collision_identity_normalizes_canonically_equivalent_unicode(
    resolver,
    state,
):
    state.watchlist[0]["title"] = "Café"
    state.watchlist[1] = {
        "title": "Cafe\u0301",
        "type": "movie",
        "genre": "drama",
        "comment": "Annen privat kommentar",
    }

    frozen = resolver.freeze(
        _route(
            BotIntent.WATCHLIST,
            {
                "watchlist": {
                    "action": "edit",
                    "index": 2,
                    "title": "Ny tittel",
                }
            },
            risk=IntentRisk.MUTATING,
        ),
        ROUTING,
        reference_time=NOW,
    )

    assert frozen.guard is not None
    assert ("nummer", "2") in frozen.guard.display_fields


def test_stable_id_families_add_number_when_public_fields_collide(
    resolver,
    state,
):
    state.reminder[1] = deepcopy(state.reminder[0])
    state.reminder[1]["reminder_id"] = "rem-b"
    reminder = resolver.freeze(
        _route(
            BotIntent.REMINDER_DELETE,
            {"reminder": {"action": "delete", "number": 2}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    assert reminder.guard is not None
    assert ("nummer", "2") in reminder.guard.display_fields

    state.polls.append(deepcopy(state.polls[0]))
    state.polls[1]["poll_id"] = "poll-b"
    poll = resolver.freeze(
        _route(
            BotIntent.POLL_DELETE,
            {"poll_delete": {"target": 2}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    assert poll.guard is not None
    assert ("nummer", "2") in poll.guard.display_fields


def test_duplicate_fingerprint_is_ambiguous_at_freeze(resolver, state):
    state.watchlist.append(deepcopy(state.watchlist[0]))
    route = _route(
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "remove", "index": 1}},
    )

    with pytest.raises(PendingTargetError, match="ambiguous_target"):
        resolver.freeze(route, ROUTING, reference_time=NOW)


def test_birthday_create_freezes_absence_and_rejects_later_record(resolver, state):
    route = _route(
        BotIntent.BIRTHDAY_CREATE,
        {"birthday": {"user_id": 40, "display_name": "Ola", "day": 1, "month": 2}},
        risk=IntentRisk.ADDITIVE,
    )
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)
    state.birthdays[(10, 40)] = {"username": "Ola", "day": 1, "month": 2}

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


@pytest.mark.parametrize(
    "record",
    ["corrupt", {"username": "Ola", "day": True, "month": 2}],
)
def test_malformed_birthday_record_fails_closed(resolver, state, record):
    state.birthdays[(10, 40)] = record
    route = _route(
        BotIntent.BIRTHDAY_EDIT,
        {"birthday": {"user_id": 40, "day": 1, "month": 2}},
        risk=IntentRisk.MUTATING,
    )

    with pytest.raises(PendingTargetError, match="invalid_target_state"):
        resolver.freeze(route, ROUTING, reference_time=NOW)


def test_non_mapping_snapshot_row_fails_closed(resolver, state):
    state.reminder[:] = ["corrupt"]
    route = _route(
        BotIntent.REMINDER_DELETE,
        {"reminder": {"number": 1}},
    )

    with pytest.raises(PendingTargetError, match="invalid_target_state"):
        resolver.freeze(route, ROUTING, reference_time=NOW)


def test_memory_delete_hashes_complete_record_without_exposing_it(resolver, state):
    route = _route(BotIntent.MEMORY_DELETE, {"memory": {"action": "delete"}})
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)
    assert frozen.guard.label == "lagret brukerminne"
    assert "kaffe" not in frozen.guard.display_detail
    state.memories[30]["facts"].append("bor i Tromsø")

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


def test_malformed_memory_record_is_not_frozen_as_absent(resolver, state):
    state.memories[30] = ["private but malformed"]

    with pytest.raises(PendingTargetError, match="invalid_target_state"):
        resolver.freeze(
            _route(
                BotIntent.MEMORY_DELETE,
                {"memory": {"action": "delete"}},
            ),
            ROUTING,
            reference_time=NOW,
        )


@pytest.mark.parametrize("year", [0, 1899, 2101, 10**100])
def test_birthday_year_outside_supported_range_fails_closed(
    resolver,
    year,
):
    with pytest.raises(PendingTargetError, match="invalid_target_state"):
        resolver.freeze(
            _route(
                BotIntent.BIRTHDAY_CREATE,
                {
                    "birthday": {
                        "action": "add",
                        "user_id": 40,
                        "display_name": "Ola",
                        "day": 1,
                        "month": 2,
                        "year": year,
                    }
                },
                risk=IntentRisk.ADDITIVE,
            ),
            ROUTING,
            reference_time=NOW,
        )


def test_guard_family_must_match_route_family(resolver):
    memory_guard = PendingTargetGuard(
        PendingTargetFamily.MEMORY,
        None,
        None,
        "fingerprint",
        None,
        "lagret brukerminne",
    )
    route = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": "cal-a"}},
    )

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            route,
            memory_guard,
            ROUTING,
            reference_time=NOW,
        )


def test_guard_binds_exact_intent_and_stable_selector(resolver):
    frozen = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    tampered_routes = (
        replace(frozen.route, intent=BotIntent.CALENDAR_COMPLETE),
        replace(
            frozen.route,
            payload={"calendar_target": {"target": "cal-b"}},
        ),
    )

    for tampered in tampered_routes:
        with pytest.raises(PendingTargetError, match="target_changed"):
            resolver.revalidate(
                tampered,
                frozen.guard,
                ROUTING,
                reference_time=NOW,
            )


def test_guard_allows_confirmation_state_promotion_without_payload_change(
    resolver,
):
    frozen = resolver.freeze(
        _route(
            BotIntent.CALENDAR_DELETE,
            {"calendar_target": {"target": 1}},
        ),
        ROUTING,
        reference_time=NOW,
    )
    promoted = replace(
        frozen.route,
        requires_confirmation=not frozen.route.requires_confirmation,
    )

    rebound = resolver.revalidate(
        promoted,
        frozen.guard,
        ROUTING,
        reference_time=NOW,
    )
    assert rebound.payload == frozen.route.payload


@pytest.mark.parametrize(
    ("route", "corrected_payload", "changed_target_payload"),
    [
        (
            _route(
                BotIntent.CALENDAR_EDIT,
                {
                    "calendar_edit": {
                        "target": 1,
                        "changes": {"title": "Før"},
                    }
                },
                risk=IntentRisk.MUTATING,
            ),
            {
                "calendar_edit": {
                    "target": "cal-a",
                    "changes": {"title": "Etter"},
                }
            },
            {
                "calendar_edit": {
                    "target": "cal-b",
                    "changes": {"title": "Etter"},
                }
            },
        ),
        (
            _route(
                BotIntent.REMINDER_EDIT,
                {
                    "reminder": {
                        "action": "edit",
                        "number": 1,
                        "changes": {"text": "Før"},
                    }
                },
                risk=IntentRisk.MUTATING,
            ),
            {
                "reminder": {
                    "action": "edit",
                    "reminder_id": "rem-a",
                    "changes": {"text": "Etter"},
                }
            },
            {
                "reminder": {
                    "action": "edit",
                    "reminder_id": "rem-b",
                    "changes": {"text": "Etter"},
                }
            },
        ),
        (
            _route(
                BotIntent.POLL_EDIT,
                {
                    "poll_edit": {
                        "poll_id": "poll-a",
                        "question": "Før?",
                    }
                },
                risk=IntentRisk.MUTATING,
            ),
            {
                "poll_edit": {
                    "poll_id": "poll-a",
                    "question": "Etter?",
                }
            },
            {
                "poll_edit": {
                    "poll_id": "poll-b",
                    "question": "Etter?",
                }
            },
        ),
    ],
)
def test_corrected_edit_rebinds_only_the_same_immutable_target(
    resolver,
    route,
    corrected_payload,
    changed_target_payload,
):
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)
    corrected = replace(frozen.route, payload=corrected_payload)
    rebound_guard = resolver.rebind_corrected(
        frozen.route,
        corrected,
        frozen.guard,
    )

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            corrected,
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )
    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            frozen.route,
            rebound_guard,
            ROUTING,
            reference_time=NOW,
        )
    assert resolver.revalidate(
        corrected,
        rebound_guard,
        ROUTING,
        reference_time=NOW,
    ).payload == corrected_payload

    changed_target = replace(
        frozen.route,
        payload=changed_target_payload,
    )
    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.rebind_corrected(
            frozen.route,
            changed_target,
            frozen.guard,
        )


@pytest.mark.parametrize(
    ("route", "tampered"),
    [
        (
            _route(
                BotIntent.REMINDER_DELETE,
                {"reminder": {"number": 1}},
            ),
            lambda frozen: replace(
                frozen,
                intent=BotIntent.REMINDER_COMPLETE,
            ),
        ),
        (
            _route(
                BotIntent.POLL_VOTE,
                {"vote": {"poll_id": "poll-a", "option": 1}},
            ),
            lambda frozen: replace(
                frozen,
                payload={"vote": {"poll_id": "poll-a", "option": 2}},
            ),
        ),
        (
            _route(
                BotIntent.WATCHLIST,
                {"watchlist": {"action": "remove", "index": 1}},
            ),
            lambda frozen: replace(
                frozen,
                payload={
                    "watchlist": {
                        "action": "edit",
                        "index": 1,
                        "title": "Endret",
                    }
                },
            ),
        ),
        (
            _route(
                BotIntent.QUOTE_DELETE,
                {"quote": {"action": "delete", "index": 1}},
            ),
            lambda frozen: replace(
                frozen,
                intent=BotIntent.QUOTE_EDIT,
                payload={
                    "quote": {
                        "action": "edit",
                        "index": 1,
                        "text": "Endret",
                    }
                },
            ),
        ),
        (
            _route(
                BotIntent.BIRTHDAY_CREATE,
                {
                    "birthday": {
                        "action": "add",
                        "user_id": 40,
                        "display_name": "Ola",
                        "day": 1,
                        "month": 2,
                    }
                },
                risk=IntentRisk.ADDITIVE,
            ),
            lambda frozen: replace(
                frozen,
                payload={
                    "birthday": {
                        "action": "add",
                        "user_id": 40,
                        "display_name": "Ola",
                        "day": 2,
                        "month": 2,
                    }
                },
            ),
        ),
        (
            _route(
                BotIntent.MEMORY_DELETE,
                {"memory": {"action": "delete"}},
            ),
            lambda frozen: replace(
                frozen,
                payload={"memory": {"action": "view"}},
            ),
        ),
        (
            _route(
                BotIntent.CALENDAR_CLEAR,
                {"calendar_target": {"all": True}},
            ),
            lambda frozen: replace(
                frozen,
                payload={"calendar_target": {"all": False}},
            ),
        ),
    ],
)
def test_guard_rejects_same_family_proposition_mispair(
    resolver,
    route,
    tampered,
):
    frozen = resolver.freeze(route, ROUTING, reference_time=NOW)

    with pytest.raises(PendingTargetError, match="target_changed"):
        resolver.revalidate(
            tampered(frozen.route),
            frozen.guard,
            ROUTING,
            reference_time=NOW,
        )


def test_oversized_confirmation_detail_maps_to_typed_error(resolver, state):
    state.calendar[0]["description"] = "x" * 8_100
    route = _route(
        BotIntent.CALENDAR_DELETE,
        {"calendar_target": {"target": 1}},
    )

    with pytest.raises(
        PendingTargetError,
        match="confirmation_preview_too_large",
    ):
        resolver.freeze(route, ROUTING, reference_time=NOW)


def test_non_targeted_add_has_no_guard(resolver):
    route = _route(
        BotIntent.WATCHLIST,
        {"watchlist": {"action": "add", "title": "Dune"}},
        risk=IntentRisk.ADDITIVE,
    )
    assert resolver.freeze(route, ROUTING, reference_time=NOW).guard is None


def test_mutation_scopes_follow_backing_store(resolver):
    assert (
        resolver.mutation_scope(
            _route(BotIntent.CALENDAR_ITEM, {"calendar_item": {}}),
            KEY,
        )
        == CALENDAR_SHARED_SCOPE
    )
    assert (
        resolver.mutation_scope(
            _route(BotIntent.REMINDER_CREATE, {"reminder": {}}),
            KEY,
        )
        == REMINDER_STORE_SCOPE
    )
    assert (
        resolver.mutation_scope(
            _route(BotIntent.SET_LOCATION, {"location": "Tromsø"}),
            KEY,
        )
        == MEMORY_STORE_SCOPE
    )
    with pytest.raises(PendingTargetError, match="unsupported_mutation_scope"):
        resolver.mutation_scope(IntentResult(BotIntent.AI_CHAT, 1.0), KEY)


def test_naive_reference_time_fails_closed(resolver):
    with pytest.raises(PendingTargetError, match="naive_reference_time"):
        resolver.freeze(
            IntentResult(BotIntent.HELP, 1.0),
            ROUTING,
            reference_time=datetime(2026, 7, 15, 12, 0),
        )


def test_conversation_turn_scope_is_exact_and_stable():
    assert conversation_turn_scope(KEY) == (
        "conversation_turn",
        "guild:10:channel:20:user:30",
    )
    assert conversation_turn_scope(
        ConversationKey(None, 99, 30)
    ) == ("conversation_turn", "dm:channel:99:user:30")

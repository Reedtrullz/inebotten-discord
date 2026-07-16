"""Resolved-identity contract for natural birthday commands."""

from __future__ import annotations

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from core.message_context import ConversationKey, ResolvedMention, RoutingContext
from features.birthday_manager import parse_birthday_command
from tests.nlu_harness import build_production_router


def _context(*, mentions: tuple[ResolvedMention, ...] = ()) -> RoutingContext:
    return RoutingContext(
        key=ConversationKey(guild_id=123, channel_id=456, user_id=7),
        author=ResolvedMention(7, "Kari"),
        mentions=mentions,
    )


@pytest.mark.parametrize(
    "text",
    (
        "bursdagen min er 15.05",
        "min bursdag er 15.05",
        "eg har bursdag 15.05",
        "jeg har bursdag 15.05",
        "my birthday is 15.05",
    ),
)
def test_first_person_birthday_targets_author(text):
    assert parse_birthday_command(text, routing_context=_context()) == {
        "action": "add",
        "user_id": 7,
        "display_name": "Kari",
        "day": 15,
        "month": 5,
    }


@pytest.mark.parametrize(
    ("text", "day", "month", "year"),
    (
        ("bursdagen min er 5. mai", 5, 5, None),
        ("jeg har bursdag 5 mai", 5, 5, None),
        ("bursdag 20 desember", 20, 12, None),
        ("eg har bursdag 17. mai 1990", 17, 5, 1990),
        ("my birthday is May 5, 1990", 5, 5, 1990),
        ("could you add my birthday December 20?", 20, 12, None),
        ("kan du legge til bursdagen min 17. mai?", 17, 5, None),
    ),
)
def test_month_name_birthdays_bind_only_the_author(text, day, month, year):
    expected = {
        "action": "add",
        "user_id": 7,
        "display_name": "Kari",
        "day": day,
        "month": month,
    }
    if year is not None:
        expected["year"] = year

    assert parse_birthday_command(text, routing_context=_context()) == expected


@pytest.mark.parametrize(
    "text",
    (
        "bursdagen min er 31. februar",
        "jeg har bursdag 32 mai",
        "my birthday is February 30",
    ),
)
def test_invalid_month_name_birthdays_fail_closed(text):
    assert parse_birthday_command(text, routing_context=_context()) == {
        "action": "clarify",
        "reason": "unresolved_target",
    }


def test_resolved_discord_mention_is_the_only_external_identity_source():
    context = _context(mentions=(ResolvedMention(42, "Ola"),))

    assert parse_birthday_command(
        "bursdag <@42> 15.05", routing_context=context
    ) == {
        "action": "add",
        "user_id": 42,
        "display_name": "Ola",
        "day": 15,
        "month": 5,
    }
    assert parse_birthday_command(
        "bursdag <@99> 15.05", routing_context=context
    ) == {"action": "clarify", "reason": "unresolved_target"}


@pytest.mark.parametrize(
    "text",
    (
        "min bursdag er 15.05 <@42>",
        "jeg har bursdag 15.05 <@42>",
        "bursdag <@42> 15.05 <@7>",
    ),
)
def test_mentions_cannot_override_a_self_frame_or_create_two_targets(text):
    context = _context(
        mentions=(ResolvedMention(42, "Ola"), ResolvedMention(7, "Kari"))
    )

    assert parse_birthday_command(text, routing_context=context) == {
        "action": "clarify",
        "reason": "unresolved_target",
    }


@pytest.mark.parametrize(
    "text",
    (
        "Mina har bursdag 15.05",
        "Myra has birthday 15.05",
        "min venn Ola har bursdag 15.05",
        "bursdagen til min søster er 15.05",
        "my sister's birthday is 15.05",
    ),
)
def test_free_names_and_relational_possessives_never_bind_author(text):
    assert parse_birthday_command(text, routing_context=_context()) == {
        "action": "clarify",
        "reason": "unresolved_target",
    }


def test_birthday_list_scope_and_self_edit_are_canonical():
    assert parse_birthday_command(
        "kven har bursdag snart?", routing_context=_context()
    ) == {"action": "list", "scope": "upcoming"}
    assert parse_birthday_command(
        "vis bursdager", routing_context=_context()
    ) == {"action": "list", "scope": "all"}
    assert parse_birthday_command(
        "when is my birthday?", routing_context=_context()
    ) == {"action": "list", "scope": "self"}
    assert parse_birthday_command(
        "who has a birthday coming up?", routing_context=_context()
    ) == {"action": "list", "scope": "upcoming"}
    assert parse_birthday_command(
        "endre bursdagen min 20.05", routing_context=_context()
    ) == {
        "action": "edit",
        "user_id": 7,
        "day": 20,
        "month": 5,
    }


@pytest.mark.parametrize(
    ("fixture", "text", "intent", "payload"),
    (
        (
            EvalFixture.EMPTY,
            "bursdagen min er 15.05",
            BotIntent.BIRTHDAY_CREATE,
            {
                "birthday": {
                    "action": "add",
                    "user_id": 7,
                    "display_name": "Kari",
                    "day": 15,
                    "month": 5,
                }
            },
        ),
        (
            EvalFixture.EMPTY,
            "kven har bursdag snart?",
            BotIntent.BIRTHDAY_LIST,
            {"birthday": {"action": "list", "scope": "upcoming"}},
        ),
        (
            EvalFixture.EMPTY,
            "endre bursdagen min 20.05",
            BotIntent.BIRTHDAY_EDIT,
            {
                "birthday": {
                    "action": "edit",
                    "user_id": 7,
                    "day": 20,
                    "month": 5,
                }
            },
        ),
        (
            EvalFixture.MENTIONED_USER_42,
            "bursdag <@42> 15.05",
            BotIntent.BIRTHDAY_CREATE,
            {
                "birthday": {
                    "action": "add",
                    "user_id": 42,
                    "display_name": "Ola",
                    "day": 15,
                    "month": 5,
                }
            },
        ),
    ),
)
def test_production_router_emits_resolved_typed_birthday_payload(
    fixture, text, intent, payload
):
    result = build_production_router(fixture).route_help_example(text)

    assert result.intent is intent
    assert result.payload == payload


@pytest.mark.parametrize(
    ("text", "day", "month"),
    (
        ("bursdagen min er 5. mai", 5, 5),
        ("jeg har bursdag 5 mai", 5, 5),
        ("bursdag 20 desember", 20, 12),
        ("my birthday is May 5", 5, 5),
        ("kan du legge til bursdagen min 17. mai?", 17, 5),
    ),
)
def test_production_router_accepts_month_name_birthdays(text, day, month):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.BIRTHDAY_CREATE
    assert result.payload == {
        "birthday": {
            "action": "add",
            "user_id": 7,
            "display_name": "Kari",
            "day": day,
            "month": month,
        }
    }


@pytest.mark.parametrize(
    "text",
    (
        "Ola har bursdag 15.05",
        "Mina har bursdag 15.05",
        "my sister's birthday is 15.05",
        "bursdag <@99> 15.05",
    ),
)
def test_production_router_clarifies_unresolved_birthday_identity(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CLARIFY
    assert result.requires_confirmation is False

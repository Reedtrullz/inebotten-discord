"""Executable contract for every phrase advertised by the help catalog."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re

import pytest

from core.help_registry import HELP_CATEGORIES, HELP_EXAMPLES
from core.intent_models import BotIntent
from core.intent_payloads import ENVELOPE_KEYS, validate_intent_payload
from tests.nlu_harness import build_production_router


ACTION_ENVELOPES = frozenset(
    {"reminder", "birthday", "watchlist", "quote", "profile"}
)


def canonical_help_payload(result):
    payload = dict(result.payload)
    envelope = ENVELOPE_KEYS.get(result.intent)
    if envelope is None:
        return payload
    if result.intent is BotIntent.CALENDAR_LIST and payload == {}:
        return {}
    assert set(payload) == {envelope}
    raw = payload[envelope]
    validated = validate_intent_payload(
        result.intent,
        raw,
        source=result.source,
    )
    return {envelope: validated}


def route_operation(result, payload):
    envelope = ENVELOPE_KEYS.get(result.intent)
    if envelope in ACTION_ENVELOPES:
        action = payload[envelope]["action"]
        return f"{envelope}.{action}"
    memory = payload.get("memory")
    if isinstance(memory, Mapping) and isinstance(
        memory.get("action"),
        str,
    ):
        return f"memory.{memory['action']}"
    return result.intent.value


@pytest.mark.parametrize(
    "example",
    HELP_EXAMPLES,
    ids=lambda example: example.id,
)
def test_every_help_example_routes_to_the_complete_advertised_contract(
    example,
):
    adapter = build_production_router(example.fixture)
    result = adapter.route_help_example(example.route_phrase)
    payload = canonical_help_payload(result)
    assert result.intent is example.intent, example.id
    assert route_operation(result, payload) == example.operation, example.id
    assert result.risk is example.risk_level, example.id
    assert (
        result.requires_confirmation is example.requires_confirmation
    ), example.id
    expected = json.loads(example.expected_payload_json)
    assert payload == expected, example.id


@pytest.mark.parametrize(
    "example",
    HELP_EXAMPLES,
    ids=lambda example: example.id,
)
def test_valid_write_plus_every_executable_help_example_requires_split(
    example,
):
    result = build_production_router(example.fixture).route_help_example(
        f"create a meeting tomorrow and {example.route_phrase}"
    )

    assert result.intent is BotIntent.CLARIFY, example.id
    assert result.reason == "multiple_actions_require_split", example.id
    assert "calendar_item" not in result.payload, example.id


def test_help_example_ids_are_unique_and_copy_is_concrete():
    assert len({example.id for example in HELP_EXAMPLES}) == len(HELP_EXAMPLES)
    category_ids = {category.id for category in HELP_CATEGORIES}
    for example in HELP_EXAMPLES:
        assert example.category in category_ids
        assert example.display_phrase == example.route_phrase
        assert "[" not in example.display_phrase
        assert not re.search(
            r"\b(?:kode|code)\s+\S+",
            example.display_phrase,
        )
        assert example.display_phrase.strip()


def test_registry_contains_no_duplicate_advertised_phrase_per_locale():
    keys = [
        (example.locale, example.display_phrase.casefold())
        for example in HELP_EXAMPLES
    ]
    assert len(keys) == len(set(keys))

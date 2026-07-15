#!/usr/bin/env python3
"""Regression tests for the strict model-action protocol boundary."""

import json
import math

import pytest

from ai.action_schema import (
    ACTION_PROTOCOL_PROMPT,
    ACTION_SPECS,
    ActionName,
    ActionValidationError,
    SlotRule,
    _ATOM_FORMATS,
    is_valid_standalone_action_line,
    parse_ai_response,
    validate_action_object,
)


EXPECTED_ACTION_MANIFEST = (
    "NONE",
    "CLARIFY",
    "SHOW_DASHBOARD",
    "HELP",
    "CALENDAR_CREATE",
    "CALENDAR_LIST",
    "CALENDAR_SEARCH",
    "CALENDAR_COMPLETE",
    "CALENDAR_EDIT",
    "CALENDAR_DELETE",
    "CALENDAR_CLEAR",
    "REMINDER_CREATE",
    "REMINDER_LIST",
    "REMINDER_SEARCH",
    "REMINDER_COMPLETE",
    "REMINDER_EDIT",
    "REMINDER_DELETE",
    "POLL_CREATE",
    "POLL_LIST",
    "POLL_VOTE",
    "POLL_EDIT",
    "POLL_DELETE",
    "POLL_CLOSE",
    "BIRTHDAY_CREATE",
    "BIRTHDAY_LIST",
    "BIRTHDAY_EDIT",
    "WATCHLIST_ADD",
    "WATCHLIST_LIST",
    "WATCHLIST_SUGGEST",
    "WATCHLIST_EDIT",
    "WATCHLIST_REMOVE",
    "QUOTE_SAVE",
    "QUOTE_GET",
    "QUOTE_LIST",
    "QUOTE_EDIT",
    "QUOTE_DELETE",
)


EXPECTED_ACTION_SPEC_SNAPSHOT = {
    "NONE": ((), (), (), (), None, None),
    "CLARIFY": ((), (), (), (), None, None),
    "SHOW_DASHBOARD": ((), (), (), (), None, None),
    "HELP": ((), (), (), (), None, None),
    "CALENDAR_CREATE": (
        (("title", "S200"),),
        (
            ("date", "DATE"),
            ("time", "TIME"),
            ("type", "EVENT_TYPE"),
            ("recurrence", "RECURRENCE"),
            ("recurrence_day", "S200"),
            ("rrule_day", "S200"),
            ("days_offset", "DAY_OFFSET"),
            ("description", "TEXT2000"),
        ),
        (),
        ("date", "days_offset"),
        "calendar",
        None,
    ),
    "CALENDAR_LIST": ((), (), (), (), None, None),
    "CALENDAR_SEARCH": ((("query", "S500"),), (), (), (), None, None),
    "CALENDAR_COMPLETE": (
        (),
        (("target", "S200"), ("number", "POS_INT")),
        ("target", "number"),
        (),
        None,
        None,
    ),
    "CALENDAR_EDIT": (
        (("target", "S200"),),
        (
            ("title", "S200"),
            ("description", "TEXT2000"),
            ("date", "DATE"),
            ("time", "TIME"),
            ("recurrence", "NULLABLE_RECURRENCE"),
        ),
        (),
        ("title", "description", "date", "time", "recurrence"),
        "calendar",
        None,
    ),
    "CALENDAR_DELETE": (
        (),
        (("target", "S200"), ("number", "POS_INT")),
        ("target", "number"),
        (),
        None,
        None,
    ),
    "CALENDAR_CLEAR": ((), (), (), (), None, None),
    "REMINDER_CREATE": (
        (("text", "S500"),),
        (
            ("due_at", "DUE_AT"),
            ("due_date", "DATE"),
            ("time", "TIME"),
            ("timezone", "OSLO"),
            ("recurrence", "RECURRENCE"),
        ),
        (),
        (),
        "reminder",
        None,
    ),
    "REMINDER_LIST": ((), (), (), (), None, None),
    "REMINDER_SEARCH": ((("query", "S500"),), (), (), (), None, None),
    "REMINDER_COMPLETE": ((("number", "POS_INT"),), (), (), (), None, None),
    "REMINDER_EDIT": (
        (("number", "POS_INT"),),
        (
            ("text", "S500"),
            ("due_at", "NULLABLE_DUE_AT"),
            ("due_date", "NULLABLE_DATE"),
            ("time", "NULLABLE_TIME"),
            ("timezone", "OSLO"),
            ("recurrence", "NULLABLE_RECURRENCE"),
        ),
        (),
        ("text", "due_at", "due_date", "time", "recurrence"),
        "reminder",
        None,
    ),
    "REMINDER_DELETE": ((("number", "POS_INT"),), (), (), (), None, None),
    "POLL_CREATE": (
        (("question", "S300"), ("options", "OPTIONS")),
        (),
        (),
        (),
        None,
        None,
    ),
    "POLL_LIST": ((), (), (), (), None, None),
    "POLL_VOTE": (
        (("option", "POS_INT"),),
        (),
        (),
        (),
        None,
        "one_active_poll",
    ),
    "POLL_EDIT": (
        (),
        (("target", "POLL_TARGET"), ("question", "S300"), ("options", "OPTIONS")),
        (),
        ("question", "options"),
        None,
        "target_or_one_active_poll",
    ),
    "POLL_DELETE": (
        (),
        (("target", "POLL_TARGET"),),
        (),
        (),
        None,
        "target_or_one_active_poll",
    ),
    "POLL_CLOSE": (
        (),
        (("target", "POLL_TARGET"),),
        (),
        (),
        None,
        "target_or_one_active_poll",
    ),
    "BIRTHDAY_CREATE": (
        (("user_id", "POS_INT"), ("day", "DAY"), ("month", "MONTH")),
        (("year", "YEAR"),),
        (),
        (),
        None,
        "resolved_mention",
    ),
    "BIRTHDAY_LIST": (
        (),
        (("scope", "BIRTHDAY_SCOPE"),),
        (),
        (),
        None,
        None,
    ),
    "BIRTHDAY_EDIT": (
        (("user_id", "POS_INT"), ("day", "DAY"), ("month", "MONTH")),
        (("year", "YEAR"),),
        (),
        (),
        None,
        "author_or_resolved_mention",
    ),
    "WATCHLIST_ADD": (
        (("title", "S500"),),
        (("type", "MEDIA_TYPE"), ("genre", "S200"), ("comment", "TEXT2000")),
        (),
        (),
        None,
        None,
    ),
    "WATCHLIST_LIST": ((), (), (), (), None, None),
    "WATCHLIST_SUGGEST": (
        (),
        (("type", "MEDIA_TYPE"), ("genre", "S200")),
        (),
        (),
        None,
        None,
    ),
    "WATCHLIST_EDIT": (
        (("index", "POS_INT"),),
        (
            ("title", "S500"),
            ("type", "MEDIA_TYPE"),
            ("genre", "NULLABLE_S200"),
            ("comment", "NULLABLE_TEXT2000"),
        ),
        (),
        ("title", "type", "genre", "comment"),
        None,
        None,
    ),
    "WATCHLIST_REMOVE": ((("index", "POS_INT"),), (), (), (), None, None),
    "QUOTE_SAVE": (
        (("text", "TEXT2000"),),
        (("author", "S200"),),
        (),
        (),
        None,
        None,
    ),
    "QUOTE_GET": ((), (), (), (), None, None),
    "QUOTE_LIST": ((), (), (), (), None, None),
    "QUOTE_EDIT": (
        (("index", "POS_INT"),),
        (("text", "TEXT2000"), ("author", "S200")),
        (),
        ("text", "author"),
        None,
        None,
    ),
    "QUOTE_DELETE": ((("index", "POS_INT"),), (), (), (), None, None),
}


def action_line(
    action: str,
    confidence: float,
    slots: dict,
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


def action_object(
    action: str,
    slots: dict,
    *,
    confidence: float = 0.9,
    reply: str = "",
    clarification: str | None = None,
) -> dict:
    return {
        "action": action,
        "confidence": confidence,
        "slots": slots,
        "reply": reply,
        "clarification": clarification,
    }


def test_action_manifest_is_exact_and_ordered():
    assert tuple(action.value for action in ActionName) == EXPECTED_ACTION_MANIFEST


def test_registry_is_closed_and_exhaustive():
    assert set(ACTION_SPECS) == set(ActionName)
    assert len(ActionName) == 36


def test_action_specs_match_exact_amended_structural_contract():
    actual = {
        action.value: (
            tuple((name, rule.value) for name, rule in spec.required.items()),
            tuple((name, rule.value) for name, rule in spec.optional.items()),
            spec.exactly_one,
            spec.at_least_one,
            spec.temporal_family,
            spec.context_rule,
        )
        for action, spec in ACTION_SPECS.items()
    }
    assert actual == EXPECTED_ACTION_SPEC_SNAPSHOT


def test_parse_one_standalone_action_line():
    raw = (
        "Det kan jeg hjelpe med.\n"
        + action_line(
            "REMINDER_CREATE",
            0.91,
            {
                "text": "ringe legen",
                "due_at": "2026-07-15T09:00:00+02:00",
            },
        )
    )
    parsed = parse_ai_response(raw)
    assert parsed.text == "Det kan jeg hjelpe med."
    assert parsed.proposal is not None
    assert parsed.proposal.action is ActionName.REMINDER_CREATE
    assert parsed.proposal.slots["text"] == "ringe legen"
    assert parsed.errors == ()


@pytest.mark.parametrize(
    "raw",
    [
        action_line("UNKNOWN", 0.9, {}),
        action_line("CALENDAR_DELETE", 1.4, {"target": "1"}),
        action_line("CALENDAR_CREATE", 0.9, {"title": ""}),
        action_line("CALENDAR_CREATE", 0.9, {"title": "Møte"}),
        action_line("CALENDAR_DELETE", True, {"target": "1"}),
        action_line("POLL_CREATE", 0.9, {"question": "Q", "options": ["a", "a"]}),
        action_line("POLL_CREATE", 0.9, {"question": "Q" * 301, "options": ["a", "b"]}),
        action_line("QUOTE_EDIT", 0.9, {"index": 1}),
    ],
)
def test_invalid_action_protocol_is_inert_and_not_user_visible(raw):
    parsed = parse_ai_response(raw)
    assert parsed.text == ""
    assert parsed.proposal is None
    assert parsed.errors


def test_invalid_action_protocol_preserves_surrounding_prose():
    raw = "Beklager.\n" + action_line("CALENDAR_CREATE", 0.9, {"title": "Møte"})
    parsed = parse_ai_response(raw)
    assert parsed.text == "Beklager."
    assert parsed.proposal is None
    assert parsed.errors == ("at_least_one_slot_required",)


def test_calendar_days_offset_is_a_valid_temporal_anchor():
    parsed = parse_ai_response(
        action_line(
            "CALENDAR_CREATE",
            0.95,
            {"title": "Møte", "days_offset": 1, "time": "14:00"},
        )
    )
    assert parsed.proposal is not None
    assert parsed.proposal.slots["days_offset"] == 1


@pytest.mark.parametrize("offset", [-3650, 3650])
def test_calendar_days_offset_boundary_is_valid(offset):
    parsed = validate_action_object(
        action_object("CALENDAR_CREATE", {"title": "Møte", "days_offset": offset}, confidence=0.99)
    )
    assert parsed.slots["days_offset"] == offset


@pytest.mark.parametrize("offset", [-3651, 3651, 1_000_000_000])
def test_calendar_days_offset_outside_horizon_is_rejected(offset):
    with pytest.raises(ActionValidationError, match="invalid_slot:days_offset"):
        validate_action_object(
            action_object("CALENDAR_CREATE", {"title": "Møte", "days_offset": offset}, confidence=0.99)
        )


def test_calendar_edit_time_only_is_valid_until_target_date_is_frozen():
    proposal = validate_action_object(
        action_object("CALENDAR_EDIT", {"target": "1", "time": "10:00"}, confidence=0.99)
    )
    assert proposal.slots["time"] == "10:00"


def test_reminder_edit_time_only_is_valid_until_target_date_is_frozen():
    proposal = validate_action_object(
        action_object("REMINDER_EDIT", {"number": 1, "time": "10:00"}, confidence=0.99)
    )
    assert proposal.slots["time"] == "10:00"


@pytest.mark.parametrize("date_key", ["due_at", "due_date"])
def test_reminder_edit_explicit_null_date_cannot_pair_with_nonnull_time(date_key):
    with pytest.raises(ActionValidationError, match="invalid_temporal"):
        validate_action_object(
            action_object(
                "REMINDER_EDIT",
                {"number": 1, date_key: None, "time": "10:00"},
            )
        )


def test_reminder_edit_timezone_only_is_not_a_change():
    with pytest.raises(ActionValidationError, match="at_least_one_slot_required"):
        validate_action_object(
            action_object(
                "REMINDER_EDIT",
                {"number": 1, "timezone": "Europe/Oslo"},
            )
        )


@pytest.mark.parametrize("recurrence", ["daily", "weekly", "biweekly", "monthly", "yearly"])
def test_recurrence_registry_matches_typed_payload_contract(recurrence):
    proposal = validate_action_object(
        action_object(
            "REMINDER_CREATE",
            {"text": "Ring", "due_date": "15.07.2026", "recurrence": recurrence},
        )
    )
    assert proposal.slots["recurrence"] == recurrence


def test_invalid_recurrence_is_rejected_and_nullable_recurrence_can_clear():
    with pytest.raises(ActionValidationError, match="invalid_slot:recurrence"):
        validate_action_object(
            action_object(
                "CALENDAR_CREATE",
                {"title": "Møte", "date": "15.07.2026", "recurrence": "hver dag"},
            )
        )
    cleared = validate_action_object(
        action_object("REMINDER_EDIT", {"number": 1, "recurrence": None})
    )
    assert cleared.slots["recurrence"] is None


def test_new_recurring_reminder_requires_a_temporal_anchor():
    with pytest.raises(ActionValidationError, match="invalid_temporal"):
        validate_action_object(
            action_object(
                "REMINDER_CREATE",
                {"text": "Ring", "recurrence": "daily"},
            )
        )


def test_due_at_rejects_microseconds_and_canonicalizes_seconds():
    with pytest.raises(ActionValidationError, match="invalid_due_at"):
        validate_action_object(
            action_object(
                "REMINDER_CREATE",
                {"text": "Ring", "due_at": "2026-07-15T09:00:00.001+02:00"},
            )
        )
    proposal = validate_action_object(
        action_object(
            "REMINDER_CREATE",
            {"text": "Ring", "due_at": "2026-07-15T09:00+02:00"},
        )
    )
    assert proposal.slots["due_at"] == "2026-07-15T09:00:00+02:00"


def test_extreme_due_at_timezone_conversion_is_bounded():
    with pytest.raises(ActionValidationError, match="invalid_due_at"):
        validate_action_object(
            action_object(
                "REMINDER_CREATE",
                {"text": "Ring", "due_at": "0001-01-01T00:00:00+14:00"},
            )
        )


def test_two_proposals_are_ambiguous_and_inert():
    raw = "\n".join(
        [
            action_line("CALENDAR_DELETE", 1.0, {"target": "1"}),
            action_line("REMINDER_DELETE", 1.0, {"number": 1}),
        ]
    )
    parsed = parse_ai_response(raw)
    assert parsed.text == ""
    assert parsed.proposal is None
    assert parsed.errors == ("multiple_proposals",)


def test_fenced_json_is_inert_visible_text():
    raw = "~~~json\n" + action_line("CALENDAR_DELETE", 1.0, {"target": "1"}) + "\n~~~"
    parsed = parse_ai_response(raw)
    assert parsed.text == raw
    assert parsed.proposal is None
    assert parsed.errors == ()


@pytest.mark.parametrize(
    "opening,closing",
    [
        ("<!--", "-->"),
        ('<pre class="language-json">', "</pre>"),
        ("<code>", "</code>"),
        ("<script>", "</script>"),
        ("<style>", "</style>"),
        ("<textarea>", "</textarea>"),
        ("<?hidden", "?>"),
        ("<![CDATA[", "]]>") ,
    ],
)
def test_html_code_container_never_promotes_action(opening, closing):
    candidate = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    raw = f"{opening}\n{candidate}\n{closing}"
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ()


@pytest.mark.parametrize("opening", ['<x data=">">', "<x data='>'>"])
def test_quote_aware_generic_html_tag_keeps_action_inert(opening):
    candidate = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    raw = f"{opening}\n{candidate}\n\n"
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ()
    assert candidate in parsed.text


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_near_column_protocol_is_suppressed_but_never_executed(indent):
    candidate = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    parsed = parse_ai_response(indent + candidate)
    assert parsed.proposal is None
    assert parsed.text == ""
    assert parsed.errors == ("non_standalone_action",)


def test_four_space_protocol_example_remains_visible_and_inert():
    candidate = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    parsed = parse_ai_response("    " + candidate)
    assert parsed.proposal is None
    assert parsed.text == "    " + candidate


def test_deep_json_nesting_is_bounded():
    depth = 2000
    raw = (
        '{"action":"HELP","confidence":0.9,"slots":{"x":'
        + "[" * depth
        + "0"
        + "]" * depth
        + '},"reply":"","clarification":null}'
    )
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ("json_too_deep",)
    assert parsed.text == ""
    assert is_valid_standalone_action_line(raw) is False


def test_json_nesting_scan_ignores_brackets_and_escaped_quotes_in_strings():
    reply = ("[{}] \\\" " * 50).strip()
    raw = action_line("HELP", 0.9, {}, reply=reply)
    parsed = parse_ai_response(raw)
    assert parsed.proposal is not None
    assert parsed.proposal.reply == reply


def test_giant_json_integer_is_bounded_without_value_error_escape():
    raw = action_line("REMINDER_DELETE", 0.9, {"number": int("9" * 127)}).replace(
        "9" * 127, "9" * 5000
    )
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ("invalid_number",)
    assert is_valid_standalone_action_line(raw) is False


def test_unmatched_html_container_is_inert_to_eof_but_closed_one_recovers():
    candidate = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    assert parse_ai_response(f"<!--\n{candidate}").proposal is None
    assert parse_ai_response(f"<pre class=x\n{candidate}").proposal is None
    assert parse_ai_response(f"  <code\n{candidate}").proposal is None
    assert parse_ai_response(f"<script\n{candidate}").proposal is None
    assert parse_ai_response(f"<?hidden\n{candidate}").proposal is None
    assert parse_ai_response(f"<!DOCTYPE\n{candidate}").proposal is None
    assert parse_ai_response(f"<![CDATA[\n{candidate}").proposal is None
    assert parse_ai_response(f"<div>\n{candidate}").proposal is None
    parsed = parse_ai_response(f"<!-- example -->\n{candidate}")
    assert parsed.proposal is not None


def test_cleaner_cannot_hide_a_truncated_second_candidate():
    valid = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    truncated = '{"action":"REMINDER_DELETE","confidence":1.0'
    parsed = parse_ai_response(valid + "\n" + truncated)
    assert parsed.proposal is None
    assert parsed.errors == ("invalid_json",)
    assert parsed.text == ""


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_indented_multiline_second_fragment_blocks_first_proposal(indent):
    valid = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    raw = "\n".join(
        [
            valid,
            indent + "{",
            indent + '"action":"REMINDER_DELETE",',
            indent + '"confidence":1.0',
            indent + "}",
        ]
    )
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ("non_standalone_action",)


@pytest.mark.parametrize(
    "second,code",
    [
        ('{"confidence":', "invalid_json"),
        ("{}", "invalid_top_level"),
    ],
)
def test_any_second_zero_indent_json_fragment_invalidates_a_proposal(second, code):
    valid = action_line("CALENDAR_DELETE", 1.0, {"target": "1"})
    parsed = parse_ai_response(valid + "\n" + second)
    assert parsed.proposal is None
    assert parsed.text == ""
    assert parsed.errors == (code,)


def test_pretty_multiline_action_json_remains_visible_and_inert():
    raw = json.dumps(action_object("HELP", {}), indent=2)
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors == ()
    assert parsed.text == raw


@pytest.mark.parametrize("confidence", [math.nan, math.inf, -math.inf])
def test_non_finite_confidence_is_rejected(confidence):
    with pytest.raises(ValueError, match="invalid_confidence"):
        validate_action_object(action_object("HELP", {}, confidence=confidence))


def test_enormous_direct_confidence_is_bounded():
    with pytest.raises(ActionValidationError, match="invalid_confidence"):
        validate_action_object(action_object("HELP", {}, confidence=10**10_000))


def test_legacy_save_event_converts_to_calendar_create():
    parsed = parse_ai_response("[SAVE_EVENT: Møte | 15.07.2026 | 14:00]")
    assert parsed.proposal is not None
    assert parsed.proposal.action is ActionName.CALENDAR_CREATE
    assert parsed.proposal.confidence == 1.0
    assert parsed.legacy is True


def test_legacy_dashboard_converts_to_read_action():
    parsed = parse_ai_response("[SHOW_DASHBOARD]")
    assert parsed.proposal is not None
    assert parsed.proposal.action is ActionName.SHOW_DASHBOARD
    assert parsed.legacy is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            json.dumps(
                {
                    "action": "SAVE_EVENT",
                    "title": "Møte",
                    "date": "15.07.2026",
                    "time": "14:00",
                },
                separators=(",", ":"),
            ),
            ActionName.CALENDAR_CREATE,
        ),
        ('{"action":"SHOW_DASHBOARD"}', ActionName.SHOW_DASHBOARD),
    ],
)
def test_legacy_standalone_json_converts_without_mutating(raw, expected):
    parsed = parse_ai_response(raw)
    assert parsed.proposal is not None
    assert parsed.proposal.action is expected
    assert parsed.proposal.confidence == 1.0
    assert parsed.legacy is True
    assert parsed.text == ""


@pytest.mark.parametrize(
    "raw,code",
    [
        (
            '{"action":"SAVE_EVENT","title":"Møte","date":"15.07.2026"}',
            "invalid_legacy_action",
        ),
        (
            '{"action":"SAVE_EVENT","title":"Møte","date":"15.07.2026","time":"14:00","extra":true}',
            "invalid_legacy_action",
        ),
        ('{"action":"SHOW_DASHBOARD","extra":true}', "invalid_top_level"),
    ],
)
def test_malformed_legacy_json_is_inert_and_hidden(raw, code):
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.text == ""
    assert parsed.errors == (code,)


def test_prompt_is_generated_from_every_action():
    for action in ActionName:
        assert f"- {action.value}:" in ACTION_PROTOCOL_PROMPT


def test_prompt_contains_machine_validation_rules_and_exact_shape():
    atom_names = [
        definition.split("=", 1)[0]
        for definition in _ATOM_FORMATS.split("; ")
    ]
    for rule in SlotRule:
        assert atom_names.count(rule.value) == 1
    assert ACTION_PROTOCOL_PROMPT.count(_ATOM_FORMATS) == 1
    assert "DATE=exact valid DD.MM.YYYY" in ACTION_PROTOCOL_PROMPT
    assert "DUE_AT=aware whole-second ISO-8601 datetime with offset" in ACTION_PROTOCOL_PROMPT
    assert "DAY_OFFSET=integer -3650..3650 inclusive" in ACTION_PROTOCOL_PROMPT
    assert "EVENT_TYPE=literal event or task" in ACTION_PROTOCOL_PROMPT
    assert "MEDIA_TYPE=literal movie or series" in ACTION_PROTOCOL_PROMPT
    assert "BIRTHDAY_SCOPE=literal all or upcoming" in ACTION_PROTOCOL_PROMPT
    assert "RECURRENCE=literal daily, weekly, biweekly, monthly, or yearly" in ACTION_PROTOCOL_PROMPT
    assert "OPTIONS=array of 2-10 unique strings" in ACTION_PROTOCOL_PROMPT
    assert "exactly_one=target,number" in ACTION_PROTOCOL_PROMPT
    assert "at_least_one=date,days_offset" in ACTION_PROTOCOL_PROMPT
    assert "context=one_active_poll" in ACTION_PROTOCOL_PROMPT
    example = ACTION_PROTOCOL_PROMPT.split("Shape example: ", 1)[1].split("\n", 1)[0]
    decoded = json.loads(example)
    assert set(decoded) == {
        "action",
        "confidence",
        "slots",
        "reply",
        "clarification",
    }


def test_prompt_states_non_registry_protocol_constraints():
    assert "finite number from 0 through 1" in ACTION_PROTOCOL_PROMPT
    assert "reply must be a string of at most 2000 characters" in ACTION_PROTOCOL_PROMPT
    assert "CLARIFY requires a nonblank clarification" in ACTION_PROTOCOL_PROMPT
    assert "all other actions require clarification to be null or blank" in ACTION_PROTOCOL_PROMPT
    assert "one zero-indent, unfenced, single line" in ACTION_PROTOCOL_PROMPT


@pytest.mark.parametrize(
    "raw,code",
    [
        (
            '{"action":"HELP","action":"NONE","confidence":0.9,"slots":{},"reply":"","clarification":null}',
            "duplicate_json_key",
        ),
        (
            '{"action":"HELP","confidence":NaN,"slots":{},"reply":"","clarification":null}',
            "invalid_json_constant",
        ),
    ],
)
def test_non_strict_json_is_inert(raw, code):
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.text == ""
    assert parsed.errors == (code,)


def test_clarification_is_required_only_for_clarify():
    clarify = validate_action_object(
        action_object("CLARIFY", {}, clarification="  Når skal det skje?  ")
    )
    assert clarify.clarification == "Når skal det skje?"

    with pytest.raises(ActionValidationError, match="invalid_clarification"):
        validate_action_object(action_object("CLARIFY", {}))
    with pytest.raises(ActionValidationError, match="unexpected_clarification"):
        validate_action_object(action_object("HELP", {}, clarification="Hva?"))


@pytest.mark.parametrize(
    "action,slots,code",
    [
        ("CALENDAR_COMPLETE", {}, "exactly_one_slot_required"),
        ("CALENDAR_DELETE", {"target": "Møte", "number": 1}, "exactly_one_slot_required"),
        ("REMINDER_CREATE", {"text": "Ring", "time": "09:00"}, "invalid_temporal"),
        (
            "REMINDER_CREATE",
            {
                "text": "Ring",
                "due_at": "2026-07-15T09:00:00+02:00",
                "due_date": "16.07.2026",
            },
            "inconsistent_temporal",
        ),
        ("BIRTHDAY_CREATE", {"user_id": 1, "day": 31, "month": 2}, "invalid_birthday"),
        ("WATCHLIST_EDIT", {"index": 1}, "at_least_one_slot_required"),
        ("HELP", {"invented": "value"}, "unknown_slot"),
    ],
)
def test_cross_field_validation_rejects_invalid_shapes(action, slots, code):
    with pytest.raises(ActionValidationError, match=code):
        validate_action_object(action_object(action, slots))


def test_protocol_slots_are_normalized_and_immutable():
    proposal = validate_action_object(
        action_object("POLL_CREATE", {"question": "  Hva?  ", "options": [" Ja ", "Nei"]})
    )
    assert proposal.slots["question"] == "Hva?"
    assert proposal.slots["options"] == ["Ja", "Nei"]
    with pytest.raises(TypeError):
        proposal.slots["question"] = "Noe annet"


def test_plain_prose_and_non_string_responses_never_propose_actions():
    assert parse_ai_response("Bare en vanlig samtale.").proposal is None
    parsed = parse_ai_response(None)
    assert parsed.text == ""
    assert parsed.proposal is None
    assert parsed.errors == ("invalid_response_type",)

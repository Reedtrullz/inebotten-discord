"""Trust-boundary tests for lossless model-response cleaning."""

from __future__ import annotations

import pytest

from ai.action_schema import (
    is_suspected_action_candidate_line,
    parse_ai_response,
)
from ai.response_cleaner import (
    MAX_CLEANER_INPUT_BYTES,
    ResponseCleaningError,
    clean_thinking_response,
)


VALID_HELP = (
    '{"action":"HELP","confidence":0.9,"slots":{},'
    '"reply":"","clarification":null}'
)
VALID_DASHBOARD = (
    '{"action":"SHOW_DASHBOARD","confidence":0.95,"slots":{},'
    '"reply":"","clarification":null}'
)
MALFORMED_DELETE = (
    '{"action":"REMINDER_DELETE","confidence":0.99,'
    '"slots":{"number":1}'
)


@pytest.mark.parametrize("value", [None, b"", 0, False, [], {}])
def test_non_string_input_fails_with_one_bounded_code(value):
    with pytest.raises(ResponseCleaningError) as captured:
        clean_thinking_response(value)
    assert captured.value.code == "invalid_response_type"
    assert str(captured.value) == "invalid_response_type"


def test_empty_string_is_preserved():
    assert clean_thinking_response("") == ""


def test_unencodable_unicode_fails_with_one_bounded_code():
    with pytest.raises(ResponseCleaningError) as captured:
        clean_thinking_response("synlig\ud800tekst")
    assert captured.value.code == "invalid_response_encoding"
    assert str(captured.value) == "invalid_response_encoding"


@pytest.mark.parametrize(
    "reply",
    [
        "Hei!",
        "Klart!",
        "Wait",
        "Actually",
        "A: Hei",
        "💡",
        "Ja",
    ],
)
def test_short_and_reasoning_sounding_natural_replies_are_exact(reply):
    assert clean_thinking_response(reply) == reply


def test_markdown_fences_html_and_blank_lines_are_byte_order_preserved():
    raw = (
        "# Overskrift\n\n"
        "Første avsnitt.\n\n"
        "- første punkt\n- andre punkt\n\n"
        "~~~json data-long='behold dette'\n"
        '{"example":true}\n'
        "~~~\n"
        "    innrykket kode\n"
        '<x data=\">\">behold</x>\n'
        "<!-- vanlig HTML-kommentar -->\n"
        "Siste avsnitt.\n"
    )
    assert clean_thinking_response(raw) == raw


def test_valid_malformed_legacy_and_indented_candidates_are_unchanged():
    raw = "\n".join(
        [
            "Vanlig svar.",
            VALID_HELP,
            MALFORMED_DELETE,
            "[SHOW_DASHBOARD]",
            "  " + VALID_DASHBOARD,
            "    " + VALID_HELP,
        ]
    )
    cleaned = clean_thinking_response(raw)
    assert cleaned == raw
    assert [
        line
        for line in cleaned.splitlines()
        if is_suspected_action_candidate_line(line)
    ] == [VALID_HELP, MALFORMED_DELETE, "[SHOW_DASHBOARD]"]


def test_multiple_proposals_survive_for_authoritative_parser_rejection():
    raw = f"Svar.\n{VALID_HELP}\n{VALID_DASHBOARD}"
    cleaned = clean_thinking_response(raw)
    assert cleaned == raw
    parsed = parse_ai_response(cleaned)
    assert parsed.proposal is None
    assert parsed.errors == ("multiple_proposals",)


def test_fenced_and_html_contained_candidates_remain_inert_after_cleaning():
    raw = (
        "```json\n"
        f"{VALID_HELP}\n"
        "```\n"
        "<pre>\n"
        f"{VALID_DASHBOARD}\n"
        "</pre>"
    )
    cleaned = clean_thinking_response(raw)
    assert cleaned == raw
    parsed = parse_ai_response(cleaned)
    assert parsed.proposal is None
    assert parsed.errors == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Hei!<think>skjult<thinking>mer</thinking></think>\nKlart!",
            "Hei!\nKlart!",
        ),
        (
            "A<thinking>x<think>y</think>z</thinking>B",
            "AB",
        ),
        (
            "før<THINK data-kind='private'>hemmelig</THINK>etter",
            "føretter",
        ),
        (
            "1<think>a</think>2<thinking>b</thinking>3",
            "123",
        ),
        (
            "<think>alt skjult</think>synlig",
            "synlig",
        ),
    ],
)
def test_only_explicit_nested_reasoning_regions_are_removed(raw, expected):
    assert clean_thinking_response(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("synlig<think>skjult til EOF", "synlig"),
        ("synlig<thinking>y<think>z</think>", "synlig"),
        ("synlig<think>x</thinking>y", "synlig"),
        ("synlig<think>x<thinking>y</think>z</thinking>etter", "synlig"),
    ],
)
def test_unmatched_open_reasoning_region_is_inert_through_eof(raw, expected):
    assert clean_thinking_response(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "før</think>etter",
        "før</thinking>etter",
        "<think",
        "<thinking",
        "<thinkable>behold</thinkable>",
        "vanlig <think tekst uten slutt-tegn",
    ],
)
def test_unproven_or_unmatched_tag_text_is_preserved(raw):
    assert clean_thinking_response(raw) == raw


def test_unmatched_closing_tag_after_removed_region_is_preserved():
    raw = "a<think>x</think>b</think>c"
    assert clean_thinking_response(raw) == "ab</think>c"


def test_action_candidates_outside_reasoning_keep_original_provenance_order():
    raw = (
        f"{VALID_HELP}\n"
        "<think>private analyse\n"
        f"{VALID_DASHBOARD}\n"
        "</think>\n"
        f"{MALFORMED_DELETE}\n"
        "Svar."
    )
    cleaned = clean_thinking_response(raw)
    assert cleaned == f"{VALID_HELP}\n\n{MALFORMED_DELETE}\nSvar."
    candidates = tuple(
        line
        for line in cleaned.splitlines()
        if is_suspected_action_candidate_line(line)
    )
    assert candidates == (VALID_HELP, MALFORMED_DELETE)


def test_exact_ascii_byte_limit_is_accepted_without_truncation():
    raw = "x" * MAX_CLEANER_INPUT_BYTES
    assert clean_thinking_response(raw) == raw


def test_exact_multibyte_utf8_limit_is_accepted_without_truncation():
    raw = "ø" * (MAX_CLEANER_INPUT_BYTES // 2)
    assert len(raw.encode("utf-8")) == MAX_CLEANER_INPUT_BYTES
    assert clean_thinking_response(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "x" * (MAX_CLEANER_INPUT_BYTES + 1),
        "ø" * ((MAX_CLEANER_INPUT_BYTES // 2) + 1),
    ],
)
def test_oversize_utf8_fails_without_prefix_truncation(raw):
    with pytest.raises(ResponseCleaningError) as captured:
        clean_thinking_response(raw)
    assert captured.value.code == "response_too_large"
    assert str(captured.value) == "response_too_large"


def test_cleaner_does_not_import_or_call_action_parser_predicate():
    # Cleaner provenance is structural only: it must not decide whether any
    # response line is a valid, malformed, or executable action candidate.
    import ai.response_cleaner as cleaner

    assert "action_schema" not in cleaner.__dict__
    assert "is_suspected_action_candidate_line" not in cleaner.__dict__

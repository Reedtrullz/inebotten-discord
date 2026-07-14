import pytest

from core.utterance import normalize_utterance


def test_normalization_is_lossless_for_payload_text_and_masks_control_spans():
    utterance = normalize_utterance(
        '  Kan   <@!42> forklare “Slett Påminnelse 1” i morgen?  '
    )
    assert utterance.text == (
        'Kan <@!42> forklare “Slett Påminnelse 1” i morgen?'
    )
    assert utterance.folded == (
        'kan <@!42> forklare “slett påminnelse 1” i morgen?'
    )
    assert utterance.quoted_segments == ("Slett Påminnelse 1",)
    assert "42" not in utterance.control_text
    assert "slett" not in utterance.control_text
    assert "i morgen" in utterance.control_text


def test_blank_normalization_is_deterministic():
    utterance = normalize_utterance(" \n\t ")
    assert (
        utterance.text,
        utterance.folded,
        utterance.control_text,
    ) == ("", "", "")
    assert utterance.tokens == ()
    assert utterance.quoted_segments == ()


def test_markdown_code_is_inert_but_surrounding_prose_remains_live():
    utterance = normalize_utterance(
        "forklar `slett kalenderen` uten å gjøre det\n"
        "~~~text\nslett påminnelse 1\n~~~\n"
        "og vis hjelp"
    )
    assert "slett" not in utterance.control_text
    assert "kalenderen" not in utterance.tokens
    assert "påminnelse" not in utterance.tokens
    assert "forklar" in utterance.control_text
    assert "vis hjelp" in utterance.control_text


def test_unclosed_fence_is_inert_to_eof():
    utterance = normalize_utterance("eksempel:\n```\nslett kalenderen")
    assert "slett" not in utterance.control_text
    assert "kalenderen" not in utterance.tokens


def test_unclosed_inline_code_is_inert_to_line_end():
    utterance = normalize_utterance("eksempel: `slett kalenderen")
    assert "slett" not in utterance.control_text
    assert "kalenderen" not in utterance.tokens


@pytest.mark.parametrize(
    "text",
    [
        "«slett kalenderen» hva betyr det?",
        "'delete reminder 1' is an example",
        "> slett kalenderen\nHva betyr dette?",
    ],
)
def test_discord_quote_forms_are_inert_for_control_evidence(text):
    utterance = normalize_utterance(text)
    assert "slett" not in utterance.control_text
    assert "delete" not in utterance.control_text


def test_discord_multiline_quote_is_inert_through_eof():
    utterance = normalize_utterance(
        ">>> slett kalenderen\nopprett påminnelse i morgen"
    )
    assert utterance.control_text == ""
    assert utterance.tokens == ()
    assert utterance.quoted_segments == (
        "slett kalenderen opprett påminnelse i morgen",
    )


def test_discord_single_line_quote_leaves_following_prose_live():
    utterance = normalize_utterance(
        "> slett kalenderen\nvis hjelp"
    )
    assert "slett" not in utterance.control_text
    assert utterance.control_text == "vis hjelp"
    assert utterance.quoted_segments == ("slett kalenderen",)


def test_apostrophe_in_contraction_is_not_treated_as_a_quote():
    utterance = normalize_utterance("don't forget the meeting")
    assert "don't forget" in utterance.control_text

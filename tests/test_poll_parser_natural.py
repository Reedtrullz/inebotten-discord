"""Natural poll creation parsing contracts."""

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from features.poll_manager import parse_poll_command, parse_vote
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    ("text", "expected_options"),
    [
        ("avstemning Pizza eller burgere i kveld?", ["Pizza", "burgere"]),
        ("poll Pizza or Burger?", ["Pizza", "Burger"]),
        (
            "lag en avstemning: Hva spiser vi? Pizza, taco eller sushi",
            ["Pizza", "taco", "sushi"],
        ),
    ],
)
def test_documented_natural_choices_become_options_not_yes_no(
    text,
    expected_options,
):
    parsed = parse_poll_command(text)

    assert parsed is not None
    assert parsed["options"] == expected_options
    assert parsed["options"] not in (["Ja", "Nei"], ["Yes", "No"])


@pytest.mark.parametrize(
    "text",
    [
        "Pizza eller burger?",
        "Skal vi spise hjemme eller ute?",
        "https://example.com/a/b",
        "filsti /Users/test/Documents",
        "src/foo/bar",
        "./src/foo/bar.py",
        "docs/setup/getting-started.md",
        "kan du se på src/foo/bar?",
        "which file is docs/setup/getting-started.md?",
    ],
)
def test_choice_questions_without_poll_evidence_remain_inert(text):
    assert parse_poll_command(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "lag en avstemning: Mat? Pizza eller taco og påminn meg om å handle",
        "lag en avstemning: Mat? Pizza eller taco, og så påminn meg om å handle",
        "lag en avstemning: Mat? Pizza eller taco, deretter påminn meg om å handle",
        "lag en avstemning: Mat? Pizza eller taco, så påminn meg om å handle",
        "lag en avstemning: Mat? Pizza eller taco, påminn meg om å handle",
        "lag en avstemning: Mat? Pizza eller taco; påminn meg om å handle",
        "create a poll: Food? Pizza or tacos, then remind me to shop",
        "create a poll: Food? Pizza or tacos; after that delete the calendar",
    ],
)
def test_poll_plus_later_action_does_not_create_a_partial_poll(text):
    assert parse_poll_command(text) is None


@pytest.mark.parametrize(
    ("text", "expected_options"),
    [
        (
            "lag en avstemning: Tilbehør? Fish and chips, taco or pizza",
            ["Fish and chips", "taco", "pizza"],
        ),
        (
            "poll Chores / Wash and fold / Cook and clean / Rest",
            ["Wash and fold", "Cook and clean", "Rest"],
        ),
        (
            'poll Commands / "then delete" / keep / archive',
            ['"then delete"', "keep", "archive"],
        ),
    ],
)
def test_poll_payload_conjunctions_and_quoted_commands_remain_data(
    text, expected_options
):
    parsed = parse_poll_command(text)

    assert parsed is not None
    assert parsed["options"] == expected_options


def test_explicit_poll_still_owns_slash_delimited_options():
    parsed = parse_poll_command("poll Path / src-foo / src-bar")

    assert parsed is not None
    assert parsed["question"] == "Path"
    assert parsed["options"] == ["src-foo", "src-bar"]


def test_spaced_slash_poll_shorthand_remains_available():
    parsed = parse_poll_command("Mat / pizza / taco")

    assert parsed is not None
    assert parsed["question"] == "Mat"
    assert parsed["options"] == ["pizza", "taco"]


@pytest.mark.parametrize(
    ("text", "question", "options"),
    [
        (
            "kan du lage en avstemning: Hva spiser vi? Pizza eller taco",
            "Hva spiser vi?",
            ["Pizza", "taco"],
        ),
        (
            "kunne du opprette en avstemning: Mat? Pizza eller taco",
            "Mat?",
            ["Pizza", "taco"],
        ),
        (
            "can you make a poll: Food? Pizza or tacos",
            "Food?",
            ["Pizza", "tacos"],
        ),
        (
            "create a poll: Food? Pizza or tacos",
            "Food?",
            ["Pizza", "tacos"],
        ),
    ],
)
def test_polite_and_infinitive_poll_creation_owns_only_the_payload(
    text, question, options
):
    parsed = parse_poll_command(text)

    assert parsed is not None
    assert parsed["question"] == question
    assert parsed["options"] == options


@pytest.mark.parametrize(
    "text",
    [
        "jeg lagde en avstemning: Mat? Pizza eller taco",
        "we discussed a poll: Food? Pizza or tacos",
        "kan du forklare hvordan man lager en avstemning?",
    ],
)
def test_descriptive_poll_mentions_are_not_creation_commands(text):
    assert parse_poll_command(text) is None


@pytest.mark.parametrize(
    ("text", "option"),
    [
        ("2", 2),
        ("stem 2", 2),
        ("stem på alternativ to", 2),
        ("jeg stemmer på alternativ to", 2),
        ("eg stemmer på valget tre", 3),
        ("I vote for option two", 2),
    ],
)
def test_natural_first_person_vote_is_bounded_to_an_option(text, option):
    assert parse_vote(text) == option


@pytest.mark.parametrize(
    "text",
    [
        "Ola stemmer på alternativ to",
        "jeg stemte på alternativ to",
        "jeg vurderer å stemme på alternativ to",
        "I might vote for option two",
    ],
)
def test_vote_reports_and_hypotheticals_are_not_direct_votes(text):
    assert parse_vote(text) is None


@pytest.mark.parametrize(
    ("text", "intent", "envelope"),
    (
        ("kan du lukke avstemningen 1?", BotIntent.POLL_CLOSE, "poll_close"),
        (
            "kan du avslutte avstemminga 1?",
            BotIntent.POLL_CLOSE,
            "poll_close",
        ),
        (
            "kan du slette avstemningen 1?",
            BotIntent.POLL_DELETE,
            "poll_delete",
        ),
    ),
)
def test_polite_infinitive_poll_mutations_bind_one_active_target(
    text,
    intent,
    envelope,
):
    result = build_production_router(
        EvalFixture.ACTIVE_POLL
    ).route_help_example(text)

    assert result.intent is intent
    assert result.payload == {envelope: {"target": 1}}


def test_polite_infinitive_poll_edit_preserves_typed_change():
    result = build_production_router(
        EvalFixture.ACTIVE_POLL
    ).route_help_example(
        "kan du redigere avstemningen 1 spørsmål: Ny mat?"
    )

    assert result.intent is BotIntent.POLL_EDIT
    assert result.payload == {
        "poll_edit": {"target": 1, "question": "Ny mat?"}
    }


@pytest.mark.parametrize(
    "text",
    (
        "kan du forklare hvordan man lukker avstemningen 1?",
        "Ola sa kan du slette avstemningen 1",
        "ikke lukk avstemningen 1",
    ),
)
def test_inflected_poll_mentions_do_not_bypass_inert_guards(text):
    result = build_production_router(
        EvalFixture.ACTIVE_POLL
    ).route_help_example(text)

    assert result.intent not in {
        BotIntent.POLL_CLOSE,
        BotIntent.POLL_DELETE,
        BotIntent.POLL_EDIT,
    }

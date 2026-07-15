import pytest

from core.intent_arbitration import arbitrate_candidates
from core.intent_models import BotIntent, IntentCandidate, IntentRisk, IntentSource
from core.utterance import normalize_utterance
from core.utterance_semantics import analyze_utterance


def candidate(
    intent=BotIntent.CALENDAR_DELETE,
    risk=IntentRisk.DESTRUCTIVE,
    *,
    priority=20,
    order=10,
    confidence=0.95,
    specificity=2,
    action_terms=("slett", "delete"),
    domain_terms=("kalender", "calendar"),
    source=IntentSource.DETERMINISTIC,
):
    return IntentCandidate(
        intent,
        confidence,
        priority,
        order=order,
        reason="test_candidate",
        risk=risk,
        source=source,
        action_terms=action_terms,
        domain_terms=domain_terms,
        specificity=specificity,
    )


@pytest.mark.parametrize(
    "text",
    [
        "ikke slett kalenderen",
        "slett ikke kalenderen",
        'hva skjer hvis jeg skriver "slett kalenderen"?',
    ],
)
def test_unsafe_destructive_candidate_is_hard_blocked(text):
    utterance = normalize_utterance(text)
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), [candidate()]
    )
    assert decision.selected is None
    assert decision.blocked is True


def test_information_question_can_fall_through_to_read_candidate():
    utterance = normalize_utterance("Når går toget i morgen kl 8?")
    candidates = [
        candidate(BotIntent.CALENDAR_ITEM, IntentRisk.ADDITIVE),
        candidate(
            BotIntent.SEARCH,
            IntentRisk.READ_ONLY,
            priority=80,
            order=361,
            confidence=0.92,
            action_terms=(),
            domain_terms=("toget",),
        ),
    ]
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), candidates
    )
    assert decision.selected is not None
    assert decision.selected.intent is BotIntent.SEARCH


def test_specific_explicit_url_candidate_beats_generic_poll_parser():
    utterance = normalize_utterance("forkort https://example.com/a/b")
    candidates = [
        candidate(
            BotIntent.POLL_CREATE,
            IntentRisk.ADDITIVE,
            priority=50,
            order=150,
            confidence=0.95,
            specificity=0,
            action_terms=(),
            domain_terms=(),
        ),
        candidate(
            BotIntent.SHORTEN_URL,
            IntentRisk.READ_ONLY,
            priority=60,
            order=330,
            confidence=0.90,
            specificity=3,
            action_terms=("forkort",),
            domain_terms=("https://example.com/a/b",),
        ),
    ]
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), candidates
    )
    assert decision.selected is not None
    assert decision.selected.intent is BotIntent.SHORTEN_URL


def test_equal_explicit_cross_domain_candidates_clarify():
    utterance = normalize_utterance("lag møte og påminnelse i morgen")
    candidates = [
        candidate(
            BotIntent.CALENDAR_ITEM,
            IntentRisk.ADDITIVE,
            priority=35,
            order=123,
            confidence=0.95,
            specificity=3,
            domain_terms=("møte",),
        ),
        candidate(
            BotIntent.REMINDER_CREATE,
            IntentRisk.ADDITIVE,
            priority=35,
            order=122,
            confidence=0.93,
            specificity=3,
            domain_terms=("påminnelse",),
        ),
    ]
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), candidates
    )
    assert decision.selected is not None
    assert decision.selected.intent is BotIntent.CLARIFY
    assert tuple(item.intent for item in decision.alternatives) == (
        BotIntent.REMINDER_CREATE,
        BotIntent.CALENDAR_ITEM,
    )


def test_equal_non_ambiguity_tier_preserves_source_order():
    utterance = normalize_utterance("status hjelp")
    candidates = [
        candidate(
            BotIntent.HELP,
            IntentRisk.READ_ONLY,
            priority=10,
            order=30,
            confidence=0.95,
            specificity=4,
            action_terms=(),
            domain_terms=("hjelp",),
        ),
        candidate(
            BotIntent.STATUS,
            IntentRisk.READ_ONLY,
            priority=10,
            order=20,
            confidence=0.93,
            specificity=4,
            action_terms=(),
            domain_terms=("status",),
        ),
    ]
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), candidates
    )
    assert decision.selected is not None
    assert decision.selected.intent is BotIntent.STATUS
    assert decision.alternatives == ()


def test_confirmation_policy_is_applied_after_selection():
    utterance = normalize_utterance("slett kalenderen")
    selected = arbitrate_candidates(
        utterance, analyze_utterance(utterance), [candidate()]
    ).selected
    assert selected is not None
    assert selected.requires_confirmation is True


def test_positive_display_number_is_exact_bounded_target_evidence():
    utterance = normalize_utterance("slett 2")
    selected = arbitrate_candidates(
        utterance,
        analyze_utterance(utterance),
        [
            candidate(
                domain_terms=("2",),
                action_terms=("slett",),
                specificity=3,
            )
        ],
    ).selected
    assert selected is not None
    assert selected.intent is BotIntent.CALENDAR_DELETE
    assert selected.risk is IntentRisk.DESTRUCTIVE
    assert selected.requires_confirmation is True


def test_semantic_write_requires_confirmation_but_deterministic_add_does_not():
    utterance = normalize_utterance("lag møte i morgen")
    semantic = candidate(
        BotIntent.CALENDAR_ITEM,
        IntentRisk.ADDITIVE,
        priority=35,
        source=IntentSource.SEMANTIC,
        action_terms=("lag",),
        domain_terms=("møte",),
    )
    deterministic = candidate(
        BotIntent.CALENDAR_ITEM,
        IntentRisk.ADDITIVE,
        priority=35,
        source=IntentSource.DETERMINISTIC,
        action_terms=("lag",),
        domain_terms=("møte",),
    )
    semantic_result = arbitrate_candidates(
        utterance, analyze_utterance(utterance), [semantic]
    ).selected
    deterministic_result = arbitrate_candidates(
        utterance, analyze_utterance(utterance), [deterministic]
    ).selected
    assert semantic_result is not None and semantic_result.requires_confirmation
    assert deterministic_result is not None
    assert not deterministic_result.requires_confirmation

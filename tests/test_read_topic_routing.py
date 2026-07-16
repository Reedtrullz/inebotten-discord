"""Compact read topics accept bounded requests without hijacking statements."""

from __future__ import annotations

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from core.utterance import normalize_utterance
from core.utterance_semantics import SpeechAct, analyze_utterance
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    ("text", "intent"),
    (
        ("dagens ord", BotIntent.WORD_OF_DAY),
        ("kan du gi meg dagens ord?", BotIntent.WORD_OF_DAY),
        ("kan du gje meg dagens ord?", BotIntent.WORD_OF_DAY),
        ("nordlys", BotIntent.AURORA),
        ("kan du vise meg nordlys?", BotIntent.AURORA),
        ("could you show me the aurora?", BotIntent.AURORA),
        ("what is the aurora forecast?", BotIntent.AURORA),
        ("what's the aurora forecast?", BotIntent.AURORA),
        ("could you show me the aurora forecast?", BotIntent.AURORA),
        ("kan du vise meg nordlysvarselet?", BotIntent.AURORA),
        ("hva er nordlysvarselet?", BotIntent.AURORA),
        ("what's the word of the day?", BotIntent.WORD_OF_DAY),
        ("lær meg et ord", BotIntent.WORD_OF_DAY),
        ("kan du lære meg et ord?", BotIntent.WORD_OF_DAY),
        ("lær meg eit ord", BotIntent.WORD_OF_DAY),
        ("teach me a word", BotIntent.WORD_OF_DAY),
        ("could you teach me a word?", BotIntent.WORD_OF_DAY),
        ("what's today's word?", BotIntent.WORD_OF_DAY),
        ("what’s today’s word?", BotIntent.WORD_OF_DAY),
        ("kan jeg se nordlys i kveld?", BotIntent.AURORA),
        ("blir det nordlys i kveld?", BotIntent.AURORA),
        ("er det nordlys i kveld?", BotIntent.AURORA),
        ("will I see aurora tonight?", BotIntent.AURORA),
        ("can I see aurora tonight?", BotIntent.AURORA),
        ("is there aurora tonight?", BotIntent.AURORA),
        ("daglig oppsummering", BotIntent.DAILY_DIGEST),
        ("kan du vise daglig oppsummering?", BotIntent.DAILY_DIGEST),
        ("could you show me the daily digest?", BotIntent.DAILY_DIGEST),
        ("could you give me a daily summary?", BotIntent.DAILY_DIGEST),
        ("kan du vise meg dagens oppsummering?", BotIntent.DAILY_DIGEST),
    ),
)
def test_bounded_read_topic_requests_route(text, intent):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent


@pytest.mark.parametrize(
    ("text", "intent"),
    (
        ("teach me a word please", BotIntent.WORD_OF_DAY),
        ("lær meg et ord takk", BotIntent.WORD_OF_DAY),
        (
            "if you have time could you teach me a word",
            BotIntent.WORD_OF_DAY,
        ),
        (
            "could you if you have time teach me a word",
            BotIntent.WORD_OF_DAY,
        ),
        (
            "if you have time could you give me the word of the day",
            BotIntent.WORD_OF_DAY,
        ),
        (
            "could you if you have time give me the word of the day",
            BotIntent.WORD_OF_DAY,
        ),
        ("show me the aurora forecast please", BotIntent.AURORA),
        ("vis meg nordlysvarselet takk", BotIntent.AURORA),
        (
            "if you have time could you show me the aurora forecast",
            BotIntent.AURORA,
        ),
        (
            "could you if you have time show me the aurora forecast",
            BotIntent.AURORA,
        ),
        ("show me daily digest please", BotIntent.DAILY_DIGEST),
        ("vis meg daglig oppsummering takk", BotIntent.DAILY_DIGEST),
        (
            "if you have time could you show me daily digest",
            BotIntent.DAILY_DIGEST,
        ),
        (
            "could you if you have time show me daily digest",
            BotIntent.DAILY_DIGEST,
        ),
    ),
)
def test_read_topics_share_the_bounded_courtesy_shell(text, intent):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent


@pytest.mark.parametrize(
    "text",
    (
        "if you have time could you give me the word of the day",
        "could you if you have time give me the word of the day",
    ),
)
def test_word_of_day_courtesy_orders_are_directives_not_hypotheticals(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    (
        "Aurora is a singer",
        "I saw the aurora yesterday",
        "jeg så nordlys i går",
        "word of the day is a phrase",
        "dagens ord var vanskelig",
        "daily digest is a newsletter format",
        "oppsummering er et substantiv",
        "I teach a word every day",
        "jeg lærer et ord hver dag",
        "Ola sa lær meg et ord",
        "kan du ikke lære meg et ord",
        "can I see Aurora perform tonight?",
        "kan jeg se Aurora på konsert?",
        "there is aurora tonight",
        "if you teach me a word, I will remember it",
        "what happens if you show me the aurora forecast?",
        "could you not show me daily digest",
        "Ola said show me the aurora forecast please",
    ),
)
def test_read_topic_statements_remain_conversation(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.AI_CHAT

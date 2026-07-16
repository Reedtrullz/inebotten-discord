"""Regression coverage for bounded conversational routing aliases."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ai.action_schema import ActionName
from cal_system.reminder_manager import parse_reminder_command
from core.action_bridge import ActionBridge
from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from core.utterance import normalize_utterance
from tests.nlu_harness import build_production_router
from tests.nlu_test_support import bridge_context, proposal_for


REFERENCE = datetime(2026, 7, 14, 12, tzinfo=ZoneInfo("Europe/Oslo"))


P2_READ_ALIASES = (
    ("Do I have anything on my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Is there anything on my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Anything on my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Check my calendar", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Can you check my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Could you check my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What do I have on my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What have I got on my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What do I have planned?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What have I got planned?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What are my plans?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Do I have plans?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("What's going on in my calendar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("List my calendar", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Har jeg noe i kalenderen?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Har jeg noe i kalenderen min?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Er det noe i kalenderen min?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Er det noko i kalenderen min?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Sjekk kalenderen min", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Kan du sjekke kalenderen min?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Kunne du sjekke kalenderen min?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Hva har jeg planlagt?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Kva har eg planlagt?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Har jeg planer?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Har eg planar?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Hva er planene mine?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Kva er planane mine?", BotIntent.CALENDAR_LIST, ActionName.CALENDAR_LIST),
    ("Check my reminders", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Can you check my reminders?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Could you check my reminders?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Are there any reminders?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Any reminders?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Er det noen påminnelser?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Er det nokon påminningar?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Sjekk påminnelsene mine", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Do I need to remember anything?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Is there anything I should remember?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Er det noe jeg må huske?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Er det noko eg må hugse?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Må jeg huske noe?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("Må eg hugse noko?", BotIntent.REMINDER_LIST, ActionName.REMINDER_LIST),
    ("What are you capable of?", BotIntent.HELP, ActionName.HELP),
    ("What capabilities do you have?", BotIntent.HELP, ActionName.HELP),
    ("Show me what you can do", BotIntent.HELP, ActionName.HELP),
    ("How can you help?", BotIntent.HELP, ActionName.HELP),
    ("Hva kan jeg bruke deg til?", BotIntent.HELP, ActionName.HELP),
)

_CALENDAR_TOMORROW_PAYLOAD = {
    "calendar_list": {"date": "15.07.2026"}
}
_REMINDER_TOMORROW_PAYLOAD = {
    "reminder": {"action": "list", "due_date": "15.07.2026"}
}
P2_FILTERED_READ_ALIASES = tuple(
    (
        text,
        BotIntent.CALENDAR_LIST,
        ActionName.CALENDAR_LIST,
        _CALENDAR_TOMORROW_PAYLOAD,
    )
    for text in (
        "What do I have planned tomorrow?",
        "Do I have anything planned tomorrow?",
        "Hva har jeg planlagt i morgen?",
        "Kva har eg planlagt i morgon?",
        "What are my plans tomorrow?",
        "What plans do I have tomorrow?",
        "What have I planned for tomorrow?",
        "What have I got planned tomorrow?",
        "Do I have plans tomorrow?",
        "What's going on in my calendar tomorrow?",
        "Har jeg planer i morgen?",
        "Har eg planar i morgon?",
        "Hva er planene mine i morgen?",
        "Kva er planane mine i morgon?",
        "Hvilke planer har jeg i morgen?",
        "Kva planar har eg i morgon?",
        "Check my calendar tomorrow",
        "Can you check my calendar tomorrow?",
        "Do I have anything on my calendar tomorrow?",
        "Is there anything on my calendar tomorrow?",
        "Anything on my calendar tomorrow?",
        "Sjekk kalenderen min i morgen",
        "Er det noe i kalenderen min i morgen?",
        "Sjekk kalenderen min i morgon",
        "Er det noko i kalenderen min i morgon?",
    )
) + tuple(
    (
        text,
        BotIntent.REMINDER_LIST,
        ActionName.REMINDER_LIST,
        _REMINDER_TOMORROW_PAYLOAD,
    )
    for text in (
        "Check my reminders tomorrow",
        "Can you check my reminders tomorrow?",
        "Are there any reminders for me tomorrow?",
        "Sjekk påminnelsene mine i morgen",
        "Er det noen påminnelser i morgen?",
        "Sjekk påminningane mine i morgon",
        "Er det nokon påminningar i morgon?",
        "Do I need to remember anything tomorrow?",
        "Do I need to remember something tomorrow?",
        "What should I remember tomorrow?",
        "Anything I should remember tomorrow?",
        "Is there anything I have to remember tomorrow?",
        "Is there anything I should remember tomorrow?",
        "Er det noe jeg må huske i morgen?",
        "Er det noko eg må hugse i morgon?",
        "Må jeg huske noe i morgen?",
        "Må eg hugse noko i morgon?",
        "Hva bør jeg huske i morgen?",
        "Kva bør eg hugse i morgon?",
    )
)


READ_ALIASES = (
    ("What’s on my calendar?", BotIntent.CALENDAR_LIST),
    ("Can I see my calendar?", BotIntent.CALENDAR_LIST),
    ("Could I see my calendar?", BotIntent.CALENDAR_LIST),
    ("Har jeg noen påminnelser?", BotIntent.REMINDER_LIST),
    ("Vis meg påminnelsene", BotIntent.REMINDER_LIST),
    ("Could I see my reminders?", BotIntent.REMINDER_LIST),
    ("Can I see my reminders?", BotIntent.REMINDER_LIST),
    ("Any reminders for me?", BotIntent.REMINDER_LIST),
    ("What reminders do I have?", BotIntent.REMINDER_LIST),
    ("What do I need to remember?", BotIntent.REMINDER_LIST),
    ("Anything I need to remember?", BotIntent.REMINDER_LIST),
    ("Is there anything I need to remember?", BotIntent.REMINDER_LIST),
    ("Kan jeg se påminnelsene mine?", BotIntent.REMINDER_LIST),
    ("Kan eg sjå påminningane mine?", BotIntent.REMINDER_LIST),
    ("Hva må jeg huske?", BotIntent.REMINDER_LIST),
    ("Hva står på huskelista?", BotIntent.REMINDER_LIST),
    ("What's coming up on my calendar?", BotIntent.CALENDAR_LIST),
    ("What is coming up on my calendar?", BotIntent.CALENDAR_LIST),
    ("Show me my schedule", BotIntent.CALENDAR_LIST),
    ("What's my schedule?", BotIntent.CALENDAR_LIST),
    ("Kan jeg se kalenderen min?", BotIntent.CALENDAR_LIST),
    ("Kan eg sjå kalenderen min?", BotIntent.CALENDAR_LIST),
    ("What's the weather like?", BotIntent.DASHBOARD),
    ("Will it rain today?", BotIntent.DASHBOARD),
    ("Will it rain?", BotIntent.DASHBOARD),
    ("Is it going to rain today?", BotIntent.DASHBOARD),
    ("Do I need an umbrella today?", BotIntent.DASHBOARD),
    ("What's the forecast today?", BotIntent.DASHBOARD),
    ("What is the forecast today?", BotIntent.DASHBOARD),
    ("What is the weather forecast?", BotIntent.DASHBOARD),
    ("How's the weather?", BotIntent.DASHBOARD),
    ("How is the weather?", BotIntent.DASHBOARD),
    ("How warm is it in Oslo?", BotIntent.DASHBOARD),
    ("Blir det regn?", BotIntent.DASHBOARD),
    ("Blir det regn i dag?", BotIntent.DASHBOARD),
    ("Trenger jeg paraply i dag?", BotIntent.DASHBOARD),
    ("Treng eg paraply i dag?", BotIntent.DASHBOARD),
    ("Hvor varmt er det i Oslo?", BotIntent.DASHBOARD),
    ("Kor varmt er det i Oslo?", BotIntent.DASHBOARD),
    ("Hvordan blir været i Oslo?", BotIntent.DASHBOARD),
    ("What can you help me with?", BotIntent.HELP),
    ("Tell me what you can do", BotIntent.HELP),
    ("How can you help me?", BotIntent.HELP),
    ("What features do you have?", BotIntent.HELP),
    ("Hva kan du hjelpe med?", BotIntent.HELP),
    ("Kva kan du hjelpe meg med?", BotIntent.HELP),
    ("Hvilke ting kan du gjøre?", BotIntent.HELP),
    ("When's my birthday?", BotIntent.BIRTHDAY_LIST),
    ("Når har jeg bursdag?", BotIntent.BIRTHDAY_LIST),
    ("Lær meg dagens ord", BotIntent.WORD_OF_DAY),
) + tuple(
    (text, intent) for text, intent, _ in P2_READ_ALIASES
) + tuple(
    (text, intent) for text, intent, _, _ in P2_FILTERED_READ_ALIASES
)


CALENDAR_CREATE_ALIASES = (
    "Could you put lunch on my calendar tomorrow?",
    "Could you book lunch tomorrow?",
    "Could you set up lunch tomorrow?",
    "Kan du sette opp lunsj i kalenderen i morgen?",
    "Kan du booke lunsj i morgen?",
    "Can you add lunch to my calendar tomorrow?",
    "Schedule lunch tomorrow at 3pm",
    "Can you schedule lunch tomorrow?",
    "Please schedule lunch tomorrow",
    "Planlegg lunsj i morgen kl 15",
    "Kan du planlegge lunsj i morgen kl 15",
    "Kan du planleggje lunsj i morgon kl 15",
    "I'd like to add lunch to my calendar tomorrow",
    "I would like to add lunch to my calendar tomorrow",
    "Please put lunch in my calendar for tomorrow",
    "Put lunch on my calendar tomorrow",
    "Can you put lunch on my calendar tomorrow?",
    "Put lunch on the calendar tomorrow",
    "Can you put lunch on the calendar tomorrow?",
)


REMINDER_CREATE_ALIASES = (
    ("I need to remember to watch Inception tomorrow", "watch Inception"),
    ("Don't let me forget to call mom tomorrow", "call mom"),
    ("Don’t let me forget to call mom tomorrow", "call mom"),
    ("Ikke la meg glemme å ringe mamma i morgen", "ringe mamma"),
    ("Can you remind me about lunch tomorrow?", "lunch"),
    ("Jeg må huske å ringe legen i morgen", "ringe legen"),
    ("Pass på at jeg ringer mamma i morgen", "jeg ringer mamma"),
    (
        "Pass på at jeg husker å ringe mamma i morgen",
        "jeg husker å ringe mamma",
    ),
    ("Ikkje lat meg gløyme å ringe mamma i morgon", "ringe mamma"),
    ("Make sure I remember to call mom tomorrow", "call mom"),
    ("I'd like a reminder to call mom tomorrow", "call mom"),
    ("I would like a reminder to call mom tomorrow", "call mom"),
    ("Can you make a reminder to call mom tomorrow?", "call mom"),
    ("Set a reminder to call mom tomorrow", "call mom"),
    ("Put a reminder to call mom tomorrow", "call mom"),
    ("Could you create a reminder for me to call mom tomorrow?", "call mom"),
    ("I want a reminder to call mom tomorrow", "call mom"),
    ("I need a reminder to call mom tomorrow", "call mom"),
    ("Can I get a reminder to call mom tomorrow?", "call mom"),
    ("Give me a reminder to call mom tomorrow", "call mom"),
)


@pytest.mark.parametrize(("text", "expected_intent"), READ_ALIASES)
def test_conversational_read_aliases_keep_typed_routes(text, expected_intent):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    ("text", "expected_intent", "action"),
    P2_READ_ALIASES,
)
def test_p2_read_aliases_keep_deterministic_and_semantic_parity(
    text,
    expected_intent,
    action,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is expected_intent
    assert semantic is not None
    assert semantic.intent is expected_intent
    assert semantic.payload == deterministic.payload


@pytest.mark.parametrize(
    ("text", "expected_intent", "action", "expected_payload"),
    P2_FILTERED_READ_ALIASES,
)
def test_p2_read_aliases_compose_with_single_date_filters_in_both_paths(
    text,
    expected_intent,
    action,
    expected_payload,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is expected_intent
    assert deterministic.payload == expected_payload
    assert semantic is not None
    assert semantic.intent is expected_intent
    assert semantic.payload == expected_payload
    assert semantic.payload == deterministic.payload


@pytest.mark.parametrize("text", CALENDAR_CREATE_ALIASES)
def test_conversational_calendar_create_aliases_keep_clean_title(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] in {"Lunch", "Lunsj"}
    assert result.payload["calendar_item"]["date"] == "15.07.2026"


@pytest.mark.parametrize(
    ("text", "expected_title"),
    (
        ("Book me a dentist appointment tomorrow", "Dentist appointment"),
        (
            "Can you book me a dentist appointment tomorrow?",
            "Dentist appointment",
        ),
        (
            "Make an appointment with the dentist tomorrow",
            "Appointment with the dentist",
        ),
        ("Book a dentist appointment tomorrow", "Dentist appointment"),
        ("Book dentist appointment tomorrow", "Dentist appointment"),
        ("Make a dentist appointment tomorrow", "Dentist appointment"),
        (
            "Can you make a dentist appointment tomorrow?",
            "Dentist appointment",
        ),
    ),
)
def test_calendar_book_and_make_frames_drop_request_pronouns(
    text,
    expected_title,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": expected_title, "date": "15.07.2026"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CALENDAR_ITEM
    assert deterministic.payload["calendar_item"]["title"] == expected_title
    assert semantic is not None
    assert semantic.intent is BotIntent.CALENDAR_ITEM


@pytest.mark.parametrize(("text", "expected_text"), REMINDER_CREATE_ALIASES)
def test_remember_idioms_take_reminder_precedence(text, expected_text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.REMINDER_CREATE
    assert result.payload["reminder"]["text"] == expected_text
    assert result.payload["reminder"]["due_date"] == "15.07.2026"


@pytest.mark.parametrize(
    "text",
    (
        "Husk at jeg vil se Inception",
        "Hugs at eg vil sjå Inception",
    ),
)
def test_bare_indirect_media_requests_never_write_the_reminder_store(text):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.WATCHLIST
    assert deterministic.payload["watchlist"]["action"] == "add"
    assert deterministic.payload["watchlist"]["title"] == "Inception"
    assert semantic is not None
    assert semantic.intent is BotIntent.WATCHLIST


def test_temporal_indirect_watch_phrase_remains_a_reminder():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "Husk at jeg vil se legen i morgen"
    )

    assert result.intent is BotIntent.REMINDER_CREATE


@pytest.mark.parametrize(
    "text",
    (
        "I need to remember that meeting tomorrow sounds good",
        "Jeg må huske at møtet er i morgen",
    ),
)
def test_reminder_language_statements_are_never_stolen_by_calendar_task_gate(
    text,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is not BotIntent.CALENDAR_ITEM


@pytest.mark.parametrize(
    ("text", "action", "slots", "expected_intent"),
    (
        *(
            (
                text,
                ActionName.CALENDAR_CREATE,
                {
                    "title": "Lunsj" if "lunsj" in text.casefold() else "Lunch",
                    "date": "15.07.2026",
                },
                BotIntent.CALENDAR_ITEM,
            )
            for text in CALENDAR_CREATE_ALIASES
        ),
        *(
            (
                text,
                ActionName.REMINDER_CREATE,
                {"text": reminder_text, "due_date": "15.07.2026"},
                BotIntent.REMINDER_CREATE,
            )
            for text, reminder_text in REMINDER_CREATE_ALIASES
        ),
    ),
)
def test_new_natural_write_frames_authorize_bounded_model_proposals(
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


ALL_NEW_EXECUTABLE_ALIASES = tuple(text for text, _ in READ_ALIASES) + (
    CALENDAR_CREATE_ALIASES
    + tuple(text for text, _ in REMINDER_CREATE_ALIASES)
    + (
        "Har jeg noe i kalenderen i morgen?",
        "Hva skjer i kalenderen i morgen?",
        "What's on my calendar tomorrow?",
        "Show me my calendar tomorrow",
        "Hva skjer i kalenderen min i morgen?",
        "What reminders do I have tomorrow?",
        "Show reminders for tomorrow",
        "Har jeg påminnelser i morgen?",
        "Hva må jeg huske i morgen?",
        "What's my schedule tomorrow?",
        "What's coming up on my calendar tomorrow?",
        "Kan eg sjå kalenderen min i morgon?",
        "Do I have any reminders tomorrow?",
        "Kan jeg se påminnelsene mine i morgen?",
        "Kan eg sjå påminningane mine i morgon?",
    )
)


@pytest.mark.parametrize("direction", ("write_first", "alias_first"))
@pytest.mark.parametrize("second_request", ALL_NEW_EXECUTABLE_ALIASES)
def test_every_new_alias_and_write_sequence_requires_split_in_both_bridges(
    second_request,
    direction,
):
    write = "add Inception to my watchlist"
    alias = second_request.rstrip(" ?.! ")
    text = (
        f"{write} and {alias}"
        if direction == "write_first"
        else f"{alias} and {write}"
    )
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "multiple_actions_require_split"
    assert semantic is None


@pytest.mark.parametrize(
    ("first", "expected_intent"),
    (
        ("create a meeting tomorrow", BotIntent.CALENDAR_ITEM),
        ("remind me to call mom tomorrow", BotIntent.REMINDER_CREATE),
        ("kan du huske at jeg vil se Inception", BotIntent.WATCHLIST),
        ("save this quote: Stay curious", BotIntent.QUOTE),
        ("lag en avstemning: Mat? Pizza eller taco", BotIntent.POLL_CREATE),
    ),
)
@pytest.mark.parametrize("separator", (" and ", ". "))
@pytest.mark.parametrize("tail", ("tell me a joke", "how are you?"))
def test_generic_conversational_tail_never_becomes_mutation_payload(
    first,
    expected_intent,
    separator,
    tail,
):
    adapter = build_production_router(EvalFixture.EMPTY)
    standalone = adapter.route_help_example(first)
    combined = adapter.route_help_example(f"{first}{separator}{tail}")
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.WATCHLIST_ADD,
            {"title": "Inception"},
            confidence=0.99,
        ),
        bridge_context(
            utterance=normalize_utterance(f"{first}{separator}{tail}")
        ),
    )

    assert standalone.intent is expected_intent
    assert combined.intent is BotIntent.CLARIFY
    assert combined.reason == "multiple_actions_require_split"
    assert semantic is None


@pytest.mark.parametrize(
    "text",
    (
        "Is it going to rain tomorrow?",
        "Do I need an umbrella tomorrow?",
        "Blir det regn i morgen?",
        "Trenger jeg paraply i morgen?",
        "Kjem det til å regne i morgon?",
        "Treng eg paraply i morgon?",
    ),
)
def test_future_weather_questions_never_use_current_conditions(text):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(ActionName.SHOW_DASHBOARD, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )
    sequenced = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(
        f"add Inception to my watchlist and {text.rstrip(' ?.!')}"
    )

    assert deterministic.intent is BotIntent.CLARIFY
    assert deterministic.reason == "weather_future_date_unsupported"
    assert semantic is None
    assert sequenced.intent is BotIntent.CLARIFY
    assert sequenced.reason == "multiple_actions_require_split"


@pytest.mark.parametrize(
    "text",
    (
        "What do you think about the weather tomorrow?",
        "How does the weather affect traffic tomorrow?",
    ),
)
def test_future_weather_topic_discussion_remains_chat(
    text,
):
    result = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)

    assert result.intent is BotIntent.AI_CHAT


@pytest.mark.parametrize(
    "text",
    (
        "Will it rain tonight?",
        "Will it rain later today?",
        "Will it rain this evening?",
        "Will it rain on Friday?",
        "Will it rain July 20?",
        "Will it rain this weekend?",
        "Will it rain over the weekend?",
        "Will it rain next month?",
        "Will it rain next year?",
        "Will it rain in a week?",
        "Will it rain in two weeks?",
        "Will it rain in 30 minutes?",
        "Will it rain next hour?",
        "Will it rain at 5pm?",
        "Will it rain at noon?",
        "Will it rain later?",
        "Will it rain this week?",
        "What will the weather be like Friday?",
        "What's the forecast next weekend?",
        "Do I need an umbrella tonight?",
        "What is the forecast this afternoon?",
        "Blir det regn i kveld?",
        "Blir det regn på fredag?",
        "Blir det regn i helga?",
        "Blir det regn neste helg?",
        "Blir det regn neste måned?",
        "Blir det regn om to uker?",
        "Blir det regn om 30 minutter?",
        "Blir det regn klokka 17?",
        "Trenger jeg paraply senere i dag?",
    ),
)
def test_common_future_weather_times_require_forecast_clarification(
    text,
):
    result = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(ActionName.SHOW_DASHBOARD, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "weather_future_date_unsupported"
    assert semantic is None


@pytest.mark.parametrize(
    "text",
    (
        "What capabilities does Python have?",
        "Check whether my calendar parsing theory is correct",
        "Any reminders about how reminder systems work?",
        "Er det noe i kalenderen som heter API?",
        "My plans changed",
        "I have plans tomorrow",
        "Plans are important tomorrow",
        "Is there anything I should remember about Python?",
        "Do I need to remember anything about how memory works?",
        "I'd like a reminder of why this happened tomorrow",
    ),
)
def test_bounded_p2_read_aliases_do_not_steal_longer_conversation(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent not in {
        BotIntent.CALENDAR_LIST,
        BotIntent.CALENDAR_ITEM,
        BotIntent.REMINDER_LIST,
        BotIntent.REMINDER_CREATE,
        BotIntent.HELP,
    }


@pytest.mark.parametrize(
    "terminal",
    (
        "mom",
        "Tom",
        "Zoom",
        "the room",
        "a broom",
        "doom",
        "dog",
        "band",
        "cat",
        "format",
        "garden",
        "Sweden",
        "Berlin",
        "login",
        "until",
        "doctor",
    ),
)
def test_temporal_cleanup_never_consumes_a_word_suffix_that_looks_like_connector(
    terminal,
):
    parsed = parse_reminder_command(
        f"remind me to call {terminal} tomorrow",
        now=REFERENCE,
    )

    assert parsed is not None
    assert parsed["text"] == f"call {terminal}"


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("remind me tomorrow to call mom", "call mom"),
        ("remind me tomorrow about calling mom", "calling mom"),
        ("remind me tomorrow to email tom", "email tom"),
        ("remind me tomorrow To Kill a Mockingbird", "To Kill a Mockingbird"),
    ),
)
def test_temporal_first_reminders_remove_only_a_lowercase_orphan_infinitive(
    text,
    expected,
):
    parsed = parse_reminder_command(text, now=REFERENCE)

    assert parsed is not None
    assert parsed["text"] == expected


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        ("meeting tomorrow at 3", BotIntent.CLARIFY),
        ("remind me to call mom tomorrow at 3", BotIntent.CLARIFY),
        ("meeting tomorrow at 3pm", BotIntent.CALENDAR_ITEM),
        ("remind me to call mom tomorrow at 3 pm", BotIntent.REMINDER_CREATE),
        ("meeting tomorrow at 15", BotIntent.CALENDAR_ITEM),
        ("remind me to call mom tomorrow at 15", BotIntent.REMINDER_CREATE),
        ("møte i morgen kl 3", BotIntent.CALENDAR_ITEM),
        ("minn meg på å ringe mamma i morgen kl 3", BotIntent.REMINDER_CREATE),
        ("husk at 3 ting i morgen", BotIntent.REMINDER_CREATE),
    ),
)
def test_bare_english_clock_hours_clarify_without_changing_norwegian_24h_policy(
    text,
    expected_intent,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    "text",
    (
        "I don't need to remember to call mom tomorrow",
        "Jeg vil ikke glemme å ringe mamma i morgen",
        "Book was a good lunch recommendation tomorrow",
        "The weather is lovely today",
        "I learned today's word yesterday",
    ),
)
def test_nearby_statements_and_general_negations_remain_non_mutating(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent not in {
        BotIntent.CALENDAR_ITEM,
        BotIntent.REMINDER_CREATE,
    }


@pytest.mark.parametrize(
    "text",
    (
        "What's on my calendar tomorrow?",
        "Har jeg noe i kalenderen i morgen?",
        "Kva skjer i kalenderen min i morgon?",
        "Do I have anything planned tomorrow?",
        "Har jeg noe planlagt i morgen?",
        "Kva står på planen i morgon?",
    ),
)
def test_date_filtered_calendar_questions_keep_the_canonical_filter(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_LIST
    assert result.payload == {"calendar_list": {"date": "15.07.2026"}}


@pytest.mark.parametrize(
    ("text", "action"),
    (
        ("What's on my calendar tomorrow?", ActionName.CALENDAR_LIST),
        ("Show me my calendar tomorrow", ActionName.CALENDAR_LIST),
        ("Har jeg noe i kalenderen i morgen?", ActionName.CALENDAR_LIST),
        ("Hva skjer i kalenderen min i morgen?", ActionName.CALENDAR_LIST),
        ("Kva skjer i kalenderen min i morgon?", ActionName.CALENDAR_LIST),
        ("What reminders do I have tomorrow?", ActionName.REMINDER_LIST),
        ("Show reminders for tomorrow", ActionName.REMINDER_LIST),
        ("Any reminders for tomorrow?", ActionName.REMINDER_LIST),
        ("Is there anything I need to remember tomorrow?", ActionName.REMINDER_LIST),
        ("Har jeg påminnelser i morgen?", ActionName.REMINDER_LIST),
        ("Hva må jeg huske i morgen?", ActionName.REMINDER_LIST),
        ("Kva må eg hugse i morgon?", ActionName.REMINDER_LIST),
    ),
)
def test_semantic_list_bridge_preserves_the_resolved_single_date_filter(
    text,
    action,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, {}, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    expected_intent = (
        BotIntent.CALENDAR_LIST
        if action is ActionName.CALENDAR_LIST
        else BotIntent.REMINDER_LIST
    )
    expected_payload = (
        {"calendar_list": {"date": "15.07.2026"}}
        if action is ActionName.CALENDAR_LIST
        else {"reminder": {"action": "list", "due_date": "15.07.2026"}}
    )
    assert deterministic.intent is expected_intent
    assert deterministic.payload == expected_payload
    assert semantic is not None
    assert semantic.intent is expected_intent
    assert semantic.payload == expected_payload


@pytest.mark.parametrize(
    "text",
    (
        "Schedule is full tomorrow",
        "Schedule tomorrow is full",
        "Schedule for tomorrow looks good",
    ),
)
def test_schedule_descriptions_are_not_immediate_calendar_writes(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is not BotIntent.CALENDAR_ITEM


@pytest.mark.parametrize(
    "text",
    (
        "My schedule is full tomorrow",
        "The schedule says lunch tomorrow",
        "Book club tomorrow sounds fun",
        "I could schedule lunch tomorrow",
    ),
)
def test_ambiguous_schedule_and_book_statements_do_not_authorize_model_writes(
    text,
):
    result = ActionBridge().to_result(
        proposal_for(
            ActionName.CALENDAR_CREATE,
            {"title": "Lunch", "date": "15.07.2026"},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is None


@pytest.mark.parametrize(
    "text",
    (
        "What is weather forecasting?",
        "How does the weather affect traffic in Oslo?",
        "Hvordan fungerer værmelding?",
        "Hvordan påvirker været Bitcoin?",
    ),
)
def test_explanatory_weather_questions_remain_conversational(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.AI_CHAT


@pytest.mark.parametrize(
    "text",
    (
        "Should I delete reminder 1?",
        "Do you think I should delete reminder 1?",
        "Would it be a good idea to delete reminder 1?",
        "Bør jeg slette påminnelse 1?",
        "Skal jeg slette påminnelse 1?",
        "Tror du jeg bør slette påminnelse 1?",
    ),
)
def test_advice_questions_never_authorize_destructive_model_actions(text):
    deterministic = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(
            ActionName.REMINDER_DELETE,
            {"number": 1},
            confidence=0.99,
        ),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is not BotIntent.REMINDER_DELETE
    assert semantic is None


@pytest.mark.parametrize(
    ("text", "action", "slots"),
    (
        (
            "Can you explain how to put lunch on my calendar tomorrow?",
            ActionName.CALENDAR_CREATE,
            {"title": "Lunch", "date": "15.07.2026"},
        ),
        (
            "Tell me how to put lunch on my calendar tomorrow.",
            ActionName.CALENDAR_CREATE,
            {"title": "Lunch", "date": "15.07.2026"},
        ),
        (
            "Show me how to put lunch on my calendar tomorrow.",
            ActionName.CALENDAR_CREATE,
            {"title": "Lunch", "date": "15.07.2026"},
        ),
        (
            "Explain how to make a reminder to call mom tomorrow.",
            ActionName.REMINDER_CREATE,
            {"text": "call mom", "due_date": "15.07.2026"},
        ),
        (
            "Can you explain how to make a reminder to call mom tomorrow?",
            ActionName.REMINDER_CREATE,
            {"text": "call mom", "due_date": "15.07.2026"},
        ),
    ),
)
def test_meta_how_to_requests_never_authorize_model_writes(
    text,
    action,
    slots,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(text),
            deterministic_route=deterministic,
        ),
    )

    assert deterministic.intent is BotIntent.AI_CHAT
    assert semantic is None


@pytest.mark.parametrize(
    ("text", "action", "slots"),
    (
        (
            "Can you make a reminder sound friendlier?",
            ActionName.REMINDER_CREATE,
            {"text": "sound friendlier", "due_date": "15.07.2026"},
        ),
        (
            "Make an appointment class in Python tomorrow",
            ActionName.CALENDAR_CREATE,
            {"title": "Appointment class", "date": "15.07.2026"},
        ),
        (
            "Can you make an appointment class for Python tomorrow?",
            ActionName.CALENDAR_CREATE,
            {"title": "Appointment class", "date": "15.07.2026"},
        ),
        (
            "Can you make an appointment sound friendlier?",
            ActionName.CALENDAR_CREATE,
            {"title": "Appointment", "date": "15.07.2026"},
        ),
        (
            "Put differently, lunch is tomorrow on my calendar",
            ActionName.CALENDAR_CREATE,
            {"title": "Lunch", "date": "15.07.2026"},
        ),
    ),
)
def test_causative_and_discourse_frames_do_not_create_records(
    text,
    action,
    slots,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert deterministic.intent is BotIntent.AI_CHAT
    assert semantic is None


@pytest.mark.parametrize(
    ("text", "action", "slots"),
    (
        (
            "What are my plans tomorrow?",
            ActionName.CALENDAR_SEARCH,
            {"query": "plans"},
        ),
        (
            "What are my plans tomorrow with Kari?",
            ActionName.CALENDAR_SEARCH,
            {"query": "Kari"},
        ),
        (
            "What are my plans tomorrow and next week?",
            ActionName.CALENDAR_SEARCH,
            {"query": "plans"},
        ),
        (
            "Do I need to remember anything tomorrow?",
            ActionName.REMINDER_SEARCH,
            {"query": "anything"},
        ),
        (
            "Do I need to remember anything tomorrow about work?",
            ActionName.REMINDER_SEARCH,
            {"query": "work"},
        ),
    ),
)
def test_list_read_meaning_cannot_be_reinterpreted_as_partial_search(
    text,
    action,
    slots,
):
    deterministic = build_production_router(
        EvalFixture.EMPTY
    ).route_help_example(text)
    semantic = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(
            utterance=normalize_utterance(text),
            deterministic_route=deterministic,
        ),
    )

    assert semantic is None


@pytest.mark.parametrize(
    "text",
    (
        "create a meeting tomorrow\ntell me a joke",
        "remind me to call mom tomorrow\nwhat is the weather?",
        "add Inception to my watchlist also tell me a joke",
        "save quote Stay curious plus tell me a joke",
        "make a poll: Lunch? Pizza, Sushi & tell me a joke",
        "lag et møte i morgen også fortell meg en vits",
        "husk å ringe mamma i morgen pluss vis kalenderen",
        "add Inception to my watchlist? tell me a joke",
        "save quote Stay curious! tell me a joke",
    ),
)
def test_additive_and_hard_boundaries_never_commit_partial_writes(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"

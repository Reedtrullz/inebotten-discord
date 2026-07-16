"""Bounded natural-language aliases for typed read-only feature routes."""

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent, IntentRisk
from features.birthday_manager import parse_birthday_command
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    "text",
    (
        "kan du vise meg kalenderen min?",
        "kva står i kalenderen min?",
        "what is on my calendar?",
    ),
)
def test_natural_owned_calendar_reads_route_to_typed_list(text):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is BotIntent.CALENDAR_LIST
    assert result.payload == {}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "intent", "payload"),
    (
        (
            "vis kommende bursdager",
            BotIntent.BIRTHDAY_LIST,
            {"birthday": {"action": "list", "scope": "upcoming"}},
        ),
        (
            "kan du vise hva du husker om meg?",
            BotIntent.MEMORY_VIEW,
            {"memory": {"action": "view"}},
        ),
    ),
)
def test_natural_birthday_and_memory_reads_keep_typed_payload(
    text,
    intent,
    payload,
):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is intent
    assert result.payload == payload
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "text",
    (
        "kan du eksportere minnet mitt?",
        "could you export my memory?",
    ),
)
def test_natural_memory_export_requires_one_explicit_bounded_request(text):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is BotIntent.MEMORY_EXPORT
    assert result.payload == {"memory": {"action": "export"}}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "text",
    (
        "kan du slette minnet mitt?",
        "could you delete my memory?",
        "kan du glemme meg?",
    ),
)
def test_polite_memory_delete_is_typed_and_requires_confirmation(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.MEMORY_DELETE
    assert result.payload == {"memory": {"action": "delete"}}
    assert result.risk is IntentRisk.DESTRUCTIVE
    assert result.requires_confirmation is True


def test_polite_active_poll_read_routes_to_typed_list():
    result = build_production_router(
        EvalFixture.ACTIVE_POLL
    ).route_help_example("kan du vise aktive avstemninger?")

    assert result.intent is BotIntent.POLL_LIST
    assert result.payload == {}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "text",
    (
        "how many reminders do I have?",
        "show me all my reminders",
        "do I have any reminders?",
    ),
)
def test_natural_reminder_inventory_questions_route_to_one_typed_list(text):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is BotIntent.REMINDER_LIST
    assert result.payload == {"reminder": {"action": "list"}}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "text",
    (
        "what’s on my watchlist?",
        "show me my watchlist",
        "which movies are on my watchlist?",
    ),
)
def test_natural_owned_watchlist_questions_route_to_status(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.WATCHLIST
    assert result.payload["watchlist"]["action"] == "status"
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "fixture",
    (EvalFixture.EMPTY, EvalFixture.ACTIVE_POLL),
)
@pytest.mark.parametrize(
    "text",
    ("what polls are active?", "are there any active polls?"),
)
def test_natural_poll_inventory_questions_route_even_when_empty(fixture, text):
    result = build_production_router(fixture).route_help_example(text)

    assert result.intent is BotIntent.POLL_LIST
    assert result.payload == {}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "scope"),
    (
        ("when is my birthday?", "self"),
        ("what is my birthday?", "self"),
        ("who has a birthday coming up?", "upcoming"),
    ),
)
def test_natural_birthday_questions_keep_truthful_scope(text, scope):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.BIRTHDAY_LIST
    assert result.payload == {"birthday": {"action": "list", "scope": scope}}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "intent", "action"),
    (
        ("what quotes have I saved?", BotIntent.QUOTE_LIST, "list"),
        ("show me my saved quotes", BotIntent.QUOTE_LIST, "list"),
        ("give me a random quote", BotIntent.QUOTE, "get"),
    ),
)
def test_natural_saved_quote_questions_keep_their_typed_operation(
    text,
    intent,
    action,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    assert result.payload["quote"]["action"] == action
    assert result.risk is IntentRisk.READ_ONLY


def test_show_me_your_commands_routes_to_help():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "show me your commands"
    )

    assert result.intent is BotIntent.HELP
    assert result.payload == {}
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "intent", "payload"),
    (
        (
            "kan du vise meg sitatene?",
            BotIntent.QUOTE_LIST,
            {"quote": {"action": "list", "lang": "no"}},
        ),
        (
            "could you show me a quote?",
            BotIntent.QUOTE,
            {"quote": {"action": "get", "lang": "en"}},
        ),
        (
            "kan du lagre dette som et sitat: Tenk stort",
            BotIntent.QUOTE,
            {"quote": {"action": "save", "text": "Tenk stort", "lang": "no"}},
        ),
    ),
)
def test_polite_quote_requests_keep_their_typed_operation(text, intent, payload):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    assert result.payload == payload


@pytest.mark.parametrize(
    ("text", "intent"),
    (
        ("kan du redigere sitat 1 tekst: Ny tekst", BotIntent.QUOTE_EDIT),
        ("kan du slette sitat 1?", BotIntent.QUOTE_DELETE),
    ),
)
def test_polite_quote_mutations_route_only_one_index(text, intent):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    assert result.payload["quote"]["index"] == 1


@pytest.mark.parametrize(
    ("text", "intent", "payload"),
    (
        (
            "kan du vise påminnelsene mine?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list"}},
        ),
        (
            "what reminders do I have?",
            BotIntent.REMINDER_LIST,
            {"reminder": {"action": "list"}},
        ),
        (
            "kan du søke i kalenderen etter tannlege?",
            BotIntent.CALENDAR_SEARCH,
            {"query": "tannlege"},
        ),
        (
            "finn påminnelsen om legen",
            BotIntent.REMINDER_SEARCH,
            {"reminder": {"action": "search", "query": "legen"}},
        ),
    ),
)
def test_owned_lists_and_local_searches_route_without_web_fallback(
    text,
    intent,
    payload,
):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is intent
    assert result.payload == payload
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "query"),
    (
        ("kan du søke på nettet etter tog til Trondheim?", "tog til Trondheim"),
        ("could you search the web for trains to Trondheim?", "trains to Trondheim"),
    ),
)
def test_polite_explicit_web_search_strips_only_the_request_shell(text, query):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SEARCH
    assert result.payload == {"search": {"query": query, "type": "web"}}


@pytest.mark.parametrize(
    ("text", "query"),
    (
        ("could you search for cats", "cats"),
        ("can you search for cats", "cats"),
        ("could you look up cats", "cats"),
        ("kan du søke etter katter", "katter"),
        ("kunne du søke etter katter", "katter"),
        ("search for cats, please", "cats"),
        ("search for cats please", "cats"),
        ("could you search for cats please?", "cats"),
        ("look up cats please", "cats"),
        ("søk etter katter, takk", "katter"),
        ("søk etter katter takk", "katter"),
        ("søk etter katter tusen takk", "katter"),
        ("could you search the web for cats, please", "cats"),
        ("search for cats if you have time", "cats"),
        (
            "if you have time could you search for never gonna give you up",
            "never gonna give you up",
        ),
        (
            "could you if you have time search for never gonna give you up",
            "never gonna give you up",
        ),
    ),
)
def test_bounded_bare_search_shells_keep_one_clean_query(text, query):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SEARCH
    assert result.payload == {"search": {"query": query, "type": "web"}}


@pytest.mark.parametrize(
    ("text", "query"),
    (
        ("search for please", "please"),
        ("search for thanks", "thanks"),
        ("search for thank you", "thank you"),
        ("søk etter takk", "takk"),
        ("søk etter tusen takk", "tusen takk"),
    ),
)
def test_courtesy_words_can_be_the_entire_intentional_search_query(text, query):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SEARCH
    assert result.payload == {"search": {"query": query, "type": "web"}}


@pytest.mark.parametrize(
    ("text", "city"),
    (
        ("eg bur i Bergen", "bergen"),
        ("kan du sette lokasjonen min til Trondheim?", "trondheim"),
        ("could you set my location to Oslo?", "oslo"),
    ),
)
def test_natural_location_frames_keep_one_validated_city(text, city):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SET_LOCATION
    assert result.payload == {"city": city}


def test_upcoming_birthday_parser_has_explicit_scope():
    assert parse_birthday_command("vis kommende bursdager") == {
        "action": "list",
        "scope": "upcoming",
    }


@pytest.mark.parametrize(
    ("text", "forbidden"),
    (
        (
            "kan du vise meg hvordan kalenderen min fungerer?",
            BotIntent.CALENDAR_LIST,
        ),
        (
            "Ola sa at jeg skulle vise kommende bursdager",
            BotIntent.BIRTHDAY_LIST,
        ),
        (
            "Ola spurte hva du husker om meg",
            BotIntent.MEMORY_VIEW,
        ),
        (
            "what reminders did Ola say I have?",
            BotIntent.REMINDER_LIST,
        ),
        (
            "kan du forklare hvordan man søker i kalenderen etter tannlege?",
            BotIntent.CALENDAR_SEARCH,
        ),
        (
            "jeg sa finn påminnelsen om legen",
            BotIntent.REMINDER_SEARCH,
        ),
        (
            "kan du vise hvordan aktive avstemninger fungerer?",
            BotIntent.POLL_LIST,
        ),
        (
            "Ola sa eksporter minnet mitt",
            BotIntent.MEMORY_EXPORT,
        ),
        (
            "ikke eksporter minnet mitt",
            BotIntent.MEMORY_EXPORT,
        ),
        (
            "hvis jeg sier eksporter minnet mitt, hva skjer?",
            BotIntent.MEMORY_EXPORT,
        ),
    ),
)
def test_reported_or_explanatory_neighbors_do_not_trigger_feature_reads(
    text,
    forbidden,
):
    result = build_production_router(EvalFixture.MIXED_STATE).route_help_example(
        text
    )

    assert result.intent is not forbidden

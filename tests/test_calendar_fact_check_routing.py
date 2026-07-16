import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent, IntentRisk
from tests.nlu_harness import build_production_router


@pytest.fixture(scope="module")
def router():
    return build_production_router(EvalFixture.CALENDAR_TITLE_MEETING)


@pytest.mark.parametrize(
    "text",
    (
        "Jeg er ganske sikker på at tidspunktet for Møte med Ola er feil",
        "Jeg tror datoen for Møte med Ola ikke stemmer",
        "Eg trur tidspunktet for Møte med Ola er feil",
        "I think the time for Møte med Ola is wrong",
    ),
)
def test_schedule_concern_routes_read_only(text, router):
    result = router.route_help_example(text)
    assert result.intent is BotIntent.CALENDAR_FACT_CHECK
    assert result.payload == {
        "calendar_fact_check": {
            "action": "start",
            "field": "schedule",
            "target": "Møte med Ola",
        }
    }
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    (
        'Ola skrev "tidspunktet for Møte med Ola er feil"',
        "```\ntidspunktet for Møte med Ola er feil\n```",
        "Ola sa at tidspunktet for Møte med Ola er feil",
        "hvis tidspunktet for Møte med Ola er feil, si fra",
        "tidspunktet for Møte med Ola er ikke feil",
        "hvorfor er tidspunktet for Møte med Ola feil?",
        "jeg tror tidspunktet er feil",
        "jeg tror tittelen for Møte med Ola er feil",
        "det er feil å hoppe over frokost",
    ),
)
def test_non_concern_frames_do_not_start_fact_check(text, router):
    result = router.route_help_example(text)
    assert result.intent is not BotIntent.CALENDAR_FACT_CHECK
    assert result.risk is not IntentRisk.MUTATING
    assert result.risk is not IntentRisk.DESTRUCTIVE

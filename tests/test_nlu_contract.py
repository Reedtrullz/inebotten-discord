"""Contract tests for the offline natural-language routing evaluator."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_router import BotIntent, IntentResult
from scripts.evaluate_nlu import _parse_args, _report_passes
from tests.nlu_harness import (
    ADDITIVE,
    DESTRUCTIVE,
    MUTATING,
    READ_ONLY,
    EvalCase,
    EvalResult,
    ParserProbe,
    aggregate_intent_report,
    build_production_router,
    classify_eval_risk,
    dotted_payload_matches,
    evaluate_case,
    load_cases,
)


class StubRouter:
    def __init__(self, result: IntentResult):
        self.result = result

    def evaluate(self, text: str, *, guild_id: int | None):
        return self.result, ()


def corpus_line(**overrides):
    value = {
        "id": "one",
        "locale": "nb",
        "family": "chat",
        "text": "hei",
        "expected_intent": "ai_chat",
        "expected_payload": {},
        "forbidden_intents": [],
        "fixture": "empty",
        "critical": False,
    }
    value.update(overrides)
    return json.dumps(value, ensure_ascii=False)


CORPUS_PATH = Path(__file__).parent / "fixtures" / "nlu_contract_v1.jsonl"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-0.01", "1.01"])
@pytest.mark.parametrize("option", ["--min-overall", "--min-locale"])
def test_cli_rejects_invalid_acceptance_thresholds(option: str, value: str):
    with pytest.raises(SystemExit, match="2"):
        _parse_args([option, value])


@pytest.mark.parametrize("value", ["0", "1"])
@pytest.mark.parametrize("option", ["--min-overall", "--min-locale"])
def test_cli_accepts_inclusive_threshold_boundaries(option: str, value: str):
    args = _parse_args([option, value])

    assert getattr(args, option.removeprefix("--").replace("-", "_")) == float(
        value
    )


def test_load_cases_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        corpus_line() + "\n" + corpus_line(locale="nn") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate eval id: one"):
        load_cases(path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_payload": []}, "expected_payload must be an object"),
        (
            {"expected_payload": {"calendar_item..time": "14:00"}},
            "invalid payload path",
        ),
        ({"expected_intent": "not_real"}, "unknown expected intent"),
        ({"forbidden_intents": ["not_real"]}, "unknown forbidden intent"),
        ({"fixture": "not_real"}, "unknown fixture"),
    ],
)
def test_load_cases_rejects_malformed_contract(
    tmp_path: Path, override, message
):
    path = tmp_path / "cases.jsonl"
    path.write_text(corpus_line(**override) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_cases(path)


@pytest.mark.parametrize(
    "case_id",
    ["Uppercase", "has space", "has/slash", "a" * 81],
)
def test_load_cases_rejects_noncanonical_ids(tmp_path: Path, case_id: str):
    path = tmp_path / "cases.jsonl"
    path.write_text(corpus_line(id=case_id) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid eval id"):
        load_cases(path)


def test_load_cases_rejects_unknown_family(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        corpus_line(family="secret-token") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown eval family"):
        load_cases(path)


def test_load_cases_rejects_non_json_constants(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    invalid_line = corpus_line().replace(
        '"critical": false', '"critical": NaN'
    )
    path.write_text(invalid_line + "\n")

    with pytest.raises(ValueError, match="invalid JSON on line 1"):
        load_cases(path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"text": "  "}, "text must be a nonblank string"),
        ({"locale": "no"}, "invalid locale"),
        ({"critical": 1}, "critical must be a boolean"),
        (
            {"expected_intent": "help", "forbidden_intents": ["help"]},
            "expected intent cannot be forbidden",
        ),
        (
            {"expected_payload": {"calendar_item.value": {"nested": True}}},
            "payload values must be JSON scalars or flat scalar lists",
        ),
        (
            {"expected_intent": "watchlist", "expected_payload": {}},
            "invalid watchlist.action",
        ),
        (
            {
                "expected_intent": "quote",
                "expected_payload": {"quote.action": "remove"},
            },
            "invalid quote.action",
        ),
    ],
)
def test_load_cases_rejects_other_invalid_fields(
    tmp_path: Path, override, message
):
    path = tmp_path / "cases.jsonl"
    path.write_text(corpus_line(**override) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_cases(path)


def test_load_cases_accepts_calendar_clear_family(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        corpus_line(
            id="clear-calendar",
            family="calendar_clear",
            expected_intent="calendar_clear",
            expected_payload={"calendar_target.all": True},
            critical=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (case,) = load_cases(path)

    assert case.family == "calendar_clear"
    assert case.fixture is EvalFixture.EMPTY


def test_versioned_corpus_loads_the_declared_baseline():
    cases = load_cases(CORPUS_PATH)

    assert len(cases) == 11
    assert {case.locale for case in cases} == {"nb", "nn", "en"}
    assert cases[0].id == "nb-reminder-husk-mandag"
    assert cases[-1].id == "nn-conversational-future"
    assert sum(case.critical for case in cases) == 9


def test_evaluator_uses_router_result_and_labeled_payload():
    case = EvalCase(
        id="help-nn",
        locale="nn",
        family="help",
        text="Kva kan du gjere?",
        expected_intent="help",
        expected_payload={},
        forbidden_intents=("calendar_item",),
        fixture=EvalFixture.EMPTY,
        critical=True,
    )
    result = evaluate_case(
        case,
        StubRouter(IntentResult(BotIntent.HELP, 0.96, {}, "help_keyword")),
        guild_id=123,
    )
    assert result.actual_intent == "help"
    assert result.intent_match is True
    assert result.payload_labeled is False
    assert result.payload_match is True


def test_local_eval_risk_partition_is_complete():
    target = {intent.value for intent in BotIntent} | {
        "clarify",
        "birthday_create",
        "birthday_list",
        "action_confirm",
        "action_cancel",
        "action_select",
        "action_correct",
    }
    assert READ_ONLY | ADDITIVE | MUTATING | DESTRUCTIVE | {
        "watchlist",
        "quote",
    } == target


@pytest.mark.parametrize(
    ("intent", "payload", "expected"),
    [
        ("watchlist", {"watchlist": {"action": "status"}}, "read_only"),
        ("watchlist", {"watchlist": {"action": "add"}}, "additive"),
        ("watchlist", {"watchlist": {"action": "edit"}}, "mutating"),
        ("watchlist", {"watchlist": {"action": "remove"}}, "destructive"),
        ("watchlist", {"watchlist": {"action": "unknown"}}, "destructive"),
        ("quote", {"quote": {"action": "get"}}, "read_only"),
        ("quote", {"quote": {"action": "save"}}, "additive"),
        ("quote", {}, "destructive"),
    ],
)
def test_local_eval_risk_is_payload_aware_and_fail_closed(
    intent, payload, expected
):
    assert classify_eval_risk(intent, payload) == expected


def test_parser_probe_records_bounded_name_once_and_hides_exception():
    probe = ParserProbe()

    def broken_parser(_text: str):
        raise RuntimeError("Ring Kari at https://secret.example/token")

    wrapped = probe.wrap("parse_event", broken_parser)
    assert wrapped("first secret utterance") is None
    assert wrapped("second secret utterance") is None
    assert probe.snapshot() == ("parse_event",)

    probe.reset()
    assert probe.snapshot() == ()


def test_production_adapter_runs_without_discord_or_file_backed_managers():
    router = build_production_router(EvalFixture.EMPTY)

    result, parser_names = router.evaluate("hjelp", guild_id=123)

    assert result.intent is BotIntent.HELP
    assert parser_names == ()


@pytest.mark.parametrize(
    ("fixture", "calendar_count", "reminder_count", "poll_count", "mentions"),
    [
        (EvalFixture.EMPTY, 0, 0, 0, {}),
        (EvalFixture.ACTIVE_POLL, 0, 0, 1, {}),
        (EvalFixture.ACTIVE_REMINDER, 0, 1, 0, {}),
        (EvalFixture.CALENDAR_TITLE_MEETING, 1, 0, 0, {}),
        (EvalFixture.MENTIONED_USER_42, 0, 0, 0, {42: "Ola"}),
        (EvalFixture.MIXED_STATE, 1, 1, 1, {42: "Ola"}),
    ],
)
def test_production_router_fixture_matrix_is_bounded_and_in_memory(
    fixture,
    calendar_count,
    reminder_count,
    poll_count,
    mentions,
):
    adapter = build_production_router(fixture)
    monitor = adapter._router.monitor

    assert len(monitor.calendar.get_upcoming(123)) == calendar_count
    assert len(monitor.reminders.get_active_reminders(123)) == reminder_count
    assert len(monitor.poll.get_active_polls(123)) == poll_count
    assert monitor.resolved_mentions == mentions
    assert (
        monitor.guild_id,
        monitor.channel_id,
        monitor.author_id,
        monitor.author_name,
    ) == (123, 456, 7, "Kari")


def test_dotted_payload_matching_only_walks_mappings():
    payload = {"calendar_item": {"time": "14:00", "days": ["monday"]}}

    assert dotted_payload_matches(
        payload,
        {"calendar_item.time": "14:00", "calendar_item.days": ["monday"]},
    )
    assert not dotted_payload_matches(
        payload, {"calendar_item.date": "15.07.2026"}
    )
    assert not dotted_payload_matches(
        payload, {"calendar_item.days.0": "monday"}
    )


def eval_result(**overrides) -> EvalResult:
    values = {
        "id": "row",
        "locale": "nb",
        "family": "chat",
        "expected_intent": "ai_chat",
        "actual_intent": "ai_chat",
        "expected_risk": "read_only",
        "actual_risk": "read_only",
        "intent_match": True,
        "payload_labeled": False,
        "payload_match": True,
        "forbidden_hit": False,
        "parser_names": (),
        "critical": False,
    }
    values.update(overrides)
    return EvalResult(**values)


def test_aggregate_report_uses_exact_metric_formulas_and_schema():
    rows = (
        eval_result(
            id="delete-one",
            family="calendar_clear",
            expected_intent="calendar_clear",
            actual_intent="calendar_clear",
            expected_risk="destructive",
            actual_risk="destructive",
            payload_labeled=True,
            critical=True,
        ),
        eval_result(id="negative-one", locale="nn", family="negative"),
        eval_result(
            id="add-one",
            locale="en",
            family="calendar_create",
            expected_intent="calendar_item",
            actual_intent="calendar_item",
            expected_risk="additive",
            actual_risk="additive",
            payload_labeled=True,
            critical=True,
        ),
    )

    report = aggregate_intent_report(rows)

    assert set(report) == {
        "schema_version",
        "totals",
        "metrics",
        "by_locale",
        "by_family",
        "parser_errors_by_name",
        "cases",
    }
    assert set(report["metrics"]) == {
        "overall_exact_intent_accuracy",
        "labeled_payload_accuracy",
        "parser_error_rate",
        "negative_mutation_false_positive_rate",
        "critical_action_recall",
        "destructive_action_precision",
    }
    assert report["metrics"]["overall_exact_intent_accuracy"] == {
        "numerator": 3,
        "denominator": 3,
        "rate": 1.0,
        "defined": True,
    }
    assert report["metrics"]["labeled_payload_accuracy"]["rate"] == 1.0
    assert report["metrics"]["parser_error_rate"]["rate"] == 0.0
    assert (
        report["metrics"]["negative_mutation_false_positive_rate"]["rate"]
        == 0.0
    )
    assert report["metrics"]["critical_action_recall"]["rate"] == 1.0
    assert report["metrics"]["destructive_action_precision"]["rate"] == 1.0
    assert report["by_locale"]["nb"]["denominator"] == 1
    assert report["by_family"]["calendar_clear"]["rate"] == 1.0
    assert set(report["cases"][0]) == {
        "id",
        "expected_intent",
        "actual_intent",
        "expected_risk",
        "actual_risk",
        "intent_match",
        "payload_labeled",
        "payload_match",
        "forbidden_hit",
        "parser_names",
        "critical",
    }
    assert report["cases"][0]["id"] != "delete-one"


def test_destructive_precision_rejects_matching_umbrella_with_wrong_action():
    report = aggregate_intent_report(
        [
            eval_result(
                family="watchlist",
                expected_intent="watchlist",
                actual_intent="watchlist",
                expected_risk="read_only",
                actual_risk="destructive",
                intent_match=True,
                payload_labeled=True,
                payload_match=False,
            )
        ]
    )

    assert report["metrics"]["destructive_action_precision"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
        "defined": True,
    }


def test_zero_denominators_are_explicitly_undefined():
    report = aggregate_intent_report([eval_result()])

    for metric_name in (
        "labeled_payload_accuracy",
        "negative_mutation_false_positive_rate",
        "critical_action_recall",
        "destructive_action_precision",
    ):
        assert report["metrics"][metric_name] == {
            "numerator": 0,
            "denominator": 0,
            "rate": 0.0,
            "defined": False,
        }
    assert report["by_locale"]["nn"]["defined"] is False
    assert report["by_family"]["negative"]["defined"] is False


def passing_report() -> dict[str, object]:
    return aggregate_intent_report(
        [
            eval_result(id="negative", family="negative"),
            eval_result(
                id="delete",
                locale="nn",
                family="calendar_clear",
                expected_intent="calendar_clear",
                actual_intent="calendar_clear",
                expected_risk="destructive",
                actual_risk="destructive",
                payload_labeled=True,
                critical=True,
            ),
            eval_result(
                id="add",
                locale="en",
                family="calendar_create",
                expected_intent="calendar_item",
                actual_intent="calendar_item",
                expected_risk="additive",
                actual_risk="additive",
                payload_labeled=True,
                critical=True,
            ),
        ]
    )


def test_strict_gate_accepts_a_complete_perfect_report():
    assert _report_passes(passing_report(), min_overall=0.98, min_locale=0.95)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["metrics"]["parser_error_rate"].update(
            {"numerator": 1, "rate": 1 / 3}
        ),
        lambda report: report["metrics"]["labeled_payload_accuracy"].update(
            {"defined": False, "denominator": 0, "rate": 0.0}
        ),
        lambda report: report["metrics"][
            "overall_exact_intent_accuracy"
        ].update({"numerator": 2, "rate": 2 / 3}),
        lambda report: report["by_locale"]["nn"].update(
            {"numerator": 0, "rate": 0.0}
        ),
        lambda report: report["cases"][0].update({"forbidden_hit": True}),
    ],
)
def test_strict_gate_rejects_each_required_failure(mutate):
    report = deepcopy(passing_report())
    mutate(report)

    assert not _report_passes(report, min_overall=0.98, min_locale=0.95)


def test_report_omits_utterance_payload_exception_and_source_id():
    case = EvalCase(
        id="secret-token",
        locale="nb",
        family="utility",
        text="Ring Kari https://secret.example/token kl 14",
        expected_intent="help",
        expected_payload={"calendar_item.title": "Ring Kari"},
        forbidden_intents=(),
        fixture=EvalFixture.EMPTY,
        critical=False,
    )
    result = evaluate_case(
        case,
        StubRouter(IntentResult(BotIntent.HELP, 0.96, {}, "help_keyword")),
    )
    serialized = json.dumps(
        aggregate_intent_report([result]), ensure_ascii=False
    )

    for secret in ("Ring", "Kari", "secret.example", "secret-token", "token"):
        assert secret not in serialized

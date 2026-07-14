# Natural-Language Routing Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline-evaluable, typed, temporally safe natural-language routing foundation that preserves existing deterministic behavior while blocking unsafe write interpretations and arbitrating competing candidates.

**Architecture:** Authorized message text is normalized losslessly, classified for speech act and negation, and offered to pure deterministic candidate collectors. A policy layer assigns risk, a temporal resolver validates Oslo-local dates and times, and one arbiter selects, clarifies, blocks, or falls back while exposing bounded diagnostics. A production-parser evaluation harness gates the migration without Discord, persisted user data, network calls, or AI.

**Tech Stack:** Python 3.12, stdlib `dataclasses`, `enum`, `json`, `re`, `zoneinfo`, existing `pytest`/`pytest-asyncio`, and the repository's existing parser functions.

## Global Constraints

- Run all Python commands with `.venv312/bin/python`; do not add a runtime dependency.
- Before a long test loop run `df -h /System/Volumes/Data`; stop and report when available space is below `30Gi`.
- Preserve the authorization order in `core/message_monitor.py`: the existing bot mention is required in both guilds and DMs, then allowed-user/channel checks run before normalization, metrics, routing, or AI. Untagged DMs remain ignored. Tasks in this plan do not modify that file.
- Preserve every existing `BotIntent` value, the first four positional fields of `IntentResult`, public `IntentRouter.route(content, guild_id=None)`, compatible payload envelopes, confidence values, and reason strings unless a regression case in Task 5 explicitly changes behavior.
- User-facing copy remains Norwegian; code, enum values, metric keys, and stable error codes remain English.
- All parser and collector failures are fail-closed and bounded: reports/diagnostics may contain allowlisted parser names and enum codes, never utterance text, payload values, URLs, Discord identities, or exception strings.
- Evaluation is local and deterministic: no Discord construction, `MessageMonitor` construction, file-backed manager, network, live AI, or system-time dependency in fixed-clock tests.
- Unknown or malformed `WATCHLIST`/`QUOTE` umbrella actions classify as `DESTRUCTIVE`.
- A destructive route always requires confirmation. A semantic-source additive or mutating route also requires confirmation. This plan stages no action and dispatches no handler.
- Collector methods may inspect bounded active state but must not mutate managers.
- Do not modify `~/.codex/config.toml`, secrets, tokens, `.env` values, or persisted user data.

---

## File and interface map

| File | Responsibility |
|---|---|
| `core/eval_fixtures.py` | Shared names for bounded, in-memory evaluation state. |
| `tests/nlu_harness.py` | JSONL loader, production-parser adapter, privacy-safe results, exact metrics. |
| `scripts/evaluate_nlu.py` | Stable JSON report and acceptance gate. |
| `core/intent_models.py` | Intent, risk, candidate, rejection, route, and diagnostics contracts. |
| `core/intent_policy.py` | Exhaustive base/action risk classification. |
| `core/message_context.py` | Already-resolved identities passed into routing. |
| `core/nlu_metrics.py` | In-memory bounded counters; persistence is outside this plan. |
| `core/utterance.py` | Lossless normalization plus masked control text. |
| `core/utterance_semantics.py` | Speech-act, quoted-action, and negation safety analysis. |
| `cal_system/temporal_resolver.py` | Fixed-clock Oslo date/time resolution and DST validation. |
| `core/intent_arbitration.py` | Pure risk-aware filtering, ordering, ambiguity, and confirmation policy. |
| `core/intent_router.py` | Compatibility wrapper and five deterministic candidate collectors. |

Execution order is strict: Task 1 provides the executable harness plus a report-only pre-change baseline; Task 2 provides shared types; Task 3 provides safety semantics; Task 4 provides validated temporal evidence; Task 5 migrates the router, reconnects bounded route diagnostics, and runs the first strict behavior gate. A future corpus row is never required to be green before its owning production task.

### Task 1: Add the deterministic production-parser evaluation gate

**Files:**

- Create: `core/eval_fixtures.py`
- Create: `tests/nlu_harness.py`
- Create: `tests/fixtures/nlu_contract_v1.jsonl`
- Create: `tests/test_nlu_contract.py`
- Create: `scripts/evaluate_nlu.py`
- Modify: `tests/README_TESTING.md`
- Modify: `.gitignore`

**Interfaces:**

- Consumes current `core.intent_router.IntentRouter`, `IntentResult`, production parser functions, `NaturalLanguageParser`, `CountdownManager`, and file-free `ConversationContext`.
- Produces `EvalFixture`, `EvalCase`, `EvalResult`, `load_cases(path)`, `build_production_router(fixture)`, `evaluate_case(case, router, guild_id=123)`, `aggregate_intent_report(results)`, and a privacy-safe JSON report.
- Task 5 changes the adapter's parser binding from `ParserProbe.wrap(...)` proxies to raw production callables and updates `ProductionRouterAdapter.evaluate()` to read `RoutedIntent.diagnostics.parser_errors`; corpus/report types remain stable.

- [ ] **Step 1: Write loader and evaluator contract tests (2–5 minutes)**

Create `tests/test_nlu_contract.py` with these imports and cases (retain the repository's normal imports around them):

```python
import json
from pathlib import Path

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_router import BotIntent, IntentResult
from tests.nlu_harness import (
    EvalCase,
    EvalResult,
    aggregate_intent_report,
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


def test_load_cases_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(corpus_line() + "\n" + corpus_line(locale="nn") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate eval id: one"):
        load_cases(path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_payload": []}, "expected_payload must be an object"),
        ({"expected_payload": {"calendar_item..time": "14:00"}}, "invalid payload path"),
        ({"expected_intent": "not_real"}, "unknown expected intent"),
        ({"forbidden_intents": ["not_real"]}, "unknown forbidden intent"),
        ({"fixture": "not_real"}, "unknown fixture"),
    ],
)
def test_load_cases_rejects_malformed_contract(tmp_path: Path, override, message):
    path = tmp_path / "cases.jsonl"
    path.write_text(corpus_line(**override) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_cases(path)


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
```

- [ ] **Step 2: Run the Task 1 red test (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_nlu_contract.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'tests.nlu_harness'`.

- [ ] **Step 3: Add the fixture enum and exact harness contracts (2–5 minutes)**

Create `core/eval_fixtures.py`:

```python
from enum import Enum


class EvalFixture(str, Enum):
    EMPTY = "empty"
    ACTIVE_POLL = "active_poll"
    ACTIVE_REMINDER = "active_reminder"
    CALENDAR_TITLE_MEETING = "calendar_title_meeting"
    MENTIONED_USER_42 = "mentioned_user_42"
    MIXED_STATE = "mixed_state"
```

Create the following public contracts at the top of `tests/nlu_harness.py`:

```python
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Literal, Protocol, TypeAlias

from cal_system.natural_language_parser import NaturalLanguageParser
from core.eval_fixtures import EvalFixture
from core.intent_router import BotIntent, IntentResult, IntentRouter

ParserName: TypeAlias = Literal[
    "parse_task_with_recurrence", "parse_event", "parse_countdown_query",
    "parse_poll_command", "parse_vote", "parse_watchlist_command",
    "parse_quote_command", "parse_price_command", "parse_horoscope_command",
    "parse_compliment_command", "parse_calculator_command",
    "parse_shorten_command", "detect_search_intent", "parse_reminder_command",
    "parse_birthday_command", "parse_profile_command",
]
RiskName: TypeAlias = Literal["read_only", "additive", "mutating", "destructive"]

CASE_KEYS = frozenset({
    "id", "locale", "family", "text", "expected_intent", "expected_payload",
    "forbidden_intents", "fixture", "critical",
})
PAYLOAD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    locale: Literal["nb", "nn", "en"]
    family: str
    text: str
    expected_intent: str
    expected_payload: Mapping[str, object]
    forbidden_intents: tuple[str, ...]
    fixture: EvalFixture
    critical: bool


@dataclass(frozen=True, slots=True)
class EvalResult:
    id: str
    locale: str
    family: str
    expected_intent: str
    actual_intent: str
    expected_risk: RiskName
    actual_risk: RiskName
    intent_match: bool
    payload_labeled: bool
    payload_match: bool
    forbidden_hit: bool
    parser_names: tuple[ParserName, ...]
    critical: bool

    @property
    def parser_error(self) -> bool:
        return bool(self.parser_names)


class EvaluationRouter(Protocol):
    def evaluate(
        self, text: str, *, guild_id: int | None
    ) -> tuple[IntentResult, tuple[ParserName, ...]]: ...
```

Define `EVAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")` and the finite `EVAL_FAMILIES = frozenset({"chat", "help", "negative", "calendar_create", "calendar_read", "calendar_search", "calendar_edit", "calendar_complete", "calendar_delete", "calendar_clear", "calendar_sync", "calendar_auth", "reminder_create", "reminder_read", "reminder_search", "reminder_edit", "reminder_complete", "reminder_delete", "poll_create", "poll_read", "poll_vote", "poll_edit", "poll_close", "poll_delete", "watchlist", "quote", "birthday", "weather", "location", "utility", "profile", "memory", "status", "dashboard", "fun", "search", "temporal"})`. Implement `load_cases(path: Path) -> tuple[EvalCase, ...]` with these exact rules: ignore blank lines; reject non-JSON constants by passing `parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}"))`; each line must decode to a mapping whose keyset equals `CASE_KEYS`; `id` must full-match `EVAL_ID_RE`, `family` must be in `EVAL_FAMILIES`, and `text` is a nonblank string; locale is exactly `nb`, `nn`, or `en`; `type(critical) is bool`; `expected_intent` and every forbidden intent are members of `{intent.value for intent in BotIntent}`; `expected_payload` is a dict whose keys match `PAYLOAD_PATH` and values are JSON scalars or lists of JSON scalars; and fixture is accepted by `EvalFixture(value)`. Reject `expected_intent in forbidden_intents`. For `expected_intent == "watchlist"`, require `watchlist.action` in `{status,list,suggest,add,edit,remove}`; for `expected_intent == "quote"`, require `quote.action` in `{get,save}`. Use the error fragments asserted above and `f"duplicate eval id: {case.id}"`. Add rejection tests for uppercase/space/slash/overlong IDs and unknown families, and one accepted `calendar_clear` row.

- [ ] **Step 4: Add the independent, exhaustive local risk classifier (2–5 minutes)**

Add this complete classifier to `tests/nlu_harness.py`; it must not import `core.intent_policy`:

```python
READ_ONLY = frozenset({
    "help", "status", "calendar_help", "calendar_list", "calendar_search",
    "poll_list", "countdown", "word_of_day", "quote_list", "aurora",
    "school_holidays", "price", "horoscope", "compliment", "calculator",
    "shorten_url", "daily_digest", "search", "dashboard", "memory_view",
    "memory_export", "reminder_search", "reminder_list", "birthday_list",
    "clarify", "action_confirm", "action_cancel", "action_select",
    "action_correct", "ai_chat",
})
ADDITIVE = frozenset({
    "calendar_item", "poll_create", "reminder_create", "birthday_create",
})
MUTATING = frozenset({
    "profile", "calendar_sync", "calendar_complete", "calendar_edit",
    "poll_vote", "poll_edit", "poll_close", "quote_edit", "set_location",
    "birthday_edit", "reminder_edit", "reminder_complete", "calendar_auth",
})
DESTRUCTIVE = frozenset({
    "calendar_delete", "calendar_clear", "poll_delete", "quote_delete",
    "memory_delete", "reminder_delete",
})
WATCHLIST_ACTION_RISK: dict[str, RiskName] = {
    "status": "read_only", "list": "read_only", "suggest": "read_only",
    "add": "additive", "edit": "mutating", "remove": "destructive",
}
QUOTE_ACTION_RISK: dict[str, RiskName] = {
    "get": "read_only", "save": "additive",
}


def nested_string(payload: Mapping[str, object], envelope: str, key: str) -> str:
    nested = payload.get(envelope)
    if not isinstance(nested, Mapping):
        return ""
    value = nested.get(key)
    return value.casefold().strip() if isinstance(value, str) else ""


def classify_eval_risk(intent: str, payload: Mapping[str, object]) -> RiskName:
    if intent == "watchlist":
        return WATCHLIST_ACTION_RISK.get(
            nested_string(payload, "watchlist", "action"), "destructive"
        )
    if intent == "quote":
        return QUOTE_ACTION_RISK.get(
            nested_string(payload, "quote", "action"), "destructive"
        )
    for values, risk in (
        (READ_ONLY, "read_only"), (ADDITIVE, "additive"),
        (MUTATING, "mutating"), (DESTRUCTIVE, "destructive"),
    ):
        if intent in values:
            return risk
    raise AssertionError(f"unclassified eval intent: {intent}")


def classify_expected_eval_risk(case: EvalCase) -> RiskName:
    if case.expected_intent in {"watchlist", "quote"}:
        action = case.expected_payload[f"{case.expected_intent}.action"]
        payload = {case.expected_intent: {"action": action}}
    else:
        payload = {}
    return classify_eval_risk(case.expected_intent, payload)
```

Add an exhaustiveness test using the current intent values plus Task 2's seven additions:

```python
def test_local_eval_risk_partition_is_complete():
    target = {intent.value for intent in BotIntent} | {
        "clarify", "birthday_create", "birthday_list", "action_confirm",
        "action_cancel", "action_select", "action_correct",
    }
    assert READ_ONLY | ADDITIVE | MUTATING | DESTRUCTIVE | {"watchlist", "quote"} == target
```

- [ ] **Step 5: Implement the parser probe and production adapter (2–5 minutes)**

Use a fresh probe and monitor for every case. Add the following classes and bind the real functions from the listed modules; do not construct a production manager:

```python
class ParserProbe:
    def __init__(self) -> None:
        self._names: list[ParserName] = []

    def call(self, name: ParserName, fn: Callable[..., object], *args: object) -> object | None:
        try:
            return fn(*args)
        except Exception:
            self._names.append(name)
            return None

    def wrap(self, name: ParserName, fn: Callable[..., object]) -> Callable[..., object | None]:
        return lambda *args: self.call(name, fn, *args)

    def reset(self) -> None:
        self._names.clear()

    def snapshot(self) -> tuple[ParserName, ...]:
        return tuple(dict.fromkeys(self._names))


class ProductionRouterAdapter:
    def __init__(self, monitor: object, probe: ParserProbe) -> None:
        self._router = IntentRouter(monitor)
        self._probe = probe

    def evaluate(self, text: str, *, guild_id: int | None):
        self._probe.reset()
        result = self._router.route(text, guild_id=guild_id)
        return result, self._probe.snapshot()
```

`build_production_router(fixture: EvalFixture) -> EvaluationRouter` imports and wraps these exact callables: `NaturalLanguageParser.parse_task_with_recurrence`, `.parse_event`; `cal_system.reminder_manager.parse_reminder_command`; `CountdownManager().parse_countdown_query`; `features.poll_manager.parse_poll_command`, `.parse_vote`; `features.watchlist_manager.parse_watchlist_command`; `features.quote_manager.parse_quote_command`; `features.birthday_manager.parse_birthday_command`; `features.crypto_manager.parse_price_command`; `features.horoscope_manager.parse_horoscope_command`; `features.compliments_manager.parse_compliment_command`; `features.calculator_manager.parse_calculator_command`; `features.url_shortener.parse_shorten_command`; and `features.search_manager.detect_search_intent`. Use `ConversationContext()` directly. The later profile-parity task attaches `features.profile_commands.parse_profile_command` through the same finite `ParserName` registry when that module exists.

Build a `SimpleNamespace` monitor with `nlp_parser`, `countdown`, the wrapped parser functions, `conversation`, and these in-memory accessors only:

```python
calendar_record = {"id": "calendar-1", "title": "Møte med Ola", "date": "15.07.2026", "time": "10:00"}
reminder_record = {"id": "reminder-1", "title": "Ring legen", "completed": False}
poll_record = {"id": "poll-1", "status": "active", "question": "Pizza?"}

calendar = SimpleNamespace(get_upcoming=lambda guild_id, days=365: calendar_rows)
reminders = SimpleNamespace(get_active_reminders=lambda guild_id: reminder_rows)
poll = SimpleNamespace(get_active_polls=lambda guild_id: poll_rows)
resolved_mentions = {42: "Ola"} if fixture in {EvalFixture.MENTIONED_USER_42, EvalFixture.MIXED_STATE} else {}
```

`ACTIVE_POLL`, `ACTIVE_REMINDER`, and `CALENDAR_TITLE_MEETING` expose their one record; `MIXED_STATE` exposes all records and the mention; `EMPTY` exposes none. Attach `guild_id=123`, `channel_id=456`, `author_id=7`, `author_name="Kari"`, and `resolved_mentions` as scalar fixture metadata without any Discord objects.

- [ ] **Step 6: Implement payload matching, evaluation, and exact formulas (2–5 minutes)**

Implement `dotted_payload_matches(payload, labels)` by walking each dot-separated path only through `Mapping` objects and comparing the leaf with `==`; a missing segment is false. `evaluate_case()` sets `payload_labeled=bool(case.expected_payload)`, makes unlabeled payloads pass, and computes both risks with the independent classifier.

Each metric object is exactly `{"numerator": int, "denominator": int, "rate": float, "defined": bool}`; use rate `0.0` when denominator is zero and set `defined=False`. Implement formulas exactly:

```text
overall exact = count(intent_match) / count(all)
per locale exact = count(intent_match in locale) / count(locale)
per family exact = count(intent_match in family) / count(family)
labeled payload accuracy = count(payload_match where payload_labeled) / count(payload_labeled)
parser error rate = count(parser_names is nonempty) / count(all)
negative mutation false-positive rate = count(family == "negative" and actual_risk != "read_only") / count(family == "negative")
critical action recall = count(intent_match for critical expected intent not in {"ai_chat", "clarify"}) / count(critical expected intent not in {"ai_chat", "clarify"})
destructive action precision = count(actual_risk == "destructive" and expected_risk == "destructive" and intent_match and (not payload_labeled or payload_match)) / count(actual_risk == "destructive")
```

The report schema contains only `schema_version`, `totals`, `metrics`, `by_locale`, `by_family`, `parser_errors_by_name`, and `cases`. `metrics` has exactly `overall_exact_intent_accuracy`, `labeled_payload_accuracy`, `parser_error_rate`, `negative_mutation_false_positive_rate`, `critical_action_recall`, and `destructive_action_precision`, each using the metric-object shape above. `by_locale` and `by_family` map each finite allowlisted label directly to one exact-intent metric object; they do not add another wrapper key. A case object contains only `id`, `expected_intent`, `actual_intent`, `expected_risk`, `actual_risk`, `intent_match`, `payload_labeled`, `payload_match`, `forbidden_hit`, `parser_names`, and `critical`. Its public `id` is `sha256(source_id.encode("utf-8")).hexdigest()[:16]`, never the source corpus label; this keeps reports correlatable within a run without copying arbitrary fixture metadata.

Add aggregate tests with (a) one correct destructive, one negative/read-only, and one labeled payload result; (b) expected `watchlist/status` versus actual `watchlist/remove`, proving destructive precision is `0/1` despite matching intent; and (c) every required zero denominator returning `defined=False`.

- [ ] **Step 7: Seed the exact corpus (2–5 minutes)**

Create `tests/fixtures/nlu_contract_v1.jsonl` with these lines, one object per line:

```jsonl
{"id":"nb-reminder-husk-mandag","locale":"nb","family":"reminder_create","text":"husk å kjøpe melk på mandag","expected_intent":"reminder_create","expected_payload":{"reminder.action":"add"},"forbidden_intents":["calendar_item","watchlist"],"fixture":"empty","critical":true}
{"id":"nb-event-time","locale":"nb","family":"calendar_create","text":"møte med Ola i morgen kl 14","expected_intent":"calendar_item","expected_payload":{"calendar_item.time":"14:00"},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":true}
{"id":"en-event-pm","locale":"en","family":"calendar_create","text":"meeting tomorrow at 3pm","expected_intent":"calendar_item","expected_payload":{"calendar_item.time":"15:00"},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":true}
{"id":"nb-context-search","locale":"nb","family":"search","text":"hva skjer i Trondheim i helga?","expected_intent":"search","expected_payload":{"search.type":"web"},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":false}
{"id":"nb-help","locale":"nb","family":"help","text":"hjelp","expected_intent":"help","expected_payload":{},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":true}
{"id":"nb-calendar-list","locale":"nb","family":"calendar_read","text":"vis kalenderen","expected_intent":"calendar_list","expected_payload":{},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":true}
{"id":"nb-reminder-list","locale":"nb","family":"reminder_read","text":"vis påminnelser","expected_intent":"reminder_list","expected_payload":{},"forbidden_intents":["calendar_item"],"fixture":"active_reminder","critical":true}
{"id":"nb-destructive-positive","locale":"nb","family":"calendar_clear","text":"slett kalenderen","expected_intent":"calendar_clear","expected_payload":{"calendar_target.all":true},"forbidden_intents":["ai_chat","calendar_delete"],"fixture":"empty","critical":true}
{"id":"nb-calc","locale":"nb","family":"utility","text":"regn ut 2+2","expected_intent":"calculator","expected_payload":{"calculator.expression":"2+2"},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":false}
{"id":"nb-conversational-future","locale":"nb","family":"negative","text":"jeg skal bare høre hva du synes om RBK i morgen","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":true}
{"id":"nn-conversational-future","locale":"nn","family":"negative","text":"Kva meiner du om RBK i morgon?","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":true}
```

- [ ] **Step 8: Add the CLI and privacy gate (2–5 minutes)**

Create `scripts/evaluate_nlu.py`. Before project imports, add `Path(__file__).resolve().parents[1]` to `sys.path`. Parse `--corpus PATH`, `--report PATH`, `--min-overall FLOAT` default `0.98`, `--min-locale FLOAT` default `0.95`, and a boolean `--report-only`. Build a fresh adapter per case, create the report parent, write sorted indented JSON with a trailing newline, and print one aggregate line.

In strict mode, exit `1` when any required metric is undefined; `parser_error_rate != 0`; `negative_mutation_false_positive_rate != 0`; destructive precision, critical recall, or labeled payload accuracy is not `1.0`; overall is below `--min-overall`; any represented locale is below `--min-locale`; or any forbidden hit exists. Otherwise exit `0`. With `--report-only`, compute and print the exact same would-pass/would-fail decision but exit `0`; do not alter thresholds, cases, report content, or metric math. Task 1 uses this only to prove the current production adapter runs before the planned recognizers exist. Task 5 runs strict mode and must pass.

Add a privacy test whose source text is `Ring Kari https://secret.example/token kl 14` and whose syntactically valid source id contains `secret-token`; assert `Ring`, `Kari`, `secret.example`, `secret-token`, and `token` are absent from `json.dumps(report)`. Separately inject `family="secret-token"` and assert the loader rejects it before evaluation. Add `.artifacts/` to `.gitignore`. Add the command and schema description to `tests/README_TESTING.md`.

- [ ] **Step 9: Run the complete Task 1 gate (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest tests/test_nlu_contract.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json \
  --report-only
```

Expected: harness tests pass; the baseline CLI exits `0` in report-only mode and may report the planned reminder/calendar gaps; the report contains no utterance text, payload data, or exception text. Do not claim the behavior gate is green here.

- [ ] **Step 10: Commit Task 1 (2–5 minutes)**

```bash
git add core/eval_fixtures.py tests/nlu_harness.py \
  tests/fixtures/nlu_contract_v1.jsonl tests/test_nlu_contract.py \
  scripts/evaluate_nlu.py tests/README_TESTING.md .gitignore
git commit -m "test: add production NLU contract harness"
```

### Task 2: Extract typed routing contracts, exhaustive risk policy, and bounded metrics

**Files:**

- Create: `core/intent_models.py`
- Create: `core/intent_policy.py`
- Create: `core/message_context.py`
- Create: `core/nlu_metrics.py`
- Create: `tests/test_intent_models.py`
- Create: `tests/test_nlu_metrics.py`
- Modify: `core/intent_router.py:5-6,41-97`
- Modify: `core/intent_thresholds.py:4`

**Interfaces:**

- Produces every type Task 5 consumes: `BotIntent`, `IntentSource`, `IntentRisk`, `RejectionCode`, `IntentResult`, `IntentCandidate`, `CandidateRejection`, `ArbitrationDecision`, `RouteDiagnostics`, and `RoutedIntent`.
- `core.intent_router` re-exports the exact objects from `core.intent_models`; old imports and four-position `IntentResult(...)` construction continue to work.
- `classify_intent_risk(intent, payload)` is exhaustive and payload-aware. `NLUMetrics` accepts only enums/allowlisted dimensions and never raw text.

- [ ] **Step 1: Write failing model, policy, and metric tests (2–5 minutes)**

Create `tests/test_intent_models.py` covering all of these assertions:

```python
from core.intent_models import (
    ArbitrationDecision, BotIntent, CandidateRejection, IntentCandidate,
    IntentResult, IntentRisk, IntentSource, RejectionCode, RouteDiagnostics,
    RoutedIntent,
)
from core.intent_policy import BASE_INTENT_RISK, classify_intent_risk
from core.intent_router import BotIntent as RouterBotIntent


def test_router_reexports_exact_public_type():
    assert RouterBotIntent is BotIntent


def test_four_position_result_remains_compatible():
    result = IntentResult(BotIntent.HELP, 0.96, {}, "help_keyword")
    assert result.source is IntentSource.DETERMINISTIC
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


def test_all_added_control_intents_exist():
    assert {intent.value for intent in BotIntent} >= {
        "clarify", "birthday_create", "birthday_list", "action_confirm",
        "action_cancel", "action_select", "action_correct",
    }


def test_candidate_to_result_copies_shared_fields_only():
    candidate = IntentCandidate(
        BotIntent.CALENDAR_DELETE, 0.98, 20, order=112,
        payload={"target": "Møte"}, reason="calendar_delete_keyword",
        risk=IntentRisk.DESTRUCTIVE, specificity=3,
        requires_confirmation=True,
    )
    assert candidate.to_result() == IntentResult(
        BotIntent.CALENDAR_DELETE, 0.98, {"target": "Møte"},
        "calendar_delete_keyword", IntentSource.DETERMINISTIC,
        IntentRisk.DESTRUCTIVE, True,
    )


def test_every_intent_has_exactly_one_base_risk():
    assert set(BASE_INTENT_RISK) == set(BotIntent)


def test_diagnostics_defaults_are_not_shared():
    first = RouteDiagnostics()
    second = RouteDiagnostics()
    assert first.rejection_counts is not second.rejection_counts
```

Parametrize every action override: WATCHLIST `status/list/suggest -> READ_ONLY`, `add -> ADDITIVE`, `edit -> MUTATING`, `remove -> DESTRUCTIVE`; QUOTE `get -> READ_ONLY`, `save -> ADDITIVE`. Parametrize missing, non-mapping, and unknown envelopes for both umbrella intents and assert `DESTRUCTIVE`.

Create `tests/test_nlu_metrics.py` proving a decision increment, snapshot-copy isolation, all unknown/sensitive dimensions become only `other`, JSON contains none of the rejected values, and `raw_text=` raises `TypeError`.

- [ ] **Step 2: Run the Task 2 red tests (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_intent_models.py tests/test_nlu_metrics.py -q`

Expected: collection errors include `ModuleNotFoundError: No module named 'core.intent_models'` and `No module named 'core.nlu_metrics'`.

- [ ] **Step 3: Create all public model contracts (2–5 minutes)**

Create `core/intent_models.py` with the current 48 intent values in their existing source order, then append the seven new values. Keep `IntentResult` frozen without `slots` for compatibility:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BotIntent(Enum):
    HELP = "help"
    STATUS = "status"
    PROFILE = "profile"
    CALENDAR_HELP = "calendar_help"
    CALENDAR_LIST = "calendar_list"
    CALENDAR_SYNC = "calendar_sync"
    CALENDAR_DELETE = "calendar_delete"
    CALENDAR_COMPLETE = "calendar_complete"
    CALENDAR_EDIT = "calendar_edit"
    CALENDAR_SEARCH = "calendar_search"
    CALENDAR_CLEAR = "calendar_clear"
    CALENDAR_ITEM = "calendar_item"
    POLL_CREATE = "poll_create"
    POLL_VOTE = "poll_vote"
    POLL_EDIT = "poll_edit"
    POLL_DELETE = "poll_delete"
    POLL_CLOSE = "poll_close"
    POLL_LIST = "poll_list"
    COUNTDOWN = "countdown"
    WATCHLIST = "watchlist"
    WORD_OF_DAY = "word_of_day"
    QUOTE = "quote"
    QUOTE_LIST = "quote_list"
    QUOTE_EDIT = "quote_edit"
    QUOTE_DELETE = "quote_delete"
    AURORA = "aurora"
    SCHOOL_HOLIDAYS = "school_holidays"
    PRICE = "price"
    HOROSCOPE = "horoscope"
    COMPLIMENT = "compliment"
    CALCULATOR = "calculator"
    SHORTEN_URL = "shorten_url"
    DAILY_DIGEST = "daily_digest"
    SEARCH = "search"
    DASHBOARD = "dashboard"
    SET_LOCATION = "set_location"
    MEMORY_VIEW = "memory_view"
    MEMORY_EXPORT = "memory_export"
    MEMORY_DELETE = "memory_delete"
    BIRTHDAY_EDIT = "birthday_edit"
    REMINDER_EDIT = "reminder_edit"
    REMINDER_DELETE = "reminder_delete"
    REMINDER_SEARCH = "reminder_search"
    REMINDER_CREATE = "reminder_create"
    REMINDER_LIST = "reminder_list"
    REMINDER_COMPLETE = "reminder_complete"
    CALENDAR_AUTH = "calendar_auth"
    AI_CHAT = "ai_chat"
    CLARIFY = "clarify"
    BIRTHDAY_CREATE = "birthday_create"
    BIRTHDAY_LIST = "birthday_list"
    ACTION_CONFIRM = "action_confirm"
    ACTION_CANCEL = "action_cancel"
    ACTION_SELECT = "action_select"
    ACTION_CORRECT = "action_correct"


class IntentSource(str, Enum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


class IntentRisk(str, Enum):
    READ_ONLY = "read_only"
    ADDITIVE = "additive"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class RejectionCode(str, Enum):
    NEGATED_ACTION = "negated_action"
    QUOTED_ONLY = "quoted_only"
    META = "meta"
    HYPOTHETICAL = "hypothetical"
    INFORMATION_QUESTION_MUTATION = "information_question_mutation"
    MISSING_ACTION_EVIDENCE = "missing_action_evidence"
    MISSING_DOMAIN_EVIDENCE = "missing_domain_evidence"
    MISSING_LIVE_EVIDENCE = "missing_live_evidence"
    INVALID_TEMPORAL = "invalid_temporal"
    PARSER_ERROR = "parser_error"
    UNSAFE_SEMANTIC = "unsafe_semantic"
    INVALID_CONTEXT = "invalid_context"
    CONFLICT = "conflict"
    OTHER = "other"


@dataclass(frozen=True)
class IntentResult:
    intent: BotIntent
    confidence: float
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: IntentSource = IntentSource.DETERMINISTIC
    risk: IntentRisk = IntentRisk.READ_ONLY
    requires_confirmation: bool = False


@dataclass(frozen=True)
class IntentCandidate:
    intent: BotIntent
    confidence: float
    priority: int
    order: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: IntentSource = IntentSource.DETERMINISTIC
    risk: IntentRisk = IntentRisk.READ_ONLY
    action_terms: tuple[str, ...] = ()
    domain_terms: tuple[str, ...] = ()
    specificity: int = 0
    requires_confirmation: bool = False

    def to_result(self) -> IntentResult:
        return IntentResult(
            self.intent, self.confidence, dict(self.payload), self.reason,
            self.source, self.risk, self.requires_confirmation,
        )


@dataclass(frozen=True)
class CandidateRejection:
    candidate: IntentCandidate
    code: RejectionCode


@dataclass(frozen=True)
class ArbitrationDecision:
    selected: IntentCandidate | None
    alternatives: tuple[IntentCandidate, ...] = ()
    rejected: tuple[CandidateRejection, ...] = ()
    blocked: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RouteDiagnostics:
    parser_errors: tuple[str, ...] = ()
    rejection_counts: Mapping[RejectionCode, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutedIntent:
    result: IntentResult
    diagnostics: RouteDiagnostics = field(default_factory=RouteDiagnostics)
```

- [ ] **Step 4: Create resolved routing-context contracts (2–5 minutes)**

Create `core/message_context.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationKey:
    guild_id: int | None
    channel_id: int
    user_id: int


@dataclass(frozen=True, slots=True)
class ResolvedMention:
    user_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class RoutingContext:
    key: ConversationKey
    author: ResolvedMention
    mentions: tuple[ResolvedMention, ...] = ()
```

These objects contain already-authorized/resolved identities. No parser may query Discord or reparse `message.mentions`.

- [ ] **Step 5: Add the complete intent risk table (2–5 minutes)**

Create `core/intent_policy.py` with `BASE_INTENT_RISK` exactly matching this table:

| Risk | Intents |
|---|---|
| `READ_ONLY` | `HELP`, `STATUS`, `CALENDAR_HELP`, `CALENDAR_LIST`, `CALENDAR_SEARCH`, `POLL_LIST`, `COUNTDOWN`, `WORD_OF_DAY`, `QUOTE_LIST`, `AURORA`, `SCHOOL_HOLIDAYS`, `PRICE`, `HOROSCOPE`, `COMPLIMENT`, `CALCULATOR`, `SHORTEN_URL`, `DAILY_DIGEST`, `SEARCH`, `DASHBOARD`, `MEMORY_VIEW`, `MEMORY_EXPORT`, `REMINDER_SEARCH`, `REMINDER_LIST`, `BIRTHDAY_LIST`, `CLARIFY`, `ACTION_CONFIRM`, `ACTION_CANCEL`, `ACTION_SELECT`, `ACTION_CORRECT`, `AI_CHAT` |
| `ADDITIVE` | `CALENDAR_ITEM`, `POLL_CREATE`, `REMINDER_CREATE`, `BIRTHDAY_CREATE` |
| `MUTATING` | `PROFILE`, `CALENDAR_SYNC`, `CALENDAR_COMPLETE`, `CALENDAR_EDIT`, `POLL_VOTE`, `POLL_EDIT`, `POLL_CLOSE`, `QUOTE_EDIT`, `SET_LOCATION`, `BIRTHDAY_EDIT`, `REMINDER_EDIT`, `REMINDER_COMPLETE`, `CALENDAR_AUTH` |
| `DESTRUCTIVE` | `CALENDAR_DELETE`, `CALENDAR_CLEAR`, `POLL_DELETE`, `QUOTE_DELETE`, `MEMORY_DELETE`, `REMINDER_DELETE` |
| Umbrella `WATCHLIST` | `status/list/suggest -> READ_ONLY`; `add -> ADDITIVE`; `edit -> MUTATING`; `remove -> DESTRUCTIVE`; missing/malformed/unknown -> `DESTRUCTIVE` |
| Umbrella `QUOTE` | `get -> READ_ONLY`; `save -> ADDITIVE`; missing/malformed/unknown -> `DESTRUCTIVE` |

Include both umbrella enums in `BASE_INTENT_RISK` as `DESTRUCTIVE`; their recognized action maps override that fail-closed base. This makes `set(BASE_INTENT_RISK) == set(BotIntent)` exact.

```python
BASE_INTENT_RISK: dict[BotIntent, IntentRisk] = {
    BotIntent.HELP: IntentRisk.READ_ONLY,
    BotIntent.STATUS: IntentRisk.READ_ONLY,
    BotIntent.PROFILE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_HELP: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_LIST: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_SYNC: IntentRisk.MUTATING,
    BotIntent.CALENDAR_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.CALENDAR_COMPLETE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_EDIT: IntentRisk.MUTATING,
    BotIntent.CALENDAR_SEARCH: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_CLEAR: IntentRisk.DESTRUCTIVE,
    BotIntent.CALENDAR_ITEM: IntentRisk.ADDITIVE,
    BotIntent.POLL_CREATE: IntentRisk.ADDITIVE,
    BotIntent.POLL_VOTE: IntentRisk.MUTATING,
    BotIntent.POLL_EDIT: IntentRisk.MUTATING,
    BotIntent.POLL_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.POLL_CLOSE: IntentRisk.MUTATING,
    BotIntent.POLL_LIST: IntentRisk.READ_ONLY,
    BotIntent.COUNTDOWN: IntentRisk.READ_ONLY,
    BotIntent.WATCHLIST: IntentRisk.DESTRUCTIVE,
    BotIntent.WORD_OF_DAY: IntentRisk.READ_ONLY,
    BotIntent.QUOTE: IntentRisk.DESTRUCTIVE,
    BotIntent.QUOTE_LIST: IntentRisk.READ_ONLY,
    BotIntent.QUOTE_EDIT: IntentRisk.MUTATING,
    BotIntent.QUOTE_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.AURORA: IntentRisk.READ_ONLY,
    BotIntent.SCHOOL_HOLIDAYS: IntentRisk.READ_ONLY,
    BotIntent.PRICE: IntentRisk.READ_ONLY,
    BotIntent.HOROSCOPE: IntentRisk.READ_ONLY,
    BotIntent.COMPLIMENT: IntentRisk.READ_ONLY,
    BotIntent.CALCULATOR: IntentRisk.READ_ONLY,
    BotIntent.SHORTEN_URL: IntentRisk.READ_ONLY,
    BotIntent.DAILY_DIGEST: IntentRisk.READ_ONLY,
    BotIntent.SEARCH: IntentRisk.READ_ONLY,
    BotIntent.DASHBOARD: IntentRisk.READ_ONLY,
    BotIntent.SET_LOCATION: IntentRisk.MUTATING,
    BotIntent.MEMORY_VIEW: IntentRisk.READ_ONLY,
    BotIntent.MEMORY_EXPORT: IntentRisk.READ_ONLY,
    BotIntent.MEMORY_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.BIRTHDAY_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.REMINDER_SEARCH: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_CREATE: IntentRisk.ADDITIVE,
    BotIntent.REMINDER_LIST: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_COMPLETE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_AUTH: IntentRisk.MUTATING,
    BotIntent.AI_CHAT: IntentRisk.READ_ONLY,
    BotIntent.CLARIFY: IntentRisk.READ_ONLY,
    BotIntent.BIRTHDAY_CREATE: IntentRisk.ADDITIVE,
    BotIntent.BIRTHDAY_LIST: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CONFIRM: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CANCEL: IntentRisk.READ_ONLY,
    BotIntent.ACTION_SELECT: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CORRECT: IntentRisk.READ_ONLY,
}
```

Implement the action extraction without assuming the envelope is a mapping:

```python
from collections.abc import Mapping
from typing import Any

from core.intent_models import BotIntent, IntentRisk


def _action(payload: Mapping[str, Any], envelope: str) -> str:
    value = payload.get(envelope)
    if not isinstance(value, Mapping):
        return ""
    action = value.get("action")
    return action.casefold().strip() if isinstance(action, str) else ""


WATCHLIST_ACTION_RISK = {
    "status": IntentRisk.READ_ONLY,
    "list": IntentRisk.READ_ONLY,
    "suggest": IntentRisk.READ_ONLY,
    "add": IntentRisk.ADDITIVE,
    "edit": IntentRisk.MUTATING,
    "remove": IntentRisk.DESTRUCTIVE,
}
QUOTE_ACTION_RISK = {
    "get": IntentRisk.READ_ONLY,
    "save": IntentRisk.ADDITIVE,
}


def classify_intent_risk(
    intent: BotIntent, payload: Mapping[str, Any]
) -> IntentRisk:
    if intent is BotIntent.WATCHLIST:
        return WATCHLIST_ACTION_RISK.get(
            _action(payload, "watchlist"), IntentRisk.DESTRUCTIVE
        )
    if intent is BotIntent.QUOTE:
        return QUOTE_ACTION_RISK.get(
            _action(payload, "quote"), IntentRisk.DESTRUCTIVE
        )
    return BASE_INTENT_RISK[intent]
```

- [ ] **Step 6: Add the final bounded in-memory metrics API (2–5 minutes)**

Create `core/nlu_metrics.py` with the same nested, bounded schema the observability lane will persist; later work must not redesign this class:

```python
from collections import Counter
from collections.abc import Mapping

from core.intent_models import BotIntent, IntentSource, RejectionCode

INTENT_VALUES = frozenset(intent.value for intent in BotIntent)
SOURCE_VALUES = frozenset({"deterministic", "semantic"})
DECISION_OUTCOMES = frozenset({
    "routed", "clarified", "blocked", "low_confidence", "staged",
    "executed", "failed", "canceled", "other",
})
REJECTION_VALUES = frozenset(code.value for code in RejectionCode)
PENDING_EVENTS = frozenset({
    "staged", "confirmed", "canceled", "selected", "corrected", "expired",
    "claim_failed", "dispatch_failed", "presentation_failed", "other",
})
ACTION_RESULTS = frozenset({
    "accepted", "invalid_json", "unknown_action", "unknown_key",
    "invalid_slot", "missing_slot", "multiple_proposals", "legacy", "other",
})
PARSER_NAMES = frozenset({
    "calendar", "reminder", "poll", "watchlist", "quote", "birthday", "profile",
    "countdown", "price", "horoscope", "compliment", "calculator",
    "shorten", "search", "action_schema", "other",
})
PARSER_ERROR_CODES = frozenset({
    "invalid_temporal", "invalid_payload", "exception", "other",
})
REMINDER_EVENTS = frozenset({
    "attempted", "sent", "send_failed", "catchup_sent", "deduplicated",
    "digest_sent", "digest_failed", "other",
})
REMINDER_ERROR_CODES = frozenset({
    "channel_missing", "send_forbidden", "send_http", "manager_error",
    "invalid_due_at", "none", "other",
})
LEGACY_FAMILIES = frozenset({
    "calendar", "reminder", "poll", "watchlist", "quote", "birthday", "other",
})
METRIC_SECTIONS = frozenset({
    "decisions", "rejections", "pending", "actions", "parser_errors",
    "legacy_payload_fallbacks", "reminder_delivery",
})


def _raw_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return enum_value if isinstance(enum_value, str) else "other"


def _bounded(value: object, allowed: frozenset[str]) -> str:
    raw = _raw_value(value)
    return raw if raw in allowed else "other"


def _allowed_metric_keys() -> dict[str, frozenset[str]]:
    decision_keys = frozenset(
        f"intent={intent}|source={source}|outcome={outcome}"
        for intent in INTENT_VALUES | {"other"}
        for source in SOURCE_VALUES | {"other"}
        for outcome in DECISION_OUTCOMES
    )
    parser_keys = frozenset(
        f"parser={parser}|code={code}"
        for parser in PARSER_NAMES
        for code in PARSER_ERROR_CODES
    )
    reminder_keys = frozenset(
        f"event={event}|error={code}"
        for event in REMINDER_EVENTS
        for code in REMINDER_ERROR_CODES
    )
    return {
        "decisions": decision_keys,
        "rejections": REJECTION_VALUES | {"other"},
        "pending": PENDING_EVENTS,
        "actions": ACTION_RESULTS,
        "parser_errors": parser_keys,
        "legacy_payload_fallbacks": LEGACY_FAMILIES,
        "reminder_delivery": reminder_keys,
    }


ALLOWED_METRIC_KEYS = _allowed_metric_keys()


class NLUMetrics:
    def __init__(self) -> None:
        self._counts: dict[str, Counter[str]] = {
            section: Counter() for section in METRIC_SECTIONS
        }

    def _increment(self, section: str, key: str, count: int = 1) -> None:
        if key in ALLOWED_METRIC_KEYS[section] and count > 0:
            self._counts[section][key] += count

    def record_decision(
        self, *, intent: BotIntent | str, source: IntentSource | str, outcome: str
    ) -> None:
        key = (
            f"intent={_bounded(intent, INTENT_VALUES)}|"
            f"source={_bounded(source, SOURCE_VALUES)}|"
            f"outcome={_bounded(outcome, DECISION_OUTCOMES)}"
        )
        self._increment("decisions", key)

    def record_rejection(self, code: RejectionCode | str) -> None:
        self._increment("rejections", _bounded(code, REJECTION_VALUES))

    def record_pending(self, event: str) -> None:
        self._increment("pending", _bounded(event, PENDING_EVENTS))

    def record_action_result(self, result: str) -> None:
        self._increment("actions", _bounded(result, ACTION_RESULTS))

    def record_parser_error(self, parser: str, code: str) -> None:
        key = (
            f"parser={_bounded(parser, PARSER_NAMES)}|"
            f"code={_bounded(code, PARSER_ERROR_CODES)}"
        )
        self._increment("parser_errors", key)

    def record_legacy_payload_fallback(self, family: str) -> None:
        self._increment("legacy_payload_fallbacks", _bounded(family, LEGACY_FAMILIES))

    def record_reminder_delivery(
        self, event: str, *, error_code: str | None = None
    ) -> None:
        key = (
            f"event={_bounded(event, REMINDER_EVENTS)}|"
            f"error={_bounded(error_code or 'none', REMINDER_ERROR_CODES)}"
        )
        self._increment("reminder_delivery", key)

    def merge_snapshot(self, delta: Mapping[str, Mapping[str, int]]) -> None:
        for section, values in delta.items():
            if section not in METRIC_SECTIONS or not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                if (
                    isinstance(key, str) and isinstance(value, int)
                    and not isinstance(value, bool) and 0 < value <= 2**63 - 1
                ):
                    self._increment(section, key, value)

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            section: dict(sorted(self._counts[section].items()))
            for section in sorted(METRIC_SECTIONS)
            if self._counts[section]
        }
```

- [ ] **Step 7: Replace declarations with exact re-exports and break the import cycle (2–5 minutes)**

In `core/intent_router.py`, delete the local `BotIntent` and `IntentResult` declarations plus now-unused `dataclass`, `field`, and `Enum` imports. Import and re-export:

```python
from core.intent_models import (
    BotIntent, IntentCandidate, IntentResult, IntentRisk, IntentSource,
    RouteDiagnostics, RoutedIntent,
)
```

Do not wrap or subclass these types. In `core/intent_thresholds.py`, replace `from core.intent_router import BotIntent` with `from core.intent_models import BotIntent`.

- [ ] **Step 8: Run model and compatibility tests (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_intent_models.py tests/test_nlu_metrics.py \
  tests/test_intent_router.py tests/test_confidence_thresholds.py -q
```

Expected: all tests pass; existing router payloads/reasons remain unchanged.

- [ ] **Step 9: Commit Task 2 (2–5 minutes)**

```bash
git add core/intent_models.py core/intent_policy.py core/message_context.py \
  core/nlu_metrics.py core/intent_router.py core/intent_thresholds.py \
  tests/test_intent_models.py tests/test_nlu_metrics.py
git commit -m "refactor: centralize intent and risk models"
```

### Task 3: Normalize utterances and classify speech acts safely

**Files:**

- Create: `core/utterance.py`
- Create: `core/utterance_semantics.py`
- Create: `tests/test_utterance.py`
- Create: `tests/test_utterance_semantics.py`
- Modify: `core/intent_utils.py:1-70`

**Interfaces:**

- Consumes cleaned, already-authorized message content.
- Produces `NormalizedUtterance`, `normalize_utterance(text)`, `SpeechAct`, `UtteranceSemantics`, `analyze_utterance(utterance)`, `is_negated_action(utterance, action_terms)`, and `evidence_is_quoted_only(utterance, terms)`.
- `text` remains case-preserving for payload parsers; `control_text` is casefolded and masks Discord mentions, quoted spans, Markdown inline code, and fenced code for control/evidence checks. `tokens` are derived from `control_text`, never from inert examples.

- [ ] **Step 1: Write the normalization red tests (2–5 minutes)**

Create `tests/test_utterance.py`:

```python
import pytest

from core.utterance import normalize_utterance


def test_normalization_is_lossless_for_payload_text_and_masks_control_spans():
    utterance = normalize_utterance(
        '  Kan   <@!42> forklare “Slett Påminnelse 1” i morgen?  '
    )
    assert utterance.text == 'Kan <@!42> forklare “Slett Påminnelse 1” i morgen?'
    assert utterance.folded == 'kan <@!42> forklare “slett påminnelse 1” i morgen?'
    assert utterance.quoted_segments == ("Slett Påminnelse 1",)
    assert "42" not in utterance.control_text
    assert "slett" not in utterance.control_text
    assert "i morgen" in utterance.control_text


def test_blank_normalization_is_deterministic():
    utterance = normalize_utterance(" \n\t ")
    assert (utterance.text, utterance.folded, utterance.control_text) == ("", "", "")
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


def test_discord_multiline_quote_is_inert_through_eof():
    utterance = normalize_utterance(
        "forklar dette:\n>>> slett kalenderen\nopprett møte i morgen"
    )
    assert "slett" not in utterance.control_text
    assert "opprett" not in utterance.control_text
    assert "i morgen" not in utterance.control_text


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


def test_apostrophe_in_contraction_is_not_treated_as_a_quote():
    utterance = normalize_utterance("don't forget the meeting")
    assert "don't forget" in utterance.control_text
```

- [ ] **Step 2: Run the normalization red tests (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_utterance.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'core.utterance'`.

- [ ] **Step 3: Implement lossless normalization (2–5 minutes)**

Create `core/utterance.py` exactly around this contract and algorithm:

```python
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_QUOTED = re.compile(
    r'"([^"\n]*)"|“([^”\n]*)”|‘([^’\n]*)’|'
    r'«([^»\n]*)»|(?<!\w)\'([^\'\n]+)\'(?!\w)'
)
_MULTILINE_BLOCKQUOTE = re.compile(
    r"(?m)^ {0,3}>>>(?!>)[^\n]*(?:\n|$)"
)
_BLOCKQUOTE = re.compile(r"(?m)^ {0,3}>[^\n]*(?:\n|$)")
_MENTION = re.compile(r"<@!?\d+>")
_FENCE_OPEN = re.compile(
    r"(?m)^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})[^\n]*$"
)
_TOKEN = re.compile(
    r"\d{1,2}(?::\d{2})|\d{1,2}(?:[./]\d{1,2})(?:[./]\d{2,4})?"
    r"|[^\W\d_]+(?:['’][^\W\d_]+)?|\d+",
    re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class NormalizedUtterance:
    raw: str
    text: str
    folded: str
    control_text: str
    quoted_segments: tuple[str, ...]
    tokens: tuple[str, ...]


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _mask_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if not chars[index].isspace():
            chars[index] = " "


def _fenced_spans(value: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while opener := _FENCE_OPEN.search(value, cursor):
        marker = opener.group("marker")
        close = re.compile(
            rf"(?m)^ {{0,3}}{re.escape(marker[0])}"
            rf"{{{len(marker)},}}[ \t]*(?:\n|$)"
        ).search(value, opener.end())
        end = close.end() if close is not None else len(value)
        spans.append((opener.start(), end))
        cursor = end
        if close is None:
            break
    return tuple(spans)


def _overlaps(spans: tuple[tuple[int, int], ...], start: int, end: int) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _inline_code_spans(
    value: str,
    fenced: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        if value[index] != "`" or _overlaps(fenced, index, index + 1):
            index += 1
            continue
        end_run = index
        while end_run < len(value) and value[end_run] == "`":
            end_run += 1
        marker = value[index:end_run]
        close = value.find(marker, end_run)
        while close >= 0 and _overlaps(fenced, close, close + len(marker)):
            close = value.find(marker, close + len(marker))
        if close < 0:
            newline = value.find("\n", end_run)
            end = len(value) if newline < 0 else newline
            spans.append((index, end))
            index = end
            continue
        spans.append((index, close + len(marker)))
        index = close + len(marker)
    return tuple(spans)


def normalize_utterance(raw: str) -> NormalizedUtterance:
    if not isinstance(raw, str):
        raise TypeError("utterance must be str")
    normalized = unicodedata.normalize("NFKC", raw)
    text = _collapse(normalized)
    folded = text.casefold()
    control_chars = list(normalized)
    fenced = _fenced_spans(normalized)
    inline = _inline_code_spans(normalized, fenced)
    inert_code = fenced + inline
    for start, end in inert_code:
        _mask_span(control_chars, start, end)
    quoted: list[str] = []
    multiline_match = next(
        (
            match
            for match in _MULTILINE_BLOCKQUOTE.finditer(normalized)
            if not _overlaps(inert_code, match.start(), match.end())
        ),
        None,
    )
    multiline_blockquotes = (
        ((multiline_match.start(), len(normalized)),)
        if multiline_match is not None
        else ()
    )
    line_blockquotes = tuple(
        (match.start(), match.end())
        for match in _BLOCKQUOTE.finditer(normalized)
        if not _overlaps(
            inert_code + multiline_blockquotes,
            match.start(),
            match.end(),
        )
    )
    blockquotes = tuple(sorted(multiline_blockquotes + line_blockquotes))
    for start, end in blockquotes:
        quoted.append(_collapse(normalized[start:end].lstrip(" >")))
        _mask_span(control_chars, start, end)
    for match in _QUOTED.finditer(normalized):
        if _overlaps(inert_code + blockquotes, match.start(), match.end()):
            continue
        body = next(group for group in match.groups() if group is not None)
        quoted.append(_collapse(body))
        _mask_span(control_chars, match.start(), match.end())
    for match in _MENTION.finditer(normalized):
        _mask_span(control_chars, match.start(), match.end())
    control_text = _collapse("".join(control_chars)).casefold()
    return NormalizedUtterance(
        raw=raw,
        text=text,
        folded=folded,
        control_text=control_text,
        tokens=tuple(match.group(0) for match in _TOKEN.finditer(control_text)),
        quoted_segments=tuple(quoted),
    )
```

- [ ] **Step 4: Adapt all keyword helpers to masked control text (2–5 minutes)**

In `core/intent_utils.py`, define `TextInput = str | NormalizedUtterance` and this one conversion helper:

```python
from core.utterance import NormalizedUtterance

TextInput = str | NormalizedUtterance


def _control(content: TextInput) -> str:
    return content.control_text if isinstance(content, NormalizedUtterance) else content
```

Change the first parameter annotation of `has_keyword`, `has_any_keyword`, `has_all_keywords`, and `extract_keywords` to `TextInput`. In `has_keyword`, apply the existing boundary regex to `_control(content)`. The other three functions continue delegating to `has_keyword`; do not duplicate normalization or change return types.

- [ ] **Step 5: Run normalization and keyword tests green (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_utterance.py tests/test_intent_utils.py -q`

Expected: all tests pass.

- [ ] **Step 6: Write speech-act and negation red tests (2–5 minutes)**

Create `tests/test_utterance_semantics.py`:

```python
import pytest

from core.utterance import normalize_utterance
from core.utterance_semantics import (
    SpeechAct, analyze_utterance, evidence_is_quoted_only, is_negated_action,
)


@pytest.mark.parametrize(
    "text",
    [
        "ikke slett kalenderen", "slett ikke kalenderen",
        "ikkje slett kalenderen", "do not delete the calendar",
        "never delete the calendar",
        "I can't delete the calendar",
        "I can’t delete the calendar",
        "I cannot delete the calendar",
        "I won't delete the calendar",
        "I won’t delete the calendar",
        "I shouldn't delete the calendar",
        "I shouldn’t delete the calendar",
        "jeg vil ikke at du skal slette kalenderen",
        "I do not want you to delete the calendar",
    ],
)
def test_negated_delete_disallows_mutation(text):
    utterance = normalize_utterance(text)
    assert is_negated_action(
        utterance,
        ("slett", "slette", "sletter", "slettar", "delete"),
    ) is True
    assert analyze_utterance(utterance).allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem møte i morgen kl 14",
        "ikkje gløym møte i morgon klokka 14",
        "don't forget the meeting tomorrow at 2pm",
    ],
)
def test_do_not_forget_idiom_is_positive(text):
    assert analyze_utterance(normalize_utterance(text)).allows_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem å ikke opprette møtet",
        "ikkje gløym å ikkje opprette møtet",
        "don't forget not to create the meeting",
    ],
)
def test_second_negation_is_not_erased_by_positive_forget(text):
    utterance = normalize_utterance(text)
    assert is_negated_action(
        utterance,
        ("opprette", "create"),
        allow_positive_forget=True,
    ) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hvorfor slettet du kalenderen?",
        "Kan man slette kalenderen?",
        "Er det mulig å slette kalenderen?",
        "Kan du forklare hvordan jeg sletter kalenderen?",
        "Could you explain how to delete a reminder?",
        "Why did you delete the calendar?",
        "Is it possible to delete the calendar?",
    ],
)
def test_questions_about_mutation_are_information_requests(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "Kan jeg slette kalenderen?",
        "Kan eg slette kalenderen?",
        "Kan æ slette kalenderen?",
        "Can I delete the calendar?",
        "May I delete the calendar?",
        "Could I delete the calendar?",
    ],
)
def test_permission_questions_about_actions_are_information_requests(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "Hvis du sletter kalenderen, mister jeg alt",
        "Om du slettar kalenderen, mistar eg alt",
        "If you delete the calendar, I lose everything",
    ],
)
def test_subject_general_conditionals_are_hypothetical(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.HYPOTHETICAL
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "det var et godt forslag",
        "kalenderen ble slettet i går",
        "the reminder was deleted yesterday",
    ],
)
def test_substrings_and_past_descriptions_are_not_directives(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.STATEMENT


def test_quoted_action_is_not_control_evidence():
    utterance = normalize_utterance('hva skjer hvis jeg skriver "slett kalenderen"?')
    assert evidence_is_quoted_only(utterance, ("slett", "kalender")) is True
    assert analyze_utterance(utterance).speech_act is SpeechAct.HYPOTHETICAL


@pytest.mark.parametrize("text", ["kan du slette kalenderen?", "could you delete reminder 1?"])
def test_polite_question_form_is_a_directive(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


def test_information_question_does_not_allow_mutation():
    semantics = analyze_utterance(normalize_utterance("Når går toget i morgen kl 8?"))
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "jeg vurderer kanskje å slette møte",
        "eg vurderer å slette møte",
        "jeg tenker på å slette møte",
        "I am considering deleting the meeting",
        "maybe I should delete the meeting",
    ],
)
def test_hedged_action_is_hypothetical_not_a_directive(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.HYPOTHETICAL
    assert semantics.allows_mutation is False
```

- [ ] **Step 7: Run the speech-act red tests (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_utterance_semantics.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'core.utterance_semantics'`.

- [ ] **Step 8: Implement explicit speech-act precedence and negation windows (2–5 minutes)**

Create `core/utterance_semantics.py` with these exact types, phrase sets, and precedence:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from collections.abc import Iterable

from core.utterance import NormalizedUtterance


class SpeechAct(str, Enum):
    DIRECTIVE = "directive"
    INFORMATION_REQUEST = "information_request"
    STATEMENT = "statement"
    HYPOTHETICAL = "hypothetical"
    META = "meta"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"


@dataclass(frozen=True, slots=True)
class UtteranceSemantics:
    speech_act: SpeechAct
    reasons: tuple[str, ...]
    allows_mutation: bool


CONFIRMATIONS = frozenset({"ja", "yes", "jepp", "bekreft", "confirm", "ok", "okay"})
REJECTIONS = frozenset({
    "nei", "no", "avbryt", "cancel", "stopp", "dropp det",
    "ikke gjør det", "ikkje gjer det",
})
HYPOTHETICAL_FRAMES = (
    "hva skjer hvis", "kva skjer om", "ka skjer hvis", "what happens if",
    "hvis jeg", "om jeg", "if i ", "hvis du", "om du", "if you ",
)
HYPOTHETICAL_PATTERNS = (
    re.compile(r"\b(?:jeg|eg)\s+vurderer\s+(?:kanskje\s+)?å\b"),
    re.compile(r"\b(?:jeg|eg)\s+tenker\s+på\s+å\b"),
    re.compile(r"\bi\s+am\s+considering\b"),
    re.compile(r"\bmaybe\s+i\s+should\b"),
)
META_FRAMES = (
    "jeg skrev", "eg skreiv", "i wrote", "eksempel", "example",
    "hva betyr", "kva tyder", "what does", "hvordan skriver",
)
POLITE_DIRECTIVES = (
    "kan du", "kunne du", "vil du", "vennligst", "vær så snill",
    "could you", "would you", "please",
)
QUESTION_STARTS = (
    "hva ", "kva ", "ka ", "hvordan ", "korleis ", "når ", "where ",
    "when ", "what ", "how ", "why ", "hvor ", "kor ",
)
INFORMATION_MUTATION_PATTERNS = (
    re.compile(r"^(?:hvorfor|kvifor|why)\b"),
    re.compile(
        r"^(?:kan\s+man|er\s+det\s+mulig\s+å|can\s+one|"
        r"is\s+it\s+possible\s+to)\b"
    ),
    re.compile(
        r"^(?:kan\s+du|kunne\s+du|could\s+you|would\s+you)\s+"
        r"(?:forklare|vise|fortelle|explain|show|tell)\b.*"
        r"\b(?:hvordan|korleis|how)\b"
    ),
)
PERMISSION_QUESTION_PATTERN = re.compile(
    r"^(?:kan\s+(?:jeg|eg|æ)|can\s+i|may\s+i|could\s+i)\b"
)
ACTION_TERMS = frozenset({
    "slett", "slette", "sletter", "slettar", "delete", "deleting",
    "fjern", "fjerne", "remove", "tøm", "tømme", "clear", "endre", "edit",
    "rediger", "flytt", "move", "opprett", "opprette", "create",
    "lag", "lage", "add", "legg",
    "husk", "glem", "gløym", "forget", "påminn", "minn", "stem", "vote",
    "lukk", "close", "fullfør", "complete", "synk", "sync", "forkort",
})
NEGATIONS = frozenset({
    "ikke", "ikkje", "aldri", "not", "never", "don't", "don’t",
    "can't", "can’t", "cannot", "won't", "won’t", "shouldn't", "shouldn’t",
})
POSITIVE_FORGET = ("ikke glem", "ikkje gløym", "don't forget", "don’t forget")


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    tokens = tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text.casefold()))
    return any(
        needle and any(True for _ in _token_starts(tokens, needle))
        for needle in (_term_tokens(phrase) for phrase in phrases)
    )


def _term_tokens(term: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", term.casefold()))


def _token_starts(tokens: tuple[str, ...], needle: tuple[str, ...]):
    width = len(needle)
    for index in range(0, len(tokens) - width + 1):
        if tokens[index:index + width] == needle:
            yield index


def is_negated_action(
    utterance: NormalizedUtterance,
    action_terms: Iterable[str],
    *,
    allow_positive_forget: bool = False,
) -> bool:
    tokens = utterance.tokens
    ignored_negations: set[int] = set()
    if allow_positive_forget:
        for phrase in POSITIVE_FORGET:
            needle = _term_tokens(phrase)
            for start in _token_starts(tokens, needle):
                ignored_negations.add(start)
    for term in action_terms:
        needle = _term_tokens(term)
        if not needle:
            continue
        for index in _token_starts(tokens, needle):
            left = max(0, index - 8)
            right = min(len(tokens), index + len(needle) + 4)
            negated_indices = {
                offset
                for offset in range(left, right)
                if tokens[offset] in NEGATIONS
            }
            if negated_indices - ignored_negations:
                return True
    return False


def evidence_is_quoted_only(
    utterance: NormalizedUtterance, terms: Iterable[str]
) -> bool:
    normalized = tuple(term.casefold().strip() for term in terms if term.strip())
    present = tuple(
        term for term in normalized
        if _contains_phrase(utterance.folded, (term,))
    )
    if not present:
        return False
    return not _contains_phrase(utterance.control_text, present)


def analyze_utterance(utterance: NormalizedUtterance) -> UtteranceSemantics:
    text = utterance.control_text.strip()
    if text in CONFIRMATIONS:
        return UtteranceSemantics(SpeechAct.CONFIRMATION, ("exact_confirmation",), False)
    if text in REJECTIONS:
        return UtteranceSemantics(SpeechAct.REJECTION, ("exact_rejection",), False)
    if _contains_phrase(text, HYPOTHETICAL_FRAMES) or any(
        pattern.search(text) for pattern in HYPOTHETICAL_PATTERNS
    ):
        return UtteranceSemantics(SpeechAct.HYPOTHETICAL, ("hypothetical_frame",), False)
    if _contains_phrase(text, META_FRAMES):
        return UtteranceSemantics(SpeechAct.META, ("meta_frame",), False)
    if any(pattern.search(text) for pattern in INFORMATION_MUTATION_PATTERNS):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("information_question",),
            False,
        )
    if PERMISSION_QUESTION_PATTERN.search(text) and _contains_phrase(text, ACTION_TERMS):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("permission_question",),
            False,
        )
    if _contains_phrase(text, POLITE_DIRECTIVES):
        negated = is_negated_action(utterance, ACTION_TERMS)
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("polite_directive",) + (("negated_action",) if negated else ()),
            not negated,
        )
    if text.startswith(QUESTION_STARTS) or (
        text.endswith("?") and not _contains_phrase(text, ACTION_TERMS)
    ):
        return UtteranceSemantics(SpeechAct.INFORMATION_REQUEST, ("information_question",), False)
    if _contains_phrase(text, ACTION_TERMS):
        negated = is_negated_action(
            utterance,
            ACTION_TERMS,
            allow_positive_forget=True,
        )
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("imperative_action",) + (("negated_action",) if negated else ()),
            not negated,
        )
    return UtteranceSemantics(SpeechAct.STATEMENT, ("statement_fallback",), True)
```

- [ ] **Step 9: Run all Task 3 tests (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_utterance.py tests/test_utterance_semantics.py \
  tests/test_intent_utils.py -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit Task 3 (2–5 minutes)**

```bash
git add core/utterance.py core/utterance_semantics.py core/intent_utils.py \
  tests/test_utterance.py tests/test_utterance_semantics.py
git commit -m "feat: classify natural-language speech acts"
```

### Task 4: Resolve and validate Norwegian temporal expressions

**Objective:** Put every legacy calendar date/time path behind one bounded Europe/Oslo resolver, while preserving dictionary-or-None parser callers and boolean calendar-handler callers. Invalid, conflicting, nonexistent, or unresolved ambiguous values must stop before a manager or Google Calendar write.

**Files (the complete implementation and staging scope is exactly seven files):**

- Create: cal_system/temporal_resolver.py
- Create: tests/test_temporal_resolver.py
- Create: tests/test_natural_language_parser_safety.py
- Modify: cal_system/natural_language_parser.py
- Modify: features/calendar_handler.py
- Modify: tests/test_calendar_edit.py
- Modify: tests/test_comprehensive.py

The following suites are verification-only in this task and are not staged unless a later independent task changes them: tests/test_intent_router.py, tests/test_false_positives.py, tests/test_calendar_sync.py, and tests/test_selfbot_comprehensive.py. Do not add core/message_monitor.py to this task. MessageMonitor ownership of the sole production clock/resolver is deferred to the typed/model-action composition lane.

**Public compatibility contract:**

- TemporalResolver.resolve(text, reference=None) returns a TemporalResolution with canonical DD.MM.YYYY, HH:MM, optional offset-bearing due_at, bounded matched_text labels, stable error codes, and a valid property.
- TemporalResolver.validate_fields(date_value, time_value, due_at=None, reference=None) validates scalar fields and the combined Oslo wall time. It never accepts a value through regex shape alone.
- TemporalResolver.validate_time(value) validates and canonicalizes an isolated H or H:MM field without inventing a date; it returns HH:MM or None. Cross-field DST validation still happens through validate_fields after the target date is known.
- TemporalResolver.strip_temporal_evidence(text, reference=None) removes only spans recognized by the resolver's shared finite grammar and returns collapsed non-temporal text. It never exposes raw spans through TemporalResolution or diagnostics, and an explicit reference causes zero provider reads.
- NaturalLanguageParser.parse_event() and parse_task_with_recurrence() remain dictionary-or-None wrappers. New parse_event_result() and parse_task_with_recurrence_result() methods expose bounded errors.
- Parser and handler reference_time keywords are optional compatibility seams. Each public operation either uses the supplied aware instant without reading a provider or captures its provider exactly once.
- CalendarHandler methods continue returning bool in Task 4. DispatchOutcome and delivery-certainty conversion belong to the later typed-dispatch task.
- Task 4 may reuse monitor.nlp_parser.temporal_resolver when available, but it does not create or claim a monitor-owned identity invariant.

- [ ] **Step 1: Write the complete fixed-clock resolver matrix**

Create tests/test_temporal_resolver.py with fixed aware clocks and table-driven assertions. At minimum define:

~~~python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from cal_system.temporal_resolver import TemporalResolver

OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)
RESOLVER = TemporalResolver()
~~~

Cover the finite compatibility vocabulary, including all aliases rather than sampling one spelling:

~~~python
@pytest.mark.parametrize(
    ("text", "date", "time"),
    [
        ("i dag kl 13", "14.07.2026", "13:00"),
        ("idag 13:30", "14.07.2026", "13:30"),
        ("today at 1pm", "14.07.2026", "13:00"),
        ("i morgen kl 8", "15.07.2026", "08:00"),
        ("imorgen kl 8", "15.07.2026", "08:00"),
        ("imorra kl 8", "15.07.2026", "08:00"),
        ("imårra kl 8", "15.07.2026", "08:00"),
        ("i morgon klokka fjorten", "15.07.2026", "14:00"),
        ("tomorrow at 2pm", "15.07.2026", "14:00"),
        ("i overmorgen kl 9", "16.07.2026", "09:00"),
        ("overmorgen kl 9", "16.07.2026", "09:00"),
        ("i overmorgon kl 9", "16.07.2026", "09:00"),
        ("overmorgon kl 9", "16.07.2026", "09:00"),
        ("day after tomorrow at 9", "16.07.2026", "09:00"),
        ("fredag kl 10", "17.07.2026", "10:00"),
        ("om to timer", "14.07.2026", "14:00"),
        ("15. august rundt tre på ettermiddagen", "15.08.2026", "15:00"),
        ("15. august noon", "15.08.2026", "12:00"),
        ("15. august midnatt", "15.08.2026", "00:00"),
        ("15. august midnight", "15.08.2026", "00:00"),
    ],
)
def test_resolve_finite_compatibility_vocabulary(text, date, time):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True
    assert (result.date, result.time) == (date, time)
~~~

Add direct cases for raw 00:00, 08:05, and 23:59 without kl/at; raw 25:61 must report invalid_time instead of disappearing as no evidence. Test cue hours, am/pm, number words zero through thirty-one, Norwegian/English month names, weekdays, neste/next and førstkommende semantics, and relative minutes/hours/days/weeks.

Pin shared title cleanup without exposing spans: strip_temporal_evidence("ring legen i morgen kl 14", reference=NOW) returns "ring legen"; relative, weekday, numeric-date, raw-time, daypart, and special-hour forms use the same collector; non-temporal text is unchanged; explicit reference reads the provider zero times. The method must not maintain a second regex vocabulary.

Pin the finite daypart behavior:

- i morges, i formiddag, and på formiddagen -> 10:00
- i ettermiddag and på ettermiddagen -> 14:00
- i kveld and på kvelden -> 19:00
- i natt and på natten -> 22:00
- noon -> 12:00
- midnatt and midnight -> 00:00
- The bare nouns formiddag, ettermiddag, kveld, and natt are time evidence only when the same utterance contains separate live date evidence, so imorgen kveld resolves to 19:00 while ordinary text such as ha en fin kveld remains non-temporal.
- A disjoint explicit time may refine a daypart default only inside this finite semantic range: morges 00:00..<12:00, formiddag 06:00..<12:00, ettermiddag 12:00..<18:00, kveld 18:00..<24:00, and natt 22:00..<24:00 or 00:00..<06:00. Thus i kveld kl 20 remains valid and anchored today, while kl 14 i kveld and kl 14 imorgen kveld return conflicting_temporal. Multiple distinct explicit times still conflict. Longest-first overlap lets one phrase such as rundt tre på ettermiddagen resolve as a single natural-time span.
- A cue/bare time without date uses the first future local occurrence.
- The explicit legacy phrases i kveld and i natt remain anchored to today's date even after their default wall time has passed.

Include a regression proving the hour-word matcher does not swallow the daypart introducer:

~~~python
def test_hour_word_does_not_consume_pa_before_daypart():
    result = RESOLVER.resolve(
        "15. august rundt tre på ettermiddagen",
        reference=NOW,
    )
    assert result.errors == ()
    assert (result.date, result.time) == ("15.08.2026", "15:00")
~~~

Add error and conflict matrices:

- invalid_date: 32.13.2026, 29.02.2025, dates below 1900, and dates above 2100
- invalid_time: -1:00, 24:00, 25:61, and a same-day DST gap
- ambiguous_time: a fold without a disambiguating due_at
- conflicting_temporal: distinct date evidence, distinct time evidence, relative plus absolute evidence, or relative plus a daypart
- duplicate consistent evidence such as i morgen / 15.07.2026 and kl 14 / 14:00 remains valid
- matched_text and errors contain only finite labels/codes, never user substrings

Test year rules explicitly: four-digit years must be 1900..2100; two-digit years map to 2000..2099; yearless dates choose the first non-past valid occurrence; den N. means the first non-past valid day N in the current or next month. A yearless same-day time in a DST gap returns invalid_time on that date and must never roll to the next year merely to become valid.

Test due_at against Oslo's 2026 fold:

~~~python
@pytest.mark.parametrize(
    ("due_at", "canonical"),
    [
        ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+02:00"),
        ("2026-10-25T02:30:00+01:00", "2026-10-25T02:30:00+01:00"),
        ("2026-10-25T00:30:00Z", "2026-10-25T02:30:00+02:00"),
        ("2026-10-25T01:30:00Z", "2026-10-25T02:30:00+01:00"),
    ],
)
def test_explicit_instant_disambiguates_fold(due_at, canonical):
    result = RESOLVER.validate_fields(
        "25.10.2026", "02:30", due_at=due_at, reference=NOW
    )
    assert result.valid is True
    assert result.due_at == canonical
~~~

Naive due_at, a due_at whose instant does not equal either valid Oslo fold, and a due_at whose Oslo date/time disagrees with the typed fields must fail. Include elapsed-relative tests across both DST transitions so om to timer means two UTC hours even when the local wall clock jumps or repeats.

- [ ] **Step 2: Run the resolver tests red**

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_temporal_resolver.py -q
~~~

Expected: collection fails with ModuleNotFoundError for cal_system.temporal_resolver. Do not weaken or defer a matrix row to make the first implementation smaller.

- [ ] **Step 3: Implement one bounded evidence grammar**

Create cal_system/temporal_resolver.py. Use these shared definitions for natural-hour evidence; no second parser-specific copy is allowed:

~~~python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from collections.abc import Callable
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
MIN_YEAR = 1900
MAX_YEAR = 2100

DATE_ALIASES = {
    "i dag": 0,
    "idag": 0,
    "today": 0,
    "i morgen": 1,
    "imorgen": 1,
    "imorra": 1,
    "imårra": 1,
    "i morgon": 1,
    "tomorrow": 1,
    "i overmorgen": 2,
    "overmorgen": 2,
    "i overmorgon": 2,
    "overmorgon": 2,
    "day after tomorrow": 2,
}
DAYPART_HOURS = {
    "i morges": "10:00",
    "i formiddag": "10:00",
    "på formiddagen": "10:00",
    "i ettermiddag": "14:00",
    "på ettermiddagen": "14:00",
    "i kveld": "19:00",
    "på kvelden": "19:00",
    "i natt": "22:00",
    "på natten": "22:00",
}
_CONTEXT_DAYPART_HOURS = {
    "formiddag": "10:00",
    "ettermiddag": "14:00",
    "kveld": "19:00",
    "natt": "22:00",
}
SPECIAL_HOURS = {
    "noon": "12:00",
    "midnatt": "00:00",
    "midnight": "00:00",
}

_HOUR_WORD = r"[a-zæøå]+(?:[- ]+(?!på\b)[a-zæøå]+)?"
NATURAL_TIME_RE = re.compile(
    rf"\b(?P<cue>kl(?:okka|okken)?\.?|at|rundt|about)\s+"
    rf"(?P<hour>-?\d{{1,2}}|{_HOUR_WORD})"
    r"(?::(?P<minute>\d{2}))?\s*(?P<suffix>am|pm)?"
    r"(?:\s+på\s+(?P<daypart>morgenen|morgonen|ettermiddagen|kvelden))?\b"
)
RAW_TIME_RE = re.compile(r"(?<![\d.:])(?P<hour>-?\d{1,2}):(?P<minute>\d{2})(?![\d:])")
~~~

Alias and finite phrase matching is longest-first and bounded with (?<!\w)...(?!\w); substrings inside words are not evidence. Bare entries from _CONTEXT_DAYPART_HOURS are collected only when the utterance also has a disjoint date-evidence span. First mask or otherwise deduplicate spans so one surface span cannot be interpreted by multiple time grammars. For exactly one valid disjoint explicit time inside the finite daypart range above, compare the daypart at that explicit canonical time while retaining its daypart label and date-anchor semantics; an out-of-range pairing retains independent canonical values and therefore conflicts. Multiple distinct explicit times always conflict. Every recognized-but-invalid span remains evidence and produces a stable error.

Use immutable result types:

~~~python
@dataclass(frozen=True, slots=True)
class TemporalResolution:
    date: str | None = None
    time: str | None = None
    due_at: str | None = None
    matched_text: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


class TemporalResolver:
    def __init__(
        self,
        *,
        zone: ZoneInfo = OSLO,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.zone = zone
        self._now_provider = now_provider or (lambda: datetime.now(self.zone))

    def resolve(
        self,
        text: str,
        *,
        reference: datetime | None = None,
    ) -> TemporalResolution:
        ...

    def validate_fields(
        self,
        date_value: str | None,
        time_value: str | None,
        *,
        due_at: str | None = None,
        reference: datetime | None = None,
    ) -> TemporalResolution:
        ...

    def validate_time(self, value: str) -> str | None:
        ...

    def strip_temporal_evidence(
        self,
        text: str,
        *,
        reference: datetime | None = None,
    ) -> str:
        ...
~~~

The reference boundary is strict: a supplied reference is used without reading now_provider; an omitted reference reads now_provider exactly once; naive values raise ValueError("temporal_reference_must_be_aware"); the captured value is converted to Europe/Oslo.

Collect independent date, time, and relative evidence before selecting values. The internal evidence objects may retain source offsets only for in-process cleanup; they are never serialized or copied into TemporalResolution. resolve() and strip_temporal_evidence() must call this same collector. Equal canonical evidence deduplicates. More than one distinct canonical value in a category, or a relative expression combined with an absolute date/time/daypart, returns only conflicting_temporal. Diagnostic labels are finite names such as date_alias, numeric_date, month_date, weekday, relative, natural_time, raw_time, special_hour, and daypart; never put raw user text or offsets in TemporalResolution.

- [ ] **Step 4: Implement canonical validation, year selection, and DST identity**

Field validation must construct real date/time objects:

- Accept D.M, DD.MM, slash variants, D.M.YY/DD.MM.YYYY, H, and H:MM.
- Canonical dates use an explicit f-string: f"{value.day:02d}.{value.month:02d}.{value.year:04d}".
- Canonical times use f"{value.hour:02d}:{value.minute:02d}".
- validate_time(value) uses the same scalar parser and year-independent canonical-time formatter; it accepts only H or H:MM and returns None for malformed or out-of-range input.
- Reject years outside 1900..2100 after two-digit expansion.
- A missing date or time is permitted only while resolving partial evidence; validate_fields reports missing_date when a time/due_at cannot be paired with a date.
- Date selection must consider the time when deciding whether a yearless same-day occurrence is past.

Build valid Oslo candidates by round-tripping each fold through UTC. Zero candidates is invalid_time. Two candidates with distinct UTC offsets is ambiguous_time unless due_at names one exact instant. Do not compare aware datetimes by wall fields or Python's same-zone fold equality shortcut.

Use this instant check for due_at:

~~~python
explicit = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
if explicit.tzinfo is None or explicit.utcoffset() is None:
    return TemporalResolution(errors=("invalid_time",))

explicit_utc = explicit.astimezone(timezone.utc)
matching = [
    candidate
    for candidate in valid_candidates
    if explicit_utc == candidate.astimezone(timezone.utc)
]
if len(matching) != 1:
    return TemporalResolution(errors=("invalid_time",))

canonical_due_at = explicit.astimezone(self.zone).isoformat(timespec="seconds")
~~~

The Oslo projection of explicit must agree with the requested canonical date/time. Offset forms +01:00 and +02:00 and equivalent Z instants are accepted only when their UTC instant equals a valid candidate.

For a yearless date, compute valid candidates in the current year before deciding whether to roll. The helper contract is:

- if at least one valid candidate is in the future, retain the current year;
- if every valid candidate is in the past, try the next valid year;
- if zero candidates are valid for the current same-day wall time, retain the current date and let final validation return invalid_time;
- never use a future year to hide today's nonexistent local time.

- [ ] **Step 5: Resolve bounded natural expressions**

Implement only the finite grammar pinned above:

- aliases and den N.
- numeric dates and month-name dates
- finite weekday forms with pinned neste/next/førstkommende behavior
- relative om/in N minutter, timer, dager, or uker
- natural cue time, raw HH:MM, special hour, and daypart evidence
- Norwegian number words zero through thirty-one
- am/pm conversion and daypart disambiguation

strip_temporal_evidence() masks the source offsets returned by that same finite collector, collapses whitespace and orphaned temporal separators, and returns the remaining text. It does not call resolve() with a second clock read and does not recognize any additional surface form.

A word hour 0..11 without am/pm/daypart may be ambiguous where existing behavior cannot choose a half-day; return ambiguous_time rather than guessing. The explicit "tre på ettermiddagen" maps to 15:00. Numeric 13..23 is unambiguous. Preserve the existing natural defaults only where a test names them.

Relative durations are elapsed instants: add minutes/hours in UTC, then project back to Oslo. Calendar-day and week offsets remain local calendar arithmetic. This distinction is covered across both DST transitions.

When an explicit cue or raw time has no date, choose the first future local date using the wall-time validity rules. Only the explicit compatibility phrases i kveld and i natt bypass that rollover and anchor today.

- [ ] **Step 6: Run the resolver suite green**

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_temporal_resolver.py -q
~~~

Expected: all resolver tests pass with a fixed clock and independently of the host timezone.

- [ ] **Step 7: Write parser compatibility, masking, recurrence, and clock tests**

Create tests/test_natural_language_parser_safety.py. Test both parse_event_result and parse_task_with_recurrence_result unless the assertion is deliberately event-only compatibility.

The required matrix includes:

- every date alias from DATE_ALIASES
- raw HH:MM, noon, midnatt/midnight, each daypart, and the "tre på ettermiddagen" regression
- invalid date/time and conflicting evidence return item=None with stable errors
- quoted and code-only temporal evidence does not populate date/time
- straight double, straight single, curly double/single, and guillemet quoted titles remain title data
- a curly quoted title containing temporal words does not leak those words into temporal slots
- recurrence-only input receives the canonical reference date and days_offset=0 for the legacy event shape
- event days_offset always equals canonical_date - Oslo reference.date()
- parse_task_with_recurrence keeps its existing shape and does not gain days_offset
- wrappers return dict-or-None and result methods return NaturalParseResult
- an omitted reference reads now_provider once per public result operation
- an explicit aware reference reads now_provider zero times
- a naive reference raises the documented ValueError

Use an advancing provider in the clock tests rather than merely counting a constant lambda.

- [ ] **Step 8: Integrate TemporalResolver with NaturalLanguageParser**

In cal_system/natural_language_parser.py, add NaturalParseResult and optional compatibility seams:

~~~python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from cal_system.temporal_resolver import OSLO, TemporalResolver


@dataclass(frozen=True, slots=True)
class NaturalParseResult:
    item: dict[str, Any] | None
    errors: tuple[str, ...] = ()


def __init__(
    self,
    now_provider: Callable[[], datetime] | None = None,
    *,
    temporal_resolver: TemporalResolver | None = None,
):
    self._now_provider = now_provider or (lambda: datetime.now(OSLO))
    self.temporal_resolver = temporal_resolver or TemporalResolver()
    self.setup_patterns()
~~~

All four public parse methods keep these optional keywords:

~~~python
def parse_event_result(
    self,
    message_content: str,
    *,
    temporal_text: str | None = None,
    reference_time: datetime | None = None,
) -> NaturalParseResult:
    ...

def parse_event(
    self,
    message_content: str,
    *,
    temporal_text: str | None = None,
    reference_time: datetime | None = None,
) -> dict[str, Any] | None:
    return self.parse_event_result(
        message_content,
        temporal_text=temporal_text,
        reference_time=reference_time,
    ).item

def parse_task_with_recurrence_result(
    self,
    message_content: str,
    *,
    temporal_text: str | None = None,
    reference_time: datetime | None = None,
) -> NaturalParseResult:
    ...

def parse_task_with_recurrence(
    self,
    message_content: str,
    *,
    temporal_text: str | None = None,
    reference_time: datetime | None = None,
) -> dict[str, Any] | None:
    return self.parse_task_with_recurrence_result(
        message_content,
        temporal_text=temporal_text,
        reference_time=reference_time,
    ).item
~~~

Each result method supplies its operation's one reference to a private helper. If reference_time is omitted, capture self._now_provider() once; if supplied, do not read it. Reject naive values and convert to Oslo. The dictionary wrapper delegates and must not capture separately.

The raw legacy parser owns title, type, and recurrence only. The compatibility wrapper owns every temporal slot:

1. Run TemporalResolver on temporal_text when supplied, otherwise on message_content.
2. If matched temporal evidence is invalid, return NaturalParseResult(None, errors).
3. Run the raw parser against original case-preserving message_content using the same reference.
4. Copy its non-temporal payload, removing raw date, time, and any stale days_offset.
5. Overlay only canonical resolver date/time/due_at.
6. If recurrence exists with no explicit live date, use the canonical Oslo reference date.
7. Revalidate the final date/time/due_at pair.
8. If no canonical date remains, return item=None; never return a malformed partial item.
9. For the legacy event shape only, restore days_offset as (canonical_date - reference.date()).days. Do not add it to the task shape.

Keep days_offset through Task 5 solely as a finite compatibility field. The later typed dispatch converts it to typed temporal data and removes it at its boundary.

Expand legacy quoted-title extraction to the same straight/curly/guillemet forms recognized by Task 3. Title parsing receives original message_content, while TemporalResolver receives masked control_text when the caller has a NormalizedUtterance. Temporal words inside quotes/code can therefore remain title data but never become control slots.

Update tests/test_comprehensive.py only where old assertions expect noncanonical dates or stale days_offset arithmetic. Preserve each compatibility scenario; change its expected value instead of deleting the case.

- [ ] **Step 9: Write calendar create/edit defense and GCal duration tests**

Extend tests/test_calendar_edit.py with spies for the manager, GCal provider, now provider, and message send. Required assertions:

- invalid create date/time makes zero CalendarManager and zero GCal calls
- valid create makes exactly one manager call and at most the intended one GCal call
- every handler path returns bool
- an omitted reference reads the handler provider once
- an explicit aware reference reads it zero times
- a naive explicit reference raises before reads or writes
- edit scalar validation happens before target lookup
- time edit scalar validation uses TemporalResolver.validate_time(value); it does not call resolve() and does not invent a date
- index and title target forms both read only the target needed for pair validation
- changing date while retaining the target's time detects a spring gap/autumn fold
- changing time while retaining the target's date detects a spring gap/autumn fold
- invalid, missing, or ambiguous effective pairs make zero edit and zero GCal calls
- a valid edit performs one edit
- a one-hour GCal event remains exactly 3600 elapsed seconds across both DST transitions

- [ ] **Step 10: Add optional single-capture handler seams and validate before writes**

In features/calendar_handler.py, use this transitional constructor and method contract:

~~~python
def __init__(
    self,
    monitor,
    *,
    temporal_resolver: TemporalResolver | None = None,
    now_provider: Callable[[], datetime] | None = None,
):
    inherited = getattr(
        getattr(monitor, "nlp_parser", None),
        "temporal_resolver",
        None,
    )
    self.temporal_resolver = temporal_resolver or inherited or TemporalResolver()
    self._now_provider = now_provider or (lambda: datetime.now(OSLO))
    ...

async def handle_save_request(
    self,
    message,
    title,
    date,
    time,
    *,
    reference_time: datetime | None = None,
) -> bool:
    ...

async def handle_calendar_item(
    self,
    message,
    item,
    *,
    reference_time: datetime | None = None,
) -> bool:
    ...

async def handle_edit(
    self,
    message,
    payload=None,
    *,
    reference_time: datetime | None = None,
) -> bool:
    ...

def _parse_date_value(
    self,
    value: str,
    *,
    reference_time: datetime,
) -> str | None:
    ...
~~~

Add one _capture_reference(reference_time) helper. A supplied aware value is converted to Oslo without a provider read; an omitted value reads _now_provider exactly once; a naive value raises ValueError("calendar_reference_must_be_aware"). handle_save_request retains the existing positional message, title, date, and time API, builds the same compatibility item, and returns handle_calendar_item's boolean while forwarding its optional reference so only the actual operation boundary captures.

Create path:

1. capture once;
2. canonicalize and validate the complete date/time/due_at pair;
3. on invalid_date, invalid_time, ambiguous_time, missing_date, or conflicting_temporal, send the fixed Norwegian clarification and return False;
4. do not call CalendarManager or GCal on failure;
5. call the manager once with canonical fields on success and return the established boolean result.

Edit path must validate in two phases, all before any write:

1. capture once;
2. scalar-canonicalize a proposed date with _parse_date_value(..., reference_time=captured) or a proposed time with temporal_resolver.validate_time(value) before reading a target; an invalid scalar returns False with zero target/provider/write calls;
3. resolve/read only the target item: preserve the existing title lookup, and for an index use the existing bounded 365-day snapshot;
4. combine the proposed field with the unchanged counterpart from that target;
5. call validate_fields on the effective pair;
6. invalid, nonexistent, or ambiguous pairs return False with no edit/GCal call;
7. a valid pair performs exactly one edit with canonical changes.

The target read is necessary for cross-field validation and is not a mutation. Do not promise that pair validation occurs before lookup; promise scalar validation before the read and pair validation after the read, with both before every write/provider mutation.

For Google Calendar, a one-hour default is elapsed time, not local wall addition:

~~~python
start_utc = start_dt.astimezone(timezone.utc)
end_dt = (start_utc + timedelta(hours=1)).astimezone(OSLO)
~~~

Never add the hour directly to the local start datetime across a DST fold/gap.

- [ ] **Step 11: Run focused, compatibility, integration, and full gates**

Run the narrow resolver gate first:

~~~bash
.venv312/bin/python -m pytest tests/test_temporal_resolver.py -q
~~~

Then the parser/router safety gate:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_temporal_resolver.py \
  tests/test_natural_language_parser_safety.py \
  tests/test_intent_router.py \
  tests/test_false_positives.py -q
~~~

Then the calendar compatibility/integration gate:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_temporal_resolver.py \
  tests/test_natural_language_parser_safety.py \
  tests/test_calendar_edit.py \
  tests/test_calendar_sync.py \
  tests/test_selfbot_comprehensive.py \
  tests/test_comprehensive.py -q
~~~

Before the full suite, run the repository disk guard:

~~~bash
df -h /System/Volumes/Data
~~~

Stop and report if free space is below 30 GiB. Otherwise run:

~~~bash
.venv312/bin/python -m pytest -q
~~~

Finally rerun the Task 1 report-only NLU readback and compare its exact artifact/counts without promoting later Task 5 corpus rows into this task's red/green gate.

- [ ] **Step 12: Stage exactly seven files and commit**

First verify the staged set:

~~~bash
git add cal_system/temporal_resolver.py \
  cal_system/natural_language_parser.py \
  features/calendar_handler.py \
  tests/test_temporal_resolver.py \
  tests/test_natural_language_parser_safety.py \
  tests/test_calendar_edit.py \
  tests/test_comprehensive.py
git diff --cached --name-only
~~~

The output must be exactly those seven paths. Verification-only suites and core/message_monitor.py remain unstaged.

Commit:

~~~bash
git commit -m "feat: resolve and validate natural temporal expressions"
~~~

Expected: focused tests and the full suite pass; the commit contains exactly the declared seven-file implementation scope.

---

### Task 5: Replace first-match routing with risk-aware candidate arbitration

**Files (the complete implementation and staging scope is exactly eleven files):**

- Create: `core/intent_arbitration.py`
- Create: `tests/test_intent_arbitration.py`
- Modify: `core/intent_router.py:101-729`
- Modify: `cal_system/reminder_manager.py` — pure reminder parser vocabulary and injected-time contract only
- Modify: `features/watchlist_manager.py` — complete pure watchlist parser prerequisite only
- Modify: `tests/nlu_harness.py`
- Modify: `tests/test_intent_router.py`
- Modify: `tests/test_reminder_crud.py`
- Modify: `tests/test_false_positives.py`
- Modify: `tests/fixtures/nlu_contract_v1.jsonl`
- Modify: `tests/test_nlu_contract.py`

`tests/test_watchlist_scope.py` already contains the scoped direct watchlist parser cases and is a focused gate only. Task 5 runs it but does not modify or stage it; new route-level watchlist assertions belong in `tests/test_intent_router.py`.

**Interfaces:**

- Consumes `NormalizedUtterance`, `UtteranceSemantics`, `IntentCandidate`, `RoutingContext`, `TemporalResolver`, and the Task 2 policy/metrics sink.
- Produces `arbitrate_candidates(utterance, semantics, candidates)`, `IntentRouter.evaluate_utterance(utterance, guild_id=None, *, channel_id=None, user_id=None, routing_context=None, reference_time=None) -> RoutedIntent`, the identically parameterized `route_utterance` wrapper returning `IntentResult` defined in Step 10, and the stable pure parser signature `parse_reminder_command(message_content, *, now=None, temporal_resolver=None)` consumed unchanged by the typed runtime lane.
- Keeps `route(content, guild_id=None)` compatible. No handler or downstream orchestration component is invoked in this plan.

- [ ] **Step 1: Write pure arbitration red tests (2–5 minutes)**

Create `tests/test_intent_arbitration.py`:

```python
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
        intent, confidence, priority, order=order,
        reason="test_candidate", risk=risk, source=source,
        action_terms=action_terms, domain_terms=domain_terms,
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
            BotIntent.SEARCH, IntentRisk.READ_ONLY, priority=80, order=361,
            confidence=0.92, action_terms=(), domain_terms=("toget",),
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
            BotIntent.POLL_CREATE, IntentRisk.ADDITIVE, priority=50, order=150,
            confidence=0.95, specificity=0, action_terms=(), domain_terms=(),
        ),
        candidate(
            BotIntent.SHORTEN_URL, IntentRisk.READ_ONLY, priority=60, order=330,
            confidence=0.90, specificity=3, action_terms=("forkort",),
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
            BotIntent.CALENDAR_ITEM, IntentRisk.ADDITIVE, priority=35, order=123,
            confidence=0.95, specificity=3, domain_terms=("møte",),
        ),
        candidate(
            BotIntent.REMINDER_CREATE, IntentRisk.ADDITIVE, priority=35, order=122,
            confidence=0.93, specificity=3, domain_terms=("påminnelse",),
        ),
    ]
    decision = arbitrate_candidates(
        utterance, analyze_utterance(utterance), candidates
    )
    assert decision.selected is not None
    assert decision.selected.intent is BotIntent.CLARIFY
    assert tuple(item.intent for item in decision.alternatives) == (
        BotIntent.REMINDER_CREATE, BotIntent.CALENDAR_ITEM,
    )


def test_equal_non_ambiguity_tier_preserves_source_order():
    utterance = normalize_utterance("status hjelp")
    candidates = [
        candidate(
            BotIntent.HELP, IntentRisk.READ_ONLY, priority=10, order=30,
            confidence=0.95, specificity=4, action_terms=(),
            domain_terms=("hjelp",),
        ),
        candidate(
            BotIntent.STATUS, IntentRisk.READ_ONLY, priority=10, order=20,
            confidence=0.93, specificity=4, action_terms=(),
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


def test_semantic_write_requires_confirmation_but_deterministic_add_does_not():
    utterance = normalize_utterance("lag møte i morgen")
    semantic = candidate(
        BotIntent.CALENDAR_ITEM, IntentRisk.ADDITIVE, priority=35,
        source=IntentSource.SEMANTIC,
    )
    deterministic = candidate(
        BotIntent.CALENDAR_ITEM, IntentRisk.ADDITIVE, priority=35,
        source=IntentSource.DETERMINISTIC,
    )
    assert arbitrate_candidates(utterance, analyze_utterance(utterance), [semantic]).selected.requires_confirmation
    assert not arbitrate_candidates(utterance, analyze_utterance(utterance), [deterministic]).selected.requires_confirmation
```

- [ ] **Step 2: Run the arbitration red tests (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_intent_arbitration.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'core.intent_arbitration'`.

- [ ] **Step 3: Implement pure risk filtering, ordering, ambiguity, and confirmation (2–5 minutes)**

Create `core/intent_arbitration.py`:

```python
from __future__ import annotations

from dataclasses import replace
from collections.abc import Iterable
import re

from core.intent_models import (
    ArbitrationDecision, BotIntent, CandidateRejection, IntentCandidate,
    IntentResult, IntentRisk, IntentSource, RejectionCode,
)
from core.utterance import NormalizedUtterance
from core.utterance_semantics import (
    SpeechAct, UtteranceSemantics, evidence_is_quoted_only, is_negated_action,
)

_WRITE_RISKS = {IntentRisk.ADDITIVE, IntentRisk.MUTATING, IntentRisk.DESTRUCTIVE}
_HARD_BLOCK_CODES = {
    RejectionCode.NEGATED_ACTION, RejectionCode.QUOTED_ONLY,
    RejectionCode.META, RejectionCode.HYPOTHETICAL,
}


def _present(control_text: str, terms: tuple[str, ...]) -> bool:
    tokens = tuple(
        re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", control_text.casefold())
    )
    return any(
        needle and any(
            tokens[index:index + len(needle)] == needle
            for index in range(0, len(tokens) - len(needle) + 1)
        )
        for needle in (
            tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", term.casefold()))
            for term in terms
        )
    )


def _rejection(candidate: IntentCandidate, code: RejectionCode) -> CandidateRejection:
    return CandidateRejection(candidate, code)


def _unsafe_code(
    utterance: NormalizedUtterance,
    semantics: UtteranceSemantics,
    candidate: IntentCandidate,
) -> RejectionCode | None:
    if candidate.risk not in _WRITE_RISKS:
        return None
    evidence = candidate.action_terms + candidate.domain_terms
    if evidence_is_quoted_only(utterance, evidence):
        return RejectionCode.QUOTED_ONLY
    live_evidence = tuple(
        term for term in evidence
        if _present(utterance.control_text, (term,))
    )
    if not live_evidence:
        return RejectionCode.MISSING_LIVE_EVIDENCE
    if semantics.speech_act is SpeechAct.META:
        return RejectionCode.META
    if semantics.speech_act is SpeechAct.HYPOTHETICAL:
        return RejectionCode.HYPOTHETICAL
    allow_positive_forget = (
        candidate.risk is IntentRisk.ADDITIVE
        and candidate.intent in {BotIntent.CALENDAR_ITEM, BotIntent.REMINDER_CREATE}
    )
    if is_negated_action(
        utterance,
        evidence,
        allow_positive_forget=allow_positive_forget,
    ):
        return RejectionCode.NEGATED_ACTION
    if semantics.speech_act is SpeechAct.INFORMATION_REQUEST:
        return RejectionCode.INFORMATION_QUESTION_MUTATION
    if candidate.risk is IntentRisk.DESTRUCTIVE:
        if not candidate.action_terms or not _present(utterance.control_text, candidate.action_terms):
            return RejectionCode.MISSING_ACTION_EVIDENCE
        if not candidate.domain_terms or not _present(utterance.control_text, candidate.domain_terms):
            return RejectionCode.MISSING_DOMAIN_EVIDENCE
    return None


def _sort_key(candidate: IntentCandidate):
    return (
        -candidate.specificity,
        candidate.priority,
        candidate.order,
        -candidate.confidence,
        candidate.intent.value,
    )


def _is_conflict(first: IntentCandidate, second: IntentCandidate) -> bool:
    return (
        first.intent is not second.intent
        and first.specificity == second.specificity
        and first.priority == second.priority == 35
        and abs(first.confidence - second.confidence) <= 0.05
        and frozenset(first.domain_terms) != frozenset(second.domain_terms)
    )


def arbitrate_candidates(
    utterance: NormalizedUtterance,
    semantics: UtteranceSemantics,
    candidates: Iterable[IntentCandidate],
) -> ArbitrationDecision:
    accepted: list[IntentCandidate] = []
    rejected: list[CandidateRejection] = []
    hard_blocked = False
    for candidate in candidates:
        code = _unsafe_code(utterance, semantics, candidate)
        if code is None:
            accepted.append(candidate)
            continue
        rejected.append(_rejection(candidate, code))
        hard_blocked = hard_blocked or code in _HARD_BLOCK_CODES
    if hard_blocked:
        return ArbitrationDecision(None, rejected=tuple(rejected), blocked=True, reason="unsafe_write")
    ordered = sorted(accepted, key=_sort_key)
    if not ordered:
        return ArbitrationDecision(None, rejected=tuple(rejected), reason="no_candidate")
    if len(ordered) > 1 and _is_conflict(ordered[0], ordered[1]):
        choices = [ordered[0].intent.value, ordered[1].intent.value]
        clarification = IntentCandidate(
            BotIntent.CLARIFY,
            min(ordered[0].confidence, ordered[1].confidence),
            ordered[0].priority,
            order=min(ordered[0].order, ordered[1].order),
            payload={"choices": choices},
            reason="candidate_conflict",
            source=IntentSource.DETERMINISTIC,
            risk=IntentRisk.READ_ONLY,
            specificity=ordered[0].specificity,
        )
        rejected.extend(
            _rejection(candidate, RejectionCode.CONFLICT)
            for candidate in ordered[:2]
        )
        return ArbitrationDecision(
            clarification,
            alternatives=tuple(ordered[:2]),
            rejected=tuple(rejected),
            reason="candidate_conflict",
        )
    selected = ordered[0]
    confirmation = (
        selected.risk is IntentRisk.DESTRUCTIVE
        or (
            selected.source is IntentSource.SEMANTIC
            and selected.risk in _WRITE_RISKS
        )
    )
    return ArbitrationDecision(
        replace(selected, requires_confirmation=confirmation),
        rejected=tuple(rejected),
        reason="selected",
    )
```

- [ ] **Step 4: Run the pure arbitration tests green (2–5 minutes)**

Run: `.venv312/bin/python -m pytest tests/test_intent_arbitration.py -q`

Expected: all tests pass.

- [ ] **Step 5: Add router collector and parser-isolation contracts (2–5 minutes)**

In `core/intent_router.py`, add imports for `Counter`, `classify_intent_risk`, `NLUMetrics`, normalization/semantics, arbitration, routing context, and temporal resolution. Add these exact local contracts:

```python
@dataclass(frozen=True, slots=True)
class CollectorContext:
    utterance: NormalizedUtterance
    semantics: UtteranceSemantics
    routing: RoutingContext | None
    guild_id: int | None
    channel_id: int | None
    user_id: int | None
    reference_time: datetime


@dataclass(frozen=True, slots=True)
class CollectorOutput:
    candidates: tuple[IntentCandidate, ...] = ()
    parser_errors: tuple[str, ...] = ()
    rejections: tuple[CandidateRejection, ...] = ()


COLLECTOR_ORDER = (
    "_collect_control_candidates",
    "_collect_calendar_reminder_candidates",
    "_collect_poll_watchlist_quote_candidates",
    "_collect_utility_candidates",
    "_collect_fallback_candidates",
)
```

Keep `IntentRouter(monitor)` compatible for offline callers and allow production ownership injection:

```python
def __init__(
    self,
    monitor,
    metrics: NLUMetrics | None = None,
    *,
    temporal_resolver: TemporalResolver | None = None,
    now_provider: Callable[[], datetime] | None = None,
):
    self.monitor = monitor
    self.metrics = metrics or NLUMetrics()
    inherited_resolver = getattr(
        getattr(monitor, "nlp_parser", None),
        "temporal_resolver",
        None,
    )
    self.temporal_resolver = (
        temporal_resolver or inherited_resolver or TemporalResolver()
    )
    self._now_provider = now_provider or (lambda: datetime.now(OSLO))
```

Task 5 accepts an explicitly injected resolver, otherwise borrows `monitor.nlp_parser.temporal_resolver`, and uses a new resolver only for offline/test compatibility. It does not claim dispatch-wide resolver or clock identity; the later model-actions composition lane owns that invariant. Every temporal collector passes `context.reference_time` through `_safe_parse(..., reference_time=context.reference_time)` (or the callee's exact `reference=` keyword), so neither the parser nor reminder provider is read again mid-route. Keep Task 4's `days_offset` only as a compatibility field through this routing task; typed dispatch converts and removes it later. Add provider-spy coverage that advances across Oslo midnight on its second call plus compatibility smoke cases for raw `HH:MM`, `noon`, and the full Task 4 date-alias families. These assumptions do not change Task 5's collector priority/order table, risk policy, payload envelopes, or fixture schema.

Add helpers; every parser exception is caught here and never copied:

```python
def _safe_parse(
    self, errors, rejections, parser_name, metric_family, fn, *args, **kwargs
):
    try:
        return fn(*args, **kwargs)
    except Exception:
        errors.append(parser_name)
        rejections.append(CandidateRejection(
            IntentCandidate(
                BotIntent.AI_CHAT,
                0.0,
                90,
                order=389,
                payload={},
                reason="parser_error_diagnostic",
                source=IntentSource.DETERMINISTIC,
                risk=IntentRisk.READ_ONLY,
                specificity=0,
            ),
            RejectionCode.PARSER_ERROR,
        ))
        self.metrics.record_parser_error(metric_family, "exception")
        return None

def _candidate_from_result(
    self, result, *, tier, order, specificity,
    action_terms=(), domain_terms=(), source=IntentSource.DETERMINISTIC,
):
    risk = classify_intent_risk(result.intent, result.payload)
    return IntentCandidate(
        result.intent, result.confidence, tier, order=order,
        payload=dict(result.payload), reason=result.reason, source=source,
        risk=risk, action_terms=tuple(action_terms),
        domain_terms=tuple(domain_terms), specificity=specificity,
    )
```

The synthetic candidate above is diagnostic-only: append it only to `CollectorOutput.rejections`, never to the arbitration candidate list. Each caught exception must produce exactly one allowlisted `parser_errors` entry, exactly one `PARSER_ERROR` rejection, and exactly one bounded `record_parser_error(..., "exception")` increment. `_safe_parse()` does not call `record_rejection()`; the single aggregate loop in `evaluate_utterance()` records that rejection once. Call each production parser at most once per route and preserve `tuple(parser_errors)` without deduplicating it. Parser names and metric families are finite values; raw exception type, message, arguments, and user text never enter the candidate, diagnostics, metrics, result, or logs.

The only allowed `parser_name` values in route diagnostics are the Task 1 `ParserName` literals. Map them to metric families: both natural-language parser calls -> `calendar`; reminder -> `reminder`; poll/vote -> `poll`; watchlist -> `watchlist`; quote -> `quote`; birthday -> `birthday`; profile -> `profile`; countdown -> `countdown`; and each utility to its same short family (`price`, `horoscope`, `compliment`, `calculator`, `shorten`, `search`). Every later feature collector must call its parser through this same `_safe_parse` boundary; direct parser calls in collectors are forbidden.

Every additive, mutating, or destructive conversion through `_candidate_from_result()` must pass the finite action/domain terms it actually matched in `utterance.control_text`; a parser result alone is never evidence. Add `_present_terms(control_text, finite_terms)` and use it for generic calendar NLP (`møte`, `avtale`, `arrangement`, `meeting`, `event` plus any live create verb), reminder NLP, poll/watchlist/quote/birthday/profile, and location (`bor`, `bosted`, `sted`, `location`, `flytt`, `sett`). `_unsafe_code()` requires at least one such live unmasked term for every write, checks negation against the complete live evidence tuple, and then applies the stricter destructive action-plus-domain rule. Thus an otherwise parseable write found only in inline/fenced code, a quote, or `jeg vil ikke møte i morgen kl 14` is hard-blocked even when its parser emitted empty action terms. Keep `ikke glem`/`ikkje gløym` as the existing narrow positive idiom.

- [ ] **Step 6: Freeze the complete collector tier/order/specificity contract (2–5 minutes)**

Lower tier is earlier. Specificity is independent: `0` implicit parser shape, `1` domain evidence, `2` action plus domain, `3` action plus domain plus target/value, `4` exact operational/context form. `order` is the old `route()` branch position inside its tier. `2/3`, `0/3`, and `1/3` use the larger value only when a nonblank typed target/value is present. Only two leading candidates whose priority is exactly tier `35` can produce `CLARIFY`; equal candidates in every other tier preserve source `order`, even when their specificity, domain difference, and confidence distance would otherwise satisfy the ambiguity predicate. The implementation must use these exact reason strings and numbers:

| Reason | Tier | Order | Specificity |
|---|---:|---:|---:|
| `calendar_help_keyword` | 10 | 10 | 4 |
| `status_keyword` | 10 | 20 | 4 |
| `help_keyword` | 10 | 30 | 4 |
| `capability_help_natural` | 10 | 31 | 2 |
| `profile_keyword` | 10 | 40 | 4 |
| `memory_delete_keyword` | 10 | 50 | 4 |
| `memory_export_keyword` | 10 | 51 | 4 |
| `memory_view_keyword` | 10 | 52 | 4 |
| `reminder_edit_keyword` | 20 | 60 | 2/3 |
| `reminder_delete_keyword` | 20 | 70 | 2/3 |
| `reminder_complete_keyword` | 20 | 90 | 2/3 |
| `active_reminder_numeric_complete` | 20 | 91 | 4 |
| `active_reminder_complete_number` | 20 | 92 | 4 |
| `calendar_auth_keyword` | 20 | 100 | 4 |
| `calendar_sync_keyword` | 20 | 110 | 2 |
| `calendar_clear_keyword` | 20 | 111 | 2/3 |
| `calendar_delete_keyword` | 20 | 112 | 2/3 |
| `calendar_delete_title_match` | 20 | 113 | 3 |
| `calendar_complete_keyword` | 20 | 114 | 2/3 |
| `calendar_complete_title_match` | 20 | 115 | 3 |
| `calendar_edit_keyword` | 20 | 116 | 2/3 |
| `calendar_edit_natural` | 20 | 117 | 3 |
| `reminder_search_keyword` | 30 | 80 | 3 |
| `calendar_search_keyword` | 30 | 81 | 3 |
| `explicit_web_search_keyword` | 30 | 82 | 3 |
| `bare_web_search_keyword` | 30 | 83 | 3 |
| `reminder_list_keyword` | 30 | 93 | 2 |
| `reminder_list_parser` | 30 | 94 | 2 |
| `calendar_list_keyword` | 30 | 118 | 2 |
| `calendar_keyword_default` | 30 | 119 | 1 |
| `birthday_edit_keyword` | 30 | 120 | 2/3 |
| `birthday_create_natural` | 35 | 121 | 3 |
| `reminder_create_natural` | 35 | 122 | 3 |
| `calendar_create_natural` | 35 | 123 | 3 |
| `poll_create_natural` | 35 | 124 | 3 |
| `watchlist_add_natural` | 35 | 125 | 3 |
| `calendar_nlp_high` | 40 | 130 | 0/3 |
| `poll_list_keyword` | 50 | 140 | 2 |
| `poll_parser` | 50 | 150 | 0/3 |
| `active_poll_vote` | 50 | 160 | 4 |
| `poll_edit_keyword` | 50 | 170 | 2/3 |
| `poll_delete_keyword` | 50 | 180 | 2/3 |
| `poll_close_keyword` | 50 | 190 | 2/3 |
| `countdown_parser` | 50 | 200 | 2/3 |
| `watchlist_parser` | 50 | 210 | 1/3 |
| `word_of_day_keyword` | 50 | 220 | 2 |
| `quote_list_keyword` | 50 | 230 | 2 |
| `quote_edit_keyword` | 50 | 240 | 2/3 |
| `quote_delete_keyword` | 50 | 250 | 2/3 |
| `quote_parser` | 50 | 260 | 1/3 |
| `aurora_keyword` | 50 | 270 | 1 |
| `school_holidays_keyword` | 50 | 280 | 1 |
| `price_parser` | 60 | 290 | 3 |
| `horoscope_parser` | 60 | 300 | 2/3 |
| `compliment_parser` | 60 | 310 | 2/3 |
| `calculator_parser` | 60 | 320 | 3 |
| `shorten_parser` | 60 | 330 | 3 |
| `daily_digest_keyword` | 60 | 340 | 2 |
| `calendar_nlp` | 70 | 350 | 0/3 |
| `search_intent` | 80 | 360 | 1 |
| `information_search_natural` | 80 | 361 | 2 |
| `dashboard_intent` | 80 | 370 | 1 |
| `location_pattern` | 80 | 380 | 3 |
| `fallback` | 90 | 390 | 0 |

Exact variable-specificity tests are:

- reminder edit/delete/complete: `3` only with a positive `number`, nonblank `id`, or nonblank `target` in the reminder envelope;
- calendar clear/delete/complete/edit and birthday edit: `3` only with nonblank `target`, positive `number/index`, or typed changes;
- calendar NLP: `3` only with nonblank title and date/recurrence; otherwise `0`;
- poll parser: `3` only with an explicit `poll|avstemning` term plus parsed nonblank question and at least two nonblank options; otherwise `0`;
- poll edit/delete/close and countdown: `3` only with a parsed positive index/id/event target; otherwise `2`;
- watchlist: `3` for add/edit/remove with typed nonblank title or positive index; `1` for status/list/suggest;
- quote parser: `3` for save with nonblank text; `1` for get. Quote edit/delete branches use `3` with a positive index, otherwise `2`;
- horoscope/compliment: `3` only with parsed sign/person target, otherwise `2`.

The two `*_title_match` candidates are not trusted bypasses. They carry the exact matched delete/complete surface verb in `action_terms`. For an unquoted target, `domain_terms` contains the resolved live title span. A quoted span may be consumed as **target data only** when an unquoted finite family noun (`møte|avtale|kalender|påminnelse|reminder|event`) and unquoted action verb are both live, the quoted value resolves to exactly one stable target, and the whole utterance is not meta/hypothetical; in that case `domain_terms` contains the live family noun, never the masked target text. Thus `slett møte "Møte med Ola"` may produce a confirmation, while `jeg skrev "slett møte Møte med Ola"` and `hva betyr "slett møte Møte med Ola"?` remain inert. Add router/corpus cases for these pairs, `ikke slett <live title>`, `ikkje fullfør <live title>`, and quoted/meta versions. Every unsafe form is blocked or falls back with zero mutation candidate; each equivalent direct form selects the uniquely bound route and still follows normal destructive confirmation.

`birthday_create_natural` is a reserved tier consumed by the separate birthday identity/parser lane; this plan must not emit it from unvalidated name/date guessing. All other rows are emitted in this task.

- [ ] **Step 7: Add compatibility wrapper tests before moving branches (2–5 minutes)**

In `tests/test_intent_router.py`, assert `route("hjelp", 123)` equals `route_utterance(normalize_utterance("hjelp"), guild_id=123)`, and a supplied `RoutingContext` whose `key.guild_id` differs from scalar `guild_id` returns `AI_CHAT`, reason `invalid_context`, and diagnostics count `{RejectionCode.INVALID_CONTEXT: 1}`. Pin the same mismatch behavior for `channel_id` and `user_id`. When no `RoutingContext` exists, use a collector spy to prove all three supplied scalar IDs survive unchanged on `CollectorContext`; when one exists, prove all three values are derived from its key after validation. Assert the result/payload and diagnostics contain no scalar identity.

- [ ] **Step 8: Implement route wrappers and one arbitration point (2–5 minutes)**

Replace only the top-level early-return body with these public signatures and flow; keep helper methods below it while collectors are migrated:

```python
def route(
    self, content: str, guild_id: Optional[int] = None, *,
    channel_id: int | None = None, user_id: int | None = None,
    routing_context: RoutingContext | None = None,
    reference_time: datetime | None = None,
) -> IntentResult:
    return self.route_utterance(
        normalize_utterance(content), guild_id=guild_id,
        channel_id=channel_id, user_id=user_id,
        routing_context=routing_context,
        reference_time=reference_time,
    )

def route_utterance(
    self, utterance: NormalizedUtterance, guild_id: int | None = None, *,
    channel_id: int | None = None, user_id: int | None = None,
    routing_context: RoutingContext | None = None,
    reference_time: datetime | None = None,
) -> IntentResult:
    return self.evaluate_utterance(
        utterance, guild_id=guild_id, channel_id=channel_id,
        user_id=user_id, routing_context=routing_context,
        reference_time=reference_time,
    ).result

def evaluate_utterance(
    self, utterance: NormalizedUtterance, guild_id: int | None = None, *,
    channel_id: int | None = None, user_id: int | None = None,
    routing_context: RoutingContext | None = None,
    reference_time: datetime | None = None,
) -> RoutedIntent:
    captured = reference_time if reference_time is not None else self._now_provider()
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("routing_reference_must_be_aware")
    captured = captured.astimezone(OSLO)
    if routing_context is not None:
        key = routing_context.key
        mismatch = (
            (guild_id is not None and guild_id != key.guild_id)
            or (channel_id is not None and channel_id != key.channel_id)
            or (user_id is not None and user_id != key.user_id)
        )
        if mismatch:
            self.metrics.record_rejection(RejectionCode.INVALID_CONTEXT)
            return RoutedIntent(
                IntentResult(BotIntent.AI_CHAT, 0.2, {}, "invalid_context"),
                RouteDiagnostics(
                    rejection_counts={RejectionCode.INVALID_CONTEXT: 1}
                ),
            )
        guild_id, channel_id, user_id = key.guild_id, key.channel_id, key.user_id
    semantics = analyze_utterance(utterance)
    context = CollectorContext(
        utterance=utterance,
        semantics=semantics,
        routing=routing_context,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        reference_time=captured,
    )
    candidates = []
    parser_errors = []
    collector_rejections = []
    for method_name in COLLECTOR_ORDER:
        output = getattr(self, method_name)(context)
        candidates.extend(output.candidates)
        parser_errors.extend(output.parser_errors)
        collector_rejections.extend(output.rejections)
    decision = arbitrate_candidates(utterance, semantics, candidates)
    all_rejections = tuple(collector_rejections) + decision.rejected
    counts = Counter(rejection.code for rejection in all_rejections)
    for rejection in all_rejections:
        self.metrics.record_rejection(rejection.code)
    if decision.selected is not None:
        result = decision.selected.to_result()
    else:
        result = IntentResult(
            BotIntent.AI_CHAT,
            0.2 if decision.blocked else 0.5,
            {},
            "unsafe_mutation_blocked" if decision.blocked else "fallback",
        )
    return RoutedIntent(
        result,
        RouteDiagnostics(
            parser_errors=tuple(parser_errors),
            rejection_counts=dict(sorted(counts.items(), key=lambda item: item[0].value)),
        ),
    )
```

`IntentRouter` records parser and rejection diagnostics only. It must not call `record_decision()`: an `AI_CHAT` fallback is an intermediate result that can still become a semantic model action. The model-actions lane makes `MessageMonitor.handle_message()` the sole final-turn decision recorder after the complete downstream routing flow resolves, preventing a false deterministic `AI_CHAT/routed` increment before a semantic route.

Run: `.venv312/bin/python -m pytest tests/test_intent_router.py -q`

Expected during this intermediate step: wrapper-only tests pass after real collectors are added in the next steps; do not commit an empty collector stub. Implement Step 8 and Step 9 in the same working change before running.

- [ ] **Step 9: Migrate control and memory branches into the first collector (2–5 minutes)**

`_collect_control_candidates(context)` evaluates, without early return: calendar help, status, help, the new capability help, profile, and all three memory routes. Use `context.utterance.control_text` for predicates and `context.utterance.text` for payload extraction. Capability help matches only these anchored forms:

```python
CAPABILITY_HELP = re.compile(
    r"^(?:hva|kva|ka|what)\s+(?:kan|can)\s+(?:du|you)\s+"
    r"(?:gjøre|gjere|gjør|do)\s*\??$",
    re.IGNORECASE,
)
```

Use `CAPABILITY_HELP.fullmatch(context.utterance.control_text.strip())`. Emit `HELP`, confidence `0.96`, reason `capability_help_natural`, tier/order/spec `10/31/2`, action terms `("kan", "can")`, domain terms `("gjøre", "gjere", "gjør", "do")`. Add negative tests `ka kan du lage avstemning`, `hva kan du slette`, and `what can you create tomorrow`; none may route HELP. For memory delete, set action terms to the exact matched surface form from `("slett", "slette", "delete", "glem")` and domain terms `("minne", "memory", "brukerminne")`; export/view carry domain terms but no write action. Convert existing helper results with `_candidate_from_result` and the table numbers; preserve their exact payloads and confidence.

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_intent_router.py tests/test_user_memory_controls.py -q
```

Expected: control/memory tests pass.

- [ ] **Step 10: Migrate calendar and reminder branches into the second collector (2–5 minutes)**

`_collect_calendar_reminder_candidates(context)` independently evaluates reminder edit/delete, local search, reminder helper, calendar auth, calendar helper, birthday edit, and calendar NLP. It may read active reminder/calendar state but may not write.

- [ ] **Step 10a: Isolate temporal parser diagnostics (2–5 minutes)**

Use `_safe_parse` with the collector's shared parser-error and rejection lists for the two `NaturalLanguageParser` result calls. If a successful parser result has semantic temporal errors, create a non-executable diagnostic candidate `IntentCandidate(BotIntent.CALENDAR_ITEM, 0.0, 40, order=130, reason="calendar_temporal_invalid", risk=IntentRisk.ADDITIVE)` and add `CandidateRejection(diagnostic_candidate, RejectionCode.INVALID_TEMPORAL)`; call `metrics.record_parser_error("calendar", "invalid_temporal")`; emit no calendar candidate and no raw error payload. An exception follows only the shared `PARSER_ERROR` path and must not also become `INVALID_TEMPORAL`. Rename high explicit reminder add reason to `reminder_create_natural` and its parsed `complete` reason to `reminder_complete_keyword`. Calendar NLP at confidence `>= 0.94` uses reason `calendar_nlp_high`, tier/order `40/130`; lower confidence uses `calendar_nlp`, `70/350`.

- [ ] **Step 10b: Add the narrow natural calendar-edit candidate (2–5 minutes)**

Add the narrow polite calendar edit parser before generic calendar NLP:

```python
match = re.match(
    r"^(?:(?:kan|kunne|could)\s+(?:du|you)\s+)?"
    r"(?:endre|rediger|flytt|edit|change|move)\s+(.+?)\s+(?:til|to)\s+(.+)$",
    context.utterance.text,
    re.IGNORECASE,
)
```

Require a nonblank target and valid temporal evidence in the change phrase. Emit `CALENDAR_EDIT`, confidence `0.98`, payload `{"calendar_edit": {"target": target, "changes": changes}}`, where `changes` contains only non-`None` canonical `date` and `time`; reason `calendar_edit_natural`; tier/order/spec `20/117/3`; action terms from the matched verb; domain terms `("møte", "avtale", "arrangement", "meeting", "event")`. If temporal evidence is invalid, add the bounded invalid-temporal rejection instead.

- [ ] **Step 10c: Add explicit reminder and calendar-create evidence (2–5 minutes)**

This routing task owns the pure prerequisite expansion of `cal_system.reminder_manager.parse_reminder_command`; the later typed-runtime plan consumes it without changing its signature or vocabulary. Preserve compatibility calls with no keywords, but production routing always passes both `now=context.reference_time` and `temporal_resolver=self.temporal_resolver` through `_safe_parse` with the collector's shared parser-error and rejection lists. The parser reads neither wall time nor a manager clock when either is supplied. It returns the complete typed `{"action":"add", "text":..., optional due_at/due_date/time/timezone/recurrence}` object; relative/yearless inputs resolve from `now`, and date-only uses the documented 09:00 policy before year selection. Resolve one `resolver = temporal_resolver or TemporalResolver()` and clean the reminder title by calling Task 4's `resolver.strip_temporal_evidence(text, reference=now)` after bounded command-frame extraction. That shared finite evidence collector is the only temporal stripping grammar; the reminder parser must not add or maintain a second date/time regex vocabulary. Add fixed-clock parser tests for relative hours, `i morgen|i morgon|imårra`, weekdays, date-only before/after 09:00, title cleanup for every Task 4 temporal family, and checklist-only input.

The same function, not a second edit parser, owns the bounded edit/target frames. `endre|rediger|edit` plus `påminnelse|påminning|reminder` and one positive visible number accepts one or more labeled `tekst|text:`, `dato|date:`, `tid|time|kl:`, and `gjentakelse|gjentaking|recurrence:` clauses, rejects duplicate/unknown/empty clauses, and returns exactly `{"action":"edit","number":N,"changes":{...canonical fields...}}`. Pin `endre påminnelse 1 tekst: Ring tannlegen` to `{"action":"edit","number":1,"changes":{"text":"Ring tannlegen"}}`. Complete/delete/list/search frames return their corresponding canonical Task-6 action discriminators and target/query fields. Add tests for every shape, parser exceptions through the shared `_safe_parse` lists, and contradictory temporal clauses; no handler-private `_parse_edit_command` is part of production routing.

Treat `påminn meg`, `minn meg`, Trøndelag-adjacent `minn mæ`, `husk å`, Nynorsk-adjacent `hugs å`, and `remind me` as explicit reminder-domain evidence. Reuse the production `parse_reminder_command` result; retain its whole dict under `payload["reminder"]`. Do not invent a result when the production parser returns `None`. The parser itself must return `None` for the finite media frames `husk å se <title>`, `hugs å sjå <title>`, and `remember to watch <title>` so the watchlist collector owns them; every other valid `husk/hugs` create such as `husk å kjøpe melk på mandag` is a reminder, not a generic calendar task. Use tier/order/spec `35/122/3`, confidence `0.96`, reason `reminder_create_natural`, action terms containing only the exact matched surface from `("påminn", "minn", "husk", "hugs", "remind")`, and domain terms containing the matched frame. Add focused route tests for `minn mæ om å ringe legen i morra`, `husk å kjøpe melk på mandag`, all three media exclusions, and a provider spy proving one route call reads the injected clock only once. Calendar natural create at tier 35 is emitted only when explicit `møte|avtale|arrangement|meeting|event` evidence and a validated title/date exist; otherwise it remains the high/low NLP row.

Reminder list recognition owns the finite forms `vis|list|show` plus `påminnelser|påminningar|reminders|gjøremål|todos|huskeliste`. Add `vis påminningar -> REMINDER_LIST` and the nearby statement `påminningar kan vere nyttige -> AI_CHAT`; the feature-parity lane only evaluates these forms and does not add recognizers.

Whole-collection phrases such as `slett kalenderen`, `tøm kalenderen`,
`delete the calendar`, and their polite directive forms emit
`CALENDAR_CLEAR` with `{"calendar_target": {"all": True}}`; they never emit
targetless `CALENDAR_DELETE`. `CALENDAR_DELETE` requires one concrete title,
stable ID, or positive displayed number.

- [ ] **Step 10d: Run calendar/reminder collector tests (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_intent_router.py tests/test_calendar_edit.py \
  tests/test_reminder_crud.py tests/test_natural_language_parser_safety.py -q
```

Expected: all listed suites pass.

- [ ] **Step 11: Migrate poll, countdown, watchlist, quote, and content features (2–5 minutes)**

`_collect_poll_watchlist_quote_candidates(context)` calls each production parser through `_safe_parse` and emits every table row from `poll_list_keyword` through `school_holidays_keyword` without returning early.

- [ ] **Step 11a: Migrate poll and countdown candidates (2–5 minutes)**

- poll create/list/edit/delete/close use domain terms `("poll", "avstemning")`; vote uses the numeric vote token plus an active poll as specificity `4`; delete action terms are `("slett", "delete", "fjern", "remove")`;
- an explicit poll parser result with nonblank question and two options is emitted twice only if needed: `poll_create_natural` at `35/124/3` and the compatibility `poll_parser` at `50/150/3`; implicit legacy parser shapes emit only `poll_parser` at specificity `0`;
- countdown uses action/domain terms from `("hvor lenge", "countdown", "dager til", "days until")` and the parsed event target;

- [ ] **Step 11b: Migrate watchlist and quote candidates (2–5 minutes)**

- this routing task owns the complete prerequisite expansion of `features.watchlist_manager.parse_watchlist_command()`; do it before emitting watchlist candidates so this plan never depends on the later feature-parity lane. Accept add only for `husk å se <title>`, `hugs å sjå <title>`, `remember to watch <title>`, `legg til film|serie <title>`, an explicit `<title> på|i watchlist`, or `<title> to (the) watchlist`. Accept remove/edit only when `watchlist|film|serie|movie|show` is live alongside the action. Return the complete Task-6 typed fields, reject blank titles and generic `legg til|fjern|endre`, and preserve title/value case;
- watchlist add with a typed title uses `watchlist_add_natural` at `35/125/3`; the compatibility row stays `50/210`. Read actions use specificity `1`, add/edit/remove with title/index use `3`. The explicit media frames `husk å se`, `hugs å sjå`, and `remember to watch` outrank/exclude generic reminder parsing. Remove uses the exact matched surface action from `("fjern", "fjerne", "slett", "slette", "remove", "delete")` and live domain terms from `("watchlist", "film", "serie", "movie", "show")`; add end-to-end positives `hugs å sjå Arrival`, `remember to watch The Bear`, `fjern film 2`, and `remove show 2`, plus generic-action, substring, quoted-only, negated, and past-description negatives;
- quote edit/delete preserve their existing envelopes/reasons; delete action terms are `("slett", "delete", "fjern", "remove")`, domain `("sitat", "quote")`; quote parser save/get uses its parsed action to choose specificity `3/1`;

- [ ] **Step 11c: Migrate read-only content candidates and deduplicate parser calls (2–5 minutes)**

- word-of-day, aurora, and school-holidays have read-only domain evidence and no action mutation evidence.

Never call `_route_watchlist_command()` from this collector because that helper hides parser exceptions. Call `monitor.parse_watchlist_command` once and construct `IntentResult(BotIntent.WATCHLIST, 0.93, {"watchlist": parsed}, "watchlist_parser")`. Likewise call poll, vote, countdown, and quote parsers once each and reuse their value for all candidate rows.

- [ ] **Step 11d: Add the bounded parser-exception regression (2–5 minutes)**

Add a test monitor whose `parse_quote_command` raises `RuntimeError("SECRET_TOKEN")`; assert `diagnostics.parser_errors == ("parse_quote_command",)`, `diagnostics.rejection_counts == {RejectionCode.PARSER_ERROR: 1}`, and `metrics.snapshot()["parser_errors"] == {"parser=quote|code=exception": 1}`. Inspect the collector output directly to prove it contains exactly one diagnostic-only `CandidateRejection` whose candidate has empty payload and constant reason `parser_error_diagnostic`, and that this candidate is absent from the arbitration input. Serialized result/diagnostics must contain neither `SECRET_TOKEN` nor `RuntimeError`.

- [ ] **Step 11e: Run poll/watchlist/quote collector tests (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_intent_arbitration.py tests/test_poll_target.py \
  tests/test_poll_manager_edit_delete.py tests/test_watchlist_scope.py \
  tests/test_quote_crud.py tests/test_intent_router.py -q
```

Expected: all listed suites pass.

- [ ] **Step 12: Migrate utilities, search, dashboard, location, and fallback (2–5 minutes)**

`_collect_utility_candidates(context)` emits price, horoscope, compliment, calculator, URL shortening, daily digest, contextual search, information search, dashboard, and location candidates. Use each production parser once through `_safe_parse`, preserve its existing confidence/payload/reason, and apply the table numbers.

- [ ] **Step 12a: Add the three bounded natural utility patterns (2–5 minutes)**

Add these narrow rules:

```python
EXPLICIT_SHORTEN = re.compile(
    r"\b(?:forkort|shorten)\b.*\bhttps?://[^\s]+", re.IGNORECASE
)
INFORMATION_TRANSIT = re.compile(
    r"^(?:når|when|hva tid|kva tid|ka tid)\b.*\b"
    r"(?:tog|toget|buss|bussen|train|bus)\b",
    re.IGNORECASE,
)
VAGUE_WHAT_HAPPENS = re.compile(r"^(?:hva|kva|ka)\s+skjer\??$", re.IGNORECASE)
```

- [ ] **Step 12b: Emit the explicit URL-shortening candidate (2–5 minutes)**

- When `EXPLICIT_SHORTEN` matches and the production shortener returns a valid URL payload, emit `SHORTEN_URL` at `60/330/3` with action terms from the matched verb and the URL as domain evidence; this beats any specificity-0 poll shape.

- [ ] **Step 12c: Emit information search and suppress vague dashboard claims (2–5 minutes)**

- When `INFORMATION_TRANSIT` matches, emit `SEARCH`, confidence `0.92`, payload `{"search": {"query": context.utterance.text.rstrip("?"), "type": "web"}}`, reason `information_search_natural`, `80/361/2`. The information-question safety rule rejects a competing write candidate but not this read candidate.
- When `VAGUE_WHAT_HAPPENS` matches, suppress both `search_intent` and `dashboard_intent`; do not suppress contextual searches such as `hva skjer i Oslo` or `hva skjer i morgen`.

- [ ] **Step 12d: Emit location and fallback candidates (2–5 minutes)**

- `_route_location_command()` remains a pure parser, but call it only with case-preserving text and convert its result at `80/380/3`.
- Pass its actually matched live action/location terms into `_candidate_from_result()`; a city parsed only from Markdown code, quotation, or negated prose is rejected with zero memory calls.

`_collect_fallback_candidates(context)` always returns exactly one `AI_CHAT` candidate with confidence `0.5`, empty payload, reason `fallback`, `90/390/0`, deterministic source, and read-only risk. It carries no evidence terms. The arbiter ignores this fallback when a hard-blocked write is present and the wrapper returns bounded `unsafe_mutation_blocked` instead.

- [ ] **Step 12e: Run utility/search collector tests (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_search_intent.py tests/test_search_manager.py \
  tests/test_url_shortener_security.py tests/test_intent_router.py -q
```

Expected: all listed suites pass.

Add end-to-end negatives for inline code `` `møte i morgen kl 14` ``, fenced `slett kalenderen`, quoted `"sett bosted Oslo"`, and `jeg vil ikke møte i morgen kl 14`. Run them only through deterministic `evaluate_utterance()` collection; each returns the bounded unsafe fallback and leaves calendar/memory mutation spies untouched. Add equivalent unmasked positive rows to prove masking did not disable ordinary natural directives. Downstream orchestration assertions begin in their owning later tasks and are not part of this gate.

- [ ] **Step 13: Delete the old top-level cascade and prove collectors are read-only (2–5 minutes)**

Once Steps 9–12 are green, delete the old statements in `IntentRouter.route()` that directly return branches. Keep reusable pure helpers (`_route_calendar_command`, title matching, local search parsing, reminder parsing, state-read helpers, location parsing, and contextual-search check). Remove `_route_watchlist_command` only after its caller count is zero.

Add spies whose mutation-like methods (`add_item`, `edit_item`, `delete_item`, `add_reminder`, `create_poll`) raise `AssertionError`. Call `evaluate_utterance()` across one input per collector and assert no mutation-like method was called. State-read methods `get_upcoming`, `get_active_reminders`, and `get_active_polls` remain allowed.

Run: `.venv312/bin/python -m pytest tests/test_intent_router.py tests/test_intent_arbitration.py -q`

Expected: all tests pass and `rg -n "return IntentResult" core/intent_router.py` shows returns only inside pure helpers/wrappers, not a first-match top-level cascade.

- [ ] **Step 14: Pin the natural-language regressions at router level (2–5 minutes)**

Add this exact parametrized test to `tests/test_intent_router.py`:

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ikke slett kalenderen", BotIntent.AI_CHAT),
        ("slett ikke kalenderen", BotIntent.AI_CHAT),
        ('hva skjer hvis jeg skriver "slett påminnelse 1"?', BotIntent.AI_CHAT),
        ("ikke slett poll 2", BotIntent.AI_CHAT),
        ("hva skjer?", BotIntent.AI_CHAT),
        ("kan du slette kalenderen?", BotIntent.CALENDAR_CLEAR),
        ("ikke glem møte i morgen kl 14", BotIntent.CALENDAR_ITEM),
        ("Når går toget i morgen kl 8?", BotIntent.SEARCH),
        ("Kan du endre møte med Ola til fredag kl 10?", BotIntent.CALENDAR_EDIT),
        ("Påminn meg om å ringe legen i morgen", BotIntent.REMINDER_CREATE),
        ("Kva kan du gjere?", BotIntent.HELP),
        ("forkort https://example.com/a/b", BotIntent.SHORTEN_URL),
    ],
)
def test_natural_language_routing_regressions(router, text, expected):
    assert router.route(text, guild_id=123).intent is expected
```

For the calendar edit case also assert payload equals:

```python
{
    "calendar_edit": {
        "target": "møte med Ola",
        "changes": {"date": "17.07.2026", "time": "10:00"},
    }
}
```

Use the fixed Task 4 clock for this assertion. With that same `NOW = 2026-07-14T12:00:00+02:00`, assert the reminder-create envelope is complete at this boundary:

```python
{
    "reminder": {
        "action": "add",
        "text": "ringe legen",
        "due_at": "2026-07-15T09:00:00+02:00",
        "due_date": "15.07.2026",
        "time": "09:00",
        "timezone": "Europe/Oslo",
    }
}
```

Task 5 owns this canonical parser output, including timing, edit, and target shapes. Typed Tasks 6–7 validate, dispatch, and persist it without adding recognizers or changing the parser vocabulary. Assert the destructive positive result has `risk is IntentRisk.DESTRUCTIVE` and `requires_confirmation is True`. Assert all five negative/hypothetical cases have empty payload and no handler spy calls.

- [ ] **Step 15: Add adjacent false-positive cases (2–5 minutes)**

In `tests/test_false_positives.py`, add:

```python
@pytest.mark.parametrize(
    "text",
    [
        "Kva meiner du om RBK i morgon?",
        "Ka trur du skjer i morra?",
        "Æ ska bare høre ka du tænke om kampen i morra",
        "Do not delete reminder 1",
        'Explain the command "delete poll 2"',
    ],
)
def test_conversation_and_quoted_actions_never_route_to_write(router, text):
    result = router.route(text, guild_id=123)
    assert result.risk is IntentRisk.READ_ONLY
    assert result.intent not in {
        BotIntent.CALENDAR_ITEM, BotIntent.CALENDAR_DELETE,
        BotIntent.REMINDER_CREATE, BotIntent.REMINDER_DELETE,
        BotIntent.POLL_CREATE, BotIntent.POLL_DELETE,
    }
```

Add the English positive `Could you delete reminder 1? -> REMINDER_DELETE` next to the English negative so politeness and negation are independently proven.

- [ ] **Step 16: Reconnect the evaluation adapter to per-call route diagnostics (2–5 minutes)**

In `tests/nlu_harness.py`, stop binding `ParserProbe.wrap(...)` proxies in `build_production_router`; bind raw production callables because collectors now own exception isolation. Replace `ProductionRouterAdapter.evaluate()` with:

```python
def evaluate(self, text: str, *, guild_id: int | None):
    routed = self._router.evaluate_utterance(
        normalize_utterance(text), guild_id=guild_id
    )
    parser_names = tuple(
        name for name in routed.diagnostics.parser_errors
        if name in PARSER_NAME_VALUES
    )
    return routed.result, parser_names
```

Add `get_args` to the existing `typing` import and define `PARSER_NAME_VALUES = frozenset(get_args(ParserName))`. Delete the now-unused `ParserProbe` member from the adapter after its tests are migrated. This is per-call state from the returned `RoutedIntent`, never a shared `last_route` attribute.

- [ ] **Step 17: Extend the JSONL contract with exact safety and arbitration cases (2–5 minutes)**

Append these objects to `tests/fixtures/nlu_contract_v1.jsonl` (one line each, with the same exact nine keys as Task 1):

```jsonl
{"id":"nb-negated-calendar-delete","locale":"nb","family":"negative","text":"ikke slett kalenderen","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["calendar_delete","calendar_clear"],"fixture":"empty","critical":true}
{"id":"nn-negated-reminder-delete","locale":"nn","family":"negative","text":"ikkje slett påminnelse 1","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["reminder_delete"],"fixture":"active_reminder","critical":true}
{"id":"nb-negated-poll-delete","locale":"nb","family":"negative","text":"ikke slett poll 2","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["poll_delete"],"fixture":"active_poll","critical":true}
{"id":"nb-quoted-delete","locale":"nb","family":"negative","text":"hva skjer hvis jeg skriver \"slett påminnelse 1\"?","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["reminder_delete"],"fixture":"active_reminder","critical":true}
{"id":"nb-hedged-delete","locale":"nb","family":"negative","text":"jeg vurderer kanskje å slette møte","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["calendar_delete"],"fixture":"calendar_title_meeting","critical":true}
{"id":"nb-vague-hva-skjer","locale":"nb","family":"negative","text":"hva skjer?","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["dashboard","search","calendar_item"],"fixture":"empty","critical":true}
{"id":"nb-polite-calendar-clear","locale":"nb","family":"calendar_clear","text":"kan du slette kalenderen?","expected_intent":"calendar_clear","expected_payload":{"calendar_target.all":true},"forbidden_intents":["ai_chat","calendar_delete"],"fixture":"empty","critical":true}
{"id":"nb-positive-ikke-glem","locale":"nb","family":"calendar_create","text":"ikke glem møte i morgen kl 14","expected_intent":"calendar_item","expected_payload":{"calendar_item.time":"14:00"},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":true}
{"id":"nb-information-train","locale":"nb","family":"search","text":"Når går toget i morgen kl 8?","expected_intent":"search","expected_payload":{"search.type":"web"},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":true}
{"id":"nb-natural-calendar-edit","locale":"nb","family":"calendar_edit","text":"Kan du endre møte med Ola til fredag kl 10?","expected_intent":"calendar_edit","expected_payload":{"calendar_edit.target":"møte med Ola","calendar_edit.changes.time":"10:00"},"forbidden_intents":["calendar_item"],"fixture":"calendar_title_meeting","critical":true}
{"id":"nb-natural-reminder-create","locale":"nb","family":"reminder_create","text":"Påminn meg om å ringe legen i morgen","expected_intent":"reminder_create","expected_payload":{},"forbidden_intents":["calendar_item"],"fixture":"empty","critical":true}
{"id":"nn-capability-help","locale":"nn","family":"help","text":"Kva kan du gjere?","expected_intent":"help","expected_payload":{},"forbidden_intents":["ai_chat"],"fixture":"empty","critical":true}
{"id":"nb-explicit-shorten","locale":"nb","family":"utility","text":"forkort https://example.com","expected_intent":"shorten_url","expected_payload":{},"forbidden_intents":["poll_create"],"fixture":"empty","critical":true}
{"id":"trondelag-conversation-future","locale":"nb","family":"negative","text":"Æ ska bare høre ka du tænke om kampen i morra","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["calendar_item","reminder_create"],"fixture":"empty","critical":true}
{"id":"en-polite-reminder-delete","locale":"en","family":"reminder_delete","text":"Could you delete reminder 1?","expected_intent":"reminder_delete","expected_payload":{},"forbidden_intents":["ai_chat"],"fixture":"active_reminder","critical":true}
{"id":"en-negated-reminder-delete","locale":"en","family":"negative","text":"Do not delete reminder 1","expected_intent":"ai_chat","expected_payload":{},"forbidden_intents":["reminder_delete"],"fixture":"active_reminder","critical":true}
```

In `tests/test_nlu_contract.py`, replace the Task 1 seed-cardinality assertions with the Task 5 corpus contract: exactly `27` rows, first id still `nb-reminder-husk-mandag`, last id exactly `en-negated-reminder-delete`, and exactly `25` rows with `critical is True`. This is an intentional Task 5 update to the existing test, not a new test file.

- [ ] **Step 18: Run focused routing and corpus gates (2–5 minutes)**

Run:

```bash
.venv312/bin/python -m pytest \
  tests/test_intent_arbitration.py tests/test_intent_router.py \
  tests/test_false_positives.py tests/test_confidence_thresholds.py \
  tests/test_nlu_contract.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
```

Expected: all tests pass; CLI exits `0`; negative mutation false-positive rate and parser error rate are `0`; destructive precision, critical recall, and labeled payload accuracy are `1.0`.

- [ ] **Step 19: Run the full local non-browser regression gate (2–5 minutes)**

First run `df -h /System/Volumes/Data` and stop below `30Gi`. Otherwise run:

```bash
.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py
```

Expected: all non-browser repository tests pass. `tests/test_console_frontend.py` is intentionally excluded because Chromium/browser proof belongs to the observability/release-gates lane. If an unrelated pre-existing failure appears, capture its exact test id and prove the five focused Task 5 suites still pass; do not weaken the NLU corpus or safety assertions.

- [ ] **Step 20: Commit Task 5 (2–5 minutes)**

```bash
git add core/intent_arbitration.py core/intent_router.py \
  cal_system/reminder_manager.py features/watchlist_manager.py \
  tests/nlu_harness.py \
  tests/test_intent_arbitration.py tests/test_intent_router.py \
  tests/test_reminder_crud.py tests/test_false_positives.py \
  tests/fixtures/nlu_contract_v1.jsonl tests/test_nlu_contract.py
git commit -m "feat: arbitrate natural-language intent candidates"
```

The staged list must be exactly the eleven declared Task 5 files. `tests/test_watchlist_scope.py` remains gate-only and unstaged.

---

## Completion evidence

The implementation is complete only when all five commits exist in order, the full non-browser suite is green, and `.artifacts/nlu-contract.json` passes the exact gate without containing utterance text, payload values, identities, URLs, or exception strings. Record the final commit SHAs and exact commands/output in the project log; do not claim handler dispatch, pending-action confirmation, AI action proposals, birthday identity routing, runtime reminder delivery, persisted observability, deployment, or live Discord verification from this foundation plan.

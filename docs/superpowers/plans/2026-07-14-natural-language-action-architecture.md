# Inebotten Natural-Language Action Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Inebotten understand ordinary Norwegian, Nynorsk, dialect-adjacent, and English requests without requiring command syntax, while preventing questions, quotations, hypotheticals, negations, or model guesses from mutating user data.

**Architecture:** Keep the mention gate and deterministic feature parsers, but replace first-match dispatch with a shared proposal pipeline. Authorized text is normalized once, parsers emit typed candidates, an arbiter applies speech-act and risk rules, and handlers consume the selected typed payload without reparsing. When deterministic evidence is missing, the AI may emit one strictly validated action proposal; that proposal enters the same arbiter and never executes directly. Ambiguity and inferred writes become short-lived, user-scoped pending actions that support natural confirmation, cancellation, selection, and correction. Conversation history is keyed by guild, channel, and user so follow-ups are useful without leaking across conversations.

**Tech Stack:** Python 3.12.13, standard-library dataclasses/enums/re/unicodedata/zoneinfo, asyncio, pytest/pytest-asyncio, discord.py-self, LM Studio bridge, OpenRouter, JSON/JSONL persistence, GitHub Actions.

## Global Constraints

- Preserve the authorization order in core/message_monitor.py: require the existing bot mention in both guild channels and DMs, then apply allowed-user/channel checks before exposing cleaned content to normalization, routing, metrics, or AI. Untagged DMs remain ignored; this project does not expand that trust boundary.
- Do not respond to untagged guild or DM messages. Confirmation copy must explicitly ask for forms such as “@inebotten ja” and “@inebotten nei”.
- Preserve IntentRouter.route(content, guild_id=None) for existing callers. Any context additions are keyword-only.
- Preserve re-exports of BotIntent and IntentResult from core.intent_router.
- Preserve existing IntentResult positional construction: intent, confidence, payload, reason.
- During typed-dispatch Tasks 6–7, keep the legacy threshold check in `MessageMonitor._handle_intent()`. Model-actions Task 7 is the explicit, tested migration that moves the check to the central `_process_route()` exactly once and removes it from `_handle_intent()`; no completed architecture may retain both gates.
- Use normalized control text only for routing evidence. Build titles, search queries, quoted names, and handler payloads from case-preserving normalized text.
- The AI may propose an action; it may not call managers, handlers, Discord send methods, or persistence directly.
- Explicit deterministic read-only actions execute immediately. Explicit deterministic additive actions retain current behavior. Semantically inferred state changes require confirmation. Destructive actions always require confirmation.
- Every semantic destructive proposal also requires explicit action and domain evidence outside quotes; vague cleanup language cannot stage deletion.
- A negated, quoted-only, hypothetical, or meta-discussed mutation must never reach a mutating handler.
- Use Europe/Oslo as the default temporal zone. Store an aware due_at value while retaining tolerant reads of legacy due_date-only reminders.
- Add no new runtime NLP dependency. python-dateutil already exists, but the new normalization, intent, and validation layer must remain standard-library based.
- Keep manager/handler separation: pure interpretation and state logic in core, ai, cal_system, memory, or feature managers; Discord adaptation in handlers.
- Keep all I/O async and preserve the existing 5/sec and 10k/day rate-limit defaults.
- Use Norwegian Bokmål/Nynorsk for user-facing copy and English for code identifiers.
- Do not hardcode Discord tokens, provider keys, API credentials, or user identifiers.
- Keep JSON data under the existing data directory. Do not eagerly rewrite existing calendar or reminder files.
- Do not run Discord, Google Calendar, LM Studio, OpenRouter, URL-shortening, web-search, or other networked/live mutation paths during implementation verification.
- Do not log raw utterances, model responses, titles, names, URLs, or action slots in the new metrics. Aggregate counters only.
- Run repository Python commands with .venv312/bin/python.
- Check df -h /System/Volumes/Data before the aggregate test loop and stop below 30 GiB free.
- This plan deliberately excludes log-retention/privacy redesign, unrelated
  Google Calendar/provider redesign, deploy-readiness policy, and model/provider
  replacement. It **does include** moving every calendar/birthday mutation,
  OAuth exchange, credential refresh, and token write reachable from these
  actions into owned shielded `asyncio.to_thread()` work with exact commit-state
  settlement; that is required by the typed mutation contract, not a generic I/O
  refactor.

---

## Executable Plan Suite

This file is the reviewed architecture, evidence contract, cross-lane interface specification, and integration checklist. Implementation is split so a zero-context worker does not have to keep unrelated subsystems in one session:

1. `2026-07-14-natural-language-routing-foundation.md` — evaluation harness, public intent/risk models, normalization, temporal validation, candidate arbitration, and router migration (master Tasks 1–5).
2. `2026-07-14-typed-dispatch-reminder-runtime.md` — canonical payloads, parse-once dispatch, and single-owner reminder runtime (master Tasks 6–7).
3. `2026-07-14-model-actions-pending-context.md` — strict model action protocol, pending state, monitor integration, and scoped role-correct history (master Tasks 8–11).
4. `2026-07-14-natural-language-feature-parity.md` — birthday identity, bounded poll/watchlist syntax, typed profile operations, measured corpus coverage, and executable help parity (master Task 12).
5. `2026-07-14-natural-language-observability-release-gates.md` — bounded metrics, persistence, authenticated/redacted state, CI, docs, and final proof (master Task 13).

Execute lanes in that order. Do not begin a later lane until the prior lane's public interfaces and focused verification are green. Each sub-plan contains its own 2–5 minute test/implement/run/commit actions; use this master when resolving a cross-lane contract, not as a substitute for those executable steps.

## Review Coverage and Root Causes

The review covered `ai/`, `cal_system/`, `core/`, `features/`, `memory/`, `web_console/`, `scripts/`, `tests/`, operator documentation, CI, and the macOS/Windows launch surfaces. The launchers contain no independent NLU policy; they remain compatibility consumers of the same Python runtime. Existing strengths to preserve are the mention-required authorization gate in guilds and DMs, bounded rate limits, manager/handler split, atomic JSON helper, provider abstraction, and broad offline pytest coverage.

| Priority | Finding and evidence | User-visible consequence | Owning lane |
|---|---|---|---|
| P0 | `core/intent_router.py:104-243` returns the first parser match and has no pre-route speech-act, quotation, or negation model. | Questions, examples, and negated phrases can become writes/deletes; routing feels keyword-command driven. | routing foundation |
| P0 | Calendar, reminder, quote, birthday, watchlist, and poll handlers reparse `message.content` after routing (`features/*_handler.py`). | A safe router decision and a handler mutation can be based on different interpretations; confirmation cannot guarantee at-most-once execution. | typed dispatch |
| P0 | Model actions are split across mutable `ai/action_schema.py` records, provider prompts, legacy `SAVE_EVENT` tags, bridge parsing, and two response cleaners. | Paraphrase recognition is inconsistent by provider/model, and schema drift weakens the mutation trust boundary. | model actions |
| P1 | Calendar NLP treats temporal shape as action evidence, while the router gives high-confidence calendar parses early priority. | “Når går toget i morgen kl 8?” is treated like a calendar item instead of an information request. | routing foundation |
| P1 | `features/poll_manager.py:251-340` treats slash structure as poll evidence; `features/watchlist_manager.py:409-530` accepts bare generic add verbs. | URLs, paths, fractions, and ordinary “legg til” language steal unrelated requests. | feature parity |
| P1 | Birthday add/list parsing exists, but only `BIRTHDAY_EDIT` is reachable; raw display-name text is used where a Discord identity is required. | Advertised birthday language either falls through or can target the wrong person. | feature parity |
| P1 | Temporal parsing returns loosely shaped dictionaries and validates impossible dates/times late or inconsistently. | Invalid requests can reach calendar/reminder handlers, and relative dates depend on wall-clock timing in tests. | routing foundation |
| P1 | Reminder scheduling has overlapping alert windows, multiple lifecycle owners, legacy `due_date` precedence, direct wall-clock calls, and send paths that do not consistently report success. | Duplicate/missed reminders and false “sent” state are possible; natural relative timing is unreliable. | typed dispatch/reminder runtime |
| P1 | There is no scoped pending-action claim state shared by deterministic and model-inferred writes. | “ja”, “nei”, corrections, and ordinal choices cannot safely continue a natural multi-turn action. | model actions/pending |
| P1 | `memory/conversation_context.py` uses legacy/integer thread shapes and the router scans unrelated history for a reminder topic; provider transport can duplicate the current turn or blur roles. | Follow-ups are less natural and can leak topic context across user/channel boundaries. | model actions/context |
| P1 | Small-model prompt shortening, Gemma role folding, and bridge request construction are not covered by one provider contract. | The exact safety/action instructions can disappear on the models most likely to need them. | model actions/context |
| P2 | Discord help, localization strings, web commands, README, and model/provider docs maintain separate examples, several of which do not route as displayed. | Users learn command incantations that either fail or collide with another parser. | feature parity |
| P2 | Existing intent stats count final routes/errors but do not measure parser exceptions, unsafe false positives, clarification, proposal rejection, or pending outcomes; no deterministic NLU corpus is gated in CI. | Recognition regressions are anecdotal and cannot be distinguished from model-quality problems. | observability/release gates |
| P2 | Console persistence loads and writes stats in separate lock scopes and shutdown cancels tasks without a guaranteed final stats flush. | Operational evidence can be lost or double-counted across concurrent flush/restart paths. | observability/release gates |

This diagnosis separates deterministic recognition from generative answer quality: the main “command style” problem is architectural routing and payload flow, not simply a weak model. A better model may improve fallback prose, but it cannot correct first-match parser theft, raw handler reparsing, missing speech-act safety, or unscoped follow-up state.

---

## Evidence and Success Contract

Current HEAD reviewed: 437bc5edcc476705be68b24779b3e9c95730e1cb.

Read-only baseline: 622 non-browser tests passed. The separate frontend run produced 24 Playwright setup errors because Chromium was not installed; those were environment errors, not application assertion failures. A focused action/context/router/monitor slice passed 78 tests plus 17 subtests.

The review established these production-path failures:

| Utterance | Current result | Required result |
|---|---|---|
| Når går toget i morgen kl 8? | CALENDAR_ITEM | SEARCH; no write |
| Ikke slett påminnelse 1 | REMINDER_DELETE | AI_CHAT; no write |
| Hva skjer hvis jeg skriver “slett påminnelse 1”? | REMINDER_DELETE | AI_CHAT; no write |
| Kan du endre møte med Ola til fredag kl 10? | CALENDAR_ITEM | CALENDAR_EDIT with parsed target and changes |
| Påminn meg om å ringe legen i morgen | CALENDAR_ITEM | REMINDER_CREATE |
| Kva kan du gjere? | AI_CHAT | HELP |
| Forkort https://example.com/a/b | POLL_CREATE | SHORTEN_URL |
| Møte 32.13.2026 kl 14:00 | CALENDAR_ITEM | CLARIFY or AI_CHAT; no write |
| Møte i morgen kl 25:61 | CALENDAR_ITEM | CLARIFY or AI_CHAT; no write |

The acceptance gate at the end of the plan is:

- parser_error_rate equals 0;
- negative_mutation_false_positive_rate equals 0;
- destructive_action_precision equals 1;
- critical_action_recall equals 1;
- labeled payload accuracy equals 1;
- overall exact-intent accuracy is at least 0.98;
- each labeled locale has exact-intent accuracy of at least 0.95;
- no current non-browser test regresses;
- the browser suite is run separately after installing Chromium;
- no raw utterance is present in the generated aggregate report.

## Target Data Flow

~~~text
authorized Discord message
  -> ConversationKey(guild_id, channel_id, user_id)
  -> NormalizedUtterance(raw, text, control_text, tokens, quoted segments)
  -> deterministic candidate collectors
  -> speech-act + negation + temporal validation
  -> risk-aware arbitration
       -> one safe IntentResult
       -> CLARIFY with typed choices
       -> AI_CHAT fallback
  -> optional strictly parsed AI ActionProposal
  -> same risk-aware arbitration
  -> immediate read / immediate explicit add / PendingAction
  -> handler consumes typed payload once
  -> centralized outbound history recorder
~~~

## Stable Interfaces

The implementation must converge on these contracts:

~~~python
# core/intent_models.py
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
    MISSING_LIVE_EVIDENCE = "missing_live_evidence"
    MISSING_ACTION_EVIDENCE = "missing_action_evidence"
    MISSING_DOMAIN_EVIDENCE = "missing_domain_evidence"
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
~~~

~~~python
# core/message_context.py
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
~~~

~~~python
# core/utterance.py
@dataclass(frozen=True, slots=True)
class NormalizedUtterance:
    raw: str
    text: str
    folded: str
    control_text: str
    quoted_segments: tuple[str, ...]
    tokens: tuple[str, ...]
~~~

~~~python
# cal_system/temporal_resolver.py
@dataclass(frozen=True, slots=True)
class TemporalResolution:
    date: str | None
    time: str | None
    due_at: str | None
    matched_text: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors
~~~

~~~python
# ai/action_schema.py
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = (
    JsonScalar
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action: ActionName
    confidence: float
    slots: Mapping[str, JsonValue]
    reply: str = ""
    clarification: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedAIResponse:
    text: str
    proposal: ActionProposal | None
    errors: tuple[str, ...] = ()
    legacy: bool = False
~~~

~~~python
# core/pending_actions.py
class PendingKind(str, Enum):
    CONFIRMATION = "confirmation"
    CHOICE = "choice"


class PendingStatus(str, Enum):
    PRESENTING = "presenting"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class PendingTargetFamily(str, Enum):
    CALENDAR = "calendar"
    REMINDER = "reminder"
    POLL = "poll"
    WATCHLIST = "watchlist"
    QUOTE = "quote"
    BIRTHDAY = "birthday"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class PendingTargetGuard:
    family: PendingTargetFamily
    stable_id: str | None
    original_position: int | None
    fingerprint: str | None
    revision: str | None
    label: str
    display_detail: str = ""

    def __post_init__(self) -> None:
        identities = int(bool(self.stable_id)) + int(bool(self.fingerprint))
        if identities != 1:
            raise ValueError("exactly_one_target_identity")
        if self.stable_id and not self.revision:
            raise ValueError("stable_id_requires_revision")
        object.__setattr__(
            self,
            "label",
            sanitize_pending_label(self.label, fallback="valgt element"),
        )
        object.__setattr__(
            self,
            "display_detail",
            sanitize_pending_detail(
                self.display_detail or self.label,
                fallback="valgt element",
            ),
        )


@dataclass(frozen=True, slots=True)
class PendingAction:
    action_id: str
    key: ConversationKey
    kind: PendingKind
    routes: tuple[IntentResult, ...]
    summary: str
    created_at: datetime
    expires_at: datetime
    status: PendingStatus = PendingStatus.PRESENTING
    target_guards: tuple[PendingTargetGuard | None, ...] = ()
    settled_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.target_guards) != len(self.routes):
            raise ValueError("guard_count_mismatch")
        terminal = self.status in {
            PendingStatus.COMPLETED,
            PendingStatus.FAILED,
        }
        if terminal != (self.settled_at is not None):
            raise ValueError("settled_at_status_mismatch")
~~~

## Dependency Order

~~~text
Task 1 evaluation foundation
  ├─> Task 2 intent/risk models ─> Task 3 utterance semantics ─┐
  └─> Task 4 temporal resolver ────────────────────────────────┤
                                                               v
Task 5 candidate arbitration -> Task 6 parse-once dispatch -> Task 7 reminders
                                      │
                                      └─> Task 8 AI proposals -> Task 9 pending state
                                                                  │
                                                                  v
Task 10 monitor action flow -> Task 11 scoped context -> Task 12 parity/corpus
                                                        │
                                                        v
                                              Task 13 CI/docs/final gate
~~~

After Task 1, Tasks 2 and 4 may be implemented in parallel because they touch disjoint production modules. All edits to core/intent_router.py must be serialized through Tasks 2, 5, 6, 9, 10, and 12. All edits to core/message_monitor.py must be serialized through Tasks 6, 7, 10, 11, 12, and 13.

---

### Task 1: Create a deterministic production-parser evaluation harness

**Objective:** Establish an offline, machine-readable contract before changing routing behavior.

**Interfaces:**

- Consumes: IntentRouter, NaturalLanguageParser, and the production feature parsing functions imported by MessageMonitor.
- Produces: EvalCase, EvalResult, aggregate_intent_report(), a JSONL corpus, a pytest gate, and an executable report command.
- Must not consume: MessageMonitor.__init__, Discord, persisted user data, live AI, or network managers.

**Files:**

- Create: tests/nlu_harness.py
- Create: tests/fixtures/nlu_contract_v1.jsonl
- Create: tests/test_nlu_contract.py
- Create: scripts/evaluate_nlu.py
- Create: core/eval_fixtures.py
- Modify: tests/README_TESTING.md
- Modify: .gitignore

- [ ] **Step 1: Write the failing harness tests**

Add tests that prove the loader rejects duplicate ids and malformed payload expectations, and that the evaluator uses the router result rather than a hand-written expected parser.

~~~python
def test_load_cases_rejects_duplicate_ids(tmp_path):
    corpus = tmp_path / "cases.jsonl"
    corpus.write_text(
        '{"id":"same","locale":"nb","family":"chat","text":"hei",'
        '"expected_intent":"ai_chat","expected_payload":{},'
        '"forbidden_intents":[],"fixture":"empty","critical":false}\n'
        '{"id":"same","locale":"nn","family":"chat","text":"hei",'
        '"expected_intent":"ai_chat","expected_payload":{},'
        '"forbidden_intents":[],"fixture":"empty","critical":false}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate eval id: same"):
        load_cases(corpus)


def test_evaluator_records_exact_intent_and_payload():
    router = StubRouter(IntentResult(BotIntent.HELP, 0.96, {}, "help_keyword"))
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
    result = evaluate_case(case, router, guild_id=123)
    assert result.actual_intent == "help"
    assert result.intent_match is True
    assert result.payload_match is True
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_nlu_contract.py -q
~~~

Expected: FAIL because tests/nlu_harness.py does not exist.

- [ ] **Step 2: Implement the harness and production-parser adapter**

In tests/nlu_harness.py:

~~~python
ParserName: TypeAlias = Literal[
    "parse_task_with_recurrence", "parse_event", "parse_countdown_query",
    "parse_poll_command", "parse_vote", "parse_watchlist_command",
    "parse_quote_command", "parse_price_command", "parse_horoscope_command",
    "parse_compliment_command", "parse_calculator_command",
    "parse_shorten_command", "detect_search_intent", "parse_reminder_command",
    "parse_birthday_command", "parse_profile_command",
]
RiskName: TypeAlias = Literal[
    "read_only", "additive", "mutating", "destructive"
]


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
~~~

- Define frozen EvalCase and EvalResult dataclasses.
- Define EvalFixture in core/eval_fixtures.py as EMPTY, ACTIVE_POLL, ACTIVE_REMINDER, CALENDAR_TITLE_MEETING, MENTIONED_USER_42, and MIXED_STATE; tests and the later help registry import this one enum.
- Fixtures use guild_id=123, channel_id=456, and author ResolvedMention(7, "Kari") once RoutingContext is available. ACTIVE_POLL exposes poll id poll-1; ACTIVE_REMINDER exposes reminder id reminder-1; CALENDAR_TITLE_MEETING exposes “Møte med Ola”; MENTIONED_USER_42 resolves user 42 as “Ola”; MIXED_STATE combines those three active domain records.
- load_cases() must require exactly these keys: id, locale, family, text, expected_intent, expected_payload, forbidden_intents, fixture, critical.
- Reject blank ids/text, unknown BotIntent values, duplicate ids, a non-object expected_payload, and non-string forbidden intent values.
- build_production_router() must construct a lightweight monitor adapter with:
  - NaturalLanguageParser();
  - actual parse_poll_command, parse_vote, parse_watchlist_command, parse_quote_command, parse_price_command, parse_horoscope_command, parse_compliment_command, parse_calculator_command, parse_shorten_command, and detect_search_intent;
  - CountdownManager();
  - bounded in-memory calendar, reminder, poll, and mention-target state selected by EvalFixture;
  - ConversationContext() with a fixed, empty key;
  - no file-backed manager and no MessageMonitor construction.
- dotted_payload_matches() must compare only labeled dotted paths and use exact scalar/list equality.
- aggregate_intent_report() must emit totals and per-locale/per-family counts, exact-intent accuracy, payload accuracy, parser error rate, negative mutation false-positive rate, critical action recall, and destructive precision.
- The harness uses this complete local classifier, so its safety formulas do not depend on Task 2:

~~~python
READ_ONLY = {
    "help", "status", "calendar_help", "calendar_list", "calendar_search",
    "reminder_list", "reminder_search", "poll_list", "countdown",
    "word_of_day", "quote_list", "aurora", "school_holidays", "price",
    "horoscope", "compliment", "calculator", "shorten_url", "daily_digest",
    "search", "dashboard", "memory_view", "memory_export", "ai_chat",
    "clarify", "birthday_list", "action_confirm", "action_cancel",
    "action_select", "action_correct",
}
ADDITIVE = {"calendar_item", "reminder_create", "poll_create", "birthday_create"}
MUTATING = {
    "profile", "calendar_sync", "calendar_complete", "calendar_edit",
    "calendar_auth", "reminder_complete", "reminder_edit", "poll_vote",
    "poll_edit", "poll_close", "quote_edit", "birthday_edit", "set_location",
}
DESTRUCTIVE = {
    "calendar_delete", "calendar_clear", "reminder_delete", "poll_delete",
    "quote_delete", "memory_delete",
}


def nested_string(
    payload: Mapping[str, object],
    outer: str,
    inner: str,
) -> str:
    dotted = payload.get(f"{outer}.{inner}")
    if isinstance(dotted, str):
        return dotted
    nested = payload.get(outer)
    if not isinstance(nested, Mapping):
        return ""
    value = nested.get(inner)
    return value if isinstance(value, str) else ""


def classify_eval_risk(intent: str, payload: Mapping[str, object]) -> str:
    if intent == "watchlist":
        action = nested_string(payload, "watchlist", "action")
        return {
            "status": "read_only", "list": "read_only", "suggest": "read_only",
            "add": "additive", "edit": "mutating", "remove": "destructive",
        }.get(action, "destructive")
    if intent == "quote":
        action = nested_string(payload, "quote", "action")
        return {"get": "read_only", "save": "additive"}.get(action, "destructive")
    if intent in READ_ONLY:
        return "read_only"
    if intent in ADDITIVE:
        return "additive"
    if intent in MUTATING:
        return "mutating"
    if intent in DESTRUCTIVE:
        return "destructive"
    raise AssertionError(f"unclassified eval intent: {intent}")
~~~

- `destructive_action_precision = results whose actual risk is destructive, expected risk is destructive, intent matches, and every labeled payload path matches / all results whose actual risk is destructive`; this catches payload-dependent WATCHLIST/QUOTE mutations even when the outer intent matches. A zero denominator fails the gate, and the corpus contains at least one positive destructive case.
- `negative_mutation_false_positive_rate = negative_cases_with_actual_risk_not_read_only / all_negative_cases`; a zero denominator fails the gate.
- `critical_action_recall = exact_intent_matches_for_critical_non_chat_cases / all_critical_cases_whose_expected_intent_is_not_ai_chat_or_clarify`; a zero denominator fails the gate.
- `parser_error_rate = parser_error_results / all_results`, `overall_exact_intent_accuracy = exact_intent_matches / all_results`, and each locale uses the same exact-intent formula over that locale.
- `labeled_payload_accuracy = payload_matches / cases_with_nonempty_expected_payload`; a zero denominator fails the gate.
- `evaluate_case()` sets `expected_risk = classify_eval_risk(expected_intent, expected_payload)`, `actual_risk = classify_eval_risk(actual_intent, actual_payload)`, `payload_labeled = bool(expected_payload)`, and `parser_names` to a sorted tuple drawn only from the parser-name allowlist. Unknown parser names become `other`; exception text is never stored.
- Bucket parser exceptions into a fixed parser_error code plus parser name allowlist; never copy exception text into a report.
- Emit only a documented schema whitelist of ids, intent enum values, bounded error codes, integer totals, and numeric rates.
- Reports contain ids and aggregate intent names, never case text.
- Wrap production parser callables in the Task 1 adapter so exceptions set EvalResult.parser_error before returning no candidate. Once Task 5 adds evaluate_utterance(), evaluate_case() consumes RoutedIntent.diagnostics directly; it must snapshot per call, not read shared last-route state.

- [ ] **Step 3: Seed a green corpus from current production contracts**

Add at least these exact JSONL rows to tests/fixtures/nlu_contract_v1.jsonl:

~~~jsonl
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
~~~

If a seed row exposes an existing failure, label it in the next task that fixes the behavior; do not weaken its expected result to make the harness green.

- [ ] **Step 4: Implement the report CLI**

scripts/evaluate_nlu.py must accept:

~~~text
--corpus PATH
--report PATH
--min-overall 0.98
--min-locale 0.95
~~~

It creates the report parent directory, writes stable sorted JSON with a trailing newline, prints one aggregate summary line, and exits 1 when any acceptance threshold fails.

At the top of the script, insert the repository root derived from Path(__file__).resolve().parents[1] into sys.path before importing core or tests modules, matching the repository entry-point convention. Add .artifacts/ to .gitignore so local reports do not dirty the worktree.

- [ ] **Step 5: Run and document the harness**

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_nlu_contract.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
~~~

Expected: PASS and a report containing no utterance text.

- [ ] **Step 6: Commit**

~~~bash
git add tests/nlu_harness.py tests/fixtures/nlu_contract_v1.jsonl \
  tests/test_nlu_contract.py scripts/evaluate_nlu.py core/eval_fixtures.py \
  tests/README_TESTING.md \
  .gitignore
git commit -m "test: add production NLU contract harness"
~~~

---

### Task 2: Extract stable intent models and classify action risk

**Objective:** Separate public data contracts from routing implementation so arbitration, AI proposals, and pending actions share one type system without import cycles.

**Interfaces:**

- Consumes: current BotIntent and IntentResult declarations from core/intent_router.py.
- Produces: core.intent_models models and core.intent_policy risk classification.
- Compatibility: core.intent_router continues to export the exact same class objects.

**Files:**

- Create: core/intent_models.py
- Create: core/intent_policy.py
- Create: core/message_context.py
- Create: core/nlu_metrics.py
- Create: tests/test_intent_models.py
- Create: tests/test_nlu_metrics.py
- Modify: core/intent_router.py:41-99
- Modify: core/intent_thresholds.py:1-24

- [ ] **Step 1: Write import-compatibility and policy tests**

~~~python
from core.intent_models import (
    BotIntent as ModelBotIntent,
    IntentCandidate,
    IntentRisk,
    IntentSource,
)
from core.intent_router import BotIntent as RouterBotIntent


def test_router_reexports_public_intent_model():
    assert RouterBotIntent is ModelBotIntent


@pytest.mark.parametrize(
    ("intent", "payload", "risk"),
    [
        (ModelBotIntent.CALENDAR_LIST, {}, IntentRisk.READ_ONLY),
        (ModelBotIntent.CALENDAR_ITEM, {}, IntentRisk.ADDITIVE),
        (ModelBotIntent.CALENDAR_COMPLETE, {}, IntentRisk.MUTATING),
        (ModelBotIntent.CALENDAR_DELETE, {}, IntentRisk.DESTRUCTIVE),
        (ModelBotIntent.WATCHLIST, {"watchlist": {"action": "remove"}}, IntentRisk.DESTRUCTIVE),
        (ModelBotIntent.WATCHLIST, {"watchlist": {"action": "suggest"}}, IntentRisk.READ_ONLY),
    ],
)
def test_classify_intent_risk(intent, payload, risk):
    assert classify_intent_risk(intent, payload) is risk
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_intent_models.py -q
~~~

Expected: FAIL because core.intent_models does not exist.

- [ ] **Step 2: Move and extend the models**

- Move BotIntent without renaming existing values.
- Append CLARIFY, BIRTHDAY_CREATE, BIRTHDAY_LIST, ACTION_CONFIRM, ACTION_CANCEL, ACTION_SELECT, and ACTION_CORRECT.
- Define IntentSource, IntentRisk, RejectionCode, IntentCandidate, CandidateRejection, ArbitrationDecision, RouteDiagnostics, and RoutedIntent exactly as shown in Stable Interfaces; Task 5 consumes these classes and must not create duplicate router-local models.
- Extend IntentResult only with defaulted source, risk, and requires_confirmation fields after the four existing fields.
- Implement IntentCandidate.to_result() by copying the shared intent, confidence, payload, reason, source, risk, and requires_confirmation fields. Priority, evidence terms, and specificity are arbitration-only and are intentionally omitted.
- Re-export BotIntent, IntentResult, IntentCandidate, IntentRisk, and IntentSource from core.intent_router.
- Change core/intent_thresholds.py to import BotIntent from core.intent_models, breaking the current threshold-to-router cycle.
- Add ConversationKey, ResolvedMention, and RoutingContext to core/message_context.py exactly as defined in Stable Interfaces. These carry already-resolved Discord identities; parsers never query Discord or reparse message.mentions.
- Add the final bounded in-memory NLUMetrics API now: `record_decision(*, intent, source, outcome)`, `record_rejection(code)`, `record_pending(event)`, `record_action_result(result)`, `record_parser_error(parser, code)`, `record_legacy_payload_fallback(family)`, `record_reminder_delivery(event, *, error_code=None)`, `merge_snapshot(delta)`, and `snapshot()`. Use the exact allowlists and composite-key naming in the observability sub-plan; Tasks 5–12 inject this same sink, while Task 13 adds persistence and console projection rather than replacing the class.

- [ ] **Step 3: Implement exhaustive risk classification**

core/intent_policy.py must contain this explicit conservative base mapping for every BotIntent. `PROFILE` changes Discord presence, `SET_LOCATION` writes user state, `CALENDAR_SYNC` and `CALENDAR_AUTH` write synchronization/auth state, and `POLL_VOTE` mutates a poll; none may be grouped with utilities. Pending control intents only resolve ephemeral pending state, so the selected route retains the domain risk.

~~~python
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
    BotIntent.BIRTHDAY_CREATE: IntentRisk.ADDITIVE,
    BotIntent.BIRTHDAY_LIST: IntentRisk.READ_ONLY,
    BotIntent.BIRTHDAY_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.REMINDER_SEARCH: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_CREATE: IntentRisk.ADDITIVE,
    BotIntent.REMINDER_LIST: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_COMPLETE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_AUTH: IntentRisk.MUTATING,
    BotIntent.CLARIFY: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CONFIRM: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CANCEL: IntentRisk.READ_ONLY,
    BotIntent.ACTION_SELECT: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CORRECT: IntentRisk.READ_ONLY,
    BotIntent.AI_CHAT: IntentRisk.READ_ONLY,
}

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


def _payload_action(payload: Mapping[str, Any], family: str) -> str:
    nested = payload.get(family)
    if not isinstance(nested, Mapping):
        return ""
    action = nested.get("action")
    return action if isinstance(action, str) else ""


def classify_intent_risk(intent: BotIntent, payload: Mapping[str, Any]) -> IntentRisk:
    if intent is BotIntent.WATCHLIST:
        action = _payload_action(payload, "watchlist")
        return WATCHLIST_ACTION_RISK.get(action, IntentRisk.DESTRUCTIVE)
    if intent is BotIntent.QUOTE:
        action = _payload_action(payload, "quote")
        return QUOTE_ACTION_RISK.get(action, IntentRisk.DESTRUCTIVE)
    return BASE_INTENT_RISK[intent]
~~~

The test must import `classify_intent_risk` and `BASE_INTENT_RISK` from `core.intent_policy`, assert `set(BASE_INTENT_RISK) == set(BotIntent)`, cover every WATCHLIST/QUOTE action, and assert the conservative DESTRUCTIVE fallback for a missing or unknown umbrella action.

Add:

~~~python
def test_every_intent_has_a_risk_classification():
    for intent in ModelBotIntent:
        risk = classify_intent_risk(intent, {})
        assert isinstance(risk, IntentRisk), intent
~~~

- [ ] **Step 4: Run compatibility suites**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_intent_models.py \
  tests/test_nlu_metrics.py \
  tests/test_intent_router.py \
  tests/test_confidence_thresholds.py -q
~~~

Expected: PASS with unchanged existing payloads and reason strings.

- [ ] **Step 5: Commit**

~~~bash
git add core/intent_models.py core/intent_policy.py core/message_context.py \
  core/nlu_metrics.py \
  core/intent_router.py \
  core/intent_thresholds.py tests/test_intent_models.py \
  tests/test_nlu_metrics.py
git commit -m "refactor: centralize intent and risk models"
~~~

---

### Task 3: Normalize utterances and detect speech acts safely

**Objective:** Distinguish a request from a question about a request, a negation, or a quoted example before any parser can claim an action.

**Interfaces:**

- Consumes: cleaned, authorized content.
- Produces: NormalizedUtterance and UtteranceSemantics.
- Does not replace: mention authorization, title extraction, or feature parsers.

**Files:**

- Create: core/utterance.py
- Create: core/utterance_semantics.py
- Create: tests/test_utterance.py
- Create: tests/test_utterance_semantics.py
- Modify: core/intent_utils.py:1-70

- [ ] **Step 1: Write normalization and safety tests**

~~~python
def test_quoted_command_is_masked_from_control_text():
    utterance = normalize_utterance(
        'hva skjer hvis jeg skriver "slett påminnelse 1"?'
    )
    assert utterance.quoted_segments == ("slett påminnelse 1",)
    assert "slett påminnelse" not in utterance.control_text
    assert utterance.text == 'hva skjer hvis jeg skriver "slett påminnelse 1"?'


@pytest.mark.parametrize(
    "text",
    [
        "ikke slett kalenderen",
        "slett ikke kalenderen",
        "ikkje slett kalenderen",
        "do not delete the calendar",
        "never delete the calendar",
    ],
)
def test_negated_delete_is_not_a_mutation_directive(text):
    utterance = normalize_utterance(text)
    semantics = analyze_utterance(utterance)
    assert is_negated_action(utterance, ("slett", "delete")) is True
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem møte i morgen kl 14",
        "ikkje gløym møte i morgon klokka 14",
        "don't forget the meeting tomorrow at 2pm",
    ],
)
def test_do_not_forget_idiom_remains_positive(text):
    utterance = normalize_utterance(text)
    assert analyze_utterance(utterance).allows_mutation is True
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_utterance.py tests/test_utterance_semantics.py -q
~~~

Expected: FAIL because the modules do not exist.

- [ ] **Step 2: Implement lossless normalization**

normalize_utterance() must:

- apply Unicode NFKC;
- collapse whitespace and normalize straight/curly quote matching without changing the case-preserving text used for payloads;
- use casefold for folded detection;
- mask quoted spans and Discord mentions in control_text with whitespace of equal token separation;
- retain quoted content in quoted_segments;
- tokenize letters, numbers, apostrophes, colon times, and date separators;
- never remove ordinary user mentions from text;
- return deterministic values for blank text.

Change has_keyword() and has_any_keyword() to accept either str or NormalizedUtterance and use control_text for the latter.

- [ ] **Step 3: Implement semantics with explicit precedence**

Define SpeechAct values DIRECTIVE, INFORMATION_REQUEST, STATEMENT, HYPOTHETICAL, META, CONFIRMATION, and REJECTION. UtteranceSemantics contains speech_act, reasons, and allows_mutation.

Detection order:

1. exact confirmation/rejection phrases;
2. meta/hypothetical frames such as “hva skjer hvis”, “kva skjer om”, “what happens if”, “jeg skrev”, and “eksempel”;
3. polite directives such as “kan du”, “kunne du”, “vil du”, “could you”, and “please”;
4. information questions;
5. imperative action evidence;
6. statement fallback.

is_negated_action() must inspect a three-token window on both sides of each action term and recognize ikke, ikkje, aldri, not, never, do not, and don't. Exempt the positive reminder idioms “ikke glem”, “ikkje gløym”, and “don't forget”.

- [ ] **Step 4: Add the first safety corpus cases**

Append exact cases for negated calendar/reminder/poll deletion, quoted examples, hypothetical mutation, polite directives, and positive “ikke glem” phrases. Expected mutation cases are not routed through semantics until Task 5, so mark the corpus update in the Task 5 commit rather than leaving the gate red here.

- [ ] **Step 5: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_utterance.py tests/test_utterance_semantics.py \
  tests/test_intent_utils.py -q
git add core/utterance.py core/utterance_semantics.py core/intent_utils.py \
  tests/test_utterance.py tests/test_utterance_semantics.py
git commit -m "feat: classify natural-language speech acts"
~~~

Expected: PASS.

---

### Task 4: Resolve and validate Norwegian temporal expressions

**Objective:** Parse natural dates and times with an injected Oslo clock, and reject impossible values before they become action candidates or handler mutations.

**Interfaces:**

- Consumes: case-preserving normalized text and an optional aware reference datetime.
- Produces: canonical DD.MM.YYYY, HH:MM, and ISO-8601 due_at.
- Called by: NaturalLanguageParser, calendar handlers, reminder parser, AI action validation.

**Files:**

- Create: cal_system/temporal_resolver.py
- Create: tests/test_temporal_resolver.py
- Create: tests/test_natural_language_parser_safety.py
- Modify: cal_system/natural_language_parser.py:13-18,156-445,478-587,590-717
- Modify: features/calendar_handler.py:225-332,614-705
- Modify: tests/test_calendar_edit.py

- [ ] **Step 1: Write fixed-clock resolver tests**

~~~python
OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)


@pytest.mark.parametrize(
    ("text", "date", "time"),
    [
        ("i morgen kl 8", "15.07.2026", "08:00"),
        ("i morgon klokka fjorten", "15.07.2026", "14:00"),
        ("om to timer", "14.07.2026", "14:00"),
        ("fredag kl 10", "17.07.2026", "10:00"),
        ("15. august rundt tre", "15.08.2026", "15:00"),
    ],
)
def test_resolve_supported_natural_time(text, date, time):
    result = TemporalResolver().resolve(text, reference=NOW)
    assert result.valid is True
    assert result.date == date
    assert result.time == time


@pytest.mark.parametrize(
    ("date_value", "time_value"),
    [
        ("32.13.2026", "14:00"),
        ("29.02.2025", "14:00"),
        ("15.07.2026", "25:61"),
        ("15.07.2026", "-1:00"),
    ],
)
def test_impossible_values_are_rejected(date_value, time_value):
    result = TemporalResolver().validate_fields(
        date_value,
        time_value,
        reference=NOW,
    )
    assert result.valid is False
    assert result.errors


def test_nonexistent_oslo_wall_time_is_rejected():
    result = TemporalResolver().validate_fields(
        "29.03.2026",
        "02:30",
        reference=NOW,
    )
    assert result.errors == ("invalid_time",)


def test_ambiguous_oslo_wall_time_requires_clarification():
    result = TemporalResolver().validate_fields(
        "25.10.2026",
        "02:30",
        reference=NOW,
    )
    assert result.errors == ("ambiguous_time",)
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_temporal_resolver.py -q
~~~

Expected: FAIL because TemporalResolver does not exist.

- [ ] **Step 2: Implement canonical validation first**

Implement validate_fields() with datetime construction rather than regex-only validation:

- accept DD.MM, DD.MM.YYYY, slash variants, H, and H:MM;
- yearless dates select the first non-past occurrence;
- accept 00:00 through 23:59 only;
- canonicalize to DD.MM.YYYY and HH:MM;
- use ZoneInfo("Europe/Oslo");
- detect local-time validity by round-tripping fold=0 and fold=1 candidates through UTC; reject zero valid round trips as invalid_time and two distinct valid offsets as ambiguous_time;
- accept an ambiguous instant only when an ISO due_at includes an explicit valid UTC offset, never by silently choosing a fold;
- default a date-only reminder time later in reminder code, not in the generic validator;
- return errors using stable machine codes: invalid_date, invalid_time, missing_date, ambiguous_time.

- [ ] **Step 3: Implement bounded natural resolution**

Support:

- i dag, i morgen, i morgon, imårra, tomorrow;
- weekdays in Bokmål, Nynorsk, common Trøndelag forms, and English;
- neste/next and førstkommende semantics pinned by tests;
- om/in N minutter, timer, dager, or uker, including Norwegian number words zero through thirty-one;
- numeric dates and Norwegian/English month names;
- kl, kl., klokka, klokken, at, rundt/about;
- 12-hour am/pm conversion;
- default evening tokens “kveld/i kveld” to 19:00 only where the current parser already promises it.

Do not parse bare future words inside information questions as mutation evidence; the resolver reports time only and leaves intent decisions to arbitration.

- [ ] **Step 4: Integrate with NaturalLanguageParser**

- Add now_provider to NaturalLanguageParser.__init__ with datetime.now in Oslo as the default.
- Replace direct datetime.now calls used for resolution.
- Call TemporalResolver for both event and task paths.
- If time/date evidence was present but invalid, return no calendar item and expose a parse diagnostic that the router can turn into CLARIFY.
- Preserve current title, recurrence, and type payload keys.

Add a compatibility-preserving result API:

~~~python
@dataclass(frozen=True, slots=True)
class NaturalParseResult:
    item: dict[str, Any] | None
    errors: tuple[str, ...] = ()


def parse_event_result(
    self,
    message_content: str,
    *,
    temporal_text: str | None = None,
    reference_time: datetime | None = None,
) -> NaturalParseResult:
    return self._parse_event_result(
        message_content,
        temporal_text=temporal_text,
        reference_time=reference_time,
    )


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
    return self._parse_task_with_recurrence_result(
        message_content,
        temporal_text=temporal_text,
        reference_time=reference_time,
    )


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

The router uses both result methods and always supplies the turn-captured aware `reference_time` plus `temporal_text=utterance.control_text`; quoted/code text remains available to raw title extraction but cannot supply temporal slots. Legacy callers keep the two dictionary-or-None wrappers and may omit the keywords. Move the current parser bodies into the named private result implementations and return stable invalid_date, invalid_time, ambiguous_time, and conflicting_temporal codes. All temporal consumers use the one monitor-owned `TemporalResolver`; defaults are offline/test compatibility only.

Add:

~~~python
def test_parser_rejects_invalid_temporal_evidence():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    assert parser.parse_event("møte 32.13.2026 kl 14:00") is None
    assert parser.parse_event("møte i morgen kl 25:61") is None
~~~

- [ ] **Step 5: Add handler defense in depth**

`CalendarHandler.handle_calendar_item()`, `_parse_date_value()`, and `handle_edit()` must revalidate typed date/time fields against the turn's captured `reference_time` before calling `CalendarManager`. Invalid values make zero manager calls, build `DispatchOutcome.failure("invalid_payload")`, send one Norwegian clarification, and return `base.with_delivery(send_result)`. Successful mutation methods follow the same two-stage pattern, separating mutation truth from delivery certainty so pending actions can be completed safely later.

- [ ] **Step 6: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_temporal_resolver.py \
  tests/test_natural_language_parser_safety.py \
  tests/test_calendar_edit.py \
  tests/test_selfbot_comprehensive.py -q
git add cal_system/temporal_resolver.py cal_system/natural_language_parser.py \
  features/calendar_handler.py tests/test_temporal_resolver.py \
  tests/test_natural_language_parser_safety.py tests/test_calendar_edit.py
git commit -m "feat: resolve and validate natural temporal expressions"
~~~

Expected: PASS.

---

### Task 5: Replace first-match routing with risk-aware candidate arbitration

**Objective:** Preserve deterministic parsing while evaluating competing interpretations and blocking unsafe mutation candidates before dispatch.

**Interfaces:**

- Consumes: NormalizedUtterance, UtteranceSemantics, and pure IntentCandidate collectors.
- Produces: one IntentResult, CLARIFY, or AI_CHAT.
- Compatibility: the current early-return source sequence is encoded by the explicit tier/order table below; confidence values, payload shapes, reason strings, and the two-position route call remain stable where behavior is not intentionally changed.

**Files:**

- Create: core/intent_arbitration.py
- Create: tests/test_intent_arbitration.py
- Modify: core/intent_router.py:104-243,245-729
- Modify: tests/test_intent_router.py
- Modify: tests/test_false_positives.py
- Modify: tests/fixtures/nlu_contract_v1.jsonl

Encode the current early-return order with explicit lower-is-earlier tiers:

| Tier | Candidate family |
|---:|---|
| 10 | exact calendar help, status, help, profile, memory controls |
| 20 | explicit destructive/edit/complete calendar or reminder, calendar auth |
| 30 | explicit domain list/search/read and birthday edit |
| 35 | equally explicit natural state-create candidates across calendar/reminder/poll/watchlist |
| 40 | calendar NLP candidate with confidence >= 0.94 |
| 50 | poll/countdown/watchlist/word/quote/content-feature parsers |
| 60 | price/horoscope/compliment/calculator/URL/digest utilities |
| 70 | lower-confidence calendar NLP candidate |
| 80 | contextual web search, dashboard, location |
| 90 | AI chat fallback |

Specificity is independent of tier: 0 for implicit parser shape, 1 for domain evidence, 2 for action plus domain, 3 for action plus domain plus target/value, and 4 for exact operational/pending forms. `order` is the monotonically increasing position of the branch in the current `IntentRouter.route()` source sequence within its tier. Only tier 35 intentionally permits cross-domain ambiguity at equal specificity and confidence distance; every other tie preserves the current source order. `intent.value` is only the final deterministic tie-breaker for candidates emitted at the same source position.

Use the following complete branch policy. `2/3` means 3 only when the typed payload contains the required target/value and 2 otherwise; `0/3` means 3 only when the natural parser proves an action, domain, and target/value, otherwise 0. A collector must use the listed reason string rather than silently sharing a different rule.

| Reason | Tier | Order | Specificity |
|---|---:|---:|---:|
| calendar_help_keyword | 10 | 10 | 4 |
| status_keyword | 10 | 20 | 4 |
| help_keyword | 10 | 30 | 4 |
| capability_help_natural | 10 | 31 | 2 |
| profile_keyword | 10 | 40 | 4 |
| memory_delete_keyword | 10 | 50 | 4 |
| memory_export_keyword | 10 | 51 | 4 |
| memory_view_keyword | 10 | 52 | 4 |
| reminder_edit_keyword | 20 | 60 | 2/3 |
| reminder_delete_keyword | 20 | 70 | 2/3 |
| reminder_complete_keyword | 20 | 90 | 2/3 |
| active_reminder_numeric_complete | 20 | 91 | 4 |
| active_reminder_complete_number | 20 | 92 | 4 |
| calendar_auth_keyword | 20 | 100 | 4 |
| calendar_sync_keyword | 20 | 110 | 2 |
| calendar_clear_keyword | 20 | 111 | 2/3 |
| calendar_delete_keyword | 20 | 112 | 2/3 |
| calendar_delete_title_match | 20 | 113 | 3 |
| calendar_complete_keyword | 20 | 114 | 2/3 |
| calendar_complete_title_match | 20 | 115 | 3 |
| calendar_edit_keyword | 20 | 116 | 2/3 |
| calendar_edit_natural | 20 | 117 | 3 |
| reminder_search_keyword | 30 | 80 | 3 |
| calendar_search_keyword | 30 | 81 | 3 |
| explicit_web_search_keyword | 30 | 82 | 3 |
| bare_web_search_keyword | 30 | 83 | 3 |
| reminder_list_keyword | 30 | 93 | 2 |
| reminder_list_parser | 30 | 94 | 2 |
| calendar_list_keyword | 30 | 118 | 2 |
| calendar_keyword_default | 30 | 119 | 1 |
| birthday_edit_keyword | 30 | 120 | 2/3 |
| birthday_create_natural | 35 | 121 | 3 |
| reminder_create_natural | 35 | 122 | 3 |
| calendar_create_natural | 35 | 123 | 3 |
| poll_create_natural | 35 | 124 | 3 |
| watchlist_add_natural | 35 | 125 | 3 |
| calendar_nlp_high | 40 | 130 | 0/3 |
| poll_list_keyword | 50 | 140 | 2 |
| poll_parser | 50 | 150 | 0/3 |
| active_poll_vote | 50 | 160 | 4 |
| poll_edit_keyword | 50 | 170 | 2/3 |
| poll_delete_keyword | 50 | 180 | 2/3 |
| poll_close_keyword | 50 | 190 | 2/3 |
| countdown_parser | 50 | 200 | 2/3 |
| watchlist_parser | 50 | 210 | 1/3 |
| word_of_day_keyword | 50 | 220 | 2 |
| quote_list_keyword | 50 | 230 | 2 |
| quote_edit_keyword | 50 | 240 | 2/3 |
| quote_delete_keyword | 50 | 250 | 2/3 |
| quote_parser | 50 | 260 | 1/3 |
| aurora_keyword | 50 | 270 | 1 |
| school_holidays_keyword | 50 | 280 | 1 |
| price_parser | 60 | 290 | 3 |
| horoscope_parser | 60 | 300 | 2/3 |
| compliment_parser | 60 | 310 | 2/3 |
| calculator_parser | 60 | 320 | 3 |
| shorten_parser | 60 | 330 | 3 |
| daily_digest_keyword | 60 | 340 | 2 |
| calendar_nlp | 70 | 350 | 0/3 |
| search_intent | 80 | 360 | 1 |
| information_search_natural | 80 | 361 | 2 |
| dashboard_intent | 80 | 370 | 1 |
| location_pattern | 80 | 380 | 3 |
| fallback | 90 | 390 | 0 |

`reminder_create_parser` becomes `reminder_create_natural` once it has explicit reminder-domain evidence; `reminder_complete_parser` becomes `reminder_complete_keyword` after payload normalization. Calendar NLP emits `calendar_nlp_high` only when its existing confidence is at least 0.94. `poll_parser` uses 3 only with an explicit poll trigger plus parsed question/options and 0 for the legacy slash-only parser shape, allowing an explicit URL-shortening candidate to win. `watchlist_parser` uses specificity 3 for add/edit/remove with a typed title/index and 1 for status/suggestion. `quote_parser` uses 3 for save and 1 for get. The arbiter checks equal `(specificity, tier)` ambiguity before applying `order`; it never compares candidates from different tiers as ambiguous.

- [ ] **Step 1: Write pure arbitration tests**

~~~python
def candidate(intent, risk, priority=100, confidence=0.95):
    return IntentCandidate(
        intent=intent,
        confidence=confidence,
        priority=priority,
        risk=risk,
        action_terms=("slett",),
        domain_terms=("kalender",),
        specificity=2,
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
        utterance,
        analyze_utterance(utterance),
        [candidate(BotIntent.CALENDAR_DELETE, IntentRisk.DESTRUCTIVE)],
    )
    assert decision.selected is None
    assert decision.blocked is True


def test_explicit_domain_action_beats_generic_parser():
    utterance = normalize_utterance("forkort https://example.com/a/b")
    candidates = [
        IntentCandidate(
            BotIntent.POLL_CREATE,
            0.95,
            160,
            reason="poll_parser",
            specificity=0,
        ),
        IntentCandidate(
            BotIntent.SHORTEN_URL,
            0.90,
            220,
            reason="shorten_parser",
            action_terms=("forkort",),
            domain_terms=("https://example.com/a/b",),
            specificity=3,
        ),
    ]
    decision = arbitrate_candidates(
        utterance,
        analyze_utterance(utterance),
        candidates,
    )
    assert decision.selected.intent is BotIntent.SHORTEN_URL
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_intent_arbitration.py -q
~~~

Expected: FAIL because arbitration does not exist.

- [ ] **Step 2: Implement arbitration rules**

arbitrate_candidates() must:

- reject mutation evidence found only inside quoted segments;
- hard-block any negated, meta, or hypothetical mutation instead of falling through to a weaker mutating candidate;
- require both action and domain evidence for destructive deterministic candidates, except a target title proven by the existing calendar lookup;
- allow polite question-form directives such as “kan du slette kalenderen?”;
- preserve “ikke glem” positive reminder/calendar idioms;
- sort candidates ascending by (-specificity, priority, order, -confidence, intent.value), where larger specificity wins, smaller priority wins, smaller source order preserves the current branch sequence, and larger confidence wins;
- return CLARIFY when the two leading candidates have different intents/domains, identical specificity and priority tiers, and an absolute confidence difference at most 0.05; collectors intentionally assign the same tier only to equally explicit competing domain interpretations;
- return AI_CHAT when no candidate remains;
- set requires_confirmation for every destructive result;
- set requires_confirmation for semantic additive/mutating results;
- isolate collector exceptions as RejectionCode.PARSER_ERROR and expose an aggregate parser-error counter without raw text or exception strings.

- [ ] **Step 3a: Add collector scaffolding and compatible route wrappers**

Add:

~~~python
@dataclass(frozen=True, slots=True)
class CollectorContext:
    utterance: NormalizedUtterance
    semantics: UtteranceSemantics
    routing: RoutingContext | None
    guild_id: int | None
    reference_time: datetime


COLLECTOR_ORDER = (
    "_collect_control_candidates",
    "_collect_calendar_reminder_candidates",
    "_collect_poll_watchlist_quote_candidates",
    "_collect_utility_candidates",
    "_collect_fallback_candidates",
)
~~~

Each named method has signature (self, context: CollectorContext) -> list[IntentCandidate] and is added with its real branches in Steps 3b–3d; do not add empty stubs. Keep `route(content, guild_id=None, *, channel_id=None, user_id=None, routing_context=None, reference_time=None)` as a compatibility wrapper. Add `route_utterance(..., reference_time=None)` and `evaluate_utterance(..., reference_time=None) -> RoutedIntent`. At the public entry, use the supplied aware `reference_time` or capture exactly one value from the injected shared clock, validate it, and put it on `CollectorContext`; every temporal parser and active-state read consumes that exact value. When `routing_context` exists, derive identity from its key and reject mismatched scalar ids as `invalid_context`. Add wrapper-only and Oslo-midnight boundary tests before moving any branch.

- [ ] **Step 3b: Migrate control, memory, calendar, and reminder branches**

Move calendar-help/status/help/profile/memory/auth/reminder/calendar/birthday branches into the first two collectors without changing reason strings or outer payloads. Feed control_text to evidence checks and text to payload parsers. Preserve the calendar confidence >=0.94 early tier and lower-confidence late tier. Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_intent_router.py \
  tests/test_user_memory_controls.py \
  tests/test_calendar_edit.py \
  tests/test_reminder_crud.py -q
~~~

- [ ] **Step 3c: Migrate poll, watchlist, quote, and countdown branches**

Move poll list/create/vote/edit/delete/close, countdown, watchlist, word-of-day, and quote branches. Keep collectors pure and isolate each parser exception as RejectionCode.PARSER_ERROR. Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_poll_target.py \
  tests/test_poll_manager_edit_delete.py \
  tests/test_watchlist_scope.py \
  tests/test_quote_crud.py -q
~~~

- [ ] **Step 3d: Migrate utility, search, dashboard, and location branches**

Move aurora/school-holidays/price/horoscope/compliment/calculator/URL/digest/search/dashboard/location branches. Apply the table’s tiers and preserve current confidence thresholds. A collector may inspect active state but must not mutate a manager. Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_search_intent.py \
  tests/test_search_manager.py \
  tests/test_url_shortener_security.py \
  tests/test_intent_router.py -q
~~~

- [ ] **Step 3e: Arbitrate once and delete the old cascade**

evaluate_utterance() invokes the five collectors, combines candidates and bounded diagnostics, arbitrates once, and returns RoutedIntent. route_utterance() returns only .result. Delete the old early-return cascade only after every family suite above is green. Include rejection enum counts in diagnostics, never user copy or exception text. Do not consult pending actions until Task 9.

- [ ] **Step 4: Add bounded natural collector evidence**

Before pinning the regressions, update collectors to emit:

- CALENDAR_EDIT for polite edit/change verbs plus calendar-item evidence, using TemporalResolver for the change fields;
- REMINDER_CREATE for “påminn/minn meg” request frames, with the reminder text retained even before Task 7 adds full timing semantics;
- HELP for “kva/ka/what can you do” capability questions;
- SHORTEN_URL with high specificity when an explicit shorten verb and a valid URL are both present;
- SEARCH for information questions such as train departure times, while rejecting the competing calendar mutation candidate.
- AI_CHAT for the context-free conversational “hva skjer?” instead of the generic dashboard keyword.

These are narrow collector additions backed by the exact tests below; broader reminder timing and help/feature registry parity remain in Tasks 7 and 12.

- [ ] **Step 5: Pin known regressions at router level**

~~~python
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
def test_natural_language_routing_regressions(text, expected):
    assert self.route(text).intent is expected
~~~

At this task boundary, assert the corrected intent and that no handler was invoked; Task 6 pins the complete CALENDAR_EDIT target/change payload, and Task 7 pins the REMINDER_CREATE title and canonical due time.

- [ ] **Step 6: Extend and run the NLU contract**

Append the exact cases from Step 5 plus adjacent negatives in Bokmål, Nynorsk, Trøndelag-adjacent forms, and English. Include the URL case removed from Task 1 because the current production poll parser steals it:

- “forkort https://example.com” -> SHORTEN_URL, never POLL_CREATE;

- “Kva meiner du om RBK i morgon?”;
- “Ka trur du skjer i morra?”;
- “Æ ska bare høre ka du tænke om kampen i morra”;
- “Could you delete reminder 1?”;
- “Do not delete reminder 1”.

Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_intent_arbitration.py \
  tests/test_intent_router.py \
  tests/test_false_positives.py \
  tests/test_confidence_thresholds.py \
  tests/test_nlu_contract.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
~~~

Expected: PASS and zero negative mutation false positives.

- [ ] **Step 7: Commit**

~~~bash
git add core/intent_arbitration.py core/intent_router.py \
  tests/test_intent_arbitration.py tests/test_intent_router.py \
  tests/test_false_positives.py tests/fixtures/nlu_contract_v1.jsonl
git commit -m "feat: arbitrate natural-language intent candidates"
~~~

---

### Task 6: Parse action payloads once and make dispatch outcomes explicit

**Objective:** Stop handlers from reinterpreting raw user text after the router has already selected an intent, and give pending actions a reliable success/failure signal.

**Interfaces:**

- Consumes: validated dictionaries produced by deterministic collectors or the future AI action bridge.
- Produces: stable TypedDict payload shapes and DispatchOutcome.
- Compatibility: the outer IntentResult.payload remains a dictionary with current top-level keys.

**Files:**

- Create: core/intent_payloads.py
- Create: core/dispatch_result.py
- Create: tests/test_parse_once_dispatch.py
- Modify: core/intent_router.py:245-729
- Modify: core/message_monitor.py:510-644
- Modify: features/calendar_handler.py:225-705
- Modify: features/reminder_handler.py:123-285
- Modify: features/polls_handler.py
- Modify: features/watchlist_handler.py
- Modify: features/watchlist_manager.py:409-530
- Modify: features/quote_handler.py
- Modify: features/quote_manager.py:210-285
- Modify: features/fun_handler.py
- Modify: features/birthday_handler.py:19-91
- Modify: tests/test_message_monitor_routing.py
- Modify: tests/test_calendar_edit.py
- Modify: tests/test_reminder_crud.py
- Modify: tests/test_poll_target.py
- Modify: tests/test_watchlist_birthday_edit.py
- Modify: tests/test_quote_crud.py

- [ ] **Step 1: Write parse-once dispatch tests**

Use handlers whose raw parser methods raise if called:

~~~python
@pytest.mark.asyncio
async def test_calendar_edit_dispatch_uses_routed_payload(monitor, message):
    monitor.handlers["calendar"].handle_edit = AsyncMock(
        return_value=DispatchOutcome.success(mutated=True)
    )
    monitor.handlers["calendar"]._parse_edit_command = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    route = IntentResult(
        BotIntent.CALENDAR_EDIT,
        0.98,
        {
            "calendar_edit": {
                "target": "møte med Ola",
                "changes": {"date": "17.07.2026", "time": "10:00"},
            }
        },
        "calendar_edit_natural",
        risk=IntentRisk.MUTATING,
    )
    outcome = await monitor._handle_intent(
        message,
        route,
        reference_time=FIXED_NOW,
    )
    assert outcome.ok is True
    monitor.handlers["calendar"].handle_edit.assert_awaited_once_with(
        message,
        route.payload["calendar_edit"],
        reference_time=FIXED_NOW,
    )


@pytest.mark.asyncio
async def test_handler_failure_is_visible_to_dispatch(monitor, message):
    monitor.handlers["reminders"].handle_reminder_delete = AsyncMock(
        return_value=DispatchOutcome.failure(
            "not_found",
            retryable=True,
        )
    )
    route = IntentResult(
        BotIntent.REMINDER_DELETE,
        0.98,
        {"reminder": {"action": "delete", "number": 1}},
        "reminder_delete_keyword",
        risk=IntentRisk.DESTRUCTIVE,
    )
    outcome = await monitor._handle_intent(
        message,
        route,
        reference_time=FIXED_NOW,
    )
    assert outcome.ok is False
    assert outcome.mutated is False


@pytest.mark.asyncio
async def test_real_calendar_handler_does_not_reparse_typed_edit(
    monitor,
    message,
):
    handler = CalendarHandler(monitor)
    handler._parse_edit_command = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    handler.calendar.snapshot_pending_items = Mock(
        return_value=(
            {
                "id": "calendar-42",
                "title": "Opprinnelig møte",
                "date": "16.07.2026",
                "time": "09:00",
                "type": "event",
                "description": "",
                "completed": False,
                "recurrence": None,
            },
        )
    )
    handler.calendar.edit_item_result = AsyncMock(
        return_value={
            "id": "calendar-42",
            "title": "Opprinnelig møte",
            "date": "17.07.2026",
            "time": "10:00",
        }
    )
    handler.send_response_result = AsyncMock(
        return_value=MessageSendResult(DeliveryState.DELIVERED)
    )
    outcome = await handler.handle_edit(
        message,
        {
            "target": "1",
            "changes": {"date": "17.07.2026", "time": "10:00"},
        },
        reference_time=FIXED_NOW,
    )
    assert outcome.mutated is True
    handler.calendar.edit_item_result.assert_awaited_once_with(
        item_id="calendar-42",
        reference_time=FIXED_NOW,
        date="17.07.2026",
        time="10:00",
    )
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py -q
~~~

Expected: FAIL because DispatchOutcome and typed dispatch do not exist.

Add equivalent real-handler tests for reminder edit/delete (_parse_edit_command and extract_number must not run), watchlist add/edit/remove (message.content is an unrelated sentinel while the manager receives title/index/genre/comment from payload), birthday edit (_parse_birthday_edit must not run), and poll mutation (the manager receives only poll payload). Pin quote editing with this real-manager test so both edit values, not just the index, are proven independent of raw content:

~~~python
@pytest.mark.asyncio
async def test_quote_edit_uses_typed_text_and_author_with_sentinel_content(
    quote_handler,
    message,
):
    seeded = await quote_handler.quote.add_quote_result(
        "123", "Gammel", "Ola"
    )
    assert seeded.success is True
    message.content = "SENTINEL RAW CONTENT THAT MUST NOT BE PARSED"
    quote_handler.extract_number = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    quote_handler._extract_edit_fields_from_content = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    outcome = await quote_handler.handle_quote_edit(
        message,
        {
            "action": "edit",
            "index": 1,
            "text": "Ny tekst",
            "author": "Kari",
            "lang": "no",
        },
    )
    assert outcome.ok is True
    assert outcome.mutated is True
    stored = quote_handler.quote.list_quotes("123")[0]
    assert stored["text"] == "Ny tekst"
    assert stored["author"] == "Kari"
~~~

The monitor-level AsyncMock test proves envelope dispatch; the real-handler tests prove no hidden reparse.

- [ ] **Step 2: Define exact required and optional payload fields**

Add these TypedDict contracts in core/intent_payloads.py:

~~~python
class CalendarCreatePayload(TypedDict):
    title: str
    date: NotRequired[str]
    time: NotRequired[str]
    type: NotRequired[Literal["event", "task"]]
    recurrence: NotRequired[str]
    recurrence_day: NotRequired[str]
    rrule_day: NotRequired[str]
    days_offset: NotRequired[int | None]
    description: NotRequired[str]


class CalendarChanges(TypedDict, total=False):
    title: str
    description: str
    date: str
    time: str
    recurrence: str | None


class CalendarTargetPayload(TypedDict, total=False):
    target: str
    number: int
    all: bool


class CalendarEditPayload(TypedDict):
    target: str
    changes: CalendarChanges


class ReminderCreatePayload(TypedDict):
    action: Literal["add"]
    text: str
    due_at: NotRequired[str]
    due_date: NotRequired[str]
    time: NotRequired[str]
    timezone: NotRequired[str]
    recurrence: NotRequired[str]


class ReminderTargetPayload(TypedDict):
    action: Literal["list", "search", "complete", "delete"]
    number: NotRequired[int]
    reminder_id: NotRequired[str]
    query: NotRequired[str]


class ReminderChanges(TypedDict, total=False):
    text: str
    due_at: str | None
    due_date: str | None
    time: str | None
    timezone: str
    recurrence: str | None


class ReminderEditPayload(TypedDict):
    action: Literal["edit"]
    number: NotRequired[int]
    reminder_id: NotRequired[str]
    changes: ReminderChanges


class PollCreatePayload(TypedDict):
    question: str
    options: list[str]
    lang: NotRequired[Literal["no", "en"]]


class PollTargetPayload(TypedDict, total=False):
    target: int | Literal["siste"] | None
    poll_id: NotRequired[str]


class PollEditPayload(TypedDict, total=False):
    target: int | Literal["siste"] | None
    poll_id: str
    question: NotRequired[str]
    options: NotRequired[list[str]]


class PollVotePayload(TypedDict):
    option: int
    poll_id: NotRequired[str]


class BirthdayCreatePayload(TypedDict):
    action: Literal["add"]
    user_id: int
    display_name: str
    day: int
    month: int
    year: NotRequired[int]


class BirthdayEditPayload(TypedDict):
    action: Literal["edit"]
    user_id: int
    day: int
    month: int
    year: NotRequired[int]


class BirthdayListPayload(TypedDict):
    action: Literal["list"]
    scope: NotRequired[Literal["all", "upcoming"]]


class WatchlistPayload(TypedDict):
    action: Literal["add", "status", "suggest", "edit", "remove"]
    title: NotRequired[str]
    type: NotRequired[Literal["movie", "series"] | None]
    index: NotRequired[int]
    genre: NotRequired[str | None]
    comment: NotRequired[str | None]
    lang: NotRequired[Literal["no", "en"]]


class QuotePayload(TypedDict):
    action: Literal["save", "get", "list", "edit", "delete"]
    index: NotRequired[int]
    text: NotRequired[str]
    author: NotRequired[str]
    lang: NotRequired[Literal["no", "en"]]
~~~

- [ ] **Step 3: Implement payload validation**

Add `PayloadValidationError(code: str)` and `validate_intent_payload(intent: BotIntent, raw: Mapping[str, Any], *, source: IntentSource = IntentSource.DETERMINISTIC) -> dict[str, Any]`. The function consumes and returns only the inner object at `ENVELOPE_KEYS[intent]`; `MessageMonitor` and `ActionBridge` preserve the outer envelope and replace only that mapped inner value. The validator must:

- reject unknown keys for semantic proposals;
- require target identity for edits/deletes;
- require at least two nonblank poll options;
- enforce maximum lengths already used by the managers;
- call TemporalResolver for calendar/reminder dates and times;
- return a normalized dict without mutating the input.

Pin target rules in tests: CalendarTargetPayload requires exactly one identifier; PollTargetPayload accepts int, “siste”, or None only when one active poll can be resolved; CalendarEditPayload requires at least one nonblank change; ReminderTargetPayload requires number/id for complete/delete and query for search; Quote delete requires a positive one-based index, while Quote edit requires that index plus at least one nonblank `text` or `author`; Watchlist/Quote required fields otherwise depend on action.

- [ ] **Step 4: Define dispatch outcomes**

`core/dispatch_result.py` uses the exact shared contract in the typed-dispatch sub-plan; do not recreate a smaller master-plan dataclass. It defines `DeliveryState(DELIVERED|NOT_DELIVERED|UNKNOWN)`, the finite `SEND_ERROR_CODES`, immutable `MessageSendResult`, `MessageSendCancelled(result)`, and `DispatchOutcome(ok, mutated, response_sent, retryable, error_code, commit_unknown, delivery_result)`. `DispatchOutcome.success()` starts with `response_sent=False`; every typed handler builds mutation/error truth first and finalizes exactly once with `base.with_delivery(send_result)`. That method alone derives `response_sent`, retains definite failure versus uncertainty, and makes `UNKNOWN` non-retryable. `DispatchCancelled` carries the fully finalized outcome when cancellation arrives after an owned send or mutation. Add construction/invariant tests from the typed sub-plan before any handler migration; no code may infer delivery from truthiness, `None`, or a global send count.

- [ ] **Step 5: Populate complete routed payloads**

Update collectors so:

- calendar edit carries target plus normalized changes;
- calendar delete/complete/clear carries a target/number or an explicit all flag;
- reminder create carries parsed text and temporal fields;
- reminder edit/delete/complete carries number or id;
- poll edit/delete/close/vote carries a positional target or stable poll ID, and vote carries its option inside the typed object;
- birthday create/edit carries resolved Discord identity plus canonical date;
- watchlist and quote operations carry their parser result.

Use one canonical outer envelope table:

| Intent family | IntentResult.payload key | Handler receives |
|---|---|---|
| CALENDAR_ITEM | calendar_item | inner CalendarCreatePayload |
| CALENDAR_EDIT | calendar_edit | inner CalendarEditPayload |
| calendar delete/complete/clear | calendar_target | inner CalendarTargetPayload |
| every REMINDER_* | reminder | inner reminder payload whose action matches the intent |
| POLL_CREATE | poll | inner PollCreatePayload |
| POLL_VOTE | vote | PollVotePayload |
| POLL_EDIT | poll_edit | PollEditPayload |
| POLL_DELETE / POLL_CLOSE | poll_delete / poll_close | PollTargetPayload |
| every BIRTHDAY_* | birthday | inner birthday payload |
| WATCHLIST | watchlist | inner WatchlistPayload |
| every QUOTE* | quote | inner QuotePayload |

MessageMonitor owns envelope unwrapping and passes only the inner typed dictionary to handlers. Existing envelope keys already used by callers remain unchanged; routes that previously had an empty payload gain the family key. Compatibility raw fallbacks receive the full original message separately and are never mixed into the typed dictionary.

Original text may be included only as non-authoritative display context. Handlers must not call parse_* when a typed payload is present.

- [ ] **Step 6a: Migrate calendar mutation handlers**

Change handle_calendar_item(), handle_edit(), handle_delete(), handle_complete(), and handle_clear() to accept the corresponding inner payload and return DispatchOutcome. Mark mutated immediately after CalendarManager success and before response send. Run tests/test_calendar_edit.py plus the real-handler no-reparse case.

- [ ] **Step 6b: Migrate reminder mutation handlers**

Change reminder create/edit/delete/complete to accept ReminderCreate/ReminderEdit/ReminderTarget payloads. At this task boundary map ReminderChanges.text to current ReminderManager.edit_reminder(title=...), due_date to date=..., and pass time/recurrence unchanged. Reject due_at/timezone with unsupported_temporal_field until Task 7 extends the manager; add a test for both the mapping and rejection. Remove typed-path calls to parse_reminder_command(), _parse_edit_command(), and extract_number(). Return retryable only for proven pre-write validation/not-found failures. Run tests/test_reminder_crud.py.

- [ ] **Step 6c: Migrate poll, watchlist, quote, and birthday handlers**

Migrate poll edit/delete/close/vote, watchlist add/edit/remove, quote save/edit/delete, and birthday create/list/edit to their exact payload types. Birthday typed writes consume all five fields of `BirthdayWriteResult(success, mutated, sync_pending, error_code, commit_unknown)` from transactional user-ID manager APIs; retain the legacy bool-returning create and dict-returning name-edit wrappers. Extend parse_watchlist_command() to emit add title and edit index/title/type/genre/comment. Extend parse_quote_command() so `rediger|endre|edit sitat|quote <index> tekst|text: ... forfatter|author: ...` emits `{"action":"edit","index":<positive int>,"text":<optional nonblank>,"author":<optional nonblank>,"lang":...}` and delete syntax emits `{"action":"delete","index":<positive int>,"lang":...}`. Reject an edit lacking both text and author before routing. The collector must put this complete object under `payload["quote"]`; it must not discard fields when converting to QUOTE_EDIT/QUOTE_DELETE. BotIntent.QUOTE save runs through FunHandler.handle_quote_command(), so migrate that method to DispatchOutcome as well as QuoteHandler edit/delete. Run the poll/watchlist/quote/birthday focused suites, including the sentinel-content test from Step 1.

- [ ] **Step 6d: Add the one-release raw compatibility branch**

Only when the canonical envelope key is absent, allow the current raw parser, increment legacy_payload_fallback through NLUMetrics, and immediately validate its output into the canonical payload. Never merge raw fields with a present typed payload. Add one fallback test and one “typed payload wins over contradictory raw content” test per handler family.

- [ ] **Step 6e: Return DispatchOutcome from MessageMonitor**

Immediately after the existing router construction, set `self.nlu_metrics = self.intent_router.metrics` so compatibility handlers share the routing lane's already-created bounded sink; do not construct a second sink. The later model-actions task moves the sole production construction ahead of all consumers and injects it back into the router. Change MessageMonitor._handle_intent() to unwrap the envelope table and return DispatchOutcome for every branch. Read-only handlers return ok when their send succeeds. Unknown/malformed payloads return invalid_payload and make zero manager calls. A handler exception whose commit state cannot be classified returns terminal `commit_state_unknown` with `commit_unknown=True`; it never claims `mutated=False` as proof.

- [ ] **Step 7: Run focused integration tests**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_parse_once_dispatch.py \
  tests/test_message_monitor_routing.py \
  tests/test_calendar_edit.py \
  tests/test_reminder_crud.py \
  tests/test_poll_target.py \
  tests/test_watchlist_birthday_edit.py \
  tests/test_quote_crud.py -q
~~~

Expected: PASS with zero raw reparses on typed routes.

- [ ] **Step 8: Commit**

~~~bash
git add core/intent_payloads.py core/dispatch_result.py core/intent_router.py \
  core/message_monitor.py features/calendar_handler.py \
  features/reminder_handler.py features/polls_handler.py \
  features/watchlist_handler.py features/watchlist_manager.py \
  features/quote_handler.py features/quote_manager.py features/fun_handler.py \
  features/birthday_handler.py tests/test_parse_once_dispatch.py \
  tests/test_message_monitor_routing.py tests/test_calendar_edit.py \
  tests/test_reminder_crud.py tests/test_poll_target.py \
  tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py
git commit -m "refactor: dispatch validated intent payloads once"
~~~

---

### Task 7: Unify reminder ownership, timing, and delivery semantics

**Objective:** Make natural reminder requests create one canonical reminder that the running checker actually sees and delivers at the requested Oslo time.

**Interfaces:**

- Consumes: ReminderCreatePayload and TemporalResolver.
- Produces: backward-compatible reminder records with `due_at`, one manager/checker owner, the shared `MessageSendResult` tri-state delivery contract, and aggregate checker health.
- Persistence rule: tolerate legacy records; enrich on the next explicit write, not on startup.

**Files:**

- Create: cal_system/reminder_clock.py
- Create: tests/test_reminder_runtime.py
- Modify: cal_system/reminder_manager.py:16-115,275-345,436-528
- Modify: cal_system/reminder_checker.py:25-535
- Modify: features/reminder_handler.py:20-285
- Modify: core/message_monitor.py:134-171,333-341,1000-1011,1283-1352,1379-1418
- Modify: web_console/state_collector.py:127-260,629-638
- Modify: tests/test_reminder_crud.py
- Modify: tests/test_gcal_reminder_routing.py
- Modify: tests/test_message_monitor_routing.py
- Modify: tests/test_console_server.py

- [ ] **Step 1: Write ownership and reconnect tests**

~~~python
@pytest.mark.asyncio
async def test_monitor_owns_one_reminder_runtime(monitor):
    await monitor.setup()
    first_manager = monitor.reminders
    first_checker = monitor.reminder_checker
    first_task = monitor.reminder_checker_task
    await monitor.setup()
    assert monitor.reminders is first_manager
    assert monitor.reminder_checker is first_checker
    assert monitor.reminder_checker.reminders is first_manager
    assert monitor.reminder_checker_task is first_task


@pytest.mark.asyncio
async def test_reconnect_does_not_replace_monitor(client):
    first = await client._ensure_runtime_started()
    second = await client._ensure_runtime_started()
    assert first is second
    assert first.reminder_checker_task is second.reminder_checker_task
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py -q
~~~

Expected: FAIL because the current client creates a second ReminderManager and checker.

- [ ] **Step 2: Make MessageMonitor the sole runtime owner**

- Initialize ReminderManager once in MessageMonitor.
- Add idempotent _start_reminder_checker(), setup(), and close().
- Make SelfbotClient._ensure_runtime_started() retain the monitor across repeated on_ready calls.
- Remove SelfbotClient._create_reminder_checker(), duplicate checker fields, and duplicate teardown.
- Preserve console attachment and uptime state across reconnect.
- Start the first checker cycle immediately; sleep only after check_once().

Add focused lifecycle assertions that duplicate setup creates no extra console-persistence, initial-GCal, or reminder tasks; repeated close is safe and awaits/cancels every owned task; console attachment and uptime survive reconnect. Build these tests with monkeypatched manager/checker factories and temporary storage paths so they never initialize Hermes home data or Google Calendar.

- [ ] **Step 3: Inject one clock into the entire reminder runtime**

Add to cal_system/reminder_clock.py:

~~~python
class ReminderClock(Protocol):
    def now(self) -> datetime:
        raise NotImplementedError

    def epoch(self) -> float:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SystemReminderClock:
    timezone: ZoneInfo = ZoneInfo("Europe/Oslo")

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def epoch(self) -> float:
        return self.now().timestamp()
~~~

Inject the same clock into ReminderManager, ReminderChecker, parsing, sent-log pruning/deduplication, digest-date calculation, recurrence advancement, and health timestamps. Replace direct datetime.now() and time.time() calls in those paths. Tests use a MutableReminderClock with advance(timedelta).

- [ ] **Step 4: Add canonical temporal fields**

Extend ReminderManager.add_reminder() and edit_reminder() with:

~~~python
due_at: str | None = None
due_date: str | None = None
time: str | None = None
timezone: str = "Europe/Oslo"
recurrence: str | None = None
~~~

Record rules:

- due_at is an aware ISO-8601 value with Oslo offset;
- due_date and time remain as display/backward-compatibility fields;
- an undated reminder is checklist-only;
- date-only reminders use 09:00 Europe/Oslo;
- yearless dates resolve to the next occurrence;
- missing legacy time defaults to 09:00 only when a due_date exists;
- malformed legacy values are skipped and counted, never rewritten silently.
- a valid due_at is authoritative when legacy due_date/time disagree; count legacy_due_mismatch and derive display values from due_at on the next explicit edit;
- every edit to due_date/time/timezone and every recurrence advancement recomputes due_at;
- recurrence advances in ZoneInfo("Europe/Oslo"), preserving wall-clock time across DST offset changes.

- [ ] **Step 5: Consume and verify the routing-owned reminder parser**

The routing-foundation lane already owns the stable pure `parse_reminder_command(message_content, *, now=None, temporal_resolver=None)` rewrite. Do not rewrite it or rename its keywords here. Inject the turn-captured `reference_time` as `now` and the monitor-owned resolver, then verify it recognizes:

- påminn meg, minn meg, påminnelse, påminning, hugs, husk å, reminder;
- om N minutter/timer/dager/uker;
- i morgen, i morgon, imårra;
- kl, kl., klokken, klokka, and English at;
- date plus time and date-only forms;
- checklist-only requests without a time;
- daily/daglig recurrence.

The parser already uses `TemporalResolver`, excludes watchlist media frames, and strips matched temporal text from the reminder title. This runtime task adds manager/checker integration and the following end-to-end pin only:

~~~python
def test_relative_reminder_has_aware_due_at():
    now = datetime(
        2026,
        7,
        14,
        12,
        0,
        tzinfo=ZoneInfo("Europe/Oslo"),
    )
    parsed = parse_reminder_command(
        "påminn meg om å ringe legen om 2 timer",
        now=now,
    )
    assert parsed["action"] == "add"
    assert parsed["text"] == "ringe legen"
    assert parsed["due_date"] == "14.07.2026"
    assert parsed["time"] == "14:00"
    assert parsed["due_at"] == "2026-07-14T14:00:00+02:00"
~~~

- [ ] **Step 6: Make delivery acknowledgement truthful**

- `_send_to_channel()`, `_send_mentions_item()`, `_send_item_reminder()`, and `_send_reminder_remind()` return and propagate the shared immutable `MessageSendResult`.
- Mark `SENT` only after `DeliveryState.DELIVERED`; a definite pre-dispatch `NOT_DELIVERED` may retry, while `UNKNOWN` is persisted/in-memory-suppressed and never replayed blindly.
- `check_morning_digest()` settles its date key by the same tri-state rule.
- A missing channel or proven pre-dispatch rejection is `NOT_DELIVERED`; HTTP/timeout/transport failures after an attempt begins are `UNKNOWN`. Each increments only a finite aggregate error code.
- check_once() records last_check_at, last_success_at, consecutive_errors, cycles, delivery_failures, skipped_missing_channel, and malformed_legacy_due_at.
- get_health() returns status starting, ok, degraded, or stopped without raw reminder content.
- Use a documented ten-minute missed-cycle catch-up window and pin its boundary with a fixed clock.

- [ ] **Step 7: Make alert windows mutually exclusive**

Apply the same rules to CalendarManager items and ReminderManager records. For delta = canonical occurrence time - now:

- send the optional 30-minute warning only when 25 minutes < delta <= 35 minutes;
- send the due notification only when -10 minutes <= delta <= 1 minute;
- when delta < -10 minutes, count missed_outside_catchup and do not send;
- never emit a separate “passed” notification;
- sent keys include source kind, item/reminder id, canonical occurrence timestamp, and alert kind.

Add fixed-clock boundary tests at 35:00, 25:00, 1:00, 0:00, -10:00, and -10:01, and prove one check cycle emits at most one alert per reminder occurrence.

- [ ] **Step 8: Show real reminders and bounded health**

Replace the hard-coded reminders=[] in MessageMonitor._generate_dashboard() with the active reminders from the same self.reminders instance. Add a test proving a newly created reminder appears without restarting or reloading a second manager.

Expose only status, running, stale, and last_success_at through the existing public /health projection. Keep delivery counts, error buckets, and other detailed reminder runtime fields for authenticated /api/status in Task 13. Never expose reminder content or raw last_error.

- [ ] **Step 9: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_reminder_runtime.py \
  tests/test_reminder_crud.py \
  tests/test_gcal_reminder_routing.py \
  tests/test_message_monitor_routing.py \
  tests/test_console_server.py -q
git add cal_system/reminder_manager.py cal_system/reminder_checker.py \
  cal_system/reminder_clock.py features/reminder_handler.py core/message_monitor.py \
  web_console/state_collector.py tests/test_reminder_runtime.py \
  tests/test_reminder_crud.py tests/test_gcal_reminder_routing.py \
  tests/test_message_monitor_routing.py tests/test_console_server.py
git commit -m "fix: unify natural reminder runtime semantics"
~~~

Expected: PASS with one runtime owner and delivery marked only after success.

---

### Task 8: Replace ad hoc model tags with one strict action proposal contract

**Objective:** Let the AI recognize paraphrases without giving model output a direct mutation path.

**Interfaces:**

- Consumes: one model response string.
- Produces: visible text plus zero or one validated ActionProposal.
- Does not execute: managers, handlers, Discord sends, dashboard sends, or persistence.

**Files:**

- Create: core/action_bridge.py
- Create: tests/test_action_bridge.py
- Create: tests/test_provider_prompt_contract.py
- Create: tests/test_ai_connectors.py
- Modify: ai/action_schema.py:1-19
- Modify: ai/personality_config.py:53-151
- Modify: ai/openrouter_connector.py:221-290
- Modify: ai/hermes_connector.py:243-330
- Modify: ai/hermes_bridge_server.py:242-304,480-577,723-773
- Modify: ai/response_cleaner.py:1-95
- Modify: tests/test_action_schema.py

- [ ] **Step 1: Write strict parser tests**

~~~python
def test_parse_one_standalone_action_line():
    parsed = parse_ai_response(
        "Det kan jeg hjelpe med.\n"
        '{"action":"REMINDER_CREATE","confidence":0.91,'
        '"slots":{"text":"ringe legen","due_at":"2026-07-15T09:00:00+02:00"},'
        '"reply":"","clarification":null}'
    )
    assert parsed.text == "Det kan jeg hjelpe med."
    assert parsed.proposal.action is ActionName.REMINDER_CREATE
    assert parsed.proposal.slots["text"] == "ringe legen"
    assert parsed.errors == ()


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"UNKNOWN","confidence":0.9,"slots":{}}',
        '{"action":"CALENDAR_DELETE","confidence":1.4,"slots":{"target":"1"}}',
        '{"action":"CALENDAR_CREATE","confidence":0.9,"slots":{"title":""}}',
        '{"action":"CALENDAR_DELETE","confidence":1,"slots":{"target":"1"}}\n'
        '{"action":"REMINDER_DELETE","confidence":1,"slots":{"number":1}}',
    ],
)
def test_invalid_or_ambiguous_action_is_never_proposed(raw):
    parsed = parse_ai_response(raw)
    assert parsed.proposal is None
    assert parsed.errors


def test_fenced_json_is_inert_visible_text():
    raw = (
        "~~~json\n"
        '{"action":"CALENDAR_DELETE","confidence":1,"slots":{"target":"1"}}\n'
        "~~~"
    )
    parsed = parse_ai_response(raw)
    assert parsed.text == raw
    assert parsed.proposal is None
    assert parsed.errors == ()
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_action_schema.py -q
~~~

Expected: FAIL because the existing action_schema contains only unused mutable dataclasses.

- [ ] **Step 2: Define a bounded action registry**

ActionName must contain:

- NONE and CLARIFY;
- SHOW_DASHBOARD and HELP;
- CALENDAR_CREATE, CALENDAR_LIST, CALENDAR_SEARCH, CALENDAR_COMPLETE, CALENDAR_EDIT, CALENDAR_DELETE, CALENDAR_CLEAR;
- REMINDER_CREATE, REMINDER_LIST, REMINDER_SEARCH, REMINDER_COMPLETE, REMINDER_EDIT, REMINDER_DELETE;
- POLL_CREATE, POLL_LIST, POLL_VOTE, POLL_EDIT, POLL_DELETE, POLL_CLOSE;
- BIRTHDAY_CREATE, BIRTHDAY_LIST, BIRTHDAY_EDIT;
- WATCHLIST_ADD, WATCHLIST_LIST, WATCHLIST_SUGGEST, WATCHLIST_EDIT, WATCHLIST_REMOVE;
- QUOTE_SAVE, QUOTE_GET, QUOTE_LIST, QUOTE_EDIT, QUOTE_DELETE.

Use these exact validation atoms: `S200` is a stripped string of 1–200 characters; `S300` is 1–300; `S500` is 1–500; `TEXT2000` is 1–2000; `POS_INT` is an integer greater than zero and explicitly rejects bool; `DATE` is an exact canonical `DD.MM.YYYY` string whose calendar date exists; `TIME` is an exact canonical `HH:MM` string in `00:00`–`23:59`; `DAY_OFFSET` is a non-bool integer in `-3650..3650`; `DUE_AT` is an aware ISO-8601 datetime; `POLL_TARGET` is `POS_INT | "siste"`; `OPTIONS` is a list of 2–10 unique stripped strings, each 1–100 characters; and `YEAR` is 1900–2100. `timezone`, when present, is exactly `Europe/Oslo`. Optional strings may not be blank. Cross-field wall-time/DST validation belongs to the shared `TemporalResolver` at the bridge boundary with the captured reference time. `ACTION_SPECS` is the following closed registry; “one of” means exactly one listed alternative, and “at least one” is checked after scalar validation.

| ActionName | Required slots | Optional slots | Cross-field rule |
|---|---|---|---|
| NONE | none | none | clarification is null/blank |
| CLARIFY | none | none | top-level clarification is S500 |
| SHOW_DASHBOARD | none | none | none |
| HELP | none | none | none |
| CALENDAR_CREATE | title:S200 | date:DATE, time:TIME, type:event\|task, recurrence:S200, recurrence_day:S200, rrule_day:S200, days_offset:DAY_OFFSET, description:TEXT2000 | at least one of date/days_offset; bridge converts days_offset to one absolute date from the captured Oslo reference and rejects disagreement with a supplied date |
| CALENDAR_LIST | none | none | none |
| CALENDAR_SEARCH | query:S500 | none | none |
| CALENDAR_COMPLETE | none | target:S200, number:POS_INT | exactly one target or number |
| CALENDAR_EDIT | target:S200 | title:S200, description:TEXT2000, date:DATE, time:TIME, recurrence:S200-or-null | at least one optional change |
| CALENDAR_DELETE | none | target:S200, number:POS_INT | exactly one target or number |
| CALENDAR_CLEAR | none | none | bridge supplies all=true |
| REMINDER_CREATE | text:S500 | due_at:DUE_AT, due_date:DATE, time:TIME, timezone:Europe/Oslo, recurrence:S200 | TemporalResolver canonicalizes one consistent due time |
| REMINDER_LIST | none | none | none |
| REMINDER_SEARCH | query:S500 | none | none |
| REMINDER_COMPLETE | number:POS_INT | none | resolver later injects internal reminder_id |
| REMINDER_EDIT | number:POS_INT | text:S500, due_at:DUE_AT-or-null, due_date:DATE-or-null, time:TIME-or-null, timezone:Europe/Oslo, recurrence:S200-or-null | at least one change; temporal fields agree |
| REMINDER_DELETE | number:POS_INT | none | resolver later injects internal reminder_id |
| POLL_CREATE | question:S300, options:OPTIONS | none | none |
| POLL_LIST | none | none | none |
| POLL_VOTE | option:POS_INT | none | exactly one active poll must exist in bounded routing state |
| POLL_EDIT | none | target:POLL_TARGET, question:S300, options:OPTIONS | at least question or options; omitted target requires one active poll |
| POLL_DELETE | none | target:POLL_TARGET | omitted target requires one active poll |
| POLL_CLOSE | none | target:POLL_TARGET | omitted target requires one active poll |
| BIRTHDAY_CREATE | user_id:POS_INT, day:1–31, month:1–12 | year:YEAR | user_id must equal an authorized resolved mention; date must exist |
| BIRTHDAY_LIST | none | scope:all\|upcoming | scope defaults to all |
| BIRTHDAY_EDIT | user_id:POS_INT, day:1–31, month:1–12 | year:YEAR | user_id must equal author or an authorized resolved mention; date must exist |
| WATCHLIST_ADD | title:S500 | type:movie\|series, genre:S200, comment:TEXT2000 | none |
| WATCHLIST_LIST | none | none | maps to status |
| WATCHLIST_SUGGEST | none | type:movie\|series, genre:S200 | none |
| WATCHLIST_EDIT | index:POS_INT | title:S500, type:movie\|series, genre:S200-or-null, comment:TEXT2000-or-null | at least one change |
| WATCHLIST_REMOVE | index:POS_INT | none | none |
| QUOTE_SAVE | text:TEXT2000 | author:S200 | none |
| QUOTE_GET | none | none | none |
| QUOTE_LIST | none | none | none |
| QUOTE_EDIT | index:POS_INT | text:TEXT2000, author:S200 | at least text or author |
| QUOTE_DELETE | index:POS_INT | none | none |

The registry and parser reject unknown action names, unknown top-level keys, unknown slot keys, bool where int is expected, non-finite confidence, confidence outside 0–1, and more than one proposal. Top-level keys are exactly `action`, `confidence`, `slots`, `reply`, and `clarification`; `reply` is a string of at most 2000 characters. `NONE` and `CLARIFY` never create an executable candidate.

`core/action_bridge.py` uses this exact bridge table. `copy(...)` means copy only the named validated slots, and every emitted result has `source=SEMANTIC`, `risk=classify_intent_risk(intent, payload)`, and `requires_confirmation=True` iff that risk is ADDITIVE, MUTATING, or DESTRUCTIVE.

| ActionName | BotIntent | Exact IntentResult.payload |
|---|---|---|
| SHOW_DASHBOARD | DASHBOARD | `{"dashboard_reason":"model_action"}` |
| HELP | HELP | `{}` |
| CALENDAR_CREATE | CALENDAR_ITEM | `{"calendar_item":copy(title,date,time,type,recurrence,recurrence_day,rrule_day,description)}` after converting `days_offset` to an absolute canonical `date` from `context.reference_time.astimezone(OSLO).date()`; emitted payload never contains `days_offset` |
| CALENDAR_LIST | CALENDAR_LIST | `{}` |
| CALENDAR_SEARCH | CALENDAR_SEARCH | `{"query":slots["query"]}` |
| CALENDAR_COMPLETE | CALENDAR_COMPLETE | `{"calendar_target":copy(target,number)}` |
| CALENDAR_EDIT | CALENDAR_EDIT | `{"calendar_edit":{"target":slots["target"],"changes":copy(title,description,date,time,recurrence)}}` |
| CALENDAR_DELETE | CALENDAR_DELETE | `{"calendar_target":copy(target,number)}` |
| CALENDAR_CLEAR | CALENDAR_CLEAR | `{"calendar_target":{"all":true}}` |
| REMINDER_CREATE | REMINDER_CREATE | `{"reminder":{"action":"add", **copy(text,due_at,due_date,time,timezone,recurrence)}}` |
| REMINDER_LIST | REMINDER_LIST | `{"reminder":{"action":"list"}}` |
| REMINDER_SEARCH | REMINDER_SEARCH | `{"reminder":{"action":"search","query":slots["query"]}}` |
| REMINDER_COMPLETE | REMINDER_COMPLETE | `{"reminder":{"action":"complete","number":slots["number"]}}` |
| REMINDER_EDIT | REMINDER_EDIT | `{"reminder":{"action":"edit","number":slots["number"],"changes":copy(text,due_at,due_date,time,timezone,recurrence)}}` |
| REMINDER_DELETE | REMINDER_DELETE | `{"reminder":{"action":"delete","number":slots["number"]}}` |
| POLL_CREATE | POLL_CREATE | `{"poll":copy(question,options)}` |
| POLL_LIST | POLL_LIST | `{}` |
| POLL_VOTE | POLL_VOTE | `{"vote":{"option":slots["option"]}}` |
| POLL_EDIT | POLL_EDIT | `{"poll_edit":copy(target,question,options)}` |
| POLL_DELETE | POLL_DELETE | `{"poll_delete":copy(target)}` |
| POLL_CLOSE | POLL_CLOSE | `{"poll_close":copy(target)}` |
| BIRTHDAY_CREATE | BIRTHDAY_CREATE | `{"birthday":{"action":"add","user_id":user_id,"display_name":resolved_name, **copy(day,month,year)}}` |
| BIRTHDAY_LIST | BIRTHDAY_LIST | `{"birthday":{"action":"list", **copy(scope)}}` |
| BIRTHDAY_EDIT | BIRTHDAY_EDIT | `{"birthday":{"action":"edit","user_id":user_id, **copy(day,month,year)}}` |
| WATCHLIST_ADD | WATCHLIST | `{"watchlist":{"action":"add", **copy(title,type,genre,comment)}}` |
| WATCHLIST_LIST | WATCHLIST | `{"watchlist":{"action":"status"}}` |
| WATCHLIST_SUGGEST | WATCHLIST | `{"watchlist":{"action":"suggest", **copy(type,genre)}}` |
| WATCHLIST_EDIT | WATCHLIST | `{"watchlist":{"action":"edit", **copy(index,title,type,genre,comment)}}` |
| WATCHLIST_REMOVE | WATCHLIST | `{"watchlist":{"action":"remove","index":slots["index"]}}` |
| QUOTE_SAVE | QUOTE | `{"quote":{"action":"save", **copy(text,author)}}` |
| QUOTE_GET | QUOTE | `{"quote":{"action":"get"}}` |
| QUOTE_LIST | QUOTE_LIST | `{"quote":{"action":"list"}}` |
| QUOTE_EDIT | QUOTE_EDIT | `{"quote":{"action":"edit", **copy(index,text,author)}}` |
| QUOTE_DELETE | QUOTE_DELETE | `{"quote":{"action":"delete","index":slots["index"]}}` |

`NONE` maps to no route. `CLARIFY` maps to a non-executable `IntentResult(BotIntent.CLARIFY, ..., {"clarification": proposal.clarification}, ...)`. `ActionBridge.to_result()` must fail closed when the target active-state or resolved-mention precondition in the spec is unavailable; it must never invent or fuzzy-match an identifier.

The model-facing registry deliberately excludes internal `reminder_id` and `poll_id` slots. Semantic proposals express only user-visible positions/options; `PendingTargetResolver.freeze()` resolves and injects stable IDs before staging. The broader typed payload contract accepts those IDs only for deterministic internal revalidation and delayed dispatch.

parse_ai_response() must:

- scan only standalone JSON object lines outside Markdown fences;
- accept at most one valid proposal;
- remove the proposal line from visible text;
- remove action-looking malformed/truncated protocol lines from visible text while returning a bounded machine error; ordinary non-protocol JSON prose remains visible;
- temporarily accept one legacy SAVE_EVENT or SHOW_DASHBOARD tag and convert it into the new proposal;
- never call an executor.

Legacy conversion tests must assert that SAVE_EVENT parses as ActionName.CALENDAR_CREATE and bridges to a SEMANTIC, ADDITIVE, confirmation-required BotIntent.CALENDAR_ITEM candidate; SHOW_DASHBOARD parses as ActionName.SHOW_DASHBOARD and bridges to a SEMANTIC, READ_ONLY BotIntent.DASHBOARD candidate; and parsing either legacy form alone performs zero manager, handler, or send calls.

- [ ] **Step 3: Build one compact prompt contract**

Export ACTION_PROTOCOL_PROMPT from ai/action_schema.py. Generate it from ACTION_SPECS so provider instructions cannot drift. It must say:

- ordinary prose first;
- zero or one standalone JSON proposal line;
- do not invent ids, dates, times, names, or choices;
- use CLARIFY when required slots are missing;
- NONE for ordinary conversation;
- a proposal is not an execution confirmation.

ai/personality_config.py must import this exact prompt. Remove duplicate legacy instructions after the compatibility parser exists.

- [ ] **Step 4: Preserve the caller prompt on both providers**

- Delete the small-Llama rule that replaces custom prompts over 800 characters.
- Extract a pure build_bridge_request() helper so payload construction can be tested without starting the bridge.
- If a compact prompt is needed, generate it centrally while retaining action, safety, current Oslo time, and trust-boundary instructions.
- Preserve the caller temperature and max_tokens through the bridge request.
- Keep the Gemma transport exception that folds the system prompt into a user role, but test content/order parity rather than identical roles.
- The response cleaner must preserve a valid standalone action JSON line even when it selects or trims prose.
- Move the inline clean_thinking_response() implementation from ai/hermes_bridge_server.py into ai/response_cleaner.py, import that single implementation in the bridge, and test that implementation directly. Do not leave two cleaners with different behavior.

Add:

~~~python
def test_small_llama_keeps_long_action_prompt(bridge_payload):
    prompt = "P" * 900 + ACTION_PROTOCOL_PROMPT
    request = build_bridge_request(
        message_content="kan du hjelpe?",
        system_prompt=prompt,
        temperature=0.2,
        max_tokens=321,
    )
    assert prompt in serialize_messages(request["messages"])
    assert request["temperature"] == 0.2
    assert request["max_tokens"] == 321
~~~

- [ ] **Step 5: Map proposals to candidates without executing**

core/action_bridge.py must:

- map every ActionName to one BotIntent and the validated existing payload shape;
- set source SEMANTIC;
- classify risk through classify_intent_risk();
- mark additive/mutating/destructive semantic candidates requires_confirmation;
- pass the original NormalizedUtterance and one candidate through arbitrate_candidates();
- reject a proposal if its action contradicts negation, quotation, hypothetical framing, or explicit deterministic evidence;
- return an IntentResult, never call MessageMonitor._handle_intent().

- [ ] **Step 6: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_action_schema.py \
  tests/test_action_bridge.py \
  tests/test_provider_prompt_contract.py \
  tests/test_ai_connectors.py -q
git add ai/action_schema.py ai/personality_config.py ai/openrouter_connector.py \
  ai/hermes_connector.py ai/hermes_bridge_server.py ai/response_cleaner.py \
  core/action_bridge.py \
  tests/test_action_schema.py tests/test_action_bridge.py \
  tests/test_provider_prompt_contract.py tests/test_ai_connectors.py
git commit -m "feat: validate semantic action proposals"
~~~

Expected: PASS; a model response cannot mutate or send anything in these tests.

---

### Task 9: Add user-scoped pending confirmations, choices, and corrections

**Objective:** Support natural follow-ups while guaranteeing at-most-once execution and preventing one user or channel from confirming another conversation’s action.

**Interfaces:**

- Consumes: ConversationKey and one or more IntentResult routes.
- Produces: PendingResolution values CONFIRM, CANCEL, SELECT, CORRECT, EXPIRED, or NONE.
- Persistence: in-memory only; restart loss is the safe default.

Use this resolution contract:

~~~python
class PendingResolutionKind(str, Enum):
    NONE = "none"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    SELECT = "select"
    CORRECT = "correct"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class PendingResolution:
    kind: PendingResolutionKind
    action_id: str | None = None
    choice_index: int | None = None
    correction_text: str | None = None
~~~

**Files:**

- Modify: core/message_context.py
- Create: core/pending_actions.py
- Create: tests/test_pending_actions.py
- Modify: core/intent_router.py:104-243
- Modify: tests/test_intent_router.py

- [ ] **Step 1: Write pure store and resolver tests**

~~~python
def key(user_id=7, channel_id=10):
    return ConversationKey(guild_id=1, channel_id=channel_id, user_id=user_id)


def test_confirmation_is_scoped_and_claimed_once(clock):
    store = PendingActionStore(now_provider=clock, ttl=timedelta(minutes=10))
    route = IntentResult(
        BotIntent.REMINDER_CREATE,
        0.91,
        {"reminder": {"action": "add", "text": "ringe legen"}},
        "semantic_action",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )
    presentation = store.begin_confirmation(key(), route, "Ringe legen")
    pending = store.activate_presentation(presentation)
    assert pending is not None
    assert store.resolve(key(user_id=8), "ja").kind is PendingResolutionKind.NONE
    resolution = store.resolve(key(), "ja")
    assert resolution.kind is PendingResolutionKind.CONFIRM
    assert store.claim(key(), pending.action_id) is not None
    assert store.claim(key(), pending.action_id) is None


@pytest.mark.parametrize(
    ("text", "kind", "index"),
    [
        ("første", PendingResolutionKind.SELECT, 0),
        ("nummer 2", PendingResolutionKind.SELECT, 1),
        ("den andre", PendingResolutionKind.SELECT, 1),
        ("nei", PendingResolutionKind.CANCEL, None),
        ("avbryt", PendingResolutionKind.CANCEL, None),
    ],
)
def test_natural_pending_resolution(text, kind, index, pending_store):
    routes = (
        IntentResult(BotIntent.REMINDER_LIST, 1.0),
        IntentResult(BotIntent.CALENDAR_LIST, 1.0),
    )
    presentation = pending_store.begin_choices(
        key(),
        routes,
        "Velg liste",
        target_guards=(None, None),
    )
    assert pending_store.activate_presentation(presentation) is not None
    result = pending_store.resolve(key(), text)
    assert result.kind is kind
    assert result.choice_index == index


def test_temporal_correction_applies_only_to_confirmation(confirmation_store):
    result = confirmation_store.resolve(key(), "i morgen kl 14")
    assert result.kind is PendingResolutionKind.CORRECT
    assert result.correction_text == "i morgen kl 14"
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_pending_actions.py -q
~~~

Expected: FAIL because pending actions do not exist.

- [ ] **Step 2: Implement ConversationKey extraction**

Add routing_context_from_message(message) and keep conversation_key_from_message(message) as its key-only wrapper:

- guild_id None for DMs, otherwise message.guild.id;
- channel_id always message.channel.id;
- user_id message.author.id.
- author is ResolvedMention(message.author.id, message.author.display_name or message.author.name).
- mentions is a tuple of ResolvedMention values built from message.mentions after authorization.

No fallback to guild_id as channel_id is permitted when the real channel exists.

- [ ] **Step 3: Implement a TTL and claim-state store**

PendingActionStore must:

- accept an injected aware clock;
- use a ten-minute TTL;
- enter PRESENTING before any prompt send, activate READY only after the complete bounded preview is definitely delivered, and restore an older READY action only when zero new chunks could have been delivered;
- serialize begin -> owned shielded send(s) -> activate/abort with the whole authorized turn under one fair FIFO per-ConversationKey coordinator scope;
- replace an older READY pending action for the same key only through that presentation transaction;
- refuse to replace EXECUTING state;
- begin one confirmation or two-to-five choices, carrying one frozen target guard per route and deep-copying all routes/guards;
- parse ja, jepp, japp, ok, bekreft, gjør det, gjer det, yes;
- parse nei, nope, avbryt, stopp, cancel;
- parse numeric and Norwegian/English ordinal choices;
- classify a follow-up as CORRECT only when it starts with an explicit correction frame such as “endre til”, “i stedet”, or “heller”, or contains temporal/title/choice evidence for a slot that the staged route exposes;
- return NONE for unrelated requests such as weather, help, or a new domain command so normal routing continues;
- atomically transition READY to EXECUTING in claim();
- complete only the matching action id;
- expose complete(key, action_id), release_retryable(key, action_id, outcome), and fail_terminal(key, action_id);
- allow release_retryable only from EXECUTING when the caller supplies a DispatchOutcome with mutated=False and retryable=True;
- move committed or ambiguous failures to COMPLETED or FAILED and never return them to READY;
- start the ten-minute TTL at successful activation, remove expired READY state on public operations, and never expire EXECUTING while a manager is in flight;
- expose counts only, never summaries or payloads, to metrics.

- [ ] **Step 4: Let the router recognize pending follow-ups first**

Add PendingActionStore to IntentRouter through the monitor-owned instance. Before normal candidate collection:

- resolve only with a matching ConversationKey;
- return ACTION_CONFIRM, ACTION_CANCEL, or ACTION_CORRECT with the pending action id;
- return ACTION_SELECT with only the action id and zero-based selected choice index; the store remains authoritative for the route and frozen guard;
- let an unmatched “ja” or “nei” fall to AI_CHAT;
- preserve the mention gate because route() still receives only authorized content.

Keep route(content, guild_id=None) valid; channel_id and user_id are keyword-only and optional. Without a complete key, pending lookup is skipped.

- [ ] **Step 5: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_pending_actions.py \
  tests/test_intent_router.py \
  tests/test_mention_gate.py -q
git add core/message_context.py core/pending_actions.py core/intent_router.py \
  tests/test_pending_actions.py tests/test_intent_router.py
git commit -m "feat: stage scoped natural-language actions"
~~~

Expected: PASS with at-most-once claims and strict user/channel isolation.

---

### Task 10: Integrate clarification and confirmation into MessageMonitor

**Objective:** Route deterministic ambiguity and semantic proposals through one safe conversational workflow, with no double sends and no direct model execution.

**Interfaces:**

- Consumes: IntentResult, ParsedAIResponse, ActionBridge, PendingActionStore, and DispatchOutcome.
- Produces: one send owner per turn (a lossless confirmation may be one ordered sequence of up to five Discord messages), one final decision record, and at-most-once mutation after explicit confirmation.
- Mention behavior: all guild and DM follow-ups remain mention-gated; no bare control utterance reaches pending resolution.

**Files:**

- Create: features/ai_action_handler.py
- Create: tests/test_ai_action_flow.py
- Modify: core/message_monitor.py:433-930
- Modify: core/intent_router.py:104-243
- Modify: tests/test_message_monitor_routing.py
- Modify: tests/test_action_schema.py
- Modify: tests/test_mention_gate.py

- [ ] **Step 1: Write end-to-end offline flow tests**

~~~python
@pytest.mark.asyncio
async def test_semantic_write_stages_then_confirms_once(
    monitor,
    mentioned_message,
):
    monitor.hermes.generate_response = AsyncMock(
        return_value=(
            True,
            "Klart.\n"
            '{"action":"REMINDER_CREATE","confidence":0.91,'
            '"slots":{"text":"ringe legen",'
            '"due_at":"2026-07-15T09:00:00+02:00"},'
            '"reply":"","clarification":null}',
        )
    )
    monitor.handlers["reminders"].handle_reminder_create = AsyncMock(
        return_value=DispatchOutcome.success(mutated=True)
    )

    await monitor.handle_message(mentioned_message("kan du huske legetelefonen?"))

    monitor.handlers["reminders"].handle_reminder_create.assert_not_awaited()
    assert monitor.pending_actions.peek(
        conversation_key_from_message(mentioned_message.last)
    ) is not None

    await monitor.handle_message(mentioned_message("ja"))
    await monitor.handle_message(mentioned_message("ja"))

    monitor.handlers["reminders"].handle_reminder_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_negated_model_proposal_cannot_stage(monitor, mentioned_message):
    monitor.hermes.generate_response = AsyncMock(
        return_value=(
            True,
            '{"action":"CALENDAR_DELETE","confidence":0.99,'
            '"slots":{"target":"1"},"reply":"","clarification":null}',
        )
    )
    await monitor.handle_message(mentioned_message("ikke slett kalenderen"))
    assert monitor.pending_actions.counts()["ready"] == 0
    monitor.handlers["calendar"].handle_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_dashboard_returns_one_outer_response(
    monitor,
    mentioned_message,
):
    monitor.hermes.generate_response = AsyncMock(
        return_value=(
            True,
            '{"action":"SHOW_DASHBOARD","confidence":0.95,'
            '"slots":{},"reply":"","clarification":null}',
        )
    )
    monitor._send_response = AsyncMock(return_value=True)
    message = mentioned_message("kan jeg få alt samlet på ett sted?")
    routing = routing_context_from_message(
        message,
        bot_user_id=monitor.client.user.id,
    )
    await monitor._send_ai_response(
        message,
        utterance=normalize_utterance(message.content),
        routing_context=routing,
        routed_intent=IntentResult(BotIntent.AI_CHAT, 1.0),
        reference_time=datetime(
            2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")
        ),
        semantic_action_allowed=True,
    )
    monitor._send_response.assert_awaited_once()
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_ai_action_flow.py -q
~~~

Expected: FAIL because MessageMonitor still parses and partially executes model tags inline.

- [ ] **Step 2: Implement AIActionHandler**

features/ai_action_handler.py must expose:

~~~python
class ModelDisposition(str, Enum):
    ORDINARY = "ordinary"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AIModelOutcome:
    visible_text: str
    route: IntentResult | None = None
    parser_errors: tuple[str, ...] = ()
    disposition: ModelDisposition = ModelDisposition.ORDINARY


@dataclass(frozen=True, slots=True)
class PendingPresentationSpec:
    kind: PendingKind
    routes: tuple[IntentResult, ...]
    target_guards: tuple[PendingTargetGuard | None, ...]
    summary: str
    messages: tuple[str, ...]
    correction_action_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionFlowOutcome:
    text: str = ""
    route: IntentResult | None = None
    target_guard: PendingTargetGuard | None = None
    presentation: PendingPresentationSpec | None = None
    dispatch: DispatchOutcome | None = None
    decision_route: IntentResult | None = None
    decision_outcome: str | None = None

    @property
    def response_sent(self) -> bool:
        return bool(self.dispatch and self.dispatch.response_sent)


class AIActionHandlerContract(Protocol):
    async def handle_model_response(
        self, *, raw: str, utterance: NormalizedUtterance,
        routing: RoutingContext, reference_time: datetime,
        deterministic_route: IntentResult | None,
        active_poll_count: int | None,
        active_poll_id: str | None,
        semantic_action_allowed: bool,
    ) -> AIModelOutcome: ...

    def prepare_confirmation(
        self, message, route: IntentResult, *, prefix: str = "",
        target_guard: PendingTargetGuard | None = None,
    ) -> ActionFlowOutcome: ...
    def prepare_choices(
        self,
        message,
        routes: tuple[IntentResult, ...],
        guards: tuple[PendingTargetGuard | None, ...],
        prompt: str,
    ) -> ActionFlowOutcome: ...
    async def confirm(
        self,
        message,
        action_id: str,
        *,
        reference_time: datetime,
    ) -> ActionFlowOutcome: ...
    async def cancel(self, message, action_id: str) -> ActionFlowOutcome: ...

    async def select(
        self,
        message,
        action_id: str,
        choice_index: int,
    ) -> ActionFlowOutcome: ...

    async def correct(
        self,
        message,
        action_id: str,
        utterance: NormalizedUtterance, *, reference_time: datetime,
    ) -> ActionFlowOutcome: ...
~~~

Rules:

- handle_model_response parses once, turns a valid proposal into a candidate, and returns an AIModelOutcome without sending or dispatching;
- a read-only proposal is returned as route and MessageMonitor dispatches it once through _handle_intent(), without an outer prose send;
- a semantic write is returned as an inert validated route; after the shared threshold and target-freeze checks, `_process_route()` asks `prepare_confirmation()` for a pure presentation spec and MessageMonitor alone begins/sends/activates it under the conversation scope;
- every destructive route, including deterministic routes, enters that same monitor-owned freeze/prepare/present path and never arrives from `handle_model_response()` as a presentation object;
- a deterministic explicit additive route retains immediate execution;
- arbitrary model prose is retained only for ordinary/NONE or proven read-only output. Accepted writes replace it with fixed system-owned “prepared, not performed” copy; parser/payload failures and bridge safety/context rejections discard it in favor of fixed non-execution copy. `ModelDisposition` is only the bounded decision state: a route-less `BLOCKED` maps to `blocked`, `INVALID` to `failed`, `ORDINARY` to `routed` (or `executed` for validated SEARCH), and an unexpected route-less `ACCEPTED` fails closed;
- `prepare_confirmation` never touches the store and formats a lossless payload-derived proposition; unsupported or overlarge previews fail closed before PRESENTING;
- confirmation copy contains no secret/internal reason, neutralizes Discord/control text, and tells users in both guilds and DMs to mention the bot;
- confirm claims before dispatch, completes only `outcome.ok`, releases only proven non-mutating retryable failure, marks partial/ambiguous/non-retryable failures FAILED, settles a typed `DispatchCancelled` before re-raising, and rejects duplicate confirmation;
- confirm dispatches dataclasses.replace(route, requires_confirmation=False) through a claimed-action path; this is the only bypass of the staging guard and prevents an infinite restaging loop;
- cancel deletes READY state only;
- select resolves the ambiguity only and returns the store's already-frozen guard; it never re-resolves a positional target after the numbered prompt;
- correct uses the single monitor-owned TemporalResolver, the turn-captured reminder clock value, and typed payload validators, then returns a correction presentation spec retaining the original guard;
- unsupported correction sends a focused question without mutating.

- [ ] **Step 3: Replace inline execution**

In MessageMonitor:

- instantiate one PendingActionStore and AIActionHandler;
- acquire one fair FIFO ConversationKey turn scope, strip only a leading bot invocation in either a guild or DM, capture one reminder-clock time, build one RoutingContext/NormalizedUtterance, and pass all three explicitly through routing/model/correction;
- add `_passes_intent_threshold(route)` and enforce it exactly once in the central `_process_route()` before staging or dispatch. `_handle_intent()` consumes an already-admitted route and does not recheck; this lets a user-selected frozen interpretation bypass only model/threshold rescue while still passing authorization, payload validation, target revalidation, risk policy, and confirmation. A below-threshold ordinary proposal falls back to chat and is never staged;
- before _handle_intent(), freeze targets, build a presentation spec, begin PRESENTING, send every owned/shielded preview chunk, activate READY only after definite complete delivery, and return without dispatching;
- handle CLARIFY by freezing every candidate/guard before presenting numbered natural-language options;
- route ACTION_CONFIRM, ACTION_CANCEL, ACTION_SELECT, and ACTION_CORRECT to AIActionHandler;
- replace _parse_and_execute_actions() with a temporary delegate to AIActionHandler.handle_model_response();
- remove direct SHOW_DASHBOARD send from parsing;
- remove command-copy confirmation as the primary flow; use “@inebotten ja/nei” copy;
- pass routed_intent explicitly to _send_ai_response() instead of reading _last_routed_intent;
- pass the existing NormalizedUtterance into _send_ai_response() and AIActionHandler instead of normalizing a second time;
- ensure every path has one send owner; a confirmation preview may invoke its bounded ordered chunk sequence, and partial/unknown delivery never leaves an actionable old or new prompt.

The compatibility _parse_and_execute_actions() wrapper returns only outcome.visible_text and never executes. The normal _send_ai_response() path consumes the complete AIModelOutcome: send visible_text only when route is absent, dispatch a read-only route once, or pass a write route to the monitor-owned freeze/presentation flow. It never stages from raw model JSON inside AIActionHandler.

- [ ] **Step 4: Pin destructive and ambiguity behavior**

Add tests for:

- explicit “slett påminnelse 1” stages and does not delete;
- “kan du slette kalenderen?” routes to `CALENDAR_CLEAR` with
  `calendar_target.all=true` and stages a whole-collection confirmation;
- “ikke slett kalenderen” neither stages nor deletes;
- a clarification choice “den andre” selects only that frozen route and bypasses only threshold/model rescue; every selected non-`READ_ONLY` route is re-presented and still needs “@inebotten ja”, while only a selected `READ_ONLY` route dispatches once;
- “i morgen kl 14” corrects a staged reminder;
- expired confirmation does not dispatch;
- a proven pre-mutation retryable handler failure releases the pending route for retry;
- a committed/partial mutation followed by response-send failure marks the pending route FAILED and cannot execute again;
- an ambiguous handler exception becomes terminal and cannot auto-retry;
- confirmation from another user or channel does nothing;
- an untagged guild “ja” is ignored before routing;
- a model response with two proposals is prose only and makes zero mutations.
- a semantic proposal below CONFIDENCE_THRESHOLDS is not staged;
- confirmed dispatch clears requires_confirmation only on the claimed copy and does not restage.

- [ ] **Step 5: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_ai_action_flow.py \
  tests/test_message_monitor_routing.py \
  tests/test_pending_actions.py \
  tests/test_action_schema.py \
  tests/test_mention_gate.py -q
git add features/ai_action_handler.py core/message_monitor.py \
  core/intent_router.py tests/test_ai_action_flow.py \
  tests/test_message_monitor_routing.py tests/test_action_schema.py \
  tests/test_mention_gate.py
git commit -m "feat: confirm inferred and destructive actions naturally"
~~~

Expected: PASS with one response per flow and at-most-once mutation.

---

### Task 11: Scope conversation history and preserve role-correct context

**Objective:** Make natural follow-ups work within one user/channel conversation without duplicating the current message, leaking context across channels, or weakening the system prompt.

**Interfaces:**

- Consumes: ConversationKey, authorized inbound messages, and successful outbound sends.
- Produces: tuple[ChatTurn, ...] supplied separately to both AI connectors.
- Does not embed: conversation history inside the system prompt.

**Files:**

- Create: ai/chat_contract.py
- Create: tests/test_chat_contract.py
- Create: tests/test_context_integration.py
- Create: tests/test_bridge_history.py
- Modify: memory/conversation_context.py:12-180
- Modify: core/intent_router.py:613-665
- Modify: core/message_monitor.py:645-805,1013-1055
- Modify: features/base_handler.py:43-100
- Modify: ai/openrouter_connector.py:221-290
- Modify: ai/hermes_connector.py:243-330
- Modify: ai/hermes_bridge_server.py:242-330,680-773
- Modify: ai/personality_config.py:53-151
- Modify: tests/test_conversation_context.py
- Modify: tests/test_base_handler_rate_limit.py

- [ ] **Step 1: Write isolation and duplication tests**

~~~python
def test_history_is_isolated_by_guild_channel_and_user():
    context = ConversationContext()
    key_a = ConversationKey(1, 10, 7)
    key_b = ConversationKey(1, 11, 7)
    key_c = ConversationKey(1, 10, 8)
    context.add_turn(key_a, ChatTurn("user", "melding a", source_message_id=1))
    assert [turn.content for turn in context.get_prompt_history(key_a)] == [
        "melding a"
    ]
    assert context.get_prompt_history(key_b) == ()
    assert context.get_prompt_history(key_c) == ()


@pytest.mark.asyncio
async def test_current_message_appears_once_in_provider_payload(
    monitor,
    message,
):
    message.id = 99
    monitor.hermes.generate_response = AsyncMock(return_value=(True, "svar"))
    utterance = normalize_utterance(message.content)
    routing = routing_context_from_message(
        message,
        bot_user_id=monitor.client.user.id,
    )
    await monitor._send_ai_response(
        message,
        utterance=utterance,
        routing_context=routing,
        routed_intent=IntentResult(BotIntent.AI_CHAT, 1.0),
        reference_time=datetime(
            2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")
        ),
        semantic_action_allowed=True,
    )
    call = monitor.hermes.generate_response.await_args.kwargs
    serialized = (
        "\n".join(turn.content for turn in call["history"])
        + "\n"
        + call["message_content"]
    )
    assert serialized.count(message.content) == 1


@pytest.mark.asyncio
async def test_base_handler_records_one_successful_outbound(
    handler,
    message,
):
    handler.monitor.record_outbound = Mock()
    await handler.send_response(message, "ett svar")
    handler.monitor.record_outbound.assert_called_once_with(message, "ett svar")
~~~

Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_chat_contract.py tests/test_context_integration.py -q
~~~

Expected: FAIL because context is currently keyed with the guild id at the call site and BaseHandler does not record output.

- [ ] **Step 2: Define ChatTurn and connector protocol**

ai/chat_contract.py:

~~~python
@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str
    source_message_id: int | None = None


class AIConnector(Protocol):
    async def generate_response(
        self,
        message_content: str,
        author_name: str,
        channel_type: str,
        is_mention: bool = True,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context_prompt: str = "",
        history: Sequence[ChatTurn] = (),
    ) -> tuple[bool, str]:
        raise NotImplementedError
~~~

Define sanitize_chat_turn_content() in ai/chat_contract.py rather than using utils.sanitizer.sanitize_text(), which collapses protocol-significant newlines. It must remove NUL and disallowed control characters, preserve newline/tab and valid Unicode, cap one turn at 4,000 characters, and never interpret JSON. Do not put user history into system-role content.

- [ ] **Step 3: Migrate ConversationContext**

- Key threads and last_bot_message by ConversationKey.
- Store ChatTurn rather than untyped dictionaries for new writes.
- Tolerate old dictionary turns in read methods during one release.
- Clean expiry in add and every get method.
- get_prompt_history() accepts a limit and exclude_source_message_id.
- Preserve get_context() as a formatting compatibility wrapper.
- Preserve existing add_message(), get_context(), and get_channel_messages() call shapes through wrappers, including integer legacy keys; add explicit migration tests for current dictionary turns and integer-key thread maps.
- Delete the fallback that scans every conversation thread for a reminder topic.
- Move the one useful calendar/reminder follow-up into PendingActionStore rather than scraping bot prose.

- [ ] **Step 4: Centralize inbound and outbound recording**

- In handle_message(), route the authorized message first, resolve the effective history policy from that route and any authoritative pending action/choice it references, then record the inbound turn exactly once with message.id under that policy before presentation or dispatch.
- For ACTION_CONFIRM/ACTION_CORRECT/ACTION_CANCEL, derive policy from the matching frozen pending route. For ACTION_SELECT and CLARIFY, evaluate **every** frozen choice conservatively before consuming the selection; redact if any choice is sensitive, even when the chosen index itself is not. A missing/stale/expired pending lookup or any recursively allowlisted credential key fails closed to REDACT_AUTH.
- In _send_ai_response(), exclude that source id from history and send the current content only in message_content.
- Add MessageMonitor.record_outbound(message, content).
- Call it after a successful send only in canonical `MessageMonitor._send_response_result()`.
- Call the same method after a successful send only in canonical `BaseHandler.send_response_result()`.
- Keep `_send_response()` and `send_response()` as result-projecting compatibility wrappers; they never record a second outbound turn.
- Guard the BaseHandler call with hasattr so existing lightweight monitor doubles remain compatible.
- Do not call `_send_response()` from BaseHandler; each actual send path owns exactly one recording call.
- Add a regression test for direct monitor sends, BaseHandler sends, failed sends, and rate-limited sends.

- [ ] **Step 5: Serialize role-correct history on both providers**

- Add history and `context_prompt: str = ""` to Hermes and OpenRouter connector signatures with backward-compatible defaults. The monitor builds at most 4,000 characters of user-memory/search context and both providers serialize it as a separate `UNTRUSTED_CONTEXT_DATA` user-role message.
- Accept only user and assistant roles; reject system/unknown roles from history.
- Cap transport history at ten turns and 12,000 aggregate characters after per-turn sanitization.
- Serialize old turns before the current user message.
- For standard chat models: trusted system prompt, optional untrusted-context user message, history roles, current user.
- For the Gemma exception: use the trusted prompt as the first user transport message, then the optional untrusted-context user message, alternating history, and current user content; never concatenate these channels.
- Forward history across the local bridge without converting it into a custom prompt string.
- Keep action JSON lines intact in assistant history but never execute them from history.

Add tests for legacy dictionary turns, integer channel keys, the old public method signatures, monitor doubles without record_outbound, unknown/system roles, oversized history truncation, and historical assistant action JSON remaining inert.

- [ ] **Step 6: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_chat_contract.py \
  tests/test_context_integration.py \
  tests/test_conversation_context.py \
  tests/test_base_handler_rate_limit.py \
  tests/test_provider_prompt_contract.py \
  tests/test_bridge_history.py -q
git add ai/chat_contract.py memory/conversation_context.py \
  core/intent_router.py core/message_monitor.py features/base_handler.py \
  ai/openrouter_connector.py ai/hermes_connector.py \
  ai/hermes_bridge_server.py ai/personality_config.py \
  tests/test_chat_contract.py tests/test_context_integration.py \
  tests/test_conversation_context.py tests/test_base_handler_rate_limit.py \
  tests/test_bridge_history.py
git commit -m "fix: scope natural conversation history correctly"
~~~

Expected: PASS with current content serialized exactly once.

---

### Task 12: Restore command/help parity and expand only measured language forms

**Objective:** Make documented natural phrases reachable and remove feature parsers whose broad syntax steals unrelated conversation.

**Interfaces:**

- Consumes: production parser contract corpus and existing manager APIs.
- Produces: reachable birthday add/list, explicit poll parsing, scoped watchlist actions, typed profile status/activity, executable help contracts, and corpus proof for prerequisite-owned Bokmål/Nynorsk/dialect-adjacent forms.
- Documentation rule: describe evaluated forms; do not claim general dialect understanding.

**Files:**

- Create: tests/test_birthday_commands.py
- Create: tests/test_help_route_parity.py
- Create: tests/test_help_handler.py
- Create: tests/test_profile_routing.py
- Create: core/help_registry.py
- Create: features/profile_commands.py
- Modify: core/intent_payloads.py
- Modify: features/birthday_manager.py:81-125,224-285,474-531
- Verify: features/birthday_handler.py — typed-dispatch prerequisite adapters
- Modify: features/poll_manager.py:251-340
- Verify: features/watchlist_manager.py — routing-foundation prerequisite parser
- Modify: core/intent_keywords.py
- Modify: core/intent_router.py:104-243
- Modify: core/message_monitor.py:510-644
- Modify: features/help_handler.py:19-66
- Modify: features/profile_handler.py
- Modify: memory/localization.py:443-505
- Modify: web_console/dashboard.py:790-885
- Modify: tests/test_poll_target.py
- Modify: tests/test_watchlist_scope.py
- Modify: tests/test_parse_once_dispatch.py
- Modify: tests/test_console_server.py
- Modify: tests/nlu_harness.py
- Modify: tests/fixtures/nlu_contract_v1.jsonl

- [ ] **Step 1: Write birthday reachability tests**

The router fixture in this file uses a TemporalResolver clock fixed at 2026-07-14 12:00 Europe/Oslo.

~~~python
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("bursdagen min er 15.05", BotIntent.BIRTHDAY_CREATE),
        ("eg har bursdag 15.05", BotIntent.BIRTHDAY_CREATE),
        ("vis bursdager", BotIntent.BIRTHDAY_LIST),
        ("kven har bursdag snart?", BotIntent.BIRTHDAY_LIST),
    ],
)
def test_documented_birthday_phrases_are_reachable(router, text, intent):
    context = RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=7),
        author=ResolvedMention(user_id=7, display_name="Kari"),
    )
    result = router.route_utterance(
        normalize_utterance(text),
        routing_context=context,
    )
    assert result.intent is intent


def test_unresolved_free_text_name_is_not_assigned_to_author(router):
    context = RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=7),
        author=ResolvedMention(user_id=7, display_name="Kari"),
    )
    result = router.route_utterance(
        normalize_utterance("Ola har bursdag 15.05"),
        routing_context=context,
    )
    assert result.intent is BotIntent.CLARIFY


@pytest.mark.parametrize(
    "text",
    [
        "Mina har bursdag 15.05",
        "Myra has birthday 15.05",
        "min venn Ola har bursdag 15.05",
        "bursdagen til min søster er 15.05",
        "my sister's birthday is 15.05",
    ],
)
def test_relational_possessives_and_free_names_never_bind_author(router, text):
    context = RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=7),
        author=ResolvedMention(user_id=7, display_name="Kari"),
    )
    result = router.route_utterance(
        normalize_utterance(text),
        routing_context=context,
    )
    assert result.intent is BotIntent.CLARIFY


def test_resolved_mention_becomes_typed_birthday_target(router):
    utterance = normalize_utterance("bursdag <@42> 15.05")
    context = RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=7),
        author=ResolvedMention(user_id=7, display_name="Kari"),
        mentions=(ResolvedMention(user_id=42, display_name="Ola"),),
    )
    result = router.route_utterance(
        utterance,
        routing_context=context,
    )
    assert result.intent is BotIntent.BIRTHDAY_CREATE
    assert result.payload["birthday"] == {
        "action": "add",
        "user_id": 42,
        "display_name": "Ola",
        "day": 15,
        "month": 5,
    }
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_birthday_commands.py -q
~~~

Expected: FAIL because only BIRTHDAY_EDIT is currently routed.

- [ ] **Step 2: Route birthday create and list**

- Route BIRTHDAY_CREATE and BIRTHDAY_LIST before generic calendar NLP.
- Only a bounded first-person birthday subject—`bursdagen min`, `min bursdag`, `eg/jeg har bursdag`, or `my birthday`—targets the author. Match the complete birthday clause after the bot invocation/date/edit verb is removed; a standalone `min|my|eg|jeg` anywhere else is never identity evidence. Relational possessives and free-name clauses such as `min venn ...`, `bursdagen til min søster ...`, and `my sister's birthday ...` return CLARIFY.
- A real Discord mention targets the matching `ResolvedMention` from the required `RoutingContext`; `parse_birthday_command(content, *, routing_context: RoutingContext)` has no optional/ambient identity fallback and never resolves identity from raw display-name text.
- An arbitrary name without a resolvable mention returns CLARIFY.
- Extract side-effect-free validate_birthday_date(day, month, year=None) at module scope in features/birthday_manager.py. BirthdayManager._validate_birthday_date() delegates to it for compatibility, while the parser/router call the pure function without constructing a manager. Do not apply TemporalResolver’s next-occurrence year to birth data.
- Verify the typed-dispatch lane's existing handler methods call the transactional BirthdayManager APIs and map all `BirthdayWriteResult` fields into delivery-attached `DispatchOutcome`; do not edit or recreate those adapters here. A persisted GCal-pending marker is mutated but terminal, never a retryable success.
- Preserve the manager’s user-id keyed storage.
- Reuse awaited create-only `BirthdayManager.create_birthday_result(...)` and `edit_birthday_by_user_id_result(guild_id, user_id, day, month, year=None)` from Task 6; fail the prerequisite gate if either is absent. An existing exact user record returns `already_exists` and must use edit instead. Keep synchronous `edit_birthday_by_user_id(...)`, upserting bool-returning `add_birthday(...)`, and dict-returning `edit_birthday(guild_id, name, day, month, year=None)` only as already-tested offline compatibility wrappers that reject in a running event loop.
- Update tests/nlu_harness.py so MENTIONED_USER_42 builds RoutingContext with ResolvedMention(42, "Ola").
- Add paired invalid-date tests through parse_birthday_command() and BirthdayManager.add_birthday() for 31.02 and a valid leap-day case.

- [ ] **Step 3: Require an explicit poll trigger**

parse_poll_command() must:

- require avstemning, poll, lag avstemning, lag poll, create poll, or ny poll;
- never infer a poll solely from slash count;
- split choices only from the tail after the question;
- support comma, slash, or eller/or separators;
- trim and deduplicate choices while preserving order;
- require two through ten nonblank options;
- use Ja/Nei only for an explicit poll question without listed options;
- reject URLs, filesystem-looking paths, fractions, and ordinary either/or questions without a poll trigger.
- parse_vote() must accept both a bare active-poll number and explicit “stem 1” / “vote 1”, matching displayed help.

Pin:

~~~python
@pytest.mark.parametrize(
    "text",
    [
        "forkort https://example.com/a/b",
        "les /var/log/system.log",
        "hva er 1/2 + 1/4?",
        "pizza eller burger?",
    ],
)
def test_non_poll_slashes_and_choices_do_not_create_poll(text):
    assert parse_poll_command(text) is None


def test_explicit_comma_poll_matches_help_copy():
    parsed = parse_poll_command(
        "lag avstemning: Hva spiser vi? pizza, burger, taco"
    )
    assert parsed["question"] == "Hva spiser vi?"
    assert parsed["options"] == ["pizza", "burger", "taco"]
~~~

- [ ] **Step 4: Require watchlist domain evidence**

Verify the routing-owned watchlist parser: generic “legg til”, “fjern”, and “endre” must not produce WATCHLIST without watchlist, film, serie, movie, show, or one of the finite media frames “husk å se”, “hugs å sjå”, and “remember to watch”. A bare “se/sjå/watch” is not sufficient evidence. Preserve quoted titles. Add paired positive/negative corpus cases; repair the routing prerequisite rather than creating a second parser here.

- [ ] **Step 5: Route profile status and activity through a typed payload**

Extend the stable envelope map only with `BotIntent.PROFILE: "profile"`. Add a pure `parse_profile_command()` that emits a two-key dictionary whose `action` is exactly `status`, `playing`, or `watching` and whose `value` is nonblank and at most 100 characters. Validate it as `ProfilePayload`, route it with `IntentRisk.MUTATING`, and pass only the inner payload to `ProfileHandler`; sentinel-content tests must prove the handler never reparses `message.content`.

- [ ] **Step 6: Prove prerequisite-owned measured language forms**

Add paired corpus rows for these already-owned forms; if a form is absent, stop and finish the routing, typed-reminder, or model-pending prerequisite that owns it rather than reimplementing it in this lane:

- help: “kva kan du gjere”, “ka kan du gjør”, “what can you do”;
- reminder: hugs, påminning, minn mæ, klokka;
- calendar: i morgon, imårra, neste/førstkommende weekdays;
- list/read forms in Bokmål, Nynorsk, English: `vis kalenderen`, `vis påminningar`, and `show reminders`.

Confirmation forms `gjer det`, `gjør det`, and `japp`, plus cancellation forms `avbryt` and `dropp det`, stay in the dedicated `PendingActionStore.resolve()` parameterized tests. They are control utterances whose expected result depends on authoritative pending state, so the stateless routing corpus must not duplicate them.

Every positive form gets a nearby conversational negative. Do not add broad one-token aliases such as status, helse, legg til, or skjer without domain/action constraints.

- [ ] **Step 7: Make every help example executable**

Define `HelpExample` in `core/help_registry.py` with `id`, `category`, `locale`, `display_phrase`, `route_phrase`, `intent`, `operation`, `expected_payload_json`, `risk_level`, `requires_confirmation`, and `fixture`. Locale is `nb`, `nn`, or `en`; rendering maps `nb` and `nn` to the existing Norwegian catalog and `en` to English while preserving the phrase. Category titles/descriptions live in an ordered `HelpCategory` registry, not renderers. `tests/test_help_route_parity.py` routes every row through its production-harness fixture and asserts exact intent, typed operation, payload, risk, and confirmation. Include memory view/export/delete, weather via the dashboard operation, typed profile status/activity, and calendar-auth initiation; remove the unproved handwritten `les URL` claim because no typed article-read operation exists. Do not include auth codes, live URLs, destructive bulk clear, unresolved identities, or provider syntax.

- [ ] **Step 8: Run and commit**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_birthday_commands.py \
  tests/test_help_route_parity.py \
  tests/test_poll_target.py \
  tests/test_watchlist_scope.py \
  tests/test_intent_router.py \
  tests/test_nlu_contract.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
git add features/birthday_manager.py features/poll_manager.py \
  core/help_registry.py core/intent_keywords.py core/intent_payloads.py \
  core/intent_router.py core/message_monitor.py \
  features/help_handler.py features/profile_commands.py \
  features/profile_handler.py memory/localization.py web_console/dashboard.py \
  tests/test_birthday_commands.py tests/test_help_route_parity.py \
  tests/test_help_handler.py tests/test_profile_routing.py \
  tests/test_parse_once_dispatch.py tests/test_console_server.py \
  tests/test_poll_target.py tests/test_watchlist_scope.py \
  tests/nlu_harness.py tests/fixtures/nlu_contract_v1.jsonl
git commit -m "feat: align natural phrases with supported actions"
~~~

Expected: PASS and every displayed canonical help example routes to the advertised intent.

---

### Task 13: Add privacy-safe NLU observability, CI gates, and operator docs

**Objective:** Make recognition quality and safety regressions visible without storing user language, and make the offline contract a required CI artifact.

**Interfaces:**

- Consumes: aggregate router, arbiter, pending-store, action-parser, and reminder-checker counters.
- Produces: persisted cumulative stats, authenticated console state, CI report artifact, and accurate documentation.
- Privacy boundary: no utterances, names, titles, URLs, slots, model text, or pending summaries.

**Files:**

- Modify: core/nlu_metrics.py
- Create: tests/test_nlu_metrics_privacy.py
- Create: tests/test_monitor_lifecycle.py
- Modify: core/message_monitor.py:244-275,355-391,489-521,1379-1418
- Modify: cal_system/reminder_checker.py
- Modify: web_console/console_store.py
- Modify: web_console/state_collector.py:127-260,629-638
- Modify: web_console/server.py
- Modify: tests/test_console_server.py
- Modify: tests/test_message_monitor_routing.py
- Modify: tests/test_reminder_runtime.py
- Modify: .github/workflows/ci.yml:42-63
- Modify: README.md
- Modify: docs/ARCHITECTURE.md
- Modify: docs/QUICK_REFERENCE.md
- Modify: docs/DEVELOPMENT.md
- Modify: docs/LM_STUDIO_SETUP.md
- Modify: docs/OPENROUTER_INTEGRATION.md
- Modify: docs/DOCUMENTATION.md
- Modify: docs/MODEL_RECOMMENDATIONS.md
- Modify: tests/README_TESTING.md

- [ ] **Step 1: Write aggregate-only metrics tests**

~~~python
def test_nlu_metrics_never_persist_content(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    sensitive = "Ring Kari https://secret.example/token kl 14"
    metrics = NLUMetrics()
    metrics.record_decision(
        intent="reminder_create",
        source="semantic",
        outcome="executed",
    )
    with pytest.raises(TypeError):
        metrics.record_decision(
            intent="reminder_create",
            source="semantic",
            outcome="executed",
            raw_text=sensitive,
        )
    store.persist_nlu_metrics(metrics.snapshot())
    persisted = (tmp_path / "stats.json").read_text(encoding="utf-8")
    assert sensitive not in persisted
    assert "Kari" not in persisted
    assert "secret.example" not in persisted
    assert '"intent=reminder_create|source=semantic|outcome=executed": 1' in persisted
~~~

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_nlu_metrics_privacy.py -q
~~~

Expected: FAIL because `ConsoleStore` does not yet accept `data_dir`, persist the nested NLU snapshot, or write schema v3.

- [ ] **Step 2: Add bounded aggregate counters**

Retain the exact nested, bounded `NLUMetrics` API frozen in Task 2: `record_decision(*, intent, source, outcome)`, `record_rejection(code)`, `record_pending(event)`, `record_action_result(result)`, `record_parser_error(parser, code)`, `record_legacy_payload_fallback(family)`, `record_reminder_delivery(event, *, error_code=None)`, `merge_snapshot(delta)`, and `snapshot() -> dict[str, dict[str, int]]`. Record cumulative counts for:

- routed intent and source;
- deterministic candidates emitted/rejected;
- negated/meta/quoted mutation blocks;
- clarifications staged/resolved/expired;
- semantic proposals accepted/rejected by machine error code;
- confirmations completed/canceled/failed;
- parser errors by parser name;
- legacy payload fallbacks;
- reminder delivery health counters.

Do not add a raw_text parameter to the production recorder. Accept enum values or allowlisted strings only. Bucket unknown intent, source, outcome, parser name, rejection code, and reminder error code into other before they become Counter keys. Persist only known keys and nonnegative integers.

Make ConsoleStore.__init__(*, data_dir: Path | None = None) use the current configured console directory when omitted and the injected directory in tests. Extend save_stats() with keyword-only nlu_stats and reminder_runtime arguments so intent, rate-limit, NLU, and reminder updates share one atomic read/merge/write transaction. Hold the existing RLock across the complete transaction by using an internal unlocked loader while the lock is held. Keep persist_nlu_metrics(delta) as a testable compatibility wrapper over the same atomic merge. Merge only known nonnegative integer deltas under an nlu key, and bump STATS_SCHEMA_VERSION from 2 to 3. A tolerant v2-to-v3 loader adds empty nlu/reminder_runtime sections without discarding intent or rate-limit totals. An unsupported future version makes writes return false and leaves the original bytes unchanged; read-only status may return a bounded empty projection plus `unsupported_stats_schema`. The no-argument constructor remains compatible.

Add tests that inject the same sensitive string into every nominal dimension and assert only other is incremented. Also prove untagged and disallowed messages leave metrics unchanged and raw reminder exceptions are reduced to bounded error codes.

- [ ] **Step 3: Wire idempotent persistence lifecycle**

MessageMonitor owns a cumulative in-process NLUMetrics, _last_persisted_nlu_stats, and _console_persist_lock: asyncio.Lock. In _persist_console_stats_once(), hold the async lock across:

1. snapshot current counters;
2. calculate nonnegative delta per allowlisted key against _last_persisted_nlu_stats;
3. await asyncio.to_thread() around one ConsoleStore.save_stats(...) batch containing intent, rate, NLU, and reminder deltas;
4. advance the baseline only after a successful write;
5. retain the old baseline after failure so the same delta is retried;
6. release the lock.

In `close()`, stop the reminder checker first, cancel and await every owned producer task including periodic persistence, clear the task registries, and only then acquire the same lock through one final `_persist_console_stats_once()` call. Set a final-flush flag so repeated close neither stops resources nor writes another delta. On first setup, hydrate the live NLU counters once from ConsoleStore and set the persisted baseline to that same snapshot; reconnect never rehydrates. This preserves cumulative readback across restart without writing old totals again. Add tests for one-time hydration, repeated no-change flush, increment delta, failed-write retry, restart readback, producer-cancellation increments included in the final flush, concurrent periodic/close attempts, and concurrent legacy+NLU save calls.

- [ ] **Step 4: Expose authenticated aggregate state**

Add detailed `nlu` and the exact typed reminder-checker health object to authenticated `/api/status`. Inject the same `ConsoleStore` through `ConsoleServer` and all endpoint collectors so restart tests never read the global store. Demo mode uses static mock aggregates. The unauthenticated `/health` projection retains exactly reminder status/running/stale/last_success_at and omits NLU, delivery/error counters, raw task items, persistence/calendar exception strings, raw `last_error`, and detailed reminder runtime. Reconstruct both endpoints from bounded projections rather than embedding existing raw dictionaries. Add server tests for authentication, exact schema, integer-only NLU counter leaves, allowlisted reminder metadata, restart persistence, and whole-endpoint redaction.

- [ ] **Step 5: Add the CI evaluation gate**

Split the current combined pytest step into a non-browser step, this NLU step, and a browser step. Place the evaluation after non-browser pytest and before browser pytest:

~~~yaml
      - name: Evaluate production NLU contract
        run: >
          python scripts/evaluate_nlu.py
          --corpus tests/fixtures/nlu_contract_v1.jsonl
          --report .artifacts/nlu-contract.json

      - name: Upload NLU contract report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nlu-contract
          path: .artifacts/nlu-contract.json
          if-no-files-found: error

      - name: Install Playwright Chromium
        run: python -m playwright install chromium
~~~

Place the explicit Playwright Chromium install after the offline evaluator/report upload and immediately before the separate frontend invocation.

- [ ] **Step 6: Update operator and architecture documentation**

Document:

- the proposal/arbitration/pending-action data flow;
- the difference between explicit deterministic adds, inferred writes, and destructive confirmations;
- guild and DM mention syntax for ja/nei/corrections;
- supported temporal expressions and default 09:00 date-only reminders;
- evaluated Bokmål/Nynorsk/dialect-adjacent forms without claiming general dialect coverage;
- the JSON action protocol and provider prompt-preservation rule;
- the offline NLU report command;
- legacy SAVE_EVENT tags and raw handler reparsing as compatibility-only paths scheduled for removal after one released migration window;
- excluded follow-up work: log retention, generic Google Calendar I/O, and deployment readiness.

Remove or correct help claims not present in the production corpus.

- [ ] **Step 7: Run the complete verification gate**

Check disk first:

~~~bash
df -h /System/Volumes/Data
~~~

Stop and report if free space is below 30 GiB. Otherwise run:

~~~bash
.venv312/bin/python -m compileall -q \
  -x '(^|/)(\.git|__pycache__|\.pytest_cache|\.venv312)(/|$)' .
.venv312/bin/python -m flake8 . \
  --exclude=.venv312,__pycache__,.git,.pytest_cache \
  --count --select=E9,F63,F7,F82 --show-source --statistics
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py
.venv312/bin/python -m pytest -q tests/test_console_frontend.py
git diff --check
~~~

Expected:

- compileall exits 0;
- flake8 reports zero selected errors;
- NLU evaluation exits 0 with every acceptance threshold satisfied;
- non-browser pytest passes;
- browser pytest passes after Chromium is installed;
- git diff --check is clean.

If Chromium is absent, run:

~~~bash
.venv312/bin/python -m playwright install chromium
.venv312/bin/python -m pytest -q tests/test_console_frontend.py
~~~

The browser install is the only network-requiring verification step and must be reported separately from the offline gate.

- [ ] **Step 8: Review the generated report and compatibility counters**

Run:

~~~bash
.venv312/bin/python - <<'PY'
import json
from pathlib import Path

from tests.nlu_harness import load_cases

report = json.loads(
    Path(".artifacts/nlu-contract.json").read_text(encoding="utf-8")
)
metrics = report["metrics"]
for name in (
    "parser_error_rate",
    "negative_mutation_false_positive_rate",
    "destructive_action_precision",
    "critical_action_recall",
    "labeled_payload_accuracy",
    "overall_exact_intent_accuracy",
):
    assert metrics[name]["defined"] is True
assert metrics["parser_error_rate"]["rate"] == 0
assert metrics["negative_mutation_false_positive_rate"]["rate"] == 0
assert metrics["destructive_action_precision"]["rate"] == 1
assert metrics["critical_action_recall"]["rate"] == 1
assert metrics["labeled_payload_accuracy"]["rate"] == 1
assert metrics["overall_exact_intent_accuracy"]["rate"] >= 0.98
assert all(
    locale["defined"] and locale["rate"] >= 0.95
    for locale in report["by_locale"].values()
)
serialized = json.dumps(report, ensure_ascii=False)
for case in load_cases(Path("tests/fixtures/nlu_contract_v1.jsonl")):
    assert case.text not in serialized


def object_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from object_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from object_keys(child)


for forbidden in {
    "text",
    "utterance",
    "title",
    "url",
    "slots",
    "model_response",
}:
    assert forbidden not in set(object_keys(report))
print("NLU contract report: PASS")
PY
~~~

Expected: NLU contract report: PASS.

- [ ] **Step 9: Commit**

~~~bash
git add core/nlu_metrics.py core/message_monitor.py \
  cal_system/reminder_checker.py web_console/console_store.py \
  web_console/state_collector.py web_console/server.py \
  tests/test_nlu_metrics_privacy.py tests/test_monitor_lifecycle.py \
  tests/test_message_monitor_routing.py tests/test_reminder_runtime.py \
  tests/test_console_server.py .github/workflows/ci.yml README.md \
  docs/ARCHITECTURE.md docs/QUICK_REFERENCE.md docs/DEVELOPMENT.md \
  docs/LM_STUDIO_SETUP.md docs/OPENROUTER_INTEGRATION.md \
  docs/DOCUMENTATION.md docs/MODEL_RECOMMENDATIONS.md \
  tests/README_TESTING.md
git commit -m "chore: gate and document natural-language behavior"
~~~

- [ ] **Step 10: Log implementation evidence to Obsidian**

After the final commit and verification, use the obsidian skill to append a concise project-note and daily-note entry containing the branch, exact HEAD, NLU report result, offline pytest result, separate browser result, compatibility paths still active, and explicit non-claims. Do not log utterances, model outputs, secrets, reminder titles, URLs, or user data.

---

## Final Review Checklist

- [ ] Every new behavior was introduced by a failing test before production code.
- [ ] BotIntent and IntentResult imports from core.intent_router remain compatible.
- [ ] Existing route(content, guild_id) callers still work.
- [ ] All candidates use control_text for action evidence and text for payload extraction.
- [ ] No negated, quoted, hypothetical, or meta mutation reaches a manager.
- [ ] Every destructive action requires a user-scoped confirmation.
- [ ] Every semantic destructive action has explicit action and domain evidence outside quotes before it can be staged.
- [ ] Every semantic state change requires confirmation.
- [ ] Explicit deterministic additive behavior remains compatible.
- [ ] Pending actions are isolated by guild, channel, and user and execute at most once.
- [ ] Invalid date/time values are rejected by parser and handler.
- [ ] Reminder parser, manager, checker, dashboard, and health use the same manager instance.
- [ ] Every handler/checker/presentation send reports shared tri-state delivery certainty; `UNKNOWN` is terminal and never causes a blind fallback or retry.
- [ ] Model prompts preserve the action and safety contract on LM Studio and OpenRouter.
- [ ] Conversation history is role-correct, scoped, expiry-cleaned, and contains the current turn once.
- [ ] Every canonical help example is covered by the production-router corpus.
- [ ] NLU metrics contain only bounded aggregate keys and integers.
- [ ] No live Discord, calendar, AI, search, or user-data mutation occurred during offline verification.
- [ ] Browser verification and offline verification are reported as separate claims.
- [ ] Legacy action tags and raw-payload fallback are documented as temporary compatibility paths.
- [ ] Excluded work remains excluded from this branch.

## Logical Milestone Order

Treat the task-level commits named in the five executable sub-plans as authoritative; do not squash work into the older illustrative thirteen-commit list. Preserve this dependency order while allowing each sub-plan's reviewed, reproducible commit boundaries:

1. routing-foundation Tasks 1–5;
2. typed-dispatch/reminder-runtime Tasks 1–8;
3. model-actions/pending/context Tasks 1–11;
4. natural-language feature-parity Tasks 1–7;
5. observability/release-gates Tasks 1–7.

At every boundary, run that sub-plan's prerequisite and focused gates before starting the next lane. Record actual commit SHAs in implementation evidence; this planning document does not predict them.

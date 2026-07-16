# Calendar Fact-Check Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make schedule-correctness concerns about known calendar entries produce a deterministic, source-aware repair conversation instead of generic feedback, while preserving the existing confirmation and stale-target safety boundary for every edit.

**Architecture:** A new read-only `CALENDAR_FACT_CHECK` intent recognizes bounded Bokmål, Nynorsk, and English concern statements. A separate exact-conversation, memory-only inquiry store binds one stable calendar snapshot and routes selection, search, direct correction, cancellation, and expiry before generic chat; web evidence is normalized and reduced by deterministic source policy, while any resulting `CALENDAR_EDIT` continues through the existing target freezer, confirmation card, mutation lock, and revalidation path.

**Tech Stack:** Python 3.12, stdlib `dataclasses`, `enum`, `json`, `re`, `hashlib`, `urllib.parse`, existing `TemporalResolver`, `SearchManager`, `BrowserManager`, AI connector protocol, `PendingTargetResolver`, `AIActionHandler`, pytest/pytest-asyncio, and the production NLU evaluator.

## Global Constraints

- Run every Python command with `.venv312/bin/python`; add no runtime dependency.
- Before a long build or full-suite loop run `df -h /System/Volumes/Data`; stop and report when free space is below `30Gi`.
- Preserve the mention gate and allowed-user/channel checks before normalization, routing, state creation, search, AI, metrics, or dispatch.
- The initial correctness concern, target selection, search, cancellation, expiry, conflict, insufficient evidence, and current-value verification are read-only.
- `feil`, `stemmer ikke`, `wrong`, and equivalent concern language never authorize a write.
- Only a scoped direct temporal reply or a supported source decision may construct `CALENDAR_EDIT`; both set `requires_confirmation=True` and use the existing target freeze, confirmation, claim, mutation lock, and stale-state revalidation path.
- Keep executable confirmation state in `PendingActionStore` and fact-check inquiry state in a separate `CalendarFactCheckStore`; neither store may inspect, confirm, cancel, replace, or mutate the other's entries.
- Existing executable pending resolution has priority over every fact-check continuation.
- Fact-check state is keyed by exact `ConversationKey`, has a ten-minute TTL, holds at most five candidates, is capped globally at 1,000 inquiries, and never survives process restart.
- Search at most three results. Pass only the selected inert title, stored year/date hint, and normalized source evidence; never pass Discord IDs, user memory, conversation history, credentials, cookies, descriptions, or unrelated calendar rows.
- Call `BrowserManager.fetch_page_content()` only after `utils.sanitizer.sanitize_url()` accepts the URL. Page text is optional because the current browser adapter returns `None`; search snippets must be sufficient or the result remains insufficient.
- Each source finding must bind to an existing result index, canonical `DD.MM.YYYY` date, canonical `HH:MM` time, an exact normalized excerpt of at most 160 characters, and an explanation of at most 240 characters.
- Trusted football domains are exactly `fotball.no`, `eliteserien.no`, `rbk.no`, and `fredrikstadfk.no`. A model cannot add a trusted domain or override source reduction.
- One trusted source with no trusted conflict, or two agreeing independent untrusted sites with no disagreement, may support a proposal. A disagreeing untrusted site is disclosed but does not override the trusted source; conflicting trusted sources always block. Evidence matching current state produces a read-only verification, never a no-op edit.
- User-facing text is Norwegian. Code names, enum values, payload keys, metric values, and error codes are English.
- Logs and persisted metrics contain only bounded intent/outcome/provider values, approved public domains or 12-character domain hashes, and counts; never raw utterances, titles, queries, URLs, excerpts, model output, page content, Discord IDs, or exception text.
- Do not modify `~/.codex/config.toml`, secrets, `.env` values, OAuth state, production `~/.hermes` data, or live calendar records during implementation tests.

---

## File and interface map

| File | Responsibility |
|---|---|
| `core/intent_models.py` | Adds the public read-only `CALENDAR_FACT_CHECK` intent. |
| `core/intent_payloads.py` | Defines and validates the exact `calendar_fact_check` envelope. |
| `core/calendar_fact_check_store.py` | Owns immutable target snapshots, exact conversation inquiry state, TTL, selection, cancellation, and bounded eviction. |
| `core/calendar_fact_check_recognition.py` | Owns pure concern-frame recognition and scoped continuation parsing. |
| `core/calendar_fact_check_evidence.py` | Owns normalized evidence, strict finding validation, trusted-domain policy, deterministic reduction, and privacy-safe domain labels. |
| `core/pending_targets.py` | Exposes read-only calendar target snapshot and revalidation helpers using confirmation-grade IDs/revisions. |
| `ai/calendar_fact_check_extractor.py` | Builds a history-free evidence-only extraction request and strictly parses one JSON response. |
| `features/search_manager.py` | Preserves the list-returning API and adds a per-request structured status for success, empty results, or provider unavailability. |
| `features/calendar_fact_check_manager.py` | Performs bounded search/fetch/extraction and returns one typed investigation outcome. |
| `features/calendar_fact_check_handler.py` | Resolves start/select/search/cancel and formats deterministic Discord copy. |
| `core/intent_router.py` | Routes initial concerns and scoped continuations after executable pending controls and before generic collectors. |
| `core/message_monitor.py` | Wires state/handler and hands supported edits back to the normal confirmation path. |
| `core/help_registry.py` / `tests/fixtures/nlu_contract_v1.jsonl` | Advertise and gate supported concern language in NB/NN/EN. |

Execution order is strict. Tasks 1–4 establish inert contracts, initial recognition, evidence policy, and inquiry state. Task 5 is the only network/model boundary. Tasks 6–7 integrate scoped continuations, Discord flow, and confirmation handoff. Task 8 expands the production contract and runs release-grade verification.

### Task 1: Add the typed read-only intent and payload boundary

**Files:**

- Modify: `core/intent_models.py`
- Modify: `core/intent_payloads.py`
- Modify: `core/intent_policy.py`
- Modify: `core/intent_thresholds.py`
- Modify: `core/intent_router.py`
- Create: `tests/test_calendar_fact_check_payload.py`

**Interfaces:**

- Produces `BotIntent.CALENDAR_FACT_CHECK` with value `calendar_fact_check`.
- Produces exact payloads for `start`, `select`, `search`, and `cancel` under envelope `calendar_fact_check`.
- Produces read-only risk, confidence threshold `0.95`, and payload metric family `calendar`.

- [ ] **Step 1: Write the failing payload contract tests**

Create `tests/test_calendar_fact_check_payload.py`:

~~~python
import pytest

from core.intent_models import BotIntent, IntentRisk
from core.intent_payloads import PayloadValidationError, validate_intent_payload
from core.intent_policy import classify_intent_risk


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ({"action": "start", "field": "schedule", "target": "Rosenborg - Fredrikstad"},
         {"action": "start", "field": "schedule", "target": "Rosenborg - Fredrikstad"}),
        ({"action": "select", "number": 2}, {"action": "select", "number": 2}),
        ({"action": "search", "field": "schedule", "target": "calendar-1"},
         {"action": "search", "field": "schedule", "target": "calendar-1"}),
        ({"action": "cancel"}, {"action": "cancel"}),
    ),
)
def test_calendar_fact_check_payload_is_exact(raw, expected):
    assert validate_intent_payload(BotIntent.CALENDAR_FACT_CHECK, raw) == expected
    assert classify_intent_risk(
        BotIntent.CALENDAR_FACT_CHECK,
        {"calendar_fact_check": expected},
    ) is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "raw",
    (
        {},
        {"action": "start", "field": "schedule"},
        {"action": "start", "field": "title", "target": "kampen"},
        {"action": "select", "number": 0},
        {"action": "select", "number": 1, "target": "kampen"},
        {"action": "search", "field": "schedule", "target": ""},
        {"action": "cancel", "target": "kampen"},
        {"action": "unknown"},
    ),
)
def test_calendar_fact_check_payload_rejects_partial_or_extra_state(raw):
    with pytest.raises(PayloadValidationError):
        validate_intent_payload(BotIntent.CALENDAR_FACT_CHECK, raw)
~~~

- [ ] **Step 2: Run the red test**

Run: `.venv312/bin/python -m pytest tests/test_calendar_fact_check_payload.py -q`

Expected: FAIL because `BotIntent.CALENDAR_FACT_CHECK` does not exist.

- [ ] **Step 3: Add the intent, payload type, and exact validator**

Add `CALENDAR_FACT_CHECK = "calendar_fact_check"` next to the calendar intents. Add this type and validator in `core/intent_payloads.py`:

~~~python
class CalendarFactCheckPayload(TypedDict, total=False):
    action: Literal["start", "select", "search", "cancel"]
    field: Literal["schedule"]
    target: str
    number: int


def _calendar_fact_check(
    raw: Mapping[str, Any], *, source: IntentSource
) -> dict[str, Any]:
    del source
    value = _mapping(raw, frozenset({"action", "field", "target", "number"}))
    action = value.get("action")
    allowed = {
        "start": {"action", "field", "target"},
        "select": {"action", "number"},
        "search": {"action", "field", "target"},
        "cancel": {"action"},
    }
    if not isinstance(action, str) or action not in allowed:
        _fail("wrong_action")
    if set(value) != allowed[action]:
        _fail("unknown_key")
    if action in {"start", "search"}:
        if value.get("field") != "schedule":
            _fail("wrong_action")
        target = _string(value.get("target"))
        if len(target) > 200:
            _fail("value_too_long")
        return {"action": action, "field": "schedule", "target": target}
    if action == "select":
        return {"action": "select", "number": _positive_int(value.get("number"))}
    return {"action": "cancel"}
~~~

Register it in `PayloadValue`, `INTENT_VALIDATORS`, and `ENVELOPE_KEYS`.

- [ ] **Step 4: Register risk, confidence, and payload metrics**

Add these exact entries:

~~~python
# core/intent_policy.py
BotIntent.CALENDAR_FACT_CHECK: IntentRisk.READ_ONLY,

# core/intent_thresholds.py
BotIntent.CALENDAR_FACT_CHECK: 0.95,

# core/intent_router.py, inside the calendar metric-family tuple
BotIntent.CALENDAR_FACT_CHECK,
~~~

- [ ] **Step 5: Run focused tests and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_payload.py tests/test_intent_models.py tests/test_confidence_thresholds.py -q
git add core/intent_models.py core/intent_payloads.py core/intent_policy.py core/intent_thresholds.py core/intent_router.py tests/test_calendar_fact_check_payload.py
git commit -m "feat: add calendar fact-check intent contract"
~~~

Expected: PASS before the commit is created.


### Task 2: Recognize bounded initial schedule concerns

**Files:**

- Create: `core/calendar_fact_check_recognition.py`
- Modify: `core/intent_router.py`
- Create: `tests/test_calendar_fact_check_routing.py`

**Interfaces:**

- Produces `parse_schedule_concern(utterance, semantics) -> str | None`.
- Initial concerns return the read-only `CALENDAR_FACT_CHECK(start)` payload. Scoped continuation routing is deliberately deferred until Task 7, after Task 4 provides bounded state.

- [ ] **Step 1: Write positive and negative recognition tests**

Create `tests/test_calendar_fact_check_routing.py` with these positive cases:

~~~python
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
~~~

Negative cases must include quoted text, fenced code, `Ola sa at ...`, hypothetical `hvis tidspunktet ...`, `tidspunktet ... er ikke feil`, explanatory `hvorfor er tidspunktet feil?`, no target, title-only correction, and unrelated uses of `feil`.

- [ ] **Step 2: Run initial routing tests red**

Run: `.venv312/bin/python -m pytest tests/test_calendar_fact_check_routing.py -q`

Expected: positive cases route to `AI_CHAT`.

- [ ] **Step 3: Implement the bounded concern grammar**

In `core/calendar_fact_check_recognition.py`, define one optional NB/NN/EN uncertainty prefix, schedule field terms, connectors `for|til|on`, a 1–200 character target, and suffixes `er feil|er galt|stemmer ikke|kan være feil|is wrong|doesn't look right|might be wrong`. Full-match the complete control text, require `SpeechAct.STATEMENT`, and reject quoted segments. Keep the grammar as compiled constants so the false-positive table remains reviewable.

- [ ] **Step 4: Add the initial candidate**

In the calendar collector, create a tier-30, specificity-3 candidate with confidence `0.99`, reason `calendar_fact_check_concern`, and payload:

~~~python
{
    "calendar_fact_check": {
        "action": "start",
        "field": "schedule",
        "target": target,
    }
}
~~~

Let existing payload validation and arbitration select it.

- [ ] **Step 5: Run initial-routing regressions and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_routing.py tests/test_pending_actions.py tests/test_statement_retraction_safety.py -q
git add core/calendar_fact_check_recognition.py core/intent_router.py tests/test_calendar_fact_check_routing.py
git commit -m "feat: route calendar fact-check conversations"
~~~

Expected: PASS, with the initial concern read-only and false positives inert.

### Task 3: Validate and reduce source-bound schedule evidence

**Files:**

- Create: `core/calendar_fact_check_evidence.py`
- Create: `tests/test_calendar_fact_check_evidence.py`

**Interfaces:**

- Produces `CalendarSearchEvidence`, `CalendarSourceFinding`, `CalendarEvidenceStatus`, `CalendarEvidenceDecision`, `CalendarSourcePolicy`, `parse_source_findings(raw, evidence)`, and `reduce_source_findings(findings, policy, current)`.

- [ ] **Step 1: Write strict parser and reducer tests**

Cover valid NFF evidence, invented index, duplicate JSON keys, extra object keys, non-finite JSON, invalid date/time, overlong excerpt/explanation, excerpt absent from evidence, date/time absent under accepted aliases, duplicate same-site findings, trusted agreement, trusted conflict, one untrusted source, two agreeing independent untrusted sites, untrusted disagreement, and evidence matching current schedule.

Representative valid assertion:

~~~python
raw = json.dumps({
    "findings": [{
        "source": 1,
        "date": "27.07.2026",
        "time": "19:00",
        "excerpt": "Rosenborg - Fredrikstad 27. juli 2026 kl. 19:00",
        "explanation": "NFF viser kampstart.",
    }]
})
findings = parse_source_findings(raw, evidence)
decision = reduce_source_findings(
    findings,
    CalendarSourcePolicy(),
    current=("26.07.2026", "09:00"),
)
assert decision.status is CalendarEvidenceStatus.SUPPORTED
assert (decision.date, decision.time) == ("27.07.2026", "19:00")
~~~

- [ ] **Step 2: Run evidence tests red**

Run: `.venv312/bin/python -m pytest tests/test_calendar_fact_check_evidence.py -q`

Expected: collection fails because the evidence module does not exist.

- [ ] **Step 3: Implement immutable evidence contracts**

~~~python
class CalendarEvidenceStatus(str, Enum):
    SUPPORTED = "supported"
    CURRENT = "current"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CalendarSearchEvidence:
    index: int
    title: str
    url: str
    body: str
    provider: str
    fetched_at: str
    published_at: str | None
    page_content: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarSourceFinding:
    source: int
    site_key: str
    trusted_domain: str | None
    date: str
    time: str
    excerpt: str
    explanation: str
    url: str


@dataclass(frozen=True, slots=True)
class CalendarEvidenceDecision:
    status: CalendarEvidenceStatus
    date: str | None = None
    time: str | None = None
    supporting: tuple[CalendarSourceFinding, ...] = ()
    conflicting: tuple[CalendarSourceFinding, ...] = ()
~~~

Use `json.loads` with `parse_constant` rejection and an `object_pairs_hook` that rejects duplicate keys. Require exactly `{"findings": list}`, at most three findings, and exactly `source,date,time,excerpt,explanation` in each finding.

- [ ] **Step 4: Bind evidence and define immutable trust policy**

Normalize whitespace before exact excerpt substring checks. Accept date aliases `DD.MM.YYYY`, `DD/MM/YYYY`, `YYYY-MM-DD`, Norwegian month names, and English month names; accept time aliases `HH:MM`, `HH.MM`, `kl HH:MM`, and `kl. HH:MM`. Canonical candidates remain `DD.MM.YYYY` and `HH:MM`.

~~~python
@dataclass(frozen=True, slots=True)
class CalendarSourcePolicy:
    trusted_domains: frozenset[str] = frozenset({
        "fotball.no",
        "eliteserien.no",
        "rbk.no",
        "fredrikstadfk.no",
    })
~~~

Derive `site_key` from `urlsplit(url).hostname`, lowercase it, and remove leading `www.`. A trusted match is only `host == trusted` or `host.endswith("." + trusted)`. For untrusted independence, conservatively collapse subdomains so two subdomains of one site never count twice.

- [ ] **Step 5: Implement deterministic reduction**

Group one finding per site and candidate. Apply rules in this order: conflicting trusted candidates -> `CONFLICTING`; one trusted candidate with no trusted conflict -> `CURRENT` or `SUPPORTED`, while retaining disagreeing untrusted findings for user-visible disclosure; two independent agreeing untrusted sites with no disagreement -> `CURRENT` or `SUPPORTED`; untrusted disagreement without a trusted winner -> `CONFLICTING`; otherwise -> `INSUFFICIENT`.

- [ ] **Step 6: Run evidence tests and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_evidence.py tests/test_sanitizer_security.py -q
git add core/calendar_fact_check_evidence.py tests/test_calendar_fact_check_evidence.py
git commit -m "feat: validate calendar schedule evidence"
~~~

Expected: PASS before the commit is created.


### Task 4: Bind immutable targets in a separate bounded inquiry store

**Files:**

- Create: `core/calendar_fact_check_store.py`
- Modify: `core/pending_targets.py`
- Create: `tests/test_calendar_fact_check_store.py`
- Modify: `tests/test_pending_targets.py`

**Interfaces:**

- Produces `CalendarFactCheckPhase`, `CalendarFactCheckTarget`, `CalendarFactCheckInquiry`, `CalendarFactCheckLookup`, and `CalendarFactCheckStore`.
- Produces `PendingTargetResolver.snapshot_calendar_fact_check_targets(query, *, reference_time, limit=6)`.
- Produces `PendingTargetResolver.revalidate_calendar_fact_check_target(snapshot, *, reference_time)`.

- [ ] **Step 1: Write failing store tests**

Create a mutable aware clock and cover one target, multiple selection, exact key isolation, expiry reported once, cancellation, replacement, global-cap eviction, invalid clocks, and invalid candidate counts. Use this central fixture:

~~~python
class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


def target(number: int) -> CalendarFactCheckTarget:
    return CalendarFactCheckTarget(
        stable_id=f"calendar-{number}",
        revision=f"revision-{number}",
        title=f"Kamp {number}",
        date="27.07.2026",
        time="19:00",
    )


def test_multiple_targets_require_bounded_selection():
    store = CalendarFactCheckStore(now_provider=Clock())
    key = ConversationKey(1, 2, 3)
    store.begin(key, (target(1), target(2)))
    selected = store.select(key, 2)
    assert selected.phase is CalendarFactCheckPhase.READY
    assert selected.targets == (target(2),)


def test_expiry_is_reported_once_and_payload_is_removed():
    clock = Clock()
    store = CalendarFactCheckStore(now_provider=clock)
    key = ConversationKey(1, 2, 3)
    store.begin(key, (target(1),))
    clock.value += timedelta(minutes=10)
    assert store.lookup(key).expired is True
    assert store.lookup(key).expired is False
~~~

- [ ] **Step 2: Run the store tests red**

Run: `.venv312/bin/python -m pytest tests/test_calendar_fact_check_store.py -q`

Expected: collection fails because `core.calendar_fact_check_store` does not exist.

- [ ] **Step 3: Implement immutable inquiry contracts**

Create these exact public contracts:

~~~python
class CalendarFactCheckPhase(str, Enum):
    CHOOSING_TARGET = "choosing_target"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class CalendarFactCheckTarget:
    stable_id: str
    revision: str
    title: str
    date: str
    time: str | None


@dataclass(frozen=True, slots=True)
class CalendarFactCheckInquiry:
    key: ConversationKey
    phase: CalendarFactCheckPhase
    targets: tuple[CalendarFactCheckTarget, ...]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CalendarFactCheckLookup:
    inquiry: CalendarFactCheckInquiry | None
    expired: bool = False
~~~

Implement `CalendarFactCheckStore` with `begin`, `lookup`, `select`, and `cancel`. Use a ten-minute default TTL, maximum five candidates, maximum 1,000 inquiries, aware clocks, one inquiry per exact key, and deterministic eviction by `(expires_at, created_at, guild_id, channel_id, user_id)`.

- [ ] **Step 4: Add read-only target snapshot tests**

In `tests/test_pending_targets.py`, cover exact-title and substring matches, zero matches, six-match overflow sentinel, duplicate stable IDs, malformed date/time, and revision changes. Assert:

~~~python
targets = resolver.snapshot_calendar_fact_check_targets(
    "Rosenborg - Fredrikstad",
    reference_time=NOW,
)
assert targets[0].stable_id == "calendar-1"
assert targets[0].title == "Rosenborg - Fredrikstad"
assert targets[0].date == "26.07.2026"
assert targets[0].time == "09:00"
assert resolver.revalidate_calendar_fact_check_target(
    targets[0], reference_time=NOW
) == targets[0]
~~~

- [ ] **Step 5: Implement target snapshot and revalidation**

Use `calendar.snapshot_target_items(reference_time=...)`, `_CALENDAR_FIELDS`, `_project`, `_digest`, and `_id`. Match an exact folded title before folded substring matches; return at most `limit` rows so six means “too many,” not five guessed results. Validate `DD.MM.YYYY`, allow `time=None`, validate non-null `HH:MM`, and require one unique stable ID.

- [ ] **Step 6: Run state tests and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_store.py tests/test_pending_targets.py -q
git add core/calendar_fact_check_store.py core/pending_targets.py tests/test_calendar_fact_check_store.py tests/test_pending_targets.py
git commit -m "feat: add scoped calendar fact-check state"
~~~

Expected: PASS before the commit is created.
### Task 5: Add history-free extraction and bounded investigation

**Files:**

- Create: `ai/calendar_fact_check_extractor.py`
- Create: `features/calendar_fact_check_manager.py`
- Modify: `features/search_manager.py`
- Create: `tests/test_calendar_fact_check_extractor.py`
- Create: `tests/test_calendar_fact_check_manager.py`
- Modify: `tests/test_search_manager.py`

**Interfaces:**

- Produces `CalendarFactCheckExtractor.extract(evidence) -> CalendarFactCheckExtraction`.
- Produces `CalendarFactCheckManager.investigate(target) -> CalendarEvidenceDecision`.
- Consumes existing `generate_response(...)`, `BrowserManager.fetch_page_content(...)`, `sanitize_url()`, and Task 3 evidence policy.
- Adds `SearchManager.search_with_status(...) -> SearchAttempt` while preserving `search(...) -> list[dict]` as a compatibility wrapper.

- [ ] **Step 1: Write extractor privacy and strictness tests**

Use a recording connector and assert:

~~~python
result = await extractor.extract((evidence_row,))
call = connector.calls[0]
assert call["temperature"] == 0.0
assert call["max_tokens"] == 800
assert call["history"] == ()
assert "DISCORD_ID_CANARY" not in json.dumps(call)
assert "UNRELATED_CALENDAR_CANARY" not in json.dumps(call)
assert result.status == "ok"
assert result.findings[0].date == "27.07.2026"
~~~

Also prove connector failure, empty response, malformed JSON, code fences, invented source index, and unsupported evidence return `CalendarFactCheckExtraction(status="unavailable", findings=())` without logging response text. A syntactically valid `{"findings":[]}` returns `status="ok"` so “no supported evidence” remains distinguishable from extraction failure.

- [ ] **Step 2: Implement the dedicated extractor**

Create these contracts and `CalendarFactCheckExtractor(connector)`:

~~~python
@dataclass(frozen=True, slots=True)
class CalendarFactCheckExtraction:
    status: Literal["ok", "unavailable"]
    findings: tuple[CalendarSourceFinding, ...] = ()
~~~

Call `generate_response` with `author_name="calendar-fact-check"`, `channel_type="INTERNAL_TOOL"`, `is_mention=False`, `temperature=0.0`, `max_tokens=800`, `history=()`, evidence-only JSON context, and a fixed system prompt that demands exactly:

~~~json
{"findings":[{"source":1,"date":"DD.MM.YYYY","time":"HH:MM","excerpt":"exact source excerpt","explanation":"bounded explanation"}]}
~~~

Return the unavailable result on connector, parse, or validation failure. Return `status="ok"` only after the strict parser accepts the complete response. Log only `calendar_fact_check_extraction outcome=<bounded-code> count=<0-3>`.

- [ ] **Step 3: Preserve search compatibility while exposing provider status**

Add this frozen value and a `search_with_status()` method in `features/search_manager.py`:

~~~python
@dataclass(frozen=True, slots=True)
class SearchAttempt:
    status: Literal["ok", "empty", "unavailable"]
    results: tuple[dict, ...]
    provider: Literal["tavily", "google", "duckduckgo"] | None
~~~

Refactor the existing fallback loop once: `ok` means normalized results were returned, `empty` means at least one provider completed successfully with no results, and `unavailable` means every configured/importable provider failed. Keep `search()` as:

~~~python
async def search(
    self,
    query: str,
    max_results: int = 3,
    region: str = "no-no",
) -> list[dict]:
    attempt = await self.search_with_status(
        query,
        max_results=max_results,
        region=region,
    )
    return list(attempt.results)
~~~

Extend `tests/test_search_manager.py` to prove the three statuses, fallback precedence, the three-result cap, and unchanged `search()` behavior. Do not store status on the manager instance; concurrent requests must remain independent.

- [ ] **Step 4: Write bounded manager tests**

Cover exactly three search results, no results, provider exception, `sanitize_url()` rejection, optional page fetch, fetch exception, 6,000-character per-page cap, 18,000-character total cap, extractor failure, and every reducer status. Assert the query contains only selected title/year/date and is never logged.

- [ ] **Step 5: Implement the manager contract**

~~~python
class CalendarFactCheckManager:
    def __init__(
        self,
        *,
        search_manager: SearchManager,
        browser_manager: BrowserManager,
        extractor: CalendarFactCheckExtractor,
        source_policy: CalendarSourcePolicy | None = None,
    ) -> None:
        self.search_manager = search_manager
        self.browser_manager = browser_manager
        self.extractor = extractor
        self.source_policy = source_policy or CalendarSourcePolicy()

    async def investigate(
        self,
        target: CalendarFactCheckTarget,
    ) -> CalendarEvidenceDecision:
        attempt = await self.search_manager.search_with_status(
            build_calendar_fact_check_query(target),
            max_results=3,
            region="no-no",
        )
        if attempt.status == "unavailable":
            return CalendarEvidenceDecision(CalendarEvidenceStatus.UNAVAILABLE)
        evidence = await self._collect_public_evidence(attempt.results[:3])
        if not evidence:
            return CalendarEvidenceDecision(CalendarEvidenceStatus.INSUFFICIENT)
        extraction = await self.extractor.extract(evidence)
        if extraction.status == "unavailable":
            return CalendarEvidenceDecision(CalendarEvidenceStatus.UNAVAILABLE)
        return reduce_source_findings(
            extraction.findings,
            self.source_policy,
            current=(target.date, target.time),
        )
~~~

Implement the shown methods plus `build_calendar_fact_check_query()` and `_collect_public_evidence()` in the same module. The reducer accepts `current: tuple[str, str | None]`. Normalize only documented metadata; fetch sequentially for at most three accepted public URLs; keep at most 6,000 page characters per result. Return `UNAVAILABLE` on `SearchAttempt(status="unavailable")`, `INSUFFICIENT` on no valid findings, otherwise the deterministic decision.

- [ ] **Step 6: Add privacy-safe investigation logging**

Log approved trusted domains verbatim. Log every other site as `sha256(site_key).hexdigest()[:12]`. Provider names come only from `tavily|google|duckduckgo|other`. Caplog canaries must prove query, title, URL, page body, excerpt, model output, exception message, and Discord/user canaries are absent.

- [ ] **Step 7: Run focused tests and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_extractor.py tests/test_calendar_fact_check_manager.py tests/test_search_manager.py -q
git add ai/calendar_fact_check_extractor.py features/calendar_fact_check_manager.py features/search_manager.py tests/test_calendar_fact_check_extractor.py tests/test_calendar_fact_check_manager.py tests/test_search_manager.py
git commit -m "feat: investigate calendar schedules safely"
~~~

Expected: PASS with zero network calls before the commit is created.

### Task 6: Handle start, selection, search, cancellation, and deterministic copy

**Files:**

- Create: `features/calendar_fact_check_handler.py`
- Modify: `core/message_monitor.py`
- Create: `tests/test_calendar_fact_check_handler.py`
- Modify: `tests/test_message_monitor_routing.py`

**Interfaces:**

- Produces `CalendarFactCheckFlow(text, proposed_route=None, clear_after_staged=False)`.
- Produces `CalendarFactCheckHandler.handle(payload, routing, *, reference_time)`.
- `MessageMonitor` owns one store, extractor/manager, and handler; the router receives the same store.

- [ ] **Step 1: Write handler outcome tests**

Cover zero matches, one match, missing current time, two-to-five matches, more than five, invalid/valid selection, cancellation, stale target before search, supported change, current-value evidence, conflict, insufficient evidence, and unavailable investigation.

~~~python
flow = await handler.handle(
    {"action": "start", "field": "schedule", "target": "Rosenborg - Fredrikstad"},
    routing,
    reference_time=NOW,
)
assert flow.proposed_route is None
assert "Rosenborg - Fredrikstad" in flow.text
assert "26.07.2026 kl. 09:00" in flow.text
assert "sjekke riktig tidspunkt" in flow.text
assert store.lookup(routing.key).inquiry is not None
~~~

- [ ] **Step 2: Implement flow and handler contracts**

~~~python
@dataclass(frozen=True, slots=True)
class CalendarFactCheckFlow:
    text: str
    proposed_route: IntentResult | None = None
    clear_after_staged: bool = False


class CalendarFactCheckHandler:
    def __init__(self, monitor, manager: CalendarFactCheckManager) -> None:
        self.monitor = monitor
        self.manager = manager

    async def handle(
        self,
        payload: Mapping[str, object],
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> CalendarFactCheckFlow:
        action = payload["action"]
        handlers = {
            "start": self._start,
            "select": self._select,
            "search": self._search,
            "cancel": self._cancel,
        }
        try:
            handler = handlers[action]
        except (KeyError, TypeError) as exc:
            raise ValueError("wrong_action") from exc
        return await handler(payload, routing, reference_time=reference_time)
~~~

Implement `_start`, `_select`, `_search`, and `_cancel` directly below the shown dispatcher. Each helper receives the validated payload plus `routing` and `reference_time`, and every branch returns `CalendarFactCheckFlow`.

Use `neutralize_discord_text()` for titles/display fields. Show source links only after `sanitize_url()`; wrap them as Discord autolinks and percent-encode `@`, `<`, `>`, CR, and LF. Never place a URL in a pending summary or guard.

- [ ] **Step 3: Construct supported edits without dispatching**

For `SUPPORTED`, compare evidence against the revalidated snapshot and create:

~~~python
IntentResult(
    BotIntent.CALENDAR_EDIT,
    1.0,
    {"calendar_edit": {"target": target.stable_id, "changes": changes}},
    "calendar_fact_check_supported_edit",
    risk=IntentRisk.MUTATING,
    requires_confirmation=True,
)
~~~

Include only changed fields and return `clear_after_staged=True`. `CURRENT`, `CONFLICTING`, `INSUFFICIENT`, and `UNAVAILABLE` return targeted read-only text with no route.

- [ ] **Step 4: Wire the store, manager, router, and handler**

After `PendingActionStore` construction, create `CalendarFactCheckStore(now_provider=clock_now)` and pass it to `IntentRouter(calendar_fact_checks=...)`. Register the handler using existing search/browser managers and `CalendarFactCheckExtractor(self.hermes)`; when `self.hermes is None`, use an extractor that returns `CalendarFactCheckExtraction(status="unavailable")` so initial deterministic behavior remains available while an attempted investigation receives the targeted unavailable response.

- [ ] **Step 5: Dispatch flows before generic AI**

In `_process_route_impl`, validate the typed payload and call the handler. Send `flow.text` with `_send_route_text` if there is no proposed route. Otherwise recursively process `flow.proposed_route` with `visible_text=flow.text`. Clear the inquiry only when the recursive decision is `staged`, the confirmation was delivered, and the matching ready pending confirmation exists; preserve it after failed/unknown presentation.

- [ ] **Step 6: Run handler/monitor tests and commit**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_fact_check_handler.py tests/test_message_monitor_routing.py -q
git add features/calendar_fact_check_handler.py core/message_monitor.py tests/test_calendar_fact_check_handler.py tests/test_message_monitor_routing.py
git commit -m "feat: handle calendar fact-check flow"
~~~

Expected: PASS; initial and investigation failures never call generic fallback.


### Task 7: Route scoped continuations and complete confirmation lifecycle isolation

**Files:**

- Modify: `core/calendar_fact_check_recognition.py`
- Modify: `core/intent_router.py`
- Modify: `core/message_monitor.py`
- Modify: `features/calendar_fact_check_handler.py`
- Create: `tests/test_calendar_fact_check_flow.py`
- Modify: `tests/test_ai_action_flow.py`

**Interfaces:**

- Produces `FactCheckContinuation(kind, number=None, changes=None, clarification=None)`.
- Direct routes use reason `calendar_fact_check_direct_edit`; supported search routes use `calendar_fact_check_supported_edit`.
- Existing executable pending resolution always wins. Inquiry state clears only after a delivered confirmation is staged.

- [ ] **Step 1: Write scoped continuation tests**

Cover exact key isolation; search phrases `sjekk`, `ja, finn ut av det`, `kan du undersøke?`, and `look it up`; numeric/ordinal selection; cancellation; unrelated messages; ready-vs-choosing phase; invalid choice; expired continuation; direct time/date/date+time; ambiguous English time; invalid/DST-impossible time; and executable pending priority.

Use this exact result contract:

~~~python
@dataclass(frozen=True, slots=True)
class FactCheckContinuation:
    kind: Literal["select", "search", "cancel", "direct", "expired"]
    number: int | None = None
    changes: Mapping[str, str] | None = None
    clarification: str | None = None
~~~

- [ ] **Step 2: Implement continuation classification after pending controls**

After existing `_pending_result(...)`, consult `CalendarFactCheckStore.lookup(key)`. Convert recognized selection/search/cancel continuations into typed `CALENDAR_FACT_CHECK` payloads. Invalid selection/direct time and expired recognized continuations return targeted `CLARIFY`; unrelated text continues through ordinary collectors without consuming state.

Parse direct temporal evidence with `TemporalResolver`. Accept only temporal evidence plus bounded fillers. A time-only reply emits only `changes.time`; a date-only reply emits only `changes.date`; date+time emits both. Validate merged stored date/time to catch Oslo DST impossibilities. Bare `6` remains ambiguous unless `am`, `pm`, or 24-hour syntax makes it exact.

- [ ] **Step 3: Write end-to-end message flow tests**

Create `tests/test_calendar_fact_check_flow.py` for:

1. concern -> deterministic current schedule question without AI;
2. ambiguity -> numbered selection -> selected schedule question;
3. concern -> search -> trusted evidence -> existing confirmation card;
4. concern -> `klokka 18` -> time-only confirmation;
5. concern -> full date/time -> two-field confirmation;
6. `ja` executes only the frozen edit;
7. `nei` returns `Avbrutt.` and calendar remains unchanged;
8. target changes before search, before staging, and before confirmation;
9. guild/channel/user/DM isolation;
10. send failure/unknown never leaves an unseen edit confirmable;
11. unrelated turn does not consume inquiry;
12. expired continuation returns targeted expiry copy.

Time-only proof:

~~~python
pending = monitor.pending_actions.peek(KEY)
assert pending is not None
assert pending.routes[0].payload == {
    "calendar_edit": {
        "target": "calendar-1",
        "changes": {"time": "18:00"},
    }
}
assert monitor.calendar.snapshot_pending_items(reference_time=NOW)[0]["date"] == "26.07.2026"
~~~

- [ ] **Step 4: Make inquiry settlement delivery-aware**

After recursive processing of a direct or supported edit, clear the inquiry only if decision outcome is `staged`, delivery state is `DELIVERED`, and `PendingActionStore.peek(key)` contains the matching ready confirmation. Retain the non-executable inquiry after failed or unknown presentation.

- [ ] **Step 5: Revalidate at every boundary**

Call `revalidate_calendar_fact_check_target()` immediately before search and before constructing an edit. Then use existing `PendingTargetResolver.freeze()` before presentation and `revalidate()` under the confirmed mutation lock. Map missing/changed/duplicate/invalid targets to “kalenderoppføringen har endret seg; start på nytt.”

- [ ] **Step 6: Prove both stores remain independent**

In `tests/test_ai_action_flow.py`, prove executable pending state claims `ja`, `nei`, numeric choices, and correction text first; completing/canceling executable pending state does not alter an unrelated inquiry; canceling an inquiry does not alter executable pending state.

- [ ] **Step 7: Run lifecycle regressions and commit**

~~~bash
.venv312/bin/python -m pytest   tests/test_calendar_fact_check_flow.py   tests/test_ai_action_flow.py   tests/test_pending_actions.py   tests/test_pending_targets.py   tests/test_mutation_commit_contract.py -q
git add core/calendar_fact_check_recognition.py core/intent_router.py core/message_monitor.py features/calendar_fact_check_handler.py tests/test_calendar_fact_check_flow.py tests/test_ai_action_flow.py
git commit -m "feat: complete calendar fact-check confirmations"
~~~

Expected: PASS with no edit before explicit confirmation.

### Task 8: Expand executable help, NLU gates, privacy proof, and release verification

**Files:**

- Modify: `core/help_registry.py`
- Modify: `tests/nlu_harness.py`
- Modify: `tests/fixtures/nlu_contract_v1.jsonl`
- Modify: `tests/test_nlu_contract.py`
- Modify: `tests/test_help_route_parity.py`
- Create: `tests/test_calendar_fact_check_privacy.py`
- Modify: `docs/COMMANDS.md`
- Modify: `docs/superpowers/specs/2026-07-16-calendar-fact-check-design.md`
- Create during execution: `docs/superpowers/plans/2026-07-16-calendar-fact-check-implementation-checkpoint.md`

**Interfaces:**

- Adds `calendar_fact_check` to `EVAL_FAMILIES` and the production report.
- Adds executable NB/NN/EN help examples for read-only `CALENDAR_FACT_CHECK(start)`.
- Produces a checkpoint with exact commits, commands, counts, CI/deploy/live evidence, and explicit non-claims.

- [ ] **Step 1: Add executable help cases**

Add these examples with `EvalFixture.CALENDAR_TITLE_MEETING`, read-only risk, and no confirmation:

~~~python
_example("cal-fact-check-nb", "kalender", "nb",
         "jeg tror tidspunktet for Møte med Ola er feil",
         BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check",
         '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}',
         RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
_example("cal-fact-check-nn", "kalender", "nn",
         "eg trur tidspunktet for Møte med Ola er feil",
         BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check",
         '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}',
         RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
_example("cal-fact-check-en", "kalender", "en",
         "I think the time for Møte med Ola is wrong",
         BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check",
         '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}',
         RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
~~~

- [ ] **Step 2: Extend the production NLU contract**

Add `calendar_fact_check` to both `EVAL_FAMILIES` and `READ_ONLY` in `tests/nlu_harness.py`. Add positive NB/NN/EN rows plus negative quoted, negated, hypothetical, reported-speech, explanatory-question, title-field, missing-target, and unrelated-`feil` rows. Positive rows forbid `ai_chat` and `calendar_edit`; negative rows forbid every mutating/destructive calendar intent. Add a harness regression asserting the new intent is classified as read-only.

- [ ] **Step 3: Add privacy canaries**

Prove raw utterance, Discord IDs, unrelated rows, descriptions, memory, credentials, query, URL, page body, excerpt, model output, and exception bodies are absent from logs, metrics, extraction history, and source-domain labels. Assert inquiry snapshots contain only stable ID, revision, title, date, time, and timestamps.

- [ ] **Step 4: Run focused acceptance**

~~~bash
.venv312/bin/python -m pytest   tests/test_calendar_fact_check_payload.py   tests/test_calendar_fact_check_store.py   tests/test_calendar_fact_check_routing.py   tests/test_calendar_fact_check_evidence.py   tests/test_calendar_fact_check_extractor.py   tests/test_calendar_fact_check_manager.py   tests/test_calendar_fact_check_handler.py   tests/test_calendar_fact_check_flow.py   tests/test_calendar_fact_check_privacy.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Run repository validation**

Run `df -h /System/Volumes/Data` and stop below `30Gi`. Otherwise run:

~~~bash
.venv312/bin/python -m compileall -q ai cal_system core features memory utils web_console
.venv312/bin/python -m flake8 ai cal_system core features memory utils web_console tests   --exclude=.venv312,__pycache__,.git,.pytest_cache   --select=E9,F63,F7,F82
.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py
.venv312/bin/python -m pytest tests/test_console_frontend.py -q
.venv312/bin/python scripts/evaluate_nlu.py   --corpus tests/fixtures/nlu_contract_v1.jsonl   --report .artifacts/nlu-contract.json
.venv312/bin/python -m pip check
git diff --check
~~~

Expected: all tests pass; evaluator says `decision=would-pass`, includes the new family, and has zero parser errors and zero negative mutation false positives; remaining gates pass.

- [ ] **Step 6: Request exact-diff review**

Use `superpowers:requesting-code-review`. Resolve actionable P0–P2 findings, rerun affected focused tests, then rerun the complete validation set. Confirm no unrelated cross-domain correction framework entered the diff.

- [ ] **Step 7: Commit documentation and checkpoint**

~~~bash
git add core/help_registry.py tests/nlu_harness.py tests/fixtures/nlu_contract_v1.jsonl tests/test_nlu_contract.py tests/test_help_route_parity.py tests/test_calendar_fact_check_privacy.py docs/COMMANDS.md docs/superpowers/specs/2026-07-16-calendar-fact-check-design.md docs/superpowers/plans/2026-07-16-calendar-fact-check-implementation-checkpoint.md
git commit -m "test: gate calendar fact-check conversations"
~~~

- [ ] **Step 8: Push, CI, deploy, and run a zero-write live smoke only after execution approval**

Push the branch; record exact CI run and SHA; deploy only that successful SHA with `deploy/ansible-playbook.yml`; verify `/app/commit_hash.txt`, structured `/health`, Discord/monitor readiness, restart count, reminder runtime, and expected public-console auth redirect.

Have the owner send:

1. `@inebotten jeg er ganske sikker på at tidspunktet for Rosenborg - Fredrikstad er feil`
2. Verify current schedule and the investigate-or-correct question.
3. `@inebotten sjekk`
4. Verify source-backed copy and a normal confirmation card only with supported evidence.
5. `@inebotten nei`
6. Verify `Avbrutt.` and unchanged calendar state.

Do not confirm an edit in the release smoke.

---

## Final acceptance checklist

- [ ] Exact reported Bokmål no longer reaches generic feedback for a matching entry.
- [ ] Initial concern, selection, search, conflict, insufficient evidence, current verification, cancellation, and expiry are deterministic/read-only.
- [ ] Initial behavior works without AI or search providers.
- [ ] Search uses at most three results and optional sanitized page fetches.
- [ ] Findings are source-index/date/time/excerpt bound and reduction is deterministic.
- [ ] Weak, conflicting, or current-value evidence never stages an edit.
- [ ] Direct/supported corrections stage the existing confirmation card and never mutate before explicit `ja`.
- [ ] Target changes fail before search, before staging, and under the mutation lock.
- [ ] Inquiry and executable pending state remain exactly scoped and independent.
- [ ] Failed/unknown send never leaves an unseen edit confirmable.
- [ ] NB/NN/EN positives and false positives are in the production contract.
- [ ] Privacy canaries, focused/full tests, evaluator, compileall, fatal flake8, dependency integrity, and diff check pass.
- [ ] Checkpoint separates local, pushed, CI, deployed, and live-smoke evidence with explicit non-claims.

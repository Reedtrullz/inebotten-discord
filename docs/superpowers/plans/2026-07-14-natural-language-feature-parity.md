# Inebotten Natural-Language Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make birthday, poll, watchlist, help, and documented Norwegian-language forms route exactly as advertised without allowing broad parser triggers to steal ordinary conversation.

**Architecture:** This lane assumes the typed routing, payload, and evaluation contracts from the routing-foundation and typed-dispatch plans. Identity-sensitive birthday phrases are resolved only through `RoutingContext`; poll and watchlist parsers require explicit domain evidence; one typed help registry becomes the source for Discord help, localization rendering, the web commands page, and production-router parity tests. Every added dialect-adjacent positive receives a nearby negative in the NLU corpus.

**Tech Stack:** Python 3.12.13, dataclasses, enums, regular expressions, pytest/pytest-asyncio, the production NLU harness, Discord handler adapters, pure-Python dashboard rendering.

## Global Constraints

- Start only after `2026-07-14-natural-language-routing-foundation.md`, `2026-07-14-typed-dispatch-reminder-runtime.md`, and `2026-07-14-model-actions-pending-context.md` are complete on the execution branch. If any consumed symbol or prerequisite test is absent, stop and complete that owning plan; do not recreate it here.
- Run every Python command with `.venv312/bin/python`.
- Do not construct `MessageMonitor`, access live Discord, Google Calendar, search, URL-shortening, browser, weather, LM Studio, or OpenRouter services, or write under `~/.hermes` in this lane. Tests use the production-parser harness and in-memory fixtures only.
- Preserve the completed plans' exact `BotIntent`, `IntentResult`, `IntentRisk`, `RoutingContext`, typed payload, `TemporalResolver`, reminder-parser, and `PendingActionStore` contracts. Task 5 makes the only extension: it adds the `PROFILE -> "profile"` envelope and its validator without changing existing entries.
- `PendingActionStore.resolve()` exclusively owns confirmation, cancellation, ordinal selection, and correction phrases. `parse_reminder_command()` exclusively owns reminder action/temporal forms. This lane may add evaluation rows for those APIs but must not reimplement their phrase recognition.
- Every row in `HELP_EXAMPLES` is a frozen executable claim. It must assert intent, operation/action, typed payload, risk level, and confirmation behavior through the production router. No implementation step may delete or weaken a red row.
- Public help contains concrete examples only: no auth codes, secret/token-shaped text, destructive bulk-clear commands, unresolved identity names, unsafe global one-token aliases, or provider action-protocol syntax.
- All steps are one bounded 2–5 minute action. Split verification commands as written; do not combine them into a longer aggregate step.

## File Responsibility Map

| File | Responsibility in this lane |
|---|---|
| `features/birthday_manager.py` | Pure birthday date validation and resolved-identity command parsing |
| `features/birthday_handler.py` | Prerequisite-owned typed create/list/edit adapters; this lane verifies them but does not reimplement them |
| `features/poll_manager.py` | Explicit poll creation/vote parsing without slash or conversational false positives |
| `features/watchlist_manager.py` | Domain-scoped watchlist parsing with complete typed fields |
| `core/intent_payloads.py` | Task-5 `ProfilePayload` validator and `PROFILE` envelope extension |
| `features/profile_commands.py` | Pure anchored profile status/activity parser |
| `features/profile_handler.py` | Parse-once profile status/activity dispatch from typed payload only |
| `core/help_registry.py` | Immutable help categories/examples plus exact payload, operation, risk, and confirmation expectations |
| `features/help_handler.py` | Discord rendering from the registry only |
| `memory/localization.py` | Localized category titles/descriptions only; no duplicated command phrases |
| `web_console/dashboard.py` | Norwegian commands-page rendering from the same registry rows |
| `tests/nlu_harness.py` | In-memory production router, resolved author/mention fixtures, one fixed Oslo clock, and `route_help_example()` |
| `tests/fixtures/nlu_contract_v1.jsonl` | Positive/negative executable language contract without raw report content |
| `tests/test_help_route_parity.py` | Full intent/payload/operation/risk/confirmation parity for every help row |

---

### Task 1: Add pure birthday date and identity parsing

**Files:**

- Modify: `features/birthday_manager.py:37-125,224-285,474-531`
- Create: `tests/test_birthday_commands.py`
- Test: `tests/test_watchlist_birthday_edit.py`

**Interfaces:**

- Consumes: `datetime(year: int, month: int, day: int)` and the prerequisite async `BirthdayManager.edit_birthday_by_user_id_result(guild_id, user_id, day, month, year=None)` transactional behavior; the old synchronous name is offline compatibility only.
- Produces: `validate_birthday_date(day: int, month: int, year: int | None = None) -> None`; invalid dates raise the exact f-string `ValueError(f"Ugyldig bursdagsdato: {day}.{month}")`.

- [ ] **Step 1: Add failing pure-date tests (2–5 minutes)**

Add:

~~~python
@pytest.mark.parametrize(
    ("day", "month", "year"),
    [(31, 2, None), (0, 5, None), (1, 13, None), (29, 2, 2025)],
)
def test_validate_birthday_date_rejects_impossible_dates(day, month, year):
    with pytest.raises(ValueError, match="Ugyldig bursdagsdato"):
        validate_birthday_date(day, month, year)


def test_validate_birthday_date_accepts_yearless_leap_day():
    validate_birthday_date(29, 2)


def test_validate_birthday_date_accepts_leap_year():
    validate_birthday_date(29, 2, 2024)
~~~

- [ ] **Step 2: Prove the test is red (2–5 minutes)**

Run:

~~~bash
.venv312/bin/python -m pytest tests/test_birthday_commands.py -q
~~~

Expected: FAIL because `validate_birthday_date` is not exported.

- [ ] **Step 3: Extract the pure validator (2–5 minutes)**

Add above `BirthdayManager` and delegate the old method to it:

~~~python
def validate_birthday_date(day: int, month: int, year: int | None = None) -> None:
    try:
        datetime(year if year is not None else 2000, month, day)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ugyldig bursdagsdato: {day}.{month}") from exc


class BirthdayManager:
    def _validate_birthday_date(self, day, month, year=None):
        validate_birthday_date(int(day), int(month), int(year) if year is not None else None)
~~~

- [ ] **Step 4: Run the date tests green (2–5 minutes)**

Run the Task 1 command. Expected: PASS.

- [ ] **Step 5: Run manager compatibility tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_birthday_commands.py \
  tests/test_watchlist_birthday_edit.py -q
~~~

Expected: PASS, including the typed-dispatch lane's awaited `edit_birthday_by_user_id_result()` and offline-only name-based compatibility projection. Add an `rg` assertion that production handlers do not call the synchronous edit name. If the async API is absent, stop and finish the typed-dispatch prerequisite rather than recreating it here.

- [ ] **Step 6: Commit the pure validator slice (2–5 minutes)**

~~~bash
git add features/birthday_manager.py tests/test_birthday_commands.py
git commit -m "refactor: expose pure birthday date validation"
~~~

---

### Task 2: Route birthday create, list, and edit through resolved identity

**Files:**

- Modify: `features/birthday_manager.py:474-531`
- Modify: `core/intent_keywords.py`
- Modify: `core/intent_router.py`
- Modify: `core/message_monitor.py`
- Modify: `tests/nlu_harness.py`
- Modify: `tests/test_birthday_commands.py`
- Modify: `tests/fixtures/nlu_contract_v1.jsonl`

**Interfaces:**

- Consumes: `RoutingContext(key: ConversationKey, author: ResolvedMention, mentions: tuple[ResolvedMention, ...])`, Task 1 `validate_birthday_date()`, typed `BirthdayCreatePayload | BirthdayEditPayload | BirthdayListPayload`, `DispatchOutcome`, and all three prerequisite-owned `handle_birthday_create/list/edit(message, payload)` adapters.
- Produces: `BirthdayCommand` and `parse_birthday_command(content: str, *, routing_context: RoutingContext) -> BirthdayCommand`; this lane adds routes to the prerequisite handlers but does not modify or recreate those handlers.
- Produces for tests while preserving the routing-foundation protocol: `ProductionRouterAdapter.evaluate(text: str, *, guild_id: int | None) -> tuple[IntentResult, tuple[ParserName, ...]]` and `ProductionRouterAdapter.route_help_example(text: str) -> IntentResult`. Both are thin projections over one private production `evaluate_utterance()` call with the adapter-held fixture `RoutingContext`. Every harness fixture supplies author `ResolvedMention(7, "Kari")`, and `MENTIONED_USER_42` additionally supplies `ResolvedMention(42, "Ola")`. Every adapter also owns one fixed `2026-07-14T12:00:00+02:00` Oslo clock and passes it to every temporal parser.

- [ ] **Step 1: Add failing routing-context cases (2–5 minutes)**

Use the fixed `RoutingContext` from the master plan and assert the exact payloads:

~~~python
import pytest

from core.intent_models import BotIntent
from core.message_context import (
    ConversationKey,
    ResolvedMention,
    RoutingContext,
)


def author_context(
    *,
    mentions: tuple[ResolvedMention, ...] = (),
) -> RoutingContext:
    return RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=7),
        author=ResolvedMention(user_id=7, display_name="Kari"),
        mentions=mentions,
    )


@pytest.mark.parametrize(
    "text",
    [
        "bursdagen min er 15.05",
        "min bursdag er 15.05",
        "eg har bursdag 15.05",
        "jeg har bursdag 15.05",
        "my birthday is 15.05",
    ],
)
def test_first_person_birthday_targets_author(router, text):
    result = router.route(text, routing_context=author_context())
    assert result.intent is BotIntent.BIRTHDAY_CREATE
    assert result.payload["birthday"] == {
        "action": "add",
        "user_id": 7,
        "display_name": "Kari",
        "day": 15,
        "month": 5,
    }


def test_discord_mention_targets_only_resolved_mention(router):
    result = router.route(
        "bursdag <@42> 15.05",
        routing_context=author_context(mentions=(ResolvedMention(42, "Ola"),)),
    )
    assert result.payload["birthday"]["user_id"] == 42
    assert result.payload["birthday"]["display_name"] == "Ola"


def test_free_text_name_requires_clarification(router):
    result = router.route("Ola har bursdag 15.05", routing_context=author_context())
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
def test_non_author_subjects_never_bind_to_author(router, text):
    result = router.route(text, routing_context=author_context())
    assert result.intent is BotIntent.CLARIFY
    assert result.requires_confirmation is False
~~~

Also assert `vis bursdager` and `kven har bursdag snart?` route to `BIRTHDAY_LIST`, and an unknown raw mention id returns CLARIFY.

- [ ] **Step 2: Run the birthday router tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_birthday_commands.py -q
~~~

Expected: FAIL because only `BIRTHDAY_EDIT` is currently reachable.

- [ ] **Step 3: Add the bounded parser result (2–5 minutes)**

In `features/birthday_manager.py`, define:

~~~python
class BirthdayCommand(TypedDict, total=False):
    action: Required[Literal["add", "edit", "list", "clarify"]]
    user_id: int
    display_name: str
    day: int
    month: int
    year: int
    scope: Literal["all", "upcoming"]
    reason: str
~~~

`parse_birthday_command(content, *, routing_context)` must follow this exact order:

1. strip only the bot mention, never user mentions;
2. return `{"action":"list","scope":"upcoming"}` for bounded `snart|kommende|upcoming|soon` list phrases and `{"action":"list","scope":"all"}` for other bounded list/read phrases;
3. parse one `DD.MM[.YYYY]`, normalize two-digit years with the existing 50-year pivot, and call `validate_birthday_date`;
4. resolve exactly one Discord mention token through its numeric id in `routing_context.mentions`;
5. otherwise use `routing_context.author` only when the complete birthday subject clause matches one of the bounded forms `bursdagen min`, `min bursdag`, `eg/jeg har bursdag`, or `my birthday`, allowing only the documented edit verb/copula/date punctuation around it; a standalone `min|mitt|eg|jeg|my` elsewhere is not identity evidence;
6. return `{"action":"clarify","reason":"unresolved_target"}` for arbitrary name text or unknown mentions;
7. choose edit only when an edit verb is present; otherwise choose add.

Never search Discord, persisted birthdays, or display names in this function. Add `Mina har bursdag 15.05` and `Myra has birthday 15.05` negatives that prove substring safety, plus `min venn Ola har bursdag 15.05`, `bursdagen til min søster er 15.05`, and `my sister's birthday is 15.05` to prove relational possessives/free-name clauses cannot silently bind the author.

- [ ] **Step 4: Add router branches before calendar NLP (2–5 minutes)**

Call the new parser only through the routing-foundation exception boundary:

~~~python
parsed = self._safe_parse(
    errors,
    "parse_birthday_command",
    "birthday",
    parse_birthday_command,
    context.utterance.text,
    routing_context=context.routing,
)
~~~

Map `add -> BIRTHDAY_CREATE`, `edit -> BIRTHDAY_EDIT`, `list -> BIRTHDAY_LIST`, and `clarify -> CLARIFY`. Put the canonical object, including list scope, under `payload["birthday"]`; do not pass `reason` into an executable payload. Use the routing-foundation policy tiers and risk classifier. If parsing raises, emit no birthday candidate, append only `parse_birthday_command` to route diagnostics, and record only `parser=birthday|code=exception`; never expose the exception class/text or fall through to a partial birthday mutation.

- [ ] **Step 5: Connect routes to the prerequisite-owned typed handlers (2–5 minutes)**

Do not edit `BirthdayHandler`. Verify that `MessageMonitor` maps the three new router intents to the typed-dispatch lane's existing `handle_birthday_create`, `handle_birthday_list`, and `handle_birthday_edit` methods. If any method is absent, stop and finish the prerequisite instead of implementing it here. Create/edit calls use resolved `user_id` and await `create_birthday_result()` / `edit_birthday_by_user_id_result()` through those handlers; list performs no mutation and calls only the synchronous read formatter; `_parse_birthday_edit()` remains confined to the prerequisite's one-release raw fallback.

- [ ] **Step 6: Add a sentinel-content handler test (2–5 minutes)**

Keep the typed-dispatch lane's edit sentinel test green. Add equivalent integration tests against the prerequisite-owned create/list methods with `message.content = "SENTINEL"`: create must `await create_birthday_result(guild_id, 42, "Ola", 15, 5, None)` exactly once from the typed payload and map its structured result; edit must await `edit_birthday_by_user_id_result(...)`; list must call only the read API. Make every legacy birthday parser and synchronous mutation wrapper raise so the tests prove this lane only supplies typed payloads and cannot reintroduce event-loop-blocking compatibility calls.

- [ ] **Step 7: Extend the production harness fixture (2–5 minutes)**

Make `EvalFixture.MENTIONED_USER_42` produce `RoutingContext(author=ResolvedMention(7,"Kari"), mentions=(ResolvedMention(42,"Ola"),))`. Do not add a fake display-name resolver. Add the fixed clock contract used by every fixture:

~~~python
FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Europe/Oslo"))


@dataclass(frozen=True, slots=True)
class FixedReminderClock:
    current: datetime = FIXED_NOW

    def now(self) -> datetime:
        return self.current

    def epoch(self) -> float:
        return self.current.timestamp()
~~~

Construct `NaturalLanguageParser(now_provider=clock.now)`, attach that exact clock as `monitor.reminder_clock`, and let the adapter's private route helper capture `reference_time = clock.now()` exactly once per evaluated turn. Pass that same value to the single routing-owned `parse_reminder_command(..., now=reference_time, temporal_resolver=resolver)` for create, edit, and target frames; no `parse_reminder_edit_command` exists, and the parser may not call the clock again. Preserve `evaluate(text, *, guild_id)` exactly so `evaluate_case()` and the corpus protocol remain unchanged. Put the single fixture-context/fixed-clock route call in a private adapter helper; `evaluate()` adds parser diagnostics, while `route_help_example()` returns only its `IntentResult`. Neither may construct a second router, omit author/mention context, or read wall-clock time. Add harness tests proving `evaluate_case()` still satisfies the `EvaluationRouter` protocol, Bokmål and English “in 2 hours” examples both resolve from `FIXED_NOW` to `2026-07-14T14:00:00+02:00`, and “bursdagen min er 15.05” produces the identical author-bound payload through direct evaluation and help-example routing with the same context/clock object identities.

- [ ] **Step 8: Run and commit the birthday route (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_birthday_commands.py \
  tests/test_watchlist_birthday_edit.py \
  tests/test_nlu_contract.py -q
git add features/birthday_manager.py \
  core/intent_keywords.py core/intent_router.py core/message_monitor.py \
  tests/nlu_harness.py tests/test_birthday_commands.py \
  tests/fixtures/nlu_contract_v1.jsonl
git commit -m "feat: route birthdays through resolved identities"
~~~

Expected: PASS; free-text identity never silently becomes the author.

---

### Task 3: Require explicit poll syntax and match displayed vote syntax

**Files:**

- Modify: `features/poll_manager.py:251-340`
- Modify: `tests/test_poll_target.py`
- Modify: `tests/fixtures/nlu_contract_v1.jsonl`

**Interfaces:**

- Consumes: prerequisite `PollCreatePayload`, `PollVotePayload`, `PollEditPayload`, `PollTargetPayload`, and their stable `poll`, `vote`, `poll_edit`, `poll_delete`, and `poll_close` envelopes.
- Produces: `parse_poll_command(message_content: str) -> PollCreatePayload | None` and `parse_vote(message_content: str) -> int | None`; only explicit poll syntax can create a poll and votes are integers 1–10.

- [ ] **Step 1: Add poll false-positive and positive tests (2–5 minutes)**

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
def test_non_poll_shapes_are_rejected(text):
    assert parse_poll_command(text) is None


def test_explicit_comma_poll_is_parsed():
    assert parse_poll_command(
        "lag avstemning: Hva spiser vi? pizza, burger, taco"
    ) == {
        "question": "Hva spiser vi?",
        "options": ["pizza", "burger", "taco"],
        "lang": "no",
    }


@pytest.mark.parametrize(("text", "vote"), [("1", 1), ("stem 1", 1), ("vote 10", 10)])
def test_vote_parser_matches_help_copy(text, vote):
    assert parse_vote(text) == vote
~~~

- [ ] **Step 2: Run the tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_poll_target.py -q
~~~

Expected: FAIL on slash false positives, comma options, and explicit vote syntax.

- [ ] **Step 3: Replace implicit slash detection (2–5 minutes)**

Use this bounded trigger and vote shape:

~~~python
POLL_TRIGGER = re.compile(
    r"^(?:(?:lag|ny|create)\s+)?(?:avstemning|poll)\b\s*:?[ ]*",
    flags=re.IGNORECASE,
)
VOTE_PATTERN = re.compile(r"^(?:(?:stem|vote)\s+)?(\d{1,2})$", re.IGNORECASE)
~~~

After bot-mention removal, return None unless `POLL_TRIGGER` matches. Split the remaining tail once at `?`; keep the left side plus `?` as question. Split a nonblank option tail on `/`, comma, or `eller|or`. Strip and deduplicate case-insensitively while preserving order. Reject fewer than two or more than ten options. When the explicit trigger has a question but no option tail, return localized yes/no. `parse_vote()` accepts only the complete `VOTE_PATTERN` and values 1–10.

- [ ] **Step 4: Run focused parser and router tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_poll_target.py \
  tests/test_intent_router.py \
  tests/test_nlu_contract.py -q
~~~

Expected: PASS; URL shortening never becomes `POLL_CREATE`.

- [ ] **Step 5: Commit (2–5 minutes)**

~~~bash
git add features/poll_manager.py tests/test_poll_target.py \
  tests/fixtures/nlu_contract_v1.jsonl
git commit -m "fix: require explicit natural poll syntax"
~~~

---

### Task 4: Verify watchlist domain evidence and feature parity

**Files:**

- Verify: `features/watchlist_manager.py` (implemented by routing-foundation Task 11b)
- Modify: `tests/test_watchlist_scope.py`
- Modify: `tests/fixtures/nlu_contract_v1.jsonl`

**Interfaces:**

- Consumes: prerequisite `WatchlistPayload` and `validate_intent_payload(BotIntent.WATCHLIST, payload, source=...)`.
- Consumes: routing-foundation Task 11b's complete `parse_watchlist_command(message_content: str) -> WatchlistPayload | None` implementation.
- Produces: parity/regression proof that add/edit/remove always contain the required typed title/index/change fields, while status/suggest remain read-only. This task does not redefine or edit the parser.

- [ ] **Step 1: Add paired evidence tests (2–5 minutes)**

~~~python
@pytest.mark.parametrize("text", ["legg til melk", "fjern nummer 2", "endre tittel", "se her"])
def test_generic_actions_are_not_watchlist_commands(text):
    assert parse_watchlist_command(text) is None


@pytest.mark.parametrize(
    ("text", "action", "title"),
    [
        ("husk å se Inception", "add", "Inception"),
        ("hugs å sjå Arrival", "add", "Arrival"),
        ("remember to watch The Bear", "add", "The Bear"),
        ("legg til film Inception", "add", "Inception"),
        ("add The Bear to watchlist", "add", "The Bear"),
    ],
)
def test_add_requires_domain_and_keeps_title(text, action, title):
    parsed = parse_watchlist_command(text)
    assert parsed["action"] == action
    assert parsed["title"] == title
~~~

Also pin typed edit fields: `endre watchlist 2 tittel: The Matrix type: film sjanger: sci-fi kommentar: klassiker` emits index 2, title, movie, genre, and comment.

- [ ] **Step 2: Run the watchlist tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_watchlist_scope.py -q
~~~

Expected: FAIL because bare `legg til` currently produces an add command and title/edit fields are discarded.

- [ ] **Step 3: Audit bounded evidence and extraction without changing production code (2–5 minutes)**

Assert the prerequisite accepts add only for one of:

- `husk å se` followed by a nonblank captured title;
- `hugs å sjå` followed by a nonblank captured title;
- `remember to watch` followed by a nonblank captured title;
- `legg til film` or `legg til serie` followed by a nonblank captured title;
- `legg til` followed by a nonblank captured title and then `på watchlist` or `i watchlist`;
- `add` followed by a nonblank captured title and then `to watchlist` or `to the watchlist`.

Assert remove/edit requires `watchlist`, `film`, `serie`, `movie`, or `show` with the action. Keep the existing suggestion phrases, except bare `recommend|anbefaling` still requires movie/series evidence. Assert labeled edit fields use the routing-owned pure helper and return the complete Task-6 `WatchlistPayload`; an add without a nonblank title fails. If any assertion is red, stop and repair routing-foundation Task 11b rather than adding a second parser implementation in this lane.

- [ ] **Step 4: Run parser, dispatch, and corpus tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_watchlist_scope.py \
  tests/test_watchlist_birthday_edit.py \
  tests/test_parse_once_dispatch.py \
  tests/test_nlu_contract.py -q
~~~

Expected: PASS with no generic-action theft.

- [ ] **Step 5: Commit (2–5 minutes)**

~~~bash
git add tests/test_watchlist_scope.py \
  tests/fixtures/nlu_contract_v1.jsonl
git commit -m "test: lock natural watchlist parity"
~~~

---

### Task 5: Route profile status and activity through a typed payload

**Files:**

- Modify: `core/intent_payloads.py`
- Modify: `core/intent_router.py`
- Modify: `core/message_monitor.py`
- Create: `features/profile_commands.py`
- Modify: `features/profile_handler.py`
- Create: `tests/test_profile_routing.py`
- Modify: `tests/test_parse_once_dispatch.py`
- Modify: `tests/test_message_send_result.py`

**Interfaces:**

- Consumes: prerequisite `IntentSource`, `IntentRisk.MUTATING`, `DispatchOutcome`, `validate_intent_payload()`, and the control-candidate collector.
- Produces: `ProfilePayload`, `parse_profile_command(message_content: str) -> ProfilePayload | None`, `ENVELOPE_KEYS[BotIntent.PROFILE] == "profile"`, and truthful `ProfileHandler.handle_status(...)`, `handle_activity(...)`, and `handle_profile_command(message, payload: ProfilePayload) -> Awaitable[DispatchOutcome]` methods.

- [ ] **Step 1: Add failing exact route tests (2–5 minutes)**

~~~python
@pytest.mark.parametrize(
    ("text", "payload"),
    [
        ("status online", {"action": "status", "value": "online"}),
        ("spiller CS2", {"action": "playing", "value": "CS2"}),
        ("ser på Netflix", {"action": "watching", "value": "Netflix"}),
    ],
)
def test_profile_routes_keep_typed_operation_and_value(router, text, payload):
    result = router.route(text, guild_id=123, channel_id=456, user_id=7)
    assert result.intent is BotIntent.PROFILE
    assert result.payload == {"profile": payload}
    assert result.risk is IntentRisk.MUTATING
    assert result.requires_confirmation is False
~~~

- [ ] **Step 2: Run the profile route test red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_profile_routing.py -q
~~~

Expected: FAIL because `PROFILE` currently carries an empty payload.

- [ ] **Step 3: Add the bounded pure parser and validator (2–5 minutes)**

~~~python
class ProfilePayload(TypedDict):
    action: Literal["status", "playing", "watching"]
    value: str


PROFILE_PATTERNS = (
    (re.compile(r"^status\s+(online|offline|idle|dnd|invisible)$", re.I), "status"),
    (re.compile(r"^(?:spiller|playing)\s+(.+)$", re.I), "playing"),
    (re.compile(r"^(?:ser\s+på|watching)\s+(.+)$", re.I), "watching"),
)


def parse_profile_command(message_content: str) -> ProfilePayload | None:
    cleaned = re.sub(r"^\s*(?:<@!?\d+>|@inebotten)\s*", "", message_content).strip()
    for pattern, action in PROFILE_PATTERNS:
        if match := pattern.fullmatch(cleaned):
            value = match.group(1).strip()
            if value and len(value) <= 100:
                return {"action": action, "value": value}
    return None
~~~

Add `BotIntent.PROFILE: "profile"` to `ENVELOPE_KEYS`. Its validator rejects unknown keys, blank/over-100-character values, invalid actions, and status values outside the five values in the regex.

- [ ] **Step 4: Emit the canonical profile candidate through bounded parser isolation (2–5 minutes)**

In the control collector, call:

~~~python
parsed = self._safe_parse(
    errors,
    "parse_profile_command",
    "profile",
    parse_profile_command,
    context.utterance.text,
)
~~~

When it returns a value, validate it with `IntentSource.DETERMINISTIC` and emit `PROFILE` with `{"profile": validated}`, reason `profile_command`, the existing profile priority, specificity 3, and `IntentRisk.MUTATING`. Remove the old empty-payload profile-keyword candidate. If it raises, emit no profile candidate, append only the finite parser name, and record only `parser=profile|code=exception`. Add injected `RuntimeError("SECRET")` cases for birthday and profile; serialized diagnostics/metrics contain neither the marker nor exception class.

- [ ] **Step 5: Dispatch without rereading message content (2–5 minutes)**

Change all three profile entry points to return `DispatchOutcome`. `handle_profile_command()` requires `ProfilePayload`, dispatches `status` to `handle_status(message, payload["value"])` and `playing|watching` to `handle_activity(message, payload["action"], payload["value"])`, and returns the exact inner outcome without fabricating success. The `PROFILE` branch in `MessageMonitor` passes only the already validated inner `profile` value.

For each inner method, validate defensively before `change_presence()` and build a base outcome before acknowledgement: invalid input is `DispatchOutcome.failure("invalid_payload", retryable=False)` with zero presence call; an exception from `change_presence()` is bounded terminal `DispatchOutcome.failure("commit_state_unknown", retryable=False, commit_unknown=True)`; a normal return is `DispatchOutcome.success(mutated=True)`. Send the corresponding bounded copy exactly once through `send_response_result()` and return `base.with_delivery(send_result)`. If that owned send is cancelled, catch only `MessageSendCancelled` and raise `DispatchCancelled(base.with_delivery(exc.result))`. Thus `DELIVERED`, definite `NOT_DELIVERED`, and `UNKNOWN` remain distinct; an uncertain acknowledgement never triggers a second monitor fallback, and a failed acknowledgement never relabels a proven presence mutation.

- [ ] **Step 6: Add sentinel-content handler tests (2–5 minutes)**

Set `message.content = "SENTINEL"`, pass each of the three payloads from Step 1, and assert the exact `handle_status` or `handle_activity` arguments and exact propagated outcome. Make `parse_profile_command` raise in these tests to prove dispatch never reparses. Parameterize the direct inner methods over `DELIVERED`, definite `NOT_DELIVERED`, and `UNKNOWN`: successful presence stays `ok=True, mutated=True`, while `response_sent`/`delivery_result` match `base.with_delivery(send)` exactly; an UNKNOWN acknowledgement is terminal and makes zero fallback sends. Also prove `change_presence()` failure is `ok=False, commit_unknown=True` with bounded `commit_state_unknown`, invalid input never calls `change_presence()`, and cancel-after-presence-before-ack raises one `DispatchCancelled` carrying the same committed base plus settled delivery result. Reuse `tests/test_message_send_result.py` fixtures rather than defining a second delivery enum or fake receipt.

- [ ] **Step 7: Run and commit the profile slice (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_profile_routing.py \
  tests/test_parse_once_dispatch.py \
  tests/test_message_send_result.py \
  tests/test_intent_router.py -q
git add core/intent_payloads.py core/intent_router.py core/message_monitor.py \
  features/profile_commands.py features/profile_handler.py \
  tests/test_profile_routing.py tests/test_parse_once_dispatch.py \
  tests/test_message_send_result.py
git commit -m "refactor: route typed profile operations"
~~~

---

### Task 6: Make one registry own executable help examples

**Files:**

- Create: `core/help_registry.py`
- Create: `tests/test_help_route_parity.py`
- Create: `tests/test_help_handler.py`
- Modify: `features/help_handler.py:19-66`
- Modify: `memory/localization.py:443-505`
- Modify: `web_console/dashboard.py:761-988`
- Modify: `tests/nlu_harness.py`
- Modify: `tests/test_console_server.py`

**Interfaces:**

- Consumes: `BotIntent`, `IntentResult`, `IntentRisk`, `IntentSource`, `ENVELOPE_KEYS`, `validate_intent_payload(intent, raw, *, source)`, `EvalFixture`, Task 2's fixed-clock `ProductionRouterAdapter.route_help_example(text)`, the typed-dispatch lane's pure reminder create/edit parsers, and Task 5's typed `profile` envelope.
- Produces: `HelpCategory`, `HelpExample`, `HELP_CATEGORIES`, `HELP_EXAMPLES`, `examples_for_catalog(locale: str) -> tuple[HelpExample, ...]`, and `catalog_sections(locale: str) -> tuple[tuple[HelpCategory, tuple[HelpExample, ...]], ...]`.

- [ ] **Step 1: Add the complete failing registry contract test (2–5 minutes)**

~~~python
def test_every_help_example_routes_to_the_complete_advertised_contract():
    for example in HELP_EXAMPLES:
        adapter = build_production_router(example.fixture)
        result = adapter.route_help_example(example.route_phrase)
        payload = canonical_help_payload(result)
        assert result.intent is example.intent, example.id
        assert route_operation(result, payload) == example.operation, example.id
        assert result.risk is example.risk_level, example.id
        assert result.requires_confirmation is example.requires_confirmation, example.id
        expected = json.loads(example.expected_payload_json)
        assert payload == expected, example.id


def test_help_example_ids_are_unique_and_copy_is_concrete():
    assert len({example.id for example in HELP_EXAMPLES}) == len(HELP_EXAMPLES)
    for example in HELP_EXAMPLES:
        assert example.display_phrase == example.route_phrase
        assert "[" not in example.display_phrase
        assert not re.search(r"\b(?:kode|code)\s+\S+", example.display_phrase)
        assert example.display_phrase.strip()
~~~

Define every referenced test helper in the same file exactly as follows:

~~~python
ACTION_ENVELOPES = frozenset(
    {"reminder", "birthday", "watchlist", "quote", "profile"}
)


def canonical_help_payload(result):
    payload = dict(result.payload)
    envelope = ENVELOPE_KEYS.get(result.intent)
    if envelope is None:
        return payload
    assert set(payload) == {envelope}
    raw = payload[envelope]
    validated = validate_intent_payload(
        result.intent,
        raw,
        source=result.source,
    )
    return {envelope: validated}


def route_operation(result, payload):
    envelope = ENVELOPE_KEYS.get(result.intent)
    if envelope in ACTION_ENVELOPES:
        action = payload[envelope]["action"]
        return f"{envelope}.{action}"
    memory = payload.get("memory")
    if isinstance(memory, Mapping) and isinstance(memory.get("action"), str):
        return f"memory.{memory['action']}"
    return result.intent.value
~~~

- [ ] **Step 2: Run the parity test red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_help_route_parity.py -q
~~~

Expected: FAIL because `core.help_registry` does not exist.

- [ ] **Step 3: Define the immutable registry (2–5 minutes)**

~~~python
@dataclass(frozen=True, slots=True)
class HelpCategory:
    id: str
    title_no: str
    title_en: str
    description_no: str
    description_en: str


@dataclass(frozen=True, slots=True)
class HelpExample:
    id: str
    category: str
    locale: Literal["nb", "nn", "en"]
    display_phrase: str
    route_phrase: str
    intent: BotIntent
    operation: str
    expected_payload_json: str
    risk_level: IntentRisk
    requires_confirmation: bool
    fixture: EvalFixture
~~~

Create `HELP_CATEGORIES` from this exact ordered copy table; no renderer owns another category list:

| id | title_no | title_en | description_no | description_en |
|---|---|---|---|---|
| hjelp | 🤖 Hjelp | 🤖 Help | Se hva Inebotten kan gjøre. | See what Inebotten can do. |
| kalender | 📅 Kalender | 📅 Calendar | Opprett, finn og endre kalenderoppføringer. | Create, find, and change calendar entries. |
| påminnelser | ⏰ Påminnelser | ⏰ Reminders | Opprett og følg opp personlige påminnelser. | Create and follow up personal reminders. |
| avstemning | 📊 Avstemninger | 📊 Polls | Lag, vis og administrer avstemninger. | Create, view, and manage polls. |
| watchlist | 🎬 Watchlist | 🎬 Watchlist | Lagre filmer og serier du vil se. | Save movies and series you want to watch. |
| sitater | 💬 Sitater | 💬 Quotes | Lagre, vis og rediger sitater. | Save, view, and edit quotes. |
| bursdager | 🎂 Bursdager | 🎂 Birthdays | Registrer og vis bursdager med løst Discord-eierskap. | Register and view birthdays with resolved Discord ownership. |
| vær | 🌦️ Vær og sted | 🌦️ Weather and location | Vis væroversikt og lagre fast sted. | View weather overview and save a home location. |
| verktøy | 🧰 Verktøy | 🧰 Tools | Søk, regn og forkort lenker. | Search, calculate, and shorten links. |
| profil | 👤 Profil | 👤 Profile | Endre Inebotten-status og aktivitet. | Change Inebotten status and activity. |
| minne | 🧠 Minne | 🧠 Memory | Vis, eksporter eller slett ditt lagrede brukerminne. | View, export, or delete your stored user memory. |
| oversikt | 📋 Oversikt | 📋 Overview | Vis botstatus og samlede oversikter. | View bot status and combined overviews. |
| moro | ✨ Moro | ✨ Fun | Hent nordlys, priser, horoskop og andre lette funksjoner. | Get aurora, prices, horoscopes, and other light features. |

Populate `HELP_EXAMPLES` from this complete matrix. `payload` is the exact JSON string stored in `expected_payload_json`; `risk` names `IntentRisk`; `confirm` is the exact Boolean. Prefixes such as `@Inebotten` are renderer-only, and `display_phrase == route_phrase`.

| id | locale/category | phrase | intent | operation | payload | risk | confirm | fixture |
|---|---|---|---|---|---|---|---|---|
| help-nb | nb/hjelp | hjelp | HELP | help | `{}` | READ_ONLY | false | empty |
| help-nn | nn/hjelp | kva kan du gjere? | HELP | help | `{}` | READ_ONLY | false | empty |
| help-en | en/hjelp | what can you do? | HELP | help | `{}` | READ_ONLY | false | empty |
| cal-create | nb/kalender | møte med Ola 15.07.2026 kl 14 | CALENDAR_ITEM | calendar_item | `{"calendar_item":{"title":"møte med Ola","date":"15.07.2026","time":"14:00","type":"event"}}` | ADDITIVE | false | empty |
| cal-list | nb/kalender | vis kalenderen | CALENDAR_LIST | calendar_list | `{}` | READ_ONLY | false | empty |
| cal-search | nb/kalender | søk kalender møte | CALENDAR_SEARCH | calendar_search | `{"query":"møte"}` | READ_ONLY | false | calendar_title_meeting |
| cal-edit | nb/kalender | endre møte med Ola til fredag kl 10 | CALENDAR_EDIT | calendar_edit | `{"calendar_edit":{"target":"møte med Ola","changes":{"date":"17.07.2026","time":"10:00"}}}` | MUTATING | false | calendar_title_meeting |
| cal-delete | nb/kalender | slett møte med Ola | CALENDAR_DELETE | calendar_delete | `{"calendar_target":{"target":"møte med Ola"}}` | DESTRUCTIVE | true | calendar_title_meeting |
| cal-complete | nb/kalender | ferdig møte med Ola | CALENDAR_COMPLETE | calendar_complete | `{"calendar_target":{"target":"møte med Ola"}}` | MUTATING | false | calendar_title_meeting |
| cal-sync | nb/kalender | synk kalender | CALENDAR_SYNC | calendar_sync | `{}` | MUTATING | false | empty |
| cal-auth | nb/kalender | kalender auth | CALENDAR_AUTH | calendar_auth | `{"auth_code":null}` | MUTATING | false | empty |
| cal-list-en | en/kalender | show calendar | CALENDAR_LIST | calendar_list | `{}` | READ_ONLY | false | empty |
| rem-create | nb/påminnelser | påminn meg om å ringe legen om 2 timer | REMINDER_CREATE | reminder.add | `{"reminder":{"action":"add","text":"ringe legen","due_at":"2026-07-14T14:00:00+02:00","due_date":"14.07.2026","time":"14:00","timezone":"Europe/Oslo"}}` | ADDITIVE | false | empty |
| rem-list | nb/påminnelser | vis påminnelser | REMINDER_LIST | reminder.list | `{"reminder":{"action":"list"}}` | READ_ONLY | false | active_reminder |
| rem-search | nb/påminnelser | søk påminnelse lege | REMINDER_SEARCH | reminder.search | `{"reminder":{"action":"search","query":"lege"}}` | READ_ONLY | false | active_reminder |
| rem-edit | nb/påminnelser | endre påminnelse 1 tekst: Ring tannlegen | REMINDER_EDIT | reminder.edit | `{"reminder":{"action":"edit","number":1,"changes":{"text":"Ring tannlegen"}}}` | MUTATING | false | active_reminder |
| rem-complete | nb/påminnelser | ferdig påminnelse 1 | REMINDER_COMPLETE | reminder.complete | `{"reminder":{"action":"complete","number":1}}` | MUTATING | false | active_reminder |
| rem-delete | nb/påminnelser | slett påminnelse 1 | REMINDER_DELETE | reminder.delete | `{"reminder":{"action":"delete","number":1}}` | DESTRUCTIVE | true | active_reminder |
| rem-create-en | en/påminnelser | remind me to call the doctor in 2 hours | REMINDER_CREATE | reminder.add | `{"reminder":{"action":"add","text":"call the doctor","due_at":"2026-07-14T14:00:00+02:00","due_date":"14.07.2026","time":"14:00","timezone":"Europe/Oslo"}}` | ADDITIVE | false | empty |
| poll-create | nb/avstemning | lag avstemning: Hva spiser vi? pizza, burger, taco | POLL_CREATE | poll_create | `{"poll":{"question":"Hva spiser vi?","options":["pizza","burger","taco"],"lang":"no"}}` | ADDITIVE | false | empty |
| poll-list | nb/avstemning | vis avstemninger | POLL_LIST | poll_list | `{}` | READ_ONLY | false | active_poll |
| poll-vote | nb/avstemning | stem 1 | POLL_VOTE | poll_vote | `{"vote":{"option":1}}` | MUTATING | false | active_poll |
| poll-edit | nb/avstemning | endre poll 1 spørsmål: Middag? | POLL_EDIT | poll_edit | `{"poll_edit":{"target":1,"question":"Middag?"}}` | MUTATING | false | active_poll |
| poll-close | nb/avstemning | lukk poll 1 | POLL_CLOSE | poll_close | `{"poll_close":{"target":1}}` | MUTATING | false | active_poll |
| poll-delete | nb/avstemning | slett poll 1 | POLL_DELETE | poll_delete | `{"poll_delete":{"target":1}}` | DESTRUCTIVE | true | active_poll |
| watch-add | nb/watchlist | husk å se Inception | WATCHLIST | watchlist.add | `{"watchlist":{"action":"add","title":"Inception","lang":"no"}}` | ADDITIVE | false | empty |
| watch-list | nb/watchlist | vis watchlist | WATCHLIST | watchlist.status | `{"watchlist":{"action":"status","lang":"no"}}` | READ_ONLY | false | empty |
| watch-suggest | nb/watchlist | hva skal vi se? | WATCHLIST | watchlist.suggest | `{"watchlist":{"action":"suggest","type":null,"genre":null,"lang":"no"}}` | READ_ONLY | false | empty |
| watch-edit | nb/watchlist | endre watchlist 1 tittel: The Matrix | WATCHLIST | watchlist.edit | `{"watchlist":{"action":"edit","index":1,"title":"The Matrix","lang":"no"}}` | MUTATING | false | empty |
| watch-remove | nb/watchlist | fjern watchlist 1 | WATCHLIST | watchlist.remove | `{"watchlist":{"action":"remove","index":1,"lang":"no"}}` | DESTRUCTIVE | true | empty |
| watch-add-en | en/watchlist | add Inception to watchlist | WATCHLIST | watchlist.add | `{"watchlist":{"action":"add","title":"Inception","lang":"en"}}` | ADDITIVE | false | empty |
| quote-get | nb/sitater | sitat | QUOTE | quote.get | `{"quote":{"action":"get","lang":"no"}}` | READ_ONLY | false | empty |
| quote-list | nb/sitater | vis sitater | QUOTE_LIST | quote.list | `{"quote":{"action":"list","lang":"no"}}` | READ_ONLY | false | empty |
| quote-save | nb/sitater | husk dette: Et klokt sitat | QUOTE | quote.save | `{"quote":{"action":"save","text":"Et klokt sitat","lang":"no"}}` | ADDITIVE | false | empty |
| quote-edit | nb/sitater | endre sitat 1 tekst: Ny tekst | QUOTE_EDIT | quote.edit | `{"quote":{"action":"edit","index":1,"text":"Ny tekst","lang":"no"}}` | MUTATING | false | empty |
| quote-delete | nb/sitater | slett sitat 1 | QUOTE_DELETE | quote.delete | `{"quote":{"action":"delete","index":1,"lang":"no"}}` | DESTRUCTIVE | true | empty |
| birthday-add | nb/bursdager | bursdagen min er 15.05 | BIRTHDAY_CREATE | birthday.add | `{"birthday":{"action":"add","user_id":7,"display_name":"Kari","day":15,"month":5}}` | ADDITIVE | false | empty |
| birthday-list | nn/bursdager | kven har bursdag snart? | BIRTHDAY_LIST | birthday.list | `{"birthday":{"action":"list","scope":"upcoming"}}` | READ_ONLY | false | empty |
| birthday-edit | nb/bursdager | endre bursdagen min 20.05 | BIRTHDAY_EDIT | birthday.edit | `{"birthday":{"action":"edit","user_id":7,"day":20,"month":5}}` | MUTATING | false | empty |
| weather | nb/vær | vær | DASHBOARD | dashboard | `{"dashboard_reason":"explicit_request"}` | READ_ONLY | false | empty |
| location | nb/vær | jeg bor i Trondheim | SET_LOCATION | set_location | `{"city":"Trondheim"}` | MUTATING | false | empty |
| shorten | nb/verktøy | forkort https://example.invalid | SHORTEN_URL | shorten_url | `{"shorten":{"url":"https://example.invalid"}}` | READ_ONLY | false | empty |
| calculate | nb/verktøy | regn ut 2+2 | CALCULATOR | calculator | `{"calculator":{"type":"math","expression":"2+2"}}` | READ_ONLY | false | empty |
| search | nb/verktøy | søk på nett tog til Trondheim | SEARCH | search | `{"search":{"query":"tog til Trondheim","type":"web"}}` | READ_ONLY | false | empty |
| profile-status | nb/profil | status online | PROFILE | profile.status | `{"profile":{"action":"status","value":"online"}}` | MUTATING | false | empty |
| profile-playing | nb/profil | spiller CS2 | PROFILE | profile.playing | `{"profile":{"action":"playing","value":"CS2"}}` | MUTATING | false | empty |
| profile-watching | nb/profil | ser på Netflix | PROFILE | profile.watching | `{"profile":{"action":"watching","value":"Netflix"}}` | MUTATING | false | empty |
| memory-view | nb/minne | vis minnet mitt | MEMORY_VIEW | memory.view | `{"memory":{"action":"view"}}` | READ_ONLY | false | empty |
| memory-export | nb/minne | eksporter minnet mitt | MEMORY_EXPORT | memory.export | `{"memory":{"action":"export"}}` | READ_ONLY | false | empty |
| memory-delete | nb/minne | slett minnet mitt | MEMORY_DELETE | memory.delete | `{"memory":{"action":"delete","confirmed":false}}` | DESTRUCTIVE | true | empty |
| dashboard | nb/oversikt | vis oversikt | DASHBOARD | dashboard | `{"dashboard_reason":"explicit_request"}` | READ_ONLY | false | empty |
| status | nb/oversikt | bot status | STATUS | status | `{}` | READ_ONLY | false | empty |
| digest | nb/oversikt | daglig oppsummering | DAILY_DIGEST | daily_digest | `{}` | READ_ONLY | false | empty |
| aurora | nb/moro | nordlys | AURORA | aurora | `{}` | READ_ONLY | false | empty |
| school-holidays | nb/moro | skoleferie | SCHOOL_HOLIDAYS | school_holidays | `{}` | READ_ONLY | false | empty |
| word | nb/moro | dagens ord | WORD_OF_DAY | word_of_day | `{}` | READ_ONLY | false | empty |
| price | nb/moro | pris BTC | PRICE | price | `{"price":{"type":"crypto","asset":"btc","coin_id":"bitcoin","display_name":"BTC"}}` | READ_ONLY | false | empty |
| horoscope | nb/moro | horoskop væren | HOROSCOPE | horoscope | `{"horoscope":{"sign":"Aries","sign_key":"væren"}}` | READ_ONLY | false | empty |
| compliment | nb/moro | kompliment | COMPLIMENT | compliment | `{"compliment":{"action":"compliment","user":null}}` | READ_ONLY | false | empty |

The old `les URL` article-retrieval claim is deliberately absent because there is no typed article operation or offline production proof; replacing the handwritten page removes that claim. The weather row advertises the existing dashboard operation, not a separate `WEATHER` enum. Do not add auth-code submission, destructive bulk clear, unresolved names, countdown values tied to wall-clock time, provider action syntax, or the inaccurate bare `legg til Inception` phrase.

- [ ] **Step 4: Run one bounded parity batch (2–5 minutes)**

Run `tests/test_help_route_parity.py -x -q`. If a row fails, stop this task and repair the parser in the prerequisite plan or earlier feature task that owns that row, then rerun the same command. `HELP_EXAMPLES` is frozen: never delete a red row, weaken its expected contract, or add a one-token global alias.

- [ ] **Step 5: Render Discord help from the registry (2–5 minutes)**

Add these pure registry functions:

~~~python
def examples_for_catalog(locale: str) -> tuple[HelpExample, ...]:
    normalized = locale.casefold()
    if normalized not in {"no", "nb", "nn", "en"}:
        raise ValueError(f"unsupported help locale: {locale}")
    accepted = {"en"} if normalized == "en" else {"nb", "nn"}
    return tuple(example for example in HELP_EXAMPLES if example.locale in accepted)


def catalog_sections(
    locale: str,
) -> tuple[tuple[HelpCategory, tuple[HelpExample, ...]], ...]:
    examples = examples_for_catalog(locale)
    return tuple(
        (category, rows)
        for category in HELP_CATEGORIES
        if (rows := tuple(row for row in examples if row.category == category.id))
    )


DISCORD_MESSAGE_LIMIT = 2000


def render_discord_help_chunks(locale: str) -> tuple[str, ...]:
    english = locale.casefold() == "en"
    chunks: list[str] = []
    current = ""
    for category, examples in catalog_sections(locale):
        section_lines = [
            category.title_en if english else category.title_no,
            category.description_en if english else category.description_no,
            *(f"• @Inebotten {example.display_phrase}" for example in examples),
        ]
        for line in section_lines:
            if len(line) > DISCORD_MESSAGE_LIMIT:
                raise ValueError("help line exceeds Discord message limit")
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= DISCORD_MESSAGE_LIMIT:
                current = candidate
                continue
            chunks.append(current)
            current = line
        # Prefer category boundaries when the whole next category fits.
        if current and len(current) >= DISCORD_MESSAGE_LIMIT - 200:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return tuple(chunks)
~~~

The renderer preserves registry/category order, never splits a single example line, prefers category boundaries, and returns no empty chunk; every chunk is at most 2,000 characters. `HelpHandler.handle_help()` sends `render_discord_help_chunks(self.loc.current_lang)` sequentially through the typed lane's canonical `send_response_result()` and returns one exact `DispatchOutcome` carrying delivery certainty: all chunks `DELIVERED` is success; first-chunk `NOT_DELIVERED` is `response_send_failed`, definitely unsent and retryable; first-chunk `UNKNOWN` is terminal `response_delivery_unknown`; any later `NOT_DELIVERED` or `UNKNOWN` stops immediately as terminal `failure("partial_response_sent", retryable=False).with_delivery(MessageSendResult(DeliveryState.UNKNOWN, "partial_send"))` because an earlier prefix was delivered. The aggregate never attaches the final chunk's bare definite failure after a delivered prefix. If cancellation settles after at least one of multiple chunks was delivered, raise `DispatchCancelled` carrying that same `partial_response_sent` outcome and `UNKNOWN/partial_send`; the owned send is settled and no remaining chunk starts. Never retry or replay a delivered/possibly delivered prefix. Add all four branches plus cancellation-after-first-chunk barriers, and assert the returned/raised aggregate bypasses neither the typed task-local receipt nor its uncertainty semantics. Remove the duplicated phrase lists from `help_events`, `help_reminders`, `help_birthdays`, `help_profile`, and `help_fun`; localization retains category prose only.

- [ ] **Step 6: Render the web commands page from the same rows (2–5 minutes)**

Replace the hand-written `sections` tuples in `render_commands_page()` with:

~~~python
def _render_cmd_section(
    category: HelpCategory,
    examples: tuple[HelpExample, ...],
) -> str:
    rows = "\n".join(
        "<tr><td><code>"
        f"{escape('@inebotten ' + example.display_phrase)}"
        "</code></td></tr>"
        for example in examples
    )
    return (
        '<section class="card scroll-mt-24">'
        f"<h2>{escape(category.title_no)}</h2>"
        f'<p class="muted">{escape(category.description_no)}</p>'
        "<table><thead><tr><th>Kommando</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


main_content = "\n".join(
    _render_cmd_section(category, examples)
    for category, examples in catalog_sections("nb")
)
~~~

No explanatory prose may add command examples outside `HELP_EXAMPLES`.

- [ ] **Step 7: Add renderer parity tests (2–5 minutes)**

Assert every registry phrase appears in the matching concatenated Discord chunks/web output exactly once; every Discord chunk is nonempty and at most 2,000 characters; category/example order is exact; neither the old inaccurate `legg til Inception` nor the unproved `les https://example.invalid` article claim remains; and registry examples contain no API/auth secrets or live mutation identifiers. Add handler tests for all sends succeeding, the first send failing, and a deterministic middle send failing; assert no chunk after the failure is attempted and the exact outcome above is returned.

- [ ] **Step 8: Run and commit (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_help_route_parity.py \
  tests/test_help_handler.py \
  tests/test_console_server.py \
  tests/test_nlu_contract.py -q
git add core/help_registry.py features/help_handler.py memory/localization.py \
  web_console/dashboard.py tests/test_help_route_parity.py tests/test_help_handler.py \
  tests/nlu_harness.py tests/test_console_server.py
git commit -m "feat: render executable natural-language help"
~~~

---

### Task 7: Prove prerequisite-owned language variants in the corpus

**Files:**

- Modify: `tests/fixtures/nlu_contract_v1.jsonl`
- Test: `tests/test_pending_actions.py`
- Test: `tests/test_reminder_runtime.py`
- Test: `tests/test_temporal_resolver.py`
- Test: `tests/test_intent_router.py`
- Test: `tests/test_nlu_contract.py`

**Interfaces:**

- Consumes: routing-foundation `CAPABILITY_HELP` and `parse_reminder_command(..., now=..., temporal_resolver=...)`; typed-dispatch reminder runtime records; `TemporalResolver`; and model-actions `PendingActionStore.resolve(key: ConversationKey, text: str)` with its frozen confirmation/cancellation vocabulary.
- Produces: new positive/negative help, reminder, and temporal `EvalCase` rows only. Pending confirmation/cancellation remains covered by `tests/test_pending_actions.py` and is not duplicated in the corpus. This task adds no runtime parser, alias table, pending-action recognizer, or temporal resolver behavior.

- [ ] **Step 1: Verify the prerequisite-owned language tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_pending_actions.py \
  tests/test_reminder_runtime.py \
  tests/test_temporal_resolver.py -q
~~~

Expected: PASS. If a required form is absent, stop and finish the named prerequisite plan; do not implement it in this lane.

- [ ] **Step 2: Add the help and reminder corpus rows (2–5 minutes)**

Add only these bounded forms:

- help positives `kva kan du gjere`, `ka kan du gjøre`, `what can you do`; negative `kva meiner du om kampen?`;
- reminder positives `hugs å`, `påminning`, and `klokka`; negatives `æ ska bare høre ka du tænke` and quoted reminder text;
- list/read positives `vis kalenderen` (`nb`), `vis påminningar` (`nn`), and `show reminders` (`en`), with nearby conversational negatives `kalenderen ser fin ut`, `påminningar kan vere nyttige`, and `reminders are useful`;

Each row has a unique id, locale `nb|nn|en`, exact expected payload fields where dates/times matter, and a forbidden mutation intent on negatives.

- [ ] **Step 3: Add the temporal corpus rows (2–5 minutes)**

Add only these prerequisite-owned forms:

- temporal positives `i morgon`, `imårra`, `neste fredag`, and `førstkommende mandag`; negatives that discuss those words without an action;
- no additional list/read rows; the exact Bokmål, Nynorsk, and English forms are owned by Step 2.

Each row has a unique id, locale `nb|nn|en`, exact expected payload fields where dates/times matter, and a forbidden mutation intent on negatives.

- [ ] **Step 4: Run the corpus gate (2–5 minutes)**

~~~bash
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
~~~

Expected: exit 0. A failure is a prerequisite-plan failure: record the failed ids and stop without changing runtime files in this task.

- [ ] **Step 5: Run the routing safety slice (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_utterance_semantics.py \
  tests/test_false_positives.py \
  tests/test_intent_router.py \
  tests/test_nlu_contract.py -q
~~~

Expected: PASS, with zero negative mutation false positives.

- [ ] **Step 6: Re-run the report threshold gate (2–5 minutes)**

Run the Step-4 command. Expected: exit 0; overall exact intent at least 0.98 and each labeled locale at least 0.95.

- [ ] **Step 7: Commit the corpus-only slice (2–5 minutes)**

~~~bash
git add tests/fixtures/nlu_contract_v1.jsonl
git commit -m "feat: add measured Norwegian language variants"
~~~

---

### Task 8: Verify the feature-parity lane

**Files:**

- Verify: `features/birthday_manager.py`
- Verify: `features/poll_manager.py`
- Verify: `features/watchlist_manager.py`
- Verify: `core/help_registry.py`
- Verify: `tests/fixtures/nlu_contract_v1.jsonl`
- Verify: `.artifacts/nlu-contract.json`

**Interfaces:**

- Consumes: Tasks 1–7 and the three completed prerequisite plans.
- Produces: passing focused tests, a threshold-passing redacted NLU report, a clean diff check, and the exact lane SHA; it produces no runtime code.

- [ ] **Step 1: Run birthday, poll, and watchlist verification (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_birthday_commands.py \
  tests/test_poll_target.py \
  tests/test_watchlist_scope.py -q
~~~

- [ ] **Step 2: Run help and routing verification (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_help_route_parity.py \
  tests/test_intent_router.py \
  tests/test_false_positives.py \
  tests/test_nlu_contract.py -q
~~~

- [ ] **Step 3: Verify the machine report (2–5 minutes)**

~~~bash
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
~~~

Expected: exit 0. No live handler, Discord, Google Calendar, search, URL-shortener, or model call is part of this verification.

- [ ] **Step 4: Check the diff (2–5 minutes)**

~~~bash
git diff --check
~~~

Expected: exit 0.

- [ ] **Step 5: Record the exact lane SHA (2–5 minutes)**

~~~bash
git rev-parse HEAD
git status --short
~~~

Expected: only intentionally uncommitted work from later plan lanes remains.

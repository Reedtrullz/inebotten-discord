# Typed Dispatch and Reminder Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete only Tasks 6-7 of the parent natural-language action architecture: route one validated typed payload into each action handler, return truthful dispatch outcomes, and run one Oslo-time reminder runtime whose delivery, recurrence, lifecycle, and bounded health are deterministic.

**Architecture:** `IntentRouter` remains the only raw-text interpreter and preserves the current outer `IntentResult.payload` envelope keys. `MessageMonitor` validates and unwraps one inner payload, then handlers call managers without rereading `message.content` and return `DispatchOutcome`. `MessageMonitor` owns one `ReminderClock`, `ReminderManager`, `ReminderChecker`, and checker task; reminder records retain compatibility display fields but use aware `due_at` as temporal authority, and delivery is acknowledged before sent state changes.

**Tech Stack:** Python 3.12, `dataclasses`, `TypedDict`, `asyncio`, `zoneinfo`, existing `python-dateutil`, JSON persistence, pytest/pytest-asyncio, discord.py-self.

## Global Constraints

- Scope is the parent plan's current Tasks 6-7 only. Do not implement the semantic action proposal bridge, pending-action confirmation flow, console NLU persistence, or later CI/deployment tasks.
- Start only after parent Tasks 2-5 exist on the execution branch. Required symbols include `core.intent_models.BotIntent`, `IntentResult`, `IntentRisk`, `IntentSource`, `core.nlu_metrics.NLUMetrics`, and `cal_system.temporal_resolver.TemporalResolver`.
- Preserve `core.intent_router.BotIntent` and `IntentResult` as exact re-exports of `core.intent_models`, and preserve `IntentRouter.route(content, guild_id=None)` for existing callers.
- Preserve the existing mention gate in both guild channels and DMs, plus allowed-user/channel checks, before routing, metrics, or dispatch. This plan does not authorize untagged DMs. Keep confidence-threshold enforcement inside `MessageMonitor._handle_intent()`.
- Preserve current outer envelope keys. `MessageMonitor` owns envelope unwrapping and passes only the inner typed value to a handler.
- A present typed envelope is authoritative even if `message.content` contradicts it. Raw compatibility parsing is allowed for one release only when that canonical envelope key is absent; record `legacy_payload_fallback` through `NLUMetrics`, validate the fallback, and never merge raw and typed fields.
- Invalid typed input returns `DispatchOutcome.failure("invalid_payload")`, is non-retryable, and calls no manager, Discord adapter, Google Calendar adapter, or persistence writer.
- A manager mutation followed by a failed response is still `ok=True` and `mutated=True`. `response_sent` is true only for `MessageSendResult(DELIVERED)`; `DispatchOutcome.delivery_result` retains `NOT_DELIVERED` versus `UNKNOWN`, and `UNKNOWN` is terminal. Never retry a proven mutation or an uncertain Discord attempt.
- Use `Europe/Oslo` as reminder temporal authority. Store aware ISO-8601 `due_at` plus `due_date`/`time` compatibility fields; do not rewrite legacy JSON at load time.
- Capture one aware `reference_time` from the injected `ReminderClock` per authorized turn or checker cycle. Pass that exact value through routing, parsing, handlers, manager timestamps, recurrence, checker windows, sent-log pruning, digest dates, Google Calendar intervals, and health; no downstream layer recaptures the clock during that operation.
- One checker cycle emits at most one alert per item occurrence. Mark alerts and digests sent only after the complete Discord send path returns `MessageSendResult(DELIVERED)`; `UNKNOWN` is terminally suppressed for that occurrence and `NOT_DELIVERED` alone is retryable.
- Health contains fixed codes, timestamps, booleans, and integers only. Never include reminder text, calendar titles, user names, channel names, URLs, exception strings, or message content.
- Keep detailed reminder counters private in this scope. The existing public health projection may expose only `status`, `running`, `stale`, and `last_success_at`; authenticated detailed projection belongs to parent Task 13.
- Keep user-facing copy Norwegian and code identifiers English. Preserve the manager/handler split.
- Do not add a dependency. `python-dateutil` is already installed.
- Run repository Python with `.venv312/bin/python`.
- Before aggregate tests, run `df -h /System/Volumes/Data` and stop if free space is below 30 GiB.
- Never run live Discord, Google Calendar, LM Studio, OpenRouter, URL-shortening, browser-search, or other network mutation paths while implementing or verifying this plan.
- Preserve unrelated worktree changes and never eagerly rewrite existing user data.

---


## Execution Prerequisite Gate

The planning review inspected commit `437bc5edcc476705be68b24779b3e9c95730e1cb`, where parent Tasks 2-5 were not present. A zero-context executor must verify the actual execution branch before editing.

- [ ] **Prerequisite Step A (2 min): Run the prerequisite imports.**

~~~bash
.venv312/bin/python - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo

from core.intent_models import BotIntent, IntentResult, IntentRisk, IntentSource
from core.intent_router import BotIntent as RouterBotIntent
from core.intent_router import IntentResult as RouterIntentResult
from core.nlu_metrics import NLUMetrics
from cal_system.temporal_resolver import TemporalResolver
from cal_system.reminder_manager import parse_reminder_command

assert RouterBotIntent is BotIntent
assert RouterIntentResult is IntentResult
assert hasattr(BotIntent, "CLARIFY")
assert isinstance(NLUMetrics().snapshot(), dict)
assert TemporalResolver().resolve("i morgen").valid
assert parse_reminder_command(
    "minn mæ om å ringe legen om 2 timer",
    now=datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    temporal_resolver=TemporalResolver(),
)["action"] == "add"
assert parse_reminder_command(
    "endre påminnelse 1 tekst: Ring tannlegen",
    now=datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    temporal_resolver=TemporalResolver(),
) == {
    "action": "edit",
    "number": 1,
    "changes": {"text": "Ring tannlegen"},
}
print("Tasks 2-5 prerequisite gate: PASS")
PY
~~~

Expected: `Tasks 2-5 prerequisite gate: PASS`. The routing prerequisite owns the complete fixed-clock `parse_reminder_command(message_content, *, now=None, temporal_resolver=None)` vocabulary, edit frames, and media-frame exclusions. That one parser returns canonical create/edit/target payloads; there is no separate `parse_reminder_edit_command`. If an import or assertion fails, stop and execute parent Tasks 2-5 first; do not recreate or change that parser contract inside this sub-plan.

- [ ] **Prerequisite Step B (2 min): Record the execution base and worktree state.**

~~~bash
git status --short --branch
git rev-parse HEAD
~~~

Expected: the intended Tasks 2-5 branch/commit is visible. Preserve pre-existing user changes.

- [ ] **Prerequisite Step C (2-3 min): Confirm the current source symbols before applying line-sensitive edits.**

~~~bash
rg -n "def _handle_intent|def _track_background_task|async def setup|async def close|async def on_ready|def _create_reminder_checker" core/message_monitor.py
rg -n "async def handle_|def parse_reminder_command" features/*_handler.py cal_system/reminder_manager.py
rg -n "class ReminderChecker|async def check_|async def _send|async def start|def stop" cal_system/reminder_checker.py
~~~

Expected: `MessageMonitor._handle_intent`, handler entry points, `parse_reminder_command`, and the current checker methods are found. Adjust line numbers, not the named contracts, if earlier tasks shifted the file.

## Exact File Responsibility Map

| File | Required responsibility |
|---|---|
| `core/intent_payloads.py` | Exact Task 6 TypedDicts, envelope map, validation, and one-release typed-or-legacy adapter. |
| `core/dispatch_result.py` | Immutable dispatch truth plus the one shared finite Discord-delivery result contract consumed by every later lane. |
| `core/send_receipt.py` | Monitor-owned Discord admission/sending coordinator plus task-local tri-state observation; no handler owns a competing send/rate-limit path. |
| `core/mutation_coordinator.py` | Process-local re-entrant async scope coordinator shared by route confirmation, managers, checker, and background sync. |
| `core/message_context.py` | Shared `domain_scope_id(ConversationKey)` used by every guild/DM manager, handler, snapshot, and pending target. |
| `core/intent_router.py` | Complete inner payload construction; raw text interpretation stops here. |
| `core/message_monitor.py` | Envelope validation/unwrapping, outcome return, sole reminder ownership, idempotent lifecycle, dashboard data. |
| `core/selfbot_runner.py` | Retain one monitor across reconnect and delegate setup/close; no client-owned reminder manager/checker/task. |
| `features/base_handler.py` | Canonical `send_response_result()` delegation and one-release boolean projection. |
| `features/calendar_handler.py` | Typed create/edit/delete/complete/clear manager adapters. |
| `cal_system/calendar_manager.py` | Retain typed calendar type/description/RRULE fields on new records without rewriting old records. |
| `cal_system/google_calendar_manager.py` | Network-free construction, structured external mutation truth, dynamic enabled state, and atomic credential persistence. |
| `features/reminder_handler.py` | Typed create/list/search/edit/delete/complete adapters and all temporal fields after Task 7. |
| `features/polls_handler.py` | Typed create/vote/edit/delete/close adapters. |
| `features/watchlist_handler.py` | Typed add/edit/remove/status/suggest adapters. |
| `features/watchlist_manager.py` | Task 5 routing prerequisite already owns complete parse-once output; typed Task 2 verifies it unchanged, while later transactional-manager steps may modify only result/persistence semantics. |
| `features/fun_handler.py` | Typed quote save/get outcome. |
| `features/quote_handler.py` | Typed quote edit/delete outcome. |
| `features/quote_manager.py` | Complete parse-once quote parser output. |
| `features/birthday_handler.py` | Typed birthday create/list/edit adapters; the feature-parity lane only supplies resolved payloads and tests them. |
| `features/birthday_manager.py` | User-ID birthday edit adapter; no handler-side persistence mutation. |
| `cal_system/reminder_clock.py` | Shared clock protocol, system clock, and test clock contract. |
| `cal_system/reminder_manager.py` | Canonical temporal records, tolerant reads, parsing, edits, recurrence/DST. |
| `cal_system/reminder_checker.py` | Exclusive alert selection, tri-state delivery chain, occurrence state, bounded health. |
| `web_console/state_collector.py` | Redacted public reminder runtime summary. |
| `tests/test_parse_once_dispatch.py` | Payload, no-reparse, handler, and monitor outcome contracts. |
| `tests/test_message_send_result.py` | Shared sender admission, tri-state delivery, cancellation settlement, and no-retry contracts. |
| `tests/test_reminder_runtime.py` | Fixed-clock manager/checker/lifecycle/health contracts. |
| Existing focused suites | Backward compatibility for each touched domain. |

## Exact Typed Payload Contract

Create `core/intent_payloads.py` with these Task 6 public types. Do not rename fields or replace the family envelopes with per-operation keys.

~~~python
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict, TypeVar

from core.intent_models import BotIntent, IntentSource


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


class PayloadValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


T = TypeVar("T")


def typed_or_legacy_payload(
    *,
    monitor: Any,
    family: str,
    typed_value: T | None,
    legacy_factory: Callable[[], T | None],
) -> T | None:
    if typed_value is not None:
        return typed_value
    monitor.nlu_metrics.record_legacy_payload_fallback(family)
    return legacy_factory()


def validate_intent_payload(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource = IntentSource.DETERMINISTIC,
) -> dict[str, Any]:
    validator = INTENT_VALIDATORS.get(intent)
    if validator is None:
        raise PayloadValidationError("unsupported_intent")
    return validator(raw, source=source)
~~~

`INTENT_VALIDATORS` is exhaustive for the action intents in this plan. Each function copies input before normalization, rejects `bool` where an integer is required, strips surrounding whitespace without changing case, and raises only these bounded codes:

- `missing_payload`
- `unknown_key`
- `wrong_action`
- `missing_target`
- `ambiguous_target`
- `missing_change`
- `blank_value`
- `invalid_number`
- `invalid_date`
- `invalid_time`
- `ambiguous_time`
- `missing_date`
- `invalid_due_at`
- `invalid_timezone`
- `invalid_recurrence`
- `invalid_options`
- `value_too_long`
- `unsupported_intent`
- `unsupported_temporal_field`, used only by the intermediate Task 6 reminder adapter before Task 7 lands

Validation rules are exact:

| Payload | Required and cross-field validation |
|---|---|
| calendar create | `title` nonblank; at least `date` or `days_offset`; combined date/time through `TemporalResolver`; type is event/task. |
| calendar target | exactly one of positive `number`, nonblank `target`, or `all=True`; `all` is accepted only for `CALENDAR_CLEAR`. |
| calendar edit | nonblank `target` and at least one nonblank/explicit-null change; date/time through `TemporalResolver`. |
| reminder create | action is add; `text` nonblank; if temporal fields exist, `TemporalResolver` confirms one consistent Oslo occurrence; `due_at` must be aware. Checklist-only text is valid only when `recurrence` is absent; recurrence requires one canonical scheduled occurrence. |
| reminder target | action matches intent; list needs no selector; search needs nonblank `query`; complete/delete require exactly one positive `number` or nonblank `reminder_id`. |
| reminder edit | action is edit; exactly one positive `number` or nonblank `reminder_id`; at least one change; temporal fields agree; timezone, when present, is exactly Europe/Oslo. Payload validation rejects self-contained contradictions; because it has no record context, `ReminderManager.edit_reminder()` also validates the resolved post-edit state before mutation. That state may retain/set recurrence only with one canonical scheduled occurrence; clearing timing while recurrence remains returns bounded `invalid_recurrence` unless the same payload explicitly sets `recurrence=None`. |
| poll create | question nonblank; 2-10 unique nonblank options; question <= 300 chars and each option <= 100 chars. |
| poll vote | positive integer `option` and not bool; optional nonblank `poll_id`; semantic/pending dispatch freezes the active poll ID before staging. |
| poll target/edit | exactly one positional `target` (positive integer or `siste`) or nonblank `poll_id`; edit also has question or options. |
| birthday | action matches intent; positive `user_id`; create has nonblank `display_name`; calendar-valid day/month/year, with year 1900-2100 when present; list scope is `all` or `upcoming` and defaults to `all`. |
| watchlist | required fields by action: add title, edit positive index plus one changed field, remove positive index; status/suggest need no mutation field. |
| quote | required fields by action: save text, edit positive index plus text or author, delete positive index; optional author/text are nonblank when present. |

Unknown keys are always rejected for `IntentSource.SEMANTIC`. Deterministic compatibility input may retain only the listed payload fields; it may not carry `content`, `original_text`, `raw_text`, or arbitrary parser state.

### Stable envelope map

~~~python
ENVELOPE_KEYS: dict[BotIntent, str] = {
    BotIntent.CALENDAR_ITEM: "calendar_item",
    BotIntent.CALENDAR_EDIT: "calendar_edit",
    BotIntent.CALENDAR_DELETE: "calendar_target",
    BotIntent.CALENDAR_COMPLETE: "calendar_target",
    BotIntent.CALENDAR_CLEAR: "calendar_target",
    BotIntent.REMINDER_CREATE: "reminder",
    BotIntent.REMINDER_LIST: "reminder",
    BotIntent.REMINDER_SEARCH: "reminder",
    BotIntent.REMINDER_COMPLETE: "reminder",
    BotIntent.REMINDER_EDIT: "reminder",
    BotIntent.REMINDER_DELETE: "reminder",
    BotIntent.POLL_CREATE: "poll",
    BotIntent.POLL_VOTE: "vote",
    BotIntent.POLL_EDIT: "poll_edit",
    BotIntent.POLL_DELETE: "poll_delete",
    BotIntent.POLL_CLOSE: "poll_close",
    BotIntent.BIRTHDAY_CREATE: "birthday",
    BotIntent.BIRTHDAY_LIST: "birthday",
    BotIntent.BIRTHDAY_EDIT: "birthday",
    BotIntent.WATCHLIST: "watchlist",
    BotIntent.QUOTE: "quote",
    BotIntent.QUOTE_LIST: "quote",
    BotIntent.QUOTE_EDIT: "quote",
    BotIntent.QUOTE_DELETE: "quote",
}
~~~

`CALENDAR_SEARCH` and unrelated read-only utility intents retain their existing payload contracts. The map above is the only unwrapping source for action families in scope.

## Exact Dispatch Contract

Create `core/dispatch_result.py` with:

~~~python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum


class DeliveryState(str, Enum):
    DELIVERED = "delivered"
    NOT_DELIVERED = "not_delivered"
    UNKNOWN = "unknown"


SEND_ERROR_CODES = frozenset(
    {
        "empty",
        "daily_quota",
        "forbidden",
        "http",
        "timeout",
        "transport",
        "send_task_cancelled",
        "send_task_exception",
        "partial_send",
        "missing_channel",
        "invalid_channel",
        "missing_adapter",
    }
)


@dataclass(frozen=True, slots=True)
class MessageSendResult:
    state: DeliveryState
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.state is DeliveryState.DELIVERED and self.error_code is not None:
            raise ValueError("delivered_with_error")
        if self.state is not DeliveryState.DELIVERED:
            if self.error_code not in SEND_ERROR_CODES:
                raise ValueError("invalid_send_error_code")


class MessageSendCancelled(asyncio.CancelledError):
    """Cancellation observed only after the owned send reaches known truth."""

    def __init__(self, result: MessageSendResult) -> None:
        self.result = result
        super().__init__(result.error_code or "message_send_cancelled")


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    ok: bool
    mutated: bool = False
    response_sent: bool = False
    retryable: bool = False
    error_code: str | None = None
    commit_unknown: bool = False
    delivery_result: MessageSendResult | None = None

    def __post_init__(self) -> None:
        if self.commit_unknown and (self.ok or self.retryable):
            raise ValueError("invalid_unknown_commit_outcome")
        if self.delivery_result is not None:
            delivered = self.delivery_result.state is DeliveryState.DELIVERED
            if self.response_sent is not delivered:
                raise ValueError("inconsistent_delivery_outcome")
            if (
                self.delivery_result.state is DeliveryState.UNKNOWN
                and self.retryable
            ):
                raise ValueError("retryable_unknown_delivery")

    @classmethod
    def success(
        cls,
        *,
        mutated: bool = False,
        response_sent: bool = False,
    ) -> "DispatchOutcome":
        return cls(
            ok=True,
            mutated=mutated,
            response_sent=response_sent,
            retryable=False,
            error_code=None,
            commit_unknown=False,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        *,
        mutated: bool = False,
        response_sent: bool = False,
        retryable: bool = False,
        commit_unknown: bool = False,
    ) -> "DispatchOutcome":
        return cls(
            ok=False,
            mutated=mutated,
            response_sent=response_sent,
            retryable=retryable,
            error_code=code,
            commit_unknown=commit_unknown,
        )

    def with_delivery(
        self,
        result: MessageSendResult,
    ) -> "DispatchOutcome":
        return replace(
            self,
            response_sent=(result.state is DeliveryState.DELIVERED),
            retryable=(
                self.retryable
                and result.state is not DeliveryState.UNKNOWN
            ),
            delivery_result=result,
        )


class ManagerMutationError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        mutated: bool,
        commit_unknown: bool = False,
    ) -> None:
        self.code = code
        self.mutated = mutated
        self.commit_unknown = commit_unknown
        super().__init__(code)


class ManagerMutationCancelled(asyncio.CancelledError):
    def __init__(
        self,
        code: str,
        *,
        mutated: bool,
        retryable: bool,
        commit_unknown: bool = False,
    ) -> None:
        self.code = code
        self.mutated = mutated
        self.retryable = retryable
        self.commit_unknown = commit_unknown
        super().__init__(code)


class DispatchCancelled(asyncio.CancelledError):
    def __init__(self, outcome: DispatchOutcome) -> None:
        self.outcome = outcome
        super().__init__(outcome.error_code or "dispatch_cancelled")


class ExternalCommitState(str, Enum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "commit_unknown"


@dataclass(frozen=True, slots=True)
class ExternalMutationResult:
    ok: bool
    state: ExternalCommitState
    value: object | None = None
    error_code: str | None = None
~~~

Create `core/mutation_coordinator.py` in the same contract task. `MutationScope` is `tuple[str, str]`. `MutationCoordinator.hold(scope)` is an async context manager backed by one weakly held fair FIFO lock per scope; first-time contenders acquire in enqueue order. The lock records `asyncio.current_task()` as owner and a depth counter so a handler already inside the route scope may safely re-enter the same manager scope without deadlock. Re-entry is allowed only for the identical task, never inherited by a child task. Cancellation removes a waiting ticket without skipping/reordering the remaining live waiters. Expose these exact constants: `CALENDAR_SHARED_SCOPE = ("calendar", "shared")`, `REMINDER_STORE_SCOPE = ("reminder", "store")`, `REMINDER_SENT_LOG_SCOPE = ("reminder", "sent_log")`, `POLL_STORE_SCOPE = ("poll", "store")`, `WATCHLIST_STORE_SCOPE = ("watchlist", "store")`, `QUOTE_STORE_SCOPE = ("quote", "store")`, `BIRTHDAY_STORE_SCOPE = ("birthday", "store")`, and `MEMORY_STORE_SCOPE = ("memory", "store")`; promote `CalendarManager.SHARED_KEY = "shared"` to a real class constant. Each constant protects one complete JSON persistence root, not one guild/user bucket within that file. `REMINDER_SENT_LOG_SCOPE` protects the one checker sent-log root shared by calendar and reminder alerts. No production writer creates a private competing lock for the same state. Add enqueue-order, canceled-middle-waiter, same-task re-entry, cross-guild/cross-user store exclusion, concurrent calendar/reminder sent-log writes, and child-task non-inheritance tests; the model-actions lane uses the same primitive for per-conversation turn/presentation serialization.

Handler result rules:

- Build the mutation/error truth first, then call `await BaseHandler.send_response_result(message, copy)` exactly once and return `base_outcome.with_delivery(send)`. Typed handlers never infer delivery from truthiness, `None`, send-count deltas, or the legacy wrapper.
- `response_sent` is true exactly when `delivery_result.state is DeliveryState.DELIVERED`. `NOT_DELIVERED` remains distinguishable from `UNKNOWN`; only the former may preserve a pre-write `retryable=True` outcome. `UNKNOWN` always forces `retryable=False` and later monitor/pending layers must not send fallback copy for that outcome.
- A proven manager write remains `DispatchOutcome.success(mutated=True)` before response finalization regardless of acknowledgement delivery. A proven pre-write not-found may start as `DispatchOutcome.failure("not_found", retryable=True)`.
- Invalid typed envelopes are non-retryable `invalid_payload` before handler invocation.
- A caught `ManagerMutationError` preserves both its proven `mutated` and `commit_unknown` bits; only `mutated=False, commit_unknown=False` storage rollback is retryable.
- A caught `ManagerMutationCancelled` is translated without losing its bits into `DispatchCancelled(DispatchOutcome.failure(...))`; generic `except Exception` never catches or relabels it.
- `BaseHandler.send_response_result()` owns and shield-awaits one coordinator send. If the outer handler task is cancelled, it settles the owned send and raises `MessageSendCancelled(result)`. The handler converts that carrier to `DispatchCancelled(base_outcome.with_delivery(result))`, preserving a manager mutation that completed before acknowledgement. A self-cancelled/exceptional send task becomes bounded `UNKNOWN` (`send_task_cancelled`/`send_task_exception`), never definite failure.
- An unclassified exception after a mutator was entered is `failure("commit_state_unknown", retryable=False, commit_unknown=True)`. Never expose `str(exc)` or claim that no write occurred.
- Typed reads use the same finalization and start from `success(mutated=False)`. The one-release boolean `send_response()` wrapper is for untouched legacy callers only and returns `True` for `DELIVERED`, otherwise `None`; no decision-sensitive code consumes it.

## Exact Reminder Clock, Record, Window, and Health Contracts

Create `cal_system/reminder_clock.py` with:

~~~python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


OSLO = ZoneInfo("Europe/Oslo")


class ReminderClock(Protocol):
    def now(self) -> datetime:
        raise NotImplementedError

    def epoch(self) -> float:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SystemReminderClock:
    timezone: ZoneInfo = OSLO

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def epoch(self) -> float:
        return self.now().timestamp()
~~~

Every `clock.now()` must be aware. Constructors reject a naive test/system clock value with `ValueError("naive_reminder_clock")`.

Canonical reminder fields:

~~~python
{
    "id": str,
    "user_id": str,
    "username": str,
    "text": str,
    "due_at": str | None,
    "due_date": str | None,
    "time": str | None,
    "timezone": "Europe/Oslo",
    "recurrence": str | None,
    "recurrence_anchor_local": str | None,
    "recurrence_sequence": int | None,
    "recurrence_day": str | None,
    "rrule_day": str | None,
    "gcal_event_id": str | None,
    "gcal_link": str | None,
    "channel_id": str | None,
    "created_at": str,
    "completed": bool,
    "completed_at": str | None,
    "completed_by": str | None,
}
~~~

`due_at` is authoritative for the current occurrence when it is valid. `recurrence_anchor_local` plus `recurrence_sequence` own the nominal recurrence phase; both are null for non-recurring records, and sequence is a nonnegative integer when recurring. `due_date` and `time` are display/backward-compatibility values. Date-only records use 09:00 Oslo; undated records remain checklist-only. A malformed legacy value is skipped and counted, not rewritten. Valid `due_at` disagreement with display fields increments `legacy_due_mismatch`; display fields are derived from `due_at` only on the next explicit write.

Alert selection is one pure function:

~~~python
from datetime import timedelta
from typing import Literal

AlertKind = Literal["warning_30m", "due"]


def select_alert_kind(delta: timedelta) -> AlertKind | None:
    if timedelta(minutes=25) < delta <= timedelta(minutes=35):
        return "warning_30m"
    if -timedelta(minutes=10) <= delta <= timedelta(minutes=1):
        return "due"
    return None
~~~

This makes the windows mutually exclusive:

| Kind | `due_at.astimezone(UTC) - now.astimezone(UTC)` boundary | Meaning |
|---|---|---|
| `warning_30m` | 25 minutes exclusive through 35 minutes inclusive | optional advance warning |
| `due` | -10 minutes inclusive through +1 minute inclusive | on-time or bounded missed-cycle catch-up |
| none | every other delta | no send; deltas older than -10 minutes increment `missed_outside_catchup` |

There is no separate passed notification. The sent key is:

~~~python
f"{source_kind}:{item_id}:{due_at.isoformat()}:{alert_kind}"
~~~

where `source_kind` is exactly `calendar` or `reminder`. A recurring occurrence receives a new key because its canonical timestamp changes.

`ReminderChecker.get_health()` returns this bounded internal schema:

~~~python
{
    "status": "starting" | "ok" | "degraded" | "stopped",
    "running": bool,
    "stale": bool,
    "last_check_at": str | None,
    "last_success_at": str | None,
    "last_error_at": str | None,
    "last_error_code": (
        None
        | "cycle_error"
        | "gcal_sync_error"
        | "delivery_failure"
        | "storage_error"
    ),
    "consecutive_errors": int,
    "stats": {
        "cycles": int,
        "warning_30m_sent": int,
        "due_sent": int,
        "digest_sent": int,
        "delivery_failures": int,
        "skipped_missing_channel": int,
        "malformed_legacy_due_at": int,
        "legacy_due_mismatch": int,
        "missed_outside_catchup": int,
        "gcal_sync_errors": int,
        "cycle_errors": int,
    },
}
~~~

`stale` is true when a running checker has no successful cycle within `max(150, interval_seconds * 2.5)` seconds. Historic counters alone do not keep status degraded; the latest cycle's bounded error code, current consecutive cycle errors, or a stale heartbeat does.

---

### Task 1: Define payload and outcome contracts

**Files:**

- Create: `core/intent_payloads.py`
- Create: `core/dispatch_result.py`
- Create: `core/mutation_coordinator.py`
- Create: `cal_system/reminder_clock.py`
- Create: `tests/test_parse_once_dispatch.py`

**Interfaces:**

- Consumes: routing-foundation `BotIntent`, `IntentSource`, Oslo temporal values, and existing outer payload envelopes.
- Produces: `DispatchOutcome.with_delivery()`, `DeliveryState`, the finite `SEND_ERROR_CODES`, immutable `MessageSendResult`, `MessageSendCancelled`, `ExternalMutationResult`, `MutationCoordinator`, `ReminderClock`, `SystemReminderClock`, `PayloadValidationError`, `ENVELOPE_KEYS`, the complete typed payload definitions, `typed_or_legacy_payload()`, and `validate_intent_payload(intent, raw, *, source=IntentSource.DETERMINISTIC) -> dict[str, Any]` for all later tasks and lanes. `BirthdayWriteResult` is introduced with the birthday manager in Task 3, not in this generic contract task.

- [ ] **Step 1.1 (2-3 min): Add two failing outcome-construction tests.**

~~~python
import pytest

from core.dispatch_result import (
    DeliveryState,
    DispatchOutcome,
    MessageSendResult,
    SEND_ERROR_CODES,
)


def test_success_keeps_mutation_separate_from_response():
    outcome = DispatchOutcome.success(mutated=True, response_sent=False)
    assert outcome == DispatchOutcome(
        True,
        True,
        False,
        False,
        None,
        False,
        None,
    )


def test_not_found_can_be_retryable_before_any_write():
    outcome = DispatchOutcome.failure("not_found", retryable=True)
    assert outcome.ok is False
    assert outcome.mutated is False
    assert outcome.retryable is True


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (DeliveryState.NOT_DELIVERED, "empty"),
        (DeliveryState.UNKNOWN, "transport"),
    ],
)
def test_message_send_result_accepts_only_finite_error_codes(state, code):
    assert MessageSendResult(state, code).error_code in SEND_ERROR_CODES
    with pytest.raises(ValueError, match="invalid_send_error_code"):
        MessageSendResult(state, "provider said secret text")


def test_unknown_delivery_is_retained_and_terminal():
    base = DispatchOutcome.failure("not_found", retryable=True)
    send = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    outcome = base.with_delivery(send)
    assert outcome.response_sent is False
    assert outcome.retryable is False
    assert outcome.delivery_result is send


def test_delivered_is_the_only_response_sent_state():
    delivered = MessageSendResult(DeliveryState.DELIVERED)
    outcome = DispatchOutcome.success(mutated=True).with_delivery(delivered)
    assert outcome.response_sent is True
    assert outcome.delivery_result is delivered
~~~

- [ ] **Step 1.2 (2 min): Run the two tests.**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_parse_once_dispatch.py::test_success_keeps_mutation_separate_from_response \
  tests/test_parse_once_dispatch.py::test_not_found_can_be_retryable_before_any_write \
  tests/test_parse_once_dispatch.py::test_unknown_delivery_is_retained_and_terminal \
  tests/test_parse_once_dispatch.py::test_delivered_is_the_only_response_sent_state -q
~~~

Expected: collection fails because `core.dispatch_result` does not exist.

- [ ] **Step 1.3 (2-3 min): Add `core/dispatch_result.py` and `cal_system/reminder_clock.py` using the exact dispatch and reminder-clock contracts above.**

Add `core/mutation_coordinator.py` at this step and unit-test same-task re-entry, cross-task exclusion, scope isolation, and weak lock cleanup. A child task created while its parent owns a scope must block, proving task ownership is not context-inherited.

- [ ] **Step 1.4 (2 min): Re-run Step 1.2.**

Expected: `4 passed`.

- [ ] **Step 1.5 (3-5 min): Add one valid round-trip case for each payload family.**

Use calendar create/edit/target, reminder create/edit/target, poll create/vote/edit/target, birthday create/edit/list, watchlist add/edit/remove, and quote save/edit/delete. Assert the normalized value and that the input dictionary remains unchanged.

- [ ] **Step 1.6 (3-5 min): Add parameterized invalid cases for every bounded error code.**

Include bool-as-index, unknown semantic key, empty edit changes, conflicting target fields, impossible date, naive `due_at`, non-Oslo timezone, duplicate poll options, blank quote author update, and wrong action discriminator.

- [ ] **Step 1.7 (2 min): Run the contract file.**

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py -q
~~~

Expected: collection fails because `core.intent_payloads` does not exist.

- [ ] **Step 1.8 (3-5 min): Add the exact TypedDicts, bounded exception, and envelope map.**

- [ ] **Step 1.9 (3-5 min): Implement scalar string/integer/list normalizers and their unit cases.**

- [ ] **Step 1.10 (3-5 min): Implement calendar and reminder validators through `TemporalResolver`.**

- [ ] **Step 1.11 (3-5 min): Implement poll, birthday, watchlist, and quote validators.**

- [ ] **Step 1.12 (2-3 min): Implement `typed_or_legacy_payload()` and test that the fallback factory is not called when typed data is present.**

- [ ] **Step 1.13 (2 min): Re-run the contract file.**

Expected: all tests in `tests/test_parse_once_dispatch.py` pass.

- [ ] **Step 1.14 (2 min): Commit the contract layer.**

~~~bash
git add core/dispatch_result.py core/mutation_coordinator.py core/intent_payloads.py \
  cal_system/reminder_clock.py \
  tests/test_parse_once_dispatch.py
git commit -m "refactor: define typed dispatch contracts"
~~~

Expected: one commit containing only the four contract modules and their initial tests.

---

### Task 2: Validate and populate complete payload envelopes at the router boundary

**Files:**

- Modify: `core/intent_router.py`
- Modify: `core/intent_payloads.py`
- Modify: `features/quote_manager.py`
- Modify: `tests/test_parse_once_dispatch.py`
- Modify: `tests/test_intent_router.py`
- Modify: `tests/test_poll_target.py`
- Modify: `tests/test_watchlist_birthday_edit.py`
- Modify: `tests/test_quote_crud.py`

**Interfaces:**

- Consumes: Task 1's `ENVELOPE_KEYS` and `validate_intent_payload()` plus the routing-foundation's candidate collectors and already-complete canonical `CALENDAR_EDIT`, reminder, and watchlist parser objects.
- Produces: complete canonical outer envelopes at the `IntentRouter` boundary for calendar, reminder, poll, watchlist, and quote intents; every emitted envelope's mapped inner value passes Task 1 validation without consulting Discord message text. This task validates/wraps the routing-owned calendar, reminder, and watchlist objects without adding recognizers or changing their parser signatures/vocabulary. Task 1 still defines birthday validators/envelopes and Task 3 implements birthday handlers, but the later feature-parity lane exclusively owns safe birthday identity parsing and production birthday route emission.

- [ ] **Step 2.1 (3-5 min): Add a parameterized router-envelope test.**

Pin these exact currently emitted family keys: `calendar_item`, `calendar_edit`, `calendar_target`, `reminder`, `poll`, `vote`, `poll_edit`, `poll_delete`, `poll_close`, `watchlist`, and `quote`. Keep `birthday` in `ENVELOPE_KEYS`, but do not manufacture a production route before feature-parity resolves the user identity safely.

Define the fixture in `tests/test_intent_router.py` rather than assuming an undeclared global fixture:

~~~python
import pytest

from core.eval_fixtures import EvalFixture
from tests.nlu_harness import build_production_router


@pytest.fixture
def production_router_adapter():
    return build_production_router(EvalFixture.MIXED_STATE)
~~~

All Task 2 route tests call `adapter.evaluate(text, guild_id=123)` and unpack `(result, parser_names)`. Do not reach into the adapter's private `_router`.

- [ ] **Step 2.2 (3-5 min): Add complete field assertions for calendar and reminder routes.**

Calendar assertions cover create `title/date/time/type/recurrence/recurrence_day/rrule_day/days_offset/description`, edit `target/changes`, and target `target/number/all`. Reminder assertions cover the action discriminator, text/query/number/reminder ID, and every temporal field.

- [ ] **Step 2.3 (3-5 min): Add complete field assertions for poll and watchlist routes.**

Assert poll question/options/lang, vote `option` plus optional frozen poll ID, target/poll ID, and watchlist action/title/type/index/genre/comment/lang. Birthday field normalization remains covered directly by Task 1 validator tests; Task 3 handler tests pass validated inner birthday payloads without claiming a pre-feature production route.

- [ ] **Step 2.4 (2-4 min): Add the quote field-boundary regression.**

~~~python
def test_quote_edit_route_keeps_text_and_author(production_router_adapter):
    result, _ = production_router_adapter.evaluate(
        "endre sitat 1 tekst: Ny tekst forfatter: Kari",
        guild_id=123,
    )
    assert result.intent is BotIntent.QUOTE_EDIT
    assert result.payload == {
        "quote": {
            "action": "edit",
            "index": 1,
            "text": "Ny tekst",
            "author": "Kari",
            "lang": "no",
        }
    }
~~~

- [ ] **Step 2.5 (2 min): Run the router/parser slice.**

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py tests/test_intent_router.py tests/test_poll_target.py tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py -q
~~~

Expected: failures show empty or target-only edit/delete payloads and watchlist/quote fields lost after parsing.

- [ ] **Step 2.6 (3-5 min): Verify the routing prerequisite's complete `parse_watchlist_command()` output without rewriting it.**

Run the existing `tests/test_watchlist_scope.py` direct-parser gate and the Step 2.3 route assertions. Verify the Task 5 parser output uses `type` and `index`, not `item_type` or `number`; removes only Inebotten's leading mention; preserves title/value case; and returns `None` rather than a partial mutating payload. Do not edit `features/watchlist_manager.py`, add a recognizer, or duplicate those cases in a new test file. Later transactional-manager tasks may still modify that file for result/persistence semantics.

~~~bash
.venv312/bin/python -m pytest tests/test_watchlist_scope.py -q
~~~

- [ ] **Step 2.7 (3-5 min): Extend `parse_quote_command()` for save/get/list/edit/delete.**

Use a field-boundary regex so text may contain spaces and punctuation:

~~~python
QUOTE_EDIT_FIELD = re.compile(
    r"\b(?:tekst|text|forfatter|author)\b\s*:",
    flags=re.IGNORECASE,
)
~~~

For edit, require a positive index and at least text or author. For delete, require a positive index. Return the full `QuotePayload` including `lang`.

- [ ] **Step 2.8 (3-5 min): Validate and wrap the routing-owned calendar and reminder candidate payloads.**

Consume Task 5's already-complete canonical `CALENDAR_EDIT` and reminder create/edit/target objects, call `validate_intent_payload()`, then preserve them under the stable family key. Do not reinterpret raw syntax, add timing/edit/target recognizers, or change `parse_reminder_command()`. Invalid deterministic objects emit the existing bounded parser diagnostic/`CLARIFY` path and never reach a handler.

- [ ] **Step 2.9 (3-5 min): Populate poll/quote payloads and wrap the routing-owned watchlist object.**

Validate and wrap Task 5's complete watchlist parser object without modifying its recognizer. Do not change Task 5 arbitration priorities, confidence thresholds, risk classification, evidence policy, or the reserved birthday collector. A birthday utterance continues through the existing safe fallback until the feature-parity lane emits a resolved identity payload.

- [ ] **Step 2.10 (2-3 min): Prove routed payloads contain no raw-text compatibility fields.**

Add an assertion that recursively rejects keys `content`, `original_text`, and `raw_text` from every action route.

- [ ] **Step 2.11 (2 min): Re-run Step 2.5.**

Expected: all focused router/parser tests pass, including the exact quote text/author object.

- [ ] **Step 2.12 (2 min): Commit parse-once router output.**

~~~bash
git add core/intent_router.py core/intent_payloads.py features/quote_manager.py \
  tests/test_parse_once_dispatch.py tests/test_intent_router.py \
  tests/test_poll_target.py tests/test_watchlist_birthday_edit.py \
  tests/test_quote_crud.py
git commit -m "refactor: route complete typed action payloads"
~~~

Expected: one commit with validator/router wrapping, quote parsing, and their tests; `features/watchlist_manager.py` is absent because Task 5 already supplied that parser, and handlers remain unchanged.

---
### Task 3: Migrate real handlers to typed payloads and truthful outcomes

**Files:**

- Modify: `core/message_context.py`
- Create: `core/send_receipt.py`
- Modify: `features/base_handler.py`
- Modify: `features/calendar_handler.py`
- Modify: `core/message_monitor.py` — composition dependencies, one turn `reference_time`, calendar sync/auth, and location outcomes only; complete envelope/outcome dispatch remains Task 4
- Modify: `cal_system/calendar_manager.py`
- Modify: `cal_system/google_calendar_manager.py`
- Modify: `cal_system/reminder_manager.py`
- Modify: `cal_system/reminder_checker.py` — dependency injection and read-only occurrence snapshots only; delivery semantics remain Task 6
- Modify: `features/reminder_handler.py`
- Modify: `features/polls_handler.py`
- Modify: `features/poll_manager.py`
- Modify: `features/watchlist_handler.py`
- Modify: `features/watchlist_manager.py`
- Modify: `features/fun_handler.py`
- Modify: `features/quote_handler.py`
- Modify: `features/quote_manager.py`
- Modify: `features/birthday_handler.py`
- Modify: `features/birthday_manager.py`
- Modify: `features/daily_digest_manager.py`
- Modify: `memory/user_memory.py`
- Modify: `tests/test_calendar_edit.py`
- Modify: `tests/test_reminder_crud.py`
- Modify: `tests/test_poll_target.py`
- Modify: `tests/test_watchlist_birthday_edit.py`
- Modify: `tests/test_quote_crud.py`
- Modify: `tests/test_parse_once_dispatch.py`
- Modify: `tests/test_user_memory_controls.py`
- Create: `tests/test_mutation_commit_contract.py`
- Create: `tests/test_google_calendar_result_compat.py`
- Create: `tests/test_auxiliary_dispatch_outcomes.py`
- Create: `tests/test_message_send_result.py`

**Interfaces:**

- Consumes: Task 1's validated inner payloads and `DispatchOutcome`; Task 2's canonical route envelopes; existing manager persistence APIs.
- Produces: `domain_scope_id()`, the monitor-owned `DiscordSendCoordinator`, canonical `BaseHandler.send_response_result()`, handler methods that accept an inner typed value or `None`, never reparse `message.content` on the typed path, call the exact manager adapter table below, and return a truthful delivery-attached `DispatchOutcome`; exact calendar sync/auth/location outcomes; structured Google result APIs with legacy-shape projections; and awaited `BirthdayManager.create_birthday_result(...)`, `BirthdayManager.edit_birthday_by_user_id_result(...)`, plus offline legacy-compatible wrappers.

Every migrated handler accepts an inner typed value or `None`. The typed branch never reads `message.content`. The `None` branch invokes exactly one existing raw parser through `typed_or_legacy_payload()`, validates its result, and is deleted after the compatibility release.

Every handler-family test injects `MessageSendResult` rather than `object()`/`None`: at minimum one successful mutation with `DELIVERED`, the same proven mutation with `UNKNOWN`, and one pre-write retryable failure with both `NOT_DELIVERED` and `UNKNOWN`. Assert `UNKNOWN` never changes manager truth, never leaves `retryable=True`, never triggers a second send, and is retained on `DispatchOutcome.delivery_result`.

### Durable local-mutation contract

Every JSON-backed manager reachable from a typed or claimed mutation—calendar, reminder, poll, watchlist, quote, birthday, and user memory—must validate first, deep-copy the smallest affected scope, mutate only that detached candidate, persist the candidate atomically, and publish/swap it into the live in-memory collection only after the writer returns. `_save_data_sync()`, `_save_reminders()`, `_save_polls()`, `_save_watchlist()`, `_save_quotes()`, `_save_birthdays()`, and `_save_memory()` must accept the candidate snapshot where needed and propagate write failure instead of logging/swallowing it. On a local save failure with no successful external side effect, leave the published in-memory state and disk bytes unchanged and raise `ManagerMutationError("storage_write_failed", mutated=False)`.

Every manager constructor accepts an optional `MutationCoordinator`; production constructs one coordinator before every manager/handler/checker and injects that identical object into them and, in the later model lane, `PendingTargetResolver`. Each manager exposes async transactional `*_result` entry points that acquire the real scope, then call private synchronous candidate helpers which assert that lease is held. Handlers, automatic initial GCal sync, ReminderChecker delivery/sent-state writes, repair jobs, and every other production writer use only those async entries. Calendar create/edit/delete/complete/clear/sync/auth all use `CALENDAR_SHARED_SCOPE`. Reminder, poll, watchlist, quote, birthday, and user-memory writers use their matching `*_STORE_SCOPE`, because each manager persists every guild/user bucket in one shared JSON file. Recurrence advancement has exactly one owner: `ReminderManager.complete_reminder_result()` advances a recurring reminder after explicit user completion; delivery/checker code never advances a schedule. The coordinator's same-task re-entry lets the later confirmation layer hold revalidate+dispatch atomically while a manager result API re-enters. There is no separate private async write lock with different ownership/order. Add blocked-writer barriers where two different guilds (and two different memory users) mutate from the same old root; both updates must survive in memory and on disk in FIFO order.

Preserve legacy method names for one release over the same private candidate
logic. A legacy method that is synchronous today remains an offline synchronous
projection: it rejects before mutation in a running event-loop thread with
`use_async_result_api`, and outside a loop it may drive the async result method
to completion. A legacy method that is already async today remains an awaitable
compatibility delegator. In particular, `UserMemory.set_location()` and
`UserMemory.delete_user_memory()` stay async and delegate to
`set_location_result()` / `delete_user_memory_result()` without changing their
historical return shapes. Add an `rg` gate over production code proving that new
production mutation paths call result APIs, while existing external callers and
tests may still await those two UserMemory compatibility names. This makes the
compatibility boundary explicit without converting existing coroutines into
synchronous APIs.

Constructor compatibility is exact and additive:

| Owner | Required additive keyword-only parameters |
|---|---|
| `CalendarManager(storage_path=None, gcal_manager=None, owner_email=None, owner_name=None, *, ...)` | `clock: Optional[ReminderClock] = None`, `mutation_coordinator: Optional[MutationCoordinator] = None` |
| `GoogleCalendarManager(*, ...)` | `mutation_coordinator: Optional[MutationCoordinator] = None` plus the module-global credential lock |
| `ReminderManager(storage_path=None, *, ...)` | `clock: Optional[ReminderClock] = None`, `mutation_coordinator: Optional[MutationCoordinator] = None` |
| `PollManager` | preserve current positional `storage_path`; add keyword-only `clock: Optional[ReminderClock] = None`, `mutation_coordinator: Optional[MutationCoordinator] = None` |
| `WatchlistManager`, `QuoteManager`, `UserMemory` | preserve current positional `storage_path`; add keyword-only `mutation_coordinator: Optional[MutationCoordinator] = None` |
| `BirthdayManager` | preserve current positional arguments; add keyword-only `mutation_coordinator: Optional[MutationCoordinator] = None`, `gcal_manager: Optional[GoogleCalendarManager] = None` |
| `ReminderChecker(...)` | preserve current arguments; add keyword-only `clock: Optional[ReminderClock] = None`, `mutation_coordinator: Optional[MutationCoordinator] = None` |

Defaults create isolated offline/test dependencies only. Make `GoogleCalendarManager.__init__()` network-free: it stores paths/config/coordinator but performs no credential refresh, OAuth exchange, or provider call. Add awaited `initialize_result()` / `refresh_configuration_result()` methods returning `ExternalMutationResult`; they run blocking credential work in owned shielded `asyncio.to_thread()` tasks under the module-global credential lock and update the same object. `enabled` is a dynamic read-only property of that object's current validated credential/config state. CalendarManager, BirthdayManager, handlers, and background jobs never cache `gcal_enabled`/`is_gcal_enabled` booleans, so disabled -> configured -> revoked transitions are visible without replacing the manager.

`MessageMonitor.__init__()` constructs one `MutationCoordinator`, one `SystemReminderClock`, and exactly one production `GoogleCalendarManager(mutation_coordinator=coordinator)` before any domain manager, then monitor setup awaits initialization. CalendarManager and BirthdayManager receive that exact object; migrated auth/sync/ensure paths call methods on it rather than constructing or replacing it. `CalendarManager.ensure_gcal_configured()` becomes an awaited result method over `self.gcal.refresh_configuration_result()`, and `BirthdayManager._init_gcal()` is removed or delegates to the same injected object. The legacy `EventManager` is not constructed on any production path; its CLI-only manager is explicitly injected if retained. A repository gate rejects a bare `GoogleCalendarManager()` in `core/`, `features/`, and production `cal_system/` call sites except the monitor composition root and explicit offline CLI/test. Inject the coordinator into Google/calendar/reminder/poll/watchlist/quote/birthday/user-memory/checker and all handlers/background writers, and inject the exact clock into `CalendarManager`, `ReminderManager`, `PollManager`, and `ReminderChecker`. `get_user_memory()` may remain a compatibility getter, but production passes the coordinator; if an existing singleton has a different coordinator it raises `mutation_coordinator_identity_mismatch` rather than silently returning it. Add ownership tests asserting the same GCal object identity across calendar, birthday, auth, and sync before and after initially-disabled -> configured refresh/code exchange and later revocation, no constructor I/O, no cached enabled booleans, coordinator identity across every writer, clock identity across all four temporal owners, and constructor compatibility for each old positional call. No module-level production singleton may predate dependency injection.

Enumerate every `UserMemory` writer rather than protecting only location/delete. The exact awaited write APIs are `get_or_create_user_result(user_id, username)`, `update_last_interaction_result(user_id, *, reference_time)`, `add_interest_result(user_id, interest)`, `set_preference_result(user_id, key, value)`, `set_location_result(user_id, canonical_city)`, and `delete_user_memory_result(user_id)`. `get_or_create_user_result()` is a write when it lazily creates a record or fills a missing username. Every result API acquires `MEMORY_STORE_SCOPE`, mutates a detached complete-root candidate, saves, then publishes. Preserve historical names for one release as projections over these result APIs; historically async names remain awaitable and historically synchronous names reject with `use_async_result_api` inside a running loop. `get_user()` returns a detached snapshot and never creates or fills data; all intentional creation uses `get_or_create_user_result()`.

Read-only lookup uses `snapshot_pending_user()` (also exported as `snapshot_user()`) and never invokes get-or-create. Inject the monitor-owned `UserMemory` into `DailyDigestManager`; replace its global `get_user_memory().get_user()` call and every dashboard/context read in `MessageMonitor` with detached snapshot reads. Only the composition root may call `get_user_memory()`, and only explicit result-backed write flows may call get-or-create. The compatibility singleton getter accepts a coordinator sentinel: its first explicit production call binds that object, and a later different coordinator raises `mutation_coordinator_identity_mismatch`; no import-time singleton is created. Add barrier tests for every exact writer, including two different users updating from the same old root, lazy creation racing preference update, username fill, save rollback, and no nested public reacquisition from a held private helper. Add an `rg` gate proving no production `get_user_memory()` outside the composition root, no read path calls a creating getter, and no production write calls a legacy projection.

### Committed snapshot contract for delayed target authorization

The later pending-action lane must freeze visible positions without reading private
mutable collections or calling get-or-create APIs. Add these synchronous,
side-effect-free accessors while each manager is migrated:

| Owner | Exact accessor | Returned order/content |
|---|---|---|
| `CalendarManager` | `snapshot_pending_items(*, reference_time: datetime) -> tuple[dict[str, object], ...]` | deep copies of active, non-delete-pending items in the canonical 365-day target window, sorted exactly as numbered calendar handlers |
| `CalendarManager` | `snapshot_all_item_ids() -> tuple[str, ...]` | stable IDs for every committed record that `clear_calendar_result()` would touch, including completed, past, more-than-365-day, and delete-pending records, sorted lexicographically |
| `ReminderManager` | `snapshot_pending_items(scope_id) -> tuple[dict[str, object], ...]` | deep copies of active reminders in the same stable creation order shown to the user |
| `PollManager` | `snapshot_pending_items(scope_id, *, reference_time: datetime) -> tuple[dict[str, object], ...]` | deep copies of active polls whose `expires_at` is after the supplied reference, in display/insertion order; every row has canonical nonblank `poll_id`, `question`, ordered option records, and `status` |
| `WatchlistManager` | `snapshot_pending_items(scope_id) -> tuple[dict[str, object], ...]` | deep copies of movies followed by series, exactly matching edit/remove numbering |
| `QuoteManager` | `snapshot_pending_items(scope_id) -> tuple[dict[str, object], ...]` | deep copies of the scoped quote list in display order |
| `BirthdayManager` | `snapshot_pending_user(scope_id, user_id) -> Optional[dict[str, object]]` | a deep copy of the exact user-ID record, never a display-name lookup |
| `UserMemory` | `snapshot_pending_user(user_id) -> Optional[dict[str, object]]` | a deep copy of an existing complete record; absence stays `None` and never creates memory |

Add the shared helper to `core/message_context.py` (not a local handler or model-lane duplicate): `domain_scope_id(key: ConversationKey) -> int`. It
returns `key.guild_id` in a guild and the bare `key.channel_id` in a DM. Discord
guild and channel snowflakes are globally unique, and retaining the bare DM
channel ID preserves the existing persisted bucket keys. Every typed handler,
manager result/read API, pending snapshot, fixture, dashboard read, and
background writer uses this helper; no path invents a `dm:`-prefixed storage
bucket. `scope_id` in the table is exactly that integer.

`reference_time` must be aware and is the one turn-captured
`ReminderClock.now()` value; the accessor never reads a clock itself. Extract one
pure calendar selector and one pure poll selector, and use each from its snapshot
accessor, numbered manager operations, and display/list operation. Add an
optional keyword-only `reference_time` to legacy `get_upcoming()` and
`get_active_polls()`; it defaults to the manager's injected clock only for
offline/legacy callers, while production routing/dispatch passes the captured
turn value. This removes the current calendar 90-day-display versus 365-day-
mutation mismatch: both display and positional mutation use the same canonical
365-day sequence (display may still show only its first bounded page).

Each accessor reads only the currently published copy-on-write root and
contains no `await`, persistence call, ambient clock read, lazy bucket creation, Google
call, log, or mutation. In particular, `WatchlistManager` must not call the
current mutating `_get_scope()` implementation for a missing scope, and
`UserMemory` must not call `get_user()`. A missing scope returns an empty tuple.
The accessor itself deep-copies before returning so the pending resolver cannot
alter manager state.

`snapshot_all_item_ids()` is deliberately clear-specific and does not widen ordinary numbered calendar targeting. It selects from the exact committed full collection used by `clear_calendar_result()`, rejects a missing/duplicate/blank stable ID as `invalid_target_state`, and includes every hidden record the clear would delete or mark pending. Pending-target freeze/revalidation fingerprints this complete tuple, so adding/removing a completed, past, far-future, or delete-pending record while confirmation waits yields `target_changed`.

Add a shared sentinel test that snapshots every family, mutates every returned
nested dictionary/list, and proves the manager's published state is byte-for-byte
unchanged. Also prove missing-scope and missing-user snapshots do not change the
in-memory roots or storage bytes. Publish-after-persist means an accessor sees
either the complete old root or the complete new root; the blocked-writer tests
must prove it never observes a candidate under construction. Calendar tests pin
the 365-day boundaries/order and Poll tests pin one instant immediately before,
at, and after expiry using the supplied aware reference. Add one DM
freeze-reorder-confirm test proving snapshot, list, handler, and persisted write
all use the same bare channel-ID bucket.

Add a calendar-clear snapshot fixture containing one active in-window item plus completed, past, more-than-365-day, and delete-pending records. Assert `snapshot_pending_items()` returns only the visible target sequence while `snapshot_all_item_ids()` returns all stable IDs in sorted order; an intervening hidden-record add/remove must invalidate a staged clear.

Calendar/birthday/auth paths use `ExternalMutationResult(ok, state, value, error_code)` for every provider call. `UNCHANGED` is allowed only when no mutating request was dispatched (disabled integration or local preflight/validation failure), an authoritative provider rejection proves no change, or a failed GET/list read provably performed no credential refresh. A positive mutating provider response is `CHANGED`. Any timeout, transport exception, malformed/ambiguous response, or legacy `None`/`False` after a mutating request was dispatched is `UNKNOWN`, even when an existing wrapper previously swallowed it. A read method reports its own bounded read failure and carries CHANGED/UNKNOWN only when credential refresh/token persistence actually changed or ambiguously changed state.

If local persistence fails after `CHANGED`, leave the published local snapshot unchanged and raise/return `external_state_changed_storage_failed, mutated=True`. After `UNKNOWN`, raise/return terminal `external_commit_unknown` with `commit_unknown=True` (and `mutated=True` too when a reconciliation/pending marker was durably stored); never authorize retry. Only proven `UNCHANGED` plus failed local persistence is a non-mutating retryable storage failure. Unknown exceptions after entering any other mutator become `commit_state_unknown`, never fabricated non-mutation.

Use one private snapshot/mutate/save/publish helper per manager rather than handler-side rollback. `UserMemory` routes get-or-create plus every mutator through private coordinator-held helpers; async `set_location_result`/`delete_user_memory_result` must not reacquire through public `get_user`, so use a private `_get_user_locked` helper. Existing async UserMemory names remain awaitable delegators; only historically synchronous manager names use offline projections. Calendar async clear/delete and UserMemory are mandatory copy-on-write cases: while a test blocks the writer thread/coroutine, a concurrent read must still see the pre-call state; after success it sees the committed state, and after failure it continues seeing the identical pre-call state.

Atomic writers and every synchronous Google/OAuth/provider call are launched as owned `asyncio.to_thread()` tasks and awaited through `asyncio.shield()` from the async transaction; no provider call blocks the event loop. If the caller is cancelled, await owned work to a known finish before publishing or rolling back; disk and published memory must never diverge. Raise `ManagerMutationCancelled(code, mutated, retryable, commit_unknown)` with exact truth; handlers translate it to `DispatchCancelled(DispatchOutcome(...))`. The later pending layer must complete/fail/release from that carried outcome and only then re-raise cancellation. Apply the same rule to an in-flight external mutation: authoritative completion keeps its CHANGED/UNCHANGED truth; loss of post-dispatch certainty is UNKNOWN. Add cancellation barriers for local save, provider request, checker sent-state delivery, and confirmed dispatch, plus an untyped `CancelledError` fail-closed case. ReminderChecker never advances recurrence.

`GoogleCalendarManager` additionally owns one module-level process-wide credential `threading.RLock` shared by every instance and legacy caller. Hold it around credential read/refresh, OAuth code exchange, and token persistence; write the token with a mode-0600 same-directory temporary file, flush/fsync, `os.replace`, and directory fsync rather than truncating the live token. Provider event requests may run concurrently after credentials are safely materialized. Test auth exchange versus background refresh across two manager instances; token bytes must always be one complete old or new document, never a torn mix.

### Canonical handler delivery boundary

Create `core/send_receipt.py` before migrating any typed handler. It contains both the task-local tri-state receipt API specified in Task 4 and `DiscordSendCoordinator(rate_limiter)`. The coordinator owns one async admission lock and makes rate-limit wait, the actual Discord attempt, and sent/failure accounting one atomic admission unit across monitor and handler callers. Empty text, exhausted quota, invalid/missing channel before an attempt, and Discord `Forbidden` are `NOT_DELIVERED` with finite codes. A normal return is `DELIVERED`. Timeout, HTTP failure after dispatch, or any other transport exception after an attempt starts is `UNKNOWN`; uncertain attempts reserve quota. Every ordinary send uses `AllowedMentions.none()` and `suppress_embeds=True`. The coordinator never sends fallback copy and never returns/records exception text.

Task 3 implements the receipt before its first green gate; Task 4 only consumes it for legacy-read adaptation. The exact aggregation contract is:

~~~python
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from core.dispatch_result import DeliveryState, MessageSendResult


@dataclass(slots=True)
class SendReceipt:
    result: MessageSendResult | None = None

    def observe(self, result: MessageSendResult) -> None:
        current = self.result
        if current is not None and current.state is DeliveryState.UNKNOWN:
            return
        if result.state is DeliveryState.UNKNOWN:
            self.result = result
        elif current is not None and {
            current.state,
            result.state,
        } == {
            DeliveryState.DELIVERED,
            DeliveryState.NOT_DELIVERED,
        }:
            self.result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "partial_send",
            )
        elif result.state is DeliveryState.DELIVERED:
            self.result = result
        elif current is None:
            self.result = result


_CURRENT_RECEIPT: ContextVar[SendReceipt | None] = ContextVar(
    "dispatch_send_receipt",
    default=None,
)


@contextmanager
def capture_send_receipt() -> Iterator[SendReceipt]:
    receipt = SendReceipt()
    token = _CURRENT_RECEIPT.set(receipt)
    try:
        yield receipt
    finally:
        _CURRENT_RECEIPT.reset(token)


def record_send_result(result: MessageSendResult) -> None:
    receipt = _CURRENT_RECEIPT.get()
    if receipt is not None:
        receipt.observe(result)
~~~

The coordinator implementation shape is exact (production imports `discord` and `asyncio`):

~~~python
class DiscordSendCoordinator:
    def __init__(self, rate_limiter) -> None:
        self.rate_limiter = rate_limiter
        self._admission_lock = asyncio.Lock()

    async def send_result(self, message, text: str) -> MessageSendResult:
        if not text:
            return MessageSendResult(DeliveryState.NOT_DELIVERED, "empty")
        if getattr(message, "channel", None) is None:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "missing_channel",
            )
        async with self._admission_lock:
            if not await self.rate_limiter.wait_if_needed():
                self.rate_limiter.record_dropped()
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "daily_quota",
                )

            async def attempt() -> None:
                kwargs = {
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "suppress_embeds": True,
                }
                if isinstance(
                    message.channel,
                    (discord.DMChannel, discord.GroupChannel),
                ):
                    await message.channel.send(text, **kwargs)
                else:
                    await message.reply(text, mention_author=False, **kwargs)

            try:
                await asyncio.wait_for(attempt(), timeout=15.0)
            except discord.errors.Forbidden:
                self.rate_limiter.record_failure()
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                )
            except discord.errors.HTTPException as exc:
                self.rate_limiter.record_sent()
                self.rate_limiter.record_failure(
                    is_rate_limit=(exc.status == 429),
                )
                return MessageSendResult(DeliveryState.UNKNOWN, "http")
            except TimeoutError:
                self.rate_limiter.record_sent()
                self.rate_limiter.record_failure()
                return MessageSendResult(DeliveryState.UNKNOWN, "timeout")
            except Exception:
                self.rate_limiter.record_sent()
                self.rate_limiter.record_failure()
                return MessageSendResult(DeliveryState.UNKNOWN, "transport")
            self.rate_limiter.record_sent()
            return MessageSendResult(DeliveryState.DELIVERED)
~~~

`MessageMonitor.__init__()` creates exactly one `self.discord_sender = DiscordSendCoordinator(self.rate_limiter)` before handlers. `MessageMonitor._send_response_result()` and `BaseHandler.send_response_result()` delegate to that exact object; neither has a private lock or a second check/wait/send/accounting path. `BaseHandler.send_response()` remains a one-release projection returning `True` only for `DELIVERED`, otherwise `None`.

`BaseHandler.send_response_result()` creates one owned coordinator task and shield-awaits it. If the outer task is cancelled, repeatedly settle that same owned task before propagating cancellation: a normal owned result is preserved; a self-cancelled owned task becomes `MessageSendResult(UNKNOWN, "send_task_cancelled")`; an escaped owned exception becomes `MessageSendResult(UNKNOWN, "send_task_exception")`. It then records the result in the task-local receipt and raises `MessageSendCancelled(result)`. It never starts a second send. A typed handler catches only `MessageSendCancelled`, computes `base_outcome.with_delivery(exc.result)`, and raises `DispatchCancelled(...)`; cancellation after manager commit therefore carries `mutated=True` and exact delivery certainty. Cancellation before manager entry retains `mutated=False`. Add a barrier test that commits a real manager candidate, pauses the acknowledgement, cancels the handler, and proves one manager write, one send attempt, a settled inner task, and a `DispatchCancelled` outcome with the committed mutation truth. Repeat for `DELIVERED`, `NOT_DELIVERED`, and `UNKNOWN` settlement plus repeated outer cancellation.

Use one shared private settlement helper from both `BaseHandler.send_response_result()` and `MessageMonitor._send_response_result()`. It saves only genuine outer cancellation (`asyncio.current_task().cancelling() > 0`), calls `uncancel()` once for each caught request solely so it can finish shield-awaiting, distinguishes an independently self-cancelled owned task from outer cancellation, converts only the former to `UNKNOWN/send_task_cancelled`, converts an escaped child exception to `UNKNOWN/send_task_exception`, records the terminal result once, and finally raises `MessageSendCancelled(result)` if any outer cancellation occurred. Tests assert the owned task is done before the carrier is raised. No generic `except Exception` surrounds or relabels `MessageSendCancelled`/`DispatchCancelled`.

Typed handlers follow this exact shape; only the base mutation/error outcome varies:

~~~python
base = DispatchOutcome.success(mutated=True)
try:
    send = await self.send_response_result(message, acknowledgement)
except MessageSendCancelled as exc:
    raise DispatchCancelled(base.with_delivery(exc.result)) from exc
return base.with_delivery(send)
~~~

For a pre-write error, `base` is the corresponding failure. `with_delivery()` is the only typed-path writer of `response_sent`/`delivery_result`; an `UNKNOWN` result remains terminal and cannot trigger handler, monitor, or pending-action fallback/retry.

### Exact manager adapter table

Every production handler receives the turn-captured aware `reference_time` and passes it unchanged to every time-dependent parser, selector, and `*_result(..., reference_time=reference_time)` manager call. A manager result API never calls its injected clock when this required production keyword is supplied. Offline compatibility projections may capture `self.clock.now()` once at their outer boundary and pass that value inward.

| Handler operation | Exact manager call or resolution |
|---|---|
| calendar create | `await calendar.add_item_result(guild_id, author.id, author.name, title, date_str, time_str, recurrence, recurrence_day, channel_id=channel_id, item_type=..., description=..., rrule_day=..., reference_time=reference_time)`. Before this call, the route/dispatch adapter converts any compatibility `days_offset` to one absolute canonical `date` using the shared `TemporalResolver` and the turn-captured `reference_time`, rejects disagreement with a supplied date, and removes `days_offset`; managers never receive a relative offset. The manager transaction—not the handler—writes a local `gcal_sync_pending` marker, invokes `create_event_result()`, and persists the provider ID/link when known. Historical `gcal_event_id`/`gcal_link` keywords may remain compatibility-only for imports, but typed handlers never precompute them or call `_sync_to_gcal()`. |
| calendar edit | Resolve number/ID/title to exactly one stable item ID, then call `await calendar.edit_item_result(item_id=..., reference_time=reference_time, **changes)`. Legacy positional/name wrappers are not production dispatch paths. |
| calendar delete | Resolve positive number/ID/title to exactly one stable item ID, then call `await calendar.delete_item_result(guild_id, item_id=..., reference_time=reference_time)`. Ambiguous/missing text returns `ambiguous_target`/`not_found` without deleting. |
| calendar complete | Resolve positive number/ID/title to exactly one stable item ID, then call `await calendar.complete_item_result(guild_id, item_id=..., reference_time=reference_time)`. |
| calendar clear | Requires `{"all": True}` and calls `await calendar.clear_calendar_result(guild_id, reference_time=reference_time)`. It never reparses a confirmation count from raw content; earlier risk/confirmation layers authorize it. |
| calendar sync | `await calendar.sync_from_gcal_result(default_guild_id=guild_id, default_channel_id=channel_id, reference_time=reference_time) -> CalendarSyncResult`; build all add/update/removal changes on one detached calendar snapshot and persist/publish once. The handler sends one terminal summary and never recursively calls `handle_list()` or `handle_sync()`. |
| calendar auth | URL initiation calls `gcal.get_auth_url_result(requester_id, channel_id)`; code exchange calls `gcal.exchange_code_result(code, requester_id, channel_id)`. Both return `ExternalMutationResult`; successful exchange may then call the same extracted sync-result function, never recursively invoke the handler. |
| reminder create, Task 6 boundary | `await reminders.add_reminder_result(guild_id, author.id, author.name, text, due_date, recurrence, channel_id=channel_id, reference_time=reference_time)`. Until Task 5 below extends the manager, `due_at`/`timezone` return pre-write `unsupported_temporal_field`. |
| reminder edit, Task 6 boundary | Call `await reminders.edit_reminder_result(..., reference_time=reference_time)`; `changes["text"]` maps to current `title`, `due_date` maps to current `date`, and `time`/`recurrence` pass unchanged. Resolve exactly one `number` or `reminder_id`; an ID is matched exactly and never converted through a current list position. `due_at`/`timezone` are rejected until Task 5. |
| reminder complete | `await reminders.complete_reminder_result(guild_id, reminder_num=number, reminder_id=reminder_id, reference_time=reference_time)`. |
| reminder delete | A positive number or stable ID resolves to one record, then calls `await reminders.delete_reminder_result(guild_id, reminder_id=..., reference_time=reference_time)`; never call the offline positional wrapper in production. |
| reminder search/list | `format_search_results(guild_id, query, lang)` or `format_reminders_list(guild_id, show_completed=True)`; no mutation. |
| poll create | `await poll.create_poll_result(guild_id, question, options, author.name, created_by_id=author.id)`. |
| poll vote | Use exact `poll_id` when supplied; otherwise resolve the one active poll required by the immediate compatibility contract. Then call `await poll.vote_result(guild_id, poll_id, option, author.id, author.name)`. |
| poll edit/delete/close | Resolve `poll_id` directly when supplied; otherwise resolve positional `target` through `_resolve_poll_id`. Call the corresponding async `edit_poll_result`, `delete_poll_result`, or `close_poll_result` with current ownership arguments. |
| watchlist add | `await watchlist.add_watchlist_result(title, content_type=payload.get("type") or "movie", guild_id=guild_id, genre=genre, comment=comment)`. |
| watchlist edit | `await watchlist.edit_watchlist_result(index, title=title, type=type, genre=genre, comment=comment, guild_id=guild_id)`. |
| watchlist remove | `await watchlist.remove_watchlist_result(index, guild_id=guild_id)`. |
| quote save | `await quote.add_quote_result(guild_id, text, payload.get("author") or author.name)`. |
| quote edit/delete | `await quote.update_quote_result(guild_id, index, text=text, author=author)` or `await quote.delete_quote_result(guild_id, index)`. |
| birthday create | `await birthdays.create_birthday_result(guild_id, user_id, display_name, day, month, year)`; it is create-only and typed code consumes its complete `BirthdayWriteResult`. |
| birthday list | `scope == "upcoming"` calls `birthdays.format_upcoming_birthdays(guild_id, days=30)`; omitted/`all` calls `birthdays.format_birthday_list(guild_id)`. It is read-only and sends exactly the returned bounded string. |
| birthday edit | Add async `BirthdayManager.edit_birthday_by_user_id_result(guild_id, user_id, day, month, year=None)` and call it. Preserve `edit_birthday(guild_id, name, day, month, year=None)` only as the offline compatibility projection; the handler must not fuzzy-match a typed user ID by display name. |
| set location | Resolve `city` through the finite `NORWEGIAN_CITIES` table before any write, then call `await user_memory.set_location_result(author.id, canonical_name)`. Unknown cities make no manager call; storage/cancellation errors retain exact mutation truth. |
| memory delete | After the model-actions lane supplies a matching claimed capability, call `await user_memory.delete_user_memory_result(author.id)` under `MEMORY_STORE_SCOPE`. The existing async `delete_user_memory()` name remains an awaitable compatibility delegator, and payload flags are never authorization. |

### Exact manager-result to dispatch-result table

Handlers must interpret manager results before sending acknowledgement copy. Pin these mappings; never infer success merely because a call returned without raising:

Add this exact immutable result and transactional async `create_birthday_result(...)` / `edit_birthday_by_user_id_result(...)` APIs for typed handlers:

~~~python
@dataclass(frozen=True, slots=True)
class BirthdayWriteResult:
    success: bool
    mutated: bool
    sync_pending: bool
    error_code: str | None = None
    commit_unknown: bool = False

    def __bool__(self) -> bool:
        # Compatibility means the requested local record was accepted even
        # when best-effort external synchronization remains pending.
        return self.success or self.mutated
~~~

Add this exact calendar sync result:

~~~python
@dataclass(frozen=True, slots=True)
class CalendarSyncResult:
    ok: bool
    mutated: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    error_code: str | None = None
    commit_unknown: bool = False
~~~

`GoogleCalendarManager` adds `create_event_result()`, `update_event_result()`, `delete_event_result()`, `get_auth_url_result()`, `exchange_code_result()`, and `list_upcoming_events_result()` as the only structured sources of truth. Transactional calendar/birthday/auth/sync paths call only these APIs. Preserve existing public projections for one release: `create_event()`/`update_event()` return the historical dict or `None`, `delete_event()` returns bool, `get_auth_url()`/`exchange_code()` return `(bool, str)`, and `list_upcoming_events()` returns list or `None`. A compatibility wrapper reads `.ok/.state/.value`; it never returns the dataclass to an old dict/bool/tuple caller. Add exact legacy-shape tests for every wrapper and prove a dataclass's truthiness can never leak into old `bool(delete_event(...))` code.

Provider classification is pinned: disabled/preflight invalid is `ok=False, UNCHANGED`; authoritative invalid-code/not-found rejection is `ok=False, UNCHANGED`; positive create/update/delete/token exchange or created auth flow is CHANGED; timeout/transport/malformed response after a mutating request is `ok=False, UNKNOWN`; token exchange followed by token-file failure is `ok=False, CHANGED, error_code="token_storage_failed"` because the code was consumed/provider credentials issued; a list/GET failure with no refresh is `ok=False, UNCHANGED, error_code="external_read_failed"`. `_save_credentials()` propagates failures and never prints token/URL/code/exception text. After any dispatched code exchange, clear the one-time flow state so retry cannot silently reuse a consumed code.

The manager validates first, writes the local record atomically with `gcal_sync_pending=True` before any external create/update, and leaves its published dictionary unchanged if that first local save fails. Only then may it call Google Calendar. An authoritative external rejection leaves the already-persisted pending marker and returns `success=False, mutated=True, sync_pending=True, commit_unknown=False, error_code="external_sync_pending"`. A post-dispatch timeout/ambiguous response returns the same durable marker truth but `commit_unknown=True, error_code="external_commit_unknown"`. A successful sync stores the external ID and clears the marker in a second atomic save. If that second save fails, the first persisted pending marker remains authoritative.

`create_birthday_result(...)` checks the exact guild/user key under the birthday scope lock and returns `success=False, mutated=False, error_code="already_exists"` when present; only edit may overwrite a typed record. Preserve both legacy return contracts: `add_birthday(...) -> bool` calls the shared private transaction with `allow_replace=True` and returns whether the local mutation was accepted (`result.success or result.mutated`), so historical upsert and best-effort GCal-failure truth remain compatible; `edit_birthday(guild_id, name, ...) -> dict` resolves the legacy case-insensitive name, delegates to the same internal user-ID transaction, and returns the updated record for existing index-based callers. Only the two typed methods return `BirthdayWriteResult`. Typed handlers inspect all five fields and never rely on truthiness. Inject existing-record, concurrent absent-to-present, first-save, provider-changed, provider-authoritatively-unchanged, provider-commit-unknown, and second-save failures, plus explicit compatibility truth/record tests.

The table defines the base outcome before acknowledgement. After choosing the row, the handler sends once through `send_response_result()` and returns `base.with_delivery(send)` (or carries that same finalized outcome in `DispatchCancelled` on cancellation). No row writes `response_sent` directly.

| Adapter result | Exact base `DispatchOutcome` before send |
|---|---|
| calendar create/edit/complete returns its documented nonempty success record/tuple | `success(mutated=True)` |
| calendar delete has `requested_count == 0` | `failure("not_found", mutated=False, retryable=True)` |
| calendar delete has `deleted_count > 0` and `pending_count == 0` | `success(mutated=True)` |
| calendar delete has `pending_count > 0` (including zero deleted) | `failure("partial_delete_pending" if deleted_count else "external_delete_pending", mutated=True, retryable=False)` because persisted `delete_pending` is already a write |
| calendar clear has `requested_count == 0` | `success(mutated=False)` (truthful idempotent no-op) |
| calendar clear has `deleted_count > 0` and `failed_count == 0` | `success(mutated=True)` |
| calendar clear has `failed_count > 0` | `failure("partial_delete_pending" if deleted_count else "external_delete_pending", mutated=True, retryable=False)` because deletions and/or pending markers were persisted |
| calendar sync result is ok with no calendar/auth change | `success(mutated=False)` |
| calendar sync result is ok with any add/update/remove or credential change | `success(mutated=True)` |
| calendar sync provider read fails before any state change | `failure("external_read_failed", mutated=False, retryable=True)` |
| calendar sync local atomic save fails with no external credential change | `failure("storage_write_failed", mutated=False, retryable=True)` |
| calendar sync is partial/unknown or local save follows CHANGED/UNKNOWN credential state | preserve `mutated`/`commit_unknown`, return terminal bounded failure, and never publish a partial calendar candidate |
| calendar auth URL flow is created | `success(mutated=True)`; ephemeral OAuth flow state is a real mutation |
| calendar auth preflight/authoritative rejection is UNCHANGED | bounded non-retryable failure with `mutated=False`; copy instructs the user to start a fresh flow when required |
| calendar auth exchange is CHANGED and persisted | `success(mutated=True)`, even if acknowledgement fails |
| calendar auth exchange is CHANGED but token persistence fails | `failure("token_storage_failed", mutated=True, retryable=False)` |
| calendar auth exchange is UNKNOWN after the request was dispatched and one-time flow state was cleared | `failure("external_commit_unknown", mutated=True, retryable=False, commit_unknown=True)`; clearing the local flow is a proven mutation even though provider commit truth is unknown |
| set location city is unknown | `failure("unsupported_city", mutated=False, retryable=False)` and zero memory calls |
| set location persists the canonical city | `success(mutated=True)`; an already-equal city is `success(mutated=False)` |
| set location storage rollback/unknown | exact `storage_write_failed` retryable pre-write rollback or terminal `commit_state_unknown`; never swallow into `None` |
| birthday write result has `success=True, mutated=True` | `success(mutated=True)` |
| birthday write result has `success=False, mutated=False, error_code="storage_write_failed"` after proven rollback/no external call | `failure("storage_write_failed", mutated=False, retryable=True)` |
| birthday write result has `success=False, mutated=True, sync_pending=True` | `failure("external_sync_pending", mutated=True, retryable=False)` |
| birthday write result also has `commit_unknown=True` | `failure("external_commit_unknown", mutated=True, retryable=False, commit_unknown=True)`; this row takes precedence over generic sync-pending |
| typed birthday create finds an existing record for that user | `failure("already_exists", mutated=False, retryable=False)`; only edit may overwrite |
| birthday list returns a string | `success(mutated=False)` using the exact scope-selected formatter above |
| watchlist add returns `True`; edit/remove returns a record | `success(mutated=True)` |
| watchlist add returns `False` or edit returns `None` | `failure("manager_rejected" if add else "not_found", mutated=False, retryable=False)` |
| quote/poll manager returns its documented false/`None` failure sentinel before write | `failure("manager_rejected", mutated=False, retryable=False)` |
| calendar/reminder completion false tuple, or a documented bounded not-found `ValueError` from calendar, reminder, birthday, watchlist, or quote lookup before write | `failure("not_found", mutated=False, retryable=True)` |
| reminder manager rejects the resolved post-edit state with bounded `invalid_recurrence` before write | `failure("invalid_payload", mutated=False, retryable=False)` |
| manager raises `ManagerMutationError("storage_write_failed", mutated=False)` after exact rollback and no external change | `failure("storage_write_failed", mutated=False, retryable=True)` |
| manager raises `ManagerMutationError("external_state_changed_storage_failed", mutated=True)` | `failure("external_state_changed_storage_failed", mutated=True, retryable=False)` |
| manager raises `ManagerMutationError("external_commit_unknown", mutated=..., commit_unknown=True)` | preserve both bits in `failure("external_commit_unknown", ..., retryable=False, commit_unknown=True)` |
| manager/provider reports external commit ambiguity | `failure("external_commit_unknown", mutated=local_marker_saved, retryable=False, commit_unknown=True)` |
| any adapter raises after mutator entry and commit state cannot be classified | `failure("commit_state_unknown", mutated=False, retryable=False, commit_unknown=True)`; do not retry, expose exception text, or claim no write occurred |

- [ ] **Step 3.0a (3-5 min): Write storage-failure injection tests for every local JSON action family.**

In `tests/test_mutation_commit_contract.py`, parameterize real CalendarManager, ReminderManager, PollManager, WatchlistManager, QuoteManager, and UserMemory mutators with an atomic writer that raises `OSError("sentinel")`. For one create and one update/delete shape where applicable, snapshot both serialized bytes and deep-copied in-memory scope, await the real result API, and assert `ManagerMutationError(code="storage_write_failed", mutated=False)`, byte identity, and unchanged published memory. Cover all exact UserMemory result writers: get-or-create, username fill, last interaction, interest, preference, location, and delete. Assert the async compatibility names remain awaitable with their historical shapes and reserve running-loop rejection tests for historically synchronous wrappers. Add a barrier-controlled Calendar clear and two concurrent UserMemory writers: while save is blocked, readers see the old snapshot; successful release publishes once, failed release publishes nothing, and no nested-lock deadlock occurs. Inject the same coordinator into manager and a simulated pending caller; while that caller holds a family scope, a background writer/checker must block, and same-task manager re-entry must complete. No assertion may inspect/log the exception string.

Add external-success/local-save-failure cases for calendar create, edit, complete, delete, and clear. When no provider request is dispatched or an authoritative rejection proves unchanged, failed local persistence is non-mutating/retryable; when at least one injected GCal create/update/delete succeeds before the local save fails, retain the last durable pending marker when one exists and raise `external_state_changed_storage_failed, mutated=True`. For calendar and birthday create/update/delete, inject a provider side effect followed by timeout plus pending/local-save failure; it must map terminal `external_commit_unknown, commit_unknown=True`, never retry. Add an unclassified post-entry exception test that maps to `commit_state_unknown=True` and bounded unknown-state copy. Barrier-cancel a `to_thread` local save and a provider call: await the owned work to known completion, assert disk equals published memory, and assert the carried outcome cannot return to retryable READY.

In `tests/test_google_calendar_result_compat.py`, pin every structured result and legacy projection: dict/None create/update, bool delete, tuple auth, list/None read, provider-side-effect-then-timeout UNKNOWN, consumed-code-plus-token-save-failure CHANGED, and a process-wide auth-exchange-versus-refresh barrier across two `GoogleCalendarManager` instances. Assert token-file bytes parse as one whole old/new JSON document and logs contain no code, URL, token, or injected exception text.

In `tests/test_auxiliary_dispatch_outcomes.py`, cover `handle_sync`, `handle_auth`, and `_handle_set_location`: sync no-op/change/read-failure/save-rollback/multi-event atomic failure; auth URL/exchange/rejection/token-save/unknown and auth-versus-create/sync serialization on `CALENDAR_SHARED_SCOPE`; location unknown/equal/change/save-failure/unknown. A sync with three remote changes and the second candidate transformation/save failure publishes either all three or none, never one/two. Every branch asserts exact `DispatchOutcome` and bounded send count/copy.

- [ ] **Step 3.0b (3-5 min): Implement the shared snapshot/mutate/save contract.**

Make CalendarManager `_save_data_sync()` re-raise atomic-writer errors and implement the structured Google result APIs plus compatibility projections above. Add the async result methods named in the adapter table for calendar, reminder, poll, watchlist, quote, birthday, and user memory; every production handler/checker/background caller awaits those methods. Each result method holds the shared `MutationCoordinator` scope, mutates a detached candidate, writes that candidate, and atomically publishes it only after success; failure leaves the live snapshot untouched and raises the exact `ManagerMutationError`. Move calendar create/edit/complete GCal calls inside the manager transaction, just like delete/clear; a typed handler may not call `_sync_to_gcal()` or perform an untracked external mutation before calling the manager. A manager method must not return its historical success sentinel until the save and publish complete. Preserve public success signatures/read APIs via offline wrappers, not by returning `ExternalMutationResult` to legacy callers. Do not catch `ManagerMutationError`, `ManagerMutationCancelled`, or `DispatchCancelled` inside a generic `except Exception` and relabel it.

Run a production-call-site gate after migration: no synchronous mutation wrapper may be called from `core/`, `features/`, `cal_system/reminder_checker.py`, or background setup; allow only its definition and the explicit offline compatibility test. This gate is required before Task 4 because one bypass would invalidate pending-target atomicity later.

Run:

~~~bash
.venv312/bin/python -m pytest \
  tests/test_mutation_commit_contract.py \
  tests/test_user_memory_controls.py -q
~~~

Expected: PASS with all disk/in-memory rollback and external-partial branches proven.

- [ ] **Step 3.0c (2 min): Commit the durable manager boundary.**

~~~bash
git add cal_system/calendar_manager.py cal_system/google_calendar_manager.py \
  cal_system/reminder_manager.py cal_system/reminder_checker.py \
  core/message_context.py \
  features/poll_manager.py features/watchlist_manager.py \
  features/quote_manager.py features/birthday_manager.py \
  features/daily_digest_manager.py memory/user_memory.py \
  tests/test_mutation_commit_contract.py tests/test_user_memory_controls.py \
  tests/test_google_calendar_result_compat.py
git commit -m "fix: make local mutations rollback safe"
~~~

- [ ] **Step 3.0d (3-5 min): Write canonical handler-send and cancellation tests.**

In `tests/test_message_send_result.py`, pin `DELIVERED`, definite empty/quota/forbidden `NOT_DELIVERED`, timeout/HTTP/transport `UNKNOWN`, finite error codes, `AllowedMentions.none()`, `suppress_embeds=True`, and one shared admission lock across monitor and handler calls. Assert `BaseHandler.send_response_result()` records all three states in the task-local receipt, while the compatibility `send_response()` returns `True` only for `DELIVERED`. Add cancel-after-manager-commit-before-ack barriers for each terminal send state and repeated cancellation; assert one manager mutation, one Discord attempt, no fallback, and the exact `DispatchCancelled(base.with_delivery(result))`.

- [ ] **Step 3.0e (3-5 min): Implement the shared sender and canonical BaseHandler API.**

Create `core/send_receipt.py`, add `BaseHandler.send_response_result()`, retain only the documented compatibility projection, and construct one `DiscordSendCoordinator` in `MessageMonitor` before handlers. Also capture one aware `reference_time` after authorization and thread it into routing and every migrated handler call so Task 3 commits remain green; do not yet change the complete envelope/outcome dispatch chain, which Task 4 owns.

- [ ] **Step 3.0f (2 min): Run and commit the canonical send boundary.**

~~~bash
.venv312/bin/python -m pytest tests/test_message_send_result.py -q
git add core/send_receipt.py core/message_monitor.py \
  features/base_handler.py tests/test_message_send_result.py
git commit -m "refactor: share typed Discord delivery truth"
~~~

Expected: the sender tests pass before any typed handler is migrated, so every later handler can use `send_response_result()` without an interim boolean contract.

- [ ] **Step 3.1 (3-5 min): Add real calendar no-reparse tests for edit, delete, complete, and clear.**

Replace `message.content` with a contradictory sentinel and make `_parse_edit_command`, `_extract_search_text`, `_extract_target_index`, `_clear_confirmation_count`, and handler `_sync_to_gcal` raise if called. Assert the exact manager calls from the table. Parameterize delete/clear results for not-found/no-op, full success, external-pending-only, and partial-delete-plus-pending; assert the exact `ok/mutated/retryable/error_code` tuple so a persisted pending marker can never return retryable or unmutated. Add the sync/auth/location outcome file here and prove typed calendar create never calls a provider directly.

- [ ] **Step 3.2 (2 min): Run the calendar tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_calendar_edit.py \
  tests/test_auxiliary_dispatch_outcomes.py tests/test_parse_once_dispatch.py -q
~~~

Expected: failures show that calendar handlers still reparse raw content and return `None`.

- [ ] **Step 3.3 (3-5 min): Add optional `item_type`, `description`, and `rrule_day` fields to `CalendarManager.add_item()`.**

Keep the positional signature compatible by making the three additions keyword-only. Store them on new records only; loading existing records remains unchanged.

- [ ] **Step 3.4 (3-5 min): Migrate calendar create/edit to typed input and `DispatchOutcome`; finalize every branch through `send_response_result()` and `with_delivery()`.**

- [ ] **Step 3.5 (3-5 min): Migrate calendar delete/complete/clear to typed input and `DispatchOutcome`; preserve `UNKNOWN` delivery as terminal and never retry/fallback.**

- [ ] **Step 3.6 (2 min): Re-run Step 3.2.**

Expected: calendar focused tests pass and no sentinel parser is called.

- [ ] **Step 3.7 (2 min): Commit the calendar adapter.**

~~~bash
git add features/calendar_handler.py cal_system/calendar_manager.py \
  cal_system/google_calendar_manager.py core/message_monitor.py memory/user_memory.py \
  tests/test_calendar_edit.py tests/test_auxiliary_dispatch_outcomes.py \
  tests/test_parse_once_dispatch.py
git commit -m "refactor: consume typed calendar actions"
~~~

- [ ] **Step 3.8 (3-5 min): Add reminder no-reparse tests for create/edit/delete/complete/search.**

Make the handler's imported `parse_reminder_command`, `_parse_edit_command`, `extract_number`, and `_parse_search_query` raise on the typed path. Assert the Task 6 boundary mapping, exact-ID edit targeting, and a pre-write `unsupported_temporal_field` outcome. The routing-owned `parse_reminder_command` already produced the typed edit envelope before handler entry; no second edit parser exists.

- [ ] **Step 3.9 (2 min): Run the reminder slice.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_crud.py tests/test_parse_once_dispatch.py -q
~~~

Expected: failures identify raw parser calls and missing outcomes.

- [ ] **Step 3.10 (3-5 min): Migrate reminder create/list/search/complete using `send_response_result()` and the captured `reference_time`.**

- [ ] **Step 3.11 (3-5 min): Migrate reminder edit/delete, add the intermediate temporal rejection, and carry send cancellation with exact mutation truth.**

- [ ] **Step 3.12 (2 min): Re-run Step 3.9.**

Expected: reminder Task 6 adapter tests pass; canonical `due_at` support remains intentionally red until Task 5.

- [ ] **Step 3.13 (2 min): Commit the Task 6 reminder adapter.**

~~~bash
git add features/reminder_handler.py tests/test_reminder_crud.py tests/test_parse_once_dispatch.py
git commit -m "refactor: consume typed reminder actions"
~~~

- [ ] **Step 3.14 (3-5 min): Add poll mutation tests with manager spies.**

Cover create, vote, edit, delete, and close. Assert owner ID/name, target resolution, question/options, and truthful manager failure outcomes.

- [ ] **Step 3.15 (2 min): Run the poll tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_poll_target.py tests/test_parse_once_dispatch.py -q
~~~

Expected: failures show handlers returning `None` rather than `DispatchOutcome`.

- [ ] **Step 3.16 (3-5 min): Migrate all poll mutations and reads in scope through the canonical tri-state send API.**

- [ ] **Step 3.17 (2 min): Re-run Step 3.15.**

Expected: poll tests pass.

- [ ] **Step 3.18 (2 min): Commit poll adapters.**

~~~bash
git add features/polls_handler.py tests/test_poll_target.py tests/test_parse_once_dispatch.py
git commit -m "refactor: consume typed poll actions"
~~~

- [ ] **Step 3.19 (3-5 min): Add watchlist and birthday sentinel tests.**

For watchlist add/edit/remove, use unrelated `message.content` and make `parse_watchlist_command` raise. Pin add `False` and edit `None` as non-mutating failures. For birthday create/list/edit, make every legacy birthday parser raise; assert the exact user-ID mutation calls, plus `scope=all -> format_birthday_list()` and `scope=upcoming -> format_upcoming_birthdays(days=30)`. Inject birthday first-save rollback, external-sync pending, and second-save pending cases and assert their exact retryable/terminal mutation truth from the result table.

- [ ] **Step 3.20 (3-5 min): Add the mandatory real quote-handler sentinel test.**

~~~python
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.dispatch_result import DeliveryState, DispatchOutcome, MessageSendResult
from features.quote_handler import QuoteHandler
from features.quote_manager import QuoteManager


@pytest.mark.asyncio
async def test_real_quote_edit_uses_typed_text_and_author_with_sentinel_content(
    tmp_path,
):
    manager = QuoteManager(tmp_path / "quotes.json")
    seeded = await manager.add_quote_result(123, "Gammel tekst", "Ola")
    assert seeded.success is True
    monitor = SimpleNamespace(
        quote=manager,
        rate_limiter=object(),
        loc=SimpleNamespace(t=lambda key, **values: key, current_lang="no"),
        client=None,
        nlu_metrics=Mock(),
    )
    handler = QuoteHandler(monitor)
    delivered = MessageSendResult(DeliveryState.DELIVERED)
    handler.send_response_result = AsyncMock(return_value=delivered)
    handler.extract_number = Mock(
        side_effect=AssertionError("raw content was reparsed"),
    )
    handler._extract_edit_fields_from_content = Mock(
        side_effect=AssertionError("raw content was reparsed"),
    )
    message = SimpleNamespace(
        content="SENTINEL RAW CONTENT THAT MUST NOT BE PARSED",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=789, name="Avsender"),
    )

    outcome = await handler.handle_quote_edit(
        message,
        {
            "action": "edit",
            "index": 1,
            "text": "Ny tekst",
            "author": "Kari",
            "lang": "no",
        },
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(delivered)
    stored = manager.list_quotes(123)[0]
    assert stored["text"] == "Ny tekst"
    assert stored["author"] == "Kari"
    handler.extract_number.assert_not_called()
    handler._extract_edit_fields_from_content.assert_not_called()
~~~

This test must use the real `QuoteHandler` and real `QuoteManager`, not an `AsyncMock` handler.

- [ ] **Step 3.21 (2 min): Run the watchlist/birthday/quote slice.**

~~~bash
.venv312/bin/python -m pytest tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py tests/test_parse_once_dispatch.py -q
~~~

Expected: failures expose raw parsing and missing outcome/user-ID adapters.

- [ ] **Step 3.22 (3-5 min): Add `BirthdayManager.edit_birthday_by_user_id_result()` by factoring the existing edit write path.**

Define the immutable `BirthdayWriteResult` and one private user-ID transaction implementing the two-phase local-pending/external-sync algorithm from the result table. Awaited create-only `create_birthday_result(...)` and `edit_birthday_by_user_id_result(...)` return that result; create returns bounded `already_exists` without a write when the exact key is present, and edit returns bounded `not_found` when absent. Preserve `add_birthday(...) -> bool`, `edit_birthday_by_user_id(...)`, and `edit_birthday(guild_id, name, ...) -> dict` only as offline compatibility projections that reject inside a running event loop. Test existing-record and simultaneous absent-to-present creates under the birthday scope lock (exactly one success), all three failure injection points, legacy truthiness after sync failure, event-loop rejection, and record indexing through the legacy edit wrapper. Do not duplicate JSON writes or GCal calls in handlers.

- [ ] **Step 3.23 (3-5 min): Migrate watchlist add/edit/remove and status/suggest through `send_response_result()`.**

- [ ] **Step 3.24 (3-5 min): Migrate quote save/get/list/edit/delete through `send_response_result()`.**

`FunHandler.handle_quote_command()` handles save/get; `QuoteHandler` handles list/edit/delete. All use the one `quote` family payload.

- [ ] **Step 3.25 (3-5 min): Migrate birthday create/list/edit with the exact list-scope/result table and tri-state delivery finalization.**

- [ ] **Step 3.26 (2 min): Re-run Step 3.21.**

Expected: all tests pass; the real quote record contains both new values despite contradictory raw content.

- [ ] **Step 3.27 (2 min): Commit the remaining handler adapters.**

~~~bash
git add features/poll_manager.py features/watchlist_handler.py features/watchlist_manager.py \
  features/fun_handler.py features/quote_handler.py features/quote_manager.py \
  features/birthday_handler.py features/birthday_manager.py \
  features/daily_digest_manager.py memory/user_memory.py \
  tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py \
  tests/test_parse_once_dispatch.py tests/test_user_memory_controls.py \
  tests/test_mutation_commit_contract.py
git commit -m "refactor: consume typed utility actions"
~~~

---

### Task 4: Make `MessageMonitor` return validated dispatch truth

**Files:**

- Modify: `core/message_monitor.py`
- Modify: `core/send_receipt.py`
- Modify: `features/base_handler.py`
- Modify: `features/calendar_handler.py`
- Modify: `features/reminder_handler.py`
- Modify: `features/polls_handler.py`
- Modify: `features/watchlist_handler.py`
- Modify: `features/fun_handler.py`
- Modify: `features/quote_handler.py`
- Modify: `features/birthday_handler.py`
- Modify: `tests/test_message_monitor_routing.py`
- Modify: `tests/test_parse_once_dispatch.py`
- Modify: `tests/test_calendar_edit.py`
- Modify: `tests/test_reminder_crud.py`
- Modify: `tests/test_poll_target.py`
- Modify: `tests/test_watchlist_birthday_edit.py`
- Modify: `tests/test_quote_crud.py`
- Modify: `tests/test_message_send_result.py`

**Interfaces:**

- Consumes: Task 1's `ENVELOPE_KEYS`, `validate_intent_payload()`, and `DispatchOutcome`; Tasks 2–3's canonical envelopes and typed handler signatures.
- Produces: a temporary `MessageMonitor.nlu_metrics is MessageMonitor.intent_router.metrics` ownership alias (the model-actions lane later moves construction ahead of all consumers), `MessageMonitor._typed_inner_payload(route)`, task-local tri-state `capture_send_receipt()`, `_invoke_legacy_read(callback)`, and a single dispatch chain returning delivery-attached `DispatchOutcome`; malformed present envelopes fail closed and absent canonical envelopes alone may enter the one-release compatibility path.

The dispatch signature is exact and temporal values are never re-read mid-turn:

~~~python
async def _handle_intent(
    self,
    message,
    route: IntentResult,
    *,
    reference_time: datetime,
) -> DispatchOutcome:
    ...
~~~

`handle_message()` captures one aware `reference_time = self.reminder_clock.now()` after authorization. It passes that exact object to `IntentRouter.route(..., routing_context=routing_context, reference_time=reference_time)` and `_handle_intent(..., reference_time=reference_time)`. Every calendar and reminder branch passes the same keyword to its handler; every reminder handler passes it to parser fallback and manager result APIs. No router collector, handler, manager, selector, or resolver calls a wall clock/clock provider again during the turn. All tests call `_handle_intent` with the fixed aware clock value, and an advancing clock spy proves exactly one provider read for the complete route-to-manager flow.

Use this envelope algorithm:

~~~python
def _typed_inner_payload(self, route):
    key = ENVELOPE_KEYS.get(route.intent)
    if key is None:
        return _NO_TYPED_ENVELOPE
    if key not in route.payload:
        return None
    return validate_intent_payload(
        route.intent,
        route.payload[key],
        source=route.source,
    )
~~~

`_NO_TYPED_ENVELOPE` distinguishes unrelated legacy read intents from an action family whose compatibility envelope is absent. A present malformed value raises `PayloadValidationError` and never falls back.

Global `response_count` is telemetry and must never determine one turn's dispatch truth. Use Task 3's task-local tri-state receipt from `core/send_receipt.py` (the exact implementation contract is repeated here because Task 4 integrates it with legacy reads):

~~~python
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from core.dispatch_result import DeliveryState, MessageSendResult


@dataclass(slots=True)
class SendReceipt:
    result: MessageSendResult | None = None

    def observe(self, result: MessageSendResult) -> None:
        current = self.result
        if current is not None and current.state is DeliveryState.UNKNOWN:
            return
        if result.state is DeliveryState.UNKNOWN:
            self.result = result
        elif current is not None and {
            current.state,
            result.state,
        } == {
            DeliveryState.DELIVERED,
            DeliveryState.NOT_DELIVERED,
        }:
            self.result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "partial_send",
            )
        elif result.state is DeliveryState.DELIVERED:
            self.result = result
        elif current is None:
            self.result = result


_CURRENT_RECEIPT: ContextVar[SendReceipt | None] = ContextVar(
    "dispatch_send_receipt",
    default=None,
)


@contextmanager
def capture_send_receipt() -> Iterator[SendReceipt]:
    receipt = SendReceipt()
    token = _CURRENT_RECEIPT.set(receipt)
    try:
        yield receipt
    finally:
        _CURRENT_RECEIPT.reset(token)


def record_send_result(result: MessageSendResult) -> None:
    receipt = _CURRENT_RECEIPT.get()
    if receipt is not None:
        receipt.observe(result)
~~~

Both canonical result senders call `record_send_result(result)` exactly once after their owned send settles, including `NOT_DELIVERED` and `UNKNOWN`; the compatibility wrappers do not record a second time. `response_count` increments only for `DELIVERED`. For unchanged legacy read handlers, use:

~~~python
async def _invoke_legacy_read(self, callback) -> DispatchOutcome:
    with capture_send_receipt() as receipt:
        try:
            result = await callback()
        except Exception:
            base = DispatchOutcome.failure("handler_exception")
            return (
                base
                if receipt.result is None
                else base.with_delivery(receipt.result)
            )
    if isinstance(result, DispatchOutcome):
        if result.delivery_result is not None:
            return result
        base = result
    else:
        base = DispatchOutcome.success(mutated=False)
    return (
        base
        if receipt.result is None
        else base.with_delivery(receipt.result)
    )
~~~

An unchanged legacy callback that observed `UNKNOWN` therefore returns `response_sent=False` **and** `delivery_result.state=UNKNOWN`; monitor/pending fallback code must check delivery certainty and must not retry or send alternate copy. Typed handlers already return their own attached result and never depend on the receipt for truth.

- [ ] **Step 4.1 (3-5 min): Add monitor-level envelope tests for every family key.**

Each handler is an `AsyncMock` returning a fixed outcome. Assert it receives the inner value, never the outer dictionary.

- [ ] **Step 4.2 (2-4 min): Add low-confidence and invalid-payload tests.**

Low confidence preserves the current fallback behavior and returns a bounded `low_confidence` failure. A malformed present envelope returns `invalid_payload` and invokes zero handlers/managers.

- [ ] **Step 4.3 (2-4 min): Add truthful tri-state outcome propagation tests.**

Cover success with mutation plus `DELIVERED`/`NOT_DELIVERED`/`UNKNOWN`, retryable not-found finalized by each state, non-retryable handler exception, and unmodified read-handler task-local send adaptation. `response_sent` is true only for `DELIVERED`; `UNKNOWN` retains its finite code, clears retryability, and suppresses outer fallback. Add two barrier-interleaved messages: only the other task sends while the legacy callback waits; the silent task's receipt remains empty even though global `response_count` increments. Also prove nested handler/monitor send paths observe only the current task receipt and both mixed orders (`DELIVERED -> NOT_DELIVERED` and `NOT_DELIVERED -> DELIVERED`) become `UNKNOWN/partial_send`.

- [ ] **Step 4.4 (3-5 min): Add one-release compatibility and metrics-ownership tests.**

For each family, omit the canonical envelope and assert one `legacy_payload_fallback` metric. Then provide a typed payload plus contradictory sentinel content and assert zero fallback metrics. Construct the real monitor through the offline fixture and assert `monitor.nlu_metrics is monitor.intent_router.metrics`; this prevents the compatibility handler from depending on a metrics attribute that does not exist until a later lane.

- [ ] **Step 4.5 (2 min): Run monitor dispatch tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py \
  tests/test_message_monitor_routing.py tests/test_message_send_result.py -q
~~~

Expected: failures show outer dictionaries passed to quote/reminder/birthday handlers and `_handle_intent()` returning `None`.

- [ ] **Step 4.6 (3-5 min): Expose the router-owned metrics sink and add `_typed_inner_payload()`.**

Immediately after the existing `self.intent_router = IntentRouter(self)` construction, set `self.nlu_metrics = self.intent_router.metrics`. Do not construct another `NLUMetrics` in this lane. Then add `_typed_inner_payload()` and bounded validation-failure handling. The model-actions lane later replaces this initialization order with one monitor-owned instance injected into the router, pending store, and action handler.

- [ ] **Step 4.7 (3-5 min): Pass only inner typed values to migrated handlers.**

Use the exact envelope map. Do not add operation-specific reminder, birthday, or quote keys.

- [ ] **Step 4.8 (3-5 min): Return handler `DispatchOutcome` for every migrated action branch and audit every typed handler for `send_response_result()`/`with_delivery()` only.**

- [ ] **Step 4.9 (3-5 min): Adapt unchanged read-only branches with `_invoke_legacy_read()`.**

- [ ] **Step 4.10 (2-4 min): Keep exception logging separate from the bounded outcome.**

Logs may retain the existing exception diagnostics; `DispatchOutcome.error_code` remains the fixed `handler_exception` code.

- [ ] **Step 4.11 (2 min): Re-run Step 4.5.**

Expected: all parse-once and monitor routing tests pass.

- [ ] **Step 4.12 (2 min): Run the complete Task 6 focused gate.**

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py \
  tests/test_message_monitor_routing.py tests/test_message_send_result.py \
  tests/test_calendar_edit.py tests/test_reminder_crud.py \
  tests/test_poll_target.py tests/test_watchlist_birthday_edit.py \
  tests/test_quote_crud.py -q
~~~

Expected: PASS with zero typed-path raw reparses.

- [ ] **Step 4.13 (2 min): Commit completed Task 6 dispatch.**

~~~bash
git add core/message_monitor.py core/send_receipt.py features/base_handler.py \
  features/calendar_handler.py features/reminder_handler.py \
  features/polls_handler.py features/watchlist_handler.py \
  features/fun_handler.py features/quote_handler.py features/birthday_handler.py \
  tests/test_message_monitor_routing.py tests/test_parse_once_dispatch.py \
  tests/test_message_send_result.py tests/test_calendar_edit.py \
  tests/test_reminder_crud.py tests/test_poll_target.py \
  tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py
git commit -m "refactor: dispatch validated intent payloads once"
~~~

Expected: Task 6 is a reviewable commit boundary before reminder temporal behavior changes.

---

### Task 5: Add one reminder clock and canonical temporal records

**Files:**

- Modify: `cal_system/reminder_clock.py`
- Create: `tests/test_reminder_runtime.py`
- Modify: `cal_system/temporal_resolver.py`
- Modify: `cal_system/reminder_manager.py`
- Modify: `features/reminder_handler.py`
- Modify: `tests/test_reminder_crud.py`
- Modify: `tests/test_gcal_reminder_routing.py`
- Modify: `tests/test_temporal_resolver.py`

**Interfaces:**

- Consumes unchanged: the routing-foundation's fixed-clock `parse_reminder_command(message_content, *, now=None, temporal_resolver=None)`, complete natural-language vocabulary/media exclusions, `TemporalResolver`, and Task 1's canonical reminder payload; one turn-captured aware `datetime` in `Europe/Oslo`.
- Produces: canonical aware `due_at`, `ReminderManager(..., clock=...)` result APIs requiring the supplied production `reference_time`, extended create/edit recurrence fields, deterministic recurrence gap/fold policy, and fixed-reference recurrence helpers consumed by Tasks 6–7. This task does not change the routing-owned parser signature, vocabulary, or collector.

### Exact manager interfaces

~~~text
ReminderManager.__init__(
    self,
    storage_path=None,
    *,
    clock: ReminderClock | None = None,
    mutation_coordinator: MutationCoordinator | None = None,
) -> None

await ReminderManager.add_reminder_result(
    self,
    guild_id,
    user_id,
    username,
    text,
    due_date=None,
    recurrence=None,
    recurrence_day=None,
    rrule_day=None,
    gcal_event_id=None,
    gcal_link=None,
    channel_id=None,
    *,
    due_at=None,
    time=None,
    timezone="Europe/Oslo",
    reference_time: datetime,
) -> str
~~~

Add async result counterparts for every reminder write used by the handler: `edit_reminder_result(..., *, reference_time) -> dict`, `complete_reminder_result(..., *, reference_time) -> tuple[bool, str]`, and `delete_reminder_result(..., *, reference_time) -> bool`. `ReminderChecker` receives detached occurrence snapshots and revalidates frozen fingerprints while holding the shared scope, but `ReminderManager` exposes no claim/sent-log mutation API. Keep `add_reminder`, `edit_reminder`, `complete_reminder`, and `delete_reminder_by_id` only as the offline synchronous compatibility projections described in the coordinator contract; production code has zero calls to them. Only `complete_reminder_result()` advances recurrence after explicit user completion; delivery state belongs exclusively to `ReminderChecker`.

The implementation follows these exact rules:

1. If `due_at` is non-null, parse it with `datetime.fromisoformat`, reject a naive value, convert it to Oslo, and derive `due_date` and `time` from it.
2. Otherwise, if `due_date` exists, resolve it with `TemporalResolver` using `time or "09:00"` and the supplied `reference_time`. A yearless date resolves to the next occurrence.
3. Otherwise store `due_at`, `due_date`, and `time` as `None`.
4. Store timezone exactly as `Europe/Oslo`.
5. Use `reference_time.isoformat()` for `created_at` and completion/edit timestamps. Production result APIs reject missing/naive reference values and never read `clock.now()` internally; only the outermost offline compatibility wrapper may capture its injected clock once.
6. Never alter records during `_load_reminders()`.

Keep old edit keywords through one compatibility release while exposing canonical keywords:

~~~text
_UNSET = object()

await ReminderManager.edit_reminder_result(
    self,
    guild_id,
    index=None,
    title=_UNSET,
    date=_UNSET,
    time=_UNSET,
    recurrence=_UNSET,
    *,
    reminder_id=None,
    text=_UNSET,
    due_at=_UNSET,
    due_date=_UNSET,
    timezone=_UNSET,
    reference_time: datetime,
) -> dict
~~~

Compatibility mapping is exact: canonical `text` wins over `title` when present; canonical `due_date` wins over `date`. An explicit `due_at=None` clears `due_at`, `due_date`, and `time` to make the reminder checklist-only only when the resulting recurrence is also null; otherwise reject the edit before writing with `invalid_recurrence`. Any explicit date/time/timezone edit recomputes all three temporal display/authority fields. Omitted fields, represented by `_UNSET`, remain unchanged. Creating or editing a recurring reminder without a resolved canonical occurrence is always rejected, and tests cover recurrence on undated create, timing clear with recurrence retained, explicit timing-plus-recurrence, and timing clear plus `recurrence=None`.

Use `dateutil.relativedelta.relativedelta` for recurrence, but advance to the first scheduled occurrence strictly after the injected reference time. Store an internal nominal wall-time anchor (`recurrence_anchor_local`, naive ISO string) and nonnegative `recurrence_sequence` on every new recurring record. The anchor is the accepted original Oslo wall time; temporary DST normalization never changes it. Text-only and other non-temporal edits preserve both fields. An explicit `due_at`, date, time, timezone, or recurrence change resets the anchor to the newly accepted wall time and sequence to zero; removing recurrence clears both fields. Untouched legacy recurring records may retain null anchor/sequence in memory and on disk. On their first completion, derive `anchor_local` from the old canonical `due_at`'s naive Oslo wall time and use sequence zero before calculating; atomically persist that derived anchor, the returned new sequence, and all new due fields together. An explicit schedule/recurrence edit performs the same bootstrap/reset. Loading alone never rewrites them.

Add one public recurrence-only wall-time policy to `TemporalResolver`: `resolve_recurrence_wall_time(local: datetime) -> datetime` accepts a naive Oslo wall time, returns the sole valid occurrence when unambiguous, shifts a spring-gap time forward by the exact round-trip gap (02:30 becomes 03:30), and selects the earlier `fold=0` occurrence in an autumn fold. User-entered gap/fold values remain rejected by `validate_fields()`; this deterministic policy applies only to an already accepted recurring schedule.

~~~python
RECURRENCE_DELTAS = {
    "daily": relativedelta(days=1),
    "weekly": relativedelta(weeks=1),
    "biweekly": relativedelta(weeks=2),
    "monthly": relativedelta(months=1),
    "yearly": relativedelta(years=1),
}
FIXED_DAY_STEPS = {"daily": 1, "weekly": 7, "biweekly": 14}
MAX_CALENDAR_STEPS = 2400


def _after(left: datetime, right: datetime) -> bool:
    return left.astimezone(timezone.utc) > right.astimezone(timezone.utc)


def advance_due_at(
    due_at: datetime,
    recurrence: str,
    *,
    reference_time: datetime,
    anchor_local: datetime | None = None,
    sequence: int = 0,
    resolver: TemporalResolver | None = None,
) -> tuple[datetime, int] | None:
    delta = RECURRENCE_DELTAS.get(recurrence)
    if delta is None:
        return None
    if due_at.tzinfo is None or reference_time.tzinfo is None:
        raise ValueError("naive_recurrence_datetime")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("invalid_recurrence_sequence")
    temporal = resolver or TemporalResolver(OSLO)
    current = due_at.astimezone(OSLO)
    reference = reference_time.astimezone(OSLO)
    anchor = anchor_local or current.replace(tzinfo=None)
    if anchor.tzinfo is not None:
        raise ValueError("recurrence_anchor_must_be_naive")

    if recurrence in FIXED_DAY_STEPS:
        days = FIXED_DAY_STEPS[recurrence]
        elapsed_days = max(0, (reference.date() - anchor.date()).days)
        next_sequence = max(sequence + 1, elapsed_days // days)
        wall = anchor + relativedelta(days=next_sequence * days)
        candidate = temporal.resolve_recurrence_wall_time(wall)
        while not _after(candidate, reference):
            next_sequence += 1
            wall = anchor + relativedelta(days=next_sequence * days)
            candidate = temporal.resolve_recurrence_wall_time(wall)
        return candidate, next_sequence

    for next_sequence in range(sequence + 1, sequence + MAX_CALENDAR_STEPS + 1):
        wall = anchor + next_sequence * delta
        candidate = temporal.resolve_recurrence_wall_time(wall)
        if _after(candidate, reference):
            return candidate, next_sequence
    raise ValueError("recurrence_catchup_limit")
~~~

Fixed-day arithmetic skips whole missed intervals without looping once per day. Monthly/yearly recurrence derives every candidate from the original anchor and sequence, so a 31st or leap-day phase is not lost after a clamped month/year; the search is bounded to 2,400 future occurrences. All ordering uses UTC instants, never direct same-`ZoneInfo` wall-time comparison across a fold. `ReminderManager.complete_reminder_result(..., reference_time=reference_time)` passes its stored anchor/sequence and `now=reference_time`; when legacy fields are null it first derives the old due's naive Oslo wall time and sequence zero. It then updates `recurrence_anchor_local`, `due_at`, `due_date`, `time`, and `recurrence_sequence` in one atomic write. A spring-gap occurrence may deliver at 03:30, while the next valid day returns to the nominal 02:30 anchor.

- [ ] **Step 5.1 (2-4 min): Add a mutable test clock.**

~~~python
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class MutableReminderClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def epoch(self) -> float:
        return self.current.timestamp()

    def advance(self, delta: timedelta) -> None:
        self.current += delta
~~~

- [ ] **Step 5.2 (3-5 min): Add a failing no-eager-rewrite test.**

Write one legacy date-only record to `tmp_path`, capture its bytes, construct `ReminderManager`, and assert the bytes remain identical.

- [ ] **Step 5.3 (3-5 min): Add canonical add/edit tests.**

Pin aware `due_at`, derived date/time, checklist-only input, date-only 09:00, explicit clear, legacy alias mapping, and due-at-authoritative mismatch enrichment only on explicit edit. Add scheduled-versus-checklist recurrence-only edits: the scheduled record preserves its canonical occurrence, while the undated record returns bounded `invalid_recurrence`, performs no write, and maps to non-retryable `invalid_payload`.

Add two fixed-clock parser -> payload validation -> manager -> checker cases for yearless date-only input. At `2026-07-14 08:00+02`, `påminn meg om medisinen 14.07` resolves to `2026-07-14T09:00:00+02:00`; at `12:00+02`, the identical input resolves to `2027-07-14T09:00:00+02:00`. The parser must apply the 09:00 default while the date is still yearless—before converting to `DD.MM.YYYY`—so the manager cannot reinterpret a canonical past-year date. The checker delivers only at the resulting canonical occurrence.

- [ ] **Step 5.4 (2-4 min): Re-run the routing-owned relative-parser contract as an integration prerequisite.**

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
        temporal_resolver=TemporalResolver(),
    )
    assert parsed == {
        "action": "add",
        "text": "ringe legen",
        "due_at": "2026-07-14T14:00:00+02:00",
        "due_date": "14.07.2026",
        "time": "14:00",
        "timezone": "Europe/Oslo",
    }
~~~

Do not alter the parser to satisfy this assertion; it must already pass in the routing-foundation suite. This task adds only the parser -> validated payload -> handler -> manager integration assertion with the same `now` object.

- [ ] **Step 5.5 (3-5 min): Consume the routing-owned vocabulary/title-stripping matrix end to end.**

The routing-foundation tests already own `påminn meg`, `minn meg`, `minn mæ`, `påminnelse`, `påminning`, `hugs å`, `husk å`, `reminder`; reminder-list nouns `påminnelser`, `påminningar`, and `reminders`; relative units; tomorrow/weekday/date/time forms; and the finite watchlist exclusions. Here select representative `minn mæ`, `hugs å`, date-only, relative, checklist, and recurrence routes and prove their already-canonical payload reaches the manager unchanged except typed normalization. Keep `husk å se Inception` owned by watchlist and prove it makes zero reminder-manager calls. This task must not add vocabulary or change `parse_reminder_command`.

- [ ] **Step 5.6 (3-5 min): Add recurrence boundary tests.**

Pin:

- 31 January 09:00 monthly -> 28 February 09:00 in 2026;
- 29 February 2024 yearly -> 28 February 2025;
- 28 March 2026 09:00 +01:00 daily -> 29 March 2026 09:00 +02:00;
- 24 October 2026 09:00 +02:00 daily -> 25 October 2026 09:00 +01:00;
- recurring completion updates `due_at`, `due_date`, and `time` together.
- a text-only edit after a clamped 31-January monthly occurrence preserves the original anchor/sequence and returns to the 31st when valid;
- a legacy monthly 31-January record with null anchor/sequence completes to 28 February and then 31 March across two atomic completions, with the original 31-January anchor persisted on the first completion;
- an explicit schedule/recurrence edit resets anchor/sequence, while removing recurrence clears both;
- a daily reminder completed 49 hours late advances to the first future daily occurrence, not merely one day;
- a biweekly reminder completed five weeks late preserves its two-week phase and advances past `now`;
- nominal 28 March 2026 02:30 +01:00 daily -> gap-day 29 March 03:30 +02:00, then 30 March returns to 02:30 +02:00 from the unchanged anchor;
- nominal 24 October 2026 02:30 +02:00 daily -> the earlier 25 October 02:30 +02:00 (`fold=0`), with the following occurrence at 26 October 02:30 +01:00;
- when `now` is 25 October 02:15 +01:00 (`fold=1`), the already-past 02:30 +02:00 (`fold=0`) candidate is rejected by UTC-instant comparison and catch-up advances to 26 October.

- [ ] **Step 5.7 (2 min): Run the new manager/parser tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py tests/test_reminder_crud.py tests/test_gcal_reminder_routing.py -q
~~~

Expected: failures show missing clock injection, date-only records, approximate month/year recurrence, and missing canonical fields.

- [ ] **Step 5.8 (2-3 min): Reuse Task 1's `reminder_clock.py`, add no second clock type, and extend only its fixed-clock tests.**

- [ ] **Step 5.9 (3-5 min): Inject the compatibility clock into `ReminderManager`; require production result APIs to use their supplied `reference_time` and remove every internal recapture.**

- [ ] **Step 5.10 (3-5 min): Implement canonical due-field resolution without changing `_load_reminders()`.**

- [ ] **Step 5.11 (3-5 min): Extend `add_reminder_result()` with canonical fields, compatibility display fields, and required production `reference_time`.**

- [ ] **Step 5.12 (3-5 min): Extend `edit_reminder_result()` with `_UNSET` semantics, stable-ID targeting, and required production `reference_time`.**

- [ ] **Step 5.13 (3-5 min): Advance recurring completion past the injected clock with bounded `relativedelta` catch-up.**

- [ ] **Step 5.14 (3-5 min): Integrate the routing-owned parser without changing it.**

The required upstream signature is exactly `parse_reminder_command(message_content, *, now=None, temporal_resolver=None)`. It returns canonical create/edit/target payloads, including the exact edit shape `{"action":"edit","number":1,"changes":{"text":"Ring tannlegen"}}`. Production routing already passes `now=context.reference_time` and the injected resolver. Keep that one parser and vocabulary untouched; remove every older handler-private temporal/edit parser from the typed path and do not introduce a second symbol.

- [ ] **Step 5.15 (3-5 min): Pass the single turn reference into the one-release fallback and manager.**

The deterministic route already receives `reference_time` from Task 4. The handler's one-release fallback accepts the same required keyword from `_handle_intent()` and calls `parse_reminder_command(message_content, now=reference_time, temporal_resolver=self.temporal_resolver)`; it never calls `self.reminders.clock.now()`. Routed and fallback paths pass that same object to manager result APIs. Add an identity/advancing-provider test proving both paths produce the same create `due_at`, exact edit payload, and manager timestamp while the provider is read once; make `_parse_edit_command()` and every clock below `handle_message()` raise.

- [ ] **Step 5.16 (3-5 min): Remove `unsupported_temporal_field` from the Task 6 handler path.**

Pass `due_at`, `due_date`, `time`, `timezone`, and `recurrence` from typed create/edit payloads to `ReminderManager`.

- [ ] **Step 5.17 (2 min): Re-run Step 5.7.**

Expected: manager, parser, handler, legacy-read, month-end, and DST tests pass.

- [ ] **Step 5.18 (2 min): Commit clock and canonical records.**

~~~bash
git add cal_system/temporal_resolver.py cal_system/reminder_clock.py \
  cal_system/reminder_manager.py features/reminder_handler.py \
  tests/test_reminder_runtime.py tests/test_reminder_crud.py \
  tests/test_gcal_reminder_routing.py tests/test_temporal_resolver.py
git commit -m "fix: canonicalize reminder timing and recurrence"
~~~

---

### Task 6: Make checker windows and delivery acknowledgement truthful

**Files:**

- Modify: `cal_system/reminder_checker.py`
- Modify: `tests/test_reminder_runtime.py`
- Modify: `tests/test_gcal_reminder_routing.py`

**Interfaces:**

- Consumes: Task 5's single clock, canonical reminder/calendar occurrences, manager, and aware `due_at` values.
- Produces: `select_alert_kind(delta)`, acknowledgement-returning send methods, occurrence sent keys, one-pass `ReminderChecker.check_once()`, injected sleep/clock behavior, and the exact bounded `ReminderChecker.get_health()` schema consumed by Tasks 7–8 and the observability lane.

Required constructor:

~~~text
SleepFunction = Callable[[float], Awaitable[None]]

ReminderChecker.__init__(
    self,
    calendar_manager=None,
    reminder_manager=None,
    event_manager=None,
    get_channel_func=None,
    send_channel_message_func=None,
    send_ping_message_func=None,
    storage_path=None,
    *,
    clock: ReminderClock | None = None,
    mutation_coordinator: MutationCoordinator | None = None,
    sleep_func: SleepFunction = asyncio.sleep,
    interval_seconds: float = 60.0,
) -> None
~~~

The checker reads only detached manager APIs: `CalendarManager.snapshot_delivery_occurrences(*, reference_time)`, `ReminderManager.snapshot_delivery_occurrences(*, reference_time)`, and scope-held `matches_delivery_fingerprint(fingerprint, *, reference_time) -> bool` on the corresponding manager. Snapshot rows contain only canonical fields required for selection/delivery. These methods do not claim, write sent state, mutate recurrence, persist, or read a clock. They reject naive references. `ReminderChecker` creates the fingerprint, owns `IN_FLIGHT`, and is the only caller that turns a successful scope-held match into a claim.

The manager and checker receive the same clock object. `ReminderChecker._capture_reference_time()` asserts awareness and returns `clock.now().astimezone(OSLO)`. `check_once()` calls it exactly once (unless an aware `reference_time` is supplied by a test/compatibility caller) and passes that same object to occurrence snapshots, eligibility, claims, alert selection, digest date, GCal interval, sent-log pruning/records, and health timestamps. Those callees never call `_capture_reference_time()`, `clock.now()`, or `clock.epoch()`. No direct `datetime.now()` or `time.time()` remains in `reminder_checker.py`.

The send chain imports its result model from `core.dispatch_result`; no checker-local enum or receipt type is permitted:

~~~python
from core.dispatch_result import DeliveryState, MessageSendResult


async def _send_to_channel(
    self,
    channel_id,
    message,
    *,
    allowed_mentions,
) -> MessageSendResult:
    if not channel_id:
        self.stats["skipped_missing_channel"] += 1
        return MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "missing_channel",
        )
    try:
        if isinstance(channel_id, bool):
            raise TypeError
        normalized_channel_id = int(channel_id)
        if not 0 < normalized_channel_id < 2**64:
            raise ValueError
    except (TypeError, ValueError):
        return MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "invalid_channel",
        )
    channel = None
    try:
        if self.get_channel is not None:
            channel = self.get_channel(normalized_channel_id)
    except Exception:
        return MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "transport",
        )
    if channel is not None:
        try:
            await channel.send(
                message,
                allowed_mentions=allowed_mentions,
                suppress_embeds=True,
            )
        except discord.errors.Forbidden:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "forbidden",
            )
        except discord.errors.HTTPException:
            return MessageSendResult(DeliveryState.UNKNOWN, "http")
        except Exception:
            return MessageSendResult(DeliveryState.UNKNOWN, "transport")
        return MessageSendResult(DeliveryState.DELIVERED)
    if self.send_channel_message is not None:
        try:
            await self.send_channel_message(
                normalized_channel_id,
                message,
                allowed_mentions=allowed_mentions,
                suppress_embeds=True,
            )
        except discord.errors.Forbidden:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "forbidden",
            )
        except discord.errors.HTTPException:
            return MessageSendResult(DeliveryState.UNKNOWN, "http")
        except Exception:
            return MessageSendResult(DeliveryState.UNKNOWN, "transport")
        return MessageSendResult(DeliveryState.DELIVERED)
    return MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "missing_adapter",
    )


async def _send_mentions_item(
    self,
    channel_id,
    item,
    message,
) -> MessageSendResult:
    user_id = item.get("user_id")
    if user_id and user_id != "gcal_sync":
        message = f"<@{user_id}>\n\n{message}"
        allowed_mentions = discord.AllowedMentions(
            users=[discord.Object(id=int(user_id))],
            roles=False,
            everyone=False,
            replied_user=False,
        )
    elif user_id == "gcal_sync":
        message = f"📅 **Google Calendar Sync**\n\n{message}"
        allowed_mentions = discord.AllowedMentions.none()
    else:
        allowed_mentions = discord.AllowedMentions.none()
    return await self._send_to_channel(
        channel_id,
        message,
        allowed_mentions=allowed_mentions,
    )
~~~

Ordinary/model/handler/presentation output uses `AllowedMentions.none()`. ReminderChecker is the sole mention exception: it may ping exactly the canonical stored creator ID, never roles/everyone/replied-user or IDs parsed from title/text. Every path, including the fallback `send_channel_message_func`, passes `suppress_embeds=True` plus the explicit allowlist. Add malicious title/text tests containing `@everyone`, `<@other>`, `<@&role>`, `<#channel>`, and URLs; only the trusted creator object is allowlisted, no embed is generated, and parallel sends cannot leak an allowlist.

`_send_item_reminder()` and `_send_reminder_remind()` propagate `MessageSendResult`; a compatibility bool wrapper may project only `result.state is DeliveryState.DELIVERED`. `ReminderChecker` is the sole occurrence claimant, in-memory occurrence-state owner, persisted sent-log writer/migrator/pruner, and digest-log writer. `ReminderManager` exposes detached occurrence snapshots and side-effect-free fingerprint revalidation only; it never claims, settles, migrates, prunes, or records delivery.

Delivery uses an in-memory occurrence state machine `absent -> IN_FLIGHT -> SENT|SUPPRESSED_UNKNOWN`, keyed by the canonical occurrence key. A reminder claim does **not** depend on a nonexistent revision/deleted field: while holding `REMINDER_STORE_SCOPE`, re-read the stable reminder ID, require the record still exists, compare the exact frozen fingerprint `(id, due_at, recurrence_anchor_local, recurrence_sequence, completed)`, and recheck current eligibility. A calendar claim similarly compares `(id, due_at, status, delete_pending)` under `CALENDAR_SHARED_SCOPE`. Then, while still holding that family scope, acquire `REMINDER_SENT_LOG_SCOPE`, check persisted/in-memory state, and atomically publish `IN_FLIGHT`. Always acquire family scope before sent-log scope; settlement takes sent-log scope only. Release both before Discord I/O.

The persisted sent-log value schema is exactly `{"state": "sent" | "suppressed_unknown", "at": epoch_float}`. `IN_FLIGHT` is process-memory-only and is never serialized. On load, accept a legacy numeric timestamp value as `{"state":"sent","at":value}`. For one release also recognize only the old calendar keys `<item_id>:30min`, `<item_id>:now`, and `<item_id>:passed`: `30min` maps to `warning_30m`, while both `now` and the retired `passed` variant map to `due`, using the unique currently stored canonical `due_at` for that item. If the item/timestamp is missing, duplicate, or ambiguous, discard the entry and increment the bounded malformed counter. Validate before use: booleans, nonfinite/negative timestamps, unknown states/fields, malformed records, and impossible old keys are discarded. Prune by validated `at`. Migration is in memory at load and is written only with the next ordinary successful sent-log mutation, never eagerly. A failed persistence write retains the process-local terminal state and degrades health so a running process cannot duplicate a possibly delivered alert. The digest log uses the same exact record shape, validation, lazy migration, and terminal semantics, keyed by the Oslo date. Both logs derive `at` from the cycle's `reference_time.timestamp()`; neither reads the clock again.

The claim is the linearization point: a writer ordered before it changes/deletes the occurrence causes revalidation to skip; a writer ordered after it does not block on network I/O and the already-claimed alert may finish. Two overlapping cycles see one claim and send once. Perform one owned send with a hard 15-second timeout. `DELIVERED` settles `SENT`; `NOT_DELIVERED` is definitive and removes `IN_FLIGHT` for retry; `UNKNOWN`, timeout, or cancellation settles `SUPPRESSED_UNKNOWN`, persists when possible, records the finite receipt error code as `delivery_failure`, and never blindly retries. Generic transport/provider exceptions after a send call begins are `UNKNOWN`, never `NOT_DELIVERED`. Cancellation repeatedly shield-awaits the one owned send to a terminal local state before settlement, then re-raises the original cancellation; settlement truth is already durable/in-memory and no second send starts. No family lease is held across Discord I/O.

Only `ReminderManager.complete_reminder_result(..., reference_time=...)` advances recurrence after an explicit user completion. The checker transaction writes no reminder/calendar due/recurrence fields. `check_morning_digest(reference_time=reference_time)` follows the same acknowledgement ordering but uses its separate daily digest key. A persistence failure after a successful Discord send keeps the in-memory occurrence key, records `storage_error`, and returns delivery success; this avoids duplicate sends in the running process while accurately degrading persistence health.

`check_once(*, reference_time: datetime | None = None)` captures/validates one aware `now`, iterates calendar and reminder occurrences once, computes `delta = due_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)`, calls `select_alert_kind(delta)` once per occurrence, and then checks the digest and bounded GCal sync with that same value. Never subtract two Oslo-zone datetimes directly because Python wall-time arithmetic can ignore fold/offset transitions. The old `check_upcoming_30min`, `check_event_now`, and `check_event_passed` methods may remain as compatibility wrappers for one release, but each captures once at its boundary and forwards the value; `start()` calls only `check_once()`.

Add fixed-clock regressions where spring-forward `due=03:00+02` and `now=01:30+01` produces the 30-minute warning, and autumn-fold `due=02:00+01 (fold=1)` with `now=02:59+02 (fold=0)` produces a +1-minute UTC-instant delta despite a negative naive wall-time delta. Both must deliver exactly once and use the canonical occurrence key. Add a separate +5-minute fold case that correctly produces no due delivery because it lies outside the +1-minute boundary.

- [ ] **Step 6.1 (3-5 min): Add pure alert-boundary tests.**

~~~python
@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=35), "warning_30m"),
        (timedelta(minutes=25), None),
        (timedelta(minutes=1), "due"),
        (timedelta(0), "due"),
        (-timedelta(minutes=10), "due"),
        (-timedelta(minutes=10, seconds=1), None),
    ],
)
def test_alert_boundaries(delta, expected):
    assert select_alert_kind(delta) == expected
~~~

- [ ] **Step 6.2 (3-5 min): Add one-alert-per-cycle tests for calendar and reminder records.**

At +30 minutes, one warning sends. At due time in a later cycle, one due alert sends. No cycle emits warning, now, and passed variants together. Add barriers for two overlapping cycles (one claim/send total), edit/delete acquiring the family scope before the claim (zero stale sends), edit/delete after an `IN_FLIGHT` claim completing without waiting for blocked Discord I/O, concurrent calendar/reminder sent-log writes preserving both keys, definitive failure releasing for one retry, timeout/cancellation/unknown suppression, and delivery never changing `due_at`, recurrence anchor, or sequence.

- [ ] **Step 6.3 (3-5 min): Add delivery-failure, uncertainty, migration, and retry tests.**

Prove a pre-dispatch missing channel returns `NOT_DELIVERED` and permits one later retry. Make a started channel send raise and assert `UNKNOWN`, `SUPPRESSED_UNKNOWN`, one bounded error code, and no blind retry. Load one numeric legacy timestamp plus derivable old `<item_id>:30min`, `:now`, and `:passed` keys; assert the exact warning/due mapping, deterministic migration, and no duplicate. Add missing/duplicate item, malformed timestamp, unknown state/field, boolean/nonfinite/negative `at`, and impossible key cases and assert deterministic pruning. Fail terminal-state persistence after delivery and prove the in-memory state still suppresses a second send while health degrades.

- [ ] **Step 6.4 (2-4 min): Add missing-channel and fallback-adapter tests.**

Missing channel returns `MessageSendResult(NOT_DELIVERED, "missing_channel")` and increments `skipped_missing_channel`. Zero, negative, boolean, nonnumeric, and overflow-like channel IDs are normalized/rejected once before either adapter and return `NOT_DELIVERED/invalid_channel` with zero send attempts. A missing resolved channel with a working `send_channel_message_func` returns `DELIVERED`. For both a resolved channel and fallback adapter, Discord `Forbidden` is definite `NOT_DELIVERED/forbidden`, Discord HTTP failure is `UNKNOWN/http`, and a started generic send failure is `UNKNOWN/transport`. Assert the normalized integer ID is reused and no branch calls `int()` on attacker-controlled input a second time.

- [ ] **Step 6.5 (2-4 min): Add digest acknowledgement tests.**

A definite pre-dispatch digest failure leaves the digest occurrence retryable; success writes today's Oslo key with `state="sent"` and increments `digest_sent` once; `UNKNOWN` writes `state="suppressed_unknown"` and does not retry blindly.

- [ ] **Step 6.6 (3-5 min): Add occurrence-key and pruning tests.**

Assert exact keys include source kind, item ID, canonical occurrence timestamp, and alert kind. Advance a recurring occurrence and prove the previous key does not suppress it. Sent-log cutoffs, record `at`, digest date/retention, GCal interval, and health timestamps all derive from the one cycle `reference_time`; make `clock.now()` raise on a second call and forbid `clock.epoch()`.

- [ ] **Step 6.7 (3-5 min): Add bounded health tests.**

Pin starting, ok, degraded delivery, degraded cycle error, stale, recovered ok, and stopped states. Recursively assert no string leaves appear except allowlisted status/error codes and ISO timestamps.

- [ ] **Step 6.8 (2 min): Run checker tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py tests/test_gcal_reminder_routing.py -q
~~~

Expected: failures show overlapping checker methods, marking on failed sends, direct wall-clock calls, and missing health.

- [ ] **Step 6.9 (2-4 min): Add `select_alert_kind()` and canonical occurrence iterators.**

- [ ] **Step 6.10 (3-5 min): Inject the clock/sleeper and replace all direct time calls.**

Search after editing:

~~~bash
rg -n "datetime\.now|time\.time|clock\.epoch|clock\.now|asyncio\.sleep" cal_system/reminder_checker.py
~~~

Expected: no direct `datetime.now`/`time.time`/`clock.epoch`; exactly one `clock.now()` inside `_capture_reference_time`; the only sleep is the injected default declaration or `self.sleep_func` call.

- [ ] **Step 6.11 (3-5 min): Implement the shared tri-state low-level send functions.**

- [ ] **Step 6.12 (3-5 min): Propagate `MessageSendResult` through item/reminder send and settle from delivery certainty.**

- [ ] **Step 6.13 (2-4 min): Make digest delivery use the same acknowledgement rule.**

- [ ] **Step 6.14 (3-5 min): Implement one-pass `check_once()` and remove the separate passed notification from the runtime loop.**

- [ ] **Step 6.15 (3-5 min): Implement checker-owned claims, exact lazy sent/digest-log migration, pruning, settlement, and bounded health.**

- [ ] **Step 6.16 (2-4 min): Make `start()` check immediately, then sleep once per interval.**

Use:

~~~python
async def start(self) -> None:
    self.running = True
    while self.running:
        await self.check_once()
        if self.running:
            await self.sleep_func(self.interval_seconds)
~~~

`check_once()` catches and records bounded operational errors so one bad record does not terminate the loop; `CancelledError` is re-raised.

- [ ] **Step 6.17 (2 min): Re-run Step 6.8.**

Expected: all fixed-clock, boundary, delivery, digest, recurrence-key, and health tests pass.

- [ ] **Step 6.18 (2 min): Commit checker semantics.**

~~~bash
git add cal_system/reminder_checker.py tests/test_reminder_runtime.py tests/test_gcal_reminder_routing.py
git commit -m "fix: acknowledge reminder delivery truthfully"
~~~

---

### Task 7: Establish one owner, idempotent lifecycle, dashboard data, and redacted health

**Files:**

- Modify: `core/message_monitor.py`
- Modify: `core/selfbot_runner.py`
- Modify: `web_console/state_collector.py`
- Modify: `tests/test_reminder_runtime.py`
- Modify: `tests/test_message_monitor_routing.py`
- Modify: `tests/test_console_server.py`

**Interfaces:**

- Consumes: Task 5's clock/manager, Task 6's checker and bounded health, and the existing `SelfbotClient` setup/close hooks.
- Produces: one retained `MessageMonitor`, idempotent `setup()`/`close()`, unique named background tasks, one checker owner, shared reminder dashboard data, and the four-field public reminder projection; the later observability lane may expose the full bounded health only on authenticated status.

### Exact ownership graph

~~~text
SelfbotClient
└── MessageMonitor (created once and retained across on_ready)
    ├── ReminderClock (one instance)
    ├── ReminderManager (one instance, same clock)
    ├── ReminderChecker (one instance, same manager and clock)
    └── reminder-checker asyncio.Task (one live task by name)
~~~

`SelfbotClient` must not retain `reminder_checker` or `reminder_checker_task` fields, construct a second `ReminderManager`, or tear down reminder state separately.

For isolated tests, add backward-compatible keyword-only injection to `MessageMonitor.__init__`:

~~~text
MessageMonitor.__init__(
    self,
    client,
    hermes_connector,
    rate_limiter,
    response_generator,
    bot_name="inebotten",
    *,
    reminder_clock=None,
    reminder_manager=None,
    reminder_checker_factory=ReminderChecker,
) -> None
~~~

Production constructs one `SystemReminderClock`, one `MutationCoordinator`, `ReminderManager(clock=clock, mutation_coordinator=coordinator)`, and one checker using those identical objects. Tests pass temporary-storage instances and a fake checker factory, so they never touch `~/.hermes` or Google Calendar.

Every lifecycle fixture sets `HERMES_HOME` to `tmp_path / "hermes"` before constructing the monitor, resets or monkeypatches cached manager factories, and replaces `GoogleCalendarManager` with a configured-false fake. This isolates all constructor-time storage, not only reminders.

Named task uniqueness:

~~~python
def _track_background_task(self, coro, name):
    existing = self._tasks_by_name.get(name)
    if existing is not None and not existing.done():
        if inspect.iscoroutine(coro):
            coro.close()
        return existing
    task = asyncio.create_task(coro, name=name)
    self._tasks_by_name[name] = task
    self._background_tasks.add(task)
    task.add_done_callback(self._background_task_done(name))
    return task
~~~

The done callback removes the matching task from both collections without removing a newer replacement with the same name.

Client lifecycle:

~~~python
async def _ensure_runtime_started(self):
    if self.monitor is None:
        self.monitor = MessageMonitor(
            client=self,
            hermes_connector=self.hermes,
            rate_limiter=self.rate_limiter,
            response_generator=self.response_gen,
        )
    await self.monitor.setup()
    await self.start_console()
    if self.console_server is not None:
        self.console_server.monitor = self.monitor
    if self.start_time is None:
        self.start_time = datetime.now()
    return self.monitor
~~~

`on_ready()` calls this helper and never replaces the monitor on reconnect. `MessageMonitor.setup()` is guarded by an `asyncio.Lock` plus completion flag; it starts calendar, memory, initial GCal sync, console persistence, checker setup, and checker task at most once. `close()` is idempotent: checker `stop()` first, cancel/await all owned tasks, clear task registries, and mark closed. Repeated close does not touch already-closed resources.

- [ ] **Step 7.1 (3-5 min): Add the one-owner/idempotent setup test.**

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
    assert monitor.reminder_checker.clock is monitor.reminder_clock
    assert monitor.reminder_checker_task is first_task
~~~

- [ ] **Step 7.2 (3-5 min): Add duplicate named-task and repeated-close tests.**

Assert only one each of `initial-gcal-sync`, `console-persistence`, and `reminder-checker` can be live. Repeated close stops the checker once, cancels/awaits every task, and leaves no unawaited coroutine warning.

- [ ] **Step 7.3 (3-5 min): Add reconnect retention tests.**

~~~python
@pytest.mark.asyncio
async def test_reconnect_does_not_replace_monitor(client):
    first = await client._ensure_runtime_started()
    first_started_at = client.start_time
    second = await client._ensure_runtime_started()
    assert second is first
    assert second.reminder_checker_task is first.reminder_checker_task
    assert client.start_time is first_started_at
    assert client.console_server.monitor is first
~~~

- [ ] **Step 7.4 (3-5 min): Add shared-manager dashboard proof.**

Create a reminder through the real handler, call `MessageMonitor._generate_dashboard()`, and assert the same `active_reminders` list reaches `conv_gen.generate_dashboard(reminders=active_reminders)` without restart or reload.

- [ ] **Step 7.5 (3-5 min): Add redacted state-collector tests.**

`collect_bot_status`, `collect_console_health`, and `StateCollector.collect_all` expose only:

~~~python
{
    "status": health["status"],
    "running": health["running"],
    "stale": health["stale"],
    "last_success_at": health["last_success_at"],
}
~~~

Assert `stats`, `last_error_code`, `last_error_at`, `last_check_at`, raw errors, reminder text, and channel data are absent from the public projection.

- [ ] **Step 7.6 (2 min): Run lifecycle/console tests.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py tests/test_message_monitor_routing.py tests/test_console_server.py -q
~~~

Expected: failures show a client-owned duplicate manager/checker, repeated monitor creation, hard-coded empty dashboard reminders, and absent health projection.

- [ ] **Step 7.7 (3-5 min): Add monitor reminder dependency injection and construct one ownership graph.**

- [ ] **Step 7.8 (3-5 min): Make named background-task tracking unique and race-safe.**

- [ ] **Step 7.9 (3-5 min): Make monitor setup/checker startup idempotent.**

- [ ] **Step 7.10 (3-5 min): Make monitor close idempotent and await all owned tasks.**

- [ ] **Step 7.11 (3-5 min): Add `SelfbotClient._ensure_runtime_started()` and retain monitor/start time across reconnect.**

- [ ] **Step 7.12 (2-4 min): Remove client checker fields, `_create_reminder_checker()`, and duplicate checker teardown.**

- [ ] **Step 7.13 (2-4 min): Replace dashboard `reminders=[]` with `self.reminders.get_active_reminders(guild_id)`.**

- [ ] **Step 7.14 (3-5 min): Add the redacted reminder projection to state collection.**

Do not add authenticated detailed counters here; parent Task 13 owns that interface.

- [ ] **Step 7.15 (2 min): Re-run Step 7.6.**

Expected: lifecycle, reconnect, dashboard, and public-redaction tests pass.

- [ ] **Step 7.16 (2 min): Run the complete Task 7 focused gate.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py tests/test_reminder_crud.py tests/test_gcal_reminder_routing.py tests/test_message_monitor_routing.py tests/test_console_server.py -q
~~~

Expected: PASS with one manager/checker/task owner and deterministic fixed-clock delivery.

- [ ] **Step 7.17 (2 min): Commit ownership and public health.**

~~~bash
git add core/message_monitor.py core/selfbot_runner.py web_console/state_collector.py \
  tests/test_reminder_runtime.py tests/test_message_monitor_routing.py \
  tests/test_console_server.py
git commit -m "fix: unify natural reminder runtime ownership"
~~~

---

### Task 8: Run aggregate verification and perform a plan-contract audit

**Files:**

- Verify only by default; do not add unrelated cleanup. A source/test edit is allowed only when this audit exposes a scoped contract correction in the files already owned by Tasks 1–7.

**Interfaces:**

- Consumes: every production/test interface produced by Tasks 1–7 and routing-foundation Tasks 1–5.
- Produces: exact focused, static, non-browser, and contract-audit evidence. The expected path makes no source edit and creates no commit; if the audit exposes a scoped Tasks 1–7 contract defect, Step 8.11 permits only that correction and its focused proof.

- [ ] **Step 8.1 (2 min): Check free disk before the aggregate loop.**

~~~bash
df -h /System/Volumes/Data
~~~

Expected: at least 30 GiB free. Stop and report if below the guard.

- [ ] **Step 8.2 (3-5 min): Run the Task 6 focused gate once more.**

~~~bash
.venv312/bin/python -m pytest tests/test_parse_once_dispatch.py \
  tests/test_message_send_result.py tests/test_mutation_commit_contract.py \
  tests/test_google_calendar_result_compat.py \
  tests/test_auxiliary_dispatch_outcomes.py tests/test_user_memory_controls.py \
  tests/test_calendar_edit.py tests/test_poll_target.py \
  tests/test_watchlist_birthday_edit.py tests/test_quote_crud.py -q
~~~

Expected: PASS.

- [ ] **Step 8.3 (3-5 min): Run the Task 7 focused gate once more.**

~~~bash
.venv312/bin/python -m pytest tests/test_reminder_runtime.py tests/test_reminder_crud.py tests/test_gcal_reminder_routing.py tests/test_message_monitor_routing.py tests/test_console_server.py -q
~~~

Expected: PASS.

- [ ] **Step 8.4 (2-5 min): Run undefined-name and syntax gates.**

~~~bash
.venv312/bin/python -m flake8 . \
  --exclude=.venv312,__pycache__,.git,.pytest_cache \
  --count --select=E9,F63,F7,F82 --show-source --statistics
.venv312/bin/python -m compileall -q \
  -x '(^|/)(\.git|__pycache__|\.pytest_cache|\.venv312)(/|$)' .
~~~

Expected: both commands exit 0 with no undefined-name or syntax failures.

- [ ] **Step 8.5 (3-5 min): Run the non-browser test suite.**

~~~bash
.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py
~~~

Expected: PASS.

- [ ] **Step 8.6 (3-5 min): Run the browser test file if local Chromium is already installed.**

~~~bash
.venv312/bin/python -m pytest -q tests/test_console_frontend.py
~~~

Expected: PASS. If the only failure is a missing local Playwright browser, report that environment limitation explicitly; do not install browsers or access the network unless separately authorized.

- [ ] **Step 8.7 (2-4 min): Run static contract searches.**

~~~bash
if rg -n "datetime\.now|time\.time" cal_system/reminder_checker.py; then exit 1; fi
rg -n "clock\.epoch|clock\.now" cal_system/reminder_checker.py
if rg -n "_create_reminder_checker|self\.reminder_checker|self\.reminder_checker_task" core/selfbot_runner.py; then exit 1; fi
rg -n "self\.reminder_checker|self\.reminder_checker_task" core/message_monitor.py
rg -n "message\.content" features/calendar_handler.py features/reminder_handler.py features/polls_handler.py features/watchlist_handler.py features/quote_handler.py features/birthday_handler.py
if rg -n "sent is not None|response_sent\s*=\s*(sent|bool\()|await self\.send_response\(" core features cal_system; then exit 1; fi
rg -n "class (DeliveryState|MessageSendResult|MessageSendCancelled)" core features cal_system
rg -n "claim|sent_log|digest_log|SUPPRESSED_UNKNOWN|IN_FLIGHT" cal_system/reminder_manager.py cal_system/reminder_checker.py
if rg -n "parse_reminder_edit_command" core features cal_system tests; then exit 1; fi
~~~

Expected:

- checker direct wall-time search has no matches; its clock search has exactly one `clock.now()` in `_capture_reference_time` and no `clock.epoch()`;
- client duplicate checker factory/fields have no matches; monitor-owned checker references are present;
- any `message.content` match is confined to the explicit `payload is None` compatibility branch and has a nearby `legacy_payload_fallback` metric.
- no typed handler infers delivery from `None`/truthiness or calls the compatibility `send_response()`;
- the three delivery contract classes exist only in `core/dispatch_result.py`;
- claim/sent/digest state exists only in `ReminderChecker`; `ReminderManager` contains snapshot/fingerprint reads but no claim or delivery writer.
- no `parse_reminder_edit_command` symbol exists; routing and the compatibility fallback consume the one fixed-clock `parse_reminder_command` API.

- [ ] **Step 8.8 (2-3 min): Check patch hygiene and exact scope.**

~~~bash
git diff --check
git status --short
git log --oneline -8
~~~

Expected: no whitespace errors; only Task 6-7 files and pre-existing user changes are present; the planned commits are visible.

- [ ] **Step 8.9 (3-5 min): Audit payload completeness and type consistency.**

Confirm:

- every Task 6 TypedDict field appears in validator tests;
- every action intent uses the stable family envelope;
- `PollVotePayload` remains the exact `{option, optional poll_id}` object and never reverts to a bare positional integer;
- reminder, quote, and birthday use one family key each;
- handler annotations match the exact inner type;
- typed paths never call raw parser helpers;
- the quote sentinel test proves both text and author;
- every mutating handler returns `DispatchOutcome`;
- `retryable=True` appears only before a proven write;
- every typed handler calls `send_response_result()` and finalizes with `with_delivery()`; `response_sent` is true only for `DELIVERED`;
- a direct handler send cancellation after a proven mutation carries `DispatchCancelled` with that mutation and the settled `MessageSendResult`;
- an attached `UNKNOWN` result is terminal and no monitor/pending fallback can send again;
- `domain_scope_id()` is defined once in `core/message_context.py` and all guild/DM persistence/snapshot call sites consume it;
- no handler or monitor invents a second reminder manager.

- [ ] **Step 8.10 (3-5 min): Audit reminder invariants.**

Confirm:

- one clock object reaches the composition graph, while each turn/cycle captures it once and passes one identical aware `reference_time` through parser, manager, checker, recurrence, sent-log, digest, GCal interval, and health;
- one manager instance is shared by handler, dashboard, and checker;
- 35:00, 25:00, 1:00, 0:00, -10:00, and -10:01 boundaries are pinned;
- one shared `MessageSendResult` propagates end-to-end and only `NOT_DELIVERED` is retried;
- `DELIVERED` writes `sent`, `UNKNOWN` writes `suppressed_unknown`, and only definite `NOT_DELIVERED` clears `IN_FLIGHT` for retry;
- `ReminderChecker` alone owns claims and sent/digest log mutation; `ReminderManager` never advances recurrence on delivery;
- legacy numeric and old calendar-key sent records migrate lazily to the exact terminal record schema, malformed records prune deterministically, and persistence failure retains process-local suppression;
- recurrence keys include occurrence timestamp;
- recurring create/edit state always has a canonical occurrence, and clearing timing cannot leave recurrence active;
- spring/fall DST and month-end tests pass;
- public health exposes exactly four allowlisted fields.

- [ ] **Step 8.11 (2 min): Commit only if verification required a scoped test or contract correction.**

~~~bash
git add core/intent_payloads.py core/dispatch_result.py core/intent_router.py \
  core/message_context.py core/mutation_coordinator.py core/send_receipt.py \
  core/message_monitor.py core/selfbot_runner.py cal_system/calendar_manager.py \
  cal_system/google_calendar_manager.py cal_system/reminder_clock.py \
  cal_system/reminder_manager.py cal_system/reminder_checker.py \
  cal_system/temporal_resolver.py features/base_handler.py \
  features/calendar_handler.py features/reminder_handler.py \
  features/polls_handler.py features/poll_manager.py \
  features/watchlist_handler.py features/watchlist_manager.py \
  features/fun_handler.py features/quote_handler.py features/quote_manager.py \
  features/birthday_handler.py features/birthday_manager.py \
  features/daily_digest_manager.py memory/user_memory.py \
  web_console/state_collector.py tests/test_parse_once_dispatch.py \
  tests/test_message_send_result.py tests/test_mutation_commit_contract.py \
  tests/test_google_calendar_result_compat.py \
  tests/test_auxiliary_dispatch_outcomes.py tests/test_user_memory_controls.py \
  tests/test_reminder_runtime.py tests/test_message_monitor_routing.py \
  tests/test_calendar_edit.py tests/test_reminder_crud.py \
  tests/test_gcal_reminder_routing.py tests/test_temporal_resolver.py \
  tests/test_poll_target.py tests/test_watchlist_birthday_edit.py \
  tests/test_quote_crud.py tests/test_intent_router.py tests/test_console_server.py
git commit -m "test: lock typed dispatch reminder invariants"
~~~

Expected: skip this commit when there are no post-verification corrections.

## Residual Uncertainty and Explicit Non-Claims

- The reviewed base `437bc5edcc476705be68b24779b3e9c95730e1cb` did not contain parent Tasks 2-5. This plan is executable only after the prerequisite gate passes; exact shifted line numbers cannot be confirmed until then.
- The parent `CalendarTargetPayload` has no explicit bulk-title flag. This plan fails closed on ambiguous title delete/complete and reserves `all=True` for calendar clear, avoiding an implicit mass mutation. If product requirements demand bulk title actions, expand the parent payload contract in a separately reviewed change.
- `BirthdayEditPayload` carries user ID but not display name. Awaited `BirthdayManager.edit_birthday_by_user_id_result()` returns structured write truth for typed callers, while synchronous user-ID/name wrappers are offline-only and retain their legacy return contracts.
- This lane defines birthday validation and typed handler behavior but does not claim production birthday route emission; the later feature-parity lane owns safe mentioned-user identity resolution and route tests.
- `ReminderEditPayload` accepts exactly one positive list number or stable `reminder_id`. Natural immediate syntax may still yield a number, while pending revalidation rewrites it to the stable ID before delayed dispatch.
- User-entered nonexistent/ambiguous local wall times remain rejected by the routing-foundation contract. Recurrence alone has the explicit spring-forward shift and earlier-fold policy pinned above, so an accepted schedule cannot later produce a nonexistent or ambiguous canonical occurrence.
- No live Discord or Google Calendar send/sync is claimed. Delivery truth is proven with injected adapters; live permissions, channel deletion, token state, and Google API behavior remain deployment smoke checks.
- Detailed authenticated reminder counters are intentionally not exposed here. Parent Task 13 owns that schema, persistence, and authentication boundary.
- Browser-suite success is conditional on an already-installed local Playwright Chromium. All non-browser behavior remains fully testable offline.

## Completion Definition

Tasks 6-7 are complete only when every focused and available aggregate gate passes, the worktree contains no out-of-scope edits, the mandatory real quote sentinel test is green, one monitor-owned reminder runtime is proven across reconnect, and the final report distinguishes offline proof from unrun live integrations.

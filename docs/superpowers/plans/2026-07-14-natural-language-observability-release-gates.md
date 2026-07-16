# Inebotten Natural-Language Observability and Release Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist privacy-safe NLU quality and action-safety counters, expose bounded operator state without leaking language content, gate the production-parser corpus in CI, and make documentation describe the implemented architecture rather than command-style aspirations.

**Architecture:** `NLUMetrics` accepts only allowlisted enum dimensions and emits integer counters. `MessageMonitor` owns cumulative runtime counters and persists deltas through one locked, atomic ConsoleStore transaction. Authenticated `/api/status` includes detailed NLU/reminder aggregates; unauthenticated `/health` contains only a redacted operational projection. CI evaluates the same production-parser corpus used locally between non-browser and browser test steps.

**Tech Stack:** Python 3.12.13, `collections.Counter`, `asyncio.Lock`, `threading.RLock`, atomic JSON storage, pytest/pytest-asyncio, GitHub Actions, Markdown documentation.

## Global Constraints

- Complete the routing-foundation, typed-dispatch/reminder-runtime, model-actions/pending/context, and feature-parity plans before starting this lane.
- Run every Python command with `.venv312/bin/python` on Python 3.12.13.
- Never persist or return raw utterances, names, titles, URLs, action slots, model text, exception strings, pending summaries, or user identifiers in NLU/reminder health data.
- Keep `core/nlu_metrics.py` dimensions finite and allowlisted; unknown values map to `other` and never become dynamic keys.
- Treat `ConsoleStore.save_stats()` inputs as deltas, advance monitor baselines only after a successful write, and preserve unsupported future-schema files byte-for-byte.
- Preserve the typed reminder contract exactly: statuses are `starting|ok|degraded|stopped`, error codes are `cycle_error|gcal_sync_error|delivery_failure|storage_error|null`, and public health exposes only status, running, stale, and last-success time.
- Keep unauthenticated `/health` bounded and redacted; detailed bounded counters are available only through authenticated `/api/status`.
- Do not access live Discord, Google Calendar, LM Studio, OpenRouter, or production `~/.hermes` data in tests.
- Stop aggregate build/test loops when `df -h /System/Volumes/Data` reports less than 30 GiB free.

---

### Task 1: Freeze a bounded aggregate metrics schema

**Files:**

- Modify: `core/nlu_metrics.py`
- Create: `tests/test_nlu_metrics_privacy.py`
- Test: `tests/test_nlu_metrics.py`

**Interfaces:**

- Consumes: `BotIntent`, `IntentSource`, and `RejectionCode` from the completed routing-foundation lane.
- Produces: `NLUMetrics.record_decision(*, intent, source, outcome)`, `record_rejection(code)`, `record_pending(event)`, `record_action_result(result)`, `record_parser_error(parser, code)`, `record_legacy_payload_fallback(family)`, `record_reminder_delivery(event, *, error_code=None)`, `merge_snapshot(delta)`, and `snapshot() -> dict[str, dict[str, int]]`; `ALLOWED_METRIC_KEYS` is the sole persisted-key allowlist consumed by Tasks 2–4.

- [ ] **Step 1: Write the constructor and allowlist tests (2–5 minutes)**

~~~python
def test_unknown_dimensions_bucket_to_other():
    metrics = NLUMetrics()
    secret = "Ring Kari https://secret.example/token"
    metrics.record_decision(intent=secret, source=secret, outcome=secret)
    assert metrics.snapshot()["decisions"] == {
        "intent=other|source=other|outcome=other": 1
    }


def test_recorders_have_no_content_parameter():
    metrics = NLUMetrics()
    with pytest.raises(TypeError):
        metrics.record_decision(
            intent="help",
            source="deterministic",
            outcome="routed",
            raw_text="private",
        )


def test_snapshot_has_only_bounded_keys_and_nonnegative_integers():
    metrics = NLUMetrics()
    metrics.record_parser_error("calendar", "invalid_temporal")
    snapshot = metrics.snapshot()
    assert set(snapshot) <= METRIC_SECTIONS
    for section, values in snapshot.items():
        assert set(values) <= ALLOWED_METRIC_KEYS[section]
        assert all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in values.values()
        )
~~~

- [ ] **Step 2: Run the privacy tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_nlu_metrics.py tests/test_nlu_metrics_privacy.py -q
~~~

Expected: FAIL until the complete bounded schema exists.

- [ ] **Step 3: Define exact dimensions (2–5 minutes)**

In `core/nlu_metrics.py`, define immutable allowlists:

~~~python
INTENT_VALUES = frozenset(intent.value for intent in BotIntent)
SOURCE_VALUES = frozenset({"deterministic", "semantic"})
DECISION_OUTCOMES = frozenset({
    "routed", "clarified", "blocked", "low_confidence", "staged",
    "executed", "failed", "canceled", "other",
})
REJECTION_VALUES = frozenset(code.value for code in RejectionCode)
PENDING_EVENTS = frozenset({
    "staged", "confirmed", "canceled", "selected", "corrected",
    "expired", "claim_failed", "dispatch_failed", "presentation_failed",
    "other",
})
ACTION_RESULTS = frozenset({
    "accepted", "invalid_json", "unknown_action", "unknown_key",
    "invalid_slot", "missing_slot", "multiple_proposals", "legacy",
    "other",
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
    "calendar", "reminder", "poll", "watchlist", "quote", "birthday",
    "other",
})
METRIC_SECTIONS = frozenset({
    "decisions", "rejections", "pending", "actions", "parser_errors",
    "legacy_payload_fallbacks", "reminder_delivery",
})
~~~

No arbitrary parser, intent, exception class, or model value may become a persisted key.

- [ ] **Step 4: Implement the counter API (2–5 minutes)**

Use a private `dict[str, Counter[str]]`. `_bounded(value, allowed)` returns the string/enum value only when present, otherwise `other`. Implement the complete class with this shape:

~~~python
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
        self,
        *,
        intent: BotIntent | str,
        source: IntentSource | str,
        outcome: str,
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
        self._increment(
            "legacy_payload_fallbacks",
            _bounded(family, LEGACY_FAMILIES),
        )

    def record_reminder_delivery(
        self,
        event: str,
        *,
        error_code: str | None = None,
    ) -> None:
        key = (
            f"event={_bounded(event, REMINDER_EVENTS)}|"
            f"error={_bounded(error_code or 'none', REMINDER_ERROR_CODES)}"
        )
        self._increment("reminder_delivery", key)

    def merge_snapshot(
        self,
        delta: Mapping[str, Mapping[str, int]],
    ) -> None:
        for section, values in delta.items():
            if section not in METRIC_SECTIONS or not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 < value <= 2**63 - 1
                ):
                    self._increment(section, key, value)

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            section: dict(sorted(self._counts[section].items()))
            for section in sorted(METRIC_SECTIONS)
            if self._counts[section]
        }
~~~

Composite keys use only bounded values, for example `intent=help|source=deterministic|outcome=routed`. `merge_snapshot` ignores unknown sections/keys, bools, negatives, floats, and values above `2**63 - 1`; it adds accepted deltas. `snapshot` sorts sections and keys and returns copies.

- [ ] **Step 5: Inject one secret into every dimension (2–5 minutes)**

Call every recorder with the same sensitive string, including parser name, parser error, rejection, pending, action result, reminder event/error, family, intent, source, and outcome. Assert the string and its substrings are absent from `json.dumps(snapshot)` and only bounded `other` keys increment.

- [ ] **Step 6: Run and commit (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_nlu_metrics.py tests/test_nlu_metrics_privacy.py -q
git add core/nlu_metrics.py tests/test_nlu_metrics.py \
  tests/test_nlu_metrics_privacy.py
git commit -m "feat: bound natural-language metrics dimensions"
~~~

---

### Task 2: Migrate ConsoleStore to atomic schema v3

**Files:**

- Modify: `web_console/console_store.py:1-145`
- Modify: `web_console/server.py` (constructor injection seam only)
- Modify: `tests/test_console_server.py`
- Modify: `tests/test_nlu_metrics_privacy.py`

**Interfaces:**

- Consumes: Task 1's `ALLOWED_METRIC_KEYS`; the typed reminder lane's exact `ReminderChecker.get_health() -> dict[str, object]` schema; `write_json_atomic(path, value, *, indent)` from `utils/json_storage.py`.
- Produces: `ConsoleStore.__init__(*, data_dir: Path | None = None)`, `load_stats()`, `load_nlu_stats()`, `load_reminder_runtime()`, `save_stats(intent_stats, rate_limit_stats, *, nlu_stats=None, reminder_runtime=None) -> bool`, `persist_nlu_metrics(delta) -> bool`, `sanitize_reminder_runtime(raw) -> dict[str, object]`, and the prerequisite `ConsoleServer(..., store: ConsoleStore | None = None)` injection seam; unsupported future schemas raise internally and cannot be overwritten.

- [ ] **Step 1: Add failing constructor and migration tests (2–5 minutes)**

~~~python
def test_console_store_accepts_keyword_only_data_dir(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    assert store._data_dir == tmp_path


def test_v2_stats_migrate_without_losing_totals(tmp_path):
    (tmp_path / "stats.json").write_text(
        json.dumps({
            "version": 2,
            "intents": {"help": {"count": 4, "low_confidence": 0, "errors": 0}},
            "rate_limits": {"user_1": 3},
            "last_saved": "2026-07-14T10:00:00",
        }),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)
    stats = store.load_stats()
    assert stats["version"] == 3
    assert stats["intents"]["help"]["count"] == 4
    assert stats["rate_limits"]["user_1"] == 3
    assert stats["nlu"] == {}
    assert stats["reminder_runtime"] == {}
~~~

- [ ] **Step 2: Run the storage tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_console_server.py tests/test_nlu_metrics_privacy.py -q
~~~

Expected: FAIL because the constructor has no injection seam and schema version is 2.

- [ ] **Step 3: Define schema v3 and compatible construction (2–5 minutes)**

Set `STATS_SCHEMA_VERSION = 3`. Implement `ConsoleStore.__init__(*, data_dir: Path | None = None)` and use `data_dir` directly when supplied; otherwise retain `hermes_discord_data_dir() / "console"`. `_empty_stats()` returns:

~~~python
{
    "version": 3,
    "intents": {},
    "rate_limits": {},
    "nlu": {},
    "reminder_runtime": {},
    "last_saved": None,
}
~~~

Add `load_stats() -> dict[str, Any]`, which acquires `self._lock`, calls the unlocked loader, and returns a detached dictionary. Keep `load_intent_stats()` and `load_rate_limit_stats()` as wrappers over `load_stats()`; add `load_nlu_stats()` and `load_reminder_runtime()` wrappers for collectors.

In the same prerequisite step, add `store: ConsoleStore | None = None` as the final keyword of `ConsoleServer.__init__()` and assign `self.store = store if store is not None else get_console_store()`. Do not change endpoint shapes yet. Add a constructor identity test. Task 3 may now inject the one client-owned store before Task 4 adds authenticated collectors; no later task redefines this seam.

- [ ] **Step 4: Add one fail-closed unlocked loader under the RLock (2–5 minutes)**

Add `UnsupportedStatsSchemaError(ValueError)`. `_load_stats_raw_unlocked()` reads/parses while the caller holds `self._lock`; it accepts v3 directly and upgrades v2 in memory by adding empty NLU/reminder sections and changing version to 3. A non-dictionary or version greater than 3 records only the bounded store-health code `unsupported_stats_schema` and raises `UnsupportedStatsSchemaError` without writing, renaming, deleting, or normalizing the file. `load_stats()` catches that exception and returns a detached `_empty_stats()` for display, but `save_stats()` calls `_load_stats_raw_unlocked()` directly and returns `False` when it raises. Add a regression that writes version 4 bytes, calls both methods, and asserts the bytes and SHA-256 digest are unchanged.

Replace raw public error strings in `ConsoleStore.health()` with this exact bounded contract. Internally keep unresolved errors per operation rather than one scalar, because a later log success must not erase a still-failing stats path:

~~~python
STORE_ERROR_CODES = frozenset({
    "load_stats", "save_stats", "append_logs", "read_error",
    "unsupported_stats_schema", "other",
})


def _selected_health_error_unlocked(self) -> tuple[str | None, str | None]:
    if not self._health_errors:
        return None, None
    code, at = max(
        self._health_errors.items(),
        key=lambda item: (item[1], item[0]),
    )
    return code, at


def health(self) -> dict[str, object]:
    with self._lock:
        error_code, error_at = self._selected_health_error_unlocked()
        return {
            "status": "degraded" if self._health_errors else "ok",
            "stats_schema_version": STATS_SCHEMA_VERSION,
            "last_stats_saved_at": self._last_stats_saved_at,
            "last_log_write_at": self._last_log_write_at,
            "error_code": error_code,
            "last_error_at": error_at,
        }
~~~

Initialize `_health_errors: dict[str, str] = {}`. Implement private `_record_error_unlocked(operation, exc)` and `_record_success_unlocked(operation)` helpers for callers already holding the `RLock`, plus public locked wrappers used only by code that does not already own it. The error helper may log through the private logger, but stores only the allowlisted operation code (or `other`) with its current ISO timestamp; `_stats_read_error()` returns `read_error` or `unsupported_stats_schema`, never exception text. `_record_success_unlocked("stats_read")` clears only `{load_stats, read_error, unsupported_stats_schema}` and does **not** update `last_stats_saved_at`; `_record_success_unlocked("stats_write")` clears `{load_stats, save_stats, read_error, unsupported_stats_schema}` and updates `last_stats_saved_at` only after the atomic replace succeeds; `_record_success_unlocked("logs_write")` clears only `append_logs` and updates `last_log_write_at`. Catching a future-schema error is not success. Every same-operation write and its health transition happen inside the same `RLock` critical section, so an older success cannot erase a newer failure and an older failure cannot re-degrade a newer success. Public `health()` takes that lock and exposes the most recent still-unresolved bounded error while every other unresolved operation remains internal and continues to keep status degraded. Add recovery tests, a stats-fail -> logs-fail -> logs-recover masking regression, a successful-load regression proving it clears only read errors without advancing the save timestamp, and deterministic old-success/new-failure plus old-failure/new-success barrier tests for both stats and log writes.

- [ ] **Step 5: Add failing atomic merge and reminder-shape tests (2–5 minutes)**

Start two threads at a barrier: one calls legacy intent/rate `save_stats`, one calls `persist_nlu_metrics`. Assert all increments survive. Add tests for unknown/negative/bool NLU leaves being ignored and valid repeated deltas accumulating exactly once per call. Pass the typed checker health object below through `save_stats()` and assert its status, timestamps, nullable error code, counters, and nested `stats` survive exactly; then inject unknown keys, negative/bool counters, bad timestamps, and raw exception text and assert they are dropped or bounded.

- [ ] **Step 6: Validate the exact typed reminder-health schema (2–5 minutes)**

Use the completed typed reminder lane's `ReminderChecker.get_health()` shape without inventing aggregate aliases:

~~~python
REMINDER_STATUS_VALUES = frozenset({"starting", "ok", "degraded", "stopped"})
REMINDER_RUNTIME_ERROR_VALUES = frozenset({
    "cycle_error", "gcal_sync_error", "delivery_failure", "storage_error",
})
REMINDER_STAT_KEYS = frozenset({
    "cycles", "warning_30m_sent", "due_sent", "digest_sent",
    "delivery_failures", "skipped_missing_channel",
    "malformed_legacy_due_at", "legacy_due_mismatch",
    "missed_outside_catchup", "gcal_sync_errors", "cycle_errors",
})


def _iso_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def sanitize_reminder_runtime(raw: Mapping[str, object]) -> dict[str, object]:
    status = raw.get("status")
    raw_stats = raw.get("stats")
    stats = raw_stats if isinstance(raw_stats, Mapping) else {}
    error = raw.get("last_error_code")
    return {
        "status": status if status in REMINDER_STATUS_VALUES else "degraded",
        "running": raw.get("running") if isinstance(raw.get("running"), bool) else False,
        "stale": raw.get("stale") if isinstance(raw.get("stale"), bool) else False,
        "last_check_at": _iso_or_none(raw.get("last_check_at")),
        "last_success_at": _iso_or_none(raw.get("last_success_at")),
        "last_error_at": _iso_or_none(raw.get("last_error_at")),
        "last_error_code": (
            error
            if isinstance(error, str) and error in REMINDER_RUNTIME_ERROR_VALUES
            else None
        ),
        "consecutive_errors": _nonnegative_int(raw.get("consecutive_errors")),
        "stats": {
            key: _nonnegative_int(stats.get(key))
            for key in sorted(REMINDER_STAT_KEYS)
        },
    }
~~~

Unknown status becomes `degraded`; unknown error codes become `None`; unknown fields and raw errors are discarded. The public projection remains a separate four-field view in Task 4.

- [ ] **Step 7: Replace save_stats with one locked transaction (2–5 minutes)**

Use this signature and transaction body:

~~~python
ReminderRuntime = Mapping[str, object]


def save_stats(
    self,
    intent_stats: Mapping[str, Mapping[str, int]],
    rate_limit_stats: Mapping[str, int],
    *,
    nlu_stats: Mapping[str, Mapping[str, int]] | None = None,
    reminder_runtime: ReminderRuntime | None = None,
) -> bool:
    with self._lock:
        try:
            existing = self._load_stats_raw_unlocked()
            for intent, delta in intent_stats.items():
                current = existing["intents"].setdefault(
                    str(intent),
                    {"count": 0, "low_confidence": 0, "errors": 0},
                )
                for key in ("count", "low_confidence", "errors"):
                    value = delta.get(key, 0)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        current[key] += value
            for user, value in rate_limit_stats.items():
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    existing["rate_limits"][str(user)] = (
                        existing["rate_limits"].get(str(user), 0) + value
                    )
            for section, values in (nlu_stats or {}).items():
                if section not in ALLOWED_METRIC_KEYS or not isinstance(values, Mapping):
                    continue
                target = existing["nlu"].setdefault(section, {})
                for key, value in values.items():
                    if (
                        key in ALLOWED_METRIC_KEYS[section]
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        target[key] = target.get(key, 0) + value
            if reminder_runtime is not None:
                existing["reminder_runtime"] = sanitize_reminder_runtime(
                    reminder_runtime
                )
            existing["version"] = STATS_SCHEMA_VERSION
            existing["last_saved"] = datetime.now().isoformat()
            write_json_atomic(self._stats_file, existing, indent=None)
            self._record_success_unlocked("stats_write")
            return True
        except UnsupportedStatsSchemaError:
            # The loader already recorded unsupported_stats_schema while
            # this same lock was held. Never relabel or touch the file.
            return False
        except Exception as exc:
            self._record_error_unlocked("save_stats", exc)
            return False
~~~

Hold `self._lock` across `_load_stats_raw_unlocked()`, all validation/merges, `last_saved`, `write_json_atomic`, and the matching success/error health transition. `append_logs()` follows the same rule: its file operation and `_record_success_unlocked("logs_write")` or `_record_error_unlocked("append_logs", exc)` remain in one lock acquisition. Intent/rate/NLU inputs are deltas. Reminder runtime is a bounded latest-state projection of the exact typed checker contract. `persist_nlu_metrics(delta)` calls `save_stats({}, {}, nlu_stats=delta)`. `UnsupportedStatsSchemaError` reaches its dedicated branch after the loader records `unsupported_stats_schema`; it is never relabeled `save_stats`, returns `False`, and leaves the future file byte- and SHA-identical. Assert `health()["error_code"] == "unsupported_stats_schema"` after both read and rejected write. Barrier tests pause the older operation before its health transition, start the newer operation, and prove the single lock preserves call order for success->failure and failure->success rather than allowing a stale transition to win.

- [ ] **Step 8: Run restart, future-schema, and concurrency tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_console_server.py tests/test_nlu_metrics_privacy.py -q
~~~

Expected: PASS; v2 totals survive, v4 bytes remain unchanged, typed reminder health round-trips, and concurrent deltas are not lost.

- [ ] **Step 9: Commit (2–5 minutes)**

~~~bash
git add web_console/console_store.py web_console/server.py tests/test_console_server.py \
  tests/test_nlu_metrics_privacy.py
git commit -m "feat: persist bounded NLU stats atomically"
~~~

---

### Task 3: Persist runtime deltas exactly once

**Files:**

- Modify: `core/message_monitor.py:244-275,333-384,489-521`
- Modify: `cal_system/reminder_checker.py`
- Modify: `tests/test_message_monitor_routing.py`
- Modify: `tests/test_reminder_runtime.py`
- Modify: `tests/test_nlu_metrics_privacy.py`
- Create: `tests/test_monitor_lifecycle.py`

**Interfaces:**

- Consumes: Task 1's `NLUMetrics` API and the model-actions lane's sole monitor-owned `self.nlu_metrics` instance already shared by `IntentRouter`, `PendingActionStore`, and `AIActionHandler`; Task 2's `ConsoleStore.save_stats(intent_stats, rate_limit_stats, *, nlu_stats=None, reminder_runtime=None) -> bool` and `load_nlu_stats()`; the typed runtime lane's `_tasks_by_name`, `_background_tasks`, `ReminderChecker.stop()`, send acknowledgements, alert kinds, bounded health, and idempotent `MessageMonitor.close()` lifecycle.
- Produces: one client-owned `ConsoleStore` injected into both early `ConsoleServer` and later `MessageMonitor`, one-time runtime metric hydration, `MessageMonitor._persist_console_stats_once() -> Awaitable[None]`, cancellation-safe retry baselines, and close ordering that stops every metric producer before one final delta flush.

- [ ] **Step 1: Add parameterized no-change, retry, and close tests (2–5 minutes)**

With an injected fake store, assert:

1. two unchanged flushes write at most once;
2. a +1 decision after the first flush writes delta 1;
3. a failed write does not advance the baseline and the next flush retries the same delta;
4. two concurrent flush tasks produce one persisted delta;
5. `close()` stops the reminder checker, cancels/awaits every owned producer task including `console-persistence`, then performs one final flush;
6. calling `close()` twice neither stops resources twice nor writes another delta;
7. `monitor.nlu_metrics is monitor.intent_router.metrics is monitor.pending_actions.metrics is monitor.ai_action_handler.metrics is monitor.ai_action_handler.bridge.metrics`, and the injected reminder checker holds that same object.
8. persisted NLU totals hydrate once before producers start; authenticated live status contains persisted plus new totals, while the next flush writes only the new delta;
9. a blocked `to_thread` write released after periodic-task cancellation is committed once, advances the baseline once, and is not duplicated by the final close flush.

- [ ] **Step 2: Add runtime fields in MessageMonitor (2–5 minutes)**

~~~python
self._last_persisted_nlu_stats: dict[str, dict[str, int]] = {}
self._last_persisted_reminder_runtime: dict[str, object] = {}
self._console_persist_lock = asyncio.Lock()
self._console_write_task: asyncio.Task[bool] | None = None
self._nlu_metrics_hydrated = False
self._final_stats_flushed = False
~~~

Do not construct or replace `self.nlu_metrics` here; the model-actions lane already creates it before the router, pending store, and action handler. Pass that same instance into `ReminderChecker` in Step 6. The constructor accepts no alternate raw-content metrics sink, and the lifecycle test asserts every producer shares object identity with `monitor.nlu_metrics`.

Create `self.console_store = get_console_store()` once in `SelfbotClient.__init__()`. Pass that exact object as `store=self.console_store` to the console server created before Discord readiness and as `console_store=self.console_store` to the later `MessageMonitor`. Before `MessageMonitor.setup()` starts any router/checker/persistence producer, run once:

~~~python
if not self._nlu_metrics_hydrated:
    persisted_nlu = self.console_store.load_nlu_stats()
    self.nlu_metrics.merge_snapshot(persisted_nlu)
    self._last_persisted_nlu_stats = self.nlu_metrics.snapshot()
    self._nlu_metrics_hydrated = True
~~~

Repeated setup/reconnect must not merge again. This makes the live collector cumulative across restart while the baseline prevents old totals from being written again.

- [ ] **Step 3: Implement the locked delta flush (2–5 minutes)**

Add these bounded helpers next to the existing intent-counter helpers, then use them from `_persist_console_stats_once()`:

~~~python
_COUNTER_LIMIT = 2**63 - 1
_RATE_SOURCE_KEYS = ("user_stats", "per_user", "users")


def _counter(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return min(max(value, 0), _COUNTER_LIMIT)


def _counter_increment(current: object, previous: object) -> int:
    now = _counter(current)
    before = _counter(previous)
    # A lower value means the producer restarted/reset. Persist the new epoch's
    # current count instead of emitting a negative delta or losing it.
    return now - before if now >= before else now


def _nested_counter_delta(
    current: Mapping[str, Mapping[str, object]],
    previous: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    # NLUMetrics has a finite public registry. Iterate that registry rather
    # than truncating arbitrary dictionary order and then advancing a broader
    # baseline, which could silently lose an omitted counter.
    for section in sorted(ALLOWED_METRIC_KEYS):
        values = current.get(section, {})
        if not isinstance(values, Mapping):
            continue
        old_values = previous.get(section, {})
        if not isinstance(old_values, Mapping):
            old_values = {}
        delta = {
            key: _counter_increment(values.get(key, 0), old_values.get(key, 0))
            for key in sorted(ALLOWED_METRIC_KEYS[section])
        }
        nonzero = {key: value for key, value in delta.items() if value}
        if nonzero:
            result[str(section)] = nonzero
    return result


def _counter_stats_delta(current, previous):
    result = {}
    for name, values in current.items():
        if not isinstance(values, Mapping):
            continue
        old = previous.get(name, {}) if isinstance(previous, Mapping) else {}
        old = old if isinstance(old, Mapping) else {}
        entry = {
            key: _counter_increment(values.get(key, 0), old.get(key, 0))
            for key in _COUNTER_STAT_KEYS
        }
        if any(entry.values()):
            result[str(name)] = entry
    return result


def _flat_counter_delta(current, previous):
    return {
        str(name): delta
        for name, value in current.items()
        if (delta := _counter_increment(
            value,
            previous.get(name, 0) if isinstance(previous, Mapping) else 0,
        ))
    }


def _bounded_rate_snapshot(self) -> dict[str, int]:
    getter = getattr(self.rate_limiter, "get_stats", None)
    overall = getter() if callable(getter) else {}
    if not isinstance(overall, Mapping):
        return {}
    for source_key in _RATE_SOURCE_KEYS:
        source = overall.get(source_key)
        if not isinstance(source, Mapping):
            continue
        bounded: dict[str, int] = {}
        valid_users = sorted(
            (
                (str(raw_user), raw_stats)
                for raw_user, raw_stats in source.items()
                if len(str(raw_user)) <= 32 and str(raw_user).isdecimal()
            ),
            key=lambda item: (int(item[0]), item[0]),
        )[:1000]
        for user, raw_stats in valid_users:
            value = (
                raw_stats.get("requests", 0)
                if isinstance(raw_stats, Mapping)
                else raw_stats
            )
            bounded[user] = _counter(value)
        return bounded
    return {}


def _bounded_reminder_runtime_snapshot(self) -> dict[str, object]:
    checker = getattr(self, "reminder_checker", None)
    getter = getattr(checker, "get_health", None)
    try:
        raw = getter() if callable(getter) else {}
    except Exception:
        raw = {
            "status": "degraded",
            "running": False,
            "stale": True,
            "last_error_code": "cycle_error",
        }
    return sanitize_reminder_runtime(raw if isinstance(raw, Mapping) else {})
~~~

Import `functools`, `Mapping`, Task 1's `ALLOWED_METRIC_KEYS`, and Task 2's `sanitize_reminder_runtime`. Attach the two bounded snapshot functions as `MessageMonitor` methods (or remove `self` and call them as pure helpers consistently). Replace the old delta helpers rather than leaving two definitions. `_bounded_rate_snapshot()` is itself the exact at-most-1,000-entry snapshot; add a matching deterministic `_bounded_intent_snapshot()` (at most 256 sorted names), and advance baselines only to those exact bounded snapshots. NLU deltas iterate the whole finite allowlist. Thus no key can be omitted by a delta helper while a broader baseline advances past it. Add tests for a counter reset, bool/negative/oversized values, more than the fixed item limits across reordered dictionaries, a missing checker, a raising/malformed `get_health()` adapter mapped by the caller to the bounded empty/degraded snapshot, and a normal typed checker snapshot.

Inside `_persist_console_stats_once()`, use:

~~~python
async with self._console_persist_lock:
    intent_snapshot = self._bounded_intent_snapshot()
    rate_snapshot = self._bounded_rate_snapshot()
    nlu_snapshot = self.nlu_metrics.snapshot()
    reminder_snapshot = self._bounded_reminder_runtime_snapshot()
    intent_delta = _counter_stats_delta(intent_snapshot, self._last_persisted_intent_stats)
    rate_delta = _flat_counter_delta(rate_snapshot, self._last_persisted_rate_stats)
    nlu_delta = _nested_counter_delta(nlu_snapshot, self._last_persisted_nlu_stats)
    cancellation_requested = False
    saved = True
    write_error: BaseException | None = None
    if intent_delta or rate_delta or nlu_delta or reminder_snapshot != self._last_persisted_reminder_runtime:
        save = functools.partial(
            self.console_store.save_stats,
            intent_delta,
            rate_delta,
            nlu_stats=nlu_delta,
            reminder_runtime=reminder_snapshot,
        )
        write_task = asyncio.create_task(
            asyncio.to_thread(save),
            name="console-stats-write",
        )
        self._console_write_task = write_task
        try:
            while True:
                try:
                    saved = await asyncio.shield(write_task)
                    break
                except asyncio.CancelledError:
                    cancellation_requested = True
                except BaseException as exc:
                    write_error = exc
                    saved = False
                    break
        finally:
            self._console_write_task = None
        if saved:
            self._last_persisted_intent_stats = intent_snapshot
            self._last_persisted_rate_stats = rate_snapshot
            self._last_persisted_nlu_stats = nlu_snapshot
            self._last_persisted_reminder_runtime = reminder_snapshot
    if cancellation_requested:
        raise asyncio.CancelledError
    if not saved:
        raise RuntimeError("console_stats_save_failed") from None
~~~

Always pass the bound `partial` to `asyncio.to_thread`. Shield only the owned worker, not the whole periodic task. If cancellation arrives during the thread write, remember it and await the worker to a known finish. Advance baselines exactly once only after `saved is True`; whether the worker returns `False` or raises, retain every old baseline. Cancellation takes precedence after settlement: re-raise `CancelledError` even when the settled worker returned `False` or raised, so the canceled persistence loop exits and final close can retry the unchanged delta. Without cancellation, map both failure shapes to the bounded `console_stats_save_failed` error without exposing the worker exception. The async lock remains held through worker completion and baseline update. Add barrier tests for canceled-write-success, canceled-write-`False`, and canceled-write-exception; the latter two are retried exactly once by final close.

- [ ] **Step 4: Stop every producer before the final flush (2–5 minutes)**

Under the typed lane's close lock, call the synchronous `reminder_checker.stop()` first. Cancel every task in `_background_tasks`—including `reminder-checker`, `initial-gcal-sync`, and `console-persistence`—then await all of them with `return_exceptions=True` and clear both task registries. A canceled persistence loop must finish any shielded `_console_write_task` and update its baseline before it exits. Only after no owned task or worker can increment/persist counters, call `_persist_console_stats_once()` exactly once and set `_final_stats_flushed = True`. A repeated close sees the completed flag, does not stop resources or persist again, and returns. Add a fake producer whose cancellation handler increments a counter; assert that increment is included in the final stored delta. Add a thread barrier test that blocks `save_stats`, starts close, releases the worker, and proves the stored delta is one rather than two.

- [ ] **Step 5: Record only authorized routing (2–5 minutes)**

Increment decision/parser/rejection metrics after the mention-required guild/DM and allowlist gates, never before. Add tests that untagged guild messages, untagged DMs, and disallowed authors leave `nlu_metrics.snapshot()` unchanged.

- [ ] **Step 6: Wire delivery metrics at exact checker branches (2–5 minutes)**

Add keyword-only `metrics: NLUMetrics | None = None` after `interval_seconds` in `ReminderChecker.__init__()` and pass `monitor.nlu_metrics` from production setup. Record this fixed mapping; these event counters are separate from, and never substituted for, the typed checker-health snapshot:

| Branch | Metric call |
|---|---|
| immediately before an actual channel/fallback send | `record_reminder_delivery("attempted")` |
| successful warning or non-late due send | `record_reminder_delivery("sent")` |
| successful due send where canonical `due_at < now` but still inside the typed catch-up window | `record_reminder_delivery("catchup_sent")` |
| existing sent occurrence key suppresses delivery | `record_reminder_delivery("deduplicated")` |
| successful digest acknowledgement | `record_reminder_delivery("digest_sent")` |
| failed digest acknowledgement | `record_reminder_delivery("digest_failed", error_code=delivery_error_code)` |
| other failed acknowledgement | `record_reminder_delivery("send_failed", error_code=delivery_error_code)` |

At each failure branch, derive the bounded metric only from the shared `MessageSendResult.error_code`, never by re-catching Discord exceptions or copying their text. Map `missing_channel|invalid_channel|missing_adapter -> channel_missing`, `forbidden -> send_forbidden`, `http -> send_http`, and `empty|daily_quota|timeout|transport|send_task_cancelled|send_task_exception|partial_send -> manager_error`; canonical due-time validation failure alone selects `invalid_due_at`. `DELIVERED` must have no error code by construction. Add a registry test that every shared `SEND_ERROR_CODES` member is mapped exactly once, fixed-clock tests for every event row, and assert checker `get_health()` still exposes only its pre-existing typed status/error/stats contract.

- [ ] **Step 7: Run lifecycle and reminder tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest \
  tests/test_nlu_metrics_privacy.py \
  tests/test_message_monitor_routing.py \
  tests/test_monitor_lifecycle.py \
  tests/test_reminder_runtime.py -q
~~~

Expected: PASS with retry-safe delta persistence and a final close flush.

- [ ] **Step 8: Commit (2–5 minutes)**

~~~bash
git add core/message_monitor.py cal_system/reminder_checker.py \
  tests/test_nlu_metrics_privacy.py tests/test_message_monitor_routing.py \
  tests/test_monitor_lifecycle.py tests/test_reminder_runtime.py
git commit -m "fix: flush NLU runtime deltas exactly once"
~~~

---

### Task 4: Expose authenticated details and redact public health

**Files:**

- Modify: `web_console/state_collector.py:127-260,629-638`
- Modify: `web_console/server.py:43-113,544-568`
- Modify: `tests/test_console_server.py`

**Interfaces:**

- Consumes: Task 2's injectable `ConsoleStore`, `load_nlu_stats()`, `load_reminder_runtime()`, and `sanitize_reminder_runtime()`; Task 3's live `monitor.nlu_metrics` and `monitor.reminder_checker.get_health()`.
- Produces: `collect_nlu_stats(monitor, *, store)`, `collect_reminder_runtime(monitor, *, store, public=False)`, `collect_authenticated_status(monitor, *, store)`, and `collect_console_health(monitor, *, port=None, store)` using Task 2's existing `ConsoleServer.store`; no endpoint response contains an unbounded exception or data-derived string.

- [ ] **Step 1: Add exact endpoint boundary tests (2–5 minutes)**

Assert unauthenticated `/api/status` is 401. With a valid API key, assert its top-level keys are exactly `status`, `bot`, `tasks`, `persistence`, `calendar_sync`, `nlu`, and `reminder_runtime`; recursively assert all NLU leaves are nonnegative integers and the reminder object equals the typed schema from Task 2. Assert `/health` has exactly `status`, `timestamp`, `console`, `ai_provider`, `bot`, `bridge`, `persistence`, `tasks`, `calendar_sync`, and `reminder_runtime`. Its reminder object has exactly `status`, `running`, `stale`, and `last_success_at`; `nlu`, delivery counters, raw `last_error`, detailed reminder errors, exception class names, and task item payloads are absent.

- [ ] **Step 2: Run the server tests red (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_console_server.py -q
~~~

Expected: FAIL because `/api/status` currently calls `collect_bot_status()` only.

- [ ] **Step 3: Add live-first bounded NLU and reminder collectors (2–5 minutes)**

Implement these exact collectors; passing `store` is mandatory at call sites, which removes hidden global-store reads from endpoint paths:

~~~python
PUBLIC_REMINDER_KEYS = (
    "status", "running", "stale", "last_success_at",
)


def collect_nlu_stats(
    monitor: object | None,
    *,
    store: ConsoleStore,
) -> dict[str, dict[str, int]]:
    metrics = getattr(monitor, "nlu_metrics", None)
    try:
        raw = (
            metrics.snapshot()
            if isinstance(metrics, NLUMetrics)
            else store.load_nlu_stats()
        )
    except Exception:
        raw = {}
    sanitized = NLUMetrics()
    sanitized.merge_snapshot(raw if isinstance(raw, Mapping) else {})
    return sanitized.snapshot()


def collect_reminder_runtime(
    monitor: object | None,
    *,
    store: ConsoleStore,
    public: bool = False,
    reference: datetime | None = None,
) -> dict[str, object]:
    checker = getattr(monitor, "reminder_checker", None)
    get_health = getattr(checker, "get_health", None)
    live = callable(get_health)
    try:
        raw = get_health() if live else store.load_reminder_runtime()
    except Exception:
        live = False
        raw = {
            "status": "degraded",
            "running": False,
            "stale": True,
            "last_error_code": "cycle_error",
        }
    full = sanitize_reminder_runtime(raw if isinstance(raw, Mapping) else {})
    if not live:
        now = reference or datetime.now().astimezone()
        last_success = full["last_success_at"]
        parsed_success = (
            datetime.fromisoformat(last_success.replace("Z", "+00:00"))
            if isinstance(last_success, str)
            else None
        )
        full["running"] = False
        full["stale"] = (
            parsed_success is None
            or (
                now.astimezone(timezone.utc)
                - parsed_success.astimezone(timezone.utc)
            ) > timedelta(seconds=150)
        )
        full["status"] = "starting" if monitor is None else "degraded"
    if not public:
        return full
    return {key: full[key] for key in PUBLIC_REMINDER_KEYS}
~~~

Never return raw reminder exception text. A raising live checker, raising store, malformed snapshot, or invalid timestamp maps to the same bounded degraded/non-running/stale shape and never escapes the endpoint. A persisted snapshot is historical aggregate/readback data, never liveness proof: it cannot retain `running=True` or an old healthy status when no callable live checker exists. Add a restart test with yesterday's persisted `status=ok,running=true,stale=false`; `monitor=None` reports starting/non-running/stale, and a ready monitor missing its checker reports degraded/non-running/stale through `/health`. Add explicit raising-checker and raising-store endpoint tests.

- [ ] **Step 4: Define exact bounded component projections (2–5 minutes)**

Do not return the existing raw task, persistence, or calendar dictionaries from either endpoint. Add allowlists for status/reason codes and reconstruct only these shapes:

~~~python
import math


DEGRADED_REASON_CODES = frozenset({
    "discord_user_missing", "discord_not_ready", "discord_closed",
    "tasks_degraded", "persistence_degraded", "calendar_sync_degraded",
})
TASK_STATES = frozenset({
    "running", "completed", "cancelled", "degraded", "failed", "other",
})
BOT_STATUS_VALUES = frozenset({"starting", "online", "degraded", "unknown"})
COMPONENT_STATUS_VALUES = frozenset({
    "starting", "ok", "healthy", "degraded", "disabled", "stopped",
    "unknown", "error", "unavailable", "unhealthy",
})
CONNECTION_STATUS_VALUES = frozenset({"connected", "disconnected", "unknown"})
STORE_ERROR_CODES = frozenset({
    "load_stats", "save_stats", "append_logs", "read_error",
    "unsupported_stats_schema", "other",
})


def _bounded_value(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _nonnegative_number_or_none(value: object) -> int | float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return value


def _iso_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _bot_projection(raw: Mapping[str, object]) -> dict[str, object]:
    reasons = raw.get("degraded_reasons")
    reason_values = reasons if isinstance(reasons, list) else []
    return {
        "status": _bounded_value(raw.get("status"), BOT_STATUS_VALUES),
        "monitor_ready": raw.get("monitor_ready") is True,
        "discord_connected": raw.get("discord_connected") is True,
        "discord_ready": raw.get("discord_ready") is True,
        "discord_closed": raw.get("discord_closed") is True,
        "uptime_seconds": _nonnegative_int(raw.get("uptime_seconds")),
        "guilds": _nonnegative_int(raw.get("guilds")),
        "users": _nonnegative_int(raw.get("users")),
        "latency": _nonnegative_number_or_none(raw.get("latency")),
        "degraded_reasons": sorted({
            value for value in reason_values
            if isinstance(value, str) and value in DEGRADED_REASON_CODES
        }),
    }


def _task_projection(raw: Mapping[str, object]) -> dict[str, object]:
    counts = {state: 0 for state in sorted(TASK_STATES)}
    items = raw.get("items")
    for value in (items.values() if isinstance(items, Mapping) else ()):
        state = value.get("state") if isinstance(value, Mapping) else None
        key = state if isinstance(state, str) and state in TASK_STATES else "other"
        counts[key] += 1
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "counts": counts,
    }


def _persistence_projection(raw: Mapping[str, object]) -> dict[str, object]:
    error = raw.get("error_code")
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "stats_schema_version": 3,
        "last_stats_saved_at": _iso_or_none(raw.get("last_stats_saved_at")),
        "last_log_write_at": _iso_or_none(raw.get("last_log_write_at")),
        "error_code": (
            error if isinstance(error, str) and error in STORE_ERROR_CODES else None
        ),
        "last_error_at": _iso_or_none(raw.get("last_error_at")),
    }


def _calendar_projection(raw: Mapping[str, object]) -> dict[str, object]:
    has_error = raw.get("last_error") is not None or raw.get("error_code") is not None
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "gcal_enabled": raw.get("gcal_enabled") is True,
        "error_code": "sync_failed" if has_error else None,
    }


def _bridge_projection(raw: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "lm_studio": _bounded_value(
            raw.get("lm_studio"), CONNECTION_STATUS_VALUES
        ),
        "requests": _nonnegative_int(raw.get("requests")),
        "errors": _nonnegative_int(raw.get("errors")),
    }
~~~

`_collect_task_health()` passes its internal result through `_task_projection`, which counts allowlisted states and drops item bodies. `_collect_persistence_health(store)` passes only `ConsoleStore.health()` into `_persistence_projection`. `_collect_calendar_sync_health()` passes its internal result through `_calendar_projection`, which converts any non-null sync error to `sync_failed` without copying it. The bridge result passes through `_bridge_projection`, dropping host, port, response bodies, and exception text. Tests assert every dictionary has exactly the keys emitted above.

- [ ] **Step 5: Inject one ConsoleStore through every endpoint collector (2–5 minutes)**

Use Task 2's existing `ConsoleServer.store` seam. Add keyword-only `store: ConsoleStore` to `_collect_persistence_health`, `collect_bot_status`, `collect_authenticated_status`, and `collect_console_health`; pass the same object through every nested call. `/api/status` calls `collect_authenticated_status(self.monitor, store=self.store)`. `/health` calls `collect_console_health(self.monitor, port=self.port, store=self.store)`. Demo data uses static zero counters and contains no persisted values.

Assemble the endpoints only from bounded projections:

~~~python
AI_PROVIDER_VALUES = frozenset({"lm_studio", "openrouter", "unknown"})


def collect_authenticated_status(
    monitor: object | None,
    *,
    store: ConsoleStore,
) -> dict[str, object]:
    bot = collect_bot_status(monitor, store=store)
    tasks = _collect_task_health(monitor)
    persistence = _collect_persistence_health(store)
    calendar_sync = _collect_calendar_sync_health(monitor)
    return {
        "status": bot["status"],
        "bot": bot,
        "tasks": tasks,
        "persistence": persistence,
        "calendar_sync": calendar_sync,
        "nlu": collect_nlu_stats(monitor, store=store),
        "reminder_runtime": collect_reminder_runtime(
            monitor, store=store, public=False
        ),
    }


async def collect_console_health(
    monitor: object | None,
    *,
    port: int | None = None,
    store: ConsoleStore,
) -> dict[str, object]:
    bot = collect_bot_status(monitor, store=store)
    tasks = _collect_task_health(monitor)
    persistence = _collect_persistence_health(store)
    calendar_sync = _collect_calendar_sync_health(monitor)
    bridge = _bridge_projection(await collect_bridge_health(monitor))
    reminder_runtime = collect_reminder_runtime(monitor, store=store, public=True)
    provider = _configured_ai_provider(monitor)
    starting = bot["status"] == "starting" or reminder_runtime["status"] == "starting"
    degraded = any(
        value["status"] in {"degraded", "error", "unavailable", "unhealthy"}
        for value in (bot, tasks, persistence, calendar_sync)
    )
    if (
        reminder_runtime["status"] in {"degraded", "stopped"}
        or reminder_runtime["stale"] is True
        or reminder_runtime["running"] is False
    ):
        degraded = True
    if provider == "lm_studio" and bridge["status"] in {
        "degraded", "error", "unavailable", "unhealthy",
    }:
        degraded = True
    return {
        "status": "starting" if starting else ("degraded" if degraded else "healthy"),
        "timestamp": datetime.now().isoformat(),
        "console": {
            "status": "running",
            "port": port if isinstance(port, int) and 0 <= port <= 65535 else None,
        },
        "ai_provider": provider if provider in AI_PROVIDER_VALUES else "unknown",
        "bot": bot,
        "bridge": bridge,
        "persistence": persistence,
        "tasks": tasks,
        "calendar_sync": calendar_sync,
        "reminder_runtime": reminder_runtime,
    }
~~~

`collect_bot_status()`, `_collect_task_health()`, `_collect_persistence_health()`, and `_collect_calendar_sync_health()` return their Step-4 bounded projections, not the pre-sanitized dictionaries. The two endpoint functions therefore return exactly the seven and ten top-level keys asserted in Step 1.

- [ ] **Step 6: Add restart/readback and whole-endpoint redaction tests (2–5 minutes)**

Write v3 stats to `ConsoleStore(data_dir=tmp_path)`, construct `ConsoleServer(host="127.0.0.1", port=0, api_key="test-key", monitor=None, store=store)`, then construct a second store and identically configured server from the same directory; prove authenticated NLU/reminder readback survives restart. Inject the marker `SECRET-EXCEPTION-CONTENT` independently into fake task item error fields, store internals, calendar sync errors, bridge response extras, and checker extras; serialize both endpoints and assert neither the marker nor the keys `last_error`, `read_errors`, `stats_read_error`, `exception`, or `items` occurs. Authenticated reminder health may expose only an allowlisted `last_error_code`, never `other` or the raw marker.

- [ ] **Step 7: Run and commit (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest tests/test_console_server.py -q
git add web_console/state_collector.py web_console/server.py \
  tests/test_console_server.py
git commit -m "feat: expose redacted NLU operator health"
~~~

---

### Task 5: Make the production NLU report a CI gate

**Files:**

- Modify: `.github/workflows/ci.yml:42-70`
- Modify: `tests/README_TESTING.md`

**Interfaces:**

- Consumes: `scripts/evaluate_nlu.py --corpus PATH --report PATH` and `tests/fixtures/nlu_contract_v1.jsonl` from the routing-foundation lane; the feature-parity lane's final corpus/help rows.
- Produces: a CI order of compile checks -> non-browser pytest -> production NLU evaluator -> always-uploaded privacy-safe report -> Playwright pytest, plus the identical documented local commands.

- [ ] **Step 1: Split the current combined test step (2–5 minutes)**

Replace it with these exact independent steps after compile checks:

~~~yaml
      - name: Run non-browser tests
        run: python -m pytest -q --ignore=tests/test_console_frontend.py

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

      - name: Run browser tests
        run: python -m pytest -q tests/test_console_frontend.py
~~~

The install deliberately occurs after the offline contract/report steps and immediately before the browser step, so a network/browser bootstrap failure cannot mask the offline NLU result.

- [ ] **Step 2: Document local commands and thresholds (2–5 minutes)**

In `tests/README_TESTING.md`, replace the obsolete model-only natural-chat instructions as the primary gate with the production parser command, its privacy guarantees, exact thresholds, and a separate optional model-quality check. State that the report contains ids and aggregate enum values, never utterances.

- [ ] **Step 3: Validate workflow syntax and report generation (2–5 minutes)**

~~~bash
.venv312/bin/python - <<'PY'
from pathlib import Path

workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
offline = workflow.index("- name: Run non-browser tests")
nlu = workflow.index("- name: Evaluate production NLU contract")
install = workflow.index("- name: Install Playwright Chromium")
browser = workflow.index("- name: Run browser tests")
assert offline < nlu < install < browser
assert "uses: actions/upload-artifact@v4" in workflow
PY
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
~~~

Expected: both exit 0.

- [ ] **Step 4: Commit (2–5 minutes)**

~~~bash
git add .github/workflows/ci.yml tests/README_TESTING.md
git commit -m "ci: gate production natural-language behavior"
~~~

---

### Task 6: Align architecture and operator documentation

**Files:**

- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/QUICK_REFERENCE.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/LM_STUDIO_SETUP.md`
- Modify: `docs/OPENROUTER_INTEGRATION.md`
- Modify: `docs/DOCUMENTATION.md`
- Modify: `docs/MODEL_RECOMMENDATIONS.md`

**Interfaces:**

- Consumes: the final `ACTION_PROTOCOL_PROMPT`, typed dispatch contract, pending-action safety matrix, `HELP_EXAMPLES`, and NLU evaluator thresholds implemented by the preceding plans.
- Produces: documentation whose executable examples are registry-backed and whose architecture, safety, compatibility, provider, and measured-language claims match the implemented contracts.

- [ ] **Step 1: Add a stale-claim search test (2–5 minutes)**

Run and save the matches for review:

~~~bash
rg -n 'SAVE_EVENT|ingen rigid|ingen rigid kommando|forstår.*dialekt|legg til Inception|current priorities' \
  README.md tests/README_TESTING.md \
  docs/ARCHITECTURE.md docs/QUICK_REFERENCE.md docs/DEVELOPMENT.md \
  docs/LM_STUDIO_SETUP.md docs/OPENROUTER_INTEGRATION.md \
  docs/DOCUMENTATION.md docs/MODEL_RECOMMENDATIONS.md
~~~

Expected before edits: legacy action-protocol and broad natural-language claims remain.

- [ ] **Step 2: Document one exact action data flow (2–5 minutes)**

In `docs/ARCHITECTURE.md` and `docs/DOCUMENTATION.md`, document:

~~~text
authorized mention-required guild/DM turn
  -> lossless normalization + speech-act safety
  -> deterministic typed candidates
  -> risk arbitration
  -> immediate explicit read/add OR scoped pending action
  -> optional strict model proposal through the same arbiter
  -> parse-once handler dispatch
~~~

State that destructive actions always confirm, inferred writes confirm, model output never directly calls a handler, and quoted/negated/hypothetical writes are blocked.

- [ ] **Step 3: Replace provider protocol examples (2–5 minutes)**

In LM Studio/OpenRouter docs, replace executable `SAVE_EVENT` guidance with one schema-valid standalone JSON example from `ACTION_PROTOCOL_PROMPT`. Mark the legacy tag as input-compatibility for one release: it converts to a semantic additive calendar proposal, enters the same validation/confirmation flow, and is never a read-only or direct-execution path. State that provider prompts preserve the same action/safety contract. Do not claim provider calls were live-tested by this offline lane.

- [ ] **Step 4: Correct language and help claims (2–5 minutes)**

Make `README`, quick reference, model recommendations, and documentation say “evaluated Bokmål, Nynorsk, selected dialect-adjacent forms, and English examples” rather than general dialect understanding or “no command structure.” Link the production report command and explain that unsupported ambiguity produces clarification or chat fallback.

- [ ] **Step 5: Update developer extension rules (2–5 minutes)**

In `docs/DEVELOPMENT.md`, require new features to add a typed payload, pure candidate collector, risk entry, parser negative cases, production corpus rows, help-registry row only after parity passes, and no reparsing in handlers.

- [ ] **Step 6: Verify examples against the registry/corpus (2–5 minutes)**

Run `tests/test_help_route_parity.py` and search again for stale claims. Any remaining legacy mention must contain the word `compatibility` or `legacy` in the same paragraph.

- [ ] **Step 7: Commit (2–5 minutes)**

~~~bash
git add README.md docs/ARCHITECTURE.md docs/QUICK_REFERENCE.md \
  docs/DEVELOPMENT.md docs/LM_STUDIO_SETUP.md \
  docs/OPENROUTER_INTEGRATION.md docs/DOCUMENTATION.md \
  docs/MODEL_RECOMMENDATIONS.md
git commit -m "docs: describe measured natural-language behavior"
~~~

Expected: the commit succeeds, every executable help example is registry-backed,
and the documentation describes measured language coverage and confirmation
boundaries without claiming live-provider or broad-dialect proof.

---

### Task 7: Run the release gate and record exact non-claims

**Files:**

- Test: `tests/`
- Test: `tests/test_console_frontend.py`
- Verify: `.artifacts/nlu-contract.json`
- Verify: `.github/workflows/ci.yml`
- Verify: `docs/superpowers/plans/2026-07-14-natural-language-action-architecture.md`

**Interfaces:**

- Consumes: every implementation and test artifact from Tasks 1–6 and the five prerequisite plans.
- Produces: exact local verification output, the current branch/HEAD, a separate browser result, explicit non-claims, and one privacy-safe Obsidian implementation record; it does not produce a source commit.

- [ ] **Step 1: Check disk before aggregate loops (2–5 minutes)**

~~~bash
df -h /System/Volumes/Data
~~~

Stop and report below 30 GiB free.

- [ ] **Step 2: Run syntax and static failure checks (2–5 minutes)**

~~~bash
.venv312/bin/python -m compileall -q \
  -x '(^|/)(\.git|__pycache__|\.pytest_cache|\.venv312)(/|$)' .
.venv312/bin/python -m flake8 . \
  --exclude=.venv312,__pycache__,.git,.pytest_cache \
  --count --select=E9,F63,F7,F82 --show-source --statistics
~~~

Expected: both exit 0.

- [ ] **Step 3: Run and inspect the offline NLU gate (2–5 minutes)**

~~~bash
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
.venv312/bin/python -m pytest -q \
  tests/test_nlu_contract.py::test_report_omits_utterance_payload_exception_and_source_id
.venv312/bin/python - <<'PY'
from hashlib import sha256
import json
from pathlib import Path
from tests.nlu_harness import load_cases

path = Path(".artifacts/nlu-contract.json")
report = json.loads(path.read_text(encoding="utf-8"))
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
assert all(value["defined"] and value["rate"] >= 0.95 for value in report["by_locale"].values())
cases = load_cases(Path("tests/fixtures/nlu_contract_v1.jsonl"))
assert [row["id"] for row in report["cases"]] == [
    sha256(case.id.encode("utf-8")).hexdigest()[:16]
    for case in cases
]


def object_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from object_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from object_keys(child)


for forbidden in {"text", "utterance", "title", "url", "slots", "model_response"}:
    assert forbidden not in set(object_keys(report))
print("NLU contract report: PASS")
PY
~~~

Expected: `NLU contract report: PASS`.

The focused canary test proves that unique utterance, payload, exception, and
source-id content is omitted. The structural inspection verifies the real
artifact and its hashed case-id mapping. Do not compare every corpus utterance
as a raw substring of the report: short legitimate cases such as `1` and
`status` also occur in aggregate counts and intent enum values, making that
check a false-positive rather than a privacy assertion.

- [ ] **Step 4: Run all offline tests (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py
~~~

Expected: PASS. Record count and duration.

- [ ] **Step 5: Run browser tests separately (2–5 minutes)**

~~~bash
.venv312/bin/python -m pytest -q tests/test_console_frontend.py
~~~

If Chromium is absent, report that environment blocker separately. Installing it requires network and is an explicit follow-up action:

~~~bash
.venv312/bin/python -m playwright install chromium
.venv312/bin/python -m pytest -q tests/test_console_frontend.py
~~~

Do not collapse offline success and browser success into one claim.

- [ ] **Step 6: Check the patch and exact HEAD (2–5 minutes)**

~~~bash
git diff --check
git status --short
git rev-parse HEAD
~~~

- [ ] **Step 7: Log implementation evidence to Obsidian (2–5 minutes)**

Use the `$obsidian` skill after implementation. Record the branch, exact HEAD, NLU report values, offline pytest count, separate browser result, compatibility paths still active, and explicit non-claims. Do not log corpus utterances, model responses, names, titles, URLs, credentials, or user data.

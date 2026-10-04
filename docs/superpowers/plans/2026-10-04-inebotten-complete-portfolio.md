# Inebotten Complete Portfolio Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if delegation is later selected. Steps use checkbox syntax. Execution authorized by the user on 4 October 2026. Task numbers follow execution order; Ixx identifiers retain proposal identity.

**Goal:** Address every finding and all 39 proposals in the improvement portfolio through independently reviewable, verified changes, including a disposition for the ten existing dependency PRs.

**Architecture:** Preserve managers as transport-independent domain owners, handlers as adapters, conservative intent routing, JSON storage, and the vanilla console. Introduce explicit storage, delivery, identity, time, and provider contracts before expanding workflows. Integrate focused PRs serially where they share files or persisted schemas; retain compatibility adapters during migration.

**Tech Stack:** Python 3.12+, asyncio, discord.py-self, JSON persistence, aiohttp, Google Calendar integration, Tk desktop launchers, HTML/CSS/vanilla JavaScript, pytest and the existing Playwright frontend checks. Optional bot transport gets its own dependency environment if feasibility supports it.

**Spec:** docs/plans/2026-10-04-improvement-portfolio.md. Read the matching proposal's evidence, scope boundaries, and full acceptance target before each task. This plan adds implementation decisions; it does not erase those requirements.

## Global constraints

- The planning-only restriction applied to the preceding turn. The user has now authorized execution; preserve separate gates for private/live data migration, shared-branch merge and deployment.
- Future implementation uses a suitable managed worktree based on freshly verified GitHub master; preserve the current dirty checkout and local-only exporter. Default branch names use codex/.
- At planning refresh, master is c0b6a321b3e63e154e466604a9980954c502fb4d; preserved local HEAD is 6a0e861eafb457fad38428da8edffc6f0fc2b1bf. Recheck both before execution.
- User-facing language remains Norwegian; code stays English. New command parsing goes through IntentRouter, not ad hoc MessageMonitor branches.
- Preserve mention gating, identity checks, target ambiguity rejection, credential-file safeguards, controller audit rules, bridge authentication, log redaction, private files, current-master partial-startup safety, and console authentication/safe DOM rendering.
- Do not increase the defaults of 5 messages/second or 10,000/day. Shared sending must also retain configured SAFE_INTERVAL behavior.
- Legacy shared calendars remain shared until explicitly migrated; no silent scope split, default proactive messaging expansion, paid provider fallback, or local-to-cloud escalation.
- Tests use generated fixtures, fake clocks/providers, and a test subprocess with controlled environment. Never use personal Hermes stores as fixtures.
- Before long build/test loops, check df -h /System/Volumes/Data; stop below 30Gi free. Use bounded run-local scratch and clean only confirmed owned scratch.
- Native execution in the parent is the default. Delegate only bounded independent work that benefits from another reviewer, using the current AGENTS routing/capability/quota policy. No mandatory fan-out or stronger-model assumption.
- Dependencies below are hard prerequisites. Optional integration notes are not hidden prerequisites. The plan strengthens prerequisites wherever a task consumes another task's storage, policy, mutation, deployment, or registry contract; this refinement is recorded in each task.

## Review focus

1. Two processes opening one Hermes store: reject the second writer before mutation; test in I05.
2. Permission revoked after preview: reauthorize on apply, not just preview; test in I08 and I26.
3. Stop/timeout after remote acceptance: preserve an unknown outcome without blind replay; test in I03 and I11.
4. Wall clock jumps during deadlines/quiet hours: elapsed deadlines use monotonic time, domain dates use an aware clock; test in I09, I16, and I25.
5. Older code opening a newer data schema: refuse destructive writes and report recovery requirements; test in I04, I23, and I35.

## Execution, tracking, and completion rules

The task owner is Codex; product decisions and private/live acceptance belong to the user. Track every ID through planned → reproducing → implementing → local verified → exact-head CI verified → awaiting any stated manual/live gate → accepted. Never label untested runtime behavior accepted. A deferred or declined stretch item gets an explicit decision record, not a fictitious implementation checkmark.

For each task: add the named behavioral regression first; observe the expected failure; implement the smallest coherent change; run the specified tests and shared regressions; review the diff and migrations; commit only the listed scope and open a focused PR once execution is authorized. Larger task sections state PR boundaries. After creating any PR, attach it to the chat. Recheck its exact head after review amendments and before interpreting CI. No merge/deploy approval is implied by this planning request.

**Verification command convention:** the initial test interpreter is .venv312/bin/python where available; CI uses its configured Python 3.12 interpreter. A referenced new test file is a planned artifact, not an existing file claim. After I20 lands, use the safe runner below with each task's listed paths. Frontend tests run separately from async tests as existing CI does. For every production-code PR also run current syntax/lint gates and relevant routing/false-positive/security regressions. Run the full offline suite at integration checkpoints; repeat only after new changes or failures justify it.

Planned commands from the execution worktree, after I20 exists:

```bash
.venv312/bin/python scripts/run_offline_tests.py --python .venv312/bin/python -- tests/test_gcal_lookup_outcomes.py tests/test_calendar_sync.py -q
.venv312/bin/python scripts/run_offline_tests.py --python .venv312/bin/python -- --ignore=tests/test_console_frontend.py -q
.venv312/bin/python scripts/run_offline_tests.py --python .venv312/bin/python -- tests/test_console_frontend.py -q
```

The runner exits nonzero on failure, reports collected/executed/skipped results, and blocks live markers by default. A passing command is evidence for its executed cases only. Substitute the selected worktree/CI interpreter explicitly; do not use the user's live runtime environment.

**PR receipts:** proposal IDs, base/full head SHA, test commands and actual counts, migrated schema versions, data backup/rollback proof, CI links, UI/live evidence where required, and remaining gates. Logs omit prompts, credentials, private data, and member content. Log meaningful completion in Obsidian.

**Shared interface rule:** interfaces listed below are planned public contracts. Records list their fields at their owning task. Consumers import that definition rather than inventing an equivalent shape. Existing APIs keep compatibility adapters until their callers and fixtures move. No general framework or repository-wide rewrite is required.

## Release sequence and integration gates

| Wave | Execution order | Gate before advancing |
| --- | --- | --- |
| 1 | I20 → I01 → I02 → I04 → I06 → I27 → I28 → I32; I39 retention decision/export safety | Safe offline harness, no inconclusive deletion, live reminder ownership, visible persistence errors, honest utility data, preserving setup. |
| 2 | I05 → I03 → I07 → I09 → I12 → I15 → I16 → I21 → I29 → I33 | Serialized stores, truthful sends, migration-tested scopes/time, bounded AI/UI, reproducible dependency graph. |
| 3 | I08 → I11 → I13 → I17 → I18 → I19 → I22 → I24 → I30 | Preview identities, recoverable sync, deliberate memory, accurate diagnostics, release artifact proof, bounded resource lifetimes. |
| 4 | I14 → I25 → I10 → I23 → I31 → I35 → I36 | Full private exports, notification/recurrence correctness, code/data rollback, desktop shutdown, restore and exchange rehearsals. |
| 5 | I26 → I34 → I37 → I38 | Authenticated calendar writes, deliberate planning, explicit transport feasibility, opt-in bounded recipes. |

These are ordered milestones, not calendar promises. After each wave, run the offline integration suite and examine every unresolved acceptance gate. Changes sharing MessageMonitor, configuration, console server, or calendar schema are integrated one at a time. Independent fixtures/UI tasks may run concurrently after their contracts land. Do not batch schema migrations with a transport rewrite or release-tool rewrite.

## Wave 1 — Preserve data and tell the truth

### Task 1: I20 — Hermetic offline verification

**Dependencies:** None. **PR boundary:** one harness/CI-isolation PR.
**Files:** modify tests/conftest.py, pytest.ini, .github/workflows/ci.yml, tests/README_TESTING.md; create tests/test_test_environment.py and scripts/run_offline_tests.py.
**Interfaces:** scripts/run_offline_tests.py --python PATH -- PYTEST_ARGS launches the selected interpreter with an explicit child env and run-local Hermes directory before any application import. live_provider and live_account markers require separate explicit --live-provider/--live-account invocation; loopback fixture servers remain allowed by default.

- [x] Add test_inherited_hermes_is_untouched: seed a synthetic outside directory, run collection in a child, and assert its bytes unchanged; test_external_network_is_blocked; test_parallel_console_ports_differ.
- [x] Observe import-order/environment/port failures with generated fixtures; do not run an unsafe old full suite against the user's inherited configuration.
- [x] Move test bootstrap before console imports, remove sensitive inherited config inside the child only, bind fixture servers to port 0, and gate live markers. Ensure failed/interrupted runs clean only their own bounded scratch.
- [x] Run tests/test_test_environment.py, then existing non-live tests and tests/test_console_frontend.py separately; verify zero external connections and record executed/skipped counts.
- [x] Review and commit the harness; document the exact safe runner. This gate unlocks all following automated checks.

### Task 2: I01 — Preserve events on inconclusive Google lookups

**Dependencies:** I20. **PR boundary:** lookup classification and reconciliation only.
**Files:** modify cal_system/google_calendar_manager.py, cal_system/calendar_manager.py, tests/test_calendar_sync.py; create tests/test_gcal_lookup_outcomes.py.
**Interfaces:** get_event_outcome(event_id: str) -> EventLookup; define EventLookup in cal_system/google_calendar_manager.py with status live|cancelled|missing|unavailable, event: dict|None, retry_after_s: float|None, reason_code: str. Keep get_event for legacy readers; deletion callers use the explicit outcome.

- [x] Add test_none_timeout_and_permission_preserve_local_item and test_authoritative_cancel_removes_item, asserting preserved IDs/fields and warning state for None/403/429/5xx/malformed responses.
- [x] Reproduce the narrow deletion failure with fake API objects.
- [x] Map errors without suppressing meaning; classify missing only when the adapter establishes authoritative absence in an accessible calendar. A bare ambiguous error/404 is insufficient. Update reconciliation to retain uncertain items.
- [x] Run tests/test_gcal_lookup_outcomes.py and tests/test_calendar_sync.py; preserve pagination and mixed-batch regressions.
- [x] Review compatibility and commit; no live Google account is needed for this PR.

### Task 3: I02 — One live reminder owner

**Dependencies:** I20. **PR boundary:** composition/wiring.
**Files:** modify core/message_monitor.py; extend tests/test_gcal_reminder_routing.py and tests/test_reminder_crud.py; create tests/test_reminder_scheduler_ownership.py.
**Interfaces:** SelfbotClient._create_reminder_checker(monitor=None) consumes the initialized monitor.reminders. ReminderChecker.reminders is that exact object; startup does not load another copy.

- [x] Add test_checker_uses_monitor_manager asserting object identity; create/edit/complete/delete a reminder after checker startup and assert its next fake scan sees the change.
- [x] Reproduce stale ownership with the current composition.
- [x] Inject the owned manager and retain current-master failure-safe initialization/reconnect behavior.
- [x] Run all three listed tests plus current-master tests/test_ready_initialization.py when working from master.
- [x] Review and commit the wiring; prove one checker and one manager across reconnects.

### Task 4: I04 — Explicit storage failures and schema compatibility

**Dependencies:** I20. **PR boundary:** storage contract, then calendar/reminder/memory/console adoption in separately reviewable slices.
**Files:** modify utils/json_storage.py, cal_system/calendar_manager.py, cal_system/reminder_manager.py, memory/user_memory.py, web_console/console_store.py and affected handlers; create utils/storage_contract.py and tests/test_storage_outcomes.py.
**Interfaces:** load_document(path: Path, schema_version: int) -> StorageLoad(status missing|valid|corrupt|unsupported, document: dict|None, error_code: str|None). commit_document(path: Path, document: dict, schema_version: int) -> StorageCommit(ok: bool, error_code: str|None). Managers expose failed mutations; never respond success before commit succeeds.

- [x] Add test_corrupt_bytes_are_preserved, test_save_failure_returns_failure, and test_newer_schema_is_read_only; assert wrong-shape/truncated files and original mutation state remain recoverable.
- [x] Reproduce default-empty/false-success behavior with fixture stores and injected write errors.
- [x] Introduce validation/version envelopes, read-only degraded state, per-store legacy backup before migration, and rollback of uncommitted in-memory mutations. Adapt every touched handler.
- [x] Run tests/test_storage_outcomes.py, tests/test_calendar_edit.py, tests/test_reminder_crud.py, tests/test_user_memory_controls.py, tests/test_console_server.py, and relevant hardening regressions.
- [x] Review each adoption slice; commit only with a fixture migration and downgrade refusal receipt. No automatic corrupt-file repair.

### Task 5: I06 — Request-owned locale

**Dependencies:** I20. **PR boundary:** request context and handler migration.
**Files:** create core/request_context.py and tests/test_request_locale.py; modify memory/localization.py, core/message_monitor.py, features/base_handler.py and handlers using loc.current_lang.
**Interfaces:** immutable RequestContext(request_id: str, user_id: str, channel_id: str, guild_id: str|None, locale: str); Localization.for_language(locale: str) returns an immutable translation view. Handler dispatch consumes one context; no handler changes singleton locale.

- [ ] Add test_interleaved_norwegian_english_keep_locale with a barrier around an await; assert each response's expected translation.
- [ ] Observe cross-request language interference.
- [ ] Pass context/localization views at dispatch and use existing detection/preferences; keep translation keys and supported Norwegian dialect behavior.
- [ ] Run tests/test_request_locale.py, tests/test_message_monitor_routing.py, tests/test_intent_router.py, tests/test_false_positives.py.
- [ ] Review handler coverage and commit; grep for dispatch-time singleton language writes to prove migration completeness.

### Task 6: I27 — Forecast validity, location, time, and useful caching

**Dependencies:** I20, I06. **PR boundary:** forecast truth/time/location first; shared cache/ownership integration second if needed.
**Files:** create features/forecast_service.py and tests/test_forecast_validity.py; modify features/weather_api.py, features/aurora_forecast.py, core/message_monitor.py, features/daily_digest_manager.py and forecast formatting.
**Interfaces:** ForecastService receives owned provider clients plus now: Callable[[], datetime] and monotonic: Callable[[], float], defaulting to aware time and monotonic time. ForecastResult(status fresh|stale|unavailable, source: str, fetched_at: aware datetime, valid_at: aware datetime|None, expires_at: aware datetime|None, location: dict, data: dict|None); async ForecastService.get_weather(location: dict) -> ForecastResult; service owns clients/cache and has async close().

- [ ] Add test_failure_never_fabricates_weather, test_unknown_city_is_actionable, test_utc_oslo_select_same_aurora_interval, and test_same_location_reuses_cache with a fake monotonic clock/provider call counter.
- [ ] Demonstrate fabricated fallback and per-instance cache loss without network.
- [ ] Replace fallback conditions with unavailable/stale output, resolve validated aliases/coordinates, preserve aware source times, reuse one owned service, and label heuristic scores accurately.
- [ ] Run tests/test_forecast_validity.py and relevant dashboard/digest regressions; assert one provider call within the existing cache TTL and refresh after expiry.
- [ ] Review and commit; integrate close ownership in I24. Accuracy/geocoder expansion needs a separate current-source review.

### Task 7: I28 — Honest currency snapshots

**Dependencies:** I20. **PR boundary:** local snapshot contract and display only.
**Files:** modify features/calculator_manager.py and features/utility_handler.py; create tests/test_currency_snapshots.py.
**Interfaces:** RateSnapshot(source: str, effective_at: aware datetime|None, base: str, rates: dict[str, Decimal], status fresh|stale|demonstration); convert_currency(amount: Decimal, source: str, target: str, snapshot: RateSnapshot) -> Decimal. Current fixed values are demonstration data with unknown effective time.

- [ ] Add test_fixed_rates_are_labeled_estimates, test_inverse_and_cross_pair_use_one_snapshot, test_unknown_pair_refuses, and precision cases for fiat/BTC.
- [ ] Confirm current output omits source/effective-time context.
- [ ] Use one base-rate snapshot, explicit rounding and estimate wording; refuse requests requiring a current quote when no current snapshot exists.
- [ ] Run tests/test_currency_snapshots.py and utility routing regressions; preserve ordinary math/unit results.
- [ ] Review and commit; a live provider is a later optional adapter, not a silently chosen dependency.

### Task 8: I32 — Preserving private onboarding

**Dependencies:** I20. **PR boundary:** shared schema/writer, then CLI/desktop/console adoption.
**Files:** create core/config_schema.py and tests/test_config_roundtrip.py; modify core/config.py, core/auth_handler.py, utils/setup.py, utils/setup.py, mac_app/launcher.py, windows_app/launcher.py, web_console/server.py and setup documentation.
**Interfaces:** validate_settings(values: dict[str, str]) -> list[dict[str, str]] returns field/reason errors without values; update_settings(path: Path, changes: dict[str, str]) -> None privately and atomically preserves untouched keys. Use the same validation in every setup adapter.

- [ ] Add test_unknown_keys_survive_setup, test_credentials_are_never_echoed, test_file_is_private_before_content, test_email_password_rejected_at_setup, and test_explicit_hermes_has_no_project_fallback.
- [ ] Reproduce template replacement/visible-input behavior using fake credentials and temporary directories.
- [ ] Implement preserving env edits and hidden input, reject unsupported auth/provider settings early, replace stale discord.py installer guidance with a clean venv flow, and migrate adapters without changing account identity.
- [ ] Run tests/test_config_roundtrip.py, tests/test_setup_security.py, tests/test_desktop_launcher_paths.py and console setup/auth checks.
- [ ] Review and commit each adapter slice; document authoritative paths and recovery from interrupted writes.

### Task 9: I39 — Decide retention and harden the local-only exporter

**Dependencies:** I20. **PR boundary:** retention decision first; one bounded utility PR only if retained.
**Files:** local-only scripts/export_members.py and tests/test_export_members.py; inspect applicable shared controls in scripts/inebotten_ctl.py before extracting only narrowly reusable helpers.
**Interfaces:** export result includes source, scope, coverage complete|partial|unknown, rows, and truncation_reason. write_exports consumes distinct exclusive output paths; a .json argument cannot overwrite its CSV.

- [ ] Record whether the local utility has an owner/use case; preserve its local commit regardless. If declined, document deprecation and leave source/data intact.
- [ ] If retained, add tests for repeated cursors/deadline, identity failure, partial fallback, same-path extensions, existing-file preservation, private modes, and formula-like strings.
- [ ] Reuse identity/ambiguity/deadline contracts, require explicit row/byte limits, emit truthful coverage, and create output files exclusively/private; no automatic joining or new scraping capability.
- [ ] Run tests/test_export_members.py and offline controller contract checks. Verify spreadsheet-text behavior with synthetic cells in supported readers before claiming it.
- [ ] Review and commit only the intentionally retained utility; do not smuggle the local-only exporter into unrelated master PRs.

## Wave 2 — Establish shared contracts

### Task 10: I05 — Serialize store ownership and snapshot commits

**Dependencies:** I04. **PR boundary:** store transaction primitive, then adoption by calendar/reminders/memory/console stats.
**Files:** modify utils/json_storage.py, cal_system/calendar_manager.py, cal_system/reminder_manager.py, memory/user_memory.py, web_console/console_store.py; create tests/test_storage_concurrency.py.
**Interfaces:** VersionedJsonStore.snapshot() -> tuple[int, dict]; async mutate(expected_revision: int|None, change: Callable[[dict], dict]) -> tuple[int, dict]. Changes operate on a private copy; successful commit publishes the new revision/state. A process-held per-store ownership lock refuses a second writer.

- [ ] Add test_barrier_updates_preserve_both_changes, test_worker_sees_immutable_snapshot, test_second_process_refused_before_mutation, and test_interrupted_commit_keeps_old_or_new_document.
- [ ] Observe current unlocked read/merge/commit and live-dictionary races with deterministic barriers.
- [ ] Lock the whole read/change/snapshot/commit, send only immutable copied data to bounded file workers, preserve the current state on failure, and use a documented cross-platform ownership-lock adapter.
- [ ] Run tests/test_storage_concurrency.py, tests/test_storage_outcomes.py and touched-store tests; include Windows lock behavior in platform CI.
- [ ] Review and commit adoption slices; document crash-durability guarantees and justify any fsync against those guarantees.

### Task 11: I03 — One sender with truthful delivery and reserved quotas

**Dependencies:** I02, I04, I05. **PR boundary:** sender/limiter, then all outbound adapters.
**Files:** create core/outbound_sender.py and tests/test_outbound_delivery.py; modify core/rate_limiter.py, features/base_handler.py, core/message_monitor.py, cal_system/reminder_checker.py.
**Interfaces:** async OutboundSender.send(channel_id: str, text: str, *, delivery_key: str|None, deadline: float) -> DeliveryResult(status delivered|dropped|retryable|forbidden|unknown, message_id: str|None, retry_after_s: float|None, reason_code: str). deadline is monotonic. Delivered requires remote message evidence; unknown means acceptance cannot be resolved.

- [ ] Add test_missing_destination_not_marked_sent, test_concurrent_reservations_keep_existing_limits, test_timeout_after_acceptance_is_unknown, and test_shutdown_preserves_pending_delivery_state.
- [ ] Reproduce false sent accounting and competing limiter checks with fake channels/clocks.
- [ ] Reserve capacity before awaiting sends, enforce existing per-second/day/interval rules on all paths, distinguish failure/unknown outcomes, and persist scheduler success only for delivered. Honor Retry-After within the deadline; do not blindly retry unknown acceptance.
- [ ] Run tests/test_outbound_delivery.py, tests/test_base_handler_rate_limit.py, tests/test_gcal_reminder_routing.py and scheduler regressions; prove cancellation before send releases appropriate reservations.
- [ ] Review and commit each adapter migration; scan for remaining direct send bypasses and retain documented controller authorization boundaries.

### Task 12: I07 — Explicit invocation and calendar scope policy

**Dependencies:** I04, I32. **PR boundary:** policy/migration, then handler/console/setup presentation.
**Files:** create core/access_policy.py and tests/test_calendar_access_policy.py; modify core/config.py, core/message_monitor.py, cal_system/calendar_manager.py, features/calendar_handler.py and web_console/state_collector.py.
**Interfaces:** authorize(actor: RequestContext, scope_id: str, operation: str) -> AccessDecision(allowed: bool, reason_code: str). Scope records contain kind legacy_shared|private_user|approved_group, owner_id, collaborator IDs and read/write policy; invocation allowlists remain separate.

- [ ] Add a matrix for empty/nonempty allowlists, guild/DM/group-DM, owner/collaborator/outsider, and read/write. Assert legacy shared data is not silently privatized or duplicated.
- [ ] Pin current sharing/allowlist behavior as compatibility fixtures before migration.
- [ ] Centralize policy checks, add explicit configured modes and scope IDs, validate personal-ID defaults in setup, and produce a reviewed migration preview before moving existing data.
- [ ] Run tests/test_calendar_access_policy.py, tests/test_mention_gate.py, tests/test_calendar_edit.py and console authorization fixtures.
- [ ] Review and commit; accept the user-facing explanation only when setup/console can show exactly who can read/write each scope.

### Task 13: I09 — Explicit calendar time and kind

**Dependencies:** I04, I07. **PR boundary:** schema/migration, parser/display, then Google/reminder adapters.
**Files:** create cal_system/event_schema.py and tests/test_calendar_time_model.py; modify cal_system/calendar_manager.py, cal_system/natural_language_parser.py, cal_system/google_calendar_manager.py, cal_system/reminder_checker.py and features/calendar_handler.py.
**Interfaces:** EventTime(kind event|task, local_date: date, local_time: time|None, timezone: str, all_day: bool, duration_minutes: int|None); Clock.now(timezone: str) -> aware datetime and Clock.monotonic() -> float. Default timezone remains Europe/Oslo.

- [ ] Add tests for all-day round trips, custom duration preservation, invalid dates/times, DST gap/fold previews, midnight, UTC/Oslo hosts and test_wall_clock_jump_does_not_change_elapsed_deadline.
- [ ] Reproduce default-noon/fixed-duration conversion with synthetic events; record legacy interpretations as migration fixtures.
- [ ] Add the model and aware clock, losslessly migrate old strings, display inferred values before saving, reject ambiguous/nonexistent times without explicit resolution, and adapt remote start/end plus date-only reminder policy.
- [ ] Run tests/test_calendar_time_model.py, tests/test_calendar_edit.py, tests/test_calendar_sync.py and date-parser/false-positive tests.
- [ ] Review migration receipts and commit slices; no silent invention of event durations or task-as-event conversion.

### Task 14: I12 — Structured AI outcomes and bounded admission

**Dependencies:** I06, I03. **PR boundary:** provider result contract, then validated drafts/dispatch feedback.
**Files:** create ai/result_schema.py and tests/test_ai_outcomes.py; modify ai/hermes_connector.py, ai/openrouter_connector.py, ai/connector_factory.py, ai/action_schema.py and core/message_monitor.py.
**Interfaces:** AIResult(status success|busy|cancelled|auth_error|retryable|unavailable, text: str|None, provider: str, model: str|None, fallback: bool, retry_after_s: float|None); async generate_reply(context: RequestContext, prompt: str, *, deadline: float) -> AIResult. parse_action_draft(raw: str) -> dict validates an allowlisted, inert action schema.

- [ ] Add malformed/unknown draft, failed-domain-command, admission saturation, cancelled request, local-only preference, 429/5xx/auth and declared-fallback tests.
- [ ] Demonstrate string/tuple ambiguity and command-error fallthrough using fake connectors.
- [ ] Adapt connectors and bounded queue/admission, use explicit deadlines/retry policies, keep domain errors out of generic chat fallback, and preserve draft-only actions with confirmation.
- [ ] Run tests/test_ai_outcomes.py, tests/test_action_schema.py, tests/test_message_monitor_routing.py and current-master tests/test_bridge_clients.py; no provider inference.
- [ ] Review and commit; health consumers in I17 use this contract, never assume model listing proves inference.

### Task 15: I15 — Render all console state consistently

**Dependencies:** I20. **PR boundary:** safe renderers and frontend behavior.
**Files:** modify web_console/static/app.js, web_console/dashboard.py, web_console/state_collector.py, web_console/templates/base.html and web_console/static/main.css as required; extend tests/test_console_frontend.py and tests/test_web_console_frontend_security.py.
**Interfaces:** renderSection(sectionName, sectionState) updates visible detail rows and the corresponding modal from the same latest state; state objects retain existing API compatibility.

- [ ] Add browser fixtures changing counts/details, deleting the final event, updating logs/copy output and refreshing an open modal. Assert focus survives and hostile text stays text.
- [ ] Capture the current count/detail mismatch in a deterministic local browser fixture.
- [ ] Implement text-safe renderers, meaningful empty/loading/error states and shared visible/modal snapshots; retain responsive layout and existing accessibility affordances.
- [ ] Run the two listed frontend files separately from async tests; check keyboard focus and narrow viewport with fixtures.
- [ ] Review screenshots/state assertions and commit; no frontend-framework change.

### Task 16: I16 — Endpoint freshness and owned polling timers

**Dependencies:** I20. **PR boundary:** polling lifecycle.
**Files:** modify web_console/static/app.js and web_console/dashboard.py; extend tests/test_console_frontend.py and tests/test_web_console_frontend_security.py.
**Interfaces:** one endpoint entry owns timerId, controller, generation, lastSuccess, status and deadline. stopPolling invalidates the generation, clears timers and aborts requests; an old callback cannot restart a chain.

- [ ] Add repeated hide/show, hung fetch, one failing card, manual retry, auth expiry and wall-clock-jump scenarios; assert one pending chain per endpoint and truthful stale labels.
- [ ] Reproduce retained-timeout behavior with controlled browser timers.
- [ ] Store timer handles, use monotonic elapsed deadlines, publish per-endpoint states and an honest overview, retaining current 5s/10s/30s intervals, backoff and visibility pause.
- [ ] Run the listed frontend tests and fixture request-count assertions; one healthy endpoint cannot refresh another's timestamp.
- [ ] Review and commit; integrate I15 renderers when available.

### Task 17: I21 — Reproducible profiles, typed boundaries, dependency integration

**Dependencies:** I20. **PR boundary:** lock/profiles, then incremental typing; reuse existing dependency PRs instead of duplicating them.
**Files:** modify requirements.txt, requirements-dev.txt, Dockerfile, .github/workflows/ci.yml and build installers; create requirements/prod.lock, requirements/dev.lock, requirements/desktop.lock and requirements/optional-google.lock, requirements/optional-search.lock, requirements/optional-browser.lock, plus docs/DEPENDENCIES.md and tests/test_dependency_profiles.py.
**Interfaces:** a generated hash-locked Python 3.12 graph per supported target/profile; dependency input files remain reviewable. Provider/store/sender Protocol definitions live beside their owning contracts; adapters satisfy them without importing optional libraries until enabled.

- [ ] Add manifest/profile parity and missing-optional-package capability tests; capture resolved graphs in clean target-platform environments.
- [ ] Review all ten existing PRs through the dependency queue below before generating the candidate locks; consult current official compatibility/release documentation during execution.
- [ ] Generate reviewed locks with hashes, update CI/container/desktop consumers, isolate optional integrations and add incremental typing/lint gates on touched boundaries.
- [ ] Verify clean installs and offline tests for supported profiles/platforms; check advisories on actual resolved graphs and record reviewed exceptions. Do not describe packages as vulnerable without evidence.
- [ ] Review and commit the graph; reconcile each existing PR as merged, updated, or superseded with its exact verification receipt once that GitHub action is authorized.

### Task 18: I29 — Maintained school-year data with coverage

**Dependencies:** I20, I32. **PR boundary:** versioned data loader/display, then reviewed current dataset.
**Files:** modify features/school_holidays.py, features/school_holidays_handler.py; create features/data/school_calendars.json and tests/test_school_calendar_coverage.py; update relevant user documentation.
**Interfaces:** get_school_schedule(locality_id: str, school_year: str, today: date) -> SchoolSchedule(coverage verified|partial|unavailable, source_refs: list[str], verified_at: date|None, holidays: list[dict]). Dates and locality IDs come from reviewed authoritative sources.

- [ ] Add audit-date expiry, year rollover, differing localities, invalid ranges, unknown locality and incomplete coverage fixtures.
- [ ] Reproduce the empty upcoming result from the populated 2025–2026 table at 4 October 2026.
- [ ] Build loader/coverage wording, replace unsupported blanket assumptions with reviewed locality records, and add yearly-expiry maintenance checks. Verify each real date/source before committing data.
- [ ] Run tests/test_school_calendar_coverage.py and holiday/routing regressions; unavailable coverage must not read as “no holidays.”
- [ ] Review dataset provenance and commit. Persisted locality preferences integrate after I13; initial explicit selection works without them.

### Task 19: I33 — Poll lifecycle and vote-safe edits

**Dependencies:** I20. **PR boundary:** domain invariant/option identity, then reset preview/history commands.
**Files:** modify features/poll_manager.py, features/polls_handler.py, core/intent_router.py and command metadata when available; extend tests/test_poll_manager_edit_delete.py and tests/test_poll_target.py; create tests/test_poll_lifecycle.py.
**Interfaces:** poll records gain revision and stable option IDs; vote rejects expired/closed at the manager boundary. preview_poll_edit(poll_id: str, changes: dict) -> dict declares preserve_votes or reset_votes; apply requires matching revision and actor.

- [ ] Add exact-expiry/direct-vote, label-only edit, removed-option, stale reset preview, non-owner and closed-results tests.
- [ ] Reproduce the expired-active manager vote and destructive option replacement with fake clocks/data.
- [ ] Enforce expiry in domain logic, retain existing close/ownership behavior, preserve harmless votes, and require confirmation for structural resets; expose closed results through a scoped read command.
- [ ] Run tests/test_poll_lifecycle.py, tests/test_poll_manager_edit_delete.py, tests/test_poll_target.py and routing false-positive tests.
- [ ] Review and commit; no anonymous-voting or completeness guarantee is introduced.

## Wave 3 — Recoverable operations and maintainable surfaces

### Task 20: I08 — Identity-bound mutations and supported undo

**Dependencies:** I04, I05, I07. **PR boundary:** ID/revision previews, then bounded undo.
**Files:** modify cal_system/calendar_manager.py, features/calendar_handler.py; create cal_system/mutation_preview.py and tests/test_calendar_mutation_preview.py; extend tests/test_calendar_edit.py.
**Interfaces:** preview_mutation(actor: RequestContext, scope_id: str, item_ids: list[str], operation: str, expected_revision: int) -> MutationPreview(token: str, revision: int, expires_at: aware datetime, effects: list[dict]); apply_preview(actor, token) reauthorizes current policy and revision. Undo records hold inverse local changes and explicit remote limitations.

- [ ] Add equal-count replacement, duplicate titles, displayed-index reorder, token expiry, actor replay, permission-revoked-after-preview and local/remote undo tests.
- [ ] Reproduce the wrong-set clear confirmation with synthetic equal-count calendars.
- [ ] Display short stable IDs, bind numeric commands to a displayed-list revision, require exact previews for destructive operations and journal supported inverses without promising remote ID preservation.
- [ ] Run tests/test_calendar_mutation_preview.py, tests/test_calendar_edit.py, tests/test_calendar_access_policy.py and routing regressions.
- [ ] Review and commit; undo storage is bounded by configured retention and respects user deletion policy.

### Task 21: I11 — Durable Google intent, retries, and conflicts

**Dependencies:** I01, I04, I05, I09. **PR boundary:** atomic outbox/local intent, worker/reconciliation, then conflict presentation.
**Files:** create cal_system/sync_outbox.py and tests/test_gcal_outbox.py; modify cal_system/calendar_manager.py, cal_system/reminder_manager.py, cal_system/google_calendar_manager.py, features/calendar_handler.py and web_console/state_collector.py.
**Interfaces:** SyncOperation(operation_id: str, item_id: str, local_revision: int, kind create|update|delete, remote_id: str|None, remote_version: str|None, state pending|synced|conflict|failed|unknown, attempts: int, retry_at: aware datetime|None). Enqueue and local mutation share one owner-store commit; async process_due(deadline: float) -> list[SyncOperation] uses a bounded worker.

- [ ] Add crashes before/after remote acceptance, stop after acceptance, failed edit versus remote pull, concurrent remote edit, retry exhaustion and slow-provider event-loop heartbeat tests.
- [ ] Demonstrate remote-first creation and failed-update loss using fake API responses.
- [ ] Persist intent before I/O, carry revisions/version evidence, classify unknown creates for reconciliation, and check current official Google custom-ID/version semantics before selecting an idempotency adapter. Never blindly repeat an ambiguous create; preserve delete_pending compatibility.
- [ ] Run tests/test_gcal_outbox.py, tests/test_calendar_sync.py, tests/test_gcal_reminder_routing.py and mutation-preview tests; measure the synthetic heartbeat budget explicitly.
- [ ] Review and commit slices with crash/restart receipts; conflicts require a displayed reviewed choice, never implicit last-writer-wins.

### Task 22: I13 — Deliberate memory, retention, and provider sharing

**Dependencies:** I04, I05, I07. **PR boundary:** controls/retention, then prompt and transient-context integration.
**Files:** modify memory/user_memory.py, memory/conversation_context.py, features/memory_handler.py and core/message_monitor.py; extend tests/test_user_memory_controls.py and tests/test_conversation_context.py; create tests/test_memory_sharing_policy.py.
**Interfaces:** MemoryPolicy(learning_enabled: bool, topic_retention_days: int|None, allowed_provider_ids: list[str], private_facts_enabled: bool); build_prompt_memory(user_id: str, provider_id: str, scope_id: str) -> dict enforces policy. delete_local_memory(user_id: str, include_transient: bool) -> dict reports affected local surfaces and exclusions.

- [ ] Add opt-out/no-prompt-inclusion, expired topic, idle-channel global pruning, transient self-delete in a shared channel, other-user preservation and backup/remote-deletion wording tests.
- [ ] Pin current self-only access and demonstrate remaining transient context after persistent deletion.
- [ ] Separate deliberately saved facts from temporary topics, expose pause/reset/retention/sharing controls, prune before access and globally, and filter personalization before calling the provider.
- [ ] Run tests/test_memory_sharing_policy.py, tests/test_user_memory_controls.py, tests/test_conversation_context.py and AI dispatch fixtures.
- [ ] Review and commit; make retention defaults explicit without silently deleting legacy facts or claiming remote/backups erased.

### Task 23: I17 — Provider-aware actionable readiness

**Dependencies:** I12, I16. **PR boundary:** health contract and UI.
**Files:** modify web_console/state_collector.py, web_console/dashboard.py, web_console/server.py, core/message_monitor.py; create tests/test_provider_health.py; extend tests/test_console_server.py.
**Interfaces:** subsystem health exposes enabled, required, status ready|degraded|unavailable|stale|disabled, checked_at, reason_code and recovery_action. Provider readiness distinguishes transport/model verification from inference acceptance; public health stays minimal.

- [ ] Add local-only, cloud-only, disabled Google, unreachable optional bridge, stale scheduler and sanitized-error fixtures.
- [ ] Demonstrate optional bridge presentation confusion without calling any provider.
- [ ] Consume configured provider contracts, add scheduler/store/sync status, and show recovery instructions only for relevant failures; authenticate detailed diagnostics.
- [ ] Run tests/test_provider_health.py, tests/test_console_server.py and frontend fixture checks; prove model-list success cannot assert inference ready.
- [ ] Review and commit; no recurring billable inference probes.

### Task 24: I18 — Bounded logs and useful diagnostics

**Dependencies:** I04, I15. **PR boundary:** retention/read path, then diagnostic UI.
**Files:** modify web_console/console_store.py, web_console/server.py, web_console/static/app.js, utils/logger.py; create tests/test_console_log_retention.py; extend frontend/security tests.
**Interfaces:** read_log_page(cursor: str|None, max_bytes: int, filters: dict) -> dict returns records/next_cursor/truncated. Records carry timestamp, level, component, request_id and outcome; prompt/member content is excluded by default.

- [ ] Add large-file bounded-read byte accounting, rotation boundaries, malformed rows, filtered pagination, pause-follow and redaction-before-persistence tests.
- [ ] Reproduce whole-file readlines tail cost with generated logs and count bytes actually read.
- [ ] Implement configured byte/age limits and reverse/cursor tail reads, keeping audit retention separate; add text-safe filters/copy/download with private access.
- [ ] Run tests/test_console_log_retention.py, tests/test_logger_hardening.py and affected frontend tests.
- [ ] Review measured I/O receipts and commit; never describe existing rotating application logs as universally unbounded.

### Task 25: I19 — Typed command catalogue and non-dispatch routing preview

**Dependencies:** I07, I12. **PR boundary:** metadata/consumers, then preview.
**Files:** create core/command_registry.py and tests/test_command_registry.py; modify core/message_monitor.py, core/intent_router.py, features/help_handler.py, web_console/dashboard.py and command documentation.
**Interfaces:** CommandSpec(intent: str, aliases: tuple[str,...], examples: tuple[str,...], mutation_kind: str, scope_rule: str, handler_name: str, payload_validator: Callable); preview_route(text: str, actor: RequestContext) -> dict returns intent/confidence/reason/validated fields/required policy without dispatch.

- [ ] Add every-intent-one-handler, help/reference parity, payload rejection, preview-no-provider/no-write and existing false-positive corpus tests.
- [ ] Pin existing route precedence and thresholds before switching consumers.
- [ ] Extend the small registry, generate all command references and route preview through existing IntentRouter; do not add a competing parser.
- [ ] Run tests/test_command_registry.py, tests/test_intent_router.py, tests/test_confidence_thresholds.py, tests/test_false_positives.py and tests/test_message_monitor_routing.py.
- [ ] Review and commit; new commands in later tasks must extend this same catalogue and its positive/negative fixtures.

### Task 26: I22 — One release owner and artifact proof

**Dependencies:** I20, I21. **PR boundary:** workflow/ref ownership, then cross-platform bundle smoke/metadata.
**Files:** modify .github/workflows/release.yml, .github/workflows/build-desktop-apps.yml, mac_app/build.py, build.sh, windows_app/build.py, scripts/write_version.py and docs/RELEASE.md; create tests/test_release_contract.py and scripts/smoke_release_artifact.py.
**Interfaces:** release manifest contains full_commit_sha, tag, version, target/platform, lock digest, artifact checksum and smoke receipt. One publisher depends on all required build/CI jobs and resolves the selected tag/ref before build.

- [ ] Add workflow ownership/ref tests, manual-version mismatch refusal, required-asset manifest checks and frozen-entrypoint no-network smoke assertions.
- [ ] Demonstrate publisher overlap and divergent asset manifests from source; do not claim a binary failure until built.
- [ ] Consolidate publisher, align scripts/web-console asset packaging and derive version/OS metadata from one release definition; create checksums/manifests.
- [ ] Run tests/test_release_contract.py, tests/test_desktop_launcher_paths.py, tests/test_write_version.py; build/test artifacts on actual supported macOS/Windows targets in nonpublishing CI.
- [ ] Review artifacts and commit; signing/notarization is a separate credential/distribution decision and never implied by ad hoc signing.

### Task 27: I24 — Owned resource shutdown and final counters

**Dependencies:** I04, I05, I27. **PR boundary:** close/flush contract and composition adoption.
**Files:** modify core/message_monitor.py, core/selfbot_runner.py, features/crypto_manager.py, features/aurora_forecast.py, features/search_manager.py, features/forecast_service.py and web_console/console_store.py; create tests/test_resource_shutdown.py.
**Interfaces:** every owned manager with resources supplies async close() -> None; MessageMonitor.close(deadline: float) idempotently cancels/awaits owned work and flushes each remaining counter delta once. Shared resources stay with their owner.

- [ ] Add partial-startup/repeated-close/cancel-during-flush/final-delta tests with fake sessions, tasks and thread workers; assert no orphaned owned resource and retained failed-flush evidence.
- [ ] Demonstrate missing manager close coverage, preserving already merged partial-readiness regressions.
- [ ] Register only actual owned resources, close in reverse dependency order within a monotonic deadline, and preserve unsaved deltas if bounded flush fails.
- [ ] Run tests/test_resource_shutdown.py, tests/test_ready_initialization.py from master, tests/test_forecast_validity.py and console stats regressions.
- [ ] Review and commit; do not duplicate task tracking, reconnect, or readiness fixes already on master.

### Task 28: I30 — Bounded cited research with optional extraction

**Dependencies:** I12, I19. **PR boundary:** evidence cards/deadlines, then optional public text extraction.
**Files:** modify features/search_manager.py, features/browser_manager.py, core/message_monitor.py and ai prompt construction; extend tests/test_search_manager.py and tests/test_search_intent.py; create tests/test_public_page_extraction.py.
**Interfaces:** ResearchCard(url: str, title: str, content_kind url_only|snippet|extracted, published_at: str|None, fetched_at: aware datetime, source: str, text: str|None); async research(query: str, *, deadline: float) -> dict exposes cards/partial_failures. External evidence is inert data, never an action instruction.

- [ ] Add hung fallback/worker saturation, URL-only-not-read, claim-to-source citation, malicious evidence and extract redirect/private-address/type/byte-limit fixtures.
- [ ] Reproduce a multi-fallback unbounded-duration path with fake providers; retain existing normalization and honest browser stub.
- [ ] Implement total/underlying network deadlines and bounded workers first. Only then choose a reviewed public extractor; validate each redirect/resolved destination and close sessions on cancellation.
- [ ] Run tests/test_search_manager.py, tests/test_search_intent.py, tests/test_public_page_extraction.py and action-schema tests; timeout tests account for executor threads still running.
- [ ] Review and commit slices; extraction has no credentialed browsing, paywall bypass or arbitrary automation.

## Wave 4 — Everyday use and recovery

### Task 29: I14 — Complete self-only private memory exports

**Dependencies:** I03, I13, I19. **PR boundary:** export artifact and explicit private delivery.
**Files:** modify features/memory_handler.py, memory/user_memory.py, core/outbound_sender.py and core/command_registry.py; extend tests/test_user_memory_controls.py; create tests/test_memory_export_delivery.py.
**Interfaces:** export_user_memory retains self-only access and returns a complete snapshot. Extend sender with keyword attachments: tuple[Attachment,...]=(); Attachment(filename: str, content_type: str, data: bytes). First version delivers a bounded JSON attachment in an already private invocation or explicitly requested private DM, using the sender's DeliveryResult.

- [ ] Add exports exceeding 1,800 characters, byte-limit refusal, cross-user refusal, unavailable private destination and failed-delivery tests; parse the bytes and compare them to the exact exported snapshot.
- [ ] Reproduce current truncation without printing personal data.
- [ ] Replace truncated code blocks with complete artifacts and metadata; group requests get safe instructions/explicit private choice, never a silent public fallback. Check actual current transport attachment limits before setting the configured limit.
- [ ] Run tests/test_memory_export_delivery.py, tests/test_user_memory_controls.py and outbound quota/delivery tests.
- [ ] Review and commit; authenticated downloads can follow separately, with their own ownership/expiry contract.

### Task 30: I25 — Opt-in notification preferences and digest cards

**Dependencies:** I03, I07, I09, I13. **PR boundary:** stored preferences/snooze, then shared digest formatting.
**Files:** modify cal_system/reminder_checker.py, features/reminder_handler.py, features/daily_digest_manager.py, features/daily_digest_handler.py, memory/user_memory.py and core/command_registry.py; create tests/test_notification_preferences.py.
**Interfaces:** NotificationProfile(enabled: bool, scope_id: str, destination_id: str|None, lead_minutes: list[int], quiet_start: time|None, quiet_end: time|None, morning_time: time|None, timezone: str, card_ids: list[str]); next_delivery(profile, event_time, clock) -> aware datetime|None. Snoozes persist item/occurrence identity and due instant.

- [ ] Add quiet hours crossing midnight/DST, snooze/restart, opt-out, absent destination, selected-card provider failure and wall-clock-jump fixtures.
- [ ] Pin legacy notification stages as explicit compatibility behavior; identify misleading post-start “finished” wording.
- [ ] Add opt-in controls without expanding recipients, persist snooze/preference state, share requested/proactive digest cards with provenance/degraded output, and use actual end semantics for finished messages.
- [ ] Run tests/test_notification_preferences.py, outbound delivery, calendar time and memory-policy tests; assert only selected recipients/cards are considered.
- [ ] Review and commit slices; end-user preference acceptance remains a stated manual gate.

### Task 31: I10 — Series, occurrences, and recurring delivery identities

**Dependencies:** I03, I09, I11. **PR boundary:** local model/migration, mutation commands, then Google occurrence/exceptions.
**Files:** create cal_system/recurrence.py and tests/test_recurring_occurrences.py; modify cal_system/calendar_manager.py, cal_system/google_calendar_manager.py, cal_system/reminder_manager.py, cal_system/reminder_checker.py and features/calendar_handler.py.
**Interfaces:** Series(series_id: str, anchor_time: EventTime, rule: dict, end_count: int|None, end_date: date|None); Occurrence(occurrence_id: str, series_id: str, original_start: aware datetime, state planned|completed|skipped, override: dict|None). Delivery keys include occurrence ID and stage. Mutation scope is this|future|series.

- [ ] Add month-end anchor/no-drift, leap day, skipped/moved/completed occurrence, end rules, restart delivery deduplication, imported exception and unsupported-rule fixtures.
- [ ] Record old recurrence advancement/collapse as migration fixtures rather than silently interpreting them as a complete series.
- [ ] Preserve supported recurrence types, migrate old items with backups, introduce stable occurrence identities and explicit edit scopes, and retain unsupported imported rules readably without flattening.
- [ ] Run tests/test_recurring_occurrences.py, tests/test_calendar_sync.py, tests/test_reminder_crud.py, calendar time and outbox tests.
- [ ] Review and commit slices; current official Google recurrence/exception contracts and approved test-calendar round trips are gates for remote acceptance.

### Task 32: I23 — Supported deployment profiles and compatible rollback

**Dependencies:** I04, I17, I21, I22. **PR boundary:** deployment contract/static checks, then profile-specific recovery.
**Files:** modify Dockerfile, docker-compose.yml, deploy/ansible-playbook.yml, scripts/deploy/inebotten-update and relevant webhook/update helpers; update docs/VPS_DEPLOYMENT.md; extend tests/test_deploy_hardening.py and test_deploy_scripts.py.
**Interfaces:** deployment manifest binds full code revision, image digest, config schema and data schema range; preflight rejects dirty source, unavailable storage/ports, incompatible schemas and missing rollback evidence. Readiness requires correct full revision and required subsystem health.

- [ ] Add fake dirty checkout/occupied port/unhealthy or stale image/source-sync failure and test_older_code_refuses_newer_store scenarios; simulate rollback without personal data.
- [ ] Inventory supported profiles before deprecating a script; current service/deploy choice is not inferred from repository definitions.
- [ ] Align Ansible/container/legacy checks, add supported HEALTHCHECK behavior, preserve tagged rollback code plus compatible data, and distinguish code rollback from an explicitly reviewed data restore.
- [ ] Run deploy tests, shell/YAML/container static validation and a disposable local rollback rehearsal; exact-head CI gates publication. Before I35 exists, rehearsals use quiescent fixture copies with checksum receipts. Actual multi-store data migrations wait for I35's consistent backup/restore gate.
- [ ] Review and commit; a live deployment is a later explicit action with fresh backup health, current port inventory, live revision/UI proof and an unchanged-data compatibility check.

### Task 33: I31 — Safe desktop UI and child-process lifecycle

**Dependencies:** I17, I32, I22. **PR boundary:** shared process controller, then Tk adapters/layout.
**Files:** create utils/launcher_runtime.py and tests/test_desktop_lifecycle.py; modify mac_app/launcher.py, windows_app/launcher.py; extend tests/test_desktop_launcher_paths.py.
**Interfaces:** LauncherController.start(command: list[str]) -> None enqueues startup of one owned child/process group; stop(deadline: float) -> None enqueues a worker shutdown request and returns without blocking Tk. The worker waits for owned exit and produces starting|connecting|ready|degraded|stopping|exited and log events through a bounded queue. Tk main-loop drain is the only widget writer.

- [ ] Add rapid double-start, early exit, blocked output, ignored terminate, close during start, child descendants and log saturation fixtures; record thread IDs for every widget call.
- [ ] Reproduce worker-thread writes and process-alive/ready conflation with fake Popen and readiness providers.
- [ ] Use a bounded queue/main-thread updates, show health-derived connection state, await graceful shutdown then bounded owned-group escalation, and make settings/logs resize with usable keyboard focus.
- [ ] Run lifecycle/path tests, frozen artifact smokes and actual macOS/Windows keyboard/scaling/window-close scenarios in platform checks.
- [ ] Review and commit; do not terminate an unrelated launchd/service process or mistake launcher exit for bot shutdown.

### Task 34: I35 — Consistent data backup and staged restore

**Dependencies:** I04, I05, I13. **PR boundary:** snapshot bundle, validate/preview, then explicit restore.
**Files:** create utils/backup_bundle.py, scripts/inebotten_backup.py, tests/test_backup_restore_bundle.py and docs/BACKUP_RESTORE.md; modify store ownership registration only where required.
**Interfaces:** create_bundle(store_registry, destination: Path) -> manifest; validate_bundle(archive: Path, staging_dir: Path) -> RestorePreview(schema_versions: dict, checksums: dict, generation: str, destination: str, warnings: list[str]); restore(preview, expected_destination: Path) only while services are quiescent and destination ownership/revision is rechecked.

- [ ] Add concurrent related-store updates, tampered/truncated archives, traversal, symlink/hardlink, concurrent destination creation, newer-schema-on-old-code and credential/session exclusion tests.
- [ ] Demonstrate mixed-generation copying with synthetic stores.
- [ ] Freeze owned writes briefly under a deterministic lock order, snapshot a single generation, create private data-only allowlisted manifests, validate into an exclusively created staging directory, and preserve the previous destination before any explicit replacement.
- [ ] Run tests/test_backup_restore_bundle.py, storage concurrency/outcome and memory-policy tests; rehearse restore/rollback using generated data and verify every reference/checksum.
- [ ] Review and commit; calendar/memory bundles are private, secrets/raw logs/exports are excluded by default, and no offsite/upload provider is selected.

### Task 35: I36 — Previewed ICS exchange

**Dependencies:** I07, I08, I09, I10. **PR boundary:** export, then import preview/apply; a non-recurring slice may precede I10 explicitly.
**Files:** create cal_system/calendar_exchange.py and tests/test_ics_exchange.py; modify features/calendar_handler.py, core/command_registry.py and documented exchange commands.
**Interfaces:** export_ics(actor: RequestContext, scope_id: str, item_ids: list[str]) -> bytes; preview_ics(actor, scope_id, data: bytes) -> dict lists new/changed/duplicate/unsupported items; apply uses I08-style revision/actor-bound confirmation. Stable UID/source mapping makes re-import idempotent.

- [ ] Add timezone/all-day/duration/Unicode/supported recurrence round trips, duplicate import, unsupported RRULE, bounded malformed input, stale preview and unauthorized scope fixtures.
- [ ] Select a maintained parser only after current official/library API and dependency review; record the supported subset before coding.
- [ ] Implement bounded export/import preview, preserve UIDs and source mapping, reject or visibly skip unsupported entries, and keep task/reminder kinds distinct.
- [ ] Run tests/test_ics_exchange.py, calendar access/time/recurrence and mutation-preview tests; import/export fixtures through two selected calendar clients and record versions/results.
- [ ] Review and commit; no URL subscriptions or automatic imports.

## Wave 5 — Deliberate product expansion

### Task 36: I26 — Authenticated agenda-first calendar workspace

**Dependencies:** I05, I07, I08, I09, I11, I15, I16, I19. **PR boundary:** scoped agenda/details, then previewed CRUD/conflicts; defer drag/drop.
**Files:** modify web_console/server.py, web_console/state_collector.py, web_console/dashboard.py, web_console/static/app.js, web_console/static/main.css and web_console/templates/base.html; create tests/test_console_calendar_workspace.py; extend browser/security tests.
**Interfaces:** authenticated GET /api/calendar/items lists authorized scope/revision; POST /api/calendar/preview validates typed changes and returns I08 MutationPreview; POST /api/calendar/apply reauthorizes actor/scope and validates token/revision/origin/CSRF. Browser-session-to-domain-actor mapping is explicit, never inferred from an arbitrary submitted user ID.

- [ ] Add forged actor/scope, cross-origin/CSRF, revoked-after-preview, stale revision, duplicate submission, conflict resolution, final-item empty state and keyboard/narrow-screen browser fixtures.
- [ ] Define console actor ownership/permissions and write methods before exposing any mutation endpoint; preserve demo as nonmutating.
- [ ] Implement agenda/week summaries and safe detail/forms, reuse domain policy/preview/sync contracts, show pending/conflict state and explicit loading/error/success, and retain focus.
- [ ] Run tests/test_console_calendar_workspace.py, tests/test_console_server.py, tests/test_web_console_frontend_security.py, tests/test_console_frontend.py and domain fixtures; manually verify keyboard and mobile-size scenarios.
- [ ] Review and commit read then write slices; no cookie-authenticated write ships without origin/CSRF and policy tests.

### Task 37: I34 — Organizer-confirmed group planning and RSVP

**Dependencies:** I03, I07, I08, I09, I33, I19. **PR boundary:** planning state/poll linkage, then finalization and scoped RSVP.
**Files:** create features/planning_manager.py, features/planning_handler.py and tests/test_group_planning.py; modify core/command_registry.py, core/intent_router.py and monitor handler composition.
**Interfaces:** PlanningSession(session_id: str, scope_id: str, organizer_id: str, poll_id: str, state draft|voting|review|finalized|cancelled, event_id: str|None, revision: int); finalize(actor: RequestContext, session_id: str, preview_token: str) -> str returns one stable event ID. RSVPs are scoped records with explicit visibility.

- [ ] Add tie/zero-vote/expired poll, unauthorized organizer, duplicate finalize/restart, post-finalize poll change and private RSVP visibility fixtures.
- [ ] Build a scripted synthetic scenario from candidates through organizer review; no majority automatically schedules.
- [ ] Compose existing poll/calendar/watchlist primitives, reuse mutation preview, store source/event identity atomically and require explicit notification recipient approval.
- [ ] Run tests/test_group_planning.py plus access/preview/time/poll/delivery tests and positive/negative routing cases.
- [ ] Review and commit; one activity/selected time only, no private-calendar access, unsolicited invitations, or booking.

### Task 38: I37 — Supported bot transport feasibility and adapter

**Dependencies:** I07, I19, I20, I21, I03. **PR boundary:** documented feasibility/capabilities, then optional runtime adapter if feasible.
**Files:** create docs/BOT_TRANSPORT_FEASIBILITY.md, core/transport.py, core/bot_runner.py, requirements-bot.txt, requirements/bot.lock and tests/test_transport_contract.py; modify handler input adaptation and configuration only after feasibility.
**Interfaces:** Transport.capabilities() -> frozenset[str]; async send_message(channel_id: str, text: str, attachments: tuple, deadline: float) -> dict exposes receipt evidence consumed by I03. Normalize inbound transport events into RequestContext and supported domain payloads; adapters do not bypass authorization or the sender.

- [ ] Inspect current official Discord policy/API and supported-library documentation; produce a capability/permission matrix for mentions, interactions, calendar, reminders, polls, controller endpoints and account-only features.
- [ ] Resolve the shared discord import namespace between bot/self libraries through separate dependency environments/entrypoints; do not install competing clients into one runtime.
- [ ] If feasible, add the bot-token adapter for the documented assistant subset and reject unsupported operations/token-mode confusion. If unsuitable, record the evidence and explicit deferred/declined disposition.
- [ ] Run tests/test_transport_contract.py and shared handler/domain fixtures in both profiles; use an explicitly approved test bot/guild for installation/permissions/commands before live acceptance.
- [ ] Review and commit stages; no private-DM access, account migration, endpoint emulation or evasion. Existing user-account mode and local controller remain separate.

### Task 39: I38 — Allowlisted opt-in workflow recipes

**Dependencies:** I03, I07, I08, I12, I25, I19. **PR boundary:** deterministic dry-run recipes, then approved durable execution/history.
**Files:** create features/workflow_manager.py, features/workflow_handler.py and tests/test_workflow_recipes.py; modify core/command_registry.py and domain receipt publication.
**Interfaces:** WorkflowRecipe(recipe_id: str, owner_id: str, scope_id: str, trigger_kind: str, template_id: str, enabled: bool, action_budget: int); preview_recipe(actor, recipe_id, trigger_receipt) -> MutationPreview; execute_confirmed(preview_token) -> dict stores execution ID, effects and delivery outcomes. Triggers come from trusted domain receipts, not model/content instructions.

- [ ] Add replay/restart, denied/paused/exhausted budget, stale preview, duplicate side effect, bounded retry and malicious retrieved-content fixtures.
- [ ] Start with confirmed event → preparation-task draft and due tasks → opted-in digest card; declare exact allowed templates/effects in the registry.
- [ ] Implement dry-run/enable/pause/history, durable idempotent execution identities, inherited domain policy and reviewed effects. AI output can propose a validated draft but cannot execute a recipe.
- [ ] Run tests/test_workflow_recipes.py, access/preview/action-schema/notification/delivery fixtures and routing false positives.
- [ ] Review and commit; no shell/Python plugins, arbitrary webhooks, broad message surveillance or expanded subscriptions.

## Existing dependency PRs — explicit disposition queue

GitHub was refreshed during planning: **zero open or closed issues, ten open dependency PRs**. The proposal IDs are local planning IDs, not issue numbers. No proposal issues or implementation PRs are created by this plan. Refresh the PR head and status before review; previous green CI is not evidence for a changed head.

The owner is Codex. Review each dependency change separately in a safe worktree/profile, consult current primary release/compatibility documentation, and record one outcome: accepted into the verified lock, needs revision, or superseded by a linked verified lock PR. Merging/closing/commenting publicly is a later authorized action. Never close a PR simply because its package appears in a candidate lock.

| PR | Requested change | Required verification before disposition |
| --- | --- | --- |
| [#12](https://github.com/Reedtrullz/inebotten-discord/pull/12) | Bandit ≥1.7.0 → ≥1.9.4 | Resolve in dev graph and replay the prior audit's scoped Bandit command on generated/config-safe source context; compare results and distinguish scanner/config changes from application findings. Bandit is not assumed to be an existing required CI job; adding one is reviewed under I21. |
| [#13](https://github.com/Reedtrullz/inebotten-discord/pull/13) | googlesearch-python ≥1.2.0 → ≥1.3.0 | Verify iterator/result API, timeout configuration and URL-only normalization through fake provider tests in I30; clean optional-search install. |
| [#14](https://github.com/Reedtrullz/inebotten-discord/pull/14) | duckduckgo-search ≥6.0.0 → ≥8.1.1 | Verify imported DDGS API, executor behavior/resource closure, error paths and result schema; check current support status and compatibility before accepting the graph. |
| [#15](https://github.com/Reedtrullz/inebotten-discord/pull/15) | aiohttp ≥3.14.0 → ≥3.14.1 | Exercise bridge auth/limits/timeouts, local/cloud client mocks, forecast and console clients, cancellation and shutdown; lock-compatible target builds. |
| [#16](https://github.com/Reedtrullz/inebotten-discord/pull/16) | tavily-python ≥0.3.0 → ≥0.7.26 | Verify TavilyClient.search inputs/raw-content schema, timeout support and error handling against fixtures; optional-search import/lock and I30 budgets. |
| [#17](https://github.com/Reedtrullz/inebotten-discord/pull/17) | pylint ≥2.17.0 → ≥4.0.6 | Resolve Python 3.12 dev graph and compare scoped diagnostics under an explicitly recorded invocation. Current CI's lint gate is flake8; do not invent an existing Pylint gate. Review any new configuration under I21 and avoid unrelated mass formatting. |
| [#18](https://github.com/Reedtrullz/inebotten-discord/pull/18) | pytest ≥9.0.3 → ≥9.1.1 | Verify pytest-asyncio/Playwright plugin graph, child-environment isolation, collection markers and split browser/async suite; record real skips. |
| [#19](https://github.com/Reedtrullz/inebotten-discord/pull/19) | requests ≥2.31.0 → ≥2.34.2 | Check all direct/transitive consumers and target graph; exercise mocked search/Google HTTP timeout/auth/error contracts with external network blocked. |
| [#20](https://github.com/Reedtrullz/inebotten-discord/pull/20) | google-auth-oauthlib ≥1.0.0 → ≥1.4.0 | Run OAuth requester/channel binding, callback/token serialization/private permission fixtures; clean optional-Google install with no real OAuth/token access. |
| [#21](https://github.com/Reedtrullz/inebotten-discord/pull/21) | simpleeval ≥0.9.0 → ≥1.0.7 | Verify allowed math syntax, rejected calls/attributes, resource/large-expression behavior and preserved unit/currency routing. Add focused calculator fixtures, not arbitrary user-code execution. |

For each PR, the future receipt records refreshed full head SHA, resolved package version/graph digest, affected test results, advisory/compatibility review, exact-head CI and final merge/revision/supersession link. The lower-bound bump is not itself a reproducible lock. I21 owns consolidation after compatible updates are understood; no all-at-once unreviewed dependency merge.

## Decisions, rollout, and completion

| Decision | Planned default / evidence needed | Owner and timing |
| --- | --- | --- |
| Legacy calendar migration | Preserve current shared scope; preview explicit private/group migration and inverse before changing data. | Codex prepares fixtures/UI; user selects actual migration at I07/I09 acceptance. |
| Member exporter | Preserve local-only commit; implement I39 only if deliberately retained, otherwise record deprecation without deletion. | User disposition before I39 publication. |
| School calendar data | Reviewed authoritative locality/year sources; unavailable means unavailable. | Codex researches/verifies at I29; no invented dates. |
| FX/geocoder/extractor vendor | Use honest current/demo/unavailable behavior first; no new paid integration by default. | Codex presents a bounded adapter choice only if needed for I27/I28/I30 expansion. |
| Notification/retention defaults | Preserve legacy behavior where documented; new recipes/subscriptions opt-in; no silent legacy memory erasure. | Codex proposes explicit settings; user confirms changes affecting personal state. |
| Deployment profile/signing | Inventory actual supported usage; validate artifacts first. | User chooses deployment/distribution action after I22/I23 reviewable evidence. |
| Bot transport | Capability/dependency feasibility precedes adapter; unsupported user-only features remain explicitly unavailable. | Codex feasibility at I37; user approves test bot/guild access if wanted. |

I will prepare all code, fixture migrations, tests, docs and receipts necessary for a reviewable result before requesting any required external action. Routine implementation choices follow the recorded contracts. Missing secrets/accounts, actual data migration, public issue publication, merge/deploy and private/live checks are explicit acceptance boundaries; they do not prevent independent offline work.

**Rollout strategy:** ship safety fixes independently; keep compatibility readers/wrappers until all consumers move; introduce schema versions and recoverable fixtures before writers change; stage new scopes/features disabled or explicit opt-in; verify artifacts and full revision before deployment; preserve rollback code and understand data compatibility. Never restore old data merely to make old code start.

**Issue lifecycle if later authorized:** refresh open/closed issues and PRs, publish each approved proposal with its complete spec and dependency links, attach implementation PRs, and close only when that issue's acceptance is satisfied. Unmet manual/live gates stay visible. No issue is silently dropped because it is large, optional, or absent from GitHub today.

**First concrete execution batch:** baseline refresh/worktree → I20 → I01 → I02. Then I04 storage outcome slices. I will use native parent execution by default and request independent review only where it improves migration/concurrency/security confidence under the user's approved routing policy.

## Plan verification and current status

- All I01–I39 are mapped to a task, files, planned interfaces, tests, PR boundary, dependencies and review/commit gate.
- The ten dependency PRs each have a specific compatibility/test/disposition path.
- Document checks verify all 39 unique task IDs, five future steps per task, required task fields, complete sequence coverage, acyclic prerequisites and prerequisite order, and all ten PR links. These are planning checks, not application tests.
- Every checkbox is future work. There are no code/test/install/build/deploy results from this planning turn.
- The original portfolio and working files remain unchanged. Only this execution-plan document and the authorized Obsidian planning log are produced.

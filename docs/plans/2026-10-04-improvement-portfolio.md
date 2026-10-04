# Inebotten — improvement discovery and future PR portfolio

**Status: Proposed future PRs — concept/design only. Not implemented.**

Reviewed 4 October 2026, Europe/Oslo. Source baseline: `6a0e861eafb457fad38428da8edffc6f0fc2b1bf`, branch `audit/preserve-control-hardening-2026-08-23`. This is the preserved local checkout, not a claim about GitHub default-branch or deployed behavior. Existing changes to `AGENTS.md`, `ARCHIVED.md`, `README.md`, untracked `CURRENT_STATE.md`, and `.artifacts/` are outside this work.

## Assessment and direction

Inebotten is a Norwegian personal and small-group assistant built around Discord mentions. A Python gateway client authorizes messages, an intent router selects handlers, managers maintain calendar/reminder/social data, and local or cloud AI handles conversation. Google Calendar bridges personal planning; a custom asyncio HTTP console supplies operational visibility; CLI and Tk launchers provide alternative control surfaces. JSON files are the persistence layer.

Its strengths are substantial: manager/handler separation, unusually broad Norwegian language coverage, conservative intent thresholds, mention gating, explicit whole-calendar confirmation, AI calendar drafts rather than automatic writes, atomic JSON replacement, hashed console sessions, bounded HTTP parsing, background-task tracking, reconnect initialization guards, non-root Docker, and a controller with identity/target/write safeguards and freshness envelopes. Preserve these strengths.

The largest opportunity is to make the assistant trustworthy end to end: a saved item must actually be durable; an unavailable remote event must not mean deleted; a sent notification must have delivery evidence; an unavailable forecast must remain unavailable; the console must show current, provider-specific state. Then extend deliberate sharing, notification control, calendar interoperability, and supported transport options.

Three plausible approaches were considered. A broad rewrite would disrupt working safeguards and require migration proof before providing user value. Adding features alone would amplify ambiguous state and storage ownership. **Recommended: focused reliability PRs, then product workflows, then optional architecture and stretch work.** Keep JSON initially; do not prescribe a database migration without measured need.

## Evidence and verification rules

- **Confirmed source behavior:** directly inspected code. This does not mean an observed production incident.
- **Reproduced:** isolated AST-extracted methods with synthetic in-memory collaborators; no application modules imported, accounts accessed, or application processes started.
- **Architectural risk:** a plausible consequence of inspected control flow, not a measured failure.
- **Product idea / stretch:** proposed capability, not a claim of broken current behavior.
- `P1` = protect data, delivery, privacy, or operational truth; `P2` = normal roadmap work; `P3` = optional expansion. These are portfolio priorities, not exploit severity ratings.
- Size `S/M/L` is relative scope, not an estimated delivery promise. Dependencies are prerequisites unless explicitly marked soft. Every proposal needs its stated acceptance checks before completion.

Synthetic probes performed during discovery:

1. `_remove_missing_gcal_items`: a missing-from-list item in the sync window is removed when `get_event` returns `None`.
2. The same method removes the item when its synthetic lookup raises `TimeoutError`.
3. `_send_item_reminder`: no destination still calls `_mark_sent` and increments `now_sent`.
4. `PollManager.vote`: an expired poll with `status='active'` accepts a direct manager vote; the current handler separately filters active polls. This proves a manager invariant gap, not an ordinary handler bypass.

The project test suite, browser UI, Discord, Google Calendar, model providers, desktop binaries, launchd service, VPS, builds, and deployments were not run. No latency, throughput, accessibility compliance, provider pricing, or production health is certified here.

## Phase A — Data and delivery foundations

### I01 — Preserve local events when Google lookup is inconclusive

**Classification:** Near-term · Reliability · P1 · S. **Evidence:** `cal_system/calendar_manager.py:807-845`; `cal_system/google_calendar_manager.py:383-408`; `tests/test_calendar_sync.py:178-212`. Reproduced by probes 1–2. The API wrapper returns `None` for errors; reconciliation removes an absent item unless a live non-cancelled event is returned.

**Problem:** Not-found, cancellation, permission failure, and timeout do not have distinct outcomes at the deletion boundary.

**Proposed PR:** Introduce explicit lookup outcomes; remove only after authoritative deletion/cancellation evidence. Keep uncertain items with sync warnings and a retry timestamp.

**Scope boundaries:** One lookup/reconciliation contract; keep existing pagination and recurring-ID deduplication. No new full sync engine.

**Acceptance target:** Fake 403/429/5xx, timeout, malformed response, and unavailable lookup preserve items; explicit confirmed missing/cancelled removes them; tests cover mixed successful/uncertain batches. No live account needed.

**Dependencies:** None.

### I02 — Share the live reminder manager with the scheduler

**Classification:** Near-term · Reliability · P1 · S. **Evidence:** `core/message_monitor.py:169-170,1346-1362`; `features/reminder_handler.py:32-34`; `cal_system/reminder_manager.py:21-38`. Handlers use `monitor.reminders`; the checker gets a separately loaded `ReminderManager`.

**Problem:** Newly created, edited, or completed reminders can diverge from the scheduler's in-memory view until restart.

**Proposed PR:** Inject the same reminder manager into handlers and checker. Make ownership explicit in startup composition.

**Scope boundaries:** Correct this wiring without unifying all calendar/reminder schemas.

**Acceptance target:** With a synthetic client, create/edit/complete/delete after scheduler initialization changes its next scan immediately; reconnect retains one manager and checker. Verify no second load is needed.

**Dependencies:** None.

### I03 — Record notification delivery only after a successful bounded send

**Classification:** Near-term · Reliability/Security · P1 · M. **Evidence:** `cal_system/reminder_checker.py:390-501`; `features/base_handler.py:63-101`; `core/rate_limiter.py:38-128`. Probe 3 confirms false sent accounting. The checker also calls `channel.send` directly instead of the handler send guard.

**Problem:** Missing destinations and caught send errors are recorded as sent. Concurrent senders can each pass the limiter before an awaited send records its slot.

**Proposed PR:** Add a shared outbound sender returning delivered/dropped/retryable/forbidden outcomes and the message ID. Reserve rate-limit capacity atomically, enforce the existing limits for proactive sends, and mark scheduler delivery only on success.

**Scope boundaries:** No higher quotas, unsolicited recipients, mass sends, or promise of exactly-once delivery across a crash after remote acceptance. Document that ambiguity explicitly.

**Acceptance target:** Missing channel, forbidden, quota refusal, timeout, and 429 never count as delivered; bounded retries honor server delay; simultaneous synthetic sends stay within configured capacity; all send paths use the contract.

**Dependencies:** I02 for reminder integration.

### I04 — Fail visibly on persistence corruption and save failure

**Classification:** Foundation · Reliability · P1 · M. **Evidence:** `utils/json_storage.py:25-34`; `cal_system/calendar_manager.py:135-159,198-200`; `memory/user_memory.py:33-53`. Invalid loads fall back to empty structures; some failed saves are printed and suppressed while mutations return success.

**Problem:** An empty fallback can later overwrite recoverable data, and a successful-looking response can describe an undurable change.

**Proposed PR:** Distinguish missing/valid/corrupt storage; preserve corrupt files, enter a visible read-only degraded state, and propagate durable-save results to handlers. Add schema versions and validation for touched stores.

**Scope boundaries:** JSON remains the store. No automatic destructive repair or reading private stores during implementation tests.

**Acceptance target:** Corrupt and wrong-shape fixtures remain byte-preserved; simulated permission/disk-write failures produce failure feedback; recovery requires a valid replacement or explicit restore; valid legacy data migrates with a backup.

**Dependencies:** None.

### I05 — Serialize JSON mutations and persist immutable snapshots

**Classification:** Foundation · Architecture/Reliability · P1 · M. **Evidence:** `utils/json_storage.py:37-59`; `memory/user_memory.py:48-51`; `cal_system/calendar_manager.py:150-157`; `web_console/console_store.py:82-102`. Atomic replacement does not serialize read/modify/write; some worker-thread writes consume live mutable dictionaries. The console stats write lock starts after its read/merge.

**Problem:** Stale writers or concurrent dictionary changes can lose updates. This is an architectural risk; no workload loss was measured.

**Proposed PR:** Establish one writer per store, lock the full mutation/snapshot/commit sequence, and document whether concurrent processes are rejected or coordinated. Move blocking file commits off the event loop under this contract.

**Scope boundaries:** No blanket async conversion or SQLite rewrite; retain existing file formats until I04 migration rules permit changes.

**Acceptance target:** Barrier-controlled competing updates preserve both changes; interrupted writes leave valid old/new JSON; readers get consistent snapshots; a second writer process follows the documented policy. Add fsync only where crash-durability requirements justify it.

**Dependencies:** I04.

### I06 — Make locale a per-request value

**Classification:** Near-term · Reliability/UX · P2 · S. **Evidence:** `core/message_monitor.py:484-486`; `memory/localization.py:522-547`; handlers retain the singleton localization object.

**Problem:** A Norwegian request can await I/O while another request changes the global language to English. This race follows from the shared mutable locale; it was not exercised on Discord.

**Proposed PR:** Pass locale through a request context or immutable localization view; stop changing global language during dispatch. Allow an explicit stored language preference over detection.

**Scope boundaries:** Preserve current translation keys and language detection; no wholesale translation rewrite.

**Acceptance target:** Interleave Norwegian/English handler calls around an await and assert each response retains its locale; unchanged single-request outputs pass existing routing/translation checks.

**Dependencies:** None.

## Phase B — Calendar, privacy, and conversational trust

### I07 — Define explicit access and calendar-sharing policies

**Classification:** Foundation · Security/Product · P1 · M. **Evidence:** `core/message_monitor.py:439-452`; `core/config.py:81-82`; `cal_system/calendar_manager.py:178,261-264`; `README.md` advertises a cross-channel shared calendar. Empty allowlists remove restrictions; group DMs bypass the channel restriction branch. Global sharing is intentional existing behavior.

**Problem:** Invocation allowlists and calendar read/write ownership are different concerns. Reusing the account in another group can expose or mutate the same shared calendar unless the owner deliberately understands that policy.

**Proposed PR:** Add named access modes and explicit calendar scopes (legacy shared, private user, approved group). Centralize read/write policy and show it in setup/console. Validate empty-list semantics and group-DM policy.

**Scope boundaries:** Do not silently privatize or split existing shared data. Preserve legacy sharing via a reviewed migration/default choice; no claim of a proven external authorization exploit.

**Acceptance target:** Tests cover allowlist empty/nonempty, DMs/group DMs/guilds, owner versus collaborator read/write, and legacy migration. A user can explain which people and channels can see each scope from the UI.

**Dependencies:** I04.

### I08 — Bind calendar mutations to stable item identities

**Classification:** Product/Reliability · P1 · M. **Evidence:** `cal_system/calendar_manager.py:261-268,466-489`; `features/calendar_handler.py:333-435`. UUIDs exist, but many commands target a current list index; clear confirmation checks count rather than the actual set.

**Problem:** A reordered list or equal-count replacement can change the target between viewing and confirming. Bulk title matching can affect more than intended.

**Proposed PR:** Show short stable IDs, resolve numbers against a bounded displayed-list revision, and bind destructive previews to actor/scope/item IDs/revision/expiry. Add an explicit reversible local undo journal for supported mutations.

**Scope boundaries:** Keep numeric commands where safe; remote undo must state whether recreation changes the remote ID. No irreversible operation may claim full undo.

**Acceptance target:** Equal-count replacement, concurrent sync, duplicate titles, cross-user replay, and expired confirmation fail closed or require a fresh preview; ID-based commands remain stable; undo tests distinguish local and remote effects.

**Dependencies:** I04, I07; I05 before adding concurrent console mutations.

### I09 — Model event time, duration, and all-day semantics explicitly

**Classification:** Foundation · Core/Product · P2 · M. **Evidence:** `cal_system/natural_language_parser.py:596-716`; `cal_system/calendar_manager.py:182-196`; `cal_system/google_calendar_manager.py:592-600,650-653,688-703`; `cal_system/reminder_checker.py:312-349`. Host-local naive dates coexist with Oslo-aware calculations; Google conversion supplies fixed durations and defaults for missing time.

**Problem:** Date-only tasks, all-day events, and timed events have different meaning; currently those distinctions can be inferred or replaced with arbitrary times.

**Proposed PR:** Introduce explicit item kind, local date/time, timezone, all-day flag, optional duration/end, and an injected clock. Define DST gaps/folds and invalid-time handling. Display inferred values before saving.

**Scope boundaries:** Migrate legacy date strings losslessly; Oslo remains default. Start with one timezone per item, not a travel-planning system.

**Acceptance target:** All-day round trips remain all-day; custom durations survive edits/sync; invalid times are rejected; UTC-host/Oslo-host behavior matches; DST fold/gap and midnight tests are deterministic.

**Dependencies:** I04; I07 for scope-aware migration.

### I10 — Preserve recurring-series and occurrence semantics

**Classification:** Core/Advanced · P2 · L. **Evidence:** `cal_system/calendar_manager.py:567-625,648-670`; `cal_system/google_calendar_manager.py:578-590`; `cal_system/reminder_checker.py:114-129`. Local completion advances the same item; Google expanded occurrences collapse to one master; deduplication uses item/type plus a one-hour window.

**Problem:** Occurrence completion, exceptions, series edits, missed occurrences, and repeat delivery identities are not a complete model.

**Proposed PR:** Represent a series separately from its occurrence; support edit-this/edit-future/edit-series, skip, end date/count, and occurrence-specific delivery keys. Define month-end and leap-day policy.

**Scope boundaries:** Start with currently supported recurrence types; explicitly reject unsupported imported RRULEs rather than flattening them. No general scheduler platform.

**Acceptance target:** Monthly anchor dates do not drift unintentionally; skipped/completed occurrences do not delete the series; restarts do not duplicate one occurrence's reminder; imported exceptions survive sync; unsupported rules stay readable.

**Dependencies:** I03, I09.

### I11 — Add a durable Google sync outbox and conflict state

**Classification:** Architecture/Reliability · P1 · L. **Evidence:** `features/calendar_handler.py:236-263`; `cal_system/calendar_manager.py:505-524`; Google calls use synchronous `.execute()`; deletion has `delete_pending` but create/update do not expose equivalent durable retry states.

**Problem:** Remote creation precedes local durability, and failed edits can later be overwritten by remote pulls. Calling sync methods from an async coroutine also keeps blocking work on the event loop.

**Proposed PR:** Commit local intent and a bounded durable operation queue, then execute Google I/O in a controlled worker. Track local revision, remote version, pending/synced/conflict/failed state, retry delay, and idempotency strategy for ambiguous creates.

**Scope boundaries:** One integration; preserve existing pagination and delete-pending records. No automatic last-writer-wins for unresolved conflicts or unbounded retries.

**Acceptance target:** Crash between remote acceptance and local acknowledgement cannot blindly duplicate creation; failed update remains pending; a concurrent remote edit is surfaced; slow fake Google calls do not stall an event-loop heartbeat. Record measured synthetic latency before claiming improvement.

**Dependencies:** I01, I04, I05; I09 before expanding time fields. A minimal current-schema outbox can precede I09.

### I12 — Make AI outcomes structured, bounded, and honest

**Classification:** Reliability/Product · P2 · M. **Evidence:** `ai/openrouter_connector.py:99-204,206-215`; `ai/hermes_connector.py:104-210`; `core/message_monitor.py:497-508,789-891`; `ai/action_schema.py:1-19`. Actions are separately hand-parsed; dataclasses are not runtime validators; handler failure can fall through to generic AI.

**Problem:** A conversational response may obscure a failed domain command, and tuple/string failures lose retry/provider details. Prefix-specific model formatting is a brittle capability assumption.

**Proposed PR:** Define response/error/action schemas with provider/model/source/fallback metadata; distinguish handler failure from chat; add bounded concurrent inference admission, user cancellation/deadline, structured retry-after, and a validated draft parser. Preserve explicit confirmation for writes.

**Scope boundaries:** No automatic action execution, paid-model fallback, or cloud escalation from a local-only preference. Do not retry ambiguous operations without an idempotency policy.

**Acceptance target:** Malformed model JSON/unknown actions stay inert; domain errors get actionable feedback; overload has a bounded queue and clear busy state; synthetic 429/5xx/auth errors follow distinct policies; fallback responses identify their origin.

**Dependencies:** None; I06 for localized feedback; I03 for reply delivery.

### I13 — Make memory retention and cloud sharing user-controlled

**Classification:** Product/Privacy · P1 · M. **Evidence:** `memory/user_memory.py:55-105,183-220,249-256`; `memory/conversation_context.py:46-106`; `core/message_monitor.py` builds personalized AI prompts. View/export/delete already exist.

**Problem:** Persistent interests/topics and shared-channel conversation context have no complete user-facing retention and provider-sharing policy. Deleting persistent memory does not inherently clear transient conversation entries.

**Proposed PR:** Add pause-learning, explicit saved facts versus temporary topics, retention settings, reset-conversation, and provider-specific sharing controls. Make delete scope visible and remove the requesting user's appropriate transient entries too.

**Scope boundaries:** Do not erase other users' history in a shared channel or claim deletion from remote providers/backups. Preserve current self-only export/delete authorization.

**Acceptance target:** Opt-out prevents new learned facts and prompt inclusion; deletion clears documented local surfaces; retained backups and remote limits are explained; context cleanup prunes idle channels globally and before every accessor.

**Dependencies:** I04, I05; I07 for shared-context policy.

### I14 — Export complete user memory through a private delivery path

**Classification:** Near-term · Product/Privacy · P2 · S. **Evidence:** `features/memory_handler.py:22-38`; `memory/user_memory.py:222-245`. Export JSON is truncated at 1,800 characters and replied to in the invoking channel.

**Problem:** Larger exports become invalid JSON; sensitive personal details can be unnecessarily displayed to a group when requested there.

**Proposed PR:** Deliver a complete bounded JSON attachment or authenticated download with explicit scope/creation metadata. Offer private delivery with a deliberate public fallback decision if unavailable.

**Scope boundaries:** No silent DM fallback or external uploads; no cross-user export; preserve view as a concise summary.

**Acceptance target:** Export well beyond 1,800 characters parses and equals the stored self-only snapshot; delivery failure does not leak it publicly; attachment size limits and expiration are tested.

**Dependencies:** I03, I13.

## Phase C — Console, discovery, and architecture

### I15 — Refresh all dashboard details from one live state model

**Classification:** Near-term · UX/Reliability · P2 · M. **Evidence:** `web_console/static/app.js:190-237,337-413`; `web_console/dashboard.py:240-600`. Poll updates change selected counters; server-rendered event rows, diagnostic panels, and log text are not rebuilt by those branches, while modal data can be newer.

**Problem:** A dashboard can show fresh counts alongside stale details and copied log text.

**Proposed PR:** Add safe DOM renderers for event rows, polls, intent/rate tables, diagnostics, activity, and logs using the same fetched state as modals. Retain text-safe rendering and focus.

**Scope boundaries:** Vanilla JS remains adequate; no framework rewrite or raw HTML injection.

**Acceptance target:** Fake successive responses update both rows and counts; deleting the final item shows an empty state; copy logs matches visible latest logs; mobile layout and an open modal retain useful focus; existing frontend security checks still pass.

**Dependencies:** None.

### I16 — Track freshness and own every polling timer

**Classification:** Near-term · UX/Reliability · P2 · S. **Evidence:** `web_console/static/app.js:111-187`; `pollEndpoint` schedules timeouts without stored handles, and any successful endpoint updates one global timestamp.

**Problem:** Hiding/showing the tab can leave old scheduled callbacks alongside new polling chains. A fresh status request can conceal failed calendar refreshes.

**Proposed PR:** Store one timer/controller/generation per endpoint, add a fetch deadline, and publish per-card last success/loading/stale/error with an explicit manual retry. Use a truthful overview freshness rule.

**Scope boundaries:** Preserve existing visibility pause, auth-expiry handling, backoff, and endpoint intervals. Do not claim an observed request storm.

**Acceptance target:** Fake-timer tests across repeated hide/show yield one active chain per endpoint; a hung request times out; one failed endpoint stays visibly stale while others succeed; auth expiry stops all work.

**Dependencies:** None; I15 is a soft integration dependency.

### I17 — Report the configured AI provider and actionable subsystem health

**Classification:** Near-term · Operations/UX · P2 · M. **Evidence:** `web_console/state_collector.py:60-77,265-333`; `web_console/dashboard.py:348-369,585-600`. `/api/bridge` probes the local bridge even when OpenRouter is configured; aggregate health already distinguishes whether the bridge is required.

**Problem:** Optional bridge unavailability can confuse cloud users, while model-list reachability is weaker than inference readiness.

**Proposed PR:** Separate transport liveness, configured provider readiness, model verification, calendar sync, persistence, and scheduler freshness. Show each failure's recovery action and whether it affects current functionality.

**Scope boundaries:** No routine billable inference health checks; retain public health data minimization and authenticate detailed diagnostics. Do not re-propose task tracking already present.

**Acceptance target:** Local-only/cloud-only/offline-template fixture states produce accurate labels; disabled features are not incidents; stale scheduler heartbeat is visible; detailed errors do not expose credentials or private content.

**Dependencies:** I12; I16 for freshness presentation.

### I18 — Bound log retention and add useful diagnostic filtering

**Classification:** Reliability/Performance/UX · P2 · M. **Evidence:** `web_console/console_store.py:50-78`; `utils/logger.py:136-191`; `web_console/server.py:681`; `web_console/static/app.js:422-438`. Console logs append persistently; loading a tail calls `readlines()` on the entire file.

**Problem:** Requested tail size does not bound bytes read, and text logs make a command difficult to trace across routing, storage, provider, and delivery.

**Proposed PR:** Add byte/age rotation and bounded tail/cursor reads; retain structured component, level, request ID, and outcome fields alongside a human view. Add filters, pause-follow, copy/download diagnostics, and privacy-safe correlation.

**Scope boundaries:** No content archive or central telemetry service; retain redaction before persistence. Keep audit records with separate retention rules.

**Acceptance target:** A synthetic large log tail reads bounded data with a measured byte budget; rotation preserves configured recent records; malformed rows are skipped visibly; request correlation omits prompt text by default.

**Dependencies:** I04 for failure reporting; I15 for UI integration.

### I19 — Centralize command metadata and provide a routing preview

**Classification:** Architecture/Product/DX · P2 · M. **Evidence:** `core/message_monitor.py:32-60,510-625,1082-1119`; `core/intent_router.py:107-140`; `features/help_handler.py`; `web_console/dashboard.py:761-982` maintains another command catalogue.

**Problem:** Aliases, documentation, dispatch, and payload conventions are spread across surfaces. The small existing registry does not describe all handlers.

**Proposed PR:** Extend typed command metadata with aliases/examples/scope/mutation kind/handler/payload contract. Generate help and console reference from it; add an offline routing preview showing route, confidence, reason, parsed fields, and authorization requirements without dispatch.

**Scope boundaries:** Preserve deterministic rule precedence and confidence thresholds; no dynamically loaded arbitrary plugin code or LLM routing replacement.

**Acceptance target:** Every routable intent resolves to one documented handler contract; help/reference parity checks pass; preview performs no writes/provider calls; false-positive regression corpus retains current safety behavior.

**Dependencies:** I07 for access descriptions; I12 for action contracts. Can initially use current contracts.

## Phase D — Developer experience and operations

### I20 — Make the offline test suite hermetic and separate live evaluations

**Classification:** Foundation · Testing/DX · P1 · M. **Evidence:** `tests/conftest.py:19-26,95-99`; `pytest.ini`; `.github/workflows/ci.yml`; `tests/README_TESTING.md` describes live model tuning. Fixtures import the console before setting test paths and preserve a pre-existing `HERMES_HOME` using `setdefault`.

**Problem:** Test isolation depends on inherited environment and import order; live model checks and deterministic application checks need an unmistakable boundary.

**Proposed PR:** Establish sandbox paths before application imports in the test harness, explicitly clear sensitive inherited config, block external network by default, allocate dynamic test ports, and mark live provider/account evaluations as opt-in. Add scenario tests for the data/delivery defects above.

**Scope boundaries:** No dependency installs or live tests during this audit. Test-path mutation applies only inside the test subprocess, never the user's shell.

**Acceptance target:** Run offline tests with a synthetic pre-existing Hermes path and prove it is untouched; socket attempts to external hosts fail; parallel suites do not collide on ports; live jobs require explicit credentials and invocation; report collected/executed/skipped counts separately.

**Dependencies:** None. This enables safe verification of all later PRs.

### I21 — Lock dependency sets and isolate optional integrations

**Classification:** Foundation · DX/Supply chain · P2 · M. **Evidence:** `requirements.txt`, `requirements-dev.txt`, `Dockerfile`, `.github/workflows/ci.yml`, desktop build workflows. Dependencies use lower bounds; Google/search/browser/keyring packages are installed in the default set even where optional.

**Problem:** CI, containers, desktop packages, and users can resolve different graphs. Optional integration installation increases setup cost and failure surface.

**Proposed PR:** Define tested reproducible production/dev/desktop dependency sets with hashes and an update workflow; package optional Google/search/browser integrations separately. Add typed connector/manager protocols and incremental lint/type checks on changed boundaries.

**Scope boundaries:** Keep `setup.py` recognizable as the existing interactive wizard; do not overwrite it as packaging metadata. Do not duplicate the ten open dependency bump PRs or claim any installed package is vulnerable without an advisory check.

**Acceptance target:** Clean installs for each supported profile use a recorded graph; missing optional packages yield disabled capability guidance; CI/desktop/container manifests agree; security checks run against the resolved graph with reviewed exceptions.

**Dependencies:** I20. Existing dependency PRs should be reviewed as input to the lock update.

### I22 — Consolidate release ownership and verify built artifacts

**Classification:** Foundation · Release/Testing · P2 · M. **Evidence:** `.github/workflows/release.yml` and `.github/workflows/build-desktop-apps.yml` both publish on `v*`; the latter accepts a version string without using it as the build checkout ref. The older May remediation plan explicitly lists release consolidation as unfinished follow-up.

**Problem:** Two publishers can race release content, and a manually named version can describe artifacts built from a different revision.

**Proposed PR:** One release publisher depending on verified platform artifacts and required CI; resolve the release ref before every build; attach checksums, full SHA, dependency manifest, and platform smoke results. Reconcile the different bundle manifests in `mac_app/build.py`, `mac_app/build.sh`, and `windows_app/build.py`: scripts and web-console templates/static assets must survive freezing. Derive application version and supported OS metadata from one release definition. Add optional signing/notarization after credentials and distribution goals are selected.

**Scope boundaries:** This is carried-forward work, not a novel finding. No signing certificate purchase or release publication is part of the proposal.

**Acceptance target:** One tag produces one release at its exact commit; manual release resolves the selected tag; missing artifacts block publication; each executable demonstrates frozen entrypoint/templates/assets and a no-network startup/configuration smoke test.

**Dependencies:** I20, I21.

### I23 — Align deployment paths around verified rollback

**Classification:** Operations/Reliability · P1 · M. **Evidence:** `deploy/ansible-playbook.yml` checks health and running commit; `scripts/deploy/inebotten-update:37-74` resets the checkout and reports completion without equivalent readiness/match enforcement; `Dockerfile` has no HEALTHCHECK. README presents local, Ansible, and legacy deployment routes.

**Problem:** The legacy route can discard local changes and report an unverified update. Definitions do not establish which route is actually in use.

**Proposed PR:** Choose/document supported deployment profiles, reject dirty deployment checkouts, pin artifacts by full revision, preflight configuration/ports/storage, and retain a tagged known-good image plus compatible data snapshot. Require readiness and revision match; roll back code on failure under an explicit data compatibility rule. Add Docker/Compose, Ansible, and shell static/synthetic gates to CI.

**Scope boundaries:** No deploy, data restoration, image prune, or runtime migration authorized here. Deprecating legacy scripts requires checking current users; do not infer VPS availability from files.

**Acceptance target:** Synthetic stale image, unhealthy app, source-sync failure, and occupied port fail clearly; dirty checkout is preserved; rollback rehearsals restore the prior code without overwriting newer incompatible data; exact revision and recovery steps are recorded.

**Dependencies:** I04, I17, I21; I22 is soft for unified release artifacts.

### I24 — Close every owned resource and persist final counters

**Classification:** Reliability/Architecture · P2 · M. **Evidence:** `core/message_monitor.py:333-353,1389-1428`; `core/selfbot_runner.py:178-190`; `features/crypto_manager.py:80-89,334`; `features/aurora_forecast.py:33-42`; `features/search_manager.py:106-113`. Monitor task cancellation exists, but manager HTTP sessions and final unsaved counters need explicit ownership review.

**Problem:** Constructor composition creates resources without one complete close contract; cancelling the periodic save can lose the last interval's metrics.

**Proposed PR:** Register owned sessions/managers with an idempotent async shutdown contract and flush pending counter deltas within a deadline.

**Scope boundaries:** Do not reimplement existing background-task tracking, reconnect guard, or the stronger partial-startup readiness handling already merged on GitHub master. Close only owned resources; shared dependencies remain under their owner's lifecycle.

**Acceptance target:** Repeated startup/failure/shutdown sequences leak no fake sessions/tasks; final counters persist once; cancellation is bounded and preserves unsaved-error evidence. Preserve current-master initialization-failure regressions.

**Dependencies:** I04, I05.

## Phase E — Product expansion

### I25 — Add notification preferences and a useful personalized digest

**Classification:** Product/UX · P2 · M. **Evidence:** `cal_system/reminder_checker.py:145-277,279-309,365-388`; `features/daily_digest_manager.py:21-156`; `memory/user_memory.py:65-79`. The checker has fixed stages/morning time; the richer on-demand digest hardcodes several sections and market assets.

**Problem:** Users cannot deliberately choose stages, offsets, quiet hours, private versus shared destination, snooze, or digest content. A notification just after start is labeled finished despite no modeled duration.

**Proposed PR:** Persist an opt-in notification profile per user/scope: delivery destination, lead times, quiet hours, snooze, morning time, and selected digest cards. Share card formatting between proactive and requested digest while retaining provenance/degraded states.

**Scope boundaries:** Defaults must not expand proactive messaging. Rename inaccurate passed-event wording independently of adding end times. No unapproved subscriptions or mass delivery.

**Acceptance target:** Fake-clock tests cover quiet-hour boundaries, snooze/restart, opt-out, selected cards, DST, and destination loss; unavailable sections do not suppress the whole digest; event-end wording uses actual end semantics.

**Dependencies:** I03, I07, I09; I13 for preference storage.

### I26 — Add an authenticated calendar workspace with previewed edits

**Classification:** Product/UX · P2 · L. **Evidence:** `web_console/server.py:667-679`; `web_console/dashboard.py:370-411`; `web_console/state_collector.py:336-381`. Console calendar is primarily counts/upcoming summaries; domain CRUD is in Discord handlers/managers.

**Problem:** Managing dense schedules through chat indices is awkward; pending sync/deletion state is difficult to resolve from the console.

**Proposed PR:** Add agenda/week views, scope filters, item details, create/edit forms, clear pending-sync indicators, previewed destructive actions, and conflict resolution. Reuse domain policy and contracts rather than invoking Discord handlers.

**Scope boundaries:** Start agenda-first with keyboard/mobile forms; calendar drag/drop can follow. Cookie-authenticated writes require origin/CSRF validation, restrictive methods, and revision checks. Preserve safe DOM rendering.

**Acceptance target:** An authenticated user can create/edit/complete by stable ID with accessible errors/loading/success states; stale edits return conflict; forbidden scope access fails; cross-origin write requests are rejected; keyboard and narrow-screen scenarios pass.

**Dependencies:** I05, I07, I08, I09, I11, I15, I16.

## Second-pass discovery

The first pass produced I01–I26 before this pass began. The second pass deliberately examined forecast/currency/school-data truthfulness, desktop lifecycle and setup, poll invariants, the standalone member exporter, import/export, and cross-feature planning. It added the thirteen distinct proposals below. Browser focus handling, reduced-motion CSS, birthday date/leap handling, watchlist scope, existing search provenance, frozen entrypoint helpers, and current-master hardening were checked to avoid proposing work already done.

## Phase F — Utility quality, onboarding, and desktop experience

### I27 — Show forecast validity instead of fabricated fallback weather

**Classification:** Near-term · Product/Reliability/Performance · P1 · M. **Evidence:** core/message_monitor.py:959-999 constructs a weather client for every dashboard, indexes a fixed city dictionary, and substitutes “Delvis skyet”/8°C on failure; features/weather_api.py has an instance cache; features/aurora_forecast.py:113-162 removes UTC timezone information before comparing with host-local time.

**Problem:** A plausible invented forecast obscures unavailable data. A stored unsupported city can fail dictionary lookup. Recreating clients prevents cache reuse across dashboard requests; aurora selection can use the wrong time basis.

**Proposed PR:** Use a shared owned forecast service with source, observation/forecast time, expiry, location, and unavailable/stale states. Preserve aware timestamps when choosing aurora intervals. Resolve unknown locations with a clear choice/error; initially accept validated coordinates or known-city aliases. Mark any heuristic aurora visibility score as a heuristic rather than measured probability.

**Scope boundaries:** No live weather accuracy claim, geocoder purchase, or forecast model. Reuse current providers; adding broader location lookup is optional after choosing its privacy and usage contract. Keep resource shutdown under I24.

**Acceptance target:** Fake unavailable/malformed/expired responses never produce invented conditions; UTC and Oslo clocks select the same instant across DST; unsupported locations receive actionable feedback; repeated same-location requests within cache TTL produce one synthetic provider request and expired cache triggers refresh. Record latency only if measured.

**Dependencies:** None; I06 for localized feedback and I24 for lifecycle integration are soft.

### I28 — Label currency estimates with their source and effective time

**Classification:** Near-term · Product/Data quality · P1 · S. **Evidence:** features/calculator_manager.py:16-24 contains fixed fiat and BTC rates labeled approximate in a code comment; :174-216 displays conversion with an equality and no effective date.

**Problem:** Users see an apparently current precise conversion from undated constants. Independently entered directional rates can also disagree on reciprocal conversion.

**Proposed PR:** Introduce a rate snapshot contract with source/effective time/freshness and one coherent base-rate table. Immediately label fixed demonstration rates as estimates with unknown effective date, or refuse current-rate requests when no verified snapshot exists. Allow a later configured provider through the same contract.

**Scope boundaries:** Ordinary calculator and physical unit conversions stay unchanged. This proposal selects no financial data vendor and promises no executable quote, fee calculation, tax result, or investment advice.

**Acceptance target:** Fixture conversions disclose their snapshot and rounding policy; stale/unknown rates are explicit; unsupported currencies fail clearly; pair/inverse/cross-rate checks use one snapshot, including differing crypto precision. No live financial account is required.

**Dependencies:** None.

### I29 — Version school calendars by year and locality

**Classification:** Product/Core functionality · P2 · M. **Evidence:** features/school_holidays.py:11-50 uses one 2025–2026 table and county/zone labels; :127-169 discards entries whose end date has passed. Every populated entry ends by 6 April 2026.

**Problem:** On the audit date the table cannot return upcoming holidays. County-wide defaults cannot establish an individual school's schedule.

**Proposed PR:** Load reviewed school-year datasets with locality/school identifiers, source references, verification date, and coverage status. Separate genuinely national dates from local schedules; select a user's chosen locality and show “schedule unavailable” when the year is missing. Add an annual maintenance checklist and expiry warning.

**Scope boundaries:** Do not mechanically shift last year's dates or assert new county boundaries/dates without authoritative verification. Source ingestion and a small reviewed dataset precede any automated scraping.

**Acceptance target:** Fake clocks exercise school-year rollover and expired datasets; two localities can have different dates; source and coverage are displayed; incomplete data cannot look like “no holidays”; new reviewed entries have date-range/schema checks.

**Dependencies:** None; I13 is soft for saved locality preferences.

### I30 — Add bounded research cards and optional real page extraction

**Classification:** Advanced · Product/Reliability · P2 · M. **Evidence:** features/search_manager.py:25-118 already normalizes provider/freshness metadata but has no outer multi-provider deadline; Google fallback returns URLs with placeholder text. features/browser_manager.py:26-38 deliberately returns no content until actual extraction exists.

**Problem:** Users cannot consistently tell a URL-only result from fetched evidence, and blocking-provider fallbacks can extend a request without a total budget. The existing browser integration nearly enables deeper research, but session metadata is correctly not treated as page text.

**Proposed PR:** Add cited result cards with publication time versus fetch time, snippet versus extracted text, coverage, and partial-failure status. Bound the total fallback budget and provider worker count, using underlying network deadlines where possible. Implement a small optional public-page text extractor only after selecting its supported content formats and access contract; keep external text inert evidence in the AI prompt.

**Scope boundaries:** No paywall/access-control bypass, credentialed browsing, arbitrary automation, automatic actions from retrieved text, or claim of an existing SSRF exploit. A timeout alone does not stop a blocking executor thread; account for that lifecycle explicitly.

**Acceptance target:** Synthetic hung providers stay within the response/worker budget; URL-only results are never described as read pages; quotes and conclusions map to fetched sources; extraction enforces redirect, resolved-address, scheme, content-type, and byte limits and rejects private/local endpoints. Browser startup and cancellation leave no sessions behind.

**Dependencies:** I12; I19 is soft for command discoverability. A cards/deadlines slice can land before optional extraction.

### I31 — Make desktop launchers reflect process and connection state safely

**Classification:** UX/Reliability · P2 · M. **Evidence:** mac_app/launcher.py:282-295 reports stopped after terminate without awaiting exit; :334-380 updates Tk state/widgets from a worker and reports running when Popen succeeds. windows_app/launcher.py has the parallel implementation. The macOS window is fixed at 600×500.

**Problem:** UI-thread ownership and child-process lifetime are ambiguous. “Running” does not establish a ready gateway; rapid restart/window close can race the previous process. A fixed window limits the space available for settings and logs.

**Proposed PR:** Put worker events on a bounded queue drained by Tk's main loop. Model starting/process-alive/connecting/ready/degraded/stopping/exited; use the supported readiness contract for connection status. Wait for graceful process-group shutdown with a bounded escalation, prevent duplicate starts, and make settings/log panes resize with keyboard-friendly labels and explicit errors.

**Scope boundaries:** Keep Tk and the corrected source/frozen command helpers. No native-platform rewrite. Do not kill a pre-existing service the launcher does not own.

**Acceptance target:** A fake child that starts, hangs, exits early, ignores terminate, and emits rapid logs yields correct state and responsive UI; all widget calls run on the main thread; closing waits within the bound and leaves no owned children; source and frozen paths retain their tests. Manual keyboard, scaling, and narrow-window checks precede release.

**Dependencies:** I17 for readiness presentation; I32 for shared settings. I22 is soft for frozen-artifact proof.

### I32 — Unify onboarding around a private, preserving configuration contract

**Classification:** Foundation · UX/Security/DX · P1 · M. **Evidence:** setup.py:49-62,125-141 uses visible input/defaults for credentials; :103 suggests system-package override on installation failure. utils/setup.py installs discord.py and carries older entrypoint guidance. mac_app/launcher.py:298-330 and the Windows equivalent replace the Hermes env file with a short template. Config accepts email/password fields while core/selfbot_runner.py:159-163 rejects that auth mode.

**Problem:** Setup paths disagree on supported dependencies/authentication and can expose entered/default secrets or discard unrelated allowlists, console, and Google settings. This is source-confirmed behavior, not a reported credential leak.

**Proposed PR:** Define one validated configuration schema consumed by CLI, console, and desktop setup. Use hidden credential entry, never echo an existing secret, show the authoritative configuration path, preserve unrelated keys, and commit private files atomically with permissions set before content. Validate supported token authentication and provider settings before start; use a project venv and retire the stale installer with a migration notice.

**Scope boundaries:** Preserve the explicit-HERMES_HOME authoritative-source rule already merged on master. Do not copy real credentials, silently change accounts, rotate keys, raise rate limits, or install packages during this audit.

**Acceptance target:** Synthetic config round trips preserve unknown/untouched keys; secret values never enter captured terminal/GUI logs; files are private throughout creation; unsupported auth fails at setup; paths with spaces and absent optional providers work; one documented clean-venv setup reaches offline preflight.

**Dependencies:** None; I21 is soft for installation profiles and I07 for access-setting descriptions.

### I33 — Enforce poll expiry and preserve votes during deliberate edits

**Classification:** Core functionality/UX · P2 · M. **Evidence:** features/poll_manager.py:105-132 replaces options and clears votes; :154-202 checks status in vote but timestamp in active-list selection. Probe 4 accepted a direct expired-active vote. Existing ownership checks must be retained.

**Problem:** Expiry is a caller convention rather than a domain invariant, and option edits have no explicit vote-reset preview. Closed results need a deliberate read path rather than disappearing with active polls.

**Proposed PR:** Make open/expired/closed states explicit, reject votes on expired or closed polls in the manager, and expose stable poll/option identities. Preserve votes across harmless label edits; structural changes require a clear reset confirmation or an explicitly versioned replacement poll. Add close and historical-results commands.

**Scope boundaries:** Keep current ownership rules and one-vote-per-user behavior. No anonymous-voting guarantee or statistical analysis.

**Acceptance target:** Fake-clock boundary tests reject direct late votes, including restart; label-only edits preserve counts; removed options cannot retain invalid votes; destructive resets require matching version/preview; closed results remain readable under the same scope policy.

**Dependencies:** None; I19 is soft for metadata and help registration.

## Phase G — Interoperability, recovery, and stretch workflows

### I34 — Turn an accepted group plan into a scoped calendar event

**Classification:** Advanced · Product · P3 · M. **Evidence:** features/poll_manager.py, features/calendar_handler.py, and features/watchlist_manager.py provide separate decision, scheduling, and shared-interest primitives. No composed plan-finalization workflow was found in the inspected routing/handlers.

**Problem:** A group can discuss what to do and maintain lists, but translating the selected activity/time into a calendar entry and attendance requires separate manual steps.

**Proposed PR:** Add an opt-in planning session with candidate activities/times, a poll, organizer confirmation of the selected outcome, a calendar draft, and RSVP state. Link source poll and finalized event by stable identity; disclose whether a result is advisory or accepted.

**Scope boundaries:** First version supports one activity and one selected time. No automatic majority scheduling, private-calendar exposure, unsolicited invitations, travel booking, or public announcement.

**Acceptance target:** A synthetic group completes proposal → poll → organizer review → one event; tied/expired/no-vote polls do not auto-finalize; retries create no duplicates; later poll edits cannot silently change the event; only authorized organizers act and attendance visibility respects scope.

**Dependencies:** I07, I08, I09, I33; I03 before any outbound invitation.

### I35 — Add a consistent backup bundle and rehearsable restore

**Classification:** Foundation · Operations/Reliability · P1 · M. **Evidence:** utils/json_storage.py and independently saved calendar/reminder/memory/feature stores under Hermes data; utils/secure_storage.py handles token material separately; deployment files do not establish a tested cross-store snapshot/restore contract.

**Problem:** Atomic replacement of each JSON file does not create a consistent backup across stores. A raw directory copy can mix generations and include secrets or stale sessions.

**Proposed PR:** Create an explicit data-only backup manifest with schema/revision/generation, checksums, allowed paths, and store snapshot coordination. Validate archives into a fresh staging directory, summarize compatibility/content, and restore only after services are quiescent and the exact destination/replacement is confirmed. Retain a recoverable previous generation.

**Scope boundaries:** Exclude API keys, Discord/OAuth tokens, browser sessions, raw logs, and exports by default. Protect calendar/memory backups as private data; no external uploader or encryption-provider decision is included. Archive members must never escape the destination.

**Acceptance target:** Two related synthetic stores snapshot one generation; truncated/tampered/traversal/symlink archives fail without modifying the destination; incompatible schemas refuse; a clean restore reproduces data and references; a rehearsal documents code/data compatibility and rollback. Never use personal stores for tests.

**Dependencies:** I04, I05, I13.

### I36 — Support previewed ICS calendar import and export

**Classification:** Product/Interoperability · P2 · M. **Evidence:** cal_system/calendar_manager.py and google_calendar_manager.py support JSON-backed items and Google linkage; inspected calendar handlers and console routes have no general ICS exchange workflow.

**Problem:** Users without Google integration cannot easily exchange their schedule with ordinary calendar clients or migrate selected scoped events.

**Proposed PR:** Export scoped events using stable UIDs and explicit all-day/timezone semantics; import a bounded ICS file into a preview showing new/changed/duplicate/unsupported entries. Require confirmation for application and record source identifiers for idempotent re-import.

**Scope boundaries:** Start with a declared interoperable subset; reject or visibly skip unsupported recurrence/attachments rather than flattening silently. No automatic URL subscriptions in this PR and no task/reminder representation invented as events.

**Acceptance target:** Fixture round trips preserve UID, timezone, duration, all-day, Unicode, and supported recurrence; re-import is idempotent; malformed/oversized input is bounded; scope leakage and stale preview confirmation fail; verify exports in at least two calendar clients before claiming interoperability.

**Dependencies:** I07, I09; I10 before enabling recurring-series exchange. A non-recurring subset can precede I10.

### I37 — Explore a supported bot-account transport behind domain adapters

**Classification:** Stretch · Architecture/Product · P3 · L. **Evidence:** core/selfbot_runner.py and requirements.txt couple runtime to a user-token Discord client; managers are already more transport-independent than handlers; scripts/inebotten_ctl.py also relies on account-specific endpoints.

**Problem:** The domain assistant and user-account research/controller behavior share a transport assumption. This limits offering the calendar/reminder/poll product to another community through a conventional bot installation.

**Proposed PR:** First produce a feasibility/capability matrix against current official Discord documentation, then add a transport adapter for the supported assistant subset, with bot-token configuration and explicit permissions. Keep the user-specific controller separate; use contract fixtures for shared handlers and optionally offer interaction commands where supported.

**Scope boundaries:** This is a product option, not a verified drop-in replacement. Current API compatibility and platform policy were not evaluated in this audit. No private-DM access, endpoint emulation, evasion, automatic account migration, or removal of the existing mode.

**Acceptance target:** Document each preserved/unavailable capability and identity boundary; a test bot in an explicitly approved test guild completes supported mentions/commands/calendar/polls; shared domain fixtures pass across adapters; configuration prevents token-mode confusion; unsupported operations refuse clearly.

**Dependencies:** I07, I19, I20, I21. Complete feasibility before adapter implementation.

### I38 — Add opt-in workflow recipes with bounded, reviewable actions

**Classification:** Stretch · Product/Automation · P3 · L. **Evidence:** core/intent_router.py, ai/action_schema.py, calendar/reminder managers, and daily_digest_manager.py already provide routing, drafts, scheduling, and summaries as separate primitives.

**Problem:** Repeated cross-feature routines require manual coordination—for example, an organizer-confirmed event should create a preparation checklist and appear in the next chosen digest.

**Proposed PR:** Offer a small set of typed trigger/action recipes owned by a user/scope: confirmed plan → reviewed preparation tasks, due tasks → selected digest card, or approved calendar change → personal reminder draft. Provide dry-run receipts, explicit enable/pause, an action/delivery budget, durable execution identities, and visible failure/retry history.

**Scope boundaries:** Templates only; no arbitrary Python, shell, webhook destination, broad message surveillance, or action execution from model/retrieved-content instructions. I25 covers notification preferences; this proposal adds conditional cross-domain orchestration. Every side effect inherits domain authorization and any required confirmation.

**Acceptance target:** Synthetic replay/restart does not repeat confirmed mutations; preview lists exact scope and effects; denied/paused/budget-exhausted recipes do nothing; retries have bounded attempts; untrusted content cannot select an action; a user can inspect and disable each recipe.

**Dependencies:** I03, I07, I08, I12, I25.

### I39 — Make the optional member exporter bounded, private, and truthful

**Classification:** Near-term · Reliability/Privacy/DX · P1 · M. **Evidence:** scripts/export_members.py:75-103 writes files with ordinary permissions and overwrites existing destinations; a .json output argument makes CSV and JSON resolve to the same pathname. :159-190 pages without an explicit overall/member bound and falls back to gateway retrieval that may omit members; the JSON output lacks that coverage distinction. tests/test_export_members.py covers basic serialization. These two files exist only on the preserved local branch, not current GitHub master.

**Problem:** The separate utility does not inherit the controller's complete identity/bounds/output contract. Its output can replace prior files, expose member data under an ordinary umask, or appear complete after a partial fallback. Spreadsheet interpretation of untrusted text cells is an additional hardening concern, not a demonstrated exploit.

**Proposed PR:** If this local utility is retained, reuse applicable controller identity/target/deadline rules, require an explicit bounded export scope, and mark collection source and completeness/limitation in both formats. Use exclusive private output creation with collision-safe CSV/JSON paths, bounded rows/bytes, and spreadsheet-safe text encoding; keep exact raw strings only in the private JSON representation where appropriate.

**Scope boundaries:** Do not publish the unmerged exporter implicitly. No expansion of member visibility, automatic joins, scrape evasion, personal-data collection during verification, or assertion that a count match proves completeness. Deprecation is a valid alternative if no current owner needs this utility.

**Acceptance target:** Fake repeated cursors/429/timeouts stop within bounds; identity/ambiguous scope failure prevents collection; fallback exports identify partial/unknown coverage; existing files and same-path extensions are preserved; created artifacts have private permissions; formula-like fixture text remains text in supported spreadsheet readers.

**Dependencies:** None; reconcile retention/publication of the local-only utility first. I21 is soft for its optional dependency profile.

### Second-pass stopping rule

Further candidates were rejected or folded into existing proposals: a wholesale database/microservice rewrite (no measured scale need), another generic cache PR (I27 owns the concrete cache lifetime), another command parser (I19), generic “add accessibility” work (existing focus/landmark/reduced-motion protections, with targeted verification in I15/I16/I26/I31), a transcript/media pipeline (no established user workflow/capability), more speculative paid integrations (no justified source or product need), and duplicate security hardening already merged in #23. New ideas at this point were mostly redundant or outside the assistant's demonstrated product scope.

## GitHub reconciliation

Live read-only GitHub discovery found **zero open or closed issues** and **ten open PRs**, all individual dependency changes: [#12](https://github.com/Reedtrullz/inebotten-discord/pull/12) Bandit, [#13](https://github.com/Reedtrullz/inebotten-discord/pull/13) googlesearch, [#14](https://github.com/Reedtrullz/inebotten-discord/pull/14) duckduckgo-search, [#15](https://github.com/Reedtrullz/inebotten-discord/pull/15) aiohttp, [#16](https://github.com/Reedtrullz/inebotten-discord/pull/16) Tavily, [#17](https://github.com/Reedtrullz/inebotten-discord/pull/17) Pylint, [#18](https://github.com/Reedtrullz/inebotten-discord/pull/18) pytest, [#19](https://github.com/Reedtrullz/inebotten-discord/pull/19) requests, [#20](https://github.com/Reedtrullz/inebotten-discord/pull/20) google-auth-oauthlib, and [#21](https://github.com/Reedtrullz/inebotten-discord/pull/21) simpleeval. Bodies and changed files were inspected; do not replace these with duplicate upgrade issues.

**Current remote baseline:** GitHub default branch master is c0b6a321b3e63e154e466604a9980954c502fb4d, the merge of [#23](https://github.com/Reedtrullz/inebotten-discord/pull/23). Recent merged [#22](https://github.com/Reedtrullz/inebotten-discord/pull/22) covers checkout-status documentation, and [#11](https://github.com/Reedtrullz/inebotten-discord/pull/11) consolidated older dependency updates. Compare the preserved local checkout against this remote revision before implementing anything; the local tree is not today's default branch.

A full remote-tree blob comparison found fifteen remote differing/new paths, covering controller/reference docs, bridge clients/server, configuration, monitor orchestration, logging, and their tests. Seven differing runtime code files were then inspected from the contents API. Current master already supplies bridge authentication headers, authoritative explicit-Hermes configuration, bearer/basic and bridge-key redaction, private log rotation/stdout redaction, peer-rate bookkeeping, controller strict-ID/audit/JSONL handling, and failure-safe publication of a fully initialized monitor. These are **excluded from new proposals**. I24 was narrowed after this check. Current master still constructs a separate checker reminder manager; the remaining domain/console/build evidence was unchanged in the blob comparison. scripts/export_members.py and tests/test_export_members.py are local-only; I39 is explicitly conditional on retaining them, not a claim about master.

The May remediation plan was checked against current code. Already implemented: task tracking/cancellation, reconnect initialization guard, date/time Google edit propagation, delta-based console counter persistence, private token writes, per-handler send checks, non-root Docker, source-sync failure handling in Ansible, and console auth/DOM hardening. I03/I05/I11/I17/I24 describe materially different remaining gaps, not generic re-proposals of those fixes. I22 and parts of I20/I23 explicitly carry forward unfinished release/CI work. I32 addresses the remaining email/password setup inconsistency.

**Publication:** None. These newly discovered proposals have not been individually approved for public issue publication; the complete portfolio is supplied locally. GitHub access was available. Before any later publication, refresh open/closed issues and open PRs, mark every body “Proposed future PR — concept/design only. Not implemented”, map proposal IDs to issue numbers, substitute dependency links, and read back every issue to verify its body against this document. Do not create empty implementation PRs.

## Recommended implementation sequence

This is a staged engineering roadmap, not approval or a delivery estimate. Each ID appears once below. Within a wave, follow the proposal dependencies; independent work may run in parallel once safe test isolation exists. Security/privacy migrations must retain reviewed legacy behavior and recoverable data. Per-store preservation in I04 precedes schema changes; the richer cross-store backup tool in I35 can follow.

| Wave | Proposals in recommended order | Purpose and release gate |
| --- | --- | --- |
| 1 — Protect present behavior | I20, I01, I02, I04, I06, I27, I28, I32; I39 only if retained | Isolate offline verification; prevent accidental deletion, stale scheduler ownership, false persistence success, locale races, fabricated utility data, and configuration loss. The smallest initial delivery is I20 + I01 + I02. |
| 2 — Define reliable contracts | I05, I03, I07, I09, I12, I15, I16, I21, I29, I33 | Serialize storage; prove send outcomes; establish access/time/provider contracts; make dashboard state truthful; stabilize dependencies and small utility domains. Land contracts in focused slices rather than one migration. |
| 3 — Build recoverable state and operations | I08, I11, I13, I17, I18, I19, I22, I24, I30 | Add identity-safe edits, current-schema Google retries/conflicts, deliberate memory, actionable diagnostics, generated command discovery, verified release ownership, clean resource shutdown, and bounded research. Optional page extraction follows its own review. |
| 4 — Complete everyday workflows | I14, I25, I10, I23, I31, I35, I36 | Private usable exports, notification preferences, real recurrence, deployment recovery, reliable desktop controls, consistent backups, and calendar exchange. Recurring ICS support follows I10; non-recurring exchange can ship earlier. |
| 5 — Expand after foundations prove useful | I26, I34, I37, I38 | Agenda-first calendar console and deliberate group planning, then optional bot transport and automation recipes. I37 starts with feasibility; I38 requires an opt-in owner and bounded action contract. |

**Highest risk/coordination:** I07/I09/I10/I11/I13/I35 touch persisted/shared state and require fixture migrations, versioned compatibility, and rollback rehearsals. I26 adds authenticated writes; origin/CSRF and conflict handling are acceptance requirements for that future surface. I37/I38 are stretch choices and may be rejected without reducing the value of the reliability roadmap.

**Performance work is evidence-led:** I11 targets observed synchronous I/O placement, I13 targets unbounded idle-context retention, I16 targets timer ownership, I18 targets full-file tail reads, I27 targets ineffective per-request cache lifetime, and I30 targets unbounded aggregate fallback duration. No production speed, memory, or throughput gain has been measured.

## Coverage and confidence

| Area | Inspected evidence | Confidence / remaining evaluation |
| --- | --- | --- |
| Product goals, status, history, roadmap | README, ARCHIVED, CURRENT_STATE, applicable AGENTS, May remediation plan, repository layout, recent local history and live GitHub issues/PRs/master | Good architectural context; active deployment/support profile needs owner/live confirmation. Existing working-tree documents were preserved. |
| Gateway, authorization, routing, locale | core/message_monitor.py, intent_router and keyword/threshold helpers, config/auth/rate limiter/selfbot runner, controller and reference contracts | Source grounded. No gateway session, private messages, live identity, account health, or permissions queried. |
| Calendar, recurrence, reminders, Google | Managers/checker/parser, calendar/reminder handlers, sync and mutation tests, school and Norwegian-calendar helpers | Deepest domain pass; deletion and false delivery reproduced synthetically. Google API compatibility, token state, quotas, and real recurrence round trips unverified. |
| Conversation, AI, and memory | Connector factory/local/cloud clients/bridge, action schema and draft parsing, user memory/context/localization, matching tests and privacy handlers | Source contracts and failure paths inspected; no inference, provider prices, model quality, prompt-injection success, or remote deletion guarantee evaluated. |
| Console, UX, and accessibility | Server/auth, store, state collector, dashboard, templates, app/login JS, main CSS, frontend/security tests | Static UI review only. Existing modal focus return/trap, landmarks, skip navigation, responsive CSS, and reduced motion acknowledged. No rendered contrast, screen-reader, keyboard, device, or usability certification. |
| Utility and social features | Weather/aurora, calculator, school holidays, polls, birthdays, watchlists, quotes, daily digest, search, browser stub, URL shortener and related handlers/tests | Concrete narrow findings plus product composition opportunities; external data accuracy and live member availability unverified. No claim every branch was exhaustively exercised. |
| Persistence/security/privacy | JSON and secure storage, logger, console sessions/stat/log persistence, auth/bridge/controller tests; local-only member exporter and its tests | Secret/private-data boundaries and concurrency risks inspected from source. No tokens, application data, private env/vault values, personal exports, or logs opened. Not a penetration test or dependency advisory audit. |
| Setup, desktop, dependencies, build/release | Root/utils setup, requirements, macOS/Windows launchers/build scripts, frozen-path tests, CI/release/desktop workflows and open dependency PR diffs | Source/manifests inspected; no installations/builds. Actual frozen assets, signing, notarization, Windows behavior, supported OS versions, and reproducible clean installs require future checks. |
| Deployment/lifecycle/observability | Dockerfile/Compose, Ansible playbook, update/webhook scripts, task lifecycle, counter persistence, health and logging | Static/synthetic design review; no launchd, Docker, SSH/VPS, container, CI run, deployment, backup health, or public origin verified. |
| Testing strategy | conftest, pytest configuration/test documentation, selected domain/console/controller/bridge/storage/routing/lifecycle/desktop tests | Four isolated behavior probes, not the project test suite. No test collection/count claim; future CI acceptance must report actual executed/skipped checks. |

Evidence references use local-checkout paths and line numbers unless explicitly identified as current-master reconciliation. They are tied to the recorded SHA and can move in later revisions. External provider/API choices and platform policy are left for current authoritative-documentation review at implementation feasibility, rather than asserted from memory.

## Delivery and non-actions

- **Deliverable:** this document contains 39 PR-ready proposals, all with title, classification, evidence, problem, concrete change, scope, acceptance, and dependencies. First pass: 26; second pass: 13.
- **Verification performed:** source inspection, live read-only GitHub reconciliation, four synthetic in-memory probes, and document field/dependency/reference/preservation checks. Runtime and production acceptance remain explicitly unverified.
- **Repository mutation:** only this dedicated planning document was created. No application source/tests/configuration/dependencies were changed; no implementation branch, commit, PR, issue, install, build, deploy, service restart, or Discord/calendar/provider side effect occurred.
- **Preservation:** original tracked working changes and CURRENT_STATE were hash-checked against the starting snapshot; .artifacts was not touched. No cleanup or private-data access was performed.
- **Audit trail:** a concise project subnote and today's daily Log entry are recorded in the Hermes Obsidian vault under the user's logging instruction. They are documentation of this audit, not implementation authorization.

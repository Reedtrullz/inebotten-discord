# Inebotten portfolio execution status

Execution authorized 4 October 2026. Local implementation, exact-head CI, external/manual acceptance and deployment are recorded separately. Base master: c0b6a321b3e63e154e466604a9980954c502fb4d.

| Task | Proposal | Title | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | I20 | Hermetic offline verification | Implemented locally | 671 passed, 1 live-provider skip, 17 subtests; separate browser suite 24 passed; four isolation probes passed. Python 3.12.12. |
| 2 | I01 | Preserve events on inconclusive Google lookups | Implemented locally | 29 offline tests passed; uncertain lookup warnings persisted; explicit cancellation/deletion tested. |
| 3 | I02 | One live reminder owner | Implemented locally | 24 ownership, CRUD, routing and READY tests passed; no duplicate load on reconnect. |
| 4 | I04 | Explicit storage failures and schema compatibility | Implemented locally | 158 focused tests; full non-browser suite 711 passed, 1 live skip, 17 subtests; separate browser suite 24 passed. Synthetic migration/downgrade/write-failure receipts. |
| 5 | I06 | Request-owned locale | Implemented locally | 99 routing/locale tests with 17 subtests; interleaved locales, immutable views and exception cleanup verified. |
| 6 | I27 | Forecast validity, location, time, and useful caching | Implemented locally | 198 forecast/dashboard/routing tests passed; unavailable/stale, shared cache, UTC/Oslo/DST and NOAA object/table formats verified. Shutdown integration remains I24. |
| 7 | I28 | Honest currency snapshots | Implemented locally | 110 currency/routing tests, 17 subtests; full suite 740 passed, 1 live skip, 17 subtests. Decimal token precision and finite-rate refusal verified. |
| 8 | I32 | Preserving private onboarding | Implemented locally | Reviewed sidecar 6ad6187 and seven parent RED-to-GREEN corrections. 165 focused tests; full non-browser suite 789 passed, 1 live skip, 17 subtests. Source imports, literal credentials, private writes, provider validation and preserving newline bytes. Real Tk/bundled desktop acceptance remains gated. |
| 9 | I39 | Decide retention and harden the local-only exporter | Planned | — |
| 10 | I05 | Serialize store ownership and snapshot commits | Implemented locally | 176 focused tests; whole suite before final crash probes 747 passed, 1 live skip, 17 subtests. Barrier, process-exit, cancellation, copied-return and stale-revision receipts. Windows CI added; not remotely verified. |
| 11 | I03 | One sender with truthful delivery and reserved quotas | Implemented locally | 107 focused tests; full non-browser checkpoint 762 passed, 1 live skip, 17 subtests. Remote-ID evidence, pending/unknown persistence, cancellation, quota race, safe interval and bounded 429 retry verified. I10 occurrence identity and I24 complete shutdown remain separate. |
| 12 | I07 | Explicit invocation and calendar scope policy | Implemented locally | 26 permission tests and I15 integrated text-safe console audience explanation; 35 browser/security tests. Legacy/orphan scopes preserved; no live data moved. |
| 13 | I09 | Explicit calendar time and kind | Implemented locally | 117 focused tests; full non-browser suite 837 passed, 1 live skip, 17 subtests. All-day, duration, seconds, task refusal, DST gap/fold, Oslo-midnight, before-save interpretation and preserving invalid edits verified. No live account migration. |
| 14 | I12 | Structured AI outcomes and bounded admission | Verified locally | 889 offline tests; 19 subtests; bounded envelope and deadline regressions; no live inference |
| 15 | I15 | Render all console state consistently | Implemented locally | Child 9caeeba reviewed/integrated; three parent RED-to-GREEN consumer corrections (absent card, owned modal snapshot, explicit calendar kind counts). 35 browser/security tests; 89 calendar/policy regressions. |
| 16 | I16 | Endpoint freshness and owned polling timers | Implemented locally | Child 4e11fdf integrated; two parent RED-to-GREEN race corrections for stale 401 and late replies. 42 separate browser/security tests; syntax/fatal lint/diff checks pass. |
| 17 | I21 | Reproducible profiles, typed boundaries, dependency integration | Implemented locally; platform CI / PR reconciliation pending | Child 3d107cb integrated as 391165e; six hash-locked macOS arm64 Python 3.12 profile installs / pip check and resolved-graph advisory receipts reviewed. Fresh parent dev install, 979 offline tests / 1 live skip / 19 subtests, 39 separate browser tests, incremental mypy and fatal lint passed. Ten exact-head dependency PRs reviewed; Linux/Windows clean builds and GitHub reconciliation remain open. |
| 18 | I29 | Maintained school-year data with coverage | Implemented locally | Reviewed child b5d17b5 integrated as 85a6440. Official Oslo/Trondheim 2026–2027 dates rechecked by parent; verified/partial scope and source/expiry explicit. 230 focused holiday/routing tests, 17 subtests; 961 full offline tests, 1 live skip, 19 subtests. Parent ambiguity and explicit-year corrections; saved preferences remain I13. |
| 19 | I33 | Poll lifecycle and vote-safe edits | Implemented locally | Child 083d169 integrated; eight observed parent RED probes fixed replacement/ID-label semantics, bounded TTL previews, preserving schema ownership, real mention/routing and expired console counts. Full non-browser suite 862 passed, 1 live skip, 17 subtests. |
| 20 | I08 | Identity-bound mutations and supported undo | Implemented locally | Exact ID/revision/actor previews, copied publication and bounded persisted local inverse. 151 focused tests; full checkpoint 908 passed, 1 live skip, 19 subtests; 42 separate browser/security tests. Hyphen-ending token regression reproduced/fixed. Google worker remains I11. |
| 21 | I11 | Durable Google intent, retries, and conflicts | Implemented locally | Same-owner outbox and acceptance reconciliation; custom IDs / If-Match checked against official docs. 125 focused tests; 942 full offline tests, 1 live skip, 19 subtests; 39 separate browser tests. Synthetic heartbeat 52.8 ms against 50 ms deadline, 9 ticks. Pending-create edit / unknown-acceptance undo corrections verified; no live Google or shutdown acceptance. |
| 22 | I13 | Deliberate memory, retention, and provider sharing | Implemented locally | Opt-in learning/provider sharing; deliberate facts versus dated topics; known-age expiry; global bounded actual-channel context and self-only local reset. 975 full offline tests, 1 live skip, 19 subtests. Concrete AI dispatch / fallback / policy-revocation probes; persistent-delete failure preserves transient entries. Legacy data and backup/remote exclusions explicit; private full export remains I14. |
| 23 | I17 | Provider-aware actionable readiness | Planned | — |
| 24 | I18 | Bounded logs and useful diagnostics | Planned | — |
| 25 | I19 | Typed command catalogue and non-dispatch routing preview | Planned | — |
| 26 | I22 | One release owner and artifact proof | Planned | — |
| 27 | I24 | Owned resource shutdown and final counters | Planned | — |
| 28 | I30 | Bounded cited research with optional extraction | Planned | — |
| 29 | I14 | Complete self-only private memory exports | Planned | — |
| 30 | I25 | Opt-in notification preferences and digest cards | Planned | — |
| 31 | I10 | Series, occurrences, and recurring delivery identities | Planned | — |
| 32 | I23 | Supported deployment profiles and compatible rollback | Planned | — |
| 33 | I31 | Safe desktop UI and child-process lifecycle | Planned | — |
| 34 | I35 | Consistent data backup and staged restore | Implemented locally | Frozen initialized-owner snapshot, private bounded allowlisted archive, domain/schema/checksum validation, private stage and exact destination review token. Quiescence assertion plus cooperating writer locks; exclusive destination creation and preserved previous / failed partial generations. 60 focused tests; 1002 full offline tests, 1 live skip, 19 subtests. Generated CLI restore/rollback rehearsal; no personal backup or live service operation. |
| 35 | I36 | Previewed ICS exchange | Planned | — |
| 36 | I26 | Authenticated agenda-first calendar workspace | Planned | — |
| 37 | I34 | Organizer-confirmed group planning and RSVP | Planned | — |
| 38 | I37 | Supported bot transport feasibility and adapter | Planned | — |
| 39 | I38 | Allowlisted opt-in workflow recipes | Planned | — |

Ten existing dependency PRs #12–#21 remain under I21 review. No GitHub issues existed at planning refresh.

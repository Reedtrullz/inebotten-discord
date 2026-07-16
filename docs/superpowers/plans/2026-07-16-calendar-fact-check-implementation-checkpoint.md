# Calendar Fact-Check Conversation — Implementation Checkpoint

Date: 2026-07-16  
Branch: `codex/natural-language-actions`  
Planning baseline: `40a7c3a005a474d4952848b89b76d86114407749`

## Ordered implementation commits

1. `f7905c4` — `feat: add calendar fact-check intent contract`
2. `86da0d4` — `feat: route calendar fact-check conversations`
3. `f64b9d8` — `feat: validate calendar schedule evidence`
4. `756ac82` — `feat: add scoped calendar fact-check state`
5. `b4a5092` — `feat: investigate calendar schedules safely`
6. `9fe6fd0` — `feat: handle calendar fact-check flow`
7. `5c45d92` — `feat: complete calendar fact-check confirmations`

The help/NLU/privacy/checkpoint changes are committed by the documentation and
acceptance commit containing this file; use `git log --follow -- <this path>`
for its exact immutable SHA.

## Verified local evidence

- Disk gate: `df -h /System/Volumes/Data` reported `33Gi` available before the
  final full-suite loop, above the required `30Gi` stop threshold.
- Focused calendar fact-check acceptance:
  `.venv312/bin/python -m pytest tests/test_calendar_fact_check_payload.py tests/test_calendar_fact_check_store.py tests/test_calendar_fact_check_routing.py tests/test_calendar_fact_check_evidence.py tests/test_calendar_fact_check_extractor.py tests/test_calendar_fact_check_manager.py tests/test_calendar_fact_check_handler.py tests/test_calendar_fact_check_flow.py tests/test_calendar_fact_check_privacy.py tests/test_help_route_parity.py tests/test_nlu_contract.py -q`
  — `597 passed`.
- Model/deterministic sequence safety after review fix:
  `.venv312/bin/python -m pytest tests/test_action_bridge.py tests/test_utterance_semantics.py tests/test_help_route_parity.py tests/test_nlu_contract.py -q`
  — `1,344 passed`.
- Full non-browser suite:
  `.venv312/bin/python -m pytest -q --ignore=tests/test_console_frontend.py`
  — `6,567 passed, 1 skipped, 734 subtests passed`.
- Browser/frontend suite:
  `.venv312/bin/python -m pytest tests/test_console_frontend.py -q`
  — `24 passed`.
- Production NLU evaluator:
  `.venv312/bin/python scripts/evaluate_nlu.py --corpus tests/fixtures/nlu_contract_v1.jsonl --report .artifacts/nlu-contract.json`
  — `cases=386 overall=1.0000 decision=would-pass`.
- Compile gate:
  `.venv312/bin/python -m compileall -q ai cal_system core features memory utils web_console`
  — passed.
- Fatal flake8 selectors:
  `.venv312/bin/python -m flake8 ai cal_system core features memory utils web_console tests --exclude=.venv312,__pycache__,.git,.pytest_cache --select=E9,F63,F7,F82`
  — passed.
- Dependency integrity: `.venv312/bin/python -m pip check` —
  `No broken requirements found.`
- Diff integrity: `git diff --check` — passed.

## Exact-diff review

The requested `superpowers:requesting-code-review` helper was unavailable in
this session, so the exact baseline-to-HEAD diff was reviewed directly.

- Fixed: the model-side sequence guard initially did not identify the new
  read-only fact-check clause after a proposed write. The bounded NB/NN/EN
  concern frame is now part of the centralized sequence grammar; focused and
  full regressions pass.
- Fixed: an unrelated turn after inquiry TTL could consume the one expiry
  notice. Continuation shape is now checked before looking up expiring state.
- Fixed: scoped direct corrections now accept bounded natural month-name dates
  through the existing `TemporalResolver` as well as canonical numeric dates.
- No remaining actionable P0-P2 finding was identified in the reviewed diff.
- No general cross-domain correction framework was added.

## Safety claims supported by tests

- Initial concerns, selection, search, cancellation, expiry, conflicts,
  insufficient evidence, and current-value verification are read-only.
- Search is bounded to three sanitized public URLs; extraction receives no
  conversation history and deterministic source reduction cannot be overridden
  by model output.
- Direct or supported changes construct only `CALENDAR_EDIT` routes with
  `requires_confirmation=True`.
- Stable target snapshots are revalidated before search, before edit staging,
  and again by the existing mutation-lock confirmation path.
- Failed or unknown confirmation delivery does not clear the non-executable
  inquiry or leave an unseen newly staged edit confirmable.
- Executable pending actions retain routing priority over fact-check inquiries.

## Non-claims

- Not pushed.
- CI was not run or checked.
- Not deployed.
- No live Discord write was performed.
- No live calendar edit was staged or confirmed.
- No live zero-write smoke was run; Task 8 step 8 requires fresh explicit user
  approval.

# Natural-Language Implementation Checkpoint

**Date:** 2026-07-16
**Branch:** `codex/natural-language-actions`
**HEAD:** `27226b290af90f64d65928469a451744ae1c3b82`
**State:** pre-deploy checkpoint; implementation is locally verified and still uncommitted at this snapshot; live runtime is still the pre-overhaul commit

## Outcome

The natural-language overhaul is implemented across deterministic routing,
model-proposed typed actions, temporal parsing, runtime lifecycle, help/docs,
privacy-bounded observability, and release gates. The bot now accepts broad
Bokmål, Nynorsk, and English conversational phrasing while failing closed on
ambiguous, retracted, multi-action, unsupported-temporal, and wrong-store
requests.

The final self-review closed the remaining command-style and safety gaps:

- natural calendar/reminder inventory questions and noun-write frames;
- calendar `put`/`book`/`make` variants with clean titles;
- reminder/watchlist and calendar/reminder completion collisions;
- terminal retractions and statement/meta false positives;
- newline, punctuation, additive-word, and symbol-separated multi-actions;
- current-weather versus dated/clock/weekend forecast requests;
- list-read proposals being reinterpreted as partial searches;
- bounded model-history disclosure, typed proposal validation, and pending
  action isolation;
- reminder startup, rollback, claim, retry, and public-health durability;
- persisted, privacy-safe NLU metrics and browser-visible release evidence.

## Final local proof

- Final pre-deploy non-browser suite: **6,349 passed**, **734 subtests passed**, **1 skipped**.
- Browser-backed console suite: **24 passed**.
- Frozen routing matrix: **2,794 passed**, **514 subtests passed** before the
  final four reminder noun aliases; the later full suite includes those aliases.
- Post-preflight possessive-clear gate: **324 router tests passed** with **286
  subtests**, and **374 NLU contract tests passed**.
- Versioned NLU contract: **375/375 exact intents** (`1.0000`, `would-pass`).
- Critical action recall: **290/290**.
- Labeled payload accuracy: **242/242**.
- Destructive action precision: **10/10**.
- Negative mutation false positives: **0/75**.
- Parser errors: **0/375**.
- `compileall`: pass.
- Fatal `flake8` selectors (`E9,F63,F7,F82`): pass.
- `git diff --check`: pass.
- `pip check`: no broken requirements.
- Deploy contract: **30 focused tests passed** and Ansible syntax check passed;
  exact-SHA deploy/rollback and calendar-only degraded readiness are fail-closed.
- Tracked-token-pattern scan: no matches.
- Evaluator report: `.artifacts/nlu-contract.json`; the report contains hashed
  case IDs, aggregate counts, intents, risks, and booleans only—no raw
  utterances, payload values, names, URLs, or source identifiers.

The only emitted warning is the dependency-level `discord.player` notice that
Python's `audioop` module is deprecated for removal in Python 3.13.

The final preflight correction aligns the advertised possessive forms with the
bounded destructive route: `Kan du tømme kalenderen min?`, the Nynorsk `heile`
variant, and `Could you clear my calendar?` now stage the same confirmation-
required whole-calendar action. Full-match, explicit-action/domain, negation,
meta-question, and trailing-target regressions keep the widening bounded.

## Workspace state

The branch still points to the pre-work HEAD above. No commit, push, deploy,
process restart, or external write was performed. The implementation is a large
task-owned working-tree change: after adding this checkpoint, `git status`
lists 124 paths (96 modified and 28 untracked). Review and commit should be a
separate explicit step.

## Live Discord preflight

The signed-in Discord desktop session has an online direct conversation with
`inebotten`, but read-only VPS/container proof shows that the connected client
is still exact commit `a4b9011ecf6fcbaedf8f4059085be0d73fd67639`, started
2026-06-18. It is 54 commits behind local HEAD, has no source bind mount, lacks
`core/help_registry.py`, and still uses stats schema 2 instead of the
remediation's schema 3. Discord is connected and ready across 10 guilds; overall
health is degraded by Google Calendar synchronization. OpenRouter is configured
and the LM Studio bridge is disconnected, but neither provider was invoked.

No Discord message was sent because any response from this runtime would test
only the old parser. Additive or destructive remediation smoke is unsafe there
because the new pending-action barriers are absent.

## Verification boundaries

The following were not exercised and must not be inferred from local proof:

- no live Discord mention/message was transmitted;
- no live LM Studio or OpenRouter model-provider call;
- no live Google Calendar OAuth or synchronization;
- no live MET weather, CoinGecko, search, or URL-shortener call;
- no deployment or daemon restart; production received read-only version and
  health checks only;
- no commit or remote branch publication.

Recommended next proof requires an explicit package/deploy/restart decision,
then a zero-write DM smoke: tomorrow calendar read; Nynorsk tomorrow reminder
read; calendar-clear request stopping at confirmation; and `Nei takk` producing
`Avbrutt.` with the calendar unchanged.

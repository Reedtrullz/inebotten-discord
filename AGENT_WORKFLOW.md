# Agent Engineering Workflow

> This file is the repository-specific contract for agent-assisted planning and implementation. Keep it aligned with the actual GitHub Project configuration.

## System

- **Product/system:** Inebotten - Norwegian Discord selfbot (AI chat, calendar, reminders, polls, weather, utilities)
- **GitHub Project:** [Inebotten - Engineering Roadmap](https://github.com/users/Reedtrullz/projects/5)
- **Project URL:** https://github.com/users/Reedtrullz/projects/5
- **Repositories covered:**
  - Reedtrullz/inebotten-discord

## Sources of truth

- Repository: implementation reality
- GitHub Issue: canonical work item/problem statement
- Pull request: canonical implementation/change review
- GitHub Project: planning/execution state

Project draft items are not substitutes for real Issues when implementation work is concrete enough to ticket.

## Lifecycle

`Intake -> Ready -> In Progress -> Blocked -> In Review -> Done`

Audit agents create/reuse Issues and place new findings in **Intake**. They do not mark their own findings Ready by default.

## Ready definition

A ticket is Ready only when:

- evidence is adequate, or the ticket is explicitly a bounded Research/Investigation task
- it is not a duplicate
- repository ownership is correct
- scope is coherent and bounded
- acceptance criteria are present
- blockers/dependencies are represented
- Priority, Phase, Effort, Confidence, Category, and Area are set where applicable

## Done definition

A ticket is Done only when the intended outcome is complete, required verification passes, and linked implementation is merged/closed as appropriate.

Duplicate/not-planned/obsolete work should be closed with the correct GitHub reason instead of being mislabeled Done.

## Project fields

- **Status:** Intake / Ready / In Progress / Blocked / In Review / Done
- **Priority:** P0 / P1 / P2 / P3
- **Phase:** Immediate / Foundation / Near-term / Medium-term / Advanced / Stretch
- **Effort:** XS / S / M / L / XL
- **Confidence:** Confirmed / Strong evidence / Needs validation
- **Category:** Bug / Feature / UX / Accessibility / Architecture / Reliability / Performance / Security / Testing / Developer Experience / Infrastructure / Documentation / Research
- **Area:** Calendar / Reminders / AI / Memory / Console / Routing / Storage / Desktop / Deployment / Testing / Tooling / Docs / Cross-cutting / Features
- **Iteration:** execution-selected work only

Do not invent dates or precise hour estimates solely to populate fields.

## Durable labels

Prefer existing repository labels. Standard workflow labels, when configured:

- `agent-found` - finding originated from an automated/agent audit
- `roadmap` - intentionally included in the engineering roadmap

Do not duplicate mutable Project fields as labels.

## Agent-created ticket provenance


Agent-created audit tickets should include a hidden marker similar to:

`<!-- agent-audit:v3 repo=Reedtrullz/inebotten-discord head=<CURRENT_SHA> baseline=<BASELINE_SHA> fingerprint=<STABLE_FINGERPRINT> content_sha256=<CURRENT_CONTENT_HASH> skill=github-agent-engineering mode=<audit|targeted-audit|reconciled> -->`

The visible ticket should also state the revalidated current commit/date where that materially affects the finding, and may record the original evidence baseline separately. Old proposal documents must be revalidated against current canonical HEAD/merged PRs before creating new open Issues.

The stable fingerprint should be deterministic enough to help repeated audits recognize the same finding. Prefer a SHA-256 over a normalized string such as:

`repository | primary subsystem/path | normalized finding slug`

Portable recipe:

```bash
printf '%s' "$NORMALIZED" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])'
```

`content_sha256` should hash the current semantic title + body with all `agent-audit` markers removed and whitespace/newlines normalized. When reconciliation rewrites a ticket to residual scope, refresh `head`, `content_sha256`, and `mode=reconciled`; migrate stale v1/v2 markers when touching the body.

Do not treat the fingerprint as proof that two semantically different findings are identical; still perform normal deduplication.


When migrating legacy v1/FNV-1a tickets, preserve their established finding identity as the fingerprint, record the legacy baseline, and refresh the current v3 content hash. Do not recreate historical findings solely because the fingerprint algorithm changed.

## Issue structure

Implementation-useful Issues normally contain:

1. Summary
2. Evidence
3. Proposed direction
4. Scope
5. Acceptance criteria
6. Dependencies
7. Provenance (agent-created tickets)

Facts, hypotheses, and stretch ideas are distinguished in the body.

## Epics and dependencies

Use GitHub-native relationships where supported. Prefer parent/sub-issues for coherent outcomes, not dumping grounds. Blocking relationships belong on the dependency itself, not only in prose.

## PR rules

- Branches use the `codex/` prefix.
- PRs link the Issue they implement; the Issue moves to **In Review** when the PR opens and **Done** after merge and verification.
- Required checks must pass on the exact PR head. Do not weaken tests or checks to force readiness.
- Do not merge PRs without required-check success and an independent verification pass when the change is risk-bearing.

## Implementation agents

Implementation agents work only on explicitly authorized **Ready**, unblocked work unless a user directly overrides this contract.

They:

- read the full Issue, parent, dependencies, and related PRs
- verify the ticket still matches current code before changing anything
- keep changes within scope
- add/update tests appropriate to the claim
- run relevant checks
- open/link a PR
- use closing keywords for every Issue the merge fully resolves; never for residual/partial scope
- move the work to In Review when appropriate
- after an authorized merge, verify fully resolved Issues are closed and their Project items are Done before reporting completion

If the Issue is materially wrong or obsolete, stop and update/report the ticket instead of forcing an implementation.

## Post-merge lifecycle closure

Completed work should not require a separate manual cleanup prompt. When an agent is present for an authorized merge, it must finish the lifecycle:

- fully resolved Issue → closed as completed
- Project item → Done
- partial Issue → remains open with truthful residual scope
- parent/dependency progress → refreshed when material
- final GitHub state → re-read and verified

Do not delete completed Issues. Preserve them as durable engineering history.

The Project should use native closed-Issue → Done automation when supported, and PRs should use GitHub closing keywords so later manual merges still close the correct Issues automatically.

## Verification rules

- Never trust a successful command return as proof of correctness.
- Re-read resulting GitHub state after meaningful writes (Issues, Project items, fields, views).
- Re-read resulting repository state after file writes.
- Separate source/structural, runtime, live-service, and acceptance claims; each needs its own evidence.
- Preserve unrelated dirty work; never clean or switch preserved checkouts without owner confirmation.

## Automation

Project #5 has six enabled native workflows. Their action targets were verified during the workspace run and their current enabled identities were re-read for this repair:

- Item added to project → Intake.
- Pull request linked to issue → In Progress.
- Item closed → Done.
- Pull request merged → Done.
- Auto-close issue when Status becomes Done.
- Auto-add sub-issues to the project.

These defaults do not establish acceptance. Do not set Done for partial work or close an Issue through a PR unless its full scope is resolved. Item closed → Done can also fire for not-planned/duplicate/obsolete closure; preserve the GitHub state reason and reconcile the resulting Project state so it never claims completed implementation. Re-read Issue and Project state after an authorized merge instead of assuming automation ran.


## Change log

- 2026-10-07: Initial contract created alongside the bootstrap of Project #5, Issue publication of portfolio I01-I39 (#81-#119), and the planning field/view schema.

- 2026-10-07: Route A follow-up repaired native-automation documentation, canonical v3 provenance with legacy identity preservation, and authorized-Ready/post-merge closure duties. Existing PR/check/privacy rules and Project #5 taxonomy remain.

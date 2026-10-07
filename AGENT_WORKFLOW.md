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

Agent-created audit tickets include a hidden marker:

`<!-- agent-audit:v1 repo=<OWNER/REPO> head=<SHA> fingerprint=<STABLE_FINGERPRINT> skill=github-agent-engineering mode=audit -->`

The visible ticket also states the inspected commit/date where that materially affects the finding.

The fingerprint is a deterministic FNV-1a hash over the normalized string `repository | area | normalized-title-slug`. It helps repeated audits recognize the same finding; it does not prove that two semantically different findings are identical, and normal deduplication still applies.

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

## Verification rules

- Never trust a successful command return as proof of correctness.
- Re-read resulting GitHub state after meaningful writes (Issues, Project items, fields, views).
- Re-read resulting repository state after file writes.
- Separate source/structural, runtime, live-service, and acceptance claims; each needs its own evidence.
- Preserve unrelated dirty work; never clean or switch preserved checkouts without owner confirmation.

## Automation

Closed Issues and merged PRs are not auto-moved to Done by automation at this time; planning-state updates are performed deliberately during reconciliation passes.

## Change log

- 2026-10-07: Initial contract created alongside the bootstrap of Project #5, Issue publication of portfolio I01-I39 (#81-#119), and the planning field/view schema.

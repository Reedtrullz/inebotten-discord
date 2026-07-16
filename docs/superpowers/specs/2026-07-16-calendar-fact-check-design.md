# Calendar Fact-Check Conversation Design

**Date:** 2026-07-16
**Status:** Approved in conversation
**Scope:** Natural-language concerns about a known calendar entry's scheduled date/time

## Problem

The utterance `jeg er ganske sikker på at tidspunktet for Rosenborg - Fredrikstad er feil` currently falls through deterministic routing as `AI_CHAT`. If the general AI provider is unavailable or returns no usable text, Inebotten answers with the unrelated generic fallback `Hmm, prøv å si det på en annen måte?`.

The sentence already contains useful intent and entity information:

- the user is raising a calendar correctness concern;
- the suspected field is the scheduled date/time;
- the target is `Rosenborg - Fredrikstad`;
- the user has not supplied a replacement value and has not authorized a write.

Inebotten should acknowledge the matched entry, expose its current value, and offer to investigate with her existing search tools or accept a correction from the user. Any calendar edit remains a separate confirmation-gated action.

The motivating case also proves that `tidspunkt` must cover the full schedule: on 2026-07-16, the [NFF match record](https://www.fotball.no/fotballdata/kamp/?fiksId=8986244) listed Rosenborg - Fredrikstad on 27.07.2026 at 19:00, while the local entry was 26.07.2026 at 09:00.

## Goals

- Recognize bounded Bokmål, Nynorsk, and English statements that a known calendar entry's scheduled date/time may be wrong.
- Resolve the statement against the current calendar without depending on the general AI provider.
- Show the matched entry's current date and time in a concise, natural reply.
- Preserve a short-lived, exact conversation-scoped fact-check inquiry so replies such as `sjekk`, `finn ut`, or `klokka 18` have the required target context.
- Use existing web-search and page-fetch tools when the user asks Inebotten to investigate.
- Present source-backed findings and offer a normal confirmation-gated calendar edit only when the evidence supports one unambiguous replacement date/time.
- Fail closed on target ambiguity, stale calendar state, conflicting evidence, weak evidence, provider failure, and unsupported corrections.

## Non-Goals

- Do not automatically edit a calendar entry from the initial concern.
- Do not treat every statement containing `feil` or `wrong` as a calendar mutation.
- Do not build a general-purpose issue-resolution or arbitrary slot-filling framework in this slice.
- Do not change the title, recurrence, description, or completion state. A search may propose both date and time only when its source-backed schedule differs on both fields; a user-supplied time changes only the time unless the user also supplies a date.
- Do not claim that a source is official unless source policy identifies it as such.
- Do not weaken existing mutation evidence, target-freezing, confirmation, or revalidation gates.

## User Experience

### One exact match

User:

> Jeg er ganske sikker på at tidspunktet for Rosenborg - Fredrikstad er feil.

Inebotten:

> Jeg fant **Rosenborg - Fredrikstad**. Den står oppført 26.07.2026 kl. 09:00.
>
> Vil du at jeg skal sjekke riktig tidspunkt, eller vet du hva det skal være?

This first response is deterministic and available even when the AI provider or search providers are unavailable.

### User asks Inebotten to investigate

User replies with a bounded search continuation such as:

- `sjekk`
- `ja, finn ut av det`
- `kan du undersøke?`
- `look it up`

Inebotten searches for the exact event and its calendar date, prefers trustworthy organizer or competition sources, and returns one of these outcomes.

When one replacement schedule is sufficiently supported:

> NFF oppgir kampen til **27.07.2026 kl. 19:00**.
>
> Skal jeg endre kalenderen fra 26.07.2026 kl. 09:00 til 27.07.2026 kl. 19:00?

The second line is represented as the existing typed `CALENDAR_EDIT` action and uses the existing confirmation card and `@inebotten ja` / `@inebotten nei` flow. The search reply itself never mutates state.

When sources conflict:

> Jeg fant ulike tidspunkter: RBK oppgir 18:00, mens en annen kilde oppgir 17:00. Jeg endrer ikke kalenderen før dette er avklart.

When no trustworthy result exists:

> Jeg fant ikke et tidspunkt jeg kan verifisere godt nok. Vet du hva det skal være?

When search or AI-assisted extraction fails:

> Jeg fikk ikke undersøkt tidspunktet akkurat nå. Kalenderen er ikke endret.

No path returns the generic conversational fallback.

### User supplies the corrected time

While the inquiry is active, replies such as `klokka 18`, `18:00`, or `det skal være kl. 18` are parsed against the frozen calendar date and change only the time. Replies containing a complete supported date and time may propose both fields. Inebotten then stages the same typed `CALENDAR_EDIT` confirmation without performing a web search.

Ambiguous bare twelve-hour English times, invalid local times, and unsupported text request a targeted clarification and do not stage an edit.

### Target ambiguity

- No matching entry: say that no matching calendar entry was found and ask the user to identify it more precisely.
- Several matching entries: show a bounded numbered choice using safe calendar display fields.
- One match: begin the scoped inquiry.

The inquiry must identify one stable calendar item before a follow-up can search or propose a change.

### Cancellation and expiry

`nei`, `avbryt`, `glem det`, `cancel`, and equivalent terminal forms clear the inquiry and answer `Avbrutt.`. An inquiry expires after ten minutes and never survives a process restart. An expired continuation receives a targeted expiry message rather than being reinterpreted as an unrelated command.

## Architecture

### Intent and recognition

Add a read-only `CALENDAR_FACT_CHECK` intent. Its payload has a small typed envelope:

```text
calendar_fact_check:
  action: start | select | search
  field: schedule
  target: string or stable calendar id, for start/search
  number: positive integer, for select
```

Payload validation enforces the action-specific fields: `start` requires a
target, `select` requires only a number, and `search` requires the stable target
from the active inquiry. Extra fields fail closed.

The deterministic recognizer accepts assertion/concern frames only when all of the following are true:

- a calendar schedule field term such as `tidspunkt`, `tid`, `dato`, `schedule`, or `time` is present;
- a bounded uncertainty or incorrectness phrase is present;
- a nonblank target follows a supported connector such as `for`, `til`, or `on`;
- utterance semantics are not quoted-only, negated, hypothetical, reported speech, or cancelled;
- the target resolves to current calendar state or produces an explicit bounded ambiguity response.

Initial supported examples include:

- `jeg tror tidspunktet for <target> er feil`
- `jeg er ganske sikker på at tiden for <target> ikke stemmer`
- `eg trur tidspunktet for <target> er feil`
- `I think the time for <target> is wrong`

The recognizer must reject examples such as:

- `Ola sa at tidspunktet for kampen var feil`
- `hvis tidspunktet er feil, kan du forklare hva som skjer?`
- `tidspunktet for kampen er ikke feil`
- `ordet «tidspunktet er feil»`
- `hvorfor er tidspunktet feil?`

### Scoped inquiry state

Add a small `CalendarFactCheckStore` rather than extending executable pending actions. It is keyed by the existing `ConversationKey` and has two explicit states:

- `choosing_target`, containing two to five bounded candidate snapshots;
- `ready`, containing exactly one selected target snapshot.

Each candidate snapshot stores only:

- stable calendar item id;
- item revision/fingerprint;
- inert display title;
- current date and time;
- field under review (`schedule` in this slice);
- creation and expiry timestamps.

The store is in memory, bounded to one inquiry per conversation, capped at five candidates per inquiry, and capped globally at 1,000 inquiries with deterministic oldest-expiry eviction. It does not replace, confirm, cancel, or otherwise mutate `PendingActionStore` state. Existing confirmation and choice resolution keeps priority over fact-check continuations.

For one match, inquiry creation enters `ready`. For several matches, it enters `choosing_target` and renders a numbered list from the same inert calendar display fields used by confirmation cards. A valid scoped number atomically replaces the candidate tuple with the selected `ready` snapshot and emits the normal current-time question. Search and direct-time continuations are rejected until selection is complete.

The target resolver exposes a read-only calendar snapshot helper so inquiry creation can bind one stable id and revision without manufacturing a partial mutation route. Before presenting any later edit confirmation, the normal calendar target resolver freezes the complete `CALENDAR_EDIT` route again. This detects deletion, title/date/time changes, duplicate identities, and other stale state before a proposal is shown.

### Follow-up routing

The router checks the exact conversation's unexpired inquiry after existing confirmation/choice controls and before generic routing.

- Search continuations produce `CALENDAR_FACT_CHECK(action=search)`.
- Numeric or ordinal continuations in `choosing_target` produce `CALENDAR_FACT_CHECK(action=select)` and cannot be interpreted as poll votes or completion commands.
- Direct time continuations produce a complete typed `CALENDAR_EDIT` route for the stored stable target.
- Cancellation clears only the fact-check inquiry unless an executable pending action has already claimed the message under existing higher-priority rules.
- Unrelated conversation does not consume or alter the inquiry.
- Different guild, channel, user, or DM conversations cannot observe or resolve the inquiry.

### Search and evidence processing

The fact-check handler reuses `SearchManager.search()` with at most three results and, when needed, `BrowserManager.fetch_page_content()` for at most those three normalized result URLs under its existing URL-safety policy and content limits. The query includes the exact inert event title, stored year, and stored date as a search hint rather than a required truth, because the date itself may be wrong. No user memory, conversation history, Discord id, credentials, cookies, or unrelated calendar rows are sent.

Search results are normalized to the existing title, URL, body, provider, fetched time, publication time, freshness, and deep-content fields. A dedicated strict extraction parser accepts zero to three source findings. Each finding contains only:

- one referenced result index that exists in the supplied evidence;
- one canonical `DD.MM.YYYY` candidate date and `HH:MM` candidate time;
- one exact supporting excerpt of at most 160 characters;
- a bounded explanation of at most 240 characters.

The candidate date, candidate time, and supporting excerpt must appear in the referenced source evidence after canonical normalization. Findings with invented indexes, URLs, excerpts, dates, or time values are discarded. A deterministic reducer groups surviving findings by normalized source domain and candidate date/time and returns `supported`, `conflicting`, or `insufficient`.

A checked-in `CalendarSourcePolicy` owns the trusted-domain registry; the model cannot add to or change it. The initial football registry is exactly [`fotball.no`](https://www.fotball.no/), [`eliteserien.no`](https://www.eliteserien.no/), [`rbk.no`](https://www.rbk.no/), and [`fredrikstadfk.no`](https://www.fredrikstadfk.no/), verified against their official public pages on 2026-07-16. Adding another trusted domain requires a code review and source-policy regression test.

An edit may be proposed only when either:

- one domain in the checked-in trusted registry supports the candidate and no other trusted domain conflicts; or
- at least two independent untrusted source domains support the same candidate and no other extracted source conflicts.

An untrusted disagreement does not overrule an otherwise unopposed trusted source, but the user-visible finding mentions that other sites differed. Conflicting trusted sources never produce an edit proposal.

The model may extract and compare evidence, but it cannot declare a domain trusted, invent a URL, or bypass the deterministic agreement rule. If the strict result is invalid, unsupported, conflicting, or unavailable, the handler returns a targeted read-only response and stages no action.

### Mutation boundary

When evidence supports one candidate, the handler constructs a complete `CALENDAR_EDIT` route containing the stable target and only the changed schedule fields. If the supported source date differs, `changes.date` and `changes.time` are included; if only the time differs, only `changes.time` is included. Existing payload validation canonicalizes the values. The existing target freezer binds the current revision and existing confirmation renderer shows the old target details and proposed new schedule.

Execution still requires an explicit confirmation. At confirmation time, existing mutation-lock revalidation must prove that the stable target, stored revision, and proposition are unchanged. A changed or missing item aborts with a targeted stale-state response.

## Error Handling

- Target not found: targeted calendar reply, no inquiry.
- Multiple targets: dedicated scoped fact-check choice state with safe numbered display fields; no guessed item and no executable pending action.
- Missing current time: explain that the entry has no specific time and ask whether to investigate; never call it wrong.
- Inquiry expired: targeted expiry reply; no generic fallback.
- Search providers unavailable: targeted investigation failure; no mutation.
- Browser fetch unavailable: use bounded search snippets if sufficient; otherwise return insufficient evidence.
- AI extraction unavailable or invalid: targeted investigation failure; no mutation.
- Conflicting or weak evidence: present the conflict/limitation with source links; no edit proposal.
- Target changed during investigation: discard the proposal and ask the user to start again.
- Discord send failure: do not leave a newly presented edit confirmable unless the existing delivery-settlement rules mark the confirmation fully delivered.

## Privacy and Security

- Search queries contain only the selected event title and date.
- Discord ids, user memory, other calendar entries, stored descriptions, OAuth material, tokens, and conversation history stay out of search and extraction prompts.
- Visible titles and source text use existing Discord neutralization and length bounds.
- URLs are shown only from normalized search results and remain inert in confirmation bookkeeping.
- Logs record bounded intent/outcome codes, provider names, source-domain hashes or approved public domains, and counts; they do not record raw user utterances, page bodies, query strings, or private calendar descriptions.
- Fact-check state is conversation-scoped, memory-only, TTL-bound, globally capped, and non-executable.

## Testing

Use red-green TDD for each behavior group.

### Recognition and false positives

- Exact reported Bokmål sentence routes to `CALENDAR_FACT_CHECK`, not `AI_CHAT`.
- Equivalent Bokmål, Nynorsk, and English concern frames route correctly.
- Quoted, negated, hypothetical, reported-speech, explanatory-question, and unrelated `feil` sentences remain non-mutating and do not start an inquiry.
- NLU contract fixtures cover all three locales and forbid `CALENDAR_EDIT` on the initial statement.

### Target resolution and state

- Zero, one, and multiple matches produce the specified outcomes; multiple matches remain non-executable until one scoped candidate is selected.
- Inquiry state is isolated by guild, channel, and user and expires after ten minutes.
- A fact-check inquiry cannot confirm, cancel, replace, or inspect an existing executable pending action.
- Changed or deleted calendar targets fail revalidation before a confirmation is presented.

### Follow-ups

- `sjekk`, Nynorsk/English equivalents, direct canonical time, cancellation, unrelated text, and expired replies behave as specified.
- Direct time replies produce a complete confirmation-gated edit and never execute immediately.
- Invalid, ambiguous, DST-impossible, or unsupported time replies clarify without mutation.

### Search evidence

- Mocked trusted-source, two-source agreement, conflict, insufficient evidence, provider failure, page-fetch failure, malformed extraction, invented source index, and unsupported-time cases are covered.
- Search/extraction inputs pass privacy canaries proving that unrelated calendar rows, descriptions, user ids, memory, credentials, and raw conversation history are absent.
- Candidate dates or times not present in cited evidence are rejected.

### Integration and regression

- Message-monitor tests prove the initial deterministic response does not call the AI provider.
- A search continuation invokes bounded search, produces source-backed copy, and stages a normal confirmation only with sufficient evidence.
- Confirmation, cancellation, delivery settlement, mutation locking, and stale-target checks retain their existing behavior.
- Focused tests, the full non-browser suite, browser suite, NLU evaluator, compileall, fatal flake8 selectors, dependency check, and diff check must pass before shipping.

## Acceptance Criteria

- The reported sentence no longer returns generic feedback when the matching entry exists.
- The first response names the matched entry, shows its current date/time, and offers investigation or user-supplied correction.
- `sjekk` can produce a source-backed date/time candidate using existing tools without exposing unrelated private context.
- No calendar change occurs before the existing explicit confirmation flow.
- Ambiguity, weak evidence, provider failure, stale state, and send failure all fail closed with targeted language.
- The behavior is covered in Bokmål, Nynorsk, and English and is included in the production NLU contract.

## Implementation Boundary

The implementation plan should keep this as one focused vertical slice: typed intent and payload, deterministic recognizer, scoped inquiry store, bounded search/evidence manager, monitor/handler integration, confirmation handoff, tests, and release verification. General correction workflows for other calendar fields or domains require a later design.

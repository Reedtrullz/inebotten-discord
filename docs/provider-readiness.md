# Provider-aware readiness

The authenticated console separates configured subsystems and observed outcomes.
Each component carries `enabled`, `required`, `status` (`ready`, `degraded`,
`unavailable`, `stale`, `disabled`), `checked_at`, a stable `reason_code` and an
applicable Norwegian `recovery_action`. Required unavailable components remain
in the aggregate even when their configuration is missing or unsupported.

An OpenRouter-only profile does not need a local bridge; that bridge is disabled
and cannot degrade its readiness. A configured local fallback bridge is optional;
a primary local provider requires its bridge. During partial startup an explicitly
configured bridge endpoint can be diagnosed without assuming a ready AI provider.
No configuration/credentials, prompt, model output, private path or raw provider
error is included in public `/health`, which returns only console/status metadata.
Detailed components are available only through authenticated console routes.

Provider transport/model-catalogue access and actual inference acceptance are
separate evidence. Startup reachability checks never prove a model response.
A real request's structured outcome supplies inference evidence, retaining only
provider, status, acceptance/fallback flags and timestamp. Evidence expires after
15 minutes; future timestamps are unverified. A fallback response does not prove
the primary transport worked. No recurring paid inference request is scheduled.
The current normal request still goes to its configured provider, under the AI
admission/deadline and memory-sharing policies.

Scheduler readiness is based on completed actual reminder-checker iterations,
not a task-alive timer. Failed iterations report degradation; a running checker
whose last successful iteration is more than three minutes old reports stale.
Task timestamps are aware UTC. Cancellation and terminal failure retain the
existing tracked-task lifecycle. Enabled Google synchronization has its own
failure/staleness evidence (30-minute age budget); disabled Google is excluded.
Store health describes local persistence availability and preserving error codes.
This is operational evidence, not a successful notification delivery guarantee,
Google/account acceptance test or a certified desktop release.

Bridge diagnostics use bounded connect/drain/read/close waits and close their owned
stream on error/cancellation. Console polling uses the existing per-endpoint timer
and freshness contract, and renders evidence/recovery strings as text.

Synthetic tests cover local/cloud profiles, disabled optional integrations,
unsupported required configuration, catalogue versus inference evidence,
fallback isolation, stale/future clocks, scheduler work/failure, private error
redaction and the public/detail access boundary. No live provider, Google account,
Discord message or private application store was used for implementation checks.

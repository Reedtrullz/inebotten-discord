# Staged selfbot rollout and dependency review — 6 October 2026

Status: **release execution authorized; live acceptance is pending**. This document
records the approved continuation: finalize calendar compatibility, defer the
optional bot transport, review the stack, and prepare a staged selfbot rollout.
A merge or production restart is a separate action, not an effect of this plan.

## Release execution — 6 October

The owner authorized execution of the recommended review, merge, canary and
promotion sequence. The release candidate is the complete reviewed stack in
original commit dependency order. Integrate it atomically through #72 targeting
master; preserve all historical proposal heads and reconcile their GitHub
dispositions against the resulting master ancestry. Do not deploy intermediate
proposal heads, bypass required checks or weaken branch protection.

The owner selected OpenRouter and identified the allowed human tester as
175509051822702593. The existing selfbot identity remains 1474528156131266815.
Canary invocation is restricted to that tester and test-en 798653999027978320
in guild 484393415149223936, with a separate empty HERMES_HOME and explicit
calendar scope. Provider credentials are configured privately; never include
them in source, evidence receipts or chat. A real accepted model response and
human invocation are required before production promotion.

The existing service degradation was traced to default LM Studio configuration
with neither its bridge nor model endpoint available. Discord and persistence
were healthy at the read-only baseline. Selecting OpenRouter is an owner
configuration decision; provider readiness remains pending until the private
key, accepted inference and canary checks succeed.

## Current disposition

38 proposals are implemented locally within their recorded scope. I36 includes
the accepted event subset and explicit Google/Proton VTODO/timezone limitations;
it does not provide lossless task/timezone round trips. I37 is deferred; its
inert adapter/tests remain preserved. See [calendar compatibility](../CALENDAR_EXCHANGE.md)
and [bot transport disposition](../BOT_TRANSPORT_FEASIBILITY.md).

The human's Sheets and idle launcher trials pass. They do not establish human
live Start/Stop, AI provider acceptance, private-data migration or production
readiness. The original calendar exports, primary WIP and installed service
remain preserved. No test guild message has been sent by this continuation.

## Fresh baseline

On 6 October at 09:33:53 UTC, a bounded, read-only controller doctor authenticated
as the pinned existing selfbot 1474528156131266815 / inebotten, gateway ready,
13 guilds, live/complete. This temporary controller query is not proof that the
separate launchd monitor is ready. The test target previously verified is guild
484393415149223936 and channel 798653999027978320 / test-en; resolve it again at
activation rather than using an old guild cache.

The installed label `local.inebotten.selfbot` points to
`/Users/reidar/Projectos/inebotten/.venv/bin/python -u core/selfbot_runner.py`,
working directory `/Users/reidar/Projectos/inebotten`; KeepAlive restarts failures.
A read-only launchctl snapshot showed it running. Its 09:35:26 UTC public
`http://127.0.0.1:8080/health` response was HTTP 200 but status degraded with no
revision/readiness fields. It is not the candidate and supplies no candidate
release proof. Diagnose configured subsystems before any production promotion;
HTTP 200 or process-alive alone is insufficient.

The primary checkout remains at 6a0e861eafb457fad38428da8edffc6f0fc2b1bf with its
existing WIP. Remote master remains c0b6a321b3e63e154e466604a9980954c502fb4d.
Candidate source is the new follow-up after 9bccbfd; its immutable full head,
Actions runs and artifact hashes are bound in the follow-up draft body. A
prepared archive records its own full commit in `commit_hash.txt` so source
launchd readiness can report the exact candidate revision.

## Dependency review

All 48 published drafts below were freshly read from GitHub and compared to the
local manifest. Every base is its predecessor (root targets master), every base
commit is an ancestor, every diff is nonempty, and whitespace / owned-secret-path
checks pass. Table heads are actual published full heads, not approximate source
checkpoints. Each diff's file ownership was inspected; historical independent
whole-branch and correction reviews remain the source-review receipts.

This is a dependency and diff-contract review, not a new independent line-by-line
review of every historical patch, nor exact-head CI for each intermediate draft.
Final integrated tests validate the combined tree. Do not merge a correction's
prerequisite without its correction or assume early stack heads are release
candidates. Only the complete reviewed tree is eligible for rollout.

| Order | Proposal | Draft | Published head | Disposition |
| --- | --- | --- | --- | --- |
| 1 | I20 | [#24](https://github.com/Reedtrullz/inebotten-discord/pull/24) | `5024f5f7a8f7811180bd9eaee0cb47ef3da7f25a` | Ancestry/diff contract checked |
| 2 | I01 | [#25](https://github.com/Reedtrullz/inebotten-discord/pull/25) | `ef8f38e0ba84f4ec131f40864b6bdfd7435d0323` | Ancestry/diff contract checked |
| 3 | I02 | [#26](https://github.com/Reedtrullz/inebotten-discord/pull/26) | `492c61bae9c608a0b271f4f44c5ec054ed965c07` | Ancestry/diff contract checked |
| 4 | I04 | [#27](https://github.com/Reedtrullz/inebotten-discord/pull/27) | `7a5daf0f15fe3733c53228a49f9a89b9a704f10b` | Ancestry/diff contract checked |
| 5 | I06 | [#28](https://github.com/Reedtrullz/inebotten-discord/pull/28) | `f70140fdfa60f9e4a79a8369e100c4fc843bb85a` | Ancestry/diff contract checked |
| 6 | I27 | [#29](https://github.com/Reedtrullz/inebotten-discord/pull/29) | `886bc06f34184b744bca69b55bf2466fb99217f0` | Ancestry/diff contract checked |
| 7 | I28 | [#30](https://github.com/Reedtrullz/inebotten-discord/pull/30) | `099334395b75aab785de305c71b2b70c134d87ee` | Ancestry/diff contract checked |
| 8 | I05 | [#31](https://github.com/Reedtrullz/inebotten-discord/pull/31) | `9b7fe26e027e6c1f691e239d8648b69eca87d7c3` | Ancestry/diff contract checked |
| 9 | I03 | [#32](https://github.com/Reedtrullz/inebotten-discord/pull/32) | `9f416e35e1d925ba328515285c358b7dcb7d35b6` | Ancestry/diff contract checked |
| 10 | I32 | [#33](https://github.com/Reedtrullz/inebotten-discord/pull/33) | `3d5a0f7987513a4f92f073010f1de07333d3d56b` | Ancestry/diff contract checked |
| 11 | I07 | [#34](https://github.com/Reedtrullz/inebotten-discord/pull/34) | `8b9950ea9514ca9431f9144ba9d693949b142bf5` | Ancestry/diff contract checked |
| 12 | I09 | [#35](https://github.com/Reedtrullz/inebotten-discord/pull/35) | `bead35a2b8fa8c57353c5c7db165bc8edff1749d` | Ancestry/diff contract checked |
| 13 | I15 | [#36](https://github.com/Reedtrullz/inebotten-discord/pull/36) | `63972827aa59e42587c4df7fd26dfde442b8f145` | Ancestry/diff contract checked |
| 14 | I16 | [#37](https://github.com/Reedtrullz/inebotten-discord/pull/37) | `3ad105b086befb1f344f27cb1ece0924380f9776` | Ancestry/diff contract checked |
| 15 | I33 | [#38](https://github.com/Reedtrullz/inebotten-discord/pull/38) | `026998f6f51d342252976f375bed17b0ecd49577` | Ancestry/diff contract checked |
| 16 | I12 | [#39](https://github.com/Reedtrullz/inebotten-discord/pull/39) | `10aee5e081978844ba219ed29e1e199eab8eb03d` | Ancestry/diff contract checked |
| 17 | I08 | [#40](https://github.com/Reedtrullz/inebotten-discord/pull/40) | `dd0418ab197ed4532cdc3b0983686cd58cbcd226` | Ancestry/diff contract checked |
| 18 | I11 | [#41](https://github.com/Reedtrullz/inebotten-discord/pull/41) | `90d2c03c041cbe47a55c3a5e255646ea7402cbc2` | Ancestry/diff contract checked |
| 19 | I29 | [#42](https://github.com/Reedtrullz/inebotten-discord/pull/42) | `bb81d8e68731bb8e6575c5ef90fc24c7d98dd8b3` | Ancestry/diff contract checked |
| 20 | I13 | [#43](https://github.com/Reedtrullz/inebotten-discord/pull/43) | `cf5372db5cf4ef451b78606b70e308b1ef3232dd` | Ancestry/diff contract checked |
| 21 | I21 | [#44](https://github.com/Reedtrullz/inebotten-discord/pull/44) | `6a0601147596704c1e511903120f69a52e0e0f33` | Ancestry/diff contract checked |
| 22 | I35 | [#45](https://github.com/Reedtrullz/inebotten-discord/pull/45) | `4acb5aed26dee6d8554c62eb0b25ba1df9cc4977` | Ancestry/diff contract checked |
| 23 | I17 | [#46](https://github.com/Reedtrullz/inebotten-discord/pull/46) | `571754cb6831758f75577338e7c926b8307f1fa1` | Ancestry/diff contract checked |
| 24 | I19 | [#47](https://github.com/Reedtrullz/inebotten-discord/pull/47) | `f409be16d6cd108be4c52425f2334f301e732bf7` | Ancestry/diff contract checked |
| 25 | I18 | [#48](https://github.com/Reedtrullz/inebotten-discord/pull/48) | `bff0c826a4730765884bc623c4774cb23bfe057d` | Ancestry/diff contract checked |
| 26 | I24 | [#49](https://github.com/Reedtrullz/inebotten-discord/pull/49) | `4ad099b4226358b54ffcf14667eb6c30c08022a7` | Ancestry/diff contract checked |
| 27 | I30 | [#50](https://github.com/Reedtrullz/inebotten-discord/pull/50) | `4ef1963ac77b6ef69eac41c397c60d27b32c810f` | Ancestry/diff contract checked |
| 28 | I14 | [#51](https://github.com/Reedtrullz/inebotten-discord/pull/51) | `09f9963eb5e4fdbc75a6b94d25ca9419fd56e399` | Ancestry/diff contract checked |
| 29 | I25 | [#52](https://github.com/Reedtrullz/inebotten-discord/pull/52) | `aa067536e3cca6d32821f96f9f96728a25ce4ca6` | Ancestry/diff contract checked |
| 30 | I22 | [#53](https://github.com/Reedtrullz/inebotten-discord/pull/53) | `133146d98f386174ef807b63f3534e163ad423cb` | Ancestry/diff contract checked |
| 31 | I23 | [#54](https://github.com/Reedtrullz/inebotten-discord/pull/54) | `9f37219bda9b326474f8b0dba982ccc0311ff0e8` | Ancestry/diff contract checked |
| 32 | I31 | [#55](https://github.com/Reedtrullz/inebotten-discord/pull/55) | `1ee53a1805c0d1b0080a9f220bf248885a88f008` | Ancestry/diff contract checked |
| 33 | I10 | [#56](https://github.com/Reedtrullz/inebotten-discord/pull/56) | `1630cbdcfbc1c50f53fd16217292f75db877c612` | Ancestry/diff contract checked |
| 34 | I36 | [#57](https://github.com/Reedtrullz/inebotten-discord/pull/57) | `4076283e3d5f54eb657dfebd34025f07b3ca7485` | Ancestry/diff contract checked |
| 35 | I34 | [#58](https://github.com/Reedtrullz/inebotten-discord/pull/58) | `127f0fbd39e3c9a23f2d5a589f39336f348fc3e6` | Ancestry/diff contract checked |
| 36 | I26 | [#59](https://github.com/Reedtrullz/inebotten-discord/pull/59) | `b8cbe0ae029ca6d748a196201fc17dabb0b87c81` | Ancestry/diff contract checked |
| 37 | I38 | [#60](https://github.com/Reedtrullz/inebotten-discord/pull/60) | `732aaf62d2f7c33abb2c15517ad3f216766cbd3c` | Ancestry/diff contract checked |
| 38 | I26 | [#61](https://github.com/Reedtrullz/inebotten-discord/pull/61) | `031e8d6ff9faad1b9bfa9a49fe5c690f83009f63` | Ancestry/diff contract checked |
| 39 | I39 | [#62](https://github.com/Reedtrullz/inebotten-discord/pull/62) | `ff7e9364094f0d7cfc52749420e986cdbaf65172` | Ancestry/diff contract checked |
| 40 | I37 | [#63](https://github.com/Reedtrullz/inebotten-discord/pull/63) | `76ea616f4bb6bd6b4eadec8c897bc294f570e591` | Prototype retained; activation deferred |
| 41 | I26 | [#64](https://github.com/Reedtrullz/inebotten-discord/pull/64) | `ec494dc57014e2cbc7dda3a8d325f0e64fb66c95` | Ancestry/diff contract checked |
| 42 | I03/I36 | [#65](https://github.com/Reedtrullz/inebotten-discord/pull/65) | `6c153b12e3a8060edb09c885224ece36a201ac4f` | Ancestry/diff contract checked |
| 43 | I18 | [#66](https://github.com/Reedtrullz/inebotten-discord/pull/66) | `28f72397ca3382cfaef6529377e984a32d7577f6` | Ancestry/diff contract checked |
| 44 | I31 | [#67](https://github.com/Reedtrullz/inebotten-discord/pull/67) | `63528dd5f38c8e78ed02f0d6c4fc054a5129c4d6` | Ancestry/diff contract checked |
| 45 | I31 | [#68](https://github.com/Reedtrullz/inebotten-discord/pull/68) | `654f8ac1e826bf456c42f4b85de16a370d0f20cc` | Ancestry/diff contract checked |
| 46 | I22/I21 | [#69](https://github.com/Reedtrullz/inebotten-discord/pull/69) | `256caca1e8a26379918e6e481de911ccfe9ada68` | Ancestry/diff contract checked |
| 47 | I22/I31 | [#70](https://github.com/Reedtrullz/inebotten-discord/pull/70) | `f4a1b287eae564362e5c9f635ceaa35a0b7babf0` | Ancestry/diff contract checked |
| 48 | I39 | [#71](https://github.com/Reedtrullz/inebotten-discord/pull/71) | `9bccbfdf0f727859a80e7c749de09079a669c977` | Ancestry/diff contract checked |

The new calendar compatibility follow-up targets #71 and preserves all existing
heads. Draft #63 is an ancestor of later fixes: deferring bot activation does not
mean a middle draft can be skipped. If its source must be removed, restack and
revalidate downstream changes before merging. Do not rewrite the preserved
branches or delete their review history as part of deferral.

## Stage A — offline preparation (safe to execute now)

1. Keep the primary checkout and live launchd configuration unchanged. Check at
   least 30 GiB free disk before build/test loops. Use the existing isolated
   portfolio worktree and hash-locked Python 3.12 environment.
2. Run the calendar regressions, full offline suite, separate browser suite,
   fatal lint and incremental type check. Existing reviewed final-source proof
   is 1372 offline / 46 browser / 130 isolated bot checks at 9bccbfd. The follow-up adds
   calendar warning/preview cases; its fresh counts and source are recorded in
   its draft body. No live credentials are present in the offline runner.
3. Commit the follow-up and publish its draft on its predecessor. Dispatch CI
   and native builds at the exact final full head. The calendar handler is a
   frozen asset, so the old f4a1b28 launcher is not proof of this new source.
   Check both platform artifacts through the joint publisher contract; record
   full source, lock digest, manifest, ZIP hashes and frozen smoke receipts.
   An ad hoc macOS signature is distinct from Developer ID/notarization.
4. Prepare one private run-local `git archive` of that committed source, with
   only `commit_hash.txt` added as generated build metadata. Record the archive
   hash and verify every extracted tracked file against the source commit.
   Keep separate empty private directories for canary home and offline rehearsal;
   do not include `.env`, tokens, personal stores, console sessions or raw logs.
5. Rehearse backup/preview/restore, schema compatibility and shutdown using only
   synthetic stores and owned fixture processes. Leave the actual stores intact.

## Stage B — explicitly authorized canary activation

This stage is specified but was not executed by preparing the release.

1. Confirm the complete merged/reviewed candidate and immutable archive hash,
   fresh successful native/CI receipts, current live identity, exact test-en
   channel permissions and the allowed human tester ID. Record a maintenance
   window and preserve the original plist, code/interpreter and configuration
   privately. Never print credentials or expose the console beyond loopback.
2. Provision the candidate's separate locked runtime; install only the required
   selfbot and selected optional integrations, never requirements/bot.lock.
   Set HERMES_HOME to the separate private canary home. Its
   `discord/.env` must be a regular 0600 file in 0700 directories. Configure the
   existing selfbot token locally, invocation allowlist, exact allowed tester
   and test-en channel, an explicit calendar scope and loopback console port.
   Dotenv values override process settings, so inspect effective nonsecret
   settings instead of assuming an environment override wins. The canary data
   must be empty/synthetic: do not copy live reminders, polls, memory or outboxes.
3. Unload the existing owned launchd job so KeepAlive cannot recreate it during
   the test. Confirm its exact process and owned descendants have exited. Do
   not kill unrelated services and do not run both active monitors on the same
   account. This is a controlled service change, not a launcher-only UI check.
4. Only after all live writers are quiescent, capture a private data-only bundle
   with `scripts/inebotten_backup.py create --data-dir ... --archive ...
   --services-stopped`. Validate it in a separate private staging directory with
   `preview`; record generation, owned store list, schemas and checksums. Keep
   credential/config rollback separately private, because bundles exclude them.
   Do not restore personal data merely to test the candidate.
5. Start exactly one owned candidate using the immutable source archive and the
   private canary configuration. Require matching 40-character revision,
   status healthy and readiness ready from its bounded loopback health endpoint,
   plus the pinned live identity. Source metadata and account checks must agree.
   Record degraded subsystem reasons privately and stop on failed readiness.
6. The approved human tester mentions Inebotten in test-en: help/status, one
   synthetic dated event, ICS export/import preview/confirmation, and one
   disposable poll. Inspect visible responses, author/target, timezone warning,
   UID duplicate behavior and unauthorized-channel refusal. Do not create real
   subscriptions, invitations, member exports or cross-channel notifications.
   A controller message authored by the selfbot is not a substitute for a human
   mention trial. Record exact test message IDs/outcomes only after authorized.
7. Stop the candidate and confirm its owned resources close; re-enable the exact
   original launchd job and verify recovery. The old live stores were never used
   by the canary, so this rollback must not change their bytes.

## Stage C — separately reviewed production promotion

After a passing canary, take a fresh quiescent backup and rehearse restoration
into an empty isolated destination. Inspect actual live schema versions before
switching to the new runtime and before any first write. Maximum new aggregate
schema is 4: calendar/reminders 2, polls 3, memory 4, delivery log 1. An old reader
may refuse newly written schemas. A code revert alone must not be used as a
rollback after such writes; stop all writers and review the validated data
restore destination/generation/token. Restoring an older snapshot can discard
post-snapshot changes, so preserve the current generation for reconciliation.

Production promotion requires exact revision/account/readiness, scoped human
flows, confirmed shutdown/recovery and preserved data references. A failed
readiness/canary leaves the candidate stopped and the old service/data preserved.
Do not substitute the Docker deploy CLI for the installed local launchd service.
No VPS, proxy, firewall or global security change is part of this local rollout.

## Evidence boundaries

The ignored owned evidence directory contains current stack JSON, RED/GREEN
logs, whole-suite/browser logs, read-only launchd/health inventories, archive
manifest and exact-head remote receipts. Personal fixture input paths and live
secret/config bytes are not committed. The latest follow-up PR body records
immutable heads/runs after publication, avoiding a self-referential source hash.
All live activation steps above remain unexecuted until explicitly authorized.

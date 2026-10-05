# Portfolio review stack — 5 October 2026

Forty-two nonempty draft PR units preserve the actual ancestry of the 39 implemented proposals. I26 has two follow-up corrections and I03/I36 has one shared outbound-mention correction. Each PR targets the preceding draft branch; review and merge order follows this table. Existing dependency PRs remain separate until their explicit reconciliation receipt. No automatic merge or deployment is requested.

Only the root targets master. Current CI and desktop workflow pull-request filters target master/main; final-stack remote workflows therefore need explicit dispatch at the final full head. Intermediate historical task checks and final integrated receipts are not exact-head CI proof for each draft.

| Order | Proposal | Branch | Source checkpoint |
| --- | --- | --- | --- |
| 1 | I20 | `codex/portfolio-01-offline-harness` | `5024f5f7a8f7811180bd9eaee0cb47ef3da7f25a` |
| 2 | I01 | `codex/portfolio-02-google-lookup` | `ef8f38e0ba84f4ec131f40864b6bdfd7435d0323` |
| 3 | I02 | `codex/portfolio-03-reminder-owner` | `492c61bae9c608a0b271f4f44c5ec054ed965c07` |
| 4 | I04 | `codex/portfolio-04-storage-outcomes` | `7a5daf0f15fe3733c53228a49f9a89b9a704f10b` |
| 5 | I06 | `codex/portfolio-05-request-locale` | `f70140fdfa60f9e4a79a8369e100c4fc843bb85a` |
| 6 | I27 | `codex/portfolio-06-forecast-validity` | `886bc06f34184b744bca69b55bf2466fb99217f0` |
| 7 | I28 | `codex/portfolio-07-currency-snapshots` | `099334395b75aab785de305c71b2b70c134d87ee` |
| 8 | I05 | `codex/portfolio-08-store-writers` | `9b7fe26e027e6c1f691e239d8648b69eca87d7c3` |
| 9 | I03 | `codex/portfolio-09-outbound-delivery` | `9f416e35e1d925ba328515285c358b7dcb7d35b6` |
| 10 | I32 | `codex/portfolio-10-private-onboarding` | `3d5a0f7987513a4f92f073010f1de07333d3d56b` |
| 11 | I07 | `codex/portfolio-11-calendar-access` | `8b9950ea9514ca9431f9144ba9d693949b142bf5` |
| 12 | I09 | `codex/portfolio-12-calendar-time` | `bead35a2b8fa8c57353c5c7db165bc8edff1749d` |
| 13 | I15 | `codex/portfolio-13-console-state` | `63972827aa59e42587c4df7fd26dfde442b8f145` |
| 14 | I16 | `codex/portfolio-14-console-polling` | `3ad105b086befb1f344f27cb1ece0924380f9776` |
| 15 | I33 | `codex/portfolio-15-poll-lifecycle` | `026998f6f51d342252976f375bed17b0ecd49577` |
| 16 | I12 | `codex/portfolio-16-ai-outcomes` | `10aee5e081978844ba219ed29e1e199eab8eb03d` |
| 17 | I08 | `codex/portfolio-17-mutation-previews` | `dd0418ab197ed4532cdc3b0983686cd58cbcd226` |
| 18 | I11 | `codex/portfolio-18-google-outbox` | `90d2c03c041cbe47a55c3a5e255646ea7402cbc2` |
| 19 | I29 | `codex/portfolio-19-school-calendars` | `bb81d8e68731bb8e6575c5ef90fc24c7d98dd8b3` |
| 20 | I13 | `codex/portfolio-20-memory-controls` | `cf5372db5cf4ef451b78606b70e308b1ef3232dd` |
| 21 | I21 | `codex/portfolio-21-dependency-profiles` | `6a0601147596704c1e511903120f69a52e0e0f33` |
| 22 | I35 | `codex/portfolio-22-backup-restore` | `4acb5aed26dee6d8554c62eb0b25ba1df9cc4977` |
| 23 | I17 | `codex/portfolio-23-provider-readiness` | `571754cb6831758f75577338e7c926b8307f1fa1` |
| 24 | I19 | `codex/portfolio-24-command-catalogue` | `f409be16d6cd108be4c52425f2334f301e732bf7` |
| 25 | I18 | `codex/portfolio-25-diagnostic-logs` | `bff0c826a4730765884bc623c4774cb23bfe057d` |
| 26 | I24 | `codex/portfolio-26-owned-shutdown` | `4ad099b4226358b54ffcf14667eb6c30c08022a7` |
| 27 | I30 | `codex/portfolio-27-bounded-research` | `4ef1963ac77b6ef69eac41c397c60d27b32c810f` |
| 28 | I14 | `codex/portfolio-28-private-memory-export` | `09f9963eb5e4fdbc75a6b94d25ca9419fd56e399` |
| 29 | I25 | `codex/portfolio-29-notification-preferences` | `aa067536e3cca6d32821f96f9f96728a25ce4ca6` |
| 30 | I22 | `codex/portfolio-30-release-artifacts` | `133146d98f386174ef807b63f3534e163ad423cb` |
| 31 | I23 | `codex/portfolio-31-deployment-rollback` | `9f37219bda9b326474f8b0dba982ccc0311ff0e8` |
| 32 | I31 | `codex/portfolio-32-desktop-lifecycle` | `1ee53a1805c0d1b0080a9f220bf248885a88f008` |
| 33 | I10 | `codex/portfolio-33-recurring-occurrences` | `1630cbdcfbc1c50f53fd16217292f75db877c612` |
| 34 | I36 | `codex/portfolio-34-calendar-exchange` | `4076283e3d5f54eb657dfebd34025f07b3ca7485` |
| 35 | I34 | `codex/portfolio-35-group-planning` | `127f0fbd39e3c9a23f2d5a589f39336f348fc3e6` |
| 36 | I26 | `codex/portfolio-36-calendar-workspace` | `b8cbe0ae029ca6d748a196201fc17dabb0b87c81` |
| 37 | I38 | `codex/portfolio-37-workflow-recipes` | `732aaf62d2f7c33abb2c15517ad3f216766cbd3c` |
| 38 | I26 | `codex/portfolio-38-agenda-date-order` | `031e8d6ff9faad1b9bfa9a49fe5c690f83009f63` |
| 39 | I39 | `codex/portfolio-39-manual-member-export` | `ff7e9364094f0d7cfc52749420e986cdbaf65172` |
| 40 | I37 | `codex/portfolio-40-supported-bot-adapter` | `76ea616f4bb6bd6b4eadec8c897bc294f570e591` |
| 41 | I26 | `codex/portfolio-41-agenda-description` | `ec494dc57014e2cbc7dda3a8d325f0e64fb66c95` |
| 42 | I03/I36 | `codex/portfolio-42-outbound-mentions` | `17907fdb2f86d780bdc6341c41e1869ea56c3c29` |

The final draft also includes current execution/dependency/review documentation. Its published full head and workflow runs are recorded after creation. The corrected source checkpoint is `17907fdb2f86d780bdc6341c41e1869ea56c3c29`; local receipt logs remain in the ignored worktree evidence directory.

Remaining acceptance owners: user-selected spreadsheet readers (I39), two real calendar clients (I36), supported target-platform CI and dependency reconciliation (I21), Windows/native build/signing/human release acceptance (I22/I31), and production bot factory/scheduler/test-guild/live proof (I37). These drafts do not certify those gates.

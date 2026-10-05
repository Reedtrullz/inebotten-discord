# Dependency PR disposition receipts — 5 October 2026

Read-only GitHub refresh: all ten existing dependency PRs remain open and BEHIND master, with the same exact heads as the earlier review. Their Test and Validate checks passed on 4 July; CodeQL was NEUTRAL. Those old checks do not validate this portfolio. No existing PR is merged or closed by this disposition record.

The candidate incorporates nine update intentions through explicit Python 3.12 hash locks; #14 uses the maintained successor instead. After the integrated graph has exact-head platform CI, the nine superseded update candidates and the successor replacement can be reconciled with a link to that accepted graph. Public closure remains a separate action.

| Existing PR | Reviewed full head | Candidate graph | Disposition and evidence |
| --- | --- | --- | --- |
| [#12](https://github.com/Reedtrullz/inebotten-discord/pull/12) | `5ae7c4131c363273ee62cbc04dac0d8315a2621a` | bandit 1.9.4 | Development scanner graph; Bandit comparison below. |
| [#13](https://github.com/Reedtrullz/inebotten-discord/pull/13) | `e045c31491c2c83025b101a2679781476c9ac3be` | googlesearch-python 1.3.0 | Optional search graph; bounded subprocess/provider contract checks. |
| [#14](https://github.com/Reedtrullz/inebotten-discord/pull/14) | `fb9f69d121fbb816778b1227a260cd754495dcea` | ddgs 9.16.0 | Decline the legacy package update as submitted; successor adapter and optional lock replace it. |
| [#15](https://github.com/Reedtrullz/inebotten-discord/pull/15) | `45cc4e834e518796d1433bca9fae62e06a8bf3a8` | aiohttp 3.14.3 | Core HTTP graph; owned-client, bounded stream and cancellation regressions. |
| [#16](https://github.com/Reedtrullz/inebotten-discord/pull/16) | `d3568d74091965a8ac254d2b3694894e25048d21` | tavily-python 0.8.4 | Optional search graph; actual SDK subprocess and timeout boundaries. |
| [#17](https://github.com/Reedtrullz/inebotten-discord/pull/17) | `ec70e1ae20fc9a4e772d33512bf11ede732b9ba6` | pylint 4.1.2 | Development diagnostics; scoped error comparison below. |
| [#18](https://github.com/Reedtrullz/inebotten-discord/pull/18) | `c90ffc1f173374b79854f96a9ea15582bc14af96` | pytest 9.1.1 | Development graph; isolated whole suite and separate browser suite. |
| [#19](https://github.com/Reedtrullz/inebotten-discord/pull/19) | `1f632c7ff23f0b9ceb160f5f9860550c6d359987` | requests 2.34.2 | Core graph; optional Google/search consumers share this pin. |
| [#20](https://github.com/Reedtrullz/inebotten-discord/pull/20) | `0fcb48dfa1b03aee0db114a8870e740cb5b97b74` | google-auth-oauthlib 1.5.0 | Optional Google graph; synthetic reconciliation/OAuth boundaries only. |
| [#21](https://github.com/Reedtrullz/inebotten-discord/pull/21) | `28842d07f5925bc612cac2e654d43b8a75022d92` | simpleeval 1.0.8 | Core and separate bot graph; calculator and bot domain checks. |

## Local graph and scanner evidence

At fixed source `76ea616f4bb6bd6b4eadec8c897bc294f570e591`, the integrated offline selfbot suite passed 1,349 tests and 23 subtests; three explicit skips and one separately executed browser case. The separate browser suite passed 46 tests. A fresh bot lock install passed 17 adapter contracts, 108 shared-domain checks, dependency compatibility and a point-in-time PyPI advisory query with zero known findings. A fresh desktop lock install checked all 75 installed packages as compatible and built the fixed macOS arm64 source with actual frozen smoke. Earlier clean macOS profile receipts remain separate from the current parser/bot additions. Linux/Windows platform installs and remote CI are not inferred from these local results.

Bandit 1.9.4 was run on the same allowlisted source directories in both an inert archived master snapshot (`c0b6a321b3e63e154e466604a9980954c502fb4d`) and current source: `python -m bandit -r ai cal_system core features memory utils web_console scripts -f json`. It reported 100 baseline findings versus 138 current findings, with no scan errors. Both commands exit 1; neither is a passing security gate. The single medium B104 finding remains an existing wildcard-host string comparison that converts the readiness target to loopback, rather than a new listener binding. The two B105 findings are a placeholder example token and a key name.

| Bandit finding | Baseline | Current | Interpretation |
| --- | --- | --- | --- |
| B311, low | 63 | 63 | Existing non-cryptographic random use; no change in this scanner count. |
| B110, low | 13 | 18 | Broad cleanup/fallback catches, including owned service cleanup and preserving unresolved sync evidence; not blanket suppression. |
| B404, low | 6 | 11 | Additional explicit subprocess owners. |
| B603, low | 8 | 17 | Argument-list subprocess calls; review their executable/argument inputs and deadline/environment constraints. |
| B112, low | 4 | 4 | Existing parse/unsupported-row continuation paths. |
| B607, low | 3 | 5 | PATH-based git/system programs, including build/deploy tooling; trusted operator environment remains part of their contract. |
| B101, low | 0 | 17 | New verification-script assertions; counts are not application vulnerability proof. |
| B105, low | 2 | 2 | Example placeholder and credential key label. |
| B104, medium | 1 | 1 | Existing readiness host normalization described above. |

Pylint 4.1.2 uses an explicitly recorded `--errors-only --output-format=json` diagnostic invocation. The new result/storage/sender boundaries report no errors. The same invocation on the existing `core/rate_limiter.py` and `memory/localization.py` reports zero errors (exit 0) both on archived master and current source; the machine-readable receipts are retained with the local evidence. This is scoped diagnostic evidence; current CI continues to use fatal flake8 and incremental mypy, not a fictitious pre-existing Pylint gate.

Machine-readable exact-head check responses, scanner JSON and lock install/test/build logs are in the ignored worktree evidence bundle `.superpowers/sdd/2026-10-04-inebotten-complete-portfolio/`; no member data, prompts, tokens or live configuration are included.

After final review corrections at `17907fdb2f86d780bdc6341c41e1869ea56c3c29`, the whole offline suite passed 1,357 tests and 23 subtests (three explicit skips and one separate browser case); the clean bot profile passed 130 combined checks. All 46 browser cases have passing evidence, including the description flow after a corrected test locator. The source was rebuilt for macOS arm64 with actual frozen smoke. The dependency graph is unchanged by these source corrections.

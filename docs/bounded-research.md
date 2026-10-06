# Bounded research and source evidence

SearchManager retains Tavily (when configured), Google and DuckDuckGo fallback
order, but all attempts share one absolute monotonic deadline, capped at eight
seconds. Each attempt has at most three seconds and no retry loop. Two workers
are admitted with no waiting queue. A timed-out or cancelled waiter does not
release a native worker's admission slot until that work actually finishes.
Closure retains/drains the same work through I24's owned-resource composition.

Real SDK calls run in short-lived Python subprocesses inside these workers.
The subprocess timeout kills and joins the child, including SDK-internal
threads. Underlying SDK network timeouts are also set. Each child has a private
temporary home, a small allowlisted environment, no inherited Discord/cloud
credentials, no account stores or proxy/netrc settings, and bounded JSON stdio.
Only the Tavily key needed for that request is passed through stdin, never an
argument, log or persisted file. Temporary homes are removed after success or
timeout. The offline harness refuses real SDK subprocesses before spawning and
the worker independently honors the offline flag. Synthetic transport seams
exercise process cleanup without any live provider calls.

The optional-search hash profile remains required for real SDKs. Missing
packages have an actionable profile message. This is local source/Python
acceptance; frozen launchers currently report the research worker unavailable.
I31 must provide and verify a dedicated frozen worker entrypoint before bundled
research can be certified. No GUI process is spawned as a Python fallback.

Research cards carry source URL/title, `url_only`, `snippet` or `extracted`,
optional publisher-provided date, aware UTC fetch time, provider and bounded
text. Google URLs have no page text. A long snippet is still a snippet. Tavily
raw content is provider-reported extracted text, not proof of a local page fetch.
Missing publication dates remain missing. Fetch time never establishes currency.
Partial provider failures and busy/unavailable outcomes are explicit.

Evidence enters the AI prompt as bounded JSON under `untrusted_evidence`, with
instructions to reference sources beside updated claims. A conservative reply
guard requires every paragraph to cite known URLs with text; URL-only results
cannot support a factual reply. Unknown/missing references or model action
drafts withhold that reply. Research never enters the action-draft path. This
checks reference consistency, not source reliability or claim entailment.

Anonymous public text extraction is separately opt-in with
`PUBLIC_PAGE_EXTRACTION_ENABLED=true`. Browserbase credentials alone do not
enable extraction: its existing session-metadata stub remains inert. The public
extractor shares the research deadline and owns at most two fetches and two DNS
workers. It accepts ordinary HTTP/HTTPS ports and refuses credentials in URLs,
private/reserved/multicast addresses, local names and mixed public/private DNS.
Validated DNS addresses are returned directly to the connector; no second
resolution can switch the connection to a private address. DNS workers keep their
slots when a caller stops waiting.

Redirects are manual (at most three), with destination checks on every hop and
DNS checks at every connection. TLS verification stays enabled. Cookies,
environment proxies/netrc and automatic decompression are disabled. Only UTF-8
HTML/plain text, at most 256 KiB of response bytes and 6,000 text characters, is
accepted. Script/style/head/iframe content is excluded by a stdlib HTML parser;
page scripts never execute. Session/connector ownership is closed on failure,
timeout or cancellation. No logged-in browsing, paywall bypass or browser
automation is provided. This extractor is a text subset, not a general browser.

Primary source review covered [aiohttp's client contract](https://docs.aiohttp.org/en/stable/client_reference.html),
[DDGS 9.16.0](https://github.com/deedy5/ddgs/blob/v9.16.0/ddgs/ddgs.py),
[Google search's provider implementation](https://github.com/Nv7-GitHub/googlesearch/blob/master/googlesearch/__init__.py),
and the hash-matched [Tavily Python 0.8.4 artifact](https://pypi.org/project/tavily-python/0.8.4/).
The SDK call chain has network timeouts and executor work, so a caller timeout
alone is insufficient evidence of provider cleanup. Fixture tests count retained
workers, exercise child timeout/environment boundaries, distinguish source kinds,
check actual AI dispatch/citations, and reject private redirects, mixed DNS,
wrong media types, compression and oversized bodies. No live provider, credential
or user page was fetched as acceptance evidence.

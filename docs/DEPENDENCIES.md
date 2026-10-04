# Python dependency profiles

The source-of-truth inputs use reviewable lower bounds; generated `.lock` files pin the complete Python 3.12 resolution and include SHA-256 hashes for every allowed distribution artifact. Lock generation uses uv universal resolution, so platform markers are retained in one cross-platform candidate graph. The committed lock files, rather than a live resolver, are the install inputs for CI, containers, setup instructions, and desktop builds.

## Profiles

| Profile | Input | Contents | Install command |
|---|---|---|---|
| Production | `requirements.txt` | Core runtime only; no Google, web-search, or Browserbase packages | `python -m pip install --require-hashes -r requirements/prod.lock` |
| Development and offline tests | `requirements-dev.txt` | Production, test/lint/audit tools, and Google libraries used by existing collection-time tests | `python -m pip install --require-hashes -r requirements/dev.lock` |
| Desktop build | `requirements/desktop.in` | Production, all optional profiles, and PyInstaller; `pywin32` is conditional on Windows | `python -m pip install --require-hashes -r requirements/desktop.lock` |
| Optional Google Calendar | `requirements/optional-google.in` | Google API and OAuth client libraries | `python -m pip install --require-hashes -r requirements/prod.lock -r requirements/optional-google.lock` |
| Optional search | `requirements/optional-search.in` | Tavily, Google search, and `ddgs` providers | `python -m pip install --require-hashes -r requirements/prod.lock -r requirements/optional-search.lock` |
| Optional browser | `requirements/optional-browser.in` | Browserbase SDK | `python -m pip install --require-hashes -r requirements/prod.lock -r requirements/optional-browser.lock` |

Install an optional profile alongside production when the corresponding capability is needed. Optional providers are imported from their feature methods, so the core application remains importable without those distributions. Missing search providers log the exact optional profile command. Google Calendar remains unconfigured when credentials are absent. The Browserbase package alone does not enable page extraction: `BrowserManager.fetch_page_content` deliberately returns no content until an extraction implementation exists. Installing an SDK does not claim that a provider has been configured or contacted.

The DuckDuckGo distribution was renamed from `duckduckgo-search` to `ddgs`; the search adapter and optional profile use the successor package and its `ddgs` import. This is the reason the open update in dependency PR #14 is not accepted as submitted.

## Refresh and review

Use Python 3.12 for lock resolution. Review input changes, the full resolved graph, platform markers, source release metadata, and the generated lock diff together. Regenerate one profile at a time; `--universal` retains OS and implementation markers, while `--generate-hashes` emits hashes for permitted artifacts. Do not treat a successful macOS installation as Windows or Linux acceptance.

```sh
uv --no-config pip compile --refresh --no-progress --python-version 3.12 --universal \
  --generate-hashes --default-index https://pypi.org/simple \
  -o requirements/prod.lock requirements.txt
uv --no-config pip compile --refresh --no-progress --python-version 3.12 --universal \
  --generate-hashes --default-index https://pypi.org/simple \
  -o requirements/dev.lock requirements-dev.txt
uv --no-config pip compile --refresh --no-progress --python-version 3.12 --universal \
  --generate-hashes --default-index https://pypi.org/simple \
  -o requirements/desktop.lock requirements/desktop.in
for profile in optional-google optional-search optional-browser; do
  uv --no-config pip compile --refresh --no-progress --python-version 3.12 --universal \
    --generate-hashes --default-index https://pypi.org/simple \
    -o "requirements/$profile.lock" "requirements/$profile.in"
done
```

Verify every profile in a fresh Python 3.12 environment with `python -m pip install --require-hashes -r requirements/<profile>.lock`. Run the dependency contract suite through `scripts/run_offline_tests.py`, then type-check its three incremental Protocol boundaries with mypy. CI runs those installs on Ubuntu, macOS, and Windows; local evidence records only the host platforms actually exercised.

For a current resolved-graph check, install the development profile and run `python -m pip_audit --strict` (or `pip-audit --strict`). The result is a point-in-time query against the selected advisory service, not a guarantee that the graph is free from unknown issues. Keep the exact command, service, timestamp, and machine-readable output with the lock digest. Do not make vulnerability claims from stale base-branch files or package-name-only searches.

## Source references

- [uv lock compilation and hash generation](https://docs.astral.sh/uv/pip/compile/) and [universal resolution](https://docs.astral.sh/uv/concepts/resolution/).
- [PyPI `duckduckgo-search` rename notice](https://pypi.org/project/duckduckgo-search/) and [the `ddgs` release metadata](https://pypi.org/project/ddgs/).
- [aiohttp 3.14.3 release metadata and Python support](https://pypi.org/project/aiohttp/3.14.3/).
- [PyPA `pip-audit` behavior and vulnerability services](https://github.com/pypa/pip-audit) and [Python Packaging Advisory Database](https://github.com/pypa/advisory-database).

The generated candidate lock graph and advisory results for this change are recorded in the ignored worktree evidence bundle at `.superpowers/dependencies/`; that bundle records the observed date and host limits.

# Inebotten control runbook

`scripts/inebotten_ctl.py` is a one-shot, live-state control surface for the
local Discord account. It is intentionally narrow: read operations query the
gateway or Discord REST API, while `send` is the only write command.

## Safety contract

- The connected identity must be account `1474528156131266815`; a mismatch is
  a hard failure.
- Token lookup is the environment, then the private Hermes `.env` when
  `HERMES_HOME` is explicitly configured, otherwise the private project
  `.env`, with the other private file as fallback. Symlinks, FIFOs,
  non-regular files, and group/world-readable files are rejected. The token is
  never printed.
- Read targets use exact IDs/names first and unique fragments otherwise.
  Ambiguous targets fail closed. Writes require exact IDs or exact names.
- `send` requires the exact current-request text plus `--confirm`, or
  `--dry-run` for a non-sending preview. `INEBOTTEN_WRITE_ALLOWLIST` can
  restrict writes to comma-separated `guild_id:channel_id` pairs.
- REST requests have a 15-second timeout, at most two retries for transient
  failures/429/5xx, bounded pagination, and a 60-second command budget.
  A message send is never retried after an unknown response.
- Write audit records are append-only JSONL under
  `~/.hermes/discord/data/control/audit.jsonl`; message text is represented by
  a SHA-256 digest rather than stored in the audit trail.

## Machine-readable output

Use `--format jsonl`. Every row includes source, UTC query time, freshness,
and live identity metadata. The final `complete` record is authoritative for
success and completeness; partial rows alone never prove a successful result.
`search` is marked `index_may_lag`; direct history
and REST/gateway reads are marked `live`.

```bash
.venv/bin/python scripts/inebotten_ctl.py status --format jsonl
.venv/bin/python scripts/inebotten_ctl.py messages <guild> <channel> --limit 25 --format jsonl
.venv/bin/python scripts/inebotten_ctl.py send <guild> <channel> "<text>" --dry-run --format jsonl
```

## Service checks

The local launchd label is `local.inebotten.selfbot`. Check process state and
the redacted/private log before claiming the bot is healthy:

```bash
launchctl print gui/$(id -u)/local.inebotten.selfbot
stat -f '%Sp %OLp %N' ~/.hermes/discord/data/bot.log
tail -100 ~/.hermes/discord/data/bot.log
```

The web console has bounded request reads and active connections. It should
bind to loopback for local use; non-loopback binds force Secure cookies. The
Hermes bridge binds to loopback by default. If it must be reachable from a
network peer, set `HERMES_BRIDGE_API_KEY`; non-loopback startup without that
key fails closed.

## Verification gates

Offline regression tests must pass before a live check:

```bash
.venv/bin/python -m pytest -q tests/test_inebotten_ctl.py tests/test_bridge_security.py tests/test_logger_hardening.py tests/test_console_server.py
.venv/bin/python -m py_compile scripts/inebotten_ctl.py ai/hermes_bridge_server.py web_console/server.py
```

Only then run a bounded, read-only live preflight:

```bash
.venv/bin/python scripts/inebotten_ctl.py doctor --format jsonl --rate-limit-info
```

An empty search is not proof of absence, and a green local test suite is not
proof that Discord currently accepts the token or that the public service is
reachable.

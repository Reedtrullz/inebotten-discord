---
name: inebotten
description: Use when the user asks about the inebotten Discord selfbot — which servers/channels it is in, what messages exist, or wants to read, search, or send Discord content as the inebotten account. Also use to start/stop/check the local bot service or to keep Discord data current.
---

# Inebotten Discord Selfbot

Local, launchd-managed Discord selfbot for the user account **inebotten** (ID `1474528156131266815`), repo at `/Users/reidar/Projectos/inebotten`. The bot runs 24/7 for presence + web console; Codex drives it with `scripts/inebotten_ctl.py`.

## Freshness rule (critical)
Always query live state via `scripts/inebotten_ctl.py`. Never answer guild/channel/message questions from logs, memory, or old Hermes sessions — stale logs have shown wrong guild counts (0 vs 10).

## Quick commands
Run from the repo root with `.venv/bin/python` (discord.py-self 2.1.0 is installed there):

```bash
.venv/bin/python scripts/inebotten_ctl.py guilds          # name, id, member count
.venv/bin/python scripts/inebotten_ctl.py status          # identity + guild count
.venv/bin/python scripts/inebotten_ctl.py channels <guild>
.venv/bin/python scripts/inebotten_ctl.py messages <guild> <channel> --limit 20
.venv/bin/python scripts/inebotten_ctl.py messages <guild> <channel> --embeds     # embed-only bot channels
.venv/bin/python scripts/inebotten_ctl.py search <guild> <query> --limit 25
.venv/bin/python scripts/inebotten_ctl.py search <guild> <query> --channel <ch> --before 2026-02-01 --after 2025-12-01 --embeds  # windowed channel-scoped search
.venv/bin/python scripts/inebotten_ctl.py threads <guild> [forum-fragment]   # forum posts (archived)
.venv/bin/python scripts/inebotten_ctl.py thread <thread-id> --limit 200     # read a forum post + replies
.venv/bin/python scripts/inebotten_ctl.py member <guild> <user-id>           # one member: nick, roles, joined (REST)
.venv/bin/python scripts/inebotten_ctl.py roles <guild>                      # roles with position + permission bits
.venv/bin/python scripts/inebotten_ctl.py pins <guild> <channel>             # pinned messages
.venv/bin/python scripts/inebotten_ctl.py guild <guild>                      # tier, boosts, verification, vanity URL
.venv/bin/python scripts/inebotten_ctl.py dm-channels                       # DM / group DM list (user-only endpoint)
.venv/bin/python scripts/inebotten_ctl.py threads-search <guild> <channel> <query>  # active + archived threads
.venv/bin/python scripts/inebotten_ctl.py send <guild> <channel> "<text>"   # write op: only on explicit user request
```

`<guild>` / `<channel>` accept a name fragment or ID. Output is tab-separated: `timestamp, message_id, guild, channel, author, content`.

## Forum posts & threads (e.g. #community-ideas)
Forums are channel type 15; `messages` does NOT work on them (`ForumChannel` has no `history`).
- `threads <guild> <forum>` lists archived posts (id, name, archive time). Active posts are usually NOT listed — this token gets `403` from `/guilds/{id}/threads/active` and the gateway thread cache is typically empty.
- Discovery for active posts: `threads-search <guild> <channel> <query>` returns active AND archived threads in one channel (undocumented `/channels/{id}/threads/search`, verified working 2026-08-02; output has `total_results` + `archived` flag). Fallback: `search <guild> <query>` — forum posts appear as hits, and the output's channel id IS the thread id.
- `thread <thread-id>` fetches the post + all replies via REST, chronological, same tab-separated shape. Any channel/thread id works; fetch thread metadata with `GET /channels/{id}` to resolve unknown ids.
- Archived-thread pagination gotcha: `before` is the ISO `thread_metadata.archive_timestamp`, not a message id.
- Announcement/bot channels (type 5, e.g. mainnet-info) are **embed-driven**: `messages`/`search`/`thread` show nothing without `--embeds`. `GET /channels/{id}/messages/{mid}` (single-message fetch) returns **403 on type-5 channels** (observed 2026-08-02) — use history windows (`messages ... --before`-style pagination or `search --before/--after`) instead.

## Library pins (discord.py-self 2.1.0 — NOT discord.py)
- No `Intents`, no `View`/`ui`/callbacks, no `AutoShardedClient`, no `Guild.active_threads`, no `GuildSearchResult`, no `Client.search`.
- Search is `Guild.search()`/`Channel.search()` returning an async iterator of `Message`s; each message carries `total_results`/`hit`/`doing_deep_historical_index`; reactions in results are incomplete.
- `send()` has no `embed`/`embeds`/`components` params — user messages can't carry embeds; the embeds route is `Webhook.from_url(url).send(embed=...)` (no bot auth).
- Forum: `ForumChannel.create_thread()` + `archived_threads()`; `history`/`send` raise AttributeError. Thread archive/lock via `thread.edit(archived=True, locked=True)`.
- `Message.edit()` returns a new Message and only edits content/attachments. Renames: `fetch_audit_logs→audit_logs()`, `fetch_webhooks→webhooks()`, `fetch_vanity_invite→vanity_invite()`, `Webhook.from_partial→partial()`, `Webhook.execute→send()`, `permissions_for` lives on channels.
- `guild.member_count`/`guild.members` partial without chunking; REST `GET /guilds/{id}/members` → 403 50001, but `GET /guilds/{id}/members/{uid}` works (ctl `member`).

## Service management
- launchd label: `local.inebotten.selfbot`; plist: `~/Library/LaunchAgents/local.inebotten.selfbot.plist` (KeepAlive).
- Reload after code changes: `launchctl bootout gui/$(id -u) local.inebotten.selfbot && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.inebotten.selfbot.plist`
- Log: `~/.hermes/discord/data/bot.log` — verify `Connected to N guilds` after restart.
- Web console: http://127.0.0.1:8080 (local only).

## Layout
- Token: project `.env` (mode 600, `DISCORD_USER_TOKEN`), also `~/.hermes/discord/.env`. Never print the token.
- No guild/channel data is persisted locally — always live-query.
- VPS deploy (`bot.reidar.tech`) is currently unreachable and behind Cloudflare Access; do not rely on it. Local launchd service is the source of truth.

## Pitfalls
- Selfbot use violates Discord ToS; keep usage human-paced: minimal writes, no mass actions, small delays.
- Rate limits: ~5 sends / 5 s per channel, 50 requests/s global, search endpoints are aggressive.
- `guild.member_count` and `guild.members` can be partial/None (guild chunking is disabled).
- Guild search is index-backed — it can lag recent messages; use `messages` (history) for the latest state.
- `messages` without a channel picks the first text channel (arbitrary) — always pass an explicit channel.
- `messages` crashes on forum channels — use `threads`/`thread` instead.
- Two gateway sessions (bot + ctl) are fine for short queries; avoid heavy concurrent automation.
- The Hermes bridge (port 3000) is NOT running, so AI chat replies fall back to local templates. Start `scripts/run_both.py` if live AI replies are needed.
- `.env` was previously a broken named pipe (FIFO) — it must stay a regular file.

See `references/control.md` for the Discord API capability/rate-limit reference.

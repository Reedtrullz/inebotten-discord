# Discord control reference (verified 2026-08-02)

## Library
- `discord.py-self` v2.1.0 (dolfies fork, PyPI `discord.py-self`, Python >= 3.10). Installed in the project `.venv`.
- API docs: https://discordpy-self.rtfd.io/en/latest/
- Version pins (checked 2026-08-02): PyPI latest 2.1.0; GitHub release v2.1.0 (2026-01-18, tag `6de18b4c`); Discord API **v10** current (v9 available; no v11/v12).
- Docs URLs: use `docs.discord.com/developers/*.md` (old `discord.com/developers/docs/...` mostly redirects; `resources/forum-channel` 404s — forum content lives in the Channel resource).
- Auth header for user tokens: `Authorization: <token>` (no `Bot ` prefix).

## Useful REST endpoints (raw HTTP)
| Operation | Endpoint |
|---|---|
| Guild message search | `GET /guilds/{id}/messages/search?content=...&author_id=...&channel_id=...&limit=25&offset=0` (offset max 9975; index-backed, may lag) |
| List my guilds | `GET /users/@me/guilds?with_counts=true` |
| Message history | `GET /channels/{id}/messages?limit=100&before=<id>` (paginate with `before`) |
| Send message | `POST /channels/{id}/messages` `{content, message_reference, ...}` |
| Create DM | `POST /users/{id}/channels` |
| Add reaction | `PUT /channels/{cid}/messages/{mid}/reactions/{emoji}/@me` |
| Create thread | `POST /channels/{id}/threads` |
| Fetch one member | `GET /guilds/{id}/members/{user_id}` (works for user tokens; the list endpoint 403s) |
| List roles | `GET /guilds/{id}/roles` |
| List pins | `GET /channels/{id}/pins` |
| List DM channels | `GET /users/@me/channels` (user-only endpoint) |
| Guild metadata | `GET /guilds/{id}` (`member_count` is null via REST — gateway-only field) |
| Forum: list archived posts | `GET /channels/{forum_id}/threads/archived/public?limit=100&before=<ISO archive_timestamp>` (paginate with `before`; response has `has_more`) |
| Forum: read a post | `GET /channels/{thread_id}/messages?limit=100&before=<msg_id>` (thread id works as a channel id) |
| Resolve any channel/thread id | `GET /channels/{id}` (returns name, type 11 = thread, parent_id) |

User-token limits: `GET /guilds/{id}/threads/active` returns **403 code 20002 "Only bots can use this endpoint"** for this account; the gateway thread cache is often empty — use `threads-search` or the archived listing instead. Search paginates with `offset` (25/page, offset cap 9975); add `include_nsfw=true` and `sort_by=timestamp` when needed.

## Verified user-token REST facts (live, 2026-08-02)
| Endpoint | Result | Notes |
|---|---|---|
| `GET /guilds/{id}/threads/active` | **403 20002** | bot-only endpoint; workaround: `/channels/{id}/threads/search` |
| `GET /guilds/{id}/members` (list) | **403 50001** Missing Access | user token; use single-member fetch or gateway chunking instead |
| `GET /guilds/{id}/members/{uid}` | **200** | nick, roles (ids), joined_at, premium_since, pending, communication_disabled_until |
| `GET /guilds/{id}/audit-logs` | **403 50013** | needs VIEW_AUDIT_LOG; not token-type-specific |
| `GET /guilds/{id}/messages/search` | **200** | user-account endpoint (bots get 403 20001); result arrays are single messages with `hit`/`position` — NOT `(before, message, after)` tuples; `threads[]` embedded with full metadata; `total_results` may lag active writes |
| `GET /channels/{id}/threads/search?query=&limit=` | **200** (undocumented) | returns ACTIVE + archived threads (verified on forum + text channels); response has `total_results`, `threads[]` with `thread_metadata.archived`, `message_count`, `total_message_sent` |
| `GET /channels/{forum}/threads/archived/public` | **200** | `has_more` + ISO `archive_timestamp` pagination confirmed |
| `GET /users/@me/channels` | **200** | user-only; DM (type 1) + group DM (type 3) |
| `GET /guilds/{id}` | **200** | `member_count: null` (documented gateway-only), `premium_tier`, `premium_subscription_count`, `verification_level`, `vanity_url_code` populated |
| `GET /channels/{id}/pins` | **200** | full message objects; channel cap 50 |
| `GET /channels/{id}/messages?limit=100` | **200** | exactly 100 per page |
| `GET /channels/{id}/messages/{mid}` | **403** on type-5 announcement channels (mainnet-info, mainnet-activity; observed 2026-08-02) | history windows (`before`/`after`) work fine on the same channels; use `messages`/`search` instead of single-message fetch |

## discord.py-self 2.1.0 pins (NOT discord.py habits)
- No `discord.Intents` (`intents=` raises TypeError), no `View`/`ui`/callbacks, no `AutoShardedClient`, no `Guild.active_threads`/`fetch_active_threads()`, no `GuildSearchResult`, no `Client.search`, no `client.user.guilds`.
- Search: `guild.search(...)` / `channel.search(...)` → `AsyncIterator[Message]`; per-message `total_results`, `hit`, `analytics_id`, `doing_deep_historical_index`; reactions incomplete; endpoint can time out and truncate (#581).
- `send()` has no `embed`/`embeds`/`components` — user messages can't carry embeds; embeds route = `Webhook.from_url(url).send(embed=...)` (no bot auth needed).
- Forum: `forum.create_thread()` (returns `ThreadWithMessage`), `forum.archived_threads()`; `history`/`send` on ForumChannel → AttributeError.
- `Message.edit()` returns a new Message (content/attachments only); `thread.edit(archived=True, locked=True)` for archive/lock.
- Renames: `audit_logs()`, `webhooks()`, `vanity_invite()`, `Webhook.partial()`, `Webhook.send()`, `create_instance()`, `channel.permissions_for()`.
- Member access: `guild.members` partial; `guild.fetch_members()` scrapes the sidebar and can hang (#907); `guild.query_members()` is lighter; REST single-member fetch (`GET /guilds/{id}/members/{uid}`) is the reliable lookup.

## Search windowing & embed hits (verified 2026-08-02)
- `Guild.search()` accepts `channels=[Channel]` (objects, NOT ids), `before`/`after` (ISO datetimes → snowflake window). ctl: `search <guild> <query> --channel <ch> --before <ISO> --after <ISO>`.
- Bot/announcement channels post **embed-only messages** — `--embeds` on `messages`/`search`/`thread` appends embed title+description (without it, hits look empty).
- Public THORChain state: `https://gateway.liquify.com/chain/thorchain_api` is reachable from this machine; `thornode.ninerealms.com` DNS fails (observed 2026-08-02). `/thorchain/mimir?height=<block>` reads historical Mimir — useful to verify pause/halt state at a past block.

## Rate limits (official)
- Global: 50 requests/s per token.
- Message send: ~5 per 5 s per channel. Delete/bulk delete/reactions/moderation have separate buckets.
- Gateway: 1000 IDENTIFY / 24 h; ~120 gateway events / 60 s; keep 1 connection, no sharding.
- On 429 always honor `Retry-After` / `X-RateLimit-Reset-After`. Never hardcode limits.

## Ban risk (real)
Discord prohibits automating normal user accounts; account termination is possible. Stay under the radar: minimal presence changes, no mass messaging/joining, human-like pacing, no scraping at scale. Prefer a bot account whenever the task doesn't require acting as the user.

## Known API quirks
- `Guild.search()` (discord.py-self >= 2.1) returns messages whose reactions may be incomplete; `total_results` is the pagination guide.
- `guild.members` is a partial cache; use `await guild.fetch_members(...)` when full lists matter.
- Search results can lag; `TextChannel.history()` is authoritative for recent messages.
- Check `channel.permissions_for(guild.me)` before writes; missing perms -> 403.

# Discord API Rate Limits — Complete Reference

> Everything worth knowing about Discord's REST + Gateway rate limits, with
> per-minute numbers for the endpoints a selfbot actually touches.
> Verified against the official docs (`discord/discord-api-docs`, fetched
> 2026-08-01) plus observed values from the community. Observed values are
> **not guarantees** — Discord changes limits without notice and the official
> docs explicitly say *do not hardcode limits; parse the headers*.

---

## 1. TL;DR — Calls per minute

| What | Limit | Per minute | Notes |
|------|-------|-----------|-------|
| **Any API call (global)** | 50 requests / sec per token | **3 000 / min** | Same for bot and user tokens; per IP if unauthenticated |
| **Message send / edit** | 5 per 5 sec **per channel** | 60 / min per channel | Burst-capped: max 5 in any 5-second window |
| **Message delete** | ~5 per sec per channel (separate, faster bucket) | ~300 / min per channel | Higher bucket than send, historically documented |
| **Bulk delete** | ~1 per 3 sec per channel | ~20 / min per channel | Only messages <14 days old |
| **Reactions add/remove** | ~1 per 0.25 sec per channel/message | ~240 / min | Throttled further on a single message |
| **Ban / unban** | ~5 per 5 sec per guild | ~60 / min per guild | Guild-shared bucket; cumulative ~2 000 non-member ban cap (error `30035`) |
| **Kick** | ~5 per 5 sec per guild | ~60 / min per guild | Shares the ban/moderation bucket; no documented cumulative cap |
| **Webhook execute** | ~5 per 2 sec per webhook | ~150 / min per webhook | Interaction webhooks share this bucket |
| **Emoji/sticker create/edit/delete** | ~50 per hour per guild | ~0.8 / min | Quota headers are *inaccurate* on these routes; expect 429s |
| **Channel follow (followers)** | ~10 per hour | 0.17 / min | |
| **Channel name/topic/position edit** | ~2 per 10 min per channel | 0.2 / min | Well-known anti-"channel flashing" throttle |
| **Member nickname/role edits** | ~1 per 10–15 sec per member | ~4–6 / min per member | |
| **Invalid requests (401/403/429)** | 10 000 per 10 min per IP | 1 000 / min | Exceeding = temporary Cloudflare IP ban; `shared`-scope 429s don't count |
| **Gateway events sent** | 120 per 60 sec per connection | 2 / sec avg | Exceeding = immediate disconnect (repeat: API access revoked) |
| **Gateway IDENTIFY** | 1 000 per 24 h per token | — | Exceeding = token reset + email to owner |

The per-minute numbers are **sustained-rate conversions**. A "5 per 5 seconds"
bucket does not mean 5 requests at t=0 and 5 more at t=0.1 — the bucket only
refills as time passes, so bursts beyond the stated window get `429`s.

---

## 2. How the system works (official)

### 2.1 Two independent layers

1. **Per-route limits** — most endpoints have their own bucket. Limits may
   depend on the HTTP method, and *similar* endpoints often **share** a bucket
   (the `X-RateLimit-Bucket` header identifies the shared bucket).
2. **Global limit** — 50 requests/second per bot or user token, independent of
   per-route limits. Interaction endpoints (`/interactions/...`) are **exempt**
   from the global limit. Unauthenticated requests are limited per IP.

### 2.2 Bucket keys ("major parameters")

Rate limits are calculated per **top-level resource** in the path:

- `channel_id`
- `guild_id`
- `webhook_id` (+ `webhook_token`)

Two calls to the same route with *different* channel/guild/webhook IDs use
independent buckets. Example: exhausting `/channels/1234/messages` does **not**
block `/channels/9876/messages`. This matters for selfbots: sending to N
different channels gives you N separate send budgets, not one shared one.

### 2.3 Response headers

Returned on most requests (optional, but present on rate-limited paths):

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Limit` | Requests allowed in the current window |
| `X-RateLimit-Remaining` | Requests left in the window |
| `X-RateLimit-Reset` | Epoch seconds when the bucket resets |
| `X-RateLimit-Reset-After` | Seconds until reset (float, can be fractional) |
| `X-RateLimit-Bucket` | Unique bucket id; use it to group shared limits |
| `X-RateLimit-Global` | Only on `429`; `true` if the *global* limit was hit |
| `X-RateLimit-Scope` | Only on `429`: `user`, `global`, or `shared` |

### 2.4 The 429 response

```json
{
  "message": "You are being rate limited.",
  "retry_after": 64.57,
  "global": false,
  "code": 20008
}
```

- `retry_after` is **seconds as a float** (older API versions used
  milliseconds — v6+ uses seconds).
- The response also carries the normal rate-limit headers.
- Scope tells you *what* you hit:
  - `user` — the per-token per-route bucket
  - `global` — the 50 req/s limit
  - `shared` — a resource-level limit; **`shared` 429s are NOT counted against
    your invalid-request quota** (see §4)

### 2.5 Exceptions to the conventions

- **Emoji/sticker routes** are limited *per guild* and the quota headers are
  inaccurate — you can get 429s even with `X-RateLimit-Remaining > 0`.
- **Message deletes** get a separate, higher bucket than sends (documented
  since 2018).
- **Ban/kick routes share a guild-scoped bucket** — every bot and moderator
  tool operating in the same guild consumes the same budget, so multi-bot
  moderation exhausts it faster than per-bot math suggests.
- **Interaction webhooks** share the normal webhook rate-limit properties;
  interaction tokens are valid for 15 minutes.
- **Forwarding messages** (2024+) has its own stricter limits based on number
  of forwards and total attachment size.
- **Request Guild Members** (all members: `limit=0`, empty `query`) is limited
  to **1 request per guild per bot per 30 seconds** (added Aug 2025, enforced
  Oct 1 2025); excess gets a `RATE_LIMITED` gateway event.

---

## 3. Global rate limit (official)

- **50 requests/second per token** (bot *or* user).
- Applied per IP when no authorization header is present.
- Interaction endpoints are exempt.
- `discordapp.com/*` got an extra global limit (Oct 2023) — use `discord.com/*`
  and `cdn.discordapp.com` (CDN is unaffected).
- Large bots can genuinely outgrow 50/s; Discord support can raise it
  (dis.gd/rate-limit). A selfbot will never get close — and shouldn't.

Global limit problems usually look like "banned from the API when the bot
starts" (a burst of unhandled errors). Occasional Cloudflare bans are almost
always **unhandled error spikes**, not the 50/s limit.

---

## 4. Invalid request limit — the one that gets you banned (official)

IPs making too many *invalid* requests are temporarily blocked by Cloudflare:

- **10 000 invalid requests per 10 minutes per IP** (≈16–17/s sustained).
- An invalid request = any response with status **401, 403, or 429**.
- `429`s with `X-RateLimit-Scope: shared` are **excluded** from the count.
- Repeatedly hitting dead webhooks (404s) also contributes to restrictions.

This is the most dangerous limit for sloppy code: it's per **IP**, so every
process on your machine shares it, and it counts your own *avoidable* mistakes
(bad tokens, permission-denied calls, hammering exhausted buckets).

Avoidance rules:

- Stop sending immediately after a token becomes invalid (401).
- Check permissions before calling (403) instead of "just try".
- Never retry an exhausted bucket before its reset time (429).
- Don't retry dead webhooks (404) — recreate or remove them.
- Log the *rate* of invalid requests, not just the count.

---

## 5. Per-route limits in detail

### 5.1 Official / documented

The official docs deliberately publish **no numeric table** — limits are
dynamic and must be read from headers. What the docs *do* state:

| Endpoint group | Documented behavior |
|----------------|---------------------|
| All routes | Bucketed per top-level resource (`channel_id`, `guild_id`, `webhook_id`+token); read headers |
| Message delete | Separate, higher limit than send/edit |
| Emoji/sticker routes | Per-guild limit; quota headers inaccurate; 429s possible with quota remaining |
| Webhook routes | Bucket shared per webhook (id+token); interaction webhooks included |
| Interaction endpoints | Exempt from the global 50/s limit |
| `/channels/{id}/followers` | Follows are limited (observed ~10/hour); "channel following" abuse protection |

### 5.2 Observed values (community, subject to change)

These are the widely-observed, stable values as of 2025/2026. Treat them as
**planning numbers, not contracts** — always parse headers and honor
`Retry-After`.

| Operation | Observed bucket | Notes |
|-----------|----------------|-------|
| Create/edit message | 5 per 5 sec per channel | Includes embeds, files (uploads count as the send) |
| Delete message | ~5 per sec per channel | Faster than send, same top-level resource |
| Bulk delete | ~1 per 3 sec per channel | 2–100 messages per call, max 14 days old; some report 1/1 s (disputed) |
| Add/remove reaction | ~1 per 0.25 sec per channel/message | Same-message reactions throttle harder (~1 per 0.5–1 s) |
| Ban/unban | ~5 per 5 sec per guild | Guild-shared; **cumulative ~2 000 non-member ban cap** per guild — exceeding it locks the *whole guild* out of bans for up to 24 h (error `30035`) |
| Kick | ~5 per 5 sec per guild | Shares the ban bucket; no documented cumulative cap (kicks need membership) |
| Get guild bans | ~5 per 60 sec per guild | `GET /guilds/{id}/bans`, observed (issue #3803) |
| Execute webhook | ~5 per 2 sec per webhook | Applies per webhook id+token |
| Create/edit/delete emoji or sticker | ~50 per hour per guild | Per-hour window; a few adds → 30–60 min lockout; quota headers unreliable |
| Follow a channel (followers) | ~10 per hour | |
| Crosspost/publish message | ~10 per hour | |
| Edit channel name/topic/position | 2 per burst, sustained ~2 per 10 min per channel | The ~10 s header window is the burst; bucket reset is ~10 min |
| Modify member (nickname/roles) | ~10 per 10 sec per guild | Role changes on the same member throttle harder |
| Create role | 250 per day (official guild cap) | Role modify ~1 000 per day (observed) |
| Most GET endpoints (messages, guilds, members) | Generous per-route buckets | Read `X-RateLimit-*`; usually not a practical constraint for a selfbot |

### 5.3 Practical per-minute budget for Inebotten

For normal bot activity (weather, polls, reminders, AI replies, reactions):

- **Sends:** 60/min per channel. With a handful of active channels this is
  effectively unbounded for human-scale use — but Discord's anti-spam and the
  account-safety rules below matter far more than the bucket.
- **Deletes (cleanup):** ~300/min per channel — plenty for cleaning up after
  itself.
- **Bans/kicks:** ~60/min per guild — and that bucket is shared with every
  other bot/mod tool in the guild, plus the cumulative 2 000 non-member ban
  cap. A selfbot should stay at single-digit kicks/min regardless.
- **Reactions:** ~4/sec sustained; pace same-message reactions to ~1/sec.
- **Global:** 3 000/min total API calls — a selfbot doing a few hundred
  requests/hour is *nowhere near* this.
- **Invalid-request ceiling:** never approach 1 000 invalid/min; the project's
  own limiter (§7) keeps even valid traffic far below the danger zone.

---

## 6. Gateway limits (official)

The WebSocket gateway has its own limits, separate from the REST API:

| Limit | Value | Consequence |
|-------|-------|-------------|
| Events sent | 120 per 60 sec per connection (2/s avg) | Immediate disconnect; repeat offenders lose API access |
| Payload size (sent events) | Max 4096 bytes | Connection closed with code `4002` |
| IDENTIFY per 5 sec | `max_concurrency` (normally 1; large bots up to 16) | `Invalid Session` (op 9) if exceeded |
| IDENTIFY per 24 h | 1 000 per token, across all shards (`RESUME` excluded) | All sessions killed, **token reset**, owner emailed |
| Session starts per day | 1 000 default; large bots `max(2000, (guild_count/1000)*5)` | Read from `session_start_limit` in Get Gateway Bot |
| Request Guild Members (all) | 1 per guild per bot per 30 sec | `RATE_LIMITED` gateway event (since Oct 2025) |

Selfbot relevance:

- One connection ≈ one IDENTIFY — no realistic risk of the 1 000/day limit
  unless the bot reconnect-loops. A **crash loop that re-identifies** hundreds
  of times can burn the daily budget and reset the token.
- Presence updates and manual gateway commands count toward 120/60s; heartbeats
  are cheap but `REQUEST_GUILD_MEMBERS` for every guild on startup is exactly
  the kind of burst the new 30-second rule targets.

---

## 7. Selfbot / user-token specifics (important for this project)

User tokens have **no official rate-limit documentation** and Discord actively
detects scripted behavior. What is known/observed:

- The 50 req/s global limit and the 10k/10min invalid-request limit apply to
  user tokens too (per-token, per-IP).
- User-account anti-abuse is stricter and partly heuristic: sudden sustained
  bursts, mass DMs, mass friend requests, or identical rapid actions trigger
  flags even below documented buckets.
- Automated selfbot use violates Discord's Terms of Service; a flagged account
  can be disabled. Keep usage human-plausible.
- Gateway: same 120 events/60s and IDENTIFY rules, but a selfbot that
  disconnect/reconnect-loops on one account is far more visible than a bot.

### How the project already fits

`core/rate_limiter.py` implements a conservative two-layer quota:

- **5 messages/sec** (matches Discord's send bucket, but applied *globally*
  across channels instead of per-channel — deliberately stricter than the API,
  which is the right direction for a selfbot);
- **10 000 messages/day** hard quota (≈ one message per 8.6 sec sustained —
  far below any Discord limit, and the real safety valve);
- Exponential backoff (capped at 30 s) on failures, and 429 awareness.

Do **not** raise `MAX_MSGS_PER_SECOND` or `DAILY_QUOTA` (project convention).
The API would tolerate more; Discord's *account-safety heuristics* would not.

---

## 8. Retry / backoff policy (recommended)

1. **Normal path:** read `X-RateLimit-Remaining`; when it hits 0, wait
   `X-RateLimit-Reset-After` (float seconds) before the next call in that
   bucket.
2. **On 429:** sleep exactly `retry_after` (plus a small safety margin, e.g.
   +0.1–0.25 s). Never retry before the reset — a 429 you caused counts toward
   the 10k/10min IP ban; `shared`-scope 429s are the only free ones.
3. **Global 429** (`X-RateLimit-Global: true` / scope `global`): stop *all*
   traffic for `retry_after`; then resume at ≤50 req/s (selfbots: far lower).
4. **429 spam / Cloudflare ban:** exponential backoff with jitter, capped
   (e.g. 1s → 2s → 4s → … → 60s). If it persists, you have an error loop —
   fix the cause, don't tune the backoff.
5. **Never retry** 401 (token invalid), 403 (missing permission), or 404
   (dead webhook/unknown resource) — each retry is an invalid request.
6. **Jitter:** add ±10–20% random delay to scheduled sends so traffic doesn't
   form a detectable fixed rhythm (selfbot hygiene, not a Discord requirement).
7. discord.py-self already sleeps on `retry_after` internally — the project
   limiter is an extra layer *before* the API, not a replacement for header
   handling.

---

## 9. Sources

- Official docs, fetched 2026-08-01 from `discord/discord-api-docs` `main`:
  - `developers/topics/rate-limits.mdx`
  - `developers/events/gateway.mdx` (Rate Limiting section)
  - `developers/change-log.mdx` (Aug 2025 Request Guild Members limit; Oct 2023
    global limit; 2024 message-forwarding limits)
- Historical docs (2018–2025 git history) confirming the message-delete
  separate-bucket rule and the removal of any numeric table.
- Observed values cross-checked with sidecar consults (Gemini Flash High
  2026-08-01; Claude Sonnet 2026-08-02) and marked `~` in this document.
- Community evidence (2026-08-02): StackOverflow discord.js mass-kick thread;
  mambahost rate-limit calculator; discord-api-docs issues #5002 (2 000
  non-member ban cap), #3803 (`GET /bans` 5/60 s), #2250 (emoji hourly
  lockouts); official error codes `30035`/`30037`/`30040`/`500000` in the
  current opcodes doc; official support article "My Bot is Being Rate
  Limited!" (2025-07-14).

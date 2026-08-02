# Discord Design, Structure & Features — Comprehensive Reference

**Project:** inebotten (Discord user-token selfbot, Python, discord.py-self)
**Researched / verified live:** 2026-08-02
**API version:** v10 (current stable; v9 also available; no v11/v12 released as of 2026-08-02)
**Library:** discord.py-self **2.1.0** (installed in `.venv`, latest on PyPI and GitHub as of 2026-08-02)

This document is the verified reference for future Codex sessions that need to
navigate, read, search, and act inside Discord through the inebotten account.
It is the companion to `docs/DISCORD_RATE_LIMITS.md` (rate limits, 2026-08-01)
and the inebotten skill (`~/.codex/skills/inebotten/`).

## Provenance legend

| Mark | Meaning |
|---|---|
| ✅ | Officially documented by Discord (URL in Sources) |
| 🔶 | Library source / community-observed / GitHub issue, not official prose |
| ✅ LIVE | Re-verified live against the inebotten account on 2026-08-02 (read-only) |
| ⚠️ | Unverified / conflicting reports — treat with care |

## 0. Version verification (2026-08-02)

- `discord.py-self` installed in `.venv`: **2.1.0** (verified via `import discord`).
- PyPI latest: **2.1.0** (pypi.org/pypi/discord.py-self/json). GitHub latest release: **v2.1.0**, published 2026-01-18, tag commit `6de18b4cb40dd42625a535f52d9715c71399ffb3`.
- The RTFD docs "latest" describe 2.2-dev in places; flagged `[docs]` where they diverge from 2.1.0.
- Discord API: **v10 and v9 "Available"; v8/v7/v6 deprecated; v5–v3 discontinued**. Docs anomaly: the reference table still marks deprecated v6 as "Default" — stale artifact; the versionless default routes to v10.
- Docs moved to `docs.discord.com/developers/...` (`.md` endpoints work); old `discord.com/developers/docs/...` mostly redirects but `resources/forum-channel` 404s (forum content now lives in the Channel resource).

---

# 1. Server architecture

## 1.1 Guilds & features

- Guild object fields: `id`, `name`, `icon`, `banner`, `owner_id`, `roles`, `channels`, `members` (gateway), `member_count` (**only sent via the gateway, and not always** — REST `GET /guilds/{id}` returned `member_count: null` for inebotten ✅ LIVE), `premium_tier` (0–3), `premium_subscription_count`, `premium_progress_bar_enabled`, `verification_level`, `features[]`, `vanity_url_code`, `welcome_screen`, `nsfw_level`, `mfa_level`, `explicit_content_filter`, `rules_channel_id`, `public_updates_channel_id`, `system_channel_id`.
- `GET /users/@me/guilds?with_counts=true` returns partial guilds: `id`, `name`, `icon`, `banner`, `owner`, `permissions` (bitfield string), `features[]`, `approximate_member_count`, `approximate_presence_count` ✅ LIVE (11 guilds for inebotten; max 200 = non-bot guild cap).
- Guild features observed live in inebotten's guilds ✅ LIVE: `COMMUNITY`, `VANITY_URL`, `DISCOVERABLE`, `GUILD_ONBOARDING`, `WELCOME_SCREEN_ENABLED`, `MEMBER_VERIFICATION_GATE_ENABLED`, `NEWS`, `AUTO_MODERATION`, `SOUNDBOARD`, `BANNER`, `ANIMATED_BANNER/ICON`, `INVITE_SPLASH`, `ROLE_ICONS`, `MAX_FILE_SIZE_50_MB` / `MAX_FILE_SIZE_100_MB`, `TIERLESS_BOOSTING`, `CHANNEL_ICON_EMOJIS_GENERATED`, `TEXT_IN_VOICE_ENABLED`, `AGE_VERIFICATION_LARGE_GUILD`, `ACTIVITY_FEED_DISABLED_BY_USER`, `GUILD_TAGS`, `ENABLED_DISCOVERABLE_BEFORE`, `GUILD_WEB_PAGE_VANITY_URL`, `GUILD_SERVER_GUIDE`, `PIN_PERMISSION_MIGRATION_COMPLETE`, `BYPASS_SLOWMODE_PERMISSION_MIGRATION_COMPLETE`.

## 1.2 Channel types (current, official)

| Type | ID | Description |
|---|---|---|
| GUILD_TEXT | 0 | text channel within a server |
| DM | 1 | direct message between users |
| GUILD_VOICE | 2 | voice channel within a server |
| GROUP_DM | 3 | direct message between multiple users |
| GUILD_CATEGORY | 4 | organizational category, contains up to 50 channels |
| GUILD_ANNOUNCEMENT | 5 | followable/crosspostable channel (formerly news) |
| ANNOUNCEMENT_THREAD | 10 | sub-channel within GUILD_ANNOUNCEMENT |
| PUBLIC_THREAD | 11 | sub-channel within GUILD_TEXT or GUILD_FORUM |
| PRIVATE_THREAD | 12 | sub-channel within GUILD_TEXT, invite/MANAGE_THREADS only |
| GUILD_STAGE_VOICE | 13 | voice channel for events with an audience |
| GUILD_DIRECTORY | 14 | hub directory channel |
| GUILD_FORUM | 15 | channel that can only contain threads |
| GUILD_MEDIA | 16 | thread-only channel similar to forum (⚠ still "in active development") |

Types 6–9 undefined (legacy GUILD_STORE type 6 removed). Types 10/11/12 require API v9+.

Live distribution in THORChain Devs ✅ LIVE: text 0 ×175, category 4 ×11, announcement 5 ×10, stage 13 ×1, forum 15 ×1.

## 1.3 Hierarchy, positions, categories

- Every channel has `position` (same-position channels sort by id) and `parent_id` for category nesting (Text, Voice, Announcement, Stage, Forum, Media).
- Channel fields: `name` (1–100), `type`, `topic` (0–1024; 0–4096 for forum/media), `nsfw`, `rate_limit_per_user` (0–21600 s slowmode), `bitrate` (voice min 8000; caps below), `user_limit` (voice 99, stage 10,000, 0 = none), `permission_overwrites`, `default_auto_archive_duration`, `flags`, forum/media fields (`available_tags`, `default_reaction_emoji`, `default_thread_rate_limit_per_user`, `default_sort_order`, `default_forum_layout`).
- Newer fields observed live ✅ LIVE: `icon_emoji` + `theme_color` (channel icons), `last_message_id`, `last_pin_timestamp`.
- Channel flags: `PINNED 1<<1` (thread pinned in forum/media), `REQUIRE_TAG 1<<4` (forum tag required), `HIDE_MEDIA_DOWNLOAD_OPTIONS 1<<15` (media), `IS_SPOILER_CHANNEL 1<<21` (requires `nsfw: false`).
- Voice bitrate caps (official): normal 96,000; boost L1 → 128,000; L2 → 256,000; L3 or `VIP_REGIONS` → 384,000. Stage caps at 64,000.
- Guild limits 🔶: 500 channels, 250 roles, 1000 active threads, 50 channels/category (official).

## 1.4 Roles

- Role object: `id`, `name`, `color` (deprecated int) / `colors` (new object), `hoist`, `icon?`, `unicode_emoji?`, `position` (sorted by id), `permissions` (bit set string), `managed`, `mentionable`, `tags?`, `flags`.
- **@everyone role has the same ID as the guild** (official). Highest role = greatest `position` (@everyone = 0).
- Hierarchy restrictions apply to moderation only (kick/ban/edit-nickname/role-grant targets must have lower highest-role than yours); permission calculation does **not** use role position (see 1.6).
- 250 roles/guild cap 🔶; `GUILD_TAGS`/`ENHANCED_ROLE_COLORS` add server tags and gradient role colors.
- `GET /guilds/{id}/roles` works for user tokens ✅ LIVE (30 roles in THORChain Devs).

## 1.5 Permissions — bitwise flags (exact values, official)

64-bit bitfield, serialized as string. `ADMINISTRATOR` bypasses all overwrites. T = text/announcement/forum/media, V = voice, S = stage.

| Permission | Value | Channels |
|---|---|---|
| CREATE_INSTANT_INVITE | `1<<0` | T, V, S |
| KICK_MEMBERS * | `1<<1` | — |
| BAN_MEMBERS * | `1<<2` | — |
| ADMINISTRATOR * | `1<<3` | — |
| MANAGE_CHANNELS * | `1<<4` | T, V, S |
| MANAGE_GUILD * | `1<<5` | — |
| ADD_REACTIONS | `1<<6` | T, V, S |
| VIEW_AUDIT_LOG | `1<<7` | — |
| PRIORITY_SPEAKER | `1<<8` | V |
| STREAM | `1<<9` | V, S |
| VIEW_CHANNEL | `1<<10` | T, V, S |
| SEND_MESSAGES | `1<<11` | T, V, S |
| SEND_TTS_MESSAGES | `1<<12` | T, V, S |
| MANAGE_MESSAGES * | `1<<13` | T, V, S |
| EMBED_LINKS | `1<<14` | T, V, S |
| ATTACH_FILES | `1<<15` | T, V, S |
| READ_MESSAGE_HISTORY | `1<<16` | T, V, S |
| MENTION_EVERYONE | `1<<17` | T, V, S |
| USE_EXTERNAL_EMOJIS | `1<<18` | T, V, S |
| VIEW_GUILD_INSIGHTS | `1<<19` | — |
| CONNECT | `1<<20` | V, S |
| SPEAK | `1<<21` | V |
| MUTE_MEMBERS | `1<<22` | V, S |
| DEAFEN_MEMBERS | `1<<23` | V |
| MOVE_MEMBERS | `1<<24` | V, S |
| USE_VAD | `1<<25` | V |
| CHANGE_NICKNAME | `1<<26` | — |
| MANAGE_NICKNAMES | `1<<27` | — |
| MANAGE_ROLES * | `1<<28` | T, V, S |
| MANAGE_WEBHOOKS * | `1<<29` | T, V, S |
| MANAGE_GUILD_EXPRESSIONS * | `1<<30` | — |
| USE_APPLICATION_COMMANDS | `1<<31` | T, V, S |
| REQUEST_TO_SPEAK | `1<<32` | S |
| MANAGE_EVENTS | `1<<33` | V, S |
| MANAGE_THREADS * | `1<<34` | T |
| CREATE_PUBLIC_THREADS | `1<<35` | T |
| CREATE_PRIVATE_THREADS | `1<<36` | T |
| USE_EXTERNAL_STICKERS | `1<<37` | T, V, S |
| SEND_MESSAGES_IN_THREADS | `1<<38` | T |
| USE_EMBEDDED_ACTIVITIES | `1<<39` | T, V |
| MODERATE_MEMBERS ** | `1<<40` | — |
| VIEW_CREATOR_MONETIZATION_ANALYTICS * | `1<<41` | — |
| USE_SOUNDBOARD | `1<<42` | V |
| CREATE_GUILD_EXPRESSIONS | `1<<43` | — |
| CREATE_EVENTS | `1<<44` | V, S |
| USE_EXTERNAL_SOUNDS | `1<<45` | V |
| SEND_VOICE_MESSAGES | `1<<46` | T, V, S |
| *(bit 47 unassigned)* | — | — |
| SET_VOICE_CHANNEL_STATUS | `1<<48` | V |
| SEND_POLLS | `1<<49` | T, V, S |
| USE_EXTERNAL_APPS | `1<<50` | T, V, S |
| PIN_MESSAGES | `1<<51` | T |
| BYPASS_SLOWMODE | `1<<52` | T, V, S |

`*` = requires server-wide 2FA when the guild has MFA enabled. `**` = timeouts.

## 1.6 Permission calculation (official 8-step order)

For a member+channel: (1) @everyone guild-level → (2) member's roles guild-level → channel overwrites in order: (3) @everyone deny, (4) @everyone allow, (5) role deny, (6) role allow, (7) member deny, (8) member allow. Owner → ALL; ADMINISTRATOR → ALL regardless of overwrites. Overwrite object: `id`, `type` (0 = role, 1 = member), `allow`, `deny` (missing/null = `"0"`).

Implicit permissions: denying VIEW_CHANNEL denies everything on that channel; denying SEND_MESSAGES implicitly denies MENTION_EVERYONE, SEND_TTS_MESSAGES, ATTACH_FILES, EMBED_LINKS; denying CONNECT denies other voice perms. **Threads inherit parent permissions except `SEND_MESSAGES` — sending in a thread needs `SEND_MESSAGES_IN_THREADS`.** Categories use permission syncing (identical overwrites); editing a child de-syncs it.

Timed-out members (`communication_disabled_until`): cannot send messages, react, speak, create threads, etc.

## 1.7 Server boosts & levels

`premium_tier`: NONE=0, TIER_1=1, TIER_2=2, TIER_3=3 (thresholds 2 / 7 / 14 boosts). Live: THORChain Devs is tier 3 with 15 boosts ✅ LIVE.

| Level | Boosts | Key perks |
|---|---|---|
| 1 | 2 | 100 emoji slots (+50), 15 stickers, 24 soundboard slots, 128 kbps, 720p60, animated icon, custom invite background |
| 2 | 7 | 150 emoji, 30 stickers, 36 soundboard, 256 kbps, 1080p60, stage audience 150, **50 MB uploads for all members (server only)**, role icons, static banner |
| 3 | 14 | 250 emoji, 60 stickers, 48 soundboard, 384 kbps, stage audience 300, **100 MB uploads**, animated banner, **custom invite link (vanity URL)** |

Experiment: "Larger File Uploads" (5 boosts) → 250 MB server upload limit.

## 1.8 Welcome screen, member onboarding, verification

- **Welcome screen** (needs `COMMUNITY` + `WELCOME_SCREEN_ENABLED`): `description` + up to **5** `welcome_channels` entries (channel_id, description, emoji). Live: `welcome_screen` was `null` in REST `GET /guilds/{id}` for THORChain Devs even with the feature ✅ LIVE (field is not populated for all guilds).
- **Membership screening**: `MEMBER_VERIFICATION_GATE_ENABLED`; `form_fields[]`.
- **Onboarding** object: `prompts[]` (type MULTIPLE_CHOICE=0 / DROPDOWN=1, `options[]` with channels/role_ids/emoji, `single_select`, `required`, `in_onboarding`), `default_channel_ids`, `enabled`, `mode` (ONBOARDING_DEFAULT=0 / ONBOARDING_ADVANCED=1). Publish requires 7+ default channels, ≥5 with @everyone View+Send.
- Verification levels: NONE=0, LOW=1 (verified email), MEDIUM=2 (5+ min account), HIGH=3 (10+ min member), VERY_HIGH=4 (verified phone). Live: THORChain Devs `verification_level: 2` ✅ LIVE.
- NSFW levels: DEFAULT=0 / EXPLICIT=1 / SAFE=2 / AGE_RESTRICTED=3. MFA: NONE=0 / ELEVATED=1.

## 1.9 Vanity URLs

- Feature `VANITY_URL` grants the endpoint `GET /guilds/{id}/vanity-url` (needs `MANAGE_GUILD`; returns partial invite, `code` null if unset). `guild.vanity_url_code` is public without permission.
- Live: THORChain Devs `vanity_url_code: "thorchaindevs"` ✅ LIVE.
- Help Center (2026): **Custom Invite Link is now a Boost Level 3 (14 boosts) perk** — historically Level 1; if boost status lapses, the link is lost after 30 days.

## 1.10 Audit logs

- `GET /guilds/{id}/audit-logs` requires `VIEW_AUDIT_LOG`; params `user_id`, `action_type`, `before`, `after`, `limit` (1–100, default 50). `before` → newest-first; `after` → ascending; `after=0` → oldest first.
- Live: **403 code 50013 "Missing Permissions"** for inebotten (no VIEW_AUDIT_LOG in THORChain Devs) ✅ LIVE.
- Entries: `target_id`, `changes[]`, `user_id`, `id`, `action_type`, `options?`, `reason?`. Response also carries `auto_moderation_rules[]`, `guild_scheduled_events[]`, `integrations[]`, `threads[]`, `users[]`, `webhooks[]`.
- Key action types: GUILD_UPDATE 1; CHANNEL_CREATE/UPDATE/DELETE 10/11/12; CHANNEL_OVERWRITE_* 13/14/15; MEMBER_KICK 20, PRUNE 21, BAN_ADD/REMOVE 22/23, UPDATE 24, ROLE_UPDATE 25; ROLE_* 30/31/32; INVITE_* 40/41/42; WEBHOOK_* 50/51/52; EMOJI_* 60/61/62; MESSAGE_DELETE 72, BULK_DELETE 73, PIN/UNPIN 74/75; INTEGRATION_* 80/81/82; STAGE_INSTANCE_* 83/84/85; STICKER_* 90/91/92; SCHEDULED_EVENT_* 100/101/102; THREAD_* 110/111/112; SOUNDBOARD_* 130/131/132; AUTOMOD_* 140–146; ONBOARDING_* 163–167; HOME_SETTINGS_* 190/191; VOICE_CHANNEL_STATUS_* 192/193.
- `X-Audit-Log-Reason` header attaches a reason (v10+, replaces `reason` param).

---

# 2. Threads & forums

## 2.1 Creation

- Public thread (11) from an existing message: `POST /channels/{id}/messages/{mid}/threads` — thread and starter message share the same ID; orphaned if the starter is deleted. Parent GUILD_TEXT → PUBLIC_THREAD; GUILD_ANNOUNCEMENT → ANNOUNCEMENT_THREAD (10).
- Private thread (12): `POST /channels/{id}/threads` (no message; text channels only; group-DM-like).
- Forum/media posts: `POST /channels/{id}/threads` on type 15/16 with a `message` object (first post); created thread is PUBLIC_THREAD; requires `SEND_MESSAGES` (`CREATE_PUBLIC_THREADS` ignored); at least one of content/embeds/sticker_ids/components/files required.
- Params: `name` (1–100), `auto_archive_duration` (60/1440/4320/10080), `rate_limit_per_user` (0–21600), `message`, `applied_tags` (max 5), `files`.
- Sending a message auto-unarchives a thread (unless locked). Archived threads are immutable except message deletion.

## 2.2 Public vs private

Public: anyone who can view the parent. Private: invited members + MANAGE_THREADS. Members auto-added on send; `invitable` (private only) allows non-mods to add non-mods.

## 2.3 Archiving & auto-archive

| `auto_archive_duration` | Meaning |
|---|---|
| 60 | 60 minutes of inactivity |
| 1440 | 24 hours |
| 4320 | 3 days |
| 10080 | 7 days |

"Activity" = send, unarchive, or auto-archive change. Near the active-thread cap Discord lowers timers automatically. Locked threads need MANAGE_THREADS to unarchive; a thread can be locked without being archived. Pinned forum threads (`PINNED 1<<1`) never auto-archive.

## 2.4 Thread metadata (exact fields)

`archived`, `auto_archive_duration` (60/1440/4320/10080), `archive_timestamp` (ISO8601, when archive status last changed), `locked`, `invitable` (private), **`create_timestamp`** (not `created_at`; populated only for threads created after 2022-01-09). Channel-level: `message_count` (decrements), `total_message_sent` (never decrements; both cap at 50 for pre-2022-07-01 threads), `member_count` (approx, caps at 50), `last_message_id`, `flags`.

Live example (forum post in THORChain Devs) ✅ LIVE: `{archived: true, archive_timestamp: "2026-07-28T10:09:17.508Z", auto_archive_duration: 10080, locked: false, create_timestamp: "2026-06-28T09:56:58.744Z"}`, `applied_tags: [tag_id]`, `total_message_sent: 2`.

## 2.5 Thread members

`GET /channels/{id}/thread-members` (with_member, after, limit 1–100 default 100) — requires GUILD_MEMBERS intent for bots; **always paginated in v11**. `PUT/DELETE /channels/{id}/thread-members/@me` join/leave; `PUT/DELETE .../{user_id}` add/remove.

## 2.6 Enumerating threads

| Endpoint | Returns | Order | Perms |
|---|---|---|---|
| `GET /guilds/{id}/threads/active` | all active threads (public+private) you can access | id desc | — |
| `GET /channels/{id}/threads/archived/public` | archived public/announcement threads | `archive_timestamp` desc | READ_MESSAGE_HISTORY |
| `GET /channels/{id}/threads/archived/private` | archived private threads | `archive_timestamp` desc | READ_MESSAGE_HISTORY + MANAGE_THREADS |
| `GET /channels/{id}/users/@me/threads/archived/private` | archived private threads you joined | id desc | READ_MESSAGE_HISTORY |

- Archived pagination: `before` = **ISO8601 archive timestamp** (snowflake for the joined-private variant), response `{threads[], members[], has_more}`; paginate until `has_more` false.
- **`/guilds/{id}/threads/active` is bot-only: user tokens get 403 code 20002 "Only bots can use this endpoint"** ✅ LIVE. Workaround: gateway thread cache (`guild.threads`) or per-channel `GET /channels/{id}/threads/search` (undocumented, what the official client uses).
- Live: `GET /channels/{forum_id}/threads/archived/public?limit=5` → 200, `has_more: true`, ISO archive timestamps ✅ LIVE.

## 2.7 Forums (type 15) & media channels (type 16)

- Contain only threads/posts; no direct messages.
- `available_tags` ≤ **20** per channel; tag: `id`, `name` (0–20 chars), `moderated`, `emoji_id`/`emoji_name` (at most one). `applied_tags` ≤ **5** per thread. `REQUIRE_TAG` flag (`1<<4`) makes tags mandatory.
- `default_reaction_emoji` (exactly one of id/name), `default_sort_order` (LATEST_ACTIVITY=0 / CREATION_DATE=1), **`default_forum_layout`** (NOT_SET=0 / LIST_VIEW=1 / GALLERY_VIEW=2), `default_thread_rate_limit_per_user` (copied to new threads).
- Topic 0–4096 chars (vs 1024 elsewhere).
- Live forum in THORChain Devs ✅ LIVE: `node-providers` (id 1135713431304015963), `default_forum_layout: 1`, `default_sort_order: 0`, `available_tags: 2`, `default_reaction_emoji` set.

---

# 3. Messages & content

## 3.1 Message types

Current values: DEFAULT 0, RECIPIENT_ADD 1, RECIPIENT_REMOVE 2, CALL 3, CHANNEL_NAME_CHANGE 4, CHANNEL_ICON_CHANGE 5, CHANNEL_PINNED_MESSAGE 6, USER_JOIN 7, GUILD_BOOST 8, GUILD_BOOST_TIER_1 9, GUILD_BOOST_TIER_2 10, GUILD_BOOST_TIER_3 11, CHANNEL_FOLLOW_ADD 12, GUILD_DISCOVERY_DISQUALIFIED 14, GUILD_DISCOVERY_REQUALIFIED 15, GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING 16, GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING 17, THREAD_CREATED 18, REPLY 19, CHAT_INPUT_COMMAND 20, THREAD_STARTER_MESSAGE 21, GUILD_INVITE_REMINDER 22, CONTEXT_MENU_COMMAND 23, AUTO_MODERATION_ACTION 24, ROLE_SUBSCRIPTION_PURCHASE 25, INTERACTION_PREMIUM_UPSELL 26, STAGE_START 27, STAGE_END 28, STAGE_SPEAKER 29, STAGE_TOPIC 31, GUILD_APPLICATION_PREMIUM_SUBSCRIPTION 32, GUILD_INCIDENT_ALERT_MODE_ENABLED 36, GUILD_INCIDENT_ALERT_MODE_DISABLED 37, GUILD_INCIDENT_REPORT_RAID 38, GUILD_INCIDENT_REPORT_FALSE_ALARM 39, PURCHASE_NOTIFICATION 44, POLL_RESULT 46. Undefined gaps: 13, 30, 33–35, 40–43, 45.

## 3.2 Content limits

- API `content` ≤ **2000 chars** (4000 is client-side Nitro 🔶); forum thread message params same. Max request body 25 MiB.
- `nonce` ≤ 25 chars; `enforce_nonce` dedupes same-author+same-nonce within minutes.
- Slowmode `rate_limit_per_user` 0–21600 s; bots + BYPASS_SLOWMODE unaffected.
- Edit: author may edit content/embeds/flags/components; others only flags with MANAGE_MESSAGES. v10+: `attachments` array must list **all** attachments to retain. **No documented edit deadline**; error 30046 caps edits of >1h-old messages at ~10 (community-measured 🔶).
- Delete: 204; others' messages need MANAGE_MESSAGES. Bulk delete: 2–100 IDs, guild channels, MANAGE_MESSAGES, fails on any message >2 weeks old or duplicates.

## 3.3 Embeds

| Field | Limit |
|---|---|
| `title` | 256 |
| `description` | 4096 |
| `fields` | 25 objects |
| `field.name` / `field.value` | 256 / 1024 |
| `footer.text` | 2048 |
| `author.name` | 256 |
| Combined sum across all embeds on one message | **6000 chars** |
| Embeds per message | **10** |

Allowed URL schemes for embed images/icons: http(s) + `attachment://filename`. Sendable fields exclude type/provider/video/proxy/height/width. Embed types: rich, image, video, gifv, article, link, poll_result. Embeds dedupe by URL.

## 3.4 Attachments

- Default **10 MiB/file**; Nitro Basic **50 MB**; Nitro **500 MB** (raised 2024); Boost L2/L3: **50/100 MB for all server members**; experiment 250 MB (5 boosts).
- Max 10 attachments/message 🔶; image dimension ceiling ~4096×4096 🔶; alt text `description` ≤ 1024 chars.
- Multipart `files[n]` + `payload_json`; embed references via `attachment://filename`.
- Live: `history` returns attachments with `url`/`proxy_url`/`size`/`content_type`/`placeholder` (thumbhash) ✅ LIVE.

## 3.5 Components (message + modal)

Component types: 1 Action Row, 2 Button, 3 String Select, 4 Text Input, 5 User Select, 6 Role Select, 7 Mentionable Select, 8 Channel Select, 9 Section, 10 Text Display, 11 Thumbnail, 12 Media Gallery, 13 File, 14 Separator, 17 Container, 18 Label (modal), 19 File Upload (modal), 21 Radio Group, 22 Checkbox Group, 23 Checkbox.

| Item | Limit |
|---|---|
| Action rows (legacy message) | 5 |
| Buttons per action row | 5 |
| Total interactive components (legacy) | 25 |
| Select options | 25 |
| Select placeholder | 150 |
| Option label/value/description | 100 each |
| Button label / link URL | 80 / 512 |
| `custom_id` | 1–100, unique per message |
| Modal components / title | 1–5 / 45 |
| Text input min/max length / value / placeholder | 0–4000 / 4000 / 100 |

Button styles: Primary 1, Secondary 2, Success 3, Danger 4, Link 5 (url, no custom_id, no interaction), **Premium 6** (new, `sku_id`). **Components V2**: message flag `IS_COMPONENTS_V2 1<<15` (32768) — components become the only content (content/embeds/stickers/poll rejected with 400), irreversible once set; legacy behavior (components alongside content, ≤5 rows) still supported.

## 3.6 Stickers & emoji

- Sticker formats PNG=1/APNG=2/LOTTIE=3/GIF=4; file ≤ **512 KiB**; ≤ **3 stickers per message** (`sticker_ids`; deprecated `stickers` field → `sticker_items`).
- Guild sticker slots: 5 default; +10/+15/+30 at boost L1/L2/L3. Emoji slots: 50 default; 100/150/250 at L1/L2/L3.
- Custom emoji path format `name:id`; USE_EXTERNAL_EMOJIS for external.

## 3.7 Reactions

- Endpoints: add `PUT .../reactions/{emoji}/@me` (needs READ_MESSAGE_HISTORY; ADD_REACTIONS only if first reactor), remove own `DELETE .../@me`, remove other `DELETE .../{user_id}` (MANAGE_MESSAGES), list `GET .../reactions/{emoji}` (`type` 0 normal/1 burst, `after`, `limit` 1–100 default 25), clear all/per-emoji (MANAGE_MESSAGES).
- Emoji URL-encoded; wrong format → error 10014. **20 reactions/message is a client/UI cap 🔶**, not stated in API docs.
- Reaction object: `count`, `count_details {burst, normal}`, `me`, `emoji`, `burst_colors`. Live search payload included `count_details`, `me`, `burst_count` ✅ LIVE.

## 3.8 Polls

- Poll object: `question` (text only, ≤ **300 chars**), `answers` ≤ **10** (each ≤ **55 chars** + optional emoji), `expiry`, `allow_multiselect`, `layout_type` (**DEFAULT=1 only**).
- Create `duration` in **hours, up to 32 days (768 h), default 24 h** — not "1–32 days". Poll messages **cannot be edited** after creation. **Apps cannot vote.** Results: `is_finalized`, `answer_counts[] {id, count, me_voted}`; poll results arrive as POLL_RESULT (type 46) + poll_result embeds. Needs `SEND_POLLS`.

## 3.9 References, replies, forwards, snapshots

- `message_reference`: `type` (DEFAULT=0 / FORWARD=1), `message_id`, `channel_id` (required for forwards), `guild_id`, `fail_if_not_exists` (default true). Reply needs READ_MESSAGE_HISTORY; target must exist and not be a system message.
- Forwards: type FORWARD + message_id + channel_id; requires content-read access (else 160014); `message_snapshots` (max 1) immutable, author excluded; only DEFAULT/REPLY/CHAT_INPUT_COMMAND/CONTEXT_MENU_COMMAND forwardable; flag `HAS_SNAPSHOT 1<<14`.
- `interaction_metadata` replaces deprecated `interaction`.

## 3.10 Message flags

`CROSSPOSTED 1<<0`, `IS_CROSSPOST 1<<1`, `SUPPRESS_EMBEDS 1<<2`, `SOURCE_MESSAGE_DELETED 1<<3`, `URGENT 1<<4`, `HAS_THREAD 1<<5`, `EPHEMERAL 1<<6`, `LOADING 1<<7`, `FAILED_TO_MENTION_SOME_ROLES_IN_THREAD 1<<8`, `SUPPRESS_NOTIFICATIONS 1<<12`, `IS_VOICE_MESSAGE 1<<13`, `HAS_SNAPSHOT 1<<14`, `IS_COMPONENTS_V2 1<<15` (irreversible).

## 3.11 Pins, search, scheduled messages

- **50 pins per channel** (official). Endpoints: `GET /channels/{id}/pins`, `PUT/DELETE /channels/{id}/messages/pins/{mid}` (needs `PIN_MESSAGES`). Live: 21 pins readable in dev-general ✅ LIVE.
- Search: see §6.4.
- **Scheduled messages: no native API exists** — verified by absence in official docs. Closest primitive: Guild Scheduled Events (events, not messages). A selfbot schedules sends client-side.

---

# 4. Interactions & commands

## 4.1 Application commands

Types: CHAT_INPUT 1, USER 2 (user context menu), MESSAGE 3 (message context menu), PRIMARY_ENTRY_POINT 4 (Activities).

- Names: `^[-_'\p{L}\p{N}\p{sc=Deva}\p{sc=Thai}]{1,32}$` for CHAT_INPUT (lowercase where variant exists); USER/MESSAGE may be mixed-case with spaces; description 1–100.
- Registration limits: 100 global CHAT_INPUT, 15 global USER, 15 global MESSAGE, 1 global PRIMARY_ENTRY_POINT (same per guild); **200 command creates/day/guild**; `POST` is an upsert.
- Endpoints: `POST /applications/{app}/commands` (global) and `/guilds/{guild}/commands` (guild); PATCH/DELETE per command. **Authorization: bot token OR client-credentials Bearer with `applications.commands.update` — there is NO user-token path. A user-token selfbot cannot register application commands.** ✅
- Fields: `options` ≤25, `default_member_permissions` (bit-set string; "0" = admins only), `dm_permission`/`default_permission` deprecated, `nsfw`, `integration_types` (GUILD_INSTALL 0 / USER_INSTALL 1), `contexts` (GUILD 0 / BOT_DM 1 / PRIVATE_CHANNEL 2), localizations, `version`.
- Guild commands update instantly; global propagate with read-repair (~1 h).

## 4.2 Options

Types: SUB_COMMAND 1, SUB_COMMAND_GROUP 2, STRING 3, INTEGER 4, BOOLEAN 5, USER 6, CHANNEL 7, ROLE 8, MENTIONABLE 9, NUMBER 10, ATTACHMENT 11. Choices ≤25 (STRING/INTEGER/NUMBER only; name 1–100, value ≤100); nested options ≤25; `min_length`/`max_length` for STRING (max 6000); `autocomplete` can't combine with choices; required options precede optional.

## 4.3 Interactions

Types: PING 1, APPLICATION_COMMAND 2, MESSAGE_COMPONENT 3, APPLICATION_COMMAND_AUTOCOMPLETE 4, MODAL_SUBMIT 5.

- **Tokens valid 15 min; initial response within 3 s** (else token invalidated). Deferred: DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE 5 (loading), DEFERRED_UPDATE_MESSAGE 6.
- Callbacks: PONG 1, CHANNEL_MESSAGE_WITH_SOURCE 4, DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE 5, DEFERRED_UPDATE_MESSAGE 6, UPDATE_MESSAGE 7, AUTOCOMPLETE_RESULT 8 (≤25 choices), MODAL 9, PREMIUM_REQUIRED 10 (deprecated), LAUNCH_ACTIVITY 12.
- Endpoints: `POST /interactions/{id}/{token}/callback` (HTTP even for gateway interactions), `PATCH/DELETE /webhooks/{app}/{token}/messages/@original`, `POST /webhooks/{app}/{token}` followups. Interaction webhooks share webhook rate limits, exempt from global 50/s.
- Ephemeral = flag `1<<6`; only valid on deferred callback; ephemeral messages disappear when the token expires (15 min).
- **Interactions are delivered to apps. A user token cannot receive app interactions or use the callback flow** ✅ — it can only invoke commands client-side via `POST /interactions` (see §7).

## 4.4 Message components (callback flow)

1. User clicks → app receives MESSAGE_COMPONENT/MODAL_SUBMIT (gateway `INTERACTION_CREATE` or HTTP endpoint) with originating message.
2. Respond within 3 s: UPDATE_MESSAGE (7), DEFERRED_UPDATE_MESSAGE (6), CHANNEL_MESSAGE_WITH_SOURCE (4), or MODAL (9).
3. Later edits via token webhooks (15 min).
4. **Messages sent by user accounts cannot carry interactive components** — components are an application-message feature.

## 4.5 Modals

Callback MODAL (9): `custom_id` 1–100, `title` ≤45, `components` 1–5 (Text Inputs; Labels in v2). Submission = MODAL_SUBMIT (5) with `data.custom_id` + `data.components[{custom_id, value}]`.

## 4.6 Webhooks

- Types: Incoming 1, Channel Follower 2 (not executable), Application 3.
- Execute: `POST /webhooks/{id}/{token}` — params `wait`, `thread_id` (auto-unarchives), `with_components`, `content` ≤2000, `username` ≤80, `avatar_url`, `tts`, `embeds` ≤10, `components`, `files`, `flags` (SUPPRESS_EMBEDS, SUPPRESS_NOTIFICATIONS, IS_COMPONENTS_V2), `thread_name`, `applied_tags`, `poll`; ≥1 of content/embeds/components/file/poll. Slack/GitHub-compatible variants.
- **Webhook creation is NOT bot-only**: `POST /channels/{id}/webhooks` requires only MANAGE_WEBHOOKS; webhook object's `user` field = creator (issue #5274). 🔶 (Hypothesis "user tokens can't create webhooks" is false per docs.)
- Channel followers: `POST /channels/{id}/followers` (MANAGE_WEBHOOKS; ~10/h limit).

## 4.7 Selfbot relevance

User token CAN: invoke slash/context commands as the client (`POST /interactions` with application_id, channel_id, data, nonce, session_id, type), click buttons/selects on existing app messages, submit modals. User token CANNOT: register commands, receive app interactions, respond via interaction webhooks, or send components on its own messages. discord.py-self removes `app_commands`/`ui` for exactly this reason.

---

# 5. Gateway

## 5.1 Opcodes & close codes

Opcodes: 0 Dispatch, 1 Heartbeat, 2 Identify, 3 Presence Update, 4 Voice State Update, 6 Resume, 7 Reconnect, 8 Request Guild Members, 9 Invalid Session, 10 Hello, 11 Heartbeat ACK, 31 Request Soundboard Sounds, 43 Request Channel Info.

Close codes: 4000 unknown error (resumable), 4001 unknown opcode (yes), 4002 decode error (yes; also payload >4096 bytes), 4003 not authenticated (yes), **4004 auth failed (no — stop)**, 4005 already authenticated (yes), 4007 invalid seq (yes), 4008 rate limited (yes), 4009 session timed out (yes), **4010 invalid shard (no)**, **4011 sharding required (no)**, **4012 invalid API version (no)**, **4013 invalid intent(s) (no)**, **4014 disallowed intent(s) (no)**.

## 5.2 Lifecycle

1. `GET /gateway` (or `/gateway/bot` for bots: shards + session_start_limit).
2. Connect `wss://gateway.discord.gg/?v=10&encoding=json` (compress: zlib-stream/zstd-stream).
3. Hello (op 10) → heartbeat after `interval * jitter`, then every interval; `d` = last seq.
4. Identify (op 2): `token`, `properties {os, browser, device}` (`$`-prefixed deprecated, removed in v11), `compress`, `large_threshold` (50–250, default 50), `shard`, `presence`, `intents` (mandatory v8+ for bots).
5. Resume (op 6): `token`, `session_id`, `seq` on `resume_gateway_url`; missed events replayed.
6. Close 1000/1001 → session invalidated; otherwise resumable a few minutes.

READY: `v`, `user`, `guilds` (Unavailable Guilds for bots), `session_id`, `resume_gateway_url`, `shard?`, `application`. User sessions add client-only keys (sessions, relationships).

## 5.3 Intents (exact bits)

| Intent | Bit | Privileged |
|---|---|---|
| GUILDS | 1<<0 | |
| GUILD_MEMBERS | 1<<1 | **yes** |
| GUILD_MODERATION | 1<<2 | (renamed from GUILD_BANS) |
| GUILD_EXPRESSIONS | 1<<3 | (renamed from GUILD_EMOJIS_AND_STICKERS) |
| GUILD_INTEGRATIONS | 1<<4 | |
| GUILD_WEBHOOKS | 1<<5 | |
| GUILD_INVITES | 1<<6 | |
| GUILD_VOICE_STATES | 1<<7 | |
| GUILD_PRESENCES | 1<<8 | **yes** |
| GUILD_MESSAGES | 1<<9 | |
| GUILD_MESSAGE_REACTIONS | 1<<10 | |
| GUILD_MESSAGE_TYPING | 1<<11 | |
| DIRECT_MESSAGES | 1<<12 | |
| DIRECT_MESSAGE_REACTIONS | 1<<13 | |
| DIRECT_MESSAGE_TYPING | 1<<14 | |
| MESSAGE_CONTENT | 1<<15 | **yes** |
| GUILD_SCHEDULED_EVENTS | 1<<16 | |
| AUTO_MODERATION_CONFIGURATION | 1<<20 | |
| AUTO_MODERATION_EXECUTION | 1<<21 | |
| GUILD_MESSAGE_POLLS | 1<<24 | |
| DIRECT_MESSAGE_POLLS | 1<<25 | |

(Bits 17–19, 22–23 unused.) Privileged-intent approval threshold is now member-count based (~10k) with annual re-approval.

Key reading events (GUILDS intent): GUILD_CREATE/UPDATE/DELETE, CHANNEL_CREATE/UPDATE/DELETE, CHANNEL_PINS_UPDATE, THREAD_CREATE/UPDATE/DELETE, THREAD_LIST_SYNC, THREAD_MEMBER_UPDATE, THREAD_MEMBERS_UPDATE, GUILD_ROLE_*, STAGE_INSTANCE_*, VOICE_CHANNEL_STATUS_UPDATE. Message events (GUILD_MESSAGES/DIRECT_MESSAGES): MESSAGE_CREATE/UPDATE/DELETE, MESSAGE_REACTION_*, MESSAGE_POLL_*.

## 5.4 Guild subscriptions & chunking (user tokens)

- User accounts don't use intents; they use **guild subscriptions**: auto-subscribed to guilds < **75,000 members**; non-subscribed guilds deliver no non-stateful events (no on_message). Presences auto-synced only for friends/implicit relationships/open DMs.
- Chunking (full member cache) requires MANAGE_ROLES/KICK/BAN perms, or guilds <1,000 members with a viewable channel; else only voice-state members cached. **There is no reliable full member list for user accounts** 🔶.
- Request Guild Members (op 8, `limit=0` empty query) rate-limited per guild per 30 s since 2025-08-14 (changelog).
- `guild.member_count`/`guild.members` can be partial/None (project-verified; chunking disabled).

## 5.5 Sharding

Formula `shard_id = (guild_id >> 22) % num_shards`; ≤2500 guilds/shard (4011 beyond); `GET /gateway/bot` → recommended shards, `session_start_limit {total (1000), remaining, reset_after (4 h), max_concurrency}`; concurrency key `shard_id % max_concurrency`; large bots: `max(2000, guilds/1000*5)` sessions/day. **discord.py-self 2.1.0 has no AutoShardedClient — user accounts don't shard.**

## 5.6 Gateway rate limits

- **120 events/60 s per connection** (2/s avg) → disconnect; repeat offenders lose API access.
- **1000 IDENTIFY/24 h** global across shards (RESUME excluded) → all sessions killed + **token reset** + owner emailed.
- Concurrent IDENTIFY bounded by max_concurrency/5 s. Client-sent payloads ≤ **4096 bytes** (close 4002).

## 5.7 v10 vs v9

v6: intents optional. v8: intents mandatory, form errors 50035. v9: threads added. v10: MESSAGE_CONTENT required for bots, `X-Audit-Log-Reason` header, `embeds` array, re-specify attachments on PATCH, guild-level `threads/active`, no discordapp.com. No v11/v12 as of 2026-08-02; v11 announced changes: thread-member list always paginated, `$os/$browser/$device` removed.

## 5.8 User-token gateway (observed, discord.py-self source)

- "While the gateway technically accepts intents for user accounts, they are — for the most part — useless and can break things" 🔶 (exact dolfies quote). Sending `intents` is "a giant waving red flag".
- User IDENTIFY sends `capabilities`, `client_state {guild_versions}`, `presence`, `compress`, `properties` (no `intents`, no `large_threshold`).
- Message content always present for user tokens (no MESSAGE_CONTENT gate).
- Client events relevant to selfbots: on_interaction, on_interaction_finish (INTERACTION_CREATE/SUCCESS/FAILURE client protocol), on_modal.

---

# 6. REST API

## 6.1 Versioning

`https://discord.com/api/v10` — v10 current stable (v9 also available). Versionless = newest default.

## 6.2 Key endpoints for reading state (selfbot-relevant)

| Purpose | Endpoint | User-token status |
|---|---|---|
| Current user | `GET /users/@me` | 200 ✅ LIVE (email/phone/mfa/premium_type fields) |
| List guilds | `GET /users/@me/guilds?with_counts=true` | 200 ✅ LIVE (max 200) |
| Own member object | `GET /users/@me/guilds/{id}/member` | documented |
| Get guild | `GET /guilds/{id}` | 200 ✅ LIVE (`member_count` null via REST) |
| Guild channels | `GET /guilds/{id}/channels` | 200 ✅ LIVE |
| Active threads | `GET /guilds/{id}/threads/active` | **403 20002 bot-only** ✅ LIVE |
| List guild members | `GET /guilds/{id}/members` | **403 50001 Missing Access** ✅ LIVE (bot path requires GUILD_MEMBERS intent; user behavior undocumented) |
| Single member | `GET /guilds/{id}/members/{user_id}` | **200** ✅ LIVE (self + others: nick, roles, joined_at, premium_since, pending, communication_disabled_until) |
| Search members | `GET /guilds/{id}/members/search?query=` | documented for bots; user-token behavior unverified ⚠️ |
| Roles | `GET /guilds/{id}/roles` | 200 ✅ LIVE |
| Audit log | `GET /guilds/{id}/audit-logs` | 403 50013 without VIEW_AUDIT_LOG ✅ LIVE |
| Channel | `GET /channels/{id}` | 200 ✅ LIVE (type 11 threads resolve: metadata + applied_tags) |
| Message history | `GET /channels/{id}/messages` | 200 ✅ LIVE (limit 100 honored) |
| Single message | `GET /channels/{id}/messages/{mid}` | documented |
| Pins | `GET /channels/{id}/pins` | 200 ✅ LIVE |
| Guild search | `GET /guilds/{id}/messages/search` | 200 ✅ LIVE (user-account endpoint; bots 403 20001) |
| Archived threads | `GET /channels/{id}/threads/archived/public` | 200 ✅ LIVE |
| DMs | `GET /users/@me/channels` | 200 ✅ LIVE (user-only) |
| Create DM | `POST /users/@me/channels` | documented |
| Vanity URL | `GET /guilds/{id}/vanity-url` | needs MANAGE_GUILD |
| Friends/relationships | `GET /users/@me/relationships` | user-only, undocumented 🔶 |

## 6.3 Pagination

- `before`/`after`/`around` (mutually exclusive) with snowflakes; messages limit 1–100 default 50; `after=0` fetches from beginning. Snowflake time: `(ms - DISCORD_EPOCH) << 22`.
- Search: `offset` (max **9975**) + `limit` 1–25 default 25; **don't rely on array length** (speed optimizations may return fewer).
- Archived threads: `before` = ISO timestamp; `has_more`.
- Audit log: `before` descending, `after` ascending, `after=0` oldest first.
- Reactions list: `type` 0/1, `after` user id, limit 1–100 default 25.

## 6.4 Guild message search — exact parameters

`GET /guilds/{id}/messages/search`. Requires READ_MESSAGE_HISTORY; bot apps need MESSAGE_CONTENT intent; **bots without it get 403 20001 "Bots cannot use this endpoint"** 🔶 (documented officially 2026-03-19; preview bot spec 2025-08-18). If the index isn't ready: HTTP **202 + code 110000 + `retry_after`**.

| Param | Constraint |
|---|---|
| `limit` | 1–25, default 25 |
| `offset` | max 9975 |
| `min_id` / `max_id` | snowflake window |
| `content` | ≤1024 |
| `slop` | ≤100, default 2 |
| `channel_id` / `author_id` / `mentions` / `mentions_role_id` | arrays ≤500 / ≤100 / ≤100 / ≤100 |
| `author_type` | `user`/`bot`/`webhook`, `-` negates |
| `mention_everyone` / `pinned` | bool |
| `replied_to_user_id` / `replied_to_message_id` | arrays ≤100 |
| `has` | `image`, `sound`, `video`, `file`, `sticker`, `embed`, `link`, `poll`, `snapshot` (`-` negates) |
| `embed_type` | `image`, `video`, `gif`, `sound`, `article` |
| `embed_provider` / `link_hostname` | arrays ≤100, ≤256 chars, case-sensitive |
| `attachment_filename` / `attachment_extension` | arrays ≤100 |
| `sort_by` | `timestamp` (default) / `relevance` |
| `sort_order` | `asc`/`desc`, default desc (ignored for relevance) |
| `include_nsfw` | default false |

Response: `total_results` (may be inaccurate during writes), `doing_deep_historical_index`, `documents_indexed?`, `messages` (nested arrays — **surrounding context no longer returned**), `threads?`, `members?`. Live: search "thor" → `total_results: 7702`, `doing_deep_historical_index: false`, inner arrays of single messages with `hit: true`, `threads[]` with full `thread_metadata` and `member_ids_preview` ✅ LIVE.

## 6.5 Message create/edit/delete

Create: `POST /channels/{id}/messages` — SEND_MESSAGES; TTS needs SEND_TTS_MESSAGES; reply needs READ_MESSAGE_HISTORY + non-system target; 25 MiB cap; content ≤2000; embeds ≤10; sticker_ids ≤3; flags settable: SUPPRESS_EMBEDS, SUPPRESS_NOTIFICATIONS, IS_COMPONENTS_V2.

Edit: `PATCH /channels/{id}/messages/{mid}` — content, embeds, flags, components, allowed_mentions, attachments, files; author-only (others: flags only w/ MANAGE_MESSAGES); v10+ attachments must list all retained; flags SUPPRESS_EMBEDS (set/unset), IS_COMPONENTS_V2 (set only). Error 30046 after ~10 edits of >1h-old messages 🔶.

Delete: 204. Bulk: 2–100 IDs, ≤2 weeks old, no duplicates.

## 6.6 Reactions

As §3.7. Emoji URL-encoded; custom `name:id`; error 10014 Unknown Emoji.

## 6.7 Rate-limit headers & conventions

`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Reset-After` (float s), `X-RateLimit-Bucket`, `X-RateLimit-Global` (429 only), `X-RateLimit-Scope` (429 only: `user`/`global`/`shared`). 429 body `{message, retry_after (float), global, code}`. Global 50 req/s per token; invalid-request ceiling 10,000/10 min/IP (401/403/429 count; `shared` 429s excluded). **Never hardcode limits; parse headers.** Full detail in `docs/DISCORD_RATE_LIMITS.md` (2026-08-01).

## 6.8 Error codes

Form errors: 400 `{code: 50035, errors: {field: {_errors: [...]}}}`. Notable: 10008 unknown message, 10014 unknown emoji, 20002 "Only bots can use this endpoint", 20001 "Bots cannot use this endpoint", 20028 channel write rate limit, 30046 max edits >1h, 50001 Missing Access, 50013 Missing Permissions, 50027 invalid webhook token, 110000 search index not ready, 160014 cannot forward unreadable content.

---

# 7. User tokens vs bot tokens

## 7.1 Authentication

User token: `Authorization: <token>` (no prefix). Bot: `Authorization: Bot <token>`. OAuth2 bearer: `Authorization: Bearer <token>`. User-account API is largely **undocumented** (client-internal routes).

## 7.2 Capability comparison

| Feature | User token (selfbot) | Bot token |
|---|---|---|
| Join servers | Accept invites / discovery / join requests | OAuth2 authorization only |
| Friends / relationships / group DMs | Full (undocumented endpoints) | **Cannot have friends** |
| DM channel list | `GET /users/@me/channels` ✅ LIVE | Only own DMs |
| Guild message search | **Works** ✅ LIVE | 403 20001 (preview spec only) |
| Active threads | **403 20002** ✅ LIVE | Works |
| Archived threads | Works ✅ LIVE | Works |
| REST member list | **403 50001** ✅ LIVE (bot docs: limit 1–1000 + GUILD_MEMBERS) | Works with intent |
| Full member enumeration | Gateway op 8 / sidebar scrape (rate-limited since 2025-08-14) | Op 8 + intent |
| GUILD_MEMBER_* events | Unreliable 🔶 | Reliable with intent |
| Gateway intents | Ignored/useless for user accounts 🔶 | Mandatory since v8; privileged gates |
| Message content | Always present 🔶 | Needs MESSAGE_CONTENT intent |
| Presence / custom status | Full incl. custom status 🔶 | Status/activity; no custom status text |
| Guild subscriptions | <75k-member auto-subscribe 🔶 | n/a (intents/chunking) |
| Register application commands | **No** ✅ | Yes |
| Invoke slash/context commands | Yes, client-side `POST /interactions` 🔶 | n/a |
| Receive app interactions | **No** | Yes (3 s / 15 min contract) |
| Send components on own messages | **No** | Yes |
| Click buttons / submit modals | Yes (client protocol) 🔶 | n/a (apps receive, not click) |
| Create webhooks | Yes with MANAGE_WEBHOOKS 🔶 | Same |
| Execute webhooks | Yes (no auth beyond id+token) | Same |
| Moderation endpoints | Yes, permission-gated | Same |
| User-only APIs (friends, sessions, read states, billing, custom status) | Yes 🔶 | No |
| Rate limits | Same architecture; stricter anti-abuse heuristics | Same; scale-up possible |

## 7.3 Key endpoint findings

- **Search is user-account-only** (bots 403 20001; staff: "it's for user accounts" — discord-api-docs #1754, discussion #3216). Bot search exists only as 2025-08-18 preview spec.
- **`threads/active` is bot-only** (403 20002, reproduced by discord.js-selfbot-v13 #119 and ✅ LIVE). Official client uses per-channel `threads/search` for dropdowns.
- **Member enumeration**: REST `GET /guilds/{id}/members` 403 for inebotten ✅ LIVE. Single-member fetch works ✅ LIVE. discord.py-self: `Guild.chunk()` (sidebar scrape; <1k members, only online above), `fetch_members()` (needs kick/ban/manage-roles for the "normal" path), `query_members()` (op 8 with IDs/names).
- **Webhooks**: creation is NOT bot-restricted (docs + issue #5274).
- **Interactions**: registration needs bot/client-credentials token (no user path); user tokens act as the client only.

## 7.4 ToS & ban risk

- Official: "Automating normal user accounts (generally called 'self-bots') outside of the OAuth2/bot API is forbidden, and can result in an account termination if found" (support article 115002192352, updated 2024-04-05). Developer ToS repeats it. Current Terms (2025-09-29) ban scraping without written consent and unauthorized software; the word "selfbot" lives in the support/developer articles.
- Enforcement: account termination; community reports of ban waves (undiscord #193, 2021). Detection heuristics (telemetry absence, TLS fingerprints, timing rhythms) are **community speculation** ⚠️ — Discord publishes nothing.
- dolfies README: "Automating user accounts is against the Discord ToS… proof of concept… use at your own risk."

## 7.5 Safe-usage patterns

Human pacing; minimal writes; randomized small delays; one gateway connection; honor Retry-After; no mass actions; don't send `intents`; keep `guild_subscriptions` defaults; no full-member enumeration; prefer a real bot account whenever the task doesn't require acting as the user. Project limits (`core/rate_limiter.py`: 5 msg/s global, 10k/day) stay as-is.

---

# 8. discord.py-self v2.1.0 API mapping

All names verified from installed 2.1.0 source (`[src]`) or RTFD docs (`[docs]`, may describe 2.2-dev). **Headline corrections vs discord.py habits:** no `discord.Intents`, no `AutoShardedClient`, no `Guild.active_threads`/`fetch_active_threads()`, no `GuildSearchResult`, no `Client.search`, no `discord.ui`/`View`; `ForumChannel.start_thread` → `create_thread`; `fetch_audit_logs` → `audit_logs()`; `fetch_webhooks` → `webhooks()`; `fetch_vanity_invite` → `vanity_invite()`; `Webhook.from_partial` → `partial()`; `Webhook.execute` → `send()`; `create_stage_instance` → `create_instance()`; `Guild.permissions_for` → `channel.permissions_for()` / `Member.guild_permissions`; `Message.edit` returns the edited Message and has no embeds/components.

## 8.1 Client

```python
bot = discord.Client()          # no intents= parameter (TypeError if passed)
await bot.login(token)          # plain user token; no bot=True
await bot.start(token, reconnect=True)

async def setup_hook(self): ...      # client.py:921
async def on_ready(self): ...        # self.user, self.guilds

await client.fetch_user(uid)                      # client.py:2530
await client.fetch_channel(cid)                   # client.py:2629
await client.fetch_guild(gid, with_counts=True)   # client.py:2024
await client.fetch_guilds(with_counts=True)       # client.py:1966 -> List[UserGuild] (partial)
await client.change_presence(activity=..., status=..., edit_settings=True)  # client.py:1803
```

- `_ClientOptions` keywords: max_messages, proxy, member_cache_flags, chunk_guilds_at_startup, guild_subscriptions, status/activity/activities, allowed_mentions, heartbeat_timeout, enable_debug_events, sync_presence, captcha_handler, timezone, canary, etc.
- `client.user.guilds` does **not** exist — use `client.guilds` (gateway cache) or `fetch_guilds()`.
- `Client.search` does not exist; search lives on Guild/Channel.

## 8.2 Guild

```python
def search(self, content=MISSING, *, contents=None, slop=MISSING, limit=25, offset=0,
           before=MISSING, after=MISSING, include_nsfw=MISSING, channels=None,
           authors=None, author_types=None, mentions=None, mention_everyone=False,
           pinned=False, has=None, embed_types=None, embed_providers=None,
           link_hostnames=None, attachment_filenames=None, attachment_extensions=None,
           application_command_id=MISSING, application_command_name=MISSING,
           oldest_first=False, most_relevant=False) -> AsyncIterator[Message]   # guild.py:2935

async for m in guild.search("vault", limit=200, authors=[uid], has=["link"]):
    print(m.total_results, m.hit, m.id, m.content)
```

- Search results are plain `Message`s carrying `total_results`, `hit`, `analytics_id`, `doing_deep_historical_index` (message.py:2123) — **no `(before, message, after)` tuples in 2.1.0**; reactions in results are incomplete (docstring).
- No public `sort_by`/`sort_order` params (internal payload keys only). `most_relevant=True` caps pagination at 10,000. Search endpoint can time out and return fewer results than requested (issue #581).
- `await guild.fetch_members(channels=None, *, cache=False, force_scraping=False, delay=0) -> List[Member]` (guild.py:5153) — websocket op, sidebar scrape fallback, can hang (#907). Lighter: `guild.query_members(query=None, *, limit=5, user_ids=None, presences=True, cache=True, subscribe=False)`.
- `await guild.fetch_channels()`, `async for e in guild.audit_logs(limit=50, user=..., action=...)`, `guild.threads` (active, viewable), `guild.get_thread(id)`, `guild.roles`, `guild.member_count` (Optional), `await guild.webhooks()`, `await guild.vanity_invite()`, `guild.vanity_url`.

## 8.3 Channels

- **TextChannel**: `channel.history(*, limit=100, before, after, around, oldest_first)`; `channel.send(content=None, *, tts, stickers, delete_after, nonce, allowed_mentions, reference, mention_author, suppress_embeds, silent, poll=None)` — **no embed/embeds/components params**; `delete_messages` (max 100); `create_thread(*, name, message=None, auto_archive_duration, type, invitable=True, slowmode_delay)` (message=None → private); `channel.webhooks()` / `create_webhook(...)`; `channel.threads`, `channel.get_thread(id)`; `channel.search(...)` (routes through guild endpoint, #557); pin/unpin are Message methods.
- **VoiceChannel** `connect(...)`, `move_to`, `play`; **StageChannel** `create_instance(*, topic, privacy_level, send_start_notification)` / `fetch_instance()`; **CategoryChannel** `create_text_channel/create_voice_channel/create_stage_channel`, `channels`.
- **ForumChannel** (channel.py:2467): `await forum.create_thread(*, name, auto_archive_duration, slowmode_delay, content, file/files, stickers, applied_tags=[], ...) -> ThreadWithMessage` (NamedTuple: `.thread`, `.message`); `forum.get_thread(id)`; `forum.threads`; `async for t in forum.archived_threads(limit=100, before=None)`; **no `history`/`send`/`start_thread`** — those raise AttributeError.
- **Thread** (threads.py:67): `parent`/`channel` aliases; `edit(*, name, archived, locked, invitable, pinned, slowmode_delay, auto_archive_duration, applied_tags)` — archiving = `edit(archived=True)` (no archive()/lock() methods); `join()`, `leave()`, `fetch_members()` (`.members` empty until then); `starter_message`, `add_tags/remove_tags`, `add_user/remove_user`, full message surface (`history`, `send`, `search`, `pins`, `purge`).
- **DMChannel**: `recipient` (singular), `accept()/decline()` (DM requests), `add_recipients`; **GroupChannel**: `add_recipients/remove_recipients`, `ack`.
- **PartialMessage**: `fetch()`, `edit(content=None, attachments=MISSING)`, `delete(delay=None)`, `pin/unpin`, `publish()`, `reply`.

## 8.4 Messages

- Fields: `id`, `channel`, `guild`, `author`, `content`, `embeds`, `attachments`, `components` (read-only payload models), `stickers`, `reactions`, `poll`, `reference` (with `.resolved` incl. DeletedReferencedMessage), `type`, `flags`, `activity`, `application`, `interaction`, `message_snapshots`, `nonce`, `pinned`, `tts`, `position`, `webhook_id`, `created_at`/`edited_at`, search-only `hit`/`total_results`/`analytics_id`/`doing_deep_historical_index`.
- Methods: `edit(content=None, attachments=MISSING, suppress=False, delete_after=None, allowed_mentions=None) -> Message` (returns new Message; **no embeds/components/poll**); `delete(*, delay=None)`; `pin/unpin(*, reason)`; `publish()`; `add_reaction(emoji, *, boost=False)` (super-reactions), `remove_reaction(emoji, *, boost=False)`, `remove_reaction(emoji, member=None)`, `clear_reaction(emoji)`, `clear_reactions()`; `reply(content, **kwargs)`; `ack()`; `fetch_thread()`; `end_poll()`.
- **No `Message.history`** — use `channel.history()`.

## 8.5 Components & interactions (user-token model)

```python
# Components are read-only payloads; clicking performs the user's own interaction
res = await message.components[0].click()          # -> str (link) or Interaction
await select_menu.choose(*options)                 # SelectMenu.choose
await modal.submit()                               # Modal.submit

async def on_interaction(self, interaction):       # state.py:3528
    print(interaction.id, interaction.type, interaction.user, interaction.successful)
async def on_modal(self, modal): ...
```

- No `View`/`ui`/`InteractionResponse`; `Interaction` has no `.response` and no ephemeral support (user tokens can't do ephemeral).
- `SlashCommand` (commands.py:560): invoke via `await command(channel=..., **options)`; enumerate `async for cmd in channel.slash_commands()`. `UserCommand`/`MessageCommand` for context menus. (Docs' `lnCommand` naming is 2.2-dev, not 2.1.0.)
- Known component-click failures (closed issues): threads 400 (#885), large servers (#631), missing application ID (#178), nonce crash (#311).

## 8.6 Webhooks

```python
wh = discord.Webhook.from_url(url)          # async_ Webhook; SyncWebhook for sync
wh2 = discord.Webhook.partial(id, token)    # renamed from from_partial
await wh.send("hei", embed=discord.Embed(title="x"), thread=..., applied_tags=...)
```

- `send()` (not `execute()`) is the only send method in 2.1.0; docs-latest `components=` param is 2.2-dev only. Executing webhooks by URL works without bot auth — **the standard selfbot route for embeds** (plain user messages can't carry embeds via send()).
- `create_webhook` exists on channels; platform behavior for user tokens is permission-dependent (⚠ not library-verified).

## 8.7 Gateway & polling

- No Intents; user IDENTIFY sends `capabilities` (gateway.py:448–490); `guild_subscriptions` client option (default True); `chunk_guilds_at_startup`; `client.sessions` for multiple gateway sessions.
- Events: `on_connect`, `on_ready`, `on_resumed`, `on_disconnect`, `on_socket_event_type` (needs `enable_debug_events=True`), `on_guild_available/unavailable`, `on_presence_update`, `on_poll_vote_add/remove` + `on_raw_poll_vote_*`.

## 8.8 Polls (new in 2.1.0)

```python
import datetime
poll = discord.Poll(question="Hvor?", duration=datetime.timedelta(hours=24),
                    multiple=False, layout_type=discord.PollLayoutType.default)
poll.add_answer(text="Café", emoji="☕").add_answer(text="Parken")
msg = await channel.send("Avstemning", poll=poll)   # send(poll=...) is the only creation path
print(msg.poll.total_votes, msg.poll.victor_answer)
await msg.poll.end()          # or await msg.end_poll()
```

- `Poll(question, duration, *, multiple=False, layout_type=default)`; duration in hours (max 7 days per Discord); `add_answer(*, text≤55, emoji=None)` chains, raises once attached; `PollAnswer` has `text`/`emoji`, `vote_count` (approximate until finalized), `self_voted`, `victor`; `PollLayoutType` has `default=1` and `layout_2` (two columns). Search results include polls.

## 8.9 Known quirks for user tokens (2.1.0)

1. Search truncation/timeout: `guild.search(limit=None)` may return only ~2 pages (#581); don't assume "less than limit ⇒ done".
2. Incomplete reactions in search results (documented docstring).
3. `fetch_members()` hangs on some guilds (#907, open) — prefer `query_members()`.
4. Thread cache sparse: `guild.threads` = active viewable only; `Thread.members` empty until `fetch_members()`; no active-threads API.
5. ForumChannel has no `history`/`send` — AttributeError (common dpy-migration crash).
6. Plain messages: no embeds/components/polls-with-ui — embeds only via Webhook.send.
7. Renames vs discord.py break migrated code (list in §8 header).

---

# 9. Discord product/design conventions

## 9.1 Server organization & naming

- Channel list is the first impression: purpose-labeled channels, categories group related channels, topics + pins supplement names (Discord's own community guide).
- Names truncate at ~25 chars in the sidebar; keep short. Channel names should be unique server-wide (mention confusion). API enforces `[a-z0-9-_]{1,100}` — client auto-formats lowercase-with-dashes.
- Emoji in names OK in moderation; verb channels (`get-roles`, `submit-clips`) vs noun channels (`rules`, `announcements`); typical order: INFORMATION → COMMUNITY → topic categories → voice → staff-only.

## 9.2 Discoverability

- Community server required for most discovery/onboarding features (rules channel, verified-email restriction, 2FA).
- Server Discovery: **1,000+ members, 8+ weeks old**, activity requirements, clean naming, Discovery Guidelines compliance.
- Spotlight = curated placement ⚠️ (FAQ URL unverified). Official Game Communities add vanity URL + verified badge.
- Welcome Screen / Server Guide / Rules Screening are the onboarding surfaces; Server Guide replaces Welcome Screen when enabled.

## 9.3 Community-server best practices (Discord's own guidance)

- Onboarding: 7+ default channels (≥5 with @everyone View+Send) to publish; customization questions grant roles/channels; required questions for critical channels.
- Dedicated rules channel; document rules before moderation; least-privilege roles; category permission cascade; AutoMod + member screening + slowmode + timeouts; Server Insights for decisions; stages/announcement/forum usage patterns.

## 9.4 UI layout conventions

- Server rail (icons, unread/badges) → channel list (collapsible uppercase categories, channel-type icons, threads nested under parents) → messages (author header, avatar, content; grouped consecutive messages) → member list (right sidebar, `Ctrl/Cmd+U`). Dark default theme; voice-state cards; stage speaker/listener layout.

## 9.5 Accessibility

- Discord claims **WCAG 2.1 AA** compliance (accessibility statement); High Contrast Mode, screen-reader support, keyboard nav, reduced motion, text-to-speech, typography scale, sync profile themes; 2026-04 a11y blog.
- Embed authoring implications: color must not be the only signal (WCAG 1.4.1), AA contrast (≥4.5:1 body, ≥3:1 large), aria-labels/fallback text for links.
- Keyboard: `Ctrl/Cmd+K` quick switcher, `Ctrl/Cmd+F` channel search, `Ctrl+Shift+F` global search, `Alt+Up/Down` channel move, `Shift+Up`/`Option+Up` edit last message, `Ctrl/Cmd+U` member list, `Ctrl/Cmd+P` pins, `Ctrl/Cmd+,` settings, `Ctrl/Cmd+/` shortcuts.

## 9.6 Moderation conventions

Slowmode (seconds → 6 h); verification levels (None → verified email → +5-min account → +10-min member → +verified phone); explicit content filter; AutoMod (keyword/mention/spam/link, regex); member screening/onboarding gates; timeouts vs bans with appeals; Community Guidelines (13+ age, no harassment/spam/scams).

## 9.7 Premium & branding

Boosts 2/7/14 → levels 1/2/3 (perks table in §1.7); additional 3-boost perks (Server Tags, Enhanced Role Styles, Game Server Hosting). Nitro: animated emoji anywhere, higher uploads, profile themes. Brand color **Blurple `#5865F2`**; logo use in color/black/white only with clearspace (discord.com/branding).

---

# 10. Capability matrix — feature × access path for a user-token selfbot

**Columns:** REST = raw `discord.com/api/v10` with user token · GW = gateway (user session) · dpy = discord.py-self 2.1.0 API · ✗ = not possible / bot-only.

| Feature | REST (user token) | Gateway | discord.py-self 2.1.0 | Notes |
|---|---|---|---|---|
| List my guilds | ✅ `GET /users/@me/guilds` | `client.guilds` | `client.guilds` / `await client.fetch_guilds()` | partial guilds; with_counts ✅ LIVE |
| Read guild metadata | ✅ `GET /guilds/{id}` | GUILD_CREATE | `await client.fetch_guild()` | member_count null via REST ✅ LIVE |
| List channels | ✅ `GET /guilds/{id}/channels` | CHANNEL_* events | `await guild.fetch_channels()` | ✅ LIVE |
| Channel types/layout | ✅ type/position/parent_id | same | `GuildChannel` classes | ✅ LIVE |
| Roles | ✅ `GET /guilds/{id}/roles` | GUILD_ROLE_* | `guild.roles` | ✅ LIVE |
| Permission calc | ✅ (bitfields) | n/a | `channel.permissions_for(member)`, `Member.guild_permissions` | verified per-channel API |
| Audit log | ✅ (needs VIEW_AUDIT_LOG) | GUILD_AUDIT_LOG_ENTRY_CREATE | `async for e in guild.audit_logs()` | ✅ LIVE 403 w/o perm |
| Message history | ✅ `GET /channels/{id}/messages` | MESSAGE_CREATE cache | `channel.history()` | limit 100 ✅ LIVE |
| Read pins | ✅ `GET /channels/{id}/pins` | CHANNEL_PINS_UPDATE | `channel.pins` | ✅ LIVE |
| Guild search | ✅ (user-only) | n/a | `guild.search()` / `channel.search()` | total_results, lag, incomplete reactions ✅ LIVE |
| Active threads (guild) | ✗ 403 20002 | `guild.threads` cache (sparse) | `guild.threads`, `get_thread()` | use search/archived instead ✅ LIVE |
| Archived threads (public) | ✅ `threads/archived/public` | n/a | `forum.archived_threads()` / `channel.archived_threads()` | ISO timestamp pagination ✅ LIVE |
| Forum post read | ✅ thread id as channel | THREAD_CREATE | `thread.history()` | ✅ LIVE |
| Create forum post / thread | ✅ `POST /channels/{id}/threads` | n/a | `forum.create_thread()` / `channel.create_thread()` | writes: only on explicit approval |
| Thread metadata | ✅ `GET /channels/{id}` | THREAD_UPDATE | `Thread` fields | create_timestamp ✅ LIVE |
| Member list (all) | ✗ 403 50001 | op 8 chunk / sidebar scrape | `guild.fetch_members()` (may hang), `query_members()` | no reliable full list 🔶 |
| Single member | ✅ `GET /guilds/{id}/members/{uid}` | GUILD_MEMBER_UPDATE | `guild.get_member()` (cache) | ✅ LIVE |
| Send message | ✅ `POST /channels/{id}/messages` | n/a | `channel.send()` | writes: explicit approval only |
| Edit/delete own message | ✅ PATCH/DELETE | MESSAGE_UPDATE/DELETE | `message.edit()` / `delete()` | edit returns new Message |
| React | ✅ PUT/DELETE reactions | MESSAGE_REACTION_* | `message.add_reaction(boost=)` | ✅ endpoints live |
| Polls | ✅ create/vote (SEND_POLLS) | MESSAGE_POLL_* events | `Poll(...)` + `send(poll=)` | creation is send()-based |
| Embeds on own messages | ✗ (user messages can't carry embeds via send) | n/a | ✗ `send()` has no embed param | use webhooks instead |
| Components on own messages | ✗ (app feature) | n/a | ✗ no View/ui | read-only payloads |
| Click buttons/selects/modals | ✅ client `POST /interactions` | INTERACTION_CREATE/SUCCESS/FAILURE | `component.click()`, `menu.choose()`, `modal.submit()` | fragile in threads/large servers 🔶 |
| Register slash commands | ✗ no auth path | ✗ | ✗ `app_commands` removed | bot/client-credentials only |
| Receive app interactions | ✗ | ✗ (client protocol only) | `on_interaction` (client-side only) | no token/callback flow |
| Webhook execute | ✅ `POST /webhooks/{id}/{token}` | n/a | `Webhook.from_url().send()` | **the embeds route** |
| Webhook create | ✅ with MANAGE_WEBHOOKS | n/a | `channel.create_webhook()` | not bot-restricted 🔶 |
| DMs / friends | ✅ user-only endpoints | DM events | `DMChannel`, `GroupChannel` | ✅ LIVE (`/users/@me/channels`) |
| Presence / custom status | ✅ PATCH settings | op 3 | `client.change_presence(edit_settings=True)` | custom status = user-only |
| Gateway intents | n/a | ✗ ignored/useless | ✗ no `Intents` class | "waving red flag" 🔶 |
| Full message content | ✅ always | ✅ always | ✅ | no MESSAGE_CONTENT gate for users |
| Guild audit-log entry stream | n/a | GUILD_MODERATION intent (user: unreliable) | n/a | 🔶 |

---

# 11. Gotchas & verified facts

## 11.1 Verified live against inebotten (2026-08-02, read-only)

| # | Fact | How verified |
|---|---|---|
| 1 | Identity: inebotten `1474528156131266815`, **11 guilds**; launchd service `local.inebotten.selfbot` running | `inebotten_ctl.py status`, `launchctl list` |
| 2 | `GET /guilds/{id}/threads/active` → **403 code 20002 "Only bots can use this endpoint"** | raw REST (THORChain Devs) |
| 3 | `GET /guilds/{id}/members?limit=1` → **403 code 50001 "Missing Access"** (user token) | raw REST |
| 4 | `GET /guilds/{id}/members/{user_id}` → **200** (self + other: nick, roles, joined_at, premium_since, pending, communication_disabled_until) | raw REST |
| 5 | `GET /guilds/{id}/audit-logs` → **403 code 50013 "Missing Permissions"** (no VIEW_AUDIT_LOG) | raw REST |
| 6 | Guild search works: `content=thor&limit=1` → 200, `total_results: 7702`, `doing_deep_historical_index: false`; result shape = single-message arrays with `hit: true`, `position`; `threads[]` embedded with full `thread_metadata` + `member_ids_preview` | raw REST |
| 7 | Search **can lag** recent messages; history endpoint is authoritative (skill note re-verified by design) | doc + project notes |
| 8 | Archived forum listing works: `threads/archived/public?limit=5` → `has_more: true`, ISO `archive_timestamp` pagination | raw REST |
| 9 | Forum channel fields live: `default_forum_layout: 1`, `default_sort_order: 0`, 2 tags, `default_reaction_emoji` | raw REST |
| 10 | Channel enumeration: THORChain Devs = 175 text + 11 category + 10 announcement + 1 stage + 1 forum (types 0/4/5/13/15); overwrites, slowmode 60 s, `icon_emoji`/`theme_color` present | raw REST |
| 11 | `GET /guilds/{id}`: `member_count: null` via REST (matches docs — member_count is gateway-only), `premium_tier: 3`, 15 boosts, `verification_level: 2`, `vanity_url_code: "thorchaindevs"` | raw REST |
| 12 | `GET /users/@me/channels` → 200, 4 DMs (user-only endpoint works) | raw REST |
| 13 | Pins: 21 pinned messages readable in dev-general | raw REST |
| 14 | History pagination: `limit=100` returns exactly 100 | raw REST |
| 15 | Thread metadata via `GET /channels/{id}` on a thread id: type 11, `archive_timestamp`, `auto_archive_duration: 10080`, `create_timestamp`, `applied_tags`, `total_message_sent`, `member_ids_preview` | raw REST |
| 16 | `GET /users/@me/guilds?with_counts=true` → features arrays incl. VANITY_URL, COMMUNITY, DISCOVERABLE, GUILD_ONBOARDING, WELCOME_SCREEN_ENABLED; approximate member/presence counts | raw REST |
| 17 | Two short gateway sessions (bot + ctl) are fine; chunking off ⇒ partial `guild.members`/`member_count` | project skill + live status |

## 11.2 Doc-only / library-observed (not live-verified)

- Embeds/attachment/component/poll exact limits (§3) — from official docs, fetched 2026-08-02; not exercised against the account.
- Interaction timing (3 s / 15 min), command registration caps — official docs; not exercisable with a user token.
- User-token `threads/search` per-channel endpoint, `GET /users/@me/messages/search` — undocumented, library/client-observed 🔶.
- `fetch_members()` hang (#907), search 2-page truncation (#581) — GitHub issues; not reproduced live.
- Upload tier numbers (Nitro 500 MB, Basic 50 MB) — Help Center; not live-tested.
- Vanity URL Level-3 requirement — Help Center; API docs silent.
- Bot search preview spec (2025-08-18) availability — ⚠️ unstable preview, may not be live.
- Detection heuristics for selfbots — community speculation ⚠️.

## 11.3 Confirmed API quirks worth remembering

- Search pagination: offset cap 9975; `include_nsfw=true` needed for NSFW channels; `sort_by=timestamp`.
- `messages` command crashes on forum channels (no history) — use `threads`/`thread`/`archived_threads`.
- `before` for archived threads = ISO `archive_timestamp`, not a message id.
- Thread metadata field is `create_timestamp` (API) — discord.py-self maps it to `created_at`.
- User messages can't send embeds via `send()` — only via webhooks.
- `member_count`/`members` partial without chunking; single-member REST fetch is the reliable per-user lookup.
- `guild.permissions_for` doesn't exist — `channel.permissions_for()`.
- Docs URLs: `docs.discord.com/developers/*.md` current; old `resources/forum-channel` 404s.

---

# 12. Sources

## 12.1 Version pins (2026-08-02)

- Discord API: **v10** current (v9 available). Reference: https://docs.discord.com/developers/reference.md · Changelog (v11 future changes, 2025-2026 entries): https://docs.discord.com/developers/change-log.md
- discord.py-self: **2.1.0** — PyPI https://pypi.org/project/discord.py-self/ · GitHub https://github.com/dolfies/discord.py-self (release v2.1.0, 2026-01-18, tag `6de18b4cb40dd42625a535f52d9715c71399ffb3`) · docs https://discordpy-self.rtfd.io/en/latest/

## 12.2 Official Discord developer docs (fetched 2026-08-02)

- Reference/versions/upload limits: https://docs.discord.com/developers/reference.md
- Channel resource (types, thread metadata, forum tags/layout): https://docs.discord.com/developers/resources/channel.md
- Guild resource (fields, premium tier, verification, features, welcome screen, onboarding, vanity URL): https://docs.discord.com/developers/resources/guild.md
- Permissions topic (bits, overwrite order, implicit perms, threads): https://docs.discord.com/developers/topics/permissions.md
- Threads topic: https://docs.discord.com/developers/topics/threads.md
- Message resource (types, flags, embeds, attachments, references, search, pins): https://docs.discord.com/developers/resources/message.md
- Poll resource: https://docs.discord.com/developers/resources/poll.md
- Audit log resource: https://docs.discord.com/developers/resources/audit-log.md
- Sticker / Emoji resources: https://docs.discord.com/developers/resources/sticker.md · https://docs.discord.com/developers/resources/emoji.md
- Components reference + using components: https://docs.discord.com/developers/components/reference.md · https://docs.discord.com/developers/components/using-message-components.md
- Application commands: https://docs.discord.com/developers/interactions/application-commands.md
- Receiving & responding (timing, callbacks, ephemeral): https://docs.discord.com/developers/interactions/receiving-and-responding.md
- Webhook resource: https://docs.discord.com/developers/resources/webhook.md
- Gateway + gateway events + opcodes: https://docs.discord.com/developers/events/gateway.md · https://docs.discord.com/developers/events/gateway-events.md · https://docs.discord.com/developers/topics/opcodes-and-status-codes.md
- Rate limits: https://docs.discord.com/developers/topics/rate-limits.md
- User resource / Application resource: https://docs.discord.com/developers/resources/user.md · https://docs.discord.com/developers/resources/application.md
- OAuth2 (bot vs user): https://docs.discord.com/developers/topics/oauth2
- Community servers (dev): https://docs.discord.com/developers/communities/overview
- Docs index: https://docs.discord.com/llms.txt

## 12.3 Discord Help Center / product pages

- Automated User Accounts (Self-Bots): https://support.discord.com/hc/en-us/articles/115002192352
- Developer ToS: https://support-dev.discord.com/hc/articles/8562894815383
- Discord Terms: https://discord.com/terms · Guidelines: https://discord.com/guidelines
- Server Boosting FAQ: https://support.discord.com/hc/en-us/articles/360028038352
- Nitro FAQ (uploads): https://support.discord.com/hc/en-us/articles/115000435108 · File Attachments: https://support.discord.com/hc/en-us/articles/25444343291031
- Custom Invite Link: https://support.discord.com/hc/en-us/articles/115001542132
- Enabling Community Server / Discovery / Onboarding: https://support.discord.com/hc/en-us/articles/360047132851 · https://support.discord.com/hc/en-us/articles/360030843331 · https://support.discord.com/hc/en-us/articles/11074987197975
- Channel categories & names: https://discord.com/community/channel-categories-and-names
- Community admin guides: https://discord.com/community/community-admin
- Verification levels: https://support.discord.com/hc/en-us/articles/216679607 · AutoMod FAQ: https://support.discord.com/hc/en-us/articles/4421269296535 · Sensitive content: https://support.discord.com/hc/en-us/articles/18210995019671
- Accessibility: https://discord.com/accessibility · https://discord.com/accessibility-statement · keyboard shortcuts: https://support.discord.com/hc/en-us/articles/31232432266647
- Branding (Blurple #5865F2): https://discord.com/branding

## 12.4 GitHub evidence

- discord/discord-api-docs: search user-only #1754 + discussion #3216; webhooks #5274; error 30046 #4413; crosspost edit #6109; changelog 2025-08-14 guild-members rate limit; bot search preview commit `976faf1` (discord-api-spec).
- dolfies/discord.py-self: issues #18, #178, #311, #440, #557, #581, #631, #695, #779, #800, #823, #885, #907; source files with line refs: guild.py L2935 (search), L5153 (fetch_members), L4571 (audit_logs); channel.py L2938 (forum create_thread), L3134 (archived_threads); threads.py L67; message.py L1995–2127; poll.py L323; components.py L158; interactions.py L56; modal.py L48; commands.py L560; client.py L921/L945/L1966; gateway.py L448–490; state.py L3528.
- aiko-chan-ai/discord.js-selfbot-v13 #119 (threads/active 403 20002); victornpb/undiscord #193 (enforcement).

---

# 13. Recommended additions to the inebotten skill

> **Status (2026-08-02): implemented.** Items 1–7 below were applied to
> `scripts/inebotten_ctl.py` (new `member`, `roles`, `pins`, `guild`,
> `dm-channels`, `threads-search` subcommands, all verified live), to
> `~/.codex/skills/inebotten/SKILL.md` (quick commands + 2.1.0 library pins +
> threads-search discovery), and to `~/.codex/skills/inebotten/references/control.md`
> (verified error codes 20002/50001/50013, search result shape, single-member
> fetch, REST `member_count` null, docs URL migration, experimental
> `threads/search`). The `threads-search` endpoint was additionally verified
> live and returns active + archived threads.

1. **New ctl commands** (all read-only, all verified possible live):
   - `member <guild> <user-id>` — single-member fetch via `GET /guilds/{id}/members/{uid}` (works where the members list endpoint 403s; returns nick/roles/joined_at).
   - `roles <guild>` — list guild roles (id, name, position, permissions bitfield).
   - `pins <guild> <channel>` — read pinned messages (verified 200).
   - `dm-channels` — list `GET /users/@me/channels` (user-only).
   - `guild <guild>` — guild metadata: premium_tier, verification_level, vanity_url_code, features, member_count (null via REST), boost count.
2. **Update `references/control.md`** with the verified error codes and workarounds: `threads/active` → **403 20002** (bot-only), `GET /guilds/{id}/members` → **403 50001**, audit logs → **403 50013** without permission; single-member fetch works; search response shape is single-message arrays (`hit`, `total_results`, `threads[]` embedded) — **not** `(before, message, after)` tuples; `member_count` is null via REST (gateway-only field).
3. **Note the search fallback for active threads:** per-channel `GET /channels/{id}/threads/search` (undocumented, official-client behavior) — mark experimental, unverified for inebotten.
4. **Pin discord.py-self 2.1.0 facts in the skill** so future sessions don't use discord.py habits: no `Intents`, no `View`/`ui`, no `Guild.active_threads`, `send()` has no `embed`/`components`, `Message.edit` returns a new Message, forum = `create_thread` + `archived_threads` (no `history`), search is `Guild.search()` async iterator with per-message `total_results`.
5. **Embeds:** document that user messages can't carry embeds via `send()` — the selfbot route is `Webhook.from_url(url).send(embed=...)` (no bot auth needed).
6. **Docs URL migration:** cite `docs.discord.com/developers/*.md` (old `resources/forum-channel` 404s); API version pinned to v10.
7. **Poll support:** ctl could expose poll reading (`message.poll` is parsed from history and search) — read-only, no votes.

---

*End of reference. Rate-limit detail lives in `docs/DISCORD_RATE_LIMITS.md`; live-state commands live in `scripts/inebotten_ctl.py` and the inebotten skill.*

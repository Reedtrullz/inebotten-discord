#!/usr/bin/env python3
"""Inebotten control CLI: query and drive the inebotten Discord account.

Uses the same user token as the selfbot (.env -> DISCORD_USER_TOKEN).
One-shot connection: connect, do the operation, disconnect.
Never prints the token.

Examples:
  scripts/inebotten_ctl.py guilds
  scripts/inebotten_ctl.py channels thorchain
  scripts/inebotten_ctl.py messages thorchain general --limit 20
  scripts/inebotten_ctl.py messages thorchain mainnet-info --embeds
  scripts/inebotten_ctl.py search thorchain "vault" --limit 30
  scripts/inebotten_ctl.py search thorchain "avax" --channel mainnet-info --before 2026-02-01 --after 2025-12-01
  scripts/inebotten_ctl.py threads thorswap "community-ideas"
  scripts/inebotten_ctl.py thread 1532069389581422773 --limit 50
  scripts/inebotten_ctl.py member thorchain 1474528156131266815
  scripts/inebotten_ctl.py roles thorchain
  scripts/inebotten_ctl.py pins thorchain dev-general
  scripts/inebotten_ctl.py guild thorchain
  scripts/inebotten_ctl.py dm-channels
  scripts/inebotten_ctl.py threads-search thorchain dev-general "node" --limit 25
  scripts/inebotten_ctl.py send thorchain general "hello"
"""

import argparse
import asyncio
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aiohttp
import discord


def load_token() -> str:
    tok = os.getenv("DISCORD_USER_TOKEN")
    if tok:
        return tok
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_USER_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DISCORD_USER_TOKEN not found in env or .env")


def find_guild(client: discord.Client, key: str):
    key = key.lower()
    for g in client.guilds:
        if key in g.name.lower() or key == str(g.id):
            return g
    raise SystemExit(f"guild not found: {key} (have: {[g.name for g in client.guilds]})")


def find_channel(guild: discord.Guild, key: str):
    key = key.lower()
    for c in guild.channels:
        if isinstance(c, discord.TextChannel) and (key in c.name.lower() or key == str(c.id)):
            return c
    raise SystemExit(f"text channel not found: {key} in {guild.name}")


async def rest_get(
    session: aiohttp.ClientSession, url: str, token: str, params: dict | None = None
) -> tuple[int, dict]:
    async with session.get(url, headers={"Authorization": token}, params=params) as r:
        return r.status, await r.json()


def find_any_channel(guild: discord.Guild, key: str):
    """Match a text/announcement/forum/media channel by name fragment or ID (not categories)."""
    key = key.lower()
    for c in guild.channels:
        if isinstance(c, discord.CategoryChannel):
            continue
        if key in c.name.lower() or key == str(c.id):
            return c
    raise SystemExit(f"channel not found: {key} in {guild.name}")


async def cmd_threads(client: discord.Client, args: argparse.Namespace) -> None:
    """List forum threads (REST; gateway thread cache is unreliable for this token)."""
    token = load_token()
    guild = find_guild(client, args.guild)
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    if args.forum:
        forums = [c for c in forums if args.forum.lower() in c.name.lower()]
    if not forums:
        raise SystemExit(f"no forum channels found in {guild.name}")
    async with aiohttp.ClientSession() as s:
        for forum in forums:
            for t in guild.threads:  # usually empty in this setup, but include when cached
                if str(t.parent_id) == str(forum.id):
                    print(f"{forum.name}\t{t.id}\t{t.name}\tACTIVE")
            before = None
            while True:
                url = (
                    f"https://discord.com/api/v10/channels/{forum.id}/threads/archived/public?limit=100"
                )
                if before:
                    url += f"&before={before}"
                status, data = await rest_get(s, url, token)
                if status != 200:
                    print(f"ERROR: HTTP {status} for {forum.name}", file=sys.stderr)
                    break
                threads = data.get("threads", [])
                for t in threads:
                    print(f"{forum.name}\t{t['id']}\t{t['name']}\t{t['thread_metadata']['archive_timestamp']}")
                if not data.get("has_more") or not threads:
                    break
                before = threads[-1]["thread_metadata"]["archive_timestamp"]
                await asyncio.sleep(0.3)


async def cmd_thread(client: discord.Client, args: argparse.Namespace) -> None:
    """Read a forum post / thread (any channel id works; messages in chronological order)."""
    token = load_token()
    async with aiohttp.ClientSession() as s:
        status, info = await rest_get(s, f"https://discord.com/api/v10/channels/{args.thread}", token)
        if status != 200:
            raise SystemExit(f"ERROR: HTTP {status} fetching thread")
        print(f"# {info.get('name', '?')} (id {args.thread}, type {info.get('type')}, parent {info.get('parent_id')})")
        msgs: list[dict] = []
        before = None
        while len(msgs) < args.limit:
            url = f"https://discord.com/api/v10/channels/{args.thread}/messages?limit=100"
            if before:
                url += f"&before={before}"
            status, batch = await rest_get(s, url, token)
            if status != 200:
                raise SystemExit(f"ERROR: HTTP {status} fetching messages")
            msgs.extend(batch)
            if len(batch) < 100:
                break
            before = batch[-1]["id"]
            await asyncio.sleep(0.3)
        for m in msgs[-args.limit:][::-1]:
            if m["type"] not in (0, 19, 20, 21, 22):
                continue
            body = m.get("content", "").replace("\n", " ")
            ref = (m.get("message_reference") or {}).get("message_id")
            refs = f" ->{ref}" if ref else ""
            emb = ""
            if args.embeds and m.get("embeds"):
                parts = [f"[{e.get('title') or ''} {(e.get('description') or '').replace(chr(10), ' ')[:150]}]" for e in m["embeds"][:3]]
                emb = " | " + " || ".join(p for p in parts if p != "[]")
            print(f"{m['timestamp']}\t{m['id']}{refs}\t{m['author']['username']}\t{body}{emb}")


async def run(args: argparse.Namespace) -> None:
    client = discord.Client()

    @client.event
    async def on_ready():
        try:
            if args.cmd == "guilds":
                for g in sorted(client.guilds, key=lambda g: g.name.lower()):
                    members = getattr(g, "member_count", None) or "?"
                    print(f"{g.name}\t{g.id}\t{members}")
            elif args.cmd == "channels":
                g = find_guild(client, args.guild)
                for c in sorted(g.text_channels, key=lambda c: c.position):
                    print(f"{c.name}\t{c.id}")
            elif args.cmd == "messages":
                g = find_guild(client, args.guild)
                c = find_channel(g, args.channel) if args.channel else g.text_channels[0]
                async for m in c.history(limit=args.limit):
                    body = m.content.replace("\n", " ")
                    emb = ""
                    if args.embeds and m.embeds:
                        parts = [f"[{e.title} {(e.description or '').replace(chr(10), ' ')[:150]}]" for e in m.embeds[:3]]
                        emb = " | " + " || ".join(p for p in parts if p != "[]")
                    print(f"{m.created_at.isoformat()}\t{m.id}\t#{c.name}\t{m.author.name}\t{body}{emb}")
            elif args.cmd == "search":
                g = find_guild(client, args.guild)
                kw = {"limit": args.limit}
                if args.channel:
                    kw["channels"] = [find_any_channel(g, args.channel)]
                if args.before:
                    kw["before"] = datetime.datetime.fromisoformat(args.before)
                if args.after:
                    kw["after"] = datetime.datetime.fromisoformat(args.after)
                async for m in g.search(args.query, **kw):
                    body = m.content.replace("\n", " ")
                    emb = ""
                    if args.embeds and m.embeds:
                        parts = [f"[{e.title} {(e.description or '').replace(chr(10), ' ')[:150]}]" for e in m.embeds[:3]]
                        emb = " | " + " || ".join(p for p in parts if p != "[]")
                    print(f"{m.created_at.isoformat()}\t{m.id}\t{g.name}\t#{m.channel.name}\t{m.author.name}\t{body}{emb}")
            elif args.cmd == "threads":
                await cmd_threads(client, args)
            elif args.cmd == "thread":
                await cmd_thread(client, args)
            elif args.cmd == "member":
                g = find_guild(client, args.guild)
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, m = await rest_get(
                        s, f"https://discord.com/api/v10/guilds/{g.id}/members/{args.user_id}", token
                    )
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} fetching member")
                    st, roles = await rest_get(s, f"https://discord.com/api/v10/guilds/{g.id}/roles", token)
                    rmap = {r["id"]: r["name"] for r in roles} if st == 200 else {}
                    names = [rmap.get(rid, rid) for rid in m.get("roles", [])]
                    u = m.get("user", {})
                    print(
                        f"{u.get('username', '?')}\t{u.get('id')}\t{m.get('nick') or '-'}\t"
                        f"{m.get('joined_at')}\t{m.get('premium_since') or '-'}\t"
                        f"{m.get('pending', False)}\t{','.join(names)}"
                    )
            elif args.cmd == "roles":
                g = find_guild(client, args.guild)
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, roles = await rest_get(s, f"https://discord.com/api/v10/guilds/{g.id}/roles", token)
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} fetching roles")
                    for r in sorted(roles, key=lambda r: r["position"], reverse=True):
                        print(
                            f"{r['name']}\t{r['id']}\t{r['position']}\t"
                            f"{r.get('hoist', False)}\t{r.get('mentionable', False)}\t{r['permissions']}"
                        )
            elif args.cmd == "pins":
                g = find_guild(client, args.guild)
                c = find_any_channel(g, args.channel)
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, msgs = await rest_get(s, f"https://discord.com/api/v10/channels/{c.id}/pins", token)
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} fetching pins")
                    for m in msgs:
                        body = m.get("content", "").replace("\n", " ")
                        print(f"{m['timestamp']}\t{m['id']}\t#{c.name}\t{m['author']['username']}\t{body}")
            elif args.cmd == "dm-channels":
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, chans = await rest_get(s, "https://discord.com/api/v10/users/@me/channels", token)
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} fetching DM channels")
                    for ch in chans:
                        name = ch.get("name")
                        if not name:
                            recips = [r.get("username", "?") for r in ch.get("recipients", [])]
                            name = ", ".join(recips)
                        print(f"{ch['type']}\t{ch['id']}\t{name or '-'}\t{ch.get('last_message_id') or '-'}")
            elif args.cmd == "guild":
                g = find_guild(client, args.guild)
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, d = await rest_get(s, f"https://discord.com/api/v10/guilds/{g.id}", token)
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} fetching guild")
                    print(f"name\t{d.get('name')}")
                    print(f"id\t{d.get('id')}")
                    print(f"member_count\t{d.get('member_count')}")
                    print(f"premium_tier\t{d.get('premium_tier')}")
                    print(f"boosts\t{d.get('premium_subscription_count')}")
                    print(f"verification_level\t{d.get('verification_level')}")
                    print(f"vanity_url\t{d.get('vanity_url_code')}")
                    print(f"features\t{','.join(d.get('features', []))}")
            elif args.cmd == "threads-search":
                g = find_guild(client, args.guild)
                c = find_any_channel(g, args.channel)
                token = load_token()
                async with aiohttp.ClientSession() as s:
                    st, data = await rest_get(
                        s,
                        f"https://discord.com/api/v10/channels/{c.id}/threads/search",
                        token,
                        params={"query": args.query, "limit": str(args.limit)},
                    )
                    if st != 200:
                        raise SystemExit(f"ERROR: HTTP {st} threads/search (undocumented endpoint; may vary)")
                    print(f"# total_results: {data.get('total_results', '?')}")
                    for t in data.get("threads", []):
                        meta = t.get("thread_metadata", {})
                        print(
                            f"{t['id']}\t{t['name']}\t{meta.get('archived')}\t"
                            f"{t.get('message_count')}\t{t.get('total_message_sent')}\t"
                            f"{t.get('last_message_id') or '-'}"
                        )
            elif args.cmd == "send":
                g = find_guild(client, args.guild)
                c = find_channel(g, args.channel)
                m = await c.send(args.text)
                print(f"sent {m.id} to #{c.name} in {g.name}")
            elif args.cmd == "status":
                print(f"logged in as {client.user} ({client.user.id}), guilds: {len(client.guilds)}")
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            raise SystemExit(1)
        finally:
            await client.close()

    client.event(on_ready)
    await client.start(load_token())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("guilds", help="list guilds the account is in")
    sub.add_parser("status", help="login identity + guild count")

    c = sub.add_parser("channels", help="list text channels of a guild")
    c.add_argument("guild")

    c = sub.add_parser("messages", help="recent messages in a channel")
    c.add_argument("guild")
    c.add_argument("channel", nargs="?", default=None)
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--embeds", action="store_true", help="append embed titles/descriptions (bot channels are embed-driven)")

    c = sub.add_parser("search", help="guild-wide message search")
    c.add_argument("guild")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--channel", help="restrict search to one channel (name fragment or ID)")
    c.add_argument("--before", help="ISO datetime window upper bound, e.g. 2026-02-01")
    c.add_argument("--after", help="ISO datetime window lower bound, e.g. 2025-12-01")
    c.add_argument("--embeds", action="store_true", help="append embed titles/descriptions")

    c = sub.add_parser("threads", help="list forum threads (archived; active not cached for this token)")
    c.add_argument("guild")
    c.add_argument("forum", nargs="?", default=None)

    c = sub.add_parser("thread", help="read a forum post / thread by id")
    c.add_argument("thread")
    c.add_argument("--limit", type=int, default=200)
    c.add_argument("--embeds", action="store_true", help="append embed titles/descriptions")

    c = sub.add_parser("member", help="fetch one guild member by user id (REST; works where the members list 403s)")
    c.add_argument("guild")
    c.add_argument("user_id")

    c = sub.add_parser("roles", help="list guild roles")
    c.add_argument("guild")

    c = sub.add_parser("pins", help="read pinned messages of a channel")
    c.add_argument("guild")
    c.add_argument("channel")

    c = sub.add_parser("guild", help="guild metadata (member_count is null via REST)")
    c.add_argument("guild")

    sub.add_parser("dm-channels", help="list DM / group DM channels (user-only endpoint)")

    c = sub.add_parser("threads-search", help="search threads in a channel (undocumented endpoint; active + archived)")
    c.add_argument("guild")
    c.add_argument("channel")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=25)

    c = sub.add_parser("send", help="send a message to a channel")
    c.add_argument("guild")
    c.add_argument("channel")
    c.add_argument("text")

    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

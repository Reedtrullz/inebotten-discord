#!/usr/bin/env python3
"""Export all members of a Discord guild to CSV + JSON.

Usage:
    python3 scripts/export_members.py --invite https://discord.gg/uYkk5rtDH
    python3 scripts/export_members.py --guild-id 123456789
    python3 scripts/export_members.py --guild-name "THORChain Community"
    python3 scripts/export_members.py --invite uYkk5rtDH --out /path/to/members.csv

Requires DISCORD_USER_TOKEN in .env (repo root or ~/.hermes/discord/.env).
Use --join to accept the invite first if the account is not yet a member.
"""

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import discord

from core.auth_handler import AuthHandler
from core.config import Config
from discord.http import Route
from utils.json_storage import hermes_home_path


def member_row(member):
    """Flatten a discord.Member into one export row."""
    return {
        "id": member.id,
        "username": member.name,
        "global_name": getattr(member, "global_name", None),
        "display_name": member.display_name,
        "discriminator": getattr(member, "discriminator", None),
        "bot": member.bot,
        "system": member.system,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        "roles": ",".join(r.name for r in member.roles if r.name != "@everyone"),
        "avatar_url": str(member.display_avatar.url),
    }


def rest_row(guild, data):
    """Build an export row from a raw REST member payload."""
    user = data["user"]
    nick = data.get("nick")
    role_names = [
        r.name for r in guild.roles
        if r.id in data.get("roles", []) and r.name != "@everyone"
    ]
    avatar = user.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png" if avatar else None
    )
    return {
        "id": int(user["id"]),
        "username": user["username"],
        "global_name": user.get("global_name"),
        "display_name": nick or user.get("global_name") or user["username"],
        "discriminator": user.get("discriminator"),
        "bot": user.get("bot", False),
        "system": user.get("system", False),
        "joined_at": data.get("joined_at"),
        "roles": ",".join(role_names),
        "avatar_url": avatar_url,
    }


def write_exports(rows, guild, out_path):
    """Write CSV (and a sibling JSON) for the given rows. Returns both paths."""
    out_path = Path(out_path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_path.with_suffix(".json")
    json_path.write_text(
        json.dumps(
            {
                "guild": {
                    "id": guild.id,
                    "name": guild.name,
                    "member_count": guild.member_count,
                },
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "count": len(rows),
                "members": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out_path, json_path


def parse_args():
    parser = argparse.ArgumentParser(description="Export all members of a Discord guild")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--invite", help="Invite code or full URL (e.g. https://discord.gg/uYkk5rtDH)")
    target.add_argument("--guild-id", type=int, help="Numeric guild ID")
    target.add_argument("--guild-name", help="Exact guild name")
    parser.add_argument("--out", help="CSV output path (JSON is written alongside)")
    parser.add_argument(
        "--join", action="store_true",
        help="Accept the invite if the account is not already a member",
    )
    return parser.parse_args()


async def resolve_guild(client, args):
    if args.invite:
        code = args.invite.rstrip("/").split("/")[-1]
        invite = await client.fetch_invite(code)
        guild = client.get_guild(invite.guild.id)
        if guild is None:
            if args.join:
                print(f"[EXPORT] Joining {invite.guild.name} via invite...")
                try:
                    await client.accept_invite(code)
                except discord.errors.CaptchaRequired:
                    raise SystemExit(
                        "Discord requires a captcha to join this server - "
                        "open the invite in a browser logged in as the bot account, "
                        "then rerun without --join"
                    )
                for _ in range(10):
                    guild = client.get_guild(invite.guild.id)
                    if guild:
                        break
                    await asyncio.sleep(0.5)
            if guild is None:
                raise SystemExit(
                    f"Not a member of '{invite.guild.name}' ({invite.guild.id}) - "
                    "join via the invite first (or pass --join)"
                )
        print(f"[EXPORT] Guild: {guild.name} ({guild.id}), invite shows ~{invite.approximate_member_count} members")
        return guild
    if args.guild_id:
        guild = client.get_guild(args.guild_id)
        if guild is None:
            raise SystemExit(f"Not a member of guild {args.guild_id}")
        return guild
    for guild in client.guilds:
        if guild.name == args.guild_name:
            return guild
    raise SystemExit(f"No guild named '{args.guild_name}'")


async def fetch_all_members(client, guild):
    """Fetch every member via REST paging; falls back to the gateway member scrape."""
    try:
        rows = []
        after = 0
        while True:
            page = await client.http.request(
                Route("GET", "/guilds/{guild_id}/members", guild_id=guild.id),
                params={"limit": 1000, "after": after},
            )
            if not page:
                break
            rows.extend(rest_row(guild, item) for item in page)
            after = page[-1]["user"]["id"]
            if len(page) < 1000:
                break
            if len(rows) % 10000 == 0:
                print(f"[EXPORT] ...{len(rows)} members")
        return rows
    except Exception as exc:
        print(
            f"[EXPORT] REST paging failed ({exc}); "
            "falling back to gateway member scrape (may miss offline members)"
        )
        scraped = await guild.fetch_members()
        return sorted((member_row(m) for m in scraped), key=lambda r: r["id"])


if __name__ == "__main__":
    args = parse_args()
    config = Config()
    auth = AuthHandler(config)
    if not auth.is_token_auth():
        sys.exit("[ERROR] Only token auth is supported. Set DISCORD_USER_TOKEN in .env")

    # client.run() blocks until the client disconnects, so the export runs in
    # on_ready. Startup guild chunking is disabled: REST paging fetches the list.
    client = discord.Client(chunk_guilds_at_startup=False)

    @client.event
    async def on_ready():
        try:
            guild = await resolve_guild(client, args)
            print(f"[EXPORT] Fetching members of {guild.name}...")
            rows = await fetch_all_members(client, guild)
            rows.sort(key=lambda r: r["id"])
            print(f"[EXPORT] Retrieved {len(rows)} members")
            if not rows:
                raise SystemExit("No members retrieved - the account may not see this guild's member list")
            default_out = hermes_home_path() / "discord" / "data" / "exports" / f"members_{guild.id}.csv"
            csv_path, json_path = write_exports(rows, guild, args.out or default_out)
            print(f"[EXPORT] CSV:  {csv_path}")
            print(f"[EXPORT] JSON: {json_path}")
        except SystemExit as exc:
            print(str(exc))
        finally:
            await client.close()

    client.run(auth.get_token())

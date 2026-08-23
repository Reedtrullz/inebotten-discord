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
  scripts/inebotten_ctl.py send thorchain general "hello" --dry-run
"""

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import random
import stat
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aiohttp
import discord


EXPECTED_USER_ID = 1474528156131266815
MAX_LIMIT = 200
MAX_REST_PAGES = 100
MAX_OUTPUT_RECORDS = 10_000
MAX_COMMAND_SECONDS = 60.0
DEFAULT_REQUEST_TIMEOUT = 15.0
MAX_RETRY_ATTEMPTS = 3
MAX_RETRY_WAIT = 15.0
MAX_MESSAGE_LENGTH = 2000
HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
AUDIT_PATH = HERMES_HOME / "discord" / "data" / "control" / "audit.jsonl"


class ControlError(RuntimeError):
    """Expected, user-facing controller failure without a traceback."""


class OutputWriter:
    """Keep human output compatible while offering safe JSONL records."""

    def __init__(self, output_format: str = "text", source: str = "unknown") -> None:
        self.output_format = output_format
        self.source = source
        self.operation = source
        self.freshness = "index_may_lag" if source == "search_index" else "live"
        self.queried_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.records_emitted = 0
        self.identity: dict[str, Any] | None = None
        self._finished = False

    def set_identity(self, user: Any) -> None:
        """Attach the live authenticated identity to subsequent JSONL rows."""
        self.identity = {
            "id": str(getattr(user, "id", "")),
            "name": str(user),
            "expected_id": str(EXPECTED_USER_ID),
        }

    def _envelope(self) -> dict[str, Any]:
        return {
            "ok": True,
            "operation": self.operation,
            "queried_at": self.queried_at,
            "source": self.source,
            "freshness": self.freshness,
            "complete": True,
            "identity": self.identity,
        }

    def _reserve_record(self) -> None:
        if self.records_emitted >= MAX_OUTPUT_RECORDS:
            raise ControlError(
                f"output exceeded the safety limit of {MAX_OUTPUT_RECORDS} records"
            )
        self.records_emitted += 1

    def line(self, *fields: Any, record: dict[str, Any] | None = None) -> None:
        self._reserve_record()
        if self.output_format == "jsonl":
            payload: dict[str, Any] = {
                "type": "row",
                "fields": [str(field) for field in fields],
            }
            payload.update(self._envelope())
            if record:
                payload.update(record)
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return
        print("\t".join(str(field) for field in fields))

    def event(self, event: str, **values: Any) -> None:
        if self.output_format == "jsonl":
            self._reserve_record()
            payload = {"type": event, **self._envelope(), **values}
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return
        if values:
            self.line(event, *(f"{key}={value}" for key, value in values.items()))
        else:
            self.line(event)

    def finish(self, *, ok: bool = True, complete: bool = True, error: str | None = None) -> None:
        """Emit a machine-readable completion envelope for JSONL consumers."""
        if self.output_format != "jsonl" or self._finished:
            return
        self._finished = True
        payload = {
            "type": "complete",
            **self._envelope(),
            "ok": ok,
            "complete": complete,
            "records_emitted": self.records_emitted,
        }
        if error:
            payload["error"] = error[:300]
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


class RequestTelemetry:
    def __init__(self) -> None:
        self.requests = 0
        self.retries = 0
        self.rate_limited = 0
        self.invalid_responses = 0
        self.last_status: int | None = None
        self.last_retry_after: float | None = None
        self.last_bucket: str | None = None
        self.last_remaining: int | None = None
        self.last_reset_after: float | None = None
        self.last_scope: str | None = None
        self.last_global: bool | None = None

    def record(
        self,
        status: int,
        retry_after: float | None = None,
        headers: Any | None = None,
    ) -> None:
        self.requests += 1
        self.last_status = status
        self.last_retry_after = retry_after
        if headers is not None and hasattr(headers, "get"):
            raw_bucket = headers.get("X-RateLimit-Bucket")
            raw_scope = headers.get("X-RateLimit-Scope")
            if raw_bucket is not None:
                self.last_bucket = raw_bucket
            if raw_scope is not None:
                self.last_scope = raw_scope
            raw_remaining = headers.get("X-RateLimit-Remaining")
            raw_reset = headers.get("X-RateLimit-Reset-After")
            if raw_remaining is not None:
                try:
                    self.last_remaining = int(raw_remaining)
                except (TypeError, ValueError):
                    self.last_remaining = None
            if raw_reset is not None:
                try:
                    self.last_reset_after = float(raw_reset)
                except (TypeError, ValueError):
                    self.last_reset_after = None
            raw_global = headers.get("X-RateLimit-Global")
            if raw_global is not None:
                self.last_global = (
                    raw_global.lower() == "true"
                    if isinstance(raw_global, str)
                    else None
                )
        if status == 429:
            self.rate_limited += 1
        if status in (401, 403, 429):
            self.invalid_responses += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "rate_limited": self.rate_limited,
            "invalid_responses": self.invalid_responses,
            "last_status": self.last_status,
            "last_retry_after": self.last_retry_after,
            "last_bucket": self.last_bucket,
            "last_remaining": self.last_remaining,
            "last_reset_after": self.last_reset_after,
            "last_scope": self.last_scope,
            "last_global": self.last_global,
        }


REQUEST_TELEMETRY = RequestTelemetry()


def _safe_env_file(path: Path) -> bool:
    """Accept only private, regular env files; never follow a FIFO or symlink."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False
    return mode & 0o077 == 0


def _read_token_file(path: Path) -> str | None:
    if not _safe_env_file(path):
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_USER_TOKEN="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value or None
    except (OSError, UnicodeError):
        return None
    return None


def load_token_with_source() -> tuple[str, str]:
    """Resolve the token without ever printing it or exposing its value."""
    token = os.getenv("DISCORD_USER_TOKEN")
    if token:
        return token, "environment"

    project_env = Path(__file__).resolve().parent.parent / ".env"
    hermes_env = HERMES_HOME / "discord" / ".env"
    env_paths = (
        [(hermes_env, "hermes_env"), (project_env, "project_env")]
        if os.getenv("HERMES_HOME")
        else [(project_env, "project_env"), (hermes_env, "hermes_env")]
    )
    for env_path, source in env_paths:
        token = _read_token_file(env_path)
        if token:
            return token, source

    unsafe = [
        str(path)
        for path in (project_env, hermes_env)
        if path.exists() and not _safe_env_file(path)
    ]
    if unsafe:
        raise ControlError(
            "Discord token file is missing, not a regular private file, or has unsafe permissions: "
            + ", ".join(unsafe)
        )
    raise ControlError(
        "DISCORD_USER_TOKEN not found in the environment, project .env, or Hermes .env"
    )


def load_token() -> str:
    return load_token_with_source()[0]


def _matches(items: Iterable[Any], key: str, name_getter) -> list[Any]:
    lowered = key.casefold()
    if key.isdecimal():
        # Discord snowflakes are decimal IDs.  Never reinterpret a numeric
        # miss as a name fragment or select a channel named with digits.
        return [item for item in items if str(getattr(item, "id", "")) == key]
    exact = [
        item
        for item in items
        if str(getattr(item, "id", "")) == key
        or name_getter(item).casefold() == lowered
    ]
    if exact:
        return exact
    return [item for item in items if lowered in name_getter(item).casefold()]


def _resolve_one(
    items: Iterable[Any],
    key: str,
    kind: str,
    name_getter,
    *,
    exact_only: bool = False,
):
    matches = _matches(items, key, name_getter)
    if not matches:
        raise ControlError(f"{kind} not found: {key}")
    if len(matches) > 1:
        choices = ", ".join(
            f"{name_getter(item)} ({item.id})" for item in matches[:10]
        )
        raise ControlError(
            f"ambiguous {kind} '{key}'; use an exact ID or unique name: {choices}"
        )
    item = matches[0]
    if exact_only and str(getattr(item, "id", "")) != key and name_getter(item).casefold() != key.casefold():
        raise ControlError(f"writes require an exact {kind} ID or exact name: {key}")
    return item


def find_guild(client: discord.Client, key: str, *, exact_only: bool = False):
    return _resolve_one(
        client.guilds, key, "guild", lambda guild: guild.name, exact_only=exact_only
    )


def find_channel(guild: discord.Guild, key: str, *, exact_only: bool = False):
    channels = [
        channel
        for channel in guild.channels
        if isinstance(channel, discord.TextChannel)
    ]
    return _resolve_one(
        channels,
        key,
        "text channel",
        lambda channel: channel.name,
        exact_only=exact_only,
    )


async def rest_get(
    session: aiohttp.ClientSession,
    url: str,
    token: str,
    params: dict | None = None,
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
) -> tuple[int, dict]:
    attempts = min(MAX_RETRY_ATTEMPTS, max(1, int(max_attempts)))
    request_timeout = min(max(0.1, float(timeout)), DEFAULT_REQUEST_TIMEOUT)
    for attempt in range(attempts):
        try:
            async with session.get(
                url,
                headers={"Authorization": token},
                params=params,
                timeout=aiohttp.ClientTimeout(total=request_timeout),
            ) as response:
                status = int(response.status)
                headers = getattr(response, "headers", {}) or {}
                try:
                    data = await response.json(content_type=None)
                except (TypeError, ValueError, aiohttp.ContentTypeError):
                    try:
                        body = await response.text()
                    except Exception:
                        body = ""
                    data = {"error": "non_json_response", "body": body[:500]}

                retry_value = data.get("retry_after") if isinstance(data, dict) else None
                retry_header = headers.get("Retry-After") if hasattr(headers, "get") else None
                try:
                    retry_after = (
                        float(retry_value if retry_value is not None else retry_header)
                        if retry_value is not None or retry_header is not None
                        else None
                    )
                except (TypeError, ValueError):
                    retry_after = None
                REQUEST_TELEMETRY.record(status, retry_after, headers)

                should_retry = status == 429 or status >= 500
                if not should_retry or attempt + 1 >= attempts:
                    return status, data if isinstance(data, dict) else {"data": data}

                wait_for = (
                    retry_after
                    if retry_after is not None
                    else REQUEST_TELEMETRY.last_reset_after
                    if REQUEST_TELEMETRY.last_reset_after is not None
                    else min(2**attempt, 5.0)
                )
                if wait_for > MAX_RETRY_WAIT:
                    return status, data if isinstance(data, dict) else {"data": data}
                REQUEST_TELEMETRY.retries += 1
                await asyncio.sleep(max(0.0, wait_for) + random.uniform(0.0, 0.25))
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if attempt + 1 >= attempts:
                raise ControlError(
                    f"Discord REST request failed: {type(exc).__name__}"
                ) from exc
            REQUEST_TELEMETRY.retries += 1
            await asyncio.sleep(min(2**attempt, 5.0) + random.uniform(0.0, 0.25))
    raise ControlError("Discord REST request exhausted its retry budget")


def find_any_channel(guild: discord.Guild, key: str, *, exact_only: bool = False):
    """Match a non-category channel, rejecting ambiguous fragments."""
    channels = [
        channel
        for channel in guild.channels
        if not isinstance(channel, discord.CategoryChannel)
    ]
    return _resolve_one(
        channels,
        key,
        "channel",
        lambda channel: channel.name,
        exact_only=exact_only,
    )


def bounded_limit(value: str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def verify_identity(client: discord.Client) -> None:
    user = getattr(client, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        raise ControlError("Discord connected without exposing the authenticated identity")
    if int(user_id) != EXPECTED_USER_ID:
        raise ControlError(
            f"authenticated as unexpected Discord user {user_id}; expected {EXPECTED_USER_ID}"
        )


def append_audit(
    *,
    command: str,
    outcome: str,
    guild_id: int | str | None = None,
    channel_id: int | str | None = None,
    content: str | None = None,
    message_id: int | str | None = None,
    error: str | None = None,
    dry_run: bool = False,
) -> None:
    """Append a private, content-minimised record for controller writes."""
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(AUDIT_PATH.parent, 0o700)
        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "command": command,
            "outcome": outcome,
            "guild_id": str(guild_id) if guild_id is not None else None,
            "channel_id": str(channel_id) if channel_id is not None else None,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content is not None
            else None,
            "message_id": str(message_id) if message_id is not None else None,
            "error": error[:300] if error else None,
            "dry_run": dry_run,
        }
        fd = os.open(
            AUDIT_PATH,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        try:
            os.write(fd, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(AUDIT_PATH, 0o600)
    except OSError:
        # Audit failure must not expose secrets or turn a successful Discord write
        # into a second write attempt. The operation result remains authoritative.
        return


def write_is_allowed(guild_id: int | str, channel_id: int | str) -> bool:
    """Apply an optional explicit guild:channel write allowlist."""
    raw = os.getenv("INEBOTTEN_WRITE_ALLOWLIST", "")
    if not raw.strip():
        return True
    target = f"{guild_id}:{channel_id}"
    allowed = {entry.strip() for entry in raw.split(",") if entry.strip()}
    return target in allowed


def embed_summary(embeds: list[Any]) -> list[dict[str, str]]:
    result = []
    for embed in embeds[:3]:
        if isinstance(embed, dict):
            result.append(
                {
                    "title": str(embed.get("title") or ""),
                    "description": str(embed.get("description") or "")[:500],
                }
            )
        else:
            result.append(
                {
                    "title": str(getattr(embed, "title", "") or ""),
                    "description": str(getattr(embed, "description", "") or "")[:500],
                }
            )
    return result


def source_for_command(command: str) -> str:
    return {
        "guilds": "gateway_guilds",
        "status": "gateway_status",
        "doctor": "gateway_doctor",
        "channels": "gateway_channels",
        "messages": "gateway_history",
        "search": "search_index",
        "threads": "rest_archived_threads",
        "thread": "rest_thread_history",
        "member": "rest_member",
        "roles": "rest_roles",
        "pins": "rest_pins",
        "guild": "rest_guild",
        "dm-channels": "rest_dm_channels",
        "threads-search": "rest_thread_search",
        "send": "gateway_send",
    }.get(command, "unknown")


async def cmd_threads(
    client: discord.Client, args: argparse.Namespace, writer: OutputWriter
) -> None:
    """List forum threads (REST; gateway thread cache is unreliable for this token)."""
    token = load_token()
    guild = find_guild(client, args.guild)
    forums = [c for c in guild.channels if isinstance(c, discord.ForumChannel)]
    if args.forum:
        forums = [_resolve_one(forums, args.forum, "forum channel", lambda c: c.name)]
    if not forums:
        raise ControlError(f"no forum channels found in {guild.name}")
    async with aiohttp.ClientSession() as s:
        for forum in forums:
            for t in guild.threads:  # usually empty in this setup, but include when cached
                if str(t.parent_id) == str(forum.id):
                    writer.line(
                        forum.name,
                        t.id,
                        t.name,
                        "ACTIVE",
                        record={
                            "forum": forum.name,
                            "forum_id": forum.id,
                            "thread_id": t.id,
                            "thread_name": t.name,
                            "archived": False,
                        },
                    )
            before = None
            for _page in range(MAX_REST_PAGES):
                url = (
                    f"https://discord.com/api/v10/channels/{forum.id}/threads/archived/public?limit=100"
                )
                if before:
                    url += f"&before={before}"
                status, data = await rest_get(s, url, token)
                if status != 200:
                    raise ControlError(f"HTTP {status} listing archived threads for {forum.name}")
                threads = data.get("threads", [])
                for t in threads:
                    archive_timestamp = t["thread_metadata"]["archive_timestamp"]
                    writer.line(
                        forum.name,
                        t["id"],
                        t["name"],
                        archive_timestamp,
                        record={
                            "forum": forum.name,
                            "forum_id": forum.id,
                            "thread_id": t["id"],
                            "thread_name": t["name"],
                            "archived": True,
                            "archive_timestamp": archive_timestamp,
                        },
                    )
                if not data.get("has_more") or not threads:
                    break
                before = threads[-1]["thread_metadata"]["archive_timestamp"]
                await asyncio.sleep(0.3)
            else:
                raise ControlError("archived thread pagination exceeded its safety limit")


async def cmd_thread(
    client: discord.Client, args: argparse.Namespace, writer: OutputWriter
) -> None:
    """Read a forum post / thread (any channel id works; messages in chronological order)."""
    token = load_token()
    async with aiohttp.ClientSession() as s:
        status, info = await rest_get(s, f"https://discord.com/api/v10/channels/{args.thread}", token)
        if status != 200:
            raise ControlError(f"HTTP {status} fetching thread metadata")
        writer.event(
            "thread",
            thread_id=args.thread,
            name=info.get("name", "?"),
            channel_type=info.get("type"),
            parent_id=info.get("parent_id"),
        )
        msgs: list[dict] = []
        before = None
        for _page in range(MAX_REST_PAGES):
            if len(msgs) >= args.limit:
                break
            url = f"https://discord.com/api/v10/channels/{args.thread}/messages?limit=100"
            if before:
                url += f"&before={before}"
            status, batch = await rest_get(s, url, token)
            if status != 200:
                raise ControlError(f"HTTP {status} fetching thread messages")
            msgs.extend(batch)
            if len(batch) < 100:
                break
            before = batch[-1]["id"]
            await asyncio.sleep(0.3)
        else:
            raise ControlError("thread pagination exceeded its safety limit")
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
            writer.line(
                m["timestamp"],
                f"{m['id']}{refs}",
                m["author"]["username"],
                f"{body}{emb}",
                record={
                    "timestamp": m["timestamp"],
                    "message_id": m["id"],
                    "author": m["author"].get("username"),
                    "content": body,
                    "reference_id": ref,
                    "embeds": m.get("embeds", []) if args.embeds else [],
                },
            )


async def run(args: argparse.Namespace) -> None:
    """Run one bounded controller operation and close the gateway session."""
    global REQUEST_TELEMETRY
    REQUEST_TELEMETRY = RequestTelemetry()
    output_format = getattr(args, "format", "text")
    writer = OutputWriter(output_format, source_for_command(args.cmd))
    token, token_source = load_token_with_source()
    client = discord.Client()
    handled = False
    operation_error: ControlError | None = None
    send_context: dict[str, Any] = {}

    async def on_ready() -> None:
        nonlocal handled, operation_error
        if handled:
            return
        handled = True
        try:
            verify_identity(client)
            writer.set_identity(client.user)
            if args.cmd == "guilds":
                for guild in sorted(client.guilds, key=lambda item: item.name.casefold()):
                    members = getattr(guild, "member_count", None) or "?"
                    writer.line(
                        guild.name,
                        guild.id,
                        members,
                        record={
                            "guild": guild.name,
                            "guild_id": guild.id,
                            "member_count": members,
                        },
                    )
            elif args.cmd in ("status", "doctor"):
                writer.event(
                    "status" if args.cmd == "status" else "doctor",
                    authenticated_as=str(client.user),
                    user_id=client.user.id,
                    expected_user_id=EXPECTED_USER_ID,
                    identity_ok=True,
                    gateway_ready=True,
                    guild_count=len(client.guilds),
                    token_source=token_source,
                    library_version=getattr(discord, "__version__", "unknown"),
                )
            elif args.cmd == "channels":
                guild = find_guild(client, args.guild)
                for channel in sorted(guild.text_channels, key=lambda item: item.position):
                    writer.line(
                        channel.name,
                        channel.id,
                        record={
                            "guild": guild.name,
                            "guild_id": guild.id,
                            "channel": channel.name,
                            "channel_id": channel.id,
                        },
                    )
            elif args.cmd == "messages":
                if not args.channel:
                    raise ControlError("messages requires an explicit channel; refusing arbitrary channel selection")
                guild = find_guild(client, args.guild)
                channel = find_channel(guild, args.channel)
                async for message in channel.history(limit=args.limit):
                    body = message.content.replace("\n", " ")
                    embeds = embed_summary(getattr(message, "embeds", [])) if args.embeds else []
                    embed_text = ""
                    if embeds:
                        embed_text = " | " + " || ".join(
                            f"[{item['title']} {item['description'][:150]}]" for item in embeds
                        )
                    writer.line(
                        message.created_at.isoformat(),
                        message.id,
                        f"#{channel.name}",
                        message.author.name,
                        f"{body}{embed_text}",
                        record={
                            "timestamp": message.created_at.isoformat(),
                            "message_id": message.id,
                            "guild": guild.name,
                            "guild_id": guild.id,
                            "channel": channel.name,
                            "channel_id": channel.id,
                            "author": message.author.name,
                            "content": body,
                            "embeds": embeds,
                        },
                    )
            elif args.cmd == "search":
                guild = find_guild(client, args.guild)
                search_kwargs: dict[str, Any] = {"limit": args.limit}
                if args.channel:
                    search_kwargs["channels"] = [find_any_channel(guild, args.channel)]
                try:
                    if args.before:
                        search_kwargs["before"] = datetime.datetime.fromisoformat(args.before)
                    if args.after:
                        search_kwargs["after"] = datetime.datetime.fromisoformat(args.after)
                except ValueError as exc:
                    raise ControlError("search date bounds must be ISO-8601") from exc
                async for message in guild.search(args.query, **search_kwargs):
                    body = message.content.replace("\n", " ")
                    embeds = embed_summary(getattr(message, "embeds", [])) if args.embeds else []
                    embed_text = ""
                    if embeds:
                        embed_text = " | " + " || ".join(
                            f"[{item['title']} {item['description'][:150]}]" for item in embeds
                        )
                    writer.line(
                        message.created_at.isoformat(),
                        message.id,
                        guild.name,
                        f"#{message.channel.name}",
                        message.author.name,
                        f"{body}{embed_text}",
                        record={
                            "timestamp": message.created_at.isoformat(),
                            "message_id": message.id,
                            "guild": guild.name,
                            "guild_id": guild.id,
                            "channel": message.channel.name,
                            "channel_id": message.channel.id,
                            "author": message.author.name,
                            "content": body,
                            "embeds": embeds,
                            "indexed": True,
                        },
                    )
            elif args.cmd == "threads":
                await cmd_threads(client, args, writer)
            elif args.cmd == "thread":
                await cmd_thread(client, args, writer)
            elif args.cmd == "member":
                guild = find_guild(client, args.guild)
                async with aiohttp.ClientSession() as session:
                    status, member = await rest_get(
                        session,
                        f"https://discord.com/api/v10/guilds/{guild.id}/members/{args.user_id}",
                        token,
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} fetching member")
                    role_status, roles = await rest_get(
                        session,
                        f"https://discord.com/api/v10/guilds/{guild.id}/roles",
                        token,
                    )
                    role_map = {role["id"]: role["name"] for role in roles} if role_status == 200 else {}
                    names = [role_map.get(role_id, role_id) for role_id in member.get("roles", [])]
                    user = member.get("user", {})
                    writer.line(
                        user.get("username", "?"),
                        user.get("id"),
                        member.get("nick") or "-",
                        member.get("joined_at"),
                        member.get("premium_since") or "-",
                        member.get("pending", False),
                        ",".join(names),
                        record={
                            "guild": guild.name,
                            "guild_id": guild.id,
                            "user": user.get("username", "?"),
                            "user_id": user.get("id"),
                            "nick": member.get("nick"),
                            "joined_at": member.get("joined_at"),
                            "roles": names,
                        },
                    )
            elif args.cmd == "roles":
                guild = find_guild(client, args.guild)
                async with aiohttp.ClientSession() as session:
                    status, roles = await rest_get(
                        session,
                        f"https://discord.com/api/v10/guilds/{guild.id}/roles",
                        token,
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} fetching roles")
                    for role in sorted(roles, key=lambda item: item["position"], reverse=True):
                        writer.line(
                            role["name"],
                            role["id"],
                            role["position"],
                            role.get("hoist", False),
                            role.get("mentionable", False),
                            role["permissions"],
                            record={"guild_id": guild.id, "role": role},
                        )
            elif args.cmd == "pins":
                guild = find_guild(client, args.guild)
                channel = find_any_channel(guild, args.channel)
                async with aiohttp.ClientSession() as session:
                    status, messages = await rest_get(
                        session,
                        f"https://discord.com/api/v10/channels/{channel.id}/pins",
                        token,
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} fetching pins")
                    for message in messages:
                        body = message.get("content", "").replace("\n", " ")
                        writer.line(
                            message["timestamp"],
                            message["id"],
                            f"#{channel.name}",
                            message["author"]["username"],
                            body,
                            record={
                                "timestamp": message["timestamp"],
                                "message_id": message["id"],
                                "guild_id": guild.id,
                                "channel_id": channel.id,
                                "author": message["author"]["username"],
                                "content": body,
                            },
                        )
            elif args.cmd == "dm-channels":
                async with aiohttp.ClientSession() as session:
                    status, channels = await rest_get(
                        session,
                        "https://discord.com/api/v10/users/@me/channels",
                        token,
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} fetching DM channels")
                    for channel in channels:
                        name = channel.get("name")
                        if not name:
                            recipients = [
                                recipient.get("username", "?")
                                for recipient in channel.get("recipients", [])
                            ]
                            name = ", ".join(recipients)
                        writer.line(
                            channel["type"],
                            channel["id"],
                            name or "-",
                            channel.get("last_message_id") or "-",
                            record={"channel": channel},
                        )
            elif args.cmd == "guild":
                guild = find_guild(client, args.guild)
                async with aiohttp.ClientSession() as session:
                    status, data = await rest_get(
                        session,
                        f"https://discord.com/api/v10/guilds/{guild.id}",
                        token,
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} fetching guild metadata")
                    for key, value in (
                        ("name", data.get("name")),
                        ("id", data.get("id")),
                        ("member_count", data.get("member_count")),
                        ("premium_tier", data.get("premium_tier")),
                        ("boosts", data.get("premium_subscription_count")),
                        ("verification_level", data.get("verification_level")),
                        ("vanity_url", data.get("vanity_url_code")),
                        ("features", ",".join(data.get("features", []))),
                    ):
                        writer.line(key, value, record={key: value, "guild_id": guild.id})
            elif args.cmd == "threads-search":
                guild = find_guild(client, args.guild)
                channel = find_any_channel(guild, args.channel)
                async with aiohttp.ClientSession() as session:
                    status, data = await rest_get(
                        session,
                        f"https://discord.com/api/v10/channels/{channel.id}/threads/search",
                        token,
                        params={"query": args.query, "limit": str(args.limit)},
                    )
                    if status != 200:
                        raise ControlError(f"HTTP {status} searching threads; endpoint may vary")
                    writer.event(
                        "thread_search",
                        guild_id=guild.id,
                        channel_id=channel.id,
                        total_results=data.get("total_results"),
                    )
                    for thread in data.get("threads", []):
                        metadata = thread.get("thread_metadata", {})
                        writer.line(
                            thread["id"],
                            thread["name"],
                            metadata.get("archived"),
                            thread.get("message_count"),
                            thread.get("total_message_sent"),
                            thread.get("last_message_id") or "-",
                            record={"thread": thread, "guild_id": guild.id, "channel_id": channel.id},
                        )
            elif args.cmd == "send":
                guild = find_guild(client, args.guild, exact_only=True)
                channel = find_channel(guild, args.channel, exact_only=True)
                send_context.update({"guild_id": guild.id, "channel_id": channel.id})
                text = args.text
                if not text or len(text) > MAX_MESSAGE_LENGTH:
                    raise ControlError(f"message text must be 1-{MAX_MESSAGE_LENGTH} characters")
                if not write_is_allowed(guild.id, channel.id):
                    append_audit(
                        command="send",
                        outcome="denied_allowlist",
                        guild_id=guild.id,
                        channel_id=channel.id,
                        content=text,
                    )
                    raise ControlError("send target is not in INEBOTTEN_WRITE_ALLOWLIST")
                if getattr(args, "dry_run", False):
                    append_audit(
                        command="send",
                        outcome="dry_run",
                        guild_id=guild.id,
                        channel_id=channel.id,
                        content=text,
                        dry_run=True,
                    )
                    writer.event(
                        "dry_run",
                        guild=guild.name,
                        guild_id=guild.id,
                        channel=channel.name,
                        channel_id=channel.id,
                        content=text,
                    )
                else:
                    if not getattr(args, "confirm", False):
                        append_audit(
                            command="send",
                            outcome="denied_confirmation",
                            guild_id=guild.id,
                            channel_id=channel.id,
                            content=text,
                        )
                        raise ControlError("send requires --confirm; use --dry-run to preview")
                    message = await channel.send(text)
                    append_audit(
                        command="send",
                        outcome="sent",
                        guild_id=guild.id,
                        channel_id=channel.id,
                        content=text,
                        message_id=message.id,
                    )
                    writer.event(
                        "sent",
                        message_id=message.id,
                        guild=guild.name,
                        guild_id=guild.id,
                        channel=channel.name,
                        channel_id=channel.id,
                    )
        except ControlError as exc:
            if args.cmd == "send" and send_context:
                append_audit(
                    command="send",
                    outcome="failed",
                    guild_id=send_context.get("guild_id"),
                    channel_id=send_context.get("channel_id"),
                    content=getattr(args, "text", None),
                    error=str(exc),
                )
            operation_error = exc
        except Exception:
            if args.cmd == "send" and send_context:
                append_audit(
                    command="send",
                    outcome="failed",
                    guild_id=send_context.get("guild_id"),
                    channel_id=send_context.get("channel_id"),
                    content=getattr(args, "text", None),
                    error="controller operation failed",
                )
            operation_error = ControlError("controller operation failed")
        finally:
            try:
                await client.close()
            except Exception:
                if operation_error is None:
                    operation_error = ControlError("controller shutdown failed")

    client.event(on_ready)
    try:
        await asyncio.wait_for(client.start(token), timeout=MAX_COMMAND_SECONDS)
    except asyncio.TimeoutError as exc:
        operation_error = ControlError(
            f"controller operation exceeded the {int(MAX_COMMAND_SECONDS)}-second safety budget"
        )
        writer.finish(ok=False, complete=False, error=str(operation_error))
        raise operation_error from exc
    finally:
        try:
            await client.close()
        except Exception:
            if operation_error is None:
                operation_error = ControlError("controller shutdown failed")
    if operation_error is not None:
        writer.finish(ok=False, complete=False, error=str(operation_error))
        raise operation_error
    if getattr(args, "rate_limit_info", False):
        writer.event("rate_limit", **REQUEST_TELEMETRY.as_dict())
    writer.finish()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_output_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--format",
            choices=("text", "jsonl"),
            default="text",
            help="output format; jsonl is safe for machine consumers",
        )
        command_parser.add_argument(
            "--rate-limit-info",
            action="store_true",
            help="append bounded REST request/rate-limit telemetry",
        )

    def add_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command_parser = sub.add_parser(name, help=help_text)
        add_output_args(command_parser)
        return command_parser

    add_command("guilds", "list guilds the account is in")
    add_command("status", "login identity + guild count")
    add_command("doctor", "identity, gateway, and controller health preflight")

    command = add_command("channels", "list text channels of a guild")
    command.add_argument("guild")

    command = add_command("messages", "recent messages in an explicit channel")
    command.add_argument("guild")
    command.add_argument("channel")
    command.add_argument("--limit", type=bounded_limit, default=25)
    command.add_argument(
        "--embeds",
        action="store_true",
        help="append embed titles/descriptions (bot channels are embed-driven)",
    )

    command = add_command("search", "guild-wide message search")
    command.add_argument("guild")
    command.add_argument("query")
    command.add_argument("--limit", type=bounded_limit, default=25)
    command.add_argument("--channel", help="restrict search to one channel")
    command.add_argument("--before", help="ISO datetime window upper bound")
    command.add_argument("--after", help="ISO datetime window lower bound")
    command.add_argument("--embeds", action="store_true", help="append embed titles/descriptions")

    command = add_command("threads", "list forum threads (archived; active cache may be empty)")
    command.add_argument("guild")
    command.add_argument("forum", nargs="?", default=None)

    command = add_command("thread", "read a forum post / thread by id")
    command.add_argument("thread")
    command.add_argument("--limit", type=bounded_limit, default=200)
    command.add_argument("--embeds", action="store_true", help="append embed titles/descriptions")

    command = add_command("member", "fetch one guild member by user id")
    command.add_argument("guild")
    command.add_argument("user_id")

    command = add_command("roles", "list guild roles")
    command.add_argument("guild")

    command = add_command("pins", "read pinned messages of a channel")
    command.add_argument("guild")
    command.add_argument("channel")

    command = add_command("guild", "guild metadata")
    command.add_argument("guild")

    add_command("dm-channels", "list DM / group DM channels")

    command = add_command("threads-search", "search active and archived threads in a channel")
    command.add_argument("guild")
    command.add_argument("channel")
    command.add_argument("query")
    command.add_argument("--limit", type=bounded_limit, default=25)

    command = add_command("send", "send a message; requires --confirm or --dry-run")
    command.add_argument("guild", help="exact guild ID or exact guild name for writes")
    command.add_argument("channel", help="exact channel ID or exact channel name for writes")
    command.add_argument("text")
    command.add_argument("--confirm", action="store_true", help="authorize the actual write")
    command.add_argument("--dry-run", action="store_true", help="preview and audit without sending")

    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except ControlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (discord.LoginFailure, discord.HTTPException) as exc:
        print(f"ERROR: Discord authentication/request failure: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    except asyncio.TimeoutError as exc:
        print("ERROR: controller operation exceeded its safety budget", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        print("ERROR: controller operation failed", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

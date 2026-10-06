"""Opt-in anonymous public text fetches with pinned, validated DNS and byte limits."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import math
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from features.research_service import ResearchWorkers


def _public(address):
    value = ipaddress.ip_address(address)
    return value.is_global and not value.is_multicast and not value.is_reserved


def validate_public_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 for c in url) or '\\' in url:
        raise ValueError('invalid_public_url')
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme not in ('http', 'https') or not host or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if parsed.port not in (None, 80 if parsed.scheme == 'http' else 443):
            raise ValueError()
        try:
            if not _public(host):
                raise ValueError('private_destination')
        except ValueError:
            # Numeric legacy IP forms and local names must not bypass IP checks.
            if re.fullmatch(r'[0-9.]+', host) or ':' in host or host.lower().rstrip('.').endswith(('localhost', '.local', '.internal')):
                raise ValueError('private_destination') from None
            labels = host.rstrip('.').encode('idna').decode().split('.')
            if len(labels) < 2 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels):
                raise ValueError('invalid_public_host')
        return url
    except (ValueError, UnicodeError):
        raise ValueError('invalid_public_url') from None


class PublicResolver(AbstractResolver):
    def __init__(self, *, lookup=None, workers=None, deadline=None):
        self.lookup = lookup
        self.workers = workers
        self.deadline = deadline

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if self.lookup is not None:
            rows = await self.lookup(host, port, family=family, type=socket.SOCK_STREAM)
        elif self.workers is not None:
            rows = await self.workers.run(host, port, family, socket.SOCK_STREAM, 0, 0,
                                         deadline=self.deadline)
        else:
            raise ValueError('unowned_dns_resolver')
        if not rows or len(rows) > 32 or any(not _public(row[4][0]) for row in rows):
            raise ValueError('private_dns_destination')
        # The connector receives the addresses just validated, not another DNS lookup.
        return [{'hostname': host, 'host': row[4][0], 'port': port,
                 'family': row[0], 'proto': row[2], 'flags': socket.AI_NUMERICHOST} for row in rows]

    async def close(self):
        # Borrowed DNS workers belong to the extractor.
        pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'iframe', 'svg', 'head'):
            self.hidden.append(tag)
    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class PublicPageExtractor:
    def __init__(self, *, session_factory=None):
        self.session_factory = session_factory
        self._dns_workers = ResearchWorkers(worker=socket.getaddrinfo)
        self._tasks = set()
        self._closed = False

    async def extract(self, url, *, deadline):
        validate_public_url(url)
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('invalid_extraction_deadline')
        if self._closed or len(self._tasks) >= 2:
            raise ValueError('extraction_closed_or_busy')
        deadline = min(deadline, time.monotonic() + 5)
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                if self.session_factory is not None:
                    session = self.session_factory()
                else:
                    resolver = PublicResolver(workers=self._dns_workers, deadline=deadline)
                    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, force_close=True, limit=2)
                    session = aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.DummyCookieJar(),
                        timeout=aiohttp.ClientTimeout(total=max(.01, deadline - time.monotonic()), sock_connect=2, sock_read=2),
                        trust_env=False, auto_decompress=False, headers={'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
                async with session:
                    current = url
                    for hop in range(4):
                        validate_public_url(current)
                        async with session.get(current, allow_redirects=False) as response:
                            if response.status in (301, 302, 303, 307, 308):
                                target = response.headers.get('Location')
                                if not target or hop == 3:
                                    raise ValueError('redirect_limit')
                                current = urljoin(current, target)
                                continue
                            if response.status != 200:
                                raise ValueError('public_fetch_failed')
                            content_type = response.headers.get('Content-Type', '').lower()
                            if content_type.split(';')[0].strip() not in ('text/html', 'text/plain'):
                                raise ValueError('unsupported_content_type')
                            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                                raise ValueError('compressed_content_refused')
                            if int(response.headers.get('Content-Length', '0')) > 262144:
                                raise ValueError('page_byte_limit')
                            raw = bytearray()
                            async for chunk in response.content.iter_chunked(8192):
                                if len(raw) + len(chunk) > 262144:
                                    raise ValueError('page_byte_limit')
                                raw.extend(chunk)
                            text = raw.decode('utf-8')
                            if content_type.startswith('text/html'):
                                parser = _Text()
                                parser.feed(text)
                                text = ' '.join(parser.parts)
                            text = ' '.join(text.split())[:6000]
                            if not text:
                                raise ValueError('no_public_text')
                            return {'url': current, 'title': urlsplit(current).hostname,
                                    'content_kind': 'extracted', 'published_at': None,
                                    'fetched_at': datetime.now(timezone.utc).isoformat(), 'source': 'public_http', 'text': text}
        finally:
            self._tasks.discard(task)

    async def close(self):
        self._closed = True
        tasks = self._tasks - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._dns_workers.close()

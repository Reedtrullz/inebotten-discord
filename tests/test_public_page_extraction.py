"""Public extraction guard receipts; fixture transport never reaches the internet."""
import asyncio
import socket
import time

import pytest

from features.public_page_extraction import PublicPageExtractor, PublicResolver, validate_public_url


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost', 'http://127.0.0.1',
    'https://[::1]', 'http://169.254.169.254/latest/meta-data', 'http://10.1.2.3',
    'https://example.com:8080', 'https://user:pass@example.com', 'https://224.0.0.1',
    'https://example.com\nHost: localhost', 'http://2130706433'])
def test_unsafe_url_is_refused_before_transport(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


@pytest.mark.asyncio
async def test_resolver_refuses_mixed_private_dns_and_returns_only_validated_addresses():
    async def mixed(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
    resolver = PublicResolver(lookup=mixed)
    with pytest.raises(ValueError):
        await resolver.resolve('example.com', 443)
    async def public(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    rows = await PublicResolver(lookup=public).resolve('example.com', 443)
    assert rows[0]['host'] == '93.184.216.34'
    assert rows[0]['hostname'] == 'example.com'


class Content:
    def __init__(self, payload, wait=None):
        self.payload, self.wait = payload, wait
    async def iter_chunked(self, size):
        if self.wait:
            await self.wait.wait()
        for start in range(0, len(self.payload), size):
            yield self.payload[start:start + size]


class Response:
    def __init__(self, payload=b'<p>synthetic text</p>', status=200, headers=None, wait=None):
        self.status = status
        self.headers = headers or {'Content-Type': 'text/html'}
        self.content = Content(payload, wait)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, replies):
        self.replies, self.urls = replies, []
        self.closed = False
    def get(self, url, **kwargs):
        assert kwargs['allow_redirects'] is False
        self.urls.append(url)
        return self.replies.pop(0)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        self.closed = True


@pytest.mark.asyncio
async def test_redirect_private_destination_is_never_requested():
    session = Session([Response(status=302, headers={'Location': 'http://127.0.0.1/secret'})])
    extractor = PublicPageExtractor(session_factory=lambda **kwargs: session)
    with pytest.raises(ValueError):
        await extractor.extract('https://example.com', deadline=time.monotonic() + 1)
    assert session.urls == ['https://example.com']
    assert session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,payload', [({'Content-Type': 'application/pdf'}, b'%PDF'),
    ({'Content-Type':'text/html','Content-Encoding':'gzip'}, b'compressed'),
    ({'Content-Type':'text/html'}, b'x' * 262145)])
async def test_type_compression_and_byte_limit_are_enforced(headers, payload):
    session = Session([Response(payload=payload, headers=headers)])
    extractor = PublicPageExtractor(session_factory=lambda **kwargs: session)
    with pytest.raises(ValueError):
        await extractor.extract('https://example.com', deadline=time.monotonic() + 1)
    assert session.closed


@pytest.mark.asyncio
async def test_text_excludes_scripts_and_cancel_closes_owned_session():
    session = Session([Response(payload=b'<script>steal_credentials()</script><style>hide</style><p>Public synthetic fact</p>')])
    extractor = PublicPageExtractor(session_factory=lambda **kwargs: session)
    card = await extractor.extract('https://example.com', deadline=time.monotonic() + 1)
    assert card['text'] == 'Public synthetic fact'
    assert card['content_kind'] == 'extracted'
    assert card['published_at'] is None
    assert session.closed
    wait = asyncio.Event()
    hanging = Session([Response(wait=wait)])
    extractor = PublicPageExtractor(session_factory=lambda **kwargs: hanging)
    task = asyncio.create_task(extractor.extract('https://example.com', deadline=time.monotonic() + 1))
    while not hanging.urls:
        await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hanging.closed

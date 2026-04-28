import asyncio

from web_console.server import ConsoleServer


HOST = "127.0.0.1"
PORT = 18080
API_KEY = "test-key-123"


async def start_server(monitor: object | None = None) -> tuple[ConsoleServer, asyncio.Task[None]]:
    server = ConsoleServer(host=HOST, port=PORT, api_key=API_KEY, monitor=monitor)
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    return server, task


async def stop_server(server: ConsoleServer, task: asyncio.Task[None]):
    await server.stop()
    _ = task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def request(path: str, *, method: str = "GET", api_key: str | None = None, body: bytes = b"", cookie: str | None = None):
    reader, writer = await asyncio.open_connection(HOST, PORT)
    headers = [
        f"{method} {path} HTTP/1.1",
        "Host: localhost",
        "Connection: close",
    ]
    if api_key is not None:
        headers.append(f"X-API-Key: {api_key}")
    if cookie is not None:
        headers.append(f"Cookie: {cookie}")
    if body:
        headers.append(f"Content-Length: {len(body)}")
    payload = "\r\n".join(headers).encode() + b"\r\n\r\n" + body
    writer.write(payload)
    await writer.drain()
    response = await reader.read(65536)
    writer.close()
    await writer.wait_closed()
    return response


async def test_auth_missing_key():
    server, task = await start_server()
    try:
        response = await request("/api/status")
        assert b"401" in response
    finally:
        await stop_server(server, task)


async def test_auth_invalid_key():
    server, task = await start_server()
    try:
        response = await request("/api/status", api_key="wrong-key")
        assert b"401" in response
    finally:
        await stop_server(server, task)


async def test_auth_valid_key():
    server, task = await start_server()
    try:
        response = await request("/api/status", api_key=API_KEY)
        assert b"200" in response
    finally:
        await stop_server(server, task)


async def test_health_no_auth():
    server, task = await start_server()
    try:
        response = await request("/health")
        assert b"200" in response
    finally:
        await stop_server(server, task)


async def test_method_not_allowed():
    server, task = await start_server()
    try:
        response = await request("/api/status", method="POST", api_key=API_KEY, body=b"{}")
        assert b"405" in response
    finally:
        await stop_server(server, task)


async def test_status_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/status", api_key=API_KEY)
        assert b'"status":' in response
    finally:
        await stop_server(server, task)


async def test_bridge_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/bridge", api_key=API_KEY)
        assert b"lm_studio" in response
    finally:
        await stop_server(server, task)


async def test_calendar_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/calendar", api_key=API_KEY)
        assert b"event_count" in response
    finally:
        await stop_server(server, task)


async def test_polls_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/polls", api_key=API_KEY)
        assert b"active_polls" in response
    finally:
        await stop_server(server, task)


async def test_rate_limits_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/rate-limits", api_key=API_KEY)
        assert b"user_stats" in response
    finally:
        await stop_server(server, task)


async def test_intents_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/intents", api_key=API_KEY)
        assert b"intent_counts" in response
    finally:
        await stop_server(server, task)


async def test_memory_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/memory", api_key=API_KEY)
        assert b"user_count" in response
    finally:
        await stop_server(server, task)


async def test_dashboard_html():
    server, task = await start_server()
    try:
        response = await request("/", api_key=API_KEY)
        assert b"<meta http-equiv=\"refresh\"" in response
    finally:
        await stop_server(server, task)


async def test_startup_monitor_none():
    server, task = await start_server(monitor=None)
    try:
        response = await request("/api/status", api_key=API_KEY)
        assert b"200" in response
    finally:
        await stop_server(server, task)


async def test_404_unknown_path():
    server, task = await start_server()
    try:
        response = await request("/unknown", api_key=API_KEY)
        assert b"404" in response
    finally:
        await stop_server(server, task)


async def test_login_page_without_auth():
    server, task = await start_server()
    try:
        response = await request("/login")
        assert b"200" in response
        assert b"Inebotten Console" in response
        assert b"api_key" in response
    finally:
        await stop_server(server, task)


async def test_root_returns_login_without_auth():
    server, task = await start_server()
    try:
        response = await request("/")
        assert b"200" in response
        assert b"api_key" in response
    finally:
        await stop_server(server, task)


async def test_api_login_valid_key():
    server, task = await start_server()
    try:
        body = b"api_key=test-key-123"
        response = await request("/api/login", method="POST", body=body)
        assert b"302" in response
        assert b"Set-Cookie: console_auth=" in response
        assert b"Location: /" in response
    finally:
        await stop_server(server, task)


async def test_api_login_invalid_key():
    server, task = await start_server()
    try:
        body = b"api_key=wrong-key"
        response = await request("/api/login", method="POST", body=body)
        assert b"401" in response
        assert "Ugyldig API-nøkkel".encode("utf-8") in response
    finally:
        await stop_server(server, task)


async def test_dashboard_with_cookie():
    server, task = await start_server()
    try:
        response = await request("/", cookie="console_auth=test-key-123")
        assert b"200" in response
        assert b"Inebotten Console" in response
    finally:
        await stop_server(server, task)


async def test_api_with_cookie():
    server, task = await start_server()
    try:
        response = await request("/api/status", cookie="console_auth=test-key-123")
        assert b"200" in response
        assert b'"status":' in response
    finally:
        await stop_server(server, task)

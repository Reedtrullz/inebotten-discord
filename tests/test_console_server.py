import asyncio

from web_console.server import ConsoleServer, MAX_BODY_BYTES


HOST = "127.0.0.1"
PORT = 18080
API_KEY = "test-key-123"


class FakeCloudflareAccessVerifier:
    configured = True

    def verify_headers(self, headers: dict[str, str]) -> bool:
        return headers.get("cf-access-jwt-assertion") == "valid-cloudflare-token"


async def start_server(monitor: object | None = None, *, secure_cookies: bool | None = None) -> tuple[ConsoleServer, asyncio.Task[None]]:
    server = ConsoleServer(host=HOST, port=PORT, api_key=API_KEY, monitor=monitor, secure_cookies=secure_cookies)
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


async def request(
    path: str,
    *,
    method: str = "GET",
    api_key: str | None = None,
    body: bytes = b"",
    cookie: str | None = None,
    extra_headers: list[str] | None = None,
):
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
    if extra_headers:
        headers.extend(extra_headers)
    if body:
        headers.append(f"Content-Length: {len(body)}")
    payload = "\r\n".join(headers).encode() + b"\r\n\r\n" + body
    writer.write(payload)
    await writer.drain()
    response = await reader.read(65536)
    writer.close()
    await writer.wait_closed()
    return response


def extract_cookie(response: bytes, name: str) -> str:
    prefix = f"Set-Cookie: {name}=".encode()
    for line in response.split(b"\r\n"):
        if line.startswith(prefix):
            value = line[len(prefix):].split(b";", 1)[0]
            return value.decode()
    raise AssertionError(f"Missing Set-Cookie for {name}")


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


async def test_cloudflare_access_header_authenticates_when_enabled():
    server = ConsoleServer(
        host=HOST,
        port=PORT,
        api_key=API_KEY,
        auth_mode="cloudflare_access",
        cloudflare_access_verifier=FakeCloudflareAccessVerifier(),
    )
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    try:
        response = await request(
            "/api/status",
            extra_headers=["Cf-Access-Jwt-Assertion: valid-cloudflare-token"],
        )
        assert b"200" in response
        assert b'"status":' in response
    finally:
        await stop_server(server, task)


async def test_cloudflare_access_mode_keeps_api_key_recovery_auth():
    server = ConsoleServer(
        host=HOST,
        port=PORT,
        api_key=API_KEY,
        auth_mode="cloudflare_access",
        cloudflare_access_verifier=FakeCloudflareAccessVerifier(),
    )
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    try:
        response = await request("/api/status", api_key=API_KEY)
        assert b"200" in response
        assert b'"status":' in response
    finally:
        await stop_server(server, task)


async def test_cloudflare_access_mode_does_not_show_api_key_login_without_access_token():
    server = ConsoleServer(
        host=HOST,
        port=PORT,
        api_key=API_KEY,
        auth_mode="cloudflare_access",
        cloudflare_access_verifier=FakeCloudflareAccessVerifier(),
    )
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    try:
        response = await request("/")
        assert b"401" in response
        assert b"Cloudflare Access authentication required" in response
        assert b"api_key" not in response
    finally:
        await stop_server(server, task)


async def test_cloudflare_access_mode_disables_browser_api_key_login():
    server = ConsoleServer(
        host=HOST,
        port=PORT,
        api_key=API_KEY,
        auth_mode="cloudflare_access",
        cloudflare_access_verifier=FakeCloudflareAccessVerifier(),
    )
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    try:
        response = await request(
            "/api/login",
            method="POST",
            api_key=API_KEY,
            body=b"api_key=test-key-123",
        )
        assert b"403" in response
        assert b"Cloudflare Access mode" in response
    finally:
        await stop_server(server, task)


async def test_cloudflare_access_mode_requires_verifier_config():
    server = ConsoleServer(
        host=HOST,
        port=0,
        api_key=API_KEY,
        auth_mode="cloudflare_access",
        cloudflare_access_team_domain="",
        cloudflare_access_audiences=[],
        cloudflare_access_allowed_emails=[],
    )
    try:
        try:
            await server.start()
        except RuntimeError as exc:
            assert "Cloudflare Access" in str(exc)
        else:
            raise AssertionError("Cloudflare Access mode accepted missing config")
    finally:
        await server.stop()


def test_missing_console_api_key_never_authenticates():
    server = ConsoleServer(api_key=None)
    assert server._is_authenticated({}) is False
    assert server._is_authenticated({"x-api-key": ""}) is False
    assert server._is_authenticated({"cookie": "console_auth="}) is False


async def test_console_server_refuses_to_start_without_api_key():
    server = ConsoleServer(host=HOST, port=0, api_key=None)
    try:
        try:
            await server.start()
        except RuntimeError as exc:
            assert "api_key" in str(exc)
        else:
            raise AssertionError("ConsoleServer.start() accepted a missing api_key")
    finally:
        await server.stop()


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
        assert b"<main" in response
        assert b"dashboard-grid" in response
        assert b"data-console-app" in response
        assert b"x-data" not in response
        assert b"tailwindcss" not in response
        assert b"alpinejs" not in response
        assert b"/static/main.css" in response
        assert b"/static/app.js" in response
    finally:
        await stop_server(server, task)


async def test_dashboard_includes_initial_data():
    server, task = await start_server()
    try:
        response = await request("/", api_key=API_KEY)
        assert b'id="initial-data"' in response
        assert b"application/json" in response
    finally:
        await stop_server(server, task)


async def test_dashboard_has_data_metrics():
    server, task = await start_server()
    try:
        response = await request("/", api_key=API_KEY)
        assert b'data-metric=' in response
        assert b'status.uptime' in response
        assert b'bridge.errors' in response
        assert b'calendar.events' in response
        assert b'polls.active' in response
        assert b'rate_limits.total' in response
        assert b'intents.fallback' in response
        assert b'memory.users' in response
        assert b'logs.count' in response
    finally:
        await stop_server(server, task)


async def test_demo_dashboard_is_auth_exempt_and_uses_static_data():
    server, task = await start_server()
    try:
        response = await request("/demo")
        assert b"200" in response
        assert b"Inebotten" in response
        assert b'data-console-app' in response
        assert b'demo-mode' in response
        assert b"/api/login" not in response
    finally:
        await stop_server(server, task)


async def test_static_css_file():
    server, task = await start_server()
    try:
        response = await request("/static/main.css")
        assert b"200" in response
        assert b"text/css" in response
    finally:
        await stop_server(server, task)


async def test_static_js_file():
    server, task = await start_server()
    try:
        response = await request("/static/app.js")
        assert b"200" in response
        assert b"application/javascript" in response
    finally:
        await stop_server(server, task)


async def test_static_path_traversal_blocked():
    server, task = await start_server()
    try:
        response = await request("/static/../../core/config.py")
        assert b"403" in response or b"404" in response
    finally:
        await stop_server(server, task)


async def test_static_nonexistent_file():
    server, task = await start_server()
    try:
        response = await request("/static/nonexistent.css")
        assert b"404" in response
    finally:
        await stop_server(server, task)


async def test_static_directory_listing_blocked():
    server, task = await start_server()
    try:
        response = await request("/static/")
        assert b"403" in response or b"404" in response
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
        assert b"HTTP/1.1 302 Found" in response
        assert b"Set-Cookie: console_session=" in response
        assert b"test-key-123" not in extract_cookie(response, "console_session").encode()
        assert b"Location: /" in response
    finally:
        await stop_server(server, task)


async def test_api_login_valid_key_sets_secure_cookie_when_enabled():
    server, task = await start_server(secure_cookies=True)
    try:
        body = b"api_key=test-key-123"
        response = await request("/api/login", method="POST", body=body)
        assert b"302" in response
        assert b"Set-Cookie: console_session=" in response
        assert b"HttpOnly" in response
        assert b"SameSite=Strict" in response
        assert b"Secure" in response
    finally:
        await stop_server(server, task)


async def test_api_login_invalid_key():
    server, task = await start_server()
    try:
        body = b"api_key=wrong-key"
        response = await request("/api/login", method="POST", body=body)
        assert b"401" in response
        assert "Innlogging feilet".encode("utf-8") in response
    finally:
        await stop_server(server, task)


async def test_dashboard_rejects_legacy_api_key_cookie():
    server, task = await start_server()
    try:
        response = await request("/", cookie="console_auth=test-key-123")
        assert b"api_key" in response
        assert b'data-metric=' not in response
    finally:
        await stop_server(server, task)


async def test_dashboard_with_session_cookie():
    server, task = await start_server()
    try:
        login = await request("/api/login", method="POST", body=b"api_key=test-key-123")
        token = extract_cookie(login, "console_session")
        response = await request("/", cookie=f"console_session={token}")
        assert b"200" in response
        assert b"Inebotten Console" in response
        assert b"<main" in response
    finally:
        await stop_server(server, task)


async def test_session_cookie_invalid_after_api_key_rotation():
    server, task = await start_server()
    try:
        login = await request("/api/login", method="POST", body=b"api_key=test-key-123")
        token = extract_cookie(login, "console_session")

        server.api_key = "rotated-key"

        old_session = await request("/api/status", cookie=f"console_session={token}")
        new_key = await request("/api/status", api_key="rotated-key")
        assert b"401" in old_session
        assert b"200" in new_key
    finally:
        await stop_server(server, task)


async def test_api_with_session_cookie():
    server, task = await start_server()
    try:
        login = await request("/api/login", method="POST", body=b"api_key=test-key-123")
        token = extract_cookie(login, "console_session")
        response = await request("/api/status", cookie=f"console_session={token}")
        assert b"200" in response
        assert b'"status":' in response
    finally:
        await stop_server(server, task)


async def test_logout_expires_session_cookie():
    server, task = await start_server()
    try:
        login = await request("/api/login", method="POST", body=b"api_key=test-key-123")
        token = extract_cookie(login, "console_session")
        logout = await request("/api/logout", method="POST", cookie=f"console_session={token}")
        assert b"302" in logout
        assert b"Location: /login" in logout
        assert b"Max-Age=0" in logout
        response = await request("/api/status", cookie=f"console_session={token}")
        assert b"401" in response
    finally:
        await stop_server(server, task)


async def test_login_throttles_repeated_failures():
    server = ConsoleServer(
        host=HOST,
        port=PORT,
        api_key=API_KEY,
        login_max_attempts=2,
        login_window_seconds=60,
    )
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    try:
        body = b"api_key=wrong-key"
        assert b"401" in await request("/api/login", method="POST", body=body)
        assert b"401" in await request("/api/login", method="POST", body=body)
        response = await request("/api/login", method="POST", body=body)
        assert b"429" in response
    finally:
        await stop_server(server, task)


async def test_login_secure_cookie_when_forwarded_https():
    server, task = await start_server()
    try:
        response = await request(
            "/api/login",
            method="POST",
            body=b"api_key=test-key-123",
            extra_headers=["X-Forwarded-Proto: https"],
        )
        cookie_line = [
            line for line in response.split(b"\r\n")
            if line.startswith(b"Set-Cookie: console_session=")
        ][0]
        assert b"Secure" in cookie_line
    finally:
        await stop_server(server, task)


async def test_logs_endpoint():
    server, task = await start_server()
    try:
        response = await request("/api/logs", api_key=API_KEY)
        assert b"200" in response
        assert b"logs" in response
    finally:
        await stop_server(server, task)


async def test_console_responses_include_security_headers():
    server, task = await start_server()
    try:
        login_page = await request("/login")
        api_response = await request("/api/status", api_key=API_KEY)

        for response in (login_page, api_response):
            assert b"Cache-Control: no-store" in response
            assert b"Pragma: no-cache" in response
            assert b"X-Content-Type-Options: nosniff" in response
            assert b"X-Frame-Options: DENY" in response
            assert b"Referrer-Policy: no-referrer" in response
        assert b"Content-Security-Policy:" in login_page
    finally:
        await stop_server(server, task)


async def test_logs_endpoint_with_lines_param():
    server, task = await start_server()
    try:
        response = await request("/api/logs?lines=50", api_key=API_KEY)
        assert b"200" in response
        assert b"logs" in response
    finally:
        await stop_server(server, task)


async def test_logs_endpoint_clamps_lines_param():
    server, task = await start_server()
    try:
        response = await request("/api/logs?lines=999999", api_key=API_KEY)
        assert b"200" in response
        assert b"logs" in response
    finally:
        await stop_server(server, task)


async def test_invalid_content_length_returns_400():
    server, task = await start_server()
    try:
        response = await request(
            "/api/login",
            method="POST",
            extra_headers=["Content-Length: not-a-number"],
        )
        assert b"400" in response
        assert b"Invalid Content-Length" in response
    finally:
        await stop_server(server, task)


async def test_oversized_body_returns_413():
    server, task = await start_server()
    try:
        body = b"x" * (MAX_BODY_BYTES + 1)
        response = await request("/api/login", method="POST", body=body)
        assert b"413" in response
        assert b"Request body too large" in response
    finally:
        await stop_server(server, task)

import asyncio
import hmac
import json
import logging
import os
import pathlib
import time
from datetime import datetime
from typing import cast
from urllib.parse import urlparse

from web_console.dashboard import render_commands_page, render_dashboard, render_login_page  # pyright: ignore[reportUnknownVariableType]
from web_console.console_store import get_console_store
from web_console.state_collector import (
    StateCollector,
    collect_bot_status,
    collect_bridge_health,
    collect_calendar_data,
    collect_intent_stats,
    collect_logs,
    collect_memory_stats,
    collect_poll_data,
    collect_rate_limits,
    generate_mock_data,
)

logger = logging.getLogger(__name__)

MAX_HEADER_BYTES = 32 * 1024
MAX_BODY_BYTES = 16 * 1024


class ConsoleServer:
    host: str
    port: int
    api_key: str | None
    cookie_secure: bool
    monitor: object | None
    _server: asyncio.AbstractServer | None

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        api_key: str | None = None,
        monitor: object | None = None,
        secure_cookies: bool | None = None,
        session_ttl_days: int | None = None,
        login_max_attempts: int | None = None,
        login_window_seconds: int | None = None,
        cookie_secure: bool | None = None,
    ):
        self.host = host
        self.port = port
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.monitor = monitor
        self._server = None
        self.store = get_console_store()
        self.session_ttl_seconds = max(
            1,
            int(session_ttl_days if session_ttl_days is not None else os.getenv("CONSOLE_SESSION_TTL_DAYS", "30")) * 86400,
        )
        self.login_max_attempts = max(
            1,
            int(login_max_attempts if login_max_attempts is not None else os.getenv("CONSOLE_LOGIN_MAX_ATTEMPTS", "5")),
        )
        self.login_window_seconds = max(
            1,
            int(login_window_seconds if login_window_seconds is not None else os.getenv("CONSOLE_LOGIN_WINDOW_SECONDS", "300")),
        )
        if cookie_secure is None:
            cookie_secure = secure_cookies
        if cookie_secure is None:
            cookie_secure = os.getenv("CONSOLE_COOKIE_SECURE", "False").lower() == "true"
        self.cookie_secure = bool(cookie_secure)
        self._login_failures: dict[str, list[float]] = {}

    @property
    def actual_port(self) -> int:
        if self._server is None:
            return self.port
        for sock in (self._server.sockets or []):
            return sock.getsockname()[1]
        return self.port

    async def start(self) -> None:
        if self._server is not None:
            return

        if self.api_key is None:
            raise RuntimeError("ConsoleServer requires a non-empty api_key")

        self._server = await asyncio.start_server(self.handle_request, self.host, self.port)
        sockets = self._server.sockets or []
        bound = ", ".join(f"{sock.getsockname()!r}" for sock in sockets) if sockets else f"{self.host}:{self.port}"
        logger.info("Console server started on %s", bound)

    async def stop(self) -> None:
        if self._server is None:
            return

        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("Console server stopped")

    def _parse_headers(self, lines: list[str]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    def _content_length(self, headers: dict[str, str]) -> int | None:
        raw_length = headers.get("content-length", "0") or "0"
        try:
            content_length = int(raw_length)
        except ValueError:
            return None
        if content_length < 0:
            return None
        return content_length

    def _parse_cookies(self, cookie_header: str | None) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if not cookie_header:
            return cookies
        for part in cookie_header.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def _candidate_matches_api_key(self, candidate: str | None) -> bool:
        if self.api_key is None or candidate is None:
            return False
        return hmac.compare_digest(candidate, self.api_key)

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        api_key = headers.get("x-api-key")
        if self._valid_api_key(api_key):
            return True
        cookies = self._parse_cookies(headers.get("cookie"))
        if self.store.validate_session(cookies.get("console_session")):
            return True
        return False

    def _valid_api_key(self, submitted: str | None) -> bool:
        expected = "" if self.api_key is None else str(self.api_key)
        if not submitted or not expected:
            return False
        return hmac.compare_digest(submitted, expected)

    def _peer_key(self, writer: asyncio.StreamWriter) -> str:
        peername = writer.get_extra_info("peername")
        if isinstance(peername, tuple) and peername:
            return str(peername[0])
        return "unknown"

    def _login_limited(self, peer_key: str) -> bool:
        now = time.time()
        failures = [
            ts for ts in self._login_failures.get(peer_key, [])
            if now - ts < self.login_window_seconds
        ]
        self._login_failures[peer_key] = failures
        return len(failures) >= self.login_max_attempts

    def _record_login_failure(self, peer_key: str) -> None:
        failures = self._login_failures.setdefault(peer_key, [])
        failures.append(time.time())
        self._login_failures[peer_key] = [
            ts for ts in failures if time.time() - ts < self.login_window_seconds
        ]

    def _clear_login_failures(self, peer_key: str) -> None:
        self._login_failures.pop(peer_key, None)

    def _secure_cookie_enabled(self, headers: dict[str, str]) -> bool:
        forwarded_proto = headers.get("x-forwarded-proto", "").lower()
        return self.cookie_secure or forwarded_proto == "https"

    def _session_cookie_header(self, token: str, headers: dict[str, str], max_age: int | None = None) -> str:
        max_age = self.session_ttl_seconds if max_age is None else max_age
        parts = [
            f"console_session={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={max_age}",
        ]
        if self._secure_cookie_enabled(headers):
            parts.append("Secure")
        return "Set-Cookie: " + "; ".join(parts)

    async def _serve_static_file(self, writer: asyncio.StreamWriter, path: str) -> None:
        static_dir = pathlib.Path(__file__).parent / "static"
        if not path.startswith("/static/"):
            await self._send_response(writer, 404, {"error": "Not found"})
            return

        relative = path[len("/static/"):]
        requested = static_dir / relative

        try:
            resolved = requested.resolve()
            static_resolved = static_dir.resolve()
            if not str(resolved).startswith(str(static_resolved) + os.sep) and str(resolved) != str(static_resolved):
                await self._send_response(writer, 403, {"error": "Forbidden"})
                return
        except (OSError, ValueError):
            await self._send_response(writer, 403, {"error": "Forbidden"})
            return

        if not resolved.is_file():
            await self._send_response(writer, 404, {"error": "Not found"})
            return

        for part in [requested] + list(requested.parents):
            if part == static_dir:
                break
            if part.is_symlink():
                await self._send_response(writer, 403, {"error": "Forbidden"})
                return

        ext = resolved.suffix.lower()
        mime_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".woff2": "font/woff2",
            ".ico": "image/x-icon",
            ".json": "application/json",
        }

        if ext not in mime_types:
            await self._send_response(writer, 403, {"error": "Forbidden"})
            return

        try:
            content = resolved.read_bytes()
            await self._send_response(writer, 200, content, content_type=mime_types[ext])
        except OSError:
            await self._send_response(writer, 404, {"error": "Not found"})

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, body: object, content_type: str = "application/json; charset=utf-8", extra_headers: list[str] | None = None) -> None:
        status_text = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            302: "Found",
            429: "Too Many Requests",
            500: "Internal Server Error",
        }.get(status, "OK")

        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")

        header_lines = [
            f"HTTP/1.1 {status} {status_text}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body_bytes)}",
            "Connection: close",
        ]
        if extra_headers:
            header_lines.extend(extra_headers)
        header_lines.extend(["", ""])

        writer.write("\r\n".join(header_lines).encode("utf-8") + body_bytes)
        await writer.drain()

    async def handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                header_data = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:
                return
            except asyncio.LimitOverrunError:
                await self._send_response(writer, 400, {"error": "Request headers too large"})
                return
            if len(header_data) > MAX_HEADER_BYTES:
                await self._send_response(writer, 400, {"error": "Request headers too large"})
                return

            header_text = header_data.decode("utf-8", errors="ignore")
            lines = header_text.split("\r\n")
            if not lines or not lines[0]:
                await self._send_response(writer, 400, {"error": "Empty request"})
                return

            request_line = lines[0].split()
            if len(request_line) < 2:
                await self._send_response(writer, 400, {"error": "Invalid request"})
                return

            method, target = request_line[0].upper(), request_line[1]
            parsed = urlparse(target)
            path = parsed.path or "/"
            headers = self._parse_headers(lines[1:])

            content_length = self._content_length(headers)
            if content_length is None:
                await self._send_response(writer, 400, {"error": "Invalid Content-Length"})
                return
            if content_length > MAX_BODY_BYTES:
                await self._send_response(writer, 413, {"error": "Request body too large"})
                return
            body_bytes = b""
            if content_length > 0:
                try:
                    body_bytes = await reader.readexactly(content_length)
                except asyncio.IncompleteReadError:
                    await self._send_response(writer, 400, {"error": "Incomplete request body"})
                    return

            if method == "GET" and path.startswith("/static/"):
                await self._serve_static_file(writer, path)
                return

            auth_exempt = path in ("/health", "/api/login", "/demo", "/commands")
            authenticated = auth_exempt or self._is_authenticated(headers)

            if not authenticated and path in ("/", "/login"):
                html = render_login_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
                return

            if not authenticated:
                peername = cast(object | None, writer.get_extra_info("peername"))
                peername_text = "None" if peername is None else repr(peername)
                logger.warning("Unauthorized request to %s from %s", path, peername_text)
                await self._send_response(writer, 401, {"error": "Unauthorized"})
                return

            if method == "POST" and path == "/api/login":
                peer_key = self._peer_key(writer)
                if self._login_limited(peer_key):
                    html = render_login_page(error="Innlogging midlertidig blokkert. Prøv igjen senere.")
                    await self._send_response(writer, 429, html, content_type="text/html; charset=utf-8")
                    return

                body_text = body_bytes.decode("utf-8", errors="replace")
                form_data: dict[str, str] = {}
                for pair in body_text.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        form_data[unquote_plus(k)] = unquote_plus(v)
                submitted_key = form_data.get("api_key", "")
                if self._valid_api_key(submitted_key):
                    self._clear_login_failures(peer_key)
                    token = self.store.create_session(self.session_ttl_seconds)
                    await self._send_response(
                        writer,
                        302,
                        "",
                        content_type="text/plain",
                        extra_headers=[
                            "Location: /",
                            self._session_cookie_header(token, headers),
                        ],
                    )
                else:
                    self._record_login_failure(peer_key)
                    html = render_login_page(error="Innlogging feilet")
                    await self._send_response(writer, 401, html, content_type="text/html; charset=utf-8")
                return

            if method == "POST" and path == "/api/logout":
                cookies = self._parse_cookies(headers.get("cookie"))
                self.store.delete_session(cookies.get("console_session"))
                await self._send_response(
                    writer,
                    302,
                    "",
                    content_type="text/plain",
                    extra_headers=[
                        "Location: /login",
                        self._session_cookie_header("", headers, max_age=0),
                    ],
                )
                return

            if method != "GET":
                await self._send_response(writer, 405, {"error": "Method not allowed"})
                return

            if path == "/login":
                html = render_login_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/health":
                await self._send_response(
                    writer,
                    200,
                    {
                        "status": "healthy",
                        "console": "running",
                        "timestamp": datetime.now().isoformat(),
                        "port": self.port,
                    },
                )
            elif path == "/":
                data = await StateCollector(self.monitor).collect_all()
                html = render_dashboard(data)
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/commands":
                html = render_commands_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/demo":
                html = render_dashboard(generate_mock_data(), is_demo=True)
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/api/status":
                await self._send_response(writer, 200, collect_bot_status(self.monitor))
            elif path == "/api/bridge":
                bridge = await collect_bridge_health(self.monitor)
                bridge.setdefault("lm_studio", "unknown")
                bridge.setdefault("requests", 0)
                bridge.setdefault("errors", 0)
                await self._send_response(writer, 200, bridge)
            elif path == "/api/calendar":
                await self._send_response(writer, 200, collect_calendar_data(self.monitor))
            elif path == "/api/polls":
                await self._send_response(writer, 200, collect_poll_data(self.monitor))
            elif path == "/api/rate-limits":
                await self._send_response(writer, 200, collect_rate_limits(self.monitor))
            elif path == "/api/intents":
                await self._send_response(writer, 200, collect_intent_stats(self.monitor))
            elif path == "/api/memory":
                await self._send_response(writer, 200, collect_memory_stats(self.monitor))
            elif path == "/api/logs":
                parsed_query = urlparse(target)
                query_lines = 200
                if parsed_query.query:
                    for pair in parsed_query.query.split("&"):
                        if pair.startswith("lines="):
                            try:
                                query_lines = int(pair.split("=", 1)[1])
                            except ValueError:
                                pass
                query_lines = max(1, min(query_lines, 2000))
                await self._send_response(writer, 200, collect_logs(query_lines))
            else:
                await self._send_response(writer, 404, {"error": "Not found"})
        except Exception:
            logger.exception("Unhandled error while processing request")
            try:
                await self._send_response(writer, 500, {"error": "Internal server error"})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

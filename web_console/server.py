import asyncio
import json
import logging
import os
import pathlib
from datetime import datetime
from typing import cast
from urllib.parse import urlparse

from web_console.dashboard import render_dashboard, render_login_page  # pyright: ignore[reportUnknownVariableType]
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
)

logger = logging.getLogger(__name__)


class ConsoleServer:
    host: str
    port: int
    api_key: object | None
    monitor: object | None
    _server: asyncio.AbstractServer | None

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, api_key: object | None = None, monitor: object | None = None):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.monitor = monitor
        self._server = None

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

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        api_key = headers.get("x-api-key")
        if api_key == self.api_key:
            return True
        cookies = self._parse_cookies(headers.get("cookie"))
        if cookies.get("console_auth") == self.api_key:
            return True
        return False

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

            content_length = int(headers.get("content-length", "0") or 0)
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

            auth_exempt = path in ("/health", "/api/login")
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
                body_text = body_bytes.decode("utf-8", errors="replace")
                form_data: dict[str, str] = {}
                for pair in body_text.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        form_data[unquote_plus(k)] = unquote_plus(v)
                submitted_key = form_data.get("api_key", "")
                if submitted_key == self.api_key:
                    await self._send_response(
                        writer,
                        302,
                        "",
                        content_type="text/plain",
                        extra_headers=[
                            "Location: /",
                            "Set-Cookie: console_auth=" + str(self.api_key) + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000",
                        ],
                    )
                else:
                    html = render_login_page(error="Ugyldig API-nøkkel")
                    await self._send_response(writer, 401, html, content_type="text/html; charset=utf-8")
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

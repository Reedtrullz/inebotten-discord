import asyncio
import json
import logging
from typing import cast
from urllib.parse import urlparse

from web_console.dashboard import render_dashboard  # pyright: ignore[reportUnknownVariableType]
from web_console.state_collector import (
    StateCollector,
    collect_bot_status,
    collect_bridge_health,
    collect_calendar_data,
    collect_intent_stats,
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

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, body: object, content_type: str = "application/json; charset=utf-8") -> None:
        status_text = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
        }.get(status, "OK")

        if isinstance(body, (dict, list)):
            payload = json.dumps(body, ensure_ascii=False)
        elif isinstance(body, bytes):
            payload = body.decode("utf-8", errors="replace")
        else:
            payload = str(body)

        body_bytes = payload.encode("utf-8")
        header_lines = [
            f"HTTP/1.1 {status} {status_text}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body_bytes)}",
            "Connection: close",
            "",
            "",
        ]

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

            if path != "/health":
                api_key = headers.get("x-api-key")
                if api_key != self.api_key:
                    peername = cast(object | None, writer.get_extra_info("peername"))
                    peername_text = "None" if peername is None else repr(peername)
                    logger.warning("Unauthorized request to %s from %s", path, peername_text)
                    await self._send_response(writer, 401, {"error": "Unauthorized"})
                    return

            content_length = int(headers.get("content-length", "0") or 0)
            if content_length > 0:
                try:
                    _ = await reader.readexactly(content_length)
                except asyncio.IncompleteReadError:
                    await self._send_response(writer, 400, {"error": "Incomplete request body"})
                    return

            if method != "GET":
                await self._send_response(writer, 405, {"error": "Method not allowed"})
                return

            if path == "/health":
                await self._send_response(writer, 200, {"status": "healthy", "console": "running"})
            elif path == "/":
                data = StateCollector(self.monitor).collect_all()
                html = render_dashboard(data)
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/api/status":
                await self._send_response(writer, 200, collect_bot_status(self.monitor))
            elif path == "/api/bridge":
                bridge = collect_bridge_health(self.monitor)
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

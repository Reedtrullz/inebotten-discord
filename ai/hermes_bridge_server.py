#!/usr/bin/env python3
"""
Hermes Bridge Server for Discord Selfbot
Connects to LM Studio on Windows host from WSL for AI responses
"""

import asyncio
from collections.abc import Mapping
import json
import logging
import math
import os
import sys
import random
import signal
import time
from datetime import datetime, date
from urllib.parse import unquote, urlparse, parse_qs

from ai.response_cleaner import MAX_CLEANER_INPUT_BYTES

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_HEADER_BYTES = 32 * 1024
MAX_BODY_BYTES = 256 * 1024
MAX_CONTEXT_CHARS = 4_000
MAX_AUTHOR_NAME_CHARS = 200
MAX_CHANNEL_TYPE_CHARS = 64
REASONING_ONLY_FALLBACK = "(Modellen ga ikke et synlig svar.)"


class BridgeContractError(ValueError):
    """Bounded request/response contract failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _utf8_size(value: str, *, code: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise BridgeContractError(code) from None


def _finite_number(
    value: object,
    *,
    code: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeContractError(code)
    try:
        selected = float(value)
    except (OverflowError, TypeError, ValueError):
        raise BridgeContractError(code) from None
    if not math.isfinite(selected) or not minimum <= selected <= maximum:
        raise BridgeContractError(code)
    return selected


def _bounded_max_tokens(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 4_096
    ):
        raise BridgeContractError("invalid_max_tokens")
    return value


def build_untrusted_context_data(
    *,
    author_name: str,
    channel_type: str,
    context_prompt: str,
) -> str:
    """Serialize bounded metadata as valid JSON data, never instructions."""

    if (
        not isinstance(author_name, str)
        or len(author_name) > MAX_AUTHOR_NAME_CHARS
    ):
        raise BridgeContractError("invalid_author_name")
    if (
        not isinstance(channel_type, str)
        or len(channel_type) > MAX_CHANNEL_TYPE_CHARS
    ):
        raise BridgeContractError("invalid_channel_type")
    if (
        not isinstance(context_prompt, str)
        or len(context_prompt) > MAX_CONTEXT_CHARS
    ):
        raise BridgeContractError("invalid_context_prompt")
    _utf8_size(author_name, code="invalid_author_name")
    _utf8_size(channel_type, code="invalid_channel_type")
    _utf8_size(context_prompt, code="invalid_context_prompt")

    def serialize(value: str) -> str:
        return json.dumps(
            {
                "author_name": author_name,
                "channel_type": channel_type,
                "context": value,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    serialized = serialize(context_prompt)
    if len(serialized) <= MAX_CONTEXT_CHARS:
        return serialized

    low = 0
    high = len(context_prompt)
    while low < high:
        middle = (low + high + 1) // 2
        if len(serialize(context_prompt[:middle])) <= MAX_CONTEXT_CHARS:
            low = middle
        else:
            high = middle - 1
    return serialize(context_prompt[:low])


def build_bridge_request(
    *,
    message_content: str,
    system_prompt: str,
    temperature: float | None,
    max_tokens: int | None,
    model: str,
    model_config: Mapping[str, object],
    context_prompt: str = "",
) -> dict[str, object]:
    """Build one strict LM Studio request without reading clocks or I/O."""

    if not isinstance(message_content, str):
        raise BridgeContractError("invalid_message")
    if not isinstance(system_prompt, str):
        raise BridgeContractError("invalid_system_prompt")
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise BridgeContractError("invalid_model")
    if not isinstance(model_config, Mapping):
        raise BridgeContractError("invalid_model_config")
    if (
        not isinstance(context_prompt, str)
        or len(context_prompt) > MAX_CONTEXT_CHARS
    ):
        raise BridgeContractError("invalid_context_prompt")
    _utf8_size(message_content, code="invalid_message")
    _utf8_size(system_prompt, code="invalid_system_prompt")
    _utf8_size(model, code="invalid_model")
    _utf8_size(context_prompt, code="invalid_context_prompt")

    selected_temperature = _finite_number(
        temperature
        if temperature is not None
        else model_config.get("temperature"),
        code="invalid_temperature",
        minimum=0.0,
        maximum=2.0,
    )
    selected_max_tokens = _bounded_max_tokens(
        max_tokens
        if max_tokens is not None
        else model_config.get("max_tokens")
    )
    top_p = _finite_number(
        model_config.get("top_p"),
        code="invalid_top_p",
        minimum=0.0,
        maximum=1.0,
    )
    frequency_penalty = _finite_number(
        model_config.get("frequency_penalty", 0.0),
        code="invalid_frequency_penalty",
        minimum=-2.0,
        maximum=2.0,
    )
    presence_penalty = _finite_number(
        model_config.get("presence_penalty", 0.0),
        code="invalid_presence_penalty",
        minimum=-2.0,
        maximum=2.0,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]
    if context_prompt:
        messages.append(
            {
                "role": "user",
                "content": f"UNTRUSTED_CONTEXT_DATA\n{context_prompt}",
            }
        )
    messages.append({"role": "user", "content": message_content})
    request: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": selected_temperature,
        "max_tokens": selected_max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "stream": False,
    }
    if "repeat_penalty" in model_config:
        request["repeat_penalty"] = _finite_number(
            model_config["repeat_penalty"],
            code="invalid_repeat_penalty",
            minimum=0.01,
            maximum=10.0,
        )
    if "stop" in model_config:
        stop = model_config["stop"]
        if (
            not isinstance(stop, (list, tuple))
            or len(stop) > 32
            or any(
                not isinstance(item, str) or len(item) > 200
                for item in stop
            )
        ):
            raise BridgeContractError("invalid_stop")
        for item in stop:
            _utf8_size(item, code="invalid_stop")
        request["stop"] = list(stop)
    return request


def extract_bridge_content(response_json: object) -> str:
    """Return only visible provider content, byte-for-byte."""

    if not isinstance(response_json, Mapping):
        raise BridgeContractError("invalid_response_shape")
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise BridgeContractError("invalid_response_shape")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise BridgeContractError("invalid_response_shape")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise BridgeContractError("invalid_response_shape")
    content = message.get("content")
    if content is None:
        return REASONING_ONLY_FALLBACK
    if not isinstance(content, str):
        raise BridgeContractError("invalid_response_content")
    content_size = _utf8_size(content, code="invalid_response_encoding")
    if content_size > MAX_CLEANER_INPUT_BYTES:
        raise BridgeContractError("response_too_large")
    if not content.strip():
        return REASONING_ONLY_FALLBACK
    return content

# Configuration
HOST = os.getenv("HERMES_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("HERMES_BRIDGE_PORT", "3000"))

# LM Studio Configuration
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")

# Model-specific settings
MODEL_CONFIG = {
    "llama-3.2-3b": {
        "temperature": 0.4,  # Very low for maximum consistency
        "max_tokens": 250,  # Increased for markdown support
        "top_p": 0.8,  # Focused sampling
        "frequency_penalty": 0.3,  # Strong penalty to avoid English mixing
        "presence_penalty": 0.2,
        "repeat_penalty": 1.3,  # Penalize repetition
    },
    "qwen-2.5-4b": {
        "temperature": 0.7,  # Qwen handles Norwegian well at normal temps
        "max_tokens": 200,  # Can handle longer responses
        "top_p": 0.9,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.1,
    },
    "qwen-2.5-7b": {
        "temperature": 0.6,  # Lower for more consistency
        "max_tokens": 150,  # Shorter to prevent rambling
        "top_p": 0.85,
        "frequency_penalty": 0.2,  # Penalty for English words
        "presence_penalty": 0.1,
        "stop": [
            "Hei again",
            "Hi ",
            "Hello ",
            "English",
        ],  # Stop if it switches to English
    },
    "qwen3.5-9b-claude-4.6-opus-reasoning-distilled@q4_k_m": {
        "temperature": 0.35,  # Very low for strict adherence to examples
        "max_tokens": 200,  # Short responses
        "top_p": 0.75,
        "frequency_penalty": 0.4,  # High penalty to prevent English thinking
        "presence_penalty": 0.2,
        "stop": [
            "Hei again",
            "Hi ",
            "Hello ",
            "English",
            "Looking at",
            "In the examples",
            "The user is",
            "This is",
            "My reasoning",
            "I should",
            "I need",
        ],
    },
    "qwen3.5-9b-claude-4.6-opus-reasoning-distilled": {
        # Alias without quantization suffix
        "temperature": 0.5,
        "max_tokens": 120,
        "top_p": 0.8,
        "frequency_penalty": 0.2,
        "presence_penalty": 0.1,
        "stop": [
            "Hei again",
            "Hi ",
            "Hello ",
            "English",
            "Looking at",
            "In the examples",
        ],
    },
    "qwen3-4b-thinking": {
        "temperature": 0.6,
        "max_tokens": 150,
        "top_p": 0.85,
        "frequency_penalty": 0.15,
        "presence_penalty": 0.1,
        "stop": ["Hei again", "Hi ", "Hello ", "English"],
    },
    "gemma-2-2b": {
        "temperature": 0.7,
        "max_tokens": 150,
        "top_p": 0.9,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.1,
    },
    "gemma-3-4b": {
        "temperature": 0.8,
        "max_tokens": 500,
        "top_p": 0.95,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
    },
    "norskgpt-llama3-8b": {
        "temperature": 0.6,  # Moderate temperature for consistency
        "max_tokens": 200,   # Reasonable length for chat responses
        "top_p": 0.9,
        "frequency_penalty": 0.2,  # Slight penalty to avoid repetition
        "presence_penalty": 0.1,
        "stop": ["<|", "WSS", "User:", "Human:"],  # Stop on special tokens (REMOVED '[' to allow Markdown)
    },
    "mistral-7b": {
        "temperature": 0.75,
        "max_tokens": 300,
        "top_p": 0.9,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.1,
    },
}

# Fun response templates (fallback when LM Studio unavailable)
RESPONSES = {
    "greeting": [
        "Hei! 👋 Jeg er Ine, din kalender-venn!",
        "Heisann! 📅 Hva kan jeg hjelpe med?",
        "Hei der! 🌟 Klar for å hjelpe!",
    ],
    "weather": [
        "Været? 🌤️ La meg sjekke...",
        "Skal se på været for deg! ☀️",
    ],
    "calendar": [
        "📅 I dag er {date}. La meg sjekke kalenderen!",
        "Kalenderen? 📆 La meg se hva som skjer!",
    ],
    "time": [
        "🕐 Klokken er nå {time}!",
        "Tiden? ⏰ Den er {time}!",
    ],
    "help": [
        "Jeg kan hjelpe med:\n📅 Kalender og arrangementer\n🌤️ Værmelding\n💬 Generelle spørsmål\n🎯 Og mye mer!",
    ],
    "fun_fact": [
        "Visste du at? 🤔 Den korteste krigen i historien varte bare 38-45 minutter!",
        "Morsomt faktum: 🍯 Honning kan holde seg i tusenvis av år!",
        "Visste du? 🐙 Blekkspruter har tre hjerter og blått blod!",
    ],
    "default": [
        "😅 Beklager, jeg sliter med å svare akkurat nå. Prøv å spørre igjen!",
        "Hmm, AI-modellen virker litt trett. Kan du spørre på nytt? 🤔",
        "Oi, jeg fikk ikke svar fra hjernen min. Prøv igjen! 🧠",
    ],
}


def generate_local_response(message, author_name):
    """Generate a response based on the message content (fallback)"""
    msg_lower = message.lower()
    today = date.today().strftime("%A, %B %d, %Y")
    now = datetime.now().strftime("%I:%M %p")

    if any(word in msg_lower for word in ["hello", "hi", "hey", "greetings"]):
        return random.choice(RESPONSES["greeting"])
    if any(
        word in msg_lower for word in ["weather", "temp", "temperature", "forecast"]
    ):
        return random.choice(RESPONSES["weather"])
    if any(
        word in msg_lower for word in ["date", "day", "calendar", "today", "schedule"]
    ):
        return random.choice(RESPONSES["calendar"]).format(date=today)
    if any(word in msg_lower for word in ["time", "clock", "hour"]):
        return random.choice(RESPONSES["time"]).format(time=now)
    if any(word in msg_lower for word in ["help", "what can you do", "commands"]):
        return random.choice(RESPONSES["help"])
    if any(word in msg_lower for word in ["fact", "trivia", "tell me something"]):
        return random.choice(RESPONSES["fun_fact"])
    return random.choice(RESPONSES["default"])


class HermesBridgeServer:
    """Bridge server with LM Studio AI integration"""

    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.session = None
        self.lm_studio_available = None
        self.lm_studio_checked_at = 0.0
        self.lm_studio_cache_ttl = float(os.getenv("LM_STUDIO_HEALTH_CACHE_TTL", "10"))

    async def _get_session(self):
        if self.session is None or self.session.closed:
            import aiohttp

            self.session = aiohttp.ClientSession()
        return self.session

    async def _check_lm_studio(self):
        now = time.monotonic()
        if self.lm_studio_available is not None and now - self.lm_studio_checked_at < self.lm_studio_cache_ttl:
            return self.lm_studio_available
        try:
            import aiohttp

            session = await self._get_session()
            async with session.get(
                f"{LM_STUDIO_URL}/models", timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                self.lm_studio_available = resp.status == 200
                self.lm_studio_checked_at = now
                if self.lm_studio_available:
                    logger.info("✓ LM Studio connected!")
                return self.lm_studio_available
        except Exception:
            logger.debug("bridge_health code=provider_unavailable")
            self.lm_studio_available = False
            self.lm_studio_checked_at = now
            return False

    async def _generate_ai_response(
        self,
        message,
        author_name,
        channel_type,
        custom_system_prompt=None,
        temperature=None,
        max_tokens=None,
        context_prompt="",
    ):
        """Generate one raw visible response through the strict bridge contract."""

        import aiohttp

        config = MODEL_CONFIG.get(LM_STUDIO_MODEL)
        if config is None:
            config = MODEL_CONFIG.get(LM_STUDIO_MODEL.split("@", 1)[0])
        if config is None:
            config = MODEL_CONFIG["llama-3.2-3b"]

        if custom_system_prompt is not None and not isinstance(
            custom_system_prompt, str
        ):
            logger.warning(
                "bridge_request_rejected code=invalid_system_prompt model=%s",
                LM_STUDIO_MODEL,
            )
            return None
        if custom_system_prompt and custom_system_prompt.strip():
            system_prompt = custom_system_prompt
        else:
            today = datetime.now().strftime("%d.%m.%Y")
            system_prompt = (
                "Du er Ine, en vennlig norsk Discord-assistent. "
                f"TRUSTED_DATE={today}. "
                "Svar direkte, kort og naturlig på norsk. "
                "Bruk aldri resonneringstekst som et synlig svar."
            )

        try:
            context_data = build_untrusted_context_data(
                author_name=author_name,
                channel_type=channel_type,
                context_prompt=context_prompt,
            )
            request = build_bridge_request(
                message_content=message,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=LM_STUDIO_MODEL,
                model_config=config,
                context_prompt=context_data,
            )
        except BridgeContractError as exc:
            logger.warning(
                "bridge_request_rejected code=%s model=%s",
                exc.code,
                LM_STUDIO_MODEL,
            )
            return None

        session = await self._get_session()
        try:
            async with session.post(
                f"{LM_STUDIO_URL}/chat/completions",
                json=request,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status != 200:
                    logger.error(
                        "bridge_provider_error code=http_status_%s model=%s",
                        response.status,
                        LM_STUDIO_MODEL,
                    )
                    self.lm_studio_available = False
                    self.lm_studio_checked_at = time.monotonic()
                    return None

                self.lm_studio_available = True
                self.lm_studio_checked_at = time.monotonic()
                response_json = await response.json()
                try:
                    return extract_bridge_content(response_json)
                except BridgeContractError as exc:
                    logger.warning(
                        "bridge_response_rejected code=%s model=%s",
                        exc.code,
                        LM_STUDIO_MODEL,
                    )
                    return None
        except asyncio.TimeoutError:
            logger.error(
                "bridge_provider_error code=timeout model=%s",
                LM_STUDIO_MODEL,
            )
        except Exception:
            logger.error(
                "bridge_provider_error code=provider_failure model=%s",
                LM_STUDIO_MODEL,
            )
        self.lm_studio_available = False
        self.lm_studio_checked_at = time.monotonic()
        return None

    async def handle_request(self, reader, writer):
        self.request_count += 1
        request_id = self.request_count

        try:
            # Read header first
            header_data = await reader.readuntil(b"\r\n\r\n")
            if len(header_data) > MAX_HEADER_BYTES:
                await self._send_response(writer, 400, {"error": "Request headers too large"})
                return
            header_text = header_data.decode("utf-8", errors="ignore")
            lines = header_text.split("\r\n")

            if not lines:
                await self._send_response(writer, 400, {"error": "Empty request"})
                return

            request_line = lines[0]
            parts = request_line.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, {"error": "Invalid request"})
                return

            method, path = parts[0], parts[1]
            headers = self._parse_headers(lines[1:])

            # Handle body if POST
            body = None
            if method == "POST":
                try:
                    content_length = int(headers.get("Content-Length", 0) or 0)
                except ValueError:
                    await self._send_response(writer, 400, {"error": "Invalid Content-Length"})
                    return
                if content_length < 0:
                    await self._send_response(writer, 400, {"error": "Invalid Content-Length"})
                    return
                if content_length > MAX_BODY_BYTES:
                    await self._send_response(writer, 413, {"error": "Request body too large"})
                    return
                if content_length > 0:
                    body_data = await reader.readexactly(content_length)
                    try:
                        body = body_data.decode("utf-8")
                    except UnicodeDecodeError:
                        await self._send_response(
                            writer, 400, {"error": "invalid_utf8_body"}
                        )
                        return

            parsed = urlparse(path)
            query = parse_qs(parsed.query)

            if parsed.path == "/api/chat":
                await self._handle_chat(writer, method, query, body)
            elif parsed.path == "/health":
                lm_available = await self._check_lm_studio()
                await self._send_response(
                    writer,
                    200,
                    {
                        "status": "healthy" if lm_available else "degraded",
                        "lm_studio": "connected" if lm_available else "disconnected",
                        "requests": self.request_count,
                        "errors": self.error_count,
                    },
                )
            elif parsed.path == "/":
                await self._send_response(
                    writer,
                    200,
                    {
                        "service": "Hermes Bridge Server",
                        "lm_studio": LM_STUDIO_URL,
                        "endpoints": ["/api/chat", "/health"],
                    },
                )
            else:
                await self._send_response(writer, 404, {"error": "Not found"})

        except asyncio.IncompleteReadError:
            await self._send_response(writer, 400, {"error": "Incomplete request"})
        except asyncio.LimitOverrunError:
            await self._send_response(writer, 400, {"error": "Request headers too large"})
        except Exception:
            self.error_count += 1
            logger.error(
                "bridge_request_failed code=internal_error request=%s",
                request_id,
            )
            await self._send_response(
                writer, 500, {"error": "internal_error"}
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

    def _parse_headers(self, lines):
        headers = {}
        for line in lines:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k] = v
        return headers

    async def _handle_chat(self, writer, method, query, body):
        payload: object = {}
        if method == "POST" and body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                await self._send_response(
                    writer, 400, {"error": "invalid_json_body"}
                )
                return
        else:
            data_param = query.get("data", [""])[0]
            if data_param:
                try:
                    payload = json.loads(unquote(data_param))
                except json.JSONDecodeError:
                    await self._send_response(
                        writer, 400, {"error": "invalid_data_parameter"}
                    )
                    return

        if not isinstance(payload, dict) or not payload:
            await self._send_response(
                writer, 400, {"error": "invalid_payload"}
            )
            return
        allowed_keys = {
            "message",
            "author_name",
            "channel_type",
            "timestamp",
            "is_mention",
            "system_prompt",
            "temperature",
            "max_tokens",
            "context_prompt",
        }
        if not set(payload).issubset(allowed_keys):
            await self._send_response(
                writer, 400, {"error": "invalid_payload"}
            )
            return

        message = payload.get("message")
        author_name = payload.get("author_name", "unknown")
        channel_type = payload.get("channel_type", "DM")
        system_prompt = payload.get("system_prompt")
        temperature = payload.get("temperature")
        max_tokens = payload.get("max_tokens")
        context_prompt = payload.get("context_prompt", "")
        timestamp = payload.get("timestamp")
        is_mention = payload.get("is_mention", True)

        if not isinstance(message, str) or not message:
            await self._send_response(
                writer, 400, {"error": "invalid_message"}
            )
            return
        if (
            not isinstance(author_name, str)
            or len(author_name) > MAX_AUTHOR_NAME_CHARS
        ):
            await self._send_response(
                writer, 400, {"error": "invalid_author_name"}
            )
            return
        if (
            not isinstance(channel_type, str)
            or len(channel_type) > MAX_CHANNEL_TYPE_CHARS
        ):
            await self._send_response(
                writer, 400, {"error": "invalid_channel_type"}
            )
            return
        if system_prompt is not None and not isinstance(system_prompt, str):
            await self._send_response(
                writer, 400, {"error": "invalid_system_prompt"}
            )
            return
        if timestamp is not None and (
            not isinstance(timestamp, str) or len(timestamp) > 64
        ):
            await self._send_response(
                writer, 400, {"error": "invalid_timestamp"}
            )
            return
        if not isinstance(is_mention, bool):
            await self._send_response(
                writer, 400, {"error": "invalid_is_mention"}
            )
            return
        try:
            if _utf8_size(message, code="invalid_message") > MAX_BODY_BYTES:
                raise BridgeContractError("invalid_message")
            if system_prompt is not None:
                _utf8_size(
                    system_prompt,
                    code="invalid_system_prompt",
                )
            if timestamp is not None:
                _utf8_size(timestamp, code="invalid_timestamp")
            selected_temperature = (
                None
                if temperature is None
                else _finite_number(
                    temperature,
                    code="invalid_temperature",
                    minimum=0.0,
                    maximum=2.0,
                )
            )
            selected_max_tokens = (
                None
                if max_tokens is None
                else _bounded_max_tokens(max_tokens)
            )
            build_untrusted_context_data(
                author_name=author_name,
                channel_type=channel_type,
                context_prompt=context_prompt,
            )
        except BridgeContractError as exc:
            await self._send_response(
                writer, 400, {"error": exc.code}
            )
            return

        if message == "health_check":
            lm_available = await self._check_lm_studio()
            lm_status = "connected" if lm_available else "disconnected"
            await self._send_response(
                writer,
                200,
                {
                    "status": "ok" if lm_available else "degraded",
                    "lm_studio": lm_status,
                    "response": f"Bridge healthy (LM Studio: {lm_status})",
                },
            )
            return

        response_text = None
        if await self._check_lm_studio():
            response_text = await self._generate_ai_response(
                message,
                author_name,
                channel_type,
                system_prompt,
                selected_temperature,
                selected_max_tokens,
                context_prompt,
            )

        if response_text is None:
            response_text = generate_local_response(message, author_name)

        await self._send_response(
            writer,
            200,
            {
                "response": response_text,
                "timestamp": datetime.now().isoformat(),
            },
        )

    async def _send_response(self, writer, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        status_text = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Server Error",
        }.get(status_code, "Unknown")

        headers = [
            f"HTTP/1.1 {status_code} {status_text}",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]

        header_bytes = "\r\n".join(headers).encode("utf-8")
        try:
            writer.write(header_bytes + body)
            await writer.drain()
        except Exception:
            logger.error("bridge_response_write code=write_failed")

    async def cleanup(self):
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    print("=" * 60)
    print("  HERMES BRIDGE SERVER FOR DISCORD SELFBOT")
    print("  Mode: LM Studio AI + Local Fallback")
    print("=" * 60)
    print(f"  LM Studio: {LM_STUDIO_URL}")
    print(f"  Model: {LM_STUDIO_MODEL}")
    print("=" * 60)

    server = HermesBridgeServer()

    srv = await asyncio.start_server(server.handle_request, HOST, PORT)

    print(f"\n✅ Bridge server running!")
    print(f"   URL: http://{HOST}:{PORT}/api/chat")
    print(f"   Health: http://{HOST}:{PORT}/health")
    print("=" * 60)
    print("\nPress Ctrl+C to stop\n")

    loop = asyncio.get_running_loop()

    def shutdown():
        logger.info("Shutting down...")
        srv.close()
        asyncio.create_task(server.cleanup())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown complete.")
        sys.exit(0)

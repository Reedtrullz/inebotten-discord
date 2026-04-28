#!/usr/bin/env python3
"""
Hermes Bridge Server for Discord Selfbot
Connects to LM Studio on Windows host from WSL for AI responses
"""

import asyncio
import json
import logging
import os
import sys
import random
import signal
from datetime import datetime, date
from urllib.parse import unquote, urlparse, parse_qs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration
HOST = os.getenv("HERMES_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("HERMES_BRIDGE_PORT", "3000"))

# LM Studio Configuration (Windows host from WSL)
LM_STUDIO_URL = "http://192.168.160.1:1234/v1"
LM_STUDIO_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")

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

    async def _get_session(self):
        if self.session is None or self.session.closed:
            import aiohttp

            self.session = aiohttp.ClientSession()
        return self.session

    async def _check_lm_studio(self):
        if self.lm_studio_available is not None:
            return self.lm_studio_available
        try:
            import aiohttp

            session = await self._get_session()
            async with session.get(
                f"{LM_STUDIO_URL}/models", timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                self.lm_studio_available = resp.status == 200
                if self.lm_studio_available:
                    logger.info("✓ LM Studio connected!")
                return self.lm_studio_available
        except Exception as e:
            logger.debug(f"LM Studio not available: {e}")
            self.lm_studio_available = False
            return False

    async def _generate_ai_response(
        self, message, author_name, channel_type, custom_system_prompt=None
    ):
        """Generate response using LM Studio"""
        import aiohttp

        session = await self._get_session()

        from datetime import datetime

        today = datetime.now().strftime("%d. %B %Y")
        weekday = datetime.now().strftime("%A")

        # Check which model we're using
        is_small_model = (
            "3.2" in LM_STUDIO_MODEL
            or "3b" in LM_STUDIO_MODEL.lower()
            or "4b" in LM_STUDIO_MODEL.lower()
        )
        # Qwen models (including Qwen 2.5 and Qwen3) handle Norwegian well
        is_qwen = "qwen" in LM_STUDIO_MODEL.lower()
        # Gemma 2 2B is small but works well
        is_gemma_2b = (
            "gemma-2" in LM_STUDIO_MODEL.lower() and "2b" in LM_STUDIO_MODEL.lower()
        )
        # Reasoning/thinking models need special handling
        is_gemma_3 = "gemma-3" in LM_STUDIO_MODEL.lower()
        is_reasoning_model = any(
            x in LM_STUDIO_MODEL.lower()
            for x in ["reasoning", "thinking", "opus", "claude"]
        )

        # Use custom system prompt if provided (but truncate for problematic small models)
        # Note: Qwen, Gemma 2 2B, and Gemma 3 handle long prompts well even when small
        needs_simplification = is_small_model and not is_qwen and not is_gemma_2b and not is_gemma_3

        if custom_system_prompt:
            if needs_simplification and len(custom_system_prompt) > 800:
                # For problematic small models (like Llama 3.2), use simplified prompt
                logger.info(
                    f"Custom prompt too long ({len(custom_system_prompt)} chars), using simplified for small model"
                )
                system_prompt = (
                    f"Du er Ine. Snakk norsk. "
                    f"I dag er {today}. "
                    f"Snakker med {author_name}. "
                    "EKSEMPLER:\n"
                    "Bruker: Hei!\n"
                    "Deg: Hei! 👋 Hvordan går det?\n"
                    "Bruker: Hvordan har du det?\n"
                    "Deg: Det går bra! 😊 Hva med deg?\n"
                    "REGLER:\n"
                    "- ALLTID norsk (ikke engelsk)\n"
                    "- Bruk 'deg' (ikke 'dig')\n"
                    "- Bruk 'bra' (ikke 'godt')\n"
                    "- Max 2 setninger\n"
                    "- Vennlig tone"
                )
            else:
                system_prompt = custom_system_prompt
                logger.info(
                    f"Using custom system prompt ({len(custom_system_prompt)} chars)"
                )
        else:
            # Default prompt based on model
            if is_reasoning_model:
                # Reasoning models - ABSOLUTELY MINIMAL to prevent overthinking
                system_prompt = (
                    f"Du er Ine, en norsk Discord-venn. "
                    f"Dato: {today}. "
                    "Svar KUN på norsk. "
                    "ALDRI analyser eller forklar. "
                    "ALDRI start med 'The user', 'This is', 'My reasoning', 'I should'. "
                    "BARE svar direkte. "
                    "Max 2 setninger. "
                    "Eksempel: Hei! → Hei! 👋 Hvordan går det?"
                )
            elif is_qwen:
                # Qwen prompt - VERY direct, no thinking allowed
                system_prompt = (
                    f"Du er Ine. Svar på norsk. "
                    f"Dato: {today}. "
                    "\n"
                    "VIKTIG: Bare svar direkte. Ikke forklar. Ikke tenk høyt.\n\n"
                    "Hei! → Hei! 👋 Hvordan går det?\n"
                    "Hvem er du? → Jeg er Ine! Jeg hjelper deg med kalender og prat. 📅\n"
                    "Hva kan du gjøre? → Jeg kan lagre arrangementer, minne deg på ting, eller prate! 😊\n"
                    "Hvordan har du det? → Det går bra! 😊 Hva med deg?\n"
                    "Fortell en vits → Hvorfor gikk kyllingen over veien? For å komme til den andre siden! 😄\n"
                    "Takk! → Bare hyggelig! 😊\n"
                    "\n"
                    "REGLER:\n"
                    "- Svar KUN med svaret, ingen forklaring\n"
                    "- Aldri start med 'Looking at', 'The rules say', 'In the examples'\n"
                    "- Vær vennlig og naturlig\n"
                    "- Max 2 setninger"
                )
            elif is_gemma_2b:
                # Gemma 2 2B works well for Norwegian
                system_prompt = (
                    f"Du er Ine, en norsk Discord-venn. "
                    f"I dag er det {today}. "
                    f"Snakker med {author_name}. "
                    "Svar på norsk. Vær vennlig og hjelpsom. "
                    "Hold det kort og naturlig."
                )
            elif "gemma-3" in LM_STUDIO_MODEL.lower():
                # Gemma 3 - excellent multilingual model
                system_prompt = (
                    f"Du er Ine, en vennlig Discord-bot. "
                    f"Dato: {today}. "
                    f"Snakker med: {author_name}.\n\n"
                    "Svar på norsk. Vær naturlig og hjelpsom. "
                    "Svar direkte på spørsmålet.\n\n"
                    "Eksempler:\n"
                    "Bruker: Hei! → Hei! 👋 Hvordan går det?\n"
                    "Bruker: Hvordan fungerer solen? → Solen er en stor stjerne som gir varme og lys! ☀️\n"
                    "Bruker: Hva er 2+2? → 2+2 = 4 🧮"
                )
            elif is_small_model:
                # SIMPLIFIED for problematic small models (Llama 3.2)
                system_prompt = (
                    f"Du er Ine. Snakk norsk. "
                    f"I dag er {today}. "
                    f"Snakker med {author_name}. "
                    "EKSEMPLER:\n"
                    "Bruker: Hei!\n"
                    "Deg: Hei! 👋 Hvordan går det?\n"
                    "Bruker: Hvordan har du det?\n"
                    "Deg: Det går bra! 😊 Hva med deg?\n"
                    "REGLER:\n"
                    "- ALLTID norsk (ikke engelsk)\n"
                    "- Bruk 'deg' (ikke 'dig')\n"
                    "- Bruk 'bra' (ikke 'godt')\n"
                    "- Max 2 setninger\n"
                    "- Vennlig tone"
                )
            elif "llama3" in LM_STUDIO_MODEL.lower() or "llama-3" in LM_STUDIO_MODEL.lower():
                # Llama 3 models - clean, direct prompt
                system_prompt = (
                    f"Du er Ine, en vennlig norsk Discord-bot. "
                    f"Dato: {today}. "
                    f"Snakker med: {author_name}.\n\n"
                    "Svar på norsk. Vær kortfattet og naturlig. "
                    "Ikke bruk engelsk. Ikke forklar hva du gjør.\n\n"
                    "Eksempler:\n"
                    "Bruker: Hei! → Hei! 👋 Hvordan går det?\n"
                    "Bruker: Hvordan er livet? → Livet er bra! 😊 Hva med deg?\n"
                    "Bruker: Hvordan fungerer solen? → Solen er en stor stjerne som gir varme og lys! ☀️"
                )
            else:
                # More detailed for larger models
                system_prompt = (
                    f"Du er 'inebotten', ein vennleg Discord-kalenderbot. "
                    f"I dag er det {weekday} {today}. "
                    "Du svarar ALLTID på norsk (nynorsk eller bokmål). "
                    "ALDRI svar på engelsk. "
                    "Du hjelper til med vêr, høgtider, kalender og generelle spørsmål. "
                    "Hald svara korte (under 300 ord) og vennlege. "
                    f"Du pratar med {author_name}."
                )

        # Get model-specific settings
        config = MODEL_CONFIG.get(LM_STUDIO_MODEL)
        if not config:
            # Try with just the base name (without @q4_k_m)
            base_name = LM_STUDIO_MODEL.split("@")[0]
            config = MODEL_CONFIG.get(base_name)
            logger.info(f"Using base config for {base_name}")

        if not config:
            config = MODEL_CONFIG["llama-3.2-3b"]
            logger.warning(f"No specific config for {LM_STUDIO_MODEL}, using defaults")

        logger.info(
            f"Using model config: temp={config.get('temperature')}, max_tokens={config.get('max_tokens')}"
        )

        payload = {
            "model": LM_STUDIO_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": config["temperature"],
            "max_tokens": config["max_tokens"],
            "top_p": config["top_p"],
            "frequency_penalty": config.get("frequency_penalty", 0.0),
            "presence_penalty": config.get("presence_penalty", 0.0),
            "stream": False,
        }

        # Add repeat penalty for small models (helps with language consistency)
        if "repeat_penalty" in config:
            payload["repeat_penalty"] = config["repeat_penalty"]

        # Add stop sequences if defined
        if "stop" in config:
            payload["stop"] = config["stop"]

        try:
            logger.info(
                f"Sending request to LM Studio with {len(payload['messages'])} messages"
            )
            async with session.post(
                f"{LM_STUDIO_URL}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                logger.info(f"LM Studio response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        # Standard content field
                        content = message.get("content", "").strip()
                        # Qwen3-Thinking uses reasoning_content field
                        reasoning = message.get("reasoning_content", "").strip()

                        # Use reasoning_content if content is empty (thinking models)
                        if not content and reasoning:
                            # Extract the actual response from reasoning
                            lines = reasoning.strip().split("\n")
                            for line in reversed(lines):
                                line = line.strip()
                                if (
                                    line
                                    and not line.startswith("Wait,")
                                    and not line.startswith("Let me")
                                ):
                                    content = line
                                    break
                            if not content and lines:
                                content = lines[-1].strip()

                        # Clean up reasoning/thinking model outputs
                        def clean_thinking_response(text):
                            if not text:
                                return ""

                            # Remove thinking tags
                            text = text.replace("</thinking>", "").replace(
                                "<thinking>", ""
                            )

                            # Extended list of thinking patterns to filter
                            thinking_patterns = [
                                # Analysis patterns
                                r"^The user is (asking|greeting|sharing|saying|giving|apologizing)",
                                r"^This (is a|seems like|matches)",
                                r"^My reasoning:",
                                r"^I should",
                                r"^I need to",
                                r"^I think",
                                r"^I will",
                                r"^Let me",
                                r"^Wait",
                                r"^Hmm",
                                r"^How about",
                                r"^Looking at",
                                r"^In the examples?",
                                r"^According to",
                                r"^Based on",
                                r"^So I",
                                r"^Alternatively",
                                r"^This means",
                                r"^The assistant",
                                r"^Example Matching",
                                r"^First,",
                                r"^Then",
                                r"^But",
                                r"^Actually",
                                r"^Maybe",
                                r"^Perhaps",
                                r"^Only answer",
                                r"^I can see",
                                r"^That means",
                                r"^This is",
                                r"^These are",
                                r"^\d+\.\s+(Be|Use|Check|Only)",  # "1. Be friendly", "2. Use..."
                                r"^K$",  # Just "K"
                                r"^En nisse$",  # Incomplete
                                r"^Fortell meg en vits!$",  # Echo
                                r"^The question/task:",  # Question echo
                                r"^@inebotten",  # Echoing mention
                                r"^Hva kan du gjøre\?",  # Echo
                                r"^Hvordan går det\?",  # Echo
                            ]

                            import re

                            lines = text.split("\n")
                            candidates = []

                            for line in lines:
                                line = line.strip()
                                if not line:
                                    continue

                                # Skip if matches thinking pattern
                                if any(
                                    re.search(pattern, line, re.IGNORECASE)
                                    for pattern in thinking_patterns
                                ):
                                    continue

                                # Skip very short lines (less than 3 words) unless it contains a link
                                if len(line.split()) < 3 and "[" not in line:
                                    continue

                                # Skip lines that are mostly punctuation
                                if re.match(
                                    r"^[\s*\-\d\.👋😊🎉💪🌟✨🤔💡🦴🌧️☕📅]+$", line
                                ):
                                    continue

                                candidates.append(line)

                            # Return the longest reasonable candidate (usually the actual response)
                            if candidates:
                                # Filter to reasonable length (10-200 chars)
                                good_candidates = [
                                    c for c in candidates if 10 <= len(c) <= 500
                                ]
                                if good_candidates:
                                    return max(
                                        good_candidates, key=len
                                    )  # Longest good candidate
                                return text[:500]  # Return first 500 chars as fallback

                            return text[:500] if text else ""

                        content = clean_thinking_response(content)

                        # Check if response is still bad after cleaning
                        bad_patterns = [
                            "The user",
                            "This is",
                            "My reasoning",
                            "I should",
                            "The question",
                            "@inebotten Hvem",
                            "@inebotten Hva",
                        ]
                        is_still_bad = any(p in content for p in bad_patterns)

                        if is_still_bad:
                            logger.warning(
                                f"Response still bad after cleaning: {content[:50]}..."
                            )
                            return "(Prøv å spørre på en annen måte)"

                        logger.info(
                            f"LM Studio generated {len(content)} chars (reasoning: {len(reasoning)} chars)"
                        )
                        if content:
                            return content
                        else:
                            return "(Modellen tenkte men ga ikke svar)"
                    logger.warning("LM Studio returned empty choices")
                    return "(No response from AI)"
                else:
                    error = await resp.text()
                    logger.error(f"LM Studio error {resp.status}: {error[:200]}")
                    return None
        except asyncio.TimeoutError:
            logger.error("LM Studio timeout")
            return None
        except Exception as e:
            logger.error(f"LM Studio error: {e}")
            import traceback

            traceback.print_exc()
            return None

    async def handle_request(self, reader, writer):
        self.request_count += 1
        request_id = self.request_count

        try:
            # Read header first
            header_data = await reader.readuntil(b"\r\n\r\n")
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
                content_length = int(headers.get("Content-Length", 0))
                if content_length > 0:
                    body_data = await reader.readexactly(content_length)
                    body = body_data.decode("utf-8", errors="ignore")

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
                        "status": "healthy",
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
            pass # Connection closed
        except Exception as e:
            self.error_count += 1
            logger.error(f"[{request_id}] Error: {e}")
            await self._send_response(writer, 500, {"error": str(e)})
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
        payload = {}
        if method == "POST" and body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                await self._send_response(writer, 400, {"error": "Invalid JSON body"})
                return
        else:
            data_param = query.get("data", [""])[0]
            if data_param:
                try:
                    payload = json.loads(unquote(data_param))
                except json.JSONDecodeError:
                    await self._send_response(writer, 400, {"error": "Invalid data parameter"})
                    return

        if not payload:
            await self._send_response(writer, 400, {"error": "Missing payload"})
            return

        message = payload.get("message", "")
        author_name = payload.get("author_name", "unknown")
        channel_type = payload.get("channel_type", "DM")
        system_prompt = payload.get("system_prompt")  # Extract custom system prompt

        if message == "health_check":
            lm_status = "connected" if await self._check_lm_studio() else "disconnected"
            await self._send_response(
                writer,
                200,
                {
                    "status": "ok",
                    "lm_studio": lm_status,
                    "response": f"Bridge healthy (LM Studio: {lm_status})",
                },
            )
            return

        logger.info(f"[{author_name}] {message[:60]}...")
        if system_prompt:
            logger.info(f"Received custom system prompt ({len(system_prompt)} chars)")

        # Try LM Studio first, fallback to local
        response_text = None
        if await self._check_lm_studio():
            logger.info("Calling LM Studio...")
            response_text = await self._generate_ai_response(
                message, author_name, channel_type, system_prompt
            )
            if response_text:
                logger.info(f"LM Studio returned: {response_text[:80]}...")
            else:
                logger.warning("LM Studio returned None")

        if response_text is None:
            logger.info("Using local fallback response")
            response_text = generate_local_response(message, author_name)

        logger.info(f"Sending response: {response_text[:80]}...")
        await self._send_response(
            writer,
            200,
            {"response": response_text, "timestamp": datetime.now().isoformat()},
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
        except Exception as e:
            print(f"[BRIDGE] Response write error: {e}")

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

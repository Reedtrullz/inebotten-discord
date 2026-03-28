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
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
HOST = os.getenv('HERMES_BRIDGE_HOST', '127.0.0.1')
PORT = int(os.getenv('HERMES_BRIDGE_PORT', '3000'))

# LM Studio Configuration (Windows host from WSL)
LM_STUDIO_URL = "http://192.168.160.1:1234/v1"
LM_STUDIO_MODEL = "llama-3.2-3b"  # Now using Llama 3.2 3B for better Norwegian

# Model-specific settings
MODEL_CONFIG = {
    "llama-3.2-3b": {
        "temperature": 0.4,  # Very low for maximum consistency
        "max_tokens": 100,   # Very short responses
        "top_p": 0.8,        # Focused sampling
        "frequency_penalty": 0.3,  # Strong penalty to avoid English mixing
        "presence_penalty": 0.2,
        "repeat_penalty": 1.3,  # Penalize repetition
    },
    "gemma-3-4b": {
        "temperature": 0.8,
        "max_tokens": 500,
        "top_p": 0.95,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
    }
}

# Fun response templates (fallback when LM Studio unavailable)
RESPONSES = {
    "greeting": [
        "Hey there! 🌟 I'm inebotten, your friendly calendar bot!",
        "Hello! 📅 Ready to help with your day!",
        "Hi there! ☀️ What can I do for you today?",
        "Hey! 🎉 I'm here and ready to assist!",
    ],
    "weather": [
        "🌤️ It's looking nice today! Around 68°F with some sunshine.",
        "☀️ Clear skies and pleasant at about 72°F!",
        "🌤️ Partly cloudy, perfect day at 70°F!",
    ],
    "calendar": [
        "📅 Today is {date}. No major events on the calendar!",
        "📆 It's {date}. Your schedule looks clear!",
        "🗓️ {date} - looks like a free day!",
    ],
    "time": [
        "🕐 It's currently {time}!",
        "⏰ Time check: {time}",
    ],
    "help": [
        "🤖 I can help with:\n"
        "• Calendar & date info\n"
        "• Weather updates\n"
        "• General questions\n"
        "• Fun facts!\n"
        "Just ask me anything!",
    ],
    "fun_fact": [
        "💡 Did you know? The shortest war in history was 38 minutes!",
        "💡 Fun fact: Honey never spoils!",
        "💡 Did you know? Octopuses have three hearts!",
        "💡 Fun fact: The Eiffel Tower can grow taller in summer!",
    ],
    "default": [
        "🤔 Interesting question! Let me think... Actually, I'm running in local mode right now, but I can help with basic calendar and weather info!",
        "😅 I'm in fallback mode without AI access. I can tell you the date, time, or weather basics though!",
        "📝 I'd love to help more! For now, I can provide calendar info and fun facts.",
    ]
}


def generate_local_response(message, author_name):
    """Generate a response based on the message content (fallback)"""
    msg_lower = message.lower()
    today = date.today().strftime("%A, %B %d, %Y")
    now = datetime.now().strftime("%I:%M %p")

    if any(word in msg_lower for word in ['hello', 'hi', 'hey', 'greetings']):
        return random.choice(RESPONSES["greeting"])
    if any(word in msg_lower for word in ['weather', 'temp', 'temperature', 'forecast']):
        return random.choice(RESPONSES["weather"])
    if any(word in msg_lower for word in ['date', 'day', 'calendar', 'today', 'schedule']):
        return random.choice(RESPONSES["calendar"]).format(date=today)
    if any(word in msg_lower for word in ['time', 'clock', 'hour']):
        return random.choice(RESPONSES["time"]).format(time=now)
    if any(word in msg_lower for word in ['help', 'what can you do', 'commands']):
        return random.choice(RESPONSES["help"])
    if any(word in msg_lower for word in ['fact', 'trivia', 'tell me something']):
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
            async with session.get(f"{LM_STUDIO_URL}/models", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                self.lm_studio_available = (resp.status == 200)
                if self.lm_studio_available:
                    logger.info("✓ LM Studio connected!")
                return self.lm_studio_available
        except Exception as e:
            logger.debug(f"LM Studio not available: {e}")
            self.lm_studio_available = False
            return False

    async def _generate_ai_response(self, message, author_name, channel_type, custom_system_prompt=None):
        """Generate response using LM Studio"""
        import aiohttp

        session = await self._get_session()

        from datetime import datetime
        today = datetime.now().strftime("%d. %B %Y")
        weekday = datetime.now().strftime("%A")
        
        # Check which model we're using
        is_small_model = "3.2" in LM_STUDIO_MODEL or "3b" in LM_STUDIO_MODEL.lower()
        
        # Use custom system prompt if provided (but truncate for small models)
        if custom_system_prompt:
            if is_small_model and len(custom_system_prompt) > 800:
                # For small models, use simplified prompt
                logger.info(f"Custom prompt too long ({len(custom_system_prompt)} chars), using simplified for small model")
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
                logger.info(f"Using custom system prompt ({len(custom_system_prompt)} chars)")
        else:
            # Default prompt based on model size
            if is_small_model:
                # SIMPLIFIED for Llama 3.2 3B - Ultra clear Norwegian
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
        config = MODEL_CONFIG.get(LM_STUDIO_MODEL, MODEL_CONFIG["llama-3.2-3b"])
        
        payload = {
            "model": LM_STUDIO_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": config["temperature"],
            "max_tokens": config["max_tokens"],
            "top_p": config["top_p"],
            "frequency_penalty": config.get("frequency_penalty", 0.0),
            "presence_penalty": config.get("presence_penalty", 0.0),
            "stream": False
        }
        
        # Add repeat penalty for small models (helps with language consistency)
        if "repeat_penalty" in config:
            payload["repeat_penalty"] = config["repeat_penalty"]

        try:
            logger.info(f"Sending request to LM Studio with {len(payload['messages'])} messages")
            async with session.post(
                f"{LM_STUDIO_URL}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                logger.info(f"LM Studio response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get('choices', [])
                    if choices:
                        content = choices[0].get('message', {}).get('content', '').strip()
                        logger.info(f"LM Studio generated {len(content)} chars")
                        return content
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
            data = await reader.read(8192)
            request_text = data.decode('utf-8', errors='ignore')
            lines = request_text.split('\r\n')

            if not lines:
                await self._send_response(writer, 400, {"error": "Empty request"})
                return

            request_line = lines[0]
            parts = request_line.split(' ')
            if len(parts) < 2:
                await self._send_response(writer, 400, {"error": "Invalid request"})
                return

            method, path = parts[0], parts[1]

            if method != 'GET':
                await self._send_response(writer, 405, {"error": "Method not allowed"})
                return

            parsed = urlparse(path)
            query = parse_qs(parsed.query)

            if parsed.path == '/api/chat':
                await self._handle_chat(writer, query)
            elif parsed.path == '/health':
                lm_available = await self._check_lm_studio()
                await self._send_response(writer, 200, {
                    "status": "healthy",
                    "lm_studio": "connected" if lm_available else "disconnected",
                    "requests": self.request_count,
                    "errors": self.error_count
                })
            elif parsed.path == '/':
                await self._send_response(writer, 200, {
                    "service": "Hermes Bridge Server",
                    "lm_studio": LM_STUDIO_URL,
                    "endpoints": ["/api/chat", "/health"]
                })
            else:
                await self._send_response(writer, 404, {"error": "Not found"})

        except Exception as e:
            self.error_count += 1
            logger.error(f"[{request_id}] Error: {e}")
            await self._send_response(writer, 500, {"error": str(e)})
        finally:
            try:
                await writer.drain()
                writer.close()
            except:
                pass

    async def _handle_chat(self, writer, query):
        data_param = query.get('data', [''])[0]

        if not data_param:
            await self._send_response(writer, 400, {"error": "Missing 'data' parameter"})
            return

        try:
            payload = json.loads(unquote(data_param))
        except json.JSONDecodeError as e:
            await self._send_response(writer, 400, {"error": f"Invalid JSON: {e}"})
            return

        message = payload.get('message', '')
        author_name = payload.get('author_name', 'unknown')
        channel_type = payload.get('channel_type', 'DM')
        system_prompt = payload.get('system_prompt')  # Extract custom system prompt

        if message == 'health_check':
            lm_status = "connected" if await self._check_lm_studio() else "disconnected"
            await self._send_response(writer, 200, {
                "status": "ok",
                "lm_studio": lm_status,
                "response": f"Bridge healthy (LM Studio: {lm_status})"
            })
            return

        logger.info(f"[{author_name}] {message[:60]}...")
        if system_prompt:
            logger.info(f"Received custom system prompt ({len(system_prompt)} chars)")

        # Try LM Studio first, fallback to local
        response_text = None
        if await self._check_lm_studio():
            logger.info("Calling LM Studio...")
            response_text = await self._generate_ai_response(message, author_name, channel_type, system_prompt)
            if response_text:
                logger.info(f"LM Studio returned: {response_text[:80]}...")
            else:
                logger.warning("LM Studio returned None")

        if response_text is None:
            logger.info("Using local fallback response")
            response_text = generate_local_response(message, author_name)

        logger.info(f"Sending response: {response_text[:80]}...")
        await self._send_response(writer, 200, {
            "response": response_text,
            "timestamp": datetime.now().isoformat()
        })

    async def _send_response(self, writer, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        status_text = {200: 'OK', 400: 'Bad Request', 404: 'Not Found',
                       405: 'Method Not Allowed', 500: 'Server Error'}.get(status_code, 'Unknown')

        headers = [
            f'HTTP/1.1 {status_code} {status_text}',
            'Content-Type: application/json; charset=utf-8',
            f'Content-Length: {len(body)}',
            'Connection: close',
            '', ''
        ]

        header_bytes = '\r\n'.join(headers).encode('utf-8')
        try:
            writer.write(header_bytes + body)
            await writer.drain()
        except:
            pass

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

    loop = asyncio.get_event_loop()

    def shutdown():
        logger.info("Shutting down...")
        srv.close()
        asyncio.create_task(server.cleanup())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    async with srv:
        await srv.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown complete.")
        sys.exit(0)

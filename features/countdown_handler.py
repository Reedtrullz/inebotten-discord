#!/usr/bin/env python3
"""CountdownHandler - Countdown to dates"""


class CountdownHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.countdown = monitor.countdown
        self.loc = monitor.loc

    async def handle_countdown(self, message, countdown_result):
        try:
            lang = self.monitor.loc.current_lang
            response_text = self.countdown.format_countdown(countdown_result, lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Countdown error: {e}")

#!/usr/bin/env python3
"""UtilityHandler - Calculator, crypto prices, URL shortener"""


class UtilityHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.calculator = monitor.calculator
        self.crypto = monitor.crypto
        self.url_shortener = monitor.url_shortener
        self.loc = monitor.loc

    async def handle_calculator(self, message, calc_cmd):
        try:
            lang = calc_cmd.get("lang", self.monitor.loc.current_lang)
            result = self.calculator.calculate(calc_cmd["expression"])
            response_text = self.calculator.format_result(result, lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calculator error: {e}")

    async def handle_price(self, message, price_cmd):
        try:
            lang = price_cmd.get("lang", self.monitor.loc.current_lang)
            value = await self.crypto.get_price(
                price_cmd["symbol"], price_cmd.get("currency", "USD")
            )
            response_text = self.crypto.format_price(price_cmd["symbol"], value, lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Price error: {e}")

    async def handle_shorten(self, message, shorten_cmd):
        try:
            lang = shorten_cmd.get("lang", self.monitor.loc.current_lang)
            short_url = await self.url_shortener.shorten_url(shorten_cmd["url"])
            response_text = self.loc.t("url_shortened", lang).format(url=short_url)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Shorten error: {e}")

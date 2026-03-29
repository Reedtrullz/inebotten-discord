#!/usr/bin/env python3
"""Aurora Handler - Nordlys forecast handler"""

import discord


class AuroraHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.aurora = monitor.aurora
        self.loc = monitor.loc

    async def handle_aurora(self, message):
        try:
            forecast = await self.aurora.get_forecast()

            if forecast:
                response_text = self.aurora.format_forecast(forecast)
            else:
                response_text = (
                    "Kunne ikke hente nordlysvarsel akkurat nå. Prøv igjen senere! 🌌"
                )

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error handling aurora command: {e}")

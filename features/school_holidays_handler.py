#!/usr/bin/env python3
import discord


class SchoolHolidaysHandler:
    def __init__(self, monitor):
        self.monitor = monitor

    async def handle_school_holidays(self, message):
        try:
            from features.school_holidays import (
                format_holidays_list,
                get_fylke_from_location,
            )

            content_lower = message.content.lower()
            fylke = get_fylke_from_location(content_lower)
            lang = self.monitor.loc.current_lang

            response_text = format_holidays_list(fylke, days=90, lang=lang)

            if not fylke:
                if lang == "no":
                    response_text += '\n\n💡 *Tips: Nevn byen din for å se ferier i ditt fylke (f.eks. "skoleferie Tromsø")*'
                else:
                    response_text += '\n\n💡 *Tip: Mention your city to see holidays in your county (e.g. "school holidays Tromsø")*'

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error handling school holidays: {e}")

import discord


class DailyDigestHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.daily_digest = monitor.daily_digest
        self.loc = monitor.loc
        self.rate_limiter = monitor.rate_limiter
        self.response_count = monitor.response_count

    async def handle_daily_digest(self, message):
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            lang = self.loc.current_lang

            response_text = self.daily_digest.generate_digest(guild_id, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[DAILY_DIGEST_HANDLER] Error handling daily digest: {e}")

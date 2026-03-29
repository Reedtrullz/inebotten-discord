import discord


class HelpHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.loc = monitor.loc
        self.calendar = monitor.calendar
        self.rate_limiter = monitor.rate_limiter
        self.response_count = monitor.response_count

    async def handle_help(self, message):
        try:
            lang = self.loc.current_lang

            gcal_status = ""
            if self.calendar.gcal_enabled:
                gcal_status = "✅ Synkronisert med Google Calendar"

            lines = [
                self.loc.t("help_title", lang),
                "",
                self.loc.t("help_events", lang),
            ]

            if gcal_status:
                lines.extend(["", gcal_status])

            lines.extend(
                [
                    "",
                    self.loc.t("help_reminders", lang),
                    "",
                    self.loc.t("help_fun", lang),
                    self.loc.t("help_footer_tip", lang),
                ]
            )

            response_text = "\n".join(lines)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1

        except Exception as e:
            print(f"[HELP_HANDLER] Error handling help command: {e}")

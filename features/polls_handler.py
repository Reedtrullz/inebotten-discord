#!/usr/bin/env python3
"""PollsHandler - Poll creation and voting"""


class PollsHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.poll = monitor.poll
        self.loc = monitor.loc

    async def handle_poll(self, message, poll_cmd):
        try:
            lang = poll_cmd.get("lang", self.monitor.loc.current_lang)
            guild_id = message.guild.id if message.guild else message.channel.id
            poll_msg = self.poll.create_poll(guild_id, poll_cmd["options"])
            response_text = self.poll.format_poll_created(poll_msg, lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Poll error: {e}")

    async def handle_vote(self, message, vote):
        try:
            lang = self.monitor.loc.current_lang
            guild_id = message.guild.id if message.guild else message.channel.id
            poll_msg = self.poll.add_vote(
                guild_id, vote["poll_id"], vote["option_index"], message.author.id
            )
            if poll_msg:
                response_text = self.loc.t("vote_registered", lang)
            else:
                response_text = self.loc.t("vote_failed", lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Vote error: {e}")

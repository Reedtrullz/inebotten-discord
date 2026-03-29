#!/usr/bin/env python3
"""WatchlistHandler - Handler for watchlist features"""

import discord


class WatchlistHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.watchlist = monitor.watchlist
        self.loc = monitor.loc

    async def handle_watchlist(self, message, watchlist_cmd):
        try:
            lang = watchlist_cmd.get("lang", self.monitor.loc.current_lang)

            if watchlist_cmd["action"] == "suggest":
                suggestion = self.watchlist.get_random_suggestion(
                    watchlist_cmd.get("type"), watchlist_cmd.get("genre")
                )
                if suggestion:
                    response_text = self.watchlist.format_suggestion(suggestion, lang)
                else:
                    response_text = self.loc.t("no_suggestions", lang)

            elif watchlist_cmd["action"] == "status":
                response_text = self.watchlist.format_watchlist_status(lang)

            elif watchlist_cmd["action"] == "add":
                content_lower = message.content.lower()
                title = None

                title_patterns = [
                    "legg til ",
                    "add to watchlist ",
                    "husk å se ",
                ]
                for pattern in title_patterns:
                    if pattern in content_lower:
                        idx = content_lower.index(pattern) + len(pattern)
                        title = message.content[idx:].strip().strip('"').strip("'")
                        break

                if title:
                    content_type = (
                        "series"
                        if any(
                            word in content_lower
                            for word in ["serie", "series", "tv show"]
                        )
                        else "movie"
                    )
                    self.watchlist.add_from_discord_message(title, content_type)
                    if lang == "no":
                        response_text = f"✅ Lagt til **{title}** til watchlista!"
                    else:
                        response_text = f"✅ Added **{title}** to watchlist!"
                else:
                    response_text = self.loc.t("watchlist_help", lang)

            else:
                response_text = self.loc.t("watchlist_help", lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling watchlist: {e}")

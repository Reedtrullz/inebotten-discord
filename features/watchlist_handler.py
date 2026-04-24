#!/usr/bin/env python3
"""
WatchlistHandler - Handles watchlist commands for the selfbot.

Commands:
- Get suggestions for movies/series
- Check watchlist status
- Add items to watchlist
"""

from typing import Dict, Any

from features.base_handler import BaseHandler


class WatchlistHandler(BaseHandler):
    """Handler for watchlist commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.watchlist = monitor.watchlist

    async def handle_watchlist(self, message, watchlist_cmd: Dict[str, Any]) -> None:
        """
        Handle watchlist commands.

        Args:
            message: The Discord message
            watchlist_cmd: Parsed command with 'action' and optional filters
        """
        try:
            lang = watchlist_cmd.get("lang", self.loc.current_lang)
            guild_id = self.get_guild_id(message)

            if watchlist_cmd["action"] == "suggest":
                suggestion = self.watchlist.get_random_suggestion(
                    watchlist_cmd.get("type"),
                    watchlist_cmd.get("genre"),
                    guild_id=guild_id,
                )
                if suggestion:
                    response_text = self.watchlist.format_suggestion(suggestion, lang)
                else:
                    response_text = self.loc.t("no_suggestions", lang)

            elif watchlist_cmd["action"] == "status":
                response_text = self.watchlist.format_watchlist_status(
                    lang,
                    guild_id=guild_id,
                )

            elif watchlist_cmd["action"] == "add":
                response_text = await self._handle_add(message, lang)

            else:
                response_text = self.loc.t("watchlist_help", lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling watchlist: {e}")

    async def _handle_add(self, message, lang: str) -> str:
        """
        Handle adding an item to the watchlist.

        Args:
            message: The Discord message
            lang: Language code

        Returns:
            Response text
        """
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
            self.watchlist.add_from_discord_message(
                title,
                content_type,
                guild_id=self.get_guild_id(message),
            )
            if lang == "no":
                return f"✅ Lagt til **{title}** til watchlista!"
            else:
                return f"✅ Added **{title}** to watchlist!"

        return self.loc.t("watchlist_help", lang)

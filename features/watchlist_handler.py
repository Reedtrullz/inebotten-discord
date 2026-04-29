#!/usr/bin/env python3
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnusedCallResult=false, reportAny=false, reportDeprecated=false, reportExplicitAny=false, reportPrivateUsage=false, reportUnknownLambdaType=false, reportImplicitOverride=false, reportOptionalSubscript=false, reportUninitializedInstanceVariable=false
"""
WatchlistHandler - Handles watchlist commands for the selfbot.

Commands:
- Get suggestions for movies/series
- Check watchlist status
- Add items to watchlist
"""

import re
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

            elif watchlist_cmd["action"] == "remove":
                response_text = await self.handle_watchlist_remove(message, watchlist_cmd)

            elif watchlist_cmd["action"] == "edit":
                response_text = await self.handle_watchlist_edit(message, watchlist_cmd)

            else:
                response_text = self.loc.t("watchlist_help", lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling watchlist: {e}")

    async def handle_watchlist_remove(self, message, payload) -> str:
        lang = payload.get("lang", self.loc.current_lang)
        guild_id = self.get_guild_id(message)
        index = payload.get("index")

        if index is None:
            index_match = re.search(r'\b(\d+)\b', message.content)
            if index_match:
                index = int(index_match.group(1))

        if index is None:
            return self.loc.t("watchlist_help", lang)

        try:
            item = self.watchlist.remove_from_watchlist(index, guild_id=guild_id)
        except ValueError:
            return "❌ Fant ikke noe med det nummeret." if lang == "no" else "❌ Could not find an item with that number."

        if item:
            title = item["title"]
            return f"✅ Fjernet **{title}** fra watchlista!" if lang == "no" else f"✅ Removed **{title}** from watchlist!"
        return "❌ Fant ikke noe med det nummeret." if lang == "no" else "❌ Could not find an item with that number."

    async def handle_watchlist_edit(self, message, payload) -> str:
        import re as _re
        lang = payload.get("lang", self.loc.current_lang)
        guild_id = self.get_guild_id(message)
        index = payload.get("index")

        if index is None:
            index_match = _re.search(r'\b(\d+)\b', message.content)
            if index_match:
                index = int(index_match.group(1))

        if index is None:
            return self.loc.t("watchlist_help", lang)

        content_lower = message.content.lower()
        remainder = message.content
        for prefix in ["endre watchlist", "rediger watchlist"]:
            if prefix in content_lower:
                idx = content_lower.index(prefix) + len(prefix)
                remainder = message.content[idx:].strip()
                break

        remainder = _re.sub(r'^\d+\s*', '', remainder).strip()
        if not remainder:
            return self.loc.t("watchlist_help", lang)

        title = remainder
        genre = None
        comment = None
        content_type = None

        genre_match = _re.search(r'(?:genre|sjanger)[=: ]\s*([^,;]+)', content_lower)
        if genre_match:
            genre = genre_match.group(1).strip()
            title = _re.sub(r'(?:genre|sjanger)[=: ]\s*[^,;]+', '', title, flags=_re.IGNORECASE).strip(',; ')

        comment_match = _re.search(r'(?:comment|kommentar)[=: ]\s*([^,;]+)', content_lower)
        if comment_match:
            comment = comment_match.group(1).strip()
            title = _re.sub(r'(?:comment|kommentar)[=: ]\s*[^,;]+', '', title, flags=_re.IGNORECASE).strip(',; ')

        type_match = _re.search(r'\btype[=: ]\s*(movie|series|film|serie)\b', content_lower)
        if type_match:
            t = type_match.group(1).strip().lower()
            content_type = "movie" if t in ("movie", "film") else "series"
            title = _re.sub(r'\btype[=: ]\s*(?:movie|series|film|serie)\b', '', title, flags=_re.IGNORECASE).strip(',; ')

        title = title.strip() if title else None

        item = self.watchlist.edit_watchlist_entry(
            index, title=title, type=content_type, genre=genre, comment=comment, guild_id=guild_id
        )
        if item:
            return f"✅ Endret **{item['title']}**!" if lang == "no" else f"✅ Updated **{item['title']}**!"
        return "❌ Fant ikke noe med det nummeret." if lang == "no" else "❌ Could not find an item with that number."

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

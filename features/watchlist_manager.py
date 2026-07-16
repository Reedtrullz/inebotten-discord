#!/usr/bin/env python3
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnusedCallResult=false, reportAny=false, reportDeprecated=false, reportExplicitAny=false, reportPrivateUsage=false, reportUnknownLambdaType=false, reportImplicitOverride=false, reportOptionalSubscript=false, reportUninitializedInstanceVariable=false, reportArgumentType=false, reportAttributeAccessIssue=false
"""
Watchlist Manager for Inebotten
Manages movie and series recommendations from Discord channels
"""

import asyncio
import copy
import json
import random
import re
from datetime import datetime
from pathlib import Path

from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator, WATCHLIST_STORE_SCOPE
from utils.json_storage import hermes_discord_data_path, write_json_atomic


_UNSET = object()


class WatchlistManager:
    """
    Manages watchlists for movies and series
    Can import from Discord channels or store locally
    """

    def __init__(
        self,
        storage_path=None,
        *,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        if storage_path is None:
            storage_path = hermes_discord_data_path("watchlist.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.watchlist = self._load_watchlist()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()

        # Default starter recommendations if no watchlist exists
        self.default_movies = [
            {"title": "Inception", "type": "movie", "genre": "Sci-Fi", "year": 2010},
            {
                "title": "The Grand Budapest Hotel",
                "type": "movie",
                "genre": "Comedy",
                "year": 2014,
            },
            {"title": "Parasitt", "type": "movie", "genre": "Thriller", "year": 2019},
            {"title": "Interstellar", "type": "movie", "genre": "Sci-Fi", "year": 2014},
            {
                "title": "The Dark Knight",
                "type": "movie",
                "genre": "Action",
                "year": 2008,
            },
        ]

        self.default_series = [
            {
                "title": "The Office (US)",
                "type": "series",
                "genre": "Comedy",
                "episodes": "9 sesonger",
            },
            {
                "title": "Breaking Bad",
                "type": "series",
                "genre": "Drama",
                "episodes": "5 sesonger",
            },
            {
                "title": "Dark",
                "type": "series",
                "genre": "Sci-Fi/Thriller",
                "episodes": "3 sesonger",
            },
            {
                "title": "Brooklyn Nine-Nine",
                "type": "series",
                "genre": "Comedy",
                "episodes": "8 sesonger",
            },
            {
                "title": "Stranger Things",
                "type": "series",
                "genre": "Sci-Fi/Horror",
                "episodes": "4 sesonger",
            },
        ]

    def _load_watchlist(self):
        """Load watchlist from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FEATURES] Watchlist load error: {e}")
        return {"movies": [], "series": []}

    def _empty_watchlist(self):
        """Create an empty watchlist bucket."""
        return {"movies": [], "series": []}

    def _get_scope(self, guild_id=None):
        """
        Read a watchlist bucket without creating missing storage state.
        Without guild_id, keep using the legacy global bucket for compatibility.
        """
        if guild_id is None:
            bucket = self.watchlist
        else:
            scopes = self.watchlist.get("scopes", {})
            bucket = (
                scopes.get(str(guild_id), {})
                if isinstance(scopes, dict)
                else {}
            )

        if not isinstance(bucket, dict):
            return self._empty_watchlist()
        movies = bucket.get("movies", [])
        series = bucket.get("series", [])
        return {
            "movies": movies if isinstance(movies, list) else [],
            "series": series if isinstance(series, list) else [],
        }

    def _save_watchlist(self, candidate):
        """Persist a detached complete-root candidate."""
        write_json_atomic(self.storage_path, candidate)

    @staticmethod
    def _require_offline_projection():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError("use_async_result_api")

    @staticmethod
    def _candidate_scope(candidate, guild_id=None):
        if guild_id is None:
            candidate.setdefault("movies", [])
            candidate.setdefault("series", [])
            return candidate
        scopes = candidate.setdefault("scopes", {})
        return scopes.setdefault(
            str(guild_id),
            {"movies": [], "series": []},
        )

    async def _commit_candidate(self, candidate):
        writer = asyncio.create_task(
            asyncio.to_thread(self._save_watchlist, candidate)
        )
        current = asyncio.current_task()
        outer_cancelled = False
        while True:
            try:
                await asyncio.shield(writer)
                break
            except asyncio.CancelledError:
                cancellation_requests = current.cancelling() if current else 0
                if cancellation_requests:
                    outer_cancelled = True
                    for _ in range(cancellation_requests):
                        current.uncancel()
                    continue
                raise ManagerMutationCancelled(
                    "commit_state_unknown",
                    mutated=False,
                    retryable=False,
                    commit_unknown=True,
                )
            except Exception:
                break

        if writer.cancelled():
            raise ManagerMutationCancelled(
                "commit_state_unknown",
                mutated=False,
                retryable=False,
                commit_unknown=True,
            )
        try:
            writer.result()
        except Exception as exc:
            if outer_cancelled:
                raise ManagerMutationCancelled(
                    "storage_write_failed",
                    mutated=False,
                    retryable=True,
                ) from exc
            raise ManagerMutationError(
                "storage_write_failed",
                mutated=False,
            ) from exc

        self.watchlist = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled",
                mutated=True,
                retryable=False,
            )

    async def add_watchlist_result(
        self,
        title,
        content_type="movie",
        guild_id=None,
        **kwargs,
    ):
        """Add one item and publish only after the complete root is durable."""
        async with self.mutation_coordinator.hold(WATCHLIST_STORE_SCOPE):
            candidate = copy.deepcopy(self.watchlist)
            bucket = self._candidate_scope(candidate, guild_id)
            item = {
                "title": title,
                "type": content_type,
                "added_at": datetime.now().isoformat(),
                "watched": False,
                "completed": False,
                **kwargs,
            }
            target = "movies" if content_type == "movie" else "series"
            bucket[target].append(item)
            await self._commit_candidate(candidate)
            return True

    def add_from_discord_message(self, title, content_type="movie", guild_id=None, **kwargs):
        """
        Add a movie/series from a Discord message

        Args:
            title: Movie/series title
            content_type: 'movie' or 'series'
            guild_id: Guild/channel scope. DMs and group DMs should pass channel ID.
            **kwargs: Extra info like genre, year, platform, etc.
        """
        self._require_offline_projection()
        return asyncio.run(
            self.add_watchlist_result(
                title,
                content_type=content_type,
                guild_id=guild_id,
                **kwargs,
            )
        )

    def get_random_suggestion(self, content_type=None, genre=None, guild_id=None):
        """
        Get a random suggestion

        Args:
            content_type: 'movie', 'series', or None for both
            genre: Optional genre filter
            guild_id: Optional guild/channel scope
        """
        bucket = self._get_scope(guild_id)
        candidates = []

        # Add from watchlist
        if content_type in (None, "movie"):
            candidates.extend(
                [m for m in bucket["movies"] if not m.get("watched", False)]
            )
        if content_type in (None, "series"):
            candidates.extend(
                [s for s in bucket["series"] if not s.get("watched", False)]
            )

        # Add defaults if watchlist is empty
        if not candidates:
            if content_type == "movie" or content_type is None:
                candidates.extend(self.default_movies)
            if content_type == "series" or content_type is None:
                candidates.extend(self.default_series)

        # Filter by genre if specified
        if genre:
            candidates = [
                c for c in candidates if genre.lower() in c.get("genre", "").lower()
            ]

        if not candidates:
            return None

        return random.choice(candidates)

    def get_watchlist(self, guild_id=None):
        """Return all watchlist items for a scope."""
        bucket = self._get_scope(guild_id)
        return bucket["movies"] + bucket["series"]

    def get_watchlist_summary(self, guild_id=None):
        """Get summary of watchlist"""
        bucket = self._get_scope(guild_id)
        unwatched_movies = [
            m for m in bucket["movies"] if not m.get("watched", False)
        ]
        unwatched_series = [
            s for s in bucket["series"] if not s.get("watched", False)
        ]

        return {
            "movies_total": len(bucket["movies"]),
            "movies_unwatched": len(unwatched_movies),
            "series_total": len(bucket["series"]),
            "series_unwatched": len(unwatched_series),
        }

    async def mark_as_watched_result(self, title, guild_id=None):
        """Mark an item through the same transactional write boundary."""
        async with self.mutation_coordinator.hold(WATCHLIST_STORE_SCOPE):
            candidate = copy.deepcopy(self.watchlist)
            bucket = self._candidate_scope(candidate, guild_id)
            for item in bucket["movies"] + bucket["series"]:
                if item["title"].lower() == title.lower():
                    item["watched"] = True
                    item["completed"] = True
                    item["watched_at"] = datetime.now().isoformat()
                    await self._commit_candidate(candidate)
                    return True
            return False

    def mark_as_watched(self, title, guild_id=None):
        """Offline compatibility projection for marking an item watched."""
        self._require_offline_projection()
        return asyncio.run(self.mark_as_watched_result(title, guild_id))

    async def remove_watchlist_result(self, index, guild_id=None):
        async with self.mutation_coordinator.hold(WATCHLIST_STORE_SCOPE):
            candidate = copy.deepcopy(self.watchlist)
            bucket = self._candidate_scope(candidate, guild_id)
            movie_count = len(bucket["movies"])
            total = movie_count + len(bucket["series"])
            if not 1 <= index <= total:
                raise ValueError(f"Invalid watchlist index: {index}")
            if index <= movie_count:
                item = bucket["movies"].pop(index - 1)
            else:
                item = bucket["series"].pop(index - movie_count - 1)
            await self._commit_candidate(candidate)
            return item

    def remove_from_watchlist(self, index, guild_id=None):
        """
        Remove an item from the watchlist by 1-based index.

        Args:
            index: 1-based index of the item to remove
            guild_id: Optional guild/channel scope

        Returns:
            The removed item dict

        Raises:
            ValueError: If index is invalid
        """
        self._require_offline_projection()
        return asyncio.run(self.remove_watchlist_result(index, guild_id))

    async def edit_watchlist_result(
        self,
        index,
        title=_UNSET,
        type=_UNSET,
        genre=_UNSET,
        comment=_UNSET,
        guild_id=None,
    ):
        async with self.mutation_coordinator.hold(WATCHLIST_STORE_SCOPE):
            candidate = copy.deepcopy(self.watchlist)
            bucket = self._candidate_scope(candidate, guild_id)
            movie_count = len(bucket["movies"])
            total = movie_count + len(bucket["series"])
            if not 1 <= index <= total:
                return None
            source = "movies" if index <= movie_count else "series"
            source_index = index - 1 if source == "movies" else index - movie_count - 1
            item = bucket[source][source_index]
            old_type = item.get("type")
            if title is not _UNSET:
                item["title"] = title
            if genre is not _UNSET:
                item["genre"] = genre
            if comment is not _UNSET:
                item["comment"] = comment
            if type is not _UNSET and type is not None and type != old_type:
                bucket[source].pop(source_index)
                item["type"] = type
                target = "movies" if type == "movie" else "series"
                bucket[target].append(item)
            await self._commit_candidate(candidate)
            return item

    def edit_watchlist_entry(self, index, title=None, type=None, genre=None, comment=None, guild_id=None):
        """
        Edit an item in the watchlist by 1-based index.

        Args:
            index: 1-based index of the item to edit
            title: New title (optional)
            type: New type 'movie' or 'series' (optional)
            genre: New genre (optional)
            comment: New comment (optional)
            guild_id: Optional guild/channel scope

        Returns:
            The updated item dict, or None if index is invalid
        """
        self._require_offline_projection()
        changes = {}
        if title is not None:
            changes["title"] = title
        if type is not None:
            changes["type"] = type
        if genre is not None:
            changes["genre"] = genre
        if comment is not None:
            changes["comment"] = comment
        return asyncio.run(
            self.edit_watchlist_result(
                index,
                guild_id=guild_id,
                **changes,
            )
        )

    def snapshot_pending_items(self, scope_id):
        """Return movies then series without creating a missing scope."""
        scopes = self.watchlist.get("scopes", {})
        bucket = scopes.get(str(scope_id))
        if not isinstance(bucket, dict):
            return ()
        movies = bucket.get("movies", [])
        series = bucket.get("series", [])
        return tuple(copy.deepcopy(movies + series))

    def format_suggestion(self, item, lang="no"):
        """Format a suggestion for display in specified language"""
        title = item["title"]

        if lang == "no":
            content_type_label = (
                "🎬 Film" if item.get("type") == "movie" else "📺 Serie"
            )
            header = "🎬 **Kveldens forslag!**"
            genre_label = "Sjanger"
            year_label = "År"
            length_label = "Lengde"
        else:
            content_type_label = (
                "🎬 Movie" if item.get("type") == "movie" else "📺 Series"
            )
            header = "🎬 **Tonight's Suggestion!**"
            genre_label = "Genre"
            year_label = "Year"
            length_label = "Length"

        genre = item.get("genre", "")

        lines = [
            header,
            "",
            f"**{title}**",
            f"{content_type_label}",
        ]

        if genre:
            lines.append(f"{genre_label}: {genre}")

        if item.get("type") == "movie" and item.get("year"):
            lines.append(f"{year_label}: {item['year']}")
        elif item.get("type") == "series" and item.get("episodes"):
            lines.append(f"{length_label}: {item['episodes']}")

        # Add a fun comment based on genre and language
        comments_no = {
            "comedy": ["Perfekt for en god latter! 😂", "Koselig kveld i vente! 🍿"],
            "drama": ["Dramatisk og engasjerende! 🎭", "For de som vil gråte litt 😢"],
            "sci-fi": ["Tankevekkende! 🚀", "For de som liker å drømme stort 🌌"],
            "thriller": ["Spenning til max! 😰", "Hjertet i halsen-garanti! 💓"],
            "horror": ["Ikke for pyser! 👻", "Lys på, dyner over hodet! 🛏️"],
            "action": ["Adrenalinfylt! 💥", "For de som liker fart og spenning! 🏎️"],
        }
        comments_en = {
            "comedy": ["Perfect for a good laugh! 😂", "Cozy evening ahead! 🍿"],
            "drama": [
                "Dramatic and engaging! 🎭",
                "For those who want to cry a bit 😢",
            ],
            "sci-fi": ["Thought-provoking! 🚀", "For dreamers 🌌"],
            "thriller": ["Maximum suspense! 😰", "Heart-in-throat guarantee! 💓"],
            "horror": [
                "Not for the faint-hearted! 👻",
                "Lights on, covers over head! 🛏️",
            ],
            "action": ["Adrenaline-filled! 💥", "For speed and thrill lovers! 🏎️"],
        }

        comments = comments_no if lang == "no" else comments_en

        if genre:
            genre_lower = genre.lower()
            for key, comments_list in comments.items():
                if key in genre_lower:
                    lines.append(f"\n💬 {random.choice(comments_list)}")
                    break

        return "\n".join(lines)

    def format_watchlist_status(self, lang="no", guild_id=None):
        """Format watchlist status in specified language"""
        summary = self.get_watchlist_summary(guild_id)

        if lang == "no":
            header = "📋 **Watchlist Status**"
            movies_label = "Filmer"
            series_label = "Serier"
            unwatched_label = "usette"
            total_label = "totalt"
            empty_msg = "\n🎉 Watchlista er tom! Tid for å legge til mer?"
            low_msg = "\n⚠️ Det begynner å bli tomt i lista..."
            waiting_msg = "\n✨ {count} titler venter på deg!"
        else:
            header = "📋 **Watchlist Status**"
            movies_label = "Movies"
            series_label = "Series"
            unwatched_label = "unwatched"
            total_label = "total"
            empty_msg = "\n🎉 Watchlist is empty! Time to add more?"
            low_msg = "\n⚠️ Getting low on the list..."
            waiting_msg = "\n✨ {count} titles waiting for you!"

        lines = [
            header,
            "",
            f"🎬 {movies_label}: {summary['movies_unwatched']} {unwatched_label} ({summary['movies_total']} {total_label})",
            f"📺 {series_label}: {summary['series_unwatched']} {unwatched_label} ({summary['series_total']} {total_label})",
        ]

        items = self.get_watchlist(guild_id)
        if items:
            lines.append("\n🔢 **Nummerert liste:**" if lang == "no" else "\n🔢 **Numbered list:**")
            for index, item in enumerate(items[:10], 1):
                item_type = "film" if item.get("type") == "movie" else "serie"
                watched = "✓ " if item.get("watched") else ""
                lines.append(f"{index}. {watched}{item.get('title', 'Uten tittel')} ({item_type})")
            if len(items) > 10:
                lines.append(f"… og {len(items) - 10} til." if lang == "no" else f"… and {len(items) - 10} more.")

        total_unwatched = summary["movies_unwatched"] + summary["series_unwatched"]

        if total_unwatched == 0:
            lines.append(empty_msg)
        elif total_unwatched < 5:
            lines.append(low_msg)
        else:
            lines.append(waiting_msg.format(count=total_unwatched))

        return "\n".join(lines)


def parse_watchlist_command(
    message_content,
    *,
    reference_time=None,
    temporal_resolver=None,
):
    """Parse only bounded, case-preserving watchlist command frames."""
    from cal_system.temporal_resolver import TemporalResolver
    from core.utterance import normalize_utterance

    if not isinstance(message_content, str):
        return None
    resolver = temporal_resolver or TemporalResolver()
    content = re.sub(r"^\s*<@!?\d+>\s*", "", message_content)
    content = re.sub(r"^\s*@inebotten\b\s*", "", content, flags=re.I).strip()
    surface = content.strip(" .!?")
    folded = surface.casefold()
    if not folded:
        return None
    lang = "no" if re.search(
        r"\b(?:hva|skal|filmforslag|serieforslag|anbefaling|husk|hugs|"
        r"legg|fjern|slett|endre|rediger|serie|sjå)\b",
        folded,
    ) else "en"

    def item_type(value):
        value = value.casefold()
        if value in {"film", "filmen", "movie"}:
            return "movie"
        if value in {"serie", "serien", "series", "show", "tv show"}:
            return "series"
        return None

    def clean_title(value):
        title = value.strip()
        quote_pairs = {
            '"': '"',
            "'": "'",
            "“": "”",
            "‘": "’",
            "«": "»",
        }
        if len(title) >= 2 and quote_pairs.get(title[0]) == title[-1]:
            title = title[1:-1].strip()
        if not title or title.casefold() in {
            "film",
            "serie",
            "movie",
            "show",
            "til",
            "to",
            "på",
            "i",
        }:
            return None
        return title

    def is_reserved_action_title(value):
        return re.fullmatch(
            r"(?:add|remove|delete|edit|change|legg\s+til|"
            r"fjern|fjerne|slett|slette|endre|rediger)",
            value,
            re.I,
        ) is not None

    def is_descriptive_suffix(value, *, suffix_lang):
        folded_value = value.casefold().strip()
        if suffix_lang == "no":
            return bool(
                re.match(
                    r"^(?:jeg|eg|vi|han|hun|ho|de|du)\b|"
                    r"^(?:ikke|ikkje)\b|"
                    r"^la\s+være\s+å\b|"
                    r"^(?:kan|kunne|vil)\s+du\b",
                    folded_value,
                    re.I,
                )
                or re.search(
                    r"\b(?:er|var|ble|blei|ligger|står)$",
                    folded_value,
                    re.I,
                )
            )
        return bool(
            re.match(
                r"^(?:i|we|he|she|they|you)\s+"
                r"(?:added|put|placed|have\s+added)\b",
                folded_value,
                re.I,
            )
            or re.match(
                r"^(?:do\s+not|don't|not)\b",
                folded_value,
                re.I,
            )
            or re.search(
                r"\b(?:is|are|was|were)$",
                folded_value,
                re.I,
            )
        )

    def is_reminder_media_body(value):
        folded_value = normalize_utterance(value).control_text.strip()
        if re.match(
            r"^(?:på|om|til)\b|^(?:the\s+)?(?:kids|children)\b",
            folded_value,
            re.I,
        ):
            return True
        resolved = resolver.resolve(
            folded_value,
            reference=reference_time,
        )
        return bool(resolved.date or resolved.time)

    def mask_quotes(value):
        quote_re = re.compile(
            r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|«[^»\n]*»|'
            r"(?<!\w)'[^'\n]+'(?!\w)"
        )
        chars = list(value)
        for quote in quote_re.finditer(value):
            for position in range(quote.start(), quote.end()):
                if not chars[position].isspace():
                    chars[position] = "\ufffc"
        return "".join(chars)

    def parse_edit_fields(value, *, edit_lang):
        aliases = (
            {
                "tittel": "title",
                "type": "type",
                "sjanger": "genre",
                "kommentar": "comment",
            }
            if edit_lang == "no"
            else {
                "title": "title",
                "type": "type",
                "genre": "genre",
                "comment": "comment",
            }
        )
        label_re = re.compile(
            rf"(?<!\w)({'|'.join(map(re.escape, aliases))})\s*:\s*",
            re.I,
        )
        any_label_re = re.compile(r"(?<!\w)([^\W\d_][^\W_]*)\s*:\s*", re.I)
        masked = mask_quotes(value)
        matches = list(label_re.finditer(masked))
        if not matches or masked[: matches[0].start()].strip():
            return None
        supported_starts = {match.start() for match in matches}
        if any(
            match.start() not in supported_starts
            for match in any_label_re.finditer(masked)
        ):
            return None
        fields = {}
        for position, match in enumerate(matches):
            key = aliases[match.group(1).casefold()]
            if key in fields:
                return None
            end = matches[position + 1].start() if position + 1 < len(matches) else len(value)
            raw_value = value[match.end() : end].strip(" ,;?.")
            if not raw_value or not raw_value.strip(" \t\r\n\"'“”‘’«»"):
                return None
            fields[key] = raw_value
        if "title" in fields:
            fields["title"] = clean_title(fields["title"])
            if fields["title"] is None:
                return None
        if "type" in fields:
            fields["type"] = item_type(fields["type"])
            if fields["type"] is None:
                return None
        return fields or None

    genre_frame = r"komedie|comedy|drama|sci-fi|action|thriller|horror"
    suggestion = re.fullmatch(
        rf"(?:hva\s+skal\s+vi\s+se|what\s+should\s+we\s+watch|"
        rf"(?:filmforslag|serieforslag)(?:\s+(?:{genre_frame}))?|"
        rf"(?:movie|series)\s+suggestion(?:\s+(?:{genre_frame}))?|"
        rf"anbefaling\s+(?:(?:{genre_frame})\s+)?"
        rf"(?:film|serie)(?:\s+(?:{genre_frame}))?|"
        rf"(?:(?:can|could|would|will)\s+you\s+|please\s+)?"
        rf"recommend(?:\s+me)?\s+(?:(?:a|an|some)\s+)?"
        rf"(?:(?:{genre_frame})\s+)?(?:movie|series|show)"
        rf"(?:\s+(?:{genre_frame}))?)",
        folded,
        re.I,
    )
    if suggestion:
        kind = (
            "movie"
            if folded.startswith("filmforslag")
            or re.search(r"\b(?:film|movie)\b", folded)
            else "series"
            if folded.startswith("serieforslag")
            or re.search(r"\b(?:serie|series|show)\b", folded)
            else None
        )
        genre = next(
            (
                value
                for value in (
                    "komedie",
                    "comedy",
                    "drama",
                    "sci-fi",
                    "action",
                    "thriller",
                    "horror",
                )
                if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", folded)
            ),
            None,
        )
        return {
            "action": "suggest",
            "type": kind,
            "genre": genre,
            "lang": lang,
        }

    if re.fullmatch(
        r"(?:vis|list|show)?\s*(?:min |my |the )?(?:watchlist|watchlista|"
        r"watch list)|hva har vi (?:på|i) watchlist|"
        r"hva\s+har\s+(?:jeg|eg|æ)\s+(?:på|i)\s+"
        r"(?:watchlist|watchlista|watchlisten)(?:\s+min)?|"
        r"show\s+me\s+my\s+(?:watchlist|watch\s+list)|"
        r"(?:what\s+is|what['’]s)\s+on\s+my\s+(?:watchlist|watch\s+list)|"
        r"which\s+(?:movies|films|series|shows)\s+are\s+on\s+my\s+"
        r"(?:watchlist|watch\s+list)",
        folded,
        re.I,
    ):
        return {"action": "status", "lang": lang}

    media_add = re.fullmatch(
        r"(?P<frame>husk\s+å\s+se|hugs\s+å\s+sjå|remember\s+to\s+watch)\s+(.+)",
        surface,
        re.I,
    )
    if media_add:
        raw_title = media_add.group(2)
        same_day_suffix = re.fullmatch(
            r"(?P<title>.+?)\s+(?:i\s+dag|idag|today)",
            raw_title,
            re.I,
        )
        if same_day_suffix and not re.match(
            r"^(?:på|om|til)\b|^(?:the\s+)?(?:kids|children)\b",
            normalize_utterance(same_day_suffix.group("title")).control_text,
            re.I,
        ):
            # In a media frame, a bare same-day suffix describes what the user
            # wants to watch, not a sufficiently precise reminder schedule.
            # Keep the canonical media title and let explicit clock/future
            # temporal forms retain reminder ownership.
            raw_title = same_day_suffix.group("title")
        title = clean_title(raw_title)
        if title is None or is_reminder_media_body(title):
            return None
        return {
            "action": "add",
            "title": title,
            "type": None,
            "lang": "en" if media_add.group("frame").casefold().startswith("remember") else "no",
        }

    norwegian_typed_add = re.fullmatch(
        r"legg\s+til\s+(film|filmen|serie|serien)\s+(.+)",
        surface,
        re.I,
    )
    if norwegian_typed_add:
        title = clean_title(norwegian_typed_add.group(2))
        if title is None:
            return None
        return {
            "action": "add",
            "title": title,
            "type": item_type(norwegian_typed_add.group(1)),
            "lang": "no",
        }

    indirect_norwegian_add = re.fullmatch(
        r"(?:(?:kan|kunne|vil)\s+du\s+|vennligst\s+)?"
        r"(?:husk|huske|hugs|hugse)\s+at\s+(?:jeg|eg|æ)\s+"
        r"(?:vil|skal)\s+(?:se|sjå)(?:\s+på)?\s+"
        r"(?:(film|filmen|serie|serien)\s+)?(?P<title>.+)",
        surface,
        re.I,
    )
    if indirect_norwegian_add:
        raw_title = indirect_norwegian_add.group("title").strip()
        is_quoted = (
            len(raw_title) >= 2
            and (raw_title[0], raw_title[-1])
            in {
                ('"', '"'),
                ("'", "'"),
                ("“", "”"),
                ("‘", "’"),
                ("«", "»"),
            }
        )
        # Without an explicit media noun, require title-shaped evidence so
        # ordinary tasks such as "se legen" retain reminder ownership.
        if (
            indirect_norwegian_add.group(1) is None
            and not is_quoted
            and (not raw_title or not raw_title[0].isupper())
        ):
            return None
        title = clean_title(raw_title)
        if title is None or is_reminder_media_body(title):
            return None
        return {
            "action": "add",
            "title": title,
            "type": item_type(indirect_norwegian_add.group(1) or ""),
            "lang": "no",
        }

    norwegian_action_add = re.fullmatch(
        r"(?:(?:kan|kunne|vil)\s+du\s+|vennligst\s+)?"
        r"(?:legg|legge)(?:\s+til)?\s+(.+?)\s+(?:på|i|til)\s+"
        r"(?:watchlist(?:a|en)?|watch\s+list)(?:\s+min)?",
        surface,
        re.I,
    )
    if norwegian_action_add:
        title = clean_title(norwegian_action_add.group(1))
        if title is None:
            return None
        return {
            "action": "add",
            "title": title,
            "type": None,
            "lang": "no",
        }

    english_action_add = re.fullmatch(
        r"(?:(?:can|could|would|will)\s+you\s+|please\s+)?"
        r"add\s+(.+?)\s+to\s+(?:(?:the|my)\s+)?watchlist",
        surface,
        re.I,
    )
    if english_action_add:
        title = clean_title(english_action_add.group(1))
        if title is None or re.match(r"^(?:film|serie)\b", title, re.I):
            return None
        return {"action": "add", "title": title, "type": None, "lang": "en"}

    remove_no = re.fullmatch(
        r"(?:fjern|fjerne|slett|slette)\s+"
        r"(film|filmen|serie|serien|watchlist(?:a)?)\s+"
        r"(?:(?:nummer|nr\.?|#)\s*)?(\d+)",
        surface,
        re.I,
    )
    if remove_no and int(remove_no.group(2)) > 0:
        return {
            "action": "remove",
            "index": int(remove_no.group(2)),
            "type": item_type(remove_no.group(1)),
            "lang": "no",
        }
    remove_en = re.fullmatch(
        r"(?:remove|delete)\s+(movie|show|watchlist)\s+"
        r"(?:(?:number|no\.?|#)\s*)?(\d+)",
        surface,
        re.I,
    )
    if remove_en and int(remove_en.group(2)) > 0:
        return {
            "action": "remove",
            "index": int(remove_en.group(2)),
            "type": item_type(remove_en.group(1)),
            "lang": "en",
        }

    for pattern, remove_lang in (
        (r"(?:fjern|fjerne|slett|slette)\s+(?:(?:nummer|nr\.?|#)\s*)?(\d+)\s+fra\s+watchlist(?:a)?", "no"),
        (r"(?:remove|delete)\s+(?:(?:number|no\.?|#)\s*)?(\d+)\s+from\s+watchlist", "en"),
    ):
        remove_from = re.fullmatch(pattern, surface, re.I)
        if remove_from and int(remove_from.group(1)) > 0:
            return {
                "action": "remove",
                "index": int(remove_from.group(1)),
                "lang": remove_lang,
            }

    edit = re.fullmatch(
        r"(?P<action>endre|rediger|edit|change)\s+"
        r"(?P<domain>film|filmen|serie|serien|movie|show|watchlist(?:a)?)\s+"
        r"(?:(?:nummer|number|nr\.?|no\.?|#)\s*)?(?P<index>\d+)\s+"
        r"(?P<body>.+)",
        surface,
        re.I,
    )
    if edit and int(edit.group("index")) > 0:
        edit_lang = (
            "no"
            if edit.group("action").casefold() in {"endre", "rediger"}
            else "en"
        )
        allowed_domains = (
            {
                "film",
                "filmen",
                "serie",
                "serien",
                "watchlist",
                "watchlista",
            }
            if edit_lang == "no"
            else {"movie", "show", "watchlist"}
        )
        domain = edit.group("domain").casefold()
        if domain not in allowed_domains:
            return None
        body = edit.group("body").strip()
        connector = re.fullmatch(
            r"(?:til|to)\s+(.+)",
            body,
            re.I,
        )
        if connector:
            matched_connector = body.split(maxsplit=1)[0].casefold()
            if (edit_lang == "no") != (matched_connector == "til"):
                return None
            title = clean_title(connector.group(1))
            if title is None:
                return None
            changes = {"title": title}
        else:
            changes = parse_edit_fields(body, edit_lang=edit_lang)
            if changes is None:
                return None
        domain_type = item_type(domain)
        if domain_type is not None:
            if changes.get("type") not in (None, domain_type):
                return None
            changes.setdefault("type", domain_type)
        return {
            "action": "edit",
            "index": int(edit.group("index")),
            **changes,
            "lang": edit_lang,
        }
    return None


# Quick test
if __name__ == "__main__":
    print("=== Watchlist Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = WatchlistManager(storage_path=storage_path)

    # Test suggestion
    suggestion = manager.get_random_suggestion()
    if suggestion:
        print("Random suggestion:")
        print(manager.format_suggestion(suggestion))
        print()

    # Test status
    print(manager.format_watchlist_status())

    # Cleanup
    manager.storage_path.unlink(missing_ok=True)

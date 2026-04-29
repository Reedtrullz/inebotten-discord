#!/usr/bin/env python3
"""
Watchlist Manager for Inebotten
Manages movie and series recommendations from Discord channels
"""

import json
import random
import re
from datetime import datetime
from pathlib import Path


class WatchlistManager:
    """
    Manages watchlists for movies and series
    Can import from Discord channels or store locally
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / ".hermes" / "discord" / "watchlist.json"

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.watchlist = self._load_watchlist()

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
        Get a watchlist bucket.
        Without guild_id, keep using the legacy global bucket for compatibility.
        """
        if guild_id is None:
            self.watchlist.setdefault("movies", [])
            self.watchlist.setdefault("series", [])
            return self.watchlist

        scopes = self.watchlist.setdefault("scopes", {})
        return scopes.setdefault(str(guild_id), self._empty_watchlist())

    def _save_watchlist(self):
        """Save watchlist to storage"""
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.watchlist, f, ensure_ascii=False, indent=2)

    def add_from_discord_message(self, title, content_type="movie", guild_id=None, **kwargs):
        """
        Add a movie/series from a Discord message

        Args:
            title: Movie/series title
            content_type: 'movie' or 'series'
            guild_id: Guild/channel scope. DMs and group DMs should pass channel ID.
            **kwargs: Extra info like genre, year, platform, etc.
        """
        bucket = self._get_scope(guild_id)
        item = {
            "title": title,
            "type": content_type,
            "added_at": datetime.now().isoformat(),
            "watched": False,
            "completed": False,
            **kwargs,
        }

        if content_type == "movie":
            bucket["movies"].append(item)
        else:
            bucket["series"].append(item)

        self._save_watchlist()
        return True

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

    def mark_as_watched(self, title, guild_id=None):
        """Mark an item as watched"""
        bucket = self._get_scope(guild_id)
        for item in bucket["movies"] + bucket["series"]:
            if item["title"].lower() == title.lower():
                item["watched"] = True
                item["completed"] = True
                item["watched_at"] = datetime.now().isoformat()
                self._save_watchlist()
                return True
        return False

    def remove_from_watchlist(self, index, guild_id=None):
        """
        Remove an item from the watchlist by 1-based index.

        Args:
            index: 1-based index of the item to remove
            guild_id: Optional guild/channel scope

        Returns:
            The removed item dict, or None if index is invalid
        """
        bucket = self._get_scope(guild_id)
        items = bucket["movies"] + bucket["series"]
        if not 1 <= index <= len(items):
            return None
        item = items[index - 1]
        if item in bucket["movies"]:
            bucket["movies"].remove(item)
        else:
            bucket["series"].remove(item)
        self._save_watchlist()
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
        bucket = self._get_scope(guild_id)
        items = bucket["movies"] + bucket["series"]
        if not 1 <= index <= len(items):
            return None
        item = items[index - 1]
        old_type = item.get("type")

        if title is not None:
            item["title"] = title
        if genre is not None:
            item["genre"] = genre
        if comment is not None:
            item["comment"] = comment
        if type is not None and type != old_type:
            if old_type == "movie":
                bucket["movies"].remove(item)
            else:
                bucket["series"].remove(item)
            item["type"] = type
            if type == "movie":
                bucket["movies"].append(item)
            else:
                bucket["series"].append(item)

        self._save_watchlist()
        return item

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

        total_unwatched = summary["movies_unwatched"] + summary["series_unwatched"]

        if total_unwatched == 0:
            lines.append(empty_msg)
        elif total_unwatched < 5:
            lines.append(low_msg)
        else:
            lines.append(waiting_msg.format(count=total_unwatched))

        return "\n".join(lines)


def parse_watchlist_command(message_content):
    """
    Parse watchlist commands (Norwegian and English)

    Returns:
        dict with action and data, or None
    """
    content_lower = message_content.lower()

    # Detect language
    lang_keywords = ["filmforslag", "serieforslag", "anbefaling", "hva skal vi se"]
    lang = (
        "no"
        if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in lang_keywords)
        else "en"
    )

    # Check for suggestion request
    suggestion_keywords = [
        "hva skal vi se",
        "filmforslag",
        "serieforslag",
        "anbefaling",
        "movie suggestion",
        "series suggestion",
        "what should we watch",
        "recommend",
    ]

    for keyword in suggestion_keywords:
        if re.search(rf'\b{re.escape(keyword)}\b', content_lower):
            # Determine type
            content_type = None
            if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in ["film", "movie", "filmforslag"]):
                content_type = "movie"
            elif any(
                re.search(rf'\b{re.escape(word)}\b', content_lower)
                for word in ["serie", "series", "serieforslag", "tv show", "program"]
            ):
                content_type = "series"

            # If it's a general 'recommend' without movie/series context, skip it
            if keyword in ["recommend", "anbefaling"] and not content_type:
                continue

            # Check for genre
            genre = None
            genres = [
                "komedie",
                "comedy",
                "drama",
                "sci-fi",
                "action",
                "thriller",
                "horror",
            ]
            for g in genres:
                if re.search(rf'\b{re.escape(g)}\b', content_lower):
                    genre = g
                    break

            return {
                "action": "suggest",
                "type": content_type,
                "genre": genre,
                "lang": lang,
            }

    # Check for removing item (before generic status match)
    remove_phrases = ["fjern watchlist", "slett watchlist", "fjern fra watchlist"]
    if any(re.search(rf'\b{re.escape(phrase)}\b', content_lower) for phrase in remove_phrases):
        number_match = re.search(r'\b(\d+)\b', message_content)
        index = int(number_match.group(1)) if number_match else None
        return {"action": "remove", "index": index, "lang": lang}

    # Check for editing item (before generic status match)
    edit_phrases = ["endre watchlist", "rediger watchlist"]
    if any(re.search(rf'\b{re.escape(phrase)}\b', content_lower) for phrase in edit_phrases):
        number_match = re.search(r'\b(\d+)\b', message_content)
        index = int(number_match.group(1)) if number_match else None
        return {"action": "edit", "index": index, "lang": lang}

    # Check for adding item
    add_phrases = ["legg til", "add to watchlist", "husk å se"]
    if any(re.search(rf'\b{re.escape(phrase)}\b', content_lower) for phrase in add_phrases):
        return {"action": "add", "lang": lang}

    # Check for watchlist status
    status_keywords = ["watchlist", "watchlista", "hva har vi"]
    if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in status_keywords):
        return {"action": "status", "lang": lang}

    return None


# Quick test
if __name__ == "__main__":
    print("=== Watchlist Manager Test ===\n")

    manager = WatchlistManager(storage_path="/tmp/test_watchlist.json")

    # Test suggestion
    suggestion = manager.get_random_suggestion()
    if suggestion:
        print("Random suggestion:")
        print(manager.format_suggestion(suggestion))
        print()

    # Test status
    print(manager.format_watchlist_status())

    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()

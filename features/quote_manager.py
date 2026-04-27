#!/usr/bin/env python3
"""
Quote Manager for Inebotten
Saves funny quotes and messages from the group
"""

import json
import random
import re
from datetime import datetime
from pathlib import Path


class QuoteManager:
    """
    Manages funny quotes and memorable messages
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / ".hermes" / "discord" / "quotes.json"

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.quotes = self._load_quotes()

    def _load_quotes(self):
        """Load quotes from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FEATURES] Quote load error: {e}")
                return {}
        return {}

    def _save_quotes(self):
        """Save quotes to storage"""
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.quotes, f, ensure_ascii=False, indent=2)

    def add_quote(self, guild_id, text, author, context=None):
        """
        Add a new quote

        Args:
            guild_id: Discord guild/channel ID
            text: The quote text
            author: Who said it
            context: Optional context (what was happening)
        """
        guild_key = str(guild_id)

        if guild_key not in self.quotes:
            self.quotes[guild_key] = []

        quote = {
            "text": text,
            "author": author,
            "context": context,
            "date": datetime.now().strftime("%d.%m.%Y"),
            "timestamp": datetime.now().isoformat(),
        }

        self.quotes[guild_key].append(quote)
        self._save_quotes()

        return True

    def get_random_quote(self, guild_id):
        """Get a random quote from a guild"""
        guild_key = str(guild_id)

        if guild_key not in self.quotes or not self.quotes[guild_key]:
            # Try searching all guilds
            all_quotes = []
            for quotes in self.quotes.values():
                all_quotes.extend(quotes)

            if all_quotes:
                return random.choice(all_quotes)
            return None

        return random.choice(self.quotes[guild_key])

    def get_quote_by_author(self, guild_id, author):
        """Get a random quote from a specific author"""
        guild_key = str(guild_id)

        candidates = []

        if guild_key in self.quotes:
            candidates.extend(
                [
                    q
                    for q in self.quotes[guild_key]
                    if author.lower() in q["author"].lower()
                ]
            )

        # Search other guilds too
        for gid, quotes in self.quotes.items():
            if gid != guild_key:
                candidates.extend(
                    [q for q in quotes if author.lower() in q["author"].lower()]
                )

        if candidates:
            return random.choice(candidates)
        return None

    def format_quote(self, quote, lang="no"):
        """Format quote for display in specified language"""
        header = (
            "💬 **Sitat fra arkivet**" if lang == "no" else "💬 **Quote from archive**"
        )
        context_label = "Kontekst" if lang == "no" else "Context"
        unknown_date = "Ukjent dato" if lang == "no" else "Unknown date"

        lines = [
            header,
            "",
            f'"{quote["text"]}"',
            f"— {quote['author']}",
        ]

        if quote.get("context"):
            lines.append(f"\n*{context_label}: {quote['context']}*")

        lines.append(f"\n_{quote.get('date', unknown_date)}_")

        return "\n".join(lines)

    def format_confirmation(self, quote_text, lang="no"):
        """Format confirmation when quote is saved"""
        if lang == "no":
            responses = [
                f'💾 Lagret! "{quote_text[:50]}{"..." if len(quote_text) > 50 else ""}"',
                f'✨ Klassiker lagret! "{quote_text[:50]}{"..." if len(quote_text) > 50 else ""}"',
                f"📝 Notert! Dette må huskes!",
            ]
        else:
            responses = [
                f'💾 Saved! "{quote_text[:50]}{"..." if len(quote_text) > 50 else ""}"',
                f'✨ Classic saved! "{quote_text[:50]}{"..." if len(quote_text) > 50 else ""}"',
                f"📝 Noted! This must be remembered!",
            ]
        return random.choice(responses)


def parse_quote_command(message_content):
    """
    Parse quote commands (Norwegian and English)

    Returns:
        dict with action and text, or None
    """
    content_lower = message_content.lower()

    # Detect language
    no_keywords = ["husk", "lagre", "gullkorn", "sitat"]
    lang = (
        "no"
        if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in no_keywords)
        else "en"
    )

    # Check for saving a quote (Norwegian)
    save_phrases_no = ["husk dette", "lagre dette", "dette må huskes", "gullkorn"]
    # Check for saving a quote (English)
    save_phrases_en = [
        "remember this",
        "save this",
        "this must be remembered",
        "quote this",
    ]

    all_save_phrases = save_phrases_no + save_phrases_en
    if any(re.search(rf'\b{re.escape(phrase)}\b', content_lower) for phrase in all_save_phrases):
        # Extract text after the command
        text = message_content
        for phrase in all_save_phrases + ["@inebotten"]:
            # Use regex for replacement to ensure word boundaries if needed, but here simple replace is usually fine for extraction
            # though regex is safer.
            text = re.sub(rf'\b{re.escape(phrase)}\b', '', text, flags=re.IGNORECASE).strip()

        # Remove colon if present at start
        text = text.lstrip(":").strip()

        if text:
            return {"action": "save", "text": text, "lang": lang}

    # Check for retrieving a quote
    get_words_no = ["sitat", "husk hva", "hva sa"]
    get_words_en = ["quote", "random quote", "show quote"]

    all_get_words = get_words_no + get_words_en
    if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in all_get_words):
        return {"action": "get", "lang": lang}

    return None


# Quick test
if __name__ == "__main__":
    print("=== Quote Manager Test ===\n")

    manager = QuoteManager(storage_path="/tmp/test_quotes.json")

    # Add test quote
    manager.add_quote(
        "test_guild",
        "Jeg er ikke full, jeg er bare litt wobbly!",
        "Ola Nordmann",
        "Etter julebordet",
    )

    # Get random
    quote = manager.get_random_quote("test_guild")
    if quote:
        print(manager.format_quote(quote))

    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()

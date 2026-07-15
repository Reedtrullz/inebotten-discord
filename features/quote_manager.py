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

from utils.json_storage import hermes_discord_data_path, write_json_atomic


QUOTE_EDIT_FIELD = re.compile(
    r"(?<!\w)(?P<label>tekst|text|forfatter|author)\s*:\s*",
    flags=re.IGNORECASE,
)


class QuoteManager:
    """
    Manages funny quotes and memorable messages
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = hermes_discord_data_path("quotes.json")

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
        write_json_atomic(self.storage_path, self.quotes)

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

    def get_random_quote(self, guild_id=None):
        """Get a random quote from a guild"""
        if guild_id is None:
            all_quotes = []
            for quotes in self.quotes.values():
                all_quotes.extend(quotes)
            return random.choice(all_quotes) if all_quotes else None

        guild_key = str(guild_id)

        if guild_key not in self.quotes or not self.quotes[guild_key]:
            return None

        return random.choice(self.quotes[guild_key])

    def get_quote_by_author(self, guild_id=None, author=None):
        """Get a random quote from a specific author"""
        if not author:
            return None

        candidates = []
        if guild_id is None:
            scoped_quotes = []
            for quotes in self.quotes.values():
                scoped_quotes.extend(quotes)
        else:
            scoped_quotes = self.quotes.get(str(guild_id), [])

        candidates.extend(
            q for q in scoped_quotes if author.lower() in q.get("author", "").lower()
        )

        if candidates:
            return random.choice(candidates)
        return None

    def list_quotes(self, guild_id):
        """Return all quotes for a guild as a list"""
        guild_key = str(guild_id)
        return self.quotes.get(guild_key, []).copy()

    def update_quote(self, guild_id, index, text=None, author=None):
        """
        Update a quote by 1-based index.

        Args:
            guild_id: Discord guild/channel ID
            index: 1-based index of the quote to update
            text: New quote text (optional)
            author: New author (optional)

        Raises:
            ValueError: If the quote index is invalid
        """
        guild_key = str(guild_id)

        if guild_key not in self.quotes:
            raise ValueError("Quote index out of range")

        quotes = self.quotes[guild_key]
        zero_based_index = index - 1

        if zero_based_index < 0 or zero_based_index >= len(quotes):
            raise ValueError("Quote index out of range")

        if text is not None:
            quotes[zero_based_index]["text"] = text
        if author is not None:
            quotes[zero_based_index]["author"] = author

        self._save_quotes()
        return True

    def delete_quote(self, guild_id, index):
        """
        Delete a quote by 1-based index.

        Args:
            guild_id: Discord guild/channel ID
            index: 1-based index of the quote to delete

        Raises:
            ValueError: If the quote index is invalid
        """
        guild_key = str(guild_id)

        if guild_key not in self.quotes:
            raise ValueError("Quote index out of range")

        quotes = self.quotes[guild_key]
        zero_based_index = index - 1

        if zero_based_index < 0 or zero_based_index >= len(quotes):
            raise ValueError("Quote index out of range")

        quotes.pop(zero_based_index)
        self._save_quotes()
        return True

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
    if not isinstance(message_content, str):
        return None
    content = re.sub(r"^\s*<@!?\d+>\s*", "", message_content)
    content = re.sub(
        r"^\s*@inebotten\b\s*", "", content, flags=re.IGNORECASE
    ).strip()
    if not content:
        return None
    content_lower = content.casefold()
    lang = (
        "no"
        if re.search(
            r"\b(?:husk|huskes|lagre|gullkorn|sitat|sitater|endre|rediger|"
            r"slett|fjern|liste|vis|forfatter|tekst|hva|sa)\b",
            content_lower,
        )
        else "en"
    )

    list_match = re.fullmatch(
        r"(?:liste\s+sitater|vis\s+sitater|alle\s+sitater|"
        r"list\s+quotes|show\s+quotes|all\s+quotes)\s*[?.!]*",
        content,
        re.IGNORECASE,
    )
    if list_match:
        return {"action": "list", "lang": lang}

    edit = re.fullmatch(
        r"(?:endre|rediger|edit)\s+(?:sitat|quote)\s+"
        r"(?P<index>\d+)\s+(?P<body>.+?)\s*",
        content,
        re.IGNORECASE,
    )
    if edit and int(edit.group("index")) > 0:
        body = edit.group("body")
        fields = list(QUOTE_EDIT_FIELD.finditer(body))
        if not fields or body[: fields[0].start()].strip():
            return None
        aliases = {
            "tekst": "text",
            "text": "text",
            "forfatter": "author",
            "author": "author",
        }
        payload = {
            "action": "edit",
            "index": int(edit.group("index")),
            "lang": lang,
        }
        seen = set()
        for index, field in enumerate(fields):
            key = aliases[field.group("label").casefold()]
            if key in seen:
                return None
            seen.add(key)
            end = (
                fields[index + 1].start()
                if index + 1 < len(fields)
                else len(body)
            )
            value = body[field.end() : end].strip(" \t\r\n,;")
            if value:
                payload[key] = value
        if "text" in payload or "author" in payload:
            return payload
        return None

    delete = re.fullmatch(
        r"(?:slett|fjern|delete|remove)\s+(?:sitat|quote)\s+"
        r"(?P<index>\d+)\s*[?.!]*",
        content,
        re.IGNORECASE,
    )
    if delete and int(delete.group("index")) > 0:
        return {
            "action": "delete",
            "index": int(delete.group("index")),
            "lang": lang,
        }

    save = re.fullmatch(
        r"(?:husk\s+dette|lagre\s+dette|dette\s+må\s+huskes|gullkorn|"
        r"remember\s+this|save\s+this|this\s+must\s+be\s+remembered|"
        r"quote\s+this|lagre\s+sitat|save\s+quote)\b"
        r"(?:\s*[:\-\u2013\u2014]\s*|\s+)(?P<text>.+?)\s*",
        content,
        re.IGNORECASE,
    )
    if save:
        text = save.group("text").strip()
        quote_pairs = {'"': '"', "'": "'", "“": "”", "‘": "’", "«": "»"}
        if len(text) >= 2 and quote_pairs.get(text[0]) == text[-1]:
            text = text[1:-1].strip()
        if text:
            return {"action": "save", "text": text, "lang": lang}

    author_match = re.fullmatch(
        r"(?:hva\s+sa\s+(?P<author_no>.+?)|"
        r"what\s+did\s+(?P<author_en>.+?)\s+say)\s*[?.!]*",
        content,
        re.IGNORECASE,
    )
    if author_match:
        author = (
            author_match.group("author_no") or author_match.group("author_en")
        ).strip()
    else:
        author = ""
    if author:
        return {
            "action": "get",
            "author": author,
            "lang": lang,
        }
    if re.fullmatch(
        r"(?:sitat|quote|random\s+quote|show\s+quote|vis\s+sitat|"
        r"vis\s+quote|husk\s+hva(?:\s+.+)?)\s*[?.!]*",
        content,
        re.IGNORECASE,
    ):
        return {"action": "get", "lang": lang}
    return None


# Quick test
if __name__ == "__main__":
    print("=== Quote Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = QuoteManager(storage_path=storage_path)

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
    manager.storage_path.unlink(missing_ok=True)

#!/usr/bin/env python3
"""
URL Shortener for Inebotten
Shortens long URLs using TinyURL or similar services
"""

import re
import asyncio
import http.client
import urllib.parse


_COURTESY = (
    r"(?:(?:hvis|om|når)\s+du\s+har\s+tid|hvis\s+det\s+passer|"
    r"(?:hvis|om)\s+du\s+kan|"
    r"(?:if|when)\s+you\s+have\s+time|"
    r"if\s+(?:it(?:'s|\s+is)\s+)?convenient|if\s+you\s+can|"
    r"if\s+possible)"
)
_POLITE = (
    r"(?:kan\s+du|kunne\s+du|vil\s+du|can\s+you|could\s+you|"
    r"would\s+you|will\s+you|vennligst|please)"
)
_SHORTEN_REQUEST = re.compile(
    rf"^(?:{_COURTESY}\s*,?\s+)?"
    rf"(?:{_POLITE}(?:\s*,?\s*{_COURTESY}\s*,?)?\s+)?"
    r"(?:(?:forkort|forkorte|kort\s+ned|korte\s+ned|shorten)\s+"
    r"(?:(?:denne|this)\s+(?:url(?:-en)?|lenk(?:e|en)|link)"
    r"(?:\s+for\s+me)?\s*[:?]?\s*)?"
    r"(?P<direct>https?://[^\s]+?)|"
    r"make\s+this\s+url\s+shorter\s*:?\s*"
    r"(?P<make>https?://[^\s]+?)|"
    r"(?:lag|lage|make)\s+(?:en|ei|a)\s+"
    r"(?:kort\s+lenke|short\s+link)\s+(?:av|for|from)\s+"
    rf"(?P<link>https?://[^\s]+?))"
    rf"(?:\s*,?\s+{_COURTESY})?"
    r"(?:\s*[,;]?\s+(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[.!?]*)?$",
    re.IGNORECASE,
)

class URLShortener:
    """
    Shortens URLs using TinyURL API
    """

    def __init__(self):
        self.url_pattern = re.compile(
            r"https?://[^\s<>\"']+",
            re.IGNORECASE,
        )

    def parse_shorten_command(self, message_content):
        """
        Parse shorten command
        Examples:
        - "shorten https://very-long-url.com/..."
        - "forkort https://example.com/very/long/path"
        """
        # Remove only a real leading invocation.  The same bytes inside a URL
        # path/query are user data and must remain lossless.
        content = re.sub(
            r"^\s*@inebotten\b\s*[,;:]?\s*",
            "",
            message_content,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        
        request = _SHORTEN_REQUEST.fullmatch(content)
        if request is None:
            return None
        # URL punctuation is ambiguous with prose punctuation. Preserve the
        # exact request token rather than changing a legal path/query/fragment.
        url = (
            request.group("direct")
            or request.group("make")
            or request.group("link")
        )
        if urllib.parse.urlsplit(url).netloc:
            return {'url': url}
        
        return None
    
    def shorten_url(self, url):
        """
        Shorten URL using TinyURL
        """
        if not url:
            return None

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        
        try:
            api_path = f"/api-create.php?url={urllib.parse.quote(url, safe='')}"
            connection = http.client.HTTPSConnection("tinyurl.com", timeout=10)
            try:
                connection.request("GET", api_path, headers={"User-Agent": "InebottenBot/1.0"})
                response = connection.getresponse()
                if response.status != 200:
                    return None
                short_url = response.read().decode('utf-8').strip()
                short_parsed = urllib.parse.urlparse(short_url)

                if short_parsed.scheme == "https" and short_parsed.netloc:
                    return {
                        'original': url,
                        'short': short_url,
                    }
            finally:
                connection.close()
        except Exception as e:
            print(f"[URL] Error shortening URL: {e}")
        
        return None

    async def shorten_url_async(self, url):
        """Shorten URL without blocking the event loop."""
        return await asyncio.to_thread(self.shorten_url, url)
    
    def format_short_url(self, data, lang='no'):
        """Format shortened URL"""
        if not data:
            if lang == 'no':
                return "❌ Kunne ikke forkorte URL"
            else:
                return "❌ Could not shorten URL"
        
        if lang == 'no':
            return f"🔗 **Forkortet URL:**\n{data['short']}"
        else:
            return f"🔗 **Short URL:**\n{data['short']}"


def parse_shorten_command(message_content):
    """Convenience function"""
    shortener = URLShortener()
    return shortener.parse_shorten_command(message_content)


def shorten_url(url):
    """Quick shorten function"""
    shortener = URLShortener()
    return shortener.shorten_url(url)

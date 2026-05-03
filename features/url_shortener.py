#!/usr/bin/env python3
"""
URL Shortener for Inebotten
Shortens long URLs using TinyURL or similar services
"""

import re
import urllib.request
import urllib.parse

class URLShortener:
    """
    Shortens URLs using TinyURL API
    """
    
    def __init__(self):
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
    
    def parse_shorten_command(self, message_content):
        """
        Parse shorten command
        Examples:
        - "shorten https://very-long-url.com/..."
        - "forkort https://example.com/very/long/path"
        """
        content_lower = message_content.lower()
        
        # Remove @inebotten
        content = message_content.replace('@inebotten', '').strip()
        
        # Check for shorten keywords (use word boundaries)
        keywords = ['shorten', 'forkort', 'kort url', 'short url']
        if not any(re.search(rf"\b{re.escape(word)}\b", content_lower) for word in keywords):
            return None
        
        # Find URL
        match = self.url_pattern.search(content)
        if match:
            return {'url': match.group(0)}
        
        return None
    
    def shorten_url(self, url):
        """
        Shorten URL using TinyURL
        """
        if not url:
            return None
        
        try:
            # TinyURL API
            api_url = f"http://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}"
            
            with urllib.request.urlopen(api_url, timeout=10) as response:
                short_url = response.read().decode('utf-8')
                
                if short_url and short_url.startswith('http'):
                    return {
                        'original': url,
                        'short': short_url,
                    }
        except Exception as e:
            print(f"[URL] Error shortening URL: {e}")
        
        return None
    
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

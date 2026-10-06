#!/usr/bin/env python3
"""
Browser Manager for Inebotten
Tracks optional Browserbase configuration for future content extraction.
"""

import os
from typing import Optional

class BrowserManager:
    """
    Manages optional Browserbase sessions.

    The REST session endpoint does not return page text by itself, so this
    manager only reports usable content when a real extraction path exists.
    """
    
    def __init__(self):
        # Support both naming conventions
        self.api_key = os.getenv("BROWSERBASE_API_KEY") or os.getenv("BROWSER_BASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID") or os.getenv("BROWSER_BASE_PROJECT_ID")
        self.public_extraction_enabled = os.getenv('PUBLIC_PAGE_EXTRACTION_ENABLED', '').lower() in ('1', 'true', 'yes')
        self._extractor = None
        self._closed = False
        self.last_extraction_status = 'disabled'
        
    def is_configured(self) -> bool:
        return not self._closed and self.public_extraction_enabled

    async def fetch_page_content(self, url: str, *, deadline=None) -> Optional[str]:
        """
        Try to fetch page text through Browserbase.

        Returns None until a CDP/Playwright or Browserbase extraction endpoint
        is wired in. This prevents session metadata from being injected into AI
        prompts as if it were source content.
        """
        card = await self.fetch_page_card(url, deadline=deadline)
        return card['text'] if card else None

    async def fetch_page_card(self, url: str, *, deadline=None):
        import time
        if not self.is_configured():
            return None
        if self._extractor is None:
            from features.public_page_extraction import PublicPageExtractor
            self._extractor = PublicPageExtractor()
        try:
            card = await self._extractor.extract(url, deadline=deadline if deadline is not None else time.monotonic() + 5)
            self.last_extraction_status = 'extracted'
            return card
        except Exception:
            # Extraction failure preserves usable snippet cards. Cancellation is
            # a BaseException and still propagates to the owned shutdown path.
            self.last_extraction_status = 'unavailable'
            return None

    async def close(self):
        self._closed = True
        if self._extractor is not None:
            await self._extractor.close()

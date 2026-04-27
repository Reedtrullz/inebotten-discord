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
        
    def is_configured(self) -> bool:
        return bool(self.api_key and self.project_id)

    async def fetch_page_content(self, url: str) -> Optional[str]:
        """
        Try to fetch page text through Browserbase.

        Returns None until a CDP/Playwright or Browserbase extraction endpoint
        is wired in. This prevents session metadata from being injected into AI
        prompts as if it were source content.
        """
        if not self.is_configured():
            return None

        print(f"[BROWSER] Browserbase content extraction is not configured for: {url}")
        return None

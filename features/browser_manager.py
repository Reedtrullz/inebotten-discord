#!/usr/bin/env python3
"""
Browser Manager for Inebotten
Uses Browserbase to fetch and "read" full web pages.
"""

import asyncio
import os
from typing import Optional
from browserbase import Browserbase

class BrowserManager:
    """
    Manages headless browser sessions via Browserbase to scrape deep content.
    """
    
    def __init__(self):
        # Support both naming conventions (with and without underscore)
        self.api_key = os.getenv("BROWSERBASE_API_KEY") or os.getenv("BROWSER_BASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID") or os.getenv("BROWSER_BASE_PROJECT_ID")
        self.bb = None
        if self.api_key and self.project_id:
            self.bb = Browserbase(api_key=self.api_key, project_id=self.project_id)
            print("[BROWSER] Browserbase initialized successfully")
        else:
            print("[BROWSER] Warning: Browserbase not fully configured (missing key or project ID)")
            
    async def fetch_page_content(self, url: str) -> Optional[str]:
        """
        Visits a URL and extracts the text content using Browserbase.
        """
        if not self.bb:
            return None
            
        try:
            print(f"[BROWSER] Visiting: {url}")
            # Browserbase is blocking, run in executor
            loop = asyncio.get_event_loop()
            
            # Use the simple load method for content extraction
            content = await loop.run_in_executor(
                None,
                lambda: self.bb.load(url)
            )
            
            if content:
                # Basic cleanup to remove excessive whitespace
                cleaned = " ".join(content.split())
                return cleaned[:4000] # Limit context size
                
            return None
        except Exception as e:
            print(f"[BROWSER] Error fetching page: {e}")
            return None

    def is_configured(self) -> bool:
        """Returns True if Browserbase is ready to use."""
        return self.bb is not None

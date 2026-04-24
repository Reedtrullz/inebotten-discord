#!/usr/bin/env python3
"""
Browser Manager for Inebotten
Uses the official Browserbase SDK for high-reliability web scraping.
"""

import asyncio
import os
from typing import Optional

class BrowserManager:
    """
    Manages browser sessions via Browserbase to scrape deep content.
    """
    
    def __init__(self):
        # Support both naming conventions
        self.api_key = os.getenv("BROWSERBASE_API_KEY") or os.getenv("BROWSER_BASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID") or os.getenv("BROWSER_BASE_PROJECT_ID")
        self._bb = None
        
    def is_configured(self) -> bool:
        return bool(self.api_key and self.project_id)

    def _get_bb(self):
        """Lazy loader for the SDK to prevent startup crashes."""
        if self._bb is None and self.is_configured():
            try:
                from browserbase import Browserbase
                # The SDK handles auth and headers internally
                self._bb = Browserbase(api_key=self.api_key, project_id=self.project_id)
                print("[BROWSER] SDK initialized successfully")
            except Exception as e:
                print(f"[BROWSER] SDK initialization failed: {e}")
        return self._bb

    async def fetch_page_content(self, url: str) -> Optional[str]:
        """
        Visits a URL and extracts content using the official Browserbase SDK.
        """
        bb = self._get_bb()
        if not bb:
            return None
            
        try:
            print(f"[BROWSER] Loading page: {url}")
            loop = asyncio.get_event_loop()
            
            # The SDK's load() method is the most reliable way to get text content
            content = await loop.run_in_executor(
                None,
                lambda: bb.load(url)
            )
            
            if content:
                # Clean up and limit size for LLM context
                cleaned = " ".join(str(content).split())
                return cleaned[:6000]
                
            return None
        except Exception as e:
            # Catch auth errors specifically
            if "401" in str(e):
                print(f"[BROWSER] Auth Error: API Key or Project ID is invalid. Please check your .env")
            else:
                print(f"[BROWSER] Load failed: {e}")
            return None

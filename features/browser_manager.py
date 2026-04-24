#!/usr/bin/env python3
"""
Browser Manager for Inebotten
Uses Browserbase to fetch and "read" full web pages.
"""

import asyncio
import os
from typing import Optional

class BrowserManager:
    """
    Manages headless browser sessions via Browserbase to scrape deep content.
    """
    
    def __init__(self):
        # Support both naming conventions (with and without underscore)
        self.api_key = os.getenv("BROWSERBASE_API_KEY") or os.getenv("BROWSER_BASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID") or os.getenv("BROWSER_BASE_PROJECT_ID")
        self._bb = None
        
    def _get_bb(self):
        if self._bb is None and self.api_key and self.project_id:
            try:
                from browserbase import Browserbase
                self._bb = Browserbase(api_key=self.api_key, project_id=self.project_id)
                print("[BROWSER] Browserbase initialized successfully")
            except ImportError:
                print("[BROWSER] Warning: browserbase library not installed")
            except Exception as e:
                print(f"[BROWSER] Error initializing Browserbase: {e}")
        return self._bb

    async def fetch_page_content(self, url: str) -> Optional[str]:
        """
        Visits a URL and extracts the text content using Browserbase.
        """
        bb = self._get_bb()
        if not bb:
            return None
            
        try:
            print(f"[BROWSER] Visiting: {url}")
            # Browserbase is blocking, run in executor
            loop = asyncio.get_event_loop()
            
            # Use the simple load method for content extraction
            content = await loop.run_in_executor(
                None,
                lambda: bb.load(url)
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

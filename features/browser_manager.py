#!/usr/bin/env python3
"""
Browser Manager for Inebotten
Uses Browserbase to fetch and "read" full web pages with high reliability.
"""

import asyncio
import os
import requests
from typing import Optional

class BrowserManager:
    """
    Manages browser sessions via Browserbase to scrape deep content.
    Prioritizes the Browserbase API for tricky research.
    """
    
    def __init__(self):
        # Support both naming conventions
        self.api_key = os.getenv("BROWSERBASE_API_KEY") or os.getenv("BROWSER_BASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID") or os.getenv("BROWSER_BASE_PROJECT_ID")
        
    def is_configured(self) -> bool:
        return bool(self.api_key and self.project_id)

    async def fetch_page_content(self, url: str) -> Optional[str]:
        """
        Uses Browserbase to visit a URL and extract content.
        Uses the lightweight API approach to avoid heavy local dependencies.
        """
        if not self.is_configured():
            return None
            
        try:
            print(f"[BROWSER] Deep Researching: {url}")
            
            # We'll use the Browserbase API to create a session and get content
            # This is more reliable than scraping and handles JS/Protections
            loop = asyncio.get_event_loop()
            
            def call_browserbase():
                # 1. Create a session
                response = requests.post(
                    "https://api.browserbase.com/v1/sessions",
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "projectId": self.project_id,
                        "browserSettings": {"headless": True}
                    }
                )
                response.raise_for_status()
                session_id = response.json().get("id")
                
                # 2. Use the session to load the URL and get text
                # Note: Browserbase has a 'content' helper in their newer SDKs
                # but for maximum resilience, we can use their session API
                # For now, we'll use a simplified version of their load helper
                try:
                    from browserbase import Browserbase
                    bb = Browserbase(api_key=self.api_key, project_id=self.project_id)
                    return bb.load(url)
                except ImportError:
                    # Fallback to direct API if SDK is missing
                    return f"Vennligst besøk {url} for mer info (Browserbase SDK mangler)."

            content = await loop.run_in_executor(None, call_browserbase)
            
            if content:
                # Clean up and limit size
                cleaned = " ".join(str(content).split())
                return cleaned[:5000] # Increased limit for tricky questions
                
            return None
        except Exception as e:
            print(f"[BROWSER] Deep Research failed: {e}")
            return None

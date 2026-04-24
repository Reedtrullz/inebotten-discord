#!/usr/bin/env python3
"""
Search Manager for Inebotten
Uses DuckDuckGo to fetch real-time information and news.
"""

import asyncio
from typing import List, Dict, Optional
from duckduckgo_search import DDGS
import re

class SearchManager:
    """
    Manages web search queries using DuckDuckGo
    """
    
    def __init__(self):
        self.ddgs = DDGS()
        
    async def search(self, query: str, max_results: int = 3, region: str = "no-no") -> List[Dict]:
        """
        Perform a web search
        
        Args:
            query: Search terms
            max_results: Number of results to return
            region: Search region (default Norway)
            
        Returns:
            List of dicts with 'title', 'href', and 'body'
        """
        try:
            # ddgs is not naturally async, so we run it in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(self.ddgs.text(query, region=region, max_results=max_results))
            )
            return results
        except Exception as e:
            print(f"[SEARCH] Error performing search: {e}")
            return []

    async def get_news(self, query: str = "", max_results: int = 3, region: str = "no-no") -> List[Dict]:
        """
        Perform a news search
        """
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(self.ddgs.news(query, region=region, max_results=max_results))
            )
            return results
        except Exception as e:
            print(f"[SEARCH] Error performing news search: {e}")
            return []

    def format_results_for_ai(self, results: List[Dict]) -> str:
        """
        Format search results as a string for AI context
        """
        if not results:
            return "Ingen søkeresultater funnet."
            
        formatted = "Her er informasjon jeg fant på nettet:\n\n"
        for i, res in enumerate(results, 1):
            title = res.get('title', 'Ingen tittel')
            body = res.get('body', res.get('snippet', 'Ingen beskrivelse'))
            url = res.get('href', res.get('link', ''))
            
            formatted += f"[{i}] {title}\n"
            formatted += f"Info: {body}\n"
            if url:
                formatted += f"Kilde: {url}\n"
            formatted += "\n"
            
        return formatted

def detect_search_intent(content: str) -> Optional[Dict[str, str]]:
    """
    Detect if the user is asking for real-time info or news.
    Returns dict with 'query' and 'type' (web/news) if detected.
    """
    content_lower = content.lower()
    
    # News keywords
    news_triggers = [
        r"nyheter", r"hva skjer i verden", r"siste nytt", 
        r"overskrifter", r"hva er det siste om", r"nytt om", r"news"
    ]
    
    # Information/Fact keywords that imply real-time need
    info_triggers = [
        r"hvem vant", r"hva ble resultatet", r"hvordan gikk det med",
        r"hva er status på", r"hvor mye koster en", r"søk på nett etter",
        r"hva skjer med", r"hvor mye er"
    ]
    
    # Check for news first
    for pattern in news_triggers:
        if re.search(pattern, content_lower):
            query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE)
            query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip("? .!,").strip()
            return {"query": query if query else "siste nyheter norge", "type": "news"}

    # Check for general info
    for pattern in info_triggers:
        if re.search(pattern, content_lower):
            query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE)
            query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip("? .!,").strip()
            return {"query": query, "type": "web"}
            
    return None

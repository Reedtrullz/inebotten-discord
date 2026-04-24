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
            return "Ingen søkeresultater funnet. Vennligst svar basert på det du vet, men nevn at du ikke fant noe nytt på nettet akkurat nå."
            
        formatted = "HER ER SANNTIDSINFORMASJON FRA NETTET (Bruk dette som din kilde!):\n\n"
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
        r"hva skjer med", r"hvor mye er", r"fortell meg om", r"hva vet du om"
    ]
    
    query_type = None
    matched_pattern = None
    
    # Check for news first
    for pattern in news_triggers:
        if re.search(pattern, content_lower):
            query_type = "news"
            matched_pattern = pattern
            break

    # Check for general info
    if not query_type:
        for pattern in info_triggers:
            if re.search(pattern, content_lower):
                query_type = "web"
                matched_pattern = pattern
                break
    
    if query_type:
        # Better query cleaning:
        # 1. Remove @inebotten
        query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE)
        # 2. Remove the matched trigger phrase
        query = re.sub(matched_pattern, "", query, flags=re.IGNORECASE)
        # 3. Remove common filler words
        fillers = [r"\bhva er\b", r"\bom\b", r"\ber\b", r"\bdet\b", r"\bi\b", r"\bpå\b"]
        for filler in fillers:
            query = re.sub(filler, "", query, flags=re.IGNORECASE)
        
        query = query.strip("? .!,").strip()
        
        # If query is too short after cleaning, use the original message (minus mention)
        if len(query) < 3:
            query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE).strip("? .!,").strip()
            
        return {"query": query if query else "siste nyheter norge", "type": query_type}
            
    return None

#!/usr/bin/env python3
"""
Search Manager for Inebotten
Uses Tavily (AI-optimized) with Google and DuckDuckGo fallbacks.
"""

# Core imports
import asyncio
import os
import re
from typing import List, Dict, Optional

class SearchManager:
    """
    Manages web search queries using multiple providers for maximum reliability.
    """
    
    def __init__(self):
        # Support both naming conventions (with and without underscore)
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.ddgs = None # Initialize lazily
        
    async def search(self, query: str, max_results: int = 3, region: str = "no-no") -> List[Dict]:
        """
        Perform a web search with multiple fallbacks.
        Order: Tavily (if key) -> Google -> DuckDuckGo
        """
        # 1. Try Tavily (Pro AI Search)
        if self.tavily_api_key:
            try:
                from tavily import TavilyClient
                client = TavilyClient(api_key=self.tavily_api_key)
                # Tavily is blocking, run in executor
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(query=query, search_depth="basic", max_results=max_results)
                )
                if response and response.get('results'):
                    print(f"[SEARCH] Tavily success for: {query}")
                    return [{"title": r['title'], "href": r['url'], "body": r['content']} for r in response['results']]
            except Exception as e:
                print(f"[SEARCH] Tavily failed: {e}")

        # 2. Try Google (Reliable Scraper Fallback)
        try:
            from googlesearch import search as google_search
            print(f"[SEARCH] Trying Google fallback for: {query}")
            loop = asyncio.get_event_loop()
            # googlesearch-python returns an iterator of URLs
            urls = await loop.run_in_executor(
                None,
                lambda: list(google_search(query, num_results=max_results, lang="no"))
            )
            if urls:
                return [{"title": "Søkeresultat", "href": url, "body": "Se kilde for detaljer."} for url in urls]
        except Exception as e:
            print(f"[SEARCH] Google search failed: {e}")

        # 3. Try DuckDuckGo (Last resort)
        try:
            from duckduckgo_search import DDGS
            if not self.ddgs:
                self.ddgs = DDGS()
            print(f"[SEARCH] Trying DuckDuckGo last resort for: {query}")
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: list(self.ddgs.text(query, region=region, max_results=max_results))
            )
            return results
        except Exception as e:
            print(f"[SEARCH] All search providers failed: {e}")
            return []

    async def get_news(self, query: str = "", max_results: int = 3, region: str = "no-no") -> List[Dict]:
        """
        Perform a news search with Tavily news or fallbacks.
        """
        if self.tavily_api_key:
            try:
                from tavily import TavilyClient
                client = TavilyClient(api_key=self.tavily_api_key)
                loop = asyncio.get_event_loop()
                # Tavily doesn't have a separate news endpoint in basic, but we can prefix query
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(query=f"news {query}", search_depth="basic", max_results=max_results)
                )
                if response and response.get('results'):
                    return [{"title": r['title'], "href": r['url'], "body": r['content']} for r in response['results']]
            except Exception as e:
                print(f"[SEARCH] Tavily news failed: {e}")

        # Fallback to general search with "nyheter" prefix
        return await self.search(f"siste nytt {query}", max_results=max_results, region=region)

    def format_results_for_ai(self, results: List[Dict]) -> str:
        """
        Format search results as a string for AI context
        """
        if not results:
            return "Ingen søkeresultater funnet. Vennligst svar basert på det du vet, men nevn at du ikke fant noe nytt på nettet akkurat nå."
            
        formatted = "HER ER SANNTIDSINFORMASJON FRA NETTET (Bruk dette som din kilde!):\n\n"
        for i, res in enumerate(results, 1):
            title = res.get('title', 'Ingen tittel')
            body = res.get('body', res.get('snippet', 'Se kilde for detaljer.'))
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
    
    # News triggers
    news_triggers = [
        r"nyheter", r"hva skjer i verden", r"siste nytt", 
        r"overskrifter", r"hva er det siste om", r"nytt om", r"news"
    ]
    
    # Information/Fact triggers
    info_triggers = [
        r"hvem vant", r"resultatet", r"hvordan gikk det",
        r"hva er status", r"hvor mye koster", r"søk på nett",
        r"hva skjer", r"hvor mye er", r"fortell meg om", r"hva vet du om",
        r"hvem er", r"hva er", r"hvordan fungerer", r"når begynner",
        r"hvilke", r"hvor", r"når", r"hvem", r"kan man", r"finnes det"
    ]
    
    query_type = None
    matched_pattern = None
    
    for pattern in news_triggers:
        if re.search(pattern, content_lower):
            query_type = "news"
            matched_pattern = pattern
            break

    if not query_type:
        for pattern in info_triggers:
            if re.search(pattern, content_lower):
                query_type = "web"
                matched_pattern = pattern
                break
    
    if query_type:
        query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE)
        query = re.sub(matched_pattern, "", query, flags=re.IGNORECASE)
        # Remove common filler words
        fillers = [r"\bhva er\b", r"\bom\b", r"\ber\b", r"\bdet\b", r"\bi\b", r"\bpå\b"]
        for filler in fillers:
            query = re.sub(filler, "", query, flags=re.IGNORECASE)
        
        query = query.strip("? .!,").strip()
        if len(query) < 3:
            query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE).strip("? .!,").strip()
            
        return {"query": query if query else "siste nyheter norge", "type": query_type}
            
    return None

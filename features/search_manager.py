#!/usr/bin/env python3
"""
Search Manager for Inebotten
Uses Tavily (AI-optimized) with Google and DuckDuckGo fallbacks.
"""

# Core imports
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import List, Dict, Optional


_BARE_TEMPORAL_WHAT_HAPPENS = re.compile(
    r"(?:hva|kva|ka)\s+skjer\s+i\s+"
    r"(?:dag|morgen|morgon|morra|overmorgen|overmorgon)\s*[?.!]*",
    re.IGNORECASE,
)


class SearchManager:
    """
    Manages web search queries using multiple providers for maximum reliability.
    """
    
    def __init__(self):
        # Support both naming conventions (with and without underscore)
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.ddgs = None # Initialize lazily

    def _normalize_result(self, result: Dict, provider: str) -> Dict:
        """Normalize provider-specific search results before AI use."""
        title = str(result.get("title") or result.get("name") or "Søkeresultat")
        url = str(result.get("url") or result.get("href") or result.get("link") or "")
        body = str(
            result.get("raw_content")
            or result.get("content")
            or result.get("body")
            or result.get("snippet")
            or "Se kilde for detaljer."
        )
        body = " ".join(body.split())[:3000]
        published_at = (
            result.get("published_at")
            or result.get("published_date")
            or result.get("date")
        )
        freshness = "published" if published_at else ("fetched_only" if url else "unknown")

        return {
            "title": title,
            "url": url,
            "href": url,
            "body": body,
            "provider": provider,
            "fetched_at": datetime.now().isoformat(),
            "published_at": str(published_at) if published_at else None,
            "freshness": freshness,
            "has_deep_content": len(body) > 500,
        }
        
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
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(
                        query=query,
                        search_depth="advanced",
                        max_results=max_results,
                        include_raw_content=True
                    )
                )
                if response and response.get('results'):
                    print("[SEARCH] Tavily advanced search succeeded")
                    return [self._normalize_result(r, "tavily") for r in response["results"]]
            except Exception as exc:
                print(
                    "[SEARCH] Tavily search failed: "
                    f"{type(exc).__name__}"
                )

        # 2. Try Google (Reliable Scraper Fallback)
        try:
            from googlesearch import search as google_search
            print("[SEARCH] Trying Google fallback")
            loop = asyncio.get_running_loop()
            # googlesearch-python returns an iterator of URLs
            urls = await loop.run_in_executor(
                None,
                lambda: list(google_search(query, num_results=max_results, lang="no"))
            )
            if urls:
                return [
                    self._normalize_result(
                        {"title": "Søkeresultat", "url": url, "body": "Se kilde for detaljer."},
                        "google",
                    )
                    for url in urls
                ]
        except Exception as exc:
            print(
                "[SEARCH] Google search failed: "
                f"{type(exc).__name__}"
            )

        # 3. Try DuckDuckGo (Last resort)
        try:
            from duckduckgo_search import DDGS
            if not self.ddgs:
                self.ddgs = DDGS()
            print("[SEARCH] Trying DuckDuckGo last resort")
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None,
                lambda: list(self.ddgs.text(query, region=region, max_results=max_results))
            )
            return [self._normalize_result(result, "duckduckgo") for result in results]
        except Exception as exc:
            print(
                "[SEARCH] All search providers failed: "
                f"{type(exc).__name__}"
            )
            return []

    async def get_news(self, query: str = "", max_results: int = 3, region: str = "no-no") -> List[Dict]:
        """
        Perform a news search with Tavily news or fallbacks.
        """
        if self.tavily_api_key:
            try:
                from tavily import TavilyClient
                client = TavilyClient(api_key=self.tavily_api_key)
                loop = asyncio.get_running_loop()
                # Tavily doesn't have a separate news endpoint in basic, but we can prefix query
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(query=f"news {query}", search_depth="basic", max_results=max_results)
                )
                if response and response.get('results'):
                    return [self._normalize_result(r, "tavily") for r in response["results"]]
            except Exception as exc:
                print(
                    "[SEARCH] Tavily news failed: "
                    f"{type(exc).__name__}"
                )

        # Fallback to general search with "nyheter" prefix
        return await self.search(f"siste nytt {query}", max_results=max_results, region=region)

    def format_results_for_ai(self, results: List[Dict]) -> str:
        """
        Format search results as a string for AI context
        """
        if not results:
            return (
                "Jeg fant ingen ferske kilder akkurat nå, så jeg vil ikke late som jeg har "
                "sjekket dette. Jeg kan svare generelt hvis brukeren ønsker det, men det må "
                "merkes som ikke-verifisert."
            )
            
        formatted = (
            "SØKEKILDER FRA NETTET:\n"
            "Bruk bare kildene under for oppdaterte påstander. Oppgi kilde med tittel "
            "eller URL. Ikke kall noe ferskt bare fordi det ble hentet nå. Hvis "
            "publiseringsdato mangler, si at publiseringsdato ikke var tilgjengelig.\n\n"
        )
        for i, res in enumerate(results, 1):
            title = res.get('title', 'Ingen tittel')
            body = res.get('body', res.get('snippet', 'Se kilde for detaljer.'))
            url = res.get('url') or res.get('href') or res.get('link', '')
            provider = res.get("provider", "ukjent")
            fetched_at = res.get("fetched_at", "ukjent")
            published_at = res.get("published_at") or "ikke tilgjengelig"
            freshness = res.get("freshness", "unknown")
            
            formatted += f"[{i}] {title}\n"
            formatted += f"Provider: {provider} | Hentet: {fetched_at} | Publisert: {published_at} | Friskhet: {freshness}\n"
            formatted += f"Info: {body}\n"
            if url:
                formatted += f"Kilde: {url}\n"
            formatted += "\n"
            
        return formatted

def detect_search_intent(content: str) -> Optional[Dict[str, str]]:
    """
    Detect if the user is asking for real-time info or news.
    Returns dict with 'query' and 'type' (web/news) if detected.
    Uses phrase-level patterns to avoid false positives on ordinary
    or opinion questions.
    """
    content_lower = content.lower()
    temporal_probe = re.sub(
        r"(?:@inebotten|<@!?\d+>)",
        "",
        content_lower,
        flags=re.IGNORECASE,
    ).strip()
    if _BARE_TEMPORAL_WHAT_HAPPENS.fullmatch(temporal_probe):
        logging.debug("search_intent_rejected reason=bare_temporal_complement")
        return None

    # Explicit web language remains authoritative.  The local-knowledge guard
    # below exists only for generic epistemic phrases such as "what do you
    # know about ...", which otherwise steal questions that should be answered
    # from the bot's own memory and feature state.
    explicit_web_pattern = (
        r"\b(?:søk(?:\s+opp)?|slå\s+opp|search|look\s+up)\b"
        r"[^.!?\n]{0,120}\b(?:på\s+nett(?:et)?|web(?:en)?|"
        r"(?:on\s+)?the\s+web)\b"
    )
    explicit_web_request = re.search(
        explicit_web_pattern,
        content_lower,
    ) is not None

    local_subject = (
        r"(?:meg|mæ|me|"
        r"(?:min|mitt|mine|my)\s+"
        r"(?:kalender|calendar|profil|profile|minne|memory|"
        r"påminnelser?|påminningar?|reminders?)|"
        r"(?:kalender(?:en)?|calendar|profil(?:en)?|profile|"
        r"minn(?:et|e)?|memory|påminnels(?:en|er|ene)|"
        r"påminning(?:a|ar|ane)|reminders?)\s+"
        r"(?:min|mitt|mine|mi|my))"
    )
    local_knowledge_patterns = (
        rf"\b(?:hva|kva|ka|what)\s+"
        rf"(?:vet|veit|know|husker|hugsar|remember)\s+"
        rf"(?:du|you)\s+(?:om|about)\s+{local_subject}\b",
        rf"\b(?:fortell|fortel|tell)\s+(?:meg|mæ|me)\s+"
        rf"(?:om|about)\s+{local_subject}\b",
    )
    if not explicit_web_request and any(
        re.search(pattern, content_lower)
        for pattern in local_knowledge_patterns
    ):
        logging.debug("search_intent_rejected reason=local_knowledge")
        return None

    # News triggers
    news_triggers = [
        r"nyheter", r"hva skjer i verden", r"siste nytt",
        r"overskrifter", r"hva er det siste om", r"nytt om", r"news"
    ]

    info_phrase_triggers = [
        r"\bhvem vant\b", r"\bresultatet\b", r"\bhvordan gikk det\b",
        r"\bhva er status\b", r"\bhvor mye koster\b", r"\bhva koster\b",
        r"\bkva kostar\b", r"\bkor mykje kostar\b", r"\bsøk på nett\b",
        r"\bhva skjer i\b", r"\bhvor mye er\b", r"\bfortell meg om\b",
        r"\bhva vet du om\b", r"\bhvem er\b", r"\bhvordan fungerer\b",
        r"\bnår begynner\b", r"\bhvilke\b", r"\bkan man\b", r"\bfinnes det\b",
        r"\bhva er\b", r"\bhvilket\b", r"\bnår\b", r"\bhvor\b", r"\bhvordan\b", r"\bhvem\b",
    ]

    opinion_blocklist = [
        r"synes du om", r"liker du", r"mener du",
        r"tror du", r"bor du", r"kommer du fra", r"er du",
    ]

    query_type = "web" if explicit_web_request else None
    matched_pattern = None

    for pattern in news_triggers:
        if re.search(pattern, content_lower):
            query_type = "news"
            matched_pattern = pattern
            break

    if not query_type:
        for pattern in info_phrase_triggers:
            if re.search(pattern, content_lower):
                query_type = "web"
                matched_pattern = pattern
                break

    if query_type:
        for opinion in opinion_blocklist:
            if not explicit_web_request and re.search(opinion, content_lower):
                logging.debug(
                    "search_intent_rejected reason=opinion_pattern"
                )
                return None

        query = re.sub(r"@inebotten", "", content, flags=re.IGNORECASE)
        if explicit_web_request:
            query = re.sub(
                r"\b(?:søk(?:\s+opp)?|slå\s+opp|search|look\s+up)\b",
                "",
                query,
                flags=re.IGNORECASE,
            )
            query = re.sub(
                r"\b(?:på\s+nett(?:et)?|web(?:en)?|"
                r"(?:on\s+)?the\s+web)\b",
                "",
                query,
                flags=re.IGNORECASE,
            )
            query = re.sub(
                r"^\s*(?:etter|for)\s+",
                "",
                query,
                flags=re.IGNORECASE,
            )
        elif matched_pattern is not None:
            query = re.sub(matched_pattern, "", query, flags=re.IGNORECASE)
        query = query.strip("? .!,").strip()

        if len(query) < 3:
            logging.debug(
                "search_intent_rejected reason=query_too_short"
            )
            return None

        # Vague queries that are usually small talk or handled by other intents
        vague_queries = ["nytt", "skjer", "det", "greia", "planen", "opplegget"]
        if query.lower() in vague_queries:
            logging.debug(
                "search_intent_rejected reason=query_too_vague"
            )
            return None

        return {"query": query, "type": query_type}

    return None

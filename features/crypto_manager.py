#!/usr/bin/env python3
"""
Crypto Price Manager for Inebotten
Fetches cryptocurrency prices using CoinGecko API
"""

import re
import aiohttp
import asyncio
from datetime import datetime


_LEADING_INVOCATION = re.compile(
    r"^\s*(?:@inebotten\b|<@!?\d+>)\s*[:,;-]?\s*",
    re.IGNORECASE,
)
_POLITE_PREFIX = re.compile(
    r"^(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s+",
    re.IGNORECASE,
)
_NON_REQUEST_PATTERNS = (
    re.compile(r"\b(?:ikke|ikkje|not|never|don['’]t|do\s+not)\b", re.IGNORECASE),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:sa|skrev|skreiv|leste|las)\b|"
        r"^i\s+(?:said|wrote|read)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva\s+skjer\s+hvis|kva\s+skjer\s+om|ka\s+skjer\s+hvis|"
        r"what\s+happens\s+if|hvis|om|if)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:eksempel|example|hva\s+betyr|kva\s+tyder|hvordan\s+skriver|"
        r"korleis\s+skriv|how\s+do\s+i\s+(?:say|write)|"
        r"what\s+does\b.*\bmean)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:vurderer|tenker\s+på)\b|"
        r"^i(?:'m|\s+am)\s+(?:considering|thinking\s+about)\b",
        re.IGNORECASE,
    ),
)
_TRAILING_POLITENESS = re.compile(
    r"\s*,?\s*(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[?!.]*$",
    re.IGNORECASE,
)
_LEADING_COURTESY_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s*"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))|"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*,?\s*"
    r"(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please))\s*,?\s*",
    re.IGNORECASE,
)
_TRAILING_COURTESY = re.compile(
    r"(?:\s*,\s*|\s+)(?:(?:om|hvis|viss)\s+du\s+kan|"
    r"(?:om|hvis|viss)\s+du\s+har\s+tid|når\s+du\s+har\s+tid|"
    r"if\s+you\s+can|if\s+you\s+have\s+(?:time|a\s+moment)|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*[?!.]*$",
    re.IGNORECASE,
)
_MARKET_CONTEXT = r"(?:crypto|krypto|coin|token)"
_PRICE_PATTERNS = (
    # Value questions: "what is Bitcoin worth?". Unknown ordinary nouns are
    # still rejected by the known-asset/explicit-market checks below.
    re.compile(
        r"^(?:(?:what\s+is)|(?:(?:hva|kva|ka)\s+er))\s+"
        r"(?P<asset>.+?)\s+(?:worth|verdt)$",
        re.IGNORECASE,
    ),
    # Action-first suffix forms: "show the bitcoin price".
    re.compile(
        r"^(?:vis(?:e)?|syn(?:e)?|fortell(?:e)?|fortel|show|tell)"
        rf"(?:\s+(?:meg|mæ|me))?\s+(?:(?:den|the)\s+)?"
        rf"(?P<asset>.+?)\s+(?:{_MARKET_CONTEXT}\s+)?"
        r"(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?)$",
        re.IGNORECASE,
    ),
    # Question-first suffix forms: "what is the bitcoin price".
    re.compile(
        r"^(?:hva|kva|ka|what)\s+(?:er|is)\s+(?:(?:den|the)\s+)?"
        rf"(?P<asset>.+?)\s+(?:{_MARKET_CONTEXT}\s+)?"
        r"(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?)$",
        re.IGNORECASE,
    ),
    # Direct, compact forms: "bitcoin pris", "the graph price".
    re.compile(
        rf"^(?P<asset>.+?)\s+(?:{_MARKET_CONTEXT}\s+)?"
        r"(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?)$",
        re.IGNORECASE,
    ),
    # Noun-first forms: "prisen på bitcoin", "the price of bitcoin".
    re.compile(
        r"^(?:(?:hva|kva|ka|what)\s+(?:er|is)\s+)?"
        rf"(?:(?:den|the)\s+)?(?:{_MARKET_CONTEXT}\s+)?"
        r"(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?)"
        r"\s+(?:(?:på|for|til|of)\s+)?(?P<asset>.+)$",
        re.IGNORECASE,
    ),
    # Natural show/tell requests after an optional polite prefix is removed.
    re.compile(
        r"^(?:vis(?:e)?|syn(?:e)?|fortell(?:e)?|fortel|sjekk(?:e)?|"
        r"show|tell|check)"
        r"(?:\s+(?:meg|mæ|me))?\s+(?:(?:den|the)\s+)?"
        rf"(?:{_MARKET_CONTEXT}\s+)?"
        r"(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?)"
        r"\s+(?:(?:på|for|til|of)\s+)?(?P<asset>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva\s+koster|kva\s+kostar|ka\s+koster|kor\s+mykje\s+kostar|"
        r"how\s+much\s+(?:is|does))\s+(?P<asset>.+?)(?:\s+cost)?$",
        re.IGNORECASE,
    ),
)
_BLOCKED_GENERIC_ASSETS = frozenset(
    {
        "a",
        "an",
        "den",
        "det",
        "dette",
        "en",
        "et",
        "flight",
        "freedom",
        "happiness",
        "prediction",
        "show",
        "the",
        "vise",
        "å",
    }
)
_WRAPPER_ASSET_TOKENS = frozenset(
    {
        "den", "det", "the", "a", "an", "en", "et", "ei",
        "show", "tell", "vis", "vise", "fortell", "fortelle",
        "me", "meg", "mæ", "what", "hva", "kva", "ka", "is", "er",
    }
)


def _prepare_price_request(message_content):
    if not isinstance(message_content, str):
        return None
    content = _LEADING_INVOCATION.sub("", message_content, count=1).strip()
    content = _LEADING_COURTESY_REQUEST.sub("", content, count=1).strip()
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = _TRAILING_COURTESY.sub("", content).strip()
    if not content or any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _POLITE_PREFIX.sub("", content, count=1).strip()
    if any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = re.sub(r"\bwhat['’]s\b", "what is", content, flags=re.IGNORECASE)
    return content.rstrip("?!.").strip()


def _clean_asset(raw_asset):
    asset = raw_asset.strip().rstrip("?!.;,:").strip()
    if len(asset) >= 2 and (asset[0], asset[-1]) in {
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    }:
        asset = asset[1:-1].strip()
    asset = re.sub(
        rf"^(?:{_MARKET_CONTEXT})\s+|\s+(?:{_MARKET_CONTEXT})$",
        "",
        asset,
        flags=re.IGNORECASE,
    ).strip()
    return re.sub(r"\s+", " ", asset)


class CryptoManager:
    """
    Manages cryptocurrency price queries using CoinGecko API
    Supports thousands of tokens including FOX, VULT, etc.
    """
    
    def __init__(self):
        self.api_base = "https://api.coingecko.com/api/v3"
        self.session = None
        self.cache = {}
        self.cache_time = 120  # Cache prices for 2 minutes (reduce API calls)
        
        # Common crypto mappings (name -> CoinGecko ID)
        self.crypto_mappings = {
            'bitcoin': 'bitcoin', 'btc': 'bitcoin',
            'ethereum': 'ethereum', 'eth': 'ethereum',
            'solana': 'solana', 'sol': 'solana',
            'cardano': 'cardano', 'ada': 'cardano',
            'polkadot': 'polkadot', 'dot': 'polkadot',
            'ripple': 'ripple', 'xrp': 'ripple',
            'dogecoin': 'dogecoin', 'doge': 'dogecoin',
            'litecoin': 'litecoin', 'ltc': 'litecoin',
            'shiba inu': 'shiba-inu', 'shib': 'shiba-inu',
            'chainlink': 'chainlink', 'link': 'chainlink',
            'polygon': 'matic-network', 'matic': 'matic-network',
            'avalanche': 'avalanche-2', 'avax': 'avalanche-2',
            'uniswap': 'uniswap', 'uni': 'uniswap',
            'fantom': 'fantom', 'ftm': 'fantom',
            'arbitrum': 'arbitrum', 'arb': 'arbitrum',
            'optimism': 'optimism', 'op': 'optimism',
            'cosmos': 'cosmos', 'atom': 'cosmos',
            'near': 'near', 'near protocol': 'near',
            'algorand': 'algorand', 'algo': 'algorand',
            'vechain': 'vechain', 'vet': 'vechain',
            'filecoin': 'filecoin', 'fil': 'filecoin',
            'internet computer': 'internet-computer', 'icp': 'internet-computer',
            'the graph': 'the-graph', 'grt': 'the-graph',
            'aave': 'aave',
            'maker': 'maker', 'mkr': 'maker',
            'lido dao': 'lido-dao', 'ldo': 'lido-dao',
            'pepe': 'pepe',
            'floki': 'floki',
            'bonk': 'bonk',
            'render': 'render-token', 'rndr': 'render-token',
            'injective': 'injective-protocol', 'inj': 'injective-protocol',
            'immutable': 'immutable-x', 'imx': 'immutable-x',
            'sui': 'sui', 'sui network': 'sui',
            'sei': 'sei-network', 'sei network': 'sei-network',
            'celestia': 'celestia', 'tia': 'celestia',
            'dymension': 'dymension', 'dym': 'dymension',
            'fox': 'fox-token', 'shapeshift': 'fox-token',
            'vult': 'vulture-2', 'vulture': 'vulture-2',
        }
        
        # Stock symbols are recognized only to return an explicit unsupported response.
        self.stock_symbols = {
            'apple': 'AAPL', 'aapl': 'AAPL',
            'microsoft': 'MSFT', 'msft': 'MSFT',
            'tesla': 'TSLA', 'tsla': 'TSLA',
            'amazon': 'AMZN', 'amzn': 'AMZN',
            'google': 'GOOGL', 'googl': 'GOOGL', 'alphabet': 'GOOGL',
            'meta': 'META', 'facebook': 'META',
            'nvidia': 'NVDA', 'nvda': 'NVDA',
            'netflix': 'NFLX', 'nflx': 'NFLX',
            'equinor': 'EQNR', 'eqnr': 'EQNR',
            'norsk hydro': 'NHY', 'nhy': 'NHY',
        }
    
    async def _get_session(self):
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    'Accept': 'application/json',
                    'User-Agent': 'InebottenBot/1.0'
                }
            )
        return self.session
    
    def parse_price_query(self, message_content):
        """
        Parse price queries
        Examples:
        - "bitcoin pris"
        - "btc price"
        - "fox price"
        - "vult verdi"
        """
        content = _prepare_price_request(message_content)
        if not content:
            return None

        for pattern in _PRICE_PATTERNS:
            match = pattern.fullmatch(content)
            if match:
                explicit_crypto_context = re.search(
                    rf"\b{_MARKET_CONTEXT}\b",
                    content,
                    re.IGNORECASE,
                ) is not None
                asset = _clean_asset(match.group("asset"))
                raw_asset_key = asset.casefold()
                if (
                    raw_asset_key in self.crypto_mappings
                    or raw_asset_key in self.stock_symbols
                ):
                    normalized_asset = asset
                else:
                    normalized_asset = re.sub(
                        r"^(?:the|a|an|den|det|en|ei|et)\s+",
                        "",
                        asset,
                        count=1,
                        flags=re.IGNORECASE,
                    ).strip()
                asset_key = normalized_asset.casefold()
                asset_tokens = tuple(re.findall(r"[^\W_]+", asset_key, re.UNICODE))
                if (
                    not normalized_asset
                    or asset_key in _BLOCKED_GENERIC_ASSETS
                    or (
                        asset_tokens
                        and all(token in _WRAPPER_ASSET_TOKENS for token in asset_tokens)
                    )
                ):
                    return None
                
                # Check if it's a known crypto
                if asset_key in self.crypto_mappings:
                    return {
                        'type': 'crypto', 
                        'asset': normalized_asset,
                        'coin_id': self.crypto_mappings[asset_key],
                        'display_name': normalized_asset.upper()
                    }

                # Check if it's a stock
                if asset_key in self.stock_symbols:
                    return {
                        'type': 'stock',
                        'asset': normalized_asset,
                        'symbol': self.stock_symbols[asset_key],
                    }

                # Unknown crypto - try to search by the name directly
                # only for explicit market/crypto wording. Generic phrases like
                # "hva koster det å fly ..." should fall through to web search.
                if (
                    len(normalized_asset) >= 2
                    and re.fullmatch(r"[\w -]+", normalized_asset, re.UNICODE)
                    and explicit_crypto_context
                ):
                    return {
                        'type': 'crypto_search',
                        'asset': normalized_asset,
                        'coin_id': asset_key,
                        'display_name': normalized_asset.upper()
                    }
        
        return None
    
    async def get_price(self, query):
        """Get real price from CoinGecko API"""
        if not query:
            return None
        
        asset_type = query['type']
        
        if asset_type == 'stock':
            return {
                'type': 'unsupported_stock',
                'symbol': query.get('symbol', query.get('asset', '')).upper(),
                'name': query.get('asset', 'aksje').title(),
            }
        
        # Get crypto price from CoinGecko
        coin_id = query.get('coin_id', query.get('asset', ''))
        
        # Check cache first
        cache_key = coin_id.lower()
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if (datetime.now() - cached['timestamp']).seconds < self.cache_time:
                print(f"[CRYPTO] Using cached price for {coin_id}")
                return cached['data']
        
        try:
            session = await self._get_session()
            url = f"{self.api_base}/coins/{coin_id}"
            params = {
                'localization': 'false',
                'tickers': 'false',
                'market_data': 'true',
                'community_data': 'false',
                'developer_data': 'false',
                'sparkline': 'false'
            }
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    market_data = data.get('market_data', {})
                    current_price = market_data.get('current_price', {})
                    price_usd = current_price.get('usd', 0)
                    
                    if price_usd == 0:
                        return None
                    
                    price_change = market_data.get('price_change_percentage_24h', 0)
                    high_24h = market_data.get('high_24h', {}).get('usd', 0)
                    low_24h = market_data.get('low_24h', {}).get('usd', 0)
                    market_cap = market_data.get('market_cap', {}).get('usd', 0)
                    
                    result = {
                        'symbol': data.get('symbol', query['display_name']).upper(),
                        'name': data.get('name', query['asset'].title()),
                        'type': 'crypto',
                        'price': price_usd,
                        'currency': 'USD',
                        'change_24h': round(price_change, 2),
                        'high_24h': high_24h,
                        'low_24h': low_24h,
                        'market_cap': market_cap,
                        'image': data.get('image', {}).get('small', ''),
                    }
                    
                    # Cache the result
                    self.cache[cache_key] = {
                        'data': result,
                        'timestamp': datetime.now()
                    }
                    
                    return result
                    
                elif resp.status == 404:
                    # Coin not found - try search API
                    return await self._search_and_get_price(query)
                else:
                    error_text = await resp.text()
                    print(f"[CRYPTO] CoinGecko error {resp.status}: {error_text[:200]}")
                    return None
                    
        except aiohttp.ClientError as e:
            print(f"[CRYPTO] API connection error: {e}")
            return None
        except Exception as e:
            print(f"[CRYPTO] Error fetching price: {e}")
            return None
    
    async def _search_and_get_price(self, query):
        """Search for coin and get price if exact ID not found"""
        try:
            search_term = query.get('asset', '')
            session = await self._get_session()
            url = f"{self.api_base}/search"
            
            async with session.get(url, params={'query': search_term}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    coins = data.get('coins', [])
                    
                    if coins:
                        # Use first match
                        coin = coins[0]
                        query['coin_id'] = coin['id']
                        query['display_name'] = coin['symbol'].upper()
                        # Retry with correct ID
                        return await self.get_price(query)
                        
            return None
        except Exception as e:
            print(f"[CRYPTO] Search error: {e}")
            return None
    
    def format_price(self, data, lang='no'):
        """Format price for display"""
        if not data:
            return None

        if data.get('type') == 'unsupported_stock':
            symbol = data.get('symbol', '').upper()
            if lang == 'no':
                return (
                    f"📊 **{symbol}**\n"
                    "Aksjekurser er ikke koblet til en live datakilde ennå, "
                    "så jeg viser ikke simulerte tall."
                )
            return (
                f"📊 **{symbol}**\n"
                "Stock prices are not connected to a live data source yet, "
                "so I will not show simulated numbers."
            )
        
        symbol = data['symbol']
        name = data['name']
        price = data['price']
        change = data['change_24h']
        
        # Format price
        if price < 1:
            price_str = f"${price:.4f}"
        elif price < 100:
            price_str = f"${price:.2f}"
        else:
            price_str = f"${price:,.2f}"
        
        # Change indicator
        if change > 0:
            change_emoji = '📈'
            change_str = f"+{change:.1f}%"
        elif change < 0:
            change_emoji = '📉'
            change_str = f"{change:.1f}%"
        else:
            change_emoji = '➡️'
            change_str = "0.0%"
        
        # Type emoji
        type_emoji = '₿' if data['type'] == 'crypto' else '📊'
        
        if lang == 'no':
            lines = [
                f"{type_emoji} **{name}** ({symbol})",
                f"💵 **Pris:** {price_str}",
                f"{change_emoji} **24h:** {change_str}",
                f"📈 Høy: ${data['high_24h']:,.2f}",
                f"📉 Lav: ${data['low_24h']:,.2f}",
            ]
        else:
            lines = [
                f"{type_emoji} **{name}** ({symbol})",
                f"💵 **Price:** {price_str}",
                f"{change_emoji} **24h:** {change_str}",
                f"📈 High: ${data['high_24h']:,.2f}",
                f"📉 Low: ${data['low_24h']:,.2f}",
            ]
        
        return "\n".join(lines)
    
    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None


def parse_price_command(message_content):
    """Convenience function to parse price command"""
    manager = CryptoManager()
    return manager.parse_price_query(message_content)

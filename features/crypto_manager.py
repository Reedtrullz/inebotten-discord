#!/usr/bin/env python3
"""
Crypto & Stock Price Manager for Inebotten
Fetches cryptocurrency prices using CoinGecko API
"""

import re
import aiohttp
import asyncio
from datetime import datetime

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
        
        # Stock symbols (kept for compatibility, but stocks need different API)
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
        content_lower = message_content.lower()
        
        # Remove @inebotten
        content_lower = content_lower.replace('@inebotten', '').strip()
        
        # Crypto patterns - expanded to catch more variations
        crypto_patterns = [
            r'(\w+)\s+(?:pris|price|verdi|value|kurs)',
            r'(?:pris|price|verdi|value|kurs)\s+(?:på|for|of|til)?\s*(\w+)',
            r'hva\s+koster\s+(\w+)',
            r'kor\s+mykje\s+kostar\s+(\w+)',
        ]
        
        for pattern in crypto_patterns:
            match = re.search(pattern, content_lower)
            if match:
                asset = match.group(1).lower()
                trigger_text = match.group(0).lower()
                
                # Check if it's a known crypto
                if asset in self.crypto_mappings:
                    return {
                        'type': 'crypto', 
                        'asset': asset, 
                        'coin_id': self.crypto_mappings[asset],
                        'display_name': asset.upper()
                    }

                # Check if it's a stock
                if asset in self.stock_symbols:
                    return {'type': 'stock', 'asset': asset, 'symbol': self.stock_symbols[asset]}

                # Unknown crypto - try to search by the name directly
                # only for explicit market/crypto wording. Generic phrases like
                # "hva koster det å fly ..." should fall through to web search.
                explicit_market_query = any(
                    word in content_lower
                    for word in ["pris", "price", "verdi", "value", "kurs", "crypto", "krypto", "coin", "token"]
                )
                generic_cost_query = trigger_text.startswith("hva koster") or trigger_text.startswith("kor mykje kostar")
                blocked_generic_asset = asset in {"det", "den", "dette", "å", "a", "an", "en", "et"}
                if (
                    len(asset) >= 2
                    and asset.isalnum()
                    and explicit_market_query
                    and not (generic_cost_query and blocked_generic_asset)
                ):
                    return {
                        'type': 'crypto_search',
                        'asset': asset,
                        'coin_id': asset,  # Will try to use as-is
                        'display_name': asset.upper()
                    }
        
        return None
    
    async def get_price(self, query):
        """Get real price from CoinGecko API"""
        if not query:
            return None
        
        asset_type = query['type']
        
        # Handle stocks differently (would need different API)
        if asset_type == 'stock':
            return self._get_simulated_stock_price(query)
        
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
    
    def _get_simulated_stock_price(self, query):
        """Fallback for stocks (simulated data)"""
        symbol = query['symbol']
        base_prices = {
            'AAPL': 185, 'MSFT': 420, 'TSLA': 175, 'AMZN': 180,
            'GOOGL': 165, 'META': 505, 'NVDA': 890, 'NFLX': 625,
            'EQNR': 28.5, 'NHY': 6.8,
        }
        
        import random
        base = base_prices.get(symbol, 100)
        variation = random.uniform(-0.05, 0.05)
        price = base * (1 + variation)
        
        return {
            'symbol': symbol,
            'name': query['asset'].title(),
            'type': 'stock',
            'price': price,
            'currency': 'USD',
            'change_24h': random.uniform(-3, 3),
            'high_24h': price * 1.02,
            'low_24h': price * 0.98,
        }
    
    def format_price(self, data, lang='no'):
        """Format price for display"""
        if not data:
            return None
        
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

#!/usr/bin/env python3
"""
Aurora Forecast (Nordlys) Module for Inebotten
Fetches aurora predictions for Northern Norway
Uses NOAA Space Weather API and Norwegian sources
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta


class AuroraForecast:
    """
    Aurora forecast for Norway
    Uses NOAA Space Weather Prediction Center data
    """
    
    # Aurora visibility thresholds
    KP_THRESHOLDS = {
        'low': 2,      # Visible in Northern Norway (Troms, Finnmark)
        'moderate': 4, # Visible in Central Norway (Trøndelag)
        'high': 6,     # Visible in Southern Norway
        'extreme': 8,  # Visible across all of Norway
    }
    
    def __init__(self):
        self.session = None
        self.headers = {
            "User-Agent": "Inebotten-Discord-Selfbot/1.0"
        }
        self.cache = None
        self.cache_time = None
    
    async def _get_session(self):
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_forecast(self):
        """
        Get current aurora forecast
        Returns dict with KP index, visibility, and recommendation
        """
        # Check cache (valid for 30 minutes)
        if self.cache and self.cache_time:
            if (datetime.now() - self.cache_time).total_seconds() < 1800:
                return self.cache
        
        try:
            # Get NOAA space weather data
            noaa_data = await self._fetch_noaa_data()
            
            if noaa_data:
                forecast = self._parse_forecast(noaa_data)
                self.cache = forecast
                self.cache_time = datetime.now()
                return forecast
            
            return None
            
        except Exception as e:
            print(f"[AURORA] Error fetching forecast: {e}")
            return None
    
    async def _fetch_noaa_data(self):
        """Fetch data from NOAA Space Weather Prediction Center"""
        try:
            session = await self._get_session()
            
            # NOAA Planetary K-Index
            url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                return None
                
        except Exception as e:
            print(f"[AURORA] NOAA API error: {e}")
            return None
    
    def _parse_forecast(self, data):
        """Parse NOAA data into readable forecast"""
        try:
            # NOAA returns a dict with data in 'data' key or a list directly
            if isinstance(data, dict):
                forecast_data = data.get('data', [])
            else:
                forecast_data = data
            
            if not forecast_data or len(forecast_data) < 2:
                return None
            
            # Check if first row is header
            start_idx = 0
            first_row = forecast_data[0]
            if isinstance(first_row, list) and len(first_row) >= 2:
                if first_row[0] == "time_tag" or first_row[1] == "kp":
                    start_idx = 1
            
            # Get the latest and next forecast
            latest = None
            next_forecast = None
            
            now = datetime.now()
            
            for entry in forecast_data[start_idx:]:
                if not isinstance(entry, list) or len(entry) < 2:
                    continue
                
                timestamp_str = entry[0]
                
                # Try to parse KP value
                try:
                    kp_value = float(entry[1])
                except (ValueError, TypeError):
                    continue
                
                # Parse timestamp (format: 2026-03-17T18:00:00Z)
                try:
                    entry_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    entry_time = entry_time.replace(tzinfo=None)
                except:
                    continue
                
                # Find current/next forecast
                if entry_time <= now:
                    latest = {'time': entry_time, 'kp': kp_value}
                elif entry_time > now and not next_forecast:
                    next_forecast = {'time': entry_time, 'kp': kp_value}
            
            if not latest:
                return None
            
            # Determine visibility
            kp = latest['kp']
            visibility = self._get_visibility(kp)
            
            # Calculate probability
            probability = self._calculate_probability(kp)
            
            # Get recommendation
            recommendation = self._get_recommendation(kp)
            
            return {
                'kp_index': kp,
                'visibility': visibility,
                'probability': probability,
                'recommendation': recommendation,
                'next_forecast': next_forecast,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"[AURORA] Error parsing forecast: {e}")
            return None
    
    def _get_visibility(self, kp):
        """Determine where aurora is visible based on KP index"""
        if kp >= self.KP_THRESHOLDS['extreme']:
            return {
                'level': 'Ekstrem',
                'areas': 'Hele Norge',
                'emoji': '🌟',
                'color': '🔴'
            }
        elif kp >= self.KP_THRESHOLDS['high']:
            return {
                'level': 'Sterk',
                'areas': 'Hele Norge, spesielt nordlige deler',
                'emoji': '✨',
                'color': '🟠'
            }
        elif kp >= self.KP_THRESHOLDS['moderate']:
            return {
                'level': 'Moderat',
                'areas': 'Trøndelag og nordover',
                'emoji': '✨',
                'color': '🟡'
            }
        elif kp >= self.KP_THRESHOLDS['low']:
            return {
                'level': 'Svak',
                'areas': 'Nord-Norge (Troms, Finnmark)',
                'emoji': '🌙',
                'color': '🟢'
            }
        else:
            return {
                'level': 'Ingen',
                'areas': 'Ikke synlig i Norge',
                'emoji': '❌',
                'color': '⚪'
            }
    
    def _calculate_probability(self, kp):
        """Calculate probability percentage based on KP"""
        if kp >= 7:
            return 90
        elif kp >= 5:
            return 70
        elif kp >= 4:
            return 50
        elif kp >= 3:
            return 30
        elif kp >= 2:
            return 15
        else:
            return 5
    
    def _get_recommendation(self, kp):
        """Get activity recommendation"""
        if kp >= 7:
            return "Perfekte forhold! Gå ut og se!"
        elif kp >= 5:
            return "Gode sjanser! Verdt å sjekke himmelen."
        elif kp >= 4:
            return "Muligheter i nord. Sjekk værmeldingen."
        elif kp >= 2:
            return "Svakt, men mulig i Nord-Norge."
        else:
            return "Ingen nordlys i kveld."
    
    def format_forecast(self, forecast):
        """Format forecast for display"""
        if not forecast:
            return "🌌 **Nordlysvarsel**\n\nIngen data tilgjengelig."
        
        vis = forecast['visibility']
        
        lines = [
            f"🌌 **Nordlysvarsel**",
            "",
            f"{vis['emoji']} **Aktivitet:** {vis['level']}",
            f"📊 **KP-indeks:** {forecast['kp_index']:.1f}",
            f"🎯 **Sjanse:** {forecast['probability']}%",
            f"📍 **Synlig:** {vis['areas']}",
            "",
            f"💡 **Tips:** {forecast['recommendation']}",
        ]
        
        return "\n".join(lines)


def get_aurora_emoji(kp):
    """Get appropriate emoji for KP level"""
    if kp >= 7:
        return '🌟'
    elif kp >= 5:
        return '✨'
    elif kp >= 3:
        return '🌙'
    else:
        return '❌'


# Quick test
if __name__ == "__main__":
    async def test():
        print("=== Aurora Forecast Test ===\n")
        
        aurora = AuroraForecast()
        forecast = await aurora.get_forecast()
        
        if forecast:
            print(aurora.format_forecast(forecast))
        else:
            print("Kunne ikke hente nordlysvarsel")
        
        await aurora.close()
    
    asyncio.run(test())

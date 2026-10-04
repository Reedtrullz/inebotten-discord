#!/usr/bin/env python3
"""
MET.no Weather API Integration
Fetches real weather data from the Norwegian Meteorological Institute
Free to use with proper attribution
"""

import aiohttp
import asyncio
import re
from datetime import datetime, timedelta, timezone
import math
import time


class METWeatherAPI:
    """
    Client for MET.no Locationforecast API
    Documentation: https://api.met.no/weatherapi/locationforecast/2.0/documentation
    """
    
    BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    
    def __init__(self, *, now=None, monotonic=None):
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.session = None
        # Required User-Agent per MET.no terms of service
        self.headers = {
            "User-Agent": "Inebotten-Discord-Selfbot/1.0 https://github.com/Reedtrullz/inebotten-discord"
        }
        self.cache = {}
        self.cache_time = 600  # Cache for 10 minutes
    
    async def _get_session(self):
        if getattr(self, '_closed', False):
            raise RuntimeError('weather_closed')
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def close(self):
        self._closed = True
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_weather(self, lat=59.9139, lon=10.7522, location_name="Oslo"):
        """
        Get current weather for a location
        
        Args:
            lat: Latitude (default Oslo: 59.9139)
            lon: Longitude (default Oslo: 10.7522)
            location_name: Name of location for display
        
        Returns:
            dict with weather data or None on error
        """
        cache_key = f"{lat:.4f},{lon:.4f}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            from features.forecast_service import aware_time
            expires = cached_data.get("expires_at")
            if ((self.monotonic() - cached_time) < self.cache_time
                    and (not expires or aware_time(self.now()) < aware_time(expires))):
                return dict(cached_data)
        
        try:
            session = await self._get_session()
            url = f"{self.BASE_URL}?lat={lat}&lon={lon}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    weather = self._parse_weather(data, location_name)
                    
                    # Cache the result
                    if weather is not None:
                        self.cache[cache_key] = (weather, self.monotonic())
                    return weather
                else:
                    print(f"[WEATHER] API error: {response.status}")
                    return None
                    
        except Exception as e:
            print(f"[WEATHER] Error fetching weather: {e}")
            return None
    
    def _parse_weather(self, data, location_name):
        """Keep forecast point/expiry times; unknown measurements stay unknown."""
        try:
            from features.forecast_service import aware_time
            timeseries = data["properties"]["timeseries"]
            if not timeseries:
                return None
            now = aware_time(self.now())
            points = [(aware_time(entry["time"]), entry) for entry in timeseries]
            past = [point for point in points if point[0] <= now]
            valid_at, current = max(past, key=lambda p: p[0]) if past else min(points, key=lambda p: p[0])
            details = current["data"].get("instant", {}).get("details", {})
            def numeric(name, precision=0, source=details):
                value = source.get(name)
                return round(value, precision) if type(value) in (int, float) and math.isfinite(value) else None
            temperature = numeric("air_temperature")
            if temperature is None:
                return None
            period = next((hours for hours in (1, 6, 12) if f"next_{hours}_hours" in current["data"]), None)
            symbol = current["data"].get(f"next_{period}_hours", {}).get("summary", {}).get("symbol_code")
            range_details = current["data"].get("next_6_hours", {}).get("details", {})
            return {
                "location": location_name, "temp": temperature,
                "temp_high": numeric("air_temperature_max", source=range_details),
                "temp_low": numeric("air_temperature_min", source=range_details),
                "wind_speed": numeric("wind_speed", 1), "humidity": numeric("relative_humidity"),
                "condition": self._translate_symbol(symbol) if symbol else None,
                "symbol_code": symbol, "valid_at": valid_at.isoformat(),
                "expires_at": (valid_at + timedelta(hours=period)).isoformat() if period else None,
                "timestamp": now.isoformat(),
                "source_updated_at": data["properties"].get("meta", {}).get("updated_at"),
            }
        except (ValueError, TypeError, KeyError, IndexError):
            return None

    def _translate_symbol(self, symbol_code):
        """
        Translate MET.no symbol code to Norwegian condition
        """
        translations = {
            'clearsky': 'Klarvær',
            'clearsky_day': 'Klarvær',
            'clearsky_night': 'Klarvær',
            'fair': 'Lettskyet',
            'fair_day': 'Lettskyet',
            'fair_night': 'Lettskyet',
            'partlycloudy': 'Delvis skyet',
            'partlycloudy_day': 'Delvis skyet',
            'partlycloudy_night': 'Delvis skyet',
            'cloudy': 'Skyet',
            'rain': 'Regn',
            'rainshowers': 'Regnbyger',
            'rainshowers_day': 'Regnbyger',
            'rainshowers_night': 'Regnbyger',
            'lightrain': 'Lett regn',
            'lightrainshowers': 'Lette regnbyger',
            'heavyrain': 'Kraftig regn',
            'heavyrainshowers': 'Kraftige regnbyger',
            'snow': 'Snø',
            'snowshowers': 'Snøbyger',
            'lightsnow': 'Lett snø',
            'heavysnow': 'Kraftig snø',
            'sleet': 'Sludd',
            'sleetshowers': 'Sluddbyger',
            'thunder': 'Torden',
            'thundershowers': 'Tordenbyger',
            'fog': 'Tåke',
            'wind': 'Vindfullt'
        }
        
        return translations.get(symbol_code, 'Ukjent')
    
    def get_weather_emoji(self, symbol_code):
        """
        Get emoji for weather condition
        """
        emoji_map = {
            'clearsky': '☀️',
            'clearsky_day': '☀️',
            'clearsky_night': '🌙',
            'fair': '🌤️',
            'fair_day': '🌤️',
            'fair_night': '🌙',
            'partlycloudy': '⛅',
            'partlycloudy_day': '⛅',
            'partlycloudy_night': '☁️',
            'cloudy': '☁️',
            'rain': '🌧️',
            'rainshowers': '🌦️',
            'rainshowers_day': '🌦️',
            'rainshowers_night': '🌧️',
            'lightrain': '🌦️',
            'lightrainshowers': '🌦️',
            'heavyrain': '⛈️',
            'heavyrainshowers': '⛈️',
            'snow': '❄️',
            'snowshowers': '🌨️',
            'lightsnow': '🌨️',
            'heavysnow': '❄️',
            'sleet': '🌨️',
            'sleetshowers': '🌨️',
            'thunder': '⛈️',
            'thundershowers': '⛈️',
            'fog': '🌫️',
            'wind': '💨'
        }
        
        return emoji_map.get(symbol_code, '🌡️')


# Major Norwegian cities with coordinates
NORWEGIAN_CITIES = {
    'oslo': {'lat': 59.9139, 'lon': 10.7522, 'name': 'Oslo'},
    'bergen': {'lat': 60.3913, 'lon': 5.3221, 'name': 'Bergen'},
    'trondheim': {'lat': 63.4305, 'lon': 10.3951, 'name': 'Trondheim'},
    'stavanger': {'lat': 58.9700, 'lon': 5.7331, 'name': 'Stavanger'},
    'tromsø': {'lat': 69.6492, 'lon': 18.9553, 'name': 'Tromsø'},
    'kristiansand': {'lat': 58.1467, 'lon': 7.9956, 'name': 'Kristiansand'},
    'bodø': {'lat': 67.2804, 'lon': 14.4049, 'name': 'Bodø'},
    'ålesund': {'lat': 62.4722, 'lon': 6.1549, 'name': 'Ålesund'},
    'skien': {'lat': 59.2096, 'lon': 9.6090, 'name': 'Skien'},
    'drammen': {'lat': 59.7439, 'lon': 10.2045, 'name': 'Drammen'},
    'fredrikstad': {'lat': 59.2205, 'lon': 10.9347, 'name': 'Fredrikstad'},
    'sandnes': {'lat': 58.8524, 'lon': 5.7352, 'name': 'Sandnes'},
    'larvik': {'lat': 59.0533, 'lon': 10.0271, 'name': 'Larvik'},
}


def extract_city(text):
    """
    Extract a city name from text if it exists in NORWEGIAN_CITIES
    """
    text_lower = text.lower()
    for city_key in NORWEGIAN_CITIES:
        # Match whole word using word boundaries
        if re.search(rf'\b{re.escape(city_key)}\b', text_lower):
            return city_key
    return None


async def get_weather_for_city(city_name='oslo'):
    """Compatibility reader using the shared service; unknown cities are explicit."""
    from features.forecast_service import get_forecast_service, resolve_location
    result = await get_forecast_service().get_weather(resolve_location(city_name))
    if result.data is None:
        return None
    return {**result.data, "location": result.location["name"], "status": result.status, "source": result.source}


if __name__ == "__main__":
    # Test the weather API
    async def test():
        print("=== MET.no Weather API Test ===\n")
        
        api = METWeatherAPI()
        
        # Test Oslo weather
        weather = await api.get_weather()
        if weather:
            print(f"Vær i {weather['location']}:")
            print(f"  Temperatur: {weather['temp']}°C")
            print(f"  Høyde: {weather['temp_high']}°C")
            print(f"  Laveste: {weather['temp_low']}°C")
            print(f"  Forhold: {weather['condition']}")
            print(f"  Vind: {weather['wind_speed']} m/s")
            print(f"  Fuktighet: {weather['humidity']}%")
        else:
            print("Kunne ikke hente værdata")
        
        await api.close()
    
    asyncio.run(test())

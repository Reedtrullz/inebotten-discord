"""Owned forecast clients and explicit validity for the existing providers."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math
import time
from typing import Literal

from features.weather_api import METWeatherAPI, NORWEGIAN_CITIES


ALIASES = {'tromso': 'tromsø', 'bodo': 'bodø', 'alesund': 'ålesund'}


def aware_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Forecast time must include a timezone')
    return value.astimezone(timezone.utc)


def resolve_location(value: str | dict) -> dict:
    if isinstance(value, str):
        key = value.strip().casefold()
        key = ALIASES.get(key, key)
        if key not in NORWEGIAN_CITIES:
            raise ValueError('Ukjent sted. Velg en kjent by eller oppgi gyldige koordinater.')
        return dict(NORWEGIAN_CITIES[key])
    if not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name'].strip():
        raise ValueError('Ukjent sted. Oppgi navn og gyldige koordinater.')
    if any(type(value.get(key)) not in (int, float) or not math.isfinite(value[key]) for key in ('lat', 'lon')):
        raise ValueError('Ukjent sted. Oppgi gyldige koordinater.')
    if not (-90 <= value['lat'] <= 90 and -180 <= value['lon'] <= 180):
        raise ValueError('Ukjent sted. Koordinatene er utenfor gyldig område.')
    return {'name': value['name'].strip(), 'lat': value['lat'], 'lon': value['lon']}


@dataclass(frozen=True)
class ForecastResult:
    status: Literal['fresh', 'stale', 'unavailable']
    source: str
    fetched_at: datetime
    valid_at: datetime | None
    expires_at: datetime | None
    location: dict
    data: dict | None


class ForecastService:
    def __init__(self, weather_client=None, aurora_client=None, *, now=None, monotonic=None,
                 owns_weather=True, owns_aurora=True):
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.weather_client = weather_client or METWeatherAPI(now=self.now, monotonic=self.monotonic)
        self.aurora_client = aurora_client
        self.cache_ttl = 600
        self.stale_limit = 3600
        self._cache = {}
        self._locks = {}
        self._closed = False
        self._owns_weather, self._owns_aurora = owns_weather, owns_aurora

    async def get_weather(self, location: dict) -> ForecastResult:
        location = resolve_location(location)
        now = aware_time(self.now())
        if self._closed:
            return ForecastResult('unavailable', 'MET Norway', now, None, None, location, None)
        key = (round(location['lat'], 4), round(location['lon'], 4))
        async with self._locks.setdefault(key, asyncio.Lock()):
            now = aware_time(self.now())
            tick = self.monotonic()
            cached = self._cache.get(key)
            if cached:
                previous, fetched_tick = cached
                if tick - fetched_tick < self.cache_ttl and (previous.expires_at is None or now < previous.expires_at):
                    return copy.deepcopy(replace(previous, location=location))
            try:
                data = await self.weather_client.get_weather(lat=location['lat'], lon=location['lon'], location_name=location['name'])
                if not isinstance(data, dict) or type(data.get('temp')) not in (int, float) or not math.isfinite(data['temp']):
                    raise ValueError('Unavailable temperature')
                valid_at = aware_time(data.get('valid_at'))
                expires = aware_time(data['expires_at']) if data.get('expires_at') else None
                if (expires and expires <= now) or valid_at < now - timedelta(hours=6):
                    raise ValueError('Expired forecast')
                result = ForecastResult('fresh', 'MET Norway', now, valid_at, expires, location, copy.deepcopy(data))
                self._cache[key] = (result, tick)
                return copy.deepcopy(result)
            except Exception:
                if cached and tick - cached[1] <= self.stale_limit:
                    return copy.deepcopy(replace(cached[0], status='stale', location=location))
                return ForecastResult('unavailable', 'MET Norway', now, None, None, location, None)

    async def close(self):
        self._closed = True
        if not hasattr(self, '_closed_clients'):
            self._closed_clients = set()
        failed = False
        for client, owned in ((self.weather_client, self._owns_weather), (self.aurora_client, self._owns_aurora)):
            if owned and client is not None and id(client) not in self._closed_clients:
                try:
                    await client.close()
                    self._closed_clients.add(id(client))
                except Exception:
                    failed = True
        if failed:
            raise RuntimeError('forecast_cleanup_failed')


_DEFAULT = None


def get_forecast_service():
    global _DEFAULT
    if _DEFAULT is None or _DEFAULT._closed:
        _DEFAULT = ForecastService()
    return _DEFAULT


def format_weather(result: ForecastResult, locale='no') -> str:
    name = result.location['name']
    if result.status == 'unavailable':
        return f'🌤️ Værdata for {name} er utilgjengelig. Prøv igjen senere.' if locale == 'no' else f'🌤️ Weather for {name} is unavailable. Try again later.'
    data = result.data
    condition = data.get('condition') or ('ukjent værtilstand' if locale == 'no' else 'unknown conditions')
    status = ('Utdatert varsel' if locale == 'no' else 'Stale forecast') if result.status == 'stale' else ('Værvarsel' if locale == 'no' else 'Forecast')
    valid = result.valid_at.isoformat() if result.valid_at else '?'
    return f"🌤️ {status} for {name}: {data['temp']}°C, {condition}. {result.source}; {valid}."

"""Forecast failures and time zones must not invent observations."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core.message_monitor import MessageMonitor
from features.aurora_forecast import AuroraForecast
from features.weather_api import METWeatherAPI


@pytest.mark.asyncio
async def test_failure_never_fabricates_weather():
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.calendar = SimpleNamespace(get_upcoming=lambda *_a, **_kw: [])
    monitor.conv_gen = SimpleNamespace(generate_dashboard=lambda **kw: kw['weather_data'])
    from features import weather_api
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(weather_api.METWeatherAPI, 'get_weather', AsyncMock(return_value=None))
        result = await monitor._generate_dashboard('guild', city_name='oslo')
    assert result['status'] == 'unavailable'
    assert result.get('temp') is None
    assert result.get('conditions') is None


@pytest.mark.asyncio
async def test_unknown_city_is_actionable():
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.calendar = SimpleNamespace(get_upcoming=lambda *_a, **_kw: [])
    monitor.conv_gen = SimpleNamespace(generate_dashboard=lambda **kw: kw['weather_data'])
    with pytest.raises(ValueError, match='Ukjent sted'):
        await monitor._generate_dashboard('guild', city_name='never-a-place')


@pytest.mark.parametrize('instant', ['2027-01-01T12:00:00+00:00', '2027-03-28T01:30:00+00:00', '2027-10-31T01:30:00+00:00'])
def test_utc_oslo_select_same_aurora_interval(instant):
    now = datetime.fromisoformat(instant)
    start = now.replace(minute=0)
    rows = [['time_tag', 'kp'], [(start-timedelta(hours=3)).isoformat(), '2'],
            [start.isoformat(), '4'], [(start+timedelta(hours=3)).isoformat(), '7']]
    utc = AuroraForecast(now=lambda: now)._parse_forecast(rows)
    oslo = AuroraForecast(now=lambda: now.astimezone(ZoneInfo('Europe/Oslo')))._parse_forecast(rows)
    assert utc['kp_index'] == oslo['kp_index'] == 4
    assert utc['valid_at'] == oslo['valid_at']
    assert 'score' in utc
    assert 'probability' not in utc


@pytest.mark.asyncio
async def test_same_location_reuses_cache_and_refreshes_after_expiry():
    from features.forecast_service import ForecastService, resolve_location
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    tick = [0]
    provider = SimpleNamespace(get_weather=AsyncMock(return_value={
        'temp': 3, 'condition': 'Skyet', 'valid_at': now.isoformat(),
        'expires_at': (now+timedelta(hours=1)).isoformat()}), close=AsyncMock())
    service = ForecastService(weather_client=provider, now=lambda: now, monotonic=lambda: tick[0])
    location = resolve_location('OSLO')
    first = await service.get_weather(location)
    again = await service.get_weather(location)
    assert first.status == again.status == 'fresh'
    assert provider.get_weather.await_count == 1
    first.data['temp'] = 99
    assert (await service.get_weather(location)).data['temp'] == 3
    tick[0] = 601
    await service.get_weather(location)
    assert provider.get_weather.await_count == 2
    tick[0] = 1202
    provider.get_weather.return_value = None
    assert (await service.get_weather(location)).status == 'stale'
    await service.close()
    assert provider.close.await_count == 1


def test_met_missing_temperature_does_not_become_zero_or_fake_high_low():
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    api = METWeatherAPI(now=lambda: now)
    payload = {'properties': {'timeseries': [{'time': now.isoformat(), 'data': {'instant': {'details': {}}}}]}}
    assert api._parse_weather(payload, 'Oslo') is None
    payload['properties']['timeseries'][0]['data']['instant']['details']['air_temperature'] = 3
    parsed = api._parse_weather(payload, 'Oslo')
    assert parsed['temp'] == 3
    assert parsed['temp_high'] is None and parsed['temp_low'] is None
    assert parsed['valid_at'] == now.isoformat()

@pytest.mark.asyncio
async def test_dashboard_and_digest_share_owned_forecast_client():
    from features.forecast_service import ForecastService
    from features.daily_digest_manager import DailyDigestManager
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    client = SimpleNamespace(get_weather=AsyncMock(return_value={'temp': 3, 'condition': 'Skyet',
        'valid_at': now.isoformat(), 'expires_at': (now+timedelta(hours=1)).isoformat()}), close=AsyncMock())
    service = ForecastService(weather_client=client, now=lambda: now)
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.forecasts = service
    monitor.calendar = SimpleNamespace(get_upcoming=lambda *_a, **_kw: [])
    monitor.conv_gen = SimpleNamespace(generate_dashboard=lambda **kw: kw['weather_data'])
    first = await monitor._generate_dashboard('guild', city_name='oslo')
    second = await monitor._generate_dashboard('guild', city_name='Oslo')
    digest = await DailyDigestManager(forecast_service=service).generate_digest('guild')
    assert first['temp'] == second['temp'] == 3
    assert 'MET Norway' in digest and '2027-01-01' in digest
    assert client.get_weather.await_count == 1
    await service.close()
    await service.close()
    assert client.close.await_count == 1


@pytest.mark.asyncio
async def test_expired_or_malformed_response_is_unavailable():
    from features.forecast_service import ForecastService, resolve_location
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    for response in ({'temp': 8, 'valid_at': now.isoformat(), 'expires_at': (now-timedelta(seconds=1)).isoformat()},
                     {'temp': 8}, {'temp': float('nan'), 'valid_at': now.isoformat()}):
        provider = SimpleNamespace(get_weather=AsyncMock(return_value=response), close=AsyncMock())
        service = ForecastService(weather_client=provider, now=lambda: now)
        result = await service.get_weather(resolve_location('oslo'))
        assert result.status == 'unavailable'
        assert result.data is None
        await service.close()


def test_noaa_object_rows_with_offsetless_provider_times_are_utc():
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    rows = [{'time_tag': '2027-01-01T09:00:00', 'kp': 2, 'observed': 'observed'},
            {'time_tag': '2027-01-01T12:00:00', 'kp': 4, 'observed': 'estimated'},
            {'time_tag': '2027-01-01T15:00:00', 'kp': 7, 'observed': 'predicted'}]
    result = AuroraForecast(now=lambda: now)._parse_forecast(rows)
    assert result['kp_index'] == 4
    assert result['valid_at'] == now
    assert result['data_kind'] == 'estimated'

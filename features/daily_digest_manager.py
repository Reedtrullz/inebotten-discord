#!/usr/bin/env python3
"""Daily briefing composition with one explicit temporal reference."""

from __future__ import annotations

from datetime import datetime

from cal_system.temporal_resolver import OSLO


class DailyDigestManager:
    """Generate a daily digest from injected, read-only dependencies."""

    def __init__(
        self,
        event_manager=None,
        birthday_manager=None,
        crypto_manager=None,
        aurora_manager=None,
        watchlist_manager=None,
        *,
        user_memory=None,
    ) -> None:
        self.event_manager = event_manager
        self.birthday_manager = birthday_manager
        self.crypto_manager = crypto_manager
        self.aurora_manager = aurora_manager
        self.watchlist_manager = watchlist_manager
        self.user_memory = user_memory

    @staticmethod
    def _capture_reference(reference_time: datetime | None) -> datetime:
        reference = (
            datetime.now(OSLO) if reference_time is None else reference_time
        )
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise ValueError("reference_time_must_be_aware")
        return reference

    async def generate_digest(
        self,
        guild_id,
        lang="no",
        user_id=None,
        *,
        reference_time: datetime | None = None,
    ) -> str:
        """Generate one briefing using the same aware reference throughout."""
        reference = self._capture_reference(reference_time)
        local_reference = reference.astimezone(OSLO)
        lines: list[str] = []

        hour = local_reference.hour
        if lang == "no":
            if hour < 12:
                greeting = "God morgen! ☀️"
            elif hour < 18:
                greeting = "God ettermiddag! 🌤️"
            else:
                greeting = "God kveld! 🌙"
            lines.extend(["✨ **Dagens Briefing** ✨", f"_{greeting}_", ""])
        else:
            if hour < 12:
                greeting = "Good morning! ☀️"
            elif hour < 18:
                greeting = "Good afternoon! 🌤️"
            else:
                greeting = "Good evening! 🌙"
            lines.extend(["✨ **Daily Briefing** ✨", f"_{greeting}_", ""])

        from cal_system.norwegian_calendar import get_navnedag

        if lang == "no":
            lines.append(f"📅 **Dato:** {local_reference.strftime('%d.%m.%Y')}")
            names = get_navnedag(local_reference.month, local_reference.day)
            if names:
                lines.append(f"🎉 **Navnedag:** {' og '.join(names[:2])}")
        else:
            lines.append(
                f"📅 **Date:** {local_reference.strftime('%B %d, %Y')}"
            )
        lines.append("─" * 20)

        from features.weather_api import METWeatherAPI, get_weather_for_city

        city_name = "oslo"
        if user_id is not None and self.user_memory is not None:
            user = self.user_memory.snapshot_user(user_id)
            if user and user.get("location"):
                city_name = user["location"]

        weather = await get_weather_for_city(city_name)
        if weather:
            emoji = METWeatherAPI().get_weather_emoji(weather["symbol_code"])
            if lang == "no":
                lines.append(
                    f"{emoji} **Været i {weather['location']}:** "
                    f"{weather['temp']}°C ({weather['condition']})"
                )
            else:
                lines.append(
                    f"{emoji} **Weather in {weather['location']}:** "
                    f"{weather['temp']}°C ({weather['condition']})"
                )
            lines.append(
                f"   ↓ {weather['temp_low']}°C  ↑ {weather['temp_high']}°C"
            )
            lines.append("")

        if self.birthday_manager:
            birthdays = self.birthday_manager.get_todays_birthdays(guild_id)
            if birthdays:
                lines.append("🎂 **Bursdager i dag!**")
                for name, age in birthdays:
                    age_text = f" ({age} år)" if age else ""
                    lines.append(f"• **{name}**{age_text} 🎉")
                lines.append("")

        if self.event_manager:
            events = self._get_today_events(
                guild_id,
                reference_time=reference,
            )
            if events:
                heading = (
                    f"📋 **Dagens planer ({len(events)}):**"
                    if lang == "no"
                    else f"📋 **Today's events ({len(events)}):**"
                )
                lines.append(heading)
                for event in events[:5]:
                    creator = f" ({event.get('username', 'Ukjent')})"
                    lines.append(
                        f"• {event['title']} kl "
                        f"{event.get('time', '??:??')}{creator}"
                    )
                lines.append("")

        if self.crypto_manager:
            lines.append("₿ **Markedet:**")
            for coin in ("bitcoin", "ethereum", "solana"):
                data = await self.crypto_manager.get_price(
                    {
                        "type": "crypto",
                        "coin_id": coin,
                        "asset": coin,
                        "display_name": coin.upper(),
                    }
                )
                if data:
                    trend = "📈" if data["change_24h"] >= 0 else "📉"
                    lines.append(
                        f"• {data['symbol']}: **${data['price']:,.0f}** "
                        f"({trend} {data['change_24h']:.1f}%)"
                    )
            lines.append("")

        if self.aurora_manager:
            forecast = await self.aurora_manager.get_forecast()
            if forecast and forecast["kp_index"] >= 3:
                visibility = forecast["visibility"]
                lines.append(
                    f"🌌 **Nordlysvarsel:** {visibility['emoji']} "
                    f"KP {forecast['kp_index']:.1f} - {visibility['level']}"
                )
                lines.append(f"   _{visibility['areas']}_")
                lines.append("")

        if self.watchlist_manager:
            items = self.watchlist_manager.get_watchlist(guild_id) or []
            active = [item for item in items if not item.get("completed")]
            if active:
                lines.append(f"📦 **Vaktliste:** {len(active)} aktive ting")
                lines.extend(f"• {item['title']}" for item in active[:2])
                lines.append("")

        lines.append("─" * 20)
        if lang == "no":
            lines.append(
                "💡 *Tips: Bruk `@inebotten hjelp` for å se alle kommandoer.*"
            )
        else:
            lines.append(
                "💡 *Tip: Use `@inebotten help` to see all commands.*"
            )
        return "\n".join(lines)

    def _get_today_events(
        self,
        guild_id,
        *,
        reference_time: datetime,
    ) -> list[dict]:
        if not self.event_manager:
            return []
        if (
            reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        local_date = reference_time.astimezone(OSLO).strftime("%d.%m.%Y")
        events = self.event_manager.get_upcoming(
            guild_id,
            days=1,
            reference_time=reference_time,
        )
        return [event for event in events if event.get("date") == local_date]


async def generate_daily_digest(
    guild_id,
    event_manager=None,
    birthday_manager=None,
    crypto_manager=None,
    aurora_manager=None,
    watchlist_manager=None,
    lang="no",
    *,
    user_memory=None,
    reference_time: datetime | None = None,
):
    """Offline-compatible convenience boundary; production injects all state."""
    manager = DailyDigestManager(
        event_manager,
        birthday_manager,
        crypto_manager,
        aurora_manager,
        watchlist_manager,
        user_memory=user_memory,
    )
    return await manager.generate_digest(
        guild_id,
        lang,
        reference_time=reference_time,
    )

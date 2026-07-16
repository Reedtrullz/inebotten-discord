#!/usr/bin/env python3
"""
ProfileHandler - Handles commands for managing Inebotten's own Discord profile.
"""

from collections.abc import Mapping

import discord
from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    MessageSendCancelled,
)
from core.intent_models import BotIntent
from core.intent_payloads import (
    PayloadValidationError,
    ProfilePayload,
    validate_intent_payload,
)
from features.base_handler import BaseHandler


class ProfileHandler(BaseHandler):
    """Handler for profile management commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.client = monitor.client
        self.token = monitor.client.config.DISCORD_TOKEN

    async def _finish(
        self,
        message,
        response_text: str,
        base: DispatchOutcome,
    ) -> DispatchOutcome:
        try:
            delivery = await self.send_response_result(message, response_text)
        except MessageSendCancelled as exc:
            raise DispatchCancelled(base.with_delivery(exc.result)) from None
        return base.with_delivery(delivery)

    async def handle_status(self, message, status: str) -> DispatchOutcome:
        """
        Change Inebotten's online status.
        Args:
            message: Discord message
            status: online, idle, dnd, invisible
        """
        status_map = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
            "offline": discord.Status.offline
        }
        
        normalized = status.strip().casefold() if isinstance(status, str) else ""
        target_status = status_map.get(normalized)
        if not target_status:
            return await self._finish(
                message,
                "⚠️ Ugyldig status. Bruk: online, offline, idle, dnd, eller invisible.",
                DispatchOutcome.failure("invalid_payload", retryable=False),
            )

        try:
            await self.client.change_presence(status=target_status)
        except Exception as exc:
            self.log(f"Error changing status: {type(exc).__name__}")
            return await self._finish(
                message,
                "⚠️ Det er uklart om statusendringen ble fullført.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    retryable=False,
                    commit_unknown=True,
                ),
            )
        return await self._finish(
            message,
            f"✅ Status endret til **{normalized}**.",
            DispatchOutcome.success(mutated=True),
        )

    async def handle_activity(
        self,
        message,
        activity_type: str,
        text: str,
    ) -> DispatchOutcome:
        """
        Change Inebotten's custom activity.
        Args:
            message: Discord message
            activity_type: playing, watching, listening, competing
            text: Activity description
        """
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing
        }
        
        normalized_type = (
            activity_type.strip().casefold()
            if isinstance(activity_type, str)
            else ""
        )
        normalized_text = text.strip() if isinstance(text, str) else ""
        target_type = type_map.get(normalized_type)
        if (
            normalized_type not in {"playing", "watching"}
            or target_type is None
            or not normalized_text
            or len(normalized_text) > 100
        ):
            return await self._finish(
                message,
                "⚠️ Ugyldig profilaktivitet.",
                DispatchOutcome.failure("invalid_payload", retryable=False),
            )

        try:
            activity = discord.Activity(type=target_type, name=normalized_text)
        except Exception:
            return await self._finish(
                message,
                "⚠️ Ugyldig profilaktivitet.",
                DispatchOutcome.failure("invalid_payload", retryable=False),
            )
        try:
            await self.client.change_presence(activity=activity)
        except Exception as exc:
            self.log(f"Error changing activity: {type(exc).__name__}")
            return await self._finish(
                message,
                "⚠️ Det er uklart om aktivitetsendringen ble fullført.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    retryable=False,
                    commit_unknown=True,
                ),
            )
        return await self._finish(
            message,
            f"✅ Aktivitet endret til: **{normalized_type} {normalized_text}**",
            DispatchOutcome.success(mutated=True),
        )

    async def handle_profile_command(
        self,
        message,
        payload: ProfilePayload,
    ) -> DispatchOutcome:
        """Dispatch one already parsed profile payload without reading content."""

        if not isinstance(payload, Mapping):
            return await self._finish(
                message,
                "⚠️ Ugyldig profilkommando.",
                DispatchOutcome.failure("invalid_payload", retryable=False),
            )
        try:
            canonical = validate_intent_payload(BotIntent.PROFILE, payload)
        except PayloadValidationError:
            return await self._finish(
                message,
                "⚠️ Ugyldig profilkommando.",
                DispatchOutcome.failure("invalid_payload", retryable=False),
            )
        if canonical["action"] == "status":
            return await self.handle_status(message, canonical["value"])
        return await self.handle_activity(
            message,
            canonical["action"],
            canonical["value"],
        )

#!/usr/bin/env python3
"""Discord-facing controls for user memory."""

import json

from features.base_handler import BaseHandler


class MemoryHandler(BaseHandler):
    """Handle view/export/delete commands for the current user's memory."""

    async def handle_memory(self, message, payload=None) -> None:
        action = (payload or {}).get("action", "view")

        if action == "export":
            await self._handle_export(message)
        elif action == "delete":
            await self._handle_delete(message, confirmed=bool((payload or {}).get("confirmed")))
        else:
            await self._handle_view(message)

    async def _handle_view(self, message) -> None:
        text = await self.monitor.user_memory.format_user_memory_for_user(
            message.author.id,
            getattr(message.author, "name", None),
        )
        await self.send_response(message, text)

    async def _handle_export(self, message) -> None:
        data = await self.monitor.user_memory.export_user_memory(message.author.id)
        if not data:
            await self.send_response(message, "Jeg har ikke lagret noe brukerminne om deg ennå.")
            return

        payload = json.dumps(data, ensure_ascii=False, indent=2)
        if len(payload) > 1800:
            payload = payload[:1800] + "\n... (forkortet)"
        await self.send_response(message, f"```json\n{payload}\n```")

    async def _handle_delete(self, message, *, confirmed: bool) -> None:
        if not confirmed:
            await self.send_response(
                message,
                "Jeg kan slette brukerminnet ditt. "
                "Skriv `@inebotten slett minnet mitt bekreft` for å bekrefte.",
            )
            return

        deleted = await self.monitor.user_memory.delete_user_memory(message.author.id)
        if deleted:
            await self.send_response(message, "✅ Ferdig. Jeg har slettet brukerminnet ditt.")
        else:
            await self.send_response(message, "Jeg hadde ikke noe brukerminne lagret om deg.")

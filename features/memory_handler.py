#!/usr/bin/env python3
"""Discord-facing controls for user memory."""

import json

from features.base_handler import BaseHandler
from utils.storage_contract import StorageMutationError


class MemoryHandler(BaseHandler):
    """Handle view/export/delete commands for the current user's memory."""

    async def handle_memory(self, message, payload=None) -> None:
        action = (payload or {}).get("action", "view")

        try:
            if action == "export":
                await self._handle_export(message)
            elif action == "delete":
                await self._handle_delete(message, confirmed=bool((payload or {}).get("confirmed")))
            elif action == 'policy':
                changes = (payload or {}).get('changes', {})
                if set(changes) - {'learning_enabled', 'topic_retention_days', 'allowed_provider_ids', 'private_facts_enabled'}:
                    raise ValueError('invalid_memory_control')
                await self.monitor.user_memory.set_policy(message.author.id, **changes)
                await self.send_response(message, '✅ Minnekontrollen er lagret for deg. Allerede lagrede fakta er bevart; pauset læring deler ingen personalisering med AI.')
            elif action == 'school_locality':
                await self.monitor.user_memory.set_saved_fact(message.author.id, 'school_locality', payload['value'])
                await self.send_response(message, '✅ Skolekommunen er lagret som et bevisst valg. Den brukes automatisk bare i direktemelding.')
            else:
                await self._handle_view(message)
        except (StorageMutationError, OSError):
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except ValueError:
            await self.send_response(message, '❌ Ugyldig minnekontroll. Velg en støttet provider eller behold tema i 1–365 dager.')

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

        result = await self.monitor.user_memory.delete_local_memory(message.author.id, include_transient=True)
        await self.send_response(message, '✅ Lokal sletting er gjennomført. '
            f'Brukerminne: {"slettet" if result["persistent_deleted"] else "ingen lagret"}; '
            f'midlertidige egne meldinger/svar: {result["transient_deleted"]}. '
            'Dette sletter ikke sikkerhetskopier, Discord-meldinger eller tidligere data hos AI-providere.')

#!/usr/bin/env python3
"""Discord-facing controls for user memory."""

import json
import asyncio
import time
import discord

from features.base_handler import BaseHandler
from utils.storage_contract import StorageMutationError
from core.outbound_sender import Attachment, MAX_ATTACHMENT_BYTES, monitor_sender


class MemoryHandler(BaseHandler):
    """Handle view/export/delete commands for the current user's memory."""

    async def handle_memory(self, message, payload=None) -> None:
        action = (payload or {}).get("action", "view")

        try:
            if action == "export":
                fields = payload or {}
                if set(fields) - {'action', 'private'} or ('private' in fields and type(fields['private']) is not bool):
                    await self.send_response(message, '❌ Du kan bare eksportere ditt eget minne med et uttrykkelig privat valg.')
                    return
                return await self._handle_export(message, private=fields.get('private', False))
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

    async def _handle_export(self, message, *, private=False):
        deadline = time.monotonic() + 10
        destination = message.channel
        if not isinstance(destination, discord.DMChannel):
            if not private:
                await self.send_response(message, 'Be om eksport i direktemelding, eller skriv `eksporter minnet mitt privat` for å velge privat levering.')
                return
            try:
                async with asyncio.timeout_at(deadline):
                    destination = await message.author.create_dm()
            except Exception:
                destination = None
        if (not isinstance(destination, discord.DMChannel)
            or getattr(getattr(destination, 'recipient', None), 'id', None) != message.author.id):
            await self.send_response(message, '❌ Kunne ikke finne en privat destinasjon til deg. Ingen eksport er sendt.')
            return
        data = await self.monitor.user_memory.export_user_memory(message.author.id)
        if not data:
            await self.send_response(message, "Jeg har ikke lagret noe brukerminne om deg ennå.")
            return

        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_ATTACHMENT_BYTES:
            await self.send_response(message, '❌ Eksporten er for stor for den lokale grensen på 1 MiB. Ingen forkortet eksport er sendt.')
            return
        attachment = Attachment('inebotten-minne.json', 'application/json', payload)
        sender = monitor_sender(self.monitor)
        content = f'Ditt komplette lagrede minne som JSON ({len(payload)} byte).'
        if destination is message.channel:
            result = await sender.reply(message, content, deadline=deadline, attachments=(attachment,))
        else:
            result = await sender.send(str(destination.id), content, deadline=deadline,
                delivery_key=f'memory-export:{message.author.id}:{message.id}',
                attachments=(attachment,), _dispatch=destination.send)
        if result.status == 'delivered':
            if result.reason_code == 'remote_message' and hasattr(self.monitor, 'response_count'):
                self.monitor.response_count += 1
        else:
            self.logger.warning('Memory export delivery: %s (%s)', result.status, result.reason_code)
            await self.send_response(message, '❌ Privat levering er ikke bekreftet. Kontroller direktemeldingen før du prøver igjen.')
        return result

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

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
            elif action == 'notification':
                await self._handle_notification(message, payload['changes'])
            elif action == 'notification_view':
                await self._handle_notification(message, None)
            elif action == 'snooze':
                await self.monitor.handlers['reminders'].handle_snooze(message, payload)
            else:
                await self._handle_view(message)
        except (StorageMutationError, OSError):
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except ValueError:
            await self.send_response(message, '❌ Ugyldig kontroll. Velg støttet provider, klokkeslett, kort eller minuttgrense (0–1440).')
        except PermissionError:
            await self.send_response(message, '❌ Dette kalenderområdet eller denne destinasjonen er ikke godkjent for deg.')

    async def _handle_notification(self, message, changes):
        from cal_system.notification_preferences import NotificationProfile
        from core.request_context import current_request
        actor = current_request()
        calendar = self.monitor.calendar
        scope_id = calendar.access_policy.default_scope
        if actor is None or actor.user_id != str(message.author.id) or actor.channel_id != str(message.channel.id):
            raise PermissionError('notification_actor_required')
        if not calendar.access_policy.authorize(actor, scope_id, 'read').allowed:
            raise PermissionError('notification_scope_denied')
        prior = self.monitor.user_memory.notification_profile(actor.user_id, scope_id)
        if changes is None:
            if prior is None:
                await self.send_response(message, 'Du har ingen egen varselprofil. Eksisterende legacy-varsler gjelder; `varsler på` velger denne kanalen, og `varsler av` pauser dine varsler.')
            else:
                quiet = f'{prior.quiet_start:%H:%M}–{prior.quiet_end:%H:%M}' if prior.quiet_start else 'av'
                morning = f'{prior.morning_time:%H:%M}' if prior.morning_time else 'av'
                await self.send_response(message, f'Egne varsler: {"på" if prior.enabled else "pauset"}; kanal {prior.destination_id}; '
                    f'forvarsel {list(prior.lead_minutes)} minutter; stille {quiet}; morgen {morning}; '
                    f'kort {", ".join(prior.card_ids) or "ingen"}; {prior.timezone}.')
            return
        if set(changes) - {'enabled', 'lead_minutes', 'quiet_start', 'quiet_end', 'morning_time', 'timezone', 'card_ids'}:
            raise ValueError('invalid_notification_changes')
        value = (prior or NotificationProfile(False, scope_id, actor.channel_id)).document()
        value.update(changes)
        if changes.get('enabled') is True:
            value['destination_id'] = actor.channel_id  # explicit enable selects this already-authorized audience
        profile = NotificationProfile.from_document(value)
        await self.monitor.user_memory.set_notification_profile(actor.user_id, profile)
        await self.send_response(message, f'✅ Egne varsler er {"på" if profile.enabled else "pauset"} for dette kalenderområdet. '
            'Valgene gjelder bare deg og valgt kanal; bruk `varsler av` for å pause.')

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

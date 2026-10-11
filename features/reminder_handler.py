#!/usr/bin/env python3
"""
ReminderHandler - Handles reminder edit and delete commands.

Commands:
- Editing reminder text, date, or recurrence by index
- Deleting reminders by index
"""

import re
from typing import Dict, Optional, Tuple

from cal_system.reminder_manager import ReminderEditError, parse_reminder_command, validate_deadline
from features.base_handler import BaseHandler
from utils.storage_contract import StorageMutationError
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class ReminderHandler(BaseHandler):
    """Handler for reminder edit and delete commands."""

    _EDIT_FIELD_MAP = {
        "tittel": "title",
        "title": "title",
        "tekst": "title",
        "text": "title",
        "dato": "date",
        "date": "date",
        "tid": "time",
        "time": "time",
        "klokkeslett": "time",
        "gjentakelse": "recurrence",
        "recurrence": "recurrence",
        "gjenta": "recurrence",
    }

    def __init__(self, monitor):
        super().__init__(monitor)
        self.reminders = monitor.reminders

    async def handle_snooze(self, message, payload):
        from cal_system.notification_preferences import occurrence_identity
        from cal_system.reminder_checker import project_current_occurrence
        from core.request_context import current_request
        actor = current_request()
        calendar = self.monitor.calendar
        if actor is None or actor.user_id != str(message.author.id):
            raise PermissionError('snooze_actor_required')
        scope = calendar.scope_key(operation='read')
        minutes = payload['minutes']
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ValueError('invalid_snooze_minutes')
        items = [i for bucket in calendar._scope_buckets() for i in calendar.items.get(bucket, [])]
        items += self.reminders.get_active_reminders(self.get_guild_id(message), include_events=False)
        matches = []
        for item in items:
            if (item['id'] != payload['item_id'] or str(item.get('user_id')) != actor.user_id
                    or item.get('completed') or item.get('_mutation_deleted') or item.get('delete_pending')):
                continue
            projected = project_current_occurrence(item)
            if projected is not None:
                matches.append(projected)
        if len(matches) != 1:
            raise PermissionError('snooze_own_active_item_required')
        due = calendar.clock.now('UTC') + timedelta(minutes=minutes)
        await self.monitor.user_memory.set_notification_snooze(actor.user_id, scope, matches[0]['id'], occurrence_identity(matches[0]), due)
        await self.send_response(message, f'✅ Egen påminnelse slumret {minutes} minutter. Stille timer gjelder fortsatt.')

    def _parse_edit_command(self, content: str) -> Tuple[Optional[int], Dict[str, str]]:
        """
        Extract index and field updates from an edit command.

        Supports formats like:
          - endre påminnelse 2 tittel: ny tekst
          - rediger påminnelse 1 dato: 15.05.2026
          - oppdater påminnelse 3 gjentakelse: ukentlig

        Returns:
            (index, kwargs) where index is 1-based or None,
            and kwargs maps to ReminderManager.edit_reminder fields.
        """
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        for kw in (
            "endre påminnelse",
            "rediger påminnelse",
            "oppdater påminnelse",
            "endre",
            "rediger",
            "oppdater",
            "påminnelse",
        ):
            if cleaned.lower().startswith(kw):
                cleaned = cleaned[len(kw) :].strip()

        num_match = re.search(r"\b(\d+)\b", cleaned)
        if not num_match:
            return None, {}
        index = int(num_match.group(1))

        remaining = re.sub(r"\b\d+\b", "", cleaned, count=1).strip(" -–—:")

        if ":" in remaining:
            prefix, value = remaining.split(":", 1)
            prefix = prefix.strip().lower()
            value = value.strip()

            field = None
            for nor_field, eng_field in self._EDIT_FIELD_MAP.items():
                if nor_field == prefix:
                    field = eng_field
                    break

            if field:
                if field == 'recurrence':
                    patterns = getattr(getattr(self.monitor, 'nlp_parser', None), 'recurrence_patterns', {})
                    value = patterns.get(value.casefold(), value)
                return index, {field: value}
            return index, {}

        if remaining:
            return index, {"title": remaining}

        return index, {}

    def _parse_search_query(self, content: str) -> Optional[str]:
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()
        match = re.match(
            r"^(?:søk|search)\s+(?:påminnelse|påminnelser|reminder|reminders)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        query = match.group(1).strip()
        return query or None

    async def handle_reminder_search(self, message, payload=None) -> None:
        """Handle reminder text search commands."""
        try:
            guild_id = self.get_guild_id(message)
            query = (payload or {}).get("query") or self._parse_search_query(message.content)
            if not query:
                await self.send_response(message, "🔎 Skriv hva du vil søke etter i påminnelser.")
                return
            await self.send_response(
                message,
                self.reminders.format_search_results(
                    guild_id,
                    query,
                    getattr(self.loc, "current_lang", "no"),
                ),
            )
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error searching reminders: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_create(self, message, payload=None) -> None:
        """Handle creating reminders from routed natural language."""
        try:
            guild_id = self.get_guild_id(message)
            data = (payload or {}).get("reminder") or parse_reminder_command(message.content)
            if not data or data.get("action") != "add" or not data.get("text"):
                await self.send_response(
                    message,
                    "🔔 Skriv hva jeg skal minne deg på, f.eks. `@inebotten påminnelse ring legen 20.06`.",
                )
                return

            deadline = validate_deadline(data.get('due_date'), self.reminders.clock)
            if deadline:
                due_value = deadline if ' ' in deadline else deadline + ' 09:00'
                if self.reminders.clock.now() >= datetime.strptime(due_value, '%d.%m.%Y %H:%M').replace(tzinfo=ZoneInfo('Europe/Oslo')):
                    await self.send_response(message, 'Fristen er i fortiden. Oppgi en fremtidig dato med år og klokkeslett; ingenting er lagret.')
                    return
            reminder_id = self.reminders.add_reminder(
                guild_id=guild_id,
                user_id=message.author.id,
                username=message.author.name,
                text=data["text"],
                due_date=deadline,
                channel_id=getattr(getattr(message, "channel", None), "id", None),
            )
            due = f"\n📅 Frist: {deadline} (Europe/Oslo)" if deadline else ""
            if deadline and ' ' not in deadline:
                due += '\nDato uten tid: automatisk varsel kl. 09:00, med gjeldende varselinnstillinger.'
            elif deadline:
                due += '\nAutomatisk varsel følger dine varselinnstillinger. Se `@inebotten varsler status`.'
            await self.send_response(
                message,
                f"✅ **Påminnelse lagt til!**\n{data['text']}{due}",
            )
            if not data.get("due_date"):
                await self.send_response(
                    message,
                    "🔔 Jeg fant ingen dato eller klokkeslett, så sender jeg ikke automatisk. "
                    "Bruk f.eks. `om 2 minutter` eller `20.06`."
                )
        except ValueError:
            await self.send_response(message, 'Ugyldig frist. Bruk DD.MM.ÅÅÅÅ kl HH:MM, med et entydig tidspunkt ved sommertid. Ingenting er lagret.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error creating reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_list(self, message, payload=None) -> None:
        """Handle listing active reminders."""
        try:
            guild_id = self.get_guild_id(message)
            records = self.reminders.get_active_reminders(guild_id)
            page = re.search(r'\bside (\d+)\b', message.content, re.I)
            page_number = max(1, int(page.group(1))) if page else 1
            reminders_text = self.reminders.format_reminders_list(guild_id, show_completed=True, page=page_number)
            if reminders_text:
                sent = await self.send_response(message, f"🔔 **Påminnelser:**\n{reminders_text}")
                if sent is not None:
                    self.remember_list(message, records, range((page_number - 1) * 8 + 1, min(len(records), page_number * 8) + 1))
            else:
                await self.send_response(message, "📭 Ingen aktive påminnelser.")
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error listing reminders: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_complete(self, message, payload=None) -> None:
        """Handle completing a reminder by active-list index."""
        try:
            guild_id = self.get_guild_id(message)
            data = (payload or {}).get("reminder")
            if not data:
                parsed = parse_reminder_command(message.content)
                data = parsed if parsed and parsed.get("action") == "complete" else {}
            index = data.get("number") if isinstance(data, dict) else None
            if index is None:
                cleaned = re.sub(r"<@!?\d+>", "", message.content)
                cleaned = cleaned.replace("@inebotten", "").strip().lower()
                match = re.fullmatch(
                    r"(?:ferdig|fullført|fullfør|done|complete|gjort)\s+(\d+)",
                    cleaned,
                    flags=re.IGNORECASE,
                )
                if match:
                    index = int(match.group(1))

            if index is None:
                reminders_text = self.reminders.format_reminders_list(guild_id)
                if reminders_text:
                    records = self.reminders.get_active_reminders(guild_id)
                    sent = await self.send_response(
                        message,
                        f"📝 Hvilken påminnelse er ferdig?\n\n{reminders_text}\n\n"
                        "Bruk `@inebotten ferdig påminnelse [nummer]`.",
                    )
                    if sent is not None:
                        self.remember_list(message, records, range(1, min(len(records), 8) + 1))
                else:
                    await self.send_response(message, "📭 Ingen aktive påminnelser.")
                return

            self.displayed_index(message, self.reminders.get_active_reminders(guild_id), index)
            success, text, next_date = self.reminders.complete_reminder(guild_id, reminder_num=index)
            if not success:
                await self.send_response(
                    message,
                    f"❌ Fant ikke påminnelse nummer {index}. Bruk `@inebotten påminnelser` for listen.",
                )
                return

            if next_date:
                await self.send_response(
                    message,
                    f"✅ **Fullført! {text}**\n📅 Neste gang: {next_date}",
                )
            else:
                await self.send_response(message, f"✅ **Fullført! {text}**")
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error completing reminder: {e}")
            await self.send_response(message, str(e) if isinstance(e, ValueError) else self.loc.t("error_generic"))

    async def handle_reminder_edit(self, message, payload=None) -> None:
        """Handle editing a reminder by its list index."""
        try:
            guild_id = self.get_guild_id(message)
            index, kwargs = self._parse_edit_command(message.content)

            if index is None:
                await self.send_response(
                    message, 'Velg et nummer fra `@inebotten påminnelser`. Eksempel: `@inebotten endre påminnelse 1 tid: 14:00`.'
                )
                return

            if not kwargs:
                await self.send_response(
                    message, 'Bruk tittel:, dato: eller tid:. Eksempel: `@inebotten endre påminnelse 1 tid: 14:00`.'
                )
                return

            self.displayed_index(message, self.reminders.get_active_reminders(guild_id), index)
            updated = self.reminders.edit_reminder(guild_id, index, **kwargs)
            await self.send_response(
                message, self.loc.t("reminder_edit_success", title=updated["text"]) + f'\nFrist: {updated.get("due_date") or "ingen automatisk varsling"} (Europe/Oslo). Bruk `@inebotten påminnelser` for ny liste.'
            )

        except ReminderEditError as error:
            await self.send_response(message, f'❌ {error}')
        except ValueError as error:
            await self.send_response(message, f'{error} Bruk `@inebotten påminnelser`.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error editing reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_delete(self, message, payload=None) -> None:
        """Handle deleting a reminder by its list index."""
        try:
            guild_id = self.get_guild_id(message)
            index = self.extract_number(message.content)
            index = await self.reviewed_delete(message, self.reminders.get_active_reminders(guild_id), index, 'påminnelse', 'text')
            if index is None:
                return

            self.reminders.delete_reminder_by_id(guild_id, index)
            await self.send_response(message, self.loc.t("reminder_delete_success"))

        except ValueError as error:
            await self.send_response(message, f'{error} Bruk `@inebotten påminnelser`.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error deleting reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

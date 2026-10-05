#!/usr/bin/env python3
"""
CalendarHandler - Handles calendar-related commands for the selfbot.

Commands:
- Creating calendar items (events, tasks, recurring items)
- Listing upcoming items
- Deleting items
- Marking items as complete
- Editing items (via delete+recreate workflow)
"""

import re
import json
import time
from typing import Optional, Dict, Any

from collections import OrderedDict
from core.request_context import RequestContext
from features.base_handler import BaseHandler
from utils.storage_contract import StorageMutationError


class CalendarHandler(BaseHandler):
    """Handler for calendar-related commands"""

    CLEAR_CONFIRM_KEYWORDS = ("bekreft", "confirm")
    DELETE_COMMANDS = r"(?:slett|slette|delete|fjern|fjerne)"
    COMPLETE_COMMANDS = r"(?:ferdig|done|complete|fullfør|fullføre|fullført|hopp over|skipp)"
    MUTATION_PREFIX = r"(?:(?:kan du|kunne du|vennligst|please)\s+)?"

    def __init__(self, monitor):
        super().__init__(monitor)
        self.calendar = monitor.calendar
        self.nlp_parser = monitor.nlp_parser
        self._displayed_lists = OrderedDict()

    def _extract_search_text(self, content: str) -> Optional[str]:
        """Extract the item title/query from calendar mutation commands."""
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").strip()

        command = rf"(?:{self.DELETE_COMMANDS}|{self.COMPLETE_COMMANDS})"
        calendar = r"(?:kalender(?:en)?|calendar|gcal)"
        patterns = (
            rf"^{self.MUTATION_PREFIX}(?:{calendar})\s+{command}\s+(.+)$",
            rf"^{self.MUTATION_PREFIX}{command}\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._normalize_calendar_target(match.group(1))
            if target and len(target) > 0:
                return target
        return None

    def _normalize_calendar_target(self, target: str) -> str:
        """Remove calendar context words and wrapping quotes from a target."""
        target = re.sub(
            r"\s+(?:i|fra)\s+(?:kalender(?:en)?|calendar|gcal)\s*$",
            "",
            target.strip(),
            flags=re.IGNORECASE,
        )
        target = target.strip(" .")
        target = self._strip_wrapping_quotes(target)

        bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)$", target, flags=re.IGNORECASE)
        if bulk_match:
            bulk_target = self._strip_wrapping_quotes(bulk_match.group(2).strip())
            return f"{bulk_match.group(1)} {bulk_target}".strip()

        return target

    def _strip_wrapping_quotes(self, value: str) -> str:
        stripped = value.strip()
        for left, right in (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")):
            if stripped.startswith(left) and stripped.endswith(right) and len(stripped) >= 2:
                return stripped[1:-1].strip()
        return stripped

    def _extract_bulk_title(self, search_text: str) -> Optional[str]:
        bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)$", search_text, flags=re.IGNORECASE)
        if not bulk_match:
            return None
        title = self._normalize_calendar_target(bulk_match.group(2))
        return title or None

    def _extract_target_index(self, search_text: Optional[str]) -> Optional[int]:
        if not search_text:
            return None
        stripped = search_text.strip()
        if re.fullmatch(r"\d+", stripped):
            return int(stripped)
        scoped_match = re.fullmatch(r"(?:nummer|nr\.?)\s+(\d+)", stripped, flags=re.IGNORECASE)
        return int(scoped_match.group(1)) if scoped_match else None

    def _matching_upcoming_items(self, guild_id, query: str):
        query_lower = query.lower()
        try:
            items = self.calendar.get_upcoming(guild_id, days=365)
        except TypeError:
            items = self.calendar.get_upcoming(guild_id)
        return [
            (index, item)
            for index, item in enumerate(items, 1)
            if query_lower in str(item.get("title", "")).lower()
        ]

    def _format_match_prompt(self, query: str, matches, *, action: str) -> str:
        action_labels = {
            "slett": ("slette", "slett", f"eller `@inebotten slett alle {query}` for alle treff."),
            "ferdig": ("fullføre", "ferdig", f"eller `@inebotten ferdig alle {query}` for alle treff."),
            "rediger": ("redigere", "rediger", ""),
        }
        verb, command, extra_hint = action_labels.get(action, ('endre', 'slett', ''))
        lines = [f"📋 Fant {len(matches)} treff for \"{query}\" i kalenderen:"]
        for index, item in matches[:10]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            lines.append(
                f"📅 `#{item['id'][:8]}` {item.get('title', 'Uten tittel')} — "
                f"{item.get('date', '')}{time_str}"
            )

        if len(matches) > 10:
            lines.append(f"\n… og {len(matches) - 10} til.")

        hint = f"\nBruk `@inebotten {command} [ID]` for å {verb} én bestemt"
        if extra_hint:
            hint += f", {extra_hint}"
        else:
            hint += "."
        lines.append(hint)
        return "\n".join(lines)

    def _format_delete_result(self, result, *, missing: str) -> str:
        requested = int(result.get("requested_count", 0))
        deleted_count = int(result.get("deleted_count", 0))
        pending_count = int(result.get("pending_count", 0))
        deleted_titles = list(result.get("deleted_titles", []))
        pending_titles = list(result.get("pending_titles", []))

        if requested == 0:
            return missing

        if pending_count and not deleted_count:
            titles = ", ".join(pending_titles[:3])
            if pending_count > 3:
                titles = f"{pending_count} stykker"
            return (
                f"⚠️ **Sletting venter i Google Calendar.**\n{titles}\n\n"
                "Jeg har skjult oppføringen lokalt som `delete_pending` og lagret feilen, "
                "slik at den ikke forsvinner uten spor hvis Google-slettingen feiler."
            )

        if pending_count:
            deleted = ", ".join(deleted_titles[:3]) if deleted_count <= 3 else f"{deleted_count} stykker"
            pending = ", ".join(pending_titles[:3]) if pending_count <= 3 else f"{pending_count} stykker"
            return (
                f"⚠️ **Delvis slettet.**\n"
                f"✅ Slettet: {deleted}\n"
                f"⏳ Venter på Google Calendar: {pending}"
            )

        if result.get("bulk"):
            titles = ", ".join(deleted_titles) if deleted_count <= 3 else f"{deleted_count} stykker"
            return f"✅ **Slettet {deleted_count} stykker!**\n{titles}"

        return f"✅ **Slettet! {result.get('title')}**"

    def _format_complete_response(self, success: bool, title: str, next_date: str | None) -> str:
        if not success:
            return ""
        if next_date:
            return (
                f"✅ **Fullført! {title}**\n\n"
                f"📅 Neste gang: {next_date}\n\n"
                f"Bra jobba! 🎉"
            )
        return f"✅ **Fullført! {title}**\n\nBra jobba! 🎉"

    def _extract_calendar_search_query(self, content: str) -> Optional[str]:
        """Extract query from calendar search commands."""
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()
        patterns = [
            r"^(?:søk|search)\s+(?:kalender|calendar)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                if query.lower().startswith(("på nett ", "web ", "nettet ")):
                    return None
                return query or None
        return None

    async def handle_search(self, message, payload=None) -> None:
        """Handle calendar title search commands."""
        try:
            query = (payload or {}).get("query") or self._extract_calendar_search_query(message.content)
            if not query:
                await self.send_response(message, "🔎 Skriv hva du vil søke etter i kalenderen.")
                return
            await self.send_response(message, self.calendar.format_search_results(query))
        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error searching calendar: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under søk i kalenderen.")

    async def handle_save_request(self, message, title, date, time):
        """
        Special entry point for AI-generated save requests.
        Ensures the title is clean and the event is created correctly.
        """
        # Final safety scrub of the title
        clean_title = title.strip()
        # Remove common leftover particles if they are at the end
        clean_title = re.sub(r'\s+(på|kl|i|ved|om)\s*$', '', clean_title, flags=re.IGNORECASE)
        # Remove leading particles
        clean_title = re.sub(r'^(å|at|om)\s+', '', clean_title, flags=re.IGNORECASE)
        
        item_data = {
            "title": clean_title[0].upper() + clean_title[1:] if clean_title else "Uten tittel",
            "date": date,
            "time": time if time and ":" in str(time) else "09:00"
        }
        
        await self.handle_calendar_item(message, item_data)

    async def handle_calendar_item(self, message, item_data: Dict[str, Any]) -> None:
        """
        Handle natural language calendar item creation (unified events + tasks).

        Args:
            message: The Discord message
            item_data: Parsed calendar item data from NLP parser
        """
        try:
            guild_id = self.get_guild_id(message)

            from cal_system.event_schema import EventTime
            self.calendar.scope_key(guild_id, 'write')
            meaning = EventTime.from_item({**item_data, 'kind': item_data.get('kind', item_data.get('type', 'event'))})
            meaning.validate_local()
            description = ('oppgave med frist' if meaning.kind == 'task' else 'heldagsarrangement' if meaning.all_day else f'arrangement kl. {meaning.local_time:%H:%M} ({meaning.timezone})')
            duration = f'{meaning.duration_minutes} minutter' if meaning.duration_minutes else 'ikke valgt'
            await self.send_response(message, f'📋 Tolkning før lagring: {description}, dato {meaning.local_date:%d.%m.%Y}, varighet {duration}.')
            # Add to calendar
            item = await self.calendar.add_item(
                guild_id=guild_id,
                user_id=message.author.id,
                username=message.author.name,
                title=item_data["title"],
                date_str=item_data["date"],
                time_str=item_data.get("time"),
                recurrence=item_data.get("recurrence"),
                recurrence_day=item_data.get("recurrence_day"),
                end_count=item_data.get("end_count"),
                end_date=item_data.get("end_date"),
                rrule_day=item_data.get("rrule_day"),
                gcal_event_id=None,
                gcal_link=None,
                channel_id=message.channel.id,
                kind=item_data.get("kind", item_data.get("type", "event")),
                duration_minutes=item_data.get("duration_minutes"),
                timezone=item_data.get("timezone", "Europe/Oslo"),
                fold=item_data.get("fold"),
            )

            if item:
                response_text = self.calendar.format_single_item(item)
                if str(item.get('sync_blocked') or '').startswith('google_'):
                    response_text += '\n📌 Gjentakelsen er lagret lokalt; Google-endringen må avklares før den kan sendes.'
                elif item.get('sync_blocked'):
                    response_text += '\n📌 Bare lokalt: Google-synkronisering krever avklart arrangementstype, dato og varighet.'
                elif item.get('_local_sync_pending'):
                    response_text += '\n⏳ Google-endring er lagret som ventende; ekstern gjennomføring er ikke bekreftet.'
            else:
                response_text = (
                    "❌ Beklager, jeg klarte ikke å legge til i kalenderen. Prøv igjen!"
                )

            await self.send_response(message, response_text)

        except ValueError as error:
            code = getattr(error, 'reason_code', str(error))
            if code in ('ambiguous_recurrence_end', 'invalid_recurrence_end_count',
                'invalid_recurrence_end_date', 'recurrence_end_precedes_anchor'):
                await self.send_response(message, '❌ Gjentakelsen må ha enten et positivt antall forekomster eller en sluttdato etter startdatoen.')
            else:
                await self.send_response(message, f"❌ Dato/tid må avklares før lagring: {getattr(error, 'reason_code', 'invalid_date_or_time')}. Velg gyldig dato, tidspunkt og eventuell DST-fold (0/1).")
        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error handling calendar item: {e}")

    async def handle_list(self, message) -> None:
        """Handle listing calendar items."""
        try:
            guild_id = self.get_guild_id(message)
            actor = self._actor(message)
            scope = self.calendar.scope_key(operation='read')
            await self.calendar.prune_mutation_history()
            revision, displayed = self.calendar.display_snapshot(scope)
            calendar_text = self.calendar.format_list(guild_id, days=90, items=displayed)
            self._remember_list(actor, scope, displayed, revision)

            if calendar_text:
                response_text = calendar_text
            else:
                response_text = (
                    "📭 **Kalenderen er tom**\n\n"
                    "Legg til med:\n"
                    "• `@inebotten [noe] på [dato]`\n"
                    "• `@inebotten Jeg må [gjøremål] på [dato]`"
                )

            await self.send_response(message, response_text)

        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error listing calendar: {e}")

    def _actor(self, message):
        return self.request_context or RequestContext.from_message(message, 'no')

    def _list_key(self, actor, scope):
        return (actor.user_id, actor.channel_id, actor.guild_id, actor.channel_kind, scope)

    def _remember_list(self, actor, scope, items, revision):
        self._displayed_lists[self._list_key(actor, scope)] = (
            revision, [item['id'] for item in items[:10]], self.calendar.clock.monotonic() + 300)
        while len(self._displayed_lists) > 128:
            self._displayed_lists.popitem(last=False)

    def _select_items(self, message, query, *, bulk=False, action='slett'):
        actor = self._actor(message)
        scope = self.calendar.scope_key(operation='write')
        explicit_id = (query or '').startswith('#')
        index = None if explicit_id else self._extract_target_index(query)
        query = (query or '').lstrip('#')
        revision = self.calendar._storage.revision
        if index is not None:
            display = self._displayed_lists.get(self._list_key(actor, scope))
            if display is None or self.calendar.clock.monotonic() >= display[2]:
                raise ValueError('Vis kalenderlisten før du bruker et nummer.')
            if display[0] != self.calendar._storage.revision:
                raise ValueError('Kalenderlisten er endret. Vis listen på nytt før du velger et nummer.')
            if not 1 <= index <= len(display[1]):
                raise ValueError('Nummeret finnes ikke i den viste listen.')
            ids = [display[1][index - 1]]
            revision = display[0]
        else:
            items = self.calendar.get_upcoming(scope, days=365)
            # Short IDs have exact prefix semantics; never choose a title's first match.
            ids = [item['id'] for item in items if len(query or '') >= 8 and item['id'].startswith(query)]
            if not ids and not explicit_id:
                ids = [item['id'] for item in items if (query or '').lower() in item['title'].lower()]
            if len(ids) > 1 and not bulk:
                matches = [(n, item) for n, item in enumerate(items, 1) if item['id'] in ids]
                raise ValueError(self._format_match_prompt(query, matches, action=action))
        if not ids:
            raise ValueError('Fant ikke oppføringen i den synlige kalenderlisten.')
        return actor, scope, ids, revision

    async def _request_preview(self, message, operation, query=None, *, changes=None, clear=False):
        if clear:
            actor = self._actor(message)
            scope = self.calendar.scope_key(operation='write')
            revision = self.calendar._storage.revision
            ids = [item['id'] for item in self.calendar.items.get(scope, [])
                   if not item.get('_mutation_deleted') and not item.get('delete_pending')]
            if not ids:
                await self.send_response(message, '📭 Kalenderen er allerede tom.')
                return
        else:
            bulk_title = self._extract_bulk_title(query or '')
            action = {'delete': 'slett', 'complete': 'ferdig', 'skip': 'hopp over', 'edit': 'rediger'}[operation]
            actor, scope, ids, revision = self._select_items(message, bulk_title or query, bulk=bool(bulk_title), action=action)
        proposal = self.calendar.preview_mutation(actor, scope, ids, operation,
            revision, changes=changes)
        labels = {'delete': 'sletting', 'clear': 'tømming', 'complete': 'fullføring',
            'skip': 'hopping over', 'edit': 'redigering'}
        lines = [f"⚠️ Forhåndsvisning av {labels[operation]} — {len(ids)} oppføringer:"]
        for effect in proposal.effects:
            line = f"• `#{effect['item_id'][:8]}` {effect['title']}"
            if operation == 'edit':
                after = effect['after']
                line += f" → {after['title']} — {after.get('date', '')} {after.get('time') or ''}"
                line += f" ({after.get('kind')}, {after.get('timezone')}; varighet {after.get('duration_minutes') or 'ukjent'})"
                if effect.get('edit_scope'):
                    line += f" · omfang: {effect['edit_scope']}"
            if operation == 'complete' and effect['before'].get('recurrence'):
                line += f" → neste dato {effect['after']['date']}"
            if effect.get('occurrence_id'):
                line += f" · forekomst `{effect['occurrence_id'][:8]}`"
            lines.append(line)
        if any(effect['remote_pending'] for effect in proposal.effects):
            lines.append('Google-endringer lagres som ventende lokalt; ekstern gjennomføring er ikke bekreftet.')
        if any(effect.get('remote_blocked') for effect in proposal.effects):
            lines.append('Google-forekomstendringen er bare lagret lokalt; ekstern gjentakelse krever egen avklaring.')
        lines.append(f"Send `@inebotten bekreft kalender {proposal.token}` innen fem minutter.")
        await self.send_response(message, '\n'.join(lines))

    async def handle_clear(self, message) -> None:
        """Create or apply an exact selection, or restore its local inverse."""
        try:
            match = re.search(r'\b(bekreft|confirm|angre|undo)\s+(?:kalender\s+)?([A-Za-z0-9_-]{20,})(?![A-Za-z0-9_-])', message.content, re.I)
            if match:
                actor, token = self._actor(message), match.group(2)
                if match.group(1).lower() in ('angre', 'undo'):
                    result = await self.calendar.undo_mutation(actor, token)
                    text = f"↩️ Gjenopprettet {result['restored_count']} oppføringer lokalt."
                    if result['remote_limitations']:
                        text += '\n' + result['remote_limitations'][0]
                else:
                    result = await self.calendar.apply_preview(actor, token)
                    label = {'clear': 'Slettet', 'delete': 'Slettet', 'complete': 'Fullført',
                        'skip': 'Hoppet over', 'edit': 'Oppdatert'}[result['operation']]
                    text = f"✅ {label} {result['applied_count']} oppføringer lokalt."
                    text += f"\nAngre med `@inebotten angre kalender {result['undo_token']}` før {result['undo_expires_at']}."
                    if result['remote_pending']:
                        text += '\nGoogle-endring venter; lokal lagring bekrefter ikke ekstern gjennomføring.'
                    if result.get('remote_blocked'):
                        text += '\nGoogle-forekomstendringen er lagret lokalt, men ikke sendt til Google.'
                await self.send_response(message, text)
            else:
                await self._request_preview(message, 'clear', clear=True)
        except (ValueError, PermissionError, StorageMutationError) as error:
            await self.send_response(message, f'❌ Endringen ble ikke utført: {error}. Vis kalenderen og lag en ny forhåndsvisning.')

    def _clear_is_confirmed(self, content: str) -> bool:
        """Require an explicit confirmation token for whole-calendar deletion."""
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").lower()
        return any(
            re.search(rf"\b{re.escape(keyword)}\b", cleaned)
            for keyword in self.CLEAR_CONFIRM_KEYWORDS
        )

    def _clear_confirmation_count(self, content: str) -> Optional[int]:
        """Return the confirmed clear count when the user supplied one."""
        if not self._clear_is_confirmed(content):
            return None
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").lower()
        match = re.search(r"\b(?:bekreft|confirm)\s+(\d+)\b", cleaned)
        if not match:
            return None
        return int(match.group(1))

    async def handle_delete(self, message) -> None:
        try:
            await self._request_preview(message, 'delete', self._extract_search_text(message.content))
        except (ValueError, PermissionError, StorageMutationError) as error:
            await self.send_response(message, f'❌ {error}')

    async def handle_complete(self, message) -> None:
        try:
            cleaned = re.sub(r"<@!?\d+>|@inebotten", "", message.content or "", flags=re.IGNORECASE)
            operation = 'skip' if re.search(r'\b(?:hopp over|skipp)\b', cleaned, re.IGNORECASE) else 'complete'
            await self._request_preview(message, operation, self._extract_search_text(message.content))
        except (ValueError, PermissionError, StorageMutationError) as error:
            await self.send_response(message, f'❌ {error}')

    _EDIT_FIELD_MAP = {
        "tittel": "title",
        "title": "title",
        "dato": "date",
        "date": "date",
        "tid": "time",
        "time": "time",
        "kl": "time",
        "klokken": "time",
        "gjentakelse": "recurrence",
        "recurrence": "recurrence",
        "gjenta": "recurrence",
        "beskrivelse": "description",
        "description": "description",
        "desc": "description",
        "varighet": "duration_minutes",
        "duration": "duration_minutes",
        "tidssone": "timezone",
        "timezone": "timezone",
        "fold": "fold",
    }

    def _parse_edit_command(self, content: str):
        """
        Extract index, search text, field name, and value from an edit command.

        Returns:
            (index, search_text, field, value) where index is 1-based or None,
            search_text is the title snippet to search for, field is the
            Norwegian/English keyword before the colon, and value is the text
            after the colon.
        """
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        for kw in (
            "kalender oppdater",
            "kalender oppdatere",
            "kalender rediger",
            "kalender redigere",
            "kalender endre",
            "oppdater",
            "oppdatere",
            "endre",
            "rediger",
            "redigere",
            "edit",
        ):
            if cleaned.lower().startswith(kw):
                cleaned = cleaned[len(kw) :].strip()
                break

        if ":" not in cleaned:
            return None, None, None, None

        prefix, value = cleaned.split(":", 1)
        prefix = prefix.strip()
        value = value.strip()

        field = None
        search_text = prefix
        for nor_field in sorted(self._EDIT_FIELD_MAP.keys(), key=len, reverse=True):
            pattern = rf"\b{re.escape(nor_field)}$"
            if re.search(pattern, prefix, re.IGNORECASE):
                field = nor_field
                search_text = re.sub(pattern, "", prefix, flags=re.IGNORECASE).strip()
                break

        index_source = (search_text if field else prefix).strip()
        index = int(index_source) if re.fullmatch(r"\d+", index_source) else None

        if index is not None:
            search_text = None
        elif field and not search_text:
            search_text = None

        return index, search_text, field, value

    def _parse_edit_scope(self, content: str):
        cleaned = re.sub(r"<@!?\d+>|@inebotten", "", content or "", flags=re.IGNORECASE).casefold()
        if re.search(r'\b(?:denne og fremtidige|denne og de fremtidige|herfra og ut|fremover)\b', cleaned):
            return 'future'
        if re.search(r'\b(?:hele serien|alle forekomster|hele rekken)\b', cleaned):
            return 'series'
        if re.search(r'\b(?:bare denne|kun denne|denne forekomsten|denne gangen)\b', cleaned):
            return 'this'
        return None

    def _strip_edit_scope(self, content: str):
        return re.sub(r'\b(?:denne og de fremtidige|denne og fremtidige|herfra og ut|fremover|'
            r'hele serien|alle forekomster|hele rekken|bare denne|kun denne|denne forekomsten|denne gangen)\b',
            '', content or '', flags=re.IGNORECASE).strip()

    def _parse_date_value(self, value: str) -> Optional[str]:
        value = value.strip()

        if re.match(r"^\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?$", value):
            return self.calendar._normalize_date_format(value)

        try:
            parsed = self.nlp_parser.parse_event(f"x på {value} kl 12")
            if parsed and parsed.get("date"):
                return parsed["date"]
        except Exception:
            pass

        return value

    async def handle_edit(self, message, payload=None) -> None:
        """
        Handle editing calendar items in-place.
        Supports:
          - endre 2 tittel: Ny tittel
          - rediger møte dato: i morgen
        """
        try:
            guild_id = self.get_guild_id(message)
            edit_scope = self._parse_edit_scope(message.content)
            index, search_text, field, value = self._parse_edit_command(
                self._strip_edit_scope(message.content)
            )

            if not field or not value:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            kwarg_field = self._EDIT_FIELD_MAP.get(field.lower())
            if not kwarg_field:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            if kwarg_field in ('duration_minutes', 'fold'):
                try:
                    value = int(value)
                except ValueError:
                    await self.send_response(message, '❌ Varighet må være positive minutter; fold må være 0 eller 1.')
                    return
            explicit_fold = None
            if kwarg_field in ('date', 'time'):
                match = re.search(r'\s+fold\s*[:=]?\s*([01])\s*$', value, re.IGNORECASE)
                if match:
                    explicit_fold = int(match.group(1))
                    value = value[:match.start()].strip()
            if kwarg_field == "date":
                parsed = self._parse_date_value(value)
                if parsed:
                    value = parsed

            changes = {kwarg_field: value}
            if edit_scope:
                changes['edit_scope'] = edit_scope
            if explicit_fold is not None:
                changes['fold'] = explicit_fold
            query = str(index) if index is not None else search_text
            if not query:
                await self.send_response(message, self.loc.t('calendar_edit_invalid'))
                return
            try:
                await self._request_preview(message, 'edit', query, changes=changes)
            except ValueError as error:
                await self.send_response(message, f'❌ {error}')

        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error editing item: {e}")

    async def handle_sync(self, message) -> None:
        """Handle manual sync from Google Calendar."""
        try:
            guild_id = self.get_guild_id(message)
            channel_id = getattr(getattr(message, "channel", None), "id", None)
            
            if not self.calendar.ensure_gcal_configured():
                await self.send_response(
                    message, 
                    "❌ Google Calendar er ikke konfigurert eller koblet til ennå."
                )
                return

            await self.send_response(message, "🔄 Synkroniserer med Google Calendar...")
            
            deadline = time.monotonic() + 20
            content = re.sub(r'<@!?\d+>|@inebotten', '', message.content).strip().lower()
            match = re.fullmatch(r'synk konflikt (?:((?:påminnelse)) )?([a-f0-9]{32}) (lokal|google)', content)
            confirmation = re.fullmatch(r'bekreft synk (?:((?:påminnelse)) )?([a-f0-9]{32})', content)
            target = self.calendar
            if (match and match[1]) or (confirmation and confirmation[1]):
                target = self.monitor.reminders
                target.configure_google(self.calendar.gcal, slot=self.calendar._outbox.slot,
                    access_policy=self.calendar.access_policy)
            if match:
                proposal = target.preview_sync_conflict(self._actor(message), match[2],
                    'use_local' if match[3] == 'lokal' else 'use_remote')
                effect = proposal.effects[0]
                def display(value):
                    return {key: value[key] for key in ('summary', 'description', 'start', 'end', 'recurrence', 'delete') if key in value}
                prefix = 'påminnelse ' if match[1] else ''
                review_text = ('⚖️ Se gjennom konflikten før valg:\nLokalt: '
                    + json.dumps(display(effect['local']), ensure_ascii=False)
                    + '\nGoogle: ' + json.dumps(display(effect['remote']), ensure_ascii=False)
                    + f'\nValg: {match[3]}. Erstatter ventende ID-er: ' + ', '.join(effect['pending_operation_ids'])
                    + f'\nBekreft innen fem minutter: `@inebotten bekreft synk {prefix}{proposal.token}`')
                if len(review_text) > 1900:
                    target._sync_conflicts.pop(proposal.token, None)
                    await self.send_response(message, '❌ Konflikten er for stor til en fullstendig forhåndsvisning i Discord. Ingen bekreftelse er åpnet.')
                    return
                await self.send_response(message, review_text)
                return
            if confirmation:
                result = await target.apply_sync_conflict(self._actor(message), confirmation[2], deadline=deadline)
                await self.send_response(message, '✅ Valget er lagret. '
                    + ('Google-endringen venter på bekreftet gjennomføring.' if result.state == 'pending' else 'Den gjennomgåtte Google-versjonen er tatt i bruk lokalt.'))
                return
            await self.calendar.process_due(deadline=deadline)
            reminders = getattr(self.monitor, 'reminders', None)
            if reminders is not None and hasattr(reminders, 'configure_google'):
                reminders.configure_google(self.calendar.gcal, slot=self.calendar._outbox.slot,
                    access_policy=self.calendar.access_policy)
                await reminders.process_due(deadline=deadline)
            count = await self.calendar.sync_from_gcal(default_guild_id=guild_id,
                default_channel_id=channel_id, deadline=deadline)
            states = self.calendar.sync_summary()
            if states['pending'] or states['unknown'] or states['failed'] or states['conflict']:
                labels = {'pending': 'ventende', 'unknown': 'uavklart', 'failed': 'feilet', 'conflict': 'konflikt'}
                await self.send_response(message, '📌 Google-status: ' + ', '.join(
                    f'{labels[key]}: {states[key]}' for key in ('pending', 'unknown', 'failed', 'conflict'))
                    + '\nKonflikter: ' + ', '.join(states['conflict_ids'])
                    + '\nSe gjennom med `@inebotten synk konflikt <ID> lokal|google`.')
            sync_error = getattr(self.calendar, "last_gcal_sync_error", None)
            if sync_error:
                await self.send_response(message, f"❌ {sync_error}")
                return
            
            if count > 0:
                await self.send_response(message, f"✅ Ferdig! Synkroniserte {count} elementer med Google Calendar.")
                # Show the updated list
                await self.handle_list(message)
            else:
                await self.send_response(message, "✅ Synkronisering ferdig. Ingen nye endringer funnet i Google Calendar.")
        except (ValueError, TimeoutError):
            await self.send_response(message, '❌ Valget eller Google-svaret er utdatert eller utilgjengelig. Lag en ny forhåndsvisning før bekreftelse.')
        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error syncing calendar: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under synkronisering med Google Calendar.")

    async def handle_auth(self, message, payload: Dict[str, Any] = None) -> None:
        """Handle Google Calendar authentication commands."""
        try:
            if not self.calendar.gcal:
                from cal_system.google_calendar_manager import GoogleCalendarManager
                self.calendar.gcal = GoogleCalendarManager()
                
            code = payload.get("auth_code") if payload else None
            requester_id = getattr(getattr(message, "author", None), "id", None)
            channel_id = getattr(getattr(message, "channel", None), "id", None)
            
            if code:
                success, msg = self.calendar.gcal.exchange_code(
                    code,
                    requester_id=requester_id,
                    channel_id=channel_id,
                )
                if success:
                    self.calendar.gcal_enabled = True
                    await self.send_response(message, "✅ " + msg)
                    await self.handle_sync(message)
                else:
                    await self.send_response(message, "❌ " + msg)
            else:
                success, result = self.calendar.gcal.get_auth_url(
                    requester_id=requester_id,
                    channel_id=channel_id,
                )
                if success:
                    auth_url = result
                    response_text = (
                        "🔐 **Koble til Google Calendar**\n\n"
                        f"1. Klikk på denne lenken for å logge inn med Google-kontoen din:\n{auth_url}\n\n"
                        "2. Etter at du har logget inn, vil nettleseren prøve å gå til `localhost`. "
                        "Dette vil kanskje feile, men det går fint! Se i adresselinjen din.\n\n"
                        "3. Kopier koden fra adresselinjen (etter `code=`) og send den til meg slik:\n"
                        "`@inebotten kalender kode <din_kode>`"
                    )
                    await self.send_response(message, response_text)
                else:
                    await self.send_response(message, "❌ " + result)
                    
        except PermissionError:
            await self.send_response(message, '🔒 Kalenderområdet er ikke tilgjengelig for deg i denne samtalen.')
        except StorageMutationError:
            await self.send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
        except Exception as e:
            self.log(f"Error handling calendar auth: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under autentiseringen.")

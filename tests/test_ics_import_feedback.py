"""Attachment mistakes should explain recovery without reading or writing data."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.calendar_exchange import MAX_BYTES
from core.request_context import RequestContext, request_scope
from features.calendar_handler import CalendarHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('attachments, expected', [
    ([], 'Legg ved én ICS-fil i samme melding'),
    ([SimpleNamespace(filename='one.ics'), SimpleNamespace(filename='two.ics')], 'én ICS-fil'),
    ([SimpleNamespace(filename='calendar.zip')], '.ics'),
    ([SimpleNamespace(filename='calendar.ics', size=MAX_BYTES+1)], '1 MiB'),
])
async def test_import_attachment_error_is_actionable_and_read_only(tmp_path, attachments, expected):
    calendar = CalendarManager(storage_path=tmp_path/'calendar.json')
    actor = RequestContext('import', '7', '9', '123', 'no', 'guild')
    monitor = SimpleNamespace(calendar=calendar, nlp_parser=None, rate_limiter=None,
                              loc=None, client=None)
    handler = CalendarHandler(monitor)
    handler.send_response = AsyncMock()
    handler._read_ics_attachment = AsyncMock()
    try:
        with request_scope(actor):
            calendar.add_item('shared', '7', 'Tester', 'Existing', '04.01.2027')
            before = calendar.storage_path.read_bytes()
            await handler.handle_exchange(SimpleNamespace(attachments=attachments), {'action':'import'})
        reply = handler.send_response.await_args.args[1]
        assert expected in reply
        if not attachments:
            assert '@inebotten kalender importer ics' in reply
        handler._read_ics_attachment.assert_not_awaited()
        assert calendar.storage_path.read_bytes() == before
        assert handler._exchange is None or not handler._exchange.previews.entries
    finally:
        calendar._storage.close()


@pytest.mark.asyncio
async def test_attached_export_preview_and_confirmation_keep_duplicate_unchanged(tmp_path):
    from cal_system.calendar_exchange import CalendarExchange

    calendar = CalendarManager(storage_path=tmp_path/'calendar.json')
    actor = RequestContext('import', '7', '9', '123', 'no', 'guild')
    handler = CalendarHandler(SimpleNamespace(calendar=calendar, nlp_parser=None,
                                             rate_limiter=None, loc=None, client=None))
    handler.send_response = AsyncMock()
    try:
        with request_scope(actor):
            item = calendar.add_item('shared', '7', 'Tester', 'Existing', '04.01.2027',
                                     '14:00', duration_minutes=60)
            raw = CalendarExchange(calendar).export_ics(actor, 'shared', [item['id']])
            before = calendar.storage_path.read_bytes()
            handler._read_ics_attachment = AsyncMock(return_value=raw)
            message = SimpleNamespace(attachments=[SimpleNamespace(filename='existing.ics',size=len(raw))])
            await handler.handle_exchange(message, {'action':'import'})
            reply = handler.send_response.await_args.args[1]
            assert '0 nye, 0 endrede, 1 identiske' in reply
            assert 'bekreft ics' in reply
            assert calendar.storage_path.read_bytes() == before
            token = next(iter(handler._exchange.previews.entries))
            await handler.handle_exchange(message, {'action':'apply', 'token':token})
            assert 'Importerte 0 oppføringer' in handler.send_response.await_args.args[1]
            assert calendar.storage_path.read_bytes() == before
    finally:
        calendar._storage.close()

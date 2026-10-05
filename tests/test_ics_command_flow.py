import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.calendar_exchange import CalendarExchange
from core.command_registry import validate_payload
from core.intent_router import IntentRouter, BotIntent
from core.outbound_sender import DeliveryResult
from core.request_context import RequestContext, request_scope
from features.calendar_handler import CalendarHandler
from tests.test_ics_exchange import data, actor


def handler(calendar, sender=None):
    monitor=SimpleNamespace(calendar=calendar,nlp_parser=None,rate_limiter=None,
        loc=SimpleNamespace(current_lang='no'),client=None,outbound=sender)
    result=CalendarHandler(monitor);result.send_response=AsyncMock()
    return result


def message(content,attachments=()):
    return SimpleNamespace(id=42,content=content,author=SimpleNamespace(id=7,name='Tester'),guild=None,
        channel=SimpleNamespace(id=9,send=AsyncMock()),attachments=attachments)


def test_anchored_routing_keeps_token_case_and_rejects_prose():
    router=IntentRouter(SimpleNamespace())
    token='AbCdEfGhIjKlMnOpQrStUvWx'
    result=router.route('bekreft ics '+token)
    assert result.intent==BotIntent.CALENDAR_EXCHANGE
    assert validate_payload(result.intent,result.payload)['exchange']['token']==token
    result=router.route('kalender eksporter ics alle')
    assert result.intent==BotIntent.CALENDAR_EXCHANGE and result.payload['exchange']['item_ids'] is None
    assert router.route('kalender importer ics').intent==BotIntent.CALENDAR_EXCHANGE
    assert router.route('Jeg lurer på om kalender kan importer ics').intent!=BotIntent.CALENDAR_EXCHANGE
    with pytest.raises(ValueError):validate_payload(BotIntent.CALENDAR_EXCHANGE,{'exchange':{'action':'import','user_id':'8'}})


async def test_handler_import_is_inert_until_same_actor_confirms(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        service=handler(calendar)
        raw=data('UID:x\r\nSUMMARY:Fixture\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
        service._read_ics_attachment=AsyncMock(return_value=raw)
        attached=SimpleNamespace(filename='fixture.ics',size=len(raw))
        await service.handle_exchange(message('kalender importer ics',[attached]),{'action':'import'})
        assert not calendar.items
        token=next(iter(service._exchange.previews.entries))
        assert 'Fixture' in service.send_response.await_args.args[1]
        await service.handle_exchange(message('bekreft ics '+token),{'action':'apply','token':token})
        assert calendar.items['shared'][0]['title']=='Fixture'
        assert calendar.items['shared'][0]['gcal_event_id'] is None
    finally:calendar._storage.close()


async def test_export_uses_shared_sender_and_policy_after_quota(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    sender=SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered',message_id='receipt')))
    try:
        with request_scope(actor()):item=calendar.add_item('shared','7','Tester','Fixture','04.01.2027')
        service=handler(calendar,sender)
        await service.handle_exchange(message('kalender eksporter ics alle'),{'action':'export','item_ids':None})
        call=sender.send.await_args
        assert call.args[0]=='9' and call.kwargs['_can_dispatch']()
        attachment=call.kwargs['attachments'][0]
        assert attachment.content_type=='text/calendar' and b'UID:' in attachment.data
        assert not service.send_response.await_count
    finally:calendar._storage.close()


@pytest.mark.parametrize('url',['http://cdn.discordapp.com/attachments/9/42/f.ics',
    'https://example.invalid/attachments/9/42/f.ics','https://cdn.discordapp.com/attachments/8/42/f.ics',
    'https://cdn.discordapp.com/attachments/9/41/f.ics'])
async def test_download_refuses_unrelated_attachment_path_before_network(tmp_path,url):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        with pytest.raises(ValueError,match='invalid_discord_attachment'):
            await handler(calendar)._read_ics_attachment(message(''),SimpleNamespace(id=42,url=url),1024)
    finally:calendar._storage.close()


async def test_stream_limit_is_enforced_and_session_closes(tmp_path,monkeypatch):
    import aiohttp
    closed=[]
    class Context:
        def __init__(self,value):self.value=value
        async def __aenter__(self):return self.value
        async def __aexit__(self,*args):closed.append(True)
    async def chunks(_size):
        yield b'a'*700
        yield b'b'*700
    class Session:
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False and kwargs['auto_decompress'] is False
        async def __aenter__(self):return self
        async def __aexit__(self,*args):closed.append(True)
        def get(self,url,**kwargs):
            assert kwargs['allow_redirects'] is False
            return Context(SimpleNamespace(status=200,headers={},content_length=None,
                content=SimpleNamespace(iter_chunked=chunks)))
    monkeypatch.setattr(aiohttp,'ClientSession',Session)
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        with pytest.raises(ValueError,match='attachment_too_large'):
            await handler(calendar)._read_ics_attachment(message(''),
                SimpleNamespace(id=42,url='https://cdn.discordapp.com/attachments/9/42/f.ics'),1024)
        assert len(closed)==2
    finally:calendar._storage.close()


def test_reimport_after_restart_and_failed_apply_preserve_source_identity(tmp_path,monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    path=tmp_path/'calendar.json'; calendar=CalendarManager(storage_path=path)
    raw=data('UID:restart\r\nSUMMARY:Fixture\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
    service=CalendarExchange(calendar); preview=service.preview_ics(actor(),'shared',raw)
    asyncio.run(service.apply(actor(),preview['token'])); original=path.read_bytes();calendar._storage.close()
    calendar=CalendarManager(storage_path=path)
    try:
        service=CalendarExchange(calendar)
        assert service.preview_ics(actor(),'shared',raw)['duplicate']==1
        preview=service.preview_ics(actor(),'shared',raw.replace(b'Fixture',b'Changed'))
        monkeypatch.setattr(calendar._storage,'commit',lambda *_args,**_kwargs:StorageCommit(False,'write_failed'))
        with pytest.raises(StorageMutationError):asyncio.run(service.apply(actor(),preview['token']))
        assert path.read_bytes()==original and calendar.items['shared'][0]['title']=='Fixture'
    finally:calendar._storage.close()


async def test_large_import_delivers_complete_review_or_invalidates_token(tmp_path):
    import json
    sender=SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered',message_id='receipt')))
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        pieces=[data(f'UID:item{i}\r\nSUMMARY:Item {i}\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105') for i in range(11)]
        body=b''.join(piece[piece.index(b'BEGIN:VEVENT'):piece.index(b'END:VCALENDAR')] for piece in pieces)
        raw=b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+body+b'END:VCALENDAR\r\n'
        service=handler(calendar,sender);service._read_ics_attachment=AsyncMock(return_value=raw)
        attached=SimpleNamespace(filename='batch.ics',size=len(raw))
        await service.handle_exchange(message('kalender importer ics',[attached]),{'action':'import'})
        assert not calendar.items
        review=json.loads(sender.send.await_args.kwargs['attachments'][0].data)
        assert len(review['changes'])==11 and review['changes'][-1]['title']=='Item 10'
        sender.send.return_value=DeliveryResult('unknown')
        service._exchange.previews.entries.clear()
        await service.handle_exchange(message('kalender importer ics',[attached]),{'action':'import'})
        assert not service._exchange.previews.entries
    finally:calendar._storage.close()


@pytest.mark.parametrize("count", [1, 11])
async def test_real_ics_preview_keeps_titles_inert_in_reply_and_attachment_path(tmp_path, count):
    from features.base_handler import BaseHandler
    calendar = CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        title = "@everyone @here <@&123456789012345678>"
        parts = [data(f'UID:mention{i}\r\nSUMMARY:{title}\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105') for i in range(count)]
        body = b''.join(part[part.index(b'BEGIN:VEVENT'):part.index(b'END:VCALENDAR')] for part in parts)
        raw = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+body+b'END:VCALENDAR\r\n'
        service = handler(calendar)
        service.send_response = BaseHandler.send_response.__get__(service)
        service._read_ics_attachment = AsyncMock(return_value=raw)
        incoming = message('kalender importer ics', [SimpleNamespace(filename='fixture.ics', size=len(raw))])
        incoming.guild = SimpleNamespace(id=1)
        remote = AsyncMock(return_value=SimpleNamespace(id='preview-receipt'))
        incoming.reply = remote
        incoming.channel.send = remote
        await service.handle_exchange(incoming, {'action':'import'})
        remote.assert_awaited_once()
        assert title in remote.await_args.args[0]
        assert remote.await_args.kwargs['allowed_mentions'].to_dict()['parse'] == []
        assert not calendar.items
        assert len(service._exchange.previews.entries) == 1
    finally:
        calendar._storage.close()

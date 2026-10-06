"""Synthetic shutdown ownership, deadlines and final-flush receipts."""
import asyncio
from collections import defaultdict
from types import SimpleNamespace
import threading
import time

import pytest

from core.message_monitor import MessageMonitor
from core.selfbot_runner import SelfbotRunner
from features.forecast_service import ForecastService


def monitor():
    value = MessageMonitor.__new__(MessageMonitor)
    value._background_tasks = set()
    value._task_health = {}
    value.intent_stats = defaultdict(dict, {'help': {'count': 3, 'errors': 0}})
    value._last_persisted_intent_stats = {}
    value._last_persisted_rate_stats = {}
    value.rate_limiter = SimpleNamespace(get_stats=lambda: {'user_stats': {'synthetic': {'requests': 2}}})
    return value


@pytest.mark.asyncio
async def test_final_delta_flush_is_once_across_repeated_and_concurrent_close(monkeypatch):
    value = monitor()
    batches = []
    def save(intents, rates):
        batches.append((intents, rates))
        return True
    monkeypatch.setattr('web_console.console_store.get_console_store', lambda: SimpleNamespace(save_stats=save))
    await asyncio.gather(value.close(time.monotonic() + 1), value.close(time.monotonic() + 1))
    await value.close(time.monotonic() + 1)
    assert len(batches) == 1
    assert batches[0][0]['help']['count'] == 3
    assert batches[0][1]['synthetic'] == 2
    assert value.shutdown_receipt['status'] == 'closed'


@pytest.mark.asyncio
async def test_cancelled_flush_acknowledges_success_before_retry(monkeypatch):
    value = monitor()
    entered, release = threading.Event(), threading.Event()
    batches = []
    def save(intents, rates):
        batches.append((intents, rates))
        entered.set()
        assert release.wait(2)
        return True
    monkeypatch.setattr('web_console.console_store.get_console_store', lambda: SimpleNamespace(save_stats=save))
    task = asyncio.create_task(value._persist_console_stats_once())
    while not entered.is_set():
        await asyncio.sleep(.001)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await value.close(time.monotonic() + 1)
    assert len(batches) == 1


@pytest.mark.asyncio
async def test_failed_flush_retains_delta_and_can_be_retried(monkeypatch):
    value = monitor()
    successes = [False, True]
    batches = []
    def save(intents, rates):
        batches.append((intents, rates))
        return successes.pop(0)
    monkeypatch.setattr('web_console.console_store.get_console_store', lambda: SimpleNamespace(save_stats=save))
    await value.close(time.monotonic() + 1)
    assert value._last_persisted_intent_stats == {}
    assert value.shutdown_receipt['status'] == 'incomplete'
    assert value.shutdown_receipt['unsaved_intents']['help']['count'] == 3
    await value.close(time.monotonic() + 1)
    assert len(batches) == 2
    assert value.shutdown_receipt['status'] == 'closed'


@pytest.mark.asyncio
async def test_cancelled_caller_and_deadline_leave_worker_owned(monkeypatch):
    from utils.resource_shutdown import OwnedResources
    scope = OwnedResources()
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []
    async def close_slow():
        entered.set()
        await release.wait()
        closed.append('slow')
    scope.add('first', lambda: closed.append('first'))
    scope.add('slow', close_slow)
    task = asyncio.create_task(scope.close(time.monotonic() + .03))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(.05)
    assert scope.receipt()['pending'] == ['slow']
    assert closed == []
    release.set()
    await scope.close(time.monotonic() + 1)
    await scope.close(time.monotonic() + 1)
    assert closed == ['slow', 'first']


@pytest.mark.asyncio
async def test_forecast_does_not_close_borrowed_aurora():
    closed = []
    class Client:
        async def close(self):
            closed.append(self)
    weather, aurora = Client(), Client()
    service = ForecastService(weather_client=weather, aurora_client=aurora,
                              owns_weather=True, owns_aurora=False)
    await service.close()
    await service.close()
    assert closed == [weather]


@pytest.mark.asyncio
async def test_runner_partial_startup_closes_connector_even_when_not_running():
    runner = SelfbotRunner()
    calls = []
    class Connector:
        async def close(self):
            calls.append('connector')
        def get_stats(self):
            return {}
    runner.ai_connector = Connector()
    await runner.shutdown()
    await runner.shutdown()
    assert calls == ['connector']


@pytest.mark.asyncio
async def test_actual_monitor_composition_closes_owned_managers_and_keeps_borrowed_memory(monkeypatch, tmp_path):
    from memory.user_memory import UserMemory
    from core.rate_limiter import RateLimiter
    memory = UserMemory(storage_path=tmp_path / 'borrowed-memory.json')
    monkeypatch.setattr('memory.user_memory.get_user_memory', lambda: memory)
    value = MessageMonitor(SimpleNamespace(config=SimpleNamespace(DISCORD_TOKEN='synthetic'), get_channel=lambda _: None),
                           None, RateLimiter(), None)
    await value.setup()
    calls = []
    class Session:
        closed = False
        async def close(self):
            calls.append(self)
            self.closed = True
    crypto, aurora, weather = Session(), Session(), Session()
    value.crypto.session, value.aurora.session = crypto, aurora
    value.forecasts.weather_client.session = weather
    await memory.add_interest('synthetic', 'synthetic interest')
    assert memory._storage._owned
    await value.close(time.monotonic() + 1)
    assert value.shutdown_receipt['status'] == 'closed'
    assert calls == [weather, aurora, crypto]
    assert not value.calendar._storage._owned
    assert not value.reminders._storage._owned
    assert not value.poll._storage._owned
    assert memory._storage._owned
    with pytest.raises(RuntimeError, match='closed'):
        await value.crypto._get_session()
    await memory._storage.aclose()


@pytest.mark.asyncio
async def test_deadline_preserves_background_work_before_closing_resource(monkeypatch):
    from utils.resource_shutdown import OwnedResources
    value = monitor()
    value._owned_resources = OwnedResources()
    calls = []
    value._owned_resources.add('session', lambda: calls.append('session'))
    entered, release = asyncio.Event(), asyncio.Event()
    async def work():
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()
    task = asyncio.create_task(work())
    value._background_tasks.add(task)
    await entered.wait()
    monkeypatch.setattr('web_console.console_store.get_console_store', lambda: SimpleNamespace(save_stats=lambda *_: True))
    start = time.monotonic()
    await value.close(start + .03)
    assert time.monotonic() - start < .15
    assert value.shutdown_receipt['status'] == 'incomplete'
    assert calls == []
    release.set()
    await value.close(time.monotonic() + 1)
    assert calls == ['session']
    assert task.done()


@pytest.mark.asyncio
async def test_console_stop_closes_idle_owned_connections():
    from web_console.server import ConsoleServer
    server = ConsoleServer(host='127.0.0.1', port=0, api_key='synthetic', request_read_timeout=60)
    await server.start()
    reader, writer = await asyncio.open_connection('127.0.0.1', server.actual_port)
    while not server._connection_tasks:
        await asyncio.sleep(.001)
    await asyncio.wait_for(server.stop(), timeout=.2)
    assert await asyncio.wait_for(reader.read(), timeout=.1) == b''
    assert server._active_connections == 0
    assert not server._connection_tasks
    writer.close()
    await writer.wait_closed()


@pytest.mark.asyncio
async def test_ai_session_waits_for_cancellation_resistant_admitted_work():
    from ai.hermes_connector import HermesConnector
    from ai.result_schema import AIResult, BoundedAdmission
    connector = HermesConnector.__new__(HermesConnector)
    connector._reply_admission = BoundedAdmission()
    release, entered = asyncio.Event(), asyncio.Event()
    class Session:
        closed = False
        async def close(self):
            self.closed = True
    session = connector.session = Session()
    async def operation():
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        return AIResult('success', 'synthetic', 'hermes', 'synthetic')
    request = asyncio.create_task(connector._reply_admission.run(operation, deadline=time.monotonic() + 1,
                                                               provider='hermes', model='synthetic'))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    closer = asyncio.create_task(connector.close())
    await asyncio.sleep(.01)
    assert not closer.done()
    assert not session.closed
    release.set()
    await closer
    await connector.close()
    assert session.closed
    assert connector._reply_admission.in_flight == 0
    refused = await connector._reply_admission.run(operation, deadline=time.monotonic() + 1,
                                                   provider='hermes', model='synthetic')
    assert refused.status == 'unavailable'


@pytest.mark.asyncio
async def test_process_composition_closes_shared_stores_after_client_and_ai(monkeypatch):
    import discord
    from core.message_monitor import SelfbotClient
    calls = []
    async def transport_close(self):
        calls.append('transport')
    monkeypatch.setattr(discord.Client, 'close', transport_close)
    client = SelfbotClient.__new__(SelfbotClient)
    class MemoryOwner:
        async def aclose(self):
            calls.append('memory')
    class Monitor:
        user_memory = SimpleNamespace(_storage=MemoryOwner())
        async def close(self):
            calls.append('monitor')
    class Checker:
        def stop(self):
            calls.append('checker-stop')
        def close_storage(self):
            calls.append('checker-store')
    class Console:
        store = SimpleNamespace(close=lambda: calls.append('console-store'))
        async def stop(self):
            calls.append('console-stop')
    class AI:
        async def close(self):
            calls.append('ai')
    client.monitor, client.reminder_checker, client.console_server = Monitor(), Checker(), Console()
    client.reminder_checker_task = client.console_task = None
    runner = SelfbotRunner()
    runner.client, runner.ai_connector = client, AI()
    monkeypatch.setattr('utils.logger.close_log_capture', lambda: calls.append('capture-stop'))
    monkeypatch.setattr('features.forecast_service._DEFAULT', None)
    await runner.shutdown()
    await runner.shutdown()
    assert calls == ['console-stop', 'checker-stop', 'monitor', 'checker-store', 'transport',
                     'ai', 'memory', 'capture-stop', 'console-store']
    assert runner.shutdown_receipt['status'] == 'closed'


@pytest.mark.asyncio
async def test_incomplete_cleanup_stops_dependencies_and_run_returns_failure():
    runner = SelfbotRunner()
    calls = []
    async def body():
        return 0
    class Client:
        async def close(self):
            calls.append('client')
            raise RuntimeError('synthetic cleanup failure')
    class AI:
        async def close(self):
            calls.append('ai')
    runner._run = body
    runner.client, runner.ai_connector = Client(), AI()
    assert await runner.run() == 2
    assert calls == ['client']
    assert runner.shutdown_receipt['errors'] == {'discord-client': 'RuntimeError'}

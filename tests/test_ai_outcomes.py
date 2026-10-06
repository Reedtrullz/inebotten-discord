"""Offline contracts for structured AI outcomes, admission, and inert drafts."""

import asyncio
import importlib.util
import json
import time
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ai import action_schema
from ai.connector_factory import AIConnectorFactory
from ai.hermes_connector import HermesConnector
from ai.openrouter_connector import OpenRouterConnector
from core.intent_router import BotIntent
from core.message_monitor import MessageMonitor


def require_result_type(test):
    spec = importlib.util.find_spec("ai.result_schema")
    test.assertIsNotNone(spec, "ai.result_schema must define the structured outcome contract")
    from ai.result_schema import AIResult

    return AIResult


def require_reply_method(test, connector):
    method = getattr(connector, "generate_reply", None)
    test.assertTrue(callable(method), "connectors must expose bounded generate_reply")
    return method


def request_context():
    from core.request_context import RequestContext

    return RequestContext("request-1", "user-7", "channel-2", None, "no", "dm")


class FakeResponse:
    def __init__(self, status, *, headers=None, data=None, body="provider error"):
        self.status = status
        self.headers = headers or {}
        self.data = data
        self.body = body
        self.content = self

    async def iter_chunked(self, size):
        raw = json.dumps(self.data).encode() if self.data is not None else self.body.encode()
        for start in range(0, len(raw), size):
            yield raw[start:start + size]

    async def json(self):
        return self.data

    async def text(self):
        return self.body


class FakeRateLimiter:
    def can_send(self):
        return True, "ok"

    async def wait_if_needed(self):
        return True

    def record_dropped(self):
        pass


class FakeMessage:
    def __init__(self, content):
        self.id = "message-1"
        self.content = content
        self.mentions = []
        self.guild = None
        self.channel = SimpleNamespace(id=2)
        self.author = SimpleNamespace(id=7, name="Tester")


class AIOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_openrouter_health_queries_selected_model_with_existing_envelope_bound(self):
        connector = OpenRouterConnector("synthetic-key", model="google/gemma-4-31b-it:free")
        requested = []

        async def request(endpoint, method="POST", payload=None):
            requested.append((endpoint, method))
            data = ({"data": [{"description": "x" * 131073}]} if endpoint == "models"
                    else {"data": {"id": connector.model, "endpoints": [{"status": 0}]}})
            return await connector._handle_response(FakeResponse(200, data=data), expect_text=False)

        connector._make_request = request
        healthy, _ = await connector.check_health()
        self.assertTrue(healthy)
        self.assertEqual(requested, [("models/google/gemma-4-31b-it%3Afree/endpoints", "GET")])
        oversized = await connector._handle_response(
            FakeResponse(200, data={"data": "x" * 131073}), expect_text=False)
        self.assertEqual(oversized.status, "unavailable")

    def result(self, **kwargs):
        AIResult = require_result_type(self)
        defaults = {
            "status": "success",
            "text": "Svar",
            "provider": "openrouter",
            "model": "test/model",
        }
        defaults.update(kwargs)
        return AIResult(**defaults)

    def test_result_schema_exports_validated_outcomes(self):
        AIResult = require_result_type(self)

        result = AIResult(
            status="success",
            text="Hei",
            provider="hermes",
            model="12b",
            fallback=False,
            retry_after_s=None,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.text, "Hei")
        self.assertEqual(result.provider, "hermes")
        with self.assertRaises(ValueError):
            AIResult(status="mystery", text=None, provider="hermes")
        with self.assertRaises(ValueError):
            AIResult(status="success", text=None, provider="hermes")
        with self.assertRaises(ValueError):
            AIResult(status="success", text="x" * 20001, provider="hermes")

    async def test_provider_admission_rejects_overflow_without_queueing(self):
        AIResult = require_result_type(self)
        connector = HermesConnector()
        release = asyncio.Event()
        entered = asyncio.Event()
        calls = 0

        async def blocked_request(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
            await release.wait()
            return AIResult(status="success", text="ferdig", provider="hermes", model="12b")

        connector._make_request = blocked_request
        reply = require_reply_method(self, connector)
        deadline = time.monotonic() + 5
        first = asyncio.create_task(reply(request_context(), "første", deadline=deadline))
        second = asyncio.create_task(reply(request_context(), "andre", deadline=deadline))
        await asyncio.wait_for(entered.wait(), timeout=1)

        overflow = await reply(request_context(), "tredje", deadline=deadline)

        self.assertEqual(overflow.status, "busy")
        self.assertEqual(calls, 2)
        release.set()
        self.assertEqual((await first).status, "success")
        self.assertEqual((await second).status, "success")

    async def test_caller_cancellation_releases_provider_admission(self):
        AIResult = require_result_type(self)
        connector = HermesConnector()
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0

        async def cancellable_request(*args, **kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        connector._make_request = cancellable_request
        reply = require_reply_method(self, connector)
        deadline = time.monotonic() + 5
        pending = asyncio.create_task(reply(request_context(), "avbryt", deadline=deadline))
        await asyncio.wait_for(entered.wait(), timeout=1)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(cancelled.wait(), timeout=1)

        async def recovered_request(*args, **kwargs):
            return AIResult(status="success", text="ledig", provider="hermes", model="12b")

        connector._make_request = recovered_request
        recovered = await reply(request_context(), "ny", deadline=time.monotonic() + 1)
        self.assertEqual(recovered.status, "success")

    async def test_deadline_cancels_provider_work_and_returns_cancelled_outcome(self):
        AIResult = require_result_type(self)
        connector = OpenRouterConnector(api_key="offline-test-key")
        cleaned_up = asyncio.Event()

        async def slow_request(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.set()

        connector._make_request = slow_request
        reply = require_reply_method(self, connector)

        result = await reply(
            request_context(), "treg", deadline=time.monotonic() + 0.01
        )

        self.assertEqual(result.status, "cancelled")
        await asyncio.wait_for(cleaned_up.wait(), timeout=1)
        connector._make_request = AsyncMock(
            return_value=AIResult(
                status="success", text="etterpå", provider="openrouter", model=connector.model
            )
        )
        self.assertEqual(
            (await reply(request_context(), "ny", deadline=time.monotonic() + 1)).status,
            "success",
        )

    async def test_provider_429_preserves_retry_after_and_5xx_is_retryable(self):
        AIResult = require_result_type(self)
        connector = OpenRouterConnector(api_key="offline-test-key")

        limited = await connector._handle_response(
            FakeResponse(429, headers={"Retry-After": "17.5"})
        )
        failed = await connector._handle_response(FakeResponse(503))
        malformed_delay = await connector._handle_response(
            FakeResponse(429, headers={"Retry-After": "NaN"})
        )

        self.assertIsInstance(limited, AIResult)
        self.assertEqual(limited.status, "busy")
        self.assertEqual(limited.retry_after_s, 17.5)
        self.assertEqual(failed.status, "retryable")
        self.assertEqual(malformed_delay.retry_after_s, 60.0)

    async def test_provider_auth_failure_is_not_a_retryable_outcome(self):
        AIResult = require_result_type(self)
        connector = HermesConnector()

        result = await connector._handle_response(FakeResponse(401))

        self.assertIsInstance(result, AIResult)
        self.assertEqual(result.status, "auth_error")
        self.assertIsNone(result.text)

    async def test_malformed_http_success_is_never_an_assistant_reply(self):
        for connector in (HermesConnector(), OpenRouterConnector(api_key="offline-test-key")):
            with self.subTest(provider=connector.provider):
                response = FakeResponse(200, body="<html>proxy login page</html>")
                response.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "<", 0))
                result = await connector._handle_response(response)
                self.assertEqual(result.status, "unavailable")
                self.assertIsNone(result.text)

    async def test_cancellation_resistant_provider_cannot_publish_late_success(self):
        AIResult = require_result_type(self)
        connector = HermesConnector()

        async def late_request(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return AIResult("success", "late", "hermes", "12b")

        connector._make_request = late_request
        result = await connector.generate_reply(request_context(), "test", deadline=time.monotonic() + .01)
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.text)

    def test_success_requires_nonblank_assistant_text(self):
        AIResult = require_result_type(self)
        for text in ("", " \n "):
            with self.assertRaises(ValueError):
                AIResult("success", text, "hermes")

    async def test_oversized_envelope_is_rejected_even_with_short_assistant_text(self):
        connector = OpenRouterConnector(api_key="offline-test-key")
        result = await connector._handle_response(FakeResponse(200, data={
            "choices": [{"message": {"content": "Hei"}}], "padding": "x" * 131072,
        }))
        self.assertEqual(result.status, "unavailable")

    async def test_deadline_returns_while_resistant_work_keeps_its_admission_slot(self):
        from ai.result_schema import AIResult, BoundedAdmission
        gate = BoundedAdmission(1)
        release = asyncio.Event()

        async def resistant():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return AIResult("success", "late", "hermes")

        result = await asyncio.wait_for(gate.run(resistant,
            deadline=time.monotonic() + .01, provider="hermes", model=None), .5)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual((await gate.run(resistant,
            deadline=time.monotonic() + 1, provider="hermes", model=None)).status, "busy")
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(gate.in_flight, 0)

    async def test_openrouter_forbidden_response_is_an_auth_error(self):
        connector = OpenRouterConnector(api_key="offline-test-key")

        result = await connector._handle_response(FakeResponse(403))

        self.assertEqual(result.status, "auth_error")

    async def test_openrouter_success_response_extracts_only_assistant_text(self):
        connector = OpenRouterConnector(api_key="offline-test-key", model="synthetic/model")
        response = FakeResponse(
            200,
            data={"choices": [{"message": {"role": "assistant", "content": "Hei"}}]},
        )

        result = await connector._handle_response(response)

        self.assertEqual(result.text, "Hei")
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "synthetic/model")

    async def test_openrouter_health_response_does_not_require_chat_choices(self):
        connector = OpenRouterConnector(api_key="offline-test-key")

        class ResponseContext:
            async def __aenter__(self):
                return FakeResponse(200, data={"data": [{"id": "model"}]})

            async def __aexit__(self, *_args):
                return None

        session = SimpleNamespace(get=lambda _url: ResponseContext())
        connector._get_session = AsyncMock(return_value=session)

        result = await connector._make_request("models", method="GET")

        self.assertEqual(result.status, "success")

    async def test_openrouter_reply_extracts_text_and_provider_metadata(self):
        AIResult = require_result_type(self)
        connector = OpenRouterConnector(api_key="offline-test-key", model="synthetic/model")
        captured = {}

        async def completed(endpoint, method="POST", payload=None):
            captured.update(endpoint=endpoint, method=method, payload=payload)
            return AIResult(
                status="success",
                text="God dag",
                provider="openrouter",
                model=connector.model,
            )

        connector._make_request = completed
        result = await require_reply_method(self, connector)(
            request_context(), "Svar på norsk", deadline=time.monotonic() + 2
        )

        self.assertEqual(result.text, "God dag")
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "synthetic/model")
        self.assertEqual(captured["endpoint"], "chat/completions")
        serialized_payload = json.dumps(captured["payload"])
        self.assertNotIn("user-7", serialized_payload)
        self.assertNotIn("request-1", serialized_payload)

    async def test_hermes_reply_does_not_put_discord_ids_in_provider_payload(self):
        AIResult = require_result_type(self)
        connector = HermesConnector()
        captured = {}

        async def completed(url, method="POST", payload=None):
            captured.update(url=url, method=method, payload=payload)
            return AIResult(
                status="success", text="God dag", provider="hermes", model="12b"
            )

        connector._make_request = completed
        await require_reply_method(self, connector)(
            request_context(), "Svar på norsk", deadline=time.monotonic() + 2
        )

        self.assertEqual(captured["payload"]["author_name"], "bruker")
        self.assertNotIn("user-7", json.dumps(captured["payload"]))

    def test_local_provider_configuration_rejects_cloud_escalation(self):
        config = SimpleNamespace(
            AI_FALLBACK_PROVIDER="openrouter",
            OPENROUTER_API_KEY="offline-test-key",
            get_ai_provider=lambda: "lm_studio",
            get_hermes_url=lambda: "http://127.0.0.1:3000/api/chat",
        )
        with patch(
            "ai.openrouter_connector.create_openrouter_connector",
            side_effect=AssertionError("cloud provider must not be constructed"),
        ) as cloud_factory:
            with self.assertRaises(ValueError):
                AIConnectorFactory.create_connector(config)
        cloud_factory.assert_not_called()

    def test_factory_builds_fallback_only_for_explicit_local_declaration(self):
        primary = SimpleNamespace(provider="openrouter")
        local = SimpleNamespace(provider="hermes")
        config = SimpleNamespace(
            get_ai_provider=lambda: "openrouter",
        )
        with (
            patch(
                "ai.openrouter_connector.create_openrouter_connector",
                return_value=primary,
            ) as cloud_factory,
            patch(
                "ai.hermes_connector.create_hermes_connector", return_value=local
            ) as local_factory,
        ):
            routed = AIConnectorFactory.create_connector(
                config, fallback_provider="lm_studio"
            )

        self.assertEqual(routed.primary, primary)
        self.assertIs(routed.fallback, local)
        cloud_factory.assert_called_once_with(config)
        local_factory.assert_called_once_with(config)

    async def test_declared_local_fallback_identifies_provider_and_fallback_origin(self):
        router_type = getattr(__import__("ai.connector_factory", fromlist=["AIConnectorRouter"]), "AIConnectorRouter", None)
        self.assertIsNotNone(router_type, "the factory must provide explicit fallback routing")
        primary = SimpleNamespace(
            provider="openrouter",
            generate_reply=AsyncMock(return_value=self.result(status="busy", text=None)),
        )
        local = SimpleNamespace(
            provider="hermes",
            generate_reply=AsyncMock(
                return_value=self.result(
                    text="Lokal respons", provider="hermes", model="12b"
                )
            ),
        )

        result = await router_type(primary, fallback=local).generate_reply(
            request_context(), "spørsmål", deadline=time.monotonic() + 2
        )

        self.assertEqual(result.text, "Lokal respons")
        self.assertEqual(result.provider, "hermes")
        self.assertTrue(result.fallback)
        local.generate_reply.assert_awaited_once()

    async def test_auth_error_does_not_trigger_declared_fallback(self):
        router_type = getattr(
            __import__("ai.connector_factory", fromlist=["AIConnectorRouter"]),
            "AIConnectorRouter",
            None,
        )
        self.assertIsNotNone(router_type, "the factory must provide explicit fallback routing")
        primary = SimpleNamespace(
            provider="openrouter",
            generate_reply=AsyncMock(return_value=self.result(status="auth_error", text=None)),
        )
        local = SimpleNamespace(
            provider="hermes",
            generate_reply=AsyncMock(return_value=self.result(provider="hermes")),
        )

        result = await router_type(primary, fallback=local).generate_reply(
            request_context(), "spørsmål", deadline=time.monotonic() + 2
        )

        self.assertEqual(result.status, "auth_error")
        local.generate_reply.assert_not_awaited()

    def test_action_parser_rejects_malformed_unknown_oversized_and_control_data(self):
        parser = getattr(action_schema, "parse_action_draft", None)
        self.assertTrue(callable(parser), "AI action drafts need one strict allowlist parser")

        self.assertIsNone(parser("{not-json}"))
        self.assertIsNone(parser('{"action":"RUN_TOOL","name":"anything"}'))
        self.assertIsNone(
            parser(json.dumps({"action": "SAVE_EVENT", "title": "x" * 161}))
        )
        self.assertIsNone(
            parser(json.dumps({"action": "SAVE_EVENT", "title": "Møte\n@slett"}))
        )
        self.assertIsNone(
            parser(json.dumps({"action": "SAVE_EVENT", "title": "\nMøte"}))
        )
        self.assertIsNone(
            parser(json.dumps({"action": "SAVE_EVENT", "title": "Møte", "execute": True}))
        )
        self.assertIsNone(parser(" " * 4097))
        self.assertIsNone(
            parser(
                '{"action":"SAVE_EVENT","title":"Møte",'
                '"title":"Annet"}'
            )
        )

    def test_valid_event_action_is_only_a_bounded_draft(self):
        parser = getattr(action_schema, "parse_action_draft", None)
        self.assertTrue(callable(parser), "AI action drafts need one strict allowlist parser")

        action = parser(
            '{"action":"SAVE_EVENT","title":"Møte","date":"2026-10-12","time":"14:00"}'
        )

        self.assertEqual(
            action,
            {
                "action": "SAVE_EVENT",
                "title": "Møte",
                "date": "2026-10-12",
                "time": "14:00",
            },
        )

    async def test_model_dashboard_action_does_not_execute_dashboard_or_other_tools(self):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.user_memory = SimpleNamespace(get_user=AsyncMock())
        monitor._generate_dashboard = AsyncMock(return_value="dashboard")
        monitor._send_response = AsyncMock()

        text = await monitor._parse_and_execute_actions(
            '{"action":"SHOW_DASHBOARD"}', FakeMessage("@inebotten hei")
        )

        self.assertEqual(text, '{"action":"SHOW_DASHBOARD"}')
        monitor.user_memory.get_user.assert_not_awaited()
        monitor._generate_dashboard.assert_not_awaited()
        monitor._send_response.assert_not_awaited()

    def make_chat_monitor(self, result):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.conversation = SimpleNamespace(
            should_show_dashboard=lambda *_args: (False, "small talk"),
            add_message=lambda **_kwargs: None,
            get_conversation_summary=lambda *_args: None,
            get_context=lambda *_args, **_kwargs: "",
        )
        monitor.user_memory = SimpleNamespace(
            update_last_interaction=AsyncMock(),
            format_context_for_prompt=AsyncMock(return_value=""),
        )
        monitor.hermes = SimpleNamespace(generate_reply=AsyncMock(return_value=result))
        monitor.ResponseStyle = SimpleNamespace(CASUAL="casual")
        monitor.get_system_prompt = lambda **_kwargs: "Norsk svarstil"
        monitor.search_manager = SimpleNamespace()
        monitor.browser_manager = SimpleNamespace(is_configured=lambda: False)
        monitor.detect_search_intent = lambda _content: None
        monitor._send_response = AsyncMock()
        return monitor

    async def test_research_dispatch_shares_deadline_and_withholds_uncited_claims(self):
        from features.search_manager import SearchManager
        manager = SearchManager()
        row = manager._normalize_result({'url':'https://example.com/source', 'body':'Synthetic fact'}, 'synthetic')
        for reply, accepted in [('Uncited synthetic fact.', False),
                                ('Synthetic fact. https://example.com/source', True),
                                ('Synthetic fact. https://example.com/source\n' +
                                 '{"action":"SAVE_EVENT","title":"Synthetic","date":"2026-10-10","time":"12:00"}', False)]:
            monitor = self.make_chat_monitor(self.result(text=reply))
            deadlines = []
            async def search(query, *, deadline):
                deadlines.append(deadline)
                return [row]
            monitor.search_manager = SimpleNamespace(search=search, format_results_for_ai=manager.format_results_for_ai)
            monitor.detect_search_intent = lambda _: {'type':'web','query':'synthetic'}
            async def extract(url, *, deadline):
                deadlines.append(deadline)
                return None
            monitor.browser_manager = SimpleNamespace(is_configured=lambda:True, fetch_page_card=extract)
            with patch('ai.personality.get_personality', return_value=SimpleNamespace(respond_to_dialect=lambda _:None)):
                await monitor._send_ai_response(FakeMessage('@inebotten søk på nett synthetic'))
            assert deadlines[0] == deadlines[1]
            prompt = monitor.hermes.generate_reply.await_args.args[1]
            assert 'untrusted_evidence' in prompt
            sent = monitor._send_response.await_args.args[1]
            assert (reply in sent) is accepted
            if not accepted:
                assert 'kildehenvisninger' in sent
        await manager.close()

    async def test_monitor_passes_request_context_deadline_and_shows_busy_outcome(self):
        monitor = self.make_chat_monitor(
            self.result(status="busy", text=None, retry_after_s=8.0)
        )
        captured = {}

        async def generate(context, prompt, *, deadline):
            captured.update(context=context, prompt=prompt, deadline=deadline)
            return self.result(status="busy", text=None, retry_after_s=8.0)

        monitor.hermes.generate_reply = generate
        with patch(
            "ai.personality.get_personality",
            return_value=SimpleNamespace(respond_to_dialect=lambda _text: None),
        ):
            await monitor._send_ai_response(FakeMessage("@inebotten hvordan virker dette?"))

        self.assertEqual(captured["context"].user_id, "7")
        self.assertIn("Brukermelding:", captured["prompt"])
        self.assertGreater(captured["deadline"], time.monotonic())
        sent_text = monitor._send_response.await_args.args[1]
        self.assertIn("opptatt", sent_text)
        self.assertIn("8 sekunder", sent_text)

    async def test_monitor_rejects_legacy_tuple_without_ambiguity(self):
        monitor = self.make_chat_monitor((True, "should not be sent"))
        with patch(
            "ai.personality.get_personality",
            return_value=SimpleNamespace(respond_to_dialect=lambda _text: None),
        ):
            await monitor._send_ai_response(FakeMessage("@inebotten hvordan virker dette?"))

        sent_text = monitor._send_response.await_args.args[1]
        self.assertIn("ikke tilgjengelig", sent_text)
        self.assertNotIn("should not be sent", sent_text)

    async def test_monitor_labels_success_from_declared_fallback(self):
        monitor = self.make_chat_monitor(
            self.result(
                text="Et lokalt svar",
                provider="hermes",
                model="12b",
                fallback=True,
            )
        )
        with patch(
            "ai.personality.get_personality",
            return_value=SimpleNamespace(respond_to_dialect=lambda _text: None),
        ):
            await monitor._send_ai_response(FakeMessage("@inebotten hvordan virker dette?"))

        sent_text = monitor._send_response.await_args.args[1]
        self.assertIn("lokal reserve hermes (12b)", sent_text.lower())
        self.assertIn("Et lokalt svar", sent_text)

    async def test_domain_command_failure_never_falls_through_to_generic_ai(self):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.client = SimpleNamespace(
            user=SimpleNamespace(id=42),
            config=SimpleNamespace(
                INVOCATION_MODE="legacy", ALLOWED_USERS=[], ALLOWED_CHANNELS=[]
            ),
        )
        monitor.bot_name = "inebotten"
        monitor.bot_mention = "@inebotten"
        monitor.processed_messages = []
        monitor.mention_count = 0
        monitor.error_count = 0
        monitor.intent_stats = defaultdict(
            lambda: {"count": 0, "low_confidence": 0, "errors": 0}
        )
        monitor.rate_limiter = FakeRateLimiter()
        monitor.loc = SimpleNamespace(detect_language=lambda _content: "no")
        monitor.intent_router = SimpleNamespace(
            route=lambda *_args, **_kwargs: SimpleNamespace(
                intent=BotIntent.HELP, confidence=1.0, reason="explicit help", payload={}
            )
        )
        ai_calls = []
        sent = []

        async def fail_domain(_message, _route):
            raise RuntimeError("synthetic handler failure")

        async def fake_ai(_message, **_kwargs):
            ai_calls.append(True)

        async def fake_send(_message, text):
            sent.append(text)

        monitor._handle_intent = fail_domain
        monitor._send_ai_response = fake_ai
        monitor._send_response = fake_send

        await monitor.handle_message(FakeMessage("@inebotten hjelp"))

        self.assertEqual(ai_calls, [])
        self.assertEqual(len(sent), 1)
        self.assertIn("kommandoen", sent[0].lower())
        self.assertEqual(monitor.intent_stats[BotIntent.HELP.value]["errors"], 1)

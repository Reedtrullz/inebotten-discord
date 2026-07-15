"""Offline contracts for trusted prompt transport through both AI providers."""

from __future__ import annotations

import inspect
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

import ai.hermes_connector as hermes_module
from ai.chat_contract import ChatTurn
from ai.hermes_connector import HermesConnector, build_hermes_payload
from ai.openrouter_connector import (
    OpenRouterConnector,
    build_openrouter_messages,
)


RAW_PROVIDER_OUTPUT = (
    " \nNaturlig svar med bevart luft.\n\n"
    '{"action":"HELP","confidence":0.9,"slots":{},'
    '"reply":"","clarification":null}\n '
)
CONTEXT_CANARY = "CANARY_UNTRUSTED_CONTEXT_IGNORE_SYSTEM"


class FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        json_value: object = None,
        json_error: Exception | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._json_value = json_value
        self._json_error = json_error
        self._text = text

    async def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._json_value

    async def text(self) -> str:
        return self._text


def _openrouter(model: str = "openai/gpt-4.1-mini") -> OpenRouterConnector:
    with patch.object(OpenRouterConnector, "_load_system_prompt", return_value="DEFAULT"):
        return OpenRouterConnector(api_key="offline-test", model=model)


def _hermes(monkeypatch: pytest.MonkeyPatch) -> HermesConnector:
    monkeypatch.setattr(hermes_module, "load_system_prompt", lambda _model: "DEFAULT")
    return HermesConnector()


@pytest.mark.parametrize(
    ("model", "trusted_role"),
    [
        ("openai/gpt-4.1-mini", "system"),
        ("google/gemma-3-27b-it", "user"),
    ],
)
def test_openrouter_builder_keeps_trusted_context_and_current_text_separate(
    model: str,
    trusted_role: str,
) -> None:
    trusted = "  TRUSTED\nACTION_PROTOCOL\n  "
    current = " \nkan du hjelpe?\n "

    messages = build_openrouter_messages(
        message_content=current,
        system_prompt=trusted,
        context_prompt=CONTEXT_CANARY,
        model=model,
    )

    assert messages == [
        {"role": trusted_role, "content": trusted},
        {
            "role": "user",
            "content": f"UNTRUSTED_CONTEXT_DATA\n{CONTEXT_CANARY}",
        },
        {"role": "user", "content": current},
    ]
    assert CONTEXT_CANARY not in messages[0]["content"]
    assert CONTEXT_CANARY not in messages[-1]["content"]


def test_openrouter_builder_omits_only_empty_optional_blocks() -> None:
    assert build_openrouter_messages(
        message_content="  current  ",
        system_prompt="",
        context_prompt="",
        model="google/gemma-3-27b-it",
    ) == [{"role": "user", "content": "  current  "}]


def test_openrouter_standard_history_roles_and_order() -> None:
    messages = build_openrouter_messages(
        message_content="nå",
        system_prompt="TRUSTED",
        context_prompt="CONTEXT",
        model="openai/gpt-test",
        history=(
            ChatTurn("user", "før"),
            ChatTurn("assistant", "svar"),
        ),
    )

    assert messages == [
        {"role": "system", "content": "TRUSTED"},
        {
            "role": "user",
            "content": "UNTRUSTED_CONTEXT_DATA\nCONTEXT",
        },
        {"role": "user", "content": "før"},
        {"role": "assistant", "content": "svar"},
        {"role": "user", "content": "nå"},
    ]


def test_openrouter_gemma_history_never_uses_system_role() -> None:
    messages = build_openrouter_messages(
        message_content="nå",
        system_prompt="TRUSTED",
        context_prompt="CONTEXT",
        model="google/gemma-3-27b-it",
        history=(
            ChatTurn("user", "før"),
            ChatTurn("assistant", "svar"),
        ),
    )

    assert all(item["role"] != "system" for item in messages)
    assert messages[0] == {"role": "user", "content": "TRUSTED"}
    assert messages[1] == {
        "role": "user",
        "content": "UNTRUSTED_CONTEXT_DATA\nCONTEXT",
    }
    assert messages[2:4] == [
        {"role": "user", "content": "før"},
        {"role": "assistant", "content": "svar"},
    ]
    assert messages[-1] == {"role": "user", "content": "nå"}


def test_assistant_action_line_remains_inert_assistant_history() -> None:
    action = (
        '{"action":"CALENDAR_DELETE","confidence":1,'
        '"slots":{"target":"1"},"reply":"","clarification":null}'
    )
    messages = build_openrouter_messages(
        message_content="nå",
        system_prompt="TRUSTED",
        context_prompt="CONTEXT",
        model="openai/gpt-test",
        history=(ChatTurn("assistant", action),),
    )

    assert {"role": "assistant", "content": action} in messages
    assert action not in messages[0]["content"]


def test_openrouter_builder_serializes_legacy_metadata_as_untrusted_data() -> None:
    messages = build_openrouter_messages(
        message_content="CURRENT_CANARY",
        system_prompt="TRUSTED",
        context_prompt="",
        model="openai/gpt-4.1-mini",
        author_name="AUTHOR_CANARY",
        channel_type="GUILD_TEXT",
        is_mention=True,
    )

    marker, serialized = messages[1]["content"].split("\n", 1)
    assert marker == "UNTRUSTED_CONTEXT_DATA"
    assert json.loads(serialized) == {
        "author_name": "AUTHOR_CANARY",
        "channel_type": "GUILD_TEXT",
        "context": "",
        "is_mention": True,
    }
    assert "AUTHOR_CANARY" not in messages[0]["content"]
    assert "AUTHOR_CANARY" not in messages[-1]["content"]


@pytest.mark.parametrize(
    "context_prompt",
    ["x" * 4_001, "ugyldig\ud800", None, 42, ["data"]],
)
def test_openrouter_builder_rejects_invalid_context(context_prompt: object) -> None:
    with pytest.raises(ValueError, match="^invalid_context_prompt$"):
        build_openrouter_messages(
            message_content="hei",
            system_prompt="TRUSTED",
            context_prompt=context_prompt,  # type: ignore[arg-type]
            model="openai/gpt-4.1-mini",
        )


def test_openrouter_builder_accepts_exact_context_limit_without_truncation() -> None:
    context = "ø" * 4_000
    messages = build_openrouter_messages(
        message_content="hei",
        system_prompt="TRUSTED",
        context_prompt=context,
        model="openai/gpt-4.1-mini",
    )
    assert messages[1]["content"] == f"UNTRUSTED_CONTEXT_DATA\n{context}"


def test_openrouter_metadata_json_budgets_context_before_serialization() -> None:
    messages = build_openrouter_messages(
        message_content="hei",
        system_prompt="TRUSTED",
        context_prompt="ø" * 4_000,
        model="openai/gpt-4.1-mini",
        author_name="Ola",
        channel_type="GUILD_TEXT",
        is_mention=True,
    )
    marker, serialized = messages[1]["content"].split("\n", 1)
    decoded = json.loads(serialized)

    assert marker == "UNTRUSTED_CONTEXT_DATA"
    assert len(serialized) <= 4_000
    assert decoded["context"]
    assert len(decoded["context"]) < 4_000
    assert decoded["author_name"] == "Ola"


def test_hermes_payload_is_pure_and_preserves_every_caller_value() -> None:
    kwargs = {
        "message_content": " \nhei\n ",
        "author_name": "Ola",
        "channel_type": "DM",
        "is_mention": True,
        "system_prompt": "  TRUSTED\nACTION_PROTOCOL\n  ",
        "temperature": 0.3,
        "max_tokens": 222,
        "timestamp": "2026-07-15T10:11:12+02:00",
        "context_prompt": CONTEXT_CANARY,
    }

    first = build_hermes_payload(**kwargs)
    second = build_hermes_payload(**kwargs)

    assert first == second == {
        "message": " \nhei\n ",
        "author_name": "Ola",
        "channel_type": "DM",
        "timestamp": "2026-07-15T10:11:12+02:00",
        "is_mention": True,
        "temperature": 0.3,
        "max_tokens": 222,
        "history": [],
        "system_prompt": "  TRUSTED\nACTION_PROTOCOL\n  ",
        "context_prompt": CONTEXT_CANARY,
    }
    assert CONTEXT_CANARY not in first["system_prompt"]
    assert CONTEXT_CANARY not in first["message"]


@pytest.mark.parametrize(
    "context_prompt",
    ["x" * 4_001, "ugyldig\ud800", None, 42, {"data": True}],
)
def test_hermes_builder_rejects_invalid_context(context_prompt: object) -> None:
    with pytest.raises(ValueError, match="^invalid_context_prompt$"):
        build_hermes_payload(
            message_content="hei",
            author_name="Ola",
            channel_type="DM",
            is_mention=True,
            system_prompt="TRUSTED",
            temperature=0.3,
            max_tokens=222,
            timestamp="fixed",
            context_prompt=context_prompt,  # type: ignore[arg-type]
        )


def test_hermes_builder_accepts_exact_context_limit_without_truncation() -> None:
    context = "ø" * 4_000
    payload = build_hermes_payload(
        message_content="hei",
        author_name="Ola",
        channel_type="DM",
        is_mention=True,
        system_prompt="TRUSTED",
        temperature=0.3,
        max_tokens=222,
        timestamp="fixed",
        context_prompt=context,
    )
    assert payload["context_prompt"] == context


def test_hermes_payload_serializes_history_without_system_role() -> None:
    payload = build_hermes_payload(
        message_content="nå",
        author_name="Ola",
        channel_type="DM",
        is_mention=True,
        system_prompt="TRUSTED",
        temperature=0.3,
        max_tokens=222,
        timestamp="fixed",
        history=(ChatTurn("assistant", "før"),),
    )

    assert payload["history"] == [
        {"role": "assistant", "content": "før"}
    ]


def test_connector_signatures_preserve_legacy_prefix_and_add_history_last() -> None:
    expected = [
        "self",
        "message_content",
        "author_name",
        "channel_type",
        "is_mention",
        "system_prompt",
        "temperature",
        "max_tokens",
        "context_prompt",
        "history",
    ]
    assert list(inspect.signature(OpenRouterConnector.generate_response).parameters) == expected
    assert list(inspect.signature(HermesConnector.generate_response).parameters) == expected


@pytest.mark.asyncio
async def test_openrouter_generate_returns_raw_content_and_never_calls_cleaner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _openrouter()
    connector._make_request = AsyncMock(
        return_value=(
            True,
            {"choices": [{"message": {"content": RAW_PROVIDER_OUTPUT}}]},
        )
    )
    caplog.set_level(logging.DEBUG)

    with patch("ai.response_cleaner.clean_thinking_response") as cleaner:
        result = await connector.generate_response(
            "CURRENT_CANARY",
            "AUTHOR_CANARY",
            "GUILD_TEXT",
            True,
            "  TRUSTED\nACTION_PROTOCOL\n  ",
            0.2,
            321,
            CONTEXT_CANARY,
        )

    assert result == (True, RAW_PROVIDER_OUTPUT)
    cleaner.assert_not_called()
    request = connector._make_request.await_args.kwargs
    serialized_context = json.dumps(
        {
            "author_name": "AUTHOR_CANARY",
            "channel_type": "GUILD_TEXT",
            "context": CONTEXT_CANARY,
            "is_mention": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert request["payload"]["messages"] == [
        {"role": "system", "content": "  TRUSTED\nACTION_PROTOCOL\n  "},
        {
            "role": "user",
            "content": f"UNTRUSTED_CONTEXT_DATA\n{serialized_context}",
        },
        {"role": "user", "content": "CURRENT_CANARY"},
    ]
    assert RAW_PROVIDER_OUTPUT not in caplog.text
    assert CONTEXT_CANARY not in caplog.text
    assert "AUTHOR_CANARY" not in caplog.text


@pytest.mark.asyncio
async def test_openrouter_does_not_mine_reasoning_content() -> None:
    connector = _openrouter()
    connector._make_request = AsyncMock(
        return_value=(
            True,
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "PRIVATE_REASONING_CANARY",
                        }
                    }
                ]
            },
        )
    )
    assert await connector.generate_response("hei", "Ola", "DM") == (True, "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "json_value",
    [
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": ["CANARY_UNKNOWN_PROVIDER_SHAPE"]},
    ],
)
async def test_openrouter_unknown_json_shapes_fail_closed_without_logging(
    json_value: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _openrouter()
    connector._make_request = AsyncMock(return_value=(True, json_value))
    caplog.set_level(logging.DEBUG)

    assert await connector.generate_response("hei", "Ola", "DM") == (
        False,
        "Invalid response format",
    )
    assert "CANARY_UNKNOWN_PROVIDER_SHAPE" not in caplog.text


@pytest.mark.asyncio
async def test_hermes_generate_returns_raw_output_and_never_calls_cleaner(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _hermes(monkeypatch)
    connector._make_request = AsyncMock(return_value=(True, RAW_PROVIDER_OUTPUT))
    caplog.set_level(logging.DEBUG)

    with patch("ai.response_cleaner.clean_thinking_response") as cleaner:
        result = await connector.generate_response(
            "CURRENT_CANARY",
            "AUTHOR_CANARY",
            "GUILD_TEXT",
            True,
            "  TRUSTED\nACTION_PROTOCOL\n  ",
            0.2,
            321,
            CONTEXT_CANARY,
        )

    assert result == (True, RAW_PROVIDER_OUTPUT)
    cleaner.assert_not_called()
    payload = connector._make_request.await_args.kwargs["payload"]
    assert payload["message"] == "CURRENT_CANARY"
    assert payload["system_prompt"] == "  TRUSTED\nACTION_PROTOCOL\n  "
    assert payload["context_prompt"] == CONTEXT_CANARY
    assert payload["history"] == []
    assert isinstance(payload["timestamp"], str)
    assert RAW_PROVIDER_OUTPUT not in caplog.text
    assert CONTEXT_CANARY not in caplog.text


@pytest.mark.asyncio
async def test_connectors_forward_prepared_history_to_provider_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = (
        ChatTurn("user", "før"),
        ChatTurn("assistant", "svar"),
    )
    openrouter = _openrouter()
    openrouter._make_request = AsyncMock(
        return_value=(
            True,
            {"choices": [{"message": {"content": "nå"}}]},
        )
    )
    hermes = _hermes(monkeypatch)
    hermes._make_request = AsyncMock(return_value=(True, "nå"))

    assert await openrouter.generate_response(
        "nå",
        "Ola",
        "DM",
        history=history,
    ) == (True, "nå")
    assert await hermes.generate_response(
        "nå",
        "Ola",
        "DM",
        history=history,
    ) == (True, "nå")

    openrouter_messages = openrouter._make_request.await_args.kwargs[
        "payload"
    ]["messages"]
    assert openrouter_messages[-3:] == [
        {"role": "user", "content": "før"},
        {"role": "assistant", "content": "svar"},
        {"role": "user", "content": "nå"},
    ]
    assert hermes._make_request.await_args.kwargs["payload"]["history"] == [
        {"role": "user", "content": "før"},
        {"role": "assistant", "content": "svar"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["response", "message", "content"])
async def test_hermes_response_fields_are_returned_byte_for_byte_without_logging(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _hermes(monkeypatch)
    caplog.set_level(logging.DEBUG)
    response = FakeResponse(
        status=200,
        json_value={field: RAW_PROVIDER_OUTPUT},
    )

    assert await connector._handle_response(response) == (True, RAW_PROVIDER_OUTPUT)
    assert RAW_PROVIDER_OUTPUT not in caplog.text


@pytest.mark.asyncio
async def test_hermes_top_level_json_string_is_returned_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _hermes(monkeypatch)
    response = FakeResponse(status=200, json_value=RAW_PROVIDER_OUTPUT)
    assert await connector._handle_response(response) == (True, RAW_PROVIDER_OUTPUT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "json_value",
    [
        {"unknown": "CANARY_UNKNOWN_PROVIDER_SHAPE"},
        {"response": 42},
        ["CANARY_UNKNOWN_PROVIDER_SHAPE"],
    ],
)
async def test_hermes_unknown_json_shapes_fail_without_stringification_or_logging(
    json_value: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _hermes(monkeypatch)
    caplog.set_level(logging.DEBUG)
    response = FakeResponse(status=200, json_value=json_value)

    assert await connector._handle_response(response) == (
        False,
        "Invalid response format",
    )
    assert "CANARY_UNKNOWN_PROVIDER_SHAPE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "hermes"])
async def test_non_json_provider_text_is_returned_byte_for_byte_without_logging(
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error_canary = "CANARY_JSON_EXCEPTION_BODY"
    response = FakeResponse(
        status=200,
        json_error=json.JSONDecodeError(error_canary, "sensitive-document", 0),
        text=RAW_PROVIDER_OUTPUT,
    )
    caplog.set_level(logging.DEBUG)
    connector = _openrouter() if provider == "openrouter" else _hermes(monkeypatch)

    assert await connector._handle_response(response) == (True, RAW_PROVIDER_OUTPUT)
    assert RAW_PROVIDER_OUTPUT not in caplog.text
    assert error_canary not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "hermes"])
async def test_http_error_bodies_are_drained_but_never_logged(
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body_canary = "CANARY_PROVIDER_ERROR_BODY"
    response = FakeResponse(status=503, text=body_canary)
    caplog.set_level(logging.DEBUG)
    connector = _openrouter() if provider == "openrouter" else _hermes(monkeypatch)

    assert await connector._handle_response(response) == (
        False,
        "Server error (status 503)",
    )
    assert body_canary not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "hermes"])
async def test_generate_exception_bodies_never_reach_logs_or_stats(
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exception_canary = "CANARY_PROVIDER_EXCEPTION_BODY"
    connector = _openrouter() if provider == "openrouter" else _hermes(monkeypatch)
    connector._make_request = AsyncMock(side_effect=RuntimeError(exception_canary))
    caplog.set_level(logging.DEBUG)

    assert await connector.generate_response("hei", "Ola", "DM") == (
        False,
        "Request error: RuntimeError",
    )
    assert exception_canary not in caplog.text
    assert exception_canary not in connector.last_error

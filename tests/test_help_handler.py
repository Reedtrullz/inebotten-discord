"""Discord help rendering and multi-send delivery truth."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import core.help_registry as registry_module
import features.help_handler as help_module
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    MessageSendCancelled,
    MessageSendResult,
)
from core.help_registry import (
    DISCORD_MESSAGE_LIMIT,
    HELP_CATEGORIES,
    catalog_sections,
    render_discord_help_chunks,
)
from core.send_receipt import capture_send_receipt, record_send_result
from features.help_handler import HelpHandler


class _SequenceHelpHandler(HelpHandler):
    def __init__(self, results):
        self.loc = SimpleNamespace(current_lang="no")
        self.results = list(results)
        self.sent: list[str] = []

    async def send_response_result(self, _message, content):
        self.sent.append(content)
        result = self.results.pop(0)
        record_send_result(result)
        return result


def test_discord_renderer_contains_each_catalog_row_once_in_exact_order():
    chunks = render_discord_help_chunks("nb")
    lines = "\n".join(chunks).splitlines()
    advertised = [
        line.removeprefix("• @Inebotten ")
        for line in lines
        if line.startswith("• @Inebotten ")
    ]
    expected = [
        example.display_phrase
        for _, examples in catalog_sections("nb")
        for example in examples
    ]

    assert advertised == expected
    assert all(chunks)
    assert all(len(chunk) <= DISCORD_MESSAGE_LIMIT for chunk in chunks)
    assert len(advertised) == len(set(advertised))

    rendered = "\n".join(chunks)
    positions = []
    for category, examples in catalog_sections("nb"):
        positions.append(rendered.index(category.title_no))
        positions.extend(
            rendered.index(f"• @Inebotten {example.display_phrase}")
            for example in examples
        )
    assert positions == sorted(positions)


def test_discord_renderer_uses_only_registry_copy():
    rendered = "\n".join(render_discord_help_chunks("nb"))
    assert "@Inebotten legg til Inception" not in rendered
    assert "@Inebotten les https://example.invalid" not in rendered
    assert "<kode>" not in rendered
    assert "ACTION_PROTOCOL" not in rendered
    assert tuple(category.id for category in HELP_CATEGORIES)


def test_discord_renderer_flushes_before_an_individually_fitting_category(
    monkeypatch,
):
    first = SimpleNamespace(
        title_no="A" * 1_200,
        title_en="A" * 1_200,
        description_no="a" * 500,
        description_en="a" * 500,
    )
    second = SimpleNamespace(
        title_no="B" * 500,
        title_en="B" * 500,
        description_no="b" * 400,
        description_en="b" * 400,
    )
    first_example = SimpleNamespace(display_phrase="første")
    second_example = SimpleNamespace(display_phrase="c" * 300)
    monkeypatch.setattr(
        registry_module,
        "catalog_sections",
        lambda _locale: (
            (first, (first_example,)),
            (second, (second_example,)),
        ),
    )

    chunks = render_discord_help_chunks("nb")

    assert len(chunks) == 2
    assert chunks[0] == "\n".join(
        (first.title_no, first.description_no, "• @Inebotten første")
    )
    assert chunks[1] == "\n".join(
        (
            second.title_no,
            second.description_no,
            f"• @Inebotten {second_example.display_phrase}",
        )
    )


@pytest.mark.asyncio
async def test_help_handler_returns_success_only_after_all_chunks_deliver(
    monkeypatch,
):
    chunks = ("en", "to", "tre")
    monkeypatch.setattr(help_module, "render_discord_help_chunks", lambda _: chunks)
    handler = _SequenceHelpHandler(
        [MessageSendResult(DeliveryState.DELIVERED) for _ in chunks]
    )

    with capture_send_receipt() as receipt:
        outcome = await handler.handle_help(object())

    assert outcome.ok
    assert outcome.response_sent
    assert outcome.delivery_result == MessageSendResult(
        DeliveryState.DELIVERED
    )
    assert handler.sent == list(chunks)
    assert receipt.result == MessageSendResult(DeliveryState.DELIVERED)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "code", "retryable"),
    [
        (
            MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
            "response_send_failed",
            True,
        ),
        (
            MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
            "response_delivery_unknown",
            False,
        ),
    ],
)
async def test_help_handler_stops_after_first_chunk_failure(
    monkeypatch,
    result,
    code,
    retryable,
):
    monkeypatch.setattr(
        help_module,
        "render_discord_help_chunks",
        lambda _: ("en", "to"),
    )
    handler = _SequenceHelpHandler([result])

    outcome = await handler.handle_help(object())

    assert not outcome.ok
    assert outcome.error_code == code
    assert outcome.retryable is retryable
    assert outcome.delivery_result == result
    assert handler.sent == ["en"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "later_result",
    [
        MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
async def test_help_handler_later_failure_is_terminal_partial_send(
    monkeypatch,
    later_result,
):
    monkeypatch.setattr(
        help_module,
        "render_discord_help_chunks",
        lambda _: ("en", "to", "tre"),
    )
    handler = _SequenceHelpHandler(
        [MessageSendResult(DeliveryState.DELIVERED), later_result]
    )

    with capture_send_receipt() as receipt:
        outcome = await handler.handle_help(object())

    assert not outcome.ok
    assert outcome.error_code == "partial_response_sent"
    assert not outcome.retryable
    assert outcome.delivery_result == MessageSendResult(
        DeliveryState.UNKNOWN,
        "partial_send",
    )
    assert handler.sent == ["en", "to"]
    assert receipt.result is not None
    assert receipt.result.state is DeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_cancellation_after_delivered_prefix_stops_remaining_chunks(
    monkeypatch,
):
    chunks = ("en", "to", "tre")
    monkeypatch.setattr(help_module, "render_discord_help_chunks", lambda _: chunks)
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BarrierHandler(_SequenceHelpHandler):
        async def send_response_result(self, _message, content):
            self.sent.append(content)
            if len(self.sent) == 1:
                result = MessageSendResult(DeliveryState.DELIVERED)
                record_send_result(result)
                return result
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None:
                    for _ in range(current.cancelling()):
                        current.uncancel()
                await release.wait()
                result = MessageSendResult(DeliveryState.DELIVERED)
                record_send_result(result)
                raise MessageSendCancelled(result) from None
            raise AssertionError("second send should observe cancellation")

    handler = _BarrierHandler([])
    with capture_send_receipt() as receipt:
        task = asyncio.create_task(handler.handle_help(object()))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(DispatchCancelled) as raised:
            await task

    outcome = raised.value.outcome
    assert outcome.error_code == "partial_response_sent"
    assert outcome.delivery_result == MessageSendResult(
        DeliveryState.UNKNOWN,
        "partial_send",
    )
    assert handler.sent == ["en", "to"]
    assert receipt.result == outcome.delivery_result

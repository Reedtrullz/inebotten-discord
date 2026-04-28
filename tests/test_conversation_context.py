import unittest
from typing import Protocol, cast

from memory.conversation_context import ConversationContext


class _ConversationContextProto(Protocol):
    threads: dict[int, list[dict[str, object]]]

    def add_message(self, channel_id: int, user_id: int | None, username: str, content: str, is_bot: bool = False) -> None:
        ...

    def get_channel_messages(self, channel_id: int, limit: int = 6) -> list[dict[str, object]]:
        ...


class ConversationContextTests(unittest.TestCase):
    def test_add_message_to_channel(self):
        ctx = cast(_ConversationContextProto, ConversationContext())
        ctx.add_message(channel_id=1, user_id=7, username="User", content="Hello", is_bot=False)
        self.assertEqual(len(ctx.threads[1]), 1)

    def test_get_channel_messages_returns_only_that_channel(self):
        ctx = cast(_ConversationContextProto, ConversationContext())
        ctx.add_message(channel_id=1, user_id=7, username="User", content="Msg1", is_bot=False)
        ctx.add_message(channel_id=2, user_id=8, username="Other", content="Msg2", is_bot=False)
        msgs = ctx.get_channel_messages(1)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "Msg1")

    def test_cross_channel_leak_prevented(self):
        ctx = cast(_ConversationContextProto, ConversationContext())
        ctx.add_message(channel_id=1, user_id=None, username="Bot", content="Reminder about meeting", is_bot=True)
        ctx.add_message(channel_id=2, user_id=7, username="User", content="Minn meg på det", is_bot=False)
        msgs = ctx.get_channel_messages(2)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "Minn meg på det")

    def test_get_channel_messages_respects_limit(self):
        ctx = cast(_ConversationContextProto, ConversationContext())
        for i in range(10):
            ctx.add_message(channel_id=1, user_id=7, username="User", content=f"Msg{i}", is_bot=False)
        msgs = ctx.get_channel_messages(1, limit=5)
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[-1]["content"], "Msg9")

    def test_get_channel_messages_empty_channel(self):
        ctx = cast(_ConversationContextProto, ConversationContext())
        msgs = ctx.get_channel_messages(999)
        self.assertEqual(msgs, [])

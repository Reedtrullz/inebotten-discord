import unittest
import pytest
from typing import Protocol, cast

from memory.conversation_context import ConversationContext


@pytest.mark.parametrize('text', [
    'Forklar kort forskjellen på et møte og en påminnelse',
    'Kan du forklare forskjellen på kalender og påminnelser?',
    'Fortell hvorfor været varierer',
    'Explain how a calendar works',
])
def test_explanation_requests_stay_chat_with_dashboard_keywords(text):
    context = ConversationContext()
    assert context.should_show_dashboard(text, 123)[0] is False


@pytest.mark.parametrize('text', ['vis dashboard', 'vær i Trondheim', 'Hva er været i dag?'])
def test_explicit_dashboard_requests_still_work(text):
    assert ConversationContext().should_show_dashboard(text, 123)[0] is True


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


def test_summary_only_learns_topics_from_the_selected_speaker():
    ctx = ConversationContext()
    ctx.add_message(1, 'u1', 'One', 'Jeg liker RBK')
    ctx.add_message(1, 'u2', 'Two', 'Vi snakker om været')
    assert ctx.get_conversation_summary(1, user_id='u1') == ['RBK']
    assert ctx.get_conversation_summary(1, user_id='u2') == ['været']

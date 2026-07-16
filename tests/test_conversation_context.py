import unittest
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast

from ai.chat_contract import (
    REDACTED_AUTH_TURN,
    ChatTurn,
    HistoryPolicy,
)
from core.message_context import ConversationKey
from memory.conversation_context import ConversationContext, _StoredTurn


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

    def test_scoped_history_isolated_by_full_conversation_key(self):
        ctx = ConversationContext()
        key_a = ConversationKey(1, 10, 7)
        key_b = ConversationKey(1, 11, 7)
        key_c = ConversationKey(1, 10, 8)
        ctx.add_turn(key_a, ChatTurn("user", "melding a", 1))

        self.assertEqual(
            [turn.content for turn in ctx.get_prompt_history(key_a)],
            ["melding a"],
        )
        self.assertEqual(ctx.get_prompt_history(key_b), ())
        self.assertEqual(ctx.get_prompt_history(key_c), ())

    def test_scoped_history_never_imports_legacy_integer_thread(self):
        ctx = ConversationContext()
        ctx.add_message(10, 8, "Annen", "hemmelig", is_bot=False)

        self.assertEqual(
            ctx.get_prompt_history(ConversationKey(1, 10, 7)),
            (),
        )
        self.assertEqual(ctx.get_context(10), "Annen: hemmelig")

    def test_dictionary_turn_under_scoped_key_is_dropped_not_imported(self):
        ctx = ConversationContext()
        key = ConversationKey(1, 10, 7)
        ctx.threads[key] = [
            {
                "content": "må aldri nå provider",
                "is_bot": False,
                "timestamp": datetime.now(timezone.utc),
            }
        ]

        self.assertEqual(ctx.get_prompt_history(key), ())
        self.assertNotIn(key, ctx.threads)

    def test_current_legacy_dictionary_turn_is_readable(self):
        ctx = ConversationContext()
        ctx.threads[10] = [
            {
                "user_id": 7,
                "username": "Ola",
                "content": "gammel melding",
                "is_bot": False,
                "timestamp": datetime.now(timezone.utc),
            }
        ]

        self.assertEqual(
            ctx.get_channel_messages(10)[0]["content"],
            "gammel melding",
        )
        self.assertEqual(ctx.get_context(10), "Ola: gammel melding")

    def test_old_add_message_positional_signature_stays_valid(self):
        ctx = ConversationContext()
        ctx.add_message(10, 7, "Ola", "hei", False)

        self.assertEqual(ctx.get_channel_messages(10)[0]["content"], "hei")

    def test_legacy_channel_id_keywords_stay_valid(self):
        ctx = ConversationContext()
        ctx.add_message(
            channel_id=10,
            user_id=7,
            username="Ola",
            content="RBK og været",
        )

        self.assertEqual(
            ctx.get_context(channel_id=10),
            "Ola: RBK og været",
        )
        self.assertEqual(
            ctx.should_show_dashboard(content="hei", channel_id=10),
            (False, "small_talk"),
        )
        self.assertEqual(
            set(ctx.get_conversation_summary(channel_id=10)),
            {"RBK", "været"},
        )

    def test_legacy_turn_without_timestamp_is_dropped_once(self):
        fixed = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        ctx = ConversationContext(now_provider=lambda: fixed)
        ctx.threads[10] = [
            {
                "user_id": 7,
                "username": "Ola",
                "content": "må ikke bli evig ung",
                "is_bot": False,
            }
        ]

        self.assertEqual(ctx.get_channel_messages(10), [])
        self.assertNotIn(10, ctx.threads)
        self.assertEqual(ctx.get_channel_messages(10), [])

    def test_valid_legacy_turn_is_migrated_to_typed_entry_once(self):
        fixed = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        ctx = ConversationContext(now_provider=lambda: fixed)
        ctx.threads[10] = [
            {
                "user_id": 7,
                "username": "Ola",
                "content": "behold",
                "is_bot": False,
                "timestamp": fixed - timedelta(minutes=1),
            }
        ]

        self.assertEqual(ctx.get_channel_messages(10)[0]["content"], "behold")
        self.assertIsInstance(ctx.threads[10][0], _StoredTurn)
        first = ctx.threads[10][0]
        ctx.get_channel_messages(10)
        self.assertIs(ctx.threads[10][0], first)

    def test_typed_history_excludes_current_source_message(self):
        ctx = ConversationContext()
        key = ConversationKey(None, 10, 7)
        ctx.add_turn(key, ChatTurn("user", "forrige", 1))
        ctx.add_turn(key, ChatTurn("assistant", "svar"))
        ctx.add_turn(key, ChatTurn("user", "nå", 2))

        self.assertEqual(
            [
                turn.content
                for turn in ctx.get_prompt_history(
                    key,
                    exclude_source_message_id=2,
                )
            ],
            ["forrige", "svar"],
        )

    def test_reclassify_source_turn_applies_all_history_policies(self):
        key = ConversationKey(1, 10, 7)
        other = ConversationKey(1, 10, 8)
        prior = (
            ChatTurn("user", "eldste spørsmål", 1),
            ChatTurn("assistant", "tidligere svar"),
            ChatTurn("user", "nyeste spørsmål", 2),
        )
        cases = (
            (
                HistoryPolicy.FULL,
                (
                    prior[1],
                    prior[2],
                    ChatTurn("user", "privat inngang", 99),
                ),
            ),
            (
                HistoryPolicy.REDACT_AUTH,
                (
                    prior[1],
                    prior[2],
                    ChatTurn("user", REDACTED_AUTH_TURN, 99),
                ),
            ),
            (HistoryPolicy.OMIT, prior),
        )

        for policy, expected in cases:
            with self.subTest(policy=policy):
                ctx = ConversationContext(max_history=3)
                for turn in prior:
                    ctx.add_turn(key, turn)
                ctx.add_turn(other, ChatTurn("user", "annen bruker", 99))
                self.assertTrue(
                    ctx.stage_source_turn(
                        key,
                        ChatTurn("user", "privat inngang", 99),
                    )
                )
                self.assertEqual(len(ctx.threads[key]), 4)
                self.assertEqual(ctx._staged_source_turns, {key: 99})
                self.assertEqual(
                    ctx.get_prompt_history(
                        key,
                        exclude_source_message_id=99,
                    ),
                    prior,
                )

                self.assertTrue(
                    ctx.reclassify_source_turn(key, 99, policy)
                )

                self.assertEqual(ctx.get_prompt_history(key), expected)
                self.assertNotIn(key, ctx._staged_source_turns)
                self.assertLessEqual(len(ctx.threads[key]), 3)
                self.assertEqual(
                    ctx.get_prompt_history(other),
                    (ChatTurn("user", "annen bruker", 99),),
                )

    def test_reclassify_source_turn_is_exact_and_reports_no_match(self):
        ctx = ConversationContext()
        key = ConversationKey(1, 10, 7)
        ctx.add_turn(key, ChatTurn("user", "behold", 1))

        self.assertFalse(
            ctx.reclassify_source_turn(
                ConversationKey(1, 11, 7),
                1,
                HistoryPolicy.OMIT,
            )
        )
        self.assertFalse(
            ctx.reclassify_source_turn(key, 2, HistoryPolicy.OMIT)
        )
        self.assertEqual(
            ctx.get_prompt_history(key),
            (ChatTurn("user", "behold", 1),),
        )

    def test_typed_context_and_summary_inspect_only_exact_key(self):
        ctx = ConversationContext()
        key = ConversationKey(1, 10, 7)
        other = ConversationKey(1, 10, 8)
        ctx.add_turn(key, ChatTurn("user", "RBK og været", 1))
        ctx.add_turn(other, ChatTurn("user", "planer", 2))

        self.assertEqual(ctx.get_context(key), "User: RBK og været")
        self.assertEqual(set(ctx.get_conversation_summary(key)), {"RBK", "været"})
        self.assertEqual(ctx.get_conversation_summary(other), ["planer"])

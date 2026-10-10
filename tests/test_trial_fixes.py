import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from zoneinfo import ZoneInfo
from cal_system.reminder_manager import parse_reminder_command
from features.poll_manager import PollManager, parse_vote
from features.polls_handler import PollsHandler


class RecordingPollsHandler(PollsHandler):
    def __init__(self, monitor):
        super().__init__(monitor)
        self.sent = []

    async def send_response(self, message, content, mention_author=None):
        self.sent.append(content)


def _parse_due(value):
    return datetime.strptime(value, "%d.%m.%Y %H:%M")


def _now_oslo():
    return datetime.now(ZoneInfo("Europe/Oslo")).replace(tzinfo=None)


class RelativeReminderTests(unittest.TestCase):
    def test_om_minutter_becomes_concrete_due_date(self):
        parsed = parse_reminder_command("påminnelse teste om 2 minutter")
        assert parsed is not None and parsed["action"] == "add"
        text, due = parsed["text"], parsed["due_date"]
        assert isinstance(text, str) and isinstance(due, str)
        assert "teste" in text
        delta = _parse_due(due) - _now_oslo()
        assert timedelta(0) < delta <= timedelta(minutes=3)

    def test_om_timer_and_dager(self):
        for phrase, min_seconds in (("om 3 timer", 170 * 60), ("om 2 dager", 47 * 3600)):
            parsed = parse_reminder_command(f"påminnelse teste {phrase}")
            assert parsed is not None and isinstance(parsed["due_date"], str)
            delta = _parse_due(parsed["due_date"]) - _now_oslo()
            assert delta >= timedelta(seconds=min_seconds)

    def test_legacy_date_still_works(self):
        parsed = parse_reminder_command("påminnelse ring legen 20.06")
        assert parsed is not None and parsed["due_date"] == "20.06"

    def test_no_time_still_parses_as_add(self):
        parsed = parse_reminder_command("påminnelse ring legen")
        assert parsed is not None and parsed["action"] == "add" and parsed["due_date"] is None


class MultiPollVoteTests(unittest.IsolatedAsyncioTestCase):
    def _handler(self, tmp):
        manager = PollManager(storage_path=Path(tmp) / "polls.json")
        monitor = SimpleNamespace(
            poll=manager,
            loc=SimpleNamespace(current_lang="no", t=lambda key, **kw: {
                "vote_registered": "Stemmen er registrert",
                "vote_error": "Feil",
            }.get(key, key)),
            rate_limiter=SimpleNamespace(record_sent=lambda: None, record_failure=lambda **kw: None),
            client=None,
        )
        handler = RecordingPollsHandler(monitor)
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )
        return manager, handler, message

    async def test_stem_poll_option_votes_on_named_poll(self):
        with TemporaryDirectory() as tmp:
            manager, handler, message = self._handler(tmp)
            for q in ("Foerste?", "Andre?", "Tredje?"):
                manager.create_poll("123", q, ["Ja", "Nei"], "T")
            await handler.handle_vote(message, {"option_index": 1, "poll_ref": 3})
            poll = manager.get_active_polls("123")[2]
            assert len(poll["options"][0]["votes"]) == 1
            assert "registrert" in handler.sent[-1]

    async def test_multi_poll_without_ref_lists_and_does_not_vote(self):
        with TemporaryDirectory() as tmp:
            manager, handler, message = self._handler(tmp)
            manager.create_poll("123", "Foerste?", ["Ja", "Nei"], "T")
            manager.create_poll("123", "Andre?", ["Ja", "Nei"], "T")
            await handler.handle_vote(message, {"option_index": 1})
            votes = sum(len(o["votes"]) for p in manager.get_active_polls("123") for o in p["options"])
            assert votes == 0
            assert "flere aktive" in handler.sent[-1]

            assert "(0 stemmer)" in handler.sent[-1]

    async def test_poll_list_shows_vote_counts(self):
        with TemporaryDirectory() as tmp:
            manager, handler, message = self._handler(tmp)
            poll = manager.create_poll("123", "Foerste?", ["Ja", "Nei"], "T")
            manager.vote("123", poll["id"], 1, "7", "Tester")
            await handler.handle_poll_list(message)
            assert "1. Foerste? (1 stemme)" in handler.sent[-1]

    def test_parse_vote_shapes(self):
        assert parse_vote("@inebotten stem 3 1") == {"option_index": 1, "poll_ref": 3}
        assert parse_vote("3") == 3
        assert parse_vote("@inebotten 3 1") == {"option_index": 1, "poll_ref": 3}
        assert parse_vote("@inebotten 3 0") is None
        assert parse_vote("@inebotten 3 99") is None


if __name__ == "__main__":
    unittest.main()

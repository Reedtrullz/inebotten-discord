"""Tests for scripts/export_members.py (no live Discord connection)."""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from export_members import member_row, rest_row, write_exports  # noqa: E402


class FakeRole:
    def __init__(self, role_id, name):
        self.id = role_id
        self.name = name


class FakeMember:
    def __init__(self, member_id, name, joined_at=None, roles=()):
        self.id = member_id
        self.name = name
        self.global_name = f"Global {name}"
        self.display_name = name
        self.discriminator = "0001"
        self.bot = False
        self.system = False
        self.joined_at = joined_at
        self.roles = list(roles)
        self.display_avatar = type("Avatar", (), {"url": f"https://cdn/{name}.png"})()


class FakeGuild:
    def __init__(self, guild_id, name):
        self.id = guild_id
        self.name = name
        self.member_count = 2
        self.roles = [FakeRole("1", "@everyone"), FakeRole("2", "Mod")]


def test_write_exports_writes_csv_and_json(tmp_path):
    guild = FakeGuild(12345, "THORChain Community")
    rows = [
        {
            "id": 1,
            "username": "alice",
            "global_name": None,
            "display_name": "alice",
            "discriminator": "0001",
            "bot": False,
            "system": False,
            "joined_at": "2026-01-01T00:00:00+00:00",
            "roles": "",
            "avatar_url": None,
        },
        {
            "id": 2,
            "username": "bob",
            "global_name": None,
            "display_name": "bob",
            "discriminator": "0002",
            "bot": False,
            "system": False,
            "joined_at": "2026-01-02T00:00:00+00:00",
            "roles": "Mod",
            "avatar_url": "https://cdn.example/bob.png",
        },
    ]

    csv_path, json_path = write_exports(rows, guild, tmp_path / "members.csv")

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == ["1", "2"]
    assert rows[0]["username"] == "alice"
    assert rows[1]["roles"] == "Mod"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["guild"]["name"] == "THORChain Community"
    assert [m["id"] for m in payload["members"]] == [1, 2]


def test_member_row_handles_missing_joined_at():
    row = member_row(FakeMember(7, "carol"))
    assert row["joined_at"] is None
    assert row["display_name"] == "carol"


def test_rest_row_maps_raw_payload():
    guild = FakeGuild(12345, "THORChain Community")
    row = rest_row(
        guild,
        {
            "user": {
                "id": "42",
                "username": "dave",
                "global_name": "Dave",
                "discriminator": "0",
                "avatar": "abc123",
                "bot": False,
                "system": False,
            },
            "nick": "D",
            "roles": ["2"],
            "joined_at": "2026-01-03T00:00:00+00:00",
        },
    )
    assert row["id"] == 42
    assert row["display_name"] == "D"
    assert row["roles"] == "Mod"
    assert row["avatar_url"] == "https://cdn.discordapp.com/avatars/42/abc123.png"

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

    csv_path, json_path = write_exports(rows, guild, tmp_path / "members.csv",max_bytes=10000)

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == ["'1", "'2"]
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


async def test_repeated_cursor_is_partial_and_bounded():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import export_members as module
    page=[{'user':{'id':'42','username':'fixture'},'roles':[]}]
    client=SimpleNamespace(http=SimpleNamespace(request=AsyncMock(return_value=page)))
    result=await module.fetch_all_members(client,FakeGuild(12345,'Fixture'),max_rows=10,max_bytes=10000,deadline=__import__('time').monotonic()+2,page_size=1)
    assert result.coverage=='partial' and result.truncation_reason=='cursor_not_advancing'
    assert len(result.rows)==1 and client.http.request.await_count==2


def test_json_extension_and_existing_output_are_preserved(tmp_path):
    import pytest
    with pytest.raises(ValueError):write_exports([],FakeGuild(12345,'Fixture'),tmp_path/'members.json',max_bytes=10000)
    target=tmp_path/'members.csv';target.write_text('preserved')
    with pytest.raises(FileExistsError):write_exports([],FakeGuild(12345,'Fixture'),target,max_bytes=10000)
    assert target.read_text()=='preserved' and not target.with_suffix('.json').exists()


def test_private_modes_and_formula_like_strings(tmp_path):
    import stat
    rows=[{'id':123456789012345678,'username':' \t=CMD()','display_name':'@SUM(1)','roles':'safe'}]
    csv_path,json_path=write_exports(rows,FakeGuild(12345,'Fixture'),tmp_path/'members.csv',max_bytes=10000)
    assert stat.S_IMODE(csv_path.stat().st_mode)==stat.S_IMODE(json_path.stat().st_mode)==0o600
    with csv_path.open() as handle:value=next(csv.DictReader(handle))
    assert value['username'].startswith("'") and value['display_name'].startswith("'")
    assert value['id']=="'123456789012345678"
    assert json.loads(json_path.read_text())['members'][0]['username']==' \t=CMD()'


async def test_cached_fallback_is_partial_without_gateway_scrape():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import export_members as module
    guild=FakeGuild(12345,'Fixture');guild.members=[FakeMember(7,'cached')];guild.fetch_members=AsyncMock()
    client=SimpleNamespace(http=SimpleNamespace(request=AsyncMock(side_effect=OSError('synthetic'))))
    result=await module.fetch_all_members(client,guild,max_rows=10,max_bytes=10000,deadline=__import__('time').monotonic()+2,allow_cached_fallback=True)
    assert result.source=='cache' and result.coverage=='partial'
    guild.fetch_members.assert_not_awaited()


async def test_request_deadline_bounds_internal_retries():
    import asyncio,time
    from types import SimpleNamespace
    import export_members as module
    async def hanging(*args,**kwargs):await asyncio.sleep(10)
    result=await module.fetch_all_members(SimpleNamespace(http=SimpleNamespace(request=hanging)),FakeGuild(12345,'Fixture'),
        max_rows=10,max_bytes=10000,deadline=time.monotonic()+.02)
    assert result.coverage=='unknown' and result.truncation_reason=='deadline' and result.rows==[]


async def test_identity_and_ambiguous_name_are_refused():
    import pytest
    from types import SimpleNamespace
    import export_members as module
    client=SimpleNamespace(user=SimpleNamespace(id=7),guilds=[FakeGuild(1,'Same'),FakeGuild(2,'Same')])
    with pytest.raises(ValueError):module.verify_identity(client,'8')
    module.verify_identity(client,'7')
    with pytest.raises(ValueError):await module.resolve_guild(client,SimpleNamespace(guild_id=None,guild_name='Same'))


async def test_row_and_byte_limits_are_truthful():
    import time
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import export_members as module
    page=[{'user':{'id':str(i),'username':'x'*3000},'roles':[]} for i in (1,2)]
    client=SimpleNamespace(http=SimpleNamespace(request=AsyncMock(return_value=page)))
    result=await module.fetch_all_members(client,FakeGuild(1,'Fixture'),max_rows=1,max_bytes=10000,deadline=time.monotonic()+2)
    assert result.coverage=='partial' and result.truncation_reason=='row_limit' and len(result.rows)==1
    result=await module.fetch_all_members(client,FakeGuild(1,'Fixture'),max_rows=10,max_bytes=1024,deadline=time.monotonic()+2)
    assert result.coverage=='unknown' and result.truncation_reason=='byte_limit' and not result.rows


def test_collision_symlink_and_oversize_preserve_outputs(tmp_path):
    import pytest
    guild=FakeGuild(12345,'Fixture')
    json_path=tmp_path/'members.json';json_path.write_text('preserved')
    with pytest.raises(FileExistsError):write_exports([],guild,tmp_path/'members.csv',max_bytes=10000)
    assert json_path.read_text()=='preserved' and not (tmp_path/'members.csv').exists()
    link=tmp_path/'alias';link.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError):write_exports([],guild,link/'another.csv',max_bytes=10000)
    with pytest.raises(ValueError):write_exports([{'id':1,'username':'x'*2000}],guild,tmp_path/'large.csv',max_bytes=1024)
    assert not (tmp_path/'large.csv').exists()


def test_cli_requires_limits_and_has_no_invite_or_join():
    import pytest
    import export_members as module
    with pytest.raises(SystemExit):module.parse_args(['--guild-id','1'])
    args=module.parse_args(['--guild-id','1','--account-id','7','--out','fixture.csv','--max-rows','10','--max-bytes','10000','--timeout','5'])
    assert not hasattr(args,'join') and not hasattr(args,'invite')

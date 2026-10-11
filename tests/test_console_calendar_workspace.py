"""Synthetic authorization and mutation tests for the authenticated agenda API."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Literal, overload

import pytest

from cal_system.calendar_manager import CalendarManager
from core.access_policy import AccessPolicy, ScopeRecord
from core.request_context import RequestContext, request_scope
from web_console.server import ConsoleServer


API_KEY = "calendar-workspace-test-key"
ACTOR = "424242"
SCOPE = "private:424242"
ORIGIN = "http://127.0.0.1"


@pytest.mark.parametrize('edit_scope', ['this', 'future', 'series'])
async def test_recurring_edit_accepts_explicit_scope_without_changing_zone(workspace, edit_scope):
    server, manager, actor = workspace
    with request_scope(actor):
        item = manager.add_item(None, ACTOR, 'Console', 'Weekly', '13.10.2026', '11:00', recurrence='weekly', timezone='America/New_York')
    status, preview = await http_request(server, '/api/calendar/preview', method='POST', api_key=API_KEY,
        body={'operation': 'edit', 'revision': manager._storage.revision, 'item_id': item['id'],
              'changes': {'title': 'Reviewed weekly', 'edit_scope': edit_scope}})
    assert status == 200
    status, result = await http_request(server, '/api/calendar/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200
    stored = next(i for i in manager.items[SCOPE] if i['id'] == item['id'])
    assert stored['title'] == 'Reviewed weekly' and stored['timezone'] == 'America/New_York'
    assert stored['time'] == '11:00'


@pytest.mark.parametrize('fold', [0, 1])
async def test_create_ambiguous_time_with_deliberate_fold(workspace, fold):
    server, manager, _ = workspace
    status, preview = await http_request(server, '/api/calendar/preview', method='POST', api_key=API_KEY,
        body={'operation': 'create', 'revision': manager._storage.revision,
              'changes': {'title': 'DST choice', 'date': '25.10.2026', 'time': '02:30', 'fold': fold}})
    assert status == 200
    status, result = await http_request(server, '/api/calendar/apply', method='POST', api_key=API_KEY,
        body={'token': preview['token']})
    assert status == 200 and result['item']['fold'] == fold


@pytest.mark.parametrize('changes,reason', [({'title': ''}, 'invalid_title'),
    ({'description': 'x' * 4001}, 'invalid_description'), ({'duration_minutes': True}, 'invalid_duration')])
async def test_edit_validates_content_before_preview(workspace, changes, reason):
    server, manager, _ = workspace
    revision = manager._storage.revision
    item = manager.items[SCOPE][0]
    status, response = await http_request(server, '/api/calendar/preview', method='POST', api_key=API_KEY,
        body={'operation': 'edit', 'revision': revision, 'item_id': item['id'], 'changes': changes})
    assert status == 400 and response['error'] == reason
    assert manager._storage.revision == revision and item['title'] == 'Seed event'


@overload
async def http_request(server, path, *, method="GET", body=None, api_key=None, cookie=None, headers=(), decode_json: Literal[False]) -> tuple[int, str]: ...


@overload
async def http_request(server, path, *, method="GET", body=None, api_key=None, cookie=None, headers=(), decode_json: Literal[True] = True) -> tuple[int, dict[str, Any]]: ...


async def http_request(server, path, *, method="GET", body=None, api_key=None, cookie=None, headers=(), decode_json=True):
    reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
    parts = [f"{method} {path} HTTP/1.1", "Host: attacker.invalid", "Connection: close"]
    if api_key:
        parts.append(f"X-API-Key: {api_key}")
    if cookie:
        parts.append(f"Cookie: {cookie}")
    if body is not None:
        payload = json.dumps(body).encode()
        parts.extend(["Content-Type: application/json", f"Content-Length: {len(payload)}"])
    else:
        payload = b""
    parts.extend(headers)
    writer.write("\r\n".join(parts).encode() + b"\r\n\r\n" + payload)
    await writer.drain()
    response = await reader.read(65536)
    writer.close()
    await writer.wait_closed()
    status = int(response.split(b" ", 2)[1])
    raw = response.split(b"\r\n\r\n", 1)[1]
    return status, (json.loads(raw) if raw else {}) if decode_json else raw.decode()


@pytest.fixture
async def workspace(tmp_path):
    policy = AccessPolicy([ScopeRecord(SCOPE, "private_user", owner_id=ACTOR)], default_scope=SCOPE)
    manager = CalendarManager(storage_path=tmp_path / "calendar.json", access_policy=policy)
    actor = RequestContext("seed", ACTOR, "console", None, "no", channel_kind="console")
    with request_scope(actor):
        manager.add_item(None, ACTOR, "Console", "Seed event", "12.10.2026", "09:30", channel_id="console")
    monitor = SimpleNamespace(calendar=manager)
    server = ConsoleServer(host="127.0.0.1", port=0, api_key=API_KEY, monitor=monitor,
                           console_actor_user_id=ACTOR, trusted_origin=ORIGIN)
    await server.start()
    try:
        yield server, manager, actor
    finally:
        await server.stop()
        await manager._storage.aclose()
        await manager._outbox.slot.close()


async def test_agenda_exposes_only_configured_actor_scope_and_revision(workspace):
    server, manager, _ = workspace
    status, body = await http_request(server, "/api/calendar/items", api_key=API_KEY)
    assert status == 200
    assert body["enabled"] is True
    assert body["scope_id"] == SCOPE
    assert body["revision"] == manager._storage.revision
    assert [item["title"] for item in body["items"]] == ["Seed event"]
    assert "user_id" not in body["items"][0]


async def test_unmapped_console_actor_disables_workspace_and_rejects_write(workspace):
    server, _, _ = workspace
    server.console_actor_user_id = ""
    status, body = await http_request(server, "/api/calendar/items", api_key=API_KEY)
    assert status == 200 and body["enabled"] is False and body["items"] == []
    status, body = await http_request(server, "/api/calendar/preview", method="POST",
                                      body={"operation": "create", "revision": 1, "changes": {"title": "X", "date": "12.10.2026"}},
                                      api_key=API_KEY)
    assert status == 403 and body["error"] == "calendar_workspace_not_configured"


async def test_poll_scope_protection_reaches_api_initial_html_and_revocation(workspace, tmp_path, monkeypatch):
    from tests.test_group_planning import fixture, context, candidates
    from web_console import state_collector
    server, _, _ = workspace
    planning, calendar, polls = fixture(tmp_path)
    title = 'Restricted synthetic planning title'
    planning.create(context(), 'group:approved', title, candidates())
    monkeypatch.setattr(state_collector, 'hermes_discord_data_path', lambda name: polls.storage_path if name == 'polls.json' else tmp_path / name)
    server.monitor = SimpleNamespace(calendar=calendar, poll=polls)
    try:
        for user, channel, visible in [('', '9', False), ('999', '9', False), ('8', 'wrong', False), ('8', '9', True), ('999', '9', False)]:
            server.console_actor_user_id, server.console_actor_channel_id = user, channel
            status, body = await http_request(server, '/api/polls', api_key=API_KEY)
            assert status == 200 and body['active_polls'] == int(visible)
            assert (title in json.dumps(body)) is visible
            status, html = await http_request(server, '/', api_key=API_KEY, decode_json=False)
            assert status == 200 and (title in html) is visible
    finally:
        calendar._storage.close()
        polls.close_storage()


async def test_this_occurrence_content_does_not_leak_to_next_occurrence(workspace):
    server, manager, actor = workspace
    with request_scope(actor):
        item = manager.add_item(None, ACTOR, 'Console', 'Series title', '13.10.2026', '11:00', recurrence='weekly', timezone='America/New_York')
    for operation, changes in [('edit', {'title': 'One occurrence', 'description': 'One description', 'edit_scope': 'this'}), ('complete', None)]:
        payload = {'operation': operation, 'revision': manager._storage.revision, 'item_id': item['id']}
        if changes:
            payload['changes'] = changes
        status, preview = await http_request(server, '/api/calendar/preview', method='POST', api_key=API_KEY, body=payload)
        assert status == 200
        status, _ = await http_request(server, '/api/calendar/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
        assert status == 200
    stored = next(i for i in manager.items[SCOPE] if i['id'] == item['id'])
    assert stored['title'] == 'Series title' and not stored.get('description')
    assert stored['timezone'] == 'America/New_York' and stored['time'] == '11:00'


async def test_create_preview_apply_is_actor_revision_and_replay_bound(workspace):
    server, manager, _ = workspace
    revision = manager._storage.revision
    payload = {"operation": "create", "revision": revision,
               "changes": {"title": "New appointment", "date": "13.10.2026", "time": "11:15", "kind": "event"}}
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", body=payload, api_key=API_KEY)
    assert status == 200 and preview["effects"][0]["after"]["title"] == "New appointment", preview
    data = manager.items
    data[SCOPE][0]["description"] = "Concurrent update"
    manager.items = data
    manager._save_data_sync()
    status, stale = await http_request(server, "/api/calendar/apply", method="POST", body={"token": preview["token"]}, api_key=API_KEY)
    assert status == 409 and stale["error"] == "revision_changed"
    payload["revision"] = manager._storage.revision
    current_revision = manager._storage.revision
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", body=payload, api_key=API_KEY)
    assert status == 200
    status, result = await http_request(server, "/api/calendar/apply", method="POST", body={"token": preview["token"]}, api_key=API_KEY)
    assert status == 200 and result["operation"] == "create"
    assert manager._storage.revision == current_revision + 1
    status, replay = await http_request(server, "/api/calendar/apply", method="POST", body={"token": preview["token"]}, api_key=API_KEY)
    assert status == 400 and replay["error"] == "preview_missing"


async def test_edit_and_delete_use_domain_preview_and_stale_revision_conflicts(workspace):
    server, manager, _ = workspace
    item = manager.items[SCOPE][0]
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "edit", "item_id": item["id"], "revision": manager._storage.revision,
              "changes": {"title": "Changed"}})
    assert status == 200 and preview["effects"][0]["after"]["title"] == "Changed"
    # A second commit makes the first preview stale before it is applied.
    manager.items[SCOPE][0]["description"] = "Concurrent change"
    manager._save_data_sync()
    status, response = await http_request(server, "/api/calendar/apply", method="POST", api_key=API_KEY,
                                          body={"token": preview["token"]})
    assert status == 409 and response["error"] == "revision_changed"
    item = manager.items[SCOPE][0]
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "delete", "item_id": item["id"], "revision": manager._storage.revision})
    assert status == 200
    status, result = await http_request(server, "/api/calendar/apply", method="POST", api_key=API_KEY,
                                         body={"token": preview["token"]})
    assert status == 200 and result["operation"] == "delete"
    assert manager.items[SCOPE][0].get("_mutation_deleted") is True


@pytest.mark.parametrize(("all_day", "time"), [(True, None), (False, "13:45")])
async def test_browser_form_edit_preserves_explicit_all_day_semantics(workspace, all_day, time):
    server, manager, _ = workspace
    item = manager.items[SCOPE][0]
    original = manager.storage_path.read_bytes()
    session = server.store.create_session(600, server._session_binding_hash())
    headers = (f"Origin: {ORIGIN}", f"X-CSRF-Token: {server._csrf_token(session)}")
    status, preview = await http_request(server, "/api/calendar/preview", method="POST",
        cookie=f"console_session={session}", headers=headers,
        body={"operation": "edit", "item_id": item["id"], "revision": manager._storage.revision,
              "changes": {"title": "Browser edit", "date": "13.10.2026", "time": time,
                          "kind": "event", "description": "Changed in browser",
                          "timezone": "Europe/Oslo", "all_day": all_day}})
    assert status == 200, preview
    assert manager.storage_path.read_bytes() == original
    after = preview["effects"][0]["after"]
    assert after["all_day"] is all_day and after["time"] == time
    status, result = await http_request(server, "/api/calendar/apply", method="POST",
        cookie=f"console_session={session}", headers=headers, body={"token": preview["token"]})
    assert status == 200 and result["applied_count"] == 1
    status, agenda = await http_request(server, "/api/calendar/items", cookie=f"console_session={session}")
    assert status == 200
    assert agenda["items"][0]["title"] == "Browser edit"
    assert agenda["items"][0]["all_day"] is all_day
    assert agenda["items"][0]["time"] == time


async def test_browser_edit_rejects_non_boolean_all_day_without_writing(workspace):
    server, manager, _ = workspace
    original = manager.storage_path.read_bytes()
    status, result = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "edit", "item_id": manager.items[SCOPE][0]["id"],
              "revision": manager._storage.revision, "changes": {"all_day": "false"}})
    assert status == 400 and result["error"] == "all_day_must_be_boolean"
    assert manager.storage_path.read_bytes() == original


async def test_forged_actor_scope_extra_keys_and_bad_json_are_rejected(workspace):
    server, manager, _ = workspace
    status, body = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "delete", "item_id": manager.items[SCOPE][0]["id"], "revision": manager._storage.revision,
              "user_id": "attacker", "scope_id": "shared", "channel_id": "forged"})
    assert status == 400 and body["error"] == "invalid_payload"
    status, body = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "delete", "item_id": manager.items[SCOPE][0]["id"], "revision": True})
    assert status == 400


async def test_browser_write_requires_exact_origin_and_session_bound_csrf(workspace):
    server, manager, _ = workspace
    session = server.store.create_session(600, server._session_binding_hash())
    cookie = f"console_session={session}"
    csrf = server._csrf_token(session)
    body = {"operation": "complete", "item_id": manager.items[SCOPE][0]["id"], "revision": manager._storage.revision}
    status, response = await http_request(server, "/api/calendar/preview", method="POST", body=body, cookie=cookie,
                                          headers=[f"Origin: {ORIGIN}", f"X-CSRF-Token: {csrf}"])
    assert status == 200
    status, response = await http_request(server, "/api/calendar/preview", method="POST", body=body, cookie=cookie,
                                          headers=["Origin: http://attacker.invalid", f"X-CSRF-Token: {csrf}"])
    assert status == 403 and response["error"] == "trusted_origin_required"
    status, response = await http_request(server, "/api/calendar/preview", method="POST", body=body, cookie=cookie,
                                          headers=[f"Origin: {ORIGIN}", "X-CSRF-Token: wrong"])
    assert status == 403 and response["error"] == "csrf_failed"
    status, response = await http_request(server, "/api/calendar/preview", method="POST", body=body, cookie=cookie,
                                          headers=[f"X-CSRF-Token: {csrf}"])
    assert status == 403 and response["error"] == "trusted_origin_required"


async def test_api_key_is_explicit_path_and_cookie_alone_cannot_bypass_it(workspace):
    server, manager, _ = workspace
    session = server.store.create_session(600, server._session_binding_hash())
    body = {"operation": "complete", "item_id": manager.items[SCOPE][0]["id"], "revision": manager._storage.revision}
    status, _ = await http_request(server, "/api/calendar/preview", method="POST", body=body, cookie="console_session=bad",
                                   headers=[f"Origin: {ORIGIN}", f"X-CSRF-Token: {server._csrf_token(session)}"])
    assert status == 401
    status, _ = await http_request(server, "/api/calendar/preview", method="POST", body=body, api_key=API_KEY)
    assert status == 200


@pytest.mark.parametrize("origin", [None, "https://attacker.invalid", ORIGIN])
@pytest.mark.parametrize("path", ["preview", "apply"])
async def test_cloudflare_calendar_is_read_only_on_http_write_routes(workspace, monkeypatch, origin, path):
    server, manager, _ = workspace
    payload = {"operation": "complete", "item_id": manager.items[SCOPE][0]["id"],
               "revision": manager._storage.revision}
    status, preview = await http_request(server, "/api/calendar/preview", method="POST",
                                        body=payload, api_key=API_KEY)
    assert status == 200
    monkeypatch.setattr(server, "auth_mode", "cloudflare_access")
    monkeypatch.setattr(server, "cloudflare_access_verifier", SimpleNamespace(
        verify_headers=lambda headers: headers.get("cf-access-jwt-assertion") == "verified-test-token"))
    headers = ["Cf-Access-Jwt-Assertion: verified-test-token"]
    if origin is not None:
        headers.append(f"Origin: {origin}")
    status, agenda = await http_request(server, "/api/calendar/items", headers=headers)
    assert status == 200 and agenda["read_only"] is True
    before = manager.storage_path.read_bytes()
    revision = manager._storage.revision
    body = payload if path == "preview" else {"token": preview["token"]}
    status, result = await http_request(server, f"/api/calendar/{path}", method="POST",
                                      body=body, headers=headers)
    assert status == 403 and result["error"] == "browser_writes_require_console_session"
    assert manager.storage_path.read_bytes() == before
    assert manager._storage.revision == revision
    status, result = await http_request(server, "/api/calendar/apply", method="POST",
                                      body={"token": preview["token"]}, api_key=API_KEY)
    assert status == 200 and result["operation"] == "complete"


async def test_browser_session_can_apply_calendar_preview(workspace):
    server, manager, _ = workspace
    session = server.store.create_session(600, server._session_binding_hash())
    headers = [f"Origin: {ORIGIN}", f"X-CSRF-Token: {server._csrf_token(session)}"]
    cookie = f"console_session={session}"
    body = {"operation": "complete", "item_id": manager.items[SCOPE][0]["id"],
            "revision": manager._storage.revision}
    status, preview = await http_request(server, "/api/calendar/preview", method="POST",
                                        body=body, cookie=cookie, headers=headers)
    assert status == 200
    status, result = await http_request(server, "/api/calendar/apply", method="POST",
                                      body={"token": preview["token"]}, cookie=cookie, headers=headers)
    assert status == 200 and result["operation"] == "complete"
    assert manager.items[SCOPE][0]["completed"] is True


async def test_apply_reauthorizes_after_access_is_revoked(workspace):
    server, manager, _ = workspace
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
        body={"operation": "complete", "item_id": manager.items[SCOPE][0]["id"], "revision": manager._storage.revision})
    assert status == 200
    manager.access_policy = AccessPolicy([ScopeRecord(SCOPE, "private_user", owner_id="999")], default_scope=SCOPE)
    status, response = await http_request(server, "/api/calendar/apply", method="POST", api_key=API_KEY, body={"token": preview["token"]})
    assert status == 403 and response["error"] == "scope_membership_required"
    assert manager.items[SCOPE][0]["completed"] is False


async def test_conflict_resolution_choices_use_calendar_preview_contract(workspace):
    from cal_system.sync_outbox import enqueue
    server, manager, _ = workspace
    data = manager.items
    item = data[SCOPE][0]
    item["duration_minutes"] = 60
    operation = enqueue(item, "update", SCOPE)
    operation.update(state="conflict", reason_code="remote_version_changed", conflict_remote={
        "id": operation["remote_id"], "etag": "etag-reviewed", "summary": item["title"],
        "start": {"date": "2026-10-12"}, "end": {"date": "2026-10-12"},
        "extendedProperties": {"private": {}},
    })
    manager.items = data
    manager._save_data_sync()
    assert manager.items[SCOPE][0]["sync_operations"][0]["operation_id"] == operation["operation_id"]
    for choice in ("use_local", "use_remote"):
        status, preview = await http_request(server, "/api/calendar/preview", method="POST", api_key=API_KEY,
            body={"operation": "conflict", "operation_id": operation["operation_id"],
                  "choice": choice, "revision": manager._storage.revision})
        assert status == 200, preview
        assert preview["effects"][0]["choice"] == choice


def test_dashboard_workspace_uses_safe_dom_and_has_keyboard_responsive_controls():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "web_console" / "static" / "app.js").read_text()
    template = (root / "web_console" / "dashboard.py").read_text()
    css = (root / "web_console" / "static" / "main.css").read_text()
    assert "textContent = item.title" in source
    assert "data-calendar-apply" in template and "data-calendar-filter" in template
    assert "@media (max-width: 700px)" in css
    assert "calendar-workspace-status" in template


def test_calendar_workspace_browser_create_preview_apply_and_empty_filter(page, console_server, tmp_path):
    from datetime import datetime
    from types import SimpleNamespace
    from cal_system.calendar_manager import CalendarManager
    from core.access_policy import AccessPolicy, ScopeRecord
    from core.request_context import RequestContext, request_scope

    actor_id = "777001"
    scope = f"private:{actor_id}"
    manager = CalendarManager(storage_path=tmp_path / "browser-calendar.json",
        access_policy=AccessPolicy([ScopeRecord(scope, "private_user", owner_id=actor_id)], default_scope=scope))
    with request_scope(RequestContext("seed", actor_id, "console", None, "no", channel_kind="console")):
        manager.add_item(None, actor_id, "Console", "Keyboard seed", "12.10.2026", channel_id="console")
    console_server.monitor = SimpleNamespace(calendar=manager)
    console_server.console_actor_user_id = actor_id
    console_server.console_actor_channel_id = "console"
    base = f"http://127.0.0.1:{console_server.actual_port}"
    console_server.trusted_origin = base
    token = console_server.store.create_session(600, console_server._session_binding_hash())
    page.context.add_cookies([{"name": "console_session", "value": token, "url": base}])
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/")
        page.locator("[data-calendar-status]").wait_for()
        assert "1 oppføringer" in page.locator("[data-calendar-status]").inner_text()
        assert page.locator("[data-calendar-agenda]").get_by_text("Keyboard seed").is_visible()
        page.locator('[data-calendar-action="complete"]').first.focus()
        page.keyboard.press("Enter")
        page.locator("[data-calendar-preview]:not([hidden])").wait_for()
        assert "complete" in page.locator("[data-calendar-preview]").inner_text().lower()
        page.locator("[data-calendar-cancel]").click()
        assert page.locator('[data-calendar-form] button[type="submit"]').evaluate("el => document.activeElement === el")
        assert page.locator("[data-calendar-workspace]").bounding_box()["width"] <= 390
        page.locator("[data-calendar-agenda] summary").first.click()
        assert page.locator("[data-calendar-agenda] details[open]").count() == 1
        page.locator('[data-calendar-form] input[name="title"]').fill("Browser appointment")
        page.locator('[data-calendar-form] input[name="date"]').fill("2026-10-13")
        page.locator('[data-calendar-form] textarea[name="description"]').fill("Behold denne beskrivelsen æøå")
        page.locator('[data-calendar-form] button[type="submit"]').click()
        page.locator("[data-calendar-preview]:not([hidden])").wait_for()
        assert "Browser appointment" in page.locator("[data-calendar-preview]").inner_text()
        page.locator("[data-calendar-apply]").click()
        page.locator("[data-calendar-agenda]").get_by_text("Browser appointment").wait_for()
        assert page.locator("[data-calendar-refresh]").evaluate("el => document.activeElement === el")
        appointment = page.locator("[data-calendar-agenda] article").filter(has=page.get_by_role("heading", name="Browser appointment", exact=True))
        appointment.locator("summary").click()
        assert appointment.get_by_text("Behold denne beskrivelsen æøå", exact=True).is_visible()
        appointment.locator('[data-calendar-action="edit"]').click()
        page.locator('[data-calendar-form] input[name="title"]').fill("Edited appointment")
        page.locator('[data-calendar-form] button[type="submit"]').click()
        page.locator("[data-calendar-preview]:not([hidden])").wait_for()
        assert appointment.get_by_role("heading", name="Browser appointment", exact=True).is_visible()
        page.locator("[data-calendar-apply]").click()
        page.locator("[data-calendar-agenda]").get_by_role("heading", name="Edited appointment", exact=True).wait_for()
        stored = next(item for item in manager.items[scope] if item["title"] == "Edited appointment")
        assert stored["all_day"] is True and stored["time"] is None
        assert stored["description"] == "Behold denne beskrivelsen æøå"
        page.locator("[data-calendar-filter]").fill("does not exist")
        assert page.locator("[data-calendar-agenda]").get_by_text("Ingen treff på filteret.").is_visible()
    finally:
        import asyncio
        import threading
        def close_manager():
            async def close():
                await manager._storage.aclose()
                await manager._outbox.slot.close()
            asyncio.run(close())
        thread = threading.Thread(target=close_manager)
        thread.start(); thread.join(timeout=5)


async def test_agenda_orders_across_month_and_year_boundaries(workspace):
    server,manager,_=workspace
    actor=RequestContext('seed',ACTOR,'console',None,'no','console')
    with request_scope(actor):
        manager.add_item(None,ACTOR,'Console','November end','30.11.2026')
        manager.add_item(None,ACTOR,'Console','December start','01.12.2026')
        manager.add_item(None,ACTOR,'Console','Next year','01.01.2027')
    status,response=await http_request(server,'/api/calendar/items',api_key=API_KEY)
    assert status==200
    assert [item['title'] for item in response['items']]==['Seed event','November end','December start','Next year']


async def test_create_keeps_reviewed_description_in_committed_store(workspace):
    server, manager, _ = workspace
    description = "Ta med noter æøå\nAndre linje,; <inert>"
    payload = {"operation": "create", "revision": manager._storage.revision,
               "changes": {"title": "Described appointment", "date": "13.10.2026", "description": description}}
    status, preview = await http_request(server, "/api/calendar/preview", method="POST", body=payload, api_key=API_KEY)
    assert status == 200 and preview["effects"][0]["after"]["description"] == description
    status, result = await http_request(server, "/api/calendar/apply", method="POST", body={"token": preview["token"]}, api_key=API_KEY)
    assert status == 200
    assert result["item"].get("description") == description
    persisted = json.loads(manager.storage_path.read_text())["document"][SCOPE]
    assert next(item for item in persisted if item["id"] == result["item"]["id"])["description"] == description

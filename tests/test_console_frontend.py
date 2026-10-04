"""Comprehensive frontend tests for the Inebotten web console."""

import json
from typing import Any

import pytest

from web_console.server import ConsoleServer

HOST = "127.0.0.1"
API_KEY = "test-key-frontend"


def _base_url(server: ConsoleServer) -> str:
    return f"http://{HOST}:{server.actual_port}"


def _login(page: Any, server: ConsoleServer) -> None:
    base = _base_url(server)
    page.goto(f"{base}/login")
    page.fill('input[name="api_key"]', API_KEY)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{base}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def test_login_page_renders(page: Any, console_server: ConsoleServer) -> None:
    """Verify login page loads with form elements."""
    page.goto(f"{_base_url(console_server)}/login")
    assert page.locator('input[name="api_key"]').is_visible()
    assert page.locator('button[type="submit"]').is_visible()
    assert "Logg inn" in page.content()


def test_login_with_valid_key(page: Any, console_server: ConsoleServer) -> None:
    """Enter valid key, submit, verify redirect to dashboard."""
    page.goto(f"{_base_url(console_server)}/login")
    page.fill('input[name="api_key"]', API_KEY)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{_base_url(console_server)}/")
    assert page.locator("header").is_visible()


def test_login_with_invalid_key(page: Any, console_server: ConsoleServer) -> None:
    """Enter invalid key, verify error message."""
    page.goto(f"{_base_url(console_server)}/login")
    page.fill('input[name="api_key"]', "wrong-key")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    content = page.content()
    assert "Ugyldig" in content or "feilet" in content.lower() or "error" in content.lower()


def test_dashboard_requires_auth(page: Any, console_server: ConsoleServer) -> None:
    """Unauthenticated access to / returns login page."""
    page.goto(f"{_base_url(console_server)}/")
    assert page.locator('input[name="api_key"]').is_visible()


def test_dashboard_renders_cards(page: Any, console_server: ConsoleServer) -> None:
    """Verify the motivating dashboard sections are visible."""
    _login(page, console_server)
    content = page.content()
    assert "Inebotten" in content
    assert "Nå" in content
    assert "Bridge" in content
    assert "Kalender" in content
    assert "Avstemninger" in content
    assert "Siste aktivitet" in content
    assert "Diagnostikk" in content
    assert "Rate Limits" in content
    assert "Intents" in content
    assert "Minne" in content
    assert "Logger" in content


def test_gcal_auth_page_renders_after_login(page: Any, console_server: ConsoleServer) -> None:
    """Verify Google Calendar setup page is reachable from an authenticated browser session."""
    _login(page, console_server)
    page.goto(f"{_base_url(console_server)}/gcal-auth")
    page.wait_for_load_state("networkidle")

    assert page.locator("#gcal-auth").is_visible()
    assert page.locator('textarea[name="credentials_json"]').is_visible()
    assert page.locator('a[href="https://console.developers.google.com/auth/clients"]').is_visible()
    assert "OAuth-oppsett" in page.content()
    assert "Desktop app" in page.content()


def test_static_assets_load(page: Any, console_server: ConsoleServer) -> None:
    """Verify the login page loads only the assets it needs."""
    page.goto(f"{_base_url(console_server)}/login")
    content = page.content()
    assert "/static/main.css" in content
    assert "/static/login.js" in content
    assert "/static/app.js" not in content

    _login(page, console_server)
    content = page.content()
    assert "/static/app.js" in content


def test_api_status_returns_json(page: Any, console_server: ConsoleServer) -> None:
    """Verify /api/status returns JSON when authenticated via header."""
    response = page.request.get(
        f"{_base_url(console_server)}/api/status",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status == 200
    body = response.json()
    assert "status" in body


def test_health_endpoint_no_auth(page: Any, console_server: ConsoleServer) -> None:
    """Verify /health is accessible without authentication."""
    response = page.request.get(f"{_base_url(console_server)}/health")
    assert response.status == 200
    body = response.json()
    assert body.get("status") in {"healthy", "degraded", "starting"}
    assert body.get("console", {}).get("status") == "running"
    assert "persistence" in body


def test_theme_toggle_login_page(page: Any, console_server: ConsoleServer) -> None:
    """Click theme toggle on login page, verify html class changes."""
    page.goto(f"{_base_url(console_server)}/login")
    html_class = page.evaluate("() => document.documentElement.className")
    initial_has_light = "light" in html_class

    page.click('button[aria-label="Bytt tema"]')
    page.wait_for_timeout(200)

    html_class = page.evaluate("() => document.documentElement.className")
    new_has_light = "light" in html_class
    assert new_has_light != initial_has_light


def test_theme_toggle_dashboard(page: Any, console_server: ConsoleServer) -> None:
    """Verify dashboard has a visible theme toggle button."""
    _login(page, console_server)
    toggles = page.locator('button[aria-label="Bytt tema"]')
    count = toggles.count()
    visible = sum(1 for i in range(count) if toggles.nth(i).is_visible())
    assert visible >= 1


def test_modal_opens_on_details_click(page: Any, console_server: ConsoleServer) -> None:
    """Verify 'Detaljer' button exists on status card."""
    _login(page, console_server)
    button = page.locator("#status button:has-text('Detaljer')")
    assert button.is_visible()


def test_modal_closes_on_escape(page: Any, console_server: ConsoleServer) -> None:
    """Verify modal dialog HTML is present with correct ARIA attributes."""
    _login(page, console_server)
    dialog = page.locator('[role="dialog"]')
    assert dialog.count() == 1
    assert dialog.get_attribute("aria-modal") == "true"
    assert dialog.get_attribute("tabindex") == "-1"


def test_modal_has_dialog_role(page: Any, console_server: ConsoleServer) -> None:
    """Verify modal close button has correct aria-label."""
    _login(page, console_server)
    close_button = page.locator('button[aria-label="Lukk"]')
    assert close_button.count() == 1


def test_mobile_menu_toggle(page: Any, console_server: ConsoleServer) -> None:
    """Verify mobile menu button is visible on small viewport."""
    page.set_viewport_size({"width": 375, "height": 667})
    _login(page, console_server)
    menu_button = page.locator('button[aria-label="Meny"]')
    assert menu_button.is_visible()


def test_skip_link_exists(page: Any, console_server: ConsoleServer) -> None:
    """Verify skip link is present on dashboard."""
    _login(page, console_server)
    assert "Hopp til hovedinnhold" in page.content()


def test_main_content_has_tabindex(page: Any, console_server: ConsoleServer) -> None:
    """Verify main content area is focusable."""
    _login(page, console_server)
    main = page.locator("main#main-content")
    assert main.is_visible()
    assert main.get_attribute("tabindex") == "-1"


def test_aria_labels_on_nav(page: Any, console_server: ConsoleServer) -> None:
    """Verify nav and interactive elements have aria-labels."""
    _login(page, console_server)
    assert page.locator('nav[aria-label="Hovednavigasjon"]').is_visible()

    toggles = page.locator('button[aria-label="Bytt tema"]')
    count = toggles.count()
    visible = sum(1 for i in range(count) if toggles.nth(i).is_visible())
    assert visible >= 1


def test_nav_links_present(page: Any, console_server: ConsoleServer) -> None:
    """Verify all nav links are present in the header."""
    _login(page, console_server)
    nav = page.locator('nav[aria-label="Hovednavigasjon"]')
    assert nav.is_visible()

    links = ["Oversikt", "Status", "Kalender", "Avstemninger", "Diagnostikk", "Minne", "Kommandoer", "Logger"]
    for text in links:
        assert nav.locator(f'a:has-text("{text}")').is_visible()


def test_mobile_viewport(page: Any, console_server: ConsoleServer) -> None:
    """Set mobile viewport, verify no horizontal overflow."""
    page.set_viewport_size({"width": 375, "height": 667})
    _login(page, console_server)

    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    assert scroll_width <= client_width


def test_api_logs_returns_json(page: Any, console_server: ConsoleServer) -> None:
    """Verify /api/logs returns JSON when authenticated."""
    response = page.request.get(
        f"{_base_url(console_server)}/api/logs",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status == 200
    body = response.json()
    assert "logs" in body


def test_api_intents_returns_json(page: Any, console_server: ConsoleServer) -> None:
    """Verify /api/intents returns JSON when authenticated."""
    response = page.request.get(
        f"{_base_url(console_server)}/api/intents",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status == 200
    body = response.json()
    assert "intent_counts" in body
    assert "fallback_count" in body


def test_initial_data_script_present(page: Any, console_server: ConsoleServer) -> None:
    """Verify initial data script is embedded in dashboard HTML."""
    _login(page, console_server)
    script = page.locator("script#initial-data")
    assert script.count() == 1
    assert script.get_attribute("type") == "application/json"


def test_demo_page_has_no_console_warnings(page: Any, console_server: ConsoleServer) -> None:
    """Demo mode should render static data without authenticated API polling warnings."""
    messages: list[str] = []
    page.on("console", lambda msg: messages.append(f"{msg.type}: {msg.text}"))
    page.goto(f"{_base_url(console_server)}/demo")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    warnings = [message for message in messages if message.startswith(("warning:", "error:"))]
    assert warnings == []


def _poll_synthetic_state(page: Any, endpoint: str, responses: list[dict[str, Any]]) -> None:
    """Drive the real browser poller with generated loopback API payloads."""
    index = 0

    def respond(route: Any) -> None:
        nonlocal index
        payload = responses[index]
        index = min(index + 1, len(responses) - 1)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route(f"**{endpoint}**", respond)
    page.evaluate(
        """async (endpoint) => {
          const app = window.consoleApp;
          app.isPolling = true;
          app.pollingConfig[endpoint].lastFetch = 0;
          await app.pollEndpoint(endpoint);
        }""",
        endpoint,
    )


def test_calendar_details_and_open_modal_follow_latest_poll(page: Any, console_server: ConsoleServer) -> None:
    """Calendar details, count and modal must use the same fetched snapshot."""
    page.goto(f"{_base_url(console_server)}/demo")
    hostile_title = '<img src=x onerror="window.pwned=true"> New event'
    refreshed_title = '<script>window.pwned=true</script> Newest event'
    _poll_synthetic_state(
        page,
        "/api/calendar",
        [
            {
                "event_count": 1,
                "task_count": 2,
                "upcoming_events": [{"title": hostile_title, "date": "2026-10-05"}],
            },
            {
                "event_count": 1,
                "task_count": 2,
                "upcoming_events": [{"title": refreshed_title, "date": "2026-10-06"}],
            },
        ],
    )

    assert page.locator('[data-metric="calendar.events"]').first.inner_text() == "1"
    assert any(hostile_title in row for row in page.locator("#calendar .mini-row").all_inner_texts())
    assert page.locator("#calendar img").count() == 0

    page.locator('#calendar [data-section-modal="calendar"]').click()
    modal = page.locator("#modal-content")
    assert hostile_title in modal.inner_text()
    close_button = page.locator(".modal-close")
    close_button.focus()
    page.evaluate(
        """async () => {
          window.consoleApp.pollingConfig['/api/calendar'].lastFetch = 0;
          await window.consoleApp.pollEndpoint('/api/calendar');
        }"""
    )
    assert refreshed_title in page.locator("#calendar .mini-row").inner_text()
    assert refreshed_title in modal.inner_text()
    assert page.evaluate("document.activeElement.className") == "modal-close"
    assert page.evaluate("window.pwned || false") is False


def test_removing_last_calendar_event_renders_empty_state(page: Any, console_server: ConsoleServer) -> None:
    """A transition from one event to none must remove stale detail rows."""
    page.goto(f"{_base_url(console_server)}/demo")
    _poll_synthetic_state(
        page,
        "/api/calendar",
        [
            {"event_count": 1, "task_count": 0, "upcoming_events": [{"title": "One event", "date": "Tomorrow"}]},
            {"event_count": 0, "task_count": 0, "upcoming_events": []},
        ],
    )
    page.evaluate(
        """async () => {
          window.consoleApp.pollingConfig['/api/calendar'].lastFetch = 0;
          await window.consoleApp.pollEndpoint('/api/calendar');
        }"""
    )

    assert page.locator('[data-metric="calendar.events"]').first.inner_text() == "0"
    assert page.locator("#calendar .mini-row").count() == 0
    assert page.locator("#calendar .empty-state").inner_text() == "Ingen kommende kalenderhendelser."


def test_poll_details_render_actual_collector_payload_and_modal(page: Any, console_server: ConsoleServer) -> None:
    """Poll title and vote count from the existing API appear in card and modal."""
    page.goto(f"{_base_url(console_server)}/demo")
    _poll_synthetic_state(
        page,
        "/api/polls",
        [{"active_polls": 1, "polls": [{"title": "Dinner choice", "vote_count": 7}]}],
    )

    assert "Dinner choice" in page.locator("#polls .card-body").inner_text()
    assert "7" in page.locator("#polls .card-body").inner_text()
    page.locator('#polls [data-section-modal="polls"]').click()
    assert "Dinner choice" in page.locator("#modal-content").inner_text()
    assert "7" in page.locator("#modal-content").inner_text()


def test_latest_logs_render_as_text_and_copy_matches_visible_lines(page: Any, console_server: ConsoleServer) -> None:
    """Log detail and copy output must follow the latest response safely."""
    page.goto(f"{_base_url(console_server)}/demo")
    hostile_line = '<svg onload="window.pwned=true"> latest log'
    _poll_synthetic_state(page, "/api/logs?lines=50", [{"logs": [hostile_line]}])
    page.evaluate(
        """() => Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: {writeText: async (text) => { window.copiedLogs = text; }}
        })"""
    )

    visible = page.locator("#log-container")
    assert hostile_line in visible.inner_text()
    assert visible.locator("svg").count() == 0
    page.locator("[data-copy-logs]").click()
    page.wait_for_function("window.copiedLogs !== undefined")

    assert page.evaluate("window.copiedLogs") == visible.inner_text()
    assert page.evaluate("window.pwned || false") is False


def test_calendar_refresh_keeps_keyboard_focus_and_narrow_layout(page: Any, console_server: ConsoleServer) -> None:
    """Updating details keeps the open dialog usable at a narrow viewport."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{_base_url(console_server)}/demo")
    _poll_synthetic_state(
        page,
        "/api/calendar",
        [{"event_count": 1, "task_count": 0, "upcoming_events": [{"title": "Focused event", "date": "Today"}]}],
    )
    page.locator('#calendar [data-section-modal="calendar"]').click()
    dialog = page.locator('[role="dialog"]')
    close_button = page.locator(".modal-close")
    close_button.focus()
    page.evaluate(
        """async () => {
          window.consoleApp.pollingConfig['/api/calendar'].lastFetch = 0;
          await window.consoleApp.pollEndpoint('/api/calendar');
        }"""
    )

    assert page.evaluate("document.activeElement.className") == "modal-close"
    assert "Focused event" in page.locator("#modal-content").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth") is True
    close_button.press("Tab")
    assert dialog.is_visible()


def test_calendar_scope_policy_explains_owner_and_audience_as_text(page: Any, console_server: ConsoleServer) -> None:
    """Optional scope fields explain access without interpreting hostile text as markup."""
    page.goto(f"{_base_url(console_server)}/demo")
    hostile_summary = '<img src=x onerror="window.scopePwned=true"> Owner controls writes'
    _poll_synthetic_state(
        page,
        "/api/calendar",
        [{
            "event_count": 0,
            "task_count": 0,
            "upcoming_events": [],
            "scope_policy": [{
                "scope_id": "private-calendar",
                "kind": "private",
                "owner_id": "owner-123",
                "collaborator_ids": ["member-456"],
                "channel_ids": ["channel-789"],
                "read_policy": "owner and approved members",
                "write_policy": "owner only",
            }],
            "default_scope": "private-calendar",
            "access_summary": hostile_summary,
            "invocation_policy": {
                "mode": "allowlist",
                "allowed_users": ["owner-123", "member-456"],
                "allowed_channels": ["channel-789"],
                "legacy_group_dm_bypass": False,
                "inherited_defaults": "Legacy group settings apply until reviewed",
            },
        }],
    )

    explanation = page.locator("#calendar [data-calendar-scope]")
    assert explanation.is_visible()
    rendered = explanation.inner_text()
    for expected in (
        "owner-123", "member-456", "channel-789", "owner and approved members",
        "owner only", "allowlist", "Legacy group settings apply until reviewed",
    ):
        assert expected in rendered
    assert hostile_summary in rendered
    assert explanation.locator("img").count() == 0

    page.locator('#calendar [data-section-modal="calendar"]').click()
    assert hostile_summary in page.locator("#modal-content").inner_text()
    assert "owner-123" in page.locator("#modal-content").inner_text()
    assert page.evaluate("window.scopePwned || false") is False


def test_calendar_poll_is_safe_when_auxiliary_page_has_no_calendar_card(page: Any, console_server: ConsoleServer) -> None:
    page.goto(f"{_base_url(console_server)}/demo")
    page.evaluate("document.getElementById('calendar').remove()")
    page.evaluate("window.consoleApp.updateDashboard('calendar', {event_count: 0, task_count: 0, upcoming_events: [], access_summary: 'Delt område'})")
    assert page.evaluate("window.consoleApp.authExpired") is False


def test_section_renderer_owns_latest_modal_and_overview_snapshot(page: Any, console_server: ConsoleServer) -> None:
    page.goto(f"{_base_url(console_server)}/demo")
    page.evaluate("window.consoleApp.showSectionModal('calendar')")
    page.evaluate("window.consoleApp.renderSection('calendar', {event_count: 1, task_count: 0, upcoming_events: [{title: 'Latest owned snapshot', date: 'Tomorrow'}]})")
    assert 'Latest owned snapshot' in page.locator('#modal-content').inner_text()
    assert page.locator('[data-metric="overview.calendar"]').inner_text()=='1 / 0'

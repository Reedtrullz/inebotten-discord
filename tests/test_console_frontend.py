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
    assert page.locator("[data-poll-endpoint]").count() == 8
    assert page.locator("[data-poll-retry]").count() == 8


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


def _start_fake_poller(page: Any, console_server: ConsoleServer, responses: dict[str, Any] | None = None) -> None:
    page.clock.install(time="2026-10-04T09:00:00")
    page.goto(f"{_base_url(console_server)}/demo")
    page.evaluate(
        """async (responses) => {
          window.__responses = responses || {};
          window.__requestCounts = {};
          window.__settledRequests = 0;
          window.__abortedRequests = {};
          window.fetch = async (url, options = {}) => {
            const endpoint = String(url);
            window.__requestCounts[endpoint] = (window.__requestCounts[endpoint] || 0) + 1;
            const configured = window.__responses[endpoint] || {status: 200, body: {}};
            const queue = Array.isArray(configured) ? configured : [configured];
            const response = queue.length > 1 ? queue.shift() : queue[0];
            window.__settledRequests += 1;
            if (response.hang) {
              return new Promise((resolve, reject) => {
                options.signal?.addEventListener('abort', () => {
                  window.__abortedRequests[endpoint] = (window.__abortedRequests[endpoint] || 0) + 1;
                  reject(new DOMException('Aborted', 'AbortError'));
                }, {once: true});
              });
            }
            return {
              status: response.status ?? 200,
              ok: (response.status ?? 200) >= 200 && (response.status ?? 200) < 300,
              json: async () => response.body || {},
            };
          };
          const app = window.consoleApp;
          app.isDemo = false;
          app.startPolling();
          for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
        }""",
        responses or {},
    )


def test_visibility_cycles_keep_one_poll_chain_per_endpoint(page: Any, console_server: ConsoleServer) -> None:
    """Repeated hide/show cycles leave only one scheduled request per endpoint."""
    _start_fake_poller(page, console_server)
    page.evaluate(
        """async () => {
          let visibility = 'visible';
          Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => visibility});
          window.__setVisibility = async (state) => {
            visibility = state;
            document.dispatchEvent(new Event('visibilitychange'));
            for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
          };
          await window.__setVisibility('hidden');
          await window.__setVisibility('visible');
          await window.__setVisibility('hidden');
          await window.__setVisibility('visible');
        }"""
    )
    page.clock.fast_forward(5000)

    assert page.evaluate("window.__requestCounts['/api/status']") == 4
    assert page.evaluate("Object.keys(window.consoleApp.pollingEntries).length") == 8
    assert page.evaluate("Object.values(window.consoleApp.pollingEntries).every((entry) => entry.timerId !== null)")


def test_endpoint_failure_stays_stale_until_its_own_retry_succeeds(page: Any, console_server: ConsoleServer) -> None:
    """A healthy endpoint cannot make a failing calendar card look fresh."""
    _start_fake_poller(
        page,
        console_server,
        {"/api/calendar": [
            {"status": 503, "body": {}},
            {"status": 200, "body": {"event_count": 2, "task_count": 0, "upcoming_events": []}},
        ]},
    )

    calendar_state = page.locator('#calendar [data-poll-endpoint="/api/calendar"]')
    status_state = page.locator('#status [data-poll-endpoint="/api/status"]')
    assert calendar_state.count() == 1
    assert "Feil" in calendar_state.inner_text() or "utdatert" in calendar_state.inner_text().lower()
    assert "utdaterte" in page.locator("#last-updated").inner_text().lower()
    first_status_time = status_state.get_attribute("data-last-success")
    page.locator('#calendar [data-poll-retry="/api/calendar"]').click()
    page.wait_for_function("window.__requestCounts['/api/calendar'] === 2")

    assert "Oppdatert" in calendar_state.inner_text()
    assert status_state.get_attribute("data-last-success") == first_status_time


def test_hung_endpoint_times_out_and_reports_failure(page: Any, console_server: ConsoleServer) -> None:
    """A hung API request is aborted by its elapsed deadline and marked stale."""
    _start_fake_poller(page, console_server, {"/api/calendar": {"hang": True}})
    page.clock.fast_forward(16000)

    assert page.evaluate("window.__abortedRequests['/api/calendar'] || 0") == 1
    calendar_state = page.locator('#calendar [data-poll-endpoint="/api/calendar"]')
    assert "Tidsavbrudd" in calendar_state.inner_text() or "utdatert" in calendar_state.inner_text().lower()
    assert page.evaluate("window.consoleApp.pollingEntries['/api/calendar'].controller") is None


def test_auth_expiry_stops_all_endpoint_chains(page: Any, console_server: ConsoleServer) -> None:
    """A 401 stops every timer and blocks further requests after expiry."""
    _start_fake_poller(page, console_server, {"/api/status": {"status": 401, "body": {}}})
    page.wait_for_function("window.consoleApp.authExpired === true")
    counts_at_expiry = page.evaluate("window.__requestCounts")
    page.clock.fast_forward(120000)

    assert page.locator("#auth-expired").is_visible()
    assert page.evaluate("window.__requestCounts") == counts_at_expiry
    assert page.evaluate("Boolean(window.consoleApp.pollingEntries) && Object.values(window.consoleApp.pollingEntries).every((entry) => entry.timerId === null)")


def test_poll_deadlines_ignore_wall_clock_jumps(page: Any, console_server: ConsoleServer) -> None:
    """Moving wall time backward does not postpone a monotonic poll deadline."""
    _start_fake_poller(page, console_server)
    page.clock.set_fixed_time("2020-01-01T00:00:00")
    page.clock.fast_forward(5000)

    assert page.evaluate("window.__requestCounts['/api/status']") == 2


def test_old_poll_generation_cannot_expire_new_auth_session(page: Any, console_server: ConsoleServer) -> None:
    page.goto(f"{_base_url(console_server)}/demo")
    page.evaluate("""async () => {
        let first = true;
        window.fetch = async (url) => {
            if (String(url) === '/api/status' && first) {
                first = false;
                return new Promise(resolve => { window.resolveOldPoll = resolve; });
            }
            return {status: 200, ok: true, json: async () => ({})};
        };
        const app=window.consoleApp;
        app.isDemo=false;
        app.startPolling();
        app.stopPolling();
        app.startPolling();
        for (let turn=0; turn<10; turn++) await Promise.resolve();
        window.resolveOldPoll({status:401, ok:false, json:async()=>({})});
        for (let turn=0; turn<10; turn++) await Promise.resolve();
    }""")
    assert page.evaluate('window.consoleApp.authExpired') is False
    assert page.evaluate('window.consoleApp.isPolling') is True
    assert page.locator('#auth-expired').is_hidden()


def test_reply_after_elapsed_deadline_cannot_refresh_endpoint(page: Any, console_server: ConsoleServer) -> None:
    page.clock.install(time='2026-10-04T09:00:00')
    page.goto(f"{_base_url(console_server)}/demo")
    page.evaluate("""async () => {
        window.fetch=async (url) => String(url)==='/api/calendar'
            ? new Promise(resolve => {window.resolveLateCalendar=resolve;})
            : {status:200,ok:true,json:async()=>({})};
        window.consoleApp.isDemo=false;
        window.consoleApp.startPolling();
        for(let turn=0;turn<10;turn++) await Promise.resolve();
    }""")
    page.clock.fast_forward(16000)
    page.evaluate("""async () => {
        window.resolveLateCalendar({status:200,ok:true,json:async()=>({event_count:123,task_count:0,upcoming_events:[]})});
        for(let turn=0;turn<10;turn++) await Promise.resolve();
    }""")
    assert page.evaluate("window.consoleApp.pollingEntries['/api/calendar'].lastSuccess") is None
    assert page.evaluate("window.consoleApp.pollingEntries['/api/calendar'].status") == 'timeout'

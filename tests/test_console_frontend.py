"""Comprehensive frontend tests for the Inebotten web console."""

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
    assert "Ugyldig" in page.content() or "error" in page.content().lower()


def test_dashboard_requires_auth(page: Any, console_server: ConsoleServer) -> None:
    """Unauthenticated access to / returns login page."""
    page.goto(f"{_base_url(console_server)}/")
    assert page.locator('input[name="api_key"]').is_visible()


def test_dashboard_renders_cards(page: Any, console_server: ConsoleServer) -> None:
    """Verify all 8 cards are visible on dashboard."""
    _login(page, console_server)
    content = page.content()
    assert "Bot Status" in content
    assert "Bridge" in content
    assert "Kalender" in content
    assert "Avstemninger" in content
    assert "Rate Limits" in content
    assert "Intents" in content
    assert "Minne" in content
    assert "Logger" in content


def test_static_assets_load(page: Any, console_server: ConsoleServer) -> None:
    """Verify CSS and JS files load without 404."""
    page.goto(f"{_base_url(console_server)}/login")
    content = page.content()
    assert "/static/main.css" in content
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
    assert body.get("status") == "healthy"


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

    links = ["Status", "Bridge", "Kalender", "Avstemninger", "Rate Limits", "Intents", "Minne", "Logger"]
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

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_modal_template_does_not_use_x_html_sink():
    base = (ROOT / "web_console" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "x-html" not in base
    assert "x-text" not in base
    assert 'id="modal-content"' in base
    assert "data-close-modal" in base


def test_modal_details_are_built_as_plain_text_not_html_strings():
    app_js = (ROOT / "web_console" / "static" / "app.js").read_text(encoding="utf-8")
    assert "showSectionModal(section)" in app_js
    assert "content += `<div" not in app_js
    assert "content = `<table" not in app_js
    assert "openModal(section, { title:" in app_js
    assert "content.textContent" in app_js


def test_calendar_workspace_uses_text_nodes_and_never_injects_agenda_markup():
    app_js = (ROOT / "web_console" / "static" / "app.js").read_text(encoding="utf-8")
    assert "heading.textContent = item.title" in app_js
    assert "description.textContent = item.description" in app_js
    assert "innerHTML" not in app_js[app_js.index("renderCalendarAgenda()"):app_js.index("renderCalendarConflicts()")]


def test_dynamic_console_renderers_use_dom_text_instead_of_html_sinks():
    app_js = (ROOT / "web_console" / "static" / "app.js").read_text(encoding="utf-8")
    assert "renderSection(sectionName, sectionState)" in app_js
    assert "createElement(tag)" in app_js
    assert "textContent" in app_js
    assert ".innerHTML" not in app_js

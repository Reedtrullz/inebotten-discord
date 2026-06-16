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
